"""가이드 겹 칠하기 · 미리보기 · 견본 띠 · `--over` 확대판 (설계 8-3 표 · 9-4 ⓐ).

- 1배 가이드(`_guide.png`)는 **색 셋만** 쓴다 : 선 `#FF00FF` · 점 `#00FFFF` · 지키는 자리 `#FFFF00`, 알파 0/255.
  프로필 램프에 없는 색이라 가이드가 결과에 섞이면 `check` 의 램프 밖 색에서 바로 걸린다.
- 미리보기(`_preview.png`)는 사람이 본다 : 정수 배 확대 + 칸 격자 + 오른쪽 이름표(「눈 줄」 「baseline」 「머리 상자」 …)
  + 프레임 번호 + (프로필에 램프가 있으면) 아래에 견본 띠.
  가이드 색 셋 규칙은 1배 가이드에만 걸린다 — 이름표 · 견본 띠는 미리보기에만 넣는다.
"""

from __future__ import annotations

import numpy as np

from .. import image
from ..draw import shapes
from .kinds import Guide

LINE = "#FF00FF"
DOT = "#00FFFF"
KEEP = "#FFFF00"
GUIDE_RGB = {(255, 0, 255), (0, 255, 255), (255, 255, 0)}

BG = (40, 40, 44, 255)
SEP = (14, 14, 16, 255)   # 프레임 사이 틈 — 바탕보다 어둡게 해 칸이 갈려 보이게
GRID_MINOR = (58, 58, 64, 255)
GRID_MAJOR = (84, 84, 92, 255)
GAP = 2           # 미리보기 칸 사이(1배 칸 수)
PREVIEW_SIDE = 256
OVER_ALPHA = 0.6  # --over 에서 가이드를 얹는 진하기


def paint(g: Guide) -> image.RGBA:
   """가이드 겹 셋 → 1배 PNG 배열. 지키는 자리 → 선 → 점 순으로 덮는다(뒤가 이긴다)."""
   height, width = g.line.shape
   arr = image.new(width, height)
   shapes.paint(arr, g.keep, KEEP)
   shapes.paint(arr, g.line, LINE)
   shapes.paint(arr, g.dot, DOT)
   return arr


def auto_scale(size: tuple[int, int]) -> int:
   """긴 변이 약 256px 이 되는 정수 배. 2 ~ 16 배 사이."""
   return max(2, min(16, PREVIEW_SIDE // max(size)))


def enlarge(arr: image.RGBA, scale: int, cell: int = 8) -> image.RGBA:
   """정수 배 확대 + 칸 격자. 격자는 칸마다 옅은 1px 선, cell 칸마다 진한 선. 배율이 4 미만이면 격자 없음.

   격자는 바탕에만 그리고 그림 칸이 덮는다 — 그림 색을 바꾸지 않는다.
   """
   height, width = arr.shape[:2]
   out = image.new(width * scale, height * scale, BG)
   if scale >= 4:
      for x in range(width + 1):
         col = min(x * scale, width * scale - 1)
         out[:, col] = GRID_MAJOR if x % cell == 0 else GRID_MINOR
      for y in range(height + 1):
         row = min(y * scale, height * scale - 1)
         out[row, :] = GRID_MAJOR if y % cell == 0 else GRID_MINOR
   big = image.scale_up(arr, scale)
   solid = big[:, :, 3] > 0
   out[solid] = big[solid]
   return out


def hstack(items: list[image.RGBA], gap: int) -> image.RGBA:
   height = max(a.shape[0] for a in items)
   width = sum(a.shape[1] for a in items) + gap * (len(items) - 1)
   out = image.new(width, height, SEP)
   x = 0
   for a in items:
      out[: a.shape[0], x : x + a.shape[1]] = a
      x += a.shape[1] + gap
   return out


def vstack(top: image.RGBA, bottom: image.RGBA, gap: int) -> image.RGBA:
   width = max(top.shape[1], bottom.shape[1])
   out = image.new(width, top.shape[0] + gap + bottom.shape[0], BG)
   out[: top.shape[0], : top.shape[1]] = top
   out[top.shape[0] + gap :, : bottom.shape[1]] = bottom
   return out


def swatch_band(ramps: list[list[tuple[int, int, int]]], cell: int) -> image.RGBA:
   """램프 한 줄 = 한 띠. 칸 cell × cell, 칸 사이 1px."""
   if not ramps:
      return image.new(1, 1, BG)
   cols = max(len(r) for r in ramps)
   out = image.new(cols * (cell + 1) + 1, len(ramps) * (cell + 1) + 1, BG)
   for row, ramp in enumerate(ramps):
      for col, rgb in enumerate(ramp):
         x, y = 1 + col * (cell + 1), 1 + row * (cell + 1)
         out[y : y + cell, x : x + cell] = (*rgb, 255)
   return out


def tile2x2(arr: image.RGBA) -> image.RGBA:
   return np.tile(arr, (2, 2, 1))


def overlay(arr: image.RGBA, frames: list[image.RGBA]) -> image.RGBA:
   """프레임을 차례로 겹친다(움직임 가이드 미리보기 — 점이 지나는 길이 다 보인다)."""
   out = arr.copy()
   for f in frames:
      solid = f[:, :, 3] > 0
      out[solid] = f[solid]
   return out


def bottom_center(inner: tuple[int, int], outer: tuple[int, int]) -> tuple[int, int]:
   """크기 inner (너비, 높이) 를 outer 판의 아래 가운데에 놓을 때 왼쪽 위 (x, y)."""
   return (outer[0] - inner[0]) // 2, outer[1] - inner[1]


def over(picture: image.RGBA, guide_arr: image.RGBA, scale: int) -> image.RGBA:
   """그림을 확대하고 그 위에 가이드를 반쯤 비치게 얹는다.

   크기가 다르면 둘 다 **아래 가운데**에 맞추고 판을 큰 쪽으로 늘린다 — 캐릭터 · 건물은 발 · 바닥이 기준이라서다.
   (예 48×64 그림을 64×64 템플릿에 : 판 64×64, 그림은 x 8 부터. 아무것도 잘리지 않는다)
   """
   gh, gw = guide_arr.shape[:2]
   ph, pw = picture.shape[:2]
   width, height = max(gw, pw), max(gh, ph)
   image.check_pixels(width * scale, height * scale, "겹쳐 보기")
   base = image.new(width, height)
   x, y = bottom_center((pw, ph), (width, height))
   base[y : y + ph, x : x + pw] = picture
   marks = image.new(width, height)
   x, y = bottom_center((gw, gh), (width, height))
   marks[y : y + gh, x : x + gw] = guide_arr
   out = enlarge(base, scale).astype(np.float32)
   big = image.scale_up(marks, scale)
   mark = big[:, :, 3] > 0
   out[mark, :3] = out[mark, :3] * (1 - OVER_ALPHA) + big[mark, :3].astype(np.float32) * OVER_ALPHA
   out[mark, 3] = 255
   return np.clip(np.rint(out), 0, 255).astype(np.uint8)


# ── 이름표 (미리보기에만) ─────────────────────────────

LABEL_TEXT = (236, 236, 240, 255)
LEADER = (150, 150, 160, 255)
CHIPS = {"line": (255, 0, 255, 255), "dot": (0, 255, 255, 255), "keep": (255, 255, 0, 255)}
LEAD_W = 10       # 미리보기 오른쪽 끝 ~ 이름표 사이 꺾은 줄 폭


def _is_int(v) -> bool:
   return isinstance(v, int) and not isinstance(v, bool)


def _positions(key: str, name: str, value) -> list[tuple[int, str]]:
   """셈 값 하나 → (1배 y, 글자) 목록. 모르는 꼴은 빈 목록. 글자 값은 맨 위 줄에 그대로."""
   if isinstance(value, str) and value:
      return [(0, f"{name} {value}")]
   if _is_int(value):
      if key.endswith("_y"):
         return [(value, f"{name} y={value}")]
      if key.endswith("_x"):
         return [(0, f"{name} x={value}")]
      return [(0, name)]
   if isinstance(value, list) and value and all(_is_int(v) for v in value):
      if len(value) == 4:
         x0, y0, x1, y1 = value
         return [(y0, f"{name} {x1 - x0}x{y1 - y0}")]
      if len(value) == 2 and key.endswith(("_y", "_x")):
         # 가운데 띠 [첫 칸, 끝 칸 + 1) — 자르는 줄은 첫 칸 · 끝 칸 두 줄
         a, b = value
         axis = "y" if key.endswith("_y") else "x"
         return [(a if axis == "y" else 0, f"{name} {axis}={a} · {b - 1}")]
   if isinstance(value, list) and value and all(isinstance(p, list) and len(p) == 2 and all(_is_int(v) for v in p) for p in value):
      return [(p[1], f"{name} {i + 1}") for i, p in enumerate(value)]
   if isinstance(value, list) and value and all(
      isinstance(p, list) and len(p) == 3 and _is_int(p[0]) and _is_int(p[1]) and isinstance(p[2], str) for p in value
   ):
      # 이름 붙은 점 [x, y, 이름] — 「칸 1」 대신 「지붕 칸」 처럼 뜻 있는 이름으로 찍는다
      return [(p[1], f"{p[2]} {name}") for p in value]
   return []


def marks(labels, calc: dict, scale: int) -> list[tuple[int, str, tuple]]:
   """처리기 이름표 표 + 셈 결과 → (미리보기 y px, 글자, 색 칩) 목록, 위에서 아래로."""
   out = []
   for key, name, color in labels:
      for y, text in _positions(key, name, calc.get(key)):
         out.append((y * scale + scale // 2, text, CHIPS[color]))
   return sorted(out, key=lambda m: m[0])


def label_side(preview: image.RGBA, rows: list[tuple[int, str, tuple]], px: int = image.LABEL_PX) -> image.RGBA:
   """미리보기 오른쪽에 이름표 칸을 붙인다. 이름표는 자기 줄 높이에 두고, 겹치면 아래로 밀고 꺾은 줄로 잇는다."""
   if not rows:
      return preview
   ph, pw = preview.shape[:2]
   row_h = px + 4
   chip = max(4, px - 5)
   text_w = max(image.label_width(text, px) for _, text, _ in rows)
   col_w = LEAD_W + chip + 4 + text_w + 6
   tops, cursor = [], 0
   for y, _, _ in rows:
      top = max(0, y - row_h // 2, cursor)
      tops.append(top)
      cursor = top + row_h
   height = max(ph, cursor)
   image.check_pixels(pw + col_w, height, "미리보기")
   out = image.new(pw + col_w, height, BG)
   out[:ph, :pw] = preview
   for (y, text, rgb), top in zip(rows, tops):
      y = min(max(y, 0), height - 1)
      mid = top + row_h // 2
      bend = pw + LEAD_W // 2
      out[y, pw:bend] = LEADER
      out[min(y, mid) : max(y, mid) + 1, bend] = LEADER
      out[mid, bend : pw + LEAD_W] = LEADER
      cx = pw + LEAD_W
      out[top + (row_h - chip) // 2 : top + (row_h - chip) // 2 + chip, cx : cx + chip] = rgb
      area = out[top : top + row_h, cx + chip + 4 :]
      image.draw_label(area, text, 0, 1, px, LABEL_TEXT)
   return out


def label_under(preview: image.RGBA, texts: list[str], xs: list[int], px: int = image.LABEL_PX) -> image.RGBA:
   """미리보기 아래에 띠를 붙이고 xs 자리마다 글자(프레임 번호 등)를 찍는다."""
   if not texts:
      return preview
   ph, pw = preview.shape[:2]
   band = px + 6
   out = image.new(pw, ph + band, BG)
   out[:ph] = preview
   for text, x in zip(texts, xs):
      image.draw_label(out[ph:, :], text, x + 2, 2, px, LABEL_TEXT)
   return out

