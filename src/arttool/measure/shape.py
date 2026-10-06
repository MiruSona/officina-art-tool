"""`measure shape` — 덩이 하나의 자리 · 크기 · 원다움을 잰다 (2026-10-06 2판 설계 C7).

합성 창(둥근 유리 등) 자리를 손으로 세던 일을 대신한다. `--at x,y` 면 그 칸과 같은 색으로 4방향 이어진 덩이,
`--color` 면 그 색(±`--tol`) 칸 덩이 가운데 가장 큰 것을 잰다. 좌표는 칸 중심이 (x+0.5, y+0.5) 인 연속 좌표다 —
`mask --from-shape` 가 같은 좌표로 원을 다시 그려 칸이 맞는다. 파일은 안 쓴다(`--report` 는 cli 가 쓴다).
"""

from __future__ import annotations

import math

import numpy as np

from .. import image
from ..checks import warning
from ..edit.cutout import flood
from ..edit.fill import parse_color, regions
from ..errors import UsageError

VERSION = 1
ROUND_MIN = 0.85     # 원다움이 이보다 낮으면 원이 아닐 수 있다고 알린다


def parse_point(text: str | None, name: str = "--at") -> tuple[int, int]:
   """`x,y` → (x, y). 정수 둘이 아니면 UsageError."""
   parts = str(text).split(",")
   try:
      x, y = (int(p.strip()) for p in parts)
   except ValueError:
      raise UsageError(f"{name} 는 x,y 정수 둘이다 : {text}") from None
   return x, y


def _tol(args) -> int:
   tol = getattr(args, "tol", 0)
   if tol is None:
      return 0
   if tol < 0:
      raise UsageError(f"--tol 은 0 이상이다 : {tol}")
   return int(tol)


def _near(arr: image.RGBA, rgb, tol: int) -> np.ndarray:
   """불투명(알파>0)이고 RGB 각 칸 차이의 최댓값이 tol 이하인 칸."""
   diff = np.abs(arr[:, :, :3].astype(np.int16) - np.array(rgb[:3], dtype=np.int16)).max(axis=2)
   return (arr[:, :, 3] > 0) & (diff <= tol)


def _pick(arr: image.RGBA, args) -> np.ndarray | None:
   """잴 덩이의 불리언 판. 고를 덩이가 없으면 None."""
   at, color = getattr(args, "at", None), getattr(args, "color", None)
   if (at is None) == (color is None):
      raise UsageError("--at 과 --color 가운데 하나만 준다")
   tol = _tol(args)
   if at is not None:
      x, y = parse_point(at)
      height, width = arr.shape[:2]
      if not (0 <= x < width and 0 <= y < height):
         raise UsageError(f"--at {x},{y} 가 그림({width}x{height}) 밖이다")
      if arr[y, x, 3] == 0:
         raise UsageError(f"--at {x},{y} 칸이 투명하다 — 잴 덩이 안의 칸을 준다")
      start = np.zeros(arr.shape[:2], dtype=bool)
      start[y, x] = True
      return flood(start, _near(arr, arr[y, x], tol))
   found = regions(_near(arr, parse_color(color), tol))
   if not found:
      return None
   # 큰 덩이부터, 같으면 먼저 만난 것(위 → 아래, 왼 → 오른) — 결과가 늘 같다.
   cells = max(found, key=len)
   mask = np.zeros(arr.shape[:2], dtype=bool)
   xs, ys = zip(*cells)
   mask[list(ys), list(xs)] = True
   return mask


def measure(mask: np.ndarray) -> dict:
   """덩이 판 → {center, r, r_max, area, box, roundness}. 칸 수에 비례하는 numpy 셈."""
   ys, xs = np.nonzero(mask)
   area = int(len(xs))
   # 중심을 먼저 둘째 자리로 반올림하고 그 중심으로 잰다 — 보고에 실린 중심과 r_max 가 짝이 맞아야
   # `mask --from-shape --r max` 가 가장 먼 칸을 빠뜨리지 않는다 (반올림 전 중심으로 재면 900개 중 86개에서 빠졌다).
   cx, cy = round(float(xs.mean()) + 0.5, 2), round(float(ys.mean()) + 0.5, 2)
   r = math.sqrt(area / math.pi)
   # 가장 먼 칸은 늘 둘레 칸이라 전체 칸에서 최댓값을 봐도 같다.
   far = float(((xs + 0.5 - cx) ** 2 + (ys + 0.5 - cy) ** 2).max())
   r_max = math.sqrt(far)
   # 올림으로 적는다 — 내림이면 `mask --r max` 가 가장 먼 칸을 빠뜨린다 (5.8309 → 5.83 이면 그 칸이 원 밖).
   # 가장 먼 칸이 원 위에 딱 걸리면 부동소수 끝자리로 r_max² < 거리² 가 될 수 있어(6.1 × 6.1 < 37.21) 한 눈금 더 올린다.
   r_max_up = math.ceil(r_max * 100) / 100
   while r_max_up * r_max_up < far:
      r_max_up = round(r_max_up + 0.01, 2)
   return {
      "center": [cx, cy],
      "r": round(r, 2),
      "r_max": r_max_up,
      "area": area,
      "box": [int(xs.min()), int(ys.min()), int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)],
      # 한 칸짜리는 r_max 가 0 이다 — 나눌 수 없어 원으로 친다.
      "roundness": round(r / r_max, 2) if r_max > 0 else 1.0,
   }


def run(args) -> dict:
   arr = image.load(args.in_path)
   mask = _pick(arr, args)
   warnings = []
   if mask is None:
      warnings.append(warning("measure.none", f"{args.color} 색(±{_tol(args)}) 칸이 없다 — 잰 것이 없다", []))
      shape = None
   else:
      shape = measure(mask)
      if shape["roundness"] < ROUND_MIN:
         warnings.append(warning("measure.not_round",
                                 f"원다움 {shape['roundness']} < {ROUND_MIN} — 원이 아닐 수 있다 (mask --from-shape 가 어긋난다)",
                                 [shape["roundness"]]))
   return {
      "version": VERSION,
      "status": "fail" if shape is None else ("warn" if warnings else "ok"),
      "in": str(args.in_path),
      "shape": shape,
      "warnings": warnings,
      "out": None,
   }
