"""`diff --alpha-only` — 색 손질 뒤 알파가 그대로인가 (2026-10-06 2판 설계 C3).

PNG 둘, 또는 폴더 둘(같은 이름끼리 짝)을 견준다. 크기가 다르면 그 짝은 실패, 같으면 알파가 다른 칸을 센다.
검사 명령이라 다른 짝이 하나라도 있거나 짝이 하나도 없으면 `status: fail`(종료 4). 파일은 안 쓴다.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .. import image
from ..checks import warning
from ..edit import list_inputs
from ..errors import UsageError
from .layerops import _alpha_changed, _points

VERSION = 1


def _pairs(a: str, b: str) -> tuple[list[tuple[Path, Path]], list[str]]:
   """(짝 목록, 한쪽에만 있는 이름)."""
   if Path(a).is_dir() != Path(b).is_dir():
      raise UsageError("--a 와 --b 는 둘 다 파일이거나 둘 다 폴더여야 한다")
   left, right = list_inputs(a), list_inputs(b)
   if not Path(a).is_dir():
      return [(left[0], right[0])], []
   by_name = {p.name: p for p in right}
   pairs = [(p, by_name[p.name]) for p in left if p.name in by_name]
   names_left = {p.name for p in left}
   unpaired = sorted([p.name for p in left if p.name not in by_name] + [n for n in by_name if n not in names_left])
   return pairs, unpaired


def _box(mask: np.ndarray) -> list[int] | None:
   ys, xs = np.nonzero(mask)
   if len(xs) == 0:
      return None
   return [int(xs.min()), int(ys.min()), int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)]


def run(args) -> dict:
   if not getattr(args, "alpha_only", False):
      raise UsageError("지금은 --alpha-only 방식뿐이다 — --alpha-only 를 준다")
   pairs, unpaired = _pairs(args.a, args.b)
   rows, failed = [], False
   for left, right in pairs:
      a, b = image.load(left), image.load(right)
      if a.shape != b.shape:
         failed = True
         rows.append({"where": left.name, "same": False, "size_a": [a.shape[1], a.shape[0]],
                      "size_b": [b.shape[1], b.shape[0]], "detail": "크기가 다르다"})
         continue
      mask = _alpha_changed(a, b)
      changed = int(np.count_nonzero(mask))
      failed |= changed > 0
      rows.append({"where": left.name, "same": changed == 0, "changed": changed, "box": _box(mask), "points": _points(mask)})

   warnings = []
   if unpaired:
      warnings.append(warning("diff.unpaired", f"한쪽에만 있는 파일 : {', '.join(unpaired)}", unpaired))
   if not pairs:
      # 견줄 짝이 하나도 없으면 아무것도 안 본 것이다 — 통과로 두면 폴더를 잘못 줘도 모른다.
      failed = True
      warnings.append(warning("diff.no_pairs", "두 폴더에 같은 이름의 PNG 가 하나도 없다 — 견준 것이 없다", []))
   return {
      "version": VERSION,
      "status": "fail" if failed else ("warn" if warnings else "ok"),
      "alpha_only": True,
      "images": rows,
      "warnings": warnings,
      "out": None,
   }
