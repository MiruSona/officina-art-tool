"""기본 도형 — 점 · 선 · 원판 · 고리 · 네모. 도트용이라 안티에일리어싱이 없다.

도형 함수는 **불리언 마스크**(높이, 너비)를 돌려준다. 칠하기는 `paint` 하나가 한다.
마스크로 주고받는 까닭 : 템플릿 가이드(겹 색 칠하기) · 마스크 PNG · `arttool.draw` 의 겹 그리기가 같은 도형을 다르게 쓴다.

좌표 약속
- `size` 는 (너비, 높이). 칸 (x, y) 의 가운데가 좌표 (x, y) 다. 그래서 16 칸 캔버스의 한가운데는 7.5 다.
- 캔버스 밖으로 나간 부분은 조용히 잘린다(도형이 일부만 걸쳐도 된다).
- 네모 · 점은 정수 칸 좌표, 원판 · 고리는 가운데에 .5 를 줄 수 있다.
"""

from __future__ import annotations

import math

import numpy as np

from .. import image
from ..errors import ArtToolError
from ..palette import parse_hex

Mask = np.ndarray
Size = tuple[int, int]


def _check_size(size: Size) -> tuple[int, int]:
   width, height = size
   if width <= 0 or height <= 0:
      raise ArtToolError(f"캔버스 크기는 양수여야 한다 : {size}")
   return int(width), int(height)


def empty(size: Size) -> Mask:
   width, height = _check_size(size)
   return np.zeros((height, width), dtype=bool)


def _grid(size: Size) -> tuple[np.ndarray, np.ndarray]:
   width, height = _check_size(size)
   ys, xs = np.mgrid[0:height, 0:width]
   return xs, ys


def box(size: Size, x0: int, y0: int, x1: int, y1: int, filled: bool = True) -> Mask:
   """네모. 끝을 뺀 [x0, x1) × [y0, y1). filled=False 면 1칸 테두리만."""
   if x1 <= x0 or y1 <= y0:
      raise ArtToolError(f"네모가 비었다 : [{x0}, {y0}, {x1}, {y1})")
   xs, ys = _grid(size)
   inside = (xs >= x0) & (xs < x1) & (ys >= y0) & (ys < y1)
   if filled:
      return inside
   core = (xs >= x0 + 1) & (xs < x1 - 1) & (ys >= y0 + 1) & (ys < y1 - 1)
   return inside & ~core


def dot(size: Size, x: int, y: int, side: int = 1) -> Mask:
   """점. 왼쪽 위가 (x, y) 인 side × side 칸."""
   if side <= 0:
      raise ArtToolError(f"점 크기는 양수여야 한다 : {side}")
   return box(size, x, y, x + side, y + side)


def line(size: Size, x0: int, y0: int, x1: int, y1: int) -> Mask:
   """1칸 굵기 곧은 선. 두 끝을 다 칠한다.

   긴 축을 한 칸씩 걷고 짧은 축은 반올림한다(브레젠험과 같은 결과). 계단 길이가 고르게 나온다 —
   예 : 가로 6 · 세로 2 면 계단이 3 · 3 이다(2 · 4 처럼 들쭉날쭉하지 않다).
   """
   out = empty(size)
   height, width = out.shape
   dx, dy = x1 - x0, y1 - y0
   count = max(abs(dx), abs(dy))
   for i in range(count + 1):
      t = i / count if count else 0.0
      # 0.5 를 늘 같은 쪽으로 반올림해야 계단이 대칭으로 나온다(파이썬 round 는 짝수 쪽으로 간다).
      x = math.floor(x0 + dx * t + 0.5)
      y = math.floor(y0 + dy * t + 0.5)
      if 0 <= x < width and 0 <= y < height:
         out[y, x] = True
   return out


def disc(size: Size, cx: float, cy: float, r: float) -> Mask:
   """원판. 칸 가운데가 (cx, cy) 에서 r 보다 가까우면 칠한다.

   가운데가 7.5 · r 8 이면 지름 16 칸을 꽉 채운다.
   """
   if r <= 0:
      raise ArtToolError(f"반지름은 양수여야 한다 : {r}")
   xs, ys = _grid(size)
   return (xs - cx) ** 2 + (ys - cy) ** 2 < r * r


def ring(size: Size, cx: float, cy: float, r: float, width: int = 1, dash: int = 0) -> Mask:
   """고리. 반지름 r 원판에서 r - width 원판을 뺀 띠.

   dash > 0 이면 둘레를 따라 dash 칸 칠하고 dash 칸 비우기를 되풀이한다(띠 가운데 둘레 길이로 잰다).
   """
   if width <= 0:
      raise ArtToolError(f"고리 두께는 양수여야 한다 : {width}")
   if dash < 0:
      raise ArtToolError(f"점선 길이는 0 이상이다 : {dash}")
   band = disc(size, cx, cy, r)
   if r - width > 0:
      band &= ~disc(size, cx, cy, r - width)
   if not dash:
      return band
   # 각도로 고르게 나눈다 : 둘레를 칠함 · 비움 마디 n 개(8 의 배수, 짧으면 4)로 나누고 마디 가운데를 축에 둔다.
   # 둘레 길이 ÷ dash 를 그대로 쓰면 끝 마디가 잘려 한 곳만 들쑥날쑥하고, 0° 에서 시작하면 상하좌우가 안 맞는다.
   xs, ys = _grid(size)
   angle = np.arctan2(ys - cy, xs - cx) % (2 * math.pi)
   around = 2 * math.pi * max(r - width / 2.0, 0.5)
   want = around / dash
   count = 8 * max(1, round(want / 8)) if want >= 8 else 4
   step = 2 * math.pi / count
   index = np.floor((angle + step / 2) / step).astype(int) % count
   return band & (index % 2 == 0)


def _rgba(color) -> tuple[int, int, int, int]:
   if isinstance(color, str):
      return (*parse_hex(color), 255)
   if len(color) == 3:
      return (int(color[0]), int(color[1]), int(color[2]), 255)
   if len(color) == 4:
      return tuple(int(c) for c in color)
   raise ArtToolError(f"색은 #RRGGBB · (R, G, B) · (R, G, B, A) 중 하나다 : {color}")


def paint(arr: image.RGBA, mask: Mask, color) -> image.RGBA:
   """마스크 칸을 한 색으로 덮는다(섞지 않는다). 받은 배열을 고쳐 그대로 돌려준다."""
   if mask.shape != arr.shape[:2]:
      raise ArtToolError(f"마스크 크기 {mask.shape[::-1]} 가 그림 {arr.shape[1::-1]} 와 다르다")
   arr[mask] = _rgba(color)
   return arr


def to_image(mask: Mask, color="#FFFFFF") -> image.RGBA:
   """마스크 → 투명 바탕에 한 색 그림. 마스크 PNG(흰 = 그릴 자리)로 쓸 때."""
   height, width = mask.shape
   return paint(image.new(width, height), mask, color)


# ---- 아래는 P 갈래(`arttool.draw`)가 더한 도형 ----


def round_box(size: Size, x0: int, y0: int, x1: int, y1: int, r: int = 1) -> Mask:
   """모서리를 계단으로 깎은 네모. 끝을 뺀 [x0, x1) × [y0, y1).

   모서리에서 가로 · 세로 칸 거리 합이 r 보다 작은 칸을 뺀다 :
   r 1 → 모서리 1칸, r 2 → 3칸(ㄱ자), r 3 → 6칸. 「정사각 → 모서리 깎기」 절차(설계 6-2)의 깎기 몫이다.
   """
   if r < 0:
      raise ArtToolError(f"모서리 깎기는 0 이상이다 : {r}")
   out = box(size, x0, y0, x1, y1)
   if not r:
      return out
   xs, ys = _grid(size)
   dx = np.minimum(xs - x0, (x1 - 1) - xs)
   dy = np.minimum(ys - y0, (y1 - 1) - ys)
   return out & ~((dx + dy) < r)


def ellipse(size: Size, x0: int, y0: int, x1: int, y1: int) -> Mask:
   """상자 [x0, x1) × [y0, y1) 에 꼭 맞는 타원판. 정사각이면 `disc` 와 같은 칸이 나온다."""
   if x1 <= x0 or y1 <= y0:
      raise ArtToolError(f"타원 상자가 비었다 : [{x0}, {y0}, {x1}, {y1})")
   cx, cy = (x0 + x1 - 1) / 2.0, (y0 + y1 - 1) / 2.0
   rx, ry = (x1 - x0) / 2.0, (y1 - y0) / 2.0
   xs, ys = _grid(size)
   return ((xs - cx) / rx) ** 2 + ((ys - cy) / ry) ** 2 < 1.0


def drop(size: Size, x0: int, y0: int, x1: int, y1: int) -> Mask:
   """물방울 (끝이 위). 상자 아래쪽은 너비만 한 원, 위쪽은 원 가운데에서 꼭짓점까지 좁아진다.

   상자가 너비보다 낮으면 그냥 타원이다.
   """
   if x1 <= x0 or y1 <= y0:
      raise ArtToolError(f"물방울 상자가 비었다 : [{x0}, {y0}, {x1}, {y1})")
   width = x1 - x0
   if y1 - y0 <= width:
      return ellipse(size, x0, y0, x1, y1)
   bulb = ellipse(size, x0, y1 - width, x1, y1)
   cx = (x0 + x1 - 1) / 2.0
   cy = y1 - width + (width - 1) / 2.0     # 원 가운데 줄
   xs, ys = _grid(size)
   # 꼭짓점(y0)에서 반 칸(짝수 너비면 2칸 · 홀수면 1칸), 원 가운데 줄에서 원 반지름이 되게 곧게 넓힌다.
   t = (ys - y0) / max(cy - y0, 1e-9)
   reach = 0.5 + 1e-6 + t * (width / 2.0 - 0.5)
   tip = (ys >= y0) & (ys <= cy) & (np.abs(xs - cx) < reach)
   return bulb | tip


def flood(arr: image.RGBA, x: int, y: int) -> Mask:
   """(x, y) 와 같은 색(투명이면 투명끼리)으로 4방향 이어진 칸. 칠하기 통(`fill`)이 쓴다."""
   height, width = arr.shape[:2]
   if not (0 <= x < width and 0 <= y < height):
      raise ArtToolError(f"칠하기 시작점이 캔버스 밖이다 : ({x}, {y})")
   if arr[y, x, 3] == 0:
      same = arr[:, :, 3] == 0
   else:
      same = (arr == arr[y, x]).all(axis=2)
   out = np.zeros((height, width), dtype=bool)
   stack = [(x, y)]
   while stack:
      px, py = stack.pop()
      if not (0 <= px < width and 0 <= py < height) or out[py, px] or not same[py, px]:
         continue
      out[py, px] = True
      stack.extend(((px + 1, py), (px - 1, py), (px, py + 1), (px, py - 1)))
   return out
