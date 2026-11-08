"""재질 무늬 — 렌더 뒤 재질 칸 위에 규칙으로 얹는 무늬 (2026-11-08 게임 그림 실측에서 더함).

| kind | 하는 일 | 칸 |
| --- | --- | --- |
| `speckle` | 점 뿌리기 (깨 · 얼룩). 표면 점마다 해시 값이 `density` 보다 작으면 그 칸에 `dot` 격자를 찍는다 | `density` · `seed` · `dot` · `cell` |
| `stripes` | 줄 (나무결 · 판자 이음매 · 차양 줄무늬). 모델 좌표 `axis` 값이 `period` 마다 `width` 칸. `fan` [cx, cy, ref_y] 를 주면 줄이 점 (cx, cy) 로 모이는 부채꼴이 된다(ref_y 줄에서 period 를 잰다) | `axis` · `period` · `phase` · `width` · `wobble` · `seed` · `fan` |
| `rows` | 정해 둔 **그림 줄**(y, 아래 +)에 가로줄. 앞에서 본 그림 기준이다 (지붕 판자 사이 그늘 줄) | `rows` · `width` |
| `strokes` | 잎 붓질 — 시작점을 해시로 뿌리고 짧은 선분을 위로 뻗는다. 칸 색은 선분 위 높이(위 밝음 · 아래 어둠) 램프 단 | `density` · `seed` · `length` · `lean` · `cell` · `colors` · `jitter` |

색은 `color`(한 색으로 칠함) 또는 `darken`(그 칸의 램프 단을 n 단 내림) 둘 중 하나다.
무늬는 맞은 표면 점의 **모델 좌표**로 정하므로 물체를 돌려도 무늬가 물체에 붙어 따라간다. 난수 대신 정수 해시라
같은 명세면 언제나 같은 무늬가 나온다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..palette import RGB

KINDS = ("speckle", "stripes", "rows", "strokes")
AXES = {"x": 0, "y": 1, "z": 2}


@dataclass
class Pattern:
   kind: str
   color: RGB | None = None
   darken: int = 0
   # speckle
   density: float = 0.05
   seed: int = 0
   dot: list[str] = field(default_factory=lambda: ["#"])
   cell: float = 1.0
   # stripes
   axis: str = "y"
   period: float = 4.0
   phase: float = 0.0
   width: float = 1.0
   wobble: float = 0.0
   fan: tuple[float, float, float] | None = None
   # rows
   rows: list[int] = field(default_factory=list)
   # strokes
   length: int = 3
   lean: float = 0.0
   colors: list[RGB] = field(default_factory=list)   # 붓질 전용 램프(어두운 → 밝은). 없으면 재질 램프
   jitter: float = 1.0                                # 높이 → 단 에 섞는 해시 흔들림 폭 (단 단위)


def hash01(keys: np.ndarray, seed: int) -> np.ndarray:
   """정수 좌표 (N, k) → [0, 1) 값 (N,). splitmix64 섞기. 같은 입력이면 늘 같은 값."""
   mask = np.uint64(0xFFFFFFFFFFFFFFFF)
   h = np.full(len(keys), np.uint64(seed * 0x9E3779B97F4A7C15 & 0xFFFFFFFFFFFFFFFF), dtype=np.uint64)
   with np.errstate(over="ignore"):
      for i in range(keys.shape[1]):
         h ^= keys[:, i].astype(np.int64).astype(np.uint64) + np.uint64(0x9E3779B97F4A7C15) + (h << np.uint64(6)) + (h >> np.uint64(2))
         z = h
         z = (z ^ (z >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9) & mask
         z = (z ^ (z >> np.uint64(27))) * np.uint64(0x94D049BB133111EB) & mask
         h = z ^ (z >> np.uint64(31))
   return (h >> np.uint64(11)).astype(np.float64) / float(1 << 53)


def _paint(arr, levels, ramp, ys, xs, pat: Pattern) -> None:
   if pat.color is not None:
      arr[ys, xs, :3] = pat.color
      return
   lv = np.clip(levels[ys, xs] - pat.darken, 0, len(ramp) - 1)
   arr[ys, xs, :3] = np.array(ramp, dtype=np.uint8)[lv]
   levels[ys, xs] = lv


def apply(spec, arr: np.ndarray, hits, mat_idx: np.ndarray, levels: np.ndarray) -> int:
   """모든 재질의 무늬를 얹는다. 바꾼 칸 수."""
   names = list(spec.materials)
   h, w = mat_idx.shape
   changed = 0
   for m_i, name in enumerate(names):
      mat = spec.materials[name]
      if not mat.patterns:
         continue
      own = mat_idx == m_i
      if not own.any():
         continue
      ys, xs = np.nonzero(own)
      pts = hits.point[ys, xs]
      for pat in mat.patterns:
         if pat.kind == "rows":
            row = np.floor(spec.origin[1] - pts[:, 1]).astype(np.int64)      # 앞에서 본 그림 줄
            on = np.zeros(len(row), dtype=bool)
            for r0 in pat.rows:
               on |= (row >= r0) & (row < r0 + pat.width)
            if on.any():
               _paint(arr, levels, mat.ramp, ys[on], xs[on], pat)
               changed += int(on.sum())
            continue
         if pat.kind == "strokes":
            changed += _strokes(arr, levels, mat.ramp, own, ys, xs, pat)
            continue
         if pat.kind == "stripes":
            ax = AXES[pat.axis]
            coord = pts[:, ax]
            if pat.fan is not None:
               # 부채꼴 : 점을 (cx, cy) 에서 ref_y 줄까지 곧게 이어 그 줄 위 자리로 잰다.
               cx, cy, ref = pat.fan
               dy = pts[:, 1] - cy
               coord = cx + (pts[:, 0] - cx) * (ref - cy) / np.where(np.abs(dy) > 1e-6, dy, 1e-6)
            if pat.wobble > 0:
               other = 0 if ax != 0 else 1
               lane = np.floor(pts[:, other] / max(pat.period, 1.0)).astype(np.int64)
               coord = coord + pat.wobble * (hash01(np.stack([lane, np.floor(coord / pat.period).astype(np.int64)], 1), pat.seed) - 0.5) * 2
            on = np.mod(np.floor(coord) - pat.phase, pat.period) < pat.width
            if on.any():
               _paint(arr, levels, mat.ramp, ys[on], xs[on], pat)
               changed += int(on.sum())
         else:   # speckle
            keys = np.floor(pts / pat.cell).astype(np.int64)
            seeds = hash01(keys, pat.seed) < pat.density
            dot = [(j, i) for j, row in enumerate(pat.dot) for i, ch in enumerate(row) if ch != "."]
            for y0, x0 in zip(ys[seeds], xs[seeds]):
               for j, i in dot:
                  y, x = y0 + j, x0 + i
                  if 0 <= y < h and 0 <= x < w and own[y, x]:
                     _paint(arr, levels, mat.ramp, np.array([y]), np.array([x]), pat)
                     changed += 1
   return changed


def _strokes(arr, levels, ramp, own, ys, xs, pat: Pattern) -> int:
   """잎 붓질. 재질 칸마다 해시로 붓 시작점을 고르고(`density`), 위로 `length` 칸 뻗는 선을 긋는다(`lean` 칸씩 옆으로 기욺).

   선 칸 색 = 그 재질 램프에서 「붓 시작점이 덩어리 위에서 얼마나 내려왔나」에 맞춘 단에서 `darken` 단 뺀 값 —
   아래쪽 붓질은 어둡게, 위쪽 붓질은 밝게 된다. 결정적이다 (같은 seed · 같은 실루엣이면 같은 그림).
   """
   h, w = own.shape
   top, bottom = ys.min(), ys.max()
   span = max(1, bottom - top)
   keys = np.stack([xs // max(1, int(pat.cell)), ys // max(1, int(pat.cell))], axis=1)
   pick = hash01(keys, pat.seed) < pat.density
   jit = hash01(keys, pat.seed + 1)
   own_ramp = bool(pat.colors)
   if own_ramp:
      ramp = pat.colors
   n = len(ramp)
   changed = 0
   for y0, x0, r in zip(ys[pick], xs[pick], jit[pick]):
      # 높이 → 단 : 위(0) 가 밝은 끝, 아래(1) 가 어두운 끝. 해시로 반 단쯤 흔든다.
      depth = (y0 - top) / span
      lv = int(np.clip(round((1.0 - depth) * (n - 1) + pat.jitter * (r - 0.5)), 0, n - 1))
      lv = max(0, lv - pat.darken)
      for k in range(pat.length):
         y = y0 - k
         x = int(round(x0 + pat.lean * k))
         if 0 <= y < h and 0 <= x < w and own[y, x]:
            arr[y, x, :3] = ramp[lv] if pat.color is None else pat.color
            if not own_ramp:
               levels[y, x] = lv
            changed += 1
   return changed
