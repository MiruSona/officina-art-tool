"""`merge-colors` — 가까운 색 합치기 (2026-10-05 피드백 판 다음 1순위). 그림은 전부 코드로 만든다."""

from __future__ import annotations

import argparse
import json

import numpy as np
import pytest

from arttool import image
from arttool.checks.pixels import measure_near_colors
from arttool.errors import ArtToolError, UsageError
from arttool.sprite import merge
from arttool.sprite.recolor import position_diff


def _args(in_path, out_path, **over):
   values = {"in_dir": str(in_path), "out_dir": str(out_path), "tol": None, "max_colors": None, "palette": False,
             "keep": None, "per_image": False, "sheet": None, "scale": 4, "report": None, "dry_run": False}
   values.update(over)
   return argparse.Namespace(**values)


def _key(rgb) -> int:
   return (rgb[0] << 16) | (rgb[1] << 8) | rgb[2]


def _gray(v) -> int:
   return _key((v, v, v))


def _strip(colors_counts, alpha=255) -> np.ndarray:
   """색마다 정한 칸 수만큼 한 줄로 늘어놓은 그림. [(rgb, 칸 수), …]"""
   total = sum(n for _c, n in colors_counts)
   arr = image.new(total, 1)
   x = 0
   for rgb, n in colors_counts:
      arr[0, x : x + n] = (*rgb, alpha)
      x += n
   return arr


def _save(tmp_path, arr, name="a.png", folder="in"):
   where = tmp_path / folder
   where.mkdir(exist_ok=True)
   image.save(where / name, arr)
   return where


def _colors(arr) -> set:
   return image.opaque_colors(arr)


# --- 1. 사슬 : 남는 색에만 붙고, 표는 한 번만 적용한다 ---


def test_tol_chain_middle_least_used_goes_to_bigger_side():
   counts = {_gray(0): 10, _gray(6): 8, _gray(3): 2}
   table = merge.plan_tol(counts, 4, set())
   assert table == {_gray(3): _gray(0)}           # 0 과 6 은 서로 안 합쳐진다


def test_tol_chain_middle_most_used_takes_both():
   counts = {_gray(3): 10, _gray(0): 4, _gray(6): 4}
   table = merge.plan_tol(counts, 4, set())
   assert table == {_gray(0): _gray(3), _gray(6): _gray(3)}


def test_tol_chain_does_not_drag_far_color():
   """0 이 가장 많고 3 이 0 에 붙으면, 6 은 (남는 색이 아닌) 3 을 따라 0 으로 끌려가지 않는다."""
   counts = {_gray(0): 10, _gray(3): 5, _gray(6): 2}
   table = merge.plan_tol(counts, 4, set())
   assert table == {_gray(3): _gray(0)}


def test_apply_table_once_not_transitive():
   arr = _strip([((0, 0, 0), 2), ((3, 3, 3), 2)])
   out = merge.apply_table(arr, {_gray(0): _gray(3), _gray(3): _gray(6)})
   assert tuple(out[0, 0, :3]) == (3, 3, 3)       # A→B 만. B→C 로 번지지 않는다
   assert tuple(out[0, 2, :3]) == (6, 6, 6)


# --- 2. --max-colors : 합친 뒤 칸 수를 다시 센다 ---


def test_max_colors_recounts_after_merge():
   """B(3)·C(3) 가 먼저 합쳐져 B 가 6칸이 되면, 그다음 A(5) 와의 짝에서 B 가 이긴다.
   칸 수를 다시 안 세면 A 가 이겨 결과가 A 로 간다."""
   a, b, c = _gray(0), _gray(10), _gray(12)
   table, left = merge.plan_max({a: 5, b: 3, c: 3}, 1, set(), None)
   assert left == 1
   assert table == {a: b, c: b}


def test_max_colors_stops_at_target():
   counts = {_gray(0): 9, _gray(2): 1, _gray(100): 9, _gray(103): 1, _gray(200): 5}
   table, left = merge.plan_max(counts, 3, set(), None)
   assert left == 3
   assert table == {_gray(2): _gray(0), _gray(103): _gray(100)}


def test_max_colors_with_tol_never_merges_beyond_tol():
   counts = {_gray(0): 9, _gray(2): 1, _gray(100): 9}
   table, left = merge.plan_max(counts, 1, set(), 4)
   assert table == {_gray(2): _gray(0)} and left == 2


def test_max_colors_large_values_no_overflow():
   """체비셰프가 같으면 유클리드 제곱으로 가른다 — 40000 · 120000 은 int16 을 넘는다."""
   x, y = _key((0, 0, 0)), _key((200, 0, 0))          # 200 · 제곱 40000
   p, q = _key((0, 255, 55)), _key((200, 55, 255))    # 200 · 제곱 120000. 다른 짝은 다 255
   table, left = merge.plan_max({x: 5, y: 1, p: 5, q: 2}, 3, set(), None)
   assert table == {y: x} and left == 3


# --- 3. 지킨 색 ---


def test_keep_color_survives_and_attracts():
   a, k = _gray(0), _gray(2)
   assert merge.plan_tol({a: 10, k: 1}, 4, {k}) == {a: k}


def test_two_kept_colors_never_merge():
   a, b = _gray(0), _gray(2)
   assert merge.plan_tol({a: 10, b: 1}, 4, {a, b}) == {}
   table, left = merge.plan_max({a: 10, b: 1}, 1, {a, b}, None)
   assert table == {} and left == 2


def test_profile_outline_is_protected(tmp_path):
   arr = _strip([((18, 18, 18), 8), ((16, 16, 16), 1)])
   src = _save(tmp_path, arr)
   prof = tmp_path / "p.yaml"
   prof.write_text('name: p\npalette:\n  outline: "#101010"\n', encoding="utf-8")
   rep = merge.run(_args(src, tmp_path / "out", profile=str(prof)))
   out = image.load(tmp_path / "out" / "a.png")
   assert _colors(out) == {(16, 16, 16)}
   assert rep["merge_table"] == {"#121212": "#101010"}


def test_keep_blocks_target_and_warns(tmp_path):
   arr = _strip([((0, 0, 0), 5), ((2, 2, 2), 1)])
   src = _save(tmp_path, arr)
   rep = merge.run(_args(src, tmp_path / "out", max_colors=1, keep="#000000,#020202"))
   assert rep["status"] == "warn"
   assert "merge.target_unreached" in {w["rule"] for w in rep["warnings"]}
   assert rep["colors_after"] == 2


# --- 4. 여러 장 ---


def test_shared_table_same_target_across_images(tmp_path):
   a, n, b = (0, 0, 0), (2, 2, 2), (4, 4, 4)
   _save(tmp_path, _strip([(a, 10), (n, 1), (b, 2)]), "one.png")
   src = _save(tmp_path, _strip([(a, 1), (n, 1), (b, 10)]), "two.png")
   rep = merge.run(_args(src, tmp_path / "out", tol=2))
   one = image.load(tmp_path / "out" / "one.png")
   two = image.load(tmp_path / "out" / "two.png")
   assert tuple(one[0, 10, :3]) == b and tuple(two[0, 1, :3]) == b     # 전체 칸 수 B 12 > A 11
   assert rep["merge_table"] == {"#020202": "#040404"}

   rep = merge.run(_args(src, tmp_path / "per", tol=2, per_image=True))
   one = image.load(tmp_path / "per" / "one.png")
   two = image.load(tmp_path / "per" / "two.png")
   assert tuple(one[0, 10, :3]) == a and tuple(two[0, 1, :3]) == b
   assert rep["merge_table"] is None
   assert [r["merge_table"] for r in rep["images"]] == [{"#020202": "#000000"}, {"#020202": "#040404"}]


def test_max_colors_counts_union_or_per_image(tmp_path):
   _save(tmp_path, _strip([((0, 0, 0), 5), ((90, 90, 90), 5)]), "one.png")
   src = _save(tmp_path, _strip([((200, 200, 200), 5), ((250, 250, 250), 5)]), "two.png")
   rep = merge.run(_args(src, tmp_path / "out", max_colors=2, dry_run=True))
   assert rep["colors_before"] == 4 and rep["colors_after"] == 2
   rep = merge.run(_args(src, tmp_path / "per", max_colors=2, per_image=True, dry_run=True))
   assert [(r["colors_before"], r["colors_after"]) for r in rep["images"]] == [(2, 2), (2, 2)]
   assert "merge.no_change" in {w["rule"] for w in rep["warnings"]}


# --- 5. 알파 ---


def test_alpha_untouched_and_transparent_rgb_ignored(tmp_path):
   arr = image.new(6, 1)
   arr[0, 0:3] = (0, 0, 0, 255)
   arr[0, 3] = (2, 2, 2, 128)          # 반투명 잡색 : RGB 만 바뀐다
   arr[0, 4] = (3, 3, 3, 0)            # 투명 칸의 RGB 찌꺼기 : 세지도 바꾸지도 않는다
   arr[0, 5] = (0, 0, 0, 255)
   src = _save(tmp_path, arr)
   rep = merge.run(_args(src, tmp_path / "out"))
   out = image.load(tmp_path / "out" / "a.png")
   assert tuple(out[0, 3]) == (0, 0, 0, 128)
   assert tuple(out[0, 4]) == (3, 3, 3, 0)
   assert np.array_equal(out[:, :, 3], arr[:, :, 3])
   assert position_diff(arr, out) == 0
   row = rep["images"][0]
   assert (row["colors_before"], row["colors_after"], row["changed"]) == (2, 1, 1)
   assert row["colors_before"] == image.count_colors(arr)


# --- 6. check 와 맞물림 ---


def _noisy(seed=7) -> np.ndarray:
   rng = np.random.default_rng(seed)
   base = np.array([(40, 30, 30), (120, 90, 60), (200, 170, 120), (60, 120, 200), (250, 250, 240)])
   pick = rng.integers(0, len(base), size=(24, 24))
   rgb = base[pick] + rng.integers(-2, 3, size=(24, 24, 3))
   arr = image.new(24, 24)
   arr[:, :, :3] = np.clip(rgb, 0, 255).astype(np.uint8)
   arr[:, :, 3] = 255
   arr[0, :, 3] = 0
   return arr


def test_default_tol_clears_near_colors(tmp_path):
   arr = _noisy()
   assert len(measure_near_colors(arr, 4)) > 0
   src = _save(tmp_path, arr)
   rep = merge.run(_args(src, tmp_path / "out"))
   out = image.load(tmp_path / "out" / "a.png")
   assert rep["tol"] == 4 and rep["tol_from"] == "near_colors.max_delta"
   assert measure_near_colors(out, 4) == []
   assert image.count_colors(out) == rep["colors_after"] <= 5


def test_default_tol_keeps_only_kept_pairs(tmp_path):
   arr = _strip([((0, 0, 0), 4), ((2, 2, 2), 1), ((50, 50, 50), 4), ((51, 51, 51), 4)])
   src = _save(tmp_path, arr)
   merge.run(_args(src, tmp_path / "out", keep="#323232,#333333"))
   out = image.load(tmp_path / "out" / "a.png")
   pairs = measure_near_colors(out, 4)
   assert {(p["from"], p["to"]) for p in pairs} <= {("#323232", "#333333"), ("#333333", "#323232")}
   assert (2, 2, 2) not in _colors(out)


def test_max_colors_result_within_limit(tmp_path):
   src = _save(tmp_path, _noisy(3))
   rep = merge.run(_args(src, tmp_path / "out", max_colors=6))
   out = image.load(tmp_path / "out" / "a.png")
   assert image.count_colors(out) <= 6 and rep["colors_after"] == image.count_colors(out)
   assert all(rgb in _colors(_noisy(3)) for rgb in _colors(out))     # 평균색을 새로 만들지 않는다


# --- 7. 인자 · 경고 · 결정성 ---


def test_dry_run_writes_nothing(tmp_path):
   src = _save(tmp_path, _noisy())
   rep = merge.run(_args(src, tmp_path / "out", sheet=str(tmp_path / "s.png"), dry_run=True))
   assert rep["dry_run"] is True and rep["merge_table"]
   assert not (tmp_path / "out").exists() and not (tmp_path / "s.png").exists()
   assert rep["images"][0]["out"] is None


@pytest.mark.parametrize("over", [{"palette": True, "tol": 3}, {"palette": True, "max_colors": 4}, {"tol": 256}, {"tol": -1}, {"max_colors": 0},
                                  {"palette": True}, {"keep": "#GGGGGG"}])
def test_bad_args(tmp_path, over):
   src = _save(tmp_path, _noisy())
   with pytest.raises(UsageError):
      merge.run(_args(src, tmp_path / "out", **over))


def test_palette_snaps_to_ramps(tmp_path):
   (tmp_path / "r.json").write_text(json.dumps({"name": "r", "ramp_len": 2, "outline": "#000000",
                                                 "ramps": {"g": ["#404040", "#C0C0C0"]}}), encoding="utf-8")
   prof = tmp_path / "p.yaml"
   prof.write_text('name: p\npalette:\n  ramps_file: r.json\n', encoding="utf-8")
   src = _save(tmp_path, _strip([((60, 60, 60), 2), ((180, 180, 180), 2), ((0, 0, 0), 1), ((7, 7, 7), 1)]))
   rep = merge.run(_args(src, tmp_path / "out", palette=True, profile=str(prof)))
   out = image.load(tmp_path / "out" / "a.png")
   assert _colors(out) == {(64, 64, 64), (192, 192, 192), (0, 0, 0)}
   assert rep["mode"] == "palette"
   with pytest.raises(UsageError):
      prof.write_text('name: p\npalette:\n  ramps_file: missing.json\n', encoding="utf-8")
      merge.run(_args(src, tmp_path / "o2", palette=True, profile=str(prof)))


def test_no_change_warns(tmp_path):
   src = _save(tmp_path, _strip([((0, 0, 0), 2), ((100, 100, 100), 2)]))
   rep = merge.run(_args(src, tmp_path / "out"))
   assert rep["status"] == "warn" and [w["rule"] for w in rep["warnings"]] == ["merge.no_change"]


def test_keep_missing_warns(tmp_path):
   src = _save(tmp_path, _strip([((0, 0, 0), 2), ((2, 2, 2), 1)]))
   rep = merge.run(_args(src, tmp_path / "out", keep="#ABCDEF"))
   found = {w["rule"]: w for w in rep["warnings"]}
   assert "#ABCDEF" in found["merge.keep_missing"]["detail"]


def test_hue_jump_warns_but_merges(tmp_path):
   # 빨강(색조 0°) · 노랑 기운(47°) — RGB 로는 가장 가까운 짝이라 합쳐진다. 회색 짝은 색조를 안 따진다
   src = _save(tmp_path, _strip([((200, 60, 60), 3), ((200, 170, 60), 1), ((30, 30, 30), 2), ((33, 32, 32), 1)]))
   rep = merge.run(_args(src, tmp_path / "out", max_colors=2))
   out = image.load(tmp_path / "out" / "a.png")
   assert _colors(out) == {(200, 60, 60), (30, 30, 30)}
   jumps = [w for w in rep["warnings"] if w["rule"] == "merge.hue_jump"]
   assert len(jumps) == 1
   assert jumps[0]["items"] == [{"from": "#C8AA3C", "to": "#C83C3C", "hue_diff": 47.1}]


def test_deterministic_bytes(tmp_path):
   src = _save(tmp_path, _noisy(11))
   merge.run(_args(src, tmp_path / "o1", max_colors=7))
   merge.run(_args(src, tmp_path / "o2", max_colors=7))
   assert (tmp_path / "o1" / "a.png").read_bytes() == (tmp_path / "o2" / "a.png").read_bytes()


def test_tie_breaks_by_key():
   a, b = _gray(0), _gray(2)
   assert merge.plan_tol({a: 3, b: 3}, 4, set()) == {b: a}
   assert merge.plan_max({a: 3, b: 3}, 1, set(), None) == ({b: a}, 1)


def _cheb(a: int, b: int) -> int:
   return max(abs(x - y) for x, y in zip(merge._rgb(a), merge._rgb(b)))


def test_max_with_tol_chain_stays_within_tol():
   """0–4 에서 4 가 이겨 3칸이 되고 4–8 에서 8 에 지면, 0 이 사슬을 타고 거리 8 의 8 로 가던 것 (리뷰 1)."""
   table, left = merge.plan_max({_gray(0): 1, _gray(4): 2, _gray(8): 5}, 1, set(), 4)
   assert all(_cheb(s, d) <= 4 for s, d in table.items())
   assert left == 2


def test_max_kept_color_wins_even_if_less_used():
   assert merge.plan_max({_gray(0): 10, _gray(2): 1}, 1, {_gray(2)}, None) == ({_gray(0): _gray(2)}, 1)


def _random_case(rng):
   n = int(rng.integers(3, 14))
   base = rng.integers(0, 40, size=3)
   keys = {_key(tuple(int(v) for v in base + rng.integers(0, 16, size=3))) for _ in range(n)}
   counts = {k: int(rng.integers(1, 20)) for k in keys}
   keep = {k for k in keys if rng.random() < 0.2}
   return counts, keep, int(rng.integers(2, 9)), int(rng.integers(1, len(keys) + 1))


def test_random_plans_keep_tol_and_kept_colors():
   """씨앗 고정 60판 : 원래 색 → 끝 색 거리가 늘 tol 안 · 지킨 색은 from 이 안 된다 · 끝 색은 표에 다시 안 나온다."""
   rng = np.random.default_rng(20261005)
   for _ in range(60):
      counts, keep, tol, target = _random_case(rng)
      for table in (merge.plan_tol(counts, tol, keep), merge.plan_max(counts, target, keep, tol)[0]):
         assert all(_cheb(s, d) <= tol for s, d in table.items())
         assert not (set(table) & keep)
         assert not (set(table.values()) & set(table))
      table, left = merge.plan_max(counts, target, keep, None)
      assert not (set(table) & keep) and left == len(counts) - len(table)


def test_close_pairs_public_name():
   from arttool.checks import pixels
   assert pixels.close_pairs is pixels._close_pairs


def test_pair_cap_refuses(tmp_path, monkeypatch):
   monkeypatch.setattr(merge, "PAIRS_MAX", 3)
   counts = {_gray(v): 1 for v in range(0, 8)}
   with pytest.raises(ArtToolError, match="--tol 을 줄이"):
      merge.plan_tol(counts, 4, set())
   with pytest.raises(ArtToolError, match="--tol 을 줄이"):
      merge.plan_max(counts, 1, set(), 4)
   src = _save(tmp_path, _noisy())
   with pytest.raises(ArtToolError):
      merge.run(_args(src, tmp_path / "out"))


def test_sheet_inside_input_folder_names_sheet(tmp_path):
   src = _save(tmp_path, _noisy())
   with pytest.raises(UsageError, match="--sheet"):
      merge.run(_args(src, tmp_path / "out", sheet=str(src / "s.png")))


def test_sheet_and_refuses_overwrite(tmp_path):
   src = _save(tmp_path, _noisy())
   rep = merge.run(_args(src, tmp_path / "out", sheet=str(tmp_path / "s.png"), scale=2))
   sheet = image.load(tmp_path / "s.png")
   assert sheet.shape[0] == 24 * 2 and sheet.shape[1] == 24 * 2 * 2 + 2
   assert rep["sheet"]
   with pytest.raises(UsageError):
      merge.run(_args(src / "a.png", src / "a.png"))
