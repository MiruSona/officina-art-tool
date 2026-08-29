import pytest

import helpers
from arttool import image
from arttool.errors import ArtToolError
from arttool.tiles import blob

TILE = 8

MARK = {
   "fill": (61, 92, 155),
   "edge_n": (27, 42, 74),
   "edge_w": (58, 155, 92),
   "corner_outer": (192, 160, 68),
   "corner_inner": (155, 61, 61),
   "single": (210, 210, 216),
}


def write_templates(folder, size=TILE):
   folder.mkdir(parents=True, exist_ok=True)
   for name, color in MARK.items():
      arr = image.new(size, size)
      arr[:, :] = (*color, 255)
      image.save(folder / f"{name}.png", arr)
   return folder


def test_47_masks():
   masks = blob.blob_masks()
   assert len(masks) == 47
   assert masks[0] == 0
   assert masks[-1] == 255


def test_normalize_drops_lonely_diagonal():
   assert blob.normalize_mask(blob.NE) == 0
   assert blob.normalize_mask(blob.N | blob.E | blob.NE) == blob.N | blob.E | blob.NE
   assert blob.normalize_mask(blob.N | blob.NE) == blob.N


def test_piece_choice():
   full = 0xFF
   assert blob.piece_for(0, blob.N, blob.W, blob.NW) == blob.OUTER
   assert blob.piece_for(blob.N, blob.N, blob.W, blob.NW) == blob.EDGE_W
   assert blob.piece_for(blob.W, blob.N, blob.W, blob.NW) == blob.EDGE_N
   assert blob.piece_for(blob.N | blob.W, blob.N, blob.W, blob.NW) == blob.INNER
   assert blob.piece_for(full, blob.N, blob.W, blob.NW) == blob.FILL


def test_build_writes_47_files(tmp_path):
   prof = helpers.tiny_profile(tmp_path, **{"tiles.size": TILE})
   templates = write_templates(tmp_path / "t6")
   data = blob.build(prof, templates, tmp_path / "out")

   assert data["count"] == 47
   assert len(list((tmp_path / "out").glob("blob_*.png"))) == 47
   assert (tmp_path / "out" / "tileset.json").is_file()
   sheet = image.load(tmp_path / "out" / "tileset.png")
   assert image.size(sheet) == (8 * TILE, 6 * TILE)


def test_lookup_covers_256(tmp_path):
   prof = helpers.tiny_profile(tmp_path, **{"tiles.size": TILE})
   data = blob.build(prof, write_templates(tmp_path / "t6"), tmp_path / "out")
   assert len(data["lookup"]) == 256
   assert data["lookup"]["2"] == data["lookup"]["0"]


def test_full_tile_is_all_fill(tmp_path):
   prof = helpers.tiny_profile(tmp_path, **{"tiles.size": TILE})
   templates = blob.load_templates(write_templates(tmp_path / "t6"), TILE)
   tile = blob.make_tile(templates, 0xFF, TILE)
   assert image.opaque_colors(tile) == {MARK["fill"]}


def test_lone_tile_uses_single(tmp_path):
   templates = blob.load_templates(write_templates(tmp_path / "t6"), TILE)
   tile = blob.make_tile(templates, 0, TILE)
   assert image.opaque_colors(tile) == {MARK["single"]}


def test_corner_quadrants_use_outer(tmp_path):
   templates = blob.load_templates(write_templates(tmp_path / "t6"), TILE)
   tile = blob.make_tile(templates, blob.S | blob.E | blob.SE, TILE)
   half = TILE // 2
   assert tuple(tile[0, 0])[:3] == MARK["corner_outer"]
   assert tuple(tile[half, half])[:3] == MARK["fill"]
   assert tuple(tile[0, half])[:3] == MARK["edge_n"]
   assert tuple(tile[half, 0])[:3] == MARK["edge_w"]


def test_inner_corner(tmp_path):
   templates = blob.load_templates(write_templates(tmp_path / "t6"), TILE)
   tile = blob.make_tile(templates, 0xFF & ~blob.NW, TILE)
   assert tuple(tile[0, 0])[:3] == MARK["corner_inner"]


def test_missing_template(tmp_path):
   folder = write_templates(tmp_path / "t6")
   (folder / "fill.png").unlink()
   prof = helpers.tiny_profile(tmp_path, **{"tiles.size": TILE})
   with pytest.raises(ArtToolError, match="템플릿 6장"):
      blob.build(prof, folder, tmp_path / "out")


def test_wrong_template_size(tmp_path):
   folder = write_templates(tmp_path / "t6", size=TILE)
   image.save(folder / "fill.png", image.new(TILE + 1, TILE))
   prof = helpers.tiny_profile(tmp_path, **{"tiles.size": TILE})
   with pytest.raises(ArtToolError, match="조각 경계"):
      blob.build(prof, folder, tmp_path / "out")


def test_odd_tile_size(tmp_path):
   prof = helpers.tiny_profile(tmp_path, **{"tiles.size": 7})
   with pytest.raises(ArtToolError, match="홀수"):
      blob.build(prof, tmp_path / "t6", tmp_path / "out")
