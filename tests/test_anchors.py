import pytest

import helpers
from arttool import image
from arttool.errors import ArtToolError
from arttool.sprite import anchors, normalize

TWO_POINTS = {"rigs.blob.anchors": ["head_top", "ground"]}


def build(tmp_path, **extra):
   over = dict(TWO_POINTS)
   over.update(extra)
   prof = helpers.tiny_profile(tmp_path, **over)
   raw = tmp_path / "raw"
   helpers.write_singles(raw, prof)
   index = normalize.normalize(prof, raw, tmp_path / "build", ["walk"])
   return prof, index


def test_extract_points(tmp_path):
   prof, index = build(tmp_path)
   markers = tmp_path / "markers"
   helpers.write_markers(markers, prof)

   data = anchors.extract(prof, index, markers, "blob")
   assert data["frame"] == [16, 16]
   assert len(data["points"]) == 4 * 2 * 2

   head_south = [p for p in data["points"] if p["direction"] == "south" and p["point"] == "head_top"]
   assert [p["x"] for p in head_south] == [5, 6]
   assert head_south[0]["y"] == 3
   assert head_south[0]["z"] == 10


def test_z_per_direction(tmp_path):
   prof, index = build(tmp_path)
   markers = tmp_path / "markers"
   helpers.write_markers(markers, prof)
   data = anchors.extract(prof, index, markers, "blob")

   north = next(p for p in data["points"] if p["direction"] == "north" and p["point"] == "head_top")
   ground = next(p for p in data["points"] if p["point"] == "ground")
   assert north["z"] == -10
   assert ground["z"] == 0


def test_missing_marker(tmp_path):
   prof, index = build(tmp_path)
   markers = tmp_path / "markers"
   helpers.write_markers(markers, prof)
   sheet = image.load(markers / "walk.png")
   sheet[3, 5] = (0, 0, 0, 0)
   image.save(markers / "walk.png", sheet)
   with pytest.raises(ArtToolError, match="빠졌다"):
      anchors.extract(prof, index, markers, "blob")


def test_two_markers(tmp_path):
   prof, index = build(tmp_path)
   markers = tmp_path / "markers"
   helpers.write_markers(markers, prof)
   sheet = image.load(markers / "walk.png")
   sheet[4, 5] = (*helpers.MARKER_HEAD, 255)
   image.save(markers / "walk.png", sheet)
   with pytest.raises(ArtToolError, match="마커가"):
      anchors.extract(prof, index, markers, "blob")


def test_marker_color_clashes_with_art(tmp_path):
   prof, index = build(tmp_path)
   markers = tmp_path / "markers"
   helpers.write_markers(markers, prof)

   art = image.load(tmp_path / "build" / "walk.png")
   art[13, 3] = (*helpers.MARKER_HEAD, 255)
   image.save(tmp_path / "build" / "walk.png", art)
   with pytest.raises(ArtToolError, match="겹친다"):
      anchors.extract(prof, index, markers, "blob", art_dir=tmp_path / "build")


def test_east_mirrored_flips_x(tmp_path):
   prof, index = build(tmp_path)
   raw = tmp_path / "raw"
   for i in range(2):
      (raw / f"walk_east_{i}.png").unlink()
   index = normalize.normalize(prof, raw, tmp_path / "build2", ["walk"])
   assert index["sheets"][0]["mirrored"] == ["east"]

   markers = tmp_path / "markers3"
   helpers.write_markers(markers, prof, directions=["south", "west", "north"])
   data = anchors.extract(prof, index, markers, "blob")

   west = next(p for p in data["points"] if p["direction"] == "west" and p["point"] == "head_top" and p["frame"] == 0)
   east = next(p for p in data["points"] if p["direction"] == "east" and p["point"] == "head_top" and p["frame"] == 0)
   assert east["x"] == 16 - 1 - west["x"]
   assert east["y"] == west["y"]


def test_duplicate_key_rejected(tmp_path):
   book = anchors.PointBook()
   book.add("blob", "walk", "south", 0, "head_top", 1, 2, 0)
   with pytest.raises(ArtToolError, match="두 번"):
      book.add("blob", "walk", "south", 0, "head_top", 5, 6, 0)


def test_layer_rig_rejected(tmp_path):
   prof, index = build(tmp_path)
   with pytest.raises(ArtToolError, match="앵커 rig 가 아니다"):
      anchors.extract(prof, index, tmp_path, "humanoid_lpc")


def test_skeleton_import_rounds(tmp_path):
   prof, _ = build(tmp_path)
   data = anchors.from_skeleton_json(
      prof,
      {"points": [{"anim": "walk", "direction": "south", "frame": 0, "point": "head_top", "x": 0.5, "y": 0.24, "z": 10}]},
      "blob",
   )
   point = data["points"][0]
   assert point["x"] == round(0.5 * 15)
   assert point["y"] == round(0.24 * 15)
   assert point["z"] == 10
