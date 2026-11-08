"""도형 명세 틀(template) — 틀 파일 하나 + 짧은 값으로 보통 명세를 펼친다 (도형 렌더러 설계 2-5절).

명세 파일이 `{"template": "<틀 파일>", "preset": "<묶음>", "params": {...}}` 꼴이면 `expand()` 가
틀을 읽어 값을 끼워 넣고, `spec.parse()` 가 읽는 보통 명세 사전을 돌려준다.

틀 파일 :

    {
      "template_version": 1,
      "params":  { "skin": {"type": "color", "default": "#C9BCA6"},
                   "light": {"type": "color", "default": {"$shade": "$skin", "steps": 6, "base": 3, "pick": 4}},
                   "filling": {"type": "choice", "choices": ["none", "redbean"], "default": "none"},
                   "sesame": {"type": "bool", "default": false} },
      "presets": { "mugwort": {"skin": "#4C7433"} },
      "spec":    { ... 보통 명세, 값 자리에 "$skin" · {"$shade": …} · {"$mix": …} · 목록 칸에 "$if" ... }
    }

틀 안 식 :

- `"$이름"` (문자열 전체) → 그 값. 값 기본에도 쓸 수 있다(앞에 적은 값만).
- `{"$shade": 색, "steps": n, "base": i, "pick": k}` → `palette.shade(색, n, base_index=i)[k]`.
- `{"$mix": [색 a, 색 b, t]}` → a 와 b 를 RGB 로 t 만큼 섞은 색 (t 0 = a, 1 = b).
- `{"$add": [a, b, …]}` · `{"$sub": [a, b]}` · `{"$mul": [a, b, …]}` → 수 셈. 부품 크기 값에서 자리를 셀 때 쓴다 (2-6절).
- 사전에 `"$if": 조건` 이 있으면 조건이 거짓일 때 그 사전을 통째로 뺀다(목록 칸이면 그 칸, 사전 값이면 그 키).
  조건은 `"이름"`(참이면 — choice 값 "none" 은 거짓으로 본다) · `"!이름"`(거짓이면) · `{"이름": 값}`(같으면) · `{"이름": [값, …]}`(그중 하나면).

값 차례 : 틀 기본 < preset < 명세 params. 모르는 이름 · 틀린 꼴은 어느 칸인지 한 줄로 `ArtToolError`.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from ..errors import ArtToolError
from ..jsonio import read_json
from ..palette import parse_hex, shade, to_hex

TEMPLATE_VERSION = 1
TYPES = ("color", "bool", "choice", "number", "text")
_REF = re.compile(r"^\$([A-Za-z_][A-Za-z0-9_]*)$")


def is_template_spec(data) -> bool:
   return isinstance(data, dict) and "template" in data


def _err(where: str, msg: str) -> ArtToolError:
   return ArtToolError(f"틀 {where} : {msg}")


def _check(name: str, decl: dict, value, where: str):
   """값 하나를 선언 type 에 맞나 보고, 색은 #RRGGBB 대문자로 고른다."""
   kind = decl.get("type", "text")
   if kind == "color":
      if not isinstance(value, str):
         raise _err(where, f"{name} 는 #RRGGBB 색이다 : {value!r}")
      try:
         return to_hex(parse_hex(value))
      except ArtToolError as exc:
         raise _err(where, f"{name} : {exc}") from None
   if kind == "bool":
      if not isinstance(value, bool):
         raise _err(where, f"{name} 는 true / false 다 : {value!r}")
      return value
   if kind == "choice":
      choices = decl.get("choices") or []
      if value not in choices:
         raise _err(where, f"{name} 는 {' · '.join(map(str, choices))} 중 하나다 : {value!r}")
      return value
   if kind == "number":
      if isinstance(value, bool) or not isinstance(value, (int, float)):
         raise _err(where, f"{name} 는 수다 : {value!r}")
      return value
   if not isinstance(value, str):
      raise _err(where, f"{name} 는 글자다 : {value!r}")
   return value


def _color_of(value, where: str) -> tuple[int, int, int]:
   if not isinstance(value, str):
      raise _err(where, f"색 자리에 색이 아닌 값 : {value!r}")
   try:
      return parse_hex(value)
   except ArtToolError as exc:
      raise _err(where, str(exc)) from None


def _int_field(node: dict, key: str, where: str, default: int | None = None) -> int:
   value = node.get(key, default)
   if isinstance(value, bool) or not isinstance(value, int):
      raise _err(f"{where}.{key}", f"정수다 : {value!r}")
   return value


def _cond(cond, values: dict, where: str) -> bool:
   if isinstance(cond, bool):
      return cond
   if isinstance(cond, str):
      neg = cond.startswith("!")
      name = cond[1:] if neg else cond
      if name not in values:
         raise _err(where, f"$if 에 모르는 이름 : {name!r}")
      return (not values[name]) if neg else bool(values[name] and values[name] != "none")
   if isinstance(cond, dict) and cond:
      for name, want in cond.items():
         if name not in values:
            raise _err(where, f"$if 에 모르는 이름 : {name!r}")
         ok = values[name] in want if isinstance(want, list) else values[name] == want
         if not ok:
            return False
      return True
   raise _err(where, f"$if 는 \"이름\" · \"!이름\" · {{이름: 값}} 이다 : {cond!r}")


def _fill(node, values: dict, where: str):
   """틀 조각 하나를 펼친다. `$if` 가 거짓인 사전은 `_DROP` 을 돌려 위에서 뺀다."""
   if isinstance(node, str):
      m = _REF.match(node)
      if not m:
         return node
      if m.group(1) not in values:
         raise _err(where, f"모르는 값 이름 : {node}")
      return values[m.group(1)]
   if isinstance(node, list):
      out = []
      for i, item in enumerate(node):
         got = _fill(item, values, f"{where}[{i}]")
         if got is not _DROP:
            out.append(got)
      return out
   if not isinstance(node, dict):
      return node
   if "$if" in node and not _cond(node["$if"], values, f"{where}.$if"):
      return _DROP
   if "$shade" in node:
      base = _color_of(_fill(node["$shade"], values, f"{where}.$shade"), f"{where}.$shade")
      steps = _int_field(node, "steps", where, 4)
      pick = _int_field(node, "pick", where)
      try:
         ramp = shade(base, steps, base_index=node.get("base"))
      except ArtToolError as exc:
         raise _err(where, str(exc)) from None
      if not 0 <= pick < len(ramp):
         raise _err(f"{where}.pick", f"램프 칸 0 ~ {len(ramp) - 1} 이다 : {pick}")
      return to_hex(ramp[pick])
   if "$mix" in node:
      parts = node["$mix"]
      if not isinstance(parts, list) or len(parts) != 3:
         raise _err(f"{where}.$mix", "[색 a, 색 b, t] 다")
      a = _color_of(_fill(parts[0], values, f"{where}.$mix[0]"), f"{where}.$mix[0]")
      b = _color_of(_fill(parts[1], values, f"{where}.$mix[1]"), f"{where}.$mix[1]")
      t = _fill(parts[2], values, f"{where}.$mix[2]")
      if isinstance(t, bool) or not isinstance(t, (int, float)) or not 0 <= t <= 1:
         raise _err(f"{where}.$mix[2]", f"0 ~ 1 수다 : {t!r}")
      return to_hex(tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3)))
   for op in _MATH:
      if op in node:
         return _math(op, node[op], values, f"{where}.{op}")
   out = {}
   for key, value in node.items():
      if key == "$if":
         continue
      got = _fill(value, values, f"{where}.{key}")
      if got is not _DROP:
         out[key] = got
   return out


_MATH = ("$add", "$sub", "$mul")


def _math(op: str, parts, values: dict, where: str) -> float:
   """`{"$add": [a, b, …]}` · `{"$sub": [a, b]}` · `{"$mul": [a, b, …]}` — 수 셈 (부품 크기를 값으로 받으려고, 2-6절)."""
   if not isinstance(parts, list) or len(parts) < 2 or (op == "$sub" and len(parts) != 2):
      raise _err(where, "[a, b] 수 목록이다" + (" (둘)" if op == "$sub" else ""))
   nums = []
   for i, item in enumerate(parts):
      got = _fill(item, values, f"{where}[{i}]")
      if isinstance(got, bool) or not isinstance(got, (int, float)):
         raise _err(f"{where}[{i}]", f"수다 : {got!r}")
      nums.append(got)
   if op == "$add":
      return sum(nums)
   if op == "$sub":
      return nums[0] - nums[1]
   out = 1
   for n in nums:
      out *= n
   return out


class _Drop:
   def __repr__(self) -> str:
      return "<빼기>"


_DROP = _Drop()


def resolve_params(template: dict, preset: str | None, given: dict, where: str = "명세") -> dict:
   """틀 기본 < preset < 명세 params 차례로 값을 정한다. 기본 식은 앞에 정한 값을 쓸 수 있다."""
   decls = template.get("params")
   if not isinstance(decls, dict):
      raise _err("params", "이름 → {type, default} 사전이다")
   presets = template.get("presets") or {}
   if preset is not None and preset not in presets:
      raise _err(f"{where}.preset", f"없는 묶음 : {preset!r} (있는 것 : {' · '.join(presets) or '없음'})")
   chosen = dict(presets.get(preset) or {})
   if not isinstance(given, dict):
      raise _err(f"{where}.params", "이름 → 값 사전이다")
   chosen.update(given)
   unknown = sorted(set(chosen) - set(decls))
   if unknown:
      raise _err(f"{where}.params", f"틀에 없는 이름 : {', '.join(unknown)}")
   values: dict = {}
   for name, decl in decls.items():
      if not isinstance(decl, dict) or decl.get("type", "text") not in TYPES:
         raise _err(f"params.{name}", f"{{type: {' | '.join(TYPES)}, default}} 이다")
      if name in chosen:
         raw = chosen[name]
         raw = _fill(raw, values, f"{where}.params.{name}") if isinstance(raw, (str, dict)) else raw
      elif "default" in decl:
         raw = _fill(decl["default"], values, f"params.{name}.default")
      else:
         raise _err(f"{where}.params", f"{name} 는 꼭 줘야 한다 (기본 없음)")
      values[name] = _check(name, decl, raw, f"{where}.params.{name}")
   return values


def expand_template(template: dict, preset: str | None = None, params: dict | None = None,
                    where: str = "명세") -> dict:
   """틀 사전 + 값 → 보통 명세 사전."""
   if not isinstance(template, dict):
      raise _err("맨 위", "사전이다")
   if template.get("template_version", TEMPLATE_VERSION) != TEMPLATE_VERSION:
      raise _err("template_version", f"{TEMPLATE_VERSION} 만 읽는다 : {template.get('template_version')!r}")
   body = template.get("spec")
   if not isinstance(body, dict):
      raise _err("spec", "펼칠 명세 사전이 있어야 한다")
   values = resolve_params(template, preset, params or {}, where)
   return _fill(body, values, "spec")


def expand(data: dict, base_dir: str | os.PathLike = ".", where: str = "명세") -> dict:
   """`{"template", "preset"?, "params"?}` 명세 → 보통 명세 사전. 틀 경로는 명세 파일 폴더 기준이다."""
   extra = sorted(set(data) - {"template", "preset", "params", "note", "texture"})
   if extra:
      raise _err(where, f"틀 명세에는 template · preset · params · note · texture 만 둔다 : {', '.join(extra)}")
   ref = data["template"]
   if not isinstance(ref, str) or not ref:
      raise _err(f"{where}.template", f"틀 파일 경로다 : {ref!r}")
   file = Path(ref)
   if not file.is_absolute():
      file = Path(base_dir) / file
   if not file.is_file():
      raise _err(f"{where}.template", f"틀 파일이 없다 : {file}")
   template = read_json(file)
   if is_template_spec(template):
      raise _err(str(file), "틀이 다른 틀을 가리킬 수는 없다")
   preset = data.get("preset")
   if preset is not None and not isinstance(preset, str):
      raise _err(f"{where}.preset", f"묶음 이름이다 : {preset!r}")
   out = expand_template(template, preset, data.get("params") or {}, where)
   if "texture" in data:
      # 질감은 틀 밖에서 붙인다 — 모양(틀 값)은 그대로 두고 질감만 더할 수 있게.
      out = {**out, "texture": data["texture"]}
   return out
