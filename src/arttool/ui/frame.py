"""①ㄱ 프레임 그리기. 9-slice 로 늘어나는 패널·버튼·바를 코드가 그리고 border 를 같이 적는다.

같은 프로필 + 같은 팔레트면 언제 돌려도 같은 픽셀이 나온다. 난수도 실수 반올림도 안 쓴다.
border 순서는 [왼, 아래, 오른, 위] 다. Unity spriteBorder 의 Vector4 순서 그대로다.
"""

from __future__ import annotations

from pathlib import Path

from .. import image, palette
from ..errors import ArtToolError
from ..jsonio import write_json
from ..paths import resolve_root, safe_join
from ..profile import Profile

VERSION = 1
KINDS = ("panel", "button", "bar")
CUT_STEPS = {"square": 0, "cut1": 1, "cut2": 2}
SLOTS = ("outline", "highlight", "fill", "shadow")


def load_ui_ramps(prof: Profile) -> palette.Ramps:
   """UI 램프를 찾는다. 프로필 팔레트에 그 이름이 있으면 그것, 없으면 palettes/<이름>.json."""
   from ..profile import tool_home

   name = str(prof.ui["generator"]["ramp"])
   own = prof.ramps_path()
   if own is not None and own.is_file():
      ramps = palette.load_ramps(own)
      if name in ramps.names():
         return ramps

   near = tool_home() / "palettes" / f"{name}.json"
   if not near.is_file():
      raise ArtToolError(f"UI 램프 파일이 없다 : {near}")
   return palette.load_ramps(near)


def _ramp_for(prof: Profile, ramps: palette.Ramps, state: str) -> list[tuple[int, int, int]]:
   gen = prof.ui["generator"]
   name = str(gen["ramp"])
   if state == "disabled":
      name = str(gen.get("ramp_disabled") or gen["ramp"])
   if name not in ramps.names():
      raise ArtToolError(f"램프 파일에 {name} 이 없다 (있는 것 : {', '.join(ramps.names())})")
   return ramps.ramp(name)


def slot_colors(prof: Profile, ramps: palette.Ramps, state: str) -> dict[str, tuple[int, int, int]]:
   """칸 이름 → 색. pressed 는 하이라이트와 그림자를 맞바꾼다."""
   colors = _ramp_for(prof, ramps, state)
   index = prof.ui["generator"]["ramp_index"]
   too_big = [k for k in SLOTS if int(index[k]) >= len(colors)]
   if too_big:
      raise ArtToolError(f"램프에 단이 모자란다 : {', '.join(too_big)} 이 램프 길이 {len(colors)} 를 넘는다")

   picked = {k: colors[int(index[k])] for k in SLOTS}
   if state == "pressed":
      picked["highlight"], picked["shadow"] = picked["shadow"], picked["highlight"]
   return picked


def _cut_steps(prof: Profile, kind: str) -> int:
   if kind == "bar":
      return 0
   return CUT_STEPS[str(prof.ui["generator"]["corner"])]


def border_of(prof: Profile, kind: str) -> list[int]:
   """[왼, 아래, 오른, 위]. 5-1 의 7번 : corner + border_px + max(highlight, shadow)."""
   gen = prof.ui["generator"]
   side = _cut_steps(prof, kind) + int(gen["border_px"]) + max(int(gen["highlight"]), int(gen["inner_shadow"]))
   if kind == "bar":
      return [side, 0, side, 0]
   return [side, side, side, side]


def min_size(prof: Profile, kind: str) -> list[int]:
   left, bottom, right, top = border_of(prof, kind)
   slack = int(prof.ui["check"]["min_size_slack"])
   return [left + right + slack, top + bottom + slack]


def content_padding(prof: Profile, kind: str, state: str) -> list[int]:
   """글자가 들어갈 안쪽 여백. 기본은 border 와 같고 pressed 만 안쪽을 1px 아래로 민다."""
   left, bottom, right, top = border_of(prof, kind)
   if state != "pressed":
      return [left, bottom, right, top]
   return [left, max(bottom - 1, 0), right, top + 1]


class _Canvas:
   """잠긴 칸을 기억해 두고 나중 단계가 그 자리를 다시 칠하지 못하게 막는다.

   깎아 낸 귀퉁이뿐 아니라 **깎인 자리 안쪽에 다시 그은 outline** 도 잠근다.
   안 잠그면 하이라이트·그림자가 그 대각선을 덮어 귀퉁이 테두리가 끊긴다.
   """

   def __init__(self, width: int, height: int):
      self.arr = image.new(width, height)
      self.width = width
      self.height = height
      self.locked: set[tuple[int, int]] = set()

   def put(self, x: int, y: int, rgb: tuple[int, int, int]) -> None:
      if (x, y) in self.locked:
         return
      self.arr[y, x] = (*rgb, 255)

   def put_locked(self, x: int, y: int, rgb: tuple[int, int, int]) -> None:
      self.arr[y, x] = (*rgb, 255)
      self.locked.add((x, y))

   def clear(self, x: int, y: int) -> None:
      self.arr[y, x] = (0, 0, 0, 0)
      self.locked.add((x, y))

   def fill_all(self, rgb: tuple[int, int, int]) -> None:
      for y in range(self.height):
         for x in range(self.width):
            self.put(x, y, rgb)


def _draw_outline(canvas: _Canvas, thickness: int, rgb, sides_lr_only: bool) -> None:
   for y in range(canvas.height):
      for x in range(canvas.width):
         near_x = x < thickness or x >= canvas.width - thickness
         near_y = y < thickness or y >= canvas.height - thickness
         if near_x or (near_y and not sides_lr_only):
            canvas.put(x, y, rgb)


def _corner_spots(canvas: _Canvas, dx: int, dy: int) -> list[tuple[int, int]]:
   right = canvas.width - 1 - dx
   bottom = canvas.height - 1 - dy
   return [(dx, dy), (right, dy), (dx, bottom), (right, bottom)]


def _cut_corners(canvas: _Canvas, steps: int, rgb) -> None:
   """귀퉁이를 대각으로 지우고, 깎인 자리 바로 안쪽에 outline 을 다시 긋는다."""
   if steps <= 0:
      return

   for dy in range(steps):
      for dx in range(steps - dy):
         for x, y in _corner_spots(canvas, dx, dy):
            canvas.clear(x, y)

   for dy in range(steps + 1):
      for x, y in _corner_spots(canvas, steps - dy, dy):
         canvas.put_locked(x, y, rgb)


def _draw_highlight(canvas: _Canvas, prof: Profile, kind: str, rgb) -> None:
   gen = prof.ui["generator"]
   edge = int(gen["border_px"])
   thick = int(gen["highlight"])
   _draw_inner_band(canvas, edge, thick, rgb, top_left=True, skip_vertical=kind == "bar")


def _draw_shadow(canvas: _Canvas, prof: Profile, kind: str, rgb) -> None:
   gen = prof.ui["generator"]
   edge = int(gen["border_px"])
   thick = int(gen["inner_shadow"])
   _draw_inner_band(canvas, edge, thick, rgb, top_left=False, skip_vertical=kind == "bar")


def _band_hit(x: int, y: int, box: tuple[int, int, int, int], thick: int, top_left: bool, skip_vertical: bool) -> bool:
   left, top, right, bottom = box
   if top_left:
      return x < left + thick or (not skip_vertical and y < top + thick)
   return x >= right - thick or (not skip_vertical and y >= bottom - thick)


def _draw_inner_band(canvas: _Canvas, edge: int, thick: int, rgb, top_left: bool, skip_vertical: bool) -> None:
   if thick <= 0:
      return

   box = (edge, edge, canvas.width - edge, canvas.height - edge)
   if skip_vertical:
      box = (edge, 0, canvas.width - edge, canvas.height)

   for y in range(box[1], box[3]):
      for x in range(box[0], box[2]):
         if _band_hit(x, y, box, thick, top_left, skip_vertical):
            canvas.put(x, y, rgb)


def draw(prof: Profile, kind: str, size: tuple[int, int], state: str, ramps: palette.Ramps | None = None) -> image.RGBA:
   if kind not in KINDS:
      raise ArtToolError(f"모르는 프레임 종류 : {kind} (쓸 수 있는 것 : {', '.join(KINDS)})")
   width, height = size
   _check_size(prof, kind, width, height)

   ramps = ramps or load_ui_ramps(prof)
   colors = slot_colors(prof, ramps, state)
   canvas = _Canvas(width, height)

   canvas.fill_all(colors["fill"])
   _draw_outline(canvas, int(prof.ui["generator"]["border_px"]), colors["outline"], sides_lr_only=kind == "bar")
   _cut_corners(canvas, _cut_steps(prof, kind), colors["outline"])
   _draw_highlight(canvas, prof, kind, colors["highlight"])
   _draw_shadow(canvas, prof, kind, colors["shadow"])
   return canvas.arr


def _check_size(prof: Profile, kind: str, width: int, height: int) -> None:
   if prof.ui["check"]["require_even"] and (width % 2 or height % 2):
      raise ArtToolError(f"원본이 홀수다 : {width}x{height} (require_even 이 켜져 있다)")
   want_w, want_h = min_size(prof, kind)
   if width < want_w or height < want_h:
      raise ArtToolError(f"최소 크기 {want_w}x{want_h} 가 원본 {width}x{height} 보다 크다")


def build(prof: Profile, kind: str, size: tuple[int, int], out_dir: str | Path) -> dict:
   ramps = load_ui_ramps(prof)
   root = resolve_root(out_dir)
   states = list(prof.ui["generator"]["states"])

   frames = []
   for state in states:
      arr = draw(prof, kind, size, state, ramps)
      name = f"{kind}_{state}"
      image.save(safe_join(root, f"{name}.png"), arr)
      frames.append(
         {
            "name": name,
            "group": kind,
            "state": state,
            "size": [size[0], size[1]],
            "border": border_of(prof, kind),
            "min_size": min_size(prof, kind),
            "content_padding": content_padding(prof, kind, state),
            "file": f"{name}.png",
         }
      )

   merge_border_file(root, prof, frames)
   return {"out": str(root), "kind": kind, "frames": frames}


def merge_border_file(root: Path, prof: Profile, frames: list[dict]) -> dict:
   """border.json 에 이번 프레임을 더한다. 같은 이름은 새 것이 이긴다."""
   path = safe_join(root, "border.json")
   kept = []
   if path.is_file():
      from ..jsonio import read_json

      kept = [f for f in read_json(path).get("frames", []) if f["name"] not in {n["name"] for n in frames}]

   data = {"version": VERSION, "profile": prof.name, "frames": sorted(kept + frames, key=lambda f: f["name"])}
   write_json(path, data)
   return data
