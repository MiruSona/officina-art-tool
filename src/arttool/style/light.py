"""화풍 뽑기 ③ 빛 방향 어림 (설계 9-3 ③, 실물 #4 로 고침).

**같은 색 램프 안에서만** 밝은 칸과 어두운 칸의 자리를 견준다.
그림 한 장의 색을 팔레트 뽑기와 같은 방법(맞닿음 + 색조)으로 램프 덩어리로 묶고, 덩어리마다
「(밝기 − 그 덩어리 평균 밝기) 무게」 의 무게중심이 그 덩어리 무게중심에서 어느 쪽으로 치우쳤나를 더한다.

옛 셈은 그림 전체 밝기 평균과 견줘, 평면 아이콘(위는 어두운 색 · 아래는 밝은 색 같은 서로 다른 부분)을
「빛이 아래」 로 읽었다. 한 색으로 칠한 부분은 덩어리 안에 밝기 차가 없으니 이제 아무것도 안 민다.
검정 · 거의 검정(외곽선)은 뺀다.
"""

from __future__ import annotations

import math

import numpy as np

from ..checks import long_side, luma, opaque
from . import ramps

MIN_SHIFT = 0.05        # 치우침이 그림 크기(불투명 bbox 긴 변)의 이 몫 미만이면 「모름」
TOP_RIGHT_MAX = 60.0    # 위쪽 반원의 각도(0 = 오른쪽, 90 = 위, 180 = 왼쪽)로 셋을 가른다
TOP_MAX = 120.0

UNKNOWN = "unknown"
BOTTOM = "bottom"


def _group_ids(keys: np.ndarray) -> np.ndarray | None:
   """칸마다 램프 덩어리 번호. 빼는 칸(투명 · 검정)은 -1. 색이 둘 미만이면 None."""
   stats = ramps.stats_of(keys)
   pixels = dict(zip(stats["colors"].tolist(), stats["counts"].tolist()))
   keep = {k for k in pixels if not ramps.is_black(k)}
   if len(keep) < 2:
      return None
   groups = ramps.group_colors(keep, ramps.touching_pairs([stats], keep), pixels)
   table = {k: gid for gid, group in enumerate(groups) for k in group}
   src = np.array(sorted(table), dtype=np.int64)
   dst = np.array([table[int(k)] for k in src], dtype=np.int64)
   at = np.clip(np.searchsorted(src, keys), 0, len(src) - 1)
   return np.where(src[at] == keys, dst[at], -1)


def estimate_light(arr: np.ndarray) -> dict:
   """빛 방향 어림. 돌려주는 것 : {light, dx, dy, shift, size}.

   - `light` : top_left · top · top_right · bottom(아래쪽 — `style.light` 는 안 받는다) · unknown
   - `dx` · `dy` : 치우침(칸, 오른쪽 · 아래가 +) · `shift` : 그 길이 ÷ 크기
   """
   size = long_side(arr)
   out = {"light": UNKNOWN, "dx": 0.0, "dy": 0.0, "shift": 0.0, "size": size}
   if int(opaque(arr).sum()) < 4:
      return out
   ids = _group_ids(ramps.key_map(arr))
   if ids is None:
      return out
   ys, xs = np.nonzero(ids >= 0)
   if len(ys) < 4:
      return out
   gid = ids[ys, xs]
   n = int(gid.max()) + 1
   cells = np.bincount(gid, minlength=n).astype(np.float64)
   bright = luma(arr[ys, xs, :3])
   weight = bright - (np.bincount(gid, bright, n) / np.maximum(cells, 1))[gid]
   cx = xs - (np.bincount(gid, xs.astype(np.float64), n) / np.maximum(cells, 1))[gid]
   cy = ys - (np.bincount(gid, ys.astype(np.float64), n) / np.maximum(cells, 1))[gid]
   total = float(np.abs(weight).sum())
   if total == 0:
      return out

   dx = float((weight * cx).sum()) / total
   dy = float((weight * cy).sum()) / total
   shift = math.hypot(dx, dy) / size
   out.update(dx=round(dx, 3), dy=round(dy, 3), shift=round(shift, 4))
   if shift < MIN_SHIFT:
      return out
   if dy >= 0:
      out["light"] = BOTTOM
      return out
   angle = math.degrees(math.atan2(-dy, dx))
   out["light"] = "top_right" if angle < TOP_RIGHT_MAX else "top" if angle <= TOP_MAX else "top_left"
   return out
