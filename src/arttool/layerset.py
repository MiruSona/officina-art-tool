"""겹 묶음 꼴 — `layers.json` 읽기 · 쓰기 · 검증 (2026-10-04 개선 설계 10-2).

겹 묶음 = 폴더 하나 :

    set/
      layers.json          겹 목록 (이름 · 순서 · 종류)
      body/idle.png        <겹>/<그림>.png
      hair/idle.png

`split` · `layers` 묶음 명령 · `arttool.draw.Canvas` · `template render` 가 같이 쓰는 약속이라 여기 한 곳에 둔다.
그림 픽셀은 다루지 않는다(읽기 도우미 `read_item` 만). 쌓기 · 검사는 쓰는 쪽 몫이다.

- `layers` 순서 = 아래에서 위로 쌓는 순서.
- `exclusive_with` : 같은 칸을 칠하면 안 되는 짝. 한쪽에만 적어도 양쪽 짝으로 본다.
- `optional` : 비어도 경고하지 않는 겹.
- 모르는 칸은 거절한다(프로필과 같은 규칙).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import image
from .errors import ArtToolError
from .jsonio import read_json, write_json
from .paths import resolve_root, safe_join

VERSION = 1
FILE_NAME = "layers.json"

# 10-3 표의 낱말. 검사 · 마스크 · 내보내기가 읽는다.
KINDS = (
   "body", "cloth", "face", "hair", "deco",     # 캐릭터
   "base", "structure", "front",                # 배경 (deco 같이 씀)
   "frame", "fill", "content", "badge",         # UI · 아이콘
   "variant",                                   # 타일 (base 같이 씀)
   "fx",                                        # 이펙트 · 움직임
)

TOP_KEYS = ("version", "canvas", "layers", "items", "template")
LAYER_KEYS = ("name", "kind", "exclusive_with", "optional")

# 겹 · 그림 이름은 폴더 · 파일 이름이 되므로 좁게 받는다.
NAME_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_\-]*$")


@dataclass(frozen=True)
class Layer:
   name: str
   kind: str
   exclusive_with: tuple[str, ...] = ()
   optional: bool = False

   def to_dict(self) -> dict:
      out: dict = {"name": self.name, "kind": self.kind}
      if self.exclusive_with:
         out["exclusive_with"] = list(self.exclusive_with)
      if self.optional:
         out["optional"] = True
      return out


@dataclass
class LayerSet:
   canvas: tuple[int, int]
   layers: list[Layer]
   items: list[str] = field(default_factory=list)
   template: str | None = None

   def names(self) -> list[str]:
      return [layer.name for layer in self.layers]

   def layer(self, name: str) -> Layer:
      for layer in self.layers:
         if layer.name == name:
            return layer
      raise ArtToolError(f"겹 묶음에 없는 겹 : {name}")

   def exclusive_pairs(self) -> list[tuple[str, str]]:
      """같은 칸을 칠하면 안 되는 짝. 쌓는 순서(아래 → 위)로 적고 겹치지 않게 한 번씩."""
      order = {name: i for i, name in enumerate(self.names())}
      pairs = set()
      for layer in self.layers:
         for other in layer.exclusive_with:
            pairs.add(tuple(sorted((layer.name, other), key=order.__getitem__)))
      return sorted(pairs, key=lambda p: (order[p[0]], order[p[1]]))

   def to_dict(self) -> dict:
      out: dict = {
         "version": VERSION,
         "canvas": [self.canvas[0], self.canvas[1]],
         "layers": [layer.to_dict() for layer in self.layers],
         "items": list(self.items),
      }
      if self.template is not None:
         out["template"] = self.template
      return out


def _fail(where, text: str) -> ArtToolError:
   return ArtToolError(f"겹 묶음이 잘못됐다 : {text} - {where}")


def _check_name(value, what: str, where) -> str:
   if not isinstance(value, str) or not NAME_RE.match(value):
      raise _fail(where, f"{what} 이름은 영숫자 · _ · - 만 쓴다 : {value!r}")
   return value


def _unknown(node: dict, allowed: tuple[str, ...], spot: str, where) -> None:
   bad = sorted(str(k) for k in node if k not in allowed)
   if bad:
      raise _fail(where, f"모르는 칸 {', '.join(bad)} ({spot})")


def _canvas(value, where) -> tuple[int, int]:
   ok = isinstance(value, (list, tuple)) and len(value) == 2
   ok = ok and all(isinstance(v, int) and not isinstance(v, bool) and v > 0 for v in value)
   if not ok:
      raise _fail(where, f"canvas 는 [너비, 높이] 양의 정수 두 칸이다 : {value}")
   return int(value[0]), int(value[1])


def _layer(node, where) -> Layer:
   if not isinstance(node, dict):
      raise _fail(where, f"겹 한 줄은 사전이다 : {node}")
   _unknown(node, LAYER_KEYS, "layers[]", where)
   name = _check_name(node.get("name"), "겹", where)
   kind = node.get("kind")
   if kind not in KINDS:
      raise _fail(where, f"{name} 의 kind 는 {' · '.join(KINDS)} 중 하나다 : {kind}")
   exclusive = node.get("exclusive_with", [])
   if not isinstance(exclusive, list) or not all(isinstance(e, str) for e in exclusive):
      raise _fail(where, f"{name} 의 exclusive_with 는 겹 이름 목록이다 : {exclusive}")
   optional = node.get("optional", False)
   if not isinstance(optional, bool):
      raise _fail(where, f"{name} 의 optional 은 true · false 다 : {optional}")
   return Layer(name, kind, tuple(exclusive), optional)


def from_dict(data, where="(사전)") -> LayerSet:
   """사전 → LayerSet. 꼴이 틀리면 ArtToolError."""
   if not isinstance(data, dict):
      raise _fail(where, "맨 위는 사전이다")
   _unknown(data, TOP_KEYS, "맨 위", where)
   if data.get("version") != VERSION:
      raise _fail(where, f"version 은 {VERSION} 이다 : {data.get('version')}")
   canvas = _canvas(data.get("canvas"), where)

   rows = data.get("layers")
   if not isinstance(rows, list) or not rows:
      raise _fail(where, "layers 는 겹이 하나 이상인 목록이다")
   layers = [_layer(row, where) for row in rows]
   names = [layer.name for layer in layers]
   # Windows 폴더는 대소문자를 안 가린다. 대소문자만 다른 두 겹은 같은 폴더가 된다.
   if len({n.casefold() for n in names}) != len(names):
      raise _fail(where, f"겹 이름이 겹친다 (대소문자만 달라도 같다) : {', '.join(names)}")
   for layer in layers:
      for other in layer.exclusive_with:
         if other == layer.name:
            raise _fail(where, f"{layer.name} 이 exclusive_with 에 자기 자신을 적었다")
         if other not in names:
            raise _fail(where, f"{layer.name} 의 exclusive_with 에 없는 겹 : {other}")

   items = data.get("items", [])
   if not isinstance(items, list):
      raise _fail(where, f"items 는 그림 이름 목록이다 : {items}")
   for item in items:
      _check_name(item, "그림", where)
   if len({i.casefold() for i in items}) != len(items):
      raise _fail(where, f"items 이름이 겹친다 : {', '.join(items)}")

   template = data.get("template")
   if template is not None and not isinstance(template, str):
      raise _fail(where, f"template 은 템플릿 이름 글자다 : {template}")
   return LayerSet(canvas, layers, list(items), template)


def validate(data) -> None:
   from_dict(data)


def _file_of(path: str | os.PathLike) -> Path:
   """폴더를 주면 그 안의 layers.json, 파일을 주면 그 파일."""
   target = Path(path)
   return target / FILE_NAME if target.is_dir() else target


def load(path: str | os.PathLike) -> LayerSet:
   """겹 묶음 폴더(또는 layers.json 경로)를 읽는다."""
   file = _file_of(path)
   if not file.is_file():
      raise ArtToolError(f"겹 묶음 목록이 없다 : {file}")
   return from_dict(read_json(file), file)


def save(folder: str | os.PathLike, layerset: LayerSet) -> Path:
   """`folder/layers.json` 을 쓴다. 쓰기 전에 다시 검증한다(틀린 목록을 남기지 않는다)."""
   data = layerset.to_dict()
   from_dict(data, "(쓰기 전)")
   root = Path(folder)
   root.mkdir(parents=True, exist_ok=True)
   file = safe_join(resolve_root(root), FILE_NAME)
   write_json(file, data)
   return file


def image_path(folder: str | os.PathLike, layer: str, item: str) -> Path:
   """`<folder>/<겹>/<그림>.png`. 이름은 검증된 것만 받는다."""
   _check_name(layer, "겹", folder)
   _check_name(item, "그림", folder)
   return safe_join(resolve_root(Path(folder)), f"{layer}/{item}.png")


def read_item(folder: str | os.PathLike, layerset: LayerSet, item: str) -> dict[str, image.RGBA]:
   """그림 하나의 겹들을 쌓는 순서대로 읽는다. 파일이 없는 겹은 빠진다(빈 겹 판정은 검사 쪽 몫).

   크기가 canvas 와 다르면 거절한다 — 겹은 캔버스를 안 자른다는 규칙.
   """
   out: dict[str, image.RGBA] = {}
   for name in layerset.names():
      path = image_path(folder, name, item)
      if not path.is_file():
         continue
      arr = image.load(path)
      if image.size(arr) != layerset.canvas:
         raise ArtToolError(f"겹 크기가 canvas 와 다르다 : {path} 이 {image.size(arr)}, canvas {layerset.canvas}")
      out[name] = arr
   return out


def check_rig_order(layerset: LayerSet, order: list[str]) -> None:
   """프로필 rig 의 layer_order 가 있으면 겹 순서와 같아야 한다(`split --rig` 규칙 그대로)."""
   if list(order) != layerset.names():
      raise ArtToolError(f"layers.json 순서가 rig 의 layer_order 와 다르다 : {layerset.names()} ≠ {list(order)}")
