import pytest

from arttool import image, profile
from arttool.errors import ArtToolError
from arttool.jsonio import read_json, write_json
from arttool.ui import check_ui, frame, icons, manifest
import test_ui_icons


def prof(**over):
   return profile.load_profile("topdown_action", over)


def make_build(tmp_path, with_icons=True):
   out = tmp_path / "ui"
   p = prof()
   frame.build(p, "panel", (16, 16), out)
   frame.build(p, "button", (32, 16), out)
   if with_icons:
      sheet = test_ui_icons.make_sheet(tmp_path)
      icons.cut(p, sheet, out)
   return p, out


# --- 자리 잡기 ---


def test_pack_is_square_ish():
   items = [(f"a{i}", 16, 16) for i in range(16)]
   spots, size = manifest.pack(items)
   assert size[0] in (64, 128) and size[1] <= size[0]
   assert spots["a0"] == (0, 0)


def test_pack_is_deterministic():
   items = [("a", 16, 16), ("b", 32, 16)]
   assert manifest.pack(items)[0] == manifest.pack(items)[0]


def test_pack_needs_items():
   with pytest.raises(ArtToolError, match="넣을 그림이 없다"):
      manifest.pack([])


# --- 매니페스트 ---


def test_manifest_shape(tmp_path):
   p, out = make_build(tmp_path)
   frames = read_json(out / "border.json")["frames"]
   icon_rows = read_json(out / "icons.json")["icons"]
   data = manifest.build(p, frames, icon_rows)

   assert data["ppu"] == 16
   assert data["slice_scale"] == 6.25
   assert data["reference"] == [320, 180]
   entry = manifest.frame_by_name(data, "panel_normal")
   assert entry["border"] == [3, 3, 3, 3]
   assert entry["min_size"] == [7, 7]
   assert entry["group"] == "panel" and entry["state"] == "normal"
   x1, y1, x2, y2 = entry["rect"]
   assert x2 - x1 == 16 and y2 - y1 == 16


def test_manifest_icons(tmp_path):
   p, out = make_build(tmp_path)
   data = manifest.build(p, read_json(out / "border.json")["frames"], read_json(out / "icons.json")["icons"])
   assert len(data["icons"]) == 6
   assert data["icons"][0]["size"] == 16
   assert data["icons"][0]["hotspot"] == [8, 8]


def test_group_border_mismatch():
   frames = [
      {"name": "a_normal", "group": "a", "state": "normal", "size": [16, 16], "border": [3, 3, 3, 3], "min_size": [7, 7], "content_padding": [3, 3, 3, 3]},
      {"name": "a_pressed", "group": "a", "state": "pressed", "size": [16, 16], "border": [2, 2, 2, 2], "min_size": [5, 5], "content_padding": [2, 2, 2, 2]},
   ]
   with pytest.raises(ArtToolError, match="border 가 다르다"):
      manifest.check_group_borders(frames)


def test_manifest_roundtrip(tmp_path):
   p, out = make_build(tmp_path, with_icons=False)
   data = manifest.build(p, read_json(out / "border.json")["frames"], [])
   manifest.save(tmp_path / "ui_manifest.json", data)
   assert manifest.load(tmp_path / "ui_manifest.json")["slice_scale"] == 6.25


def test_manifest_bad_version(tmp_path):
   write_json(tmp_path / "m.json", {"version": 9})
   with pytest.raises(ArtToolError, match="판 번호"):
      manifest.load(tmp_path / "m.json")


# --- 검수 ---


def test_clean_ui_passes(tmp_path):
   p, out = make_build(tmp_path)
   report = check_ui.run(out, p)
   assert report["status"] == "ok", report["failed"]
   assert report["checked"] == {"frames": 6, "icons": 6}
   assert report["warnings"] == []


def test_min_size_rule(tmp_path):
   p, out = make_build(tmp_path, with_icons=False)
   image.save(out / "panel_normal.png", image.new(4, 4))
   assert "ui_min_size" in check_ui.run(out, p)["failed"]


def test_even_size_rule(tmp_path):
   p, out = make_build(tmp_path, with_icons=False)
   image.save(out / "panel_normal.png", image.new(15, 16))
   report = check_ui.run(out, p)
   assert "ui_even_size" in report["failed"]

   loose = prof(**{"ui.check.require_even": False})
   assert "ui_even_size" not in check_ui.run(out, loose)["failed"]


def test_palette_rule(tmp_path):
   p, out = make_build(tmp_path, with_icons=False)
   arr = image.load(out / "panel_normal.png")
   arr[8, 8] = (1, 2, 3, 255)
   image.save(out / "panel_normal.png", arr)
   assert "ramp_colors" in check_ui.run(out, p)["failed"]


def test_alpha_rule(tmp_path):
   p, out = make_build(tmp_path, with_icons=False)
   arr = image.load(out / "panel_normal.png")
   arr[8, 8] = (30, 27, 23, 128)
   image.save(out / "panel_normal.png", arr)
   assert "alpha" in check_ui.run(out, p)["failed"]


def test_states_rule(tmp_path):
   p, out = make_build(tmp_path, with_icons=False)
   data = read_json(out / "border.json")
   data["frames"] = [f for f in data["frames"] if f["name"] != "panel_pressed"]
   write_json(out / "border.json", data)

   report = check_ui.run(out, p)
   assert "ui_states" in report["failed"]
   rule = next(r for r in report["rules"] if r["rule"] == "ui_states")
   assert rule["items"][0]["missing"] == ["pressed"]


def test_atlas_size_warning(tmp_path):
   p, out = make_build(tmp_path)
   tight = prof(**{"ui.check.atlas_max": 8})
   report = check_ui.run(out, tight)
   assert report["status"] == "ok"
   assert report["warnings"][0]["rule"] == "ui_atlas_size"


def test_icon_family_warning(tmp_path):
   p, out = make_build(tmp_path)
   data = read_json(out / "icons.json")
   data["icons"][0]["size"] = 32
   write_json(out / "icons.json", data)

   report = check_ui.run(out, p)
   assert report["status"] == "ok"
   assert any(w["rule"] == "ui_icon_family" for w in report["warnings"])


def test_nothing_to_check(tmp_path):
   empty = tmp_path / "빈곳"
   empty.mkdir()
   with pytest.raises(ArtToolError, match="검수할 것이 없다"):
      check_ui.run(empty, prof())
