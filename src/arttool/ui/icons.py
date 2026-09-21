"""①ㄷ 아이콘 들이기. 시트를 격자로 자르거나(cut), 이미 낱장인 PNG 를 모은다(gather).

둘 다 낱장 PNG 와 icons.json 한 장을 낸다.
"""

from __future__ import annotations

import math
from pathlib import Path

from .. import image
from ..errors import ArtToolError
from ..jsonio import write_json
from ..paths import resolve_root, safe_join
from ..profile import Profile

VERSION = 1


def grid_count(total: int, cell: int, margin: int, spacing: int, axis: str) -> int:
   """한 축에 칸이 몇 개 들어가나. 딱 안 떨어지면 오류."""
   usable = total - 2 * margin
   if usable < cell:
      raise ArtToolError(f"격자가 시트 크기와 안 맞는다 : {axis} {total}px 에 칸 {cell}px 이 안 들어간다")

   count = (usable + spacing) // (cell + spacing)
   used = 2 * margin + count * cell + (count - 1) * spacing
   if used != total:
      raise ArtToolError(f"격자가 시트 크기와 안 맞는다 : {axis} {total}px 인데 격자는 {used}px 을 쓴다")
   return count


def hotspot_of(prof: Profile, cell: int) -> list[int]:
   spot = prof.ui["icon"]["hotspot"]
   if isinstance(spot, (list, tuple)):
      return [int(spot[0]), int(spot[1])]
   if spot == "top_left":
      return [0, 0]
   return [cell // 2, cell // 2]


def cut(prof: Profile, sheet_path: str | Path, out_dir: str | Path, cell: int | None = None, family: str | None = None) -> dict:
   source = Path(sheet_path)
   icon = prof.ui["icon"]
   size = int(cell or icon["sheet"]["cell"])
   if size not in [int(s) for s in icon["sizes"]]:
      raise ArtToolError(f"칸 크기 {size} 는 ui.icon.sizes {icon['sizes']} 밖이다")

   margin = int(icon["sheet"]["margin"])
   spacing = int(icon["sheet"]["spacing"])
   arr = image.load(source)
   width, height = image.size(arr)
   cols = grid_count(width, size, margin, spacing, "가로")
   rows = grid_count(height, size, margin, spacing, "세로")

   root = resolve_root(out_dir)
   group = family or source.stem
   entries = []
   empty = 0
   for row in range(rows):
      for col in range(cols):
         x = margin + col * (size + spacing)
         y = margin + row * (size + spacing)
         piece = image.crop(arr, x, y, size, size)
         if image.bbox(piece) is None:
            empty += 1
            continue
         name = f"{group}_{len(entries):03d}"
         entries.append(_write_icon(prof, root, piece, name, group, size, row, col))

   data = {
      "version": VERSION,
      "profile": prof.name,
      "cell": size,
      "grid": [cols, rows],
      "empty_cells": empty,
      "icons": entries,
   }
   write_json(safe_join(root, "icons.json"), data)
   return data


def fit_square(arr: image.RGBA, side: int, where: str) -> image.RGBA:
   """bbox 로 자르고 side×side 가운데에 붙인다. 중심 공식은 sprite/normalize.fit_frame 과 같다."""
   box = image.bbox(arr)
   if box is None:
      raise ArtToolError(f"빈 그림이다 : {where}")

   x0, y0, x1, y1 = box
   content = image.crop(arr, x0, y0, x1 - x0, y1 - y0)
   width, height = image.size(content)
   if width > side or height > side:
      raise ArtToolError(f"그림 {width}x{height} 가 {side}x{side} 보다 크다 : {where}")

   # round 는 .5 를 짝수 쪽으로 보내서 크기에 따라 중심이 1픽셀 튄다. floor(x+0.5) 로 한쪽으로 고정한다.
   center = (side - 1) / 2.0
   canvas = image.new(side, side)
   image.paste(canvas, content, math.floor(center - width / 2.0 + 0.5), math.floor(center - height / 2.0 + 0.5))
   return canvas


def png_files(source: Path) -> list[Path]:
   """폴더 바로 아래 PNG 만 이름순으로. 확장자 대소문자는 가리지 않고 하위 폴더는 안 본다."""
   return sorted(p for p in source.iterdir() if p.is_file() and p.suffix.lower() == ".png")


def gather(prof: Profile, in_dir: str | Path, out_dir: str | Path, family: str | None = None, fit: int | None = None) -> dict:
   """이미 낱장인 PNG 를 모아 icons.json 한 장을 낸다. 자르지 않는다."""
   source = Path(in_dir)
   files = png_files(source)
   if not files:
      raise ArtToolError(f"들일 PNG 가 하나도 없다 : {source}")

   sizes = [int(s) for s in prof.ui["icon"]["sizes"]]
   root = resolve_root(out_dir)
   # 제자리라도 --fit 으로 그림을 고쳤으면 덮어써야 icons.json 의 크기와 파일이 맞는다.
   save = (source.resolve() != root) or bool(fit)
   group = family or source.name

   entries = []
   empty = 0
   for file in files:
      arr = image.load(file)
      if image.bbox(arr) is None:
         empty += 1
         continue
      if fit:
         arr = fit_square(arr, int(fit), file.name)
      side = _icon_side(arr, sizes, file.name)
      entries.append(_write_icon(prof, root, arr, file.stem, group, side, 0, len(entries), save))

   if not entries:
      raise ArtToolError(f"들일 PNG 가 다 비어 있다 : {source}")

   found = sorted({int(e["size"]) for e in entries})
   data = {
      "version": VERSION,
      "profile": prof.name,
      "cell": found[0] if len(found) == 1 else None,
      "sizes": found,
      "grid": [len(entries), 1],
      "empty_cells": empty,
      "icons": entries,
   }
   write_json(safe_join(root, "icons.json"), data)
   return data


def _icon_side(arr: image.RGBA, sizes: list[int], name: str) -> int:
   """정사각형이고 크기가 프로필 가족 안인지 본다."""
   width, height = image.size(arr)
   if width != height:
      raise ArtToolError(f"아이콘이 정사각형이 아니다 : {name} ({width}x{height})")
   if width not in sizes:
      raise ArtToolError(f"아이콘 크기 {width} 는 ui.icon.sizes {sizes} 밖이다 : {name}. 프로필 ui.icon.sizes 에 더하라")
   return width


def _write_icon(
   prof: Profile, root: Path, piece: image.RGBA, name: str, group: str, size: int, row: int, col: int, save: bool = True
) -> dict:
   out_file = safe_join(root, f"{name}.png")
   if save:
      image.save(out_file, piece)
   return {
      "name": name,
      "file": out_file.name,
      "size": size,
      "family": group,
      "row": row,
      "col": col,
      "hotspot": hotspot_of(prof, size),
   }
