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
from ..pieces import labels as _labels   # 덩이 번호 매기기는 겹 구멍 검사도 써서 공용 자리로 옮겼다 (7판 2-3)
from ..sprite.split import DEFAULT_MIN_PIECE
from . import ramps

MIN_SHIFT = 0.05        # 치우침이 그림 크기(불투명 bbox 긴 변)의 이 몫 미만이면 「모름」
TOP_RIGHT_MAX = 60.0    # 위쪽 반원의 각도(0 = 오른쪽, 90 = 위, 180 = 왼쪽)로 셋을 가른다
TOP_MAX = 120.0

UNKNOWN = "unknown"
BOTTOM = "bottom"

MIN_PIECE = DEFAULT_MIN_PIECE   # 이보다 작은 자리 덩이(눈 반짝임 · 티끌)는 덩이로 안 센다 — split 과 같은 기준
MIN_PIECE_SHARE = 0.1           # 가장 큰 덩이 칸 수의 이 몫 미만인 덩이(작은 장식)도 덩이로 안 센다
MAX_PIECES = 64                 # 덩이별 판정은 큰 덩이부터 이만큼만 — 자잘한 덩이 수천 개에서 느려지지 않게
HIGH = "high"
LOW = "low"


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


def _piece_ids(arr: np.ndarray) -> tuple[np.ndarray, int]:
   """칸마다 뜻 있는 덩이 번호(큰 덩이부터 0, 1, …, 그 밖 -1)와 그 수.

   덩이는 투명으로 떨어진 불투명 덩이(외곽선 포함)다 — 검정 선이 안을 갈라도 한 덩이.
   뜻 있는 덩이 = MIN_PIECE 칸 이상이고 가장 큰 덩이의 MIN_PIECE_SHARE 이상.
   """
   label, sizes = _labels(opaque(arr))
   keep = int(((sizes >= MIN_PIECE) & (sizes >= MIN_PIECE_SHARE * (sizes[0] if len(sizes) else 0))).sum())
   return np.where(label < keep, label, -1), keep


def _judge(out: dict, ys: np.ndarray, xs: np.ndarray, gid: np.ndarray, bright: np.ndarray, size: int) -> dict:
   """묶음 번호 gid(0 부터 빈틈없이)로 무게 · 무게중심을 잡아 치우침과 판정을 out 에 채운다."""
   n = int(gid.max()) + 1
   cells = np.bincount(gid, minlength=n).astype(np.float64)
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


def estimate_light(arr: np.ndarray) -> dict:
   """빛 방향 어림. 돌려주는 것 : {light, dx, dy, shift, size, confidence, pieces}.

   - `light` : top_left · top · top_right · bottom(아래쪽 — `style.light` 는 안 받는다) · unknown
   - `dx` · `dy` : 치우침(칸, 오른쪽 · 아래가 +) · `shift` : 그 길이 ÷ 크기
   - `pieces` : 뜻 있는 덩이 수(1 이하 = 덩이 나누기 없이 옛 셈)
   - `confidence` : 덩이마다 따로 낸 판정(모름 빼고)이 엇갈리면 "low", 아니면 "high"

   덩이는 투명으로 떨어진 불투명 덩이(외곽선 포함)다. 검정 선이 안을 갈라도 한 덩이로 센다 —
   검정 뺀 칸으로 나누면 선으로 갈린 한 캐릭터의 판정이 조용히 바뀐다(리뷰 실측).
   뜻 있는 덩이(MIN_PIECE 칸 이상 · 가장 큰 덩이의 MIN_PIECE_SHARE 이상)가 하나 이하면
   티끌까지 그림 전체로 옛 셈을 그대로 한다 — light · dx · dy · shift · size 가 옛 판과 같다.

   둘 이상이면 무게중심을 (램프 덩어리, 덩이) 쌍마다 잡고, 뜻 없는 작은 덩이 칸은 뺀다.
   같은 램프의 두 덩이가 무게중심 하나를 나눠 가지면 그 점이 두 덩이 사이 빈 곳에 놓여
   「어느 덩이가 더 밝은가」 가 판정을 좌우하기 때문이다.
   외곽선을 같이 쓰는(투명으로 안 떨어진) 두 덩이는 한 덩이로 세어 옛 셈으로 간다 — 이건 못 가른다.
   """
   size = long_side(arr)
   out = {"light": UNKNOWN, "dx": 0.0, "dy": 0.0, "shift": 0.0, "size": size, "confidence": HIGH, "pieces": 0}
   if int(opaque(arr).sum()) < 4:
      return out
   ids = _group_ids(ramps.key_map(arr))
   if ids is None:
      return out
   piece, count = _piece_ids(arr)
   out["pieces"] = count
   # 뜻 있는 덩이가 하나 이하면 그림 전체(티끌 포함)로 옛 셈 그대로
   ys, xs = np.nonzero((ids >= 0) & (piece >= 0)) if count > 1 else np.nonzero(ids >= 0)
   if len(ys) < 4:
      return out
   bright = luma(arr[ys, xs, :3])
   gid = ids[ys, xs]
   if count > 1:
      # (램프 덩어리, 자리 덩이) 쌍을 빈틈없는 번호로
      pid = piece[ys, xs]
      _, gid = np.unique(gid * count + pid, return_inverse=True)
      gid = gid.reshape(-1)
      out["confidence"] = _confidence(ys, xs, gid, pid, bright)
   return _judge(out, ys, xs, gid, bright, size)


def _confidence(ys: np.ndarray, xs: np.ndarray, gid: np.ndarray, pid: np.ndarray, bright: np.ndarray) -> str:
   """큰 덩이부터 MAX_PIECES 개까지 덩이마다 따로 판정해, 모름 뺀 판정이 둘 이상 갈리면 low.

   덩이 크기는 그 덩이 bbox 긴 변 — MIN_SHIFT 를 덩이 크기에 맞춰 잰다.
   """
   seen = set()
   for k in range(min(int(pid.max()) + 1, MAX_PIECES)):
      sel = pid == k
      if int(sel.sum()) < 4:
         continue
      py, px = ys[sel], xs[sel]
      size = max(int(px.max() - px.min()), int(py.max() - py.min())) + 1
      _, sub = np.unique(gid[sel], return_inverse=True)
      verdict = _judge({"light": UNKNOWN}, py, px, sub.reshape(-1), bright[sel], size)["light"]
      if verdict != UNKNOWN:
         seen.add(verdict)
   return LOW if len(seen) > 1 else HIGH
