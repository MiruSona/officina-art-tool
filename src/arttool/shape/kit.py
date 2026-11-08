"""부품 사전(kit) — 작은 부품 틀 여러 개를 한 명세 안에 놓아 조립한다 (도형 렌더러 설계 2-6절).

떡처럼 같은 구도의 묶음은 틀 하나(2-5절)로 덮지만, 화분 · 의자 · 액자처럼 서로 다른 물건은 틀 하나로 못 덮는다.
그래서 「나무 틀」 · 「도기 화분」 · 「잎 하나」 같은 **부품**을 틀 파일로 만들어 두고, 명세 `shapes` 맨 위 칸에
부품 놓기 칸을 적어 조립한다.

    "shapes": [
      { "part": "kit/pot.part.json", "as": "pot", "at": [12, 60], "scale": [1.2, 1], "z": 4,
        "preset": "terracotta", "params": { "clay": "#C0643C" } },
      { "part": "kit/leaf.part.json", "as": "leaf1", "at": [10, 30], "flip": true }
    ]

부품 파일은 틀 파일(2-5절)과 같은 꼴이고, `spec` 에는 `materials` · `shapes` · `stamps` 만 둔다.
부품 좌표는 그 부품의 기준점(보통 바닥 가운데)을 (0, 0) 으로 적는다.

놓기 칸 :

| 칸 | 뜻 |
| --- | --- |
| `part` | 부품 파일 경로 (그 명세 파일 폴더 기준) |
| `as` | 이름. 부품 재질은 `<as>.<재질>` 로 이름이 바뀐다 (같은 부품을 여러 번 놓아도 안 섞인다) |
| `at` [x, y] | 기준점을 그림 칸(아래 +)만큼 옮긴다. 캔버스 origin 이 [0, 0] 이면 그대로 그림 좌표다 |
| `z` | 앞뒤 (모델 z 에 더한다) |
| `scale` | 수 하나 또는 [sx, sy]. **x · y 만** 늘인다 — z(두께 · 앞뒤)는 그대로라 안쪽 선 규칙이 안 바뀐다 |
| `flip` | true 면 좌우 거울 (도장 격자도 뒤집는다) |
| `preset` · `params` | 부품 틀 값 (2-5절과 같다) |

- 부품이 자기 `materials` 에 없는 재질 이름을 쓰면 **놓은 쪽(바깥 명세) 재질**을 가리킨다 — 선 색 같은 공용 재질을 나눠 쓴다.
- 부품 안에 부품을 놓을 수 있다 (깊이 4 까지, 제 자신을 다시 부르면 오류).
- 늘이기는 도형 칸 값을 고쳐서 한다(근사가 아니라 정확한 거리 함수). 돌린 도형에 x · y 를 다르게 늘이면
  도형 자기 축 기준으로 늘어난다 — 돌린 판은 늘이기를 같게 두는 편이 안전하다.
"""

from __future__ import annotations

import copy
import os
from pathlib import Path

from ..errors import ArtToolError
from ..jsonio import read_json
from .template import expand_template, is_template_spec

MAX_DEPTH = 4
PART_KEYS = {"part", "as", "at", "z", "scale", "flip", "preset", "params", "note", "name"}
PART_SPEC_KEYS = {"materials", "shapes", "stamps"}


def _err(where: str, msg: str) -> ArtToolError:
   return ArtToolError(f"부품 {where} : {msg}")


def _num(value, where: str) -> float:
   if isinstance(value, bool) or not isinstance(value, (int, float)):
      raise _err(where, f"수다 : {value!r}")
   return float(value)


def _pair(value, where: str, default) -> tuple[float, float]:
   if value is None:
      return default
   if isinstance(value, (int, float)) and not isinstance(value, bool):
      return float(value), float(value)
   if not isinstance(value, list) or len(value) != 2:
      raise _err(where, f"[a, b] 다 : {value!r}")
   return _num(value[0], where), _num(value[1], where)


class _Place:
   """부품 하나를 놓는 법 : 늘이기(sx, sy) · 거울(f = ±1)."""

   def __init__(self, sx: float, sy: float, flip: bool):
      if sx <= 0 or sy <= 0:
         raise _err("scale", f"0 보다 큰 수다 : {[sx, sy]}")
      self.sx, self.sy, self.f = sx, sy, (-1.0 if flip else 1.0)

   def x(self, v: float) -> float:
      return v * self.sx * self.f

   def y(self, v: float) -> float:
      return v * self.sy

   def shape(self, data: dict, where: str) -> dict:
      """도형 사전 하나(묶음이면 안까지)를 늘이고 거울에 비춘다. 원본은 안 건드린다."""
      out = dict(data)
      if "pos" in out:
         p = list(out["pos"])
         out["pos"] = [self.x(_num(p[0], where)), self.y(_num(p[1], where)), *p[2:]]
      if "rot" in out and self.f < 0:
         r = list(out["rot"])
         out["rot"] = [r[0], -_num(r[1], where), -_num(r[2], where)]
      if "copies" in out:
         out["copies"] = [[self.x(_num(c[0], where)), self.y(_num(c[1], where))] for c in out["copies"]]
      kind = out.get("type")
      s_min = min(self.sx, self.sy)
      if kind == "group":
         out["shapes"] = [self.shape(s, f"{where}.shapes[{i}]") for i, s in enumerate(out.get("shapes") or [])]
      elif kind == "extrude":
         if "points" in out:
            out["points"] = [[self.x(_num(q[0], where)), self.y(_num(q[1], where))] for q in out["points"]]
         if "mirror" in out:
            out["mirror"] = self.x(_num(out["mirror"], where))
         if "rect" in out:
            x0, y0, x1, y1 = (_num(v, where) for v in out["rect"])
            xa, xb = sorted((self.x(x0), self.x(x1)))
            out["rect"] = [xa, self.y(y0), xb, self.y(y1)]
         if "ellipse" in out:
            cx, cy, rx, ry = (_num(v, where) for v in out["ellipse"])
            out["ellipse"] = [self.x(cx), self.y(cy), rx * self.sx, ry * self.sy]
      elif kind == "sphere":
         r = _num(out.get("r"), where)
         if self.sx != self.sy:
            out.pop("r")
            out["type"] = "ellipsoid"
            out["radii"] = [r * self.sx, r * self.sy, r * s_min]
         else:
            out["r"] = r * self.sx
      elif kind == "ellipsoid":
         a, b, c = (_num(v, where) for v in out.get("radii"))
         out["radii"] = [a * self.sx, b * self.sy, c * s_min]
      elif kind == "capsule":
         out["r"] = _num(out.get("r"), where) * self.sx
         out["length"] = _num(out.get("length", 0), where) * self.sy
      elif kind == "box":
         w, h, d = (_num(v, where) for v in out.get("size"))
         out["size"] = [w * self.sx, h * self.sy, d]
         if "round" in out:
            out["round"] = min(_num(out["round"], where) * s_min, min(w * self.sx, h * self.sy, d) / 2)
      elif kind == "lathe":
         out["profile"] = [[_num(q[0], where) * self.sx, self.y(_num(q[1], where))] for q in out.get("profile") or []]
      elif kind == "cone":
         out["r"] = _num(out.get("r"), where) * self.sx
         out["top"] = _num(out.get("top", 0), where) * self.sx
         out["height"] = _num(out.get("height"), where) * self.sy
      return out


def _rename_materials(shape: dict, names: dict[str, str]) -> dict:
   out = dict(shape)
   if out.get("material") in names:
      out["material"] = names[out["material"]]
   if out.get("type") == "group":
      out["shapes"] = [_rename_materials(s, names) for s in out.get("shapes") or []]
   return out


def _place_part(entry: dict, base_dir: Path, where: str, depth: int, chain: tuple[str, ...]) -> tuple[dict, list, list]:
   """놓기 칸 하나 → (재질 사전, 도형 목록 [묶음 하나], 도장 목록). 이름은 이미 `<as>.` 로 바뀐 것."""
   extra = sorted(set(entry) - PART_KEYS)
   if extra:
      raise _err(where, f"모르는 칸 : {', '.join(extra)} (part · as · at · z · scale · flip · preset · params)")
   name = entry.get("as")
   if not isinstance(name, str) or not name or "." in name:
      raise _err(f"{where}.as", f"점 없는 이름이다 : {name!r}")
   ref = entry.get("part")
   if not isinstance(ref, str) or not ref:
      raise _err(f"{where}.part", f"부품 파일 경로다 : {ref!r}")
   file = Path(ref)
   if not file.is_absolute():
      file = base_dir / file
   if not file.is_file():
      raise _err(f"{where}.part", f"부품 파일이 없다 : {file}")
   key = str(file.resolve())
   if key in chain:
      raise _err(f"{where}.part", f"부품이 자기 자신을 다시 부른다 : {file.name}")
   if depth >= MAX_DEPTH:
      raise _err(where, f"부품 안 부품은 {MAX_DEPTH} 겹까지다")
   template = read_json(file)
   if is_template_spec(template):
      raise _err(str(file), "부품 파일은 틀 꼴(template_version · params · spec)이다")
   if "params" not in template:
      template = {**template, "params": {}}
   preset = entry.get("preset")
   if preset is not None and not isinstance(preset, str):
      raise _err(f"{where}.preset", f"묶음 이름이다 : {preset!r}")
   body = expand_template(template, preset, entry.get("params") or {}, f"{where}({file.name})")
   wrong = sorted(set(body) - PART_SPEC_KEYS)
   if wrong:
      raise _err(str(file), f"부품 spec 에는 materials · shapes · stamps 만 둔다 : {', '.join(wrong)}")
   # 부품 안 부품 먼저 풀기 (그 부품 파일 폴더 기준)
   body = assemble(body, file.parent, f"{where}({file.name})", depth + 1, chain + (key,), need_materials=False)

   sx, sy = _pair(entry.get("scale"), f"{where}.scale", (1.0, 1.0))
   flip = entry.get("flip", False)
   if not isinstance(flip, bool):
      raise _err(f"{where}.flip", f"true / false 다 : {flip!r}")
   place = _Place(sx, sy, flip)
   ax, ay = _pair(entry.get("at"), f"{where}.at", (0.0, 0.0))
   az = _num(entry.get("z", 0), f"{where}.z")

   own = body.get("materials") or {}
   if not isinstance(own, dict):
      raise _err(str(file), "materials 는 사전이다")
   names = {m: f"{name}.{m}" for m in own}
   materials = {names[m]: copy.deepcopy(v) for m, v in own.items()}
   shapes = [_rename_materials(place.shape(s, f"{where}.shapes[{i}]"), names)
             for i, s in enumerate(body.get("shapes") or [])]
   group = {"type": "group", "name": name, "pos": [ax, -ay, az], "shapes": shapes}
   stamps = []
   for i, st in enumerate(body.get("stamps") or []):
      st = dict(st)
      here = f"{where}.stamps[{i}]"
      if st.get("on") in names:
         st["on"] = names[st["on"]]
      at = st.get("at")
      if not isinstance(at, list) or len(at) != 2:
         raise _err(f"{here}.at", "[x, y] 다")
      st["at"] = [place.x(_num(at[0], here)) + ax, place.y(_num(at[1], here)) - ay]
      if place.f < 0 and isinstance(st.get("grid"), list):
         st["grid"] = [row[::-1] for row in st["grid"]]
      if "copies" in st:
         st["copies"] = [[round(place.x(_num(c[0], here))), round(place.y(_num(c[1], here)))] for c in st["copies"]]
      stamps.append(st)
   return materials, [group], stamps


def has_parts(data) -> bool:
   return isinstance(data, dict) and any(isinstance(s, dict) and "part" in s for s in data.get("shapes") or [])


def assemble(data: dict, base_dir: str | os.PathLike = ".", where: str = "명세", depth: int = 0,
             chain: tuple[str, ...] = (), need_materials: bool = True) -> dict:
   """명세 `shapes` 맨 위의 부품 놓기 칸을 풀어 보통 명세 사전으로. 부품이 없으면 그대로 돌려준다."""
   if not has_parts(data):
      return data
   out = dict(data)
   materials = dict(data.get("materials") or {})
   stamps = list(data.get("stamps") or [])
   shapes = []
   seen: set[str] = set()
   for i, item in enumerate(data.get("shapes") or []):
      if not (isinstance(item, dict) and "part" in item):
         shapes.append(item)
         continue
      here = f"{where}.shapes[{i}]"
      mats, grp, sts = _place_part(item, Path(base_dir), here, depth, chain)
      if item["as"] in seen:
         raise _err(f"{here}.as", f"같은 이름을 두 번 썼다 : {item['as']!r}")
      seen.add(item["as"])
      clash = sorted(set(mats) & set(materials))
      if clash:
         raise _err(f"{here}.as", f"재질 이름이 겹친다 : {', '.join(clash)}")
      materials.update(mats)
      shapes.extend(grp)
      stamps.extend(sts)
   out["shapes"] = shapes
   if materials or need_materials:
      out["materials"] = materials
   if stamps:
      out["stamps"] = stamps
   return out
