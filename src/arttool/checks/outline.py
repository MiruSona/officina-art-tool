"""② outline — 외곽선 방식 (설계 7-2 ②).

가장자리 칸(투명과 맞닿고 안쪽 이웃이 있는 불투명 칸)의 색을 안쪽 색과 견줘
`black` · `solid` · `selout` · `selout+light` · `none` · `mixed` 중 하나로 판정한다.

안쪽 색은 안쪽으로 1 · 2 · 3 칸 들어간 자리 중 **가장 밝은 깊이**를 쓴다.
바로 안쪽 1칸만 보면 2px 두께 외곽선은 가장자리와 안쪽이 같은 색이라 「없음」 으로 나왔다 (실물 시험 버그 5).
"""

from __future__ import annotations

import numpy as np

from . import DIRS4, LOW_SAT, edge_mask, long_side, luma, opaque, raw_edge, shifted

BLACK_MAX = 32          # max(R,G,B) 가 이 이하면 순흑. 실물의 거의 검정 외곽선이 밝기 20~30 이다 (실물 시험 #2)
DEPTHS = (1, 2, 3)      # 안쪽 색을 볼 깊이. 이 중 가장 밝은 것과 견준다
SOLID_SHARE = 0.8       # 가장자리 칸의 이 몫 이상이 한 색이면 「한 색 선」 후보
SOLID_INNER = 0.8       # …단 안쪽 색도 이만큼 한 색이면 selout 과 못 가려 selout 으로 둔다 (한 색 물체)
DARK_FACTOR = 0.85      # 가장자리 밝기 < 안쪽 이웃 평균 × 이 값이면 「어둡다」
SELOUT_BLACK = 0.2      # selout 은 순흑이 이보다 적어야 한다
SELOUT_DARK = 0.6       # selout 은 어두운 가장자리가 이 이상
SELOUT_HUE = 40.0       # selout 은 가장자리 · 안쪽 색조 차 평균이 이 이하 (도)
LIGHT_FACTOR = 1.15     # 빛 쪽 가장자리의 「안쪽 대비 밝기」 평균 ≥ 반대쪽 × 이 값이면 selout+light
NONE_DARK = 0.3         # 어두운 가장자리가 이보다 적으면 외곽선 없음
SMALL_SIZE = 16         # 이 크기 이하에서 외곽선을 두르면 외곽선 몫이 커진다 (정보 한 줄)

# style.light → (빛 쪽에서 투명과 맞닿는 방향들, 반대쪽 방향들). 방향은 (dy, dx).
LIGHT_SIDES = {
   "top_left": (((-1, 0), (0, -1)), ((1, 0), (0, 1))),
   "top": (((-1, 0),), ((1, 0),)),
   "top_right": (((-1, 0), (0, 1)), ((1, 0), (0, -1))),
}


def _side_mask(solid: np.ndarray, dirs) -> np.ndarray:
   """그 방향들 중 하나라도 투명(그림 밖 포함)과 맞닿은 칸."""
   out = np.zeros_like(solid)
   for dy, dx in dirs:
      out |= ~shifted(solid, dy, dx, fill=False)
   return out


def measure_outline(arr: np.ndarray, light: str = "top_left", black_ratio: float = 0.8) -> dict:
   """외곽선 재기. 화풍 뽑기(묶음 7 ②)도 이것을 부른다.

   돌려주는 것 :
   - `edges` · `opaque` : 센 가장자리 칸 수 · 불투명 칸 수
   - `black_ratio` · `dark_ratio` : 순흑 비율 · 어두운 가장자리 비율 (가장자리가 없으면 None)
   - `hue_diff` : 가장자리 · 안쪽 색조 차 평균(도). 채도 낮은 칸만 있으면 None
   - `lit_ratio` : 빛 쪽 가장자리의 「안쪽 이웃 대비 밝기」 평균 ÷ 반대쪽. 어느 한쪽이 없으면 None.
     칸마다 안쪽 이웃과 견준 몫이라 위 · 아래 칠한 색이 달라도(밝은 머리 · 어두운 옷) 빛 방향만 남는다
   - `share` · `expected_share` : 외곽선 몫(가장자리 ÷ 불투명) · 크기 n 의 (4n−4)/n²
   - `size` : 불투명 bbox 긴 변
   - `solid_share` · `inner_share` : 가장자리 · 안쪽 색 중 가장 흔한 한 색의 몫 (가장자리가 없으면 None)
   - `edge_top` · `edge_top_count` : 가장자리 칸에 가장 많이 쓰인 한 색 [r, g, b] 과 그 칸 수 (없으면 None · 0).
     화풍 뽑기가 판정 solid 일 때 외곽선 색으로 쓴다
   - `verdict` : black · solid · selout · selout+light · none · mixed. 가장자리가 없으면 None.
     solid 는 「한 색 선」 — 안쪽 색은 여럿인데 외곽선은 (검정이 아닌) 한 색이다
   """
   solid = opaque(arr)
   edge = edge_mask(arr)
   inner = solid & ~raw_edge(arr)
   size = long_side(arr)
   n_edges, n_opaque = int(edge.sum()), int(solid.sum())
   out = {
      "edges": n_edges,
      "opaque": n_opaque,
      "black_ratio": None,
      "dark_ratio": None,
      "hue_diff": None,
      "lit_ratio": None,
      "share": round(n_edges / n_opaque, 4) if n_opaque else 0.0,
      "expected_share": round((4 * size - 4) / (size * size), 4) if size else 0.0,
      "size": size,
      "solid_share": None,
      "inner_share": None,
      "edge_top": None,
      "edge_top_count": 0,
      "verdict": None,
   }
   if n_edges == 0:
      return out

   rgb = arr[:, :, :3].astype(np.float64)
   ys, xs = np.nonzero(edge)
   edge_rgb = rgb[ys, xs]
   near_rgb, inner_rgb = _inner_color(rgb, solid, inner, ys, xs)

   black = edge_rgb.max(axis=1) <= BLACK_MAX
   dark = luma(edge_rgb) < luma(inner_rgb) * DARK_FACTOR
   out["black_ratio"] = round(float(black.mean()), 4)
   out["dark_ratio"] = round(float(dark.mean()), 4)
   out["solid_share"] = round(_top_share(edge_rgb), 4)
   out["inner_share"] = round(_top_share(np.rint(inner_rgb)), 4)
   out["edge_top"], out["edge_top_count"] = _top_color(edge_rgb)

   eh, es = _hue_sat_many(edge_rgb)
   ih, isat = _hue_sat_many(inner_rgb)
   colored = (es >= LOW_SAT) & (isat >= LOW_SAT)
   if colored.any():
      gap = np.abs(eh[colored] - ih[colored]) % 360.0
      out["hue_diff"] = round(float(np.minimum(gap, 360.0 - gap).mean()), 2)

   lit_dirs, far_dirs = LIGHT_SIDES[light]
   lit = edge & _side_mask(solid, lit_dirs) & ~_side_mask(solid, far_dirs)
   far = edge & _side_mask(solid, far_dirs) & ~_side_mask(solid, lit_dirs)
   if lit.any() and far.any():
      # 가장자리 칸마다 (자기 밝기 + 1) ÷ (안쪽 이웃 밝기 + 1). 1 을 더해 순흑에서도 나눌 수 있게 한다(JSON 에 inf 를 안 쓴다)
      rel = np.zeros(solid.shape)
      # 빛 몫은 바로 안쪽 1칸과 견준다 — 깊이 고르기를 쓰면 안쪽 음영(왼쪽 위가 밝다)이 빛 쪽 몫에 섞인다
      rel[ys, xs] = (luma(edge_rgb) + 1.0) / (luma(near_rgb) + 1.0)
      out["lit_ratio"] = round(float(rel[lit].mean()) / float(rel[far].mean()), 3)

   out["verdict"] = _verdict(out, black_ratio)
   return out


def _inner_color(rgb: np.ndarray, solid: np.ndarray, inner: np.ndarray, ys: np.ndarray, xs: np.ndarray) -> np.ndarray:
   """가장자리 칸마다 견줄 안쪽 색.

   안쪽 방향 = 4방향 중 바로 옆(1칸)이 안쪽 칸인 방향. 깊이 1 · 2 · 3 마다 그 방향들로 d 칸 들어간 불투명 칸의 평균 색을 내고,
   그중 밝기가 가장 높은 깊이의 색을 고른다. 깊이 1 은 늘 있다(edge_mask 가 그렇게 골랐다).
   돌려주는 것 : (깊이 1 색, 가장 밝은 깊이 색)
   """
   h, w = solid.shape
   best = None
   best_luma = None
   first = None
   for depth in DEPTHS:
      total = np.zeros((len(ys), 3))
      count = np.zeros(len(ys))
      for dy, dx in DIRS4:
         ny1, nx1 = ys + dy, xs + dx
         ok1 = (ny1 >= 0) & (ny1 < h) & (nx1 >= 0) & (nx1 < w)
         toward = np.zeros(len(ys), dtype=bool)
         toward[ok1] = inner[ny1[ok1], nx1[ok1]]               # 이 방향이 안쪽인가
         ny, nx = ys + dy * depth, xs + dx * depth
         ok = toward & (ny >= 0) & (ny < h) & (nx >= 0) & (nx < w)
         ok[ok] = solid[ny[ok], nx[ok]]
         total[ok] += rgb[ny[ok], nx[ok]]
         count[ok] += 1
      have = count > 0
      mean = np.zeros_like(total)
      mean[have] = total[have] / count[have][:, None]
      level = np.where(have, luma(mean), -1.0)
      if best is None:
         first = mean.copy()
         best, best_luma = mean, level
         continue
      brighter = level > best_luma
      best[brighter] = mean[brighter]
      best_luma = np.where(brighter, level, best_luma)
   return first, best


def _hue_sat_many(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
   """(N, 3) RGB → (색조 0~360 도, 채도 0~1). `hue_sat` 을 배열로 한 번에 (HSV, colorsys 와 같은 셈)."""
   x = rgb / 255.0
   high = x.max(axis=1)
   low = x.min(axis=1)
   span = high - low
   sat = np.where(high > 0, span / np.where(high > 0, high, 1.0), 0.0)
   safe = np.where(span > 0, span, 1.0)
   r, g, b = x[:, 0], x[:, 1], x[:, 2]
   rc, gc, bc = (high - r) / safe, (high - g) / safe, (high - b) / safe
   hue = np.where(r == high, bc - gc, np.where(g == high, 2.0 + rc - bc, 4.0 + gc - rc))
   hue = np.where(span > 0, (hue / 6.0) % 1.0, 0.0)
   return hue * 360.0, sat


def _top_color(colors: np.ndarray) -> tuple[list[int], int]:
   """가장자리 칸에 가장 많이 쓰인 한 색 [r, g, b] 과 그 칸 수. 같은 수면 열쇠가 작은 색."""
   uniq, counts = np.unique(colors.astype(np.int64), axis=0, return_counts=True)
   top = int(np.argmax(counts))
   return [int(v) for v in uniq[top]], int(counts[top])


def _top_share(colors: np.ndarray) -> float:
   """색 목록에서 가장 흔한 한 색의 몫."""
   _, counts = np.unique(colors.astype(np.int64), axis=0, return_counts=True)
   return float(counts.max()) / len(colors)


def _verdict(m: dict, black_ratio: float) -> str:
   if m["black_ratio"] >= black_ratio:
      return "black"
   one_line = m["solid_share"] is not None and m["solid_share"] >= SOLID_SHARE
   varied_inside = m["inner_share"] is not None and m["inner_share"] < SOLID_INNER
   if one_line and varied_inside and m["dark_ratio"] >= SELOUT_DARK:
      return "solid"
   hue_ok = m["hue_diff"] is None or m["hue_diff"] <= SELOUT_HUE
   if m["black_ratio"] < SELOUT_BLACK and m["dark_ratio"] >= SELOUT_DARK and hue_ok:
      lit = m["lit_ratio"]
      return "selout+light" if lit is not None and lit >= LIGHT_FACTOR else "selout"
   if m["dark_ratio"] < NONE_DARK:
      return "none"
   return "mixed"


def judge_outline(m: dict, style_outline: str, accept=()) -> list[str]:
   """재 둔 값 → 걸린 까닭 목록. `unset` 이거나 가장자리가 없으면 늘 통과.

   accept 는 프로필 `check.warn.outline.accept` — style.outline 말고도 받아 주는 판정들.
   """
   if style_outline == "unset" or m["verdict"] is None:
      return []
   if m["verdict"] == style_outline or m["verdict"] in accept:
      return []
   also = f" (accept {' · '.join(accept)})" if accept else ""
   return [f"외곽선 판정 {m['verdict']} 가 style.outline {style_outline}{also} 과 다르다"]


def small_note(m: dict, style_outline: str) -> str | None:
   """작은 그림(n ≤ 16)에 외곽선을 두르면 외곽선 몫이 크다는 정보 한 줄. 경고는 아니다."""
   if 0 < m["size"] <= SMALL_SIZE and style_outline not in ("none", "unset"):
      return f"{m['size']}px 그림에서 외곽선 몫 {m['share']:.2f} (크기 기준 {m['expected_share']:.2f}) — 작은 그림은 외곽선을 빼는 길도 있다"
   return None
