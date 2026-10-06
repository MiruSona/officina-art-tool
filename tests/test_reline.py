"""`reline` — 외곽선 단색 맞추기 (2026-10-04 피드백후속설계 3-6). 그림은 전부 코드로 만든다."""

from __future__ import annotations

import argparse

import numpy as np
import pytest

from arttool import image
from arttool.errors import UsageError
from arttool.sprite import reline

INK = (10, 10, 10)        # 고리에 가장 많은 어두운 색
INK2 = (30, 20, 20)
INK3 = (20, 20, 40)
SKIN = (240, 200, 160)
LIGHT = (200, 180, 150)   # 고리에 걸친 밝은 칸 (볕 받은 가장자리)


def _args(in_path, out_path, **over):
   values = {"in_dir": str(in_path), "out_dir": str(out_path), "color": None, "pick": "dark", "scope": "ring", "tol": 40, "report": None}
   values.update(over)
   return argparse.Namespace(**values)


def _sprite():
   """10×10, 바깥 한 칸 투명. [1, 9) 네모의 고리는 어두운 색 셋 + 밝은 칸 둘, 안은 살색."""
   arr = image.new(10, 10)
   arr[1:9, 1:9] = (*INK, 255)
   arr[2:8, 2:8] = (*SKIN, 255)
   arr[1, 3] = (*INK2, 255)
   arr[1, 4] = (*INK2, 255)
   arr[8, 5] = (*INK3, 255)
   arr[4, 1] = (*LIGHT, 255)
   arr[5, 1] = (*LIGHT, 255)
   return arr


def _ring_mask():
   mask = np.zeros((10, 10), dtype=bool)
   mask[1:9, 1:9] = True
   mask[2:8, 2:8] = False
   return mask


def _save(tmp_path, arr, name="a.png"):
   folder = tmp_path / "in"
   folder.mkdir(exist_ok=True)
   image.save(folder / name, arr)
   return folder


def test_reline_ring_dark_to_one_color(tmp_path):
   src = _save(tmp_path, _sprite())
   rep = reline.run(_args(src, tmp_path / "out"))
   out = image.load(tmp_path / "out" / "a.png")
   ring = _ring_mask()
   ring[4, 1] = ring[5, 1] = False
   assert np.all(out[ring][:, :3] == INK)
   assert np.all(out[2:8, 2:8, :3] == SKIN)
   assert np.array_equal(out[:, :, 3], _sprite()[:, :, 3])
   row = rep["images"][0]
   assert row["target"] == "#0A0A0A"
   assert row["changed"] == 3
   assert sorted(row["merged_colors"]) == ["#141428", "#1E1414"]
   assert rep["status"] == "ok"


def test_reline_keeps_light_ring_pixels(tmp_path):
   src = _save(tmp_path, _sprite())
   reline.run(_args(src, tmp_path / "out"))
   out = image.load(tmp_path / "out" / "a.png")
   assert tuple(out[4, 1, :3]) == LIGHT and tuple(out[5, 1, :3]) == LIGHT


def test_reline_pick_all(tmp_path):
   src = _save(tmp_path, _sprite())
   rep = reline.run(_args(src, tmp_path / "out", pick="all"))
   out = image.load(tmp_path / "out" / "a.png")
   assert np.all(out[_ring_mask()][:, :3] == INK)
   assert rep["images"][0]["changed"] == 5


def test_reline_scope_colors_inner_lines(tmp_path):
   arr = _sprite()
   arr[4, 4] = (*INK2, 255)      # 안쪽 선 한 칸 — 고리와 같은 색
   src = _save(tmp_path, arr)
   reline.run(_args(src, tmp_path / "ring"))
   assert tuple(image.load(tmp_path / "ring" / "a.png")[4, 4, :3]) == INK2
   rep = reline.run(_args(src, tmp_path / "colors", scope="colors"))
   assert tuple(image.load(tmp_path / "colors" / "a.png")[4, 4, :3]) == INK
   assert rep["images"][0]["changed"] == 4


def test_reline_color_from_profile(tmp_path):
   src = _save(tmp_path, _sprite())
   prof = tmp_path / "p.yaml"
   prof.write_text('name: p\npalette:\n  outline: "#112233"\n', encoding="utf-8")
   rep = reline.run(_args(src, tmp_path / "out", profile=str(prof)))
   out = image.load(tmp_path / "out" / "a.png")
   assert tuple(out[1, 1, :3]) == (0x11, 0x22, 0x33)
   assert rep["images"][0]["target"] == "#112233"
   # --color 가 프로필보다 먼저다
   rep = reline.run(_args(src, tmp_path / "out2", profile=str(prof), color="#445566"))
   assert rep["images"][0]["target"] == "#445566"
   assert tuple(image.load(tmp_path / "out2" / "a.png")[1, 1, :3]) == (0x44, 0x55, 0x66)


def test_reline_many_colors_warns(tmp_path):
   arr = _sprite()
   for i, x in enumerate(range(2, 9)):
      arr[8, x] = (i * 4, i * 3, i * 2, 255)
   src = _save(tmp_path, arr)
   rep = reline.run(_args(src, tmp_path / "out"))
   assert len(rep["images"][0]["merged_colors"]) > reline.MANY_COLORS
   assert rep["status"] == "warn"
   assert any(w["rule"] == "reline.many_colors" for w in rep["warnings"])


def test_reline_no_alpha_copies_and_warns(tmp_path):
   arr = image.new(6, 6, (*SKIN, 255))
   arr[0, :] = (*INK2, 255)
   src = _save(tmp_path, arr)
   rep = reline.run(_args(src, tmp_path / "out"))
   assert np.array_equal(image.load(tmp_path / "out" / "a.png"), arr)
   assert rep["images"][0]["changed"] == 0
   assert any(w["rule"] == "reline.no_alpha" for w in rep["warnings"])


def test_reline_refuses_in_place(tmp_path):
   src = _save(tmp_path, _sprite())
   with pytest.raises(UsageError):
      reline.run(_args(src, src))
   with pytest.raises(UsageError):
      reline.run(_args(src / "a.png", src / "a.png"))
   assert np.array_equal(image.load(src / "a.png"), _sprite())


def test_reline_from_changes_only_named_colors(tmp_path):
   """--from — 같은 밝기의 선 색 둘 중 고른 색만 바꾼다 (피드백 2026-10-05)."""
   arr = _sprite()
   other = (20, 30, 20)
   arr[1, 6] = (*other, 255)                                   # INK2 와 밝기가 비슷한 다른 선 색
   src = _save(tmp_path, arr)
   rep = reline.run(_args(src, tmp_path / "out", pick=None, tol=None, from_colors="#1E1414", color="#000000"))
   out = image.load(tmp_path / "out" / "a.png")
   assert tuple(out[1, 3, :3]) == (0, 0, 0) and tuple(out[1, 4, :3]) == (0, 0, 0)
   assert tuple(out[1, 6, :3]) == other                       # 이름 안 준 색은 그대로
   assert tuple(out[8, 5, :3]) == INK3
   row = rep["images"][0]
   assert row["changed"] == 2 and row["merged_colors"] == ["#1E1414"]
   assert rep["from"] == ["#1E1414"]


def test_reline_from_with_scope_colors_reaches_inside(tmp_path):
   arr = _sprite()
   arr[4, 4] = (*INK2, 255)                                    # 안쪽 선 한 칸
   src = _save(tmp_path, arr)
   reline.run(_args(src, tmp_path / "ring", pick=None, tol=None, from_colors="#1E1414", color="#000000"))
   assert tuple(image.load(tmp_path / "ring" / "a.png")[4, 4, :3]) == INK2
   rep = reline.run(_args(src, tmp_path / "all", pick=None, tol=None, from_colors="#1E1414", color="#000000", scope="colors"))
   assert tuple(image.load(tmp_path / "all" / "a.png")[4, 4, :3]) == (0, 0, 0)
   assert rep["images"][0]["changed"] == 3


def test_reline_from_without_color_picks_from_rest_of_ring(tmp_path):
   """--from 만 주면 목록 밖 어두운 고리 칸에서 가장 많은 색으로 바꾼다."""
   src = _save(tmp_path, _sprite())
   rep = reline.run(_args(src, tmp_path / "out", pick=None, tol=None, from_colors="#1E1414"))
   assert rep["images"][0]["target"] == "#0A0A0A"
   assert tuple(image.load(tmp_path / "out" / "a.png")[1, 3, :3]) == INK


def test_reline_from_darkest_named_still_picks_rest(tmp_path):
   """목록 색이 고리에서 가장 어두워도 남은 선 색(갈색)을 고른다 — 가장 어두운 밝기는 목록 밖 고리 칸에서 잰다 (리뷰 1)."""
   brown = (0x46, 0x32, 0x28)
   arr = image.new(10, 10)
   arr[1:9, 1:9] = (*brown, 255)
   arr[2:8, 2:8] = (*SKIN, 255)
   arr[1, 1:9] = (0, 0, 0, 255)                                # 윗변만 순흑
   src = _save(tmp_path, arr)
   rep = reline.run(_args(src, tmp_path / "out", pick=None, tol=None, from_colors="#000000"))
   row = rep["images"][0]
   assert row["target"] == "#463228" and row["changed"] == 8
   assert not any(w["rule"] == "reline.no_target" for w in rep["warnings"])


def test_reline_from_no_target_warns(tmp_path):
   """목록 밖 고리 칸이 없으면 안 바꾸고 reline.no_target."""
   arr = image.new(10, 10)
   arr[1:9, 1:9] = (*INK2, 255)
   arr[2:8, 2:8] = (*SKIN, 255)
   src = _save(tmp_path, arr)
   rep = reline.run(_args(src, tmp_path / "out", pick=None, tol=None, from_colors="#1E1414"))
   assert rep["images"][0]["changed"] == 0
   assert any(w["rule"] == "reline.no_target" for w in rep["warnings"])
   assert rep["status"] == "warn"


def test_reline_from_missing_color_warns(tmp_path):
   """목록 색이 대상 칸에 한 칸도 없으면 그 색을 적어 reline.from_missing (hex 오타 알아채기, 리뷰 2)."""
   src = _save(tmp_path, _sprite())
   rep = reline.run(_args(src, tmp_path / "out", pick=None, tol=None, from_colors="#1E1414,#ABCDEF", color="#000000"))
   miss = [w for w in rep["warnings"] if w["rule"] == "reline.from_missing"]
   assert len(miss) == 1 and "#ABCDEF" in miss[0]["detail"] and "#1E1414" not in miss[0]["detail"]
   assert rep["status"] == "warn" and rep["images"][0]["changed"] == 2


def test_reline_from_scope_colors_inner_only_color(tmp_path):
   """--from + --scope colors 는 고리와 상관없이 그 색을 그림 전체에서 바꾼다 (리뷰 3).
   --scope ring 이면 안쪽에만 있는 색은 안 걸려 from_missing."""
   inner = (0x3C, 0x14, 0x14)
   arr = _sprite()
   arr[4, 4] = arr[4, 5] = (*inner, 255)
   src = _save(tmp_path, arr)
   ring_rep = reline.run(_args(src, tmp_path / "ring", pick=None, tol=None, from_colors="#3C1414", color="#000000"))
   assert ring_rep["images"][0]["changed"] == 0
   assert any(w["rule"] == "reline.from_missing" for w in ring_rep["warnings"])
   rep = reline.run(_args(src, tmp_path / "all", pick=None, tol=None, from_colors="#3C1414", color="#000000", scope="colors"))
   out = image.load(tmp_path / "all" / "a.png")
   assert tuple(out[4, 4, :3]) == (0, 0, 0) and tuple(out[4, 5, :3]) == (0, 0, 0)
   assert rep["images"][0]["changed"] == 2
   assert not any(w["rule"] == "reline.from_missing" for w in rep["warnings"])


def test_reline_from_many_colors_hint_does_not_suggest_tol(tmp_path):
   arr = _sprite()
   names = []
   for i, x in enumerate(range(2, 9)):
      arr[8, x] = (i * 4, i * 3, i * 2, 255)
      names.append("#%02X%02X%02X" % (i * 4, i * 3, i * 2))
   src = _save(tmp_path, arr)
   rep = reline.run(_args(src, tmp_path / "out", pick=None, tol=None, from_colors=",".join(names), color="#FF0000"))
   line = next(w for w in rep["warnings"] if w["rule"] == "reline.many_colors")
   assert "--tol" not in line["detail"] and "--from" in line["detail"]


def test_reline_from_rejects_bad_hex_and_pick_tol(tmp_path):
   src = _save(tmp_path, _sprite())
   for over in ({"from_colors": "#12345"}, {"from_colors": "#1E1414,zz"}, {"from_colors": " , "},
                {"from_colors": "#1E1414", "pick": "dark"}, {"from_colors": "#1E1414", "tol": 10}):
      values = {"pick": None, "tol": None, **over}
      with pytest.raises(UsageError):
         reline.run(_args(src, tmp_path / "out", **values))
   assert not (tmp_path / "out").exists()


def test_reline_bad_values_exit2(tmp_path):
   src = _save(tmp_path, _sprite())
   for over in ({"color": "#12345"}, {"pick": "light"}, {"scope": "all"}, {"tol": 300}):
      with pytest.raises(UsageError):
         reline.run(_args(src, tmp_path / "out", **over))
   assert not (tmp_path / "out").exists()


# --- 1판 : --depth · --color-dark · 보고 나누기 (2026-10-06 설계 4절) ---

BLACK = (0, 0, 0)
LINE = (60, 50, 40)


def _framed(size=10, thick=2, body=(200, 160, 120)):
   """투명 1칸 테두리 안에 thick 칸 검정 선, 그 안이 몸통인 네모."""
   arr = np.zeros((size, size, 4), dtype=np.uint8)
   arr[1:-1, 1:-1] = (*BLACK, 255)
   arr[1 + thick : -1 - thick, 1 + thick : -1 - thick] = (*body, 255)
   return arr


def test_depth2_fills_2px_line():
   out, info = reline.reline(_framed(), LINE, depth=2)
   assert not np.any(np.all(out[:, :, :3] == BLACK, axis=2) & (out[:, :, 3] > 0))
   assert info["changed_inner"] > 0


def test_depth2_skips_detached_eye():
   arr = _framed(size=12)
   arr[6, 6] = (*BLACK, 255)          # 선과 떨어진 눈동자
   out, _ = reline.reline(arr, LINE, depth=2)
   assert tuple(out[6, 6, :3]) == BLACK


def test_depth_with_from_stays_in_list():
   arr = _framed()
   arr[2, 2:8] = (10, 10, 10, 255)    # 안쪽 줄 일부가 목록 밖 색
   out, _ = reline.reline(arr, LINE, from_colors=[BLACK], depth=2)
   assert tuple(out[2, 4, :3]) == (10, 10, 10)


def test_depth_with_scope_colors_usage_error(tmp_path):
   image.save(tmp_path / "a.png", _framed())
   with pytest.raises(UsageError, match="--depth"):
      reline.run(_args(tmp_path / "a.png", tmp_path / "out", depth=2, scope="colors"))


def test_dark_gap_without_color_usage_error(tmp_path):
   image.save(tmp_path / "a.png", _framed())
   with pytest.raises(UsageError, match="--dark-gap"):
      reline.run(_args(tmp_path / "a.png", tmp_path / "out", dark_gap=10))


def test_color_dark_on_low_contrast():
   arr = _framed(thick=1, body=(62, 52, 42))   # 면이 선 색과 밝기가 거의 같다
   out, info = reline.reline(arr, LINE, color_dark=(250, 250, 250))
   assert info["changed_dark"] > 0
   assert tuple(out[1, 1, :3]) == LINE          # 모서리 칸은 면 이웃이 없어 기본 색
   assert tuple(out[2, 1, :3]) == (250, 250, 250)


def test_changed_split_sums():
   _, info = reline.reline(_framed(), LINE, depth=2, color_dark=(250, 250, 250))
   assert info["changed"] == info["changed_ring"] + info["changed_inner"]
   _, colors = reline.reline(_framed(), LINE, pick="all", scope="colors")
   assert colors["changed"] == colors["changed_ring"] + colors["changed_inner"]


def test_inner_left_warns():
   _, info = reline.reline(_framed(), LINE)
   assert info["inner_left"] > 0
   rules = [w["rule"] for w in reline.image_warnings("a.png", {**info, "no_alpha": False})]
   assert "reline.inner_left" in rules


def test_low_contrast_warns():
   _, info = reline.reline(_framed(thick=1, body=(62, 52, 42)), LINE)
   rules = [w["rule"] for w in reline.image_warnings("a.png", {**info, "no_alpha": False})]
   assert "reline.low_contrast" in rules


def test_default_call_same_as_before():
   arr = _framed()
   out, info = reline.reline(arr, LINE)
   ring = reline.ring_mask(arr)
   expect = arr.copy()
   expect[ring, :3] = LINE
   assert np.array_equal(out, expect)
   assert info["changed"] == int(ring.sum()) and info["changed_inner"] == 0 and info["changed_dark"] == 0


def test_depth_zero_is_usage_not_one(tmp_path):
   image.save(tmp_path / "a.png", _framed())
   with pytest.raises(UsageError, match="--depth"):
      reline.run(_args(tmp_path / "a.png", tmp_path / "out", depth=0))
   assert not (tmp_path / "out").exists()


def test_early_return_reports_have_same_keys_as_full_report():
   full = reline.reline(_framed(), LINE)[1]
   no_alpha = reline.reline(np.full((6, 6, 4), 255, dtype=np.uint8), LINE)[1]
   no_ring = reline.reline(np.zeros((6, 6, 4), dtype=np.uint8), LINE)[1]
   for info in (no_alpha, no_ring):
      assert {"changed_ring", "changed_inner", "changed_dark"} <= set(info)
      assert info["changed_ring"] == info["changed_inner"] == info["changed_dark"] == 0
   assert {"changed_ring", "changed_inner", "changed_dark"} <= set(full)
