"""프로필 읽기. 기본값 → 프리셋 → 프로필 파일 → CLI 인자 순으로 뒤가 앞을 이긴다."""

from __future__ import annotations

import copy
import math
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
# style 칸 (2026-10-04 개선 설계 7-1). 「이 게임은 이렇게 그린다」
STYLE_OUTLINES = ("unset", "none", "black", "solid", "selout", "selout+light")   # solid = 검정이 아닌 한 색 선
STYLE_LIGHTS = ("top_left", "top", "top_right")
MATERIALS = ("metal", "ice", "gem", "goo", "stone", "wood", "cloth")
WARN_RULES = ("integer_scale", "outline", "isolated", "color_cap", "near_colors", "ramp_shape", "loop_seam", "odd_size")

DIRECTION_NAMES = {
   1: ["south"],
   4: ["south", "west", "north", "east"],
   8: ["south", "southwest", "west", "northwest", "north", "northeast", "east", "southeast"],
}

TOP_KEYS = ("name", "preset", "axes", "canvas", "palette", "anim", "rigs", "tiles", "check", "sprite", "ui", "style")

# rig 와 anim 은 이름이 사람 마음이라 DEFAULTS 로 못 검사한다. 안쪽 칸 이름만 정해 둔다.
ANIM_KEYS = ("frames", "dirs")
RIG_KEYS = ("method", "layer_order", "anchors", "marker_colors", "anchor_z")
# 값이 사람이 정한 이름표라 안쪽을 안 들여다보는 칸. 열쇠가 크기 숫자인 표도 여기 둔다(값은 validate 가 본다).
FREE_MAPS = ("rigs.*.marker_colors", "rigs.*.anchor_z", "check.warn.color_cap.table")

# 새 검사 일곱의 문턱값. isolated · color_cap · near_colors 는 실물 시험(2026-10-04, 기준 무리 146장)으로 맞췄다.
WARN_DEFAULTS: dict = {
   "integer_scale": {"enabled": True, "block_ratio": 0.95, "smooth_ratio": 0.15},
   "outline": {"enabled": True, "black_ratio": 0.8, "accept": []},     # accept : style.outline 말고도 통과시킬 판정들
   "isolated": {"enabled": True, "max_ratio": 0.15},      # 0.03 이면 기준 무리 40% 가 걸렸다 → 0.15 면 8%
   "color_cap": {"enabled": True, "table": {8: 4, 16: 8, 32: 16, 48: 44, 64: 48, 128: 48, 256: 64}},   # 48 칸 p90 42 · 64 칸 p90 48 · 64 초과 p90 55. 칸이 커지면 한도도 줄지 않게
   "near_colors": {"enabled": True, "max_delta": 4, "min_pairs": 20},   # 짝이 20 개 넘어야 경고 (기준 38% → 3.4%)
   "ramp_shape": {"enabled": True, "steps": [4, 6], "hue_min": 5, "hue_max": 30},
   "loop_seam": {"enabled": True, "k": 2.0, "anims": ["idle", "walk", "run"]},
   "odd_size": {"enabled": True},     # 피벗이 반 픽셀에 놓이는 홀수 크기 (2026-10-06 1판 3절)
}

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
   "check": {
      "max_colors": 48,
      "allow_alpha": "binary",
      "baseline_tolerance": 0,
      "bbox_drift": 1,
      "warn": WARN_DEFAULTS,
      # 투명 칸이 하나도 없고 짧은 변이 min_side 이상이면 배경으로 본다
      "background": {"auto": True, "min_side": 128, "color_cap": 64, "max_colors": None},
   },
   "sprite": {},
   "ui": UI_DEFAULTS,
   # unset 이면 외곽선 검사가 「방식 미정이라 건너뜀」으로 지나간다 — 옛 프로필에서 오탐을 안 낸다
   "style": {"outline": "unset", "light": "top_left", "scale": 1, "materials": {}},
}


HOME_COPY = "_home"     # 휠 설치 때 profiles/ · palettes/ · templates/ 사본이 들어가는 꾸러미 안 폴더 (pyproject 참고)


def tool_home() -> Path:
   """ArtTool 폴더. profiles/ · palettes/ · templates/ 가 여기 있다.

   찾는 차례 : ① ARTTOOL_HOME ② 소스 폴더(편집 설치 · 저장소에서 바로 돌릴 때) ③ 휠로 설치한 꾸러미 안 `_home` 사본.
   """
   env = os.environ.get("ARTTOOL_HOME")
   if env:
      return Path(env).resolve()
   source = Path(__file__).resolve().parents[2]
   # profiles/ 하나로 판정한다. templates/ 까지 요구하면 템플릿 폴더가 없는 소스 사본이 _home 으로 빠진다 (리뷰 R1-L4)
   if (source / "profiles").is_dir():
      return source
   return Path(__file__).resolve().parent / HOME_COPY


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
   def style(self) -> dict:
      return self.data["style"]

   def warn(self, rule: str) -> dict:
      """새 검사 하나의 문턱값 묶음. 예 : warn("isolated")["max_ratio"]"""
      if rule not in WARN_RULES:
         raise ProfileError(f"모르는 경고 검사 : {rule} (쓸 수 있는 것 : {' · '.join(WARN_RULES)})")
      return self.check["warn"][rule]

   def color_cap_table(self) -> dict[int, int]:
      """크기 → 색 수 한도 표를 정수 열쇠로, 크기 순으로.

      YAML 은 열쇠가 정수, JSON(템플릿)을 겹치면 문자열이라 둘이 섞일 수 있다. 뒤에 겹친 쪽이 이긴다.
      """
      merged: dict[int, int] = {}
      for key, value in self.warn("color_cap")["table"].items():
         merged[int(key)] = int(value)
      return dict(sorted(merged.items()))

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


def load_profile_args(args) -> Profile:
   """CLI 인자(argparse 결과)에서 프로필을 읽는다. 새 명령 모듈은 이것만 부른다.

   `--profile` 과 `--directions` 를 본다. 칸이 없는 args 도 받는다(안 준 것으로 본다).
   """
   overrides = {}
   directions = getattr(args, "directions", None)
   if directions:
      overrides["axes.directions"] = directions
   return load_profile(getattr(args, "profile", None), overrides)


def reject_unknown(raw: dict, where) -> None:
   """프로필 꼴 사전(일부만 있어도 된다)에서 DEFAULTS 에 없는 칸을 거절한다. 템플릿 · 검사가 같이 쓴다."""
   _reject_unknown(raw, DEFAULTS, "", where)


def _reject_unknown_top(raw: dict, source: Path | None) -> None:
   reject_unknown(raw, source or "(인자)")


def _reject_unknown(raw: dict, allowed: dict, path: str, where) -> None:
   """겹구조를 재귀로 훑어 DEFAULTS 에 없는 칸을 거절한다. 오타가 조용히 기본값으로 넘어가면 안 된다."""
   if path in FREE_MAPS:
      return

   names = _allowed_names(allowed, path)
   unknown = [] if names == () else sorted(str(k) for k in raw if str(k) not in names)
   if unknown:
      spot = path or "맨 위"
      # YAML 1.1 은 on · off · yes · no 열쇠를 참거짓으로 읽는다. 오타보다 이쪽이 흔해 따로 알린다.
      hint = " — YAML 은 on · off · yes · no 를 참거짓으로 읽는다. 켜고 끄기는 enabled 칸이다" if any(isinstance(k, bool) for k in raw) else ""
      raise ProfileError(f"모르는 항목이 있다 : {', '.join(unknown)} ({spot}){hint} - {where}")

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

   validate_style(data["style"])
   validate_warn(data["check"]["warn"])
   validate_background(data["check"]["background"])


def _is_int(value) -> bool:
   return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value) -> bool:
   return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _ratio(node: dict, key: str, where: str) -> float:
   value = node.get(key)
   if not _is_number(value) or not 0 <= value <= 1:
      raise ProfileError(f"{where}.{key} 는 0 ~ 1 사이 수여야 한다 : {value}")
   return float(value)


def _positive_int(node: dict, key: str, where: str) -> int:
   value = node.get(key)
   if not _is_int(value) or value <= 0:
      raise ProfileError(f"{where}.{key} 는 양의 정수여야 한다 : {value}")
   return value


def _flag(node: dict, key: str, where: str) -> bool:
   value = node.get(key)
   if not isinstance(value, bool):
      raise ProfileError(f"{where}.{key} 는 true · false 다 : {value}")
   return value


def validate_style(style: dict) -> None:
   _one_of(style, "outline", STYLE_OUTLINES, "style")
   _one_of(style, "light", STYLE_LIGHTS, "style")
   _positive_int(style, "scale", "style")
   materials = style.get("materials")
   if not isinstance(materials, dict):
      raise ProfileError(f"style.materials 는 「램프 이름 : 재질」 사전이다 : {materials}")
   bad = sorted(f"{name}={kind}" for name, kind in materials.items() if kind not in MATERIALS)
   if bad:
      raise ProfileError(f"style.materials 의 재질은 {' · '.join(MATERIALS)} 중 하나다 : {', '.join(bad)}")


def validate_warn(warn: dict) -> None:
   where = "check.warn"
   for rule in WARN_RULES:
      node = warn.get(rule)
      if not isinstance(node, dict):
         raise ProfileError(f"{where}.{rule} 는 사전이다 : {node}")
      _flag(node, "enabled", f"{where}.{rule}")

   _ratio(warn["integer_scale"], "block_ratio", f"{where}.integer_scale")
   _ratio(warn["integer_scale"], "smooth_ratio", f"{where}.integer_scale")
   _ratio(warn["outline"], "black_ratio", f"{where}.outline")
   accept = warn["outline"].get("accept")
   allowed = [o for o in STYLE_OUTLINES if o != "unset"]
   if not isinstance(accept, list) or not all(a in allowed for a in accept):
      raise ProfileError(f"{where}.outline.accept 는 {' · '.join(allowed)} 중에서 고른 목록이다 : {accept}")
   _ratio(warn["isolated"], "max_ratio", f"{where}.isolated")
   _validate_color_cap(warn["color_cap"].get("table"), f"{where}.color_cap.table")

   delta = warn["near_colors"].get("max_delta")
   if not _is_int(delta) or not 0 <= delta <= 255:
      raise ProfileError(f"{where}.near_colors.max_delta 는 0 ~ 255 정수다 : {delta}")
   _positive_int(warn["near_colors"], "min_pairs", f"{where}.near_colors")

   _validate_ramp_shape(warn["ramp_shape"], f"{where}.ramp_shape")

   seam = warn["loop_seam"]
   if not _is_number(seam.get("k")) or seam["k"] <= 0:
      raise ProfileError(f"{where}.loop_seam.k 는 양수여야 한다 : {seam.get('k')}")
   anims = seam.get("anims")
   if not isinstance(anims, list) or not all(isinstance(a, str) and a for a in anims):
      raise ProfileError(f"{where}.loop_seam.anims 는 애니 이름 목록이다 : {anims}")


def _validate_color_cap(table, where: str) -> None:
   """열쇠 = 크기(양의 정수, JSON 에서 온 숫자 글자도 받는다), 값 = 색 수 한도(양의 정수)."""
   if not isinstance(table, dict) or not table:
      raise ProfileError(f"{where} 는 「크기 : 색 수」 사전이고 비면 안 된다 : {table}")
   for key, value in table.items():
      size_ok = (_is_int(key) and key > 0) or (isinstance(key, str) and key.isdigit() and int(key) > 0)
      if not size_ok:
         raise ProfileError(f"{where} 의 열쇠는 양의 정수 크기다 : {key}")
      if not _is_int(value) or value <= 0:
         raise ProfileError(f"{where}.{key} 는 양의 정수다 : {value}")


def _validate_ramp_shape(node: dict, where: str) -> None:
   steps = node.get("steps")
   if not isinstance(steps, list) or len(steps) != 2 or not all(_is_int(s) and s > 0 for s in steps) or steps[0] > steps[1]:
      raise ProfileError(f"{where}.steps 는 [최소, 최대] 양의 정수 두 칸이다 : {steps}")
   low, high = node.get("hue_min"), node.get("hue_max")
   if not _is_number(low) or not _is_number(high) or not 0 <= low <= high <= 180:
      raise ProfileError(f"{where}.hue_min · hue_max 는 0 ≤ 최소 ≤ 최대 ≤ 180 이다 : {low} · {high}")


def validate_background(node: dict) -> None:
   where = "check.background"
   _flag(node, "auto", where)
   _positive_int(node, "min_side", where)
   _positive_int(node, "color_cap", where)
   if node.get("max_colors") is not None:
      _positive_int(node, "max_colors", where)


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
