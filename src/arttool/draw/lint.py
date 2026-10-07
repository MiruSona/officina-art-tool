"""좌표 박힌 린트 — 결함을 칸 (x, y) 하나씩 짚어 준다 (draw 고리 설계 3절).

`check` · `report()` 와 따로 논다. 규칙 이름은 모두 `lint.` 머리를 붙인다.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np

from ..checks import opaque
from ..checks.pixels import same_neighbors
from ..errors import ArtToolError
from ..palette import Ramps, load_ramps, to_hex
from .grid import bbox_of, require_rgba
from .outline import check_light, check_mode, edge, luma, solid_color

DEFAULT_RULES = ("lint.orphan", "lint.hole", "lint.stray_color", "lint.alpha_px", "lint.outline_gap")

# light_guess : 밝은 칸 무게중심이 어두운 칸보다 이만큼(칸) 넘게 위에 있어야 빛 방향을 말한다.
LIGHT_MIN_SHIFT = 0.5
# double : 2×2 를 한 점으로 볼 때 둘레 12칸 중 같은 색이 이 수 이하면 「선 위」로 본다(선이 드나드는 두 팔).
DOUBLE_RING_MAX = 4
# hole : 덩어리 하나의 detail 에 늘어놓는 칸 수 상한.
HOLE_LIST_MAX = 8


@dataclass
class LintResult:
   status: str = "ok"
   issues: list[dict] = field(default_factory=list)
   counts: dict[str, int] = field(default_factory=dict)
   metrics: dict = field(default_factory=dict)

   def to_dict(self) -> dict:
      return asdict(self)

   def lines(self) -> list[str]:
      """한 줄 글 목록. 예 : `lint.orphan (12,7) #6A3E2A 8이웃에 같은 색 없음`."""
      out = []
      for i in self.issues:
         head = [i["rule"]]
         if i["layer"]:
            head.append(i["layer"])
         if i["x"] is not None:
            head.append(f"({i['x']},{i['y']})")
         if i["color"]:
            head.append(i["color"])
         head.append(i["detail"])
         out.append(" ".join(head))
      return out


@dataclass
class _Ctx:
   ramps: Ramps | None
   light: str
   outline_mode: str | None
   axis_x: float | None = None
   outline_color: tuple[int, int, int] | None = None
   metrics: dict = field(default_factory=dict)


def _issue(rule: str, x, y, color: str | None, detail: str) -> dict:
   """x · y 가 None 이면 칸이 아닌 그림 전체 이슈(수치 비교 등)."""
   x = None if x is None else int(x)
   y = None if y is None else int(y)
   return {"rule": rule, "layer": None, "x": x, "y": y, "color": color, "detail": detail}


def _hex(arr: np.ndarray, x, y) -> str:
   return to_hex(tuple(int(c) for c in arr[y, x, :3]))


def _rule_orphan(arr: np.ndarray, ctx: _Ctx) -> list[dict]:
   """8이웃에 같은 RGBA 가 없는 불투명 칸. 가장자리 칸도 잰다 — 일부러 둔 점은 waive 로 뺀다.

   `measure_isolated`(check 명령)는 바깥 AA 를 봐 주려고 가장자리를 빼지만, 린트는 듬성한 겹(눈 · 볼 점)의
   외딴 점도 짚어야 해서 빼지 않는다.
   """
   lonely = opaque(arr) & (same_neighbors(arr) == 0)
   ys, xs = np.nonzero(lonely)
   return [_issue("lint.orphan", x, y, _hex(arr, x, y), "8이웃에 같은 색 없음") for y, x in zip(ys, xs)]


def _holes(clear: np.ndarray) -> list[list[tuple[int, int]]]:
   """투명 칸 판에서 그림 테두리와 4방향으로 안 이어진 덩어리들. 덩어리마다 [(y, x) …]."""
   h, w = clear.shape
   seen = np.zeros_like(clear)
   # 테두리에서 닿는 투명은 바깥이다 — 먼저 다 지운다
   stack = [(y, x) for y in range(h) for x in (0, w - 1) if clear[y, x]]
   stack += [(y, x) for x in range(w) for y in (0, h - 1) if clear[y, x]]
   _fill(clear, seen, stack)
   blobs = []
   for y, x in zip(*np.nonzero(clear & ~seen)):
      if not seen[y, x]:
         blobs.append(_fill(clear, seen, [(int(y), int(x))]))
   return blobs


def _fill(clear: np.ndarray, seen: np.ndarray, stack: list[tuple[int, int]]) -> list[tuple[int, int]]:
   """stack 칸에서 4방향으로 이어진 투명 칸을 seen 에 칠하고 칠한 칸 목록을 돌려준다."""
   h, w = clear.shape
   got = []
   while stack:
      y, x = stack.pop()
      if seen[y, x] or not clear[y, x]:
         continue
      seen[y, x] = True
      got.append((y, x))
      for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
         ny, nx = y + dy, x + dx
         if 0 <= ny < h and 0 <= nx < w and clear[ny, nx] and not seen[ny, nx]:
            stack.append((ny, nx))
   return got


def _rule_hole(arr: np.ndarray, ctx: _Ctx) -> list[dict]:
   """그림 테두리와 4방향으로 안 이어진 투명 덩어리마다 이슈 하나. 좌표는 덩어리의 왼쪽 위 칸(맨 윗줄의 맨 왼쪽).

   detail 은 `N칸 구멍 (x,y) (x,y) …` — 칸은 위에서 아래 · 왼쪽에서 오른쪽 순으로 HOLE_LIST_MAX 칸까지.
   칸마다 이슈를 내면 액자처럼 큰 속 빈 그림에서 수천 줄이 나와 다른 이슈를 덮는다.
   """
   out = []
   for blob in _holes(arr[:, :, 3] == 0):
      cells = sorted(blob)
      listed = " ".join(f"({x},{y})" for y, x in cells[:HOLE_LIST_MAX])
      more = " …" if len(cells) > HOLE_LIST_MAX else ""
      y, x = cells[0]
      out.append(_issue("lint.hole", x, y, None, f"{len(cells)}칸 구멍 {listed}{more}"))
   out.sort(key=lambda i: (i["y"], i["x"]))
   return out


def _rule_stray_color(arr: np.ndarray, ctx: _Ctx) -> list[dict]:
   """팔레트 밖 색 칸. 팔레트가 없으면 `lint` 가 안 부른다."""
   allowed = ctx.ramps.colors()
   out = []
   for y, x in zip(*np.nonzero(opaque(arr))):
      if tuple(int(c) for c in arr[y, x, :3]) not in allowed:
         out.append(_issue("lint.stray_color", x, y, _hex(arr, x, y), f"팔레트 {ctx.ramps.name} 밖 색"))
   return out


def _rule_alpha_px(arr: np.ndarray, ctx: _Ctx) -> list[dict]:
   """알파가 0 도 255 도 아닌 칸."""
   a = arr[:, :, 3]
   ys, xs = np.nonzero((a > 0) & (a < 255))
   return [_issue("lint.alpha_px", x, y, _hex(arr, x, y), f"알파 {int(a[y, x])} (0·255 아님)") for y, x in zip(ys, xs)]


def _rule_outline_gap(arr: np.ndarray, ctx: _Ctx) -> list[dict]:
   """실루엣 가장자리 칸 중 선이 아닌 칸. 판정 꼴은 설계 3절 표 `lint.outline_gap` 줄."""
   mode = ctx.outline_mode
   solid = opaque(arr)
   rim = edge(solid)
   ys, xs = np.nonzero(rim)
   if len(ys) == 0:
      return []
   rgb = [tuple(int(c) for c in arr[y, x, :3]) for y, x in zip(ys, xs)]
   if mode in ("black", "solid"):
      line = ctx.outline_color if mode == "solid" and ctx.outline_color else _line_color(mode, ctx.ramps, rgb)
      want = to_hex(line)
      return [_issue("lint.outline_gap", x, y, to_hex(c), f"선 색 {want} 아님")
              for y, x, c in zip(ys, xs, rgb) if c != line]
   # selout 계열 : 안쪽(가장자리 아닌 불투명) 4이웃 중 가장 밝은 칸보다 어둡지 않으면 빈 선.
   h, w = solid.shape
   inner = solid & ~rim
   out = []
   for y, x, c in zip(ys, xs, rgb):
      near = [luma(arr[y + dy, x + dx, :3]) for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1))
              if 0 <= y + dy < h and 0 <= x + dx < w and inner[y + dy, x + dx]]
      if near and luma(c) >= max(near):
         out.append(_issue("lint.outline_gap", x, y, to_hex(c), "안쪽 이웃보다 어둡지 않음"))
   return out


def _line_color(mode: str, ramps: Ramps | None, rgb: list[tuple]) -> tuple[int, int, int]:
   """black 은 팔레트 outline 색(없으면 검정). solid 는 outline_color 를 안 받았으면 가장자리 최다 색을 선 색으로 본다."""
   if mode == "black":
      if ramps is not None and ramps.outline is not None:
         return ramps.outline
      return (0, 0, 0)
   colors, counts = np.unique(np.array(rgb), axis=0, return_counts=True)
   return tuple(int(c) for c in colors[int(np.argmax(counts))])


def _rule_double(arr: np.ndarray, ctx: _Ctx) -> list[dict]:
   """1px 선 위 같은 색 2×2 뭉침. 2×2 를 한 점으로 보고 둘레 12칸 중 같은 색이 1~DOUBLE_RING_MAX 칸이면 선 위다.

   넓은 면(둘레가 거의 다 같은 색)과 따로 떨어진 2×2 점(둘레 0칸)은 안 걸린다. 좌표는 2×2 의 왼쪽 위.
   """
   h, w = arr.shape[:2]
   solid = opaque(arr)
   out = []
   for y in range(h - 1):
      for x in range(w - 1):
         c = arr[y, x]
         if not solid[y, x] or not all((arr[y + dy, x + dx] == c).all() for dy in (0, 1) for dx in (0, 1)):
            continue
         ring = sum(1 for yy in range(y - 1, y + 3) for xx in range(x - 1, x + 3)
                    if not (y <= yy <= y + 1 and x <= xx <= x + 1)
                    and 0 <= yy < h and 0 <= xx < w and (arr[yy, xx] == c).all())
         if 1 <= ring <= DOUBLE_RING_MAX:
            out.append(_issue("lint.double", x, y, _hex(arr, x, y), "선 위 같은 색 2×2 뭉침"))
   return out


def _axis(w: int, axis_x) -> float:
   """거울 축 x 위치. 기본은 그림 가운데 ((w-1)/2). 칸 가운데나 칸 사이(0.5 단위)만 받는다."""
   a = (w - 1) / 2 if axis_x is None else float(axis_x)
   if (a * 2) != int(a * 2):
      raise ArtToolError(f"axis_x 는 0.5 단위다 : {axis_x}")
   return a


def _mirror_same(arr: np.ndarray, a: float) -> tuple[np.ndarray, np.ndarray]:
   """(거울 칸과 같은가, 거울 x) 두 배열. 둘 다 투명이면 같다고 본다. 거울이 그림 밖이면 투명으로 본다."""
   h, w = arr.shape[:2]
   mx = (2 * a - np.arange(w)).astype(int)
   inside = (mx >= 0) & (mx < w)
   mirrored = np.zeros_like(arr)
   mirrored[:, inside] = arr[:, mx[inside]]
   solid = opaque(arr)
   same = (arr == mirrored).all(axis=2) | (~solid & ~opaque(mirrored))
   return same, mx


def _rule_asym(arr: np.ndarray, ctx: _Ctx) -> list[dict]:
   """축 왼쪽 칸 중 좌우 거울 칸과 RGBA 가 다른 칸. 오른쪽 칸은 짝이 같으니 안 짚는다."""
   a = _axis(arr.shape[1], ctx.axis_x)
   same, mx = _mirror_same(arr, a)
   solid = opaque(arr)
   out = []
   for y, x in zip(*np.nonzero(~same)):
      if x < a:
         color = _hex(arr, x, y) if solid[y, x] else None
         out.append(_issue("lint.asym", x, y, color, f"거울 칸 ({int(mx[x])},{int(y)}) 과 다름"))
   return out


def _rule_light_mismatch(arr: np.ndarray, ctx: _Ctx) -> list[dict]:
   """수치 light_guess 가 지정한 빛과 다르면 그림 전체 이슈 하나. unknown 이면 판단하지 않는다."""
   guess = ctx.metrics.get("light_guess", "unknown")
   if guess in ("unknown", ctx.light):
      return []
   return [_issue("lint.light_mismatch", None, None, None, f"명암 추정 {guess} · 지정 빛 {ctx.light}")]


RULES = {
   "lint.orphan": _rule_orphan,
   "lint.hole": _rule_hole,
   "lint.stray_color": _rule_stray_color,
   "lint.alpha_px": _rule_alpha_px,
   "lint.outline_gap": _rule_outline_gap,
   "lint.double": _rule_double,
   "lint.asym": _rule_asym,
   "lint.light_mismatch": _rule_light_mismatch,
}


def _bright_dark(rgb: list[tuple], ramps: Ramps | None) -> tuple[np.ndarray, np.ndarray]:
   """밝은 칸 · 어두운 칸 마스크(불투명 칸 순서). 램프 안 위치 위 절반 / 아래 절반, 못 가르면 luma 중앙값 기준."""
   if ramps is not None:
      pos = {}
      for colors in ramps.ramps.values():
         for i, c in enumerate(colors):
            if len(colors) > 1:
               pos.setdefault(tuple(c), i / (len(colors) - 1))
      p = np.array([pos.get(c, 0.5) for c in rgb])
      if (p > 0.5).any() and (p < 0.5).any():
         return p > 0.5, p < 0.5
   lum = np.array([luma(c) for c in rgb])
   med = np.median(lum)
   return lum > med, lum < med


def _light_guess(arr: np.ndarray, ramps: Ramps | None) -> str:
   """밝은 칸 무게중심 − 어두운 칸 무게중심 = (dx, dy). 위로 LIGHT_MIN_SHIFT 칸 넘게 안 가면 unknown.

   가로 차가 세로 차의 절반보다 작으면 top, 아니면 왼쪽 · 오른쪽으로 top_left · top_right.
   """
   ys, xs = np.nonzero(opaque(arr))
   if len(ys) == 0:
      return "unknown"
   bright, dark = _bright_dark([tuple(int(c) for c in arr[y, x, :3]) for y, x in zip(ys, xs)], ramps)
   if not bright.any() or not dark.any():
      return "unknown"
   dx = xs[bright].mean() - xs[dark].mean()
   dy = ys[bright].mean() - ys[dark].mean()
   if dy > -LIGHT_MIN_SHIFT:
      return "unknown"
   if abs(dx) < abs(dy) / 2:
      return "top"
   return "top_left" if dx < 0 else "top_right"


def _metrics(arr: np.ndarray, ctx: _Ctx) -> dict:
   """늘 내는 수치. 불투명 칸이 없으면 symmetry · center · bbox 는 None, light_guess 는 unknown."""
   solid = opaque(arr)
   out = {"symmetry": None, "center": None, "center_offset": None, "bbox": None,
          "light_guess": _light_guess(arr, ctx.ramps)}
   box = bbox_of(solid)
   if box is None:
      return out
   same, _ = _mirror_same(arr, _axis(arr.shape[1], ctx.axis_x))
   out["symmetry"] = round(float((same & solid).sum() / solid.sum()), 3)
   x0, y0, x1, y1 = box
   out["bbox"] = box
   ys, xs = np.nonzero(solid)
   cx, cy = float(xs.mean()), float(ys.mean())
   out["center"] = [round(cx, 2), round(cy, 2)]
   out["center_offset"] = [round(cx - (x0 + x1 - 1) / 2, 2), round(cy - (y0 + y1 - 1) / 2, 2)]
   return out


def pick_rules(rules) -> list[str]:
   """규칙 이름 목록(`lint.` 머리 없어도 됨) → 머리 붙인 이름. None 이면 기본 규칙. 없는 이름은 거절."""
   if rules is None:
      return list(DEFAULT_RULES)
   if isinstance(rules, str):
      rules = [rules]
   names = []
   for r in rules:
      name = r if r.startswith("lint.") else f"lint.{r}"
      if name not in RULES:
         raise ArtToolError(f"없는 린트 규칙 : {r} (있는 것 : {' · '.join(RULES)})")
      names.append(name)
   return names


def lint(arr: np.ndarray, *, ramps=None, light: str = "top_left", outline_mode: str | None = None,
         rules=None, waive=(), axis_x: float | None = None, outline_color=None) -> LintResult:
   """RGBA 배열 하나를 린트한다. ramps : `Ramps` 또는 램프 파일 경로. waive : 뺄 칸 [(x, y), …].

   axis_x : 거울 축 x(0.5 단위, 기본 그림 가운데). outline_color : solid 선 색(#RRGGBB · (R, G, B)).
   수치(`metrics`)는 규칙 고르기와 상관없이 늘 채운다.
   """
   require_rgba(arr)
   check_light(light)
   if outline_mode is not None:
      check_mode(outline_mode)
   if ramps is not None and not isinstance(ramps, Ramps):
      ramps = load_ramps(ramps)
   line = None if outline_color is None else solid_color(outline_color)
   ctx = _Ctx(ramps=ramps, light=light, outline_mode=outline_mode, axis_x=axis_x, outline_color=line)
   _axis(arr.shape[1], axis_x)       # 빈 그림이어도 축 값은 검사한다
   ctx.metrics = _metrics(arr, ctx)
   skip = {(int(x), int(y)) for x, y in waive}
   result = LintResult(metrics=ctx.metrics)
   for name in pick_rules(rules):
      if name == "lint.stray_color" and ramps is None:
         continue
      if name == "lint.outline_gap" and outline_mode in (None, "none"):
         continue
      found = [i for i in RULES[name](arr, ctx) if (i["x"], i["y"]) not in skip]
      result.issues += found
      result.counts[name] = len(found)
   if result.issues:
      result.status = "warn"
   return result
