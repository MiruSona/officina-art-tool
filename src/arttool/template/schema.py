"""템플릿 JSON 스키마 v1 — 찾기 · 읽기 · 검증 · 프리셋 · 크기 (설계 8-2 · 9-4 끝).

규칙
- 모르는 칸은 거절한다(프로필과 같은 규칙). kind 별로 받는 `values` · `presets` 칸은 처리기(`kinds`)가 정한다.
- JSON 에는 숫자 · 글자 · 목록 · 표만 둔다. 식이나 스크립트는 넣지 않는다 — 셈은 처리기 코드에 있다.
- `check` 칸은 프로필 꼴 그대로(+ 대조 값 `frames` · `size` · `colors`)라 `check --template` 이 겹치기만 하면 된다.
- `fixed` : 프로필보다 템플릿 값을 앞세울 점 경로. 템플릿 `check` 에 값이 있고 프로필 `DEFAULTS` 에도 있는 경로만.
- `must` : 최소 규칙 낱말(canvas · alpha · scale · palette). kind 기본 목록에 **더하기만** 한다.
"""

from __future__ import annotations

import copy
import re
from pathlib import Path

from .. import layerset
from ..errors import ArtToolError, ProfileError, UsageError
from ..jsonio import read_json
from ..profile import DEFAULTS, TOP_KEYS as PROFILE_TOP_KEYS, deep_merge, reject_unknown, tool_home, validate as validate_profile
from . import TemplateError
from .kinds import KINDS, handler

VERSION = 1
TEMPLATES_DIR = "templates"

TOP_KEYS = (
   "version", "name", "kind", "title", "sizes", "values", "frames", "presets", "default_preset",
   "check", "fixed", "must", "prompt", "steps", "sources", "layers",
)
REQUIRED = ("version", "name", "kind", "title", "sizes", "prompt", "steps", "sources")
MUST_WORDS = ("canvas", "alpha", "scale", "palette")
# check 칸 안에서 프로필에 없는 대조 값. check --template 이 따로 읽는다.
CHECK_EXTRA = ("frames", "size", "colors")
MAX_SIDE = 4096

NAME_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_\-]*$")
SIZE_RE = re.compile(r"^\s*(\d+)\s*[xX×]\s*(\d+)\s*$")
SIDE_RE = re.compile(r"^\s*(\d+)\s*$")


def templates_dir() -> Path:
   return tool_home() / TEMPLATES_DIR


def _fail(where, text: str) -> TemplateError:
   return TemplateError(f"템플릿이 잘못됐다 : {text} - {where}")


# ── 찾기 ─────────────────────────────────────────────


def find(name_or_path: str) -> Path:
   """이름이면 `templates/<이름>.json`, `.json` 경로면 그 파일. 이름은 경로 문자를 못 쓴다."""
   text = str(name_or_path)
   direct = Path(text)
   if direct.suffix.lower() == ".json":
      if not direct.is_file():
         raise UsageError(f"템플릿 파일이 없다 : {text}")
      return direct
   if not NAME_RE.match(text):
      raise UsageError(f"템플릿 이름은 영숫자 · _ · - 만 쓴다(경로는 .json 으로 준다) : {text}")
   candidate = templates_dir() / f"{text}.json"
   if not candidate.is_file():
      raise UsageError(f"템플릿을 못 찾았다 : {text} ({templates_dir()})")
   return candidate


def load(name_or_path: str) -> dict:
   """찾아 읽고 검증한다. 돌려주는 사전에는 `_source`(파일 경로)가 붙는다."""
   path = find(name_or_path)
   data = read_json(path)
   validate(data, path)
   out = copy.deepcopy(data)
   out["_source"] = str(path.resolve())
   return out


def list_all() -> list[dict]:
   """`templates/` 아래 템플릿 전부를 이름 순으로. 하나라도 틀리면 거절한다(틀린 파일을 숨기지 않는다)."""
   root = templates_dir()
   if not root.is_dir():
      return []
   out = []
   for path in sorted(root.glob("*.json")):
      out.append(load(str(path)))
   return out


# ── 크기 · 프리셋 ────────────────────────────────────


def parse_size(text: str) -> tuple[int, int]:
   """`WxH` 또는 숫자 하나(정사각, `32` = `32x32`)."""
   match = SIZE_RE.match(str(text))
   side = SIDE_RE.match(str(text))
   if match:
      width, height = int(match.group(1)), int(match.group(2))
   elif side:
      width = height = int(side.group(1))
   else:
      raise UsageError(f"--size 는 WxH 또는 숫자 하나(정사각)다 : {text}")
   if not (0 < width <= MAX_SIDE and 0 < height <= MAX_SIDE):
      raise UsageError(f"--size 는 1 ~ {MAX_SIDE} 이다 : {text}")
   return width, height


def preset_names(tpl: dict) -> list[str]:
   return list((tpl.get("presets") or {}).keys())


def default_preset(tpl: dict, size: tuple[int, int] | None) -> str | None:
   """`default_preset` 칸이 정한 그 크기의 기본 프리셋. 칸이 없거나 크기를 모르면 None(→ 첫 프리셋).

   글자 하나면 늘 그 프리셋, 크기 표면 `kinds.pick` 규칙("WxH" 가 먼저, 아니면 짧은 변)으로 고른다.
   """
   node = tpl.get("default_preset")
   if node is None:
      return None
   if isinstance(node, str):
      return node
   if size is None:
      return None
   from .kinds import pick
   return pick(node, size)


def _validate_default_preset(data: dict, where) -> None:
   node = data.get("default_preset")
   if node is None:
      return
   from .kinds import is_table
   names = set((data.get("presets") or {}).keys())
   values = [node] if isinstance(node, str) else (list(node.values()) if is_table(node) else None)
   if values is None:
      raise _fail(where, f"default_preset 는 프리셋 이름 또는 크기 표({{\"16\": \"sd\", \"48x64\": \"sd\"}})다 : {node!r}")
   bad = sorted({str(v) for v in values if v not in names})
   if bad:
      raise _fail(where, f"default_preset 에 없는 프리셋 : {', '.join(bad)} (있는 것 : {', '.join(names) or '없음'})")


def apply_preset(tpl: dict, preset: str | None) -> tuple[dict, str | None]:
   """프리셋을 골라 겹친 템플릿 사본과 고른 이름. 프리셋이 있는데 안 고르면 첫 프리셋.

   kind 의 `flat_presets` 가 참이면(cycle · motion · palette) 프리셋 칸은 전부 `values` 로 간다.
   아니면(effect 등) 프리셋 칸이 맨 위 칸을 덮는다 — `values` · `check` 는 깊게 겹친다.
   """
   presets = tpl.get("presets") or {}
   if not presets:
      if preset:
         raise UsageError(f"{tpl['name']} 에는 프리셋이 없다 : {preset}")
      return copy.deepcopy(tpl), None
   chosen = preset or next(iter(presets))
   if chosen not in presets:
      raise UsageError(f"{tpl['name']} 에 없는 프리셋 : {chosen} (있는 것 : {', '.join(presets)})")
   out = copy.deepcopy(tpl)
   node = presets[chosen]
   if handler(tpl["kind"]).flat_presets:
      out["values"] = deep_merge(out.get("values") or {}, node)
      return out, chosen
   for key, value in node.items():
      if key in ("values", "check") and isinstance(out.get(key), dict):
         out[key] = deep_merge(out[key], value)
      else:
         out[key] = copy.deepcopy(value)
   return out, chosen


def size_list(tpl: dict) -> list[tuple[int, int]]:
   return [(int(w), int(h)) for w, h in tpl["sizes"]]


# ── 검증 ─────────────────────────────────────────────


def _unknown(node: dict, allowed, spot: str, where) -> None:
   bad = sorted(str(k) for k in node if k not in allowed)
   if bad:
      raise _fail(where, f"모르는 칸 {', '.join(bad)} ({spot})")


def _str_list(value, spot: str, where) -> list[str]:
   if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
      raise _fail(where, f"{spot} 는 글자 목록이다 : {value!r}")
   return value


def _sizes(value, spot: str, where) -> None:
   ok = isinstance(value, list) and value
   for row in value if ok else []:
      good = isinstance(row, list) and len(row) == 2
      good = good and all(isinstance(v, int) and not isinstance(v, bool) and 0 < v <= MAX_SIDE for v in row)
      if not good:
         ok = False
   if not ok:
      raise _fail(where, f"{spot} 는 [너비, 높이] 양의 정수 쌍 목록이고 비면 안 된다 : {value!r}")


def _dig(node: dict, dotted: str):
   """점 경로 값. 없으면 KeyError."""
   cur = node
   for part in dotted.split("."):
      if not isinstance(cur, dict) or part not in cur:
         raise KeyError(dotted)
      cur = cur[part]
   return cur


def validate_check(check, where, spot: str = "check") -> None:
   """프로필 꼴 부분은 프로필 검증 함수로, 대조 값은 여기서 본다."""
   if not isinstance(check, dict):
      raise _fail(where, f"{spot} 는 사전이다")
   _unknown(check, tuple(PROFILE_TOP_KEYS) + CHECK_EXTRA, spot, where)
   part = {k: v for k, v in check.items() if k not in CHECK_EXTRA}
   try:
      reject_unknown(part, f"{where} ({spot})")
      validate_profile(deep_merge(DEFAULTS, part))
   except ProfileError as exc:
      raise _fail(where, f"{spot} 의 프로필 꼴 칸 : {exc}") from exc
   frames = check.get("frames")
   if frames is not None and (not isinstance(frames, int) or isinstance(frames, bool) or frames <= 0):
      raise _fail(where, f"{spot}.frames 는 양의 정수다 : {frames!r}")
   if "size" in check:
      _sizes([check["size"]], f"{spot}.size", where)
   colors = check.get("colors")
   if colors is not None and (not isinstance(colors, int) or isinstance(colors, bool) or colors <= 0):
      raise _fail(where, f"{spot}.colors 는 양의 정수다 : {colors!r}")


def _validate_fixed(data: dict, where) -> None:
   fixed = _str_list(data.get("fixed", []), "fixed", where)
   check = data.get("check") or {}
   for dotted in fixed:
      try:
         _dig(check, dotted)
      except KeyError:
         raise _fail(where, f"fixed 의 {dotted} 는 템플릿 check 칸에 값이 없다") from None
      try:
         _dig(DEFAULTS, dotted)
      except KeyError:
         raise _fail(where, f"fixed 의 {dotted} 는 프로필에 없는 칸이다") from None


def _validate_layers(data: dict, kind, where) -> None:
   rows = data.get("layers")
   if not kind.has_layers:
      if rows not in (None, []):
         raise _fail(where, f"kind {data['kind']} 는 그림이 아니라 layers 를 안 둔다")
      return
   if rows is None:
      raise _fail(where, "layers 칸이 없다 (겹 구성 10-3)")
   try:
      layerset.from_dict({"version": 1, "canvas": [1, 1], "layers": rows}, where)
   except ArtToolError as exc:
      raise _fail(where, f"layers : {exc}") from exc


def validate(data, where="(사전)") -> None:
   """템플릿 사전 하나를 검증한다. 틀리면 TemplateError."""
   if not isinstance(data, dict):
      raise _fail(where, "맨 위는 사전이다")
   _unknown(data, TOP_KEYS, "맨 위", where)
   missing = [k for k in REQUIRED if k not in data]
   if missing:
      raise _fail(where, f"꼭 있어야 할 칸이 없다 : {', '.join(missing)}")
   if data["version"] != VERSION:
      raise _fail(where, f"version 은 {VERSION} 이다 : {data['version']!r}")
   if not isinstance(data["name"], str) or not NAME_RE.match(data["name"]):
      raise _fail(where, f"name 은 영숫자 · _ · - 만 쓴다 : {data['name']!r}")
   if data["kind"] not in KINDS:
      raise _fail(where, f"kind 는 {' · '.join(KINDS)} 중 하나다 : {data['kind']!r}")
   kind = handler(data["kind"])
   for key in ("title", "prompt"):
      if not isinstance(data[key], str) or not data[key].strip():
         raise _fail(where, f"{key} 는 빈칸 아닌 글자다")
   _str_list(data["steps"], "steps", where)
   _str_list(data["sources"], "sources", where)
   _sizes(data["sizes"], "sizes", where)

   values = data.get("values", {})
   if not isinstance(values, dict):
      raise _fail(where, "values 는 사전이다")
   _unknown(values, kind.value_keys, "values", where)

   if "frames" in data and not kind.frames_field:
      raise _fail(where, f"kind {data['kind']} 는 frames 칸을 안 쓴다")
   if kind.frames_field and "frames" in data:
      kind.validate_frames(data["frames"], where)

   presets = data.get("presets", {})
   if not isinstance(presets, dict):
      raise _fail(where, "presets 는 「이름 : 값」 사전이다")
   for pname, node in presets.items():
      if not NAME_RE.match(str(pname)) or not isinstance(node, dict):
         raise _fail(where, f"presets.{pname} 는 이름 규칙에 맞는 사전이어야 한다")
      spot = f"presets.{pname}"
      if kind.flat_presets:
         _unknown(node, kind.value_keys, spot, where)
         continue
      _unknown(node, ("sizes", "values", "frames", "check", "title", "prompt", "steps", "layers"), spot, where)
      if "layers" in node:
         # 프리셋이 겹 구성을 바꿀 수 있다 (예 bg_screen indoor : 천장 · 벽 · 바닥)
         _validate_layers({"kind": data["kind"], "layers": node["layers"]}, kind, f"{where} ({spot})")
      if "steps" in node:
         _str_list(node["steps"], f"{spot}.steps", where)
      if "sizes" in node:
         _sizes(node["sizes"], f"{spot}.sizes", where)
      if "values" in node:
         if not isinstance(node["values"], dict):
            raise _fail(where, f"{spot}.values 는 사전이다")
         _unknown(node["values"], kind.value_keys, f"{spot}.values", where)
      if "frames" in node:
         kind.validate_frames(node["frames"], where)
      if "check" in node:
         validate_check(node["check"], where, f"{spot}.check")
   _validate_default_preset(data, where)
   if kind.needs_frames and "frames" not in data and not all("frames" in n for n in presets.values()):
      raise _fail(where, f"kind {data['kind']} 는 frames 가 있어야 한다 (맨 위 또는 모든 프리셋에)")

   if "check" in data:
      validate_check(data["check"], where)
   _validate_fixed(data, where)

   must = _str_list(data.get("must", []), "must", where)
   bad = [m for m in must if m not in MUST_WORDS]
   if bad:
      raise _fail(where, f"must 낱말은 {' · '.join(MUST_WORDS)} 뿐이다 : {', '.join(bad)}")
   _validate_layers(data, kind, where)

   # 프리셋마다 값까지 처리기가 읽어 본다 — 틀린 숫자는 render 때가 아니라 지금 잡는다.
   for pname in presets or [None]:
      resolved, _ = apply_preset(data, pname)
      kind.validate_values(resolved, where)


def effective_must(tpl: dict) -> list[str]:
   """kind 기본 목록 ∪ 템플릿 must. 「최소」라서 빼지는 못한다. 순서는 MUST_WORDS 순.

   kind 가 없으면(손으로 쓴 작은 template.json) 템플릿 must 만 본다.
   """
   base = handler(tpl["kind"]).must_default if tpl.get("kind") else ()
   wanted = set(base) | set(tpl.get("must") or [])
   return [w for w in MUST_WORDS if w in wanted]


# ── render 결과 읽기 (check --template · layers · draw 가 쓴다) ──


def _rendered_size(data: dict) -> tuple[int, int] | None:
   """고른 크기. `size` 가 [w, h] · "WxH" 꼴이면 그것, 없고 `sizes` 가 하나뿐이면 그것."""
   size = data.get("size")
   if size is None and isinstance(data.get("sizes"), list) and len(data["sizes"]) == 1:
      size = data["sizes"][0]
   if isinstance(size, str):
      match = SIZE_RE.match(size)
      size = [match.group(1), match.group(2)] if match else None
   if isinstance(size, (list, tuple)) and len(size) == 2:
      try:
         return int(size[0]), int(size[1])
      except (TypeError, ValueError):
         pass
   return None


def read_rendered(path: str | Path) -> dict:
   """`template render` 가 쓴 `template.json`(= `template show` 사전)을 읽어 검증하고 쓰기 좋게 추린다.

   원본 템플릿(`templates/*.json`)과 꼴이 다르다 — 크기는 고른 하나(`size`), 값은 크기 표를 고른 뒤,
   `check` 에는 프로필 값 · 대조 값(frames · size · colors)이 이미 겹쳐 있다.
   틀리면 UsageError(종료 2) — 사람이 `--template` 으로 준 파일이라서.
   돌려주는 것 : path · name · kind · size · check(프로필 꼴만) · compare(대조 값) · fixed · must · profile_applied · data(원본 사전)
   """
   file = Path(path)
   data = read_json(file)
   if not isinstance(data, dict):
      raise UsageError(f"템플릿 JSON 맨 위는 사전이어야 한다 : {file}")
   kind = data.get("kind")
   if kind is not None and kind not in KINDS:
      raise UsageError(f"템플릿 kind 를 모른다 : {kind} (쓸 수 있는 것 : {' · '.join(KINDS)}) - {file}")
   check = data.get("check") or {}
   try:
      validate_check(check, file)
      must = _str_list(data.get("must") or [], "must", file)
      fixed = _str_list(data.get("fixed") or [], "fixed", file)
   except TemplateError as exc:
      raise UsageError(str(exc)) from exc
   bad = [w for w in must if w not in MUST_WORDS]
   if bad:
      raise UsageError(f"템플릿 must 의 낱말은 {' · '.join(MUST_WORDS)} 뿐이다 : {', '.join(bad)} - {file}")
   for dotted in fixed:
      try:
         _dig(check, dotted)
      except KeyError:
         raise UsageError(f"템플릿 fixed 의 {dotted} 가 check 칸에 값이 없다 - {file}") from None

   layer = {k: copy.deepcopy(v) for k, v in check.items() if k not in CHECK_EXTRA}
   compare = {k: copy.deepcopy(check[k]) for k in CHECK_EXTRA if k in check}
   values = data.get("values") or {}
   if "colors" not in compare and isinstance(values, dict) and "colors" in values:
      compare["colors"] = values["colors"]
   return {
      "path": str(file),
      "name": data.get("name"),
      "kind": kind,
      "size": _rendered_size(data),
      "layer": layer,
      "compare": compare,
      "fixed": list(fixed),
      "must": effective_must({"kind": kind, "must": must}),
      "profile_applied": bool(data.get("profile_applied")),
      "data": data,
   }
