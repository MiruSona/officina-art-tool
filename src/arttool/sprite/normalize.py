"""① 규격 맞추기. 낱장·시트를 프레임 크기·baseline·중심에 맞춘 시트로 만든다.

들어오는 파일 이름은 셋 중 하나다.
  walk.png              방향이 줄, 프레임이 칸인 격자 시트
  walk_south.png        한 방향짜리 가로 시트
  walk_south_0.png      낱장
"""

from __future__ import annotations

import math
from pathlib import Path

from .. import image
from ..errors import ArtToolError
from ..jsonio import write_json
from ..paths import resolve_root, safe_join
from ..profile import Profile


def _anim_dirs(prof: Profile, anim: str) -> list[str]:
   spec = prof.anim[anim]
   return prof.direction_names(int(spec.get("dirs", prof.directions)))


def _anim_frames(prof: Profile, anim: str) -> int:
   return int(prof.anim[anim]["frames"])


def _load_grid_sheet(in_dir: Path, anim: str, prof: Profile) -> list[list[image.RGBA]] | None:
   path = in_dir / f"{anim}.png"
   if not path.is_file():
      return None
   frame_w, frame_h = prof.frame
   return image.split_grid(image.load(path), frame_w, frame_h)


def _load_row_sheet(in_dir: Path, anim: str, direction: str, prof: Profile) -> list[image.RGBA] | None:
   path = in_dir / f"{anim}_{direction}.png"
   if not path.is_file():
      return None
   frame_w, frame_h = prof.frame
   rows = image.split_grid(image.load(path), frame_w, frame_h)
   if len(rows) != 1:
      raise ArtToolError(f"{path.name} 은 한 줄짜리 시트여야 한다 (줄 {len(rows)})")
   return rows[0]


def _frame_number(path: Path) -> int:
   tail = path.stem.rsplit("_", 1)[-1]
   if not tail.isdigit():
      raise ArtToolError(f"낱장 이름 끝이 번호가 아니다 : {path.name}")
   return int(tail)


def _load_singles(in_dir: Path, anim: str, direction: str, only_dir: bool) -> list[image.RGBA] | None:
   names = sorted(in_dir.glob(f"{anim}_{direction}_*.png"), key=_frame_number)
   if not names and only_dir:
      names = sorted(in_dir.glob(f"{anim}_[0-9]*.png"), key=_frame_number)
   if not names:
      return None
   return [image.load(p) for p in names]


def _grid_directions(prof: Profile, directions: list[str], grid) -> list[str]:
   """격자 시트의 줄이 어느 방향인가. east 하나만큼 모자라면 반전으로 채울 시트로 본다."""
   if grid is None:
      return []
   if len(grid) == len(directions):
      return list(directions)
   source = [d for d in directions if d != "east"]
   if prof.mirror_east() and len(grid) == len(source):
      return source
   return list(directions)[: len(grid)]


def _collect_one(in_dir: Path, prof: Profile, anim: str, direction: str, grid, row_index: int | None):
   if grid is not None:
      # 줄이 없으면 여기서 터뜨리지 않는다. 반전으로 채울 방향인지는 collect 가 본다.
      if row_index is None:
         return None
      return grid[row_index]

   frames = _load_row_sheet(in_dir, anim, direction, prof)
   if frames is not None:
      return frames
   return _load_singles(in_dir, anim, direction, only_dir=len(_anim_dirs(prof, anim)) == 1)


def collect(in_dir: Path, prof: Profile, anim: str) -> tuple[dict[str, list[image.RGBA]], list[str]]:
   """방향별 원본 프레임을 모은다. 반전으로 채울 방향 이름도 같이 준다.

   반전은 여기서 안 한다. 규격을 맞춘 뒤에 해야 프레임 통째 반전이 참이 되고
   앵커의 x' = frame_w - 1 - x 가 그림과 맞는다.
   """
   directions = _anim_dirs(prof, anim)
   grid = _load_grid_sheet(in_dir, anim, prof)
   rows = _grid_directions(prof, directions, grid)
   found: dict[str, list[image.RGBA]] = {}
   for direction in directions:
      row_index = rows.index(direction) if direction in rows else None
      frames = _collect_one(in_dir, prof, anim, direction, grid, row_index)
      if frames is not None:
         found[direction] = frames

   mirrored = []
   if "east" in directions and "east" not in found and prof.mirror_east() and "west" in found:
      mirrored.append("east")

   missing = [d for d in directions if d not in found and d not in mirrored]
   if missing:
      raise ArtToolError(f"{anim} 의 그림이 없다 : {', '.join(missing)}")
   return found, mirrored


def fit_frame(arr: image.RGBA, prof: Profile, where: str) -> image.RGBA:
   """한 장을 프레임 캔버스에 앉힌다. 발끝이 baseline, 가로는 center_x 에 맞춘다."""
   frame_w, frame_h = prof.frame
   if prof.check["allow_alpha"] == "binary" and image.has_soft_alpha(arr):
      raise ArtToolError(f"반투명 픽셀이 있다 : {where}")

   box = image.bbox(arr)
   if box is None:
      raise ArtToolError(f"빈 그림이다 : {where}")

   x0, y0, x1, y1 = box
   content = image.crop(arr, x0, y0, x1 - x0, y1 - y0)
   width, height = image.size(content)
   if width > frame_w or height > frame_h:
      raise ArtToolError(f"그림 {width}x{height} 가 프레임 {frame_w}x{frame_h} 보다 크다 : {where}")

   baseline = int(prof.canvas["baseline_y"])
   # round 는 .5 를 짝수 쪽으로 보내서 너비에 따라 중심이 1픽셀 튄다. floor(x+0.5) 로 한쪽으로 고정한다.
   left = math.floor(float(prof.canvas["center_x"]) - width / 2.0 + 0.5)
   top = baseline - height + 1
   if left < 0 or top < 0 or left + width > frame_w or top + height > frame_h:
      raise ArtToolError(f"캔버스가 안 맞는다 (자리 {left},{top} 크기 {width}x{height}) : {where}")

   canvas = image.new(frame_w, frame_h)
   image.paste(canvas, content, left, top)
   return canvas


def _fit_rows(prof: Profile, anim: str, directions, found, mirrored, want) -> list[list[image.RGBA]]:
   """규격을 먼저 맞추고, 반전 방향은 맞춰진 결과를 뒤집어 채운다."""
   fitted: dict[str, list[image.RGBA]] = {}
   for direction in directions:
      if direction in mirrored:
         continue
      frames = found[direction]
      if len(frames) != want:
         raise ArtToolError(f"{anim}/{direction} 프레임이 {len(frames)}장이다. 프로필은 {want}장")
      fitted[direction] = [fit_frame(f, prof, f"{anim}/{direction}/{i}") for i, f in enumerate(frames)]

   for direction in mirrored:
      fitted[direction] = [image.flip_x(f) for f in fitted["west"]]
   return [fitted[d] for d in directions]


def normalize(prof: Profile, in_dir: str | Path, out_dir: str | Path, anims: list[str] | None = None) -> dict:
   source = Path(in_dir)
   if not source.is_dir():
      raise ArtToolError(f"입력 폴더가 없다 : {source}")
   root = resolve_root(out_dir)

   picked = anims or list(prof.anim)
   unknown = [a for a in picked if a not in prof.anim]
   if unknown:
      raise ArtToolError(f"프로필에 없는 애니메이션 : {', '.join(unknown)}")

   frame_w, frame_h = prof.frame
   sheets = []
   for anim in picked:
      want = _anim_frames(prof, anim)
      found, mirrored = collect(source, prof, anim)
      directions = _anim_dirs(prof, anim)

      rows = _fit_rows(prof, anim, directions, found, mirrored, want)

      out_file = safe_join(root, f"{anim}.png")
      image.save(out_file, image.pack_grid(rows, frame_w, frame_h))
      sheets.append(
         {
            "anim": anim,
            "file": out_file.name,
            "frames": want,
            "directions": directions,
            "cols": want,
            "rows": len(directions),
            "mirrored": mirrored,
         }
      )

   index = {
      "version": 1,
      "profile": prof.name,
      "frame": [frame_w, frame_h],
      "baseline_y": int(prof.canvas["baseline_y"]),
      "sheets": sheets,
   }
   write_json(safe_join(root, "frames.json"), index)
   return index
