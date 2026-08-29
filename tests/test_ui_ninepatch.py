import pytest

from arttool import image, profile
from arttool.errors import ArtToolError
from arttool.jsonio import read_json
from arttool.ui import frame, ninepatch

BLACK = (0, 0, 0, 255)
BODY = (110, 101, 85, 255)


def make_nine(inner_w=16, inner_h=16, border=(3, 3, 3, 3), content=None):
   """안내선 1px 을 두른 .9.png 를 만든다. border 는 [왼, 아래, 오른, 위]."""
   left, bottom, right, top = border
   arr = image.new(inner_w + 2, inner_h + 2)
   arr[1 : inner_h + 1, 1 : inner_w + 1] = BODY

   for x in range(1 + left, 1 + inner_w - right):
      arr[0, x] = BLACK
   for y in range(1 + top, 1 + inner_h - bottom):
      arr[y, 0] = BLACK

   if content is None:
      return arr
   c_left, c_bottom, c_right, c_top = content
   for x in range(1 + c_left, 1 + inner_w - c_right):
      arr[inner_h + 1, x] = BLACK
   for y in range(1 + c_top, 1 + inner_h - c_bottom):
      arr[y, inner_w + 1] = BLACK
   return arr


def test_read_border():
   guides = ninepatch.read_guides(make_nine())
   assert guides["border"] == [3, 3, 3, 3]
   assert guides["size"] == [16, 16]
   assert guides["content_padding"] == [3, 3, 3, 3]


def test_read_uneven_border():
   guides = ninepatch.read_guides(make_nine(32, 16, border=(5, 2, 4, 6)))
   assert guides["border"] == [5, 2, 4, 6]
   assert guides["size"] == [32, 16]


def test_content_padding_from_bottom_right():
   guides = ninepatch.read_guides(make_nine(border=(3, 3, 3, 3), content=(4, 5, 4, 3)))
   assert guides["border"] == [3, 3, 3, 3]
   assert guides["content_padding"] == [4, 5, 4, 3]


def test_strip_removes_guides():
   inner = ninepatch.strip(make_nine())
   assert image.size(inner) == (16, 16)
   assert tuple(inner[0, 0]) == BODY


def test_missing_top_guide():
   arr = make_nine()
   arr[0, :] = (0, 0, 0, 0)
   with pytest.raises(ArtToolError, match="위쪽 안내선이 없다"):
      ninepatch.read_guides(arr)


def test_missing_left_guide():
   arr = make_nine()
   arr[:, 0] = (0, 0, 0, 0)
   with pytest.raises(ArtToolError, match="왼쪽 안내선이 없다"):
      ninepatch.read_guides(arr)


def test_two_runs_rejected():
   arr = make_nine()
   arr[0, 5] = (0, 0, 0, 0)
   with pytest.raises(ArtToolError, match="검은 구간이 2개"):
      ninepatch.read_guides(arr)


def test_corner_guide_rejected():
   arr = make_nine()
   arr[0, 0] = BLACK
   with pytest.raises(ArtToolError, match="네 변에 안 맞는다"):
      ninepatch.read_guides(arr)


def test_too_small():
   with pytest.raises(ArtToolError, match="너무 작다"):
      ninepatch.read_guides(image.new(2, 2))


def test_plain_png_refused(tmp_path):
   image.save(tmp_path / "panel_normal.png", image.new(16, 16))
   with pytest.raises(ArtToolError, match="안내선이 없다"):
      ninepatch.import_file(tmp_path / "panel_normal.png", tmp_path / "out")


def test_split_name():
   states = ["normal", "pressed", "disabled"]
   assert ninepatch.split_name("panel_normal", states) == ("panel", "normal")
   assert ninepatch.split_name("window", states) == ("window", "normal")


def test_import_dir(tmp_path):
   raw = tmp_path / "raw"
   raw.mkdir()
   image.save(raw / "window_normal.9.png", make_nine())
   image.save(raw / "window_pressed.9.png", make_nine())

   prof = profile.load_profile("topdown_action")
   out = tmp_path / "frames"
   result = ninepatch.import_dir(prof, raw, out)

   assert len(result["frames"]) == 2
   assert (out / "window_normal.png").is_file()
   assert image.size(image.load(out / "window_normal.png")) == (16, 16)

   data = read_json(out / "border.json")
   assert data["frames"][0]["group"] == "window"
   assert data["frames"][0]["min_size"] == [7, 7]


def test_import_dir_without_nine_files(tmp_path):
   raw = tmp_path / "raw"
   raw.mkdir()
   image.save(raw / "a.png", image.new(8, 8))
   prof = profile.load_profile("topdown_action")
   with pytest.raises(ArtToolError, match="파일이 없다"):
      ninepatch.import_dir(prof, raw, tmp_path / "out")


def test_import_merges_with_generated(tmp_path):
   prof = profile.load_profile("topdown_action")
   out = tmp_path / "frames"
   frame.build(prof, "panel", (16, 16), out)

   raw = tmp_path / "raw"
   raw.mkdir()
   image.save(raw / "window_normal.9.png", make_nine())
   ninepatch.import_dir(prof, raw, out)

   names = [f["name"] for f in read_json(out / "border.json")["frames"]]
   assert "panel_normal" in names and "window_normal" in names
