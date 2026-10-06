"""`merge-colors --clean` 잡티 메우기와 hue_jump 어두운 색 헛경고 (2026-10-06 실물 재기 뒤). 그림은 전부 코드로 만든다."""

from __future__ import annotations

import argparse

import numpy as np
import pytest

from arttool import cli, errors, image
from arttool.checks.pixels import measure_isolated
from arttool.sprite import clean, merge
from arttool.sprite.recolor import position_diff

BG = (100, 120, 80)


def _key(rgb) -> int:
   return (rgb[0] << 16) | (rgb[1] << 8) | rgb[2]


def _field(w=7, h=7, rgb=BG) -> np.ndarray:
   arr = image.new(w, h)
   arr[:, :] = (*rgb, 255)
   return arr


def _near(rgb, d):
   return tuple(min(255, v + d) for v in rgb)


def _args(in_path, out_path, **over):
   values = {"in_dir": str(in_path), "out_dir": str(out_path), "tol": None, "max_colors": None, "palette": False,
             "keep": None, "per_image": False, "sheet": None, "scale": 4, "report": None, "dry_run": False, "clean": False}
   values.update(over)
   return argparse.Namespace(**values)


# --- hue_jump : 거의 검정은 색조를 안 따진다 ---


def test_hue_jump_skips_near_black_pair():
   assert merge.hue_jumps({_key((2, 2, 5)): _key((5, 1, 1))}) == []
   assert merge.hue_jumps({_key((63, 20, 20)): _key((20, 63, 20))}) == []      # 둘 다 64 미만이면 건너뛴다
   assert merge.hue_jumps({_key((60, 10, 10)): _key((10, 60, 10))}) == []      # 알려진 한계 : 둘 다 어두운 진짜 이동도 놓친다


@pytest.mark.parametrize("src, dst", [((20, 20, 63), (230, 120, 20)), ((200, 200, 60), (40, 10, 10)), ((63, 45, 30), (50, 64, 30))])
def test_hue_jump_one_side_dark_still_warns(src, dst):
   """한쪽만 어두우면 따진다 — --max-colors · --palette 에서 어두운 색이 먼 밝은 색으로 가는 이동을 잡는다."""
   assert len(merge.hue_jumps({_key(src): _key(dst)})) == 1


def test_hue_jump_both_below_dark_max_skipped_review_case():
   assert merge.hue_jumps({_key((63, 45, 30)): _key((50, 63, 30))}) == []      # 둘 다 63 이하


def test_hue_jump_still_catches_bright_pair():
   found = merge.hue_jumps({_key((64, 20, 20)): _key((20, 64, 20))})
   assert len(found) == 1 and found[0]["hue_diff"] == 120.0
   leaf = merge.hue_jumps({_key((90, 140, 50)): _key((130, 100, 60))})          # 녹색 잎 → 갈색
   assert len(leaf) == 1


# --- clean_specks : 메우는 조건 ---


def test_lonely_speck_close_to_field_is_filled():
   arr = _field()
   arr[3, 3, :3] = _near(BG, 10)
   out, filled = clean.clean_specks(arr, tol=4, keep=set())
   assert filled == 1 and tuple(out[3, 3]) == (*BG, 255)


def test_far_speck_highlight_is_kept():
   arr = _field()
   arr[3, 3, :3] = (240, 240, 230)          # 하이라이트 : 거리가 문턱 밖
   out, filled = clean.clean_specks(arr, tol=4, keep=set())
   assert filled == 0 and np.array_equal(out, arr)


def test_needs_six_of_eight_same_neighbors():
   arr = _field()
   arr[3, 3, :3] = _near(BG, 5)
   arr[2, 2:5, :3] = [(30, 30, 200), (31, 30, 200), (32, 30, 200)]   # 이웃 셋이 먼 색 → 바탕 몫 5/8
   out, _filled = clean.clean_specks(arr, tol=4, keep=set())
   assert tuple(out[3, 3, :3]) == _near(BG, 5)


def test_six_of_eight_is_enough():
   arr = _field(9, 9)
   arr[4, 4, :3] = _near(BG, 5)
   arr[3, 3, :3] = (30, 30, 200)
   arr[3, 4, :3] = (31, 30, 200)
   out, _filled = clean.clean_specks(arr, tol=4, keep=set())
   assert tuple(out[4, 4, :3]) == BG


def test_two_pixel_blob_is_filled_three_is_kept():
   arr = _field(9, 9)
   speck = _near(BG, 8)
   arr[4, 3, :3] = speck
   arr[4, 4, :3] = speck
   out, filled = clean.clean_specks(arr, tol=4, keep=set())
   assert filled == 2 and speck not in image.opaque_colors(out)
   arr[4, 5, :3] = speck
   out, filled = clean.clean_specks(arr, tol=4, keep=set())
   assert filled == 0


def _changed(a, b) -> int:
   return int((a != b).any(axis=2).sum())


def test_pair_one_side_blocked_keeps_both():
   """짝 한 칸만 메울 수 있으면 둘 다 둔다 — 한 칸만 메우면 남은 칸이 새 외톨이가 된다 (리뷰 재현 ①)."""
   arr = _field(9, 9)
   speck = (108, 128, 88)
   arr[4, 4, :3] = speck
   arr[4, 5, :3] = speck
   arr[3:6, 6, :3] = [(20, 20, 200), (20, 20, 201), (20, 20, 202)]
   before = measure_isolated(arr)["count"]
   out, filled = clean.clean_specks(arr, tol=4, keep=set())
   assert filled == 0 == _changed(arr, out)
   assert measure_isolated(out)["count"] == before


def test_pair_on_picture_border_keeps_both():
   """짝 한 칸이 그림 테두리면 안쪽 칸도 안 메운다 (리뷰 재현 ②)."""
   arr = _field(9, 9)
   speck = (108, 128, 88)
   arr[0, 4, :3] = speck
   arr[1, 4, :3] = speck
   out, filled = clean.clean_specks(arr, tol=4, keep=set())
   assert filled == 0 and np.array_equal(out, arr)


def test_diagonal_pair_filled_together():
   arr = _field(9, 9)
   speck = (108, 128, 88)
   arr[3, 3, :3] = speck
   arr[4, 4, :3] = speck
   out, filled = clean.clean_specks(arr, tol=4, keep=set())
   assert filled == 2 == _changed(arr, out)
   assert speck not in image.opaque_colors(out)


@pytest.mark.parametrize("seed", range(12))
def test_clean_never_adds_isolated(seed):
   rng = np.random.default_rng(seed)
   arr = _field(24, 24)
   base = np.array([BG, (140, 100, 70), (60, 60, 160)])
   arr[:, :, :3] = base[rng.integers(0, 3, size=(24, 24)) * (rng.random((24, 24)) < 0.15)]
   for _ in range(40):
      y, x = rng.integers(0, 24, size=2)
      arr[y, x, :3] = np.clip(arr[y, x, :3].astype(int) + rng.integers(-12, 13, size=3), 0, 255)
   for _ in range(10):                          # 2칸 덩어리를 일부러 많이
      y, x = rng.integers(1, 22, size=2)
      dy, dx = [(0, 1), (1, 0), (1, 1), (1, -1)][int(rng.integers(0, 4))]
      color = np.clip(arr[y, x, :3].astype(int) + 9, 0, 255)
      arr[y, x, :3] = color
      arr[y + dy, x + dx, :3] = color
   arr[rng.random((24, 24)) < 0.03, 3] = 0
   out, filled = clean.clean_specks(arr, tol=4, keep=set())
   assert filled == _changed(arr, out)
   assert measure_isolated(out)["count"] <= measure_isolated(arr)["count"]


@pytest.mark.parametrize("tol, d, filled", [(4, 16, 1), (4, 17, 0), (None, 16, 1), (None, 17, 0),
                                             (10, 20, 1), (10, 21, 0), (16, 24, 1), (16, 25, 0), (40, 25, 0)])
def test_distance_limit(tol, d, filled):
   arr = _field()
   arr[3, 3, :3] = _near(BG, d)
   _out, n = clean.clean_specks(arr, tol=tol, keep=set())
   assert n == filled


def test_touching_transparent_or_half_alpha_is_kept():
   arr = _field()
   arr[3, 3, :3] = _near(BG, 5)
   arr[2, 2, 3] = 0                         # 대각선으로 투명과 맞닿음
   assert clean.clean_specks(arr, tol=4, keep=set())[1] == 0
   arr = _field()
   arr[3, 3] = (*_near(BG, 5), 128)
   assert clean.clean_specks(arr, tol=4, keep=set())[1] == 0


def test_picture_border_is_kept():
   arr = _field()
   arr[0, 3, :3] = _near(BG, 5)
   assert clean.clean_specks(arr, tol=4, keep=set())[1] == 0


def test_keep_color_is_kept():
   arr = _field()
   arr[3, 3, :3] = _near(BG, 5)
   assert clean.clean_specks(arr, tol=4, keep={_key(_near(BG, 5))})[1] == 0


def test_isolated_mask_shared_with_check():
   arr = _field()
   arr[3, 3, :3] = (240, 240, 230)
   arr[1, 1, :3] = _near(BG, 3)
   assert measure_isolated(arr)["count"] == 2


# --- run : 보고 · dry-run · 여러 장 ---


def _noisy_field(seed=5) -> np.ndarray:
   rng = np.random.default_rng(seed)
   arr = _field(16, 16)
   for _ in range(12):
      y, x = rng.integers(2, 14, size=2)
      arr[y, x, :3] = _near(BG, int(rng.integers(8, 14)))
   arr[8, 8, :3] = (250, 250, 250)           # 하이라이트 하나
   arr[0, :, 3] = 0
   return arr


def _save(tmp_path, arr, name="a.png"):
   folder = tmp_path / "in"
   folder.mkdir(exist_ok=True)
   image.save(folder / name, arr)
   return folder


def test_run_clean_reports_and_fills(tmp_path):
   arr = _noisy_field()
   src = _save(tmp_path, arr)
   rep = merge.run(_args(src, tmp_path / "out", clean=True))
   out = image.load(tmp_path / "out" / "a.png")
   row = rep["images"][0]["clean"]
   assert row["filled"] > 0 and row["isolated_after"] < row["isolated_before"]
   assert row["isolated_after"] == measure_isolated(out)["count"]
   assert tuple(out[8, 8, :3]) == (250, 250, 250)
   assert rep["clean"] == {"filled": row["filled"], "isolated_before": row["isolated_before"], "isolated_after": row["isolated_after"]}
   assert position_diff(arr, out) == 0 and np.array_equal(out[:, :, 3], arr[:, :, 3])
   assert rep["colors_after"] == image.count_colors(out)


def test_run_clean_off_by_default(tmp_path):
   src = _save(tmp_path, _noisy_field())
   rep = merge.run(_args(src, tmp_path / "out"))
   assert rep["clean"] is None and rep["images"][0]["clean"] is None


def test_run_clean_dry_run_same_numbers(tmp_path):
   src = _save(tmp_path, _noisy_field())
   _save(tmp_path, _noisy_field(9), "b.png")
   real = merge.run(_args(src, tmp_path / "out", clean=True))
   dry = merge.run(_args(src, tmp_path / "dry", clean=True, dry_run=True, sheet=str(tmp_path / "s.png")))
   assert not (tmp_path / "dry").exists() and not (tmp_path / "s.png").exists()
   assert dry["clean"] == real["clean"] and [r["clean"] for r in dry["images"]] == [r["clean"] for r in real["images"]]
   assert real["clean"]["filled"] == sum(r["clean"]["filled"] for r in real["images"])


def test_run_clean_per_image_and_keep(tmp_path):
   arr = _field(9, 9)
   arr[4, 4, :3] = (110, 130, 90)
   src = _save(tmp_path, arr)
   rep = merge.run(_args(src, tmp_path / "out", clean=True, per_image=True, keep="#6E825A"))
   assert rep["images"][0]["clean"]["filled"] == 0
   out = image.load(tmp_path / "out" / "a.png")
   assert tuple(out[4, 4, :3]) == (110, 130, 90)


def test_cli_clean_flag(tmp_path):
   src = _save(tmp_path, _noisy_field())
   report = tmp_path / "r.json"
   assert cli.main(["merge-colors", "--in", str(src), "--out", str(tmp_path / "o"), "--clean", "--report", str(report)]) == errors.EXIT_OK
   import json
   assert json.loads(report.read_text(encoding="utf-8"))["clean"]["filled"] > 0
