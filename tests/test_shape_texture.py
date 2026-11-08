"""도형 렌더러 질감 규칙 (shape/texture.py) 시험."""

import copy

import numpy as np
import pytest

from arttool.errors import ArtToolError
from arttool.shape import expand, parse, render
from arttool.shape.texture import KINDS, hue_color, shift_color, value_noise


def _luma(c):
   return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]


BASE = {
   "canvas": {"size": [40, 24], "origin": [20, 12]},
   "outline": {"mode": "solid", "color": "#2A1A14"},
   "materials": {
      "wood": {"ramp": ["#6B3F2A", "#8E5A3C", "#B07A52"], "level": 1},
      "cloth": {"ramp": ["#A83A34", "#C8524A", "#E07A6E"], "level": 1},
   },
   "shapes": [
      {"type": "box", "size": [30, 6, 4], "pos": [0, 5, 0], "material": "wood"},
      {"type": "box", "size": [6, 10, 4], "pos": [-10, -4, 0], "material": "wood"},
      {"type": "ellipsoid", "radii": [7, 5, 4], "pos": [6, -4, 0], "material": "cloth"},
   ],
}


def _spec(texture=None):
   data = copy.deepcopy(BASE)
   if texture is not None:
      data["texture"] = texture
   return parse(data)


def test_no_texture_is_identical_and_report_unchanged():
   a, rep_a = render(_spec())
   b, rep_b = render(_spec([]))
   assert np.array_equal(a, b)
   assert "textured" not in rep_a and "textured" not in rep_b


@pytest.mark.parametrize("kind", ["wood_grain", "weave", "mottle", "fold"])
def test_each_kind_changes_only_its_material_and_is_deterministic(kind):
   rule = {"kind": kind, "on": "wood", "seed": 3, "density": 0.5, "knots": 1.0}
   plain, _ = render(_spec())
   one, rep = render(_spec([rule]))
   two, _ = render(_spec([rule]))
   assert np.array_equal(one, two)                    # 같은 seed → 같은 그림
   assert rep["textured"] > 0
   cloth = np.all(plain[:, :, :3] == (0xC8, 0x52, 0x4A), axis=2)
   assert np.array_equal(one[cloth], plain[cloth])    # 다른 재질은 그대로
   assert np.array_equal(one[:, :, 3], plain[:, :, 3])  # 실루엣은 그대로


def test_seed_changes_texture():
   a, _ = render(_spec([{"kind": "mottle", "on": "*", "seed": 1}]))
   b, _ = render(_spec([{"kind": "mottle", "on": "*", "seed": 2}]))
   assert not np.array_equal(a, b)


def test_wood_grain_follows_long_side():
   """가로 판은 결이 가로로 길다 : 가로 같은 색 줄이 세로 줄보다 길다."""
   spec = parse({**copy.deepcopy(BASE), "outline": {"mode": "none"},
                 "shapes": [{"type": "box", "size": [36, 10, 4], "material": "wood"}],
                 "texture": [{"kind": "wood_grain", "on": "wood", "density": 0.5, "length": 6, "gap": 0.2, "seed": 1}]})
   arr, _ = render(spec)
   key = arr[:, :, 0].astype(int) << 16 | arr[:, :, 1].astype(int) << 8 | arr[:, :, 2]
   inner = key[8:16, 4:36]
   same_h = (inner[:, 1:] == inner[:, :-1]).mean()
   same_v = (inner[1:, :] == inner[:-1, :]).mean()
   assert same_h > same_v


def test_texture_adds_colors_and_lint_has_no_stray():
   plain, rp = render(_spec())
   arr, rep = render(_spec([{"kind": "mottle", "on": "*", "seed": 1}, {"kind": "hue_side", "on": "*", "share": 0.4}]))
   assert rep["colors"] > rp["colors"]
   assert rep["lint"]["counts"].get("lint.stray_color", 0) == 0


def test_shift_color_half_step_sits_between_ramp_steps():
   ramp = [(0x6B, 0x3F, 0x2A), (0x8E, 0x5A, 0x3C), (0xB0, 0x7A, 0x52)]
   half = shift_color(ramp[1], ramp, -0.5)
   assert _luma(ramp[0]) < _luma(half) < _luma(ramp[1])
   up = shift_color(ramp[1], ramp, 0.5)
   assert _luma(ramp[1]) < _luma(up) < _luma(ramp[2])
   below = shift_color(ramp[0], ramp, -1.0)          # 램프 밖은 셈한 색
   assert _luma(below) < _luma(ramp[0])


def test_hue_color_keeps_luma_and_turns_hue():
   c = (0xC8, 0x52, 0x4A)
   for deg in (10, -10):
      got = hue_color(c, deg)
      assert got != c
      assert abs(_luma(got) - _luma(c)) < 2.5
   assert hue_color((128, 128, 128), 10) == (128, 128, 128)   # 무채색은 그대로


def test_value_noise_range_and_determinism():
   ys, xs = np.mgrid[0:20, 0:20]
   a = value_noise(xs.ravel().astype(float), ys.ravel().astype(float), 3.0, 4)
   b = value_noise(xs.ravel().astype(float), ys.ravel().astype(float), 3.0, 4)
   assert np.array_equal(a, b) and a.min() >= 0 and a.max() < 1


@pytest.mark.parametrize("bad, word", [
   ({"kind": "plaid", "on": "wood"}, "kind"),
   ({"kind": "mottle", "on": "stone"}, "맞는 재질"),
   ({"kind": "mottle", "on": "wood", "share": 2}, "share"),
   ({"kind": "weave", "on": "wood", "period": 1}, "period"),
   ({"kind": "wood_grain", "on": "wood", "dir": "z"}, "dir"),
])
def test_bad_rules_name_the_field(bad, word):
   with pytest.raises(ArtToolError, match=word):
      _spec([bad])


def test_glob_matches_materials():
   arr, rep = render(_spec([{"kind": "mottle", "on": ["w*"], "seed": 1}]))
   assert rep["textured"] > 0


def test_template_wrapper_passes_texture(tmp_path):
   tpl = tmp_path / "t.template.json"
   tpl.write_text('{"template_version": 1, "params": {}, "spec": ' + __import__("json").dumps(BASE) + "}", encoding="utf-8")
   data = expand({"template": "t.template.json", "texture": [{"kind": "mottle", "on": "wood"}]}, tmp_path)
   assert data["texture"][0]["kind"] == "mottle"
   assert set(KINDS) >= {"wood_grain", "weave", "mottle", "fold", "hue_side"}


# ── follow (모양 · 빛 따르기) · fold mass (2026-11-08 마무리 흐름 시험) ──────────────

BALL = {
   "canvas": {"size": [32, 32], "origin": [16, 16]},
   "light": "top_left",
   "outline": {"mode": "none"},
   "materials": {"clay": {"ramp": ["#3E5A7A", "#5E80A0", "#8EB0CC"], "ambient": 0.2,
                          "highlight": {"color": "#E8F4FF", "above": 0.97}}},
   "shapes": [{"type": "ellipsoid", "radii": [13, 13, 13], "material": "clay"}],
}


def _ball(texture):
   return parse({**copy.deepcopy(BALL), "texture": texture})


def _changed(a, b):
   return np.any(a[:, :, :3] != b[:, :, :3], axis=2)


def test_follow_none_is_the_old_behaviour():
   rule = {"kind": "mottle", "on": "clay", "seed": 3, "share": 0.4}
   a, _ = render(_ball([rule]))
   b, _ = render(_ball([{**rule, "follow": "none"}]))
   assert np.array_equal(a, b)


@pytest.mark.parametrize("follow", ["light", "form"])
def test_follow_puts_texture_on_shadow_side_and_spares_highlight(follow):
   """그늘 쪽(오른 아래)은 결이 많고 빛 쪽(왼 위)은 적다. 하이라이트 칸은 그대로."""
   rule = {"kind": "mottle", "on": "clay", "seed": 3, "share": 0.5}
   plain, _ = render(_ball([]))
   old, _ = render(_ball([rule]))
   new, _ = render(_ball([{**rule, "follow": follow}]))
   ch_old, ch_new = _changed(plain, old), _changed(plain, new)
   lit = np.zeros((32, 32), dtype=bool)
   lit[:16, :16] = True
   shade = np.zeros((32, 32), dtype=bool)
   shade[16:, 16:] = True
   assert ch_new[shade].sum() > ch_new[lit].sum()
   assert ch_new[lit].sum() < ch_old[lit].sum()
   shine = np.all(plain[:, :, :3] == (0xE8, 0xF4, 0xFF), axis=2)
   assert shine.any() and not ch_new[shine].any()


def test_follow_light_keeps_light_marks_off_the_top_level():
   """밝은 결은 맨 밝은 단에 안 생긴다 (맨 밝은 띠는 비운다)."""
   rule = {"kind": "mottle", "on": "clay", "seed": 5, "share": 0.6, "follow": "light"}
   plain, _ = render(_ball([]))
   arr, _ = render(_ball([rule]))
   top = np.all(plain[:, :, :3] == (0x8E, 0xB0, 0xCC), axis=2)
   brighter = (arr[:, :, :3].astype(int).sum(axis=2) > plain[:, :, :3].astype(int).sum(axis=2))
   assert top.any() and not (brighter & top).any()


def test_form_bends_mottle_around_round_shapes():
   """form : 둥근 도형은 얼룩이 둘레를 따라 늘어난다 — 바뀐 칸의 이웃이 둘레 방향으로 더 많이 같이 바뀐다."""
   rule = {"kind": "mottle", "on": "clay", "seed": 2, "share": 0.5, "cell": 2, "follow": "form", "fade": 0.0}
   plain, _ = render(_ball([]))
   arr, _ = render(_ball([rule]))
   ch = _changed(plain, arr)
   ys, xs = np.nonzero(ch)
   tang = rad = 0
   for y, x in zip(ys, xs):
      dx, dy = x + 0.5 - 16, y + 0.5 - 16
      n = np.hypot(dx, dy)
      if n < 4:
         continue
      tx, ty = -dy / n, dx / n
      for sx, sy, bucket in ((tx, ty, "t"), (dx / n, dy / n, "r")):
         nx, ny = int(round(x + sx)), int(round(y + sy))
         if 0 <= nx < 32 and 0 <= ny < 32 and ch[ny, nx]:
            if bucket == "t":
               tang += 1
            else:
               rad += 1
   assert tang > rad


def test_form_wood_grain_runs_around_a_ring():
   """form : 둥근 판의 나뭇결은 가로줄이 아니라 고리를 따라 돈다 — 가로 줄 길이가 auto 보다 짧다."""
   base = {"kind": "wood_grain", "on": "clay", "density": 0.5, "length": 6, "gap": 0.1, "seed": 1}
   flat = parse({**copy.deepcopy(BALL), "materials": {"clay": {"ramp": ["#6B3F2A", "#8E5A3C", "#B07A52"], "level": 1}},
                 "shapes": [{"type": "ellipsoid", "radii": [13, 13, 2], "material": "clay"}]})
   plain, _ = render(flat)

   def run_h(texture):
      spec = parse({**copy.deepcopy(BALL), "materials": {"clay": {"ramp": ["#6B3F2A", "#8E5A3C", "#B07A52"], "level": 1}},
                    "shapes": [{"type": "ellipsoid", "radii": [13, 13, 2], "material": "clay"}],
                    "texture": texture})
      arr, _ = render(spec)
      ch = _changed(plain, arr)
      return (ch[:, 1:] & ch[:, :-1]).sum() / max(1, ch.sum()), (ch[1:, :] & ch[:-1, :]).sum() / max(1, ch.sum())

   h_auto, v_auto = run_h([base])
   h_form, v_form = run_h([{**base, "follow": "form", "fade": 0.0}])
   assert h_auto > v_auto                     # 그냥은 가로 결
   assert v_form > v_auto                     # form 은 세로로도 이어진다 (고리의 왼 · 오른 쪽)


def test_fold_mass_makes_wide_patches_with_lit_rim():
   """mass 주름 : 그늘 판이 2칸 넘게 넓고, 빛 쪽(왼쪽) 옆에 밝은 테가 붙는다."""
   spec = parse({"canvas": {"size": [40, 40], "origin": [20, 20]}, "light": "top_left", "outline": {"mode": "none"},
                 "materials": {"cloth": {"ramp": ["#A83A34", "#C8524A", "#E07A6E"], "level": 1}},
                 "shapes": [{"type": "box", "size": [36, 36, 2], "material": "cloth"}],
                 "texture": [{"kind": "fold", "on": "cloth", "style": "mass", "density": 0.01, "length": 12, "width": 3,
                              "light": 0.5, "strength": 1.0, "seed": 4}]})
   arr, rep = render(spec)
   base = np.all(arr[:, :, :3] == (0xC8, 0x52, 0x4A), axis=2) | (arr[:, :, 3] == 0)
   luma = arr[:, :, :3].astype(float) @ np.array([0.299, 0.587, 0.114])
   mid = 0.299 * 0xC8 + 0.587 * 0x52 + 0.114 * 0x4A
   dark = (luma < mid - 1) & ~base
   light = (luma > mid + 1) & ~base
   assert rep["textured"] > 0 and dark.any() and light.any()
   widest = max(int(np.max(np.diff(np.flatnonzero(np.diff(np.r_[0, row.astype(int), 0]) != 0))[::2], initial=0))
                for row in dark)
   assert widest >= 3
   lit_rim = light[:, :-1] & dark[:, 1:]       # 밝은 칸 바로 오른쪽이 그늘
   assert lit_rim.sum() >= light.sum() * 0.5


def test_fold_line_default_unchanged_by_style_field():
   rule = {"kind": "fold", "on": "wood", "seed": 3, "density": 0.05}
   a, _ = render(_spec([rule]))
   b, _ = render(_spec([{**rule, "style": "line"}]))
   assert np.array_equal(a, b)


@pytest.mark.parametrize("bad, word", [
   ({"kind": "mottle", "on": "wood", "follow": "shape"}, "follow"),
   ({"kind": "mottle", "on": "wood", "style": "mass"}, "style"),
   ({"kind": "fold", "on": "wood", "style": "blob"}, "style"),
   ({"kind": "fold", "on": "wood", "style": "mass", "width": 0}, "width"),
   ({"kind": "mottle", "on": "wood", "follow": "light", "fade": 1.5}, "fade"),
])
def test_bad_follow_and_fold_fields(bad, word):
   with pytest.raises(ArtToolError, match=word):
      _spec([bad])
