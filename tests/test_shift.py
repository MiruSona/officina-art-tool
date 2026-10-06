"""`shift` 시험 (2026-10-06 1판 설계 1절). 그림은 모두 코드로 만든 합성 그림이다."""

from __future__ import annotations

import colorsys
import json

from arttool import cli, errors, image
from arttool.sprite.shift import shift_rgb

GREEN = (106, 143, 60, 255)
DARK = (78, 107, 43, 255)
GRAY = (128, 128, 128, 255)


def _pic(path, colors):
   arr = image.new(len(colors), 2)
   for x, c in enumerate(colors):
      arr[0, x] = c
   arr[1, 0] = (10, 20, 30, 0)   # 투명 칸 : 늘 그대로
   path.parent.mkdir(parents=True, exist_ok=True)
   image.save(path, arr)
   return arr


def _run(tmp_path, *extra):
   report = tmp_path / "r.json"
   code = cli.main(["shift", "--in", str(tmp_path / "raw"), "--out", str(tmp_path / "o"), "--report", str(report), *extra])
   return code, (json.loads(report.read_text(encoding="utf-8")) if report.exists() else None)


def test_shift_rgb_matches_hsv_math():
   new, clipped = shift_rgb(GREEN[:3], -10, 1.2, 0.03)
   h, s, v = colorsys.rgb_to_hsv(*(c / 255 for c in GREEN[:3]))
   want = colorsys.hsv_to_rgb((h - 10 / 360) % 1, s * 1.2, v + 0.03)
   assert new == tuple(int(round(c * 255)) for c in want)
   assert not clipped


def test_all_opaque_colors_move_and_alpha_kept(tmp_path):
   _pic(tmp_path / "raw" / "a.png", [GREEN, DARK, (200, 50, 50, 120)])
   code, rep = _run(tmp_path, "--hue", "30")
   assert code == errors.EXIT_OK and rep["status"] == "ok"
   out = image.load(tmp_path / "o" / "a.png")
   assert tuple(out[0, 0, :3]) == shift_rgb(GREEN[:3], 30, 1, 0)[0]
   assert out[0, 2, 3] == 120 and out[1, 0, 3] == 0
   assert rep["images"][0]["changed"] == 3 and len(rep["images"][0]["colors"]) == 3
   assert rep["pick"] is None


def test_pick_moves_only_that_color_and_warns_missing(tmp_path):
   _pic(tmp_path / "raw" / "a.png", [GREEN, DARK])
   code, rep = _run(tmp_path, "--light", "0.1", "--pick", "#6A8F3C,#010203")
   out = image.load(tmp_path / "o" / "a.png")
   assert tuple(out[0, 1]) == DARK
   assert tuple(out[0, 0, :3]) != GREEN[:3]
   assert rep["pick"] == ["#6A8F3C", "#010203"]
   assert [w["rule"] for w in rep["warnings"]] == ["shift.pick_missing"]
   assert code == errors.EXIT_OK


def test_clipped_merged_gray_warnings(tmp_path):
   _pic(tmp_path / "raw" / "a.png", [(250, 250, 250, 255), (240, 240, 240, 255), GRAY])
   _, rep = _run(tmp_path, "--hue", "20", "--light", "0.5")
   rules = {w["rule"] for w in rep["warnings"]}
   assert {"shift.clipped", "shift.merged", "shift.gray"} <= rules
   assert rep["status"] == "warn"


def test_nothing_to_change_and_bad_ranges_are_usage(tmp_path, capsys):
   _pic(tmp_path / "raw" / "a.png", [GREEN])
   for extra in ([], ["--hue", "400"], ["--sat", "-1"], ["--light", "2"], ["--hue", "5", "--pick", "zz"]):
      assert _run(tmp_path, *extra)[0] == errors.EXIT_USAGE
   assert not (tmp_path / "o").exists()


def test_dry_run_writes_nothing(tmp_path):
   _pic(tmp_path / "raw" / "a.png", [GREEN])
   code, rep = _run(tmp_path, "--sat", "0.5", "--dry-run")
   assert code == errors.EXIT_OK
   assert not (tmp_path / "o" / "a.png").exists()
   assert rep["images"][0]["changed"] == 1


def test_non_finite_numbers_are_usage(tmp_path):
   _pic(tmp_path / "raw" / "a.png", [GREEN])
   for extra in (["--hue", "inf"], ["--hue", "nan"], ["--sat", "inf"], ["--sat", "nan"], ["--light", "nan"], ["--light=-inf"]):
      assert _run(tmp_path, *extra)[0] == errors.EXIT_USAGE
   assert not (tmp_path / "o").exists()
