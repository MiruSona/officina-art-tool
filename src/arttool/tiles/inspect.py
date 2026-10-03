"""타일 낱장 한 표. 장마다 크기 · bbox · 불투명 비율 · 반투명 · 색 수 · 네 변 · 넘친 픽셀. 설계 문서 6-2.

`Docs/Design/2026-09-23-겹나누기·팔레트굽기·타일·아이콘설계.md`
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .. import check, image
from ..errors import UsageError
from ..profile import Profile

VERSION = 1


def _edges(area: image.RGBA) -> dict[str, bool]:
   """--size 칸 안에서 네 변 줄에 불투명 픽셀이 있나."""
   solid = area[:, :, 3] > 0
   return {
      "top": bool(solid[0].any()),
      "bottom": bool(solid[-1].any()),
      "left": bool(solid[:, 0].any()),
      "right": bool(solid[:, -1].any()),
   }


def inspect_tile(name: str, arr: image.RGBA, size: int) -> dict:
   width, height = image.size(arr)
   solid = arr[:, :, 3] > 0
   alpha = arr[:, :, 3]
   overflow = int(np.count_nonzero(solid)) - int(np.count_nonzero(solid[:size, :size]))
   box = image.bbox(arr)
   return {
      "name": name,
      "size": [width, height],
      "size_ok": (width, height) == (size, size),
      "bbox": list(box) if box else None,
      "opaque_ratio": round(float(np.count_nonzero(solid)) / (width * height), 4),
      "soft_alpha": int(np.count_nonzero((alpha != 0) & (alpha != 255))),
      "colors": image.count_colors(arr),
      "edges": _edges(arr[:size, :size]),
      "overflow": overflow,
   }


def _reasons(row: dict, size: int, binary: bool) -> list[str]:
   out = []
   if not row["size_ok"]:
      out.append(f"크기 {row['size'][0]}x{row['size'][1]} 가 {size}x{size} 와 다르다")
   if row["overflow"]:
      out.append(f"{size}x{size} 밖 불투명 픽셀 {row['overflow']}개")
   if binary and row["soft_alpha"]:
      out.append(f"반투명 픽셀 {row['soft_alpha']}개")
   return out


def run(prof: Profile, in_path: str | Path, size: int | None = None) -> dict:
   """--size 를 안 주면 프로필 tiles.size. 반투명은 프로필 check.allow_alpha 를 따른다."""
   want = int(prof.tiles["size"]) if size is None else size
   if want <= 0:
      raise UsageError(f"--size 는 양수여야 한다 : {want}")
   items = check.load_loose(check.check_source(in_path))
   mode = str(prof.check["allow_alpha"])

   rows, failed, warnings = [], [], []
   for item in items:
      row = inspect_tile(item["where"], item["arr"], want)
      rows.append(row)
      reasons = _reasons(row, want, mode == "binary")
      if reasons:
         failed.append({"name": row["name"], "reasons": reasons})
      if row["bbox"] is None:
         warnings.append(f"{row['name']} : 불투명 픽셀이 하나도 없다")

   status = "fail" if failed else ("warn" if warnings else "ok")
   return {
      "version": VERSION,
      "profile": prof.name,
      "status": status,
      "size": want,
      "allow_alpha": mode,
      "files": len(rows),
      "tiles": rows,
      "failed": failed,
      "warnings": warnings,
   }
