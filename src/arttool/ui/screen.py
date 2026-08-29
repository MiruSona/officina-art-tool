"""화면 정의 JSON 읽기와 검사. 1차는 일곱 종류만 받는다.

column · row · panel · label · button · icon · spacer
격자 · 스크롤 · 목록 · 전환은 2차다.

**값 검사는 여기 한 곳에서만 한다.** `id` 와 `bg` 는 USS 에 `#id` · `.bg-이름` 으로 그대로 들어가므로
이름 꼴을 여기서 막지 않으면 남이 쓴 화면 JSON 이 스타일 규칙을 새로 만들 수 있다.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..errors import ArtToolError
from ..jsonio import read_json

TYPES = ("column", "row", "panel", "label", "button", "icon", "spacer")
CONTAINERS = ("column", "row", "panel")
TEXT_TYPES = ("label", "button")
NODE_KEYS = ("id", "type", "bg", "text", "pad", "gap", "size", "grow", "children")
TOP_KEYS = ("screen", "root")

# USS 선택자·UXML 이름에 그대로 들어가는 값이라 글자를 좁힌다.
NAME_SHAPE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")


def check_name(value, what: str) -> str:
   if not isinstance(value, str):
      raise ArtToolError(f"{what} 은 문자열이어야 한다 : {value!r}")
   if not NAME_SHAPE.match(value):
      raise ArtToolError(f"{what} 은 영문자나 밑줄로 시작하고 영숫자·밑줄·붙임표만 쓴다 : {value!r}")
   return value


def load(path: str | Path) -> dict:
   data = read_json(path)
   unknown = sorted(str(k) for k in data if str(k) not in TOP_KEYS)
   if unknown:
      raise ArtToolError(f"화면 정의 맨 위에 모르는 칸이 있다 : {', '.join(unknown)}")
   if "root" not in data:
      raise ArtToolError(f"화면 정의에 root 가 없다 : {path}")
   if not data.get("screen"):
      raise ArtToolError(f"화면 정의에 screen 이름이 없다 : {path}")

   check_name(data["screen"], "screen 이름")
   validate(data["root"])
   return data


def walk(node: dict):
   yield node
   for child in node.get("children", []):
      yield from walk(child)


def validate(root: dict) -> dict:
   seen: set[str] = set()
   for node in walk(root):
      _check_node(node)
      node_id = node["id"]
      if node_id in seen:
         raise ArtToolError(f"화면 안에서 id 가 겹친다 : {node_id}")
      seen.add(node_id)
   return root


def _check_node(node: dict) -> None:
   if not isinstance(node, dict):
      raise ArtToolError(f"마디가 사전이 아니다 : {node}")

   unknown = sorted(set(node) - set(NODE_KEYS))
   if unknown:
      raise ArtToolError(f"모르는 칸이 있다 : {', '.join(unknown)}")
   if "id" not in node:
      raise ArtToolError(f"id 가 없는 마디가 있다 : {node}")
   check_name(node["id"], "id")

   kind = node.get("type")
   if kind not in TYPES:
      raise ArtToolError(f"모르는 type : {kind} (쓸 수 있는 것 : {' · '.join(TYPES)})")
   if node.get("children") and kind not in CONTAINERS:
      raise ArtToolError(f"{kind} 은 children 을 못 가진다 : {node['id']}")

   _check_text(node, kind)
   _check_bg(node)
   _check_pad(node)
   _check_size(node)
   _check_gap(node)
   _check_grow(node)


def _check_text(node: dict, kind: str) -> None:
   if node.get("text") is None:
      return
   if kind not in TEXT_TYPES:
      raise ArtToolError(f"text 는 label · button 만 갖는다 : {node['id']}")
   if not isinstance(node["text"], str):
      raise ArtToolError(f"text 는 문자열이어야 한다 : {node['id']}")


def _check_bg(node: dict) -> None:
   if node.get("bg") is None:
      return
   check_name(node["bg"], "bg 이름")


def _whole_number(value, node_id: str, what: str) -> int:
   if isinstance(value, bool) or not isinstance(value, int):
      raise ArtToolError(f"{what} 은 정수여야 한다 : {node_id} 의 {value!r}")
   if value < 0:
      raise ArtToolError(f"{what} 은 0 이상이어야 한다 : {node_id} 의 {value}")
   return value


def _check_pad(node: dict) -> None:
   pad = node.get("pad")
   if pad is None:
      return
   if isinstance(pad, (list, tuple)):
      if len(pad) != 4:
         raise ArtToolError(f"pad 는 정수 하나이거나 [상, 우, 하, 좌] 네 칸이다 : {node['id']}")
      for value in pad:
         _whole_number(value, node["id"], "pad")
      return
   _whole_number(pad, node["id"], "pad")


def _check_size(node: dict) -> None:
   size = node.get("size")
   if size is None or size == "auto":
      return
   if not isinstance(size, (list, tuple)) or len(size) != 2:
      raise ArtToolError(f"size 는 [가로, 세로] 또는 auto 다 : {node['id']}")
   for value in size:
      _whole_number(value, node["id"], "size")


def _check_gap(node: dict) -> None:
   if node.get("gap") is None:
      return
   _whole_number(node["gap"], node["id"], "gap")


def _check_grow(node: dict) -> None:
   if node.get("grow") is None:
      return
   if not isinstance(node["grow"], bool):
      raise ArtToolError(f"grow 는 참·거짓이어야 한다 : {node['id']} 의 {node['grow']!r}")


def check_backgrounds(root: dict, data: dict) -> None:
   """bg 이름이 매니페스트에 있는지 본다."""
   names = {entry["name"] for entry in data.get("frames", [])}
   missing = sorted({n["bg"] for n in walk(root) if n.get("bg") and n["bg"] not in names})
   if missing:
      raise ArtToolError(f"매니페스트에 없는 bg : {', '.join(missing)}")


def build(prof, spec_path, out_dir, manifest_path=None, assets_root=None):
   """화면 정의 하나를 UXML 과 USS 로 낸다."""
   from ..paths import resolve_root, safe_join, write_text
   from . import manifest as manifest_mod
   from . import uss as uss_mod
   from . import uxml as uxml_mod

   data = load(spec_path)
   root_node = data["root"]
   name = str(data["screen"])
   out_root = resolve_root(out_dir)

   found = _find_manifest(manifest_path, out_root)
   if found is not None:
      check_backgrounds(root_node, manifest_mod.load(found))

   where = uss_mod.check_assets_root(assets_root or uss_mod.ASSETS_ROOT)
   uxml_file = safe_join(out_root, f"{name}.uxml")
   uss_file = safe_join(out_root, f"{name}.uss")
   write_text(uxml_file, uxml_mod.to_uxml(root_node))
   write_text(uss_file, uss_mod.screen_uss(prof, root_node, where))

   return {
      "screen": name,
      "out": str(out_root),
      "files": [uxml_file.name, uss_file.name],
      "nodes": len(list(walk(root_node))),
      "bg_checked": found is not None,
   }


def _find_manifest(manifest_path, out_root: Path) -> Path | None:
   """--manifest 를 대놓고 줬는데 없으면 실패. 안 줬으면 out 폴더를 보고, 없으면 검사를 건너뛴다."""
   if manifest_path:
      wanted = Path(manifest_path)
      if not wanted.is_file():
         raise ArtToolError(f"매니페스트 파일이 없다 : {wanted}")
      return wanted

   near = out_root / "ui_manifest.json"
   if near.is_file():
      return near
   return None
