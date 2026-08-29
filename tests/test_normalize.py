import pytest

import helpers
from arttool import image
from arttool.errors import ArtToolError
from arttool.sprite import normalize


def test_normalize_makes_sheet_and_index(tmp_path):
   prof = helpers.tiny_profile(tmp_path)
   raw = tmp_path / "raw"
   helpers.write_singles(raw, prof)

   out = tmp_path / "build"
   index = normalize.normalize(prof, raw, out, ["walk"])

   assert index["frame"] == [16, 16]
   sheet = index["sheets"][0]
   assert sheet["cols"] == 2 and sheet["rows"] == 4
   arr = image.load(out / "walk.png")
   assert image.size(arr) == (32, 64)
   assert (out / "frames.json").is_file()


def test_baseline_and_center_are_fixed(tmp_path):
   prof = helpers.tiny_profile(tmp_path)
   raw = tmp_path / "raw"
   helpers.write_singles(raw, prof)
   out = tmp_path / "build"
   normalize.normalize(prof, raw, out, ["walk"])

   rows = image.split_grid(image.load(out / "walk.png"), 16, 16)
   for row in rows:
      for frame in row:
         x0, y0, x1, y1 = image.bbox(frame)
         assert y1 - 1 == 13
         assert abs((x0 + x1 - 1) / 2.0 - 7.5) <= 0.5


def test_frame_count_mismatch(tmp_path):
   prof = helpers.tiny_profile(tmp_path)
   raw = tmp_path / "raw"
   helpers.write_singles(raw, prof)
   (raw / "walk_south_1.png").unlink()
   with pytest.raises(ArtToolError, match="프레임이"):
      normalize.normalize(prof, raw, tmp_path / "b", ["walk"])


def test_soft_alpha_rejected(tmp_path):
   prof = helpers.tiny_profile(tmp_path)
   art = helpers.blob(6, 6)
   art[2, 2] = (10, 10, 10, 128)
   with pytest.raises(ArtToolError, match="반투명"):
      normalize.fit_frame(art, prof, "시험")


def test_too_big_for_canvas(tmp_path):
   prof = helpers.tiny_profile(tmp_path)
   with pytest.raises(ArtToolError, match="큽|크다"):
      normalize.fit_frame(helpers.blob(20, 20), prof, "시험")


def test_empty_frame_rejected(tmp_path):
   prof = helpers.tiny_profile(tmp_path)
   with pytest.raises(ArtToolError, match="빈 그림"):
      normalize.fit_frame(image.new(16, 16), prof, "시험")


def test_east_from_west_mirror(tmp_path):
   prof = helpers.tiny_profile(tmp_path)
   raw = tmp_path / "raw"
   helpers.write_singles(raw, prof)
   for index in range(2):
      (raw / f"walk_east_{index}.png").unlink()

   index = normalize.normalize(prof, raw, tmp_path / "build", ["walk"])
   assert index["sheets"][0]["mirrored"] == ["east"]


def test_missing_direction_without_mirror(tmp_path):
   prof = helpers.tiny_profile(tmp_path, **{"tiles.mirror_east_from_west": False})
   raw = tmp_path / "raw"
   helpers.write_singles(raw, prof)
   (raw / "walk_east_0.png").unlink()
   (raw / "walk_east_1.png").unlink()
   with pytest.raises(ArtToolError, match="그림이 없다"):
      normalize.normalize(prof, raw, tmp_path / "build", ["walk"])


def test_unknown_anim(tmp_path):
   prof = helpers.tiny_profile(tmp_path)
   raw = tmp_path / "raw"
   helpers.write_singles(raw, prof)
   with pytest.raises(ArtToolError, match="없는 애니메이션"):
      normalize.normalize(prof, raw, tmp_path / "build", ["없음"])


def test_grid_sheet_input(tmp_path):
   prof = helpers.tiny_profile(tmp_path)
   raw = tmp_path / "raw"
   helpers.write_singles(raw, prof)
   mid = tmp_path / "mid"
   normalize.normalize(prof, raw, mid, ["walk"])

   again = tmp_path / "again"
   index = normalize.normalize(prof, mid, again, ["walk"])
   assert index["sheets"][0]["rows"] == 4
