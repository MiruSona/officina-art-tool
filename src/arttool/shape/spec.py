"""도형 명세 JSON 읽기 · 검사 · 묶음 풀기 (도형 렌더러 설계 2절).

읽은 결과는 `Spec` 하나다. 잘못된 칸은 어느 칸이 왜 틀렸는지 한 줄로 `ArtToolError` 를 낸다.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..errors import ArtToolError
from ..jsonio import read_json
from ..palette import RGB, parse_hex, shade
from .pattern import AXES as PATTERN_AXES, KINDS as PATTERN_KINDS, Pattern
from .sdf import KINDS, OPS, Prim, lathe_polygon, rotation
from .kit import assemble
from .template import expand, is_template_spec

VERSION = 1
VIEWS = {"front": 0.0, "left": -90.0, "back": 180.0, "right": 90.0}
LIGHT_WORDS = {"top_left": (-1.0, 1.0, 1.0), "top": (0.0, 1.0, 1.0), "top_right": (1.0, 1.0, 1.0)}
OUTLINE_MODES = ("none", "black", "solid", "selout", "selout+light")
STAMP_MODES = ("card",)
BAND_MODES = ("min", "set")
SIZE_MAX = 512


@dataclass
class Material:
   name: str
   ramp: list[RGB]
   ambient: float = 0.3
   rim_below: float | None = None
   rim_index: int = 0
   highlight: RGB | None = None
   highlight_above: float = 0.95
   line: RGB | None = None          # 이 재질 둘레 선(바깥 외곽선 · 안쪽 선) 색. 없으면 전체 outline 규칙
   line_light: RGB | None = None    # 빛 쪽(왼쪽 · 위) 둘레 선 색. 없으면 line
   patterns: list[Pattern] = field(default_factory=list)
   level: int | None = None         # 납작 칠 : 빛을 안 보고 늘 이 램프 단 (띠 그늘 · 무늬는 그 위에)
   bands: list[tuple[tuple[int, int], int, str]] = field(default_factory=list)   # ((dx, dy), 램프 단, min 상한 | set 그 단으로)


@dataclass
class Stamp:
   on: str
   at: tuple[float, float]
   yaw: float
   grid: list[str]
   legend: dict[str, RGB]
   hide_below: float = 0.15
   depth_tol: float = 4.0
   copies: list[tuple[int, int]] = field(default_factory=lambda: [(0, 0)])   # 같은 격자를 (dx, dy) 칸 옮겨 또 찍기

   @property
   def size(self) -> tuple[int, int]:
      return len(self.grid[0]), len(self.grid)


@dataclass
class Spec:
   size: tuple[int, int]
   origin: tuple[float, float]
   light: np.ndarray
   light_word: str
   outline_mode: str
   outline_color: RGB | None
   outline_width: int
   inner_gap: float | None
   max_colors: int | None
   dither: float
   views: dict[str, float]
   materials: dict[str, Material]
   prims: list[Prim]
   stamps: list[Stamp] = field(default_factory=list)
   inner_width: int = 1     # 안쪽 선 두께 (앞 물체 안쪽으로 몇 칸)


def _where(path: str, msg: str) -> ArtToolError:
   return ArtToolError(f"명세 {path} : {msg}")


def _number(value, path: str, low=-math.inf, high=math.inf) -> float:
   if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
      raise _where(path, f"수가 아니다 : {value!r}")
   if not low <= value <= high:
      raise _where(path, f"{low} ~ {high} 밖이다 : {value}")
   return float(value)


def _vec(value, n: int, path: str, low=-math.inf, high=math.inf) -> list[float]:
   if not isinstance(value, (list, tuple)) or len(value) != n:
      raise _where(path, f"수 {n} 개 목록이어야 한다 : {value!r}")
   return [_number(v, f"{path}[{i}]", low, high) for i, v in enumerate(value)]


def _color(value, path: str) -> RGB:
   if not isinstance(value, str):
      raise _where(path, f"색은 #RRGGBB 다 : {value!r}")
   try:
      return parse_hex(value)
   except ArtToolError as exc:
      raise _where(path, str(exc)) from None


def _material(name: str, data, path: str) -> Material:
   if not isinstance(data, dict):
      raise _where(path, "재질은 사전이다")
   if "ramp" in data:
      if not isinstance(data["ramp"], list) or not data["ramp"]:
         raise _where(f"{path}.ramp", "색 목록(어두운 쪽 → 밝은 쪽)이어야 한다")
      ramp = [_color(c, f"{path}.ramp[{i}]") for i, c in enumerate(data["ramp"])]
   elif "color" in data:
      steps = data.get("steps", 4)
      if isinstance(steps, bool) or not isinstance(steps, int) or not 2 <= steps <= 8:
         raise _where(f"{path}.steps", f"2 ~ 8 정수다 : {steps!r}")
      ramp = shade(_color(data["color"], f"{path}.color"), steps)
   else:
      raise _where(path, "ramp 또는 color 가 있어야 한다")
   out = Material(name, ramp, ambient=_number(data.get("ambient", 0.3), f"{path}.ambient", 0.0, 1.0))
   if "level" in data:
      out.level = _int(data["level"], f"{path}.level", 0, len(ramp) - 1)
   rim = data.get("rim")
   if rim is not None:
      if not isinstance(rim, dict):
         raise _where(f"{path}.rim", "사전이다 {below, index}")
      out.rim_below = _number(rim.get("below", 0.3), f"{path}.rim.below", 0.0, 1.0)
      index = rim.get("index", 0)
      if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(ramp):
         raise _where(f"{path}.rim.index", f"램프 칸 번호 0 ~ {len(ramp) - 1} 이다 : {index!r}")
      out.rim_index = index
   high = data.get("highlight")
   if high is not None:
      if not isinstance(high, dict):
         raise _where(f"{path}.highlight", "사전이다 {color, above}")
      out.highlight = _color(high.get("color"), f"{path}.highlight.color")
      out.highlight_above = _number(high.get("above", 0.95), f"{path}.highlight.above", 0.0, 1.0)
   line = data.get("line")
   if line is not None:
      if not isinstance(line, dict):
         raise _where(f"{path}.line", "사전이다 {color, light}")
      out.line = _color(line.get("color"), f"{path}.line.color")
      out.line_light = _color(line["light"], f"{path}.line.light") if "light" in line else out.line
   bands = data.get("bands") or []
   if not isinstance(bands, list):
      raise _where(f"{path}.bands", "[{offset: [dx, dy], level}] 목록이다")
   for i, band in enumerate(bands):
      here = f"{path}.bands[{i}]"
      if not isinstance(band, dict):
         raise _where(here, "사전이다 {offset, level}")
      off = band.get("offset")
      if not isinstance(off, list) or len(off) != 2 or not all(isinstance(v, int) and not isinstance(v, bool) for v in off):
         raise _where(f"{here}.offset", f"정수 [dx, dy] 다 : {off!r}")
      mode = band.get("mode", "min")
      if mode not in BAND_MODES:
         raise _where(f"{here}.mode", f"{' · '.join(BAND_MODES)} 중 하나다 : {mode!r}")
      out.bands.append(((off[0], off[1]), _int(band.get("level", 0), f"{here}.level", 0, len(ramp) - 1), mode))
   pats = data.get("pattern") or []
   if isinstance(pats, dict):
      pats = [pats]
   if not isinstance(pats, list):
      raise _where(f"{path}.pattern", "무늬 사전 또는 그 목록이다")
   out.patterns = [_pattern(p, f"{path}.pattern[{i}]", len(ramp)) for i, p in enumerate(pats)]
   return out


def _int(value, path: str, low: int, high: int) -> int:
   if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
      raise _where(path, f"{low} ~ {high} 정수다 : {value!r}")
   return value


def _pattern(data, path: str, ramp_len: int) -> Pattern:
   if not isinstance(data, dict):
      raise _where(path, "무늬는 사전이다")
   kind = data.get("kind")
   if kind not in PATTERN_KINDS:
      raise _where(f"{path}.kind", f"{' · '.join(PATTERN_KINDS)} 중 하나다 : {kind!r}")
   if "color" in data and "darken" in data or (kind != "strokes" and "color" not in data and "darken" not in data):
      raise _where(path, "color 또는 darken 중 하나만 준다 (strokes 는 둘 다 없어도 된다)")
   out = Pattern(kind)
   if "color" in data:
      out.color = _color(data["color"], f"{path}.color")
   elif "darken" in data:
      out.darken = _int(data["darken"], f"{path}.darken", 1 if kind != "strokes" else 0, max(1, ramp_len - 1))
   out.seed = _int(data.get("seed", 0), f"{path}.seed", 0, 2**31 - 1)
   if kind == "rows":
      rows = data.get("rows")
      if not isinstance(rows, list) or not rows or not all(isinstance(r, int) and not isinstance(r, bool) for r in rows):
         raise _where(f"{path}.rows", "그림 줄 번호(정수) 목록이다")
      out.rows = rows
      out.width = _number(data.get("width", 1), f"{path}.width", 1.0)
      return out
   if kind == "strokes":
      out.density = _number(data.get("density", 0.1), f"{path}.density", 0.0, 1.0)
      out.length = _int(data.get("length", 3), f"{path}.length", 1, 32)
      out.lean = _number(data.get("lean", 0.0), f"{path}.lean", -4.0, 4.0)
      out.cell = _number(data.get("cell", 1.0), f"{path}.cell", 1.0)
      out.jitter = _number(data.get("jitter", 1.0), f"{path}.jitter", 0.0, 8.0)
      cols = data.get("colors", [])
      if not isinstance(cols, list):
         raise _where(f"{path}.colors", "색 목록(어두운 → 밝은)이다")
      out.colors = [_color(c, f"{path}.colors[{i}]") for i, c in enumerate(cols)]
      return out
   if kind == "speckle":
      out.density = _number(data.get("density", 0.05), f"{path}.density", 0.0, 1.0)
      out.cell = _number(data.get("cell", 1.0), f"{path}.cell", 0.25)
      dot = data.get("dot", ["#"])
      if not isinstance(dot, list) or not dot or not all(isinstance(r, str) and r for r in dot):
         raise _where(f"{path}.dot", "글자 줄 목록이다 ('.' 빈칸)")
      out.dot = dot
   else:
      axis = data.get("axis", "y")
      if axis not in PATTERN_AXES:
         raise _where(f"{path}.axis", f"x · y · z 중 하나다 : {axis!r}")
      out.axis = axis
      out.period = _number(data.get("period", 4), f"{path}.period", 1.0)
      out.phase = _number(data.get("phase", 0), f"{path}.phase")
      out.width = _number(data.get("width", 1), f"{path}.width", 0.0, out.period)
      out.wobble = _number(data.get("wobble", 0), f"{path}.wobble", 0.0)
      if "fan" in data:
         out.fan = tuple(_vec(data["fan"], 3, f"{path}.fan"))
   return out


ELLIPSE_STEPS = 64


def _outline_2d(data: dict, path: str) -> np.ndarray:
   """돌출 단면 : `points` · `rect` [x0, y0, x1, y1] · `ellipse` [cx, cy, rx, ry] 가운데 하나 (+ `mirror` x).

   `mirror` 를 주면 points 를 x = mirror 선에 거울로 비춰 거꾸로 이어 붙인다 — 좌우 대칭 모양을 반쪽만 적는다.
   """
   given = [key for key in ("points", "rect", "ellipse") if key in data]
   if len(given) != 1:
      raise _where(path, "points · rect · ellipse 가운데 하나만 준다")
   if "rect" in data:
      x0, y0, x1, y1 = _vec(data["rect"], 4, f"{path}.rect")
      if x1 <= x0 or y1 <= y0:
         raise _where(f"{path}.rect", "x0 < x1 · y0 < y1 이어야 한다")
      return np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], dtype=float)
   if "ellipse" in data:
      cx, cy, rx, ry = _vec(data["ellipse"], 4, f"{path}.ellipse")
      if rx <= 0 or ry <= 0:
         raise _where(f"{path}.ellipse", "반지름은 0 보다 크다")
      a = np.linspace(0.0, 2.0 * math.pi, ELLIPSE_STEPS, endpoint=False)
      return np.stack([cx + rx * np.cos(a), cy + ry * np.sin(a)], axis=1)
   pts = data["points"]
   if not isinstance(pts, list) or len(pts) < (2 if "mirror" in data else 3):
      raise _where(f"{path}.points", "[x, y] 점이 셋 이상인 목록이다 (mirror 면 둘 이상)")
   poly = np.array([_vec(q, 2, f"{path}.points[{i}]") for i, q in enumerate(pts)], dtype=float)
   if "mirror" in data:
      m = _number(data["mirror"], f"{path}.mirror")
      back = poly[::-1].copy()
      back[:, 0] = 2.0 * m - back[:, 0]
      # 거울선 위의 점은 한 번만
      keep = ~np.isclose(back[:, 0], m)
      if np.isclose(poly[-1, 0], m):
         keep[0] = False
      if np.isclose(poly[0, 0], m):
         keep[-1] = False
      poly = np.concatenate([poly, back[keep]], axis=0)
   return poly


def _prim_params(kind: str, data: dict, path: str) -> dict:
   if kind == "sphere":
      return {"r": _number(data.get("r"), f"{path}.r", 0.01)}
   if kind == "ellipsoid":
      return {"radii": _vec(data.get("radii"), 3, f"{path}.radii", 0.01)}
   if kind == "capsule":
      return {"r": _number(data.get("r"), f"{path}.r", 0.01), "length": _number(data.get("length", 0), f"{path}.length", 0.0)}
   if kind == "box":
      size = _vec(data.get("size"), 3, f"{path}.size", 0.01)
      rnd = _number(data.get("round", 0), f"{path}.round", 0.0, min(size) / 2)
      return {"size": size, "round": rnd}
   if kind == "extrude":
      poly = _outline_2d(data, path)
      if data.get("y_down", False) is True:
         poly[:, 1] = -poly[:, 1]      # 그림 좌표(아래로 +)로 적은 점
      depth = _number(data.get("depth", 8), f"{path}.depth", 0.01)
      rnd = _number(data.get("round", 0), f"{path}.round", 0.0, depth / 2)
      return {"points": poly.tolist(), "_poly": poly, "depth": depth, "round": rnd}
   if kind == "cone":
      r = _number(data.get("r"), f"{path}.r", 0.0)
      top = _number(data.get("top", 0), f"{path}.top", 0.0)
      height = _number(data.get("height"), f"{path}.height", 0.01)
      if r == 0 and top == 0:
         raise _where(f"{path}.r", "r · top 가 둘 다 0 이면 도형이 없다")
      return {"r": r, "top": top, "height": height, "_poly": lathe_polygon([[r, 0], [top, height]])}
   # lathe
   profile = data.get("profile")
   if not isinstance(profile, list) or len(profile) < 2:
      raise _where(f"{path}.profile", "[반지름, 높이] 점이 둘 이상인 목록이다")
   pts = [_vec(p, 2, f"{path}.profile[{i}]") for i, p in enumerate(profile)]
   if any(r < 0 for r, _ in pts):
      raise _where(f"{path}.profile", "반지름은 0 이상이다")
   return {"profile": pts, "_poly": lathe_polygon(pts)}


def _prims(items, path: str, rot: np.ndarray, pos: np.ndarray, materials: dict, out: list[Prim], inherit: str | None) -> None:
   if not isinstance(items, list):
      raise _where(path, "도형 목록이어야 한다")
   for i, data in enumerate(items):
      here = f"{path}[{i}]"
      if not isinstance(data, dict):
         raise _where(here, "도형은 사전이다")
      kind = data.get("type")
      local_rot = rotation(_vec(data.get("rot", [0, 0, 0]), 3, f"{here}.rot"))
      local_pos = np.array(_vec(data.get("pos", [0, 0, 0]), 3, f"{here}.pos"))
      world_rot = rot @ local_rot
      world_pos = rot @ local_pos + pos
      material = data.get("material", inherit)
      if kind == "group":
         _prims(data.get("shapes"), f"{here}.shapes", world_rot, world_pos, materials, out, material)
         continue
      if kind not in KINDS:
         raise _where(f"{here}.type", f"{' · '.join([*KINDS, 'group'])} 중 하나다 : {kind!r}")
      if material not in materials:
         raise _where(f"{here}.material", f"없는 재질 : {material!r}")
      op = data.get("op", "union")
      if op not in OPS:
         raise _where(f"{here}.op", f"{' · '.join(OPS)} 중 하나다 : {op!r}")
      k = _number(data.get("k", 2.0), f"{here}.k", 0.0) if op == "smooth" else 0.0
      params = _prim_params(kind, data, here)
      for dx, dy in _offsets(data.get("copies", [[0, 0]]), f"{here}.copies"):
         # 옮김은 그림 칸(아래 +) 이라 모델 y 는 거꾸로 간다. 묶음 회전은 타지 않는 화면 기준 옮김이다.
         shifted = world_pos + np.array([dx, -dy, 0.0])
         out.append(Prim(kind, params, material, op, k, world_rot, shifted, str(data.get("name", here))))


def _offsets(copies, path: str) -> list[tuple[int, int]]:
   if not isinstance(copies, list) or not copies or not all(
         isinstance(c, list) and len(c) == 2 and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in c) for c in copies):
      raise _where(path, "[dx, dy] 목록이다 (그림 칸, 아래 +)")
   return [(float(c[0]), float(c[1])) for c in copies]


def _stamp(data, path: str, materials: dict) -> Stamp:
   if not isinstance(data, dict):
      raise _where(path, "도장은 사전이다")
   if data.get("mode", "card") not in STAMP_MODES:
      raise _where(f"{path}.mode", f"이번 판은 {' · '.join(STAMP_MODES)} 만 된다 : {data.get('mode')!r}")
   on = data.get("on")
   if on not in materials:
      raise _where(f"{path}.on", f"없는 재질 : {on!r}")
   grid = data.get("grid")
   if not isinstance(grid, list) or not grid or not all(isinstance(r, str) for r in grid):
      raise _where(f"{path}.grid", "글자 줄 목록이다")
   if len({len(r) for r in grid}) != 1 or not grid[0]:
      raise _where(f"{path}.grid", "줄 길이가 모두 같아야 한다")
   legend_raw = data.get("legend")
   if not isinstance(legend_raw, dict):
      raise _where(f"{path}.legend", "글자 → #RRGGBB 사전이다")
   legend = {}
   for key, value in legend_raw.items():
      if len(key) != 1 or key == ".":
         raise _where(f"{path}.legend", f"글자 하나여야 하고 '.' 는 빈칸이라 못 쓴다 : {key!r}")
      legend[key] = _color(value, f"{path}.legend.{key}")
   unknown = sorted({c for r in grid for c in r} - set(legend) - {"."})
   if unknown:
      raise _where(f"{path}.grid", f"legend 에 없는 글자 : {''.join(unknown)}")
   at = _vec(data.get("at"), 2, f"{path}.at")
   copies = data.get("copies", [[0, 0]])
   if not isinstance(copies, list) or not copies or not all(
         isinstance(c, list) and len(c) == 2 and all(isinstance(v, int) and not isinstance(v, bool) for v in c) for c in copies):
      raise _where(f"{path}.copies", "정수 [dx, dy] 목록이다 (그림 칸, 아래 +)")
   return Stamp(on, (at[0], at[1]), _number(data.get("yaw", 0), f"{path}.yaw", -360, 360), grid, legend,
                _number(data.get("hide_below", 0.15), f"{path}.hide_below", -1.0, 1.0),
                _number(data.get("depth_tol", 4.0), f"{path}.depth_tol", 0.0), [(c[0], c[1]) for c in copies])


def parse(data, where: str = "명세") -> Spec:
   """읽은 JSON 사전 → `Spec`."""
   if not isinstance(data, dict):
      raise ArtToolError(f"{where} : 맨 위는 사전이다")
   if data.get("version", VERSION) != VERSION:
      raise _where("version", f"{VERSION} 만 읽는다 : {data.get('version')!r}")
   canvas = data.get("canvas", {})
   if not isinstance(canvas, dict):
      raise _where("canvas", "사전이다 {size, origin}")
   w, h = (int(v) for v in _vec(canvas.get("size"), 2, "canvas.size", 1, SIZE_MAX))
   origin = _vec(canvas.get("origin", [w / 2, h / 2]), 2, "canvas.origin")

   light_raw = data.get("light", "top_left")
   if isinstance(light_raw, str):
      if light_raw not in LIGHT_WORDS:
         raise _where("light", f"{' · '.join(LIGHT_WORDS)} 또는 [x, y, z] 다 : {light_raw!r}")
      light_word, vec = light_raw, np.array(LIGHT_WORDS[light_raw])
   else:
      vec = np.array(_vec(light_raw, 3, "light"))
      light_word = "top_left" if vec[0] <= 0 else "top_right"
   norm = float(np.linalg.norm(vec))
   if norm == 0:
      raise _where("light", "길이 0 인 빛은 없다")

   line = data.get("outline", {"mode": "none"})
   if not isinstance(line, dict) or line.get("mode", "none") not in OUTLINE_MODES:
      raise _where("outline.mode", f"{' · '.join(OUTLINE_MODES)} 중 하나다")
   mode = line.get("mode", "none")
   line_color = _color(line["color"], "outline.color") if mode == "solid" or "color" in line else None
   width = line.get("width", 1)
   if isinstance(width, bool) or not isinstance(width, int) or not 1 <= width <= 4:
      raise _where("outline.width", f"1 ~ 4 정수다 : {width!r}")
   inner_width = line.get("inner_width", 1)
   if isinstance(inner_width, bool) or not isinstance(inner_width, int) or not 1 <= inner_width <= 4:
      raise _where("outline.inner_width", f"1 ~ 4 정수다 : {inner_width!r}")
   gap = line.get("inner_gap")
   inner_gap = None if gap is None else _number(gap, "outline.inner_gap", 0.0)

   cap = data.get("max_colors")
   if cap is not None and (isinstance(cap, bool) or not isinstance(cap, int) or cap < 2):
      raise _where("max_colors", f"2 이상 정수다 : {cap!r}")

   views = dict(VIEWS)
   for key, value in (data.get("views") or {}).items():
      views[str(key)] = _number(value, f"views.{key}", -360, 360)

   mats_raw = data.get("materials")
   if not isinstance(mats_raw, dict) or not mats_raw:
      raise _where("materials", "재질이 하나 이상 있어야 한다")
   materials = {name: _material(name, value, f"materials.{name}") for name, value in mats_raw.items()}

   prims: list[Prim] = []
   _prims(data.get("shapes"), "shapes", np.eye(3), np.zeros(3), materials, prims, None)
   if not prims:
      raise _where("shapes", "도형이 하나도 없다")
   stamps = [_stamp(s, f"stamps[{i}]", materials) for i, s in enumerate(data.get("stamps") or [])]

   return Spec((w, h), (origin[0], origin[1]), vec / norm, light_word, mode, line_color, width, inner_gap, cap,
               _number(data.get("dither", 0.0), "dither", 0.0, 1.0), views, materials, prims, stamps, inner_width)


def load(path: str | os.PathLike) -> Spec:
   file = Path(path)
   if not file.is_file():
      raise ArtToolError(f"명세 파일이 없다 : {file}")
   data = read_json(file)
   if is_template_spec(data):
      data = expand(data, file.parent, str(file))
   data = assemble(data, file.parent, str(file))
   return parse(data, str(file))
