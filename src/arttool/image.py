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

# 만들 그림 한 장의 픽셀 상한. 잘못 준 배율·배치표 하나로 메모리가 터지지 않게 그리기 전에 본다.
MAX_PIXELS = 8192 * 8192


def check_pixels(width: int, height: int, what: str) -> None:
   if width * height > MAX_PIXELS:
      raise ArtToolError(f"{what}가 너무 크다 : {width}x{height} (한도 {MAX_PIXELS} 픽셀)")


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


BITMAP_MIN_PIXELS = 1 << 16   # 칸이 이보다 많으면 색 세기를 2²⁴ 표시판으로 한다 (작은 그림은 표시판 만드는 값이 더 든다)


def _opaque_keys_raw(arr: RGBA) -> np.ndarray:
   """알파 > 0 칸의 RGB 를 수 하나(R<<16 | G<<8 | B)로 엮은 값들 (겹침 있음)."""
   mask = arr[:, :, 3] > 0
   rgb = arr[:, :, :3][mask].astype(np.uint32)
   return (rgb[:, 0] << 16) | (rgb[:, 1] << 8) | rgb[:, 2]


def opaque_colors(arr: RGBA) -> set[tuple[int, int, int]]:
   # np.unique(axis=0) 은 줄 비교라 큰 그림에서 몇 초 걸린다. 수 하나로 엮어 세면 수십 배 빠르다
   return {(int(k) >> 16, (int(k) >> 8) & 0xFF, int(k) & 0xFF) for k in np.unique(_opaque_keys_raw(arr))}


def count_colors(arr: RGBA) -> int:
   """불투명 색 가짓수 (알파 > 0 칸의 RGB). `checks.pixels.color_count` 도 이것을 부른다.

   큰 그림은 2²⁴ 칸 표시판(16MB)에 찍어 센다 — 정렬이 없어 945×2048 한 장이 0.1초 안팎이다.
   """
   keys = _opaque_keys_raw(arr)
   if keys.size < BITMAP_MIN_PIXELS:
      return int(np.unique(keys).size)
   seen = np.zeros(1 << 24, dtype=bool)
   seen[keys] = True
   return int(np.count_nonzero(seen))


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
   """알파가 있는 칸의 색만 바꾼다. 자리는 원본에서 찾아 A→B, B→C 가 A→C 로 번지지 않는다."""
   out = arr.copy()
   for src, dst in table.items():
      mask = (arr[:, :, 0] == src[0]) & (arr[:, :, 1] == src[1]) & (arr[:, :, 2] == src[2])
      mask &= arr[:, :, 3] > 0
      out[mask, 0] = dst[0]
      out[mask, 1] = dst[1]
      out[mask, 2] = dst[2]
   return out


def scale_up(arr: RGBA, factor: int) -> RGBA:
   """정수 배로 키운다. 칸을 그대로 늘리므로 NEAREST 와 같다."""
   if factor <= 0:
      raise ArtToolError(f"배율은 양수여야 한다 : {factor}")
   return np.repeat(np.repeat(arr, factor, axis=0), factor, axis=1)


def contact_sheet(items: list[RGBA], scale: int = 1, cols: int | None = None, gap: int = 2) -> RGBA:
   """그림 여러 장을 격자로 늘어놓은 한 장. 칸 크기는 가장 큰 그림, 작은 그림은 칸 왼쪽 위에 둔다.

   배율을 먼저 걸고, 칸 사이는 gap 픽셀 투명. cols 를 안 주면 한 줄에 8장까지.
   """
   if not items:
      raise ArtToolError("늘어놓을 그림이 없다")
   if gap < 0:
      raise ArtToolError(f"칸 사이는 0 이상이다 : {gap}")
   count = cols or min(len(items), 8)
   if count <= 0:
      raise ArtToolError(f"칸 수는 양수여야 한다 : {cols}")
   if scale <= 0:
      raise ArtToolError(f"배율은 양수여야 한다 : {scale}")
   cell_w = max(item.shape[1] for item in items) * scale
   cell_h = max(item.shape[0] for item in items) * scale
   rows = (len(items) + count - 1) // count
   width, height = count * cell_w + (count - 1) * gap, rows * cell_h + (rows - 1) * gap
   check_pixels(width, height, "시트")
   big = [scale_up(item, scale) for item in items]
   sheet = new(width, height)
   for index, item in enumerate(big):
      col, row = index % count, index // count
      paste(sheet, item, col * (cell_w + gap), row * (cell_h + gap))
   return sheet


# ── 비교판(sheet)이 쓰는 것 : 흐림 · 밝기 · 밝기 단계 · 딱지 글자 ──

# 딱지 글꼴. 패키지 안에 넣어 설치해도 따라간다 (설계 5-1). 라이선스 글은 같은 폴더 OFL-Pretendard.txt.
LABEL_FONT = Path(__file__).parent / "assets" / "fonts" / "Pretendard-Medium.otf"
LABEL_PX = 13
_FONT_CACHE: dict[int, object] = {}  # 글자 크기 → 읽은 글꼴


def luma(arr: RGBA) -> np.ndarray:
   """칸마다 밝기 (높이, 너비) float. 0.299R + 0.587G + 0.114B, 0~255."""
   rgb = arr[:, :, :3].astype(np.float64)
   return rgb[:, :, 0] * 0.299 + rgb[:, :, 1] * 0.587 + rgb[:, :, 2] * 0.114


def quantize_luma(arr: RGBA, levels: int = 4) -> RGBA:
   """불투명 칸을 밝기 순으로 칸 수가 고르게 levels 덩이로 나눠 회색 levels 개로 칠한다.

   밝기 값마다 「칸 수로 센 순위의 가운데」(0~1)를 구해 levels 칸으로 자른다.
   분위수 경계를 그대로 쓰면 한 밝기가 칸을 많이 차지할 때 이웃 밝기와 한 덩이로 뭉개지므로 이렇게 한다.
   같은 밝기는 늘 같은 덩이로 가므로 색 수는 levels 이하다. 투명 칸 · 알파 값은 그대로 둔다.
   """
   if levels < 2:
      raise ArtToolError(f"밝기 단계는 2 이상이다 : {levels}")
   out = arr.copy()
   mask = arr[:, :, 3] > 0
   if not np.any(mask):
      return out
   values = np.round(luma(arr)[mask], 6)
   _, inverse, counts = np.unique(values, return_inverse=True, return_counts=True)
   centers = (np.cumsum(counts) - counts / 2.0) / values.size
   level_of = np.minimum(levels - 1, (centers * levels).astype(np.int64))
   grays = np.linspace(24, 232, levels).round().astype(np.uint8)
   shade = grays[level_of[inverse.reshape(-1)]]
   out[mask, 0] = shade
   out[mask, 1] = shade
   out[mask, 2] = shade
   return out


def blur(arr: RGBA, radius: float) -> RGBA:
   """가우스 흐림. 투명 칸까지 같이 흐리므로 보통은 배경 위에 얹은 뒤 부른다."""
   from PIL import ImageFilter

   if radius <= 0:
      return arr.copy()
   img = Image.fromarray(arr, mode="RGBA").filter(ImageFilter.GaussianBlur(radius))
   return np.array(img, dtype=np.uint8)


def has_label_font() -> bool:
   return LABEL_FONT.is_file()


def _label_font(px: int):
   from PIL import ImageFont

   cached = _FONT_CACHE.get(px)
   if cached is None:
      if not has_label_font():
         raise ArtToolError(f"딱지 글꼴이 없다 (설치가 깨졌다) : {LABEL_FONT}")
      cached = ImageFont.truetype(str(LABEL_FONT), px)
      _FONT_CACHE[px] = cached
   return cached


def label_width(text: str, px: int = LABEL_PX) -> int:
   """딱지 글자를 찍었을 때 가로 픽셀 수."""
   return int(np.ceil(_label_font(px).getlength(text)))


def draw_label(arr: RGBA, text: str, x: int, y: int, px: int = LABEL_PX, color: tuple[int, int, int, int] = (255, 255, 255, 255)) -> None:
   """arr 위 (x, y) 에 글자를 찍는다 (제자리). 흑백 두 값으로 찍어 반투명 칸이 안 생긴다.

   arr 밖으로 나가는 글자는 잘린다. 띠 안에만 찍고 싶으면 띠 부분 배열(view)을 넘긴다.
   """
   from PIL import ImageDraw

   font = _label_font(px)
   img = Image.fromarray(arr, mode="RGBA")
   draw = ImageDraw.Draw(img)
   draw.fontmode = "1"
   draw.text((x, y), text, font=font, fill=tuple(color))
   arr[:, :] = np.array(img, dtype=np.uint8)
