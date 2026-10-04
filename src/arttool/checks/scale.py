"""① integer_scale — 정수 배율 · 부드러운 확대 (설계 7-2 ①).

- 도트 굵기 : 그림을 덩어리로 나눠 덩어리마다 n×n 격자(어긋남 n² 가지 중 가장 잘 맞는 것)를 깐다.
  **색 경계에 닿는 칸**만 골라, 그 칸이 한 색인 비율을 잰다. ×n 으로 키운 그림은 경계가 칸 테두리에만 오므로 비율이 거의 1 이다.
- 부드러운 확대 : 양옆(또는 위아래) 이웃이 많이 다른데 가운데 칸이 딱 중간색이면 bilinear 흔적이다.
"""

from __future__ import annotations

import numpy as np

from . import norm_rgba, opaque
from .pixels import color_count

SCALES = (4, 3, 2)            # 큰 배율부터 본다. ×4 그림은 ×2 격자에도 맞기 때문이다
MIN_EDGE_CELLS = 16           # 경계 칸이 이보다 적은 덩어리는 판정에서 뺀다 (큰 평면 덩어리)
BACKGROUND_BLOCK = 32         # 배경 그림은 투명으로 안 갈리니 32×32 칸으로 나눈다
SMOOTH_GAP = 32               # 양옆 이웃 색이 이만큼 넘게 달라야 본다 (RGB 각 칸 최댓값)
SMOOTH_TOL = 8                # 가운데 칸이 두 이웃의 중간색에서 각 칸 이만큼 안이면 「중간색」
MIN_CORNERS = 8               # 꺾인 2×2 자리가 이보다 적은 덩어리는 판정에서 뺀다 (직선 줄 · 끝 몇 개뿐인 벽 칸)
CORNER_SHARE = 0.4            # …그리고 (꺾인 자리 ÷ 경계 자리) × n 이 이 이상이어야 ×n 으로 본다 (`_bent_enough`)
SMOOTH_MIN_COLORS = 8        # 색이 이 이하인 그림은 부드러운 확대를 안 본다


def _label(mask: np.ndarray) -> tuple[np.ndarray, list[tuple[int, int, int, int]]]:
   """8방향으로 이어진 참 덩어리에 번호를 붙인다. (번호 판 (-1 = 빈 칸), 덩어리별 (x0, y0, x1, y1)).

   번호는 래스터 순서(위 → 아래, 왼 → 오)로 처음 나온 칸 차례다.
   칸마다 걷지 않고 **줄마다 이어진 토막(run)** 끼리 잇는다 — 1024 칸 그림도 토막 수만큼만 돈다.
   """
   h, w = mask.shape
   labels = np.full((h, w), -1, dtype=np.int64)
   edge = np.diff(np.pad(mask.astype(np.int8), ((0, 0), (1, 1))), axis=1)
   rows, starts = np.nonzero(edge == 1)      # 토막 시작 칸
   _, ends = np.nonzero(edge == -1)          # 토막 끝 (끝 칸 + 1). 둘 다 래스터 순서라 짝이 맞는다
   count = len(rows)
   if count == 0:
      return labels, []
   # 아랫줄 토막 j 가 윗줄 토막 i 와 8방향으로 닿는 조건 : 윗줄 시작 ≤ 아랫줄 끝, 윗줄 끝 ≥ 아랫줄 시작.
   # 줄 · 칸을 한 수(key)로 엮어 전체 토막에서 한 번에 찾는다. 한 줄 안 토막은 정렬돼 있어 닿는 것이 이어진 구간이다.
   wide = w + 2
   start_key = rows * wide + starts
   end_key = rows * wide + ends
   below = np.nonzero(rows > 0)[0]
   up_row = rows[below] - 1
   lo = np.searchsorted(end_key, up_row * wide + starts[below], side="left")
   hi = np.searchsorted(start_key, up_row * wide + ends[below], side="right")
   reach = np.maximum(hi - lo, 0)
   pair_a = np.repeat(below, reach)
   pair_b = np.repeat(lo, reach) + (np.arange(int(reach.sum())) - np.repeat(np.cumsum(reach) - reach, reach))

   parent = list(range(count))

   def root(i: int) -> int:
      while parent[i] != i:
         parent[i] = parent[parent[i]]
         i = parent[i]
      return i

   for a, b in zip(pair_a.tolist(), pair_b.tolist()):
      ra, rb = root(a), root(b)
      if ra != rb:
         parent[max(ra, rb)] = min(ra, rb)   # 작은 번호(먼저 나온 토막)를 뿌리로 — 차례가 래스터 순서로 남는다
   roots = np.array([root(i) for i in range(count)])
   order, comp = np.unique(roots, return_inverse=True)   # 뿌리는 그 덩어리 첫 토막이라 정렬 = 래스터 순서

   lengths = ends - starts
   flat = np.repeat(rows * w + starts - (np.cumsum(lengths) - lengths), lengths) + np.arange(int(lengths.sum()))
   labels.reshape(-1)[flat] = np.repeat(comp, lengths)
   x0 = np.full(len(order), w)
   y0 = np.full(len(order), h)
   x1 = np.zeros(len(order), dtype=np.int64)
   y1 = np.zeros(len(order), dtype=np.int64)
   np.minimum.at(x0, comp, starts)
   np.minimum.at(y0, comp, rows)
   np.maximum.at(x1, comp, ends)
   np.maximum.at(y1, comp, rows + 1)
   boxes = [(int(a), int(b), int(c), int(d)) for a, b, c, d in zip(x0, y0, x1, y1)]
   return labels, boxes


def components(mask: np.ndarray) -> list[tuple[np.ndarray, tuple[int, int, int, int]]]:
   """8방향으로 이어진 참 덩어리들. (덩어리 판, (x0, y0, x1, y1)) 목록. 끝은 포함하지 않는다."""
   labels, boxes = _label(mask)
   return [(labels == k, box) for k, box in enumerate(boxes)]


def _window_sum(table: np.ndarray, y0: int, x0: int, n: int, rows: int, cols: int, span_y: int, span_x: int) -> np.ndarray:
   """누적합 표 → 격자 칸마다 [y, y+span_y) × [x, x+span_x) 합. 칸 왼쪽 위는 (y0 + i·n, x0 + j·n). 첫 축은 묶음."""
   ya = slice(y0, y0 + rows * n, n)
   yb = slice(y0 + span_y, y0 + span_y + rows * n, n)
   xa = slice(x0, x0 + cols * n, n)
   xb = slice(x0 + span_x, x0 + span_x + cols * n, n)
   return table[:, yb, xb] - table[:, ya, xb] - table[:, yb, xa] + table[:, ya, xa]


def _prefix(flags: np.ndarray) -> np.ndarray:
   """(묶음, 높이, 너비) 참거짓 → 앞에 0 줄 · 0 칸을 붙인 2차원 누적합."""
   b, h, w = flags.shape
   out = np.zeros((b, h + 1, w + 1), dtype=np.int64)
   out[:, 1:, 1:] = flags.cumsum(axis=1).cumsum(axis=2)
   return out


def _grid_ratio(regions: np.ndarray, n: int) -> tuple[np.ndarray, np.ndarray]:
   """같은 크기 조각 묶음 (묶음, 높이, 너비, 4) → 조각마다 n×n 격자 어긋남 n² 가지 중 가장 잘 맞는 것의 (한 색 비율, 경계 칸 수).

   칸 하나가 「한 색」인 것은 칸 안 이웃끼리 모두 같은 색인 것과 같다 — 색 다른 이웃 짝 수를 누적합으로 한 번에 센다.
   """
   # 가장자리 칸을 n 칸씩 되풀이해 둘러 어느 어긋남에서도 모든 칸이 격자에 들어가게 한다.
   # 안 두르면 작은 덩어리에서 「몇 칸만 들어가는 어긋남」이 우연히 1.0 을 낸다. 되풀이라 새 경계는 안 생긴다.
   region = np.pad(regions, ((0, 0), (n, n), (n, n), (0, 0)), mode="edge")
   batch, h, w = region.shape[:3]
   horiz = np.any(region[:, :, :-1] != region[:, :, 1:], axis=-1)   # (x, x+1) 색이 다르다
   vert = np.any(region[:, :-1] != region[:, 1:], axis=-1)         # (y, y+1) 색이 다르다
   touch = np.zeros((batch, h, w), dtype=bool)                       # 둘레(4방향)에 색 경계가 있는 칸
   touch[:, :, :-1] |= horiz
   touch[:, :, 1:] |= horiz
   touch[:, :-1] |= vert
   touch[:, 1:] |= vert
   touch_sum, horiz_sum, vert_sum = _prefix(touch), _prefix(horiz), _prefix(vert)

   best = np.zeros(batch)
   best_cells = np.zeros(batch, dtype=np.int64)
   for oy in range(n):
      for ox in range(n):
         rows, cols = (h - oy) // n, (w - ox) // n
         if rows <= 0 or cols <= 0:
            continue
         cand = _window_sum(touch_sum, oy, ox, n, rows, cols, n, n) > 0
         # 칸 안 가로 짝은 n 줄 × (n-1) 짝, 세로 짝은 (n-1) 줄 × n 칸
         same = (_window_sum(horiz_sum, oy, ox, n, rows, cols, n, n - 1) == 0) & (_window_sum(vert_sum, oy, ox, n, rows, cols, n - 1, n) == 0)
         cells = cand.sum(axis=(1, 2))
         hit = (cand & same).sum(axis=(1, 2))
         alive = cells > 0
         ratio = np.where(alive, hit / np.maximum(cells, 1), 0.0)
         better = alive & ((ratio > best) | ((ratio == best) & (cells > best_cells)))
         best = np.where(better, ratio, best)
         best_cells = np.where(better, cells, best_cells)
   return best, best_cells


def _one_color(regions: np.ndarray) -> np.ndarray:
   """조각마다 보이는 칸이 모두 한 색인가 (보이는 칸이 없어도 참)."""
   flat = regions.reshape(len(regions), -1, 4)
   solid = flat[:, :, 3] > 0
   first = flat[np.arange(len(flat)), solid.argmax(axis=1)]
   differ = np.any(flat != first[:, None, :], axis=-1) & solid
   return ~differ.any(axis=1)


def _corners(regions: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
   """조각마다 (색 경계가 「꺾인」 2×2 자리 수, 색 경계가 있는 2×2 자리 수).

   2×2 안에서 가로로도 색이 다르고 세로로도 색이 다르면 꺾인 자리다(모서리 · 계단 · 끊긴 줄 끝).
   가로 · 세로 직선 경계만 있는 조각(벽 줄 · 2px 줄무늬)은 꺾인 자리가 없다 — 줄 굵기가 우연히 2 · 4 칸이면
   ×2 · ×4 로 맞아 버려서 배율을 가릴 근거가 못 된다 (실물 시험 버그 3).
   """
   if regions.shape[1] < 2 or regions.shape[2] < 2:
      zero = np.zeros(len(regions), dtype=np.int64)
      return zero, zero
   horiz = np.any(regions[:, :, :-1] != regions[:, :, 1:], axis=-1)   # (b, h, w-1)
   vert = np.any(regions[:, :-1] != regions[:, 1:], axis=-1)         # (b, h-1, w)
   across = horiz[:, :-1] | horiz[:, 1:]                             # 2×2 의 위 · 아래 줄 중 하나가 가로로 다름
   down = vert[:, :, :-1] | vert[:, :, 1:]                           # 2×2 의 왼 · 오 칸 중 하나가 세로로 다름
   return (across & down).sum(axis=(1, 2)), (across | down).sum(axis=(1, 2))


def _bent_enough(corners: int, boundary: int, n: int) -> bool:
   """×n 판정을 믿을 만큼 꺾인 자리가 있는가.

   ×n 그림은 경계 자리가 n 배로 늘고 꺾인 자리는 그대로라, 「꺾인 몫 × n」 이 배율과 상관없이 비슷하다.
   실측 : 배경 벽 칸 ×2 판정 0.08~0.24, ×2 잡음 · ×2 캐릭터 0.69.
   """
   return corners >= MIN_CORNERS and corners * n >= CORNER_SHARE * boundary


def _block_scales(regions: np.ndarray, block_ratio: float) -> list[dict]:
   """같은 크기 조각 묶음 → 조각마다 {scale, ratios, edge_cells}."""
   found = {n: _grid_ratio(regions, n) for n in SCALES}
   # 한 색짜리 덩어리(평면 네모 등)는 외곽 모양만으로 배율을 못 가린다 — 짝수 네모가 ×2 · ×4 로 잡히는 오탐을 막는다
   one_color = _one_color(regions)
   corners, boundary = _corners(regions)
   out = []
   for i in range(len(regions)):
      ratios = {n: round(float(found[n][0][i]), 3) for n in SCALES}
      edge_cells = int(found[2][1][i])
      scale = None
      if edge_cells >= MIN_EDGE_CELLS and not one_color[i]:
         scale = next((n for n in SCALES if ratios[n] >= block_ratio), 1)
         if scale > 1 and not _bent_enough(int(corners[i]), int(boundary[i]), scale):
            scale = None     # 직선 줄이 거의 다인 칸 — ×n 에 맞아도 근거가 못 된다
      out.append({"scale": scale, "ratios": ratios, "edge_cells": edge_cells})
   return out


def _blocks(arr: np.ndarray, background: bool) -> list[tuple[np.ndarray, tuple[int, int, int, int]]]:
   """(덩어리만 남긴 조각, 자리) 목록. 스프라이트는 투명으로 갈린 덩어리, 배경은 32×32 칸."""
   norm = norm_rgba(arr)
   h, w = norm.shape[:2]
   if background:
      out = []
      for y in range(0, h, BACKGROUND_BLOCK):
         for x in range(0, w, BACKGROUND_BLOCK):
            box = (x, y, min(w, x + BACKGROUND_BLOCK), min(h, y + BACKGROUND_BLOCK))
            out.append((norm[box[1] : box[3], box[0] : box[2]], box))
      return out

   out = []
   labels, boxes = _label(opaque(arr))
   for k, (x0, y0, x1, y1) in enumerate(boxes):
      # 한 칸 둘러 투명 테두리까지 넣는다 — 덩어리 바깥 경계도 격자에 맞아야 한다
      x0, y0, x1, y1 = max(0, x0 - 1), max(0, y0 - 1), min(w, x1 + 1), min(h, y1 + 1)
      piece = norm[y0:y1, x0:x1].copy()
      piece[labels[y0:y1, x0:x1] != k] = 0     # 옆 덩어리가 끼어들지 않게 지운다
      out.append((piece, (x0, y0, x1, y1)))
   return out


def measure_scale(arr: np.ndarray, background: bool = False, block_ratio: float = 0.95) -> dict:
   """도트 배율 재기. 화풍 뽑기(묶음 7 ④) · must.scale 도 이것을 부른다.

   돌려주는 것 :
   - `blocks` : 덩어리마다 {box [x0,y0,x1,y1], scale (1~4, 경계 칸이 적으면 None), ratios {4,3,2: 한 색 비율}, edge_cells}
   - `scales` : 판정된 배율들 (작은 순, 겹침 없음)
   - `mixed` : 한 장 안에서 덩어리마다 배율이 다른가
   - `scale` : 모두 같으면 그 배율, 섞였거나 판정할 덩어리가 없으면 None
   """
   pieces = _blocks(arr, background)
   # 같은 크기 조각끼리 묶어 한 번에 잰다 (배경 32×32 칸은 거의 다 한 묶음이다)
   groups: dict[tuple[int, int], list[int]] = {}
   for i, (piece, _) in enumerate(pieces):
      groups.setdefault(piece.shape[:2], []).append(i)
   found: list[dict] = [{}] * len(pieces)
   for members in groups.values():
      for i, result in zip(members, _block_scales(np.stack([pieces[i][0] for i in members]), block_ratio)):
         found[i] = result
   blocks = [{"box": list(box), **found[i]} for i, (_, box) in enumerate(pieces)]
   scales = sorted({b["scale"] for b in blocks if b["scale"] is not None})
   return {
      "blocks": blocks,
      "scales": scales,
      "mixed": len(scales) > 1,
      "scale": scales[0] if len(scales) == 1 else None,
   }


def measure_smooth(arr: np.ndarray) -> dict:
   """부드러운 확대(bilinear) 흔적 재기.

   양옆(위아래) 이웃 색이 `SMOOTH_GAP` 넘게 다른 세 칸 줄을 「후보」로, 그중 가운데가 두 이웃의 중간색(각 칸 ±8)인 것을 센다.
   돌려주는 것 : {ratio (중간색 ÷ 후보, 후보가 없으면 0), smooth (중간색 칸 수), candidates (후보 수), colors (불투명 색 수)}
   판정(`smooth_hit`)은 색이 `SMOOTH_MIN_COLORS` 이하면 안 본다.
   """
   rgb = arr[:, :, :3].astype(np.int32)
   solid = opaque(arr)
   smooth = cand = 0
   for axis in (1, 0):
      if arr.shape[axis] < 3:
         continue
      take = (lambda a, s: a[:, s]) if axis == 1 else (lambda a, s: a[s])
      left, mid, right = (take(rgb, slice(i, rgb.shape[axis] - 2 + i)) for i in range(3))
      alive = take(solid, slice(0, -2)) & take(solid, slice(1, -1)) & take(solid, slice(2, None))
      wide = alive & (np.abs(left - right).max(axis=-1) > SMOOTH_GAP)
      halfway = np.abs(2 * mid - (left + right)).max(axis=-1) <= 2 * SMOOTH_TOL
      cand += int(wide.sum())
      smooth += int((wide & halfway).sum())
   return {"ratio": round(smooth / cand, 4) if cand else 0.0, "smooth": smooth, "candidates": cand, "colors": color_count(arr)}


def smooth_hit(smooth: dict, cfg: dict) -> bool:
   """부드러운 확대로 걸리는가. 색이 적은 그림(≤ 8)은 넓은 단계 명암일 뿐이라 안 본다 — bilinear 확대면 색이 수백 개가 된다 (실물 시험 버그 4)."""
   colors = smooth.get("colors")
   if colors is not None and colors <= SMOOTH_MIN_COLORS:
      return False
   return smooth["ratio"] > float(cfg["smooth_ratio"])


def judge_integer_scale(scale: dict, smooth: dict, cfg: dict, style_scale: int) -> list[str]:
   """재 둔 값 → 걸린 까닭 목록(비면 통과). cfg 는 프로필 `check.warn.integer_scale`."""
   why = []
   if scale["mixed"]:
      why.append(f"한 장 안에 도트 굵기가 섞였다 : ×{' · ×'.join(map(str, scale['scales']))}")
   elif scale["scale"] is not None and scale["scale"] != int(style_scale):
      why.append(f"도트 굵기 ×{scale['scale']} 가 style.scale ×{style_scale} 와 다르다")
   if smooth_hit(smooth, cfg):
      # 소수 셋째 자리까지 — 둘째 자리면 0.1504 가 「0.15 > 0.15」 로 찍힌다 (실물 시험 버그 6)
      why.append(f"부드러운 확대 흔적 {smooth['ratio']:.3f} > {cfg['smooth_ratio']}")
   return why
