"""재질 질감 — 납작 칠 위에 결 · 짜임 · 얼룩 · 주름과 곁색을 규칙으로 얹는다 (2026-11-08 질감 규칙 시험).

게임 그림은 한 장에 40~48색을 쓰고 재질마다 나뭇결 · 짚결 · 잎 얼룩 · 옷 주름을 촘촘히 넣는다.
렌더러의 3단 납작 칠과 섞으면 그 차이가 티가 나서, 명세 맨 위 `texture` 목록으로 질감을 붙인다.

    "texture": [
      { "kind": "wood_grain", "on": ["*.wood"], "density": 0.4, "length": 5, "knots": 0.6, "seed": 1 },
      { "kind": "mottle", "on": "body.m", "cell": 2, "share": 0.3 },
      { "kind": "hue_side", "on": "*", "shift": 10, "share": 0.35 }
    ]

| kind | 하는 일 | 칸 |
| --- | --- | --- |
| `wood_grain` | 도형마다 긴 쪽(판 방향)을 따라 끊어진 결 줄. 줄은 반 단 어둡게(가끔 밝게), 가끔 옹이(한 단) | `density` 줄 비율 · `length` 토막 길이 · `gap` 끊김 비율 · `light` 밝은 줄 비율 · `knots` 100칸당 옹이 · `dir` x/y/auto/around |
| `weave` | 짚 · 바구니. 칸 `period` 마다 방향이 엇갈리는 사선 줄(짜임) | `period` · `light` 가운데 밝은 줄을 넣나 |
| `mottle` | 잎 · 도기 · 칠판. 값 잡음 덩어리 얼룩 — 낮은 곳 어둡게, 높은 곳 밝게, 아주 낮은 곳 두 배 | `cell` 덩어리 크기 · `share` 어둡게/밝게 몫 · `deep` 두 배 몫 |
| `fold` | 천. 짧은 사선 · 곡선 주름 그늘(+ 빛 쪽 옆 한 칸 밝게). `style: mass` 는 넓은 그늘 판 + 빛 쪽 한 칸 밝은 테 | `density` · `length` · `lean` 기울기 · `bend` 휨 · `light` · `style` line/mass · `width` 판 너비 · `spots` 자리 지정 · `tone` shade/light |
| `hue_side` | 램프 곁색 : 같은 밝기에서 색조만 ±`shift`° 돈 색을 덩어리로 섞는다 (게임 그림 색 수 흉내) | `shift` · `share` · `cell` |

- `on` 은 재질 이름 또는 그 목록이다. `*` · `?` 글자 맞추기(fnmatch)가 된다 (`*.wood`).
- 세기 `strength` 는 「램프 한 단의 몇 몫만큼 옮기나」다 (기본 0.5 = 반 단). 반 단 색은 램프 두 칸을 섞어 만든다.
  램프 끝을 넘으면(맨 아래 칸을 더 어둡게) 색을 셈해서 만든다 — 어두울수록 파랑 쪽, 밝을수록 노랑 쪽으로 조금 돈다.
- `follow` (기본 `none`) 은 질감을 모양 · 빛에 묶는다 (2026-11-08 마무리 흐름 시험).
  `light` : 칸의 빛 단(levels)을 보고 그늘 쪽은 어두운 결을 그대로 · 밝은 쪽은 `fade`(기본 .85) 몫만큼 덜어 내고,
  밝은 결은 가운데 단에만 남긴다(맨 밝은 단은 비운다). 하이라이트 칸(재질 `highlight` 색)에는 질감을 안 얹는다.
  `form` : `light` 와 같되 빛 정도를 노멀(n·빛)로 부드럽게 재고, 둥근 도형은 얼룩 · 곁색 · 결이 둘레를 따라 휜다
  (도형 가운데를 축으로 한 각도 · 반지름 좌표로 잡음을 뽑는다).
- `fold` `style: mass` 에 `spots` ([[x, y] 또는 [x, y, 길이]], 그림 칸)을 주면 해시로 뿌리지 않고 그 자리에만 판을 놓는다
  (어깨 아래 · 팔꿈치 · 주머니 위). `tone: light` 는 그늘 대신 밝은 판(테 없음) — 머리 빛 띠를 자리 지정으로 놓는다 (보완 고리 1).
  `tone: band` 는 빛 띠를 「한 색」으로 : 띠 안 칸은 재질과 머리결 줄을 가리지 않고 모두 `on` 첫 재질의 가장 많은 색을
  `strength` 단 밝힌 한 색이 된다 — 띠 자리에서 머리결 줄이 빠지고 회색 잡음으로 안 부서진다 (보완 고리 2, 검은 머리).
- `dir: around` (wood_grain) 는 `follow` 와 상관없이 둥근 도형의 결을 둘레를 따라 돌린다 — 둥근 테 · 바퀴 (보완 고리 3).
  `follow: form` 은 원래도 둘레로 돌지만, 테처럼 앞을 보는 판은 노멀 빛이 0 에 가까워 `light` 를 써야 결이 산다.
- `ramp_extra` (색 목록) 는 한 단 옮길 때 이웃 색을 재질 램프와 이 색들 가운데서 찾는다 — 한 색 재질(틀 색 갈이)에서
  주름 그늘이 셈한 색(파랑 쪽으로 돈 회색)이 아니라 정해 둔 「한 단 어두운 같은 계열 색」이 되게 한다 (보완 고리 3, 앞치마).
- 모두 정수 해시라 `seed` 가 같으면 언제나 같은 그림이다. `texture` 가 없으면 렌더 결과는 질감 전과 칸까지 같다.
"""

from __future__ import annotations

import colorsys
import dataclasses
import fnmatch
from dataclasses import dataclass, field

import numpy as np

from ..errors import ArtToolError
from ..palette import RGB, parse_hex
from .pattern import hash01

KINDS = ("wood_grain", "weave", "mottle", "fold", "hue_side")
DIRS = ("auto", "x", "y", "around")
FOLLOWS = ("none", "light", "form")
FOLD_STYLES = ("line", "mass")
TONES = ("shade", "light", "band")
LIGHT_DX = {"top_left": -1, "top": 0, "top_right": 1}   # 빛이 오는 쪽 x (그림 좌표)
ROUND_ASPECT = 1.6       # 도형 칸 상자의 긴 변 / 짧은 변이 이 아래면 「둥근 도형」 — form 이 둘레 좌표를 쓴다
CURVE_STRETCH = 2.5      # form : 얼룩을 둘레 방향으로 이만큼 늘인다
LUMA_GAP = 3.0           # 램프 이웃 칸을 찾을 때 이만큼 넘게 밝기가 달라야 「다른 단」
DERIVED_DARK = 0.80      # 램프 밖 어두운 칸 : 밝기(HSV v) 배율
DERIVED_LIGHT = 0.30     # 램프 밖 밝은 칸 : 남은 밝기 몫
DERIVED_HUE = 8.0        # 램프 밖 칸 색조 돌림(도)


@dataclass
class TexRule:
   kind: str
   on: list[str]
   seed: int = 0
   strength: float = 0.5
   density: float = 0.4
   length: float = 5.0
   gap: float = 0.25
   light: float = 0.25
   knots: float = 0.0
   dir: str = "auto"
   period: int = 4
   cell: float = 2.0
   share: float = 0.3
   deep: float = 0.08
   lean: float = 1.0
   bend: float = 0.0
   shift: float = 10.0
   follow: str = "none"
   fade: float = 0.85
   style: str = "line"
   width: int = 3
   spots: list = field(default_factory=list)   # fold mass : 자리 지정 [[x, y] 또는 [x, y, 길이]] (그림 칸). 주면 density 대신
   tone: str = "shade"                          # fold mass : shade 그늘 판 · light 빛 띠 (밝게, 테 없음)
   ramp_extra: list = field(default_factory=list)  # 이웃 색 찾기에 재질 램프와 함께 쓸 색 (보완 고리 3). 비면 재질 램프만
   extra: dict = field(default_factory=dict)


def _err(path: str, msg: str) -> ArtToolError:
   return ArtToolError(f"명세 {path} : {msg}")


def _num(data: dict, key: str, path: str, default: float, low: float, high: float) -> float:
   value = data.get(key, default)
   if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
      raise _err(f"{path}.{key}", f"{low} ~ {high} 수다 : {value!r}")
   return float(value)


def parse(raw, materials: dict, path: str = "texture") -> list[TexRule]:
   """명세 `texture` 칸 → 규칙 목록. 없으면 빈 목록."""
   if raw is None:
      return []
   if isinstance(raw, dict):
      raw = [raw]
   if not isinstance(raw, list):
      raise _err(path, "질감 사전 또는 그 목록이다")
   out = []
   for i, data in enumerate(raw):
      here = f"{path}[{i}]"
      if not isinstance(data, dict):
         raise _err(here, "질감은 사전이다")
      kind = data.get("kind")
      if kind not in KINDS:
         raise _err(f"{here}.kind", f"{' · '.join(KINDS)} 중 하나다 : {kind!r}")
      on = data.get("on")
      on = [on] if isinstance(on, str) else on
      if not isinstance(on, list) or not on or not all(isinstance(p, str) and p for p in on):
         raise _err(f"{here}.on", "재질 이름(글자 맞추기 가능) 또는 그 목록이다")
      if not any(fnmatch.fnmatchcase(name, p) for p in on for name in materials):
         raise _err(f"{here}.on", f"맞는 재질이 없다 : {on}")
      seed = data.get("seed", 0)
      if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2**31:
         raise _err(f"{here}.seed", f"0 이상 정수다 : {seed!r}")
      direction = data.get("dir", "auto")
      if direction not in DIRS:
         raise _err(f"{here}.dir", f"{' · '.join(DIRS)} 중 하나다 : {direction!r}")
      period = data.get("period", 4)
      if isinstance(period, bool) or not isinstance(period, int) or not 2 <= period <= 16:
         raise _err(f"{here}.period", f"2 ~ 16 정수다 : {period!r}")
      follow = data.get("follow", "none")
      if follow not in FOLLOWS:
         raise _err(f"{here}.follow", f"{' · '.join(FOLLOWS)} 중 하나다 : {follow!r}")
      style = data.get("style", "line")
      if style not in FOLD_STYLES:
         raise _err(f"{here}.style", f"{' · '.join(FOLD_STYLES)} 중 하나다 : {style!r}")
      if style != "line" and kind != "fold":
         raise _err(f"{here}.style", "fold 에만 쓴다")
      width = data.get("width", 3)
      if isinstance(width, bool) or not isinstance(width, int) or not 1 <= width <= 8:
         raise _err(f"{here}.width", f"1 ~ 8 정수다 : {width!r}")
      spots = data.get("spots", [])
      if not isinstance(spots, list) or not all(
            isinstance(q, list) and len(q) in (2, 3) and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in q)
            for q in spots):
         raise _err(f"{here}.spots", "[x, y] 또는 [x, y, 길이] 목록이다 (그림 칸)")
      tone = data.get("tone", "shade")
      if tone not in TONES:
         raise _err(f"{here}.tone", f"{' · '.join(TONES)} 중 하나다 : {tone!r}")
      if (spots or tone != "shade") and style != "mass":
         raise _err(f"{here}.spots", "spots · tone 은 fold style mass 에만 쓴다")
      if direction == "around" and kind != "wood_grain":
         raise _err(f"{here}.dir", "around 는 wood_grain 에만 쓴다")
      extra = data.get("ramp_extra", [])
      if not isinstance(extra, list) or not all(isinstance(c, str) for c in extra):
         raise _err(f"{here}.ramp_extra", "#RRGGBB 색 목록이다")
      try:
         extra = [parse_hex(c) for c in extra]
      except Exception as exc:   # noqa: BLE001 — 잘못된 색 글자
         raise _err(f"{here}.ramp_extra", f"#RRGGBB 색 목록이다 : {exc}") from None
      rule = TexRule(
         kind, on, seed,
         strength=_num(data, "strength", here, 0.5, 0.05, 2.0),
         density=_num(data, "density", here, 0.4, 0.0, 1.0),
         length=_num(data, "length", here, 5.0, 1.0, 64.0),
         gap=_num(data, "gap", here, 0.25, 0.0, 0.95),
         light=_num(data, "light", here, 0.25, 0.0, 1.0),
         knots=_num(data, "knots", here, 0.0, 0.0, 10.0),
         dir=direction, period=period,
         cell=_num(data, "cell", here, 2.0, 1.0, 32.0),
         share=_num(data, "share", here, 0.3, 0.0, 1.0),
         deep=_num(data, "deep", here, 0.08, 0.0, 1.0),
         lean=_num(data, "lean", here, 1.0, -4.0, 4.0),
         bend=_num(data, "bend", here, 0.0, -4.0, 4.0),
         shift=_num(data, "shift", here, 10.0, 0.0, 45.0),
         follow=follow, fade=_num(data, "fade", here, 0.85, 0.0, 1.0), style=style, width=width,
         spots=[[float(v) for v in q] for q in spots], tone=tone, ramp_extra=extra,
      )
      out.append(rule)
   return out


# ── 색 셈 ────────────────────────────────────────────────────────────────

def _luma(c) -> float:
   return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]


def _turn(hue: float, toward: float, deg: float) -> float:
   gap = (toward - hue + 180.0) % 360.0 - 180.0
   step = min(abs(gap), deg)
   return (hue + (step if gap >= 0 else -step)) % 360.0


def _hsv(c) -> tuple[float, float, float]:
   h, s, v = colorsys.rgb_to_hsv(c[0] / 255.0, c[1] / 255.0, c[2] / 255.0)
   return h * 360.0, s, v


def _rgb(h: float, s: float, v: float) -> RGB:
   r, g, b = colorsys.hsv_to_rgb((h % 360.0) / 360.0, min(1.0, max(0.0, s)), min(1.0, max(0.0, v)))
   return int(round(r * 255)), int(round(g * 255)), int(round(b * 255))


def _derived(c: RGB, darker: bool) -> RGB:
   h, s, v = _hsv(c)
   if darker:
      return _rgb(_turn(h, 240.0, DERIVED_HUE) if s > 0.05 else h, s * 1.05, v * DERIVED_DARK)
   return _rgb(_turn(h, 60.0, DERIVED_HUE) if s > 0.05 else h, s * 0.85, v + (1.0 - v) * DERIVED_LIGHT)


def _neighbor(c: RGB, ramp: list[RGB], darker: bool) -> RGB:
   """c 에서 한 단 어둡게(또는 밝게) 간 색 : 램프에서 밝기가 바로 다음인 칸, 없으면 셈한 색."""
   lc = _luma(c)
   if darker:
      cand = [r for r in ramp if _luma(r) < lc - LUMA_GAP]
      return max(cand, key=_luma) if cand else _derived(c, True)
   cand = [r for r in ramp if _luma(r) > lc + LUMA_GAP]
   return min(cand, key=_luma) if cand else _derived(c, False)


def _mix(a: RGB, b: RGB, t: float) -> RGB:
   return tuple(int(round(a[k] + (b[k] - a[k]) * t)) for k in range(3))


def shift_color(c: RGB, ramp: list[RGB], amount: float) -> RGB:
   """c 를 램프 단 기준 amount 단 옮긴 색 (음수 = 어둡게). 한 단 넘게는 이웃 칸을 이어 밟는다."""
   darker = amount < 0
   left = abs(amount)
   cur = tuple(int(v) for v in c)
   while left > 1e-6:
      nxt = _neighbor(cur, ramp, darker)
      t = min(1.0, left)
      cur = _mix(cur, nxt, t)
      left -= t
   return cur


def hue_color(c: RGB, deg: float) -> RGB:
   """같은 밝기(luma)로 색조만 deg 돈 색. 무채색이면 그대로."""
   h, s, v = _hsv(c)
   if s < 0.06:
      return tuple(int(x) for x in c)
   out = _rgb(h + deg, s, v)
   lo, lt = _luma(out), _luma(c)
   if lo > 0:
      k = lt / lo
      out = tuple(int(round(min(255.0, x * k))) for x in out)
   return out


# ── 잡음 · 틀 ────────────────────────────────────────────────────────────

def _h(seed: int, *keys) -> np.ndarray:
   return hash01(np.stack([np.asarray(k, dtype=np.int64) for k in keys], axis=1), seed)


def value_noise(xs: np.ndarray, ys: np.ndarray, cell: float, seed: int) -> np.ndarray:
   """칸 좌표 → [0, 1) 값 잡음 (격자 cell 마다 해시 값, 사이는 부드럽게 잇는다)."""
   gx, gy = xs / cell, ys / cell
   x0, y0 = np.floor(gx).astype(np.int64), np.floor(gy).astype(np.int64)
   fx, fy = gx - x0, gy - y0
   fx, fy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
   a = _h(seed, x0, y0)
   b = _h(seed, x0 + 1, y0)
   c = _h(seed, x0, y0 + 1)
   d = _h(seed, x0 + 1, y0 + 1)
   return (a * (1 - fx) + b * fx) * (1 - fy) + (c * (1 - fx) + d * fx) * fy


class _Painter:
   """칸마다 「몇 단 옮기나」 · 「색조 몇 도」를 모아 두었다가 한 번에 칠한다 (같은 입력이면 같은 색)."""

   def __init__(self, arr: np.ndarray):
      self.arr = arr
      self.cache: dict = {}
      self.new: set[RGB] = set()
      self.changed = 0

   def shift(self, ys, xs, amounts, ramp: list[RGB]) -> None:
      key_ramp = tuple(ramp)
      for y, x, a in zip(ys, xs, amounts):
         if a == 0:
            continue
         c = tuple(int(v) for v in self.arr[y, x, :3])
         k = ("s", c, round(float(a), 3), key_ramp)
         if k not in self.cache:
            self.cache[k] = shift_color(c, ramp, float(a))
         self._put(y, x, self.cache[k])

   def hue(self, ys, xs, degs) -> None:
      for y, x, d in zip(ys, xs, degs):
         if d == 0:
            continue
         c = tuple(int(v) for v in self.arr[y, x, :3])
         k = ("h", c, round(float(d), 2))
         if k not in self.cache:
            self.cache[k] = hue_color(c, float(d))
         self._put(y, x, self.cache[k])

   def _put(self, y, x, rgb: RGB) -> None:
      if tuple(int(v) for v in self.arr[y, x, :3]) != rgb:
         self.arr[y, x, :3] = rgb
         self.new.add(rgb)
         self.changed += 1


# ── 모양 · 빛 따르기 (follow) ──────────────────────────────────────────

@dataclass
class _Ctx:
   """질감이 모양 · 빛을 따를 때 보는 칸 정보. (H, W) 배열들."""

   levels: np.ndarray       # 램프 단 (없으면 -1)
   steps: np.ndarray        # 그 칸 재질의 램프 길이
   ndl: np.ndarray          # 노멀 · 빛 (0 ~ 1)
   shine: np.ndarray        # 하이라이트 칸 (재질 highlight 색)
   owner: np.ndarray        # 맞은 도형 번호
   light_dx: int = -1


def _lit(rule: TexRule, ys, xs, ctx: _Ctx) -> np.ndarray:
   """칸마다 밝은 정도 0(그늘) ~ 1(빛). light 는 램프 단, form 은 노멀."""
   if rule.follow == "form":
      return np.clip(ctx.ndl[ys, xs], 0.0, 1.0)
   steps = ctx.steps[ys, xs]
   lv = ctx.levels[ys, xs]
   return np.where(steps > 1, np.clip(lv, 0, None) / np.maximum(1, steps - 1), np.clip(ctx.ndl[ys, xs], 0.0, 1.0))


def _follow(rule: TexRule, ys, xs, amounts: np.ndarray, ctx: _Ctx | None) -> np.ndarray:
   """follow 가 켜져 있으면 결 · 얼룩을 덜어 낸다 : 그늘 쪽 어두운 결은 그대로, 밝은 쪽은 fade 만큼 덜고,
   밝은 결은 가운데 단에만. 덜어 낼 때 칸 하나씩이 아니라 2칸 덩어리 잡음으로 골라 결이 점으로 부서지지 않게 한다."""
   if rule.follow == "none" or ctx is None:
      return amounts
   f = _lit(rule, ys, xs, ctx)
   r = value_noise(xs.astype(float), ys.astype(float), 2.0, rule.seed + 21)
   r = (np.argsort(np.argsort(r)) + 0.5) / max(1, len(r))           # 고르게 펴기 (순위)
   keep_dark = r < 1.0 - rule.fade * f
   keep_light = r < 4.0 * f * (1.0 - f)                              # 밝은 결은 가운데 단에만 — 맨 밝은 띠는 비운다
   out = np.where(amounts < 0, np.where(keep_dark, amounts, 0.0), np.where(keep_light, amounts, 0.0))
   return np.where(ctx.shine[ys, xs], 0.0, out)


def _polar(ys, xs, owner) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
   """도형마다 칸 상자 가운데를 축으로 (둘레 길이 u, 반지름 v, 둥근 도형인가). 둥글지 않으면 u = x, v = y."""
   u = xs.astype(float).copy()
   v = ys.astype(float).copy()
   rnd = np.zeros(len(xs), dtype=bool)
   prims = owner[ys, xs]
   for p in np.unique(prims):
      sel = prims == p
      px, py = xs[sel].astype(float), ys[sel].astype(float)
      w, h = px.max() - px.min() + 1, py.max() - py.min() + 1
      if max(w, h) / max(1.0, min(w, h)) >= ROUND_ASPECT or min(w, h) < 4:
         continue
      cx, cy = (px.max() + px.min()) / 2, (py.max() + py.min()) / 2
      dx, dy = px - cx, py - cy
      rad = np.hypot(dx, dy)
      u[sel] = np.arctan2(dy, dx) * np.maximum(1.0, rad)          # 둘레 길이 (칸)
      v[sel] = rad
      rnd[sel] = True
   return u, v, rnd


# ── 질감마다 (칸마다 「몇 단 옮기나」를 돌려준다) ─────────────────────────

def _wood(rule: TexRule, ys, xs, owner, ctx: _Ctx | None = None) -> np.ndarray:
   out = np.zeros(len(xs))
   prims = owner[ys, xs]
   cu = cv = rnd = None
   if (rule.follow == "form" and ctx is not None) or rule.dir == "around":
      cu, cv, rnd = _polar(ys, xs, owner)
   for p in np.unique(prims):
      sel = prims == p
      py, px = ys[sel], xs[sel]
      w, h = px.max() - px.min() + 1, py.max() - py.min() + 1
      if rnd is not None and rnd[sel].all():
         # 둥근 도형 : 결이 둘레를 따라 돈다 (줄 = 반지름, 줄 안 위치 = 둘레 길이)
         u = np.floor(cu[sel]).astype(np.int64)
         v = np.floor(cv[sel]).astype(np.int64)
      else:
         along_x = rule.dir == "x" or (rule.dir in ("auto", "around") and w >= h)   # around : 둥글지 않으면 auto
         u = px if along_x else py
         v = (py - py.min()) if along_x else (px - px.min())
      pid = np.full(len(u), int(p) + 1, dtype=np.int64)
      lane_on = _h(rule.seed, pid, v, np.zeros_like(v)) < rule.density
      lane_light = _h(rule.seed, pid, v, np.ones_like(v)) < rule.light
      off = np.floor(_h(rule.seed, pid, v, np.full_like(v, 2)) * rule.length).astype(np.int64)
      seg = np.floor((u + off) / rule.length).astype(np.int64)
      seg_on = _h(rule.seed + 1, pid, v, seg) >= rule.gap
      on = lane_on & seg_on
      amounts = np.where(on, np.where(lane_light, rule.strength, -rule.strength), 0.0)
      if rule.knots > 0:
         n = int(len(u) * rule.knots / 100.0 + _h(rule.seed + 2, pid[:1], pid[:1])[0])
         for k in range(n):
            pick = int(_h(rule.seed + 3, pid[:1], np.array([k]))[0] * len(u))
            ku, kv = u[pick], v[pick]
            amounts = np.where((v == kv) & (u == ku), -2 * rule.strength, amounts)
            amounts = np.where((v == kv) & (np.abs(u - ku) == 1), np.minimum(amounts, -rule.strength), amounts)
            amounts = np.where((np.abs(v - kv) == 1) & (u == ku), np.minimum(amounts, -rule.strength), amounts)
      out[sel] = amounts
   return out


def _weave(rule: TexRule, ys, xs) -> np.ndarray:
   p = rule.period
   s, d = xs + ys, xs - ys
   i, j = np.floor_divide(s, p), np.floor_divide(d, p)
   a, b = np.mod(s, p), np.mod(d, p)
   horiz = np.mod(i + j, 2) == 0
   edge = np.where(horiz, a == 0, b == 0)
   mid = np.where(horiz, a == p // 2, b == p // 2)
   jit = _h(rule.seed, i, j) < rule.gap          # 가끔 한 칸 짜임은 결을 빼 덜 기계적으로
   amounts = np.where(edge & ~jit, -rule.strength, 0.0)
   if rule.light > 0:
      amounts = np.where(mid & (_h(rule.seed + 1, i, j) < rule.light), rule.strength, amounts)
   return amounts


def _noise_xy(rule: TexRule, ys, xs, ctx: _Ctx | None) -> tuple[np.ndarray, np.ndarray]:
   """잡음을 뽑을 좌표. form 이면 둥근 도형은 (둘레 길이 / 늘임, 반지름) — 얼룩이 둘레를 따라 휜다."""
   if rule.follow == "form" and ctx is not None:
      u, v, rnd = _polar(ys, xs, ctx.owner)
      return np.where(rnd, u / CURVE_STRETCH, xs), np.where(rnd, v, ys)
   return xs, ys


def _mottle(rule: TexRule, ys, xs, ctx: _Ctx | None = None) -> np.ndarray:
   nx, ny = _noise_xy(rule, ys, xs, ctx)
   n = 0.65 * value_noise(nx, ny, rule.cell, rule.seed) + 0.35 * value_noise(nx, ny, max(1.0, rule.cell / 2), rule.seed + 7)
   lo, hi = np.quantile(n, rule.share / 2), np.quantile(n, 1 - rule.share / 2)
   deep = np.quantile(n, rule.deep) if rule.deep > 0 else -1.0
   amounts = np.where(n < lo, -rule.strength, np.where(n > hi, rule.strength, 0.0))
   return np.where(n < deep, -2 * rule.strength, amounts)


def _fold(rule: TexRule, ys, xs, own: np.ndarray) -> np.ndarray:
   h, w = own.shape
   start = _h(rule.seed, xs, ys) < rule.density
   amount = np.zeros((h, w))
   for y0, x0, r1, r2 in zip(ys[start], xs[start], _h(rule.seed + 1, xs, ys)[start], _h(rule.seed + 2, xs, ys)[start]):
      length = max(2, int(round(rule.length * (0.6 + 0.8 * r1))))
      lean = rule.lean * (0.5 + r2)
      for k in range(length):
         t = k / max(1, length - 1)
         x = int(round(x0 + lean * k * 0.5 + rule.bend * (t * t - t) * length * 0.5))
         y = y0 + k
         if 0 <= y < h and 0 <= x < w and own[y, x]:
            amount[y, x] = -rule.strength
            if rule.light > 0 and 0 <= x - 1 and own[y, x - 1] and amount[y, x - 1] == 0 and r1 < rule.light * 2:
               amount[y, x - 1] = rule.strength * 0.5
   return amount[ys, xs]


def _fold_mass(rule: TexRule, ys, xs, own: np.ndarray, light_dx: int) -> np.ndarray:
   """덩어리 주름 : 가운데가 넓고(width) 끝이 가는 그늘 판을 아래로 늘어뜨리고, 빛 쪽 가장자리에 한 칸 밝은 테.

   게임 옷 주름은 가는 줄이 아니라 2 ~ 3칸 너비 그늘 조각이다 (손님 셔츠 실측). 판끼리 겹치면 하나로 뭉친다.
   """
   h, w = own.shape
   shade = np.zeros((h, w), dtype=bool)
   rim = np.zeros((h, w), dtype=bool)
   side = light_dx if light_dx != 0 else -1
   if rule.spots:
      # 자리 지정 : 적은 자리에서만 판을 늘어뜨린다 (어깨 아래 · 팔꿈치 · 주머니 위 · 머리 빛 띠). 해시는 모양 흔들림에만
      pts = np.array([[int(round(q[0])), int(round(q[1]))] for q in rule.spots], dtype=np.int64)
      starts = [(int(y), int(x), r1, r2, q[2] if len(q) > 2 else None) for (x, y), q, r1, r2 in
                zip(pts, rule.spots, _h(rule.seed + 1, pts[:, 0], pts[:, 1]), _h(rule.seed + 2, pts[:, 0], pts[:, 1]))]
   else:
      start = _h(rule.seed, xs, ys) < rule.density
      starts = [(y0, x0, r1, r2, None) for y0, x0, r1, r2 in
                zip(ys[start], xs[start], _h(rule.seed + 1, xs, ys)[start], _h(rule.seed + 2, xs, ys)[start])]
   for y0, x0, r1, r2, fixed in starts:
      if not (0 <= y0 < h and 0 <= x0 < w) or (shade[y0, x0] and not rule.spots):
         continue
      length = max(3, int(round(rule.length * (0.6 + 0.8 * r1)))) if fixed is None else max(2, int(round(fixed)))
      lean = rule.lean * (r2 - 0.5)
      for k in range(length):
         t = k / max(1, length - 1)
         wk = max(1, int(round(rule.width * np.sin(np.pi * (0.15 + 0.7 * t)) ** 0.7)))
         xc = x0 + lean * k * 0.5 + rule.bend * (t * t - t) * length * 0.5
         xl = int(round(xc - (wk - 1) / 2))
         y = y0 + k
         if not 0 <= y < h:
            continue
         for x in range(xl, xl + wk):
            if 0 <= x < w and own[y, x]:
               shade[y, x] = True
         edge = xl - 1 if side < 0 else xl + wk
         if rule.tone == "shade" and rule.light > 0 and 0 <= edge < w and own[y, edge] and \
               _h(rule.seed + 4, np.array([edge]), np.array([y]))[0] < rule.light * 2:
            rim[y, edge] = True
   if rule.tone == "light":
      return np.where(shade, rule.strength, 0.0)[ys, xs]
   amount = np.where(shade, -rule.strength, np.where(rim, rule.strength, 0.0))
   return amount[ys, xs]


def _hue_side(rule: TexRule, ys, xs, ctx: _Ctx | None = None) -> np.ndarray:
   nx, ny = _noise_xy(rule, ys, xs, ctx)
   n = value_noise(nx, ny, rule.cell, rule.seed + 11)
   lo, hi = np.quantile(n, rule.share / 2), np.quantile(n, 1 - rule.share / 2)
   return np.where(n < lo, -rule.shift, np.where(n > hi, rule.shift, 0.0))


def _context(spec, arr, hits, mat_idx, levels) -> _Ctx:
   h, w = mat_idx.shape
   names = list(spec.materials)
   steps = np.ones((h, w), dtype=np.int64)
   shine = np.zeros((h, w), dtype=bool)
   for i, name in enumerate(names):
      m = spec.materials[name]
      own = mat_idx == i
      steps[own] = len(m.ramp)
      if m.highlight is not None:
         shine |= own & np.all(arr[:, :, :3] == np.array(m.highlight, dtype=arr.dtype), axis=2)
   light = np.asarray(spec.light, dtype=float)
   ndl = np.clip(hits.normal @ light, 0.0, 1.0)
   lv = levels if levels is not None else np.full((h, w), -1, dtype=np.int64)
   return _Ctx(lv, steps, ndl, shine, hits.owner, LIGHT_DX.get(getattr(spec, "light_word", "top_left"), -1))


def apply(spec, arr: np.ndarray, hits, mat_idx: np.ndarray, levels: np.ndarray | None = None) -> tuple[int, list[RGB]]:
   """명세 `texture` 규칙을 차례대로 얹는다. (바꾼 칸 수, 새로 생긴 색 목록 — 팔레트 · lint 용).

   levels : 칸마다 램프 단 (shade_pixels 결과). follow 가 쓴다 — 없으면 노멀로만 잰다.
   """
   painter = _Painter(arr)
   names = list(spec.materials)
   ctx = _context(spec, arr, hits, mat_idx, levels) if any(r.follow != "none" for r in spec.texture) else None
   for rule in spec.texture:
      if rule.style == "mass" and rule.tone == "band":
         _band(rule, spec, names, mat_idx, painter)
         continue
      for m_i, name in enumerate(names):
         if not any(fnmatch.fnmatchcase(name, p) for p in rule.on):
            continue
         own = mat_idx == m_i
         if not own.any():
            continue
         ys, xs = np.nonzero(own)
         ramp = list(spec.materials[name].ramp) + list(rule.ramp_extra)
         if rule.kind == "hue_side":
            degs = _hue_side(rule, ys, xs, ctx)
            if rule.follow != "none" and ctx is not None:
               degs = np.where(ctx.shine[ys, xs], 0.0, degs)
            painter.hue(ys, xs, degs)
            continue
         if rule.kind == "wood_grain":
            amounts = _wood(rule, ys, xs, hits.owner, ctx)
         elif rule.kind == "weave":
            amounts = _weave(rule, ys, xs)
         elif rule.kind == "mottle":
            amounts = _mottle(rule, ys, xs, ctx)
         elif rule.style == "mass":
            amounts = _fold_mass(rule, ys, xs, own, LIGHT_DX.get(getattr(spec, "light_word", "top_left"), -1))
         else:
            amounts = _fold(rule, ys, xs, own)
         painter.shift(ys, xs, _follow(rule, ys, xs, amounts, ctx), ramp)
   solid = arr[:, :, 3] > 0
   used = {tuple(int(v) for v in c) for c in np.unique(arr[solid][:, :3], axis=0)} if solid.any() else set()
   return painter.changed, sorted(painter.new & used)


def _band(rule: TexRule, spec, names: list[str], mat_idx: np.ndarray, painter: _Painter) -> None:
   """tone band : 맞는 재질 칸을 하나로 보고 빛 띠 판을 놓은 뒤, 띠 안을 모두 한 색(첫 재질 주색 + strength 단)으로 칠한다."""
   picked = [i for p in rule.on for i, n in enumerate(names) if fnmatch.fnmatchcase(n, p)]
   picked = list(dict.fromkeys(picked))
   if not picked:
      return
   own = np.isin(mat_idx, picked)
   ref_own = mat_idx == picked[0]
   if not ref_own.any():
      return
   ys, xs = np.nonzero(own)
   light = dataclasses.replace(rule, tone="light")
   hit = _fold_mass(light, ys, xs, own, LIGHT_DX.get(getattr(spec, "light_word", "top_left"), -1)) > 0
   cols, counts = np.unique(painter.arr[ref_own][:, :3], axis=0, return_counts=True)
   ref = tuple(int(v) for v in cols[int(counts.argmax())])
   color = shift_color(ref, list(spec.materials[names[picked[0]]].ramp) + list(rule.ramp_extra), rule.strength)
   for y, x in zip(ys[hit], xs[hit]):
      painter._put(y, x, color)
