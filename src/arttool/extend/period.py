"""`extend period` — 띠에서 되풀이 단위 찾기 · 타일 크기에 맞추기 (피드백 후속 설계 3-5, R4).

찾기 : `--axis x` 면 열(세로 줄) 하나를 RGBA 벡터 하나로 본다. 간격 p 마다 d(p) = 열 i 와 i+p 의 평균 차.
점수 = d(p) ÷ (p/2 ~ p-1 간격의 d 평균) — 되풀이면 d 가 p 에서 움푹 꺼진다.
가장 낮은 점수 근처(`NEAR_RATIO` 배 또는 `NEAR_ADD` 더한 값 안)에서 **가장 작은 p** 를 고른다 —
배수(2p · 3p)도 점수가 낮아서, 가장 낮은 것만 고르면 두 단위를 한 단위로 잘못 고른다.

맞추기 : 한 단위를 자르고 열을 겹쳐 넣거나 빼서 폭을 맞춘다. 고르는 열은 「앞 열과 차가 작고, 같은 열이 길게 이어진 자리」다
(난간 한가운데). 기둥 같은 굵은 선은 안 건드린다. 보간은 없다.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .. import image
from ..checks import warning
from ..edit import dry_run_fields, is_dry_run
from ..errors import ArtToolError, UsageError
from ..paths import guard_overwrite, jailed_output

VERSION = 1
AXES = ("x", "y")
MIN_PERIOD = 4
NEAR_RATIO = 1.1      # 가장 낮은 점수의 이 배 안이면 같은 후보로 본다
NEAR_ADD = 0.05       # 가장 낮은 점수가 0 에 가까울 때도 후보 폭이 0 이 안 되게 더하는 값
WEAK_SCORE = 0.35     # 고른 점수가 이보다 크면 「되풀이가 약하다」
FIT_RANGE = 0.25      # 맞출 폭이 단위의 ±25% 밖이면 그림이 일그러진다


def lines_of(arr: image.RGBA, axis: str) -> np.ndarray:
   """되풀이 방향이 0번 축이 되게 돌린 그림 (길이, 줄 길이, 4)."""
   if axis == "x":
      return arr.transpose(1, 0, 2)
   return arr


def score_periods(lines: np.ndarray) -> dict[int, float]:
   """간격 p → 점수 = d(p) ÷ d(p/2 ~ p-1) 평균. p 범위는 MIN_PERIOD ~ 길이/2. 범위가 비었거나 띠가 고르면 빈 dict.

   분모를 「모든 p 의 평균」으로 하면 매끈한 그림은 작은 p 일수록 d 가 작아 아무 그림에서나 p=4 를 0.3 안팎으로 골랐다.
   바로 앞 간격들과 견주면 「d 가 움푹 꺼진 자리」만 1 아래로 내려간다.
   """
   length = lines.shape[0]
   flat = lines.reshape(length, -1).astype(np.float64)
   gaps = {p: float(np.mean(np.abs(flat[p:] - flat[:-p]))) for p in range(1, length // 2 + 1)}
   scores = {}
   for p in range(MIN_PERIOD, length // 2 + 1):
      base = sum(gaps[q] for q in range((p + 1) // 2, p)) / (p - (p + 1) // 2)
      if base > 0:
         scores[p] = gaps[p] / base
   return scores


def pick_period(scores: dict[int, float]) -> int | None:
   if not scores:
      return None
   best = min(scores.values())
   limit = max(best * NEAR_RATIO, best + NEAR_ADD)
   return min(p for p, s in scores.items() if s <= limit)


def line_gaps(lines: np.ndarray) -> np.ndarray:
   """줄 i 와 앞 줄 i-1 의 평균 차. 0번 줄은 비교할 앞 줄이 없어 무한대."""
   flat = lines.reshape(lines.shape[0], -1).astype(np.float64)
   gaps = np.full(lines.shape[0], np.inf)
   gaps[1:] = np.mean(np.abs(flat[1:] - flat[:-1]), axis=1)
   return gaps


def cut_start(lines: np.ndarray, period: int) -> int:
   """한 단위를 자를 첫 줄. 앞 줄과 차가 가장 작은 줄(기둥 한가운데를 안 자르게). 같으면 앞쪽."""
   gaps = line_gaps(lines)
   last = lines.shape[0] - period
   return int(np.argmin(gaps[1 : last + 1])) + 1


def _run_lengths(same: np.ndarray) -> np.ndarray:
   """same[j] = 줄 j 가 앞 줄(고리처럼 이어 붙인)과 같은가. 줄마다 그 줄이 든 「같은 줄이 이어진 덩이」의 길이."""
   count = same.size
   if np.all(same):
      return np.full(count, count)
   start = int(np.argmin(same))          # 덩이가 시작하는 줄 하나에서 돌기 시작한다
   lengths = np.zeros(count, dtype=np.int64)
   members: list[int] = []
   for step in range(count + 1):
      j = (start + step) % count
      if step == count or not same[j]:
         for m in members:
            lengths[m] = len(members)
         members = []
      if step < count:
         members.append(j)
   return lengths


def fit_unit(unit: np.ndarray, target: int) -> tuple[np.ndarray, list[int], list[int]]:
   """unit 의 줄 수를 target 에 맞춘다. (결과, 뺀 줄, 겹친 줄) — 줄 번호는 unit 안의 번호."""
   count = unit.shape[0]
   flat = unit.reshape(count, -1).astype(np.float64)
   gaps = np.mean(np.abs(flat - np.roll(flat, 1, axis=0)), axis=1)   # 단위는 이어 붙으므로 0번 줄의 앞은 마지막 줄
   runs = _run_lengths(gaps == 0)
   order = sorted(range(count), key=lambda j: (gaps[j], -runs[j], j))
   picked = sorted(order[: abs(target - count)])
   if target < count:
      keep = [j for j in range(count) if j not in picked]
      return unit[keep], picked, []
   rows = []
   for j in range(count):
      rows.append(j)
      if j in picked:
         rows.append(j)
   return unit[rows], [], picked


def _target_width(period: int, fit: int | None, tile: int | None) -> int:
   if fit is not None:
      return fit
   if tile is not None:
      return max(tile, round(period / tile) * tile)
   return period


def run(args) -> dict:
   axis = str(args.axis)
   if axis not in AXES:
      raise UsageError(f"--axis 는 x 또는 y 다 : {axis}")
   tile = args.tile
   fit = args.fit
   if tile is not None and int(tile) < 1:
      raise UsageError(f"--tile 은 1 이상이다 : {tile}")
   if fit is not None and int(fit) < 1:
      raise UsageError(f"--fit 은 1 이상이다 : {fit}")

   source = Path(args.in_file)
   out_file = jailed_output(args.out_file) if args.out_file else None
   guard_overwrite([out_file], [source])
   arr = image.load(source)
   lines = lines_of(arr, axis)
   length = lines.shape[0]

   scores = score_periods(lines)
   period = pick_period(scores)
   warnings = []
   dry_run = is_dry_run(args)
   report = {
      "version": VERSION,
      **dry_run_fields(dry_run, [out_file]),
      "in": str(source),
      "axis": axis,
      "length": length,
      "period": period,
      "score": None,
      "tile": tile,
      "out": None,
   }
   if period is None:
      warnings.append(warning("period.not_found",
                              f"되풀이 단위를 못 찾았다 (길이 {length} 가 짧거나 줄이 다 같다 — 단위 {MIN_PERIOD} 이상이 두 번 들어가야 한다)",
                              []))
      if out_file is not None:
         raise ArtToolError(f"되풀이 단위를 못 찾아 자를 것이 없다 : {source}")
      return {**report, "status": "warn", "warnings": warnings}

   score = round(scores[period], 4)
   report["score"] = score
   if score > WEAK_SCORE:
      warnings.append(warning("period.weak",
                              f"되풀이가 약하다 (점수 {score} > {WEAK_SCORE}). 단위 {period} 를 눈으로 확인한다",
                              [period]))
   if tile is not None and period % int(tile) != 0:
      low = (period // int(tile)) * int(tile)
      near = [m for m in (low, low + int(tile)) if m > 0]
      warnings.append(warning("period.not_multiple",
                              f"단위 {period} 가 타일 {tile} 의 배수가 아니다. 가까운 배수 : {', '.join(map(str, near))}",
                              near))

   if out_file is not None:
      target = _target_width(period, fit, None if tile is None else int(tile))
      if abs(target - period) > period * FIT_RANGE:
         raise UsageError(f"맞출 폭 {target} 이 단위 {period} 의 ±{int(FIT_RANGE * 100)}% 밖이다 — 그림이 일그러진다. --fit 으로 가까운 폭을 준다")
      start = cut_start(lines, period)
      fitted, removed, duplicated = fit_unit(lines[start : start + period], target)
      out = fitted.transpose(1, 0, 2) if axis == "x" else fitted
      if not dry_run:
         image.save(out_file, np.ascontiguousarray(out))
      report.update({
         "out": None if dry_run else str(out_file),
         "cut_at": start,
         "width": target,
         "removed": [start + j for j in removed],
         "duplicated": [start + j for j in duplicated],
      })

   return {**report, "status": "warn" if warnings else "ok", "warnings": warnings}
