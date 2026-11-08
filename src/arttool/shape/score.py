"""원본 대비 닮음 점수 (draw 고리 실측 2-2 절의 채점기 정의를 그대로 다시 짠 것).

| 점수 | 뜻 |
| --- | --- |
| silhouette_iou | 불투명 칸 마스크의 교집합 ÷ 합집합 |
| exact | 원본 불투명 칸 중 RGBA 가 똑같은 칸 비율 |
| near | 원본 불투명 칸 중 그림도 불투명이고 RGB 각 칸 차가 모두 tol(24) 이하인 칸 비율 |
| near_shifted | 그림을 ±shift(2) 칸 안에서 밀어 본 near 가운데 가장 큰 값. **닮음의 주 점수** |

그때 채점기(`score.py`)는 세션 스크래치패드에만 있어 저장소에 없다. 자가 시험 넷(자신 1.0 · 1칸 밀면 near < 1 → shifted 1.0 ·
전부 투명 0 · +10 밝게 exact 0 / near 1.0)은 `tests/test_shape_render.py` 가 다시 본다.
"""

from __future__ import annotations

import numpy as np

from ..errors import ArtToolError

TOL = 24
SHIFT = 2


def _shifted(arr: np.ndarray, dx: int, dy: int) -> np.ndarray:
   """out[y, x] = arr[y - dy, x - dx]. 밀려 들어오는 칸은 투명."""
   out = np.zeros_like(arr)
   h, w = arr.shape[:2]
   out[max(dy, 0):h + min(dy, 0), max(dx, 0):w + min(dx, 0)] = arr[max(-dy, 0):h + min(-dy, 0), max(-dx, 0):w + min(-dx, 0)]
   return out


def _near(img: np.ndarray, ref: np.ndarray, ref_solid: np.ndarray, tol: int) -> float:
   both = ref_solid & (img[:, :, 3] > 0)
   diff = np.abs(img[:, :, :3].astype(int) - ref[:, :, :3].astype(int)).max(axis=2)
   return float((both & (diff <= tol)).sum()) / float(ref_solid.sum())


def similarity(img: np.ndarray, ref: np.ndarray, tol: int = TOL, shift: int = SHIFT) -> dict:
   """그림 img 를 원본 ref 와 견준 점수 사전. 두 그림 크기가 같아야 한다."""
   if img.shape != ref.shape:
      raise ArtToolError(f"크기가 다르다 : 그림 {img.shape[1]}×{img.shape[0]} · 원본 {ref.shape[1]}×{ref.shape[0]}")
   ref_solid = ref[:, :, 3] > 0
   if not ref_solid.any():
      raise ArtToolError("원본에 불투명 칸이 없다")
   img_solid = img[:, :, 3] > 0
   union = (ref_solid | img_solid).sum()
   exact = (ref_solid & np.all(img == ref, axis=2)).sum() / ref_solid.sum()
   best, best_at = -1.0, (0, 0)
   for dy in range(-shift, shift + 1):
      for dx in range(-shift, shift + 1):
         value = _near(_shifted(img, dx, dy), ref, ref_solid, tol)
         # 같은 값이면 덜 민 쪽
         if value > best + 1e-12 or (abs(value - best) <= 1e-12 and abs(dx) + abs(dy) < abs(best_at[0]) + abs(best_at[1])):
            best, best_at = value, (dx, dy)
   return {
      "silhouette_iou": round(float((ref_solid & img_solid).sum() / union), 4),
      "exact": round(float(exact), 4),
      "near": round(_near(img, ref, ref_solid, tol), 4),
      "near_shifted": round(best, 4),
      "shift": list(best_at),
   }
