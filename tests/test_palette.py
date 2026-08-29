import json

import pytest

from arttool import image, palette
from arttool.errors import ArtToolError
from arttool.profile import tool_home


def sample_path():
   return tool_home() / "palettes" / "lpc_cloth.json"


def test_parse_hex():
   assert palette.parse_hex("#FF8000") == (255, 128, 0)
   assert palette.to_hex((255, 128, 0)) == "#FF8000"


def test_bad_hex():
   with pytest.raises(ArtToolError):
      palette.parse_hex("FF8000")


def test_load_sample_ramps():
   ramps = palette.load_ramps(sample_path())
   assert ramps.ramp_len == 6
   assert "cloth_blue" in ramps.names()
   assert len(ramps.ramp("cloth_blue")) == 6
   assert (0, 0, 0) in ramps.colors()


def test_wrong_ramp_length(tmp_path):
   path = tmp_path / "r.json"
   path.write_text(json.dumps({"ramps": {"a": ["#000000"]}, "ramp_len": 3}), encoding="utf-8")
   with pytest.raises(ArtToolError):
      palette.load_ramps(path)


def test_outside_colors():
   ramps = palette.load_ramps(sample_path())
   arr = image.new(2, 1)
   arr[0, 0] = (*ramps.ramp("cloth_blue")[0], 255)
   arr[0, 1] = (1, 2, 3, 255)
   assert palette.outside_colors(arr, ramps) == [(1, 2, 3)]


def test_snap_exact_does_not_change():
   ramps = palette.load_ramps(sample_path())
   arr = image.new(1, 1)
   arr[0, 0] = (1, 2, 3, 255)
   out, strays = palette.snap_exact(arr, ramps)
   assert tuple(out[0, 0]) == (1, 2, 3, 255)
   assert strays == [(1, 2, 3)]


def test_snap_nearest_moves_to_ramp():
   ramps = palette.load_ramps(sample_path())
   target = ramps.ramp("cloth_blue")[2]
   arr = image.new(1, 1)
   arr[0, 0] = (target[0] + 1, target[1], target[2], 255)
   out, changed = palette.snap_nearest(arr, ramps)
   assert changed == 1
   assert tuple(out[0, 0])[:3] == target
   assert palette.outside_colors(out, ramps) == []


def test_build_lut_shape():
   ramps = palette.load_ramps(sample_path())
   lut = palette.build_lut(ramps, ["cloth_blue", "cloth_red"])
   assert image.size(lut) == (6, 2)
   assert tuple(lut[0, 0])[:3] == ramps.ramp("cloth_blue")[0]
   assert tuple(lut[1, 5])[:3] == ramps.ramp("cloth_red")[5]


def test_save_lut(tmp_path):
   ramps = palette.load_ramps(sample_path())
   out = tmp_path / "lut.png"
   palette.save_lut(out, ramps)
   assert image.size(image.load(out)) == (6, len(ramps.names()))


def test_ramp_asset_json():
   ramps = palette.load_ramps(sample_path())
   data = palette.ramp_asset_json(ramps, ["gold"])
   assert data["rampLen"] == 6
   assert data["ramps"][0]["name"] == "gold"
   assert data["ramps"][0]["colors"][0].startswith("#")
