"""그림 다루기. Pillow 를 부르는 자리는 여기 하나뿐이다.

밖으로는 numpy 배열 (높이, 너비, 4) uint8 RGBA 만 오간다.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
from PIL import Image

from .errors import ArtToolError
from .paths import ensure_parent

RGBA = np.ndarray


def new(width: int, height: int, fill: tuple[int, int, int, int] = (0, 0, 0, 0)) -> RGBA:
   arr = np.zeros((height, width, 4), dtype=np.uint8)
   arr[:, :] = fill
   return arr


def load(path: str | os.PathLike) -> RGBA:
   file = Path(path)
   if not file.is_file():
      raise ArtToolError(f"그림 파일이 없다 : {file}")
   try:
      with Image.open(file) as img:
         return np.array(img.convert("RGBA"), dtype=np.uint8)
   except (OSError, ValueError) as exc:
      raise ArtToolError(f"그림을 못 읽었다 (잘렸거나 PNG 가 아니다) : {file} - {exc}") from exc


def save(path: str | os.PathLike, arr: RGBA) -> None:
   """tmp 에 쓰고 이름을 바꾼다. 반쯤 쓰인 파일을 남기지 않는다."""
   file = Path(path)
   ensure_parent(file)
   tmp = file.with_name(f"{file.name}.{os.getpid()}.tmp")
   Image.fromarray(arr, mode="RGBA").save(tmp, format="PNG")
   os.replace(tmp, file)


def size(arr: RGBA) -> tuple[int, int]:
   return int(arr.shape[1]), int(arr.shape[0])


def crop(arr: RGBA, x: int, y: int, width: int, height: int) -> RGBA:
   return arr[y : y + height, x : x + width].copy()


def paste(dst: RGBA, src: RGBA, x: int, y: int) -> None:
   """위에 얹는다. 알파가 0 인 칸만 아래를 남기고, 나머지는 섞지 않고 덮어쓴다."""
   h, w = src.shape[0], src.shape[1]
   if x < 0 or y < 0 or x + w > dst.shape[1] or y + h > dst.shape[0]:
      raise ArtToolError(f"붙일 자리가 캔버스를 넘는다 : ({x}, {y})")

   area = dst[y : y + h, x : x + w]
   mask = src[:, :, 3] > 0
   area[mask] = src[mask]


def flip_x(arr: RGBA) -> RGBA:
   return arr[:, ::-1].copy()


def flip_y(arr: RGBA) -> RGBA:
   return arr[::-1, :].copy()


def has_soft_alpha(arr: RGBA) -> bool:
   """0 도 255 도 아닌 알파가 있으면 참."""
   alpha = arr[:, :, 3]
   return bool(np.any((alpha != 0) & (alpha != 255)))


def opaque_colors(arr: RGBA) -> set[tuple[int, int, int]]:
   mask = arr[:, :, 3] > 0
   if not np.any(mask):
      return set()
   rgb = arr[:, :, :3][mask]
   uniq = np.unique(rgb.reshape(-1, 3), axis=0)
   return {tuple(int(v) for v in row) for row in uniq}


def count_colors(arr: RGBA) -> int:
   return len(opaque_colors(arr))


def bbox(arr: RGBA) -> tuple[int, int, int, int] | None:
   """알파가 있는 칸의 (x0, y0, x1, y1). 끝은 포함하지 않는다. 다 비었으면 None."""
   mask = arr[:, :, 3] > 0
   rows = np.any(mask, axis=1)
   cols = np.any(mask, axis=0)
   if not rows.any():
      return None
   y0 = int(np.argmax(rows))
   y1 = int(len(rows) - np.argmax(rows[::-1]))
   x0 = int(np.argmax(cols))
   x1 = int(len(cols) - np.argmax(cols[::-1]))
   return x0, y0, x1, y1


def find_color(arr: RGBA, rgb: tuple[int, int, int]) -> list[tuple[int, int]]:
   """그 색인 칸의 (x, y) 목록. 알파가 0 인 칸은 빼고 센다."""
   mask = (arr[:, :, 0] == rgb[0]) & (arr[:, :, 1] == rgb[1]) & (arr[:, :, 2] == rgb[2])
   mask &= arr[:, :, 3] > 0
   ys, xs = np.nonzero(mask)
   return [(int(x), int(y)) for x, y in zip(xs, ys)]


def split_grid(arr: RGBA, frame_w: int, frame_h: int) -> list[list[RGBA]]:
   """시트를 격자로 자른다. 바깥 목록이 줄, 안쪽 목록이 칸."""
   w, h = size(arr)
   if w % frame_w != 0 or h % frame_h != 0:
      raise ArtToolError(f"시트 {w}x{h} 가 프레임 {frame_w}x{frame_h} 로 안 나뉜다")

   rows = []
   for ry in range(h // frame_h):
      row = [crop(arr, rx * frame_w, ry * frame_h, frame_w, frame_h) for rx in range(w // frame_w)]
      rows.append(row)
   return rows


def pack_grid(rows: list[list[RGBA]], frame_w: int, frame_h: int) -> RGBA:
   """격자로 붙인다. 줄마다 칸 수가 달라도 된다."""
   cols = max((len(row) for row in rows), default=0)
   sheet = new(frame_w * cols, frame_h * len(rows))
   for ry, row in enumerate(rows):
      for rx, frame in enumerate(row):
         paste(sheet, frame, rx * frame_w, ry * frame_h)
   return sheet


def replace_colors(arr: RGBA, table: dict[tuple[int, int, int], tuple[int, int, int]]) -> RGBA:
   out = arr.copy()
   for src, dst in table.items():
      mask = (out[:, :, 0] == src[0]) & (out[:, :, 1] == src[1]) & (out[:, :, 2] == src[2])
      mask &= out[:, :, 3] > 0
      out[mask, 0] = dst[0]
      out[mask, 1] = dst[1]
      out[mask, 2] = dst[2]
   return out
