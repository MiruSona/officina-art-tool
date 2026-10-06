"""`extend canvas` — 배경 늘리기 (피드백 후속 설계 3-5, R8).

원본을 `--anchor` 자리에 두고, 새로 생긴 칸은 그쪽 가장자리의 `--band` 줄을 바깥으로 되풀이해 채운다.
되풀이 위상은 원본에서 이어진다 — 원본 위로 늘리면 바로 위 줄이 띠의 마지막 줄이다.
축마다 「결과 칸 → 원본 칸」 표를 만들어 칸을 고르기만 한다(보간 없음).
"""

from __future__ import annotations

from pathlib import Path

from .. import image
from ..checks import warning
from ..edit import dry_run_fields, is_dry_run
from ..errors import UsageError
from ..paths import guard_overwrite, jailed_output
from . import parse_size

VERSION = 1
ANCHORS = ("top", "bottom", "left", "right", "center", "top-left", "top-right", "bottom-left", "bottom-right")
BUSY_COLORS = 4       # --band 1 인데 가장자리 줄 색이 이보다 많으면 줄무늬가 생긴다


def _offset(anchor: str, small: int, big: int, low: str, high: str) -> int:
   """한 축에서 원본을 놓을 자리. low 쪽 이름이면 0, high 쪽이면 끝, 둘 다 아니면 가운데."""
   if low in anchor:
      return 0
   if high in anchor:
      return big - small
   return (big - small) // 2


# trim --canvas 가 놓을 자리 셈만 빌린다 (가장자리 채움은 안 빌린다).
offset = _offset


def axis_map(length: int, offset: int, total: int, band: int) -> list[int]:
   """한 축의 결과 칸 → 원본 칸. 원본 앞쪽은 처음 band 줄을, 뒤쪽은 마지막 band 줄을 위상 맞춰 되풀이한다."""
   picks = []
   for index in range(total):
      rel = index - offset
      if rel < 0:
         picks.append(rel % band)
      elif rel >= length:
         picks.append(length - band + (rel - length + band) % band)
      else:
         picks.append(rel)
   return picks


def _grown_edges(offset: tuple[int, int], size: tuple[int, int], src: tuple[int, int]) -> list[str]:
   ox, oy = offset
   width, height = size
   src_w, src_h = src
   edges = []
   if oy > 0:
      edges.append("top")
   if oy + src_h < height:
      edges.append("bottom")
   if ox > 0:
      edges.append("left")
   if ox + src_w < width:
      edges.append("right")
   return edges


def _edge_line(arr: image.RGBA, edge: str) -> image.RGBA:
   """가장자리 한 줄을 (1, 길이, 4) 그림으로."""
   if edge == "top":
      return arr[:1]
   if edge == "bottom":
      return arr[-1:]
   if edge == "left":
      return arr[:, :1]
   return arr[:, -1:]


def run(args) -> dict:
   anchor = str(args.anchor)
   if anchor not in ANCHORS:
      raise UsageError(f"--anchor 는 {', '.join(ANCHORS)} 중 하나다 : {anchor}")
   band = int(args.band)
   if band < 1:
      raise UsageError(f"--band 는 1 이상이다 : {band}")
   width, height = parse_size(args.size)

   source = Path(args.in_file)
   out_file = jailed_output(args.out_file)
   guard_overwrite([out_file], [source])
   arr = image.load(source)
   src_w, src_h = image.size(arr)
   if width < src_w or height < src_h:
      raise UsageError(f"--size {width}x{height} 가 원본 {src_w}x{src_h} 보다 작은 변이 있다. 자르기는 trim · stitch 로 한다")
   image.check_pixels(width, height, "늘린 그림")

   ox = _offset(anchor, src_w, width, "left", "right")
   oy = _offset(anchor, src_h, height, "top", "bottom")
   edges = _grown_edges((ox, oy), (width, height), (src_w, src_h))
   if any(e in ("top", "bottom") for e in edges) and band > src_h:
      raise UsageError(f"--band {band} 가 원본 높이 {src_h} 를 넘는다")
   if any(e in ("left", "right") for e in edges) and band > src_w:
      raise UsageError(f"--band {band} 가 원본 너비 {src_w} 를 넘는다")

   warnings = []
   if band == 1:
      busy = [e for e in edges if image.count_colors(_edge_line(arr, e)) > BUSY_COLORS]
      if busy:
         warnings.append(warning("canvas.edge_busy",
                                 f"가장자리 줄 색이 {BUSY_COLORS}개 넘는다 — 한 줄 되풀이면 줄무늬가 생긴다. --band 16 같은 값을 준다",
                                 busy))

   ys = axis_map(src_h, oy, height, band)
   xs = axis_map(src_w, ox, width, band)
   out = arr[ys][:, xs].copy()
   dry_run = is_dry_run(args)
   if not dry_run:
      image.save(out_file, out)

   return {
      "version": VERSION,
      "status": "warn" if warnings else "ok",
      **dry_run_fields(dry_run, [out_file]),
      "in": str(source),
      "out": None if dry_run else str(out_file),
      "source_size": [src_w, src_h],
      "size": [width, height],
      "anchor": anchor,
      "band": band,
      "offset": [ox, oy],
      "grown": edges,
      "warnings": warnings,
   }
