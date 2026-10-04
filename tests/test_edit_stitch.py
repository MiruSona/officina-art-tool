"""`stitch` 시험. 그림은 모두 코드로 만든 합성 그림이다. 배선 전이라 `run` 을 Namespace 로 바로 부른다."""

from __future__ import annotations

import argparse

import pytest

from arttool import errors, image
from arttool.edit import stitch

RED = (200, 30, 30, 255)
RED2 = (205, 32, 28, 255)
BLUE = (30, 30, 200, 255)


def _args(pieces, out_file, **extra):
   values = {"in_specs": [str(p) for p in pieces], "out_file": str(out_file), "axis": "y", "report": None}
   values.update(extra)
   return argparse.Namespace(**values)


def _save(tmp_path, arr, name):
   path = tmp_path / name
   image.save(path, arr)
   return path


def _rows(w, h, start=0):
   """줄마다 다른 색 — 어느 줄이 어디로 갔나 알 수 있다. 빨강 값 = 원래 줄 번호."""
   arr = image.new(w, h, RED)
   for y in range(h):
      arr[y, :, 0] = (start + y) % 256
   return arr


def test_stitch_three_pieces_height(tmp_path):
   top = _save(tmp_path, _rows(10, 20), "top.png")
   mid = _save(tmp_path, _rows(10, 30), "mid.png")
   low = _save(tmp_path, _rows(10, 15), "floor.png")
   out = tmp_path / "wall.png"
   result = stitch.run(_args([f"{top}:0-18", f"{mid}:5-25", f"{low}:3-"], out))
   arr = image.load(out)
   assert image.size(arr) == (10, 18 + 20 + 12)
   assert result["size"] == [10, 50]
   assert arr[0, 0, 0] == 0 and arr[17, 0, 0] == 17
   assert arr[18, 0, 0] == 5 and arr[37, 0, 0] == 24
   assert arr[38, 0, 0] == 3 and arr[49, 0, 0] == 14
   assert [j["at"] for j in result["joins"]] == [18, 38]
   assert [p["range"] for p in result["pieces"]] == [[0, 18], [5, 25], [3, 15]]


def test_stitch_open_end_range(tmp_path):
   a = _save(tmp_path, _rows(4, 10), "a.png")
   b = _save(tmp_path, _rows(4, 10), "b.png")
   result = stitch.run(_args([f"{a}:-4", f"{b}:6-"], tmp_path / "o.png"))
   assert [p["range"] for p in result["pieces"]] == [[0, 4], [6, 10]]
   assert result["size"] == [4, 8]


def test_stitch_whole_file_without_range(tmp_path):
   a = _save(tmp_path, _rows(4, 6), "a.png")
   b = _save(tmp_path, _rows(4, 9), "b.png")
   result = stitch.run(_args([a, b], tmp_path / "o.png"))
   assert result["size"] == [4, 15]


def test_stitch_windows_drive_colon(tmp_path):
   a = _save(tmp_path, _rows(4, 6), "a.png")
   b = _save(tmp_path, _rows(4, 9), "b.png")
   # tmp_path 는 절대경로(윈도면 C:\…). 드라이브 콜론을 구간으로 잘못 읽으면 안 된다
   result = stitch.run(_args([str(a.resolve()), f"{b.resolve()}:1-3"], tmp_path / "o.png"))
   assert result["size"] == [4, 8]
   assert stitch.parse_piece(r"C:\art\x.png") == (r"C:\art\x.png", None, None)
   assert stitch.parse_piece(r"C:\art\x.png:2-7") == (r"C:\art\x.png", 2, 7)
   assert stitch.parse_piece("d:12-") == ("d", 12, None)


def test_stitch_width_mismatch_exit2(tmp_path):
   a = _save(tmp_path, _rows(4, 6), "a.png")
   b = _save(tmp_path, _rows(5, 6), "b.png")
   with pytest.raises(errors.UsageError) as info:
      stitch.run(_args([a, b], tmp_path / "o.png"))
   assert "a.png" in str(info.value) and "b.png" in str(info.value)


@pytest.mark.parametrize("rng", ["0-20", "5-5", "7-3"])
def test_stitch_range_outside_exit2(tmp_path, rng):
   a = _save(tmp_path, _rows(4, 10), "a.png")
   b = _save(tmp_path, _rows(4, 10), "b.png")
   with pytest.raises(errors.UsageError):
      stitch.run(_args([f"{a}:{rng}", b], tmp_path / "o.png"))
   assert not (tmp_path / "o.png").exists()


def test_stitch_single_piece_exit2(tmp_path):
   a = _save(tmp_path, _rows(4, 10), "a.png")
   with pytest.raises(errors.UsageError):
      stitch.run(_args([a], tmp_path / "o.png"))


def test_stitch_seam_jump_warns(tmp_path):
   a = _save(tmp_path, image.new(6, 6, RED), "a.png")
   b = _save(tmp_path, image.new(6, 6, RED2), "b.png")
   c = _save(tmp_path, image.new(6, 6, BLUE), "c.png")
   result = stitch.run(_args([a, b, c], tmp_path / "o.png"))
   assert result["joins"][0]["delta"] <= 24
   assert result["joins"][1]["delta"] > 24
   jumps = [w for w in result["warnings"] if w["rule"] == "stitch.seam_jump"]
   assert len(jumps) == 1 and jumps[0]["items"] == [12]
   assert result["status"] == "warn"


def test_stitch_axis_x(tmp_path):
   left = image.new(5, 4, RED)
   right = image.new(7, 4, BLUE)
   a = _save(tmp_path, left, "a.png")
   b = _save(tmp_path, right, "b.png")
   result = stitch.run(_args([f"{a}:0-3", f"{b}:2-"], tmp_path / "o.png", axis="x"))
   arr = image.load(tmp_path / "o.png")
   assert image.size(arr) == (8, 4)
   assert tuple(arr[0, 2]) == RED and tuple(arr[0, 3]) == BLUE
   assert result["joins"][0]["at"] == 3


def test_stitch_refuses_overwrite_piece(tmp_path):
   a = _save(tmp_path, _rows(4, 6), "a.png")
   b = _save(tmp_path, _rows(4, 6), "b.png")
   before = b.read_bytes()
   with pytest.raises(errors.UsageError):
      stitch.run(_args([f"{a}:0-3", f"{b}:0-3"], b))
   assert b.read_bytes() == before


def test_stitch_bad_axis_exit2(tmp_path):
   a = _save(tmp_path, _rows(4, 6), "a.png")
   with pytest.raises(errors.UsageError):
      stitch.run(_args([a, a], tmp_path / "o.png", axis="z"))
