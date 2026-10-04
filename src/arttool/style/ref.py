"""`style ref` — PixelLab 에 넘길 화풍 그림 준비 (피드백 후속 설계 3-1).

`create_image_pro_flash` 는 화풍 그림이 캔버스보다 크면 거절하고, base64 가 길면 잘려 못 읽는다.
그래서 ① 캔버스 크기로 자르고 ② 색을 줄이고 ③ 알파를 0/255 로 ④ 팔레트 PNG 로 ⑤ base64 를 파일로 쓴다.

- **키우기 · 줄이기는 안 한다** — 도트 굵기가 깨진다. 캔버스보다 작으면 그대로 둔다.
- base64 는 stdout · 보고에 안 싣는다 (문맥을 먹는다). `--b64` 파일로만 쓴다.
"""

from __future__ import annotations

import base64
import os
import re
from pathlib import Path

import numpy as np

from .. import image
from ..checks import warning
from ..errors import ArtToolError, UsageError
from ..paths import guard_overwrite, jailed_output, write_text

VERSION = 1
DEFAULT_COLORS = 32
DEFAULT_MAX_KB = 12.0    # 피드백 실측 : 16~40색 3~9KB 통과, 57KB 실패
ALPHA_CUT = 128          # 이 값 이상이면 불투명, 아래면 투명

_CANVAS = re.compile(r"^(\d+)x(\d+)$")


def parse_canvas(text: str) -> tuple[int, int]:
   match = _CANVAS.match(str(text).strip().lower())
   if match is None:
      raise UsageError(f"--canvas 는 WxH 꼴이다 (예 128x128) : {text}")
   width, height = int(match.group(1)), int(match.group(2))
   if width <= 0 or height <= 0:
      raise UsageError(f"--canvas 는 양수여야 한다 : {text}")
   return width, height


def parse_crop(text: str, width: int, height: int) -> tuple[int, int, int, int]:
   parts = str(text).split(",")
   try:
      x, y, w, h = (int(p) for p in parts)
   except ValueError as exc:
      raise UsageError(f"--crop 은 X,Y,W,H 정수 넷이다 : {text}") from exc
   if w <= 0 or h <= 0 or x < 0 or y < 0 or x + w > width or y + h > height:
      raise UsageError(f"--crop {text} 이 그림({width}x{height}) 밖이다")
   return x, y, w, h


def center_crop_box(arr: image.RGBA, canvas: tuple[int, int]) -> tuple[int, int, int, int] | None:
   """그림이 캔버스보다 크면 불투명 칸 bbox 의 가운데를 기준으로 캔버스 크기 칸. 안 크면 None."""
   width, height = image.size(arr)
   cw, ch = canvas
   if width <= cw and height <= ch:
      return None
   x0, y0, x1, y1 = image.bbox(arr)
   w, h = min(width, cw), min(height, ch)
   left = min(max((x0 + x1) // 2 - w // 2, 0), width - w)
   top = min(max((y0 + y1) // 2 - h // 2, 0), height - h)
   return left, top, w, h


def reduce_colors(arr: image.RGBA, colors: int) -> image.RGBA:
   """불투명 칸 색을 colors 개 이하로. FASTOCTREE · 디더 없음. 투명 칸은 그대로."""
   opaque = arr[:, :, 3] > 0
   rgb = arr[:, :, :3].copy()
   # 투명 칸 RGB 찌꺼기가 색 고르기에 끼지 않게 그림에 있는 색 하나로 덮는다
   rgb[~opaque] = rgb[opaque][0]
   out = arr.copy()
   out[:, :, :3] = image.quantize_rgb(rgb, colors)
   out[~opaque, :3] = 0
   return out


def palette_png_bytes(arr: image.RGBA) -> bytes:
   """알파 0/255 그림 → 팔레트 PNG(mode P + 투명 색 하나) 바이트. 파일 쓰기는 `image.palette_png_bytes` 가 한다."""
   opaque = arr[:, :, 3] > 0
   keys = (arr[:, :, 0].astype(np.uint32) << 16) | (arr[:, :, 1].astype(np.uint32) << 8) | arr[:, :, 2]
   colors, inverse = np.unique(keys[opaque], return_inverse=True)
   index = np.zeros(opaque.shape, dtype=np.uint8)
   index[opaque] = inverse.reshape(-1).astype(np.uint8)
   palette = []
   for key in colors:
      palette += [int(key) >> 16, (int(key) >> 8) & 0xFF, int(key) & 0xFF]
   clear = None
   if not opaque.all():
      clear = len(colors)
      index[~opaque] = clear
      palette += [0, 0, 0]
   return image.palette_png_bytes(index, palette, clear)


def _write_bytes(path: Path, data: bytes) -> None:
   """tmp 에 쓰고 이름을 바꾼다 (`image.save` 와 같은 길)."""
   path.parent.mkdir(parents=True, exist_ok=True)
   tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
   tmp.write_bytes(data)
   os.replace(tmp, path)


def _check_args(args) -> tuple[tuple[int, int], int, float]:
   canvas = parse_canvas(args.canvas)
   colors = int(getattr(args, "colors", DEFAULT_COLORS))
   if not 2 <= colors <= 256:
      raise UsageError(f"--colors 는 2~256 이다 : {colors}")
   max_kb = float(getattr(args, "max_kb", DEFAULT_MAX_KB))
   if max_kb <= 0:
      raise UsageError(f"--max-kb 는 양수여야 한다 : {max_kb}")
   return canvas, colors, max_kb


def run(args) -> dict:
   canvas, colors, max_kb = _check_args(args)
   out = jailed_output(args.out_file)
   b64_arg = getattr(args, "b64", None)
   b64_path = jailed_output(b64_arg) if b64_arg else None
   guard_overwrite([out, b64_path], [args.in_file])
   guard_overwrite([b64_path], [out], "--b64")

   arr = image.load(args.in_file)
   warnings = []
   crop = None
   crop_arg = getattr(args, "crop", None)
   if crop_arg:
      crop = parse_crop(crop_arg, *image.size(arr))
      arr = image.crop(arr, *crop)
   if image.bbox(arr) is None:
      raise ArtToolError(f"불투명 칸이 없다 — 화풍 그림으로 쓸 것이 없다 : {args.in_file}")

   # 손으로 잘라도 캔버스보다 크면 그 안에서 한 번 더 가운데로 자른다
   auto = center_crop_box(arr, canvas)
   if auto is not None:
      arr = image.crop(arr, *auto)
      base_x, base_y = (crop[0], crop[1]) if crop else (0, 0)
      crop = (base_x + auto[0], base_y + auto[1], auto[2], auto[3])
      warnings.append(warning("ref.cropped", f"캔버스 {canvas[0]}x{canvas[1]} 보다 커서 불투명 칸 가운데로 잘랐다 : {list(crop)}", list(crop)))

   if image.has_soft_alpha(arr):
      warnings.append(warning("ref.soft_alpha", f"반투명 칸을 알파 {ALPHA_CUT} 문턱으로 0/255 로 바꿨다"))
   arr = arr.copy()
   arr[:, :, 3] = np.where(arr[:, :, 3] >= ALPHA_CUT, 255, 0).astype(np.uint8)
   arr[arr[:, :, 3] == 0] = 0
   if image.bbox(arr) is None:
      raise ArtToolError(f"알파 {ALPHA_CUT} 이상인 칸이 없다 — 화풍 그림으로 쓸 것이 없다 : {args.in_file}")

   colors_before = image.count_colors(arr)
   if colors_before > colors:
      # 투명 색 하나 자리를 남긴다 (팔레트는 256 칸까지)
      room = colors - 1 if colors == 256 and not (arr[:, :, 3] > 0).all() else colors
      arr = reduce_colors(arr, room)
   colors_after = image.count_colors(arr)

   png = palette_png_bytes(arr)
   encoded = base64.b64encode(png).decode("ascii")
   _write_bytes(out, png)
   if b64_path is not None:
      write_text(b64_path, encoded)

   if len(encoded) > max_kb * 1024:
      warnings.append(warning("ref.b64_large", f"base64 가 {len(encoded)} 바이트로 {max_kb:g}KB 를 넘는다 — 색을 더 줄이거나 더 잘라라",
                              [len(encoded)]))
   return {
      "version": VERSION,
      "status": "warn" if any(w["rule"] == "ref.b64_large" for w in warnings) else "ok",
      "out": str(out),
      "b64": str(b64_path) if b64_path else None,
      "canvas": list(canvas),
      "size": list(image.size(arr)),
      "crop": list(crop) if crop else None,
      "colors_before": colors_before,
      "colors_after": colors_after,
      "png_bytes": len(png),
      "b64_bytes": len(encoded),
      "warnings": warnings,
   }
