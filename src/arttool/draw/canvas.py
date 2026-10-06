"""`Canvas` — 겹 여럿을 같은 크기로 들고 겹마다 그려 겹 묶음으로 저장한다 (2026-10-04 개선 설계 6-5 · 10-4 길 ⓐ).

    c = Canvas(template="char_small", size=32)  # 템플릿 이름 · render 가 낸 폴더 · template.json · layers.json · 사전
    skin = c.pick("skin", 3)                      # 팔레트 램프에서 색 하나 (#RRGGBB)
    c["body"].round_box(10, 12, 22, 30, skin, r=2)
    c.outline("selout")                           # 합친 실루엣 둘레에, 칸마다 주인 겹으로
    c.report()                                    # 팔레트 밖 색 · 겹침 · 빈 겹 — 예외가 아니라 보고
    c.save("set/")                                # set/layers.json + set/<겹>/idle.png

규칙
- 반투명은 만들지 않는다. 알파가 255 가 아닌 색을 주면 거절한다(지우기는 `erase`).
- 좌표는 `shapes` 와 같다 : 칸 (x, y), 상자는 끝을 뺀 [x0, x1) × [y0, y1). 캔버스 밖은 조용히 잘린다.
- 팔레트 밖 색은 막지 않고 `report()` 가 알린다. 그려 보며 고르는 일을 끊지 않으려는 것이다.
"""

from __future__ import annotations

import numbers
import os
from pathlib import Path

import numpy as np

from .. import image, layerset, paths
from ..errors import ArtToolError
from ..jsonio import read_json
from ..palette import Ramps, load_ramps, parse_hex, to_hex
from . import shapes
from .guide import GUIDE_COLORS, Guide, guide as open_guide
from .outline import MODES, check_light, check_mode, plan

DEFAULT_ITEM = "idle"


def _rgba(color) -> tuple[int, int, int, int]:
   """색 → (R, G, B, 255). 반투명 · 투명 색은 거절한다."""
   if isinstance(color, str):
      return (*parse_hex(color), 255)
   if isinstance(color, (tuple, list, np.ndarray)) and len(color) in (3, 4):
      # 정수만 받는다 — 1.7 을 int 로 깎아 다른 색이 조용히 칠해지는 일을 막는다 (리뷰 R2-L4)
      if not all(isinstance(c, numbers.Integral) and not isinstance(c, bool) for c in color):
         raise ArtToolError(f"색 값은 0 ~ 255 정수다 : {color}")
      values = tuple(int(c) for c in color)
      if not all(0 <= v <= 255 for v in values):
         raise ArtToolError(f"색 값은 0 ~ 255 다 : {color}")
      if len(values) == 4 and values[3] != 255:
         raise ArtToolError(f"반투명 · 투명 색은 안 쓴다 (알파 {values[3]}). 지우려면 erase 를 부른다 : {color}")
      return values[0], values[1], values[2], 255
   raise ArtToolError(f"색은 #RRGGBB · (R, G, B) 중 하나다 : {color}")


def pick(ramps: Ramps, name: str, index: int) -> str:
   """램프 `name` 의 `index` 칸 색(#RRGGBB). 0 = 가장 어두운 칸, -1 = 가장 밝은 칸."""
   colors = ramps.ramp(name)
   if not -len(colors) <= index < len(colors):
      raise ArtToolError(f"램프 {name} 은 {len(colors)} 칸이다 (0 ~ {len(colors) - 1}) : {index}")
   return to_hex(colors[index])


class Layer:
   """겹 하나. 그리기 함수는 모두 자기 자신을 돌려줘 이어 부를 수 있다."""

   def __init__(self, name: str, kind: str, size: tuple[int, int]):
      self.name = name
      self.kind = kind
      self.size = size
      self.arr = image.new(size[0], size[1])

   def __repr__(self) -> str:
      return f"Layer({self.name!r}, kind={self.kind!r}, 칠한 칸 {int(self.mask().sum())})"

   # ---- 칠하기 바탕 ----

   def paint(self, mask: np.ndarray, color) -> "Layer":
      """마스크 칸을 한 색으로 덮는다. 다른 도형 함수가 모두 이것을 부른다."""
      shapes.paint(self.arr, mask, _rgba(color))
      return self

   def erase(self, mask: np.ndarray | None = None) -> "Layer":
      """마스크 칸을 투명으로. 마스크를 안 주면 겹 전체."""
      if mask is None:
         self.arr[:, :] = 0
      else:
         if mask.shape != self.arr.shape[:2]:
            raise ArtToolError(f"마스크 크기 {mask.shape[::-1]} 가 겹 {self.size} 와 다르다")
         self.arr[mask] = 0
      return self

   def mask(self) -> np.ndarray:
      """칠한 칸 (불리언)."""
      return self.arr[:, :, 3] > 0

   def px(self, x: int, y: int) -> str | None:
      """칸 하나의 색(#RRGGBB). 투명이거나 캔버스 밖이면 None (음수 칸이 반대쪽 끝을 읽지 않게)."""
      if not (0 <= x < self.size[0] and 0 <= y < self.size[1]):
         return None
      r, g, b, a = (int(v) for v in self.arr[y, x])
      return to_hex((r, g, b)) if a else None

   # ---- 도형 ----

   def dot(self, x: int, y: int, color, side: int = 1) -> "Layer":
      return self.paint(shapes.dot(self.size, x, y, side), color)

   def line(self, x0: int, y0: int, x1: int, y1: int, color) -> "Layer":
      """1칸 굵기 선. 두 끝 다 칠한다. 계단 길이가 고르게 나온다."""
      return self.paint(shapes.line(self.size, x0, y0, x1, y1), color)

   def box(self, x0: int, y0: int, x1: int, y1: int, color, filled: bool = True) -> "Layer":
      """네모 [x0, x1) × [y0, y1). filled=False 면 1칸 테두리만."""
      return self.paint(shapes.box(self.size, x0, y0, x1, y1, filled), color)

   def round_box(self, x0: int, y0: int, x1: int, y1: int, color, r: int = 1) -> "Layer":
      """모서리를 계단으로 r 만큼 깎은 네모."""
      return self.paint(shapes.round_box(self.size, x0, y0, x1, y1, r), color)

   def ellipse(self, x0: int, y0: int, x1: int, y1: int, color) -> "Layer":
      """상자 [x0, x1) × [y0, y1) 에 꼭 맞는 타원판."""
      return self.paint(shapes.ellipse(self.size, x0, y0, x1, y1), color)

   def disc(self, cx: float, cy: float, r: float, color) -> "Layer":
      """원판. 지름 16 칸을 채우려면 가운데 7.5 · r 8."""
      return self.paint(shapes.disc(self.size, cx, cy, r), color)

   def ring(self, cx: float, cy: float, r: float, color, width: int = 1, dash: int = 0) -> "Layer":
      return self.paint(shapes.ring(self.size, cx, cy, r, width, dash), color)

   def drop(self, x0: int, y0: int, x1: int, y1: int, color) -> "Layer":
      """물방울(끝이 위)을 상자 [x0, x1) × [y0, y1) 에."""
      return self.paint(shapes.drop(self.size, x0, y0, x1, y1), color)

   def fill(self, x: int, y: int, color) -> "Layer":
      """칠하기 통 : (x, y) 와 같은 색으로 4방향 이어진 칸을 덮는다(이 겹 안에서만)."""
      return self.paint(shapes.flood(self.arr, x, y), color)

   def mirror(self) -> "Layer":
      """왼쪽 반을 오른쪽 반에 거울로 옮긴다(좌우 대칭 그림). 홀수 너비면 가운데 줄은 그대로."""
      width = self.size[0]
      half = width // 2
      self.arr[:, width - half :] = self.arr[:, :half][:, ::-1]
      return self

   def recolor(self, old, new) -> "Layer":
      """이 겹의 old 색 칸을 모두 new 색으로."""
      o = _rgba(old)
      return self.paint((self.arr == o).all(axis=2), new)


def _layers_from(rows, where) -> list[layerset.Layer]:
   """`layers.json` 의 layers 줄 · 이름 목록 · (이름, kind) 목록 → 검증된 겹 목록."""
   parsed = []
   for row in rows:
      if isinstance(row, str):
         if row not in layerset.KINDS:
            raise ArtToolError(f"겹 이름 {row!r} 은 kind 낱말이 아니다. {{'name': {row!r}, 'kind': …}} 로 준다 (kind : {' · '.join(layerset.KINDS)})")
         row = {"name": row, "kind": row}
      elif isinstance(row, (tuple, list)) and len(row) == 2:
         row = {"name": row[0], "kind": row[1]}
      parsed.append(row)
   # 꼴 검증은 겹 묶음 약속 한 곳(layerset)에 맡긴다.
   return layerset.from_dict({"version": layerset.VERSION, "canvas": [1, 1], "layers": parsed}, where).layers


def _size_text(size) -> str | None:
   if size is None:
      return None
   if isinstance(size, numbers.Integral) and not isinstance(size, bool):
      return f"{size}x{size}"
   if isinstance(size, (tuple, list)) and len(size) == 2:
      return f"{size[0]}x{size[1]}"
   raise ArtToolError(f"캔버스 크기는 양의 정수 (너비, 높이) 다 : {size}")


def _from_name(name: str, size, preset: str | None, profile) -> tuple[None, dict, Guide, str]:
   """템플릿 이름으로 바로 연다. `template show` 와 같은 셈(`template.run.build`)을 부르고 파일은 안 쓴다."""
   # 늦게 부른다 : template 이 draw.shapes 를 읽어 맨 위에서 부르면 서로 물린다.
   from ..profile import load_profile
   from ..template import guide as template_guide
   from ..template import run as template_run

   prof = load_profile(profile) if profile else None
   shown, _warnings, made = template_run.build(name, _size_text(size), preset, prof)
   png = template_guide.paint(made["kind"].guide(made["ctx"], made["calc"]))
   where = f"템플릿 {name}"
   return None, shown, Guide(shown, png, where), where


def _read_source(template, size=None, preset: str | None = None, profile=None) -> tuple[dict | None, dict | None, Guide | None, str]:
   """template 인자 → (layers.json 사전, template 사전, 가이드, 어디서)."""
   if isinstance(template, dict):
      if "canvas" in template and "version" in template and "layers" in template and "check" not in template:
         return template, None, None, "(사전)"
      return None, template, open_guide(template), "(사전)"
   path = Path(template)
   if path.is_dir():
      lay = layerset.read_data(path / layerset.FILE_NAME) if (path / layerset.FILE_NAME).is_file() else None
      tpl_file = path / "template.json"
      tpl = read_json(tpl_file) if tpl_file.is_file() else None
      if lay is None and tpl is None:
         raise ArtToolError(f"폴더에 layers.json · template.json 이 없다 : {path}")
      return lay, tpl, (open_guide(path) if tpl is not None else None), str(path)
   if path.is_file():
      data = layerset.read_data(path)
      if path.name == layerset.FILE_NAME:
         tpl_file = path.parent / "template.json"
         tpl = read_json(tpl_file) if tpl_file.is_file() else None
         return data, tpl, (open_guide(tpl_file) if tpl is not None else None), str(path)
      return None, data, open_guide(path), str(path)
   if isinstance(template, str) and path.suffix == "" and len(path.parts) == 1:
      # 템플릿 이름(예 "char_small") — templates/<이름>.json 을 크기에 맞춰 셈한다
      return _from_name(template, size, preset, profile)
   raise ArtToolError(
      f"템플릿을 못 찾았다 : {template}. 템플릿 이름(templates/ 아래) · `arttool template render` 로 뽑은 "
      "폴더 · template.json · layers.json 경로나 사전을 준다"
   )


class Canvas:
   """같은 크기 겹 여럿. `c["body"]` 로 겹을 꺼내 그린다.

   size     : 정수 하나(정사각) 또는 (너비, 높이). 템플릿에 크기가 있으면 안 줘도 된다.
   template : 템플릿 이름(예 "char_small", 파일을 안 쓰고 바로 셈) · `template render` 출력 폴더 · `template.json` ·
              `layers.json` 경로 또는 사전. 겹 목록 · 가이드 · 화풍을 읽는다.
   layers   : 템플릿 없이 겹을 정할 때. 이름 목록(이름이 kind 낱말일 때) · (이름, kind) 목록 · layers.json 꼴 줄 목록.
              둘 다 없으면 `body` 한 겹.
   ramps    : 팔레트 램프 파일 경로 또는 `Ramps`. 없으면 template.json 의 `check.palette.ramps_file` 을 쓴다.
   light    : 빛 방향 top_left · top · top_right. 없으면 템플릿 화풍, 그것도 없으면 top_left.
   preset · profile : 템플릿을 이름으로 열 때만 쓴다 (`template show` 의 `--preset` · `--profile` 과 같다).
   """

   def __init__(self, size=None, *, template=None, layers=None, ramps=None, light: str | None = None,
                preset: str | None = None, profile=None):
      lay_data = tpl_data = None
      self.warnings: list[dict] = []   # 그리기를 막지 않는 알림(예: template.ramps_outside)
      self.guide: Guide | None = None
      self.template_name: str | None = None
      self.meta: dict | None = None   # layers.json 맨 위 meta — 다시 쓸 때 잃지 않게 들고 있는다
      where = "(인자)"
      if template is not None:
         lay_data, tpl_data, self.guide, where = _read_source(template, size, preset, profile)

      self.size = self._pick_size(size, lay_data, tpl_data, where)
      if layers is not None:
         rows = _layers_from(layers, where)
      elif lay_data is not None:
         parsed = layerset.from_dict(lay_data, where)
         rows = parsed.layers
         self.meta = parsed.meta
      elif tpl_data is not None and isinstance(tpl_data.get("layers"), list) and tpl_data["layers"]:
         rows = _layers_from(tpl_data["layers"], where)
      else:
         rows = _layers_from(["body"], where)
      self.spec = rows
      self._picks: dict[str, dict[str, str]] = {}   # open 으로 연 사전 꼴 그림의 pick — 새 폴더에 save 해도 잇는다
      self._layers ={row.name: Layer(row.name, row.kind, self.size) for row in rows}

      if lay_data is not None and isinstance(lay_data.get("template"), str):
         self.template_name = lay_data["template"]
      elif tpl_data is not None and isinstance(tpl_data.get("name"), str):
         self.template_name = tpl_data["name"]

      if isinstance(ramps, Ramps):
         self.ramps: Ramps | None = ramps
      elif ramps is not None:
         self.ramps = load_ramps(ramps)
      elif self.guide is not None and self.guide.ramps_file:
         # template.json 의 절대경로는 믿지 않는다. 뿌리(툴 폴더 · 프로필 폴더 · ARTTOOL_PALETTES) 밖이면 경고만 남긴다.
         from ..profile import load_profile, tool_home
         prof = load_profile(profile) if profile else None
         roots = prof.palette_roots(self.warnings) if prof is not None else [paths.resolve_root(tool_home()), paths.gathered_palettes_root(self.warnings)]
         trusted = paths.trusted_ramps(self.guide.ramps_file, roots, self.warnings)
         back = prof.ramps_path() if trusted is None and prof is not None else None
         self.ramps = load_ramps(trusted or back) if (trusted or (back is not None and back.is_file())) else None
      else:
         self.ramps = None

      style = self.guide.style if self.guide is not None else {}
      self.light = light or style.get("light") or "top_left"
      check_light(self.light)
      # 화풍의 외곽선 방식. unset 이면 None — outline() 에 방식을 직접 줘야 한다.
      mode = style.get("outline")
      self.outline_mode: str | None = mode if mode in MODES else None
      self._outlined: list[dict] = []     # outline() 부른 기록 — 두 번 두르면 report 가 알린다
      self._notes: list[dict] = []        # 외곽선이 남긴 알릴 일 (램프 맨 아래 등)
      self._folders: list[Path] = []      # 이 캔버스가 읽고 쓴 겹 묶음 폴더 — preview 가 그 안에 쓰지 않게

   @staticmethod
   def _pick_size(size, lay_data, tpl_data, where) -> tuple[int, int]:
      found = None
      if lay_data is not None:
         found = tuple(lay_data.get("canvas") or ()) or None
      if found is None and tpl_data is not None:
         for key in ("size", "canvas"):
            value = tpl_data.get(key)
            if isinstance(value, (list, tuple)) and len(value) == 2:
               found = tuple(value)
               break
      if size is None:
         if found is None:
            raise ArtToolError(f"캔버스 크기를 모른다. size 를 준다 (예 : Canvas(32)) - {where}")
         wanted = found
      else:
         wanted = (size, size) if isinstance(size, numbers.Integral) else tuple(size)
      if len(wanted) != 2 or not all(isinstance(v, numbers.Integral) and not isinstance(v, bool) and v > 0 for v in wanted):
         raise ArtToolError(f"캔버스 크기는 양의 정수 (너비, 높이) 다 : {size}")
      if found is not None and tuple(found) != tuple(wanted):
         raise ArtToolError(f"준 크기 {wanted} 가 템플릿 크기 {tuple(found)} 와 다르다 - {where}")
      image.check_pixels(wanted[0], wanted[1], "캔버스")
      return int(wanted[0]), int(wanted[1])

   # ---- 겹 ----

   @property
   def names(self) -> list[str]:
      """겹 이름, 쌓는 순서(아래 → 위)."""
      return [row.name for row in self.spec]

   def layer(self, name: str) -> Layer:
      if name not in self._layers:
         raise ArtToolError(f"없는 겹 : {name}. 있는 겹 : {', '.join(self.names)}")
      return self._layers[name]

   __getitem__ = layer

   # ---- 색 ----

   def pick(self, ramp: str, index: int) -> str:
      """팔레트 램프 `ramp` 의 `index` 칸 색. 0 = 가장 어두운 칸, -1 = 가장 밝은 칸."""
      if self.ramps is None:
         raise ArtToolError("팔레트가 없다. Canvas(ramps=\"palettes/<이름>.json\") 로 준다")
      return pick(self.ramps, ramp, index)

   # ---- 외곽선 ----

   def outline(self, mode: str | None = None, *, layers: list[str] | None = None, where: str = "outside",
               color=None, width: int = 1) -> "Canvas":
      """고른 겹(기본 전부)을 합친 실루엣 둘레에 외곽선을 두른다.

      외곽선 칸마다 그 색을 정한 칠한 칸의 **주인 겹**(그 칸에서 맨 위에 보이는 겹)에 넣는다 —
      머리카락 둘레선은 hair 겹에 들어가, 겹을 끄면 그 둘레선도 같이 꺼진다.
      mode 를 안 주면 템플릿 화풍의 외곽선 방식을 쓴다. solid 는 color 를, 2px 선은 width=2 를 준다.
      layers 로 일부 겹만 고르면, 고르지 않은 겹이 칠한 칸에는 바깥 외곽선을 넣지 않는다(남의 그림을 덮지 않게).
      같은 겹에 두 번 두르면 선이 두 겹이 된다 — report() 가 알린다.
      """
      mode = mode or self.outline_mode
      if mode is None:
         raise ArtToolError(f"외곽선 방식을 준다 : {' · '.join(MODES)} (템플릿 화풍이 unset 이다)")
      check_mode(mode)
      picked = layers or self.names
      for name in picked:
         self.layer(name)
      merged = self.merged(only=picked)
      owner = self._owner_map(picked)
      others = np.zeros((self.size[1], self.size[0]), dtype=bool)
      for name in self.names:
         if name not in picked:
            others |= self._layers[name].mask()
      self._outlined.append({"layers": list(picked), "where": where, "mode": mode})
      for x, y, rgb, (ax, ay) in plan(merged, mode, ramps=self.ramps, light=self.light, where=where,
                                      color=color, width=width, notes=self._notes):
         if where == "outside" and others[y, x]:
            continue
         self._layers[owner[ay][ax]].arr[y, x] = (*rgb, 255)
      return self

   def _owner_map(self, picked: list[str]) -> list[list[str | None]]:
      height = self.size[1]
      owner: list[list[str | None]] = [[None] * self.size[0] for _ in range(height)]
      for name in self.names:
         if name not in picked:
            continue
         ys, xs = np.nonzero(self._layers[name].mask())
         for y, x in zip(ys.tolist(), xs.tolist()):
            owner[y][x] = name
      return owner

   # ---- 보기 ----

   def merged(self, only: list[str] | None = None) -> image.RGBA:
      """겹을 아래부터 쌓은 한 장. 알파가 0 · 255 뿐이라 위 겹의 칠한 칸이 그대로 덮는다."""
      out = image.new(self.size[0], self.size[1])
      for name in self.names:
         if only is not None and name not in only:
            continue
         arr = self._layers[name].arr
         solid = arr[:, :, 3] > 0
         out[solid] = arr[solid]
      return out

   def preview(self, path: str | os.PathLike, scale: int = 8, only: list[str] | None = None) -> Path:
      """합친 그림을 scale 배(nearest)로 키워 PNG 로 쓴다. 눈으로 볼 때."""
      if not isinstance(scale, int) or scale < 1:
         raise ArtToolError(f"배율은 1 이상 정수다 : {scale}")
      file = Path(path)
      # 겹 묶음 폴더 안에 쓰면 겹 그림 · layers.json 을 덮거나 묶음에 낯선 파일이 섞인다 (리뷰 R2-L8)
      paths.guard_outside([file], self._folders, what="preview 경로")
      image.save(file, image.scale_up(self.merged(only), scale))
      return file

   # ---- 보고 ----

   def report(self) -> dict:
      """그린 것을 훑어 경고를 모은다. 예외를 내지 않는다.

      rule : `palette`(팔레트 밖 색, 팔레트가 있을 때만) · `guide_color`(가이드 색 #FF00FF · #00FFFF · #FFFF00 이 섞임) ·
      `exclusive`(exclusive_with 짝이 같은 칸을 칠함) · `empty`(optional 아닌 빈 겹).
      """
      warnings = []
      allowed = self.ramps.colors() if self.ramps is not None else None
      strays, guides = [], []
      for name in self.names:
         arr = self._layers[name].arr
         solid = arr[:, :, 3] > 0
         colors, counts = np.unique(arr[solid][:, :3], axis=0, return_counts=True) if solid.any() else ([], [])
         for rgb, count in zip(colors, counts):
            rgb = tuple(int(v) for v in rgb)
            row = {"layer": name, "color": to_hex(rgb), "count": int(count)}
            if allowed is not None and rgb not in allowed:
               strays.append(row)
            if rgb in GUIDE_COLORS:
               guides.append(row)
      if strays:
         warnings.append({"rule": "palette", "ok": False, "detail": f"팔레트 {self.ramps.name} 밖 색 {len({r['color'] for r in strays})}가지", "items": strays})
      if guides:
         warnings.append({"rule": "guide_color", "ok": False, "detail": "가이드 색이 그림에 섞였다", "items": guides})
      # 그리기 함수는 반투명을 안 만든다. 반투명은 open() 으로 연 남의 그림 · arr 을 직접 고친 경우에만 생긴다.
      soft = []
      for name in self.names:
         alpha = self._layers[name].arr[:, :, 3]
         count = int(((alpha > 0) & (alpha < 255)).sum())
         if count:
            soft.append({"layer": name, "count": count})
      if soft:
         warnings.append({"rule": "alpha", "ok": False, "detail": "반투명 칸이 있다", "items": soft})

      lay = layerset.LayerSet(self.size, list(self.spec))
      overlaps = []
      for a, b in lay.exclusive_pairs():
         both = self._layers[a].mask() & self._layers[b].mask()
         if both.any():
            ys, xs = np.nonzero(both)
            overlaps.append({"layers": [a, b], "count": int(both.sum()), "first": [int(xs[0]), int(ys[0])]})
      if overlaps:
         warnings.append({"rule": "exclusive", "ok": False, "detail": "같은 칸을 칠하면 안 되는 겹이 겹쳤다", "items": overlaps})

      twice = []
      for i, a in enumerate(self._outlined):
         for b in self._outlined[i + 1 :]:
            shared = sorted(set(a["layers"]) & set(b["layers"]))
            if shared and a["where"] == b["where"]:
               twice.append({"layers": shared, "where": a["where"]})
      if twice:
         warnings.append({"rule": "outline_twice", "ok": False, "detail": "같은 겹에 외곽선을 두 번 둘렀다 — 선이 두 겹(2px)이 된다. 두꺼운 선은 outline(width=2)",
                          "items": twice})
      for note in self._notes:
         warnings.append({"rule": note["rule"], "ok": False, "detail": note["detail"], "items": [{"count": note["count"]}]})

      empty = [row.name for row in self.spec if not row.optional and not self._layers[row.name].mask().any()]
      if empty:
         warnings.append({"rule": "empty", "ok": False, "detail": "빈 겹", "items": empty})

      return {
         "status": "warn" if warnings else "ok",
         "canvas": list(self.size),
         "layers": {name: int(self._layers[name].mask().sum()) for name in self.names},
         "palette": self.ramps.name if self.ramps is not None else None,
         "warnings": warnings,
      }

   # ---- 저장 · 열기 ----

   def save(self, folder: str | os.PathLike, item: str = DEFAULT_ITEM) -> Path:
      """겹 묶음 꼴로 쓴다 : `<folder>/layers.json` + `<folder>/<겹>/<item>.png` (빈 겹도 투명 그림으로).

      폴더에 layers.json 이 이미 있으면 겹 목록 · 크기가 같을 때만 item 을 더한다(걷기 프레임을 한 묶음에 모을 때).
      돌려주는 값은 layers.json 경로.
      """
      root = Path(folder)
      items = [item]
      old = None
      existing = root / layerset.FILE_NAME
      if existing.is_file():
         old = layerset.load(existing)
         if old.canvas != self.size or [layer.to_dict() for layer in old.layers] != [row.to_dict() for row in self.spec]:
            raise ArtToolError(f"폴더의 layers.json 과 겹 목록 · 크기가 다르다. 다른 폴더에 쓴다 : {existing}")
         items = old.items + ([item] if item not in old.items else [])
      # 사전 꼴 그림이면 그 pick 을 잇는다 : 있는 폴더는 그 폴더의 pick, 새 폴더는 open 때 읽은 pick
      pick = old.picks.get(item) if old is not None and item in old.items else self._picks.get(item)
      picks = {item: dict(pick)} if pick is not None else {}
      lay = layerset.carry_meta(old, layerset.LayerSet(self.size, list(self.spec), items, self.template_name, self.meta, picks))
      # pick 에 없는 겹은 이 그림에 없다. 그 겹에 그린 게 있으면 조용히 버리지 않고 거절한다.
      for name in self.names:
         if layerset.image_path(root, lay, name, item) is None and self._layers[name].arr[..., 3].any():
            raise ArtToolError(f"그림 {item} 의 pick 에 겹 {name} 이 없는데 그 겹에 그린 칸이 있다 - {root}")
      # 작은 겹은 상자로 잘라 쓴다. 상자 밖에 칸이 있으면 crop_to_box 가 거절한다 —
      # 한 장이라도 쓰기 전에 다 잘라 봐서, 거절될 때 반쯤 쓴 묶음을 남기지 않는다.
      cut = {name: layerset.crop_to_box(lay.layer(name), self._layers[name].arr, root) for name in self.names}
      self._folders.append(root)
      for name in self.names:
         path = layerset.image_path(root, lay, name, item)
         if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)   # files 무늬는 겹 폴더가 아닐 수 있다
            image.save(path, cut[name])
      return layerset.save(root, lay)

   @classmethod
   def open(cls, folder: str | os.PathLike, item: str = DEFAULT_ITEM, *, ramps=None, light: str | None = None) -> "Canvas":
      """저장한 겹 묶음을 다시 연다(이어 그리기). 파일이 없는 겹은 빈 겹으로."""
      root = Path(folder)
      canvas = cls(template=root / layerset.FILE_NAME, ramps=ramps, light=light)
      lay = layerset.load(root)
      on_disk = any((p := layerset.image_path(root, lay, row.name, item)) is not None and p.is_file() for row in lay.layers)
      if item not in lay.items and not on_disk:
         # 없는 그림을 빈 겹으로 열면 「이어 그리기」가 조용히 백지에서 시작한다 (리뷰 R2-L2)
         raise ArtToolError(f"겹 묶음에 그림 {item!r} 이 없다. 있는 그림 : {', '.join(lay.items) or '없음'} - {root}")
      canvas._folders.append(root)
      if item in lay.picks:
         canvas._picks[item] = dict(lay.picks[item])
      for name, arr in layerset.read_item(root, lay, item).items():
         canvas._layers[name].arr = arr.copy()
      return canvas
