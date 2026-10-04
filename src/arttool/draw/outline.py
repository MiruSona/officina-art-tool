"""외곽선 두르기 — none · black · solid · selout · selout+light (2026-10-04 개선 설계 6-2 · 6-5).

| 방식 | 외곽선 칸의 색 |
| --- | --- |
| `none` | 안 두른다 |
| `black` | 팔레트 `outline` 색, 없으면 #000000 |
| `solid` | 준 한 색(`color`) — 검정이 아닌 진한 갈색 · 남색 선 같은 것. check 의 판정 solid 와 짝 |
| `selout` | 맞닿은 칠한 색의 **두 단 어두운** 색 |
| `selout+light` | `selout` 과 같되 빛이 오는 쪽만 **한 단 어두운** 색(그래서 빛 쪽이 밝다) |

「한 단 어두운 색」은 팔레트가 있고 칠한 색이 어느 램프에 있으면 그 램프의 한 칸 아래 색이다(팔레트 안에 머문다).
없으면 밝기를 단마다 20% 덜고 색조를 파랑 쪽으로 10° 돌려 셈한다(어두울수록 차갑게) — 이때는 팔레트 밖 색이 될 수 있다.
칠한 색이 이미 램프 맨 아래 칸이라 더 내려갈 데가 없으면(그대로면 외곽선이 안 보인다) 팔레트 `outline` 색,
그것도 없으면 셈한 색을 쓴다 — `plan(notes=…)` 에 그 칸 수를 남긴다.

두께(`width`) : 2 이상이면 한 바퀴씩 더 두른다. 바깥 바퀴 칸은 맞닿은 안쪽 바퀴 칸의 색을 그대로 잇는다.

어디에 두르나(`where`)
- `outside` (기본) : 모양 **바깥** 1칸 띠. 모양이 1칸씩 커진다.
- `inside` : 모양의 **가장자리 칸**(투명과 4방향으로 맞닿은 칸)을 어둡게 덧칠한다. 크기가 안 변한다.

`check` 의 외곽선 검사(7-2 ②)가 보는 「가장자리 칸 · 빛 쪽」 정의와 같게 맞췄다 — 이 모듈로 두른 그림은 그 검사에서 같은 방식으로 읽힌다.
"""

from __future__ import annotations

import colorsys

import numpy as np

from .. import image
from ..errors import ArtToolError
from ..palette import Ramps, parse_hex

MODES = ("none", "black", "solid", "selout", "selout+light")
WHERE = ("outside", "inside")

# 빛이 오는 쪽 (x, y). 프로필 style.light 낱말과 같다.
LIGHTS = {"top_left": (-1, -1), "top": (0, -1), "top_right": (1, -1)}

# 4방향 (dx, dy). 이웃을 고를 때 이 순서로 본다.
_DIRS = ((0, 1), (1, 0), (0, -1), (-1, 0))

DARK_STEP = 0.2      # 셈으로 어둡게 할 때 단마다 덜어 낼 밝기 몫
HUE_STEP = 10.0      # 셈으로 어둡게 할 때 단마다 파랑 쪽으로 돌릴 색조(도)
COOL_HUE = 240.0


def check_mode(mode: str) -> str:
   if mode not in MODES:
      raise ArtToolError(f"외곽선 방식은 {' · '.join(MODES)} 중 하나다 : {mode}")
   return mode


def check_light(light: str) -> tuple[int, int]:
   if light not in LIGHTS:
      raise ArtToolError(f"빛 방향은 {' · '.join(LIGHTS)} 중 하나다 : {light}")
   return LIGHTS[light]


def _shift(mask: np.ndarray, dx: int, dy: int) -> np.ndarray:
   """mask 를 (dx, dy) 만큼 민다. 밀려 들어오는 칸은 False. out[y, x] = mask[y - dy, x - dx]."""
   out = np.zeros_like(mask)
   h, w = mask.shape
   ys = slice(max(dy, 0), h + min(dy, 0))
   xs = slice(max(dx, 0), w + min(dx, 0))
   src_y = slice(max(-dy, 0), h + min(-dy, 0))
   src_x = slice(max(-dx, 0), w + min(-dx, 0))
   out[ys, xs] = mask[src_y, src_x]
   return out


def ring(mask: np.ndarray) -> np.ndarray:
   """모양 바깥 1칸 띠 (4방향으로 맞닿은 빈 칸)."""
   near = np.zeros_like(mask)
   for dx, dy in _DIRS:
      near |= _shift(mask, dx, dy)
   return near & ~mask


def edge(mask: np.ndarray) -> np.ndarray:
   """모양의 가장자리 칸 (빈 칸 · 캔버스 밖과 4방향으로 맞닿은 칠한 칸)."""
   padded = np.pad(mask, 1, constant_values=False)
   inner = padded[1:-1, 1:-1].copy()
   for dx, dy in _DIRS:
      inner &= padded[1 + dy : padded.shape[0] - 1 + dy, 1 + dx : padded.shape[1] - 1 + dx]
   return mask & ~inner


def darker(rgb: tuple[int, int, int], steps: int, ramps: Ramps | None = None) -> tuple[int, int, int]:
   """rgb 를 steps 단 어둡게. 팔레트 램프에 있으면 그 램프에서 고른다(맨 아래 칸에서 멈춘다).

   이미 맨 아래 칸이면 팔레트 outline 색, 없으면 셈한 색 (리뷰 R2-M3 — 외곽선이 칠한 색과 같아 안 보이는 일을 막는다).
   """
   return _darker(rgb, steps, ramps)[0]


def _darker(rgb, steps: int, ramps: Ramps | None) -> tuple[tuple[int, int, int], bool]:
   """(색, 램프 맨 아래라 다른 색으로 바꿨나)."""
   if ramps is not None:
      for colors in ramps.ramps.values():
         if rgb in colors:
            got = colors[max(0, colors.index(rgb) - steps)]
            if got != rgb:
               return got, False
            if ramps.outline is not None and ramps.outline != rgb:
               return ramps.outline, True
            return _computed(rgb, steps), True
   return _computed(rgb, steps), False


def _computed(rgb, steps: int) -> tuple[int, int, int]:
   hue, sat, val = colorsys.rgb_to_hsv(rgb[0] / 255.0, rgb[1] / 255.0, rgb[2] / 255.0)
   hue *= 360.0
   gap = (COOL_HUE - hue + 180.0) % 360.0 - 180.0
   turn = min(abs(gap), HUE_STEP * steps)
   hue = (hue + (turn if gap >= 0 else -turn)) % 360.0
   r, g, b = (c * 255.0 for c in colorsys.hsv_to_rgb(hue / 360.0, sat, val))
   # 밝기(luma)를 정확히 단마다 같은 몫으로 덜어 낸다 — 색조를 돌리면 색마다 밝기가 다르게 변해서,
   # 빛 쪽 · 그늘 쪽 바탕색이 다르면 같은 단 수라도 check 가 「빛 쪽이 밝다」로 잘못 읽는다.
   want = _luma(rgb) * max(0.0, 1.0 - DARK_STEP * steps)
   now = _luma((r, g, b))
   k = want / now if now > 0 else 0.0
   return tuple(int(min(255, max(0, round(c * k)))) for c in (r, g, b))


def _luma(rgb) -> float:
   return 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]


def _solid_color(color) -> tuple[int, int, int]:
   if isinstance(color, str):
      return parse_hex(color)
   if isinstance(color, (tuple, list)) and len(color) == 3 and all(isinstance(c, int) and 0 <= c <= 255 for c in color):
      return tuple(color)
   raise ArtToolError(f"solid 외곽선은 color 에 한 색(#RRGGBB · (R, G, B))을 준다 : {color!r}")


def plan(arr: image.RGBA, mode: str, *, ramps: Ramps | None = None, light: str = "top_left", where: str = "outside",
         color=None, width: int = 1, notes: list | None = None) -> list[tuple[int, int, tuple[int, int, int], tuple[int, int]]]:
   """두를 칸 목록 `(x, y, 색, 기댄 칠한 칸 (x, y))` 을 셈만 하고 그리지는 않는다.

   「기댄 칠한 칸」은 그 외곽선 색을 정한 칸이다. 겹이 여럿일 때 `Canvas.outline` 이 그 칸의 주인 겹에 외곽선을 넣는다.
   color : solid 방식의 한 색. width : 두께(1 ~ 4). notes : 목록을 주면 알릴 일(`{"rule", "count"}`)을 덧붙인다.
   """
   check_mode(mode)
   if where not in WHERE:
      raise ArtToolError(f"외곽선 자리는 {' · '.join(WHERE)} 중 하나다 : {where}")
   if not isinstance(width, int) or isinstance(width, bool) or not 1 <= width <= 4:
      raise ArtToolError(f"외곽선 두께는 1 ~ 4 정수다 : {width!r}")
   lx, ly = check_light(light)
   if mode == "none":
      return []
   one = _solid_color(color) if mode == "solid" else None
   first = _one_round(arr, mode, ramps, (lx, ly), where, one, notes)
   out = list(first)
   done = {(x, y): (c, a) for x, y, c, a in first}
   solid = arr[:, :, 3] > 0
   for _ in range(width - 1):
      ring_now = np.zeros_like(solid)
      for x, y in done:
         ring_now[y, x] = True
      if where == "outside":
         targets = ring(solid | ring_now)
      else:
         targets = edge(solid & ~ring_now) & solid
      added = []
      for y, x in zip(*np.nonzero(targets)):
         x, y = int(x), int(y)
         near = [(x - dx, y - dy) for dx, dy in _DIRS if (x - dx, y - dy) in done]
         if not near:
            continue
         c, a = done[near[0]]
         added.append((x, y, c, a))
      for x, y, c, a in added:
         done[(x, y)] = (c, a)
      out += added
   return out


def _one_round(arr, mode, ramps, light_xy, where, one, notes):
   lx, ly = light_xy
   fell = 0
   solid = arr[:, :, 3] > 0
   h, w = solid.shape
   targets = ring(solid) if where == "outside" else edge(solid)
   black = ramps.outline if (ramps is not None and ramps.outline is not None) else (0, 0, 0)

   out = []
   for y, x in zip(*np.nonzero(targets)):
      x, y = int(x), int(y)
      # 바깥 띠면 맞닿은 칠한 칸이 기준, 안쪽이면 자기 칸이 기준이다.
      if where == "outside":
         near = [(x - dx, y - dy) for dx, dy in _DIRS if 0 <= x - dx < w and 0 <= y - dy < h and solid[y - dy, x - dx]]
         outward = [(dx, dy) for dx, dy in _DIRS if (x - dx, y - dy) in near]
         # 맞닿은 색이 여럿이면 가장 많은 색, 같으면 어두운 색.
         counts: dict[tuple[int, int, int], list[tuple[int, int]]] = {}
         for nx, ny in near:
            counts.setdefault(tuple(int(c) for c in arr[ny, nx, :3]), []).append((nx, ny))
         base = min(counts, key=lambda c: (-len(counts[c]), _luma(c)))
         anchor = counts[base][0]
      else:
         outward = [(dx, dy) for dx, dy in _DIRS if not (0 <= x + dx < w and 0 <= y + dy < h) or not solid[y + dy, x + dx]]
         base = tuple(int(c) for c in arr[y, x, :3])
         anchor = (x, y)
      if mode == "black":
         color = black
      elif mode == "solid":
         color = one
      else:
         lit = mode == "selout+light" and any(dx * lx + dy * ly > 0 for dx, dy in outward)
         color, changed = _darker(base, 1 if lit else 2, ramps)
         fell += changed
      out.append((x, y, color, anchor))
   if fell and notes is not None:
      notes.append({"rule": "outline_ramp_bottom", "count": fell,
                    "detail": f"램프 맨 아래 색이라 더 어두운 칸이 없어 outline 색(없으면 셈한 색)을 쓴 외곽선 {fell}칸"})
   return out


def outline(arr: image.RGBA, mode: str, *, ramps: Ramps | None = None, light: str = "top_left", where: str = "outside",
            color=None, width: int = 1) -> image.RGBA:
   """그림 한 장에 외곽선을 두른 새 배열을 돌려준다(받은 배열은 그대로). solid 는 color 를, 두꺼운 선은 width 를 준다."""
   out = arr.copy()
   for x, y, color, _ in plan(arr, mode, ramps=ramps, light=light, where=where, color=color, width=width):
      out[y, x] = (*color, 255)
   return out
