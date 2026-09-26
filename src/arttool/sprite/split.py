"""한 장을 겹 여러 장으로 가른다. 겹은 원본과 같은 크기·같은 좌표다.

가르는 순서와 표 꼴은 `Docs/Design/2026-09-23-겹나누기·팔레트굽기·타일·아이콘설계.md` 3절.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .. import image, pieces
from ..errors import ArtToolError, UsageError
from ..jsonio import read_json, write_json
from ..palette import parse_hex, to_hex
from ..paths import check_relative, jailed_output, resolve_root, safe_join
from . import layers as layers_mod
from .anchors import VERSION as ANCHOR_VERSION
from .anchors import PointBook

VERSION = 1
DEFAULT_MIN_PIECE = 8
ANCHOR_KINDS = ("bbox_bottom_center", "bbox_center", "bbox_top_center")
REPORT_NAME = "split_report.json"
ANCHORS_NAME = "anchors.json"

SPEC_KEYS = ("version", "layers", "default", "outline", "colors", "rules", "masks", "layer_opts")
RULE_KEYS = ("color", "to", "box", "above_y", "below_y", "near", "from")
RESERVED_NAMES = (REPORT_NAME, ANCHORS_NAME)
OPT_KEYS = ("min_piece", "anchor")

# 픽셀마다 어느 단계에서 주인이 정해졌나. 투표 뒤 규칙(near·from)은 색 표·투표 몫만 덮는다.
STAGE_NONE, STAGE_MASK, STAGE_RULE, STAGE_TABLE, STAGE_VOTE = 0, 1, 2, 3, 4


@dataclass
class Rule:
   color: tuple[int, int, int]
   to: int
   box: tuple[int, int, int, int] | None = None
   above_y: int | None = None
   below_y: int | None = None
   near: int | None = None
   source: int | None = None

   @property
   def late(self) -> bool:
      """near·from 이 붙은 규칙은 외곽선 투표가 끝난 뒤에 돈다."""
      return self.near is not None or self.source is not None

   def covers(self, x: int, y: int) -> bool:
      """box 는 끝을 뺀 [x0, y0, x1, y1). above_y 는 y < 값, below_y 는 y >= 값."""
      if self.box is not None:
         x0, y0, x1, y1 = self.box
         if not (x0 <= x < x1 and y0 <= y < y1):
            return False
      if self.above_y is not None and not y < self.above_y:
         return False
      if self.below_y is not None and not y >= self.below_y:
         return False
      return True


@dataclass
class SplitSpec:
   layers: list[str]
   default: int
   outline: tuple[int, int, int] | None
   colors: dict[tuple[int, int, int], int]
   rules: list[Rule]
   masks: dict[int, Path] = field(default_factory=dict)
   min_piece: dict[int, int] = field(default_factory=dict)
   anchor: dict[int, str] = field(default_factory=dict)


def _layer_index(spec_layers: list[str], name, where: str) -> int:
   if name not in spec_layers:
      raise ArtToolError(f"layers 에 없는 겹 이름 : {name} ({where})")
   return spec_layers.index(name)


def _check_layer_name(name) -> None:
   if not isinstance(name, str) or not name.strip():
      raise ArtToolError(f"겹 이름은 빈칸 없는 글자여야 한다 : {name!r}")
   # 겹 이름이 곧 출력 폴더 이름이다. 한 칸짜리 상대경로만 받는다.
   if "/" in name or "\\" in name or len(check_relative(name).parts) != 1 or name == ".":
      raise ArtToolError(f"겹 이름에 경로를 못 쓴다 : {name}")
   if name.casefold() in (n.casefold() for n in RESERVED_NAMES):
      raise ArtToolError(f"겹 이름이 보고 파일 이름과 같다 : {name}")


def _reject_unknown(node: dict, allowed: tuple[str, ...], where: str) -> None:
   unknown = sorted(set(node) - set(allowed))
   if unknown:
      raise ArtToolError(f"{where} 에 모르는 칸 : {', '.join(unknown)}")


def _int(value, where: str) -> int:
   if isinstance(value, bool) or not isinstance(value, int):
      raise ArtToolError(f"{where} 는 정수여야 한다 : {value!r}")
   return value


def _parse_rule(row, spec_layers: list[str], index: int) -> Rule:
   where = f"rules[{index}]"
   if not isinstance(row, dict):
      raise ArtToolError(f"{where} 는 사전이어야 한다")
   _reject_unknown(row, RULE_KEYS, where)
   if "color" not in row or "to" not in row:
      raise ArtToolError(f"{where} 에 color 와 to 가 있어야 한다")
   rule = Rule(color=parse_hex(str(row["color"])), to=_layer_index(spec_layers, row["to"], where))
   if "box" in row:
      box = row["box"]
      if not isinstance(box, list) or len(box) != 4:
         raise ArtToolError(f"{where}.box 는 [x0, y0, x1, y1] 네 정수다")
      rule.box = tuple(_int(v, f"{where}.box") for v in box)
      if rule.box[0] >= rule.box[2] or rule.box[1] >= rule.box[3]:
         raise ArtToolError(f"{where}.box 는 x0 < x1, y0 < y1 이어야 한다 : {box}")
   if "above_y" in row:
      rule.above_y = _int(row["above_y"], f"{where}.above_y")
   if "below_y" in row:
      rule.below_y = _int(row["below_y"], f"{where}.below_y")
   if "near" in row:
      rule.near = _layer_index(spec_layers, row["near"], f"{where}.near")
   if "from" in row:
      rule.source = _layer_index(spec_layers, row["from"], f"{where}.from")
   if rule.box is None and rule.above_y is None and rule.below_y is None and not rule.late:
      raise ArtToolError(f"{where} 에 조건이 없다. 조건 없는 색은 colors 에 적는다")
   return rule


def _parse_opts(raw, spec_layers: list[str], spec: SplitSpec) -> None:
   if not isinstance(raw, dict):
      raise ArtToolError("layer_opts 는 사전이어야 한다")
   for name, opts in raw.items():
      idx = _layer_index(spec_layers, name, "layer_opts")
      if not isinstance(opts, dict):
         raise ArtToolError(f"layer_opts.{name} 는 사전이어야 한다")
      _reject_unknown(opts, OPT_KEYS, f"layer_opts.{name}")
      if "min_piece" in opts:
         value = _int(opts["min_piece"], f"layer_opts.{name}.min_piece")
         if value < 0:
            raise ArtToolError(f"layer_opts.{name}.min_piece 는 0 이상이다 : {value}")
         spec.min_piece[idx] = value
      if "anchor" in opts:
         if opts["anchor"] not in ANCHOR_KINDS:
            raise ArtToolError(f"layer_opts.{name}.anchor 는 {' · '.join(ANCHOR_KINDS)} 중 하나다 : {opts['anchor']}")
         spec.anchor[idx] = opts["anchor"]


def load_spec(data: dict, spec_dir: Path) -> SplitSpec:
   """나누기 표를 읽고 검사한다. 마스크 경로는 표 파일 폴더 아래만 받는다."""
   if not isinstance(data, dict):
      raise ArtToolError("나누기 표는 JSON 사전이어야 한다")
   _reject_unknown(data, SPEC_KEYS, "나누기 표")
   if data.get("version") != VERSION:
      raise ArtToolError(f"모르는 나누기 표 판 번호 : {data.get('version')}")

   spec_layers = data.get("layers")
   if not isinstance(spec_layers, list) or not spec_layers:
      raise ArtToolError("layers 는 겹 이름 목록이어야 한다")
   for name in spec_layers:
      _check_layer_name(name)
   # 겹 이름이 폴더 이름이라 Windows 에서는 대소문자만 다른 두 이름이 한 폴더를 쓴다.
   if len({n.casefold() for n in spec_layers}) != len(spec_layers):
      raise ArtToolError("layers 에 같은 이름이 두 번 있다 (대소문자는 안 가린다)")
   if "default" not in data:
      raise ArtToolError("default 겹이 있어야 한다 (표에 없는 색이 갈 곳)")

   outline = parse_hex(str(data["outline"])) if data.get("outline") else None
   colors = {}
   for hex_text, name in (data.get("colors") or {}).items():
      rgb = parse_hex(hex_text)
      if rgb in colors:
         raise ArtToolError(f"colors 에 같은 색이 두 번 있다 (대소문자는 안 가린다) : {hex_text}")
      if rgb == outline:
         raise ArtToolError(f"outline 색이 colors 에도 있다. 그러면 외곽선 투표가 안 돈다 : {hex_text}")
      colors[rgb] = _layer_index(spec_layers, name, f"colors.{hex_text}")
   rules = [_parse_rule(row, spec_layers, i) for i, row in enumerate(data.get("rules") or [])]

   spec = SplitSpec(
      layers=list(spec_layers),
      default=_layer_index(spec_layers, data["default"], "default"),
      outline=outline,
      colors=colors,
      rules=rules,
   )
   for name, rel in (data.get("masks") or {}).items():
      spec.masks[_layer_index(spec_layers, name, "masks")] = safe_join(resolve_root(spec_dir), str(rel))
   _parse_opts(data.get("layer_opts") or {}, spec_layers, spec)
   return spec


def _rgb_at(arr: image.RGBA, x: int, y: int) -> tuple[int, int, int]:
   return int(arr[y, x, 0]), int(arr[y, x, 1]), int(arr[y, x, 2])


def _apply_masks(owner, stage, masks: dict[int, np.ndarray], opaque) -> None:
   taken = np.zeros(opaque.shape, dtype=bool)
   for idx, mask in masks.items():
      if mask.shape != opaque.shape:
         raise ArtToolError(f"마스크 크기가 그림과 다르다 : {mask.shape[1]}x{mask.shape[0]}")
      if np.any(taken & mask):
         raise ArtToolError("마스크 둘이 같은 자리를 덮는다")
      taken |= mask
      hit = mask & opaque
      owner[hit] = idx
      stage[hit] = STAGE_MASK


def _assign(arr: image.RGBA, spec: SplitSpec, masks: dict[int, np.ndarray]):
   """가르기 1~5단. 주인 번호 배열과 표에 없는 색 목록을 돌려준다."""
   height, width = arr.shape[0], arr.shape[1]
   opaque = arr[:, :, 3] > 0
   owner = np.full((height, width), pieces.NONE, dtype=np.int32)
   stage = np.zeros((height, width), dtype=np.int8)
   _apply_masks(owner, stage, masks, opaque)

   early = [r for r in spec.rules if not r.late]
   late = [r for r in spec.rules if r.late]
   unmapped: set[tuple[int, int, int]] = set()
   waiting: list[tuple[int, int]] = []
   for y, x in zip(*np.nonzero(opaque & (stage == STAGE_NONE))):
      x, y = int(x), int(y)
      rgb = _rgb_at(arr, x, y)
      rule = next((r for r in early if r.color == rgb and r.covers(x, y)), None)
      if rule is not None:
         owner[y, x], stage[y, x] = rule.to, STAGE_RULE
      elif rgb in spec.colors:
         owner[y, x], stage[y, x] = spec.colors[rgb], STAGE_TABLE
      elif rgb == spec.outline:
         waiting.append((x, y))
      else:
         owner[y, x], stage[y, x] = spec.default, STAGE_TABLE
         unmapped.add(rgb)

   # 반경마다 정해진 외곽선이 다음 반경 투표에 낀다 (손 스크립트와 같은 방식).
   _, lost = pieces.vote_each(owner, waiting)
   for x, y in lost:
      owner[y, x] = spec.default
   for x, y in waiting:
      stage[y, x] = STAGE_VOTE

   for rule in late:
      snapshot = owner.copy()
      for y, x in zip(*np.nonzero(opaque & (stage >= STAGE_TABLE))):
         x, y = int(x), int(y)
         if _rgb_at(arr, x, y) != rule.color or not rule.covers(x, y):
            continue
         if rule.source is not None and snapshot[y, x] != rule.source:
            continue
         if rule.near is not None and not pieces.touches(snapshot, x, y, rule.near):
            continue
         owner[y, x] = rule.to
   return owner, unmapped


def _move_pieces(owner, spec: SplitSpec, default_min_piece: int) -> dict[int, dict]:
   """겹마다 떨어진 작은 조각을 이웃 겹으로 옮긴다. 옮길 곳이 없으면 그대로 두고 적는다."""
   result = {}
   already = np.zeros(owner.shape, dtype=bool)
   for idx in range(len(spec.layers)):
      limit = spec.min_piece.get(idx, default_min_piece)
      moved, floating, moved_to = [], [], {}
      # 앞 겹에서 옮겨 온 조각은 다시 보지 않는다. 한 번 옮긴 것이 또 떠돌지 않게.
      for piece in pieces.small_pieces((owner == idx) & ~already, limit):
         target = pieces.vote(owner, piece, exclude={idx})
         if target is None:
            floating.extend([x, y] for x, y in piece)
            continue
         for x, y in piece:
            owner[y, x] = target
            already[y, x] = True
         moved.extend([x, y] for x, y in piece)
         name = spec.layers[target]
         moved_to[name] = moved_to.get(name, 0) + len(piece)
      result[idx] = {"pieces_moved": moved, "pieces_moved_to": moved_to, "pieces_floating": floating}
   return result


def _anchor_xy(box: tuple[int, int, int, int], kind: str) -> tuple[int, int]:
   """bbox 는 끝을 뺀 값이다. 가운데는 floor(v + 0.5) 로 한쪽에 고정한다 (fit_square 와 같은 공식)."""
   x0, y0, x1, y1 = box
   x = math.floor((x0 + x1 - 1) / 2 + 0.5)
   if kind == "bbox_top_center":
      return x, y0
   if kind == "bbox_center":
      return x, math.floor((y0 + y1 - 1) / 2 + 0.5)
   return x, y1 - 1


def roundtrip_diff(original: image.RGBA, stacked: image.RGBA) -> int:
   """다른 픽셀 수. 알파가 다르거나, 불투명한데 색이 다르면 다른 것이다."""
   alpha_diff = original[:, :, 3] != stacked[:, :, 3]
   rgb_diff = np.any(original[:, :, :3] != stacked[:, :, :3], axis=2) & (original[:, :, 3] > 0)
   return int(np.count_nonzero(alpha_diff | rgb_diff))


def split_array(arr: image.RGBA, spec: SplitSpec, masks: dict[int, np.ndarray] | None = None, default_min_piece: int = DEFAULT_MIN_PIECE):
   """겹 그림들과 보고 조각을 돌려준다. 파일은 안 만진다."""
   if image.has_soft_alpha(arr):
      raise ArtToolError("반투명 픽셀이 있다. 색으로 가르므로 섞인 색은 못 가른다")
   owner, unmapped = _assign(arr, spec, masks or {})
   piece_info = _move_pieces(owner, spec, default_min_piece)

   parts = {}
   for idx, name in enumerate(spec.layers):
      layer = image.new(arr.shape[1], arr.shape[0])
      mine = owner == idx
      layer[mine] = arr[mine]
      parts[name] = layer
   diff = roundtrip_diff(arr, layers_mod.compose(spec.layers, parts))
   return parts, {"roundtrip_diff": diff, "unmapped": unmapped, "pieces": piece_info}


def _layer_report(parts, spec: SplitSpec, piece_info: dict, rig: str, book: PointBook, warnings: list[str]) -> dict:
   out = {}
   for idx, name in enumerate(spec.layers):
      layer = parts[name]
      box = image.bbox(layer)
      row = {"pixels": int(np.count_nonzero(layer[:, :, 3] > 0)), "bbox": list(box) if box else None}
      row.update(piece_info[idx])
      out[name] = row
      if box is None:
         warnings.append(f"빈 겹 : {name}")
         continue
      x, y = _anchor_xy(box, spec.anchor.get(idx, ANCHOR_KINDS[0]))
      book.add(rig, "split", "south", 0, name, x, y, idx * 10)
      if row["pieces_floating"]:
         warnings.append(f"{name} 에 옮길 이웃이 없는 조각이 있다 : {row['pieces_floating']}")
   return out


def _load_masks(spec: SplitSpec) -> dict[int, np.ndarray]:
   return {idx: image.load(path)[:, :, 3] > 0 for idx, path in spec.masks.items()}


def run(in_file: str | Path, spec_file: str | Path, out_dir: str | Path, rig_order: list[str] | None = None,
        rig_name: str | None = None, profile_name: str | None = None, default_min_piece: int = DEFAULT_MIN_PIECE) -> dict:
   """`<out>/<겹>/<원본>.png` · 보고 · 앵커를 쓴다. rig_order 를 주면 표의 겹 목록과 같아야 한다."""
   if default_min_piece < 0:
      raise UsageError(f"--min-piece 는 0 이상이다 : {default_min_piece}")
   source = Path(in_file)
   spec_path = Path(spec_file)
   spec = load_spec(read_json(spec_path), spec_path.parent)
   if rig_order is not None and list(rig_order) != spec.layers:
      raise ArtToolError(f"rig 의 layer_order {rig_order} 와 표의 layers {spec.layers} 가 다르다")

   arr = image.load(source)
   parts, info = split_array(arr, spec, _load_masks(spec), default_min_piece)

   root = resolve_root(out_dir)
   for name, layer in parts.items():
      image.save(safe_join(root, f"{name}/{source.name}"), layer)
   # 되돌림은 저장한 파일을 다시 읽어서 본다. 한 파일을 두 겹이 덮어쓴 사고도 여기서 잡힌다.
   saved = {name: image.load(safe_join(root, f"{name}/{source.name}")) for name in spec.layers}
   info["roundtrip_diff"] = roundtrip_diff(arr, layers_mod.compose(spec.layers, saved))

   warnings: list[str] = []
   book = PointBook()
   layer_rows = _layer_report(parts, spec, info["pieces"], rig_name or source.stem, book, warnings)
   unmapped = sorted(to_hex(rgb) for rgb in info["unmapped"])
   if unmapped:
      warnings.append(f"표에 없는 색이 default({spec.layers[spec.default]}) 로 갔다 : {', '.join(unmapped)}")

   status = "ok"
   if warnings:
      status = "warn"
   if info["roundtrip_diff"] != 0:
      status = "fail"
   width, height = image.size(arr)
   report = {
      "status": status,
      "image": source.name,
      "size": [width, height],
      "roundtrip_diff": info["roundtrip_diff"],
      "layers": layer_rows,
      "unmapped_colors": unmapped,
      "warnings": warnings,
      "out": str(root),
   }
   write_json(safe_join(root, REPORT_NAME), report)
   anchors = {"version": ANCHOR_VERSION, "profile": profile_name, "frame": [width, height], "points": book.points}
   write_json(safe_join(root, ANCHORS_NAME), anchors)
   return report


def list_colors(arr: image.RGBA) -> list[dict]:
   """색마다 개수 · bbox · y 범위. 많은 색부터. bbox 와 y 범위는 둘 다 끝을 뺀 값이다."""
   rows = []
   for rgb in image.opaque_colors(arr):
      mask = (arr[:, :, 0] == rgb[0]) & (arr[:, :, 1] == rgb[1]) & (arr[:, :, 2] == rgb[2]) & (arr[:, :, 3] > 0)
      ys, xs = np.nonzero(mask)
      rows.append(
         {
            "hex": to_hex(rgb),
            "count": int(len(xs)),
            "bbox": [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1],
            "y_range": [int(ys.min()), int(ys.max()) + 1],
         }
      )
   return sorted(rows, key=lambda r: (-r["count"], r["hex"]))


def run_list_colors(in_file: str | Path, out_file: str | Path) -> dict:
   source = Path(in_file)
   arr = image.load(source)
   if image.has_soft_alpha(arr):
      raise ArtToolError("반투명 픽셀이 있다. 색으로 가르므로 섞인 색은 못 가른다")
   width, height = image.size(arr)
   data = {"image": source.name, "size": [width, height], "colors": list_colors(arr)}
   out = jailed_output(out_file)
   write_json(out, data)
   return {"out": str(out), "colors": len(data["colors"])}
