import pytest

import helpers
from arttool import bake, check, image
from arttool.errors import CheckFailed
from arttool.jsonio import read_json, write_json
from arttool.sprite import normalize


def build(tmp_path, run_check=True, **extra):
   prof = helpers.tiny_profile(tmp_path, **extra)
   raw = tmp_path / "raw"
   helpers.write_singles(raw, prof)
   out = tmp_path / "build"
   normalize.normalize(prof, raw, out, ["walk"])
   if run_check:
      write_json(out / "check.json", check.run(prof, out))
   return prof, out


def test_bake_makes_files(tmp_path):
   prof, out = build(tmp_path)
   result = bake.bake(prof, out, tmp_path / "unity", "Game.Art")

   made = set(result["files"])
   assert {"atlas.png", "atlas_slices.json", "sprite_manifest.json", "SpriteSpecAsset.json"} <= made
   assert "PaletteRampAsset.json" in made and "palette_lut.png" in made
   assert image.size(image.load(tmp_path / "unity" / "atlas.png")) == (32, 64)


def test_manifest_shape(tmp_path):
   prof, out = build(tmp_path)
   bake.bake(prof, out, tmp_path / "unity")
   manifest = read_json(tmp_path / "unity" / "sprite_manifest.json")
   assert manifest["forced"] is False
   assert manifest["check"] == "ok"
   anim = manifest["animations"][0]
   assert anim["name"] == "walk"
   assert anim["entries"][0] == "walk_south_0"
   assert len(anim["entries"]) == 8


def test_slices_match_frames(tmp_path):
   prof, out = build(tmp_path)
   bake.bake(prof, out, tmp_path / "unity")
   slices = read_json(tmp_path / "unity" / "atlas_slices.json")["slices"]
   assert len(slices) == 8
   assert slices[0]["w"] == 16 and slices[0]["h"] == 16
   assert 0.0 <= slices[0]["pivot"]["x"] <= 1.0


def test_bake_refuses_without_report(tmp_path):
   prof, out = build(tmp_path, run_check=False)
   with pytest.raises(CheckFailed, match="검수 보고"):
      bake.bake(prof, out, tmp_path / "unity")


def test_bake_refuses_failed_report(tmp_path):
   prof, out = build(tmp_path, run_check=False)
   write_json(out / "check.json", {"version": 1, "status": "fail", "failed": ["baseline"]})
   with pytest.raises(CheckFailed, match="통과하지"):
      bake.bake(prof, out, tmp_path / "unity")


def test_force_marks_manifest(tmp_path):
   prof, out = build(tmp_path, run_check=False)
   write_json(out / "check.json", {"version": 1, "status": "fail", "failed": ["baseline"]})
   bake.bake(prof, out, tmp_path / "unity", force=True)
   assert read_json(tmp_path / "unity" / "sprite_manifest.json")["forced"] is True


def test_anchors_carried_over(tmp_path):
   prof, out = build(tmp_path)
   write_json(out / "anchors.json", {"version": 1, "profile": prof.name, "frame": [16, 16], "points": []})
   result = bake.bake(prof, out, tmp_path / "unity")
   assert "anchors.json" in result["files"]


def test_sprite_spec_numbers_only(tmp_path):
   prof, out = build(tmp_path)
   bake.bake(prof, out, tmp_path / "unity", "Game.Art")
   spec = read_json(tmp_path / "unity" / "SpriteSpecAsset.json")
   assert spec["frameWidth"] == 16
   assert spec["baselineY"] == 13
   assert spec["namespace"] == "Game.Art"
