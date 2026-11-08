"""명세 → RGBA 배열 (도형 렌더러 설계 3절의 차례 그대로).

1 광선 → 2 깊이 · 노멀 · 맞은 도형 → 3 빛 · 램프 · 디더 · rim · highlight → 4 도장 → 5 안쪽 선
→ 6 바깥 외곽선(`draw.outline`) → 7 색 수 상한 → 8 lint(`draw.lint`).
같은 명세 · 같은 view 면 언제나 같은 그림이 나온다 (난수 없음).
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

import numpy as np

from .. import image
from ..draw.lint import lint as run_lint
from ..draw.outline import darker, outline as draw_outline
from ..errors import ArtToolError
from ..palette import RGB, Ramps
from . import lock as lock_mod
from . import pattern as pattern_mod
from . import texture as texture_mod
from .sdf import Prim, scene
from .spec import Material, Spec, Stamp

LIGHT_XY = {"top_left": (-1, -1), "top": (0, -1), "top_right": (1, -1)}   # 빛이 오는 쪽 (그림 좌표)

MAX_STEPS = 200
HIT_EPS = 0.004
STEP_SCALE = 0.9      # 타원체 거리는 근사라 걸음을 조금 줄인다
NORMAL_EPS = 0.01
BAYER4 = (np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]], dtype=float) + 0.5) / 16.0


@dataclass
class Hits:
   """픽셀마다 광선이 맞은 결과. 안 맞은 칸은 hit False."""

   hit: np.ndarray        # (H, W) bool
   depth: np.ndarray      # (H, W) 화면 z (클수록 보는 사람 쪽)
   normal: np.ndarray     # (H, W, 3) 화면 좌표 노멀
   owner: np.ndarray      # (H, W) 맞은 도형 번호, 없으면 -1
   point: np.ndarray | None = None   # (H, W, 3) 맞은 표면 점의 모델 좌표 (재질 무늬가 쓴다)


def view_rotation(yaw_deg: float) -> np.ndarray:
   """물체를 y 축으로 yaw 도 돌리는 행렬. 화면 점 = R · 모델 점."""
   a = math.radians(yaw_deg)
   c, s = math.cos(a), math.sin(a)
   return np.array([[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]])


def march(prims: list[Prim], origins: np.ndarray, direction: np.ndarray, far: float) -> tuple[np.ndarray, np.ndarray]:
   """광선 따라가기 (모델 좌표). 돌려주는 것 : (맞았나 (N,), 나아간 거리 (N,))."""
   n = len(origins)
   t = np.zeros(n)
   hit = np.zeros(n, dtype=bool)
   alive = np.ones(n, dtype=bool)
   for _ in range(MAX_STEPS):
      idx = np.nonzero(alive)[0]
      if len(idx) == 0:
         break
      d, _ = scene(prims, origins[idx] + np.outer(t[idx], direction))
      got = d < HIT_EPS
      hit[idx[got]] = True
      t[idx] += np.where(got, 0.0, np.maximum(d * STEP_SCALE, HIT_EPS * 0.5))
      alive[idx[got]] = False
      alive &= t < far
   return hit, t


def normals(prims: list[Prim], points: np.ndarray) -> np.ndarray:
   """가운데 차분 노멀 (모델 좌표, 단위 벡터)."""
   out = np.zeros_like(points)
   for axis in range(3):
      step = np.zeros(3)
      step[axis] = NORMAL_EPS
      out[:, axis] = scene(prims, points + step)[0] - scene(prims, points - step)[0]
   length = np.linalg.norm(out, axis=1, keepdims=True)
   return out / np.where(length > 0, length, 1.0)


def _pixel_grid(spec: Spec) -> tuple[np.ndarray, np.ndarray]:
   """픽셀 중심의 화면 x · y (모델 단위). (H, W) 둘."""
   w, h = spec.size
   ox, oy = spec.origin
   xs = np.arange(w) + 0.5 - ox
   ys = oy - (np.arange(h) + 0.5)
   return np.meshgrid(xs, ys)


def trace(spec: Spec, yaw: float, prims: list[Prim] | None = None) -> Hits:
   """픽셀 중심마다 정사영 광선을 쏴 깊이 · 노멀 · 맞은 도형을 얻는다. prims 를 주면 그 도형들만 놓고 쏜다."""
   prims = spec.prims if prims is None else prims
   w, h = spec.size
   rot = view_rotation(yaw)
   gx, gy = _pixel_grid(spec)
   far = 2.0 * (max(w, h) + float(np.abs(spec.origin).max()))
   start = np.stack([gx.ravel(), gy.ravel(), np.full(gx.size, far / 2)], axis=1)
   # 화면 → 모델 : p_model = Rᵀ p_screen. 행 벡터라 p @ R.
   origins = start @ rot
   direction = np.array([0.0, 0.0, -1.0]) @ rot
   hit, t = march(prims, origins, direction, far)
   depth = np.full(gx.size, -np.inf)
   normal = np.zeros((gx.size, 3))
   owner = np.full(gx.size, -1, dtype=np.int64)
   point = np.zeros((gx.size, 3))
   if hit.any():
      points = origins[hit] + np.outer(t[hit], direction)
      point[hit] = points
      depth[hit] = far / 2 - t[hit]
      normal[hit] = normals(prims, points) @ rot.T
      owner[hit] = scene(prims, points)[1]
   return Hits(hit.reshape(h, w), depth.reshape(h, w), normal.reshape(h, w, 3), owner.reshape(h, w), point.reshape(h, w, 3))


def _shift_mask(mask: np.ndarray, dx: int, dy: int) -> np.ndarray:
   """out[y, x] = mask[y + dy, x + dx]. 캔버스 밖은 False."""
   h, w = mask.shape
   out = np.zeros_like(mask)
   ys, xs = slice(max(-dy, 0), h + min(-dy, 0)), slice(max(-dx, 0), w + min(-dx, 0))
   out[ys, xs] = mask[max(dy, 0):h + min(dy, 0), max(dx, 0):w + min(dx, 0)]
   return out


def shade_pixels(spec: Spec, hits: Hits, yaw: float = 0.0) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
   """빛 → 램프 칸. 돌려주는 것 : (RGBA 배열, 칸마다 재질 이름 번호 (H, W) 없으면 -1, 칸마다 램프 단 (H, W) 없으면 -1)."""
   w, h = spec.size
   arr = image.new(w, h)
   names = list(spec.materials)
   mat_idx = np.full((h, w), -1, dtype=np.int64)
   levels = np.full((h, w), -1, dtype=np.int64)
   light = spec.light
   half = light + np.array([0.0, 0.0, 1.0])
   half /= np.linalg.norm(half)
   bayer = np.tile(BAYER4, (h // 4 + 1, w // 4 + 1))[:h, :w]
   for i, prim in enumerate(spec.prims):
      sel = hits.hit & (hits.owner == i)
      if not sel.any():
         continue
      mat = spec.materials[prim.material]
      mat_idx[sel] = names.index(prim.material)
      n = hits.normal[sel]
      ndl = np.maximum(0.0, n @ light)
      t = mat.ambient + (1.0 - mat.ambient) * ndl
      steps = len(mat.ramp)
      level = np.floor(t * steps + spec.dither * (bayer[sel] - 0.5))
      level = np.clip(level, 0, steps - 1).astype(int)
      if mat.level is not None:
         level = np.full_like(level, mat.level)
      if mat.rim_below is not None:
         # rim 은 둘레를 그 칸 「까지만」 밝게 한다 — 그늘 쪽 둘레는 더 어두운 칸을 그대로 둔다.
         level = np.where(n[:, 2] < mat.rim_below, np.minimum(level, mat.rim_index), level)
      if mat.bands:
         # 띠 그늘 : 이 도형 실루엣을 (dx, dy) 만큼 옮겨 봤을 때 밖으로 나가는 칸은 그 단까지 낮춘다 (2D 도트 명암 규칙).
         cover = trace(spec, yaw, [prim]).hit
         for (dx, dy), cap, mode in mat.bands:
            outside = ~_shift_mask(cover, dx, dy)[sel]
            level = np.where(outside, np.minimum(level, cap) if mode == "min" else cap, level)
      levels[sel] = level
      ramp = np.array(mat.ramp, dtype=np.uint8)
      rgb = ramp[level]
      if mat.highlight is not None:
         spec_term = n @ half
         rgb = np.where((spec_term > mat.highlight_above)[:, None], np.array(mat.highlight, dtype=np.uint8), rgb)
      arr[sel, :3] = rgb
      arr[sel, 3] = 255
   return arr, mat_idx, levels


def _stamp_anchor(spec: Spec, stamp: Stamp, at: tuple[float, float]) -> tuple[np.ndarray, np.ndarray]:
   """도장이 붙을 표면 점과 그 노멀 (모델 좌표). 그 재질 도형만 놓고 앞쪽에서 광선을 쏜다."""
   prims = [p for p in spec.prims if p.material == stamp.on]
   a = math.radians(stamp.yaw)
   facing = np.array([math.sin(a), 0.0, math.cos(a)])
   side = np.array([math.cos(a), 0.0, -math.sin(a)])
   far = 4.0 * max(spec.size)
   start = at[0] * side + np.array([0.0, at[1], 0.0]) + facing * far / 2
   hit, t = march(prims, start[None, :], -facing, far)
   if not hit[0]:
      raise ArtToolError(f"도장 at {list(at)} 이 재질 {stamp.on} 표면에 안 닿는다")
   point = start + t[0] * -facing
   return point, normals(prims, point[None, :])[0]


def place_stamps(spec: Spec, arr: np.ndarray, hits: Hits, mat_idx: np.ndarray, yaw: float) -> int:
   """카드 도장을 찍는다. `copies` 가 있으면 그 자리마다 한 번씩. 찍은 칸 수를 돌려준다."""
   rot = view_rotation(yaw)
   names = list(spec.materials)
   h, w = arr.shape[:2]
   painted = 0
   for stamp in spec.stamps:
      jit = stamp.jitter
      for ci, (cx, cy) in enumerate(stamp.copies):
         cut: set = set()
         fat: set = set()
         if jit is not None:
            # 반복 흔들림 : 복사본마다 위아래로 ±shift 칸, 가로 토막(seg 칸)마다 끊김 · 한 칸 두께를 해시로 고른다
            k = np.array([[ci, 0]], dtype=np.int64)
            cy = cy + int(round((pattern_mod.hash01(k, jit["seed"])[0] * 2 - 1) * jit["shift"]))
            off = int(pattern_mod.hash01(np.array([[ci, 1]], dtype=np.int64), jit["seed"])[0] * jit["seg"])   # 토막 경계도 복사본마다 다르게
            nseg = -(-(stamp.size[0] + off) // jit["seg"])
            segs = np.stack([np.full(nseg, ci), np.arange(nseg)], axis=1).astype(np.int64)
            r_gap = pattern_mod.hash01(segs, jit["seed"] + 1)
            r_fat = pattern_mod.hash01(segs, jit["seed"] + 2)
            cut = {i for i in range(nseg) if r_gap[i] < jit["gap"]}
            fat = {i for i in range(nseg) if r_fat[i] < jit["thick"]}
         # 옮김은 그림 칸(아래 +) 이라 모델 y 는 거꾸로 간다.
         point, normal = _stamp_anchor(spec, stamp, (stamp.at[0] + cx, stamp.at[1] - cy))
         p = rot @ point
         n = rot @ normal
         if n[2] < stamp.hide_below:
            continue
         sx = spec.origin[0] + p[0]
         sy = spec.origin[1] - p[1]
         gw, gh = stamp.size
         x0 = math.floor(sx - gw / 2 + 0.5)
         y0 = math.floor(sy - gh / 2 + 0.5)
         on = names.index(stamp.on)
         for j, row in enumerate(stamp.grid):
            for i, ch in enumerate(row):
               if ch == ".":
                  continue
               if jit is not None and (i + off) // jit["seg"] in cut:
                  continue
               spots = [(x0 + i, y0 + j)]
               if jit is not None and (i + off) // jit["seg"] in fat and j == len(stamp.grid) - 1:
                  spots.append((x0 + i, y0 + j + 1))
               for x, y in spots:
                  if not (0 <= x < w and 0 <= y < h) or mat_idx[y, x] != on:
                     continue
                  if hits.depth[y, x] > p[2] + stamp.depth_tol:   # 앞에 무엇이 가렸다
                     continue
                  arr[y, x] = (*stamp.legend[ch], 255)
                  painted += 1
   return painted


def palette_ramps(spec: Spec, more: list[RGB] | None = None) -> Ramps:
   """명세에 나오는 색을 모두 램프 묶음 하나로. 외곽선 selout 이 팔레트 안에 머물고 lint 가 팔레트 밖 색을 짚게.

   more : 질감이 새로 만든 색 — 한 색 램프로 덧붙인다.
   """
   ramps: dict[str, list[RGB]] = {name: list(m.ramp) for name, m in spec.materials.items()}
   extra: list[RGB] = []
   for m in spec.materials.values():
      if m.highlight is not None:
         extra.append(m.highlight)
      extra.extend(p.color for p in m.patterns if p.color is not None)
      for p in m.patterns:
         extra.extend(p.colors)
      for c in (m.line, m.line_light):
         if c is not None:
            extra.append(c)
   for s in spec.stamps:
      extra.extend(s.legend.values())
   extra.extend(more or [])
   for i, color in enumerate(dict.fromkeys(extra)):
      ramps[f"_extra{i}"] = [color]
   length = max(len(c) for c in ramps.values())
   return Ramps("shape", ramps, spec.outline_color, length, mode="max")


def _is_light_side(dx: int, dy: int, light_word: str) -> bool:
   """(dx, dy) = 칠한 칸에서 선 칸 쪽 (그림 좌표, 아래 +). 빛이 오는 쪽을 보면 True."""
   lx, ly = LIGHT_XY[light_word]
   return (dx != 0 and dx == lx) or (dy != 0 and dy == ly)


def _line_color(mat: Material, dx: int, dy: int, light_word: str) -> RGB:
   return mat.line_light if _is_light_side(dx, dy, light_word) else mat.line


def inner_lines(arr: np.ndarray, hits: Hits, gap: float, ramps: Ramps, spec: Spec | None = None,
                mat_idx: np.ndarray | None = None) -> int:
   """뒤 칸보다 gap 넘게 앞에 있는 칸(앞 물체 테두리)을 한 단 어둡게. 바꾼 칸 수.

   그 칸 재질에 `line` 이 있으면 한 단 어둡게 대신 그 선 색을 칠한다 (뒤 칸이 빛 쪽이면 `line.light`).
   """
   h, w = hits.hit.shape
   front = np.zeros((h, w), dtype=bool)
   toward = np.zeros((h, w, 2), dtype=np.int64)      # 처음 걸린 뒤 칸 쪽 (dx, dy)
   depth = hits.depth
   for dx, dy in ((-1, 0), (0, -1), (1, 0), (0, 1)):
      nb_hit = np.zeros((h, w), dtype=bool)
      nb_depth = np.full((h, w), -np.inf)
      ys = slice(max(dy, 0), h + min(dy, 0))
      xs = slice(max(dx, 0), w + min(dx, 0))
      sy = slice(max(-dy, 0), h + min(-dy, 0))
      sx = slice(max(-dx, 0), w + min(-dx, 0))
      nb_hit[sy, sx] = hits.hit[ys, xs]
      nb_depth[sy, sx] = depth[ys, xs]
      gap_ok = np.where(hits.hit & nb_hit, depth - np.where(nb_hit, nb_depth, 0.0), -np.inf) > gap
      fresh = gap_ok & ~front
      toward[fresh] = (dx, dy)
      front |= gap_ok
   width = spec.inner_width if spec is not None else 1
   for _ in range(width - 1):
      # 두꺼운 선 : 선 칸과 같은 면(깊이 차 gap 이하)에 붙은 칸으로 한 칸씩 안쪽으로 번진다.
      grow = np.zeros((h, w), dtype=bool)
      for dx, dy in ((-1, 0), (0, -1), (1, 0), (0, 1)):
         ys = slice(max(dy, 0), h + min(dy, 0))
         xs = slice(max(dx, 0), w + min(dx, 0))
         sy = slice(max(-dy, 0), h + min(-dy, 0))
         sx = slice(max(-dx, 0), w + min(-dx, 0))
         nb_front = np.zeros((h, w), dtype=bool)
         nb_depth = np.full((h, w), -np.inf)
         nb_front[sy, sx] = front[ys, xs]
         nb_depth[sy, sx] = depth[ys, xs]
         with np.errstate(invalid="ignore"):
            same = np.abs(depth - nb_depth) <= gap
         add = hits.hit & ~front & ~grow & nb_front & same
         nb_toward = np.zeros((h, w, 2), dtype=np.int64)
         nb_toward[sy, sx] = toward[ys, xs]
         toward[add] = nb_toward[add]
         grow |= add
      front |= grow
   names = list(spec.materials) if spec is not None else []
   cache: dict[RGB, RGB] = {}
   by_mat = spec is not None and mat_idx is not None and spec.inner_color == "material"
   for y, x in zip(*np.nonzero(front)):
      if by_mat and mat_idx[y, x] >= 0:
         # 재질별 어두운 색 : 램프 맨 아래 칸을 같은 색조로 더 어둡게 (뒤 칸이 빛 쪽이면 맨 아래 칸 그대로)
         mat = spec.materials[names[mat_idx[y, x]]]
         lit = _is_light_side(int(toward[y, x, 0]), int(toward[y, x, 1]), spec.light_word)
         arr[y, x, :3] = mat.ramp[0] if lit else material_dark(mat.ramp[0])
         continue
      if spec is not None and mat_idx is not None and mat_idx[y, x] >= 0:
         mat = spec.materials[names[mat_idx[y, x]]]
         if mat.line is not None:
            arr[y, x, :3] = _line_color(mat, int(toward[y, x, 0]), int(toward[y, x, 1]), spec.light_word)
            continue
      rgb = tuple(int(c) for c in arr[y, x, :3])
      if rgb not in cache:
         cache[rgb] = darker(rgb, 1, ramps)
      arr[y, x, :3] = cache[rgb]
   return int(front.sum())


INNER_DARK = 0.62     # inner_color material : 맨 아래 칸 밝기(HSV v) 배율
INNER_HUE = 6.0       # 그때 파랑 쪽으로 돌릴 색조(도)


def material_dark(c: RGB) -> RGB:
   """재질 램프 맨 아래 칸 → 같은 색조로 더 어두운 선 색 (어두울수록 차갑게 — 파랑 쪽 6°)."""
   h, s, v = texture_mod._hsv(c)
   if s > 0.05:
      h = texture_mod._turn(h, 240.0, INNER_HUE)
   return texture_mod._rgb(h, min(1.0, s * 1.1), v * INNER_DARK)


def material_lines(spec: Spec, arr: np.ndarray, before: np.ndarray, mat_idx: np.ndarray, hits: Hits) -> int:
   """바깥 외곽선 칸 가운데 맞닿은 칠한 칸(가장 앞 칸)의 재질에 `line` 이 있으면 그 색으로 다시 칠한다. 바꾼 칸 수."""
   names = list(spec.materials)
   h, w = before.shape
   ring = (arr[:, :, 3] > 0) & ~before
   changed = 0
   for y, x in zip(*np.nonzero(ring)):
      best, pick = -np.inf, None
      for dx, dy in ((-1, 0), (0, -1), (1, 0), (0, 1)):
         nx, ny = x - dx, y - dy        # 칠한 칸 → 선 칸 쪽이 (dx, dy)
         if 0 <= nx < w and 0 <= ny < h and before[ny, nx] and mat_idx[ny, nx] >= 0 and hits.depth[ny, nx] > best:
            best, pick = hits.depth[ny, nx], (dx, dy, mat_idx[ny, nx])
      if pick is None:
         continue
      mat = spec.materials[names[pick[2]]]
      if mat.line is None:
         continue
      arr[y, x, :3] = _line_color(mat, pick[0], pick[1], spec.light_word)
      changed += 1
   return changed


def cap_colors(arr: np.ndarray, limit: int) -> int:
   """색 수가 limit 를 넘으면 가장 적게 쓴 색을 가장 가까운 남은 색으로 합친다. 합친 색 수."""
   merged = 0
   while True:
      solid = arr[:, :, 3] > 0
      colors, counts = np.unique(arr[solid][:, :3], axis=0, return_counts=True)
      if len(colors) <= limit:
         return merged
      order = np.lexsort((colors[:, 2], colors[:, 1], colors[:, 0], counts))   # 적게 쓴 것 → 같으면 색값 순
      drop = colors[order[0]].astype(int)
      rest = np.delete(colors, order[0], axis=0).astype(int)
      target = rest[int(np.argmin(np.sum((rest - drop) ** 2, axis=1)))]
      match = solid & np.all(arr[:, :, :3] == drop, axis=2)
      arr[match, :3] = target
      merged += 1


def render(spec: Spec, view: str = "front") -> tuple[np.ndarray, dict]:
   """명세 하나 · 보는 방향 하나 → (RGBA 배열, 보고 사전)."""
   if view not in spec.views:
      raise ArtToolError(f"없는 보는 방향 : {view} (있는 것 : {' · '.join(spec.views)})")
   started = time.perf_counter()
   yaw = spec.views[view]
   return finish(spec, trace(spec, yaw), yaw, view, started)


def finish(spec: Spec, hits: Hits, yaw: float, view: str, started: float | None = None) -> tuple[np.ndarray, dict]:
   """render 뒷단 : 맞은 결과(Hits) → 칠 · 무늬 · 질감 · 선 · 도장 · 잠금 · 색 수 → (RGBA 배열, 보고 사전).

   납작화(`flatten`)는 진짜 그림에서 흉내 낸 가짜 Hits 를 넣어 같은 뒷단을 돌린다.
   started : 보고 ms 를 잴 시작 시각 (render 가 trace 시간까지 넣으려고 준다).
   """
   started = time.perf_counter() if started is None else started
   ramps = palette_ramps(spec)
   arr, mat_idx, levels = shade_pixels(spec, hits, yaw)
   patterned = pattern_mod.apply(spec, arr, hits, mat_idx, levels)
   textured = 0
   if spec.texture:
      textured, tex_colors = texture_mod.apply(spec, arr, hits, mat_idx, levels)
      ramps = palette_ramps(spec, tex_colors)
   inner = inner_lines(arr, hits, spec.inner_gap, ramps, spec, mat_idx) if spec.inner_gap is not None else 0
   stamped = place_stamps(spec, arr, hits, mat_idx, yaw)
   lined = 0
   if spec.outline_mode != "none":
      before = arr[:, :, 3] > 0
      arr = draw_outline(arr, spec.outline_mode, ramps=ramps, light=spec.light_word, color=spec.outline_color,
                         width=spec.outline_width)
      lined = material_lines(spec, arr, before, mat_idx, hits)
   locked = 0
   if spec.palette_lock is not None:
      # 바깥 외곽선 칸(재질 없음)은 따로 한 무리로 짝짓는다
      groups = np.where(mat_idx >= 0, mat_idx, -1)
      locked = lock_mod.apply(spec.palette_lock, arr, groups)
      ramps = Ramps("lock", {"lock": list(spec.palette_lock.colors)}, spec.outline_color,
                    len(spec.palette_lock.colors), mode="max")
   merged = cap_colors(arr, spec.max_colors) if spec.max_colors else 0
   ms = (time.perf_counter() - started) * 1000.0
   result = run_lint(arr, ramps=ramps, light=spec.light_word,
                     outline_mode=None if spec.outline_mode == "none" else spec.outline_mode,
                     outline_color=spec.outline_color)
   solid = arr[:, :, 3] > 0
   report = {
      "view": view,
      "yaw": yaw,
      "size": list(spec.size),
      "colors": int(len(np.unique(arr[solid][:, :3], axis=0))) if solid.any() else 0,
      "opaque": int(solid.sum()),
      "stamped": stamped,
      "inner_line": inner,
      "material_line": lined,
      "patterned": patterned,
      "merged_colors": merged,
      **({"textured": textured} if spec.texture else {}),
      **({"locked": locked} if spec.palette_lock is not None else {}),
      **({"lock_kept": spec.palette_lock.kept} if spec.palette_lock is not None and spec.palette_lock.family else {}),
      "ms": round(ms, 1),
      "lint": {"status": result.status, "counts": result.counts},
   }
   return arr, report
