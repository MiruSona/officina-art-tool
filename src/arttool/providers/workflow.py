"""ComfyUI 워크플로 JSON 읽기 · API 꼴 검사 · 자리표시 채우기.

자리표시는 값이 문자열 통째로 `"$이름"` 인 칸만이다. 규칙은 설계 문서 3절(`Docs/Design/2026-10-07-provider-local설계.md`).
"""

from __future__ import annotations

import copy
import json
import re
from importlib import resources
from pathlib import Path

from ..errors import UsageError

# 제공자가 늘 채우는 자리. 이 밖의 자리는 설정 models 의 키다 (예 $unet $lora)
BASE_PLACEHOLDERS = ("prompt", "negative", "seed", "width", "height", "image", "mask")
BUILTIN = {"prop": "klein_prop.json", "inpaint": "klein_inpaint.json"}

_PLACEHOLDER = re.compile(r"^\$([A-Za-z_][A-Za-z0-9_]*)$")


def load_builtin(kind: str) -> dict:
   if kind not in BUILTIN:
      raise UsageError(f"{kind} 에는 내장 워크플로 본보기가 없다 (있는 것 : {', '.join(BUILTIN)})")
   text = resources.files("arttool.providers").joinpath("workflows", BUILTIN[kind]).read_text(encoding="utf-8")
   return check_api_form(json.loads(text), BUILTIN[kind])


def load_file(path: str | Path) -> dict:
   wanted = Path(path)
   if not wanted.is_file():
      raise UsageError(f"워크플로 파일이 없다 : {wanted.name}")
   try:
      data = json.loads(wanted.read_text(encoding="utf-8-sig"))   # 메모장이 붙이는 BOM 도 받는다
   except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
      raise UsageError(f"워크플로 파일이 JSON 이 아니다 : {wanted.name} ({exc})") from None
   return check_api_form(data, wanted.name)


def check_api_form(data, name: str = "워크플로") -> dict:
   """최상위가 「노드 id → {class_type, inputs}」 인지 본다. 화면 저장 꼴(nodes · links)은 거절한다."""
   if isinstance(data, dict) and "nodes" in data and "links" in data:
      raise UsageError(f"{name} 는 화면 저장 꼴이다. ComfyUI 에서 API 꼴로 내보내라 (Export (API))")
   if not isinstance(data, dict) or not data:
      raise UsageError(f"{name} 는 API 꼴 워크플로가 아니다 (노드 id → class_type · inputs)")
   for node_id, node in data.items():
      if not isinstance(node, dict):
         raise UsageError(f"{name} 의 노드 {node_id} 가 객체가 아니다")
      if not isinstance(node.get("class_type"), str) or not isinstance(node.get("inputs"), dict):
         raise UsageError(f"{name} 의 노드 {node_id} 에 class_type · inputs 가 없다")
   return data


def placeholders(workflow: dict) -> set[str]:
   """노드 inputs 안의 자리표시 이름들. 채우기 전 본보기에서 센다 — 사용자 프롬프트의 $ 를 자리로 오인하지 않게."""
   found = set()
   for node in workflow.values():
      _collect(node["inputs"], found)
   return found


def fill(workflow: dict, values: dict) -> dict:
   """자리표시를 값으로 바꾼 사본을 돌려준다. 값이 없는 자리가 있으면 종료 2."""
   missing = sorted(placeholders(workflow) - set(values))
   if missing:
      names = ", ".join(f"${name}" for name in missing)
      raise UsageError(f"채울 값이 없다 : {names} (설정 models 에 넣는다)")
   filled = copy.deepcopy(workflow)
   for node in filled.values():
      node["inputs"] = _replace(node["inputs"], values)
   return filled


def class_types(workflow: dict) -> list[str]:
   return sorted({node["class_type"] for node in workflow.values()})


def save_nodes(workflow: dict) -> list[str]:
   """SaveImage 노드 id 를 id 순으로. 숫자 id 는 숫자 크기대로 놓는다."""
   ids = [node_id for node_id, node in workflow.items() if node["class_type"] == "SaveImage"]
   return sorted(ids, key=_id_order)


def _id_order(node_id: str) -> tuple:
   if node_id.isdigit():
      return (0, int(node_id), "")
   return (1, 0, node_id)


def _collect(value, found: set[str]) -> None:
   if isinstance(value, str):
      match = _PLACEHOLDER.match(value)
      if match:
         found.add(match.group(1))
   elif isinstance(value, dict):
      for item in value.values():
         _collect(item, found)
   elif isinstance(value, list):
      for item in value:
         _collect(item, found)


def _replace(value, values: dict):
   if isinstance(value, str):
      match = _PLACEHOLDER.match(value)
      if match:
         return values[match.group(1)]
      return value
   if isinstance(value, dict):
      return {key: _replace(item, values) for key, item in value.items()}
   if isinstance(value, list):
      return [_replace(item, values) for item in value]
   return value
