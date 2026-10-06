"""그림 다루기. Pillow 를 부르는 자리는 여기 하나뿐이다.

밖으로는 numpy 배열 (높이, 너비, 4) uint8 RGBA 만 오간다.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
from PIL import Image

from .errors import ArtToolError, UsageError
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
   try:
      Image.fromarray(arr, mode="RGBA").save(tmp, format="PNG")
      os.replace(tmp, file)
   except BaseException:
      tmp.unlink(missing_ok=True)      # 실패하면 tmp 찌꺼기를 남기지 않는다
      raise


GIF_ALPHA_CUT = 128        # 이 알파 밑은 투명, 위는 불투명 (GIF 는 반투명이 없다)
# GIF 한 장 지연은 1/100초 단위 16비트(최대 655350ms). Pillow 가 똑같은 이웃 프레임을 합치며 지연을 더하므로
# 최악(전부 같은 프레임)인 duration × 장 수가 이 값을 넘으면 저장 중에 날 오류로 죽는다 — 쓰기 전에 거절한다.
GIF_MAX_TOTAL_MS = 655350


def check_gif_duration(duration: int, count: int) -> None:
   if duration * count > GIF_MAX_TOTAL_MS:
      raise UsageError(f"--duration × 프레임 수가 GIF 한도를 넘는다 : {duration} × {count} > {GIF_MAX_TOTAL_MS} ms")


def strip(frames: list[RGBA]) -> RGBA:
   """같은 크기 그림들을 여백 없이 가로로 붙인 띠 (엔진이 칸 크기로 자르는 시트)."""
   if not frames:
      raise ArtToolError("띠에 붙일 그림이 없다")
   height, width = frames[0].shape[:2]
   for arr in frames[1:]:
      if arr.shape[:2] != (height, width):
         raise ArtToolError(f"띠는 프레임 크기가 같아야 한다 : {width}x{height} 와 {arr.shape[1]}x{arr.shape[0]}")
   check_pixels(width * len(frames), height, "띠")
   return np.concatenate(frames, axis=1)


def save_gif(frames: list[RGBA], path: str | os.PathLike, duration: int, *, loop: int = 0, scale: int = 1,
             write: bool = True) -> int:
   """프레임들을 공용 팔레트 하나로 GIF 에 쓴다. 0번 = 투명. 반투명 칸 수를 돌려준다.

   write=False 면 거절 검사(색 수 · 크기)만 하고 쓰지 않는다 — dry-run 이 진짜 판과 같은 종료를 내게.

   PIL 기본 변환은 프레임마다 팔레트를 새로 만들고 투명을 잃어서 직접 만든다.
   크기가 다른 프레임은 가장 큰 크기로 왼쪽 위에 맞춰 투명으로 채운다.
   """
   if not frames:
      raise ArtToolError("GIF 에 넣을 프레임이 없다")
   check_gif_duration(int(duration), len(frames))
   width = max(arr.shape[1] for arr in frames)
   height = max(arr.shape[0] for arr in frames)
   check_pixels(width * scale, height * scale, "GIF 프레임")
   soft = 0
   padded = []
   for arr in frames:
      alpha = arr[:, :, 3]
      soft += int(((alpha > 0) & (alpha < 255)).sum())
      canvas = new(width, height)
      canvas[: arr.shape[0], : arr.shape[1]] = arr
      padded.append(scale_up(canvas, scale) if scale > 1 else canvas)
   keys = [(arr[:, :, 0].astype(np.int32) << 16) | (arr[:, :, 1].astype(np.int32) << 8) | arr[:, :, 2] for arr in padded]
   solid = [arr[:, :, 3] >= GIF_ALPHA_CUT for arr in padded]
   colors = np.unique(np.concatenate([k[m] for k, m in zip(keys, solid)]))
   if len(colors) > 255:
      raise ArtToolError(f"GIF 공용 팔레트는 255 색까지다 : {len(colors)} 색 (줄이면 색이 몰래 바뀌어 거절한다)")
   palette = [0, 0, 0]
   for key in colors.tolist():
      palette += [(key >> 16) & 255, (key >> 8) & 255, key & 255]
   palette += [0] * (768 - len(palette))
   if not write:
      return soft
   images = []
   for key, mask in zip(keys, solid):
      index = np.zeros(key.shape, dtype=np.uint8)
      index[mask] = (np.searchsorted(colors, key[mask]) + 1).astype(np.uint8)
      frame = Image.fromarray(index, mode="P")
      frame.putpalette(palette)
      images.append(frame)
   file = Path(path)
   ensure_parent(file)
   tmp = file.with_name(f"{file.name}.{os.getpid()}.tmp")
   try:
      images[0].save(tmp, format="GIF", save_all=True, append_images=images[1:], duration=int(duration), loop=loop,
                     transparency=0, disposal=2, optimize=False)
      os.replace(tmp, file)
   except BaseException:
      tmp.unlink(missing_ok=True)
      raise
   return soft


def gif_frame_count(frames: list[RGBA]) -> int:
   """`save_gif` 로 쓴 GIF 에 실제로 남는 장 수.

   Pillow 는 바로 앞과 똑같은 프레임을 한 장으로 합치고 duration 을 더한다 (끄는 저장 옵션이 없다 — Pillow 12.3 확인).
   그래서 GIF 에 들어가는 모양(투명 컷 뒤의 색)으로 앞 장과 같은지 세어 실제 장 수를 낸다.
   """
   if not frames:
      return 0
   width = max(arr.shape[1] for arr in frames)
   height = max(arr.shape[0] for arr in frames)
   count, prev = 0, None
   for arr in frames:
      canvas = new(width, height)
      canvas[: arr.shape[0], : arr.shape[1]] = arr
      solid = canvas[:, :, 3] >= GIF_ALPHA_CUT
      look = np.where(solid[:, :, None], canvas[:, :, :3], 0)
      look = np.dstack([look, solid])
      if prev is None or not np.array_equal(look, prev):
         count += 1
      prev = look
   return count


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


def paste_over(dst: RGBA, src: RGBA, x: int, y: int) -> None:
   """위에 알파 합성(source-over)으로 얹는다. 아래가 투명이어도 알파까지 섞는다 (`sheet.over_rgba` 와 같은 셈)."""
   h, w = src.shape[0], src.shape[1]
   if x < 0 or y < 0 or x + w > dst.shape[1] or y + h > dst.shape[0]:
      raise ArtToolError(f"붙일 자리가 캔버스를 넘는다 : ({x}, {y})")
   area = dst[y : y + h, x : x + w]
   ta = src[:, :, 3:4].astype(np.float64) / 255.0
   ba = area[:, :, 3:4].astype(np.float64) / 255.0
   oa = ta + ba * (1.0 - ta)
   rgb = src[:, :, :3] * ta + area[:, :, :3] * ba * (1.0 - ta)
   rgb = np.divide(rgb, oa, out=np.zeros_like(rgb), where=oa > 0)
   area[:, :, :3] = np.rint(rgb).astype(np.uint8)
   area[:, :, 3] = np.rint(oa[:, :, 0] * 255.0).astype(np.uint8)


def read_size(path: str | os.PathLike) -> tuple[int, int]:
   """그림 머리만 읽어 (너비, 높이). 화소는 풀지 않는다."""
   file = Path(path)
   try:
      with Image.open(file) as img:
         return int(img.width), int(img.height)
   except (OSError, ValueError) as exc:
      raise ArtToolError(f"그림을 못 읽었다 (잘렸거나 PNG 가 아니다) : {file} - {exc}") from exc


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


def contact_sheet_size(sizes: list[tuple[int, int]], scale: int = 1, cols: int | None = None, gap: int = 2) -> tuple[int, int, int, int, int]:
   """그리기 전에 판 크기만 셈하고 인자 · 상한을 본다. (너비, 높이, 칸 수, 칸 너비, 칸 높이). dry-run 도 이것을 부른다."""
   if not sizes:
      raise ArtToolError("늘어놓을 그림이 없다")
   if gap < 0:
      raise ArtToolError(f"칸 사이는 0 이상이다 : {gap}")
   count = cols or min(len(sizes), 8)
   if count <= 0:
      raise ArtToolError(f"칸 수는 양수여야 한다 : {cols}")
   if scale <= 0:
      raise ArtToolError(f"배율은 양수여야 한다 : {scale}")
   cell_w = max(w for w, _ in sizes) * scale
   cell_h = max(h for _, h in sizes) * scale
   rows = (len(sizes) + count - 1) // count
   width, height = count * cell_w + (count - 1) * gap, rows * cell_h + (rows - 1) * gap
   check_pixels(width, height, "시트")
   return width, height, count, cell_w, cell_h


def contact_sheet(items: list[RGBA], scale: int = 1, cols: int | None = None, gap: int = 2) -> RGBA:
   """그림 여러 장을 격자로 늘어놓은 한 장. 칸 크기는 가장 큰 그림, 작은 그림은 칸 왼쪽 위에 둔다.

   배율을 먼저 걸고, 칸 사이는 gap 픽셀 투명. cols 를 안 주면 한 줄에 8장까지.
   """
   width, height, count, cell_w, cell_h = contact_sheet_size([size(item) for item in items], scale, cols, gap)
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


def quantize_rgb(rgb: np.ndarray, colors: int) -> np.ndarray:
   """(높이, 너비, 3) RGB 를 colors 색 이하로. FASTOCTREE · 디더 없음 (`style ref`)."""
   quant = Image.fromarray(rgb, mode="RGB").quantize(colors=colors, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE)
   return np.array(quant.convert("RGB"), dtype=np.uint8)


def palette_png_bytes(index: np.ndarray, palette: list[int], transparency: int | None = None) -> bytes:
   """색 번호 판(uint8) + 팔레트 [r, g, b, …] → 팔레트 PNG(mode P) 바이트. transparency 는 투명으로 칠 번호."""
   import io

   img = Image.fromarray(index, mode="P")
   img.putpalette(palette)
   save_args: dict = {"format": "PNG", "optimize": True}
   if transparency is not None:
      save_args["transparency"] = transparency
   buffer = io.BytesIO()
   img.save(buffer, **save_args)
   return buffer.getvalue()


def truetype(path: str | os.PathLike, px: int):
   """ttf · otf 글꼴을 읽는다. 못 읽으면 Pillow 의 OSError 를 그대로 올린다 (`ui glyphs`)."""
   from PIL import ImageFont

   return ImageFont.truetype(str(path), px)


def text_mask(font, text: str, width: int, height: int, x: int, y: int) -> np.ndarray:
   """width×height 판 (x, y) 에 글자를 흑백 두 값(0 · 255)으로 그린 (높이, 너비) uint8."""
   from PIL import ImageDraw

   canvas = Image.new("L", (width, height), 0)
   draw = ImageDraw.Draw(canvas)
   draw.fontmode = "1"
   draw.text((x, y), text, font=font, fill=255)
   return np.array(canvas, dtype=np.uint8)


def text_line_mask(font, text: str, x: int, y: int) -> tuple[np.ndarray, int, int]:
   """글자 한 줄을 줄 크기 판에만 그린다. (마스크, 판 왼쪽 위 x, y) — 마스크는 0 · 255 uint8, 빈 줄이면 0×0."""
   from PIL import ImageDraw

   left, top, right, bottom = font.getbbox(text) if text else (0, 0, 0, 0)
   width, height = max(right - left, 0), max(bottom - top, 0)
   canvas = Image.new("L", (width, height), 0)
   if width and height:
      draw = ImageDraw.Draw(canvas)
      draw.fontmode = "1"
      draw.text((-left, -top), text, font=font, fill=255)
   return np.array(canvas, dtype=np.uint8).reshape(height, width), x + left, y + top


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
