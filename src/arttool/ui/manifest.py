"""ui_manifest.json 쓰기·읽기와 아틀라스 자리 잡기.

border 순서는 [왼, 아래, 오른, 위] - Unity spriteBorder 의 Vector4 순서다. 바꾸지 않는다.
rect 는 [x1, y1, x2, y2] 로 왼쪽 위 기준이다.
"""

from __future__ import annotations

from pathlib import Path

from ..errors import ArtToolError
from ..jsonio import read_json, write_json
from ..profile import Profile

VERSION = 1
ATLAS_NAME = "ui_atlas.png"


def _next_pow2(value: int) -> int:
   size = 1
   while size < value:
      size *= 2
   return size


def _shelf(items: list[tuple[str, int, int]], width: int) -> tuple[dict[str, tuple[int, int]], int]:
   """왼쪽부터 채우다 줄이 차면 아래로 내려간다. 같은 입력이면 늘 같은 자리가 나온다."""
   spots: dict[str, tuple[int, int]] = {}
   x, y, row_height = 0, 0, 0
   for name, w, h in items:
      if x + w > width:
         x = 0
         y += row_height
         row_height = 0
      spots[name] = (x, y)
      x += w
      row_height = max(row_height, h)
   return spots, y + row_height


def pack(items: list[tuple[str, int, int]]) -> tuple[dict[str, tuple[int, int]], tuple[int, int]]:
   """이름·너비·높이 목록을 아틀라스에 앉힌다. 가로는 2의 거듭제곱으로 잡고 정사각에 가깝게 늘린다."""
   if not items:
      raise ArtToolError("아틀라스에 넣을 그림이 없다")

   width = _next_pow2(max(w for _n, w, _h in items))
   while True:
      spots, height = _shelf(items, width)
      if height <= width or width >= 8192:
         return spots, (width, _next_pow2(height))
      width *= 2


def check_group_borders(frames: list[dict]) -> None:
   """같은 group 안에서 border 가 다르면 눌렸을 때 창이 들썩인다."""
   seen: dict[str, tuple] = {}
   for entry in frames:
      group = entry["group"]
      border = tuple(entry["border"])
      if group in seen and seen[group] != border:
         raise ArtToolError(f"{group} 묶음 안에서 border 가 다르다 : {list(seen[group])} 와 {list(border)}")
      seen[group] = border


def check_unique_names(frames: list[dict], icons: list[dict]) -> None:
   """이름 하나가 아틀라스 자리 하나다. 겹치면 한 그림이 두 자리에 붙는다."""
   seen: set[str] = set()
   twice = []
   for entry in frames + icons:
      if entry["name"] in seen:
         twice.append(entry["name"])
      seen.add(entry["name"])
   if twice:
      raise ArtToolError(f"프레임·아이콘 이름이 겹친다 : {', '.join(sorted(set(twice)))}")


def build(prof: Profile, frames: list[dict], icons: list[dict], atlas: str = ATLAS_NAME) -> dict:
   check_group_borders(frames)
   check_unique_names(frames, icons)

   items = [(f"frame:{f['name']}", f["size"][0], f["size"][1]) for f in frames]
   items += [(f"icon:{i['name']}", i["size"], i["size"]) for i in icons]
   spots, (width, height) = pack(items)

   frame_rows = []
   for entry in frames:
      x, y = spots[f"frame:{entry['name']}"]
      w, h = entry["size"]
      frame_rows.append(
         {
            "name": entry["name"],
            "rect": [x, y, x + w, y + h],
            "border": list(entry["border"]),
            "min_size": list(entry["min_size"]),
            "content_padding": list(entry["content_padding"]),
            "state": entry["state"],
            "group": entry["group"],
         }
      )

   icon_rows = []
   for entry in icons:
      x, y = spots[f"icon:{entry['name']}"]
      size = int(entry["size"])
      icon_rows.append(
         {
            "name": entry["name"],
            "rect": [x, y, x + size, y + size],
            "size": size,
            "family": entry["family"],
            "hotspot": list(entry.get("hotspot", [size // 2, size // 2])),
         }
      )

   return {
      "version": VERSION,
      "profile": prof.name,
      "ppu": int(prof.ui["ppu"]),
      "reference": list(prof.ui["reference"]),
      "slice_scale": prof.slice_scale(),
      "atlas": atlas,
      "atlas_size": [width, height],
      "frames": frame_rows,
      "icons": icon_rows,
   }


def save(path: str | Path, data: dict) -> None:
   write_json(path, data)


def load(path: str | Path) -> dict:
   data = read_json(path)
   if data.get("version") != VERSION:
      raise ArtToolError(f"모르는 UI 매니페스트 판 번호 : {data.get('version')}")
   return data


def frame_by_name(data: dict, name: str) -> dict:
   for entry in data.get("frames", []):
      if entry["name"] == name:
         return entry
   raise ArtToolError(f"매니페스트에 없는 프레임 : {name}")
