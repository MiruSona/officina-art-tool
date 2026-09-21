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


# --- 낱장 모드 ---


def loose_dir(tmp_path, count=3):
   """낱장 PNG 를 몇 장 쓴다. 색은 램프 안에 있는 것만 쓴다."""
   out = tmp_path / "loose"
   out.mkdir(parents=True, exist_ok=True)
   for index in range(count):
      image.save(out / f"icon_{index}.png", helpers.blob(8, 8))
   return out


def test_loose_folder_passes(tmp_path):
   prof = helpers.tiny_profile(tmp_path)
   report = check.run(prof, loose_dir(tmp_path))
   assert report["status"] == "ok"
   assert report["checked"]["mode"] == "loose"
   assert report["checked"]["files"] == 3


def test_loose_single_png(tmp_path):
   prof = helpers.tiny_profile(tmp_path)
   report = check.run(prof, loose_dir(tmp_path) / "icon_0.png")
   assert report["status"] == "ok"
   assert report["checked"]["files"] == 1


def test_loose_reports_per_file_colors(tmp_path):
   prof = helpers.tiny_profile(tmp_path)
   report = check.run(prof, loose_dir(tmp_path))
   rule = next(r for r in report["rules"] if r["rule"] == "max_colors")
   assert [i["where"] for i in rule["items"]] == ["icon_0.png", "icon_1.png", "icon_2.png"]
   assert rule["items"][0]["colors"] == 2


def test_loose_alpha_fails(tmp_path):
   prof = helpers.tiny_profile(tmp_path)
   out = loose_dir(tmp_path)
   arr = image.load(out / "icon_1.png")
   arr[3, 3] = (27, 42, 74, 128)
   image.save(out / "icon_1.png", arr)
   report = check.run(prof, out)
   assert "alpha" in report["failed"]


def test_loose_skips_baseline(tmp_path):
   prof = helpers.tiny_profile(tmp_path)
   report = check.run(prof, loose_dir(tmp_path))
   for name in ("baseline", "bbox_drift"):
      rule = next(r for r in report["rules"] if r["rule"] == name)
      assert rule["ok"] and "낱장 모드" in rule["detail"]


def test_no_ramps_flag_marks_skipped(tmp_path):
   prof = helpers.tiny_profile(tmp_path)
   report = check.run(prof, loose_dir(tmp_path), no_ramps=True)
   assert report["skipped"] == ["baseline", "bbox_drift", "ramp_colors"]
   assert [r["rule"] for r in report["rules"] if r["rule"] == "ramp_colors"] == []


def test_loose_empty_folder_errors(tmp_path):
   prof = helpers.tiny_profile(tmp_path)
   empty = tmp_path / "빈폴더"
   empty.mkdir()
   with pytest.raises(ArtToolError, match="PNG"):
      check.run(prof, empty)
