"""프로필 읽기. 기본값 → 프리셋 → 프로필 파일 → CLI 인자 순으로 뒤가 앞을 이긴다."""

from __future__ import annotations

import copy
import os
import sys
from pathlib import Path

import yaml

from .errors import ProfileError
from .paths import check_relative, resolve_root, safe_join

PROJECTIONS = ("front", "topdown", "quarter", "isometric")
MOVEMENTS = ("plane", "gravity")
DIRECTION_COUNTS = (1, 4, 8)
PIVOTS = ("bottom_center", "center", "top_left")
SWAP_MODES = ("runtime_lut", "bake", "both")
ALPHA_MODES = ("binary", "any")
RIG_METHODS = ("layer", "anchor")
CORNER_CUTS = ("square", "cut1", "cut2")
UI_STATES = ("normal", "pressed", "disabled", "hover")
SCALE_MODES = ("integer",)
HOTSPOTS = ("center", "top_left")
PRESET_NAMES = ("platformer", "beltscroll", "topdown_action", "iso")

DIRECTION_NAMES = {
   1: ["south"],
   4: ["south", "west", "north", "east"],
   8: ["south", "southwest", "west", "northwest", "north", "northeast", "east", "southeast"],
}

TOP_KEYS = ("name", "preset", "axes", "canvas", "palette", "anim", "rigs", "tiles", "check", "sprite", "ui")

# rig 와 anim 은 이름이 사람 마음이라 DEFAULTS 로 못 검사한다. 안쪽 칸 이름만 정해 둔다.
ANIM_KEYS = ("frames", "dirs")
RIG_KEYS = ("method", "layer_order", "anchors", "marker_colors", "anchor_z")
# 값이 사람이 정한 이름표라 안쪽을 안 들여다보는 칸
FREE_MAPS = ("rigs.*.marker_colors", "rigs.*.anchor_z")

UI_DEFAULTS: dict = {
   "ppu": 16,
   "reference": [320, 180],
   "scale_mode": "integer",
   "letterbox": True,
   "frame": {"source": [16, 16], "even_only": True},
   "icon": {
      "sizes": [16, 32],
      "sheet": {"cell": 16, "margin": 0, "spacing": 2},
      "hotspot": "center",
   },
   "generator": {
      "border_px": 1,
      "corner": "cut1",
      "highlight": 1,
      "inner_shadow": 1,
      "ramp": "ui_panel",
      "ramp_disabled": "ui_gray",
      "ramp_index": {"outline": 5, "highlight": 1, "fill": 3, "shadow": 4},
      "states": ["normal", "pressed", "disabled"],
   },
   "font": {
      "family": "Galmuri11",
      "native_px": 11,
      "sizes_px": [11, 22],
      "subset": {
         "scan_dirs": ["Text/"],
         "extensions": [".txt", ".json", ".csv"],
         "always": "0123456789.,!?%:()+-/ ",
         "atlas_max": 2048,
      },
   },
   "check": {
      "min_size_slack": 1,
      "palette_strict": True,
      "allow_alpha": "binary",
      "require_even": True,
      "atlas_max": 2048,
   },
}

DEFAULTS: dict = {
   "name": "default",
   "preset": "topdown_action",
   "axes": {"projection": "quarter", "directions": 4, "movement": "plane"},
   "canvas": {"frame": [64, 64], "baseline_y": 50, "center_x": 31.5, "pivot": "bottom_center"},
   "palette": {
      "ramp_len": 6,
      "outline": "#000000",
      "exact_match": True,
      "ramps_file": None,
      "swap": "runtime_lut",
   },
   "anim": {"idle": {"frames": 2, "dirs": 4}},
   "rigs": {},
   "tiles": {"size": 16, "blob": 47, "mirror_east_from_west": True},
   "check": {"max_colors": 48, "allow_alpha": "binary", "baseline_tolerance": 0, "bbox_drift": 1},
   "sprite": {},
   "ui": UI_DEFAULTS,
}


def tool_home() -> Path:
   """ArtTool 폴더. profiles/ · palettes/ 가 여기 있다."""
   env = os.environ.get("ARTTOOL_HOME")
   if env:
      return Path(env).resolve()
   return Path(__file__).resolve().parents[2]


def profiles_dir() -> Path:
   return tool_home() / "profiles"


def deep_merge(base: dict, over: dict) -> dict:
   out = copy.deepcopy(base)
   for key, value in over.items():
      if isinstance(value, dict) and isinstance(out.get(key), dict):
         out[key] = deep_merge(out[key], value)
         continue
      out[key] = copy.deepcopy(value)
   return out


def _read_yaml(path: Path) -> dict:
   if not path.is_file():
      raise ProfileError(f"프로필 파일이 없다 : {path}")
   text = _read_text(path)
   try:
      data = yaml.safe_load(text)
   except yaml.YAMLError as exc:
      raise ProfileError(f"YAML 을 못 읽었다 : {path} - {exc}") from exc
   if data is None:
      return {}
   if not isinstance(data, dict):
      raise ProfileError(f"프로필 맨 위는 사전이어야 한다 : {path}")
   return data


def _read_text(path: Path) -> str:
   raw = path.read_bytes()
   try:
      return raw.decode("utf-8-sig")
   except UnicodeDecodeError:
      pass

   try:
      text = raw.decode("cp949")
   except UnicodeDecodeError as exc:
      raise ProfileError(f"utf-8 도 cp949 도 아니라 못 읽었다 : {path} - {exc}") from exc

   print(f"경고 : cp949 로 되살려 읽었다. utf-8 로 다시 저장한다 : {path}", file=sys.stderr)
   return text


def load_preset(name: str) -> dict:
   if name not in PRESET_NAMES:
      raise ProfileError(f"모르는 프리셋 : {name} (쓸 수 있는 것 : {', '.join(PRESET_NAMES)})")
   return _read_yaml(profiles_dir() / "presets" / f"{name}.yaml")


def find_profile_file(name_or_path: str) -> Path:
   direct = Path(name_or_path)
   if direct.suffix in (".yaml", ".yml") and direct.is_file():
      return direct
   candidate = profiles_dir() / f"{name_or_path}.yaml"
   if candidate.is_file():
      return candidate
   raise ProfileError(f"프로필을 못 찾았다 : {name_or_path}")


def apply_overrides(data: dict, overrides: dict[str, object]) -> dict:
   """CLI 인자를 점 찍은 열쇠로 덮어쓴다. 예 : axes.directions"""
   out = copy.deepcopy(data)
   for dotted, value in overrides.items():
      if value is None:
         continue
      parts = dotted.split(".")
      node = out
      for part in parts[:-1]:
         node = node.setdefault(part, {})
         if not isinstance(node, dict):
            raise ProfileError(f"덮어쓸 자리가 사전이 아니다 : {dotted}")
      node[parts[-1]] = value
   return out


class Profile:
   """읽어들인 프로필 한 벌."""

   def __init__(self, data: dict, source: Path | None = None):
      self.data = data
      self.source = source

   @property
   def name(self) -> str:
      return str(self.data["name"])

   @property
   def axes(self) -> dict:
      return self.data["axes"]

   @property
   def canvas(self) -> dict:
      return self.data["canvas"]

   @property
   def palette(self) -> dict:
      return self.data["palette"]

   @property
   def anim(self) -> dict:
      return self.data["anim"]

   @property
   def rigs(self) -> dict:
      return self.data["rigs"]

   @property
   def tiles(self) -> dict:
      return self.data["tiles"]

   @property
   def ui(self) -> dict:
      return self.data["ui"]

   def ui_frame_size(self) -> tuple[int, int]:
      w, h = self.ui["frame"]["source"]
      return int(w), int(h)

   def slice_scale(self) -> float:
      """USS -unity-slice-scale 에 넣을 값. 100 / ppu 다."""
      return round(100.0 / int(self.ui["ppu"]), 6)

   @property
   def check(self) -> dict:
      return self.data["check"]

   @property
   def frame(self) -> tuple[int, int]:
      w, h = self.canvas["frame"]
      return int(w), int(h)

   @property
   def directions(self) -> int:
      return int(self.axes["directions"])

   def direction_names(self, count: int | None = None) -> list[str]:
      return list(DIRECTION_NAMES[count or self.directions])

   def mirror_east(self) -> bool:
      """east 를 west 반전으로 만들 것인가. sprite 쪽 값이 먼저다."""
      sprite = self.data.get("sprite") or {}
      if "mirror_east_from_west" in sprite:
         return bool(sprite["mirror_east_from_west"])
      return bool(self.tiles.get("mirror_east_from_west", False))

   def rig(self, name: str) -> dict:
      if name not in self.rigs:
         raise ProfileError(f"프로필에 없는 rig : {name}")
      return self.rigs[name]

   def ramps_path(self) -> Path | None:
      """램프 파일 자리. 프로필 파일 폴더 또는 툴 폴더 아래 상대경로만 받는다."""
      rel = self.palette.get("ramps_file")
      if not rel:
         return None

      check_relative(rel)
      if self.source is not None:
         near = safe_join(resolve_root(self.source.parent), rel)
         if near.is_file():
            return near
      return safe_join(resolve_root(tool_home()), rel)

   def as_dict(self) -> dict:
      return copy.deepcopy(self.data)


def load_profile(name_or_path: str | None = None, overrides: dict[str, object] | None = None) -> Profile:
   source = None
   raw: dict = {}
   if name_or_path:
      source = find_profile_file(name_or_path)
      raw = _read_yaml(source)

   _reject_unknown_top(raw, source)
   preset_name = raw.get("preset", DEFAULTS["preset"])
   data = deep_merge(DEFAULTS, load_preset(str(preset_name)))
   data = deep_merge(data, raw)
   if overrides:
      data = apply_overrides(data, overrides)
   if name_or_path and "name" not in raw:
      data["name"] = Path(name_or_path).stem

   validate(data)
   return Profile(data, source)


def _reject_unknown_top(raw: dict, source: Path | None) -> None:
   where = source or "(인자)"
   _reject_unknown(raw, DEFAULTS, "", where)


def _reject_unknown(raw: dict, allowed: dict, path: str, where) -> None:
   """겹구조를 재귀로 훑어 DEFAULTS 에 없는 칸을 거절한다. 오타가 조용히 기본값으로 넘어가면 안 된다."""
   if path in FREE_MAPS:
      return

   names = _allowed_names(allowed, path)
   unknown = [] if names == () else sorted(str(k) for k in raw if str(k) not in names)
   if unknown:
      spot = path or "맨 위"
      raise ProfileError(f"모르는 항목이 있다 : {', '.join(unknown)} ({spot}) - {where}")

   for key, value in raw.items():
      if not isinstance(value, dict):
         continue
      _reject_unknown(value, _child_schema(allowed, path, str(key)), _join(path, str(key)), where)


def _join(path: str, key: str) -> str:
   if not path:
      return key
   return f"{path}.{key}"


def _allowed_names(allowed: dict, path: str) -> tuple[str, ...]:
   if path in ("anim", "rigs"):
      return ()
   if path.startswith("rigs.") and path.count(".") == 1:
      return RIG_KEYS
   if path == "":
      return TOP_KEYS
   return tuple(allowed)


def _child_schema(allowed: dict, path: str, key: str) -> dict:
   if path == "rigs":
      return {}
   if path == "anim":
      return dict.fromkeys(ANIM_KEYS)
   child = allowed.get(key)
   if isinstance(child, dict):
      return child
   return {}


def validate(data: dict) -> None:
   axes = data["axes"]
   _one_of(axes, "projection", PROJECTIONS, "axes")
   _one_of(axes, "movement", MOVEMENTS, "axes")
   if int(axes["directions"]) not in DIRECTION_COUNTS:
      raise ProfileError(f"axes.directions 는 1 · 4 · 8 중 하나다 : {axes['directions']}")

   canvas = data["canvas"]
   frame = canvas.get("frame")
   if not isinstance(frame, (list, tuple)) or len(frame) != 2:
      raise ProfileError(f"canvas.frame 은 [너비, 높이] 두 칸이다 : {frame}")
   if int(frame[0]) <= 0 or int(frame[1]) <= 0:
      raise ProfileError(f"canvas.frame 은 양수여야 한다 : {frame}")
   if not 0 <= float(canvas["baseline_y"]) < int(frame[1]):
      raise ProfileError(f"canvas.baseline_y 가 프레임 밖이다 : {canvas['baseline_y']}")
   _one_of(canvas, "pivot", PIVOTS, "canvas")

   _one_of(data["palette"], "swap", SWAP_MODES, "palette")
   _one_of(data["check"], "allow_alpha", ALPHA_MODES, "check")

   for anim_name, spec in data["anim"].items():
      if int(spec.get("frames", 0)) < 1:
         raise ProfileError(f"anim.{anim_name}.frames 는 1 이상이다")
      if int(spec.get("dirs", 1)) not in DIRECTION_COUNTS:
         raise ProfileError(f"anim.{anim_name}.dirs 는 1 · 4 · 8 중 하나다")

   for rig_name, rig in data["rigs"].items():
      method = rig.get("method")
      if method not in RIG_METHODS:
         raise ProfileError(f"rigs.{rig_name}.method 는 layer 또는 anchor 다 : {method}")
      if method == "anchor" and not rig.get("anchors"):
         raise ProfileError(f"rigs.{rig_name} 는 anchor 인데 anchors 가 비었다")

   validate_ui(data["ui"])

   tiles = data["tiles"]
   if int(tiles["size"]) <= 0:
      raise ProfileError(f"tiles.size 는 양수여야 한다 : {tiles['size']}")
   if int(tiles["blob"]) != 47:
      raise ProfileError(f"tiles.blob 은 47 만 된다 : {tiles['blob']}")


def _one_of(node: dict, key: str, allowed: tuple[str, ...], where: str) -> None:
   value = node.get(key)
   if value not in allowed:
      raise ProfileError(f"{where}.{key} 는 {' · '.join(allowed)} 중 하나다 : {value}")


def _positive_pair(node: dict, key: str, where: str) -> tuple[int, int]:
   value = node.get(key)
   if not isinstance(value, (list, tuple)) or len(value) != 2:
      raise ProfileError(f"{where}.{key} 는 두 칸짜리 목록이다 : {value}")
   if int(value[0]) <= 0 or int(value[1]) <= 0:
      raise ProfileError(f"{where}.{key} 는 양수여야 한다 : {value}")
   return int(value[0]), int(value[1])


def _non_negative(node: dict, key: str, where: str) -> int:
   value = node.get(key)
   if not isinstance(value, int) or isinstance(value, bool) or value < 0:
      raise ProfileError(f"{where}.{key} 는 0 이상 정수여야 한다 : {value}")
   return value


def validate_ui(ui: dict) -> None:
   if int(ui["ppu"]) <= 0:
      raise ProfileError(f"ui.ppu 는 양수여야 한다 : {ui['ppu']}")
   _positive_pair(ui, "reference", "ui")
   _one_of(ui, "scale_mode", SCALE_MODES, "ui")

   frame = ui["frame"]
   width, height = _positive_pair(frame, "source", "ui.frame")
   if frame.get("even_only") and (width % 2 or height % 2):
      raise ProfileError(f"ui.frame.source 가 홀수다 : {width}x{height} (even_only 가 켜져 있다)")

   _validate_ui_icon(ui["icon"])
   _validate_ui_generator(ui["generator"])
   _validate_ui_font(ui["font"])
   _one_of(ui["check"], "allow_alpha", ALPHA_MODES, "ui.check")
   _non_negative(ui["check"], "min_size_slack", "ui.check")
   if int(ui["check"]["atlas_max"]) <= 0:
      raise ProfileError(f"ui.check.atlas_max 는 양수여야 한다 : {ui['check']['atlas_max']}")


def _validate_ui_icon(icon: dict) -> None:
   sizes = icon.get("sizes")
   if not sizes or any(int(s) <= 0 for s in sizes):
      raise ProfileError(f"ui.icon.sizes 는 양수 하나 이상이다 : {sizes}")

   sheet = icon["sheet"]
   if int(sheet["cell"]) <= 0:
      raise ProfileError(f"ui.icon.sheet.cell 은 양수여야 한다 : {sheet['cell']}")
   _non_negative(sheet, "margin", "ui.icon.sheet")
   _non_negative(sheet, "spacing", "ui.icon.sheet")

   hotspot = icon.get("hotspot")
   if isinstance(hotspot, (list, tuple)):
      if len(hotspot) != 2:
         raise ProfileError(f"ui.icon.hotspot 좌표는 두 칸이다 : {hotspot}")
      return
   if hotspot not in HOTSPOTS:
      raise ProfileError(f"ui.icon.hotspot 은 {' · '.join(HOTSPOTS)} 또는 픽셀 좌표다 : {hotspot}")


def _validate_ui_generator(gen: dict) -> None:
   _non_negative(gen, "border_px", "ui.generator")
   _non_negative(gen, "highlight", "ui.generator")
   _non_negative(gen, "inner_shadow", "ui.generator")
   _one_of(gen, "corner", CORNER_CUTS, "ui.generator")
   if not gen.get("ramp"):
      raise ProfileError("ui.generator.ramp 가 비었다")

   index = gen["ramp_index"]
   for key in ("outline", "highlight", "fill", "shadow"):
      _non_negative(index, key, "ui.generator.ramp_index")

   states = gen.get("states")
   if not states:
      raise ProfileError("ui.generator.states 가 비었다")
   bad = [s for s in states if s not in UI_STATES]
   if bad:
      raise ProfileError(f"모르는 상태 : {', '.join(bad)} (쓸 수 있는 것 : {' · '.join(UI_STATES)})")


def _validate_ui_font(font: dict) -> None:
   native = int(font["native_px"])
   if native <= 0:
      raise ProfileError(f"ui.font.native_px 는 양수여야 한다 : {native}")

   sizes = font.get("sizes_px")
   if not sizes:
      raise ProfileError("ui.font.sizes_px 가 비었다")
   for size in sizes:
      if int(size) <= 0 or int(size) % native != 0:
         raise ProfileError(f"ui.font.sizes_px 는 native_px({native}) 의 정수 배수만 된다 : {size}")

   subset = font["subset"]
   bad = [e for e in subset.get("extensions", []) if not str(e).startswith(".")]
   if bad:
      raise ProfileError(f"ui.font.subset.extensions 는 점으로 시작한다 : {', '.join(bad)}")
   if int(subset["atlas_max"]) <= 0:
      raise ProfileError(f"ui.font.subset.atlas_max 는 양수여야 한다 : {subset['atlas_max']}")
