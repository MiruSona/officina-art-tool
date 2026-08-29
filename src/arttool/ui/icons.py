"""①ㄷ 아이콘 자르기. 격자(cell · margin · spacing)로 시트를 잘라 낱장과 icons.json 을 낸다."""

from __future__ import annotations

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
         entries.append(_write_icon(prof, root, piece, group, size, row, col, len(entries)))

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


def _write_icon(prof: Profile, root: Path, piece: image.RGBA, group: str, size: int, row: int, col: int, index: int) -> dict:
   name = f"{group}_{index:03d}"
   out_file = safe_join(root, f"{name}.png")
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
