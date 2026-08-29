"""①ㄴ 들여오기. `.9.png` 바깥 1px 안내선을 읽어 border 를 뽑고 안내선을 떼어 낸다.

| 테두리 자리 | 뜻 | 쓰는 곳 |
| --- | --- | --- |
| 위 | 가로로 늘어나는 구간 | border 왼·오른 |
| 왼쪽 | 세로로 늘어나는 구간 | border 위·아래 |
| 아래 · 오른쪽 | 글자가 들어가는 안쪽 영역 | content_padding. 없으면 border 와 같다 |

원본 파일은 안 고친다. 안내선 뗀 PNG 를 따로 쓴다.
"""

from __future__ import annotations

from pathlib import Path

from .. import image
from ..errors import ArtToolError
from ..paths import resolve_root, safe_join
from ..profile import Profile
from .frame import merge_border_file

VERSION = 1
SUFFIX = ".9.png"


def _is_guide(arr: image.RGBA, x: int, y: int) -> bool:
   pixel = arr[y, x]
   if int(pixel[3]) != 255:
      return False
   return int(pixel[0]) == 0 and int(pixel[1]) == 0 and int(pixel[2]) == 0


def _runs(marks: list[bool]) -> list[tuple[int, int]]:
   """참인 칸이 이어진 구간 목록. 끝은 포함하지 않는다."""
   found = []
   start = None
   for index, mark in enumerate(marks):
      if mark and start is None:
         start = index
      if not mark and start is not None:
         found.append((start, index))
         start = None
   if start is not None:
      found.append((start, len(marks)))
   return found


def _one_run(marks: list[bool], where: str, required: bool) -> tuple[int, int] | None:
   found = _runs(marks)
   if len(found) > 1:
      raise ArtToolError(f"{where} 안내선의 검은 구간이 {len(found)}개다. 하나여야 한다")
   if not found:
      if required:
         raise ArtToolError(f"{where} 안내선이 없다. .9.png 규약대로 검은 점을 그린다")
      return None
   return found[0]


def _check_corners(arr: image.RGBA, width: int, height: int) -> None:
   spots = ((0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1))
   bad = [(x, y) for x, y in spots if _is_guide(arr, x, y)]
   if bad:
      raise ArtToolError(f"안내선이 네 변에 안 맞는다. 귀퉁이에 검은 점이 있다 : {bad}")


def read_guides(arr: image.RGBA) -> dict:
   """안내선을 읽어 border 와 content_padding 을 낸다. 순서는 [왼, 아래, 오른, 위]."""
   width, height = image.size(arr)
   if width < 3 or height < 3:
      raise ArtToolError(f"안내선을 두르기에 너무 작다 : {width}x{height}")

   _check_corners(arr, width, height)
   inner_w, inner_h = width - 2, height - 2

   top = _one_run([_is_guide(arr, x, 0) for x in range(1, width - 1)], "위쪽", required=True)
   left = _one_run([_is_guide(arr, 0, y) for y in range(1, height - 1)], "왼쪽", required=True)
   bottom = _one_run([_is_guide(arr, x, height - 1) for x in range(1, width - 1)], "아래쪽", required=False)
   right = _one_run([_is_guide(arr, width - 1, y) for y in range(1, height - 1)], "오른쪽", required=False)

   border = [top[0], inner_h - left[1], inner_w - top[1], left[0]]
   padding = list(border)
   if bottom is not None:
      padding[0], padding[2] = bottom[0], inner_w - bottom[1]
   if right is not None:
      padding[3], padding[1] = right[0], inner_h - right[1]
   return {"border": border, "content_padding": padding, "size": [inner_w, inner_h]}


def strip(arr: image.RGBA) -> image.RGBA:
   """안내선 1px 을 떼어 낸 그림."""
   width, height = image.size(arr)
   return image.crop(arr, 1, 1, width - 2, height - 2)


def split_name(stem: str, states: list[str]) -> tuple[str, str]:
   """panel_normal → (panel, normal).

   뒤 조각이 상태 목록에 있을 때만 상태로 본다. dialog_box 는 통째로 묶음 이름이다.
   """
   if "_" not in stem:
      return stem, "normal"

   group, tail = stem.rsplit("_", 1)
   if tail in states and group:
      return group, tail
   return stem, "normal"


def import_file(path: str | Path, out_dir: str | Path, states: list[str] | None = None) -> dict:
   source = Path(path)
   if not source.name.endswith(SUFFIX):
      raise ArtToolError(f"안내선이 없다 : {source.name} - 이름이 {SUFFIX} 로 끝나야 한다")

   arr = image.load(source)
   guides = read_guides(arr)
   stem = source.name[: -len(SUFFIX)]
   group, state = split_name(stem, states or ["normal"])

   root = resolve_root(out_dir)
   out_file = safe_join(root, f"{stem}.png")
   image.save(out_file, strip(arr))
   return {
      "name": stem,
      "group": group,
      "state": state,
      "size": guides["size"],
      "border": guides["border"],
      "min_size": _min_size_of(guides["border"]),
      "content_padding": guides["content_padding"],
      "file": out_file.name,
   }


def _min_size_of(border: list[int], slack: int = 1) -> list[int]:
   left, bottom, right, top = border
   return [left + right + slack, top + bottom + slack]


def import_dir(prof: Profile, in_dir: str | Path, out_dir: str | Path) -> dict:
   source = Path(in_dir)
   if not source.is_dir():
      raise ArtToolError(f"들여올 폴더가 없다 : {source}")

   files = sorted(p for p in source.glob(f"*{SUFFIX}"))
   if not files:
      raise ArtToolError(f"{source} 에 {SUFFIX} 파일이 없다. 안내선 없는 낱장은 안 받는다")

   slack = int(prof.ui["check"]["min_size_slack"])
   root = resolve_root(out_dir)
   frames = []
   for file in files:
      entry = import_file(file, root, list(prof.ui["generator"]["states"]))
      entry["min_size"] = _min_size_of(entry["border"], slack)
      frames.append(entry)

   merge_border_file(root, prof, frames)
   return {"out": str(root), "frames": frames}
