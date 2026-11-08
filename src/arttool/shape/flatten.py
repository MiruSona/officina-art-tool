"""납작화 — 진짜 그림 → 렌더러처럼 납작한 짝 (2026-11-08 작은 다듬기 모델 설계 3절).

진짜 그림에서 렌더러의 `Hits`(맞음 · 깊이 · 노멀 · 도형 번호)를 흉내 내고, `render.finish()` 뒷단을 그대로 돌린다.
그래서 「납작함」이 렌더러와 같은 코드에서 나온다 — 램프 몇 단 · 노멀 빛 하나 · 한 색 선 · 잠금 · 색 수 상한.

1 바깥 테(투명과 맞닿은 칸) 떼기 → 2 이웃끼리 색이 가까우면 잇는 4연결 덩어리 (`regions`) → 3 덩어리마다 램프 2~4 단
(바탕색 = 덩어리에서 가장 많은 색, 평평한 면이 받는 단에 둔다)
→ 4 가짜 Hits : 노멀 = 덩어리 가장자리 몇 칸만 둥근 돔 기울기(타일 · 작은 부품은 정면), 깊이 = 덩어리 넓이 차례 → 5 `finish()` → 6 알파는 입력 그대로.

손잡이(램프 단 · ambient · 디더 · 선 · 질감 · 잠금 · 색 수 · 노멀 잡음)는 `seed` 로 섞는다. 같은 seed 면 같은 그림.
bands 는 `trace()` 를 다시 부르므로 쓰지 않는다 (가짜 재질에 bands 가 없다).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .. import image
from ..errors import UsageError
from ..palette import RGB
from ..paths import guard_overwrite, jailed_output
from . import lock as lock_mod
from . import texture as texture_mod
from .render import Hits, finish
from .sdf import Prim
from .spec import LIGHT_WORDS, Material, Spec

L_WEIGHT = 0.5       # 덩어리 잇기 : 밝기 차는 이만큼만 센다 (한 재질 램프는 밝기가 넓게 퍼진다)
COLOR_TOL = 18.0     # 덩어리 잇기 : 맞닿은 두 칸의 Lab 거리(밝기 가중)가 이 안이면 잇는다
HIGHLIGHT_MIX = 0.5  # highlight 손잡이 : 맨 밝은 칸을 흰색 쪽으로 이만큼
CHROMA = 8.0         # 덩어리 잇기 : 이보다 채도가 낮으면 회색 — 색조를 안 따진다
HUE_TOL = 30.0       # 덩어리 잇기 : 채도 있는 두 색의 색조 차가 이보다 크면 다른 덩어리
SPECK = 3            # 이 칸 수 이하 덩어리만 이웃 덩어리로 흡수 (점 · 잡티). 작은 그림은 SPECK_AREA 칸마다 1 — 16칸 타일의 점은 무늬다
SPECK_AREA = 400
DOME_R = 3           # 돔은 덩어리 가장자리 이 칸 수만 둥글다 — 큰 판 안쪽은 평평
TILE_OPAQUE = 0.95   # 불투명 몫이 이 이상이면 타일 — 노멀을 모두 정면으로

KNOBS = {
   "ramp": (2, 4),
   "ambient": (0.3, 0.9),
   "dither": (0.0, 0.25, 0.5),
   "outline": ("solid", "selout", "selout+light", "none"),
   "inner_gap": (1.0, 3.0),
   "texture": tuple(texture_mod.KINDS),
   "strength": (0.25, 0.5),
   "max_colors": (8, 16),
   "blur": (0, 2),
}


def knobs(seed: int) -> dict:
   """seed → 손잡이 한 벌 (설계 3절 표). 질감 없음 60% · 나머지 반반."""
   rng = np.random.default_rng(seed)
   tex = []
   if rng.random() >= 0.6:
      for _ in range(int(rng.integers(1, 3))):
         tex.append({"kind": str(rng.choice(KNOBS["texture"])), "strength": round(float(rng.uniform(*KNOBS["strength"])), 3),
                     "seed": int(rng.integers(0, 2**31 - 1))})
   return {
      "ramp": int(rng.integers(KNOBS["ramp"][0], KNOBS["ramp"][1] + 1)),
      "ambient": round(float(rng.uniform(*KNOBS["ambient"])), 3),
      "dither": float(rng.choice(KNOBS["dither"])),
      "outline": str(rng.choice(KNOBS["outline"])),
      "inner_gap": round(float(rng.uniform(*KNOBS["inner_gap"])), 2) if rng.random() < 0.5 else None,
      "rim": bool(rng.random() < 0.5),
      "highlight": bool(rng.random() < 0.5),
      "texture": tex,
      "lock": bool(rng.random() < 0.5),
      "max_colors": int(rng.integers(KNOBS["max_colors"][0], KNOBS["max_colors"][1] + 1)),
      "blur": int(rng.integers(KNOBS["blur"][0], KNOBS["blur"][1] + 1)),
   }


_DIRS = ((-1, 0), (0, -1), (1, 0), (0, 1))


def _shift(a: np.ndarray, dx: int, dy: int, fill) -> np.ndarray:
   """out[y, x] = a[y + dy, x + dx]. 캔버스 밖은 fill."""
   h, w = a.shape[:2]
   out = np.full_like(a, fill)
   out[max(-dy, 0):h + min(-dy, 0), max(-dx, 0):w + min(-dx, 0)] = a[max(dy, 0):h + min(dy, 0), max(dx, 0):w + min(dx, 0)]
   return out


def _spread(values: np.ndarray, known: np.ndarray, want: np.ndarray) -> np.ndarray:
   """want 안의 모르는 칸을 4방향 이웃의 아는 값으로 한 칸씩 번져 채운다. 끝까지 못 닿는 칸은 그대로."""
   values, known = values.copy(), known.copy()
   while True:
      todo = want & ~known
      if not todo.any():
         return values
      grew = False
      for dx, dy in _DIRS:
         nb_known = _shift(known, dx, dy, False) & todo
         if nb_known.any():
            values[nb_known] = _shift(values, dx, dy, 0)[nb_known]
            known |= nb_known
            todo &= ~nb_known
            grew = True
      if not grew:
         return values


def _components(on: np.ndarray, links: dict) -> np.ndarray:
   """on 칸끼리 이어 붙인 4연결 덩어리 번호 (밖은 -1). links[(dx, dy)] : 그 방향 이웃과 이어지나. 번호는 0 부터."""
   h, w = on.shape
   lab = np.where(on, np.arange(h * w).reshape(h, w), h * w)
   while True:
      # 이어진 이웃의 가장 작은 번호로 모은다 — 바뀌는 칸이 없을 때까지
      new = lab.copy()
      for d, joined in links.items():
         new = np.where(joined, np.minimum(new, _shift(lab, *d, h * w)), new)
      if np.array_equal(new, lab):
         break
      lab = new
   _, out = np.unique(np.where(on, lab, -1), return_inverse=True)
   out = out.reshape(h, w) - (0 if on.all() else 1)
   return np.where(on, out, -1)


def _rim(solid: np.ndarray) -> np.ndarray:
   """투명 칸과 4방향으로 맞닿은 칠한 칸 (외곽선 자리). 캔버스 끝은 안 센다 — 불투명 타일 둘레는 테가 아니다."""
   out = np.zeros_like(solid)
   for dx, dy in _DIRS:
      out |= ~_shift(solid, dx, dy, True)
   return solid & out


def _links(arr: np.ndarray, core: np.ndarray) -> dict:
   """맞닿은 두 칸이 같은 덩어리로 이어지나 (방향마다). 이웃끼리 색이 가까우면 잇는다 — 램프 단처럼 한 걸음씩 변하는
   색은 한 덩어리가 되고, 갈색 판과 노란 눈알처럼 한 번에 크게 뛰는 경계는 끊긴다.

   거리는 밝기 가중 Lab. 채도 있는 두 색의 색조 차가 HUE_TOL 넘거나, 회색과 옅은 색 사이면 거리와 상관없이 끊는다.
   """
   lab = lock_mod.to_lab(arr[:, :, :3].reshape(-1, 3)).reshape(arr.shape[0], arr.shape[1], 3)
   chroma = np.hypot(lab[:, :, 1], lab[:, :, 2])
   hue = np.degrees(np.arctan2(lab[:, :, 2], lab[:, :, 1]))
   scaled = lab * np.array([L_WEIGHT, 1.0, 1.0])
   out = {}
   for dx, dy in _DIRS:
      n_scaled, n_chroma, n_hue = (_shift(v, dx, dy, 0.0) for v in (scaled, chroma, hue))
      d = np.linalg.norm(scaled - n_scaled, axis=2)
      turn = np.abs((hue - n_hue + 180.0) % 360.0 - 180.0)
      hue_cut = (chroma > CHROMA) & (n_chroma > CHROMA) & (turn > HUE_TOL)
      gray_cut = (np.abs(chroma - n_chroma) > CHROMA) & (np.minimum(chroma, n_chroma) < CHROMA)
      out[(dx, dy)] = core & _shift(core, dx, dy, False) & (d < COLOR_TOL) & ~hue_cut & ~gray_cut
   return out


def _regions(arr: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
   """(덩어리 번호 (H, W), 그 덩어리 「제 색」 칸 (H, W) bool — 테 · 흡수한 점을 뺀 칸)."""
   solid = arr[:, :, 3] > 0
   labels = np.full(solid.shape, -1, dtype=np.int64)
   if not solid.any():
      return labels, solid
   core = solid & ~_rim(solid)
   if not core.any():
      core = solid
   comp = _components(core, _links(arr, core))
   # 아주 작은 덩어리(점 · 잡티)만 이웃으로 — 눈알 · 가는 선 같은 부품은 제 덩어리로 남는다
   sizes = np.bincount(comp[comp >= 0])
   speck = min(SPECK, int(solid.sum()) // SPECK_AREA)
   comp[(comp >= 0) & (sizes[np.maximum(comp, 0)] <= speck)] = -1
   own = comp >= 0
   if own.any():
      comp = _spread(comp, own, solid)
      comp[solid & (comp < 0)] = comp.max() + 1   # 이웃 덩어리가 없는 외딴 점들은 한 덩어리로
   else:
      comp, own = np.where(solid, 0, -1), solid.copy()
   _, comp_idx = np.unique(comp[solid], return_inverse=True)   # 빈 번호 없이 다시 매긴다
   labels[solid] = comp_idx.reshape(-1)
   for i in np.unique(labels[solid]):
      if not (own & (labels == i)).any():
         own |= labels == i   # 외딴 점 덩어리 — 제 칸이 없으면 다 제 색으로 본다
   return labels, own


def regions(arr: np.ndarray) -> tuple[np.ndarray, list[list[RGB]]]:
   """그림 → (칸마다 덩어리 번호 (H, W), 빈 칸 -1 · 덩어리마다 색 목록 어두운 → 밝은).

   바깥 테(투명과 맞닿은 칸)와 SPECK 칸 이하 덩어리(점 · 잡티)는 빼고 이웃 덩어리로 채운다.
   색 목록은 그 덩어리 「제 색」 칸만 센다.
   """
   labels, own = _regions(arr)
   colors = []
   luma = image.luma(arr)
   for i in range(int(labels.max()) + 1):
      seen = {}
      for y, x in zip(*np.nonzero(own & (labels == i))):
         seen.setdefault(tuple(int(v) for v in arr[y, x, :3]), luma[y, x])
      colors.append(sorted(seen, key=lambda c: (seen[c], c)))
   return labels, colors


def _luma(c) -> float:
   return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]


def _ramp(pixels: np.ndarray, steps: int, flat: set[int]) -> list[RGB]:
   """덩어리 제 색 칸 (N, 3) → steps 단 램프. 바탕색(가장 많은 색)을 평평한 면이 받는 단(flat)에 모두 두고,
   아래 · 위 단은 그 덩어리의 더 어둡고 · 밝은 제 색에서 고른다. 모자라면 바탕색에서 셈해 만든다 (다른 덩어리 색은 안 낀다)."""
   cols, n = np.unique(pixels, axis=0, return_counts=True)
   base = tuple(int(v) for v in cols[int(n.argmax())])
   lo, hi = min(flat), max(flat)
   own = [tuple(int(v) for v in c) for c in cols]
   darker = sorted((c for c in own if _luma(c) < _luma(base) - 3), key=_luma, reverse=True)   # 바탕에 가까운 것부터
   lighter = sorted((c for c in own if _luma(c) > _luma(base) + 3), key=_luma)
   ramp: list[RGB] = [base] * steps
   prev = base
   for level in range(lo - 1, -1, -1):
      prev = darker.pop(0) if darker else texture_mod._derived(prev, True)
      ramp[level] = prev
   prev = base
   for level in range(hi + 1, steps):
      prev = lighter.pop(0) if lighter else texture_mod._derived(prev, False)
      ramp[level] = prev
   return ramp


def _flat_levels(k: dict, light_z: float) -> set[int]:
   """평평한 면(노멀 0,0,1)이 디더까지 받아 갈 수 있는 램프 단들 (shade_pixels 셈 그대로)."""
   t = k["ambient"] + (1.0 - k["ambient"]) * max(0.0, light_z)
   steps = k["ramp"]
   return {int(np.clip(np.floor(t * steps + k["dither"] * (b - 0.5)), 0, steps - 1)) for b in (1 / 32, 0.5, 31 / 32)}


def _dome(labels: np.ndarray, blur: int, flat: bool = False) -> np.ndarray:
   """덩어리마다 가장자리 → 안쪽 거리장을 돔 높이로. 가장자리 DOME_R 칸만 둥글고 안쪽은 평평하다.

   flat : 불투명 그림(타일) — 높이 0, 노멀은 모두 정면 (큰 판에 대각 그늘이 안 생긴다).
   """
   on = labels >= 0
   height = np.zeros(labels.shape)
   if flat:
      return height
   dist = np.zeros(labels.shape)
   alive = on.copy()
   while alive.any() and dist.max() < DOME_R:
      for dx, dy in _DIRS:
         alive &= _shift(alive, dx, dy, False) & (_shift(labels, dx, dy, -1) == labels)
      dist += alive
   for i in range(int(labels.max()) + 1):
      own = labels == i
      if own.sum() < (2 * DOME_R) ** 2:
         continue   # 작은 부품(눈 · 점)은 평평하게 — 돔이 덩어리 전체를 덮어 바탕색이 사라진다
      r = dist[own].max() + 1.0
      t = (dist[own] + 1.0) / r
      height[own] = r * np.sqrt(1.0 - (1.0 - t) ** 2)
   for _ in range(blur):
      # 노멀 잡음 : 높이장을 한 칸 상자 흐림
      acc = height.copy()
      for dx, dy in _DIRS:
         acc += _shift(height, dx, dy, 0.0)
      height = np.where(on, acc / 5.0, 0.0)
   return height


def fake_hits(labels: np.ndarray, hit: np.ndarray, blur: int = 0, flat: bool = False) -> Hits:
   """덩어리 번호 → 렌더러 Hits 흉내. owner = 덩어리 번호, normal = 돔 기울기, depth = 넓이 차례(넓을수록 뒤, 작은 부품은 맨 뒤)."""
   h, w = labels.shape
   owner = np.where(hit, labels, -1)
   height = _dome(labels, blur, flat)
   gy, gx = np.gradient(height)
   # 화면 노멀은 y 가 위로 + 다 : n ∝ (-∂h/∂x, +∂h/∂y_그림, 1)
   normal = np.stack([-gx, gy, np.ones_like(gx)], axis=2)
   normal /= np.linalg.norm(normal, axis=2, keepdims=True)
   normal[~hit] = 0.0
   n = int(labels.max()) + 1
   areas = np.array([(labels == i).sum() for i in range(n)])
   rank = np.empty(n)
   rank[np.argsort(-areas, kind="stable")] = np.arange(n)
   # 작은 부품은 맨 뒤로 — 안쪽 선이 얇은 부품을 다 덮지 않고 둘레의 큰 덩어리 쪽에 그어진다
   rank[areas < (2 * DOME_R) ** 2] = -1.0
   depth = np.where(hit, rank[np.maximum(labels, 0)], -np.inf)
   ys, xs = np.mgrid[0:h, 0:w]
   point = np.stack([xs, ys, np.where(hit, depth, 0.0)], axis=2).astype(float)
   return Hits(hit, depth, normal, owner, point)


def _spec(arr: np.ndarray, labels: np.ndarray, own: np.ndarray, k: dict, light: str) -> Spec:
   """덩어리마다 재질 하나인 가짜 명세. 도형은 재질 이름만 쓰는 껍데기다."""
   vec = np.array(LIGHT_WORDS[light])
   vec = vec / np.linalg.norm(vec)
   flat = _flat_levels(k, float(vec[2]))
   materials, prims = {}, []
   for i in range(int(labels.max()) + 1):
      ramp = _ramp(arr[own & (labels == i)][:, :3], k["ramp"], flat)
      mat = Material(f"r{i}", ramp, ambient=k["ambient"])
      if k["rim"]:
         mat.rim_below, mat.rim_index = 0.3, max(0, min(flat) - 1)
      if k["highlight"]:
         top = np.array(ramp[-1], dtype=float)
         mat.highlight = tuple(int(round(v)) for v in top + (255.0 - top) * HIGHLIGHT_MIX)
         mat.highlight_above = 0.97   # 돔 노멀은 빛 쪽 비탈이 넓어 .9 면 하이라이트가 판처럼 커진다
      materials[mat.name] = mat
      prims.append(Prim("sphere", {"r": 1.0}, mat.name))
   texture = texture_mod.parse([{"kind": t["kind"], "on": "*", "strength": t["strength"], "seed": t["seed"]}
                                for t in k["texture"]], materials)
   solid = arr[:, :, 3] > 0
   cols = np.unique(arr[solid][:, :3], axis=0)
   palette = [tuple(int(v) for v in c) for c in cols]
   darkest = min(palette, key=lambda c: (_luma(c), c))
   lock = lock_mod.Lock(palette, ramps=[("colors", palette)], family=True) if k["lock"] else None
   h, w = labels.shape
   return Spec((w, h), (w / 2, h / 2), vec, light, k["outline"],
               darkest if k["outline"] == "solid" else None, 1, k["inner_gap"], k["max_colors"], k["dither"],
               {"flat": 0.0}, materials, prims, [], 1, texture, lock)


def flatten(arr: np.ndarray, seed: int, light: str = "top_left") -> tuple[np.ndarray, dict]:
   """진짜 그림 (H, W, 4) → 납작화한 짝 (같은 크기 RGBA, 알파 그대로) · 보고."""
   if light not in LIGHT_WORDS:
      raise UsageError(f"light 는 {' · '.join(LIGHT_WORDS)} 중 하나다 : {light!r}")
   k = knobs(seed)
   solid = arr[:, :, 3] > 0
   if not solid.any():
      return arr.copy(), {"seed": seed, "knobs": k, "regions": 0}
   labels, own = _regions(arr)
   hit = solid
   if k["outline"] != "none":
      # 바깥 테(투명과 맞닿은 칸)를 떼고 칠한다 — finish 가 그 자리에 새 외곽선을 두른다
      peeled = solid & ~_rim(solid)
      hit = peeled if peeled.any() else solid
   tile = solid.mean() >= TILE_OPAQUE
   out, report = finish(_spec(arr, labels, own, k, light), fake_hits(labels, hit, k["blur"], tile), 0.0, "flat")
   # 알파는 입력 그대로 : 밖으로 나간 칸은 지우고, 못 칠한 칸(대각 모서리 · 한 칸 두께)은 이웃 색으로
   painted = out[:, :, 3] > 0
   out[:, :, :3] = _spread(out[:, :, :3], painted & solid, solid)
   out[~solid] = 0
   out[:, :, 3] = arr[:, :, 3]
   return out, {"seed": seed, "knobs": k, "regions": int(labels.max()) + 1, "render": report}


def run(args) -> dict:
   """`arttool shape flatten <in> --out <out> --seed N`. in 이 폴더거나 --out 이 있는 폴더면 묶음 (같은 seed)."""
   src = Path(args.in_path)
   files = sorted(src.glob("*.png")) if src.is_dir() else [src]
   if src.is_dir() and not files:
      raise UsageError(f"PNG 가 없는 폴더다 : {src}")
   folder = src.is_dir() or Path(args.out_file).is_dir()
   if src.is_dir() and Path(args.out_file).is_file():
      raise UsageError(f"--out 은 .png 또는 있는 폴더다 : {args.out_file}")
   if folder:
      outs = [jailed_output(Path(args.out_file) / f.name) for f in files]
   else:
      if Path(args.out_file).suffix.lower() != ".png":
         raise UsageError(f"--out 은 .png 또는 있는 폴더다 : {args.out_file}")
      outs = [jailed_output(args.out_file)]
   guard_overwrite(outs, files, "--out")
   items = []
   for file, out in zip(files, outs):
      flat, report = flatten(image.load(file), args.seed)
      image.save(out, flat)
      items.append({"in": str(file), "out": str(out), "regions": report["regions"], "knobs": report["knobs"]})
   return {"status": "ok", "seed": args.seed, "count": len(items), "items": items}
