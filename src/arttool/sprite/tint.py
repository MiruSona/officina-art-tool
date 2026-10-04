"""`tint` — 흰 · 밝은 회색으로 뽑은 겹에 색을 곱해 변종을 만든다 (2026-10-04 피드백후속설계 3-6).

불투명 칸(알파 > 0)의 RGB 에 `색 / 255` 를 곱한다. 알파와 투명 칸은 그대로다.
출력은 `--out` 폴더에 `<원래이름>_<RRGGBB>.png`. `--sheet` 를 주면 그림마다 한 줄(원본 + 색마다 한 칸) 비교판.
`recolor`(색표 1:1 바꾸기)와 따로 둔 까닭은 설계 5절.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .. import image
from ..checks import warning
from ..edit import list_inputs
from ..errors import ArtToolError, UsageError
from ..palette import parse_hex, to_hex
from ..paths import guard_outside, guard_overwrite, jailed_output, resolve_root, safe_join

VERSION = 1
SHEET_SCALE = 4
# 원본 불투명 칸의 평균 밝기가 이보다 낮으면 곱한 결과가 탁하다.
DARK_SOURCE = 170


def parse_colors(text) -> list[tuple[int, int, int]]:
   colors = []
   for part in str(text or "").split(","):
      if not part.strip():
         continue
      try:
         colors.append(parse_hex(part))
      except ArtToolError as exc:
         raise UsageError(f"--colors 색을 못 읽었다 : {part.strip()} (#RRGGBB 꼴)") from exc
   if not colors:
      raise UsageError("--colors 에 색이 하나 이상 있어야 한다")
   return colors


def tint(arr: image.RGBA, rgb: tuple[int, int, int]) -> image.RGBA:
   """불투명 칸의 RGB × rgb / 255 (반올림)."""
   out = arr.copy()
   opaque = arr[:, :, 3] > 0
   mixed = (arr[:, :, :3].astype(np.uint32) * np.array(rgb, dtype=np.uint32) + 127) // 255
   out[opaque, :3] = mixed[opaque].astype(np.uint8)
   return out


def mean_luma(arr: image.RGBA) -> float | None:
   opaque = arr[:, :, 3] > 0
   if not opaque.any():
      return None
   return float(image.luma(arr)[opaque].mean())


def _plan(inputs: list[Path], colors, out_dir) -> list[list[Path]]:
   """그림마다 색 순서대로 쓸 자리. 이름이 겹치면(대소문자 무시) 거절한다."""
   root = resolve_root(out_dir)
   if root.is_file():
      raise UsageError(f"--out 은 폴더여야 한다 : {out_dir}")
   seen: dict[str, str] = {}
   plan = []
   for source in inputs:
      row = []
      for rgb in colors:
         name = f"{source.stem}_{to_hex(rgb)[1:]}.png"
         if name.casefold() in seen:
            raise UsageError(f"출력 이름이 겹친다 : {name} (같은 색을 두 번 줬거나 그림 이름이 겹친다)")
         seen[name.casefold()] = name
         row.append(safe_join(root, name))
      plan.append(row)
   return plan


def run(args) -> dict:
   colors = parse_colors(args.colors)
   scale = int(getattr(args, "scale", SHEET_SCALE) or SHEET_SCALE)
   if scale < 1:
      raise UsageError(f"--scale 은 1 이상이다 : {scale}")
   inputs = list_inputs(args.in_dir)
   plan = _plan(inputs, colors, args.out_dir)
   writes = [path for row in plan for path in row]
   sheet_path = jailed_output(args.sheet) if getattr(args, "sheet", None) else None
   if sheet_path is not None:
      guard_overwrite([sheet_path], writes, "--sheet")
   # 아무것도 쓰기 전에 : 원본을 덮지 않고, 입력 폴더 안에도 안 쓴다(다음 판에 결과를 또 읽는다)
   guard_overwrite([*writes, sheet_path], inputs)
   if Path(args.in_dir).is_dir():
      guard_outside([*writes, sheet_path], [args.in_dir])

   rows, warnings, board = [], [], []
   for source, targets in zip(inputs, plan):
      arr = image.load(source)
      made = [tint(arr, rgb) for rgb in colors]
      for path, result in zip(targets, made):
         image.save(path, result)
      luma = mean_luma(arr)
      if luma is not None and luma < DARK_SOURCE:
         warnings.append(warning("tint.dark_source", f"{source.name} : 평균 밝기 {luma:.0f} < {DARK_SOURCE} — 곱하면 탁해진다. 흰 · 밝은 회색으로 뽑는다", [source.name]))
      rows.append({"file": source.name, "outputs": [p.name for p in targets], "mean_luma": None if luma is None else round(luma, 1)})
      board.append([arr, *made])

   if sheet_path is not None:
      cells = [cell for row in board for cell in row]
      image.save(sheet_path, image.contact_sheet(cells, scale, cols=len(colors) + 1))

   return {
      "version": VERSION,
      "status": "warn" if warnings else "ok",
      "colors": [to_hex(c) for c in colors],
      "images": rows,
      "sheet": str(sheet_path) if sheet_path else None,
      "warnings": warnings,
      "out": str(resolve_root(args.out_dir)),
   }
