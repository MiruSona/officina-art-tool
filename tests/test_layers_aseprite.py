import pytest

import helpers
from arttool import image
from arttool.errors import ArtToolError, MissingExecutable
from arttool.sprite import aseprite, layers


def test_layer_order_from_profile(tmp_path):
   prof = helpers.tiny_profile(tmp_path)
   order = layers.layer_order(prof, "humanoid_lpc")
   assert order[0] == "body" and order[-1] == "headwear"


def test_anchor_rig_rejected(tmp_path):
   prof = helpers.tiny_profile(tmp_path)
   with pytest.raises(ArtToolError, match="층 겹치기 rig 가 아니다"):
      layers.layer_order(prof, "blob")


def test_compose_top_wins():
   order = ["body", "hair"]
   body = image.new(2, 2)
   body[:, :] = (10, 10, 10, 255)
   hair = image.new(2, 2)
   hair[0, 0] = (20, 20, 20, 255)

   out = layers.compose(order, {"body": body, "hair": hair})
   assert tuple(out[0, 0]) == (20, 20, 20, 255)
   assert tuple(out[1, 1]) == (10, 10, 10, 255)


def test_compose_unknown_layer():
   with pytest.raises(ArtToolError, match="없는 층"):
      layers.compose(["body"], {"모자": image.new(2, 2)})


def test_compose_size_mismatch():
   with pytest.raises(ArtToolError, match="크기가 다르다"):
      layers.compose(["body", "hair"], {"body": image.new(2, 2), "hair": image.new(4, 4)})


def test_compose_sheets(tmp_path):
   prof = helpers.tiny_profile(tmp_path)
   source = tmp_path / "parts"
   for name, color in (("body", (61, 92, 155)), ("hair", (192, 160, 68))):
      folder = source / name
      folder.mkdir(parents=True)
      arr = image.new(16, 16)
      arr[0 if name == "hair" else 1, 0] = (*color, 255)
      image.save(folder / "walk.png", arr)

   out = layers.compose_sheets(prof, "humanoid_lpc", source, tmp_path / "merged", ["walk"])
   assert out["sheets"][0]["layers"] == ["body", "hair"]
   merged = image.load(tmp_path / "merged" / "walk.png")
   assert image.count_colors(merged) == 2


def test_aseprite_missing(monkeypatch):
   monkeypatch.delenv(aseprite.ENV_KEY, raising=False)
   with pytest.raises(MissingExecutable, match="실행 파일이 없다"):
      aseprite.find_exe()


def test_aseprite_bad_path(tmp_path):
   with pytest.raises(MissingExecutable, match="못 찾았다"):
      aseprite.find_exe(str(tmp_path / "없다.exe"))


def test_export_args_are_a_list(tmp_path):
   args = aseprite.export_args(tmp_path / "a.exe", tmp_path / "b.aseprite", tmp_path / "c.png", tmp_path / "d.json", "anchors")
   assert args[1] == "-b"
   assert "--layer" in args and args[args.index("--layer") + 1] == "anchors"
   assert all(isinstance(a, str) for a in args)


def test_slices_to_points():
   data = {
      "meta": {
         "slices": [
            {"name": "head_top", "keys": [{"frame": 2, "bounds": {"x": 10, "y": 4, "w": 1, "h": 1}, "pivot": {"x": 1, "y": 1}}]}
         ]
      }
   }
   points = aseprite.slices_to_points(data, "blob", "walk", "south")
   assert points[0] == {
      "rig": "blob",
      "anim": "walk",
      "direction": "south",
      "frame": 2,
      "point": "head_top",
      "x": 11,
      "y": 5,
      "z": 0,
   }


def test_points_to_slices_roundtrip():
   points = [{"rig": "blob", "anim": "walk", "direction": "south", "frame": 0, "point": "head_top", "x": 7, "y": 3, "z": 10}]
   back = aseprite.slices_to_points(aseprite.points_to_slices(points), "blob", "walk", "south")
   assert back[0]["x"] == 7 and back[0]["y"] == 3 and back[0]["point"] == "head_top"


def test_slice_without_name():
   with pytest.raises(ArtToolError, match="이름이나 key"):
      aseprite.slices_to_points({"meta": {"slices": [{"keys": []}]}}, "blob", "walk", "south")
