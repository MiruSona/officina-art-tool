"""`merge-colors --clean` — 색을 합친 뒤 홀로 남은 잡티 점을 둘레 색으로 메운다 (2026-10-06).

메우는 칸 (모두 만족) :
- 8이웃에 같은 색이 없는 칸(외톨이, `checks.pixels.same_neighbors` == 0) 또는 같은 색 2칸 덩어리(두 칸 다 같은 색으로 메울 수 있을 때만 같이)
- 이웃 8칸 중 FILL_SHARE 칸 이상이 한 색 — 그 색으로 메운다
- 그 색까지 체비셰프 거리 ≤ max(2 × tol, NEAR_MIN), 상한 NEAR_CAP. tol 이 없으면(--max-colors 만 · --palette) NEAR_MIN
- 저와 이웃 8칸이 모두 알파 255 (투명 · 반투명과 맞닿지 않고, 그림 테두리도 아니다). `--keep` 색이 아니다
그 밖(하이라이트 · 눈동자 · 무늬)은 살린다. 문턱의 까닭은 `Docs/Guide/명령안내.md` merge-colors 절.
판정은 모두 메우기 전 그림으로 한 번에 한다 — 앞에서 메운 칸이 뒤 판정을 바꾸지 않는다.
"""

from __future__ import annotations

import numpy as np

from .. import image
from ..checks.pixels import neighbor_keys, rgba_keys

# 문턱 셋은 실물 15장 재기(2026-10-06)로 정했다. 까닭은 명령안내 merge-colors 절
FILL_SHARE = 6      # 이웃 8칸 중 한 색이 이만큼
NEAR_MIN = 16       # 거리 문턱 바닥
NEAR_CAP = 24       # 거리 문턱 상한


def near_limit(tol: int | None) -> int:
   return min(max(2 * int(tol or 0), NEAR_MIN), NEAR_CAP)


def _rgb_of(keys: np.ndarray) -> np.ndarray:
   return np.stack([(keys >> 24) & 255, (keys >> 16) & 255, (keys >> 8) & 255], axis=-1)


def clean_specks(arr: image.RGBA, tol: int | None, keep: set[int]) -> tuple[image.RGBA, int]:
   """(메운 그림, 메운 칸 수). keep 은 RGB 열쇠(r << 16 | g << 8 | b) 모음. 알파 · 투명 칸은 그대로."""
   out = arr.copy()
   keys = rgba_keys(arr)
   nb = neighbor_keys(keys)
   same = np.where(keys >= 0, (nb == keys).sum(axis=0), 0)
   is_partner = (neighbor_keys(same) == 1) & (nb == keys)
   pair = (same == 1) & is_partner.any(axis=0)
   solid_around = ((nb >= 0) & ((nb & 255) == 255)).all(axis=0)
   rgb_key = keys >> 8
   kept = np.isin(rgb_key, np.array(sorted(keep), dtype=np.int64)) if keep else np.zeros(keys.shape, dtype=bool)
   cand = (arr[:, :, 3] == 255) & ((same == 0) | pair) & solid_around & ~kept
   ys, xs = np.nonzero(cand)
   if ys.size == 0:
      return out, 0

   around = nb[:, ys, xs]                                    # (8, n)
   votes = (around[:, None, :] == around[None, :, :]).sum(axis=1)
   top = around[votes.argmax(axis=0), np.arange(ys.size)]
   gap = np.abs(_rgb_of(top) - _rgb_of(keys[ys, xs])).max(axis=1)
   ok = (votes.max(axis=0) >= FILL_SHARE) & (gap <= near_limit(tol))
   target = np.full(keys.shape, -3, dtype=np.int64)          # 칸마다 메울 색 열쇠, 못 메우면 -3
   target[ys[ok], xs[ok]] = top[ok]
   # 2칸 덩어리는 짝도 같은 색으로 메울 수 있을 때만 — 한 칸만 메우면 남은 칸이 새 외톨이가 된다
   partner_target = neighbor_keys(target)[is_partner.argmax(axis=0), np.arange(keys.shape[0])[:, None], np.arange(keys.shape[1])]
   fill = (target >= 0) & (~pair | (partner_target == target))
   fy, fx = np.nonzero(fill)
   out[fy, fx, :3] = _rgb_of(target[fy, fx]).astype(out.dtype)
   return out, int(fill.sum())
