"""템플릿 가이드 읽기 — 가이드 줄 · 점 · 상자 좌표를 이름으로 꺼낸다 (2026-10-04 개선 설계 6-5 · 8-3).

`template render` 가 낸 폴더(또는 그 안의 `template.json` · 사전)를 받는다.

    g = guide("work/guide/")
    g.y("eye")            # 눈 줄 y
    g.box("head")         # 머리 상자 (x0, y0, x1, y1), 끝 뺌
    g.rows                # 가이드 PNG 의 가로선 y 목록 (JSON 에 이름이 없을 때)

이름 있는 좌표는 JSON 에서 읽는다. `template render` 의 `template.json` 은 셈 결과를 `lines` 칸에 둔다 —
정수는 줄(`top_y` · `baseline_y` · `eye_line_y` …), 네 정수 목록은 상자(`head` · `eye_box_l` · `torso` …)로 읽는다.
줄은 끝말을 뗀 이름으로도 꺼낸다 : `eye_line_y` = `eye_line` = `eye`, `baseline_y` = `baseline`.
그 밖에 맨 위 · `guide` · `guides` · `values` 아래의 `lines` · `points`(이름 → [x, y]) · `boxes`(이름 → [x0, y0, x1, y1])와
`values` 바로 아래의 `<이름>_y` · `<이름>_x` 정수도 읽는다(손으로 쓴 사전용).
이름 없는 좌표는 `<이름>_guide.png` 에서 색으로 읽는다(선 #FF00FF · 점 #00FFFF · 지키는 자리 #FFFF00, 설계 8-3).
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np

from .. import image
from ..errors import ArtToolError
from ..jsonio import read_json

LINE_COLOR = (255, 0, 255)
DOT_COLOR = (0, 255, 255)
KEEP_COLOR = (255, 255, 0)
GUIDE_COLORS = (LINE_COLOR, DOT_COLOR, KEEP_COLOR)

_HOLDERS = ("guide", "guides", "values")


def _ints(value, count: int) -> tuple[int, ...] | None:
   if isinstance(value, (list, tuple)) and len(value) == count and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value):
      return tuple(int(v) for v in value)
   return None


def _table(node: dict, key: str) -> list:
   value = node.get(key)
   return list(value.items()) if isinstance(value, dict) else []


def _number(value) -> int | None:
   if isinstance(value, (int, float)) and not isinstance(value, bool):
      return int(value)
   return None


class Guide:
   """가이드 좌표 묶음. 없는 이름을 물으면 있는 이름을 같이 알려 준다."""

   def __init__(self, data: dict | None = None, png: image.RGBA | None = None, where: str = "(사전)"):
      self.data = data or {}
      self.where = where
      self.lines: dict[str, int] = {}
      self.points: dict[str, tuple[int, int]] = {}
      self.boxes: dict[str, tuple[int, int, int, int]] = {}
      self._collect()
      self.rows: list[int] = []
      self.cols: list[int] = []
      self.dots: list[tuple[int, int]] = []
      self.keep: np.ndarray | None = None
      if png is not None:
         self._read_png(png)

   # ---- JSON ----

   def _collect(self) -> None:
      nodes = [self.data] + [self.data[k] for k in _HOLDERS if isinstance(self.data.get(k), dict)]
      for node in nodes:
         for name, value in _table(node, "lines"):
            if _number(value) is not None:
               self.lines[name] = _number(value)
               self._alias(name, _number(value))
            elif _ints(value, 4):
               # template render 의 `lines` 칸은 셈 결과 전부라 상자([x0, y0, x1, y1])도 같이 있다 (예 head · eye_box_l)
               self.boxes.setdefault(name, _ints(value, 4))
         for name, value in _table(node, "points"):
            if _ints(value, 2):
               self.points[name] = _ints(value, 2)
         for name, value in _table(node, "boxes"):
            if _ints(value, 4):
               self.boxes[name] = _ints(value, 4)
      values = self.data.get("values")
      if isinstance(values, dict):
         for key, value in values.items():
            if (key.endswith("_y") or key.endswith("_x")) and _number(value) is not None:
               self.lines.setdefault(key[:-2], _number(value))

   def _alias(self, name: str, value: int) -> None:
      """`eye_line_y` → `eye_line` · `eye`, `baseline_y` → `baseline` 처럼 끝말을 뗀 이름도 둔다(이미 있으면 안 덮는다)."""
      for tail in ("_line_y", "_line_x", "_y", "_x"):
         if name.endswith(tail) and len(name) > len(tail):
            self.lines.setdefault(name[: -len(tail)], value)

   @property
   def size(self) -> tuple[int, int] | None:
      """고른 크기 (너비, 높이). `size` · `canvas` 칸에서 읽는다."""
      for key in ("size", "canvas"):
         got = _ints(self.data.get(key), 2)
         if got:
            return got
      return None

   @property
   def style(self) -> dict:
      """template.json 의 `check.style` (외곽선 방식 · 빛 방향)."""
      check = self.data.get("check")
      style = check.get("style") if isinstance(check, dict) else None
      return dict(style) if isinstance(style, dict) else {}

   @property
   def ramps_file(self) -> str | None:
      """template.json 의 `check.palette.ramps_file` (화풍이 입혀졌을 때만, 설계 9-4 ⓓ)."""
      check = self.data.get("check")
      pal = check.get("palette") if isinstance(check, dict) else None
      value = pal.get("ramps_file") if isinstance(pal, dict) else None
      return value if isinstance(value, str) and value else None

   def _missing(self, what: str, name: str, have) -> ArtToolError:
      shown = ", ".join(sorted(have)) or "(없음)"
      return ArtToolError(f"가이드에 {what} {name!r} 이 없다. 있는 것 : {shown} - {self.where}")

   def y(self, name: str) -> int:
      """이름 있는 가로 줄의 y."""
      if name not in self.lines:
         raise self._missing("줄", name, self.lines)
      return self.lines[name]

   x = y  # 세로 줄도 같은 표에 있다. 읽는 쪽 글이 자연스럽게 두 이름을 둔다.

   def point(self, name: str) -> tuple[int, int]:
      if name not in self.points:
         raise self._missing("점", name, self.points)
      return self.points[name]

   def box(self, name: str) -> tuple[int, int, int, int]:
      """(x0, y0, x1, y1), 끝 뺌 — `Layer.box` 에 그대로 넣는다."""
      if name not in self.boxes:
         raise self._missing("상자", name, self.boxes)
      return self.boxes[name]

   def names(self) -> dict[str, list[str]]:
      return {"lines": sorted(self.lines), "points": sorted(self.points), "boxes": sorted(self.boxes)}

   # ---- 가이드 PNG ----

   def _read_png(self, arr: image.RGBA) -> None:
      solid = arr[:, :, 3] > 0
      rgb = arr[:, :, :3]
      line = solid & (rgb == LINE_COLOR).all(axis=2)
      h, w = line.shape
      # 줄의 반 넘게 선 색이면 가로선(세로선)으로 본다.
      self.rows = [int(y) for y in np.nonzero(line.sum(axis=1) * 2 > w)[0]]
      self.cols = [int(x) for x in np.nonzero(line.sum(axis=0) * 2 > h)[0]]
      dot = solid & (rgb == DOT_COLOR).all(axis=2)
      self.dots = [(int(x), int(y)) for y, x in zip(*np.nonzero(dot))]
      self.keep = solid & (rgb == KEEP_COLOR).all(axis=2)


def _find_png(folder: Path, data: dict) -> Path | None:
   name = data.get("name")
   if isinstance(name, str):
      exact = folder / f"{name}_guide.png"
      if exact.is_file():
         return exact
   found = sorted(folder.glob("*_guide.png"))
   return found[0] if len(found) == 1 else None


def guide(source: str | os.PathLike | dict, png: str | os.PathLike | None = None) -> Guide:
   """가이드를 연다. `source` = render 출력 폴더 · `template.json` 경로 · 그 사전.

   폴더나 파일을 주면 같은 폴더의 `<이름>_guide.png` 도 찾아 읽는다(하나뿐일 때). `png` 로 따로 줘도 된다.
   """
   if isinstance(source, dict):
      data, folder, where = source, None, "(사전)"
   else:
      path = Path(source)
      file = path / "template.json" if path.is_dir() else path
      if not file.is_file():
         raise ArtToolError(f"가이드 파일이 없다 : {file} (template render 의 --out 폴더나 template.json 을 준다)")
      data, folder, where = read_json(file), file.parent, str(file)
      if not isinstance(data, dict):
         raise ArtToolError(f"가이드 파일 맨 위는 사전이다 : {file}")
   png_path = Path(png) if png is not None else (_find_png(folder, data) if folder else None)
   arr = image.load(png_path) if png_path is not None else None
   return Guide(data, arr, where)
