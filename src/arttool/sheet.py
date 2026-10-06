"""비교판 `sheet` — 그림 하나 = 한 줄, 판 하나 = 한 칸 (설계 5절).

판 다섯 :
- zoom       정수 배 nearest 확대
- silhouette 불투명 칸을 한 색으로
- colors4    밝기 4분위로 회색 4색
- blur       확대한 판을 배경 위에 얹고 가우스 흐림 (반지름 = 배율)
- tile       2×2 또는 4×4 로 이어 붙인 판

판정은 없다 — status 는 늘 ok. 보고에 장마다 크기 · 색 수 · 외톨이 칸 수 · 외곽선 몫을 적는다.
줄 그리기(`layout_rows`)는 순수 함수라 `layers view --each` 도 같이 쓴다.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from . import image
from .checks import outline as outline_check
from .checks import pixels as pixel_check
from .edit import dry_run_fields, is_dry_run
from .errors import ArtToolError, UsageError
from .palette import parse_hex
from .paths import guard_overwrite, is_plain_file, jailed_output

KINDS = ("zoom", "silhouette", "colors4", "blur", "tile")
KIND_TITLES = {"zoom": "확대", "silhouette": "실루엣", "colors4": "4색", "blur": "흐림", "tile": "타일"}

AUTO_TARGET = 256          # --scale auto : 가장 큰 그림이 이 픽셀 안팎이 되는 정수 배
AUTO_MAX = 8
SCALE_MAX = 64             # --scale 정수의 위 한도. 넘으면 판을 그리기도 전에 메모리를 다 쓴다 (R1-M3)
SILHOUETTE = (24, 24, 32, 255)
CHECKER = ((236, 238, 244, 255), (206, 210, 222, 255))  # 회색 판(colors4)과 안 헷갈리게 푸른 기를 조금 섞었다
CHECKER_CELL = 8           # 바둑판 한 칸, 출력 픽셀
SHEET_BACK = (44, 44, 52, 255)
LABEL_COLOR = (240, 240, 240, 255)
GAP = 4
ELLIPSIS = "…"


# ── 인자 읽기 ──

def parse_kinds(text: str) -> list[str]:
   kinds: list[str] = []
   for part in str(text).split(","):
      name = part.strip()
      if not name:
         continue
      if name not in KINDS:
         raise UsageError(f"모르는 판 : {name} (쓸 수 있는 것 : {', '.join(KINDS)})")
      if name not in kinds:
         kinds.append(name)
   if not kinds:
      raise UsageError("--kinds 가 비었다")
   return kinds


def parse_bg(text: str) -> tuple[int, int, int, int] | None:
   """checker 면 None, #RRGGBB 면 그 색."""
   if text == "checker":
      return None
   try:
      return (*parse_hex(text), 255)
   except ArtToolError as exc:
      raise UsageError(f"--bg 는 checker 또는 #RRGGBB 다 : {text}") from exc


def pick_scale(text: str, items: list[np.ndarray]) -> int:
   if str(text) == "auto":
      biggest = max(max(arr.shape[0], arr.shape[1]) for arr in items)
      return max(1, min(AUTO_MAX, AUTO_TARGET // max(1, biggest)))
   try:
      value = int(text)
   except ValueError as exc:
      raise UsageError(f"--scale 은 auto 또는 양의 정수다 : {text}") from exc
   if value <= 0:
      raise UsageError(f"--scale 은 양의 정수다 : {text}")
   if value > SCALE_MAX:
      raise UsageError(f"--scale 은 {SCALE_MAX} 이하다 : {text}")
   return value


def collect_inputs(paths: list[str]) -> tuple[list[Path], list[dict]]:
   """파일은 그대로, 폴더는 그 안 PNG 를 이름 순으로 (하위 폴더는 안 본다)."""
   files: list[Path] = []
   warnings: list[dict] = []
   for text in paths:
      path = Path(text)
      if path.is_dir():
         found = sorted(p for p in path.iterdir() if p.suffix.lower() == ".png" and is_plain_file(p))
         if not found:
            warnings.append(_warn("empty_folder", f"PNG 가 없는 폴더 : {path}", [str(path)]))
         files.extend(found)
      elif path.is_file():
         files.append(path)
      else:
         raise ArtToolError(f"입력이 없다 : {path}")
   if not files:
      raise ArtToolError("비교판에 놓을 그림이 없다")
   return files, warnings


def _warn(rule: str, detail: str, items: list) -> dict:
   return {"rule": rule, "ok": False, "detail": detail, "items": items}


# ── 판 만들기 ──

def backdrop(width: int, height: int, bg: tuple[int, int, int, int] | None) -> np.ndarray:
   """칸 배경. bg 가 None 이면 바둑판."""
   if bg is not None:
      return image.new(width, height, bg)
   ys, xs = np.indices((height, width))
   odd = ((ys // CHECKER_CELL) + (xs // CHECKER_CELL)) % 2 == 1
   out = image.new(width, height, CHECKER[0])
   out[odd] = CHECKER[1]
   return out


def over(top: np.ndarray, bottom: np.ndarray) -> np.ndarray:
   """top 을 bottom 위에 알파로 섞어 얹는다. bottom 은 불투명이라고 본다."""
   alpha = top[:, :, 3:4].astype(np.float64) / 255.0
   rgb = top[:, :, :3] * alpha + bottom[:, :, :3] * (1.0 - alpha)
   out = bottom.copy()
   out[:, :, :3] = np.rint(rgb).astype(np.uint8)
   out[:, :, 3] = 255
   return out


def kind_layer(arr: np.ndarray, kind: str, scale: int, tile: int = 2) -> np.ndarray:
   """배경을 깔기 전의 판 (blur 는 확대 판과 같다 — 흐림은 배경 위에서 한다)."""
   if kind in ("zoom", "blur"):
      return image.scale_up(arr, scale)
   if kind == "silhouette":
      out = image.new(arr.shape[1], arr.shape[0])
      out[arr[:, :, 3] > 0] = SILHOUETTE
      return image.scale_up(out, scale)
   if kind == "colors4":
      return image.scale_up(image.quantize_luma(arr, 4), scale)
   if kind == "tile":
      return image.scale_up(np.tile(arr, (tile, tile, 1)), scale)
   raise UsageError(f"모르는 판 : {kind}")


def render_kind(arr: np.ndarray, kind: str, scale: int, tile: int = 2, bg: tuple[int, int, int, int] | None = None) -> np.ndarray:
   """칸 하나 — 판을 배경 위에 얹은 불투명 그림."""
   layer = kind_layer(arr, kind, scale, tile)
   out = over(layer, backdrop(layer.shape[1], layer.shape[0], bg))
   if kind == "blur":
      out = image.blur(out, scale)
   return out


# ── 줄 그리기 (순수 함수 — layers view --each 도 쓴다) ──

def fit_text(text: str, width: int, px: int = image.LABEL_PX) -> str:
   """width 픽셀에 들어가게 뒤를 자르고 … 를 붙인다."""
   if width <= 0:
      return ""
   if image.label_width(text, px) <= width:
      return text
   cut = text
   while cut and image.label_width(cut + ELLIPSIS, px) > width:
      cut = cut[:-1]
   return cut + ELLIPSIS if cut else ""


def _grid(sizes: list[list[tuple[int, int]]]) -> tuple[int, list[int], list[int]]:
   """칸 크기 (너비, 높이) 줄들 → 열 수 · 열 너비 · 줄 높이."""
   cols = max(len(row) for row in sizes)
   col_w = [max((row[c][0] for row in sizes if c < len(row)), default=0) for c in range(cols)]
   row_h = [max((cell[1] for cell in row), default=0) for row in sizes]
   return cols, col_w, row_h


def layout_size(sizes: list[list[tuple[int, int]]], row_labels: bool = False, col_labels: bool = False,
                gap: int = GAP, px: int = image.LABEL_PX) -> tuple[int, int]:
   """`layout_rows` 가 낼 판 크기 (너비, 높이) 를 그리지 않고 셈한다. 칸은 (너비, 높이).

   큰 판은 칸을 다 그리기 전에 이것으로 크기 상한을 먼저 본다 (R1-M3).
   """
   band = px + 4
   cols, col_w, row_h = _grid(sizes)
   width = sum(col_w) + gap * (cols - 1) + gap * 2
   head = band + gap if col_labels else 0
   label_h = band if row_labels else 0
   height = gap + head + sum(h + label_h for h in row_h) + gap * (len(sizes) - 1) + gap
   return width, height


def kind_size(width: int, height: int, kind: str, scale: int, tile: int = 2) -> tuple[int, int]:
   """`render_kind` 가 낼 칸 크기. tile 판만 tile 배 넓다."""
   times = scale * (tile if kind == "tile" else 1)
   return width * times, height * times


def layout_rows(
   rows: list[list[np.ndarray]],
   row_labels: list[str] | None = None,
   col_labels: list[str] | None = None,
   gap: int = GAP,
   back: tuple[int, int, int, int] = SHEET_BACK,
   px: int = image.LABEL_PX,
) -> np.ndarray:
   """그림 여러 줄을 한 장으로. 줄마다 칸 수가 달라도 된다. 칸은 자기 자리 왼쪽 위에 놓는다.

   col_labels : 맨 위 머리 띠에 칸(열)마다 글자. row_labels : 줄마다 그 줄 아래 띠에 글자.
   띠 높이 = 글자 크기 + 4. 글자는 띠 폭에 맞춰 자른다. 딱지를 주면 글꼴이 있어야 한다
   (없으면 ArtToolError — 부르는 쪽이 `image.has_label_font()` 로 먼저 보고 딱지를 뺀다).
   출력이 image.MAX_PIXELS 를 넘으면 그리기 전에 거절한다.
   """
   if not rows or not any(rows):
      raise ArtToolError("늘어놓을 그림이 없다")
   if row_labels is not None and len(row_labels) != len(rows):
      raise ArtToolError(f"줄 딱지 수 {len(row_labels)} 가 줄 수 {len(rows)} 와 다르다")
   band = px + 4
   sizes = [[(cell.shape[1], cell.shape[0]) for cell in row] for row in rows]
   cols, col_w, row_h = _grid(sizes)
   inner_w = sum(col_w) + gap * (cols - 1)
   head = band + gap if col_labels else 0
   width, height = layout_size(sizes, row_labels is not None, bool(col_labels), gap, px)
   image.check_pixels(width, height, "비교판")

   sheet = image.new(width, height, back)
   xs = [gap + sum(col_w[:c]) + gap * c for c in range(cols)]
   if col_labels:
      for c, text in enumerate(col_labels[:cols]):
         area = sheet[gap : gap + band, xs[c] : xs[c] + col_w[c]]
         image.draw_label(area, fit_text(text, col_w[c], px), 0, 1, px, LABEL_COLOR)
   y = gap + head
   for r, row in enumerate(rows):
      for c, cell in enumerate(row):
         image.paste(sheet, cell, xs[c], y)
      y += row_h[r]
      if row_labels is not None:
         area = sheet[y : y + band, gap : gap + inner_w]
         image.draw_label(area, fit_text(row_labels[r], inner_w, px), 0, 1, px, LABEL_COLOR)
         y += band
      y += gap
   return sheet


# ── 격자 눈금 (--grid N, 피드백 후속 설계 3-7) ──
# zoom 판에만 원본 N 칸마다 1px 선과 위 · 왼 여백에 원본 좌표 숫자. 기본 0 = 끔이라 예전 출력과 바이트까지 같다.

GRID_COLOR = "#FF00FF"
GRID_MIN_SCALE = 4          # 선이 원본 칸을 다 덮지 않으려면 4배는 돼야 한다


def grid_options(args, kinds: list[str]) -> tuple[int, tuple[int, int, int, int] | None]:
   """(N, 선 색). 끔이면 (0, None). 배선 전에도 돌게 getattr 로 읽는다."""
   grid = int(getattr(args, "grid", 0) or 0)
   if grid == 0:
      return 0, None
   if grid < 2:
      raise UsageError(f"--grid 는 2 이상이다 (끄려면 0) : {grid}")
   if "zoom" not in kinds:
      raise UsageError("--grid 는 zoom 판에만 긋는다. --kinds 에 zoom 을 넣는다")
   text = getattr(args, "grid_color", None) or GRID_COLOR
   try:
      color = (*parse_hex(text), 255)
   except ArtToolError as exc:
      raise UsageError(f"--grid-color 는 #RRGGBB 다 : {text}") from exc
   return grid, color


def grid_marks(length: int, grid: int) -> list[int]:
   """눈금을 긋는 원본 좌표 — 0, N, 2N … (길이 안)."""
   return list(range(0, length, grid))


def grid_margin(items: list[np.ndarray], grid: int) -> tuple[int, int]:
   """(왼 여백 폭, 위 여백 높이). 딱지 글꼴이 없으면 숫자 없이 선만 긋는다."""
   if not image.has_label_font():
      return 0, 0
   longest = max(max(grid_marks(arr.shape[0], grid)) for arr in items)
   return image.label_width(str(longest)) + 4, image.LABEL_PX + 4


def draw_grid(cell: np.ndarray, scale: int, grid: int, color: tuple[int, int, int, int], margin: tuple[int, int]) -> np.ndarray:
   """확대 칸에 선을 긋고 위 · 왼에 여백을 붙여 원본 좌표 숫자를 찍는다. 숫자가 겹칠 자리는 건너뛴다."""
   left, top = margin
   height, width = cell.shape[0], cell.shape[1]
   out = image.new(width + left, height + top, SHEET_BACK)
   lined = cell.copy()
   xs = grid_marks(width // scale, grid)
   ys = grid_marks(height // scale, grid)
   for x in xs:
      lined[:, x * scale] = color
   for y in ys:
      lined[y * scale, :] = color
   out[top:, left:] = lined
   if left == 0 or top == 0:
      return out

   free = 0
   for x in xs:
      at = left + x * scale + 1
      if at < free:
         continue
      image.draw_label(out[:top], str(x), at, 1, image.LABEL_PX, LABEL_COLOR)
      free = at + image.label_width(str(x)) + 2
   free = 0
   for y in ys:
      at = top + y * scale + 1
      if at < free:
         continue
      image.draw_label(out[:, :left], str(y), 1, at, image.LABEL_PX, LABEL_COLOR)
      free = at + image.LABEL_PX + 2
   return out


# ── 재기 (판정 없음) ──
# 검사(checks/)의 재기 함수를 그대로 부른다 — 비교판 숫자와 check 경고가 같은 정의로 센다 (설계 7-2 ② · ③).

def measure(arr: np.ndarray) -> dict:
   """색 수 · 외톨이 칸 수 · 외곽선 몫. 그림 밖은 투명으로 본다.

   `outline_ratio` = 외곽선 검사의 가장자리 칸 ÷ 불투명 칸, `outline_ratio_ref` = 불투명 bbox 긴 변 n 의 (4n−4)/n².
   """
   lonely = pixel_check.measure_isolated(arr)
   edge = outline_check.measure_outline(arr)
   return {
      "colors": image.count_colors(arr),
      "opaque": lonely["opaque"],
      "isolated": lonely["count"],
      "outline_ratio": edge["share"],
      "outline_ratio_ref": edge["expected_share"],
   }


# ── 명령 ──

def run(args) -> dict:
   kinds = parse_kinds(args.kinds)
   bg = parse_bg(args.bg)
   tile = int(args.tile)
   if tile not in (2, 4):
      raise UsageError(f"--tile 은 2 또는 4 다 : {tile}")
   out_file = jailed_output(args.out_file)

   grid, grid_color = grid_options(args, kinds)

   files, warnings = collect_inputs(list(args.in_paths))
   guard_overwrite([out_file], files)          # 비교판이 입력 PNG 를 덮지 않게 (R1-H1)
   items = [image.load(path) for path in files]
   scale = pick_scale(args.scale, items)
   margin = (0, 0)
   if grid:
      if scale < GRID_MIN_SCALE:
         warnings.append(_warn("grid_scale", f"--grid 라 배율을 {scale} 에서 {GRID_MIN_SCALE} 로 올렸다", [scale]))
         scale = GRID_MIN_SCALE
      margin = grid_margin(items, grid)

   label = bool(args.label)
   if label and not image.has_label_font():
      label = False
      warnings.append(_warn("label_font", f"딱지 글꼴이 없어 딱지를 뺐다 (설치가 깨졌다) : {image.LABEL_FONT}", []))

   # 판 크기를 그리기 전에 셈해 상한을 먼저 본다 — 칸을 다 그린 뒤에 거절하면 메모리를 이미 다 썼다 (R1-M3)
   sizes = [[kind_size(arr.shape[1], arr.shape[0], kind, scale, tile) for kind in kinds] for arr in items]
   if grid:
      sizes = [[(w + margin[0], h + margin[1]) if kind == "zoom" else (w, h) for kind, (w, h) in zip(kinds, row)]
               for row in sizes]
   image.check_pixels(*layout_size(sizes, label, label), "비교판")

   rows =[[render_kind(arr, kind, scale, tile, bg) for kind in kinds] for arr in items]
   if grid:
      rows = [[draw_grid(cell, scale, grid, grid_color, margin) if kind == "zoom" else cell for kind, cell in zip(kinds, row)]
              for row in rows]
   report_items = []
   row_labels = []
   for index, (path, arr) in enumerate(zip(files, items), start=1):
      w, h = image.size(arr)
      numbers = measure(arr)
      report_items.append({"no": index, "name": path.name, "path": str(path), "size": [w, h], **numbers})
      row_labels.append(f"{index}. {path.stem}  {w}x{h} · {numbers['colors']}색")

   titles = [KIND_TITLES[k] + (f" {tile}×{tile}" if k == "tile" else "") for k in kinds]
   sheet = layout_rows(rows, row_labels if label else None, titles if label else None)
   dry_run = is_dry_run(args)
   if not dry_run:
      image.save(out_file, sheet)

   result = {
      "status": "ok",
      **dry_run_fields(dry_run, [out_file]),
      "out": None if dry_run else str(out_file),
      "size": list(image.size(sheet)),
      "scale": scale,
      "kinds": kinds,
      "tile": tile,
      "bg": args.bg,
      "label": label,
      "items": report_items,
      "warnings": warnings,
   }
   if grid:
      result.update({"grid": grid, "grid_color": getattr(args, "grid_color", None) or GRID_COLOR, "grid_margin": list(margin)})
   return result
