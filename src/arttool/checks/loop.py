"""⑦ loop_seam — 애니 루프 이음새 (설계 7-2 ⑦).

이웃 프레임 차이 dᵢ 와 마지막 → 첫 차이 d_loop 를 견준다. 차이 셈은 `tile seam` 과 같다(칸마다 RGBA 네 칸 차이 합).
"""

from __future__ import annotations

import re

import numpy as np

from . import norm_rgba

MIN_FRAMES = 3
# 낱장 이름 <anim>_<방향>_<번호>.png
LOOSE_NAME = re.compile(r"^(?P<anim>.+)_(?P<dir>[^_]+)_(?P<num>\d+)$")


def frame_diff(a: np.ndarray, b: np.ndarray) -> float | None:
   """두 프레임의 칸 평균 차이 (0 ~ 1020). 크기가 다르면 견줄 수 없어 None."""
   if a.shape != b.shape:
      return None
   return float(np.abs(norm_rgba(a) - norm_rgba(b)).sum(axis=-1).mean())


def measure_loop(frames: list[np.ndarray]) -> dict | None:
   """한 줄(같은 anim · 방향)의 루프 재기. 3장 미만이거나 크기가 섞였으면 None.

   돌려주는 것 : {diffs [d₁ …] (이웃 프레임), loop (마지막 → 첫), median (diffs 중앙값), frames (장 수)}
   """
   if len(frames) < MIN_FRAMES:
      return None
   diffs = [frame_diff(a, b) for a, b in zip(frames, frames[1:])]
   loop = frame_diff(frames[-1], frames[0])
   if loop is None or any(d is None for d in diffs):
      return None
   return {
      "diffs": [round(d, 3) for d in diffs],
      "loop": round(loop, 3),
      "median": round(float(np.median(diffs)), 3),
      "frames": len(frames),
   }


def judge_loop(m: dict, k: float) -> list[str]:
   if m["loop"] == 0:
      return ["마지막 장이 첫 장과 같다 (한 박자 멈춤)"]
   if m["loop"] > float(k) * m["median"]:
      return [f"이음새가 튄다 — 마지막 → 첫 차이 {m['loop']:.1f} > {k} × 중앙값 {m['median']:.1f}"]
   return []


def group_loose(names: list[str]) -> dict[tuple[str, str], list[tuple[int, str]]]:
   """낱장 이름을 (anim, 방향) 줄로 묶는다. 값은 (번호, 이름) 을 번호 순으로. 꼴이 안 맞는 이름은 뺀다."""
   groups: dict[tuple[str, str], list[tuple[int, str]]] = {}
   for name in names:
      stem = name.rsplit(".", 1)[0]
      hit = LOOSE_NAME.match(stem)
      if hit:
         groups.setdefault((hit["anim"], hit["dir"]), []).append((int(hit["num"]), name))
   return {key: sorted(items) for key, items in sorted(groups.items())}
