"""`tile offset` — 반 칸 밀기 + 십자 가림판 (피드백 후속 설계 3-4).

바탕이 꽉 찬 타일은 「seamless」 글로는 네 변이 안 이어진다. 그림을 (W//2, H//2) 만큼 감아 밀면 원래 네 변이
가운데 십자로 모이고, 그 십자만 PixelLab inpaint 로 다시 그리면 이어 붙는 타일이 된다 (다시 밀어 되돌리지 않는다).

가림판은 불투명 검정 바탕 + 흰 십자(흰 = 다시 그릴 자리). 띠는 이음 줄을 가운데에 두고 `--band` 칸 폭.
"""

from __future__ import annotations

import numpy as np

from .. import image
from ..checks import warning
from ..errors import UsageError
from ..paths import guard_overwrite, jailed_output
from .seam import DEFAULT_K, check_pair

VERSION = 1
DEFAULT_BAND = 16
MASK_BG = (0, 0, 0, 255)
MASK_FG = (255, 255, 255, 255)


def shift_half(arr: image.RGBA) -> tuple[image.RGBA, tuple[int, int]]:
   """(W//2, H//2) 만큼 감아 민 그림과 민 값 (x, y)."""
   width, height = image.size(arr)
   sx, sy = width // 2, height // 2
   return np.roll(arr, (sy, sx), axis=(0, 1)), (sx, sy)


def cross_mask(width: int, height: int, shift: tuple[int, int], band: int) -> image.RGBA:
   """이음 줄(민 값 자리)을 가운데에 둔 band 폭 십자."""
   sx, sy = shift
   half = band // 2
   mask = image.new(width, height, MASK_BG)
   mask[:, sx - half : sx + half] = MASK_FG
   mask[sy - half : sy + half, :] = MASK_FG
   return mask


def _check_band(band: int, width: int, height: int) -> None:
   if band < 2 or band % 2:
      raise UsageError(f"--band 는 2 이상의 짝수다 : {band}")
   short = min(width, height)
   if band * 2 >= short:
      raise UsageError(f"--band {band} 가 짧은 변 {short} 의 절반 이상이다 — 그림이 거의 다 가려진다")


def run(args) -> dict:
   band = int(getattr(args, "band", DEFAULT_BAND))
   out = jailed_output(args.out_file)
   mask_path = jailed_output(args.mask)
   guard_overwrite([mask_path], [out], "--mask")
   guard_overwrite([out, mask_path], [args.in_file])

   arr = image.load(args.in_file)
   width, height = image.size(arr)
   _check_band(band, width, height)

   warnings = []
   if bool((arr[:, :, 3] < 255).any()):
      warnings.append(warning("offset.has_transparent", "투명 · 반투명 칸이 있다 — 바탕 타일은 꽉 차야 한다"))
   seam_before = check_pair(arr, arr, DEFAULT_K)
   shifted, shift = shift_half(arr)
   image.save(out, shifted)
   image.save(mask_path, cross_mask(width, height, shift, band))
   return {
      "version": VERSION,
      "status": "warn" if warnings else "ok",
      "out": str(out),
      "mask": str(mask_path),
      "size": [width, height],
      "shift": list(shift),
      "band": band,
      "seam_before": seam_before,
      "warnings": warnings,
   }
