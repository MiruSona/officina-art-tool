"""③ isolated · ④ color_cap · ⑤ near_colors — 픽셀 · 색 수 검사 (설계 7-2 ③ ④ ⑤)."""

from __future__ import annotations

import numpy as np

from .. import image, palette
from . import long_side, opaque, raw_edge

MAX_POINTS = 50       # isolated 보고에 적는 좌표 수
MAX_PAIRS = 20        # near_colors 보고에 적는 쌍 수
NEAR_MAX_COLORS = 4096   # 색이 이보다 많으면 check 는 near_colors 를 건너뛴다 (도트가 아닌 그림 · 큰 배경. 다 걸릴 것이라 셈이 헛일)


# --- ③ isolated ---


def measure_isolated(arr: np.ndarray) -> dict:
   """외톨이 픽셀 재기 : 8이웃에 같은 색이 하나도 없는 불투명 칸. 투명과 맞닿은 가장자리 칸(바깥 AA)은 뺀다.

   돌려주는 것 : {count, opaque, ratio (외톨이 ÷ 불투명), points [[x, y] …] 앞 50개}
   """
   solid = opaque(arr)
   h, w = solid.shape
   # int64 로 엮는다. int32 면 R ≥ 128 에서 넘쳐 순백 #FFFFFFFF 가 빈칸 표시 -1 과 같아진다
   rgba = arr.astype(np.int64)
   key = (rgba[:, :, 0] << 24) | (rgba[:, :, 1] << 16) | (rgba[:, :, 2] << 8) | rgba[:, :, 3]
   pad = np.full((h + 2, w + 2), -1, dtype=np.int64)
   pad[1:-1, 1:-1] = np.where(solid, key, -1)
   center = pad[1:-1, 1:-1]
   same = np.zeros((h, w), dtype=bool)
   for dy in (-1, 0, 1):
      for dx in (-1, 0, 1):
         if dy == 0 and dx == 0:
            continue
         same |= pad[1 + dy : 1 + dy + h, 1 + dx : 1 + dx + w] == center
   lonely = solid & ~same & ~raw_edge(arr)
   ys, xs = np.nonzero(lonely)
   n_opaque = int(solid.sum())
   count = int(lonely.sum())
   return {
      "count": count,
      "opaque": n_opaque,
      "ratio": round(count / n_opaque, 4) if n_opaque else 0.0,
      "points": [[int(x), int(y)] for y, x in list(zip(ys, xs))[:MAX_POINTS]],
   }


def judge_isolated(m: dict, cfg: dict) -> list[str]:
   if m["ratio"] > float(cfg["max_ratio"]):
      return [f"외톨이 픽셀 {m['count']}개 · 비율 {m['ratio']:.3f} > {cfg['max_ratio']}"]
   return []


# --- ④ color_cap ---


def color_count(arr: np.ndarray) -> int:
   """불투명 색 가짓수. 셈은 `image.count_colors` 하나에 둔다 (RGB 를 수 하나로 엮어 세서 큰 그림도 빠르다)."""
   return image.count_colors(arr)


def measure_colors(arr: np.ndarray) -> dict:
   """크기 · 색 수 재기. 돌려주는 것 : {size (불투명 bbox 긴 변), colors (불투명 색 가짓수)}"""
   return {"size": long_side(arr), "colors": color_count(arr)}


def cap_for(size: int, table: dict[int, int]) -> tuple[int, int]:
   """크기 n 에 맞는 (표의 칸, 한도). n 이상인 가장 작은 칸, 표 끝을 넘으면 마지막 칸."""
   keys = sorted(int(k) for k in table)
   pick = next((k for k in keys if k >= size), keys[-1])
   return pick, int(table[pick])


def judge_color_cap(m: dict, cap: int) -> list[str]:
   if m["colors"] > cap:
      return [f"색 {m['colors']}가지 > 권장 {cap}가지 (크기 {m['size']})"]
   return []


# --- ⑤ near_colors ---


def measure_near_colors(arr: np.ndarray, max_delta: int = 4) -> list[dict]:
   """비슷한 색 쌍 재기 : 불투명 색 쌍 중 RGB 각 칸 차이의 최댓값 ≤ max_delta 인 것. 화풍 뽑기 ① 1단계도 같은 셈이다.

   돌려주는 것 : 쌍 목록 [{from, to, from_count, to_count, delta}] — 적게 쓰인 쪽(from) → 많이 쓰인 쪽(to) 합치기 후보.
   from_count 가 큰 순으로 늘어놓는다(많이 쓰인 잡색부터).
   """
   solid = opaque(arr)
   if not solid.any():
      return []
   colors, counts = np.unique(arr[:, :, :3][solid].reshape(-1, 3), axis=0, return_counts=True)
   colors = colors.astype(np.int32)
   pairs = []
   for a, b, delta in _close_pairs(colors, max_delta):
      small, big = (a, b) if (counts[a], -a) < (counts[b], -b) else (b, a)
      pairs.append({
         "from": palette.to_hex(tuple(int(v) for v in colors[small])),
         "to": palette.to_hex(tuple(int(v) for v in colors[big])),
         "from_count": int(counts[small]),
         "to_count": int(counts[big]),
         "delta": delta,
      })
   pairs.sort(key=lambda p: (-p["from_count"], p["from"], p["to"]))
   return pairs


def _close_pairs(colors: np.ndarray, max_delta: int) -> list[tuple[int, int, int]]:
   """색 번호 쌍 (a < b, 차이). 색을 (max_delta + 1) 크기 상자에 나눠 이웃 상자끼리만 견준다.

   가까운 두 색은 각 칸에서 상자 하나 이상 떨어질 수 없다. 색이 수만 가지인 그림(도트가 아닌 그림)도 메모리가 안 터진다.
   상자 번호로 색을 정렬해 두고, 이웃 상자 27 개마다 「그 상자에 든 색 구간」을 searchsorted 로 한 번에 찾는다 — 파이썬 줄 돌기가 없다.
   돌려주는 차례는 (a, b) 순이다.
   """
   colors = np.asarray(colors, dtype=np.int64)
   if len(colors) < 2:
      return []
   step = max_delta + 1
   box = colors // step + 1                         # +1 : 이웃 상자 -1 도 음수가 안 되게
   span = int(box.max()) + 2
   key = (box[:, 0] * span + box[:, 1]) * span + box[:, 2]
   order = np.argsort(key, kind="stable")
   sorted_key = key[order]
   found_a, found_b = [], []
   for dr in (-1, 0, 1):
      for dg in (-1, 0, 1):
         for db in (-1, 0, 1):
            target = key + (dr * span + dg) * span + db
            lo = np.searchsorted(sorted_key, target, side="left")
            hi = np.searchsorted(sorted_key, target, side="right")
            reach = hi - lo
            total = int(reach.sum())
            if total == 0:
               continue
            a = np.repeat(np.arange(len(colors)), reach)
            offset = np.arange(total) - np.repeat(np.cumsum(reach) - reach, reach)
            b = order[np.repeat(lo, reach) + offset]
            keep = a < b
            a, b = a[keep], b[keep]
            near = np.abs(colors[a] - colors[b]).max(axis=1) <= max_delta    # 상자마다 바로 걸러 메모리를 작게
            found_a.append(a[near])
            found_b.append(b[near])
   if not found_a:
      return []
   a = np.concatenate(found_a)
   b = np.concatenate(found_b)
   gap = np.abs(colors[a] - colors[b]).max(axis=1)
   pick = np.lexsort((b, a))
   return [(int(x), int(y), int(g)) for x, y, g in zip(a[pick], b[pick], gap[pick])]


def judge_near_colors(pairs: list[dict], min_pairs: int = 1) -> list[str]:
   """쌍이 min_pairs 개 이상이면 걸린다. 정식 그림도 짝 몇 개는 흔하다 — 실물 기준 무리 최대 31, 날것은 853 넘게 (실물 시험 3장)."""
   if pairs and len(pairs) >= int(min_pairs):
      return [f"비슷한 색 쌍 {len(pairs)}개 (합치기 후보)"]
   return []
