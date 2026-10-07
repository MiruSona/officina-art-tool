"""덩어리 묶기 · 떨어진 조각 찾기 · 이웃 투표.

`split` 과 뒤의 아이콘 정리가 같이 쓴다. 그림 파일은 모르고 numpy 배열만 받는다.
"""

from __future__ import annotations

import numpy as np

NONE = -1
VOTE_RADII = (1, 2, 3, 4, 6)

Point = tuple[int, int]


def components(mask: np.ndarray) -> list[list[Point]]:
   """참인 칸을 8방향 연결로 묶는다. 큰 덩어리부터, 같으면 먼저 만난 것부터. 점은 (x, y)."""
   height, width = mask.shape
   seen = np.zeros(mask.shape, dtype=bool)
   groups: list[list[Point]] = []
   for y0, x0 in zip(*np.nonzero(mask)):
      if seen[y0, x0]:
         continue
      seen[y0, x0] = True
      stack = [(int(x0), int(y0))]
      group = []
      while stack:
         x, y = stack.pop()
         group.append((x, y))
         for ny in range(max(0, y - 1), min(height, y + 2)):
            for nx in range(max(0, x - 1), min(width, x + 2)):
               if mask[ny, nx] and not seen[ny, nx]:
                  seen[ny, nx] = True
                  stack.append((nx, ny))
      groups.append(sorted(group, key=lambda p: (p[1], p[0])))
   # sorted 는 안정 정렬이라 크기가 같으면 훑은 순서(위→아래)가 남는다.
   return sorted(groups, key=len, reverse=True)


def small_pieces(mask: np.ndarray, min_piece: int) -> list[list[Point]]:
   """가장 큰 덩어리가 아니면서 min_piece 보다 작은 덩어리들. min_piece 가 0 이하면 없다."""
   if min_piece <= 0:
      return []
   groups = components(mask)
   return [g for g in groups[1:] if len(g) < min_piece]


def vote_at(owner: np.ndarray, points: list[Point], radius: int, exclude: set[int] | None = None) -> int | None:
   """반경 하나에서 points 둘레의 주인 번호로 투표한다. 표가 없으면 None.

   표 무게는 1 / (|dx| + |dy| + 1). 같으면 먼저 표를 준 쪽 — 위 줄부터, 줄 안에서는 왼쪽부터 훑는다.
   """
   skip = exclude or set()
   own = set(points)
   height, width = owner.shape
   scores: dict[int, float] = {}
   for x, y in points:
      for ny in range(max(0, y - radius), min(height, y + radius + 1)):
         for nx in range(max(0, x - radius), min(width, x + radius + 1)):
            who = int(owner[ny, nx])
            if who == NONE or who in skip or (nx, ny) in own:
               continue
            scores[who] = scores.get(who, 0.0) + 1.0 / (abs(nx - x) + abs(ny - y) + 1)
   if not scores:
      return None
   # max 는 같은 값이면 먼저 넣은 것을 고른다. 사전은 넣은 차례를 지킨다.
   return max(scores, key=lambda k: scores[k])


def vote(owner: np.ndarray, points: list[Point], exclude: set[int] | None = None, radii=VOTE_RADII) -> int | None:
   """points 를 한 덩어리로 보고 반경을 넓히며 투표한다. 처음 표가 나온 반경에서 정한다."""
   for radius in radii:
      winner = vote_at(owner, points, radius, exclude)
      if winner is not None:
         return winner
   return None


def vote_each(owner: np.ndarray, points: list[Point], radii=VOTE_RADII) -> tuple[dict[Point, int], list[Point]]:
   """점마다 따로 투표한다. 한 반경에서 정해진 점은 반경이 끝난 뒤 owner 에 넣어 다음 반경 투표에 낀다.

   owner 를 고친다. (정해진 점 → 번호, 끝까지 못 정한 점) 을 돌려준다.
   """
   decided: dict[Point, int] = {}
   left = list(points)
   for radius in radii:
      found = {}
      rest = []
      for x, y in left:
         winner = vote_at(owner, [(x, y)], radius)
         if winner is None:
            rest.append((x, y))
         else:
            found[(x, y)] = winner
      for (x, y), winner in found.items():
         owner[y, x] = winner
      decided.update(found)
      left = rest
      if not left:
         break
   return decided, left


def touches(owner: np.ndarray, x: int, y: int, who: int) -> bool:
   """(x, y) 의 8방향 이웃 중에 주인이 who 인 칸이 있나."""
   height, width = owner.shape
   for ny in range(max(0, y - 1), min(height, y + 2)):
      for nx in range(max(0, x - 1), min(width, x + 2)):
         if (nx, ny) != (x, y) and owner[ny, nx] == who:
            return True
   return False


def labels(mask: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
   """8방향 이어짐 덩이 번호(큰 덩이부터 0, 1, …, 덩이 밖 -1)와 덩이별 칸 수.

   `components` 와 같은 묶음을 파이썬 루프 없이 낸다 — 2048 그림에서 34초 → 0.6초 (6판 리뷰). `style.light` 에서 옮겨 왔다.

   numpy 로만 짠다 — 줄마다 이어진 칸(run)을 뽑고, 윗줄 · 아랫줄 run 이 닿으면(대각선 포함) 잇는다.
   잇기는 「작은 번호로 맞추기 + 번호 건너뛰기」 를 안 바뀔 때까지 되풀이한다.
   """
   h, w = mask.shape
   edge = np.diff(np.pad(mask.astype(np.int8), ((0, 0), (1, 1))), axis=1)
   rows, starts = np.nonzero(edge == 1)
   _, ends = np.nonzero(edge == -1)            # 끝 칸 + 1. 같은 줄 순서라 starts 와 짝이 맞는다
   n = len(rows)
   if n == 0:
      return np.full(mask.shape, -1, dtype=np.int64), np.zeros(0, dtype=np.int64)
   # 아랫줄에서 닿는 run 은 이어진 구간 [lo, hi) — 줄 · 칸을 한 열쇠로 묶어 searchsorted 로 찾는다
   span = w + 4
   lo = np.searchsorted(rows * span + ends, (rows + 1) * span + starts, side="left")       # 끝 >= 내 시작 - 1
   hi = np.searchsorted(rows * span + starts + 1, (rows + 1) * span + ends + 1, side="right")  # 시작 <= 내 끝 + 1
   count = np.maximum(hi - lo, 0)
   a = np.repeat(np.arange(n), count)
   b = np.repeat(lo, count) + (np.arange(int(count.sum())) - np.repeat(np.cumsum(count) - count, count))
   comp = np.arange(n)
   while True:
      low = np.minimum(comp[a], comp[b])
      new = comp.copy()
      np.minimum.at(new, a, low)
      np.minimum.at(new, b, low)
      new = new[new]
      if np.array_equal(new, comp):
         break
      comp = new
   lengths = ends - starts
   _, comp = np.unique(comp, return_inverse=True)
   comp = comp.reshape(-1)
   sizes = np.bincount(comp, lengths)
   order = np.argsort(-sizes, kind="stable")    # 큰 덩이부터
   rank = np.empty_like(order)
   rank[order] = np.arange(len(order))
   comp = rank[comp]
   # run 번호를 칸에 칠한다 — 시작에 +번호, 끝 다음 칸에 -번호를 놓고 줄 따라 누적
   paint = np.zeros(h * w + 1, dtype=np.int64)
   np.add.at(paint, rows * w + starts, comp + 1)
   np.add.at(paint, rows * w + ends, -(comp + 1))
   label = np.cumsum(paint[:-1]).reshape(h, w) - 1
   return label, sizes[order].astype(np.int64)
