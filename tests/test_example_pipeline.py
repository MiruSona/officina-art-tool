"""Example/ 참고 그림으로 네 단계를 실제로 돌린다."""

import numpy as np

from arttool import bake, check, image, profile
from arttool.jsonio import read_json, write_json
from arttool.sprite import anchors, normalize

SOURCE = {"south": "Front.png", "west": "Left.png", "north": "Back.png"}


def test_shipped_profiles_load():
   for name in ("topdown_action", "slime_demo"):
      assert profile.load_profile(name).name == name


def make_raw(tmp_path):
   raw = tmp_path / "raw"
   raw.mkdir()
   example = profile.tool_home() / "Example"
   for direction, file_name in SOURCE.items():
      image.save(raw / f"idle_{direction}_0.png", image.load(example / file_name))
   return raw


def test_example_runs_end_to_end(tmp_path):
   prof = profile.load_profile("slime_demo")
   raw = make_raw(tmp_path)
   build = tmp_path / "build"

   index = normalize.normalize(prof, raw, build, ["idle"])
   assert index["sheets"][0]["mirrored"] == ["east"]

   report = check.run(prof, build)
   assert report["status"] == "ok", report["failed"]
   write_json(build / "check.json", report)

   result = bake.bake(prof, build, tmp_path / "unity", "Game.Art")
   assert "palette_lut.png" in result["files"]
   manifest = read_json(tmp_path / "unity" / "sprite_manifest.json")
   assert len(manifest["animations"][0]["entries"]) == 4


def test_mirrored_east_is_flipped_west(tmp_path):
   """프레임 통째로 본다. 잘라낸 내용만 비교하면 자리가 어긋나도 통과한다."""
   prof = profile.load_profile("slime_demo")
   build = tmp_path / "build"
   normalize.normalize(prof, make_raw(tmp_path), build, ["idle"])

   rows = image.split_grid(image.load(build / "idle.png"), 64, 64)
   west, east = rows[1][0], rows[3][0]
   assert np.array_equal(image.flip_x(west), east)


def test_east_anchor_lands_on_the_east_drawing(tmp_path):
   """west 마커만 주고 east 를 반전으로 얻은 뒤, 그 좌표에 실제 픽셀이 있는지 본다."""
   prof = profile.load_profile("slime_demo")
   build = tmp_path / "build"
   index = normalize.normalize(prof, make_raw(tmp_path), build, ["idle"])
   rows = image.split_grid(image.load(build / "idle.png"), 64, 64)

   markers = tmp_path / "markers"
   markers.mkdir()
   made = []
   for row in range(3):
      frame = image.new(64, 64)
      head = _first_opaque(rows[row][0])
      foot = _last_opaque(rows[row][0])
      frame[head[1], head[0]] = (255, 0, 255, 255)
      frame[foot[1], foot[0]] = (255, 128, 0, 255)
      made.append([frame])
   image.save(markers / "idle.png", image.pack_grid(made, 64, 64))

   data = anchors.extract(prof, index, markers, "blob")
   for point in data["points"]:
      arr = rows[index["sheets"][0]["directions"].index(point["direction"])][0]
      assert arr[point["y"], point["x"]][3] == 255, point


def _first_opaque(arr):
   ys, xs = np.nonzero(arr[:, :, 3] > 0)
   return int(xs[0]), int(ys[0])


def _last_opaque(arr):
   ys, xs = np.nonzero(arr[:, :, 3] > 0)
   return int(xs[-1]), int(ys[-1])
