"""`mask --from-shape` — `measure shape` 로 잰 원으로 흰 가림판을 만든다 (2026-10-06 2판 설계 C8).

`layers mask` 는 「이 색 칸만」 이라 다르다. 여기는 보고 JSON 의 `shape.center` · `shape.r` 로 원을 그린다.
칸 중심 (x+0.5, y+0.5) 이 원 안(거리 ≤ r)이면 흰색 불투명, 아니면 투명. `--invert` 면 거꾸로.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from .. import image
from ..checks import warning
from ..errors import UsageError
from ..paths import guard_not_folder, guard_overwrite, jailed_output
from . import dry_run_fields, is_dry_run

VERSION = 1
WHITE = (255, 255, 255, 255)


def _shape(path: str) -> dict:
   try:
      data = json.loads(Path(path).read_text(encoding="utf-8"))
   except (OSError, ValueError) as error:
      raise UsageError(f"--from-shape 를 못 읽는다 : {path} ({error})") from None
   shape = data.get("shape") if isinstance(data, dict) else None
   if not isinstance(shape, dict) or "center" not in shape or "r" not in shape:
      raise UsageError(f"--from-shape 에 shape(center · r) 가 없다 — measure shape 보고인지 본다 : {path}")
   return shape


def _positive(value, name: str) -> float:
   try:
      number = float(value)
   except (TypeError, ValueError):
      raise UsageError(f"{name} 가 숫자가 아니다 : {value}") from None
   if not math.isfinite(number) or number <= 0:
      raise UsageError(f"{name} 는 0 보다 큰 유한한 수다 : {value}")
   return number


def _radius(shape: dict, how: str) -> float:
   if how == "round":
      # Python round 는 짝수 쪽(2.5 → 2)이라 반 올림을 손으로 한다 (2.5 → 3).
      r = math.floor(_positive(shape["r"], "shape.r") + 0.5)
      return _positive(r, "반올림한 shape.r")
   if how == "max":
      if "r_max" not in shape:
         raise UsageError("--r max 인데 shape 에 r_max 가 없다")
      return _positive(shape["r_max"], "shape.r_max")
   return _positive(how, "--r")


def _size(args) -> tuple[int, int]:
   size, like = getattr(args, "size", None), getattr(args, "like", None)
   if (size is None) == (like is None):
      raise UsageError("--size 와 --like 가운데 하나만 준다")
   if like is not None:
      arr = image.load(like)
      return arr.shape[1], arr.shape[0]
   parts = str(size).split(",")
   try:
      width, height = (int(p.strip()) for p in parts)
   except ValueError:
      raise UsageError(f"--size 는 w,h 정수 둘이다 : {size}") from None
   if width <= 0 or height <= 0:
      raise UsageError(f"--size 는 둘 다 1 이상이다 : {size}")
   return width, height


def run(args) -> dict:
   shape = _shape(args.from_shape)
   center = shape["center"]
   if not isinstance(center, (list, tuple)) or len(center) != 2:
      raise UsageError(f"shape.center 는 [x, y] 다 : {center}")
   try:
      cx, cy = (float(v) for v in center)
   except (TypeError, ValueError):
      raise UsageError(f"shape.center 가 숫자가 아니다 : {center}") from None
   if not (math.isfinite(cx) and math.isfinite(cy)):
      raise UsageError(f"shape.center 가 유한한 수가 아니다 : {center}")
   r = _radius(shape, str(getattr(args, "r", "round")))
   width, height = _size(args)
   image.check_pixels(width, height, "가림판")
   out = guard_not_folder(jailed_output(args.out_file))
   guard_overwrite([out], [args.from_shape, getattr(args, "like", None)])

   # 칸 중심 거리로 한 번에 셈한다 — ogrid 라 줄·칸 한 벌씩만 만들고 브로드캐스트한다.
   ys, xs = np.ogrid[0:height, 0:width]
   inside = (xs + 0.5 - cx) ** 2 + (ys + 0.5 - cy) ** 2 <= r * r
   white = ~inside if getattr(args, "invert", False) else inside
   arr = np.zeros((height, width, 4), dtype=np.uint8)
   arr[white] = WHITE

   warnings = []
   if cx - r < 0 or cy - r < 0 or cx + r > width or cy + r > height:
      warnings.append(warning("mask.clipped", f"원(중심 {cx},{cy} · r {r})이 캔버스 {width}x{height} 를 벗어난다",
                              [cx, cy, r]))
   dry_run = is_dry_run(args)
   if not dry_run:
      image.save(out, arr)
   return {
      **dry_run_fields(dry_run, [out]),
      "version": VERSION,
      "status": "warn" if warnings else "ok",
      "center": [cx, cy],
      "r": r,
      "size": [width, height],
      "invert": bool(getattr(args, "invert", False)),
      "white": int(np.count_nonzero(white)),
      "images": [{"file": out.name, "out": None if dry_run else str(out)}],
      "warnings": warnings,
      "out": None if dry_run else str(out),
   }
