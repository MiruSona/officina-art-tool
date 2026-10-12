"""`arttool grid show` · `grid apply` — 문자 격자를 찍고, 격자 패치를 덧그려 새 자리에 쓴다 (draw 고리 설계 2-3).

입력은 겹 묶음 폴더(layers.json 이 있는 폴더)나 PNG 한 장. PNG 는 `body` 한 겹으로 연다.
원본은 안 덮는다 : `apply` 는 `--out` 새 자리에만 쓰고, `--in` 과 겹치면 종료 2 (설계 9절 · 17절 원본 보호).
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import numpy as np

from .. import image, layerset
from ..edit import dry_run_fields, is_dry_run
from ..errors import ArtToolError, UsageError
from ..jsonio import read_json
from ..palette import to_hex
from ..paths import guard_outside, guard_overwrite, jailed_output, same_key
from . import grid
from .canvas import Canvas


def _ints(text: str, count: int, flag: str) -> list[int]:
   try:
      values = [int(v) for v in str(text).split(",")]
   except ValueError:
      values = []
   if len(values) != count:
      raise UsageError(f"{flag} 는 정수 {count} 개를 쉼표로 준다 : {text}")
   return values


def _box(text: str | None):
   """`--box x,y,w,h` → (x0, y0, x1, y1)."""
   if text is None:
      return None
   x, y, w, h = _ints(text, 4, "--box")
   if w <= 0 or h <= 0:
      raise UsageError(f"--box 의 너비 · 높이는 1 이상이다 : {text}")
   return x, y, x + w, y + h


def open_input(args) -> tuple[Canvas, Path | None]:
   """--in → (캔버스, 겹 묶음 폴더 또는 None). --legend 를 주면 글자표를 그것으로 바꾼다."""
   source = Path(args.in_path)
   if source.is_dir():
      canvas, folder = Canvas.open(source, args.item), source
   elif source.is_file() and source.suffix.lower() == ".png":
      arr = image.load(source)
      canvas, folder = Canvas((arr.shape[1], arr.shape[0])), None
      canvas["body"].arr = arr.copy()
   else:
      raise UsageError(f"--in 은 겹 묶음 폴더나 PNG 다 : {source}")
   if args.legend_file:
      data = read_json(args.legend_file)
      if not isinstance(data, dict):
         raise UsageError(f"--legend 는 {{\"글자\": \"#RRGGBB\"}} 꼴 JSON 이다 : {args.legend_file}")
      try:
         canvas.legend = grid.Legend(data)
      except ArtToolError as exc:
         raise UsageError(f"--legend : {exc}") from exc
   return canvas, folder


def _pick_layer(canvas: Canvas, name: str | None) -> str:
   if name is not None:
      canvas.layer(name)
      return name
   if len(canvas.names) == 1:
      return canvas.names[0]
   raise UsageError(f"--layer 로 겹을 고른다 : {' · '.join(canvas.names)}")


def _shrink_window(source, shrink: int, box):
   """줄인 그림(전체 크기)을 만들되, 창이 있으면 원본에서 창×N 영역만 줄여 그 자리에 놓는다. 나머지 칸은 투명.

   맞출 색 목록은 늘 원본 전체에서 뽑는다 — 창만 잘라도 전체를 줄인 뒤 자른 것과 같게."""
   colors = grid.opaque_colors(source)
   height, width = source.shape[:2]
   small_h, small_w = (height + shrink - 1) // shrink, (width + shrink - 1) // shrink
   if box is None:
      return grid.shrink_cells(source, shrink, colors)
   x0, y0 = max(box[0], 0), max(box[1], 0)
   x1, y1 = min(box[2], small_w), min(box[3], small_h)
   small = np.zeros((small_h, small_w, 4), dtype=source.dtype)
   if x0 >= x1 or y0 >= y1:
      return small   # 빈 창 — to_text 가 거절 글을 낸다
   part = source[y0 * shrink:y1 * shrink, x0 * shrink:x1 * shrink]
   small[y0:y1, x0:x1] = grid.shrink_cells(part, shrink, colors)
   return small


def _show_text(canvas: Canvas, args, box, shrink: int) -> tuple[str, list[int]]:
   """(격자 글, 찍은 그림 크기 [너비, 높이]). shrink ≥ 2 면 줄인 그림에서 찍고 `# 줄임 N WxH` 줄을 맨 위에 단다.

   WxH 는 원본 캔버스 크기다 — `grid apply` 가 이 글을 어느 크기 캔버스에 붙이는지 가릴 때 쓴다."""
   if shrink == 1:
      return canvas.to_grid(args.layer, box, args.rulers), list(canvas.size)
   source = canvas.layer(args.layer).arr if args.layer is not None else canvas.merged()
   small = _shrink_window(source, shrink, box)
   text = grid.to_text(small, canvas.legend, box, args.rulers)
   width, height = canvas.size
   return f"# 줄임 {shrink} {width}x{height}\n{text}", [small.shape[1], small.shape[0]]


def _too_big_hint(shrink: int) -> str:
   if shrink > 1:
      return "--box x,y,w,h 로 창을 주거나 --shrink 를 더 크게 준다"
   return "--box x,y,w,h 로 창을 주거나 --shrink 로 줄인다"


def run_show(args) -> dict:
   shrink = args.shrink
   if shrink < 1:
      raise UsageError(f"--shrink 는 1 이상 정수다 : {shrink}")
   canvas, _folder = open_input(args)
   box = _box(args.box)
   try:
      text, size = _show_text(canvas, args, box, shrink)
   except ArtToolError as exc:
      shown = [(side + shrink - 1) // shrink for side in canvas.size]
      if box is None and max(shown) > grid.MAX_SIDE:
         raise UsageError(f"{exc}. {_too_big_hint(shrink)}") from exc
      raise
   result = {"status": "ok", "in": str(args.in_path), "layer": args.layer, "shrink": shrink, "size": size,
             "legend": {k: to_hex(rgb) for k, rgb in canvas.legend.letters().items()},
             "grid_text": text}
   if args.no_legend:
      # 창 여럿을 나란히 볼 때 범례 수십 줄이 끼지 않게 글에서만 뺀다.
      # 글자표는 --legend 파일이 들고 있을 때만 JSON 칸도 뺀다 — 없으면 글자 → 색을 잃는다
      result["grid_text"] = grid.strip_legend(text)
      if args.legend_file:
         del result["legend"]
   return result


# `# 줄임 N WxH`(새 꼴, WxH = 원본 크기) · `# 줄임 N`(옛 꼴) 둘 다 받는다
_SHRINK_LINE = re.compile(r"^#\s*줄임\s+(\d+)(?:\s+(\d+)x(\d+))?\s*$")


def _shrink_of(text: str) -> tuple[int, tuple[int, int] | None] | None:
   """격자 글 머리의 (줄임 N, 원본 크기 또는 None). `# 줄임` 줄이 없으면 None."""
   for line in text.splitlines():
      found = _SHRINK_LINE.match(line.strip())
      if found:
         size = None if found.group(2) is None else (int(found.group(2)), int(found.group(3)))
         return int(found.group(1)), size
   return None


def _shrink_warnings(header, canvas_size) -> list[str]:
   """줄인 좌표 격자(`# 줄임 N`, N ≥ 2)를 어느 크기 캔버스에 붙이나 본다. 붙이기는 그대로 한다(경고만).

   새 꼴(원본 크기 있음) : 캔버스 = 원본이면 「어긋난다」, = 줄인 크기(올림 나눗셈)면 경고 없음,
   둘 다 아니면 「원본도 줄인 크기도 아니다」. 창 글이라도 원본 크기로 가린다.
   옛 꼴(크기 없음) : 가릴 수 없어 일반 경고 한 줄.
   """
   n, original = header
   cw, ch = canvas_size
   if original is None:
      return [f"격자 글이 `# 줄임 {n}` 이라 1/{n} 좌표다 — 캔버스 {cw}x{ch} 가 줄인 크기가 아니면 자리가 어긋난다"]
   ow, oh = original
   small = ((ow + n - 1) // n, (oh + n - 1) // n)
   if (cw, ch) == small:
      return []
   if (cw, ch) == (ow, oh):
      return [f"격자 글이 `# 줄임 {n}` 이라 1/{n} 좌표인데 캔버스 {cw}x{ch} 는 원본 크기다 — "
              f"줄인 크기 {small[0]}x{small[1]} 캔버스에 붙이거나 --shrink 없이 다시 찍는다"]
   return [f"격자 글이 `# 줄임 {n}` (원본 {ow}x{oh} → {small[0]}x{small[1]}) 인데 "
           f"캔버스 {cw}x{ch} 는 원본도 줄인 크기도 아니다 — 자리가 맞는지 본다"]


def _plan_writes(folder: Path | None, out: Path, canvas: Canvas, item: str) -> list[Path]:
   """진짜로 쓸 파일 목록 — 원본 묶음 복사본 + 그림 item 의 겹 그림들 + layers.json."""
   if folder is None:
      return [out]
   files = {out / p.relative_to(folder) for p in folder.rglob("*") if p.is_file()}
   lay = layerset.load(folder)
   files |= {p for n in canvas.names if (p := layerset.image_path(out, lay, n, item)) is not None}
   files.add(out / layerset.FILE_NAME)
   return sorted(files)


def run_apply(args) -> dict:
   if same_key(args.in_path) == same_key(args.out):
      raise UsageError(f"--out 이 --in 과 같다 — 원본을 안 덮는다. 새 자리를 준다 : {args.out}")
   grid_file = Path(args.grid_file)
   if not grid_file.is_file():
      raise UsageError(f"--grid 파일이 없다 : {grid_file}")
   canvas, folder = open_input(args)
   if folder is None:
      out = jailed_output(args.out)
      if out.suffix.lower() != ".png":
         raise UsageError(f"PNG 입력이면 --out 도 .png 다 : {args.out}")
      guard_overwrite([out], [args.in_path, grid_file])
   else:
      out = Path(args.out).resolve()
      guard_outside([out], [folder])                 # 원본 묶음 안에 쓰지 않는다
      guard_outside([folder], [out], "--in")         # 원본 묶음을 품은 폴더에도 안 쓴다
      if out.exists() and (not out.is_dir() or any(out.iterdir())):
         raise UsageError(f"--out 은 없거나 빈 폴더여야 한다 (원본 묶음을 안 덮는다) : {out}")
   name = _pick_layer(canvas, args.layer)
   at = None if args.at is None else tuple(_ints(args.at, 2, "--at"))
   text = grid_file.read_text(encoding="utf-8")
   result = canvas.paste_grid(name, text, at, args.mode)
   at = canvas[name].last["at"]                     # --at 을 안 주면 글의 `# 원점` 줄 자리
   header = _shrink_of(text)
   warnings = _shrink_warnings(header, canvas.size) if header is not None and header[0] >= 2 else []

   dry_run = is_dry_run(args)
   writes = _plan_writes(folder, out, canvas, args.item)
   if folder is not None:
      # 작은 겹 상자 밖 칸 등 save 가 거절할 일을 복사 전에 잡는다 — dry-run 도 같은 자리에서 같은 오류
      canvas.check_save(folder, args.item)
   if not dry_run:
      if folder is None:
         image.save(out, canvas[name].arr)
      else:
         shutil.copytree(folder, out, dirs_exist_ok=True)   # 손 안 댄 겹 · 다른 그림은 바이트 그대로
         canvas.save(out, args.item)
   return {"status": "ok", **dry_run_fields(dry_run, writes), "in": str(args.in_path),
           "out": None if dry_run else str(out), "layer": name, "at": at, "mode": args.mode, **result,
           **({"warnings": warnings} if warnings else {})}


SUBS = {"show": run_show, "apply": run_apply}


def run(args) -> dict:
   return SUBS[args.sub](args)
