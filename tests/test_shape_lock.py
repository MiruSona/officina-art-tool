"""도형 렌더러 보완 고리 1 : 팔레트 잠금(shape/lock.py) · 안쪽 선 재질 색 · 도장 반복 흔들림 시험."""

import copy
import json

import numpy as np
import pytest

from arttool.errors import ArtToolError
from arttool.shape import expand, load, parse, render
from arttool.shape.lock import Lock, apply as lock_apply, to_lab

BASE = {
   "canvas": {"size": [40, 24], "origin": [20, 12]},
   "outline": {"mode": "solid", "color": "#2A1A14", "inner_gap": 1},
   "materials": {
      "wood": {"ramp": ["#6B3F2A", "#8E5A3C", "#B07A52"]},
      "pot": {"ramp": ["#4F6E8C", "#6E92B0", "#9CBBD2"], "line": {"color": "#3E1E21"}},
   },
   "shapes": [
      {"type": "box", "size": [30, 6, 4], "pos": [0, -6, 0], "material": "wood"},
      {"type": "ellipsoid", "radii": [8, 6, 5], "pos": [0, 2, 6], "material": "pot"},
   ],
   "texture": [{"kind": "mottle", "on": "*", "seed": 2}],
}
PAL = ["#352E27", "#513930", "#8D6347", "#A66B4E", "#C98A6A", "#2C2D46", "#415174", "#558AA2", "#95CAE2", "#D4EEFA"]


def _spec(**extra):
   data = copy.deepcopy(BASE)
   data.update(extra)
   return parse(data)


def _colors(arr):
   solid = arr[:, :, 3] > 0
   return {tuple(int(v) for v in c) for c in np.unique(arr[solid][:, :3], axis=0)}


def _hex(c):
   return tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))


def test_no_lock_is_identical_and_report_unchanged():
   a, rep = render(_spec())
   b, _ = render(parse(copy.deepcopy(BASE)))
   assert np.array_equal(a, b) and "locked" not in rep


def test_lock_keeps_every_color_in_palette_and_silhouette():
   plain, _ = render(_spec())
   out, rep = render(_spec(palette_lock={"colors": PAL}))
   assert _colors(out) <= {_hex(c) for c in PAL}
   assert rep["locked"] > 0
   assert np.array_equal(out[:, :, 3], plain[:, :, 3])
   assert rep["lint"]["counts"]["lint.stray_color"] == 0


def test_lock_from_file_with_real_len_and_ramp_filter(tmp_path):
   pal = {"ramps": {"wood": ["#513930", "#8D6347", "#A66B4E", "#A66B4E"], "sky": ["#558AA2", "#95CAE2"],
                    "food_x": ["#FF0000"]}, "real_len": {"wood": 3}, "outline": "#352E27"}
   (tmp_path / "p.json").write_text(json.dumps(pal), encoding="utf-8")
   data = copy.deepcopy(BASE)
   data["palette_lock"] = {"file": "p.json", "ramps": ["*", "!food_*"]}
   (tmp_path / "s.shape.json").write_text(json.dumps(data), encoding="utf-8")
   out, _ = render(load(tmp_path / "s.shape.json"))
   allowed = {_hex(c) for c in ["#513930", "#8D6347", "#A66B4E", "#558AA2", "#95CAE2", "#352E27"]}
   assert _colors(out) <= allowed


def test_keep_steps_keeps_luma_order_and_avoids_merging():
   # 램프 세 단이 모두 한 팔레트 색에 가장 가깝더라도, 단 순서대로 다른 색으로 간다
   arr = np.zeros((1, 3, 4), dtype=np.uint8)
   arr[0, :, 3] = 255
   arr[0, 0, :3], arr[0, 1, :3], arr[0, 2, :3] = (100, 70, 50), (110, 78, 56), (120, 86, 62)
   pal = [(105, 74, 53), (60, 40, 30), (160, 120, 90)]
   near = arr.copy()
   lock_apply(Lock(pal, keep_steps=False), near, np.zeros((1, 3), dtype=np.int64))
   assert len(_colors(near)) == 1                    # 가장 가까운 색만 고르면 세 단이 한 색
   kept = arr.copy()
   lock_apply(Lock(pal, keep_steps=True, merge_cost=50), kept, np.zeros((1, 3), dtype=np.int64))
   L = to_lab(kept[0, :, :3].astype(int))[:, 0]
   assert len(_colors(kept)) >= 2 and np.all(np.diff(L) >= 0)   # 단이 남고 밝기 차례가 안 뒤집힌다


def test_lock_maps_blue_to_nearest_blue_family():
   out, _ = render(_spec(palette_lock={"colors": PAL}))
   plain, _ = render(_spec())
   blue = (plain[:, :, 2].astype(int) > plain[:, :, 0].astype(int) + 20) & (plain[:, :, 3] > 0)
   got = out[blue][:, :3].astype(int)
   assert (got[:, 2] >= got[:, 0]).mean() > 0.9     # 파란 도기는 팔레트 안 파랑 · 남색 계열로


@pytest.mark.parametrize("bad, word", [
   ({"colors": []}, "colors"), ({"file": "a.json", "colors": ["#000000"]}, "하나만"), ({"colors": ["#00"]}, "colors"),
   ({"colors": PAL, "keep_steps": 1}, "keep_steps"), ({"colors": PAL, "merge_cost": -1}, "merge_cost"),
   ({"colors": PAL, "ramps": "x"}, "ramps"), (3, "사전"),
])
def test_lock_bad_values(bad, word):
   with pytest.raises(ArtToolError, match=word):
      _spec(palette_lock=bad)


def test_lock_missing_file_is_refused(tmp_path):
   with pytest.raises(ArtToolError, match="없다"):
      parse({**copy.deepcopy(BASE), "palette_lock": {"file": "nope.json"}}, base=tmp_path)


def test_template_spec_passes_palette_lock(tmp_path):
   tpl = {"template_version": 1, "params": {}, "spec": copy.deepcopy(BASE)}
   (tmp_path / "t.template.json").write_text(json.dumps(tpl), encoding="utf-8")
   data = expand({"template": "t.template.json", "palette_lock": {"colors": PAL}}, tmp_path)
   assert data["palette_lock"] == {"colors": PAL}


# ── 안쪽 선 재질 색 ──────────────────────────────────────────────────────────

def test_inner_color_default_is_unchanged():
   a, _ = render(_spec())
   data = copy.deepcopy(BASE)
   data["outline"]["inner_color"] = "line"
   b, _ = render(parse(data))
   assert np.array_equal(a, b)


def test_inner_color_material_uses_dark_of_own_ramp():
   data = copy.deepcopy(BASE)
   data.pop("texture")
   data["outline"] = {"mode": "none", "inner_gap": 1}      # 바깥 선(재질 line) 빼고 안쪽 선만 본다
   line, _ = render(parse(data))
   data["outline"]["inner_color"] = "material"
   mat, rep = render(parse(data))
   assert rep["inner_line"] > 0
   red = np.all(line[:, :, :3] == _hex("#3E1E21"), axis=2)
   assert red.any() and not np.all(mat[:, :, :3] == _hex("#3E1E21"), axis=2).any()   # 붉은 선이 사라졌다
   changed = np.any(line != mat, axis=2)
   got = mat[changed][:, :3].astype(int)
   assert (got[:, 2] >= got[:, 0]).all()             # 파란 도기 안쪽 선은 파랑 계열


def test_inner_color_bad_value():
   data = copy.deepcopy(BASE)
   data["outline"]["inner_color"] = "pink"
   with pytest.raises(ArtToolError, match="inner_color"):
      parse(data)


# ── 도장 반복 흔들림 ─────────────────────────────────────────────────────────

STAMPED = {
   "canvas": {"size": [30, 40], "origin": [15, 20]},
   "outline": {"mode": "none"},
   "materials": {"paper": {"ramp": ["#C2434A", "#DE6B6E", "#F2A08E"], "level": 1}},
   "shapes": [{"type": "box", "size": [26, 34, 6], "material": "paper"}],
   "stamps": [{"on": "paper", "at": [0, 12], "grid": ["####################"], "legend": {"#": "#A8323A"},
               "copies": [[0, 0], [0, 6], [0, 12], [0, 18]]}],
}


def _band_rows(arr):
   band = np.all(arr[:, :, :3] == (0xA8, 0x32, 0x3A), axis=2)
   return band, sorted({int(y) for y in np.nonzero(band.any(axis=1))[0]})


def test_stamp_without_jitter_is_identical():
   a, _ = render(parse(copy.deepcopy(STAMPED)))
   data = copy.deepcopy(STAMPED)
   data["stamps"][0]["jitter"] = None
   b, _ = render(parse(data))
   assert np.array_equal(a, b)


def test_stamp_jitter_breaks_rhythm_and_is_deterministic():
   plain, _ = render(parse(copy.deepcopy(STAMPED)))
   data = copy.deepcopy(STAMPED)
   data["stamps"][0]["jitter"] = {"seed": 3, "shift": 1, "gap": 0.3, "thick": 0.5, "seg": 4}
   one, _ = render(parse(data))
   two, _ = render(parse(data))
   assert np.array_equal(one, two)
   b0, rows0 = _band_rows(plain)
   b1, rows1 = _band_rows(one)
   assert len(set(np.diff(rows0))) == 1                       # 예전 : 같은 간격
   assert b1.sum() != b0.sum()                                # 끊김 · 두께로 칸 수가 바뀐다
   per_row = [int(b1[y].sum()) for y in rows1]
   assert len(set(per_row)) > 1                               # 줄마다 길이가 다르다


def test_stamp_jitter_bad_key():
   data = copy.deepcopy(STAMPED)
   data["stamps"][0]["jitter"] = {"wobble": 1}
   with pytest.raises(ArtToolError, match="모르는 칸"):
      parse(data)


# ── 주름 · 빛 띠 자리 지정 (fold mass spots · tone) ─────────────────────────

CLOTH = {
   "canvas": {"size": [40, 40], "origin": [20, 20]},
   "outline": {"mode": "none"},
   "materials": {"cloth": {"ramp": ["#2C2D46", "#393651", "#415174", "#558AA2"], "level": 2}},
   "shapes": [{"type": "box", "size": [36, 36, 4], "material": "cloth"}],
}


def _cloth(rule):
   data = copy.deepcopy(CLOTH)
   data["texture"] = [{"kind": "fold", "style": "mass", "on": "cloth", "width": 3, "light": 0.0, "strength": 1.0, **rule}]
   return render(parse(data))[0]


def test_spots_place_masses_only_there():
   plain = render(parse(copy.deepcopy(CLOTH)))[0]
   out = _cloth({"spots": [[10, 8, 6], [28, 20, 6]], "density": 0.5})
   changed = np.any(out != plain, axis=2)
   ys, xs = np.nonzero(changed)
   assert changed.sum() > 0
   assert set(zip(ys // 10, xs // 10)) <= {(0, 0), (0, 1), (1, 0), (1, 1), (1, 2), (2, 2), (2, 3), (1, 3)}
   assert not changed[30:, :8].any() and not changed[:5, 30:].any()   # 적지 않은 자리는 그대로 (density 무시)
   l_plain = np.mean(plain[changed][:, :3].astype(float))
   assert np.mean(out[changed][:, :3].astype(float)) < l_plain        # shade = 어둡게


def test_tone_light_brightens_without_rim():
   plain = render(parse(copy.deepcopy(CLOTH)))[0]
   out = _cloth({"spots": [[20, 10, 5]], "tone": "light", "width": 6})
   changed = np.any(out != plain, axis=2)
   assert changed.sum() >= 15
   assert np.mean(out[changed][:, :3].astype(float)) > np.mean(plain[changed][:, :3].astype(float))


def test_spots_deterministic_and_default_unchanged():
   a = _cloth({"density": 0.01, "seed": 4})
   data = copy.deepcopy(CLOTH)
   data["texture"] = [{"kind": "fold", "style": "mass", "on": "cloth", "width": 3, "light": 0.0, "strength": 1.0,
                       "density": 0.01, "seed": 4, "spots": [], "tone": "shade"}]
   assert np.array_equal(a, render(parse(data))[0])
   assert np.array_equal(_cloth({"spots": [[10, 10, 5]]}), _cloth({"spots": [[10, 10, 5]]}))


@pytest.mark.parametrize("rule, word", [
   ({"kind": "fold", "spots": [[1, 2]]}, "mass"), ({"kind": "fold", "style": "mass", "spots": [[1]]}, "spots"),
   ({"kind": "fold", "style": "mass", "tone": "glow"}, "tone"), ({"kind": "mottle", "tone": "light"}, "mass"),
])
def test_spots_tone_bad_values(rule, word):
   data = copy.deepcopy(CLOTH)
   data["texture"] = [{"on": "cloth", **rule}]
   with pytest.raises(ArtToolError, match=word):
      parse(data)
