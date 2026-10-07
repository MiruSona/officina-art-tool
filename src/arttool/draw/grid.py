"""문자 격자 — 그림을 글자 한 칸 = 칸 하나인 글로 옮긴다 (설계 `Docs/Design/2026-10-07-draw고리설계.md` 2절).

    k #2A2238          ← 범례 줄 : 글자 #RRGGBB
    s #F6D0B0
    # 원점 8,8         ← rulers=True 일 때만 : 첫 칸의 캔버스 좌표 (paste_grid 가 at 없이 이 자리에 찍는다)
                       ← 빈 줄 하나로 범례와 격자를 가른다
       01234567        ← rulers=True 일 때만 : x 눈금(일의 자리, 캔버스 절대 좌표)
     0 ssssssss        ← 줄 머리 `yy ` 도 rulers=True 일 때만
     1 sskkskks

약속
- `.` 은 늘 투명(알파 0). 반투명(0 < 알파 < 255)은 그 RGB 색으로 범례에 올린다.
- `#` 로 시작하는 줄은 주석이다. 그래서 `.` · `#` · 공백은 범례 글자로 못 쓴다.
- 글자는 `a-z` → `A-Z` → `0-9` 순서로 자동 배정한다(최대 62색). 같은 색은 늘 같은 글자다.
- 창(box)은 `shapes` 와 같은 `(x0, y0, x1, y1)` 끝 뺌. 창이 있든 없든 한 변이 64 를 넘으면 거절한다.
- x 눈금은 일의 자리뿐이라 x 원점을 못 담는다. 그래서 눈금을 찍을 때 `# 원점 x,y` 줄을 범례 끝에 같이 쓴다.
"""

from __future__ import annotations

import re
import string

import numpy as np

from ..errors import ArtToolError
from ..palette import RGB, parse_hex, to_hex

LETTERS = string.ascii_lowercase + string.ascii_uppercase + string.digits
MAX_SIDE = 64
TRANSPARENT = "."
_FORBIDDEN = {TRANSPARENT, "#"}
_LEGEND_LINE = re.compile(r"^(\S)\s+(#[0-9A-Fa-f]{6})\s*$")
_RULER_TOP = re.compile(r"^\s+\d+\s*$")
_ROW_HEAD = re.compile(r"^\s*(\d+)\s+(\S+)\s*$")
_ORIGIN_LINE = re.compile(r"^#\s*원점\s+(-?\d+)\s*,\s*(-?\d+)\s*$")

Box = tuple[int, int, int, int]
Origin = tuple[int | None, int]


def require_rgba(arr) -> None:
   """RGBA 배열(높이, 너비, 4)이 아니면 거절한다."""
   if not isinstance(arr, np.ndarray) or arr.ndim != 3 or arr.shape[2] != 4:
      raise ArtToolError(f"RGBA 배열(높이, 너비, 4)이어야 한다 : {getattr(arr, 'shape', type(arr))}")


def bbox_of(mask: np.ndarray) -> list[int] | None:
   """참인 칸을 감싸는 상자 [x0, y0, x1, y1] (끝 뺌). 참인 칸이 없으면 None."""
   ys, xs = np.nonzero(mask)
   if len(xs) == 0:
      return None
   return [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]


def _rgb(color) -> RGB:
   """#RRGGBB · (R, G, B) → (R, G, B). 값은 0 ~ 255 정수만."""
   if isinstance(color, str):
      return parse_hex(color)
   values = tuple(color)
   if len(values) != 3 or not all(isinstance(v, (int, np.integer)) and 0 <= v <= 255 for v in values):
      raise ArtToolError(f"범례 색은 #RRGGBB · (R, G, B) 0 ~ 255 정수다 : {color}")
   return int(values[0]), int(values[1]), int(values[2])


class Legend:
   """색 ↔ 글자 양방향 표. 되읽고 되쓸 때 글자가 바뀌지 않게 한 번 준 글자를 지킨다."""

   def __init__(self, mapping: dict[str, RGB] | None = None):
      self._by_letter: dict[str, RGB] = {}
      self._by_color: dict[RGB, str] = {}
      for letter, color in (mapping or {}).items():
         self._add(letter, _rgb(color))

   def __len__(self) -> int:
      return len(self._by_letter)

   def __repr__(self) -> str:
      return f"Legend({len(self)} 색)"

   def _add(self, letter: str, rgb: RGB) -> None:
      if not isinstance(letter, str) or len(letter) != 1 or letter.isspace() or letter in _FORBIDDEN:
         raise ArtToolError(f"범례 글자는 한 글자이고 '.' · '#' · 공백은 못 쓴다 : {letter!r}")
      if letter in self._by_letter:
         raise ArtToolError(f"범례 글자 {letter!r} 가 두 번 나온다")
      if rgb in self._by_color:
         raise ArtToolError(f"색 {to_hex(rgb)} 가 글자 {self._by_color[rgb]!r} · {letter!r} 둘에 걸렸다")
      self._by_letter[letter] = rgb
      self._by_color[rgb] = letter

   def assign(self, rgb) -> str:
      """색의 글자. 처음 보는 색이면 비어 있는 다음 글자를 준다."""
      key = _rgb(rgb)
      if key in self._by_color:
         return self._by_color[key]
      for letter in LETTERS:
         if letter not in self._by_letter:
            self._add(letter, key)
            return letter
      raise ArtToolError(f"색이 {len(LETTERS)} 개를 넘는다 — 범례 글자가 모자란다. 색을 줄인다 : {to_hex(key)}")

   def color(self, letter: str) -> RGB:
      """글자의 색. 범례에 없는 글자면 거절한다."""
      if letter not in self._by_letter:
         raise ArtToolError(f"범례에 없는 글자다 : {letter!r}")
      return self._by_letter[letter]

   def letters(self) -> dict[str, RGB]:
      """글자 → 색 사본(배정 순서)."""
      return dict(self._by_letter)

   def adopt(self, letter: str, rgb) -> bool:
      """글자 · 색이 둘 다 비어 있으면 등록하고 True. 하나라도 이미 쓰였으면 아무것도 안 하고 False."""
      key = _rgb(rgb)
      if letter in self._by_letter or key in self._by_color:
         return False
      self._add(letter, key)
      return True

   def text(self) -> str:
      """범례 줄들(`k #2A2238` 꼴, 배정 순서). 끝 줄바꿈 없음."""
      return "\n".join(f"{letter} {to_hex(rgb)}" for letter, rgb in self._by_letter.items())


def _window(box: Box | None, width: int, height: int) -> Box:
   """창을 캔버스 안으로 자른다. 창이 없으면 전체. 어느 쪽이든 한 변이 64 칸을 넘으면 거절."""
   if box is None:
      if width > MAX_SIDE or height > MAX_SIDE:
         raise ArtToolError(
            f"그림이 {width}x{height} 라 {MAX_SIDE} 칸을 넘는다. "
            f"box=(x0, y0, x1, y1) 로 창을 주라 (한 변 {MAX_SIDE} 칸 이하)")
      return 0, 0, width, height
   if len(box) != 4:
      raise ArtToolError(f"box 는 (x0, y0, x1, y1) 네 값이다 : {box}")
   x0, y0, x1, y1 = (int(v) for v in box)
   x0, x1 = max(x0, 0), min(x1, width)
   y0, y1 = max(y0, 0), min(y1, height)
   if x0 >= x1 or y0 >= y1:
      raise ArtToolError(f"창이 비었다 — 캔버스 {width}x{height} 안에 걸치는 칸이 없다 : {box}")
   if x1 - x0 > MAX_SIDE or y1 - y0 > MAX_SIDE:
      raise ArtToolError(f"창이 {x1 - x0}x{y1 - y0} 라 {MAX_SIDE} 칸을 넘는다. 창을 한 변 {MAX_SIDE} 칸 이하로 나눈다 : {box}")
   return x0, y0, x1, y1


def to_text(arr: np.ndarray, legend: Legend | None = None, box: Box | None = None, rulers: bool = False) -> str:
   """RGBA 배열(높이, 너비, 4) → 격자 글(범례 + 빈 줄 + 격자 줄, 끝 줄바꿈 하나).

   `legend` 를 주면 그 표에 이어 배정한다(호출 뒤에도 새 색이 남아 있다).
   rulers=True 면 범례 끝에 `# 원점 x0,y0` 줄을 붙인다 — 되읽어 `paste_grid` 가 같은 자리에 찍게.
   """
   require_rgba(arr)
   if legend is None:
      legend = Legend()
   height, width = arr.shape[:2]
   x0, y0, x1, y1 = _window(box, width, height)

   rows = []
   for y in range(y0, y1):
      chars = []
      for x in range(x0, x1):
         r, g, b, a = (int(v) for v in arr[y, x])
         if a == 0:
            chars.append(TRANSPARENT)
         else:
            chars.append(legend.assign((r, g, b)))
      rows.append("".join(chars))

   if rulers:
      head = len(str(y1 - 1))
      top = " " * (head + 1) + "".join(str(x % 10) for x in range(x0, x1))
      rows = [top] + [f"{y:>{head}} {row}" for y, row in zip(range(y0, y1), rows)]

   legend_block = legend.text()
   if not legend_block:
      legend_block = "# 범례 : 색 없음 (모두 투명)"
   if rulers:
      legend_block += f"\n# 원점 {x0},{y0}"
   return legend_block + "\n\n" + "\n".join(rows) + "\n"


def _merge(own: Legend, given: Legend | None) -> Legend:
   """글 안 범례(own)를 먼저, 모자란 글자는 given 에서 채운 새 표. 같은 글자에 다른 색이면 거절한다.

   글 안 범례가 비었으면 given 을 그대로 돌려준다(같은 객체 — 새 색 배정이 그 표에 남게).
   given 의 색이 own 에 다른 글자로 이미 있으면 그 given 글자는 싣지 않는다(한 색 = 한 글자).
   """
   if given is None:
      return own
   if not len(own):
      return given
   merged = Legend(own.letters())
   mine = own.letters()
   for letter, rgb in given.letters().items():
      if letter in mine:
         if mine[letter] != rgb:
            raise ArtToolError(
               f"범례 글자 {letter!r} 가 글 안 범례({to_hex(mine[letter])})와 캔버스 범례({to_hex(rgb)})에서 다르다. "
               f"글 안 범례 글자를 바꾼다")
         continue
      merged.adopt(letter, rgb)
   return merged


def parse(text: str, legend: Legend | None = None) -> tuple[Legend, list[str], tuple[int, int], Origin | None]:
   """격자 글 → (범례, 격자 줄, (너비, 높이), 원점). `to_text` 의 거꾸로.

   `#` 주석 · 빈 줄 · 맨 위 x 눈금 줄 · 줄머리 숫자(`yy `)는 떼고 읽는다.
   범례는 글 안 범례를 먼저, 모자란 글자는 `legend` 인자에서 채운다(같은 글자에 다른 색이면 거절).
   원점은 첫 칸의 캔버스 좌표다 : `# 원점 x,y` 줄이 있으면 (x, y), 없이 줄머리만 있으면 (None, y), 둘 다 없으면 None.
   틀린 곳은 줄 번호(1부터)를 붙여 거절한다.
   """
   own = Legend()
   rows: list[str] = []
   first = 0                                   # 첫 격자 줄 번호 — 너비 오류에 같이 알린다
   origin_line: tuple[int, int] | None = None
   head_y: int | None = None                   # 첫 격자 줄의 줄머리 y
   for number, line in enumerate(text.splitlines(), start=1):
      at = _ORIGIN_LINE.match(line.strip())
      if at:
         origin_line = (int(at.group(1)), int(at.group(2)))
         continue
      if not line.strip() or line.lstrip().startswith("#"):
         continue
      found = _LEGEND_LINE.match(line)
      if found and not rows:
         try:
            own._add(found.group(1), parse_hex(found.group(2)))
         except ArtToolError as exc:
            raise ArtToolError(f"{number}째 줄 : {exc}") from exc
         continue
      if not rows and _RULER_TOP.match(line):
         continue                               # 맨 위 x 눈금 줄
      row = line
      if any(c.isspace() for c in line.rstrip()):
         head = _ROW_HEAD.match(line)
         if head is None:
            raise ArtToolError(f"{number}째 줄 : 격자 줄에 빈칸이 있다 (줄머리 `yy ` 만 된다) : {line!r}")
         row = head.group(2)
         if not rows:
            head_y = int(head.group(1))
      row = row.rstrip()
      if rows and len(row) != len(rows[0][1]):
         raise ArtToolError(f"{number}째 줄 : 너비가 {len(row)} 칸이다 ({first}째 줄은 {len(rows[0][1])} 칸)")
      if not rows:
         first = number
      rows.append((number, row))
   if not rows:
      raise ArtToolError("격자 줄이 없다")

   origin: Origin | None = None
   if origin_line is not None:
      if head_y is not None and head_y != origin_line[1]:
         raise ArtToolError(f"원점 줄 y {origin_line[1]} 와 첫 줄머리 y {head_y} 가 다르다")
      origin = origin_line
   elif head_y is not None:
      origin = (None, head_y)                  # x 눈금은 일의 자리뿐이라 x 원점은 모른다

   use = _merge(own, legend) if legend is not None else (own if len(own) else Legend())
   known = use.letters()
   for number, row in rows:
      for column, char in enumerate(row):
         if char != TRANSPARENT and char not in known:
            if not known:
               raise ArtToolError(f"{number}째 줄 {column}째 칸 : 범례가 없는데 글자 {char!r} 가 있다. 범례 줄(`{char} #RRGGBB`)을 붙인다")
            raise ArtToolError(f"{number}째 줄 {column}째 칸 : 범례에 없는 글자 {char!r} (있는 글자 : {''.join(known)})")
   plain = [row for _, row in rows]
   return use, plain, (len(plain[0]), len(plain)), origin


DIFF_SAME = "·"   # 가운뎃점 — diff_text 에서 안 바뀐 칸


def diff_text(before: np.ndarray, after: np.ndarray, legend: Legend | None = None, box: Box | None = None) -> str:
   """두 RGBA 배열의 다른 칸만 글자로 (설계 5절). 안 바뀐 칸은 `·`, 바뀌어 투명이 된 칸은 `.`.

   글자는 `legend` 에서 받고(새 색이면 배정), 범례 줄은 바뀐 칸에 쓰인 색만 싣는다. 창 규칙은 `to_text` 와 같다.
   """
   for arr in (before, after):
      require_rgba(arr)
   if before.shape != after.shape:
      raise ArtToolError(f"두 그림 크기가 다르다 : {before.shape[:2]} · {after.shape[:2]}")
   if legend is None:
      legend = Legend()
   height, width = after.shape[:2]
   x0, y0, x1, y1 = _window(box, width, height)
   differ = (before != after).any(axis=2)

   used: set[str] = set()
   rows = []
   for y in range(y0, y1):
      chars = []
      for x in range(x0, x1):
         r, g, b, a = (int(v) for v in after[y, x])
         if not differ[y, x]:
            chars.append(DIFF_SAME)
         elif a == 0:
            chars.append(TRANSPARENT)
         else:
            letter = legend.assign((r, g, b))
            used.add(letter)
            chars.append(letter)
      rows.append("".join(chars))

   block = "\n".join(f"{letter} {to_hex(rgb)}" for letter, rgb in legend.letters().items() if letter in used)
   if not block:
      block = "# 범례 : 바뀐 색 없음"
   return block + "\n\n" + "\n".join(rows) + "\n"
