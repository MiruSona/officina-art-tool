"""`fill --enclosed` — 틀에 갇힌 투명 칸 채우기 (2026-10-06 2판 설계 C2).

투명(alpha 0) 칸 중 그림 테두리에서 4이웃으로 닿지 않는 칸 = 갇힌 칸. 덩이(4이웃)별로 나눠 `--max-area` 로 거른 뒤 한 색으로 칠한다.
4이웃으로 퍼지므로 대각선으로만 이어진 1px 선도 막힌 틀로 본다 (도트 외곽선은 대개 8이웃 선이다).
"""

from __future__ import annotations

from collections import deque
from pathlib import Path

import numpy as np

from .. import image
from ..checks import warning
from ..errors import UsageError
from ..paths import guard_outside
from . import dry_run_fields, is_dry_run, list_inputs, plan_outputs
from .cutout import flood

VERSION = 1
# 한 덩이가 그림 넓이의 이 몫을 넘으면 일부러 뚫은 창일 수 있다.
LARGE_SHARE = 0.25


def parse_color(text: str) -> tuple[int, int, int, int]:
   value = (text or "").strip()
   if not value.startswith("#") or len(value) not in (7, 9):
      raise UsageError(f"--color 는 #rrggbb 또는 #rrggbbaa 다 : {text}")
   try:
      parts = [int(value[i:i + 2], 16) for i in range(1, len(value), 2)]
   except ValueError as exc:
      raise UsageError(f"--color 를 못 읽었다 : {text}") from exc
   if len(parts) == 4 and parts[3] == 0:
      # 알파 0 으로 채우면 갇힌 칸이 그대로 투명이다 — 바꾼 게 없는데 채웠다고 보고하게 된다.
      raise UsageError(f"--color 의 알파가 0 이면 채워도 투명 그대로다 : {text}")
   return tuple(parts + [255])[:4]


def _max_area(args) -> int | None:
   value = getattr(args, "max_area", None)
   if value is None:
      return None
   if not isinstance(value, int) or isinstance(value, bool) or value < 1:
      raise UsageError(f"--max-area 는 1 이상 정수다 : {value}")
   return value


def enclosed(arr: image.RGBA) -> np.ndarray:
   """테두리에서 투명 칸만 따라 못 닿는 투명 칸."""
   clear = arr[:, :, 3] == 0
   start = np.zeros_like(clear)
   start[0, :] = start[-1, :] = True
   start[:, 0] = start[:, -1] = True
   return clear & ~flood(start, clear)


def regions(mask: np.ndarray) -> list[list[tuple[int, int]]]:
   """4이웃 덩이별 칸 목록. 각 칸을 한 번씩만 보므로 칸 수에 비례한다."""
   seen = np.zeros_like(mask)
   height, width = mask.shape
   out = []
   for y0, x0 in zip(*np.nonzero(mask)):
      if seen[y0, x0]:
         continue
      seen[y0, x0] = True
      cells, queue = [], deque([(int(x0), int(y0))])
      while queue:
         x, y = queue.popleft()
         cells.append((x, y))
         for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < width and 0 <= ny < height and mask[ny, nx] and not seen[ny, nx]:
               seen[ny, nx] = True
               queue.append((nx, ny))
      out.append(cells)
   return out


def _box(cells) -> list[int]:
   xs, ys = [c[0] for c in cells], [c[1] for c in cells]
   return [min(xs), min(ys), max(xs) - min(xs) + 1, max(ys) - min(ys) + 1]


def run(args) -> dict:
   if not getattr(args, "enclosed", False):
      raise UsageError("지금은 --enclosed 방식뿐이다 — --enclosed 를 준다")
   color = parse_color(getattr(args, "color", None))
   max_area = _max_area(args)
   inputs = list_inputs(args.in_dir)
   outs = plan_outputs(inputs, args.in_dir, args.out_dir)
   if Path(args.in_dir).is_dir():
      guard_outside(outs, [args.in_dir])

   dry_run = is_dry_run(args)
   rows, none, large, skipped = [], [], [], []
   for source, target in zip(inputs, outs):
      arr = image.load(source)
      found = regions(enclosed(arr))
      out = arr.copy()
      filled, kept = 0, []
      for cells in found:
         if max_area is not None and len(cells) > max_area:
            skipped.append({"where": source.name, "area": len(cells), "box": _box(cells)})
            continue
         xs = np.fromiter((c[0] for c in cells), dtype=np.intp, count=len(cells))
         ys = np.fromiter((c[1] for c in cells), dtype=np.intp, count=len(cells))
         out[ys, xs] = color
         filled += len(cells)
         kept.append({"area": len(cells), "box": _box(cells)})
         if len(cells) > LARGE_SHARE * arr.shape[0] * arr.shape[1] and source.name not in large:
            large.append(source.name)       # 큰 덩이가 여럿이어도 파일 이름은 한 번만
      if not found:
         none.append(source.name)
      if not dry_run:
         image.save(target, out)
      rows.append({"file": source.name, "out": None if dry_run else str(target), "filled": filled, "regions": kept})

   warnings = []
   if none:
      warnings.append(warning("fill.none", f"갇힌 투명 칸이 없다 — 틀이 열려 있을 수 있다 : {', '.join(none)}", none))
   if large:
      warnings.append(warning("fill.large", f"그림 넓이의 {int(LARGE_SHARE * 100)}% 넘는 덩이를 채웠다 — 창일 수 있다 : {', '.join(large)}", large))
   if skipped:
      warnings.append(warning("fill.skipped", f"--max-area 보다 커서 건너뛴 덩이 {len(skipped)}개", skipped))
   return {
      **dry_run_fields(dry_run, outs),
      "version": VERSION,
      "status": "warn" if warnings else "ok",
      "enclosed": True,
      "color": "#" + "".join(f"{c:02x}" for c in color),
      "max_area": max_area,
      "images": rows,
      "warnings": warnings,
      "out": str(Path(outs[0]).parent),
   }
