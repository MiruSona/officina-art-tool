"""`trim` — 둘레의 빈 여백을 걷는다 (설계 4-2).

- 불투명 칸의 bbox 로 자른다. 정사각형이 아니어도 된다.
- `--square` : 긴 변에 맞춰 정사각으로 채운다. 가운데 맞춤은 `ui.icons.fit_square` 와 같은 floor(v + 0.5).
- `--pad N` : 자르고(정사각으로 채운) 뒤 둘레에 투명 N 칸.
- `--common` : 폴더 전체에 bbox 하나. 겹 폴더를 잘라도 쌓은 자리가 그대로다.

보고의 `offset` 은 **결과 그림의 (0, 0) 이 원본에서 어디였나**다. pad · square 로 늘린 몫까지 넣은 값이라
음수일 수 있다. 원래 자리로 되돌릴 때는 원본 캔버스의 (offset) 에 결과를 그대로 얹으면 된다.
"""

from __future__ import annotations

import math
from pathlib import Path

from .. import image
from ..checks import warning
from ..errors import ArtToolError, UsageError
from . import list_inputs, plan_outputs

VERSION = 1
Box = tuple[int, int, int, int]


def common_bbox(arrs: list[image.RGBA]) -> Box | None:
   """여러 장의 bbox 를 합친 하나. 모두 비었으면 None. 그림 크기는 같아야 한다."""
   sizes = {image.size(arr) for arr in arrs}
   if len(sizes) > 1:
      raise ArtToolError(f"--common 은 크기가 같은 그림만 받는다 : {sorted(sizes)}")
   boxes = [b for b in (image.bbox(arr) for arr in arrs) if b is not None]
   if not boxes:
      return None
   return min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)


def crop_box(arr: image.RGBA, box: Box, pad: int = 0, square: bool = False) -> tuple[image.RGBA, tuple[int, int]]:
   """box 로 자르고 square · pad 를 입힌 그림과 offset (결과 (0,0) 의 원본 좌표)."""
   x0, y0, x1, y1 = box
   content = image.crop(arr, x0, y0, x1 - x0, y1 - y0)
   width, height = x1 - x0, y1 - y0
   left = top = 0
   side_w, side_h = width, height
   if square:
      side_w = side_h = max(width, height)
      # round 는 .5 를 짝수 쪽으로 보내 크기마다 1칸 튄다. floor(x+0.5) 로 한쪽에 고정한다 (fit_square 와 같은 공식).
      center = (side_w - 1) / 2.0
      left = math.floor(center - width / 2.0 + 0.5)
      top = math.floor(center - height / 2.0 + 0.5)
   out_w, out_h = side_w + pad * 2, side_h + pad * 2
   image.check_pixels(out_w, out_h, "잘라 낸 그림")
   canvas = image.new(out_w, out_h)
   canvas[pad + top : pad + top + height, pad + left : pad + left + width] = content
   return canvas, (x0 - pad - left, y0 - pad - top)


def trim_common(arrs: list[image.RGBA], pad: int = 0, square: bool = False) -> tuple[list[image.RGBA], tuple[int, int]] | None:
   """여러 장(겹)을 bbox 하나로 같은 자리에서 자른다. 모두 비었으면 None.

   돌려주는 offset 하나가 모든 장에 같다 — 결과를 그대로 쌓으면 원래 겹 순서 · 자리 그대로다.
   `layers export --trim-common` 이 이 함수를 쓴다.
   """
   box = common_bbox(arrs)
   if box is None:
      return None
   cut = [crop_box(arr, box, pad, square) for arr in arrs]
   return [c[0] for c in cut], cut[0][1]


def trim_one(arr: image.RGBA, pad: int = 0, square: bool = False) -> tuple[image.RGBA, tuple[int, int]] | None:
   """한 장을 제 bbox 로 자른다. 비었으면 None."""
   box = image.bbox(arr)
   if box is None:
      return None
   return crop_box(arr, box, pad, square)


def _check_same_size(files: list[Path], arrs: list[image.RGBA]) -> None:
   """--common 은 크기가 같은 그림만 받는다. 다르면 어느 파일이 다른지 적어 UsageError (실물 버그 8)."""
   sizes = [image.size(arr) for arr in arrs]
   counts: dict[tuple[int, int], int] = {}
   for size in sizes:
      counts[size] = counts.get(size, 0) + 1
   if len(counts) <= 1:
      return
   # 가장 많은 크기를 기준으로, 그와 다른 파일을 적는다 (같은 수면 앞 파일의 크기)
   main = max(counts, key=lambda s: (counts[s], -sizes.index(s)))
   odd = [f"{f.name} {w}x{h}" for f, (w, h) in zip(files, sizes) if (w, h) != main]
   raise UsageError(f"--common 은 크기가 같은 그림만 받는다. 기준 {main[0]}x{main[1]} 과 다른 파일 : {', '.join(odd)}. "
                    "크기별로 폴더를 나눠 따로 돌린다")


def run(args) -> dict:
   pad = int(args.pad)
   if pad < 0:
      raise UsageError(f"--pad 는 0 이상이다 : {pad}")
   square, common = bool(args.square), bool(args.common)

   inputs = list_inputs(args.in_dir)
   outs = plan_outputs(inputs, args.in_dir, args.out_dir)
   arrs = [image.load(f) for f in inputs]

   if common:
      _check_same_size(inputs, arrs)
      shared = trim_common(arrs, pad, square)
      results = [None] * len(arrs) if shared is None else [(cut, shared[1]) for cut in shared[0]]
   else:
      results = [trim_one(arr, pad, square) for arr in arrs]

   rows, warnings = [], []
   for source, target, arr, result in zip(inputs, outs, arrs, results):
      width, height = image.size(arr)
      row = {"file": source.name, "size_before": [width, height]}
      # --common 에서 한 장만 비었으면 그 장도 같은 자리로 자른다(빈 겹). 다 비었을 때만 건너뛴다.
      if result is None:
         warnings.append(warning("trim.empty", f"{source.name} : 빈 그림이라 건너뛰었다", [source.name]))
         rows.append({**row, "out": None, "skipped": True})
         continue
      cut, offset = result
      image.save(target, cut)
      if common and image.bbox(arr) is None:
         warnings.append(warning("trim.empty", f"{source.name} : 빈 그림이다 (--common 이라 같은 자리로 잘라 썼다)", [source.name]))
      rows.append({**row, "out": str(target), "size": list(image.size(cut)), "offset": list(offset), "skipped": False})

   return {
      "version": VERSION,
      "status": "warn" if warnings else "ok",
      "pad": pad,
      "square": square,
      "common": common,
      "images": rows,
      "warnings": warnings,
      "out": str(Path(outs[0]).parent),
   }
