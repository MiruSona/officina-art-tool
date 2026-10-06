"""`trim` 시험. 그림은 모두 코드로 만든 합성 그림이다."""

from __future__ import annotations

import json

import pytest

from arttool import cli, errors, image
from arttool.edit.trim import common_bbox, trim_common, trim_one

RED = (200, 30, 30, 255)
BLUE = (30, 30, 200, 255)


def _with_box(w, h, x0, y0, x1, y1, color=RED):
   arr = image.new(w, h)
   arr[y0:y1, x0:x1] = color
   return arr


def test_non_square_crop_and_offset():
   out, offset = trim_one(_with_box(20, 20, 3, 5, 9, 15))
   assert image.size(out) == (6, 10)
   assert offset == (3, 5)


def test_pad_shifts_offset():
   out, offset = trim_one(_with_box(20, 20, 3, 5, 9, 15), pad=2)
   assert image.size(out) == (10, 14)
   assert offset == (1, 3)
   assert out[2, 2, 3] == 255 and out[1, 1, 3] == 0


def test_square_centers_with_floor_half():
   out, offset = trim_one(_with_box(20, 20, 3, 5, 9, 15), square=True)
   assert image.size(out) == (10, 10)
   # 너비 6 을 10 칸 가운데 : floor(4.5 - 3 + 0.5) = 2
   box = image.bbox(out)
   assert box == (2, 0, 8, 10)
   assert offset == (1, 5)


def test_offset_restores_original_position():
   arr = _with_box(20, 20, 3, 5, 9, 15)
   out, (ox, oy) = trim_one(arr, pad=3, square=True)
   back = image.new(30, 30)
   back[oy + 5 : oy + 5 + out.shape[0], ox + 5 : ox + 5 + out.shape[1]] = out
   assert (back[5:25, 5:25] == arr).all()


def test_common_keeps_layer_positions():
   body = _with_box(32, 32, 10, 10, 20, 28, RED)
   hat = _with_box(32, 32, 12, 4, 18, 10, BLUE)
   assert common_bbox([body, hat]) == (10, 4, 20, 28)
   cuts, offset = trim_common([body, hat])
   assert offset == (10, 4)
   assert all(image.size(c) == (10, 24) for c in cuts)
   assert image.bbox(cuts[1]) == (2, 0, 8, 6)


def test_common_needs_same_size():
   with pytest.raises(errors.ArtToolError):
      common_bbox([image.new(4, 4), image.new(5, 4)])


def test_empty_returns_none():
   assert trim_one(image.new(5, 5)) is None
   assert trim_common([image.new(5, 5)]) is None


def test_cli_report_and_empty_warns(tmp_path, capsys):
   src = tmp_path / "raw"
   image.save(src / "a.png", _with_box(20, 20, 3, 5, 9, 15))
   image.save(src / "z.png", image.new(8, 8))
   report = tmp_path / "t.json"
   assert cli.main(["trim", "--in", str(src), "--out", str(tmp_path / "t"), "--report", str(report)]) == errors.EXIT_OK
   data = json.loads(report.read_text(encoding="utf-8"))
   assert data["status"] == "warn"
   assert data["images"][0]["offset"] == [3, 5]
   assert data["images"][1]["skipped"] is True
   assert not (tmp_path / "t" / "z.png").exists()


def test_cli_common(tmp_path, capsys):
   src = tmp_path / "layers"
   image.save(src / "body.png", _with_box(32, 32, 10, 10, 20, 28, RED))
   image.save(src / "hat.png", _with_box(32, 32, 12, 4, 18, 10, BLUE))
   report = tmp_path / "t.json"
   assert cli.main(["trim", "--in", str(src), "--out", str(tmp_path / "t"), "--common", "--report", str(report)]) == errors.EXIT_OK
   data = json.loads(report.read_text(encoding="utf-8"))
   assert {tuple(r["offset"]) for r in data["images"]} == {(10, 4)}
   assert image.size(image.load(tmp_path / "t" / "hat.png")) == (10, 24)


def test_cli_common_different_sizes_is_friendly_usage(tmp_path, capsys):
   """크기 다른 그림에 --common : 종료 2 + 어느 파일이 다른지 (실물 #23 / 버그 8)."""
   src = tmp_path / "raw"
   image.save(src / "a.png", _with_box(16, 16, 2, 2, 8, 8))
   image.save(src / "b.png", _with_box(16, 16, 3, 3, 9, 9))
   image.save(src / "c.png", _with_box(24, 24, 2, 2, 8, 8))
   assert cli.main(["trim", "--in", str(src), "--out", str(tmp_path / "t"), "--common"]) == errors.EXIT_USAGE
   err = capsys.readouterr().err
   assert "c.png 24x24" in err and "16x16" in err and "a.png" not in err
   assert not (tmp_path / "t").exists()


def test_cli_warnings_use_check_shape(tmp_path, capsys):
   src = tmp_path / "raw"
   image.save(src / "z.png", image.new(8, 8))
   image.save(src / "a.png", _with_box(8, 8, 1, 1, 3, 3))
   report = tmp_path / "t.json"
   cli.main(["trim", "--in", str(src), "--out", str(tmp_path / "t"), "--report", str(report)])
   warns = json.loads(report.read_text(encoding="utf-8"))["warnings"]
   assert warns == [{"rule": "trim.empty", "ok": False, "detail": warns[0]["detail"], "items": ["z.png"]}]


def test_cli_refuses_overwrite_and_bad_pad(tmp_path, capsys):
   src = tmp_path / "raw"
   image.save(src / "a.png", _with_box(8, 8, 1, 1, 3, 3))
   assert cli.main(["trim", "--in", str(src), "--out", str(src)]) == errors.EXIT_USAGE
   assert cli.main(["trim", "--in", str(src), "--out", str(tmp_path / "o"), "--pad", "-1"]) == errors.EXIT_USAGE


# --- --canvas · --anchor · --margin (2026-10-06 1판 설계 2절) ---

def _trim(tmp_path, *extra):
   report = tmp_path / "c.json"
   code = cli.main(["trim", "--in", str(tmp_path / "raw"), "--out", str(tmp_path / "c"), "--report", str(report), *extra])
   return code, (json.loads(report.read_text(encoding="utf-8")) if report.exists() else None)


def test_canvas_bottom_margin_places_and_offsets(tmp_path):
   (tmp_path / "raw").mkdir()
   image.save(tmp_path / "raw" / "a.png", _with_box(20, 20, 3, 5, 9, 15))
   code, rep = _trim(tmp_path, "--canvas", "16x16", "--margin", "1")
   assert code == errors.EXIT_OK and rep["status"] == "ok"
   out = image.load(tmp_path / "c" / "a.png")
   assert image.size(out) == (16, 16)
   # 너비 6 을 16 가운데 : (16-6)//2 = 5, 바닥에서 1칸 : 16-10-1 = 5
   assert image.bbox(out) == (5, 5, 11, 15)
   assert rep["images"][0]["offset"] == [3 - 5, 5 - 5]
   assert (rep["canvas"], rep["anchor"], rep["margin"]) == ([16, 16], "bottom", 1)


def test_canvas_half_pixel_warns_and_common_keeps_place(tmp_path):
   (tmp_path / "raw").mkdir()
   image.save(tmp_path / "raw" / "a.png", _with_box(20, 20, 3, 5, 8, 15))
   image.save(tmp_path / "raw" / "b.png", _with_box(20, 20, 4, 6, 6, 9, BLUE))
   _, rep = _trim(tmp_path, "--canvas", "10x12", "--anchor", "top-left", "--margin", "2", "--common")
   assert rep["images"][0]["offset"] == rep["images"][1]["offset"] == [1, 3]
   assert image.bbox(image.load(tmp_path / "c" / "a.png")) == (2, 2, 7, 12)
   _, rep = _trim(tmp_path, "--canvas", "10x12", "--anchor", "center")
   assert [w["rule"] for w in rep["warnings"]] == ["trim.half_pixel"]


def test_canvas_too_big_and_bad_mixes_are_usage(tmp_path, capsys):
   (tmp_path / "raw").mkdir()
   image.save(tmp_path / "raw" / "a.png", _with_box(20, 20, 3, 5, 9, 15))
   for extra in (["--canvas", "6x10", "--margin", "1"], ["--anchor", "top"], ["--margin", "1"],
                 ["--canvas", "16x16", "--pad", "1"], ["--canvas", "16x16", "--square"], ["--canvas", "16x16", "--anchor", "up"]):
      assert _trim(tmp_path, *extra)[0] == errors.EXIT_USAGE
   assert not (tmp_path / "c").exists()
   assert "trim.too_big" in capsys.readouterr().err


def test_no_canvas_report_has_no_new_keys(tmp_path):
   (tmp_path / "raw").mkdir()
   image.save(tmp_path / "raw" / "a.png", _with_box(20, 20, 3, 5, 9, 15))
   _, rep = _trim(tmp_path)
   assert set(rep) == {"version", "status", "pad", "square", "common", "images", "warnings", "out"}   # 옛 trim 보고 꼴 (HEAD)
