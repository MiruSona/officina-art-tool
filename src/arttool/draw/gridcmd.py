"""`arttool grid show` · `grid apply` — 문자 격자를 찍고, 격자 패치를 덧그려 새 자리에 쓴다 (draw 고리 설계 2-3).

입력은 겹 묶음 폴더(layers.json 이 있는 폴더)나 PNG 한 장. PNG 는 `body` 한 겹으로 연다.
원본은 안 덮는다 : `apply` 는 `--out` 새 자리에만 쓰고, `--in` 과 겹치면 종료 2 (설계 9절 · 17절 원본 보호).
"""

from __future__ import annotations

import shutil
from pathlib import Path

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


def run_show(args) -> dict:
   canvas, _folder = open_input(args)
   box = _box(args.box)
   try:
      text = canvas.to_grid(args.layer, box, args.rulers)
   except ArtToolError as exc:
      if box is None and max(canvas.size) > grid.MAX_SIDE:
         raise UsageError(f"{exc}. --box x,y,w,h 로 창을 준다") from exc
      raise
   return {"status": "ok", "in": str(args.in_path), "layer": args.layer, "size": list(canvas.size),
           "legend": {k: to_hex(rgb) for k, rgb in canvas.legend.letters().items()},
           "grid_text": text}


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
   result = canvas.paste_grid(name, grid_file.read_text(encoding="utf-8"), at, args.mode)
   at = canvas[name].last["at"]                     # --at 을 안 주면 글의 `# 원점` 줄 자리

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
           "out": None if dry_run else str(out), "layer": name, "at": at, "mode": args.mode, **result}


SUBS = {"show": run_show, "apply": run_apply}


def run(args) -> dict:
   return SUBS[args.sub](args)
