"""local 제공자의 그림 손질 : 키우기 · 줄이기 · 마스크 안 색 맞추기 · 밖 덮어쓰기 · 밖 바뀐 칸 세기.

자리를 왜 제공자 안에 두나는 설계 문서 2절(`Docs/Design/2026-10-07-provider-local설계.md`).
"""

from __future__ import annotations

import io
import warnings

import numpy as np
from PIL import Image

from .. import image
from ..errors import ArtToolError, UsageError


LATENT_STEP = 16   # 잠재 공간이 받는 크기 단위. 아니면 모델이 잘라 먹어 결과 크기가 어긋난다
SNAP_CHUNK = 4096  # 색 맞추기를 이만큼씩 끊어 센다 (칸 수 × 팔레트 크기 배열이 커지지 않게)


def work_layout(size: tuple[int, int], work_size: int) -> tuple[int, tuple[int, int]]:
   """(배율, 모델에 줄 크기). 긴 변이 work_size 를 넘지 않는 정수 배율 중 두 변이 다 16 의 배수가 되는 가장 큰 것.

   그런 배율이 없으면 가장 큰 배율로 키우고 오른쪽 · 아래를 16 의 배수까지 덧댄다(결과에서 잘라 낸다).
   """
   width, height = size
   top = max(1, work_size // max(size))
   for factor in range(top, 0, -1):
      if (factor * width) % LATENT_STEP == 0 and (factor * height) % LATENT_STEP == 0:
         return factor, (factor * width, factor * height)
   return top, (_round_up(top * width), _round_up(top * height))


def _round_up(value: int) -> int:
   return -(-value // LATENT_STEP) * LATENT_STEP


def pad_to(arr: np.ndarray, size: tuple[int, int]) -> np.ndarray:
   """오른쪽 · 아래를 0(투명 · False)으로 덧대 size 로 만든다."""
   width, height = size
   out = np.zeros((height, width, *arr.shape[2:]), dtype=arr.dtype)
   out[: arr.shape[0], : arr.shape[1]] = arr
   return out


def upscale_nearest(arr: image.RGBA, factor: int) -> image.RGBA:
   return np.repeat(np.repeat(arr, factor, axis=0), factor, axis=1)


def downscale_box(arr: image.RGBA, size: tuple[int, int]) -> image.RGBA:
   if image.size(arr) == tuple(size):
      return arr.copy()
   picture = Image.fromarray(arr, mode="RGBA").resize(tuple(size), Image.Resampling.BOX)
   return np.array(picture, dtype=np.uint8)


def to_png(arr: image.RGBA) -> bytes:
   buffer = io.BytesIO()
   Image.fromarray(arr, mode="RGBA").save(buffer, format="PNG")
   return buffer.getvalue()


def from_png(data: bytes, max_side: int) -> image.RGBA:
   """받은 PNG 를 푼다. 풀기 전에 크기를 보고 max_side 를 넘거나 압축 폭탄이면 거절한다."""
   try:
      with warnings.catch_warnings():
         warnings.simplefilter("error", Image.DecompressionBombWarning)
         with Image.open(io.BytesIO(data)) as picture:
            if max(picture.size) > max_side:
               raise ArtToolError(f"ComfyUI 가 준 그림이 너무 크다 : {picture.size[0]}x{picture.size[1]} (상한 {max_side})")
            return np.array(picture.convert("RGBA"), dtype=np.uint8)
   except (Image.DecompressionBombError, Image.DecompressionBombWarning):
      raise ArtToolError("ComfyUI 가 준 그림이 압축 폭탄이다 (풀면 너무 크다)") from None
   except (OSError, ValueError) as exc:
      raise ArtToolError(f"ComfyUI 가 준 그림을 못 읽었다 : {exc}") from None


def mask_area(mask: image.RGBA) -> np.ndarray:
   """흰 칸(밝고 불투명) = 고칠 곳. bool 배열."""
   bright = mask[:, :, :3].astype(np.int32).mean(axis=2) >= 128
   return bright & (mask[:, :, 3] >= 128)


def mask_picture(area: np.ndarray) -> image.RGBA:
   """모델에 올릴 마스크 그림. 고칠 곳은 흰색, 나머지는 검정, 모두 불투명."""
   out = np.zeros((*area.shape, 4), dtype=np.uint8)
   out[:, :, 3] = 255
   out[area, :3] = 255
   return out


def parse_colors(items, what: str) -> list[tuple[int, int, int]]:
   """'#rrggbb' 나 [r, g, b] 목록을 RGB 튜플 목록으로."""
   if not isinstance(items, list):
      raise UsageError(f"{what} 는 색 목록이어야 한다 ('#rrggbb' 나 [r, g, b])")
   colors = []
   for item in items:
      colors.append(_parse_color(item, what))
   return colors


def _parse_color(item, what: str) -> tuple[int, int, int]:
   if isinstance(item, str) and len(item) == 7 and item.startswith("#"):
      try:
         return (int(item[1:3], 16), int(item[3:5], 16), int(item[5:7], 16))
      except ValueError:
         pass
   if isinstance(item, list) and len(item) == 3 and all(isinstance(v, int) and 0 <= v <= 255 for v in item):
      return (item[0], item[1], item[2])
   raise UsageError(f"{what} 의 색을 못 읽었다 : {item!r}")


def snap_colors(arr: image.RGBA, area: np.ndarray, colors: list[tuple[int, int, int]]) -> image.RGBA:
   """area 안 칸만 colors 중 가장 가까운 색(RGB 거리)으로 바꾸고 불투명으로 둔다. 밖은 그대로."""
   if not colors:
      raise UsageError("마스크 안 색을 맞출 색이 없다 (원본이 다 투명하면 extra_colors 를 준다)")
   out = arr.copy()
   table = np.array(sorted(set(colors)), dtype=np.int32)
   inside = out[area][:, :3].astype(np.int32)
   if len(inside) == 0:
      return out
   picked = np.empty_like(inside)
   for start in range(0, len(inside), SNAP_CHUNK):
      chunk = inside[start:start + SNAP_CHUNK]
      distance = ((chunk[:, None, :] - table[None, :, :]) ** 2).sum(axis=2)
      picked[start:start + SNAP_CHUNK] = table[distance.argmin(axis=1)]
   out[area, :3] = picked.astype(np.uint8)
   out[area, 3] = 255
   return out


def composite_outside(result: image.RGBA, source: image.RGBA, area: np.ndarray) -> image.RGBA:
   """마스크 밖은 원본 그대로 덮어쓴다. inpaint 계약 「밖은 안 바뀐다」를 요청 크기에서 맨 끝에 지킨다."""
   out = result.copy()
   out[~area] = source[~area]
   return out


def count_outside_changed(result: image.RGBA, source: image.RGBA, area: np.ndarray) -> int:
   changed = (result != source).any(axis=2)
   return int((changed & ~area).sum())
