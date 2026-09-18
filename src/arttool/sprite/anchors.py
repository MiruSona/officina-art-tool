"""② 앵커 뽑기. 한 줄 = 한 점.

마커 시트는 규격 맞춘 시트와 칸이 똑같은 PNG 다. 프레임마다 부착점 색 한 픽셀씩 찍혀 있다.
"""

from __future__ import annotations

from pathlib import Path

from .. import image, palette
from ..errors import ArtToolError
from ..jsonio import read_json
from ..profile import Profile

VERSION = 1


def _marker_colors(rig: dict) -> dict[str, tuple[int, int, int]]:
   colors = rig.get("marker_colors") or {}
   points = rig.get("anchors") or []
   missing = [p for p in points if p not in colors]
   if missing:
      raise ArtToolError(f"마커 색이 없는 부착점 : {', '.join(missing)}")
   return {p: palette.parse_hex(colors[p]) for p in points}


def _resolve_z(rig: dict, point: str, direction: str) -> int:
   table = rig.get("anchor_z") or {}
   value = table.get(point, 0)
   if isinstance(value, dict):
      value = value.get(direction, value.get("default", 0))
   return int(value)


def _one_marker(frame: image.RGBA, rgb: tuple[int, int, int], where: str) -> tuple[int, int]:
   spots = image.find_color(frame, rgb)
   if not spots:
      raise ArtToolError(f"부착점이 프레임에서 빠졌다 : {where}")
   if len(spots) > 1:
      raise ArtToolError(f"마커가 {len(spots)}개다. 하나여야 한다 : {where}")
   return spots[0]


def _check_color_clash(art: image.RGBA, colors: dict[str, tuple[int, int, int]], where: str) -> None:
   used = image.opaque_colors(art)
   clash = sorted(name for name, rgb in colors.items() if rgb in used)
   if clash:
      raise ArtToolError(f"마커 색이 그림 색과 겹친다 : {', '.join(clash)} - {where}")


def _mirror_x(x: int, frame_w: int) -> int:
   return frame_w - 1 - x


class PointBook:
   """열쇠가 겹치는지 보면서 점을 모은다."""

   def __init__(self):
      self.points: list[dict] = []
      self._keys: set[tuple] = set()

   def add(self, rig: str, anim: str, direction: str, frame: int, point: str, x: int, y: int, z: int) -> None:
      key = (rig, anim, direction, frame, point)
      if key in self._keys:
         raise ArtToolError(f"같은 열쇠에 점이 두 번 : {rig}/{anim}/{direction}/{frame}/{point}")
      self._keys.add(key)
      self.points.append(
         {
            "rig": rig,
            "anim": anim,
            "direction": direction,
            "frame": frame,
            "point": point,
            "x": int(x),
            "y": int(y),
            "z": int(z),
         }
      )


def _split_sheet(path: Path, frame_w: int, frame_h: int, where: str) -> list[list[image.RGBA]]:
   if not path.is_file():
      raise ArtToolError(f"마커 시트가 없다 : {path} ({where})")
   return image.split_grid(image.load(path), frame_w, frame_h)


def _source_directions(sheet: dict, rows: int) -> tuple[list[str], list[str]]:
   """마커 시트에 실제로 든 방향과, 반전으로 만들 방향을 가른다."""
   directions = list(sheet["directions"])
   mirrored = [d for d in sheet.get("mirrored", []) if d in directions]
   if rows == len(directions):
      return directions, []
   source = [d for d in directions if d not in mirrored]
   if rows != len(source):
      raise ArtToolError(f"마커 시트 줄이 {rows}개다. {len(directions)} 또는 {len(source)} 여야 한다")
   return source, mirrored


def extract(prof: Profile, frames_index: dict, markers_dir: str | Path, rig_name: str, art_dir: str | Path | None = None) -> dict:
   rig = prof.rig(rig_name)
   if rig.get("method") != "anchor":
      raise ArtToolError(f"{rig_name} 은 앵커 rig 가 아니다 (method={rig.get('method')})")

   colors = _marker_colors(rig)
   frame_w, frame_h = prof.frame
   marker_root = Path(markers_dir)
   art_root = Path(art_dir) if art_dir else None
   book = PointBook()

   for sheet in frames_index["sheets"]:
      anim = sheet["anim"]
      grid = _split_sheet(marker_root / sheet["file"], frame_w, frame_h, anim)
      source, mirrored = _source_directions(sheet, len(grid))
      _collect_sheet(book, prof, rig, rig_name, anim, sheet, grid, source, colors, art_root)
      _mirror_sheet(book, rig, rig_name, anim, mirrored, frame_w)

   return {
      "version": VERSION,
      "profile": prof.name,
      "frame": [frame_w, frame_h],
      "points": book.points,
   }


def _collect_sheet(book, prof, rig, rig_name, anim, sheet, grid, source, colors, art_root) -> None:
   frame_w, frame_h = prof.frame
   art_grid = None
   if art_root is not None:
      art_grid = _split_sheet(art_root / sheet["file"], frame_w, frame_h, anim)

   art_rows = list(sheet["directions"])
   for row, direction in enumerate(source):
      # 마커 시트는 반전 방향 줄이 없을 수 있다. 아트 격자는 줄 번호가 아니라 방향 이름으로 찾는다.
      art_row = _art_row(art_grid, art_rows, direction, anim)
      for col, frame in enumerate(grid[row]):
         art = art_row[col] if art_row is not None else None
         _collect_frame(book, rig, rig_name, anim, direction, col, frame, art, colors)


def _art_row(art_grid, art_rows: list[str], direction: str, anim: str):
   if art_grid is None:
      return None
   if direction not in art_rows or art_rows.index(direction) >= len(art_grid):
      raise ArtToolError(f"{anim} 아트 시트에 {direction} 줄이 없다")
   return art_grid[art_rows.index(direction)]


def _collect_frame(book, rig, rig_name, anim, direction, col, frame, art, colors) -> None:
   where = f"{anim}/{direction}/{col}"
   if art is not None:
      _check_color_clash(art, colors, where)
   for point, rgb in colors.items():
      x, y = _one_marker(frame, rgb, f"{where}/{point}")
      book.add(rig_name, anim, direction, col, point, x, y, _resolve_z(rig, point, direction))


def _mirror_sheet(book, rig, rig_name, anim, mirrored, frame_w) -> None:
   if not mirrored:
      return
   west = [p for p in book.points if p["anim"] == anim and p["direction"] == "west"]
   if not west:
      raise ArtToolError(f"{anim} 에 west 점이 없어 east 를 못 만든다")
   for direction in mirrored:
      if direction != "east":
         raise ArtToolError(f"반전으로 만들 수 있는 방향은 east 뿐이다 : {direction}")
      for point in west:
         z = _resolve_z(rig, point["point"], "east")
         book.add(rig_name, anim, "east", point["frame"], point["point"], _mirror_x(point["x"], frame_w), point["y"], z)


def from_skeleton_json(prof: Profile, data: dict, rig_name: str) -> dict:
   """PixelLab estimate-skeleton 의 0~1 실수를 들여올 때 한 번만 반올림한다."""
   frame_w, frame_h = prof.frame
   book = PointBook()
   for row in data.get("points", []):
      x = int(round(float(row["x"]) * (frame_w - 1)))
      y = int(round(float(row["y"]) * (frame_h - 1)))
      book.add(rig_name, row["anim"], row["direction"], int(row["frame"]), row["point"], x, y, int(row.get("z", 0)))
   return {"version": VERSION, "profile": prof.name, "frame": [frame_w, frame_h], "points": book.points}


def load(path: str | Path) -> dict:
   data = read_json(path)
   if data.get("version") != VERSION:
      raise ArtToolError(f"모르는 앵커 판 번호 : {data.get('version')}")
   return data
