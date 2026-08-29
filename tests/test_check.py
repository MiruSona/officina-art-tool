import pytest

import helpers
from arttool import check, image
from arttool.errors import ArtToolError
from arttool.sprite import normalize


def build(tmp_path, **extra):
   prof = helpers.tiny_profile(tmp_path, **extra)
   raw = tmp_path / "raw"
   helpers.write_singles(raw, prof)
   normalize.normalize(prof, raw, tmp_path / "build", ["walk"])
   return prof, tmp_path / "build"


def test_clean_build_passes(tmp_path):
   prof, out = build(tmp_path)
   report = check.run(prof, out)
   assert report["status"] == "ok"
   assert report["checked"]["frames"] == 8
   assert report["failed"] == []


def test_max_colors_fails(tmp_path):
   prof, out = build(tmp_path, **{"check.max_colors": 1})
   report = check.run(prof, out)
   assert report["status"] == "fail"
   assert "max_colors" in report["failed"]


def test_ramp_colors_fails(tmp_path):
   prof, out = build(tmp_path)
   sheet = image.load(out / "walk.png")
   sheet[13, 3] = (1, 2, 3, 255)
   image.save(out / "walk.png", sheet)
   report = check.run(prof, out)
   assert "ramp_colors" in report["failed"]
   rule = next(r for r in report["rules"] if r["rule"] == "ramp_colors")
   assert rule["items"][0]["color"] == "#010203"


def test_alpha_fails(tmp_path):
   prof, out = build(tmp_path)
   sheet = image.load(out / "walk.png")
   sheet[13, 3] = (27, 42, 74, 128)
   image.save(out / "walk.png", sheet)
   report = check.run(prof, out)
   assert "alpha" in report["failed"]


def test_baseline_fails(tmp_path):
   prof, out = build(tmp_path)
   sheet = image.load(out / "walk.png")
   sheet[15, 3] = (27, 42, 74, 255)
   image.save(out / "walk.png", sheet)
   report = check.run(prof, out)
   assert "baseline" in report["failed"]


def test_bbox_drift_fails(tmp_path):
   prof, out = build(tmp_path, **{"check.bbox_drift": 0})
   report = check.run(prof, out)
   assert "bbox_drift" in report["failed"]


def test_frame_size_mismatch(tmp_path):
   prof, out = build(tmp_path)
   other = helpers.tiny_profile(tmp_path, **{"canvas.frame": [8, 8], "canvas.baseline_y": 6, "canvas.center_x": 3.5})
   with pytest.raises(ArtToolError, match="프레임이 프로필과 다르다"):
      check.run(other, out)


def test_ramp_rule_skipped_without_file(tmp_path):
   prof, out = build(tmp_path, **{"palette.ramps_file": ""})
   report = check.run(prof, out)
   rule = next(r for r in report["rules"] if r["rule"] == "ramp_colors")
   assert rule["ok"] and "건너뛴다" in rule["detail"]
