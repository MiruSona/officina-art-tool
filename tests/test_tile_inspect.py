"""tile inspect — 그림은 전부 코드로 만든다. 설계 6-4 의 inspect 줄을 하나씩 박는다."""

from __future__ import annotations

import json

import pytest

from arttool import cli, image
from arttool.errors import ArtToolError
from arttool.profile import load_profile
from arttool.tiles import inspect as tile_inspect

GRASS = (40, 160, 60, 255)
SPOT = (200, 200, 40, 255)


def full(w=8, h=8):
   arr = image.new(w, h)
   arr[:, :] = GRASS
   return arr


def row_of(report, name):
   return next(r for r in report["tiles"] if r["name"] == name)


def write(tmp_path, items):
   folder = tmp_path / "tiles"
   for name, arr in items.items():
      image.save(folder / name, arr)
   return folder


def test_size_mismatch_fails(tmp_path):
   folder = write(tmp_path, {"a.png": full(), "b.png": full(8, 6)})
   report = tile_inspect.run(load_profile(None), folder, size=8)
   assert report["status"] == "fail"
   assert row_of(report, "a.png")["size_ok"] is True
   assert row_of(report, "b.png")["size_ok"] is False
   assert [f["name"] for f in report["failed"]] == ["b.png"]


def test_size_defaults_to_profile(tmp_path):
   folder = write(tmp_path, {"a.png": full(16, 16)})
   report = tile_inspect.run(load_profile(None), folder)
   assert report["size"] == 16
   assert report["status"] == "ok"


def test_soft_alpha_counted_and_fails_under_binary(tmp_path):
   arr = full()
   arr[0, 0] = (40, 160, 60, 128)
   arr[1, 1] = (40, 160, 60, 10)
   folder = write(tmp_path, {"a.png": arr})
   report = tile_inspect.run(load_profile(None), folder, size=8)
   assert row_of(report, "a.png")["soft_alpha"] == 2
   assert report["status"] == "fail"

   loose = load_profile(None, {"check.allow_alpha": "any"})
   report = tile_inspect.run(loose, folder, size=8)
   assert row_of(report, "a.png")["soft_alpha"] == 2
   assert report["status"] == "ok"


def test_edges_touched(tmp_path):
   arr = image.new(8, 8)
   arr[0, 3] = GRASS           # 윗변
   arr[4, 7] = GRASS           # 오른변
   mid = image.new(8, 8)
   mid[3:5, 3:5] = GRASS
   folder = write(tmp_path, {"a.png": arr, "full.png": full(), "mid.png": mid})
   report = tile_inspect.run(load_profile(None), folder, size=8)
   assert row_of(report, "a.png")["edges"] == {"top": True, "bottom": False, "left": False, "right": True}
   assert row_of(report, "full.png")["edges"] == {"top": True, "bottom": True, "left": True, "right": True}
   assert row_of(report, "mid.png")["edges"] == {"top": False, "bottom": False, "left": False, "right": False}


def test_overflow_counted(tmp_path):
   arr = image.new(10, 9)
   arr[:8, :8] = GRASS
   arr[2, 9] = SPOT            # 오른쪽 넘침
   arr[8, 0] = SPOT            # 아래 넘침
   arr[8, 9] = SPOT            # 모서리 넘침
   folder = write(tmp_path, {"a.png": arr})
   report = tile_inspect.run(load_profile(None), folder, size=8)
   row = row_of(report, "a.png")
   assert row["overflow"] == 3
   assert row["size_ok"] is False
   assert row["edges"]["right"] is True  # 네 변은 --size 칸 안에서 본다


def test_basic_numbers(tmp_path):
   arr = image.new(8, 8)
   arr[2:4, 1:5] = GRASS
   arr[2, 1] = SPOT
   folder = write(tmp_path, {"a.png": arr})
   row = row_of(tile_inspect.run(load_profile(None), folder, size=8), "a.png")
   assert row["size"] == [8, 8]
   assert row["bbox"] == [1, 2, 5, 4]
   assert row["opaque_ratio"] == pytest.approx(8 / 64)
   assert row["colors"] == 2
   assert row["overflow"] == 0


def test_empty_tile_warns(tmp_path):
   folder = write(tmp_path, {"a.png": image.new(8, 8)})
   report = tile_inspect.run(load_profile(None), folder, size=8)
   assert report["status"] == "warn"
   assert row_of(report, "a.png")["bbox"] is None
   assert report["warnings"]


def test_single_file_and_bad_input(tmp_path):
   folder = write(tmp_path, {"a.png": full()})
   report = tile_inspect.run(load_profile(None), folder / "a.png", size=8)
   assert report["files"] == 1
   with pytest.raises(ArtToolError):
      tile_inspect.run(load_profile(None), tmp_path / "none", size=8)
   with pytest.raises(ArtToolError):
      tile_inspect.run(load_profile(None), folder, size=0)


def test_cli_tile_inspect(tmp_path, capsys):
   folder = write(tmp_path, {"a.png": full(), "b.png": full(8, 6)})
   report = tmp_path / "inspect.json"
   code = cli.main(["tile", "inspect", "--in", str(folder), "--report", str(report), "--size", "8", "--json"])
   assert code == 4
   saved = json.loads(report.read_text(encoding="utf-8"))
   assert saved["status"] == "fail"
   assert json.loads(capsys.readouterr().out)["status"] == "fail"


# --- 리뷰 뒤 더한 시험 ---


def test_size_zero_is_usage_error(tmp_path):
   from arttool.errors import UsageError

   folder = write(tmp_path, {"a.png": full()})
   with pytest.raises(UsageError):
      tile_inspect.run(load_profile(None), folder, size=0)
   code = cli.main(["tile", "inspect", "--in", str(folder), "--report", str(tmp_path / "i.json"), "--size", "0"])
   assert code == 2
