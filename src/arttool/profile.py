"""프로필 읽기. 기본값 → 프리셋 → 프로필 파일 → CLI 인자 순으로 뒤가 앞을 이긴다."""

from __future__ import annotations

import copy
import math
import os
import sys
from pathlib import Path

import yaml

from .errors import ProfileError, UsageError
from .paths import PALETTES_ENV, PALETTES_PREFIX, check_relative, gathered_palettes_root, is_plain_file, palettes_root, resolve_root, safe_join

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
# 열쇠를 사용자가 정하는 자리. 「*」 는 마디 하나와 맞는다. sprite · style.materials 는 기본값이 빈 사전이라
# 예전에 우연히 자유였던 자리를 그대로 이어받았다(09-18 보류 1 정리).
FREE_MAPS = ("rigs.*.marker_colors", "rigs.*.anchor_z", "check.warn.color_cap.table", "sprite", "style.materials")
# 기본값에는 없지만 적어도 되는 칸(경로 → 이름들). 기본값에 넣으면 옛 프로필의 profile show · 템플릿 출력이 바뀌어 따로 둔다.
OPTIONAL_KEYS: dict[str, tuple[str, ...]] = {"check.warn.color_cap": ("table_mode",), "check.warn.ramp_shape": ("report",)}
# 색 한도 표를 겹치는 법. merge = 아래 표 위에 겹치기(옛 뜻), replace = 이 겹의 표만 쓰기.
TABLE_MODES = ("merge", "replace")

# 새 검사 일곱의 문턱값. isolated · color_cap · near_colors 는 실물 시험(2026-10-04, 기준 무리 146장)으로 맞췄다.
# ramp_shape 경고를 어디에 싣나 (설계 2-4). each = 그림 보고 경고 줄(옛 동작, 기본) · once = 맨 위 `palette` 칸에만 한 번.
RAMP_REPORTS = ("each", "once")

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

   def __init__(self, data: dict, source: Path | None = None, cap_left: tuple[int, ...] | None = None):
      self.data = data
      self.source = source
      # 사용자 표 위에 겹쳐 남은 기본 표 칸(크기). None = 아직 아무 겹도 표를 안 적었다.
      self.cap_left = cap_left

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

      text = str(rel).replace("\\", "/")
      if text.startswith(PALETTES_PREFIX):
         # 접두가 있을 때만 환경변수 뿌리를 본다. 접두 없는 옛 프로필은 환경변수를 켜도 다른 파일을 안 집는다.
         root = palettes_root()
         if root is None:
            raise UsageError(f"ramps_file 이 {PALETTES_PREFIX} 로 시작하는데 {PALETTES_ENV} 가 꺼져 있다 : {rel}")
         target = safe_join(root, text[len(PALETTES_PREFIX):])
         if target.suffix.casefold() != ".json" or (target.exists() and not is_plain_file(target)):
            raise UsageError(f"{PALETTES_PREFIX} 램프는 링크 아닌 .json 파일이어야 한다 : {rel}")
         return target

      check_relative(rel)
      if self.source is not None:
         near = safe_join(resolve_root(self.source.parent), rel)
         if near.is_file():
            return near
      return safe_join(resolve_root(tool_home()), rel)

   def palette_roots(self, warnings: list | None = None) -> list[Path]:
      """램프 파일을 믿는 뿌리 셋 : 프로필 폴더 · 툴 폴더 · ARTTOOL_PALETTES(켰고 값이 맞을 때만).

      ARTTOOL_PALETTES 가 틀리면 그 뿌리만 빼고 warnings 에 경고를 남긴다 — $palettes/ 를 안 쓰는 일은 안 죽는다.
      """
      roots = [resolve_root(tool_home())]
      if self.source is not None:
         roots.insert(0, resolve_root(self.source.parent))
      env = gathered_palettes_root(warnings)
      if env is not None:
         roots.append(env)
      return roots

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
   preset = load_preset(str(preset_name))
   if "table_mode" in (((preset.get("check") or {}).get("warn") or {}).get("color_cap") or {}):
      # 프리셋 겹에는 table_mode 를 적용하지 않는다. 말없이 무시하지 않고 거절한다.
      raise ProfileError(f"프리셋은 check.warn.color_cap.table_mode 를 둘 수 없다 (프로필에 적는다) : {preset_name}")
   data = deep_merge(DEFAULTS, preset)
   base = data
   data = deep_merge(data, raw)
   cap_left = apply_table_mode(data, raw, base, None, source or "(인자)")
   if overrides and any(str(key).split(".")[-1] == "table_mode" for key in overrides):
      # 인자 겹에는 table_mode 가 닿지 않는다. 말없이 무시하지 않고 거절한다.
      raise UsageError("table_mode 는 인자로 바꿀 수 없다. 프로필 · 템플릿의 check.warn.color_cap 에 적는다")
   if overrides:
      data = apply_overrides(data, overrides)
   if name_or_path and "name" not in raw:
      data["name"] = Path(name_or_path).stem

   validate(data)
   return Profile(data, source, cap_left)


def cap_left_line(prof: Profile) -> str | None:
   """사용자 표 위에 기본 표 칸이 겹쳐 남았으면 알릴 한 줄. 없으면 None (설계 2-3)."""
   if not prof.cap_left:
      return None
   sizes = "·".join(str(k) for k in prof.cap_left)
   return f"색 한도 표 : 기본 표 {sizes} 가 겹쳐 남았다 (통째로 쓰려면 table_mode: replace)"


def show_lines(prof: Profile) -> list[str]:
   """profile show 가 덧붙이는 사람용 줄 : 색 한도 표 · 외곽선 받는 값 (설계 2-2 · 2-3)."""
   node = prof.warn("color_cap")
   table = " · ".join(f"{k}→{v}" for k, v in prof.color_cap_table().items())
   lines = [f"색 한도 표 : {table} ({node.get('table_mode', 'merge')})"]
   left = cap_left_line(prof)
   if left:
      lines.append(left)
   outline = prof.style.get("outline")
   accept = [a for a in prof.warn("outline").get("accept", []) if a != outline]
   tail = f" (+ 받기 {', '.join(accept)})" if accept else ""
   lines.append(f"외곽선 : {outline if outline is not None else '없음'}{tail}")
   return lines


def _cap_node(data: dict):
   node = ((data.get("check") or {}).get("warn") or {}).get("color_cap") if isinstance(data, dict) else None
   return node if isinstance(node, dict) else None


def apply_table_mode(merged: dict, layer: dict, below: dict, cap_left: tuple[int, ...] | None, where) -> tuple[int, ...] | None:
   """겹 하나(layer)를 아래(below) 위에 겹친 merged 에 table_mode 를 적용하고, 남은 기본 칸을 돌려준다 (설계 2-3).

   - replace : merged 의 표를 이 겹의 표로 통째 바꾼다. 남은 칸은 없다.
   - merge(없음) : deep_merge 가 이미 겹쳤다. 아래 표에서 이 겹이 안 덮은 칸이 남는다.
   - 이 겹에 표가 없으면 아무것도 안 바꾼다.
   """
   node = _cap_node(layer)
   if node is None or "table" not in node:
      if node is not None and node.get("table_mode") == "replace":
         raise ProfileError(f"check.warn.color_cap.table_mode: replace 는 같은 자리에 table 이 있어야 한다 - {where}")
      return cap_left
   if node.get("table_mode", "merge") == "replace":
      if isinstance(node["table"], dict):
         merged["check"]["warn"]["color_cap"]["table"] = copy.deepcopy(node["table"])
      return ()
   if not isinstance(node["table"], dict):
      return cap_left      # 꼴 틀림은 validate 가 막는다
   if cap_left is None:
      under = _cap_node(below) or {}
      cap_left = tuple(sorted(int(k) for k in (under.get("table") or {})))
   given = {int(k) for k in node["table"] if str(k).isdigit() or isinstance(k, int)}
   return tuple(k for k in cap_left if k not in given)


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
   _reject_unknown(raw, DEFAULTS, (), where)


def _reject_unknown_top(raw: dict, source: Path | None) -> None:
   reject_unknown(raw, source or "(인자)")


def _reject_unknown(raw: dict, allowed: dict, parts: tuple, where) -> None:
   """겹구조를 재귀로 훑어 DEFAULTS 에 없는 칸을 거절한다. 오타가 조용히 기본값으로 넘어가면 안 된다.

   자리는 글이 아니라 마디 튜플(parts)로 넘긴다. rig 이름에 점이 들어도(rigs.a.b) 한 마디로 맞추기 위해서다.
   """
   if _is_free(parts):
      return

   path = ".".join(parts)
   names = _allowed_names(allowed, parts)
   unknown = [] if path in ("anim", "rigs") else sorted(str(k) for k in raw if str(k) not in names)
   if unknown:
      spot = path or "맨 위"
      # YAML 1.1 은 on · off · yes · no 열쇠를 참거짓으로 읽는다. 오타보다 이쪽이 흔해 따로 알린다.
      hint = " — YAML 은 on · off · yes · no 를 참거짓으로 읽는다. 켜고 끄기는 enabled 칸이다" if any(isinstance(k, bool) for k in raw) else ""
      raise ProfileError(f"모르는 항목이 있다 : {', '.join(unknown)} ({spot}){hint} - {where}")

   for key, value in raw.items():
      if not isinstance(value, dict):
         continue
      default = allowed.get(str(key), {}) if path not in ("anim", "rigs") else {}
      if _is_rig(parts) and str(key) in ("anchors", "layer_order"):
         # 이름 목록 자리다. 예전엔 사전도 지나가 값은 버리고 열쇠만 읽혔다 — 조용한 오독이라 막는다.
         raise ProfileError(f"{_join(path, str(key))} 는 이름 목록 자리다. 사전을 둘 수 없다 - {where}")
      if str(key) in allowed and not isinstance(default, dict):
         # 스칼라 자리에 사전이 오면 여기서 막는다. 그냥 두면 validate · 사용처에서 TypeError 로 터진다.
         raise ProfileError(f"{_join(path, str(key))} 는 값 하나 자리다. 사전을 둘 수 없다 - {where}")
      _reject_unknown(value, _child_schema(allowed, path, str(key)), parts + (str(key),), where)


def _is_rig(parts: tuple) -> bool:
   """rigs 아래 rig 하나의 자리인가 (rig 이름에 점이 들어도 한 마디다)."""
   return len(parts) == 2 and parts[0] == "rigs"


def _is_free(parts: tuple) -> bool:
   """FREE_MAPS 무늬와 마디별로 맞춘다. 글자 그대로 비교하면 「*」 줄이 한 번도 안 맞는다."""
   for pattern in FREE_MAPS:
      pat = pattern.split(".")
      if len(pat) == len(parts) and all(a == "*" or a == b for a, b in zip(pat, parts)):
         return True
   return False


def _join(path: str, key: str) -> str:
   if not path:
      return key
   return f"{path}.{key}"


def _allowed_names(allowed: dict, parts: tuple) -> tuple[str, ...]:
   path = ".".join(parts)
   if path in ("anim", "rigs"):
      return ()
   if _is_rig(parts):
      return RIG_KEYS
   if path == "":
      return TOP_KEYS
   # 빈 사전 꼴이면 받을 칸이 없다는 뜻이다. 예전엔 () 가 「자유」 로 읽혀 무엇이든 지나갔다.
   return tuple(allowed) + OPTIONAL_KEYS.get(path, ())


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
   mode = warn["color_cap"].get("table_mode", "merge")
   if mode not in TABLE_MODES:
      raise ProfileError(f"{where}.color_cap.table_mode 는 {' · '.join(TABLE_MODES)} 중 하나다 : {mode}")

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
   report = node.get("report", "each")
   if report not in RAMP_REPORTS:
      raise ProfileError(f"{where}.report 는 {' · '.join(RAMP_REPORTS)} 중 하나다 : {report}")


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
