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

import json
import os
import re
from dataclasses import dataclass, field, replace
from pathlib import Path

from . import image
from .errors import ArtToolError, UsageError
from .jsonio import read_json, write_json
from .paths import resolve_root, safe_join

VERSION = 1          # 새 칸을 안 쓰는 묶음이 쓰는 판 (옛 묶음은 다시 써도 1 그대로)
VERSION_2 = 2        # meta · size · offset · files · 사전 꼴 items 를 쓰는 묶음
VERSIONS = (VERSION, VERSION_2)
META_MAX_BYTES = 64 * 1024   # meta 를 JSON 으로 편 크기 한도 — 그림 데이터를 실수로 넣는 일 막기
META_MAX_DEPTH = 32
FILES_MAX = 256      # files 무늬 글자 수 상한 (profile_map 무늬와 같은 값)
FILES_SLOT = "{v}"   # files 무늬의 치환 낱말. 이것 하나만 받는다
FILES_PART = re.compile(r"^[A-Za-z0-9_\-.]*$")
RESERVED_RE = re.compile(r"con|prn|nul|aux|com[1-9]|lpt[1-9]", re.IGNORECASE)   # Windows 예약 이름
VARIANT_MAX = 64     # pick 변형 이름 글자 수 상한
FILE_NAME = "layers.json"

# 10-3 표의 낱말. 검사 · 마스크 · 내보내기가 읽는다.
KINDS = (
   "body", "cloth", "face", "hair", "deco",     # 캐릭터
   "base", "structure", "front",                # 배경 (deco 같이 씀)
   "frame", "fill", "content", "badge",         # UI · 아이콘
   "variant",                                   # 타일 (base 같이 씀)
   "fx",                                        # 이펙트 · 움직임
)

TOP_KEYS = ("version", "canvas", "layers", "items", "template", "meta")
LAYER_KEYS = ("name", "kind", "exclusive_with", "optional", "meta", "size", "offset", "files")
# 버전 2 에서만 받는 칸. 버전 1 파일에 있으면 「version 2 로 올려라」 로 거절한다.
TOP_KEYS_V2 = ("meta",)
LAYER_KEYS_V2 = ("meta", "size", "offset", "files")

# 겹 · 그림 이름은 폴더 · 파일 이름이 되므로 좁게 받는다.
NAME_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_\-]*$")


@dataclass(frozen=True)
class Layer:
   name: str
   kind: str
   exclusive_with: tuple[str, ...] = ()
   optional: bool = False
   # 작은 겹 : 그림이 size 크기이고 캔버스의 offset 자리에 놓인다. 둘 다 None 이면 캔버스 크기.
   size: tuple[int, int] | None = None
   offset: tuple[int, int] | None = None
   # 파일 무늬 : 묶음 폴더 기준 상대 경로, {v} 자리에 변형 이름. None 이면 `<겹>/<그림>.png`.
   # 툴이 해석하지 않는 자유 사전(피벗 · 메모). 사전이라 해시 · 비교에서 뺀다.
   files: str | None = None
   meta: dict | None = field(default=None, compare=False)

   @property
   def small(self) -> bool:
      return self.size is not None

   def uses_v2(self) -> bool:
      return self.size is not None or self.meta is not None or self.files is not None

   def to_dict(self) -> dict:
      out: dict = {"name": self.name, "kind": self.kind}
      if self.exclusive_with:
         out["exclusive_with"] = list(self.exclusive_with)
      if self.optional:
         out["optional"] = True
      if self.size is not None:
         out["size"] = [self.size[0], self.size[1]]
         out["offset"] = [self.offset[0], self.offset[1]]
      if self.files is not None:
         out["files"] = self.files
      if self.meta is not None:
         out["meta"] = self.meta
      return out


@dataclass
class LayerSet:
   canvas: tuple[int, int]
   layers: list[Layer]
   items: list[str] = field(default_factory=list)
   template: str | None = None
   meta: dict | None = None
   # 사전 꼴 items : 그림 이름 → {겹: 변형}. 여기 없는 그림은 글자 꼴(모든 겹에서 변형 = 그림 이름).
   picks: dict[str, dict[str, str]] = field(default_factory=dict)

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
      v2 = self.meta is not None or bool(self.picks) or any(layer.uses_v2() for layer in self.layers)
      out: dict = {
         "version": VERSION_2 if v2 else VERSION,
         "canvas": [self.canvas[0], self.canvas[1]],
         "layers": [layer.to_dict() for layer in self.layers],
         "items": [{"name": i, "pick": dict(self.picks[i])} if i in self.picks else i for i in self.items],
      }
      if self.template is not None:
         out["template"] = self.template
      if self.meta is not None:
         out["meta"] = self.meta
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


def _bad(where, text: str) -> UsageError:
   """새 칸(버전 2)의 거절. 믿을 수 없는 입력이라 사용 오류(종료 2)로 낸다."""
   return UsageError(f"겹 묶음이 잘못됐다 : {text} - {where}")


def _v1_extra(node: dict, v2_keys: tuple[str, ...], spot: str, where) -> None:
   used = sorted(k for k in v2_keys if k in node)
   if used:
      raise _bad(where, f"version 1 에는 {', '.join(used)} 칸이 없다 ({spot}). version 2 로 올려라")


def _meta(value, spot: str, where) -> dict:
   """meta 는 해석하지 않는다. 사전인지 · JSON 으로 쓸 수 있는지 · 크기 · 깊이만 본다."""
   if not isinstance(value, dict):
      raise _bad(where, f"meta 는 사전이다 ({spot}) : {type(value).__name__}")
   stack = [(value, 1)]
   while stack:   # 재귀 대신 쌓아 두고 돌린다 — 아주 깊은 meta 로 RecursionError 가 나지 않게
      node, depth = stack.pop()
      if depth > META_MAX_DEPTH:
         raise _bad(where, f"meta 가 너무 깊다 ({spot}) : {META_MAX_DEPTH} 단 넘음")
      children = node.values() if isinstance(node, dict) else node if isinstance(node, list) else ()
      stack.extend((c, depth + 1) for c in children if isinstance(c, (dict, list)))
   try:
      size = len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8"))
   except (TypeError, ValueError) as exc:
      raise _bad(where, f"meta 를 JSON 으로 못 쓴다 ({spot}) : {exc}") from None
   if size > META_MAX_BYTES:
      raise _bad(where, f"meta 가 너무 크다 ({spot}) : {size} 바이트 (한도 {META_MAX_BYTES})")
   return value


def _pair(value, what: str, name: str, low: int, where) -> tuple[int, int]:
   ok = isinstance(value, (list, tuple)) and len(value) == 2
   ok = ok and all(isinstance(v, int) and not isinstance(v, bool) and v >= low for v in value)
   if not ok:
      raise _bad(where, f"{name} 의 {what} 는 [x, y] 정수 두 칸이다 ({low} 이상) : {value}")
   return int(value[0]), int(value[1])


def _box(node: dict, name: str, canvas: tuple[int, int], where):
   """size · offset 은 함께 쓴다. 상자가 캔버스를 넘으면 거절."""
   has_size, has_offset = "size" in node, "offset" in node
   if not has_size and not has_offset:
      return None, None
   if has_size != has_offset:
      raise _bad(where, f"{name} 의 size 와 offset 은 함께 쓴다")
   size = _pair(node["size"], "size", name, 1, where)
   offset = _pair(node["offset"], "offset", name, 0, where)
   if offset[0] + size[0] > canvas[0] or offset[1] + size[1] > canvas[1]:
      raise _bad(where, f"{name} 의 offset {list(offset)} + size {list(size)} 가 canvas {list(canvas)} 를 넘는다")
   return size, offset


def _layer(node, where, version: int = VERSION, canvas: tuple[int, int] = (0, 0)) -> Layer:
   if not isinstance(node, dict):
      raise _fail(where, f"겹 한 줄은 사전이다 : {node}")
   _unknown(node, LAYER_KEYS, "layers[]", where)
   if version == VERSION:
      _v1_extra(node, LAYER_KEYS_V2, "layers[]", where)
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
   size, offset = _box(node, name, canvas, where)
   meta = _meta(node["meta"], f"겹 {name}", where) if "meta" in node else None
   files = _files(node["files"], name, where) if "files" in node else None
   return Layer(name, kind, tuple(exclusive), optional, size, offset, files, meta)


def _files(value, name: str, where) -> str:
   """files 무늬는 믿을 수 없는 입력이라 묶음 폴더 밖으로 못 나가는 좁은 꼴만 받는다.

   `{v}` 정확히 하나(다른 치환 낱말 · 중괄호 거절) · `/` 로 나눈 상대 경로(역슬래시 · 드라이브 · 절대 경로 ·
   빈 마디 · `.` · `..` 거절) · 마디는 영숫자 _ - . 만 · 끝은 `{v}` 가 든 `.png`. 링크로 나가는 것은 safe_join 이 막는다.
   """
   if not isinstance(value, str) or not value:
      raise _bad(where, f"{name} 의 files 는 글자 무늬다 : {value!r}")
   if len(value) > FILES_MAX:
      raise _bad(where, f"{name} 의 files 무늬가 너무 길다 : {len(value)} 자 (한도 {FILES_MAX})")
   rest = value.replace(FILES_SLOT, "")
   if value.count(FILES_SLOT) != 1 or "{" in rest or "}" in rest:
      raise _bad(where, f"{name} 의 files 에는 {FILES_SLOT} 가 정확히 하나 있고 다른 치환 낱말은 없다 : {value!r}")
   parts = value.split("/")
   if any(p in ("", ".", "..") for p in parts) or not all(FILES_PART.match(p.replace(FILES_SLOT, "")) for p in parts):
      raise _bad(where, f"{name} 의 files 는 묶음 폴더 안 상대 경로다 (영숫자 _ - . 와 / 만, .. · 절대 경로 · 드라이브 · 역슬래시 안 됨) : {value!r}")
   if not value.lower().endswith(".png") or FILES_SLOT not in parts[-1]:
      raise _bad(where, f"{name} 의 files 는 {FILES_SLOT} 가 든 .png 파일 이름으로 끝난다 : {value!r}")
   # Windows 는 마디 끝 점을 떼어 다른 파일을 읽는다. 점으로 시작 · 끝나거나 점이 둘 잇닿은 마디는 거절
   # ({v} 는 영숫자 · _ 로 시작하고 점이 없어서, 무늬 글자만 보면 채운 꼴도 같이 막힌다).
   if any(p.startswith(".") or p.endswith(".") or ".." in p for p in parts):
      raise _bad(where, f"{name} 의 files 마디는 점으로 시작 · 끝나거나 점이 둘 잇닿으면 안 된다 : {value!r}")
   if any(_reserved(p) for p in parts if FILES_SLOT not in p):
      raise _bad(where, f"{name} 의 files 에 Windows 예약 이름 마디가 있다 : {value!r}")
   return value


def _reserved(part: str) -> bool:
   """Windows 예약 이름(con · prn · nul · aux · com1~9 · lpt1~9). 대소문자 무시, 첫 점 앞 이름 기준."""
   return RESERVED_RE.fullmatch(part.split(".")[0]) is not None


def _pattern(layer: Layer) -> str:
   return layer.files if layer.files is not None else f"{layer.name}/{FILES_SLOT}.png"


def _check_paths(layers: list[Layer], items: list[str], picks: dict, where) -> None:
   """모든 (그림, 겹)을 실제 경로로 풀어 두 칸이 한 파일로 풀리면 거절한다. 윈도는 대소문자를 안 가린다.

   무늬 글자가 달라도 `body/x_{v}.png`(변형 y) 와 기본 `body/{v}.png`(그림 x_y) 처럼 같은 파일이 될 수 있다.
   files 무늬 첫 마디가 다른 겹 이름이면 남의 기본 폴더에 쓰게 되니 그것도 거절한다.
   """
   names = {layer.name.casefold(): layer.name for layer in layers}
   for layer in layers:
      first = layer.files.split("/")[0].casefold() if layer.files is not None else None
      if first in names and names[first] != layer.name:
         raise _bad(where, f"{layer.name} 의 files 첫 마디가 다른 겹 이름이다 : {layer.files}")
   seen: dict[str, tuple[str, str]] = {}
   for item in items:
      pick = picks.get(item)
      for layer in layers:
         if pick is not None and layer.name not in pick:
            continue
         path = _pattern(layer).replace(FILES_SLOT, pick[layer.name] if pick is not None else item).casefold()
         other = seen.setdefault(path, (item, layer.name))
         if other != (item, layer.name):
            raise _bad(where, f"(그림 {other[0]}, 겹 {other[1]}) · (그림 {item}, 겹 {layer.name}) 이 같은 파일로 풀린다 : {path}")


def _item(node, version: int, names: list[str], where):
   """items 한 줄. 글자 꼴은 (이름, None), 사전 꼴 {name, pick} 은 (이름, {겹: 변형})."""
   if not isinstance(node, dict):
      return _check_name(node, "그림", where), None
   if version == VERSION:
      raise _bad(where, "version 1 에는 사전 꼴 items 가 없다 (items[]). version 2 로 올려라")
   if set(node) != {"name", "pick"}:
      raise _bad(where, f"사전 꼴 items 는 name · pick 두 칸이다 : {sorted(map(str, node))}")
   item = _check_name(node["name"], "그림", where)
   pick = node["pick"]
   if not isinstance(pick, dict) or not pick:
      raise _bad(where, f"{item} 의 pick 은 비지 않은 {{겹: 변형}} 사전이다 : {pick}")
   for layer_name, variant in pick.items():
      if layer_name not in names:
         raise _bad(where, f"{item} 의 pick 에 없는 겹 : {layer_name}")
      if not isinstance(variant, str) or not NAME_RE.match(variant):
         raise _bad(where, f"{item} 의 pick 변형 이름은 영숫자 · _ · - 만 쓴다 : {variant!r}")
      if len(variant) > VARIANT_MAX or _reserved(variant):
         raise _bad(where, f"{item} 의 pick 변형 이름은 {VARIANT_MAX} 자 안이고 Windows 예약 이름이 아니다 : {variant!r}")
   return item, dict(pick)


def from_dict(data, where="(사전)") -> LayerSet:
   """사전 → LayerSet. 꼴이 틀리면 ArtToolError."""
   if not isinstance(data, dict):
      raise _fail(where, "맨 위는 사전이다")
   _unknown(data, TOP_KEYS, "맨 위", where)
   version = data.get("version")
   if type(version) is not int or version not in VERSIONS:   # bool · 2.0 같은 실수는 거절
      raise _fail(where, f"version 은 {' · '.join(map(str, VERSIONS))} 이다 : {version}")
   if version == VERSION:
      _v1_extra(data, TOP_KEYS_V2, "맨 위", where)
   canvas = _canvas(data.get("canvas"), where)

   rows = data.get("layers")
   if not isinstance(rows, list) or not rows:
      raise _fail(where, "layers 는 겹이 하나 이상인 목록이다")
   layers = [_layer(row, where, version, canvas) for row in rows]
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

   raw_items = data.get("items", [])
   if not isinstance(raw_items, list):
      raise _fail(where, f"items 는 그림 이름 목록이다 : {raw_items}")
   items, picks = [], {}
   for row in raw_items:
      item, pick = _item(row, version, names, where)
      items.append(item)
      if pick is not None:
         picks[item] = pick
   # 두 겹의 무늬가 같으면 (겹, 그림) 둘이 한 파일로 풀린다. 윈도는 대소문자를 안 가린다.
   patterns = [_pattern(layer).casefold() for layer in layers]
   if len(set(patterns)) != len(patterns):
      raise _bad(where, f"두 겹의 파일 무늬가 같다 : {', '.join(_pattern(l) for l in layers)}")
   for item, pick in picks.items():
      for layer in layers:
         clash = [o for o in layer.exclusive_with if layer.name in pick and o in pick]
         if clash:
            raise _bad(where, f"{item} 의 pick 이 exclusive_with 짝 {layer.name} · {clash[0]} 을 같이 골랐다")
   if len({i.casefold() for i in items}) != len(items):
      raise _fail(where, f"items 이름이 겹친다 : {', '.join(items)}")
   _check_paths(layers, items, picks, where)

   template = data.get("template")
   if template is not None and not isinstance(template, str):
      raise _fail(where, f"template 은 템플릿 이름 글자다 : {template}")
   meta = _meta(data["meta"], "맨 위", where) if "meta" in data else None
   return LayerSet(canvas, layers, list(items), template, meta, picks)


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
   return from_dict(read_data(file), file)


def read_data(file: str | os.PathLike) -> dict:
   """layers.json(또는 그 자리의 JSON)을 사전으로 읽는다. 아주 깊게 겹친 meta 는 json.loads 에서 RecursionError 로 온다."""
   file = Path(file)
   try:
      return read_json(file)
   except RecursionError:
      raise UsageError(f"{file.name} 이 너무 깊게 겹쳐 있다 : {file}") from None


def carry_meta(old: LayerSet | None, fresh: LayerSet) -> LayerSet:
   """다시 쓸 때 옛 묶음의 meta 를 잃지 않게 이어 붙인다.

   맨 위 meta 는 새 묶음에 없을 때만 옛 것을, 겹 meta 는 같은 이름 겹에 meta 가 없을 때만 옛 것을 쓴다.
   """
   if old is None:
      return fresh
   old_meta = {layer.name: layer.meta for layer in old.layers}
   layers = [
      replace(layer, meta=old_meta.get(layer.name)) if layer.meta is None and old_meta.get(layer.name) is not None else layer
      for layer in fresh.layers
   ]
   meta = fresh.meta if fresh.meta is not None else old.meta
   # files · 사전 꼴 items 도 같은 규칙 : 새 묶음에 없고 같은 이름 겹 · 그림이 남아 있을 때만 옛 것을 잇는다.
   old_files = {layer.name: layer.files for layer in old.layers}
   layers = [replace(l, files=old_files[l.name]) if l.files is None and old_files.get(l.name) else l for l in layers]
   names = {layer.name for layer in layers}
   picks = dict(fresh.picks)
   for item, pick in old.picks.items():
      if item in fresh.items and item not in picks and set(pick) <= names:
         picks[item] = dict(pick)
   return LayerSet(fresh.canvas, layers, list(fresh.items), fresh.template, meta, picks)


def save(folder: str | os.PathLike, layerset: LayerSet) -> Path:
   """`folder/layers.json` 을 쓴다. 쓰기 전에 다시 검증한다(틀린 목록을 남기지 않는다)."""
   data = layerset.to_dict()
   from_dict(data, "(쓰기 전)")
   root = Path(folder)
   root.mkdir(parents=True, exist_ok=True)
   file = safe_join(resolve_root(root), FILE_NAME)
   write_json(file, data)
   return file


def image_path(folder: str | os.PathLike, layerset: LayerSet, layer: str, item: str) -> Path | None:
   """그림 item 의 겹 layer 파일. 기본은 `<folder>/<겹>/<그림>.png`, files 무늬가 있으면 {v} 에 변형 이름.

   변형 이름 = 사전 꼴 item 이면 pick 값, 글자 꼴이면 그림 이름. pick 에 없는 겹은 그 그림에 없어서 None.
   """
   _check_name(layer, "겹", folder)
   _check_name(item, "그림", folder)
   pick = layerset.picks.get(item)
   if pick is not None and layer not in pick:
      return None
   variant = pick[layer] if pick is not None else item
   return safe_join(resolve_root(Path(folder)), _pattern(layerset.layer(layer)).replace(FILES_SLOT, variant))


def read_item(folder: str | os.PathLike, layerset: LayerSet, item: str) -> dict[str, image.RGBA]:
   """그림 하나의 겹들을 쌓는 순서대로 읽는다. 파일이 없는 겹은 빠진다(빈 겹 판정은 검사 쪽 몫).

   크기가 canvas 와 다르면 거절한다 — 겹은 캔버스를 안 자른다는 규칙.
   작은 겹(size · offset)은 그림이 size 와 같아야 하고, 투명 캔버스에 offset 으로 펴서 돌려준다.
   그래서 뒤의 compose · mask · view · export 는 늘 캔버스 크기 배열만 본다.
   """
   out: dict[str, image.RGBA] = {}
   pick = layerset.picks.get(item)
   seen: dict[str, str] = {}
   for layer in layerset.layers:
      path = image_path(folder, layerset, layer.name, item)
      if path is None:
         continue
      key = os.path.normcase(str(path))
      if key in seen:   # 무늬가 달라도 변형 이름에 따라 같은 파일로 풀릴 수 있다
         raise UsageError(f"겹 {seen[key]} · {layer.name} 이 그림 {item} 에서 같은 파일로 풀린다 : {path}")
      seen[key] = layer.name
      if not path.is_file():
         if pick is not None:   # pick 이 고른 변형은 꼭 있어야 한다
            raise UsageError(f"그림 {item} 의 pick 이 고른 변형 파일이 없다 ({layer.name}={pick[layer.name]}) : {path}")
         continue
      arr = image.load(path)
      if layer.small:
         if image.size(arr) != layer.size:
            raise UsageError(f"겹 크기가 size 와 다르다 : {path} 이 {image.size(arr)}, size {layer.size}")
         arr = expand(layerset, layer, arr)
      elif image.size(arr) != layerset.canvas:
         raise ArtToolError(f"겹 크기가 canvas 와 다르다 : {path} 이 {image.size(arr)}, canvas {layerset.canvas}")
      out[layer.name] = arr
   return out


def expand(layerset: LayerSet, layer: Layer, arr: image.RGBA) -> image.RGBA:
   """size 크기 그림 → 캔버스 크기 투명 판의 offset 자리에 붙인 그림. 크기 검사는 부르는 쪽 몫."""
   width, height = layerset.canvas
   try:
      image.check_pixels(width, height, "겹 캔버스")
   except ArtToolError as exc:
      raise UsageError(str(exc)) from None
   out = image.new(width, height)
   image.paste(out, arr, layer.offset[0], layer.offset[1])
   return out


def crop_to_box(layer: Layer, arr: image.RGBA, where) -> image.RGBA:
   """쓰기용 : 캔버스 크기 그림 → 작은 겹 상자로 자른 그림. 작은 겹이 아니면 그대로.

   상자 밖에 불투명 · 반투명 칸이 있으면 조용히 버리지 않고 거절한다(경고 통로가 없는 자리에서 그림이 사라지지 않게).
   """
   if not layer.small:
      return arr
   (x, y), (w, h) = layer.offset, layer.size
   outside = arr[..., 3].copy()
   outside[y:y + h, x:x + w] = 0
   count = int((outside > 0).sum())
   if count:
      raise UsageError(f"겹 {layer.name} 의 상자({x},{y} {w}x{h}) 밖에 칸 {count}개가 있다. size · offset 을 늘린다 - {where}")
   return image.crop(arr, x, y, w, h)


def refuse_small(layerset: LayerSet, what: str) -> None:
   """작은 겹 쓰기를 아직 못 하는 명령은 미리 막는다 — 캔버스 크기 그림을 작은 겹 자리에 몰래 쓰지 않게."""
   small = [layer.name for layer in layerset.layers if layer.small]
   if small:
      raise UsageError(f"{what} 는 작은 겹(size · offset)이 있는 묶음에 아직 못 쓴다 : {', '.join(small)}")


def check_rig_order(layerset: LayerSet, order: list[str]) -> None:
   """프로필 rig 의 layer_order 가 있으면 겹 순서와 같아야 한다(`split --rig` 규칙 그대로)."""
   if list(order) != layerset.names():
      raise ArtToolError(f"layers.json 순서가 rig 의 layer_order 와 다르다 : {layerset.names()} ≠ {list(order)}")
