r"""`stitch` — 조각 잇기 (피드백 후속 설계 3-3).

`--in 파일:시작-끝` 을 차례대로 받아 `--axis y`(기본)면 위에서 아래로, `x` 면 왼쪽에서 오른쪽으로 붙인다.
- 구간은 끝을 포함하지 않는다. 비우면 처음 · 끝까지(`12-` · `-40`), 구간을 통째로 빼면 그림 전체.
- **마지막 `:` 뒤가 `숫자?-숫자?` 꼴일 때만 구간으로 본다** — 윈도 드라이브 콜론(`C:\`)과 안 헷갈리게.
- 이음 자리마다 앞 조각 마지막 줄과 뒷 조각 첫 줄의 평균 색 차(`bands.line_delta`)를 적고, 문턱을 넘으면 경고.
"""

from __future__ import annotations

import re

import numpy as np

from .. import image
from ..checks import warning
from ..errors import UsageError
from ..paths import guard_overwrite, jailed_output
from .bands import line_delta

VERSION = 1
SEAM_JUMP = 24.0         # 이음 차가 이보다 크면 경고
AXES = ("x", "y")

_RANGE = re.compile(r"^(\d*)-(\d*)$")


def parse_piece(text: str) -> tuple[str, int | None, int | None]:
   """`파일[:시작-끝]` → (파일, 시작, 끝). 빈 자리는 None."""
   head, sep, tail = str(text).rpartition(":")
   match = _RANGE.match(tail) if sep else None
   if match is None:
      return str(text), None, None
   start = int(match.group(1)) if match.group(1) else None
   end = int(match.group(2)) if match.group(2) else None
   return head, start, end


def _cut(arr: image.RGBA, spec: str, start, end) -> tuple[image.RGBA, list[int]]:
   """조각을 구간대로 자른다. arr 는 이미 「줄 = 첫 축」으로 눕혀 둔 것이다."""
   length = arr.shape[0]
   lo = 0 if start is None else start
   hi = length if end is None else end
   if lo >= hi or hi > length:
      raise UsageError(f"구간이 잘못됐다 : {spec} (길이 {length}, 시작 < 끝 ≤ 길이 여야 한다)")
   return arr[lo:hi], [lo, hi]


def run(args) -> dict:
   axis = str(getattr(args, "axis", "y"))
   if axis not in AXES:
      raise UsageError(f"--axis 는 x 또는 y 다 : {axis}")
   specs = list(args.in_specs)
   if len(specs) < 2:
      raise UsageError(f"이을 조각이 둘 이상이어야 한다 : {len(specs)}개")
   parsed = [parse_piece(spec) for spec in specs]
   out = jailed_output(args.out_file)
   guard_overwrite([out], [p[0] for p in parsed])

   pieces, rows = [], []
   for spec, (file, start, end) in zip(specs, parsed):
      arr = image.load(file)
      work = arr if axis == "y" else arr.transpose(1, 0, 2)
      cut, span = _cut(work, spec, start, end)
      pieces.append(cut)
      rows.append({"file": file, "range": span, "size": list(image.size(arr))})

   # 잇는 방향과 엇갈린 변(axis y 면 폭)이 모두 같아야 한다
   cross = {piece.shape[1] for piece in pieces}
   if len(cross) > 1:
      what = "폭" if axis == "y" else "높이"
      listed = ", ".join(f"{row['file']} {what} {piece.shape[1]}" for row, piece in zip(rows, pieces))
      raise UsageError(f"조각의 {what}이 다르다 : {listed}")

   joins, warnings, at = [], [], 0
   for prev, nxt in zip(pieces, pieces[1:]):
      at += prev.shape[0]
      delta = round(line_delta(prev[-1], nxt[0]), 2)
      joins.append({"at": at, "delta": delta})
      if delta > SEAM_JUMP:
         warnings.append(warning("stitch.seam_jump", f"{axis} {at} 이음 차 {delta} 가 {SEAM_JUMP:g} 를 넘는다 — 이음 자리가 튄다", [at]))

   joined = np.concatenate(pieces, axis=0)
   result = joined if axis == "y" else joined.transpose(1, 0, 2)
   result = np.ascontiguousarray(result)
   image.check_pixels(*image.size(result), "이은 그림")
   image.save(out, result)
   return {
      "version": VERSION,
      "status": "warn" if warnings else "ok",
      "axis": axis,
      "out": str(out),
      "size": list(image.size(result)),
      "pieces": rows,
      "joins": joins,
      "warnings": warnings,
   }
