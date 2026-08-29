"""USS 조각 만들기.

`-unity-slice-scale` 은 반드시 적는다. 빠뜨리면 테두리가 사라지는데 원인을 찾기 어렵다.
값은 100 / ppu 다 (PPU 16 이면 6.25).
"""

from __future__ import annotations

import re

from ..errors import ArtToolError
from ..profile import Profile

ASSETS_ROOT = "/Assets/UI"

# USS 의 url("...") 안에 그대로 들어가는 값이라 따옴표·괄호·세미콜론이 끼면 규칙이 깨진다.
ROOT_SHAPE = re.compile(r"^[A-Za-z0-9_/.-]+$")


def check_assets_root(value: str) -> str:
   if not isinstance(value, str) or not ROOT_SHAPE.match(value):
      raise ArtToolError(f"assets_root 는 영숫자·/·_·-·. 만 쓴다 : {value!r}")
   return value


def slice_rule(entry: dict, atlas: str, slice_scale: float, assets_root: str = ASSETS_ROOT) -> str:
   check_assets_root(assets_root)
   name = entry["name"]
   left, bottom, right, top = entry["border"]
   min_w, min_h = entry["min_size"]
   return (
      f".bg-{name} {{\n"
      f'  background-image: url("{assets_root}/{atlas}#{name}");\n'
      f"  -unity-slice-left: {left};  -unity-slice-bottom: {bottom};\n"
      f"  -unity-slice-right: {right}; -unity-slice-top: {top};\n"
      f"  -unity-slice-scale: {slice_scale};   /* 100 / ppu. 안 적으면 테두리가 사라진다 */\n"
      f"  min-width: {min_w}px; min-height: {min_h}px;\n"
      f"}}\n"
   )


def bg_rules(data: dict, assets_root: str = ASSETS_ROOT) -> str:
   atlas = data.get("atlas", "ui_atlas.png")
   scale = data["slice_scale"]
   return "\n".join(slice_rule(e, atlas, scale, assets_root) for e in data.get("frames", []))


def font_url(prof: Profile, assets_root: str = ASSETS_ROOT) -> str:
   check_assets_root(assets_root)
   family = prof.ui["font"]["family"]
   return f'{assets_root}/Fonts/{family} SDF.asset'


def base_rules(prof: Profile, assets_root: str = ASSETS_ROOT) -> str:
   """어느 화면에나 같은 값. 화면마다 다른 여백·간격은 #id 규칙으로 나간다."""
   size = int(prof.ui["font"]["sizes_px"][0])
   return (
      ".ui-column { flex-direction: column; }\n"
      ".ui-row    { flex-direction: row; }\n"
      ".ui-panel  { flex-direction: column; }\n"
      ".ui-spacer { flex-grow: 1; }\n"
      ".ui-icon   { flex-shrink: 0; }\n"
      f'.ui-label  {{ -unity-font-definition: url("{font_url(prof, assets_root)}"); font-size: {size}px; }}\n'
      f'.ui-button {{ -unity-font-definition: url("{font_url(prof, assets_root)}"); font-size: {size}px; }}\n'
   )


def _pad_text(pad) -> str:
   if isinstance(pad, (list, tuple)):
      top, right, bottom, left = pad
      return f"padding: {top}px {right}px {bottom}px {left}px;"
   return f"padding: {pad}px;"


def node_rules(node: dict, parent_row: bool = False) -> list[str]:
   """한 마디의 #id 규칙. 여백·간격·크기·늘리기만 여기 적는다."""
   lines = []
   own = []
   if node.get("pad") is not None:
      own.append(_pad_text(node["pad"]))
   size = node.get("size")
   if isinstance(size, (list, tuple)):
      own.append(f"width: {int(size[0])}px; height: {int(size[1])}px;")
   if node.get("grow"):
      own.append("flex-grow: 1;")
   if own:
      lines.append("#" + node["id"] + " { " + " ".join(own) + " }\n")

   gap = node.get("gap")
   if gap:
      side = "margin-right" if node.get("type") == "row" else "margin-bottom"
      lines.append(f"#{node['id']} > * {{ {side}: {int(gap)}px; }}\n")
   return lines


def screen_rules(tree: dict) -> str:
   lines: list[str] = []
   for node in walk(tree):
      lines += node_rules(node)
   return "".join(lines)


def walk(node: dict):
   yield node
   for child in node.get("children", []):
      yield from walk(child)


def screen_uss(prof: Profile, tree: dict, assets_root: str = ASSETS_ROOT) -> str:
   return base_rules(prof, assets_root) + "\n" + screen_rules(tree)
