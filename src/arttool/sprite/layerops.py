"""`layers` 묶음 명령 — diff · mask · view · check · export (2026-10-04 개선 설계 10-4).

`compose`(옛 `layers`)는 cli 가 `sprite.layers.compose_sheets` 를 바로 부른다. 여기는 나머지 다섯이다.
겹 묶음 꼴(`layers.json` + `<겹>/<그림>.png`)은 `arttool.layerset` 이 정본이고, 여기서는 픽셀만 다룬다.

- 겹은 캔버스를 안 자른다. 같은 크기 · 같은 좌표라 쌓기만 하면 맞는다.
- 쌓기는 `sprite.layers.compose` — 알파가 0 인 칸만 아래를 남기고 덮어쓴다(섞지 않음).
- 경고 한 줄 꼴은 `check` 와 같다 : `{rule, ok: false, detail, items}`. items 는 [x, y] 좌표(많으면 앞 MAX_POINTS 개).
"""

from __future__ import annotations

import functools
import math
import os
from pathlib import Path

import numpy as np

from .. import check as check_mod
from .. import image, layerset, sheet
from ..edit import dry_run_fields, is_dry_run, trim
from ..edit import fill as fill_mod
from ..errors import ArtToolError, UsageError
from ..jsonio import read_json, write_json
from ..palette import parse_hex, to_hex
from ..paths import guard_outside, guard_overwrite, jailed_output, resolve_root, safe_join, same_key
from ..pieces import labels as piece_labels
from . import layers as layers_mod
from . import tint as tint_mod
from .split import ANCHOR_KINDS

VERSION = 1
MAX_POINTS = 64
OFFSETS_NAME = "offsets.json"
BASE_LAYER = "body"

# diff --carve : 깎인 윤곽(기본체에선 칠했는데 inpaint 결과에서 투명이 된 칸)을 기본체에서 어떻게 하나.
# report = 본체를 그대로 두고 세기만 · common = 모든 겹이 똑같이 깎은 칸만 뺀다 · apply = 하나라도 깎은 칸을 다 뺀다.
# 기본이 report 인 까닭 : 머리 파츠가 여럿이면 서로 다른 칸을 깎아, 다 빼면 본체에 구멍이 쌓인다.
CARVE_MODES = ("report", "common", "apply")

# diff --drop : 겹에서 뺄 색과의 RGB 각 칸 차 최댓값 기본.
DROP_TOL = 24

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
   return _alpha_changed(base, other) | _rgb_changed(base, other)


def _alpha_changed(base: image.RGBA, other: image.RGBA) -> np.ndarray:
   """알파가 다른 칸 (`diff --alpha-only` 도 쓴다)."""
   return base[:, :, 3] != other[:, :, 3]


def _rgb_changed(base: image.RGBA, other: image.RGBA) -> np.ndarray:
   """둘 다 불투명한데 색이 다른 칸."""
   return np.any(base[:, :, :3] != other[:, :, :3], axis=2) & _opaque(base) & _opaque(other)


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


def _names(text: str | None, known: list[str], what: str, noun: str = "겹") -> list[str]:
   """쉼표 목록을 이름으로 나눈다. noun 은 오류 문구에서 부르는 이름(겹 · 그림)."""
   if not text:
      return []
   names = [n.strip() for n in text.split(",") if n.strip()]
   unknown = [n for n in names if n not in known]
   if unknown:
      raise UsageError(f"{what} 에 겹 묶음에 없는 {noun} : {', '.join(unknown)} (있는 {noun} : {', '.join(known)})")
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
   """크기를 따지지 않고 읽는다(check 가 크기 다름을 경고로 낸다). 없는 파일은 빠진다.

   작은 겹은 그림이 그 겹의 size 와 같을 때만 캔버스로 펴서 돌려준다. 다르면 날것 그대로 둬서
   check 가 크기 다름 경고를 내게 한다.
   """
   out = {}
   for layer in ls.layers:
      path = layerset.image_path(folder, ls, layer.name, item)
      if path is not None and path.is_file():
         arr = image.load(path)
         if layer.small and image.size(arr) == layer.size:
            arr = layerset.expand(ls, layer, arr)
         out[layer.name] = arr
   return out


def _open_set(in_dir) -> tuple[Path, layerset.LayerSet]:
   folder = Path(in_dir)
   if not folder.is_dir():
      raise ArtToolError(f"겹 묶음 폴더가 없다 : {folder}")
   return folder, layerset.load(folder)


def _split_names(text) -> list[str]:
   return [n.strip() for n in str(text).split(",") if n.strip()] if text else []


def _open_like(in_dir, order: list[str] | None, masks: list[str], what: str = "--in") -> tuple[Path, layerset.LayerSet]:
   """layers.json 이 있으면 그것, 없고 order 가 있으면 맨 폴더로 (7판 4절). 둘 다면 거절. what 은 거절 문구에 쓰는 인자 이름."""
   if not order:
      return _open_set(in_dir)
   folder = Path(in_dir)
   if not folder.is_dir():
      raise ArtToolError(f"겹 묶음 폴더가 없다 ({what}) : {folder}")
   if (folder / layerset.FILE_NAME).exists():
      raise UsageError(f"--order 를 줬는데 {what} 폴더에 {layerset.FILE_NAME} 이 있다 — 둘 중 무엇을 믿을지 헷갈리지 않게 하나만 쓴다 : {folder}")
   return folder, layerset.from_folder(folder, order, masks)


def _open_any(args) -> tuple[Path, layerset.LayerSet, bool]:
   """--in 을 연다. 돌려줌 : (폴더, 묶음, 맨 폴더인가)."""
   order = _split_names(getattr(args, "order", None))
   masks = _split_names(getattr(args, "masks", None))
   if masks and not order:
      raise UsageError("--masks 는 --order 와 같이 쓴다 (layers.json 묶음은 겹 kind 를 mask 로 적는다)")
   folder, ls = _open_like(args.in_dir, order, masks)
   return folder, ls, bool(order)


def mask_base(ls: layerset.LayerSet, text) -> str | None:
   """--mask-of 기준겹 검사 (check · view 공용). 이름 하나 · 묶음에 마스크 겹이 있음 · 기준겹은 그리는 겹. 틀리면 종료 2."""
   if not text:
      return None
   base = _names(text, ls.names(), "--mask-of")
   if len(base) != 1:
      raise UsageError(f"--mask-of 는 기준겹 하나다 : {text}")
   if ls.layer(base[0]).is_mask:
      raise UsageError(f"--mask-of 기준겹이 마스크 겹이다 — 그리는 겹을 준다 : {base[0]}")
   if not any(layer.is_mask for layer in ls.layers):
      raise UsageError("--mask-of : 묶음에 마스크 겹(kind: mask)이 없다 (맨 폴더면 --masks 로 적는다)")
   return base[0]


def _inferred_head(report: dict, ls: layerset.LayerSet, inferred: bool) -> dict:
   """맨 폴더일 때만 보고 맨 위(version 다음)에 inferred · order 를 단다."""
   if not inferred:
      return report
   head = {"version": report["version"]} if "version" in report else {}
   return {**head, "inferred": True, "order": ls.names(), **{k: v for k, v in report.items() if k != "version"}}


def _stack(ls: layerset.LayerSet, parts: dict[str, image.RGBA], pick: list[str] | None = None) -> image.RGBA:
   """쌓은 그림. 마스크 겹(kind: mask)은 그리는 겹이 아니라 빠진다 (7판 5절)."""
   order = [n for n in ls.painted() if (pick is None or n in pick)]
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


# 맨 폴더 모드(7판 4절)도 써서 layerset 으로 옮겼다. 이름은 그대로 둔다.
guess_kind = layerset.guess_kind


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


def _parse_drop(specs, drop_tol, layer_names: list[str]) -> dict[str, list[tuple[int, int, int]]]:
   """`--drop 겹:#hex,#hex` (여러 번) → {겹: [색…]}. 같은 겹을 두 번 주면 색을 합친다. 기본체에는 못 쓴다."""
   if not specs:
      return {}
   if isinstance(specs, str):
      specs = [specs]
   if not 0 <= int(drop_tol) <= 255:
      raise UsageError(f"--drop-tol 은 0~255 다 : {drop_tol}")
   out: dict[str, list[tuple[int, int, int]]] = {}
   for spec in specs:
      name, sep, text = str(spec).partition(":")
      name = name.strip()
      if not sep or not text.strip():
         raise UsageError(f"--drop 은 겹이름:#RRGGBB[,#RRGGBB…] 꼴이다 : {spec}")
      if name not in layer_names:
         raise UsageError(f"--drop 에 inpaint 결과에 없는 겹 : {name} (있는 겹 : {', '.join(layer_names)})")
      try:
         colors = [parse_hex(part) for part in text.split(",") if part.strip()]
      except ArtToolError as exc:
         raise UsageError(f"--drop 색을 못 읽었다 : {spec} (#RRGGBB 꼴)") from exc
      out.setdefault(name, []).extend(colors)
   return out


def _near_colors(arr: image.RGBA, colors: list[tuple[int, int, int]], tol: int) -> np.ndarray:
   """불투명 칸 중 colors 가운데 하나와 RGB 각 칸 차가 모두 tol 이하인 칸."""
   rgb = arr[:, :, :3].astype(np.int16)
   hit = np.zeros(arr.shape[:2], dtype=bool)
   for color in colors:
      hit |= np.abs(rgb - np.array(color, dtype=np.int16)).max(axis=2) <= tol
   return hit & _opaque(arr)


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
   drop_tol = int(getattr(args, "drop_tol", DROP_TOL))
   drops = _parse_drop(getattr(args, "drop", None), drop_tol, list(files))

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
      if name in drops:
         # 마스크 안에서 다시 그려진 뺨 · 옷 점 같은 색을 이 겹에서 뺀다. 뺀 칸은 아래 본체가 보인다.
         dropped = _near_colors(layer, drops[name], drop_tol)
         layer[dropped] = 0
         row["dropped"] = int(np.count_nonzero(dropped))
         row["pixels"] = int(np.count_nonzero(_opaque(layer)))
         if row["dropped"]:
            warnings.append(warning("diff_dropped", f"{name} : --drop 색에 가까운 칸 {row['dropped']}개를 겹에서 뺐다 (--drop-tol {drop_tol})", _points(dropped)))
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
   layerset.from_dict(ls.to_dict(), "(layers diff)")   # 뼈대의 작은 겹 상자가 기본체 크기를 넘으면 쓰기 전에 거절
   # 작은 겹은 상자로 잘라 쓴다. 상자 밖 칸은 crop_to_box 가 거절한다 — 한 장이라도 쓰기 전에 다 잘라 본다.
   cut = {name: layerset.crop_to_box(ls.layer(name), parts[name], f"layers diff {name}") for name in names}
   for name, path in zip(names, writes):
      image.save(path, cut[name])
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
   dry_run = is_dry_run(args)
   if not dry_run:
      image.save(path, out)
   return {
      "status": "warn" if warnings else "ok",
      **dry_run_fields(dry_run, [path]),
      "out": None if dry_run else str(path),
      "colors": [to_hex(c) for c in colors],
      "picked": picked,
      "pixels": int(np.count_nonzero(mask)),
      "grow": args.grow,
      "warnings": warnings,
   }


# --- view ---

TINT_MAX = 32   # --tint 물들임 칸 수 상한 (사례 7 · 8 크기에서 어림, 7판 2-5)


def _tint_table(raw: dict, ls: layerset.LayerSet, mask_base: str | None, where: str) -> dict[str, tuple[int, int, int]]:
   """{겹: #hex} → {겹: (r, g, b)}. 마스크 겹 열쇠는 --mask-of 기준겹의 그 마스크 안 칸을 칠한다."""
   out = {}
   for name, text in raw.items():
      if name not in ls.names():
         raise UsageError(f"{where} 에 겹 묶음에 없는 겹 : {name} (있는 겹 : {', '.join(ls.names())})")
      if ls.layer(name).is_mask and mask_base is None:
         raise UsageError(f"{where} 의 {name} 은 마스크 겹이다 — 어느 겹을 칠할지 --mask-of 로 준다")
      try:
         out[name] = parse_hex(str(text))
      except ArtToolError as exc:
         raise UsageError(f"{where} 의 색을 못 읽었다 : {name}={text} (#RRGGBB 꼴)") from exc
   return out


def _parse_tints(specs, ls: layerset.LayerSet, mask_base: str | None) -> list[tuple[str, dict]]:
   """--tint 들 → [(칸 이름, 물들임 표)]. 글자 `겹=#hex,…` 는 한 칸(이름 = 그 글자), `.json` 은 [{name, tint}] 칸 여럿."""
   cols: list[tuple[str, dict]] = []
   for spec in specs or []:
      text = str(spec).strip()
      if text.lower().endswith(".json"):
         data = read_json(text)
         if not isinstance(data, list) or not data:
            raise UsageError(f"--tint JSON 은 [{{name, tint}}, …] 비지 않은 목록이다 : {text}")
         if len(cols) + len(data) > TINT_MAX:   # 칸마다 풀어 보기 전에 개수부터 — 큰 목록을 다 훑지 않는다
            raise UsageError(f"--tint 물들임 칸은 {TINT_MAX}개까지다")
         for n, entry in enumerate(data):
            spot = f"--tint {Path(text).name} 의 {n}번"
            if not isinstance(entry, dict) or set(entry) != {"name", "tint"}:
               raise UsageError(f"{spot} 은 name · tint 두 칸 객체다")
            if not isinstance(entry["name"], str) or not entry["name"].strip() or not isinstance(entry["tint"], dict):
               raise UsageError(f"{spot} : name 은 글, tint 는 {{겹: #hex}} 사전이다")
            cols.append((entry["name"], _tint_table(entry["tint"], ls, mask_base, spot)))
      else:
         raw = {}
         for part in text.split(","):
            name, sep, color = part.partition("=")
            if not sep or not name.strip():
               raise UsageError(f"--tint 는 겹=#RRGGBB[,겹=#RRGGBB…] 또는 .json 이다 : {text}")
            raw[name.strip()] = color.strip()
         cols.append((text, _tint_table(raw, ls, mask_base, "--tint")))
      if len(cols) > TINT_MAX:
         raise UsageError(f"--tint 물들임 칸은 {TINT_MAX}개까지다")
   return cols


def _tinted(ls: layerset.LayerSet, parts: dict[str, image.RGBA], table: dict, mask_base: str | None, shown: list[str] | None) -> image.RGBA:
   """물들임 표 하나로 쌓은 그림. 표에 있는 겹은 색을 곱하고(`tint`), 마스크 열쇠는 기준겹의 그 마스크 안 칸만 곱한다.

   마스크 칸은 기준겹 **원래 색**에 곱한다 — 기준겹 자체 물들임 위에 또 곱하지 않는다. 마스크가 겹치면 뒤 마스크가 이긴다.
   """
   painted = {}
   for name in ls.painted():
      if name not in parts or (shown is not None and name not in shown):
         continue
      arr = parts[name]
      out = tint_mod.tint(arr, table[name]) if name in table else arr.copy()
      if name == mask_base:
         for mask in ls.names():
            if mask in table and ls.layer(mask).is_mask and mask in parts:
               cells = _opaque(parts[mask]) & _opaque(arr)
               out[cells] = tint_mod.tint(arr, table[mask])[cells]
      painted[name] = out
   return _stack(ls, painted)


def run_view(args) -> dict:
   if args.only and args.hide:
      raise UsageError("--only 와 --hide 는 같이 못 준다")
   if args.scale < 1:
      raise UsageError(f"--scale 은 1 이상이다 : {args.scale}")
   if args.scale > sheet.SCALE_MAX:
      raise UsageError(f"--scale 은 {sheet.SCALE_MAX} 이하다 : {args.scale}")
   folder, ls, inferred = _open_any(args)
   path = jailed_output(args.out_file)
   guard_outside([path], [folder])          # 겹 묶음 폴더 안에 쓰면 겹 PNG 를 덮을 수 있다 (R1-H2)
   names = ls.names()
   only = _names(args.only, names, "--only")
   hide = _names(args.hide, names, "--hide")
   shown = only or [n for n in names if n not in hide]
   tint_specs = getattr(args, "tint", None)
   if tint_specs and args.each:
      raise UsageError("--tint 와 --each 는 같이 못 준다 (판이 너무 넓어진다)")
   if getattr(args, "mask_of", None) and not tint_specs:
      raise UsageError("layers view --mask-of 는 --tint 와 같이 쓴다")
   base = mask_base(ls, getattr(args, "mask_of", None))
   tints = _parse_tints(tint_specs, ls, base)

   warnings: list[dict] = []
   labels = image.has_label_font()
   if not labels:
      warnings.append(warning("label_font", f"딱지 글꼴이 없어 겹 이름 딱지를 뺐다 (설치가 깨졌다) : {image.LABEL_FONT}"))

   items = _items(folder, ls)
   # 판 크기를 그리기 전에 본다 (sheet 와 같은 셈)
   cell = sheet.kind_size(ls.canvas[0], ls.canvas[1], "zoom", args.scale)
   per_row = (len(shown) + 1) if args.each else (len(tints) or 1)
   image.check_pixels(*sheet.layout_size([[cell] * per_row for _ in items], labels, labels), "겹 보기판")
   rows = []
   for item in items:
      parts = layerset.read_item(folder, ls, item)
      cells = []
      if args.each:
         cells = [parts.get(n, image.new(*ls.canvas)) for n in shown]
      if tints:
         cells = [_tinted(ls, parts, table, base, shown) for _, table in tints]
      else:
         cells.append(_stack(ls, parts, shown))
      # 비교판(sheet)과 같은 칸 : nearest 확대 + 바둑판 바탕 — 투명 칸이 어디인지 보인다
      rows.append([sheet.render_kind(cell, "zoom", args.scale) for cell in cells])
   col_labels = ([name for name, _ in tints] if tints else [*shown, "합침"] if args.each else ["합침"]) if labels else None
   row_labels = items if labels else None
   board = sheet.layout_rows(rows, row_labels, col_labels)
   dry_run = is_dry_run(args)
   if not dry_run:
      image.save(path, board)
   return _inferred_head({
      "status": "warn" if warnings else "ok",
      **dry_run_fields(dry_run, [path]),
      "out": None if dry_run else str(path),
      "layers": shown,
      "each": bool(args.each),
      "items": len(rows),
      "label": labels,
      "warnings": warnings,
      **({"tints": [name for name, _ in tints]} if tints else {}),   # --tint 를 줄 때만
   }, ls, inferred)


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
   pick = ls.picks.get(item)
   for name in ls.names():
      if pick is not None and name not in pick:   # 사전 꼴 그림은 pick 에 있는 겹만 갖는다 — 빠진 겹은 빈 겹이 아니다
         continue
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
      if a in good and b in good and not (ls.layer(a).is_mask or ls.layer(b).is_mask):
         both = _opaque(good[a]) & _opaque(good[b])
         if np.any(both):
            warnings.append(warning("layer_exclusive", f"{item} : {a} 와 {b} 가 같은 칸 {int(np.count_nonzero(both))}개를 칠했다", _points(both)))

   names = [n for n in ls.painted() if n in good]   # 마스크 겹은 칠한 칸이 아니라 삐짐을 안 본다
   if names:
      everything = np.zeros(good[names[0]].shape[:2], dtype=bool)
      for name in names:
         everything |= _opaque(good[name])
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


VARIANTS_SCAN_MAX = 4096   # 변형 파일을 찾으려 폴더 하나를 훑을 때 볼 항목 수 상한 — 넘으면 거절


def _scan_variants(folder: Path, ls: layerset.LayerSet) -> dict[str, list[str]]:
   """겹마다 files 무늬(없으면 `<겹>/{v}.png`)에 맞는 파일들의 {v} 값. 무늬의 폴더 하나만 본다.

   같은 폴더를 쓰는 겹들은 그 폴더를 한 번 훑어 나눈다 — 파일마다 맞는 겹 무늬 가운데 앞이 가장 긴 겹 하나에만
   (`hair_{v}.png` · `hair_front_{v}.png`, 리뷰 7-1).
   """
   root = resolve_root(folder)
   groups: dict[str, dict[str, tuple[str, str]]] = {}
   for layer in ls.layers:
      head, _, tail = layerset._pattern(layer).rpartition("/")
      prefix, _, suffix = tail.partition(layerset.FILES_SLOT)
      groups.setdefault(head, {})[layer.name] = (prefix, suffix)
   out: dict[str, list[str]] = {}
   for head, patterns in groups.items():
      parent = safe_join(root, head) if head else root
      names = []
      if parent.is_dir():
         # Path.iterdir 는 (3.13+) 폴더를 통째로 목록으로 만든 뒤 돌려준다. scandir 로 흘려 읽어야 상한이 훑는 도중에 걸린다.
         # 링크는 따라가지 않는다 (is_file(follow_symlinks=False)) — 묶음 폴더 밖 파일을 변형으로 세지 않게.
         with os.scandir(parent) as entries:
            for n, entry in enumerate(entries):
               if n >= VARIANTS_SCAN_MAX:
                  raise UsageError(f"layers check : {parent} 에 항목이 {VARIANTS_SCAN_MAX}개보다 많아 변형을 다 훑지 않는다")
               if entry.is_file(follow_symlinks=False):
                  names.append(entry.name)
      for name, found in layerset.assign_stems(names, patterns).items():
         out[name] = sorted(found)
   return {layer.name: out[layer.name] for layer in ls.layers}


def _check_variants(folder: Path, ls: layerset.LayerSet, items: list[str], warnings: list[dict]) -> dict[str, list[str]]:
   """변형 하나하나에 낱장 검사(크기 · 반투명)를 돌리고, 어느 그림도 안 고른 변형을 경고한다."""
   variants = _scan_variants(folder, ls)
   for layer in ls.layers:
      used = set()
      for item in items:
         pick = ls.picks.get(item)
         if pick is None:
            used.add(item)
         elif layer.name in pick:
            used.add(pick[layer.name])
      want = tuple(layer.size) if layer.size is not None else ls.canvas
      head = layerset._pattern(layer)
      for v in variants[layer.name]:
         rel = head.replace(layerset.FILES_SLOT, v)
         if v not in used:
            warnings.append(warning("unused_variant", f"{layer.name} : 어느 그림의 pick 도 안 고른 변형 {v} ({rel})"))
         arr = image.load(safe_join(resolve_root(folder), rel))
         if image.size(arr) != want:
            warnings.append(warning("variant_size", f"{layer.name} 변형 {v} : 크기 {image.size(arr)} 가 {want} 와 다르다"))
         elif image.has_soft_alpha(arr):
            soft = (arr[:, :, 3] != 0) & (arr[:, :, 3] != 255)
            warnings.append(warning("variant_alpha", f"{layer.name} 변형 {v} : 반투명 칸 {int(np.count_nonzero(soft))}개", _points(soft)))
   return variants


def run_check(args) -> dict:
   from .layerchecks import Extra   # 7판 검사는 이 모듈의 도우미를 쓴다 — 맨 위에서 읽으면 서로 물린다

   folder, ls, inferred = _open_any(args)
   items = _items(folder, ls)
   # 새 인자 검사는 그림을 읽기 전에. 전 판은 이번 판과 같은 길(layers.json 또는 같은 --order · --masks)로 연다
   order, bare_masks = (_split_names(getattr(args, k, None)) for k in ("order", "masks"))
   open_before = functools.partial(_open_like, order=order, masks=bare_masks, what="--before")
   extra = Extra(args, folder, ls, items, inferred, open_before=open_before)
   masks = _template_masks(args.template, ls.canvas)
   original = Path(args.original) if args.original else None
   target = _pick_original_item(items, original) if original else None

   cover = _load_cover(args.cover, ls.canvas) if getattr(args, "cover", None) else None

   warnings: list[dict] = []
   rules: list[dict] = []
   cover_rows: list[dict] = []
   roundtrip = None
   for item in items:
      good = _check_item(ls, item, _read_raw(folder, ls, item), masks, warnings)
      extra.item(item, good, warnings)
      if cover is not None:
         cover_rows.append(_cover_item(item, _painted_parts(ls, good), cover, Path(args.cover).name, rules, warnings))
      if item != target:
         continue
      want = image.load(original)
      if image.size(want) != ls.canvas:
         roundtrip = image.size(want)[0] * image.size(want)[1]
         rules.append({"rule": "original", "ok": False, "detail": f"원본 크기 {image.size(want)} 가 canvas {ls.canvas} 와 다르다", "items": []})
         continue
      extra.original(item, good, want, warnings)
      diff = _changed(want, _stack(ls, good))
      roundtrip = int(np.count_nonzero(diff))
      rules.append({"rule": "original", "ok": roundtrip == 0, "detail": f"{item} : 합친 결과와 원본이 다른 칸 {roundtrip}개", "items": _points(diff)})

   # files 무늬 · 사전 꼴 items 를 쓴 묶음만 변형을 본다 — 안 쓴 묶음의 보고는 예전과 바이트까지 같다
   variants = None
   # 맨 폴더는 그림 목록 = 파일 목록이라 안 쓴 변형이 없다 — 장 수는 counts 가 본다
   if not inferred and (ls.picks or any(layer.files is not None for layer in ls.layers)):
      variants = _check_variants(folder, ls, items, warnings)
   added: dict = {}
   extra.finish(added, warnings)

   failed = list(dict.fromkeys(r["rule"] for r in rules if not r["ok"]))   # cover 는 그림마다 줄이 생겨 겹칠 수 있다
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
   if variants is not None:
      report["variants"] = variants
   if roundtrip is not None:
      report["roundtrip_diff"] = roundtrip
   if cover is not None:   # --cover 를 안 주면 보고 꼴이 예전 그대로다
      report["cover"] = cover_rows
   report.update(added)    # 7판 칸 — 새 인자 · anchor 칸이 없으면 비어 있다
   report = _inferred_head(report, ls, inferred)
   known, baseline, fail_on_new = (getattr(args, k, None) for k in ("known", "baseline", "fail_on_new"))
   if known or baseline or fail_on_new:   # 셋 다 없으면 부르지 않는다 — 보고 바이트 그대로
      report = check_mod.apply_known(report, check_mod.load_known(known, baseline), fail_on_new)
   return report


def _painted_parts(ls: layerset.LayerSet, parts: dict[str, image.RGBA]) -> dict[str, image.RGBA]:
   """마스크 겹을 뺀 겹들 (가림판 · 빈 칸 셈에 쓴다)."""
   keep = set(ls.painted())
   return {name: arr for name, arr in parts.items() if name in keep}


def _load_cover(path, canvas: tuple[int, int]) -> np.ndarray:
   """가림판 PNG → 덮여야 할 칸(알파 > 0). 캔버스와 크기가 다르면 거절한다 — 칸 자리가 어긋난 채 세지 않게."""
   arr = image.load(path)   # 픽셀 상한은 image.load 가 본다
   if image.size(arr) != canvas:
      raise UsageError(f"가림판 크기 {image.size(arr)} 가 canvas {canvas} 와 다르다 : {path}")
   return arr[..., 3] > 0


def _coverage(parts: dict[str, image.RGBA], shape) -> np.ndarray:
   """칸마다 몇 겹이 칠했나 (알파 > 0). 캔버스 크기가 아닌 겹은 check 가 따로 경고하므로 뺀다."""
   count = np.zeros(shape, dtype=np.int32)
   for arr in parts.values():
      if arr.shape[:2] == shape:
         count += arr[..., 3] > 0
   return count


def _cover_item(item: str, parts: dict[str, image.RGBA], cover: np.ndarray, mask_name: str, rules: list[dict], warnings: list[dict]) -> dict:
   """가림판 안에서 빈 칸(어느 겹도 안 덮음)은 실패, 둘 이상이 덮은 칸은 경고만 (겹침이 뜻한 것일 수 있다)."""
   count = _coverage(parts, cover.shape)
   empty = cover & (count == 0)
   overlap = cover & (count >= 2)
   n_empty, n_overlap = int(np.count_nonzero(empty)), int(np.count_nonzero(overlap))
   rules.append({"rule": "cover", "ok": n_empty == 0, "detail": f"{item} : 가림판 안 빈 칸 {n_empty}개", "items": _points(empty)})
   if n_empty:
      warnings.append(warning("cover_empty", f"{item} : 가림판 안을 어느 겹도 안 덮은 칸 {n_empty}개", _points(empty)))
   if n_overlap:
      warnings.append(warning("cover_overlap", f"{item} : 가림판 안을 둘 이상의 겹이 덮은 칸 {n_overlap}개", _points(overlap)))
   return {"item": item, "mask": mask_name, "cells": int(np.count_nonzero(cover)), "empty": n_empty, "overlap": n_overlap}


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
   reads = [p for item in items for name in ls.names() if (p := layerset.image_path(folder, ls, name, item)) is not None] + [folder / layerset.FILE_NAME]
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

# --- fill ---

_NEIGHBORS8 = [(dy, dx) for dy in (-1, 0, 1) for dx in (-1, 0, 1) if (dy, dx) != (0, 0)]


def _nearest_source(seed: np.ndarray, need: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
   """seed(불투명 칸)에서 8방향으로 한 칸씩 번져 칸마다 체비셰프 거리와 가장 가까운 seed 칸 (y, x) 을 찾는다.

   3x3 로 한 번 번지면 체비셰프 거리가 1 는다. need 칸이 다 닿거나 더 번질 데가 없으면 멈춘다 —
   칸마다 도는 Python 이중 루프 대신 판 전체를 numpy 로 민다(한 걸음 = 판 8번 밀기).
   """
   h, w = seed.shape
   dist = np.full((h, w), np.iinfo(np.int32).max, dtype=np.int32)
   ys, xs = np.indices((h, w), dtype=np.int32)
   src_y = np.where(seed, ys, -1).astype(np.int32)
   src_x = np.where(seed, xs, -1).astype(np.int32)
   dist[seed] = 0
   reached = seed.copy()
   step = 0
   while not np.all(reached[need]):
      step += 1
      grown = reached.copy()
      for dy, dx in _NEIGHBORS8:
         # 이웃 (y+dy, x+dx) 가 이미 닿았고 나는 아직이면 그 이웃의 출처를 물려받는다
         nb = np.zeros_like(reached)
         nb_y = np.full_like(src_y, -1)
         nb_x = np.full_like(src_x, -1)
         ty, sy = slice(max(0, -dy), h - max(0, dy)), slice(max(0, dy), h - max(0, -dy))
         tx, sx = slice(max(0, -dx), w - max(0, dx)), slice(max(0, dx), w - max(0, -dx))
         nb[ty, tx] = reached[sy, sx]
         nb_y[ty, tx] = src_y[sy, sx]
         nb_x[ty, tx] = src_x[sy, sx]
         take = nb & ~grown
         src_y[take], src_x[take] = nb_y[take], nb_x[take]
         grown |= take
      new = grown & ~reached
      if not np.any(new):
         break
      dist[new] = step
      reached = grown
   return dist, src_y, src_x


def _fill_plan(ls: layerset.LayerSet, parts: dict[str, image.RGBA], cover: np.ndarray, nearest: list[str]) -> tuple[dict[str, np.ndarray], list[str], int]:
   """빈 칸(가림판 안 · 어느 겹도 안 덮음)을 후보 겹에 나눈다. 거리 같으면 --nearest 목록 앞 겹.

   작은 겹은 상자 밖 칸의 후보에서 빠진다(거리를 무한대로) — 그 칸은 다음으로 가까운 겹이 채운다.
   돌려줌 : {겹: (칸 마스크, 출처 y, 출처 x)} · 그 그림에 있는 후보 · 어느 후보도 상자 밖이라 못 채운 칸 수.
   """
   empty = cover & (_coverage(_painted_parts(ls, parts), cover.shape) == 0)
   cands = [n for n in nearest if n in parts and np.any(parts[n][..., 3] > 0)]
   if not cands or not np.any(empty):
      return {}, cands, 0
   found = [_nearest_source(parts[n][..., 3] > 0, empty) for n in cands]
   far = np.iinfo(np.int32).max
   dists = np.stack([d for d, _, _ in found])
   reach = np.min(dists, axis=0) < far                              # 상자를 따지기 전에 닿는 칸
   for i, name in enumerate(cands):
      layer = ls.layer(name)
      if layer.small:   # 작은 겹은 상자 밖에 못 쓴다 — 그 칸에서는 후보가 아니다
         (x, y), (bw, bh) = layer.offset, layer.size
         inside = np.zeros(dists.shape[1:], dtype=bool)
         inside[y:y + bh, x:x + bw] = True
         dists[i][~inside] = far
   pick = np.argmin(dists, axis=0)                                  # argmin 은 같으면 앞 것 — 목록 앞 겹
   ok = np.min(dists, axis=0) < far
   outside = int(np.count_nonzero(empty & reach & ~ok))             # 모든 후보가 상자 밖이라 못 채운 칸
   plan = {}
   for i, name in enumerate(cands):
      cells = empty & ok & (pick == i)
      if np.any(cells):
         plan[name] = (cells, found[i][1], found[i][2])
   return plan, cands, outside


HOLE_MAX = 32    # fill --holes 기본 : 이보다 큰 구멍은 뜻한 빈 곳(고리 · 손잡이 안)일 수 있어 안 메운다.
                 # 실측(7판) : 실수 구멍은 많아야 19칸, 일부러 둔 구멍은 2~1,759칸 — 256 이면 손잡이 안을 메운다
FAR = 10 ** 9


def _row_sources(opaque: np.ndarray, need: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
   """need 칸마다 같은 행에서 가장 가까운 불투명 칸 (y, x). 거리 같으면 왼쪽. 그 행에 없으면 -1."""
   src_y = np.full(need.shape, -1, dtype=np.int64)
   src_x = np.full(need.shape, -1, dtype=np.int64)
   for y in np.unique(np.nonzero(need)[0]):
      have = np.nonzero(opaque[y])[0]
      if len(have) == 0:
         continue
      xs = np.nonzero(need[y])[0]
      at = np.searchsorted(have, xs)
      left = np.where(at > 0, have[np.clip(at - 1, 0, len(have) - 1)], -FAR)    # 왼쪽에 없으면 아주 멀리
      right = np.where(at < len(have), have[np.clip(at, 0, len(have) - 1)], FAR)
      src_x[y, xs] = np.where(xs - left <= right - xs, left, right)
      src_y[y, xs] = y
   return src_y, src_x


def _fill_holes_item(ls: layerset.LayerSet, item: str, parts: dict[str, image.RGBA], holes: list[str], hole_max: int,
                     out: Path, writes: dict, warnings: list[dict]) -> dict | None:
   """겹 자신의 안쪽 구멍(`fill --enclosed` 와 같은 뜻)을 그 겹 자신의 색으로 메운다 (7판 3절).

   칸마다 ① 같은 행 가장 가까운 불투명 칸 색 ② 그 행에 없으면 가장 가까운(체비셰프) 칸 색을 그대로 옮긴다 — 평균을 안 낸다.
   new_colors 는 메운 뒤 색을 실제로 다시 센 값이다(늘 0 이어야 하고, 아니면 그 자체가 버그 신호).
   """
   present = [n for n in holes if n in parts]
   if not present:
      warnings.append(warning("fill_no_target", f"{item} : --holes 겹이 이 그림에 없어 건너뛰었다"))
      return None
   filled, new_colors = {}, {}
   for name in present:
      arr = parts[name]
      label, sizes = piece_labels(fill_mod.enclosed(arr))
      big = sizes > hole_max
      inside = label >= 0
      too_big = inside & big[np.where(inside, label, 0)] if len(sizes) else inside
      if np.any(too_big):
         warnings.append(warning("fill_hole_skipped", f"{item} : {name} 의 구멍 {int(big.sum())}개({int(np.count_nonzero(too_big))}칸)가 --hole-max {hole_max} 칸보다 커서 안 메웠다 (뜻한 빈 곳일 수 있다)", _points(too_big)))
      need = inside & ~too_big
      if not np.any(need):
         continue
      seed = _opaque(arr)
      src_y, src_x = _row_sources(seed, need)
      rest = need & (src_x < 0)
      if np.any(rest):   # 늘 없다 — 지킴용. 갇힌 칸은 같은 행 양쪽에 칠한 칸이 있다. 그래도 조용히 빼먹지 않게
         _, near_y, near_x = _nearest_source(seed, rest)
         src_y[rest], src_x[rest] = near_y[rest], near_x[rest]
      fixed = arr.copy()
      fixed[need] = arr[src_y[need], src_x[need]]
      dst = layerset.image_path(out, ls, name, item)
      if dst is None:
         raise UsageError(f"layers fill : 그림 {item} 의 pick 에 겹 {name} 이 없다")
      writes[dst] = layerset.crop_to_box(ls.layer(name), fixed, f"layers fill {item}")
      filled[name] = int(np.count_nonzero(need))
      new_colors[name] = len(image.opaque_colors(fixed) - image.opaque_colors(arr))
   return {"item": item, "filled": filled, "new_colors": new_colors}


def run_fill(args) -> dict:
   folder, ls, inferred = _open_any(args)
   items = _items(folder, ls)
   pick = _names(args.items, items, "--items", "그림") if args.items else items
   holes_text = getattr(args, "holes", None)
   hole_max = getattr(args, "hole_max", None)
   if bool(args.mask) == bool(holes_text):
      raise UsageError("layers fill : --mask(가림판 빈 칸) 와 --holes(겹 안쪽 구멍) 중 하나만 준다")
   if holes_text:
      return _run_fill_holes(args, folder, ls, inferred, items, pick, holes_text, hole_max)
   if hole_max is not None:
      raise UsageError("--hole-max 는 --holes 와 같이 쓴다")
   nearest = _names(args.nearest, ls.names(), "--nearest")
   if not nearest:
      raise UsageError("--nearest 에 겹이 하나 이상 있어야 한다")
   masks = [n for n in nearest if ls.layer(n).is_mask]
   if masks:
      raise UsageError(f"--nearest 에 마스크 겹(kind: mask)은 못 쓴다 — 그리는 겹이 아니다 : {', '.join(masks)}")
   color = None
   if args.color:
      try:
         color = parse_hex(args.color)
      except ArtToolError as exc:
         raise UsageError(str(exc)) from exc
   out = _fill_out(args, folder)
   cover = _load_cover(args.mask, ls.canvas)

   warnings: list[dict] = []
   rows: list[dict] = []
   writes: dict[Path, image.RGBA | Path] = {}
   for item in items:
      _copy_plan(folder, ls, item, out, writes)
      if item not in pick:
         continue
      parts = layerset.read_item(folder, ls, item)
      plan, cands, outside = _fill_plan(ls, parts, cover, nearest)
      if not cands:
         warnings.append(warning("fill_no_target", f"{item} : --nearest 겹이 이 그림에 없어 건너뛰었다"))
         continue
      if outside:
         warnings.append(warning("fill_outside_box", f"{item} : 작은 겹 상자 밖이라 못 채운 칸 {outside}개"))
      filled = {}
      for name, (cells, src_y, src_x) in plan.items():
         layer = ls.layer(name)
         arr = parts[name].copy()
         if color is not None:
            arr[cells] = (*color, 255)
         else:
            arr[cells] = parts[name][src_y[cells], src_x[cells]]
         dst = layerset.image_path(out, ls, name, item)
         if dst is None:   # 사전 꼴 그림의 pick 에 없는 겹은 그 그림에 없다 — 새로 만들지 않고 거절
            raise UsageError(f"layers fill : 그림 {item} 의 pick 에 겹 {name} 이 없다")
         writes[dst] = layerset.crop_to_box(layer, arr, f"layers fill {item}")
         filled[name] = int(np.count_nonzero(cells))
      rows.append({"item": item, "filled": filled})

   dry_run = is_dry_run(args)
   listed = _write_fill(dry_run, folder, out, inferred, writes)
   return _inferred_head({
      "version": VERSION,
      "status": "warn" if warnings else "ok",
      **dry_run_fields(dry_run, [*listed, *writes]),
      "in": str(folder),
      "cover": Path(args.mask).name,   # "mask" 칸은 다른 명령에서 쓴 가림판 경로라 이름을 가른다
      "nearest": nearest,
      "color": to_hex(color) if color else None,
      "images": rows,
      "warnings": warnings,
      "out": None if dry_run else str(out),
   }, ls, inferred)


def _fill_out(args, folder: Path) -> Path:
   out = jailed_output(args.out_dir)
   guard_outside([out], [folder])                    # 원본 묶음 안에 쓰지 않는다
   guard_outside([folder], [out], "--in")            # 원본 묶음을 품은 폴더에도 안 쓴다
   if out.exists() and (not out.is_dir() or any(out.iterdir())):
      raise UsageError(f"--out 은 없거나 빈 폴더여야 한다 (원본 묶음을 안 덮는다) : {out}")
   return out


def _copy_plan(folder: Path, ls: layerset.LayerSet, item: str, out: Path, writes: dict) -> None:
   for layer in ls.layers:   # 손 안 대는 겹은 바이트 그대로 복사
      src = layerset.image_path(folder, ls, layer.name, item)
      if src is not None and src.is_file():
         writes[layerset.image_path(out, ls, layer.name, item)] = src


def _write_fill(dry_run: bool, folder: Path, out: Path, inferred: bool, writes: dict) -> list[Path]:
   """새 묶음을 쓴다(dry-run 이면 안 쓴다). 돌려줌 : writes 말고 더 쓰는(쓸) 파일 — layers.json."""
   listed = [] if inferred else [out / layerset.FILE_NAME]
   if not dry_run:
      out.mkdir(parents=True, exist_ok=True)
      if not inferred:   # 맨 폴더는 목록 없이 같은 꼴(하위 폴더 · <겹>_<그림>.png)로만 쓴다
         (out / layerset.FILE_NAME).write_bytes((folder / layerset.FILE_NAME).read_bytes())   # layers.json 도 바이트 그대로
      for dst, what in writes.items():
         dst.parent.mkdir(parents=True, exist_ok=True)
         if isinstance(what, Path):
            dst.write_bytes(what.read_bytes())
         else:
            image.save(dst, what)
   return listed


def _run_fill_holes(args, folder: Path, ls: layerset.LayerSet, inferred: bool, items: list[str], pick: list[str], holes_text, hole_max) -> dict:
   if args.color:
      raise UsageError("--holes 와 --color 는 같이 못 준다 — 구멍은 겹 자신의 색으로만 메운다 (새 색을 안 만든다)")
   if args.nearest:
      raise UsageError("--holes 는 --nearest 를 안 받는다 — 겹 자신의 색으로 메운다")
   holes = _names(holes_text, ls.names(), "--holes")
   masks = [n for n in holes if ls.layer(n).is_mask]
   if masks:
      raise UsageError(f"--holes 에 마스크 겹(kind: mask)은 못 쓴다 : {', '.join(masks)}")
   hole_max = HOLE_MAX if hole_max is None else int(hole_max)
   if hole_max < 1:
      raise UsageError(f"--hole-max 는 1 이상이다 : {hole_max}")
   out = _fill_out(args, folder)
   warnings: list[dict] = []
   rows: list[dict] = []
   writes: dict[Path, image.RGBA | Path] = {}
   for item in items:
      _copy_plan(folder, ls, item, out, writes)
      if item in pick:
         row = _fill_holes_item(ls, item, layerset.read_item(folder, ls, item), holes, hole_max, out, writes, warnings)
         if row is not None:
            rows.append(row)
   dry_run = is_dry_run(args)
   listed = _write_fill(dry_run, folder, out, inferred, writes)
   return _inferred_head({
      "version": VERSION,
      "status": "warn" if warnings else "ok",
      **dry_run_fields(dry_run, [*listed, *writes]),
      "in": str(folder),
      "holes": holes,
      "hole_max": hole_max,
      "images": rows,
      "warnings": warnings,
      "out": None if dry_run else str(out),
   }, ls, inferred)


SUBS = {"diff": run_diff, "mask": run_mask, "view": run_view, "check": run_check, "export": run_export, "fill": run_fill}


def run(args) -> dict:
   func = SUBS.get(getattr(args, "sub", None))
   if func is None:
      raise UsageError(f"모르는 layers 하위 명령 : {getattr(args, 'sub', None)}")
   return func(args)
