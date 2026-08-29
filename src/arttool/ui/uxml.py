"""화면 트리 → UXML.

UXML 은 배선을 안 담는다. 버튼 동작은 코드에서 Q<Button>("id").clicked += … 로 붙인다.
클래스 이름은 ui-<type> 과 bg-<프레임이름> 둘뿐이다.
"""

from __future__ import annotations

from xml.sax.saxutils import quoteattr

HEADER = '<ui:UXML xmlns:ui="UnityEngine.UIElements">'
FOOTER = "</ui:UXML>"

TAGS = {
   "column": "ui:VisualElement",
   "row": "ui:VisualElement",
   "panel": "ui:VisualElement",
   "spacer": "ui:VisualElement",
   "icon": "ui:VisualElement",
   "label": "ui:Label",
   "button": "ui:Button",
}


def class_of(node: dict) -> str:
   names = [f"ui-{node['type']}"]
   if node.get("bg"):
      names.append(f"bg-{node['bg']}")
   return " ".join(names)


def _attrs(node: dict) -> str:
   parts = [f"name={quoteattr(node['id'])}"]
   if node.get("text") is not None:
      parts.append(f"text={quoteattr(str(node['text']))}")
   parts.append(f"class={quoteattr(class_of(node))}")
   return " ".join(parts)


def _lines(node: dict, depth: int) -> list[str]:
   pad = "  " * depth
   tag = TAGS[node["type"]]
   children = node.get("children") or []
   if not children:
      return [f"{pad}<{tag} {_attrs(node)} />"]

   out = [f"{pad}<{tag} {_attrs(node)}>"]
   for child in children:
      out += _lines(child, depth + 1)
   out.append(f"{pad}</{tag}>")
   return out


def to_uxml(root: dict) -> str:
   return "\n".join([HEADER, *_lines(root, 1), FOOTER]) + "\n"
