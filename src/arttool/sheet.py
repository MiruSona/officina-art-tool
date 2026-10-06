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

import time
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
SCALE_PER = "per"          # --scale per : 그림(줄)마다 auto 배율 (2판 C10)
SCALE_MAX = 64             # --scale 정수의 위 한도. 넘으면 판을 그리기도 전에 메모리를 다 쓴다 (R1-M3)
SILHOUETTE = (24, 24, 32, 255)
CHECKER = ((236, 238, 244, 255), (206, 210, 222, 255))  # 회색 판(colors4)과 안 헷갈리게 푸른 기를 조금 섞었다
CHECKER_CELL = 8           # 바둑판 한 칸, 출력 픽셀
SHEET_BACK = (44, 44, 52, 255)
LABEL_COLOR = (240, 240, 240, 255)
GAP = 4
ELLIPSIS = "…"
FIND_SECONDS = 10          # --find 가 이보다 오래 걸리면 거절 (고른 무늬 장면에서 후보가 안 줄 때)
FIND_LIST_MAX = 20         # find_many 경고에 싣는 자리 수 상한


# ── 인자 읽기 ──

def parse_kinds(text: str) -> list[str]:
   kinds: list[str] = []
   for part in str(text).split(","):
      name = part.strip()
      if not name:
         continue
      if name.startswith("fit:"):
         name = f"fit:{_fit_size(name)}"
      elif name not in KINDS:
         raise UsageError(f"모르는 판 : {name} (쓸 수 있는 것 : {', '.join(KINDS)}, fit:N)")
      if name not in kinds:
         kinds.append(name)
   if not kinds:
      raise UsageError("--kinds 가 비었다")
   return kinds


def _fit_size(name: str) -> int:
   """`fit:N` 의 N — 줄여 찍을 긴 변 px."""
   try:
      value = int(name[4:])
   except ValueError as exc:
      raise UsageError(f"fit:N 의 N 은 양의 정수다 : {name}") from exc
   if value < 1:
      raise UsageError(f"fit:N 의 N 은 1 이상이다 : {name}")
   return value


def kind_title(kind: str, tile: int = 2) -> str:
   if kind.startswith("fit:"):
      return f"맞춤 {kind[4:]}"
   return KIND_TITLES[kind] + (f" {tile}×{tile}" if kind == "tile" else "")


def fit_down(arr: np.ndarray, target: int) -> np.ndarray:
   """비율을 지켜 긴 변을 target 으로 nearest 줄인다. target 이 긴 변 이상이면 원본 그대로."""
   height, width = arr.shape[:2]
   longest = max(width, height)
   if target >= longest:
      return arr
   new_w = max(1, round(width * target / longest))
   new_h = max(1, round(height * target / longest))
   ys = ((np.arange(new_h) + 0.5) * height / new_h).astype(int)     # 칸 가운데를 뽑는다 (PIL NEAREST 와 같은 셈)
   xs = ((np.arange(new_w) + 0.5) * width / new_w).astype(int)
   return arr[ys][:, xs]


def parse_bg(text: str) -> tuple[int, int, int, int] | np.ndarray | None:
   """checker 면 None, 색 꼴이면 그 색, 그 밖은 타일 PNG 그림(원래 크기 그대로).

   색 꼴에 맞으면 색으로 본다 — 옛 `--bg #hex` 호출이 그대로 돈다. 아니면 경로로 보고, 파일이 없으면 거절한다.
   """
   if text == "checker":
      return None
   try:
      return (*parse_hex(text), 255)
   except ArtToolError as exc:
      path = Path(text)
      if text.startswith("#") or not is_plain_file(path):
         raise UsageError(f"--bg 는 checker · #RRGGBB · PNG 경로 중 하나다 : {text}") from exc
   tile = image.load(path)
   image.check_pixels(tile.shape[1], tile.shape[0], "--bg 타일")
   return tile


def bg_layer(width: int, height: int, tile: np.ndarray, scale: int) -> np.ndarray:
   """타일을 칸 배율로 키운 무늬를 왼쪽 위부터 되풀이 깐다.

   키운 타일을 통째로 만들지 않고, 칸의 픽셀마다 「타일 몇 번째 칸인가」 를 셈해 바로 집는다 —
   큰 타일 × 큰 배율이라도 메모리는 칸 크기만큼만 쓴다.
   """
   th, tw = tile.shape[:2]
   ys = (np.arange(height) // scale) % th
   xs = (np.arange(width) // scale) % tw
   return tile[ys[:, None], xs[None, :]]


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


def parse_ints(text: str, name: str, count: int) -> list[int]:
   """`x,y` · `x,y,w,h` 꼴 정수 묶음."""
   parts = str(text).split(",")
   try:
      values = [int(part.strip()) for part in parts]
   except ValueError as exc:
      raise UsageError(f"{name} 는 정수 {count}개를 쉼표로 잇는다 : {text}") from exc
   if len(values) != count:
      raise UsageError(f"{name} 는 정수 {count}개를 쉼표로 잇는다 : {text}")
   return values


def over_rgba(top: np.ndarray, bottom: np.ndarray) -> np.ndarray:
   """알파 합성(over) — `over` 와 달리 bottom 이 투명일 수 있어 알파도 섞는다 (투명 칸에는 뒤에서 --bg 가 깔린다)."""
   ta = top[:, :, 3:4].astype(np.float64) / 255.0
   ba = bottom[:, :, 3:4].astype(np.float64) / 255.0
   oa = ta + ba * (1.0 - ta)
   rgb = top[:, :, :3] * ta + bottom[:, :, :3] * ba * (1.0 - ta)
   rgb = np.divide(rgb, oa, out=np.zeros_like(rgb), where=oa > 0)
   out = np.empty_like(bottom)
   out[:, :, :3] = np.rint(rgb).astype(np.uint8)
   out[:, :, 3] = np.rint(oa[:, :, 0] * 255.0).astype(np.uint8)
   return out


def place_on(scene: np.ndarray, arr: np.ndarray, x: int, y: int) -> tuple[np.ndarray, bool]:
   """장면 사본에 arr 를 (x, y) 에 얹는다. 장면 밖으로 나간 부분은 자르고 잘렸는지를 같이 돌려준다."""
   out = scene.copy()
   sh, sw = scene.shape[:2]
   h, w = arr.shape[:2]
   x0, y0, x1, y1 = max(x, 0), max(y, 0), min(x + w, sw), min(y + h, sh)
   clipped = (x0, y0, x1, y1) != (x, y, x + w, y + h)
   if x0 < x1 and y0 < y1:
      part = arr[y0 - y:y1 - y, x0 - x:x1 - x]
      out[y0:y1, x0:x1] = over_rgba(part, out[y0:y1, x0:x1])
   return out, clipped


def find_spots(scene: np.ndarray, old: np.ndarray) -> tuple[list[list[int]], int]:
   """장면에서 old 의 불투명 칸이 정확히 같은 자리를 찾는다 (알파 0 칸은 안 본다). ([x, y] 목록, 모두 몇 곳).

   목록은 위→아래 · 왼→오 순서로 FIND_LIST_MAX 개까지만 만든다 — 단색 장면에서 1x1 을 찾으면 후보가 수백만 곳이라
   파이썬 목록으로 다 만들지 않는다. 개수는 numpy 로 센다.
   첫 불투명 칸으로 후보 자리를 한 번에 거른 뒤, 남은 후보만 칸마다 numpy 로 좁힌다 — 보통 몇 칸 만에 후보가 거의 사라진다.
   무늬가 고른 장면처럼 후보가 끝까지 많이 남는 경우를 위해 걸리는 시간에 상한을 둔다 (반복 안 · 앞뒤 모두 본다).
   """
   sh, sw = scene.shape[:2]
   h, w = old.shape[:2]
   if h > sh or w > sw:
      return [], 0
   dys, dxs = np.nonzero(old[:, :, 3] > 0)
   if dys.size == 0:
      raise UsageError("--find 그림에 불투명 칸이 없다")
   packed = np.ascontiguousarray(scene).view(np.uint32)[:, :, 0]      # RGBA 네 바이트를 한 수로 — 한 번에 견준다
   want = np.ascontiguousarray(old).view(np.uint32)[:, :, 0]
   started = time.monotonic()

   def check_time(left: int) -> None:
      if time.monotonic() - started > FIND_SECONDS:
         raise ArtToolError(f"--find 가 {FIND_SECONDS}초 안에 못 끝났다 (후보 {left}곳) — 장면이나 찾는 그림을 작게 잘라 다시 준다 (--find 는 --crop 전 장면 전체에서 찾는다)")

   dy, dx = int(dys[0]), int(dxs[0])
   ys, xs = np.nonzero(packed[dy:dy + sh - h + 1, dx:dx + sw - w + 1] == want[dy, dx])
   check_time(ys.size)
   for dy, dx in zip(dys[1:].tolist(), dxs[1:].tolist()):
      if ys.size == 0:
         break
      keep = packed[ys + dy, xs + dx] == want[dy, dx]
      ys, xs = ys[keep], xs[keep]
      check_time(ys.size)
   check_time(ys.size)
   # np.nonzero 는 행 우선 순서라 걸러도 위→아래 · 왼→오 가 그대로다
   spots = [[int(x), int(y)] for y, x in zip(ys[:FIND_LIST_MAX].tolist(), xs[:FIND_LIST_MAX].tolist())]
   return spots, int(ys.size)


def scene_options(args, files: list[Path]) -> dict | None:
   """--on · --at · --crop · --find 를 읽어 장면 설정으로 묶는다. --on 이 없으면 None (옛 sheet 그대로)."""
   on, at, crop, find = (getattr(args, name, None) for name in ("on_scene", "at", "crop", "find_old"))
   clear = bool(getattr(args, "find_clear", False))
   if on is None:
      given = [name for name, value in (("--at", at), ("--crop", crop), ("--find", find), ("--find-clear", clear or None))
               if value is not None]
      if given:
         raise UsageError(f"{', '.join(given)} 는 --on 과 같이 쓴다")
      return None
   if (at is None) == (find is None):
      raise UsageError("--on 에는 --at 과 --find 중 하나만 준다")
   if clear and find is None:
      raise UsageError("--find-clear 는 --find 와 같이 쓴다")
   scene = _load_arg(on, "--on")
   sh, sw = scene.shape[:2]
   box = [0, 0, sw, sh]
   if crop is not None:
      box = parse_ints(crop, "--crop", 4)
      if box[2] <= 0 or box[3] <= 0 or box[0] < 0 or box[1] < 0 or box[0] + box[2] > sw or box[1] + box[3] > sh:
         raise UsageError(f"--crop 상자가 장면({sw}x{sh}) 안에 있지 않다 : {crop}")
   # 사본이 입력 수만큼 생기니 만들기 전에 합친 크기를 본다
   image.check_pixels(box[2], box[3] * len(files), "장면 사본")
   warnings = []
   count = None
   bx, by, bw, bh = box
   if find is not None:
      old = _load_arg(find, "--find")
      spots, count = find_spots(scene, old)
      if not spots:
         raise UsageError(f"--find 그림을 장면에서 못 찾았다 : {find}")
      if count > 1:
         warnings.append(_warn("find_many", f"--find 자리가 모두 {count}곳이라 첫 자리를 썼다 (목록은 {FIND_LIST_MAX}곳까지)",
                               spots))
      x, y = spots[0]
   else:
      x, y = parse_ints(at, "--at", 2)
   # 장면을 먼저 상자로 잘라 사본으로 둔다 — 칸마다 상자 크기만큼만 쓰게 (위 크기 검사와 셈이 맞는다)
   cut = scene[by:by + bh, bx:bx + bw].copy()
   del scene
   if clear:
      # --find-clear : 찾은 자리에서 옛 그림의 불투명 칸을 투명으로 비운다 — 뒤에서 --bg 가 비친다
      dys, dxs = np.nonzero(old[:, :, 3] > 0)
      ys, xs = dys + (y - by), dxs + (x - bx)
      keep = (ys >= 0) & (ys < bh) & (xs >= 0) & (xs < bw)
      cut[ys[keep], xs[keep]] = 0
   return {"scene": cut, "path": on, "at": [x, y], "rel": [x - bx, y - by], "box": box, "crop": crop is not None,
           "find": find, "find_count": count, "find_clear": clear, "warnings": warnings}


def _load_arg(path: str, name: str) -> np.ndarray:
   """--on · --find 로 준 PNG — 없거나 못 읽으면 인자 잘못(종료 2)이다."""
   try:
      return image.load(path)
   except ArtToolError as exc:
      raise UsageError(f"{name} : {exc}") from exc


def compose_scene(items: list[np.ndarray], files: list[Path], spec: dict) -> tuple[list[np.ndarray], list[dict]]:
   """입력 그림마다 (이미 --crop 상자로 자른) 장면 사본에 얹는다."""
   x, y = spec["rel"]
   out, clipped = [], []
   for path, arr in zip(files, items):
      cell, cut = place_on(spec["scene"], arr, x, y)
      if cut:
         clipped.append(path.name)
      out.append(cell)
   warnings = list(spec["warnings"])
   if clipped:
      warnings.append(_warn("on_clipped", "얹은 그림이 장면(또는 --crop 상자) 밖으로 나가 잘렸다", clipped))
   return out, warnings


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

def backdrop(width: int, height: int, bg: tuple[int, int, int, int] | np.ndarray | None, scale: int = 1) -> np.ndarray:
   """칸 배경. bg 가 None 이면 바둑판, 그림이면 그 타일 (반투명 타일은 바둑판 위에 먼저 깐다)."""
   if isinstance(bg, np.ndarray):
      return over(bg_layer(width, height, bg, scale), backdrop(width, height, None))
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
   if kind.startswith("fit:"):
      return image.scale_up(fit_down(arr, int(kind[4:])), scale)    # 원래 크기로 되키우지 않는다
   raise UsageError(f"모르는 판 : {kind}")


def render_kind(arr: np.ndarray, kind: str, scale: int, tile: int = 2,
                bg: tuple[int, int, int, int] | np.ndarray | None = None) -> np.ndarray:
   """칸 하나 — 판을 배경 위에 얹은 불투명 그림."""
   layer = kind_layer(arr, kind, scale, tile)
   out = over(layer, backdrop(layer.shape[1], layer.shape[0], bg, scale))
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
   """`render_kind` 가 낼 칸 크기. tile 판만 tile 배 넓고, fit 판은 줄인 크기다."""
   if kind.startswith("fit:"):
      small = fit_down(np.zeros((height, width, 1), dtype=np.uint8), int(kind[4:]))
      return small.shape[1] * scale, small.shape[0] * scale
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

def run_strip(args) -> dict:
   """--strip : 여백 0 · 딱지 없음 · 배율 1 · 투명 바탕으로 --in 순서대로 가로로 붙인다."""
   given = [name for name, value in (("--kinds", args.kinds not in (None, "zoom")),
                                         ("--scale", args.scale not in (None, "auto")), ("--grid", getattr(args, "grid", 0)),
                                         ("--grid-color", getattr(args, "grid_color", None)),
                                         ("--tile", getattr(args, "tile", 2) not in (None, 2)),
                                         ("--bg", getattr(args, "bg", "checker") not in (None, "checker")),
                                         ("--label", getattr(args, "label", False)),
                                         ("--on", getattr(args, "on_scene", None)),
                                         ("--at", getattr(args, "at", None)),
                                         ("--crop", getattr(args, "crop", None)),
                                         ("--find", getattr(args, "find_old", None)),
                                         ("--find-clear", getattr(args, "find_clear", False)))
            if value]       # 기본값(zoom · auto · 0 · 없음 · 2 · checker · 끔)과 다르면 준 것으로 본다 — strip 은 이것들을 안 쓴다
   if given:
      raise UsageError(f"--strip 은 {', '.join(given)} 와 같이 못 쓴다 (뜻이 섞인다)")
   out_file = jailed_output(args.out_file)
   files, warnings = collect_inputs(list(args.in_paths))
   guard_overwrite([out_file], files)
   items = [image.load(path) for path in files]
   band = image.strip(items)
   dry_run = is_dry_run(args)
   if not dry_run:
      image.save(out_file, band)
   return {
      "status": "ok",
      **dry_run_fields(dry_run, [out_file]),
      "out": None if dry_run else str(out_file),
      "size": list(image.size(band)),
      "strip": True,
      "frame": list(image.size(items[0])),
      "count": len(items),
      "items": [{"no": i, "name": p.name, "path": str(p)} for i, p in enumerate(files, start=1)],
      "warnings": warnings,
   }


def run(args) -> dict:
   if getattr(args, "strip", False):
      return run_strip(args)
   kinds = parse_kinds(args.kinds if args.kinds is not None else "zoom")
   bg = parse_bg(args.bg)
   tile = int(args.tile)
   if tile not in (2, 4):
      raise UsageError(f"--tile 은 2 또는 4 다 : {tile}")
   out_file = jailed_output(args.out_file)

   grid, grid_color = grid_options(args, kinds)

   files, warnings = collect_inputs(list(args.in_paths))
   # 비교판이 입력 PNG(--bg 타일 · --on 장면 · --find 그림 포함)를 덮지 않게 (R1-H1)
   extra = [Path(p) for p in (args.bg if isinstance(bg, np.ndarray) else None,
                              getattr(args, "on_scene", None), getattr(args, "find_old", None)) if p]
   guard_overwrite([out_file], files + extra)
   spec = scene_options(args, files)
   items = [image.load(path) for path in files]
   originals = items
   if spec is not None:
      # 칸 = 장면 사본 — 배율 · 판 · 눈금은 얹은 장면을 한 그림으로 보고 그대로 돈다
      items, scene_warnings = compose_scene(items, files, spec)
      warnings.extend(scene_warnings)
   # --scale per (2판 C10) : 그림(줄)마다 auto 배율을 따로 정한다. 25px 소품이 397px 조각 탓에 1배로 나오지 않게.
   per = str(args.scale) == SCALE_PER
   if per:
      scales = [pick_scale("auto", [arr]) for arr in items]
   else:
      scales = [pick_scale(args.scale if args.scale is not None else "auto", items)] * len(items)
   scale = scales[0] if scales else 1
   for kind in kinds:
      if kind.startswith("fit:"):
         bigger = [path.name for path, arr in zip(files, items) if int(kind[4:]) > max(arr.shape[:2])]
         if bigger:
            warnings.append(_warn("fit_upscale", f"{kind} 이 그림 긴 변보다 커서 원본 그대로 넣었다", bigger))
   margin = (0, 0)
   if grid:
      low = sorted({s for s in scales if s < GRID_MIN_SCALE})
      if low:
         warnings.append(_warn("grid_scale", f"--grid 라 배율을 {', '.join(map(str, low))} 에서 {GRID_MIN_SCALE} 로 올렸다", low))
         scales = [max(s, GRID_MIN_SCALE) for s in scales]
         scale = scales[0]
      margin = grid_margin(items, grid)

   label = bool(args.label)
   if label and not image.has_label_font():
      label = False
      warnings.append(_warn("label_font", f"딱지 글꼴이 없어 딱지를 뺐다 (설치가 깨졌다) : {image.LABEL_FONT}", []))

   # 판 크기를 그리기 전에 셈해 상한을 먼저 본다 — 칸을 다 그린 뒤에 거절하면 메모리를 이미 다 썼다 (R1-M3)
   sizes = [[kind_size(arr.shape[1], arr.shape[0], kind, s, tile) for kind in kinds] for arr, s in zip(items, scales)]
   if grid:
      sizes = [[(w + margin[0], h + margin[1]) if kind == "zoom" else (w, h) for kind, (w, h) in zip(kinds, row)]
               for row in sizes]
   image.check_pixels(*layout_size(sizes, label, label), "비교판")

   rows = [[render_kind(arr, kind, s, tile, bg) for kind in kinds] for arr, s in zip(items, scales)]
   if grid:
      rows = [[draw_grid(cell, s, grid, grid_color, margin) if kind == "zoom" else cell for kind, cell in zip(kinds, row)]
              for row, s in zip(rows, scales)]
   report_items = []
   row_labels = []
   for index, (path, arr, s) in enumerate(zip(files, originals, scales), start=1):
      w, h = image.size(arr)
      numbers = measure(arr)
      entry = {"no": index, "name": path.name, "path": str(path), "size": [w, h], **numbers}
      text = f"{index}. {path.stem}  {w}x{h} · {numbers['colors']}색"
      if per:
         # 줄마다 배율이 달라 크기를 오해하지 않게 딱지 끝 · 보고 칸에 배율을 싣는다
         entry["scale"] = s
         text += f" · ×{s}"
      report_items.append(entry)
      row_labels.append(text)

   titles = [kind_title(k, tile) for k in kinds]
   sheet = layout_rows(rows, row_labels if label else None, titles if label else None)
   dry_run = is_dry_run(args)
   if not dry_run:
      image.save(out_file, sheet)

   result = {
      "status": "ok",
      **dry_run_fields(dry_run, [out_file]),
      "out": None if dry_run else str(out_file),
      "size": list(image.size(sheet)),
      "scale": SCALE_PER if per else scale,
      "kinds": kinds,
      "tile": tile,
      "bg": args.bg,
      "label": label,
      "items": report_items,
      "warnings": warnings,
   }
   if spec is not None:
      result["on"] = {"scene": str(spec["path"]), "at": spec["at"], "crop": spec["box"] if spec["crop"] else None,
                      "find": str(spec["find"]) if spec["find"] else None, "find_count": spec["find_count"],
                      "find_clear": spec["find_clear"]}
   if grid:
      result.update({"grid": grid, "grid_color": getattr(args, "grid_color", None) or GRID_COLOR, "grid_margin": list(margin)})
   return result
