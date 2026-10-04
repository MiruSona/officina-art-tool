"""`bands` — 흰 띠 · 몰딩 줄 찾기 (피드백 후속 설계 3-2).

- `blank` : 가장자리에서 이어지는 빈 줄 띠. 빈 줄 = 칸의 95% 이상이 흰색(세 값 모두 240 이상) 또는 투명.
- `lines` : 앞 줄과의 평균 색 차 `delta` × 줄 안 최다 색 비율 `uniform` 이 큰 줄 상위 `--top` 개.
  몰딩 · 걸레받이 · 널 이음 줄은 둘 다 높다. 흰 띠 안과 그 경계 줄은 후보에서 뺀다.

`--axis x` 는 그림을 눕혀(전치) 같은 셈을 한다. 줄 번호 열쇠만 `y` 대신 `x` 다.
`line_delta` 는 `stitch` 의 이음 차도 같이 쓴다.
"""

from __future__ import annotations

import numpy as np

from .. import image
from ..checks import warning
from ..errors import UsageError
from ..paths import guard_overwrite, jailed_output

VERSION = 1
WHITE_MIN = 240          # 세 값 모두 이 이상이면 흰색
BLANK_SHARE = 0.95       # 줄의 이 몫 이상이 흰색 · 투명이면 빈 줄
LINE_MIN_DELTA = 8.0     # 앞 줄과 평균 차가 이보다 작으면 줄 후보로 안 본다 (잔잔한 그러데이션 거르기)
AXES = ("x", "y")

MARK_SCALE = 2
MARK_RED = (255, 0, 0, 255)
MARK_BLUE = (40, 120, 255, 255)
MARK_PAD = 4


def _norm(arr: image.RGBA) -> np.ndarray:
   """투명 칸은 RGB 찌꺼기를 지워 0 으로. 차이 셈이 넘치지 않게 int32."""
   out = arr.astype(np.int32)
   out[arr[..., 3] == 0] = 0
   return out


def line_delta(a: np.ndarray, b: np.ndarray) -> float:
   """두 줄(같은 길이의 RGBA 칸 줄)의 평균 색 차. 칸마다 RGBA 네 칸 차의 평균을 내고 그것을 다시 평균한다 (0~255)."""
   na, nb = _norm(a), _norm(b)
   return float(np.abs(na - nb).mean())


def _blank_rows(arr: image.RGBA) -> np.ndarray:
   clear = arr[:, :, 3] == 0
   white = np.all(arr[:, :, :3] >= WHITE_MIN, axis=-1)
   return (clear | white).mean(axis=1) >= BLANK_SHARE


def _uniform(row: np.ndarray) -> float:
   """줄 안 최다 색 비율. 투명 칸은 한 색으로 센다."""
   norm = _norm(row)
   keys = (norm[:, 0] << 24) | (norm[:, 1] << 16) | (norm[:, 2] << 8) | norm[:, 3]
   _, counts = np.unique(keys, return_counts=True)
   return float(counts.max() / len(keys))


def find_blank(arr: image.RGBA) -> tuple[list[int] | None, list[int] | None]:
   """처음 · 끝 빈 띠 `[시작, 끝)`. 없으면 None. 그림 전체가 비었으면 처음 띠 하나로 본다."""
   blank = _blank_rows(arr)
   length = len(blank)
   lead = length if blank.all() else int(np.argmin(blank))
   if lead == length:
      return [0, length], None
   tail = int(np.argmin(blank[::-1]))
   start = [0, lead] if lead else None
   end = [length - tail, length] if tail else None
   return start, end


def find_lines(arr: image.RGBA, start, end, top: int) -> list[dict]:
   """흰 띠 밖 줄 가운데 점수 상위 top 개. 띠 경계 줄(앞 줄이 띠 안)도 뺀다."""
   lo = start[1] if start else 0
   hi = end[0] if end else arr.shape[0]
   rows = []
   for y in range(lo + 1, hi):
      delta = line_delta(arr[y - 1], arr[y])
      if delta < LINE_MIN_DELTA:
         continue
      uniform = _uniform(arr[y])
      rows.append({"at": y, "delta": round(delta, 2), "uniform": round(uniform, 3), "score": round(delta * uniform, 2)})
   rows.sort(key=lambda r: (-r["score"], r["at"]))
   return rows[:top]


def _mark(arr: image.RGBA, axis: str, start, end, lines: list[dict]) -> image.RGBA:
   """원본 ×2 에 왼쪽(axis x 면 위쪽) 여백을 붙여 줄마다 빨간 눈금과 번호, 흰 띠 경계는 파란 눈금."""
   big = image.scale_up(arr, MARK_SCALE)
   length = arr.shape[0] if axis == "y" else arr.shape[1]
   has_font = image.has_label_font()
   label_w = image.label_width(str(length)) if has_font else 0
   margin = label_w + MARK_PAD * 3 if axis == "y" else image.LABEL_PX + MARK_PAD * 3
   h, w = big.shape[0], big.shape[1]
   out_w, out_h = (w + margin, h) if axis == "y" else (w, h + margin)
   image.check_pixels(out_w, out_h, "눈금 그림")
   canvas = image.new(out_w, out_h, (24, 24, 24, 255))
   ox, oy = (margin, 0) if axis == "y" else (0, margin)
   canvas[oy:oy + h, ox:ox + w] = big

   ticks = [(edge, MARK_BLUE) for band in (start, end) if band for edge in band if 0 < edge < length]
   ticks += [(row["at"], MARK_RED) for row in lines]
   for at, color in ticks:
      pos = at * MARK_SCALE
      if axis == "y":
         canvas[pos, :margin] = color
         canvas[pos, margin:] = color
      else:
         canvas[:margin, pos] = color
         canvas[margin:, pos] = color
   if not has_font:
      return canvas
   for row in lines:
      pos = row["at"] * MARK_SCALE
      if axis == "y":
         image.draw_label(canvas, str(row["at"]), MARK_PAD, max(pos - image.LABEL_PX - 1, 0), color=MARK_RED)
      else:
         image.draw_label(canvas, str(row["at"]), pos + 2, MARK_PAD, color=MARK_RED)
   return canvas


def run(args) -> dict:
   axis = str(getattr(args, "axis", "y"))
   if axis not in AXES:
      raise UsageError(f"--axis 는 x 또는 y 다 : {axis}")
   top = int(getattr(args, "top", 8))
   if top < 1:
      raise UsageError(f"--top 은 1 이상이다 : {top}")
   mark_arg = getattr(args, "mark", None)
   mark = jailed_output(mark_arg) if mark_arg else None
   guard_overwrite([mark], [args.in_file], "--mark")

   arr = image.load(args.in_file)
   work = arr if axis == "y" else arr.transpose(1, 0, 2)
   start, end = find_blank(work)
   lines = find_lines(work, start, end, top)
   for row in lines:
      row[axis] = row.pop("at")

   warnings = []
   if start is None and end is None and not lines:
      warnings.append(warning("bands.none", "그림이 고르다 — 흰 띠도 이을 자리도 안 보인다"))
   if mark is not None:
      ticked = [{"at": row[axis]} for row in lines]
      image.save(mark, _mark(arr, axis, start, end, ticked))

   return {
      "version": VERSION,
      "status": "warn" if warnings else "ok",
      "axis": axis,
      "size": list(image.size(arr)),
      "blank": {"start": start, "end": end},
      "lines": [{axis: row[axis], "delta": row["delta"], "uniform": row["uniform"], "score": row["score"]} for row in lines],
      "mark": str(mark) if mark else None,
      "warnings": warnings,
   }
