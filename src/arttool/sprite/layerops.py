"""`layers` 묶음 명령 — diff · mask · view · check · export (2026-10-04 개선 설계 10-4).

`compose`(옛 `layers`)는 cli 가 `sprite.layers.compose_sheets` 를 바로 부른다. 여기는 나머지 다섯이다.
겹 묶음 꼴(`layers.json` + `<겹>/<그림>.png`)은 `arttool.layerset` 이 정본이고, 여기서는 픽셀만 다룬다.

- 겹은 캔버스를 안 자른다. 같은 크기 · 같은 좌표라 쌓기만 하면 맞는다.
- 쌓기는 `sprite.layers.compose` — 알파가 0 인 칸만 아래를 남기고 덮어쓴다(섞지 않음).
- 경고 한 줄 꼴은 `check` 와 같다 : `{rule, ok: false, detail, items}`. items 는 [x, y] 좌표(많으면 앞 MAX_POINTS 개).
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from .. import image, layerset, sheet
from ..edit import trim
from ..errors import ArtToolError, UsageError
from ..jsonio import read_json, write_json
from ..palette import parse_hex, to_hex
from ..paths import guard_outside, guard_overwrite, jailed_output, resolve_root, safe_join, same_key
from . import layers as layers_mod
from .split import ANCHOR_KINDS

VERSION = 1
MAX_POINTS = 64
OFFSETS_NAME = "offsets.json"
BASE_LAYER = "body"

# diff --carve : 깎인 윤곽(기본체에선 칠했는데 inpaint 결과에서 투명이 된 칸)을 기본체에서 어떻게 하나.
# report = 본체를 그대로 두고 세기만 · common = 모든 겹이 똑같이 깎은 칸만 뺀다 · apply = 하나라도 깎은 칸을 다 뺀다.
# 기본이 report 인 까닭 : 머리 파츠가 여럿이면 서로 다른 칸을 깎아, 다 빼면 본체에 구멍이 쌓인다.
CARVE_MODES = ("report", "common", "apply")

# diff 에서 겹 이름이 정해진 낱말이 아닐 때 쌓는 순서 · 종류를 정하는 기본 (10-3 캐릭터 줄).
CHAR_ORDER = ("body", "cloth", "face", "hair", "deco")

# layer_poke : exclusive_with 짝이 아닌 겹끼리는 이만큼 넘게 이어진 띠만 「깎인 윤곽의 흔적」으로 본다.
POKE_RUN_MIN = 4


# --- 작은 도우미 ---


def warning(rule: str, detail: str, items: list | None = None) -> dict:
   """`check` 의 warnings 한 줄과 같은 꼴."""
   return {"rule": rule, "ok": False, "detail": detail, "items": items or []}


def _points(mask: np.ndarray) -> list[list[int]]:
   ys, xs = np.nonzero(mask)
   return [[int(x), int(y)] for x, y in zip(xs[:MAX_POINTS], ys[:MAX_POINTS])]


def _opaque(arr: image.RGBA) -> np.ndarray:
   return arr[:, :, 3] > 0


def _changed(base: image.RGBA, other: image.RGBA) -> np.ndarray:
   """알파가 다르거나, 둘 다 불투명한데 색이 다른 칸. `split.roundtrip_diff` 와 같은 뜻."""
   alpha = base[:, :, 3] != other[:, :, 3]
   rgb = np.any(base[:, :, :3] != other[:, :, :3], axis=2) & _opaque(base) & _opaque(other)
   return alpha | rgb


def _grow(mask: np.ndarray, steps: int) -> np.ndarray:
   """여덟 이웃으로 steps 칸 넓힌다(네모 퍼짐). 앞머리 같은 비스듬한 자리를 덜 놓친다."""
   out = mask.copy()
   for _ in range(steps):
      padded = np.pad(out, 1)
      grown = out.copy()
      for dy in (-1, 0, 1):
         for dx in (-1, 0, 1):
            grown |= padded[1 + dy : 1 + dy + out.shape[0], 1 + dx : 1 + dx + out.shape[1]]
      out = grown
   return out


def _shift(mask: np.ndarray, dx: int, dy: int) -> np.ndarray:
   """(x, y) 칸에 (x + dx, y + dy) 칸 값을 놓는다. 캔버스 밖은 거짓."""
   padded = np.pad(mask, 1)
   h, w = mask.shape
   return padded[1 + dy : 1 + dy + h, 1 + dx : 1 + dx + w]


def _names(text: str | None, known: list[str], what: str) -> list[str]:
   if not text:
      return []
   names = [n.strip() for n in text.split(",") if n.strip()]
   unknown = [n for n in names if n not in known]
   if unknown:
      raise UsageError(f"{what} 에 겹 묶음에 없는 겹 : {', '.join(unknown)} (있는 겹 : {', '.join(known)})")
   return names


def _anchor_xy(box: tuple[int, int, int, int], kind: str) -> tuple[int, int]:
   """`split` 의 bbox 앵커와 같은 공식. bbox 는 끝을 뺀 값."""
   x0, y0, x1, y1 = box
   x = math.floor((x0 + x1 - 1) / 2 + 0.5)
   if kind == "bbox_top_center":
      return x, y0
   if kind == "bbox_center":
      return x, math.floor((y0 + y1 - 1) / 2 + 0.5)
   return x, y1 - 1


# --- 겹 묶음 읽기 ---


def _items(folder: Path, ls: layerset.LayerSet) -> list[str]:
   """layers.json 의 items. 비어 있으면 겹 폴더의 PNG 이름을 모은다."""
   if ls.items:
      return list(ls.items)
   found = set()
   for name in ls.names():
      sub = folder / name
      if sub.is_dir():
         found.update(p.stem for p in sub.glob("*.png") if layerset.NAME_RE.match(p.stem))
   if not found:
      raise ArtToolError(f"겹 묶음에 그림이 없다 : {folder}")
   return sorted(found)


def _read_raw(folder: Path, ls: layerset.LayerSet, item: str) -> dict[str, image.RGBA]:
   """크기를 따지지 않고 읽는다(check 가 크기 다름을 경고로 낸다). 없는 파일은 빠진다."""
   out = {}
   for name in ls.names():
      path = layerset.image_path(folder, name, item)
      if path.is_file():
         out[name] = image.load(path)
   return out


def _open_set(in_dir) -> tuple[Path, layerset.LayerSet]:
   folder = Path(in_dir)
   if not folder.is_dir():
      raise ArtToolError(f"겹 묶음 폴더가 없다 : {folder}")
   return folder, layerset.load(folder)


def _stack(ls: layerset.LayerSet, parts: dict[str, image.RGBA], pick: list[str] | None = None) -> image.RGBA:
   order = [n for n in ls.names() if (pick is None or n in pick)]
   chosen = {n: parts[n] for n in order if n in parts}
   if not chosen:
      return image.new(*ls.canvas)
   return layers_mod.compose(order, chosen)


# --- 템플릿 마스크 ---


def _template_masks(template, canvas: tuple[int, int] | None = None) -> dict[str, np.ndarray]:
   """template.json 옆의 `<이름>_mask_<겹>.png` 들. 이름은 JSON 의 name, 없으면 아무 이름이나(`*_mask_<겹>.png`).

   흰(알파 > 0) = 그릴 자리. canvas 를 주면 크기가 같아야 한다.
   """
   if not template:
      return {}
   file = Path(template)
   if not file.is_file():
      raise ArtToolError(f"템플릿 파일이 없다 : {file}")
   data = read_json(file)
   stem = data.get("name") if isinstance(data, dict) and isinstance(data.get("name"), str) else None
   pattern = f"{stem}_mask_*.png" if stem else "*_mask_*.png"
   masks = {}
   for path in sorted(file.parent.glob(pattern)):
      layer = path.stem.rsplit("_mask_", 1)[1]
      if layer in masks:
         raise ArtToolError(f"같은 겹 마스크가 둘 있다 : {layer} ({file.parent})")
      mask = _opaque(image.load(path))
      if canvas is not None and (mask.shape[1], mask.shape[0]) != tuple(canvas):
         raise ArtToolError(f"템플릿 마스크 크기가 canvas 와 다르다 : {path} 이 {mask.shape[1]}x{mask.shape[0]}, canvas {canvas}")
      masks[layer] = mask
   return masks


def _template_layerset(template) -> layerset.LayerSet | None:
   """템플릿 폴더에 `template render` 가 쓴 layers.json 뼈대가 있으면 그 순서 · 종류를 쓴다."""
   if not template:
      return None
   near = Path(template).parent / layerset.FILE_NAME
   return layerset.load(near) if near.is_file() else None


# --- diff ---


def _diff_order(names: list[str], skeleton: layerset.LayerSet | None) -> list[layerset.Layer]:
   """기본체(body) + inpaint 겹들의 쌓는 순서. 뼈대가 있으면 그 순서, 없으면 캐릭터 기본 순서 → 이름 순."""
   wanted = [BASE_LAYER, *names]
   if skeleton is not None:
      missing = [n for n in wanted if n not in skeleton.names()]
      if missing:
         raise ArtToolError(f"템플릿 layers.json 에 없는 겹 : {', '.join(missing)} (있는 겹 : {', '.join(skeleton.names())})")
      return [layer for layer in skeleton.layers if layer.name in wanted]

   def rank(name: str):
      kind = guess_kind(name)
      return (CHAR_ORDER.index(kind) if kind in CHAR_ORDER else len(CHAR_ORDER), name)

   return [layerset.Layer(name, guess_kind(name)) for name in sorted(wanted, key=rank)]


def guess_kind(name: str) -> str:
   """템플릿이 없을 때 겹 이름으로 종류를 짐작한다 (실물 #24).

   이름 그대로 또는 첫 낱말(`_` · `-` 앞)이 종류 낱말이면 그 종류 — `cloth_top` → cloth, `hair-front` → hair.
   아니면 deco. 쌓는 순서는 종류로 정한다 : body < cloth < face < hair < deco, 같은 종류끼리는 이름 순.
   """
   if name in layerset.KINDS:
      return name
   head = name.replace("-", "_").split("_", 1)[0].lower()
   return head if head in layerset.KINDS else "deco"


def _diff_inputs(in_dir, base: Path | None = None) -> tuple[dict[str, Path], bool]:
   """inpaint 결과 PNG → {겹 이름: 경로}, 그리고 기본체가 폴더 안에 있어 뺐는가.

   `--base` 가 `--in` 폴더 안에 있으면 그 파일은 겹이 아니다 — 빼고 센다 (R1-L3).
   """
   folder = Path(in_dir)
   if not folder.is_dir():
      raise ArtToolError(f"inpaint 결과 폴더가 없다 : {folder}")
   base_key = same_key(base) if base is not None else None
   files = {}
   base_inside = False
   for path in sorted(folder.iterdir()):
      if path.suffix.lower() != ".png" or not path.is_file():
         continue
      if base_key is not None and same_key(path) == base_key:
         base_inside = True
         continue
      name = path.stem
      if not layerset.NAME_RE.match(name):
         raise UsageError(f"inpaint 파일 이름 = 겹 이름이라 영숫자 · _ · - 만 쓴다 : {path.name}")
      if name == BASE_LAYER:
         raise UsageError(f"{BASE_LAYER} 는 기본체 겹 이름이라 inpaint 파일 이름으로 못 쓴다 : {path.name}")
      if name.casefold() in (n.casefold() for n in files):
         raise UsageError(f"겹 이름이 겹친다 (대소문자만 달라도 같다) : {path.name}")
      files[name] = path
   if not files:
      raise ArtToolError(f"inpaint 결과 PNG 가 없다 : {folder}")
   return files, base_inside


def run_diff(args) -> dict:
   if args.carve not in CARVE_MODES:
      raise UsageError(f"--carve 는 {' · '.join(CARVE_MODES)} 중 하나다 : {args.carve}")
   base_path = Path(args.base)
   item = base_path.stem
   if not layerset.NAME_RE.match(item):
      raise UsageError(f"기본체 파일 이름이 그림 이름이 된다 — 영숫자 · _ · - 만 쓴다 : {base_path.name}")
   base = image.load(base_path)
   if image.has_soft_alpha(base):
      raise ArtToolError(f"기본체에 반투명 픽셀이 있다. 차이를 칸으로 가르므로 못 받는다 : {base_path}")
   width, height = image.size(base)
   files, base_inside = _diff_inputs(args.in_dir, base_path)
   masks = _template_masks(args.template, (width, height))
   order = _diff_order(list(files), _template_layerset(args.template))
   names = [layer.name for layer in order]

   # 쓸 자리가 읽은 파일(기본체 · inpaint 결과 · 템플릿)을 덮으면 아무것도 쓰기 전에 거절한다 (R1-H3)
   root = resolve_root(Path(args.out_dir))
   writes = [safe_join(root, f"{name}/{item}.png") for name in names] + [safe_join(root, layerset.FILE_NAME)]
   guard_overwrite(writes, [base_path, *files.values(), *_template_files(args.template)])

   base_op = _opaque(base)
   warnings: list[dict] = []
   if base_inside:
      warnings.append(warning("diff_base_in_folder", f"--base {base_path.name} 가 --in 폴더 안에 있어 겹에서 뺐다", [base_path.name]))
   layer_rows: dict[str, dict] = {}
   parts: dict[str, image.RGBA] = {}
   carved: dict[str, np.ndarray] = {}
   for name in names:
      if name == BASE_LAYER:
         continue
      result = image.load(files[name])
      if image.size(result) != (width, height):
         raise ArtToolError(f"inpaint 결과 크기가 기본체와 다르다 : {files[name]} 이 {image.size(result)}, 기본체 {(width, height)}")
      if image.has_soft_alpha(result):
         raise ArtToolError(f"inpaint 결과에 반투명 픽셀이 있다 : {files[name]}")
      changed = _changed(base, result)
      mine = changed & _opaque(result)
      carved[name] = base_op & ~_opaque(result)
      layer = image.new(width, height)
      layer[mine] = result[mine]
      parts[name] = layer
      row = {"changed": int(np.count_nonzero(changed)), "pixels": int(np.count_nonzero(mine)),
             "carved": {"count": int(np.count_nonzero(carved[name])), "points": _points(carved[name])}}
      if name in masks:
         outside = changed & ~masks[name]
         row["outside_mask"] = int(np.count_nonzero(outside))
         if row["outside_mask"]:
            warnings.append(warning("diff_outside_mask", f"{name} : 마스크 밖이 바뀐 칸 {row['outside_mask']}개 (inpaint 면 0 이어야 한다)", _points(outside)))
      layer_rows[name] = row

   # 겹끼리 같은 칸을 칠했으면 쌓는 순서상 위 겹이 갖는다.
   upper = [n for n in reversed(names) if n in parts]
   taken = np.zeros(base_op.shape, dtype=bool)
   for name in upper:
      clash = taken & _opaque(parts[name])
      if np.any(clash):
         parts[name][clash] = 0
         layer_rows[name]["pixels"] = int(np.count_nonzero(_opaque(parts[name])))
         warnings.append(warning("diff_overlap", f"{name} 이 바꾼 칸 {int(np.count_nonzero(clash))}개를 위 겹이 이미 가져갔다 (위 겹이 갖는다)", _points(clash)))
      taken |= _opaque(parts[name])

   # 깎인 윤곽 : report 는 본체를 그대로 두고, common 은 모든 겹이 깎은 칸만, apply 는 하나라도 깎은 칸을 다 뺀다.
   any_carved = np.zeros(base_op.shape, dtype=bool)
   for mask in carved.values():
      any_carved |= mask
   all_carved = np.ones(base_op.shape, dtype=bool) if carved else np.zeros(base_op.shape, dtype=bool)
   for mask in carved.values():
      all_carved &= mask
   removed = {"report": np.zeros(base_op.shape, dtype=bool), "common": all_carved, "apply": any_carved}[args.carve]
   body = base.copy()
   body[removed] = 0
   parts[BASE_LAYER] = body
   layer_rows[BASE_LAYER] = {"pixels": int(np.count_nonzero(_opaque(body))), "carved_removed": int(np.count_nonzero(removed))}
   total_carved = int(np.count_nonzero(any_carved))
   if total_carved:
      kept = total_carved - int(np.count_nonzero(removed))
      warnings.append(warning(
         "diff_carved",
         f"기본체 윤곽이 깎인 칸 {total_carved}개 — 본체에서 뺀 칸 {total_carved - kept}개 · 남긴 칸 {kept}개 (--carve {args.carve})",
         _points(any_carved),
      ))

   ls = layerset.LayerSet((width, height), order, [item], _template_name(args.template))
   for name, path in zip(names, writes):
      image.save(path, parts[name])
   layerset.save(root, ls)

   return {
      "version": VERSION,
      "status": "warn" if warnings else "ok",
      "base": base_path.name,
      "size": [width, height],
      "carve": args.carve,
      "layers": layer_rows,
      "carved_all": {"count": int(np.count_nonzero(all_carved)), "points": _points(all_carved)},
      "warnings": warnings,
      "out": str(root),
   }


def _template_files(template) -> list[Path]:
   """템플릿이 읽는 파일 — template.json · 옆의 layers.json 뼈대 · 마스크 PNG. 덮어쓰기 검사에 쓴다."""
   if not template:
      return []
   file = Path(template)
   return [file, file.parent / layerset.FILE_NAME, *file.parent.glob("*_mask_*.png")]


def _template_name(template) -> str | None:
   if not template:
      return None
   data = read_json(template)
   name = data.get("name") if isinstance(data, dict) else None
   return name if isinstance(name, str) else None


# --- mask ---


def run_mask(args) -> dict:
   if args.grow < 0:
      raise UsageError(f"--grow 는 0 이상이다 : {args.grow}")
   try:
      colors = [parse_hex(text) for text in str(args.colors).split(",") if text.strip()]
   except ArtToolError as exc:
      raise UsageError(str(exc)) from exc
   if not colors:
      raise UsageError("--colors 에 색이 하나 이상 있어야 한다")
   path = jailed_output(args.out_file)
   guard_overwrite([path], [args.in_file])      # 마스크가 기본체를 덮지 않게 (R1-H2)
   arr = image.load(args.in_file)
   op = _opaque(arr)
   mask = np.zeros(op.shape, dtype=bool)
   warnings = []
   for rgb in colors:
      hit = op & (arr[:, :, 0] == rgb[0]) & (arr[:, :, 1] == rgb[1]) & (arr[:, :, 2] == rgb[2])
      if not np.any(hit):
         warnings.append(warning("mask_color_missing", f"그림에 없는 색 : {to_hex(rgb)}"))
      mask |= hit
   picked = int(np.count_nonzero(mask))
   mask = _grow(mask, args.grow)
   out = image.new(*image.size(arr))
   out[mask] = (255, 255, 255, 255)
   image.save(path, out)
   return {
      "status": "warn" if warnings else "ok",
      "out": str(path),
      "colors": [to_hex(c) for c in colors],
      "picked": picked,
      "pixels": int(np.count_nonzero(mask)),
      "grow": args.grow,
      "warnings": warnings,
   }


# --- view ---


def run_view(args) -> dict:
   if args.only and args.hide:
      raise UsageError("--only 와 --hide 는 같이 못 준다")
   if args.scale < 1:
      raise UsageError(f"--scale 은 1 이상이다 : {args.scale}")
   if args.scale > sheet.SCALE_MAX:
      raise UsageError(f"--scale 은 {sheet.SCALE_MAX} 이하다 : {args.scale}")
   folder, ls = _open_set(args.in_dir)
   path = jailed_output(args.out_file)
   guard_outside([path], [folder])          # 겹 묶음 폴더 안에 쓰면 겹 PNG 를 덮을 수 있다 (R1-H2)
   names = ls.names()
   only = _names(args.only, names, "--only")
   hide = _names(args.hide, names, "--hide")
   shown = only or [n for n in names if n not in hide]

   warnings: list[dict] = []
   labels = image.has_label_font()
   if not labels:
      warnings.append(warning("label_font", f"딱지 글꼴이 없어 겹 이름 딱지를 뺐다 (설치가 깨졌다) : {image.LABEL_FONT}"))

   items = _items(folder, ls)
   # 판 크기를 그리기 전에 본다 (sheet 와 같은 셈)
   cell = sheet.kind_size(ls.canvas[0], ls.canvas[1], "zoom", args.scale)
   per_row = (len(shown) + 1) if args.each else 1
   image.check_pixels(*sheet.layout_size([[cell] * per_row for _ in items], labels, labels), "겹 보기판")
   rows = []
   for item in items:
      parts = layerset.read_item(folder, ls, item)
      cells = []
      if args.each:
         cells = [parts.get(n, image.new(*ls.canvas)) for n in shown]
      cells.append(_stack(ls, parts, shown))
      # 비교판(sheet)과 같은 칸 : nearest 확대 + 바둑판 바탕 — 투명 칸이 어디인지 보인다
      rows.append([sheet.render_kind(cell, "zoom", args.scale) for cell in cells])
   col_labels = ([*shown, "합침"] if args.each else ["합침"]) if labels else None
   row_labels = items if labels else None
   board = sheet.layout_rows(rows, row_labels, col_labels)
   image.save(path, board)
   return {
      "status": "warn" if warnings else "ok",
      "out": str(path),
      "layers": shown,
      "each": bool(args.each),
      "items": len(rows),
      "label": labels,
      "warnings": warnings,
   }


# --- check ---


def _poke(lower: np.ndarray, upper: np.ndarray, everything: np.ndarray) -> np.ndarray:
   """아래 겹이 위 겹 바깥으로 1칸 삐진 칸 — 깎인 윤곽의 흔적.

   칸 p 가 아래 겹에만 있고, 한쪽 이웃은 위 겹 · 반대쪽 이웃은 다 빈 칸(또는 캔버스 밖)이면 걸린다.
   위 겹과 바깥 사이에 낀 한 줄 테두리다.

   부르는 쪽(`_check_item`)이 좁힌다 : exclusive_with 짝은 그대로 다 보고, 아닌 짝은 위 겹이 face 면 안 보며
   나머지는 POKE_RUN_MIN 칸 이상 이어진 띠만 남긴다.
   """
   alone = lower & ~upper
   empty = ~everything
   hit = np.zeros(lower.shape, dtype=bool)
   for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
      toward_upper = _shift(upper, dx, dy)
      away_empty = _shift(empty, -dx, -dy) | _outside(lower.shape, -dx, -dy)
      hit |= alone & toward_upper & away_empty
   return hit


def _long_runs(mask: np.ndarray, least: int) -> np.ndarray:
   """여덟 이웃으로 이어진 덩어리 가운데 칸 수가 least 이상인 것만 남긴다.

   깎인 윤곽의 흔적은 위 겹 둘레를 따라 길게 이어진다. 한두 칸 튄 것은 가이드대로 그려도 생긴다.
   걸린 칸은 많지 않아 파이썬으로 훑어도 된다.
   """
   left = {(int(y), int(x)) for y, x in zip(*np.nonzero(mask))}
   keep = np.zeros(mask.shape, dtype=bool)
   while left:
      todo = [left.pop()]
      group = []
      while todo:
         y, x = todo.pop()
         group.append((y, x))
         for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
               near = (y + dy, x + dx)
               if near in left:
                  left.remove(near)
                  todo.append(near)
      if len(group) >= least:
         for y, x in group:
            keep[y, x] = True
   return keep


def _outside(shape, dx: int, dy: int) -> np.ndarray:
   """(x + dx, y + dy) 가 캔버스 밖인 칸."""
   h, w = shape
   out = np.zeros(shape, dtype=bool)
   if dx > 0:
      out[:, w - dx :] = True
   elif dx < 0:
      out[:, : -dx] = True
   if dy > 0:
      out[h - dy :, :] = True
   elif dy < 0:
      out[: -dy, :] = True
   return out


def _check_item(ls: layerset.LayerSet, item: str, raw: dict[str, image.RGBA], masks: dict[str, np.ndarray], warnings: list[dict]) -> dict[str, image.RGBA]:
   """그림 하나의 겹들을 본다. 크기가 맞는 겹만 돌려준다(쌓기 · 원본 대조에 쓴다)."""
   good: dict[str, image.RGBA] = {}
   for name in ls.names():
      layer = ls.layer(name)
      arr = raw.get(name)
      if arr is None:
         if not layer.optional:
            warnings.append(warning("layer_empty", f"{item} : 빈 겹 {name} (파일 없음)"))
         continue
      if image.size(arr) != ls.canvas:
         warnings.append(warning("layer_canvas", f"{item} : {name} 크기 {image.size(arr)} 가 canvas {ls.canvas} 와 다르다"))
         continue
      if image.has_soft_alpha(arr):
         soft = (arr[:, :, 3] != 0) & (arr[:, :, 3] != 255)
         warnings.append(warning("layer_alpha", f"{item} : {name} 에 반투명 칸 {int(np.count_nonzero(soft))}개", _points(soft)))
      if not np.any(_opaque(arr)) and not layer.optional:
         warnings.append(warning("layer_empty", f"{item} : 빈 겹 {name}"))
      if name in masks:
         outside = _opaque(arr) & ~masks[name]
         if np.any(outside):
            warnings.append(warning("layer_mask", f"{item} : {name} 이 템플릿 마스크 밖에 칠한 칸 {int(np.count_nonzero(outside))}개", _points(outside)))
      good[name] = arr

   for a, b in ls.exclusive_pairs():
      if a in good and b in good:
         both = _opaque(good[a]) & _opaque(good[b])
         if np.any(both):
            warnings.append(warning("layer_exclusive", f"{item} : {a} 와 {b} 가 같은 칸 {int(np.count_nonzero(both))}개를 칠했다", _points(both)))

   names = [n for n in ls.names() if n in good]
   if names:
      everything = np.zeros(next(iter(good.values())).shape[:2], dtype=bool)
      for arr in good.values():
         everything |= _opaque(arr)
      exclusive = set(ls.exclusive_pairs())
      for i, low in enumerate(names):
         for high in names[i + 1 :]:
            paired = (low, high) in exclusive
            # 얼굴은 본체 위에 얹어 그린다 — 얼굴 둘레로 본체가 1칸 보이는 것은 정상이다 (스킬 판 S1).
            if not paired and ls.layer(high).kind == "face":
               continue
            poke = _poke(_opaque(good[low]), _opaque(good[high]), everything)
            if not paired:
               poke = _long_runs(poke, POKE_RUN_MIN)
            if np.any(poke):
               warnings.append(warning("layer_poke", f"{item} : {low} 가 {high} 바깥으로 1칸 삐진 칸 {int(np.count_nonzero(poke))}개 (깎인 윤곽의 흔적일 수 있다)", _points(poke)))
   return good


def _pick_original_item(items: list[str], original: Path) -> str:
   if original.stem in items:
      return original.stem
   if len(items) == 1:
      return items[0]
   raise UsageError(f"--original {original.name} 과 짝인 그림을 못 골랐다 — 그림 이름과 같은 파일 이름을 쓴다 (그림 : {', '.join(items)})")


def run_check(args) -> dict:
   folder, ls = _open_set(args.in_dir)
   items = _items(folder, ls)
   masks = _template_masks(args.template, ls.canvas)
   original = Path(args.original) if args.original else None
   target = _pick_original_item(items, original) if original else None

   warnings: list[dict] = []
   rules: list[dict] = []
   roundtrip = None
   for item in items:
      good = _check_item(ls, item, _read_raw(folder, ls, item), masks, warnings)
      if item != target:
         continue
      want = image.load(original)
      if image.size(want) != ls.canvas:
         roundtrip = image.size(want)[0] * image.size(want)[1]
         rules.append({"rule": "original", "ok": False, "detail": f"원본 크기 {image.size(want)} 가 canvas {ls.canvas} 와 다르다", "items": []})
         continue
      diff = _changed(want, _stack(ls, good))
      roundtrip = int(np.count_nonzero(diff))
      rules.append({"rule": "original", "ok": roundtrip == 0, "detail": f"{item} : 합친 결과와 원본이 다른 칸 {roundtrip}개", "items": _points(diff)})

   failed = [r["rule"] for r in rules if not r["ok"]]
   status = "fail" if failed else ("warn" if warnings else "ok")
   report = {
      "version": VERSION,
      "status": status,
      "in": str(folder),
      "canvas": list(ls.canvas),
      "layers": ls.names(),
      "items": items,
      "failed": failed,
      "rules": rules,
      "warnings": warnings,
   }
   if roundtrip is not None:
      report["roundtrip_diff"] = roundtrip
   return report


# --- export ---


def run_export(args) -> dict:
   if not args.flat and not args.each:
      raise UsageError("--flat · --each 중 하나 이상을 준다")
   if args.anchor not in ANCHOR_KINDS:
      raise UsageError(f"--anchor 는 {' · '.join(ANCHOR_KINDS)} 중 하나다 : {args.anchor}")
   folder, ls = _open_set(args.in_dir)
   items = _items(folder, ls)
   loaded = {item: layerset.read_item(folder, ls, item) for item in items}
   flats = {item: _stack(ls, parts) for item, parts in loaded.items()}

   everything = [arr for parts in loaded.values() for arr in parts.values()]
   box = trim.common_bbox(everything)
   if box is None:
      raise ArtToolError(f"겹 묶음이 다 비었다 : {folder}")
   anchor_canvas = _anchor_xy(box, args.anchor)

   outputs: dict[str, image.RGBA] = {}
   seen: dict[str, str] = {}

   def put(key: str, arr: image.RGBA) -> None:
      # 윈도는 대소문자를 안 가린다 — 글자 크기만 다른 이름도 같은 파일이다. flat · each 어느 쪽이 먼저든 잡는다 (R1-M1)
      fold = key.casefold()
      if fold in seen:
         raise ArtToolError(f"내보낼 파일 이름이 겹친다 : {key} 와 {seen[fold]} (그림 이름과 <그림>_<겹> 이 같다)")
      seen[fold] = key
      outputs[key] = arr

   for item in items:
      if args.flat:
         put(f"{item}.png", flats[item])
      if args.each:
         for name in ls.names():
            if name in loaded[item]:
               put(f"{item}_{name}.png", loaded[item][name])

   offset = [0, 0]
   if args.trim_common:
      # 합친 그림은 겹들의 합집합이라 bbox 가 같다 — 내보낼 장 전부를 한 자리에서 자른다(trim --common 과 같은 함수)
      cuts, (ox, oy) = trim.trim_common(list(outputs.values()))
      outputs = dict(zip(outputs, cuts))
      offset = [ox, oy]

   root = resolve_root(args.out_dir)
   targets = {rel: safe_join(root, rel) for rel in outputs}
   reads = [layerset.image_path(folder, name, item) for item in items for name in ls.names()] + [folder / layerset.FILE_NAME]
   guard_overwrite([*targets.values(), safe_join(root, OFFSETS_NAME) if args.trim_common else None], reads)
   for rel, arr in outputs.items():
      image.save(targets[rel], arr)

   anchor = {"kind": args.anchor, "canvas": list(anchor_canvas), "out": [anchor_canvas[0] - offset[0], anchor_canvas[1] - offset[1]]}
   report = {
      "version": VERSION,
      "status": "ok",
      "in": str(folder),
      "out": str(root),
      "files": sorted(outputs),
      "canvas": list(ls.canvas),
      "bbox": list(box),
      "anchor": anchor,
   }
   if args.trim_common:
      size = list(image.size(next(iter(outputs.values()))))
      offsets = {
         "version": VERSION,
         # trim --common 보고와 같은 칸 : pad · square · common · images[file, size_before, size, offset]
         "pad": 0,
         "square": False,
         "common": True,
         "images": [{"file": rel, "size_before": list(ls.canvas), "size": size, "offset": offset} for rel in sorted(outputs)],
         # 겹 묶음에만 있는 칸
         "canvas": list(ls.canvas),
         "bbox": list(box),
         "size": size,
         "anchor": anchor,
         "files": {rel: offset for rel in sorted(outputs)},
      }
      write_json(safe_join(root, OFFSETS_NAME), offsets)
      report["offset"] = offset
      report["offsets"] = OFFSETS_NAME
   return report


# --- 들머리 ---

SUBS = {"diff": run_diff, "mask": run_mask, "view": run_view, "check": run_check, "export": run_export}


def run(args) -> dict:
   func = SUBS.get(getattr(args, "sub", None))
   if func is None:
      raise UsageError(f"모르는 layers 하위 명령 : {getattr(args, 'sub', None)}")
   return func(args)
