import json

import pytest

from arttool import image
from arttool.draw import guide, shapes
from arttool.errors import ArtToolError


def test_reads_named_coords_from_several_holders():
   g = guide({"size": [32, 32], "lines": {"base": 31},
              "guide": {"points": {"eye_l": [12, 14]}, "boxes": {"head": [8, 4, 24, 18]}},
              "values": {"crotch_y": 24, "knee_y": 28, "frame_ms": 100}})
   assert g.size == (32, 32)
   assert g.y("base") == 31 and g.y("crotch") == 24 and g.x("knee") == 28
   assert g.point("eye_l") == (12, 14) and g.box("head") == (8, 4, 24, 18)
   assert "frame_ms" not in g.lines and "frame" not in g.lines


def test_missing_name_lists_known():
   g = guide({"lines": {"eye": 3}})
   with pytest.raises(ArtToolError, match="eye"):
      g.y("mouth")
   with pytest.raises(ArtToolError, match="없음"):
      g.box("head")


def test_style_and_ramps_file():
   g = guide({"check": {"style": {"outline": "black"}, "palette": {"ramps_file": "C:/x.json"}}})
   assert g.style == {"outline": "black"} and g.ramps_file == "C:/x.json"
   assert guide({}).style == {} and guide({}).ramps_file is None


def test_folder_reads_guide_png(tmp_path):
   png = image.new(16, 16)
   shapes.paint(png, shapes.line((16, 16), 0, 10, 15, 10), "#FF00FF")
   shapes.paint(png, shapes.line((16, 16), 4, 0, 4, 15), "#FF00FF")
   shapes.paint(png, shapes.dot((16, 16), 7, 3), "#00FFFF")
   shapes.paint(png, shapes.box((16, 16), 0, 0, 16, 1), "#FFFF00")
   image.save(tmp_path / "char_small_guide.png", png)
   (tmp_path / "template.json").write_text(json.dumps({"name": "char_small", "size": [16, 16]}), encoding="utf-8")
   g = guide(tmp_path)
   assert g.rows == [10] and g.cols == [4]
   assert g.dots == [(7, 3)]
   assert g.keep.sum() == 16 and g.keep[0].all()


def test_missing_file(tmp_path):
   with pytest.raises(ArtToolError, match="template render"):
      guide(tmp_path / "nope.json")
