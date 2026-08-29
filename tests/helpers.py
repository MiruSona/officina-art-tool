"""시험용 그림을 코드로 만든다. 바깥 파일에 기대지 않는다."""

from __future__ import annotations

from pathlib import Path

from arttool import image, palette
from arttool.profile import load_profile, tool_home

BODY = (61, 92, 155)      # cloth_blue 3번
DARK = (27, 42, 74)       # cloth_blue 0번
CROWN = (192, 160, 68)    # gold 3번

MARKER_HEAD = (255, 0, 255)
MARKER_BACK = (0, 255, 0)
MARKER_FRONT = (0, 255, 255)
MARKER_GROUND = (255, 128, 0)


def tiny_profile(tmp_path: Path, **extra) -> object:
   """작은 프레임으로 줄인 시험용 프로필. 파일로 쓴 다음 읽는다."""
   overrides = {
      "canvas.frame": [16, 16],
      "canvas.baseline_y": 13,
      "canvas.center_x": 7.5,
      "anim": {"walk": {"frames": 2, "dirs": 4}},
   }
   overrides.update(extra)
   return load_profile("topdown_action", overrides)


def blob(width: int, height: int, body=BODY, outline=DARK):
   """가운데가 몸통, 테두리가 어두운 네모 하나."""
   arr = image.new(width, height)
   arr[:, :] = (*outline, 255)
   if width > 2 and height > 2:
      arr[1:-1, 1:-1] = (*body, 255)
   return arr


def put_on_canvas(arr, canvas_w: int, canvas_h: int, x: int, y: int):
   canvas = image.new(canvas_w, canvas_h)
   image.paste(canvas, arr, x, y)
   return canvas


def write_singles(out_dir: Path, prof, anim: str = "walk", sizes=None) -> None:
   """방향·프레임마다 낱장 PNG 하나씩 쓴다. 자리는 일부러 어긋나게 둔다."""
   out_dir.mkdir(parents=True, exist_ok=True)
   frame_w, frame_h = prof.frame
   count = int(prof.anim[anim]["frames"])
   for direction in prof.direction_names(int(prof.anim[anim]["dirs"])):
      for index in range(count):
         w, h = (sizes or (6, 6))
         art = blob(w, h + index)
         out = put_on_canvas(art, frame_w, frame_h, 1 + index, 2)
         image.save(out_dir / f"{anim}_{direction}_{index}.png", out)


def write_markers(out_dir: Path, prof, anim: str = "walk", directions=None) -> None:
   """규격 맞춘 시트와 짝이 되는 마커 시트를 쓴다. 한 프레임에 점 하나씩."""
   out_dir.mkdir(parents=True, exist_ok=True)
   frame_w, frame_h = prof.frame
   count = int(prof.anim[anim]["frames"])
   names = directions or prof.direction_names(int(prof.anim[anim]["dirs"]))
   rows = []
   for row, _direction in enumerate(names):
      row_frames = []
      for index in range(count):
         canvas = image.new(frame_w, frame_h)
         canvas[3, 5 + index] = (*MARKER_HEAD, 255)
         canvas[10, 4] = (*MARKER_GROUND, 255)
         row_frames.append(canvas)
      rows.append(row_frames)
   image.save(out_dir / f"{anim}.png", image.pack_grid(rows, frame_w, frame_h))


def sample_ramps():
   return palette.load_ramps(tool_home() / "palettes" / "lpc_cloth.json")
