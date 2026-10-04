"""tile seam — 그림은 전부 코드로 만든다. 설계 6-4 의 seam 줄을 하나씩 박는다."""

from __future__ import annotations

import json

import numpy as np
import pytest

from arttool import cli, image
from arttool.errors import ArtToolError, UsageError
from arttool.tiles import seam

TRI = [0, 1, 2, 3, 3, 2, 1, 0]   # 8칸마다 되풀이되는 세모 물결. 끝과 처음이 같은 값이라 이어진다
GREEN = (40, 160, 60, 255)
BROWN = (120, 80, 40, 255)


def seamless():
   """가로·세로 둘 다 이어지는 8×8 무늬."""
   arr = image.new(8, 8)
   for y in range(8):
      for x in range(8):
         v = 30 * (TRI[x] + TRI[y])
         arr[y, x] = (v, v, v, 255)
   return arr


def flat(color):
   arr = image.new(8, 8)
   arr[:, :] = color
   return arr


def write(tmp_path, items):
   folder = tmp_path / "tiles"
   for name, arr in items.items():
      image.save(folder / name, arr)
   return folder


def tile_row(report, name):
   return next(t for t in report["tiles"] if t["name"] == name)


def seam_of(row, which):
   return next(s for s in row["seams"] if s["seam"] == which)


def test_seamless_pattern_passes(tmp_path):
   report = seam.run(write(tmp_path, {"a.png": seamless()}))
   row = tile_row(report, "a.png")
   assert report["status"] == "ok"
   assert row["ok"] is True
   assert seam_of(row, "right_left")["diff"] == 0
   assert seam_of(row, "bottom_top")["diff"] == 0


def test_broken_column_marks_that_seam(tmp_path):
   arr = seamless()
   arr[:, 7] = arr[:, 3]       # 오른쪽 끝 줄만 어긋나게
   report = seam.run(write(tmp_path, {"a.png": arr}))
   row = tile_row(report, "a.png")
   rl, bt = seam_of(row, "right_left"), seam_of(row, "bottom_top")
   assert report["status"] == "fail"
   assert rl["ok"] is False
   assert rl["line"] == {"x": [7, 0]}
   assert rl["rows"] == list(range(8))
   assert bt["ok"] is True
   assert "cols" not in bt


def test_single_point_on_flat_tile_passes(tmp_path):
   """평평한 바탕 위 한 칸 묘사는 비율이 튀어도 넘친 칸이 1개라 통과 (실물 시험 #20)."""
   arr = flat(GREEN)
   arr[3, 7] = BROWN
   row = tile_row(seam.run(write(tmp_path, {"a.png": arr})), "a.png")
   rl = seam_of(row, "right_left")
   assert rl["ratio"] > 2 and rl["bad_px"] == 1 and rl["bad_px_min"] == 2
   assert rl["ok"] is True


def test_two_point_break_gives_its_rows(tmp_path):
   arr = flat(GREEN)
   arr[3:5, 7] = BROWN
   row = tile_row(seam.run(write(tmp_path, {"a.png": arr})), "a.png")
   rl = seam_of(row, "right_left")
   assert rl["ok"] is False and rl["bad_px"] == 2
   assert rl["rows"] == [3, 4]


def test_sparse_detail_on_wide_flat_tile_passes(tmp_path):
   """64 칸 줄에서 넘친 칸이 15% 밑(9칸 미만)이면 통과, 넘으면 실패."""
   few = np.zeros((64, 64, 4), dtype=np.uint8)
   few[:, :] = GREEN
   few[0:64:8, 63] = BROWN                   # 8칸
   rl = seam_of(tile_row(seam.run(write(tmp_path / "few", {"a.png": few})), "a.png"), "right_left")
   assert rl["bad_px_min"] == 10 and rl["bad_px"] == 8 and rl["ok"] is True
   many = few.copy()
   many[1:64:4, 63] = BROWN                  # 8 + 16 칸
   rl = seam_of(tile_row(seam.run(write(tmp_path / "many", {"a.png": many})), "a.png"), "right_left")
   assert rl["ok"] is False


def test_bottom_top_break_gives_cols(tmp_path):
   arr = flat(GREEN)
   arr[7, 2:4] = BROWN
   row = tile_row(seam.run(write(tmp_path, {"a.png": arr})), "a.png")
   bt = seam_of(row, "bottom_top")
   assert bt["ok"] is False
   assert bt["line"] == {"y": [7, 0]}
   assert bt["cols"] == [2, 3]


def test_flat_tile_passes(tmp_path):
   report = seam.run(write(tmp_path, {"a.png": flat(GREEN)}))
   assert report["status"] == "ok"
   assert seam_of(tile_row(report, "a.png"), "right_left")["ratio"] == 0


def test_transparent_rgb_ignored(tmp_path):
   arr = image.new(8, 8)
   arr[:, 0] = (255, 0, 0, 0)  # 투명 칸의 RGB 찌꺼기는 다르게 둔다
   arr[:, 7] = (0, 0, 255, 0)
   report = seam.run(write(tmp_path, {"a.png": arr}))
   assert report["status"] == "ok"


def test_k_threshold(tmp_path):
   arr = seamless()
   arr[:, 7] = arr[:, 3]
   folder = write(tmp_path, {"a.png": arr})
   ratio = seam_of(tile_row(seam.run(folder), "a.png"), "right_left")["ratio"]
   assert seam.run(folder, k=ratio + 0.01)["status"] == "ok"
   assert seam.run(folder, k=ratio - 0.01)["status"] == "fail"
   with pytest.raises(UsageError):
      seam.run(folder, k=0)


def test_pairs_count_and_mismatch(tmp_path):
   folder = write(tmp_path, {"a.png": flat(GREEN), "b.png": flat(BROWN), "c.png": flat(GREEN)})
   assert "pairs" not in seam.run(folder)
   report = seam.run(folder, pairs=True)
   assert len(report["pairs"]) == 6
   ab = next(p for p in report["pairs"] if (p["a"], p["b"]) == ("a.png", "b.png"))
   ac = next(p for p in report["pairs"] if (p["a"], p["b"]) == ("a.png", "c.png"))
   assert ab["ok"] is False
   assert ac["ok"] is True
   assert {s["seam"] for s in ab["seams"]} == {"right_left", "bottom_top"}
   assert report["status"] == "fail"


def test_pairs_size_mismatch_rejected(tmp_path):
   small = image.new(4, 4)
   small[:, :] = GREEN
   folder = write(tmp_path, {"a.png": flat(GREEN), "b.png": small})
   seam.run(folder)  # 낱장 검사는 크기가 달라도 된다
   with pytest.raises(ArtToolError, match="크기"):
      seam.run(folder, pairs=True)


def test_tiny_tile_rejected(tmp_path):
   arr = image.new(1, 8)
   arr[:, :] = GREEN
   with pytest.raises(ArtToolError):
      seam.run(write(tmp_path, {"a.png": arr}))


def test_sheet(tmp_path):
   folder = write(tmp_path, {"a.png": seamless(), "b.png": flat(GREEN)})
   out = tmp_path / "seams.png"
   report = seam.run(folder, sheet=out, scale=2)
   pic = image.load(out)
   assert image.size(pic) == (2 * 48 + 2, 48)
   assert report["sheet"] == str(out.resolve())
   # 3×3 으로 이었으니 가운데 장의 왼쪽 위가 원본 왼쪽 위와 같다
   assert tuple(pic[16, 16]) == tuple(seamless()[0, 0])
   with pytest.raises(UsageError):
      seam.run(folder, scale=2)


def test_cli_tile_seam(tmp_path, capsys):
   arr = seamless()
   arr[:, 7] = arr[:, 3]
   folder = write(tmp_path, {"a.png": arr})
   report = tmp_path / "seam.json"
   code = cli.main(["tile", "seam", "--in", str(folder), "--report", str(report), "--k", "2.5", "--json"])
   assert code == 4
   saved = json.loads(report.read_text(encoding="utf-8"))
   assert saved["k"] == 2.5
   assert json.loads(capsys.readouterr().out)["status"] == "fail"


# --- 리뷰 뒤 더한 시험 ---


def test_sheet_over_limit_rejected(tmp_path):
   folder = write(tmp_path, {"a.png": flat(GREEN)})
   out = tmp_path / "seams.png"
   with pytest.raises(ArtToolError, match="시트가"):
      seam.run(folder, sheet=out, scale=350)  # 24 × 350 = 8400 > 8192. 고치기 전에도 메모리가 버티게 겨우 넘긴다
   assert not out.exists()


@pytest.mark.parametrize("k", [float("inf"), float("nan"), -1.0])
def test_k_not_finite_rejected(tmp_path, k):
   folder = write(tmp_path, {"a.png": flat(GREEN)})
   with pytest.raises(UsageError):
      seam.run(folder, k=k)


def test_cli_k_inf_exit_2(tmp_path):
   folder = write(tmp_path, {"a.png": flat(GREEN)})
   code = cli.main(["tile", "seam", "--in", str(folder), "--report", str(tmp_path / "s.json"), "--k", "inf"])
   assert code == 2
