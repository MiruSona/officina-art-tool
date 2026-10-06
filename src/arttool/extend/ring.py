"""`extend ring` — 한 바퀴 그림 늘리기 (피드백 후속 설계 3-5, R9).

모서리는 그대로 두고 변의 가운데 단위를 되풀이한다. 셈은 `ui.ninepatch.slice_stretch(mode="tile")` 를 부르기만 한다.
`ui preview --mode tile` 과 다른 점 : 가운데 길이가 단위의 배수가 아니면 끝 단위가 잘린다는 것을 알리고,
`--snap` 이면 가까운 맞는 크기로 바꿔 만든다. 준 크기를 몰래 바꾸지 않게 기본은 경고만 한다.
"""

from __future__ import annotations

from pathlib import Path

from .. import image
from ..checks import warning
from ..edit import dry_run_fields, is_dry_run
from ..errors import UsageError
from ..paths import guard_overwrite, jailed_output
from ..ui.ninepatch import slice_stretch
from . import parse_size

VERSION = 1


def parse_border(text: str) -> list[int]:
   """`N` 또는 `L,B,R,T` → [왼, 아래, 오른, 위]. `ui preview --border` 와 같은 꼴."""
   parts = [p.strip() for p in str(text).split(",")]
   try:
      values = [int(p) for p in parts]
   except ValueError as exc:
      raise UsageError(f"--border 는 N 또는 L,B,R,T 숫자다 : {text}") from exc
   if len(values) == 1:
      values *= 4
   if len(values) != 4 or any(v < 0 for v in values):
      raise UsageError(f"--border 는 0 이상 숫자 하나 또는 넷([왼, 아래, 오른, 위])이다 : {text}")
   return values


def fit_lengths(want: int, low: int, high: int, unit: int) -> tuple[int, int]:
   """한 축에서 가운데가 단위의 배수가 되는 길이 (작은 쪽, 큰 쪽). 작은 쪽은 한 단위 이상이다."""
   whole = (want - low - high) // unit
   small = low + high + max(1, whole) * unit
   big = low + high + (whole + 1) * unit
   return small, big


def _nearest(want: int, small: int, big: int) -> int:
   """가까운 쪽. 같은 거리면 큰 쪽 — 준 자리보다 좁아지지 않게."""
   if want - small < big - want:
      return small
   return big


def run(args) -> dict:
   border = parse_border(args.border)
   req_w, req_h = parse_size(args.size)
   source = Path(args.in_file)
   out_file = jailed_output(args.out_file)
   guard_overwrite([out_file], [source])
   arr = image.load(source)

   src_w, src_h = image.size(arr)
   left, bottom, right, top = border
   if left + right >= src_w or top + bottom >= src_h:
      raise UsageError(f"border {border} 합이 원본 {src_w}x{src_h} 이상이다")
   min_w, min_h = left + right + 1, top + bottom + 1
   if req_w < min_w or req_h < min_h:
      raise UsageError(f"최소 크기 {min_w}x{min_h} 보다 작다 : {req_w}x{req_h}")

   unit_w, unit_h = src_w - left - right, src_h - top - bottom
   partial_w = (req_w - left - right) % unit_w != 0
   partial_h = (req_h - top - bottom) % unit_h != 0
   width, height = req_w, req_h
   fit_sizes = None
   warnings = []
   if partial_w or partial_h:
      small_w, big_w = fit_lengths(req_w, left, right, unit_w) if partial_w else (req_w, req_w)
      small_h, big_h = fit_lengths(req_h, top, bottom, unit_h) if partial_h else (req_h, req_h)
      fit_sizes = [[small_w, small_h], [big_w, big_h]]
      if args.snap:
         width = _nearest(req_w, small_w, big_w)
         height = _nearest(req_h, small_h, big_h)
      else:
         warnings.append(warning("ring.partial_unit",
                                 f"가운데 길이가 단위({unit_w}x{unit_h})의 배수가 아니라 끝 단위가 잘린다. "
                                 f"맞는 크기 : {small_w}x{small_h} · {big_w}x{big_h} (--snap 이면 가까운 쪽으로 만든다)",
                                 fit_sizes))

   image.check_pixels(width, height, "늘린 그림")
   dry_run = is_dry_run(args)
   if not dry_run:
      image.save(out_file, slice_stretch(arr, border, width, height, mode="tile"))
   return {
      "version": VERSION,
      "status": "warn" if warnings else "ok",
      **dry_run_fields(dry_run, [out_file]),
      "in": str(source),
      "out": None if dry_run else str(out_file),
      "border": border,
      "source_size": [src_w, src_h],
      "unit": [unit_w, unit_h],
      "requested": [req_w, req_h],
      "size": [width, height],
      "snapped": [width, height] != [req_w, req_h],
      "fit_sizes": fit_sizes,
      "warnings": warnings,
   }
