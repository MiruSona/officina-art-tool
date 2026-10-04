"""kind 별 처리기 — 그리는 법과 셈은 여기, 숫자는 템플릿 JSON 에 (설계 8-2).

처리기 하나가 하는 일
- `validate_values` : JSON 의 `values`(프리셋까지 겹친 것)를 읽어 본다. 틀리면 TemplateError.
- `compute`         : 고른 크기에 맞춘 셈(줄 y · 상자 · 점 자리). `template show` 의 `lines` 칸이 된다.
- `guide`           : 가이드 겹 마스크 셋(선 · 점 · 지키는 자리). 칠하기는 `guide.py` 가 한다.
- `frames`          : 프레임별 밑그림(effect · cycle · motion).
- `masks`           : 겹별 마스크(흰 = 그릴 자리). 서로 안 겹친다 — `split` 의 `masks` 에 그대로 쓴다.

좌표 약속은 `draw/shapes.py` 와 같다 : 크기는 (너비, 높이), 칸 (x, y) 의 가운데가 좌표 (x, y).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .. import image
from ..draw import shapes
from ..palette import auto_hue_step, parse_hex, shade
from . import TemplateError

Mask = np.ndarray
Size = tuple[int, int]

WHITE = (255, 255, 255, 255)
ALL_MUST = ("canvas", "alpha", "scale", "palette")


def rhu(value: float) -> int:
   """0.5 를 늘 위로 올리는 반올림. 파이썬 round 는 짝수 쪽으로 가서 크기마다 들쭉날쭉해진다."""
   return int(math.floor(value + 0.5))


def fit(total: int, part: int) -> int:
   """가운데 맞춤이 좌우 같게 되도록 part 의 홀짝을 total 에 맞춘다(한 칸 늘리거나, 못 늘리면 줄인다)."""
   if (total - part) % 2:
      part = part + 1 if part + 1 <= total else part - 1
   return max(1, part)


@dataclass
class Guide:
   """가이드 겹 셋. 선 `#FF00FF` · 점 `#00FFFF` · 지키는 자리 `#FFFF00` 로 칠한다(guide.py)."""

   line: Mask
   dot: Mask
   keep: Mask

   @classmethod
   def blank(cls, size: Size) -> "Guide":
      return cls(shapes.empty(size), shapes.empty(size), shapes.empty(size))


@dataclass
class Ctx:
   """처리기가 받는 것 : 프리셋까지 겹친 템플릿 · 고른 크기 · 크기 표를 고른 값 · 프로필(없으면 None)."""

   tpl: dict
   size: Size
   values: dict
   prof: object | None = None
   extra: dict = field(default_factory=dict)

   @property
   def w(self) -> int:
      return self.size[0]

   @property
   def h(self) -> int:
      return self.size[1]


# ── 값 읽기 도우미 ───────────────────────────────────


def _fail(where, text: str) -> TemplateError:
   return TemplateError(f"템플릿이 잘못됐다 : {text} - {where}")


def _is_num(v) -> bool:
   return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _is_int(v) -> bool:
   return isinstance(v, int) and not isinstance(v, bool)


def _table_key(key) -> bool:
   """크기 표 열쇠 : 숫자 글자(짧은 변) 또는 "WxH"(그 크기에만)."""
   if not isinstance(key, str):
      return False
   if key.isdigit():
      return True
   w, sep, h = key.partition("x")
   return bool(sep) and w.isdigit() and h.isdigit()


def is_table(value) -> bool:
   """크기 표 : 열쇠가 모두 숫자 글자 · "WxH" 인 사전. 예 {"8": 1.5, "16": 2, "48x64": 1.7}.

   숫자 열쇠는 짧은 변으로 고르고, "WxH" 열쇠는 그 크기와 꼭 같을 때만 쓴다(숫자 열쇠보다 앞선다).
   숫자 열쇠가 하나는 있어야 한다 — 다른 크기에서 고를 값이 없으면 안 된다.
   """
   return (
      isinstance(value, dict) and bool(value)
      and all(_table_key(k) for k in value)
      and any(k.isdigit() for k in value)
   )


def pick(value, size: Size):
   """크기 표면 ① "WxH" 열쇠가 그 크기와 같으면 그 값 ② 아니면 「짧은 변 이하인 숫자 열쇠 중 가장 큰 것」의 값,
   다 크면 가장 작은 숫자 열쇠의 값. 표가 아니면 그대로."""
   if not is_table(value):
      return value
   exact = f"{size[0]}x{size[1]}"
   if exact in value:
      return value[exact]
   side = min(size)
   keys = sorted(int(k) for k in value if k.isdigit())
   chosen = keys[0]
   for k in keys:
      if k <= side:
         chosen = k
   return value[str(chosen)]


def resolve_values(values: dict, size: Size) -> dict:
   return {k: pick(v, size) for k, v in values.items()}


def _need(values: dict, key: str, test, what: str, where, table_ok: bool = False):
   if key not in values:
      raise _fail(where, f"values.{key} 가 없다 ({what})")
   value = values[key]
   items = value.values() if (table_ok and is_table(value)) else [value]
   if not all(test(v) for v in items):
      raise _fail(where, f"values.{key} 는 {what}{' (또는 크기 표)' if table_ok else ''} : {value!r}")
   return value


def _pos_num(v) -> bool:
   return _is_num(v) and v > 0


def _pos_int(v) -> bool:
   return _is_int(v) and v > 0


def _ratio(v) -> bool:
   return _is_num(v) and 0 <= v < 1


# ── 처리기 바탕 ──────────────────────────────────────


class Kind:
   name = ""
   value_keys: tuple[str, ...] = ()
   flat_presets = False      # 프리셋 칸을 전부 values 로 보낸다
   frames_field = False      # 맨 위 frames 칸(프레임별 모양 목록)을 쓴다
   needs_frames = False
   has_layers = True
   must_default: tuple[str, ...] = ALL_MUST
   mask_files = False        # _mask_<겹>.png 를 낸다
   preview = "guide"         # guide · frames · overlay · tile2x2 · swatch
   # 미리보기(_preview.png) 옆에 찍는 이름표 : (셈 결과 `lines` 의 열쇠, 한글 이름, 가이드 색 line · dot · keep).
   # 값이 정수면 그 y(이름이 _x 로 끝나면 x), 네 정수면 상자 위 y, [x, y] 목록이면 점마다 하나. 1배 가이드에는 안 찍는다.
   labels: tuple[tuple[str, str, str], ...] = ()

   def validate_values(self, tpl: dict, where) -> None:
      values = tpl.get("values") or {}
      for size in tpl["sizes"]:
         self.check_values(resolve_values(values, tuple(size)), tuple(size), tpl, where)

   def check_values(self, values: dict, size: Size, tpl: dict, where) -> None:
      if "frame_ms" in values:
         _need(values, "frame_ms", _pos_int, "양의 정수 ms", where)

   def validate_frames(self, frames, where) -> None:
      raise _fail(where, f"kind {self.name} 는 frames 칸을 안 쓴다")

   def compute(self, ctx: Ctx) -> dict:
      return {}

   def guide(self, ctx: Ctx, calc: dict) -> Guide:
      return Guide.blank(ctx.size)

   def frame_count(self, ctx: Ctx) -> int | None:
      return None

   def frames(self, ctx: Ctx, calc: dict) -> list[image.RGBA]:
      return []

   def masks(self, ctx: Ctx, calc: dict) -> dict[str, Mask]:
      return {}


# ── character · parts · cycle ────────────────────────


CHAR_KEYS = (
   "heads", "top_ratio", "foot_ratio", "head_aspect", "torso_ratio", "crotch_ratio", "knee_ratio",
   "eye_h", "eye_w", "eye_gap", "eye_ratio", "cheek", "hair_side", "note",
)
# 몸통(턱 아래 ~ 가랑이 위)은 적어도 이만큼 남긴다 — 0 이면 옷 마스크가 빈다(리뷰 R2-H1)
MIN_TORSO = 2


class Character(Kind):
   """작은 캐릭터 밑판. 크기별 등신 · 머리 상자 · 눈 줄 · 눈 카드 · baseline · 가랑이 · 무릎 줄.

   비율 약속
   - `heads` : 몸 높이(top ~ baseline) ÷ 머리 높이.
   - `crotch_ratio` : **턱 아래 몸**(턱 다음 줄 ~ baseline) 중 몸통 몫. 나머지가 다리다. 몸통은 적어도 MIN_TORSO 줄.
   - `knee_ratio` : 몸 높이 중 baseline 에서 무릎 줄까지 몫(가랑이보다 위로는 안 간다).
   - `eye_ratio` : 눈 줄이 머리 위(0) ~ 턱(1) 의 어디인가. 없으면 0.5. SD 는 0.7 근처(이마가 넓다).
   - `cheek` : 볼 칸 너비 px (0 = 없음). 눈 아래 한 줄 띄고 2줄, 눈 가운데 아래.
   - `hair_side` : 머리 상자 양옆 중 옆머리 몫(0 ~ 0.5). 눈 줄 위 앞머리에 더해 턱까지 내려온다.
   """

   name = "character"
   value_keys = CHAR_KEYS + ("frame_ms",)
   mask_files = True
   labels = (
      ("head", "머리 상자", "line"),
      ("eye_box_l", "눈 카드", "dot"),
      ("mouth", "입", "dot"),
      ("crotch_y", "가랑이 줄", "line"),
      ("knee_y", "무릎 줄", "line"),
      ("baseline_y", "baseline (발 닿는 줄)", "line"),
   )

   def check_values(self, values, size, tpl, where) -> None:
      super().check_values(values, size, tpl, where)
      _need(values, "heads", _pos_num, "양수 등신", where)
      for key in ("top_ratio", "foot_ratio", "crotch_ratio", "knee_ratio"):
         _need(values, key, _ratio, "0 이상 1 미만", where)
      for key in ("head_aspect", "torso_ratio"):
         _need(values, key, _pos_num, "양수", where)
      for key in ("eye_h", "eye_w"):
         _need(values, key, _pos_int, "양의 정수 px", where)
      _need(values, "eye_gap", lambda v: _is_int(v) and v >= 0, "0 이상 정수 px", where)
      if "eye_ratio" in values:
         _need(values, "eye_ratio", lambda v: _is_num(v) and 0 <= v <= 1, "0 ~ 1", where)
      if "cheek" in values:
         _need(values, "cheek", lambda v: _is_int(v) and v >= 0, "0 이상 정수 px", where)
      if "hair_side" in values:
         _need(values, "hair_side", lambda v: _is_num(v) and 0 <= v < 0.5, "0 이상 0.5 미만", where)
      if "note" in values and not isinstance(values["note"], str):
         raise _fail(where, f"values.note 는 글자(또는 크기 표)다 : {values['note']!r}")
      calc = self.compute(Ctx(tpl, size, values))
      if calc["head"][3] - calc["head"][1] < 2 or calc["eye_box_l"][1] < calc["head"][1]:
         raise _fail(where, f"{size[0]}x{size[1]} 에서 머리가 너무 작다 : {calc['head']}")
      if calc["eye_box_l"][3] > calc["head"][3]:
         raise _fail(where, f"{size[0]}x{size[1]} 에서 눈 카드가 턱 아래로 나간다 : {calc['eye_box_l']} · 머리 {calc['head']}")
      torso, legs = calc["torso"], calc["legs"]
      if torso[3] <= torso[1] or legs[3] <= legs[1]:
         raise _fail(where, f"{size[0]}x{size[1]} 에서 몸통 · 다리 칸이 없다 (등신 {values['heads']} 가 너무 낮다) : 몸통 {torso} · 다리 {legs}")

   def compute(self, ctx: Ctx) -> dict:
      v, w, h = ctx.values, ctx.w, ctx.h
      top = int(math.floor(h * v["top_ratio"]))
      baseline = h - 1 - int(math.floor(h * v["foot_ratio"]))
      body_h = baseline - top + 1
      # 턱 아래로 몸통 MIN_TORSO 줄 + 다리 1줄은 남긴다 (2등신 이하 · 8px 에서도 옷 칸이 빈칸이 안 되게)
      head_room = max(2, body_h - MIN_TORSO - 1)
      head_h = min(head_room, max(2, rhu(body_h / v["heads"])))
      head_w = fit(w, min(w, max(2, rhu(head_h * v["head_aspect"]))))
      head_x0 = (w - head_w) // 2
      chin = top + head_h - 1

      # 눈 줄 = 머리 위 ~ 턱 사이 eye_ratio 자리. 카드 높이가 짝수면 눈 줄이 카드 위쪽 가운데 줄이다.
      eye_h, eye_w, gap = int(v["eye_h"]), int(v["eye_w"]), int(v["eye_gap"])
      eye_line = top + int(math.floor((chin - top) * float(v.get("eye_ratio", 0.5))))
      eye_top = eye_line - (eye_h - 1) // 2
      eye_top = max(top, min(eye_top, chin - eye_h + 1))
      eye_bottom = eye_top + eye_h - 1
      pair = fit(w, 2 * eye_w + gap)
      gap += pair - (2 * eye_w + gap)
      left_x0 = (w - pair) // 2
      right_x0 = left_x0 + eye_w + gap

      mouth = None
      if eye_bottom + 1 <= chin:
         mouth_y = eye_bottom + 1 + (chin - eye_bottom - 1) // 2
         mouth_w = fit(w, max(1, min(gap, eye_w)))
         mouth_x0 = (w - mouth_w) // 2
         mouth = [mouth_x0, mouth_y, mouth_x0 + mouth_w, mouth_y + 1]

      cheeks = []
      cheek = int(v.get("cheek", 0) or 0)
      if cheek and eye_bottom + 2 <= chin:
         cy0, cy1 = eye_bottom + 2, min(chin, eye_bottom + 3) + 1
         lx = left_x0 + eye_w // 2 - cheek // 2         # 눈 바로 아래 가운데
         rx = w - lx - cheek                            # 거울
         for x0 in (lx, rx):
            cheeks.append([max(head_x0, x0), cy0, min(head_x0 + head_w, x0 + cheek), cy1])
         if mouth and mouth[1] >= cy0:
            # 입과 볼이 같은 줄이면 볼이 입을 안 덮게 안쪽 끝을 1칸 띄운다
            cheeks[0][2] = min(cheeks[0][2], mouth[0] - 1)
            cheeks[1][0] = max(cheeks[1][0], mouth[2] + 1)
         cheeks = [c for c in cheeks if c[2] > c[0]]

      side = int(math.floor(head_w * float(v.get("hair_side", 0) or 0)))
      side = min(side, max(0, left_x0 - head_x0 - 1))     # 옆머리가 눈 카드를 덮지 않게 (눈과 사이 1칸)

      below = baseline - chin                  # 턱 다음 줄 ~ baseline 줄 수
      torso_h = rhu(below * v["crotch_ratio"])
      torso_h = max(min(MIN_TORSO, below - 1), min(torso_h, below - 1))
      crotch = chin + 1 + max(1, torso_h)
      crotch = min(crotch, baseline)
      torso_w = fit(w, min(w, max(2, rhu(head_w * v["torso_ratio"]))))
      torso_x0 = (w - torso_w) // 2
      knee = min(baseline, max(crotch, baseline - rhu(body_h * v["knee_ratio"])))
      return {
         "top_y": top,
         "baseline_y": baseline,
         "body_h": body_h,
         "heads": v["heads"],
         "head_h": head_h,
         "head_w": head_w,
         # 상자는 [x0, y0, x1, y1) — 끝을 뺀다(split 규칙 · shapes.box 와 같다)
         "head": [head_x0, top, head_x0 + head_w, chin + 1],
         "chin_y": chin,
         "eye_line_y": eye_line,
         "eye_box_l": [left_x0, eye_top, left_x0 + eye_w, eye_bottom + 1],
         "eye_box_r": [right_x0, eye_top, right_x0 + eye_w, eye_bottom + 1],
         "mouth": mouth,
         "cheeks": cheeks,
         "hair_side": side,
         "torso": [torso_x0, chin + 1, torso_x0 + torso_w, crotch],
         "crotch_y": crotch,
         "knee_y": knee,
         "legs": [torso_x0, crotch, torso_x0 + torso_w, baseline + 1],
      }

   def _face(self, size: Size, calc: dict) -> Mask:
      face = _box(size, calc["eye_box_l"]) | _box(size, calc["eye_box_r"])
      if calc["mouth"]:
         face |= _box(size, calc["mouth"])
      for cheek in calc.get("cheeks") or []:
         face |= _box(size, cheek)
      return face

   def guide(self, ctx: Ctx, calc: dict) -> Guide:
      size, w = ctx.size, ctx.w
      g = Guide.blank(size)
      g.line |= _box(size, calc["head"], filled=False)
      g.line |= shapes.line(size, 0, calc["baseline_y"], w - 1, calc["baseline_y"])
      # 가랑이 · 무릎 줄은 양 끝 2칸 눈금만 — 몸 자리를 가리지 않게
      tick = min(2, w)
      for y in (calc["crotch_y"], calc["knee_y"]):
         g.line |= shapes.line(size, 0, y, tick - 1, y) | shapes.line(size, w - tick, y, w - 1, y)
      g.dot |= self._face(size, calc)
      return g

   def masks(self, ctx: Ctx, calc: dict) -> dict[str, Mask]:
      size = ctx.size
      head = _box(size, calc["head"])
      face = self._face(size, calc)
      # 앞머리 = 눈 카드 위 한 줄까지(눈썹 자리는 피부로 남긴다), 옆머리 = 양옆 hair_side 칸이 턱까지
      eye_top = calc["eye_box_l"][1]
      gap = max(1, rhu(calc["head_h"] * 0.06))         # 큰 머리일수록 이마가 넓다 (48×64 sd 는 2줄)
      bang = max(calc["head"][1] + 1, eye_top - gap)
      bang = min(bang, eye_top)
      hair = head & (_rows(size) < bang)
      side = calc.get("hair_side") or 0
      if side:
         x0, _, x1, _ = calc["head"]
         cols = _cols(size)
         hair |= head & ((cols < x0 + side) | (cols >= x1 - side))
      hair &= ~face
      skin = head & ~hair & ~face
      return {
         "body": skin | _box(size, calc["legs"]),
         "cloth": _box(size, calc["torso"]),
         "face": face,
         "hair": hair,
      }


class Parts(Character):
   """`char_small` 비율로 겹 자리를 잡아 겹별 마스크와 split.json 초안을 낸다. 얼굴은 눈 · 입 · 볼 칸만.

   아랫옷 = 몸통 아래쪽 `waist_ratio` 몫(바지 허리 ~ 가랑이) + 가랑이 ~ 무릎 다리. sd 는 반바지라 허리 몫이 크고 다리는 맨살이다.
   """

   name = "parts"
   value_keys = Character.value_keys + ("waist_ratio",)

   def check_values(self, values, size, tpl, where) -> None:
      if "waist_ratio" in values:
         _need(values, "waist_ratio", lambda v: _is_num(v) and 0 <= v < 1, "0 이상 1 미만", where)
      super().check_values(values, size, tpl, where)

   def compute(self, ctx: Ctx) -> dict:
      calc = super().compute(ctx)
      x0, y0, x1, y1 = calc["torso"]
      cut = rhu((y1 - y0) * float(ctx.values.get("waist_ratio", 0) or 0))
      cut = min(cut, y1 - y0 - 1)           # 윗옷은 적어도 1줄
      calc["waist_y"] = y1 - max(0, cut)
      return calc

   def masks(self, ctx: Ctx, calc: dict) -> dict[str, Mask]:
      size = ctx.size
      base = super().masks(ctx, calc)
      legs = _box(size, calc["legs"])
      upper_legs = legs & (_rows(size) <= calc["knee_y"])
      x0, _, x1, y1 = calc["torso"]
      hips = _box(size, [x0, calc["waist_y"], x1, y1])
      return {
         "body": (base["body"] & ~legs) | (legs & ~upper_legs),
         "cloth_top": base["cloth"] & ~hips,
         "cloth_bottom": upper_legs | hips,
         "face": base["face"],
         "hair": base["hair"],
      }


class Cycle(Character):
   """걷기 · 달리기 · idle · 공격 프레임 틀. 프레임별 몸 위아래(bob)는 JSON 의 표 그대로 쓴다."""

   name = "cycle"
   value_keys = CHAR_KEYS + ("frame_ms", "frames", "bob", "order", "phases")
   flat_presets = True
   mask_files = True
   preview = "frames"
   labels = (("baseline_y", "baseline (발 닿는 줄)", "line"),)

   def check_values(self, values, size, tpl, where) -> None:
      # bob 을 먼저 본다 — 부모 검사가 compute 를 부르고, compute 가 bob 을 읽는다
      frames = _need(values, "frames", _pos_int, "양의 정수 프레임 수", where)
      _need(values, "frame_ms", _pos_int, "양의 정수 ms", where)
      bob = values.get("bob")
      if not isinstance(bob, list) or len(bob) != frames or not all(_is_int(b) for b in bob):
         raise _fail(where, f"values.bob 은 프레임 수({frames})만큼의 정수 목록이다 : {bob!r}")
      for key in ("order", "phases"):
         row = values.get(key)
         if row is not None and (not isinstance(row, list) or len(row) != frames):
            raise _fail(where, f"values.{key} 는 프레임 수({frames})만큼의 목록이다 : {row!r}")
      super().check_values(values, size, tpl, where)

   def frame_count(self, ctx: Ctx) -> int:
      return int(ctx.values["frames"])

   def compute(self, ctx: Ctx) -> dict:
      calc = super().compute(ctx)
      bob = [int(b) for b in ctx.values["bob"]]
      calc["bob"] = bob
      calc["head_top_y"] = [calc["top_y"] + b for b in bob]
      return calc

   def guide(self, ctx: Ctx, calc: dict) -> Guide:
      g = super().guide(ctx, calc)
      # 머리 줄이 오르내리는 폭을 왼쪽 끝 점으로 : 가장 높은 줄 ~ 가장 낮은 줄
      ys = sorted(set(calc["head_top_y"]))
      for y in ys:
         if 0 <= y < ctx.h:
            g.dot |= shapes.dot(ctx.size, 0, y)
      return g

   def frames(self, ctx: Ctx, calc: dict) -> list[image.RGBA]:
      size, out = ctx.size, []
      for b in calc["bob"]:
         body = _box(size, _shift(calc["head"], b)) | _box(size, _shift(calc["torso"], b))
         x0, y0, x1, y1 = calc["legs"]
         if y0 + b < y1:
            body |= _box(size, [x0, y0 + b, x1, y1])
         arr = shapes.to_image(body, "#FFFFFF")
         shapes.paint(arr, shapes.line(size, 0, calc["baseline_y"], ctx.w - 1, calc["baseline_y"]), "#FF00FF")
         out.append(arr)
      return out


# ── background ───────────────────────────────────────


class Background(Kind):
   """화면 배경 층 틀. `scene` 이 outdoor(기본)면 하늘 · 먼 층 · 앞 층 띠, indoor 면 천장 · 벽 · 바닥 띠.
   둘 다 화면비 자르는 줄 · 안전 영역을 같이 그린다."""

   name = "background"
   value_keys = (
      "scene", "sky_ratio", "far_ratio", "front_ratio", "sky_colors", "far_colors", "front_colors",
      "ceiling_ratio", "floor_ratio", "ceiling_colors", "wall_colors", "floor_colors",
      "safe_top", "safe_side", "safe_bottom", "crops",
   )
   SCENES = ("outdoor", "indoor")
   labels = (
      ("safe", "안전 영역", "keep"),
      ("sky_end_y", "하늘 끝 줄", "line"),
      ("far_end_y", "먼 층 끝 줄", "line"),
      ("front_y", "앞 층 줄", "line"),
      ("ceiling_end_y", "천장 끝 줄", "line"),
      ("floor_y", "벽-바닥 경계", "line"),
   )
   mask_files = True

   def check_values(self, values, size, tpl, where) -> None:
      scene = values.get("scene", "outdoor")
      if scene not in self.SCENES:
         raise _fail(where, f"values.scene 은 {' · '.join(self.SCENES)} 중 하나다 : {scene!r}")
      for key in ("safe_top", "safe_side", "safe_bottom"):
         _need(values, key, _ratio, "0 이상 1 미만", where)
      if scene == "indoor":
         for key in ("ceiling_ratio", "floor_ratio"):
            _need(values, key, _ratio, "0 이상 1 미만", where)
         if values["ceiling_ratio"] + values["floor_ratio"] >= 1:
            raise _fail(where, "ceiling_ratio + floor_ratio 는 1 보다 작아야 한다(가운데 벽 자리)")
         for key in ("ceiling_colors", "wall_colors", "floor_colors"):
            _need(values, key, _pos_int, "양의 정수 색 수", where)
      else:
         for key in ("sky_ratio", "far_ratio", "front_ratio"):
            _need(values, key, _ratio, "0 이상 1 미만", where)
         if values["sky_ratio"] + values["far_ratio"] + values["front_ratio"] >= 1:
            raise _fail(where, "sky_ratio + far_ratio + front_ratio 는 1 보다 작아야 한다(가운데 구조물 자리)")
         for key in ("sky_colors", "far_colors", "front_colors"):
            _need(values, key, _pos_int, "양의 정수 색 수", where)
      crops = values.get("crops", [])
      ok = isinstance(crops, list) and all(isinstance(c, list) and len(c) == 2 and all(_pos_int(x) for x in c) for c in crops)
      if not ok:
         raise _fail(where, f"values.crops 는 [가로, 세로] 화면비 목록이다 : {crops!r}")

   def compute(self, ctx: Ctx) -> dict:
      v, w, h = ctx.values, ctx.w, ctx.h
      crops = []
      for rw, rh in v.get("crops", []):
         seen_h = rhu(w * rh / rw)
         if seen_h < h:
            y0 = (h - seen_h) // 2
            crops.append({"ratio": f"{rw}:{rh}", "axis": "y", "from": y0, "to": y0 + seen_h})
            continue
         seen_w = rhu(h * rw / rh)
         if seen_w < w:
            x0 = (w - seen_w) // 2
            crops.append({"ratio": f"{rw}:{rh}", "axis": "x", "from": x0, "to": x0 + seen_w})
      safe = [rhu(w * v["safe_side"]), rhu(h * v["safe_top"]), w - rhu(w * v["safe_side"]), h - rhu(h * v["safe_bottom"])]
      if safe == [0, 0, w, h]:
         safe = None          # 안전 영역 없음 (화면 조각처럼 판 전체를 쓰는 그림)
      if v.get("scene", "outdoor") == "indoor":
         ceiling_end = rhu(h * v["ceiling_ratio"])
         floor_y = h - rhu(h * v["floor_ratio"])
         return {"scene": "indoor", "ceiling_end_y": ceiling_end, "floor_y": floor_y, "crops": crops, "safe": safe}
      sky_end = rhu(h * v["sky_ratio"])
      far_end = sky_end + rhu(h * v["far_ratio"])
      front_y = h - rhu(h * v["front_ratio"])
      return {"scene": "outdoor", "sky_end_y": sky_end, "far_end_y": far_end, "front_y": front_y, "crops": crops, "safe": safe}

   def _band_lines(self, calc: dict) -> tuple[int, ...]:
      if calc["scene"] == "indoor":
         return calc["ceiling_end_y"], calc["floor_y"]
      return calc["sky_end_y"], calc["far_end_y"], calc["front_y"]

   def guide(self, ctx: Ctx, calc: dict) -> Guide:
      size, w, h = ctx.size, ctx.w, ctx.h
      g = Guide.blank(size)
      if calc["safe"]:
         g.keep |= _box(size, calc["safe"], filled=False)
      for y in self._band_lines(calc):
         if 0 <= y < h:
            g.line |= shapes.line(size, 0, y, w - 1, y)
      dash = (_cols(size) // 2 % 2 == 0)
      dash_y = (_rows(size) // 2 % 2 == 0)
      for crop in calc["crops"]:
         for edge in (crop["from"], crop["to"] - 1):
            if crop["axis"] == "y":
               g.dot |= (_rows(size) == edge) & dash
            else:
               g.dot |= (_cols(size) == edge) & dash_y
      return g

   def masks(self, ctx: Ctx, calc: dict) -> dict[str, Mask]:
      rows = _rows(ctx.size)
      if calc["scene"] == "indoor":
         return {
            "ceiling": rows < calc["ceiling_end_y"],
            "wall": (rows >= calc["ceiling_end_y"]) & (rows < calc["floor_y"]),
            "floor": rows >= calc["floor_y"],
         }
      return {
         "base": rows < calc["far_end_y"],
         "structure": (rows >= calc["far_end_y"]) & (rows < calc["front_y"]),
         "front": rows >= calc["front_y"],
      }


# ── ui9 · icon_set · tile ────────────────────────────


class Ui9(Kind):
   """9조각 밑판 : 자르는 줄 · 테 선 자리 · 최소 크기 · (말풍선이면) 꼬리 자리.

   테두리 칸 수는 `border` 하나(네 변 같음) 또는 `border_l` · `border_b` · `border_r` · `border_t` 로 변마다 따로.
   꼬리(`tail_w` × `tail_h`)는 아래 테두리 안 가운데에 둔다 — 9조각으로 늘려도 꼬리는 아래 가운데 조각에 남는다.
   """

   name = "ui9"
   value_keys = ("border", "border_l", "border_b", "border_r", "border_t", "border_px", "min_center", "tail_w", "tail_h")
   SIDES = ("border_l", "border_b", "border_r", "border_t")
   labels = (
      ("border_text", "테두리 L,B,R,T", "dot"),
      ("cut_y", "자르는 줄 (가운데 띠가 늘어난다)", "line"),
      ("tail", "꼬리 자리", "keep"),
   )

   @classmethod
   def sides(cls, values) -> tuple[int, int, int, int]:
      """(왼, 아래, 오른, 위) 테두리 칸 수. 변 값이 없으면 border."""
      b = values["border"]
      return tuple(int(values[k]) if values.get(k) is not None else int(b) for k in cls.SIDES)

   def check_values(self, values, size, tpl, where) -> None:
      _need(values, "border", _pos_int, "양의 정수 px", where)
      for key in self.SIDES:
         if values.get(key) is not None:
            _need(values, key, _pos_int, "양의 정수 px", where)
      _need(values, "border_px", _pos_int, "양의 정수 px", where)
      _need(values, "min_center", _pos_int, "양의 정수 px", where)
      for key in ("tail_w", "tail_h"):
         if key in values:
            _need(values, key, lambda v: _is_int(v) and v >= 0, "0 이상 정수 px", where)
      left, bottom, right, top = self.sides(values)
      if left + right + 1 > size[0] or top + bottom + 1 > size[1]:
         raise _fail(where, f"{size[0]}x{size[1]} 에 테두리 L{left} B{bottom} R{right} T{top} 가 안 들어간다")
      tail_h = int(values.get("tail_h", 0) or 0)
      if tail_h and tail_h >= bottom:
         raise _fail(where, f"꼬리 높이 {tail_h} 는 아래 테두리 {bottom} 보다 작아야 한다 (몸 테두리 줄이 남게)")

   def compute(self, ctx: Ctx) -> dict:
      v, w, h = ctx.values, ctx.w, ctx.h
      border_px = int(v["border_px"])
      if ctx.prof is not None:
         border_px = int(ctx.prof.ui["generator"]["border_px"])
      left, bottom, right, top = self.sides(v)
      center = int(v["min_center"])
      tail_w, tail_h = int(v.get("tail_w", 0) or 0), int(v.get("tail_h", 0) or 0)
      tail = None
      if tail_w and tail_h:
         tw = fit(w, min(tail_w, w - 2))
         tail = [(w - tw) // 2, h - tail_h, (w - tw) // 2 + tw, h]
      return {
         "border": int(v["border"]),
         "borders": [left, bottom, right, top],
         "border_text": f"{left},{bottom},{right},{top}",
         "border_px": border_px,
         "cut_x": [left, w - right],
         "cut_y": [top, h - bottom],
         "min_size": [left + right + center, top + bottom + center],
         "body": [0, 0, w, h - tail_h if tail else h],
         "tail": tail,
      }

   def guide(self, ctx: Ctx, calc: dict) -> Guide:
      size, w, h = ctx.size, ctx.w, ctx.h
      g = Guide.blank(size)
      x0, y0, x1, y1 = calc["body"]
      ring = _box(size, calc["body"])
      inset = calc["border_px"]
      if x1 - x0 > 2 * inset and y1 - y0 > 2 * inset:
         ring &= ~_box(size, [x0 + inset, y0 + inset, x1 - inset, y1 - inset])
      g.dot |= ring
      if calc["tail"]:
         g.keep |= _box(size, calc["tail"])
      # 자르는 줄 = 가운데 띠의 첫 칸 · 끝 칸(이 사이가 늘어난다)
      for x in (calc["cut_x"][0], calc["cut_x"][1] - 1):
         g.line |= shapes.line(size, x, 0, x, h - 1)
      for y in (calc["cut_y"][0], calc["cut_y"][1] - 1):
         g.line |= shapes.line(size, 0, y, w - 1, y)
      return g


class IconSet(Kind):
   """아이콘 한 벌 틀 : 같은 테 · 안쪽 여유 · 표식 구석."""

   name = "icon_set"
   value_keys = ("padding", "corner_cut", "badge")
   labels = (("frame", "틀", "line"), ("content", "내용 자리 (노랑 밖은 비운다)", "keep"), ("badge", "배지 자리", "dot"))

   def check_values(self, values, size, tpl, where) -> None:
      _need(values, "padding", lambda v: _is_int(v) and v >= 0, "0 이상 정수 px", where)
      _need(values, "corner_cut", lambda v: _is_int(v) and v >= 0, "0 이상 정수 px", where)
      _need(values, "badge", _pos_int, "양의 정수 px", where)
      if values["badge"] * 2 > min(size):
         raise _fail(where, f"표식 {values['badge']} 가 {size} 의 반을 넘는다")

   def compute(self, ctx: Ctx) -> dict:
      v, w, h = ctx.values, ctx.w, ctx.h
      pad, b = int(v["padding"]), int(v["badge"])
      return {
         "frame": [0, 0, w, h],
         "content": [1 + pad, 1 + pad, w - 1 - pad, h - 1 - pad],
         "badge": [w - 1 - b, h - 1 - b, w - 1, h - 1],
         "corner_cut": int(v["corner_cut"]),
      }

   def guide(self, ctx: Ctx, calc: dict) -> Guide:
      size, w, h = ctx.size, ctx.w, ctx.h
      g = Guide.blank(size)
      frame = _box(size, calc["frame"], filled=False)
      cut = calc["corner_cut"]
      if cut:
         xs, ys = _cols(size), _rows(size)
         near_x = np.minimum(xs, w - 1 - xs)
         near_y = np.minimum(ys, h - 1 - ys)
         frame &= ~((near_x + near_y) < cut)
      g.line |= frame
      x0, y0, x1, y1 = calc["content"]
      if x1 > x0 + 1 and y1 > y0 + 1:
         g.keep |= _box(size, [1, 1, w - 1, h - 1]) & ~_box(size, calc["content"])
      g.dot |= _box(size, calc["badge"], filled=False)
      return g


class Tile(Kind):
   """타일 밑판 : 가장자리 지키는 줄 · 50% 밀어 보기 줄 · 2×2 반복 미리보기."""

   name = "tile"
   value_keys = ("edge",)
   preview = "tile2x2"
   labels = (("variant_area", "변종 자리 (노랑 = 이음 가장자리)", "keep"), ("seam_y", "이음 줄", "line"))

   def check_values(self, values, size, tpl, where) -> None:
      _need(values, "edge", _pos_int, "양의 정수 px", where)
      if 2 * values["edge"] >= min(size):
         raise _fail(where, f"가장자리 {values['edge']} 가 {size} 에 너무 두껍다")

   def compute(self, ctx: Ctx) -> dict:
      e = int(ctx.values["edge"])
      return {"edge": e, "variant_area": [e, e, ctx.w - e, ctx.h - e], "seam_x": ctx.w // 2, "seam_y": ctx.h // 2}

   def guide(self, ctx: Ctx, calc: dict) -> Guide:
      size, w, h = ctx.size, ctx.w, ctx.h
      g = Guide.blank(size)
      g.keep |= _box(size, [0, 0, w, h]) & ~_box(size, calc["variant_area"])
      g.line |= shapes.line(size, calc["seam_x"], 0, calc["seam_x"], h - 1)
      g.line |= shapes.line(size, 0, calc["seam_y"], w - 1, calc["seam_y"])
      return g


# ── prop (건물 · 큰 물건) ─────────────────────────────


PROP_ALIGN = ("left", "center", "right")
# 미리보기 이름표에 쓰는 칸 이름. 표에 없는 겹 이름은 그대로 찍는다 (bands 의 겹 이름)
BAND_WORDS = {"roof": "지붕", "wall": "벽", "top": "위판", "body": "몸통", "foot": "받침", "base": "받침"}


class Prop(Kind):
   """건물 · 큰 물건 틀 : 바닥선 · 위에서 아래로 나눈 칸(지붕 · 벽 / 위판 · 몸통 · 받침) · 문 칸 · 바닥 그림자 · 외곽선 두께.

   - `bands` : [[겹 이름, 몫], …] 위 → 아래. 몫은 몸 높이(top ~ baseline) 기준, 마지막 칸이 남은 줄을 다 갖는다.
     겹 이름은 템플릿 layers 에 있어야 마스크가 나온다.
   - `door` : [너비 몫, 높이 몫, 자리 left · center · right] — 몸 너비 · 높이 기준, 바닥선에 붙는다. 없으면 null.
   - `shadow_ratio` : 바닥선 아래 그림자 띠 높이(캔버스 높이 몫). 0 이면 없음.
   - `outline_px` : 외곽선 두께 안내(1 또는 2). 가이드 왼쪽 위 모서리에 그 두께 점 칸으로 보여 준다.
   """

   name = "prop"
   value_keys = ("top_ratio", "foot_ratio", "side_ratio", "bands", "door", "shadow_ratio", "outline_px")
   mask_files = True
   labels = (
      ("body", "몸 상자", "line"),
      ("band_names", "칸", "line"),
      ("door_box", "문 칸", "dot"),
      ("baseline_y", "바닥선 (땅에 닿는 줄)", "line"),
      ("outline_text", "외곽선", "dot"),
   )

   def check_values(self, values, size, tpl, where) -> None:
      for key in ("top_ratio", "foot_ratio", "side_ratio", "shadow_ratio"):
         _need(values, key, _ratio, "0 이상 1 미만", where)
      _need(values, "outline_px", lambda v: _is_int(v) and 1 <= v <= 4, "1 ~ 4 px", where)
      bands = values.get("bands")
      ok = isinstance(bands, list) and bands and all(
         isinstance(b, list) and len(b) == 2 and isinstance(b[0], str) and _is_num(b[1]) and 0 < b[1] <= 1 for b in bands
      )
      if not ok:
         raise _fail(where, f"values.bands 는 [[겹 이름, 몫 0~1], …] 목록이다 : {bands!r}")
      if sum(b[1] for b in bands[:-1]) >= 1:
         raise _fail(where, "values.bands 의 마지막 칸 앞 몫의 합이 1 보다 작아야 한다 (마지막 칸 자리)")
      door = values.get("door")
      if door is not None:
         good = isinstance(door, list) and len(door) == 3 and _is_num(door[0]) and _is_num(door[1])             and 0 < door[0] <= 1 and 0 < door[1] <= 1 and door[2] in PROP_ALIGN
         if not good:
            raise _fail(where, f"values.door 는 [너비 몫, 높이 몫, {' · '.join(PROP_ALIGN)}] 이다 : {door!r}")
      calc = self.compute(Ctx(tpl, size, values))
      if any(y1 <= y0 for _, y0, y1 in calc["bands"]):
         raise _fail(where, f"{size[0]}x{size[1]} 에서 빈 칸이 생긴다 : {calc['bands']}")

   def compute(self, ctx: Ctx) -> dict:
      v, w, h = ctx.values, ctx.w, ctx.h
      top = int(math.floor(h * v["top_ratio"]))
      baseline = h - 1 - int(math.floor(h * v["foot_ratio"]))
      side = int(math.floor(w * v["side_ratio"]))
      body_h = baseline - top + 1
      x0, x1 = side, w - side
      bands, y = [], top
      for i, (name, share) in enumerate(v["bands"]):
         end = baseline + 1 if i == len(v["bands"]) - 1 else min(baseline + 1, y + rhu(body_h * share))
         bands.append([name, y, end])
         y = end
      door_box = None
      if v.get("door"):
         dw = fit(x1 - x0, max(1, rhu((x1 - x0) * v["door"][0])))
         dh = max(1, rhu(body_h * v["door"][1]))
         align = v["door"][2]
         dx0 = {"left": x0 + max(1, (x1 - x0) // 10), "center": x0 + (x1 - x0 - dw) // 2,
                "right": x1 - max(1, (x1 - x0) // 10) - dw}[align]
         door_box = [dx0, baseline + 1 - dh, dx0 + dw, baseline + 1]
      shadow = None
      sh = rhu(h * v["shadow_ratio"])
      if sh:
         shadow = [x0, max(top, baseline + 1 - sh), x1, min(h, baseline + 1 + sh // 2)]
      out = int(v["outline_px"])
      return {
         "top_y": top,
         "baseline_y": baseline,
         "body": [x0, top, x1, baseline + 1],
         "bands": bands,
         # 이름표용 : 칸마다 [x, 칸 첫 줄, 이름] — 미리보기 옆에 「지붕 칸」「벽 칸」… 으로 찍힌다
         "band_names": [[x0, y0, BAND_WORDS.get(name, name)] for name, y0, _ in bands],
         "band_list": " · ".join(name for name, _, _ in bands),
         "door_box": door_box,
         "shadow": shadow,
         "outline_px": out,
         "outline_text": f"{out}px",
      }

   def guide(self, ctx: Ctx, calc: dict) -> Guide:
      size, w = ctx.size, ctx.w
      g = Guide.blank(size)
      g.line |= _box(size, calc["body"], filled=False)
      x0, _, x1, _ = calc["body"]
      for _, y0, _ in calc["bands"][1:]:
         g.line |= shapes.line(size, x0, y0, x1 - 1, y0)
      g.line |= shapes.line(size, 0, calc["baseline_y"], w - 1, calc["baseline_y"])
      if calc["door_box"]:
         g.dot |= _box(size, calc["door_box"], filled=False)
      if calc["shadow"]:
         sx0, sy0, sx1, sy1 = calc["shadow"]
         g.keep |= shapes.ellipse(size, sx0, sy0, sx1, sy1) & (_rows(size) > calc["baseline_y"])
      # 외곽선 두께 견본 : 몸 상자 왼쪽 위 모서리 안쪽에 outline_px 두께 ㄱ 자
      n, bx0, by0 = calc["outline_px"], calc["body"][0], calc["body"][1]
      arm = max(4, 3 * n)
      g.dot |= _box(size, [bx0, by0, bx0 + arm, by0 + n]) | _box(size, [bx0, by0, bx0 + n, by0 + arm])
      return g

   def masks(self, ctx: Ctx, calc: dict) -> dict[str, Mask]:
      size = ctx.size
      x0, _, x1, _ = calc["body"]
      door = _box(size, calc["door_box"]) if calc["door_box"] else shapes.empty(size)
      out: dict[str, Mask] = {}
      for name, y0, y1 in calc["bands"]:
         out[name] = out.get(name, shapes.empty(size)) | (_box(size, [x0, y0, x1, y1]) & ~door)
      if calc["door_box"]:
         out["door"] = door
      if calc["shadow"]:
         sx0, sy0, sx1, sy1 = calc["shadow"]
         body = _box(size, calc["body"])
         out["shadow"] = shapes.ellipse(size, sx0, sy0, sx1, sy1) & ~body
      return out


# ── palette ──────────────────────────────────────────


class Palette(Kind):
   """바탕색 + 재질 → 램프 초안. 그림이 아니라 가이드 · 겹이 없다."""

   name = "palette"
   value_keys = ("base", "steps", "hue_step", "metal", "ramp_name")
   flat_presets = True
   has_layers = False
   must_default = ()
   preview = "swatch"

   def check_values(self, values, size, tpl, where) -> None:
      try:
         parse_hex(str(values.get("base", "")))
      except Exception as exc:
         raise _fail(where, f"values.base 는 #RRGGBB 다 : {values.get('base')!r}") from exc
      _need(values, "steps", lambda v: _is_int(v) and v >= 2, "2 이상 정수", where)
      _need(values, "hue_step", lambda v: v == "auto" or (_is_num(v) and 0 <= v <= 180), "\"auto\" 또는 0 ~ 180 도", where)
      if not isinstance(values.get("metal", False), bool):
         raise _fail(where, f"values.metal 은 true · false 다 : {values.get('metal')!r}")

   def compute(self, ctx: Ctx) -> dict:
      v = ctx.values
      # 프로필 값 0 · 0.0 도 값이다 — `or` 로 고르면 템플릿 기본으로 바뀐다 (리뷰 R2-L1)
      extra = ctx.extra
      base = extra.get("base") or v["base"]
      steps = int(extra["steps"] if extra.get("steps") is not None else v["steps"])
      raw_step = extra["hue_step"] if extra.get("hue_step") is not None else v["hue_step"]
      # "auto" : 칸 수에 맞춘 기본 걸음 (처음 ~ 끝 36° 이하 — style extract 가 램프 하나로 되읽는다)
      hue_step = auto_hue_step(steps) if raw_step == "auto" else float(raw_step)
      colors = shade(base, steps=steps, hue_step=hue_step, metal=bool(v.get("metal", False)))
      return {"base": base.upper(), "steps": steps, "hue_step": hue_step, "metal": bool(v.get("metal", False)), "ramp": colors}


# ── effect ───────────────────────────────────────────


SHAPE_KEYS = {
   "dot": ("size",),
   "disc": ("r",),
   "ring": ("r", "width", "dash"),
   "box": ("w", "h", "filled"),
   "line": ("x0", "y0", "x1", "y1"),
   "plus": ("r", "hollow"),
   "cross": ("r",),
   "diamond": ("r", "filled"),
}
SHAPE_NEED = {"disc": ("r",), "ring": ("r",), "box": ("w", "h"), "line": ("x0", "y0", "x1", "y1"), "plus": ("r",), "cross": ("r",), "diamond": ("r",)}


def _center(size: Size, spec: dict) -> tuple[float, float]:
   w, h = size
   return (w - 1) / 2 + spec.get("dx", 0), (h - 1) / 2 + spec.get("dy", 0)


def effect_shape(size: Size, spec: dict) -> Mask:
   """도형 하나. 자리는 캔버스 가운데에서 (dx, dy) 만큼 옮긴 곳."""
   kind = spec["shape"]
   cx, cy = _center(size, spec)
   px, py = int(math.floor(cx)), int(math.floor(cy))
   if kind == "dot":
      side = int(spec.get("size", 1))
      return shapes.dot(size, int(math.floor(cx - side / 2 + 0.5)), int(math.floor(cy - side / 2 + 0.5)), side)
   if kind == "disc":
      return shapes.disc(size, cx, cy, spec["r"])
   if kind == "ring":
      return shapes.ring(size, cx, cy, spec["r"], int(spec.get("width", 1)), int(spec.get("dash", 0)))
   if kind == "box":
      bw, bh = int(spec["w"]), int(spec["h"])
      x0, y0 = int(math.floor(cx - bw / 2 + 0.5)), int(math.floor(cy - bh / 2 + 0.5))
      return shapes.box(size, x0, y0, x0 + bw, y0 + bh, bool(spec.get("filled", True)))
   if kind == "line":
      return shapes.line(size, px + spec["x0"], py + spec["y0"], px + spec["x1"], py + spec["y1"])
   r = int(spec["r"])
   if kind == "plus":
      out = shapes.line(size, px - r, py, px + r, py) | shapes.line(size, px, py - r, px, py + r)
      hole = int(spec.get("hollow", 0))
      if hole:
         xs, ys = _cols(size), _rows(size)
         out &= ~((abs(xs - px) < hole) & (abs(ys - py) < hole))
      return out
   if kind == "cross":
      return shapes.line(size, px - r, py - r, px + r, py + r) | shapes.line(size, px - r, py + r, px + r, py - r)
   if kind == "diamond":
      xs, ys = _cols(size), _rows(size)
      dist = abs(xs - px) + abs(ys - py)
      return dist <= r if spec.get("filled", True) else dist == r
   raise TemplateError(f"모르는 도형 : {kind}")


def _validate_shape(spec, where, spot: str) -> None:
   if not isinstance(spec, dict) or spec.get("shape") not in SHAPE_KEYS:
      raise _fail(where, f"{spot} 의 shape 는 {' · '.join(SHAPE_KEYS)} 중 하나다 : {spec!r}")
   kind = spec["shape"]
   allowed = ("shape", "dx", "dy") + SHAPE_KEYS[kind]
   bad = sorted(k for k in spec if k not in allowed)
   if bad:
      raise _fail(where, f"{spot} ({kind}) 에 모르는 칸 {', '.join(bad)}")
   missing = [k for k in SHAPE_NEED.get(kind, ()) if k not in spec]
   if missing:
      raise _fail(where, f"{spot} ({kind}) 에 {', '.join(missing)} 가 없다")
   for key, value in spec.items():
      if key in ("shape",):
         continue
      if key == "filled":
         if not isinstance(value, bool):
            raise _fail(where, f"{spot}.filled 는 true · false 다")
         continue
      if not _is_num(value):
         raise _fail(where, f"{spot}.{key} 는 수다 : {value!r}")
      if key in ("size", "r", "width", "w", "h") and value <= 0:
         raise _fail(where, f"{spot}.{key} 는 양수다 : {value!r}")
      if key in ("dash", "hollow") and value < 0:
         raise _fail(where, f"{spot}.{key} 는 0 이상이다 : {value!r}")


class Effect(Kind):
   """이펙트 프레임 공식 — 프레임마다 흰 1색 모양(도형 목록)."""

   name = "effect"
   value_keys = ("frame_ms", "colors")
   frames_field = True
   needs_frames = True
   must_default = ("canvas", "alpha", "scale")
   preview = "frames"

   def validate_frames(self, frames, where) -> None:
      if not isinstance(frames, list) or not frames:
         raise _fail(where, "frames 는 프레임 목록이고 비면 안 된다")
      for i, frame in enumerate(frames):
         if not isinstance(frame, dict) or set(frame) != {"draw"} or not isinstance(frame["draw"], list):
            raise _fail(where, f"frames[{i}] 는 {{\"draw\": [도형…]}} 이다 (빈 장은 \"draw\": [])")
         for j, spec in enumerate(frame["draw"]):
            _validate_shape(spec, where, f"frames[{i}].draw[{j}]")

   def check_values(self, values, size, tpl, where) -> None:
      super().check_values(values, size, tpl, where)
      _need(values, "frame_ms", _pos_int, "양의 정수 ms", where)
      _need(values, "colors", _pos_int, "양의 정수 색 수", where)
      want = (tpl.get("check") or {}).get("frames")
      if want is not None and want != len(tpl["frames"]):
         raise _fail(where, f"check.frames {want} 가 frames {len(tpl['frames'])} 장과 다르다")

   def frame_count(self, ctx: Ctx) -> int:
      return len(ctx.tpl["frames"])

   def _frame_mask(self, size: Size, frame: dict) -> Mask:
      out = shapes.empty(size)
      for spec in frame["draw"]:
         out |= effect_shape(size, spec)
      return out

   def compute(self, ctx: Ctx) -> dict:
      counts = [int(self._frame_mask(ctx.size, f).sum()) for f in ctx.tpl["frames"]]
      return {"frame_pixels": counts}

   def guide(self, ctx: Ctx, calc: dict) -> Guide:
      """1배 가이드 = 모든 프레임 모양을 겹친 바깥 자리(선 색). 프레임 하나하나는 _f 파일에 있다."""
      g = Guide.blank(ctx.size)
      for frame in ctx.tpl["frames"]:
         g.line |= self._frame_mask(ctx.size, frame)
      return g

   def frames(self, ctx: Ctx, calc: dict) -> list[image.RGBA]:
      return [shapes.to_image(self._frame_mask(ctx.size, f), "#FFFFFF") for f in ctx.tpl["frames"]]


# ── motion ───────────────────────────────────────────


MOTION_PATHS = ("updown", "corner", "side")
MOTION_SHAPES = ("dot", "circle")


def wave(step: int, frames: int) -> int:
   """한 바퀴(frames 장) 정수 파형 : 0 → 1 → 0 → −1 꼴. 사인을 반올림한 표라 장 수가 달라도 같은 결이다."""
   return rhu(math.sin(2 * math.pi * (step % frames) / frames))


class Motion(Kind):
   """움직임 가이드 : 점 N개가 위상을 delay 장씩 늦춰 같은 진폭으로 흔들린다."""

   name = "motion"
   value_keys = ("frame_ms", "points", "frames", "delay", "amp", "path", "shape")
   labels = (("bases", "기준점", "dot"),)
   flat_presets = True
   must_default = ("canvas", "alpha", "scale")
   preview = "overlay"

   def check_values(self, values, size, tpl, where) -> None:
      super().check_values(values, size, tpl, where)
      _need(values, "points", _pos_int, "양의 정수", where)
      _need(values, "frames", lambda v: _is_int(v) and v >= 2, "2 이상 정수", where)
      _need(values, "delay", lambda v: _is_int(v) and v >= 0, "0 이상 정수", where)
      _need(values, "amp", _pos_int, "양의 정수 px", where)
      if values.get("path") not in MOTION_PATHS:
         raise _fail(where, f"values.path 는 {' · '.join(MOTION_PATHS)} 중 하나다 : {values.get('path')!r}")
      if values.get("shape", "dot") not in MOTION_SHAPES:
         raise _fail(where, f"values.shape 는 {' · '.join(MOTION_SHAPES)} 중 하나다 : {values.get('shape')!r}")

   def frame_count(self, ctx: Ctx) -> int:
      return int(ctx.values["frames"])

   def _bases(self, ctx: Ctx) -> list[tuple[int, int]]:
      v, w, h = ctx.values, ctx.w, ctx.h
      n, path = int(v["points"]), v["path"]
      if path == "updown":
         # 위가 먼저, 아래가 늦게 — 세로로 한 줄
         y0, y1 = h // 4, h - 1 - h // 4
         return [(w // 2, y0 + rhu(i * (y1 - y0) / max(1, n - 1))) for i in range(n)]
      if path == "side":
         y = h - 1 - max(3, h // 8)
         x0, x1 = w // 4, w - 1 - w // 4
         return [(x0 + rhu(i * (x1 - x0) / max(1, n - 1)), y) for i in range(n)]
      # corner : 판 둘레를 고르게. 넷이면 네 모서리
      inset = max(2, min(w, h) // 6)
      x0, y0, x1, y1 = inset, inset, w - 1 - inset, h - 1 - inset
      ring = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
      if n == 4:
         return ring
      perim = 2 * ((x1 - x0) + (y1 - y0))
      out = []
      for i in range(n):
         d = i * perim / n
         for (ax, ay), (bx, by) in zip(ring, ring[1:] + ring[:1]):
            seg = abs(bx - ax) + abs(by - ay)
            if d <= seg:
               t = d / seg if seg else 0
               out.append((rhu(ax + (bx - ax) * t), rhu(ay + (by - ay) * t)))
               break
            d -= seg
      return out

   def points(self, ctx: Ctx) -> list[list[tuple[int, int]]]:
      """프레임마다 점 자리 목록. 점 i 는 프레임 f 에서 amp × wave(f − i × delay) 만큼 옮긴다."""
      v = ctx.values
      frames, delay, amp = int(v["frames"]), int(v["delay"]), int(v["amp"])
      sideways = v["path"] == "side"
      out = []
      for f in range(frames):
         row = []
         for i, (x, y) in enumerate(self._bases(ctx)):
            move = amp * wave(f - i * delay, frames)
            row.append((x + move, y) if sideways else (x, y + move))
         out.append(row)
      return out

   def compute(self, ctx: Ctx) -> dict:
      return {"bases": [list(p) for p in self._bases(ctx)], "points": [[list(p) for p in row] for row in self.points(ctx)]}

   def _mark(self, ctx: Ctx, x: int, y: int) -> Mask:
      if ctx.values.get("shape", "dot") == "circle":
         return shapes.ring(ctx.size, x, y, 2.5, 1)
      return shapes.dot(ctx.size, x, y)

   def guide(self, ctx: Ctx, calc: dict) -> Guide:
      """점마다 움직이는 폭 상자(선 색). 상자 안에서만 흔들린다."""
      g = Guide.blank(ctx.size)
      amp = int(ctx.values["amp"])
      pad = 3 if ctx.values.get("shape", "dot") == "circle" else 1
      sideways = ctx.values["path"] == "side"
      for x, y in calc["bases"]:
         ax, ay = (amp, 0) if sideways else (0, amp)
         g.line |= _box(ctx.size, [x - ax - pad, y - ay - pad, x + ax + pad + 1, y + ay + pad + 1], filled=False)
      return g

   def frames(self, ctx: Ctx, calc: dict) -> list[image.RGBA]:
      out = []
      for row in calc["points"]:
         mask = shapes.empty(ctx.size)
         for x, y in row:
            mask |= self._mark(ctx, x, y)
         out.append(shapes.to_image(mask, "#00FFFF"))
      return out


# ── 표 ───────────────────────────────────────────────


def _rows(size: Size) -> np.ndarray:
   w, h = size
   return np.mgrid[0:h, 0:w][0]


def _cols(size: Size) -> np.ndarray:
   w, h = size
   return np.mgrid[0:h, 0:w][1]


def _box(size: Size, rect, filled: bool = True) -> Mask:
   """[x0, y0, x1, y1) 상자. 캔버스 밖은 잘린다. 비면 빈 마스크."""
   x0, y0, x1, y1 = (int(v) for v in rect)
   if x1 <= x0 or y1 <= y0:
      return shapes.empty(size)
   return shapes.box(size, x0, y0, x1, y1, filled)


def _shift(rect, dy: int) -> list[int]:
   x0, y0, x1, y1 = rect
   return [x0, y0 + dy, x1, y1 + dy]


HANDLERS: dict[str, Kind] = {
   k.name: k
   for k in (Character(), Parts(), Background(), Ui9(), IconSet(), Tile(), Prop(), Palette(), Effect(), Cycle(), Motion())
}
KINDS = tuple(HANDLERS)


def handler(kind: str) -> Kind:
   if kind not in HANDLERS:
      raise TemplateError(f"모르는 kind : {kind} (있는 것 : {' · '.join(KINDS)})")
   return HANDLERS[kind]
