"""새 검사 일곱 (2026-10-04 개선 설계 7절). 모두 「경고」다 — `status` · 종료 코드 · `bake` 를 안 바꾼다.

검사마다 「재기」 함수(`measure_*`)와 「판정」 함수(`judge_*`)를 나눈다.
재기 함수는 그림(또는 램프) 하나를 받아 숫자 dict 를 돌려주고 프로필을 모른다 — `sheet` · `style extract` 가 그대로 불러 쓴다.
판정 함수는 재 둔 값과 프로필 문턱을 견줘 경고 한 줄(또는 None)을 낸다.

| 모듈 | 검사 |
| --- | --- |
| `scale` | ① integer_scale |
| `outline` | ② outline |
| `pixels` | ③ isolated · ④ color_cap · ⑤ near_colors |
| `ramp` | ⑥ ramp_shape |
| `loop` | ⑦ loop_seam |

여기에는 여럿이 같이 쓰는 작은 셈(불투명 판 · 가장자리 판 · 밝기 · 색조 · 경고 꼴)만 둔다.
"""

from __future__ import annotations

import colorsys

import numpy as np

# 채도가 이보다 낮은 칸은 색조가 뜻이 없다(회색). 외곽선 · 램프 검사가 같이 쓴다.
LOW_SAT = 0.12


def warning(rule: str, detail: str, items: list | None = None, must: bool = False) -> dict:
   """걸린 경고 한 줄. `ui check` 의 warnings 와 같은 꼴 {rule, ok: false, detail, items}."""
   out = {"rule": rule, "ok": False, "detail": detail, "items": items or []}
   if must:
      out["must"] = True
   return out


def opaque(arr: np.ndarray) -> np.ndarray:
   """알파가 0 이 아닌 칸."""
   return arr[:, :, 3] > 0


def shifted(mask: np.ndarray, dy: int, dx: int, fill: bool = False) -> np.ndarray:
   """판을 (dy, dx) 만큼 민다. 결과[y, x] = mask[y + dy, x + dx]. 밖은 fill."""
   h, w = mask.shape
   out = np.full_like(mask, fill)
   ys = slice(max(0, -dy), min(h, h - dy))
   xs = slice(max(0, -dx), min(w, w - dx))
   ys_src = slice(max(0, dy), min(h, h + dy))
   xs_src = slice(max(0, dx), min(w, w + dx))
   out[ys, xs] = mask[ys_src, xs_src]
   return out


DIRS4 = ((-1, 0), (1, 0), (0, -1), (0, 1))   # 위 · 아래 · 왼 · 오


def raw_edge(arr: np.ndarray) -> np.ndarray:
   """투명과 4방향으로 맞닿은 불투명 칸. 그림 밖은 투명으로 본다."""
   solid = opaque(arr)
   touch = np.zeros_like(solid)
   for dy, dx in DIRS4:
      touch |= ~shifted(solid, dy, dx, fill=False)
   return solid & touch


def edge_mask(arr: np.ndarray) -> np.ndarray:
   """외곽선 검사가 세는 가장자리 칸 (설계 7-2 ②).

   투명과 맞닿은 불투명 칸 중 **안쪽 불투명 이웃(가장자리가 아닌 칸)이 4방향에 하나라도 있는 칸**만.
   1~2px 가는 머리카락 끝처럼 안쪽이 없는 칸은 뺀다.
   """
   edge = raw_edge(arr)
   inner = opaque(arr) & ~edge
   near_inner = np.zeros_like(edge)
   for dy, dx in DIRS4:
      near_inner |= shifted(inner, dy, dx, fill=False)
   return edge & near_inner


def luma(rgb: np.ndarray) -> np.ndarray:
   """밝기 0 ~ 255 (Rec.601). 끝 칸이 RGB 인 배열을 받는다."""
   rgb = rgb.astype(np.float64)
   return 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]


def hue_sat(rgb) -> tuple[float, float]:
   """색 하나 → (색조 0~360 도, 채도 0~1). HSV 기준."""
   r, g, b = (float(v) / 255.0 for v in rgb[:3])
   hue, sat, _val = colorsys.rgb_to_hsv(r, g, b)
   return hue * 360.0, sat


def hue_gap(a: float, b: float) -> float:
   """두 색조 사이 짧은 쪽 각도 (0 ~ 180)."""
   gap = abs(a - b) % 360.0
   return min(gap, 360.0 - gap)


def norm_rgba(arr: np.ndarray) -> np.ndarray:
   """투명 칸의 RGB 찌꺼기를 지워 (0,0,0,0) 으로. int32 라 차이 셈이 안 넘친다."""
   out = arr.astype(np.int32)
   out[arr[:, :, 3] == 0] = 0
   return out


def long_side(arr: np.ndarray) -> int:
   """불투명 bbox 의 긴 변. 다 비었으면 0."""
   solid = opaque(arr)
   if not solid.any():
      return 0
   ys = np.nonzero(solid.any(axis=1))[0]
   xs = np.nonzero(solid.any(axis=0))[0]
   return int(max(ys[-1] - ys[0] + 1, xs[-1] - xs[0] + 1))


def is_background(arr: np.ndarray, min_side: int) -> bool:
   """배경 그림인가 (설계 7-1 `check.background.auto`) : 투명 칸이 하나도 없고 짧은 변이 min_side 이상."""
   h, w = arr.shape[:2]
   return bool(min(h, w) >= min_side and not np.any(arr[:, :, 3] == 0))
