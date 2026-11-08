"""도형 렌더러 보완 고리 2 : 잠금 계열 지킴(family · max_de · hue_tol) · 종류별 잠금 프로필."""

import json

import numpy as np
import pytest

from arttool.errors import ArtToolError
from arttool.shape import parse, render
from arttool.shape.lock import Lock, apply as lock_apply, parse as lock_parse, to_lab

# 파랑 계열 없음 : 보라 · 갈색 · 회색 램프만
RAMPS = [("violet", [(0x3B, 0x2A, 0x55), (0x5E, 0x46, 0x86), (0x8A, 0x70, 0xB4)]),
         ("wood", [(0x51, 0x39, 0x30), (0x8D, 0x63, 0x47), (0xC9, 0x8A, 0x6A)]),
         ("gray", [(0x40, 0x40, 0x40), (0x80, 0x80, 0x80), (0xC0, 0xC0, 0xC0)])]
FLAT = [c for _, cols in RAMPS for c in cols]


def _lock(**kw):
   return Lock(list(FLAT), ramps=list(RAMPS), **kw)


def _row(*cols):
   a = np.zeros((1, len(cols), 4), dtype=np.uint8)
   for i, c in enumerate(cols):
      a[0, i] = (*c, 255)
   return a


def test_family_off_is_old_behavior():
   a1 = _row((60, 80, 140), (90, 120, 180))
   a2 = a1.copy()
   g = np.zeros((1, 2), dtype=np.int64)
   lock_apply(Lock(list(FLAT)), a1, g)
   lock_apply(_lock(), a2, g)            # family 끔 : ramps 를 줘도 같다
   assert (a1 == a2).all()


def test_family_keeps_blue_out_of_violet():
   # 계열 없는 파랑 : 옛 잠금은 보라로 보내지만 family 는 그대로 둔다
   blue = _row((50, 70, 130), (70, 100, 170), (110, 150, 210))
   g = np.zeros((1, 3), dtype=np.int64)
   old = blue.copy()
   lock_apply(Lock(list(FLAT)), old, g)
   assert any(tuple(int(v) for v in old[0, i, :3]) in FLAT for i in range(3))
   new = blue.copy()
   lk = _lock(family=True)
   lock_apply(lk, new, g)
   assert (new == blue).all()
   assert lk.kept == 3


def test_family_picks_one_ramp_and_keeps_order():
   brown = _row((0x55, 0x3A, 0x2E), (0x90, 0x62, 0x48), (0xC5, 0x8C, 0x68))
   g = np.zeros((1, 3), dtype=np.int64)
   lk = _lock(family=True)
   lock_apply(lk, brown, g)
   got = [tuple(int(v) for v in brown[0, i, :3]) for i in range(3)]
   assert got == RAMPS[1][1]
   assert lk.kept == 0


def test_family_groups_choose_their_own_ramp():
   a = _row((0x8C, 0x60, 0x45), (0x5F, 0x47, 0x84), (0x82, 0x82, 0x82))
   g = np.array([[0, 1, 2]], dtype=np.int64)
   lock_apply(_lock(family=True), a, g)
   assert tuple(a[0, 0, :3]) == RAMPS[1][1][1]
   assert tuple(a[0, 1, :3]) == RAMPS[0][1][1]
   assert tuple(a[0, 2, :3]) == RAMPS[2][1][1]


def test_hue_side_color_stays_in_family():
   # 곁색(같은 밝기 · 색조만 돈 색)은 같은 계열 안 색으로 간다 — 보라 · 회색으로 안 튄다
   a = _row((0x8C, 0x60, 0x45), (0x8C, 0x5A, 0x60), (0x8E, 0x66, 0x3C))
   g = np.zeros((1, 3), dtype=np.int64)
   lock_apply(_lock(family=True, max_de=30), a, g)
   for i in range(3):
      assert tuple(int(v) for v in a[0, i, :3]) in RAMPS[1][1]


def test_max_de_threshold():
   a = _row((0x90, 0x62, 0x48))
   g = np.zeros((1, 1), dtype=np.int64)
   lk = _lock(family=True, max_de=0.5)
   b = a.copy()
   lock_apply(lk, b, g)
   assert (b == a).all() and lk.kept == 1


def test_parse_family_fields_and_bad_values(tmp_path):
   lk = lock_parse({"colors": ["#112233", "#445566"], "family": True, "max_de": 9, "hue_tol": 20}, None)
   assert lk.family and lk.max_de == 9 and lk.hue_tol == 20 and lk.ramps[0][0] == "colors"
   for bad in ({"family": 1}, {"max_de": True}, {"max_de": -1}, {"hue_tol": 400}):
      with pytest.raises(ArtToolError):
         lock_parse({"colors": ["#112233"], **bad}, None)


def test_read_ramps_keeps_ramp_names(tmp_path):
   f = tmp_path / "p.json"
   f.write_text(json.dumps({"outline": "#101010", "real_len": {"a": 2},
                            "ramps": {"a": ["#200000", "#400000", "#600000"], "b": ["#002000"]}}))
   lk = lock_parse({"file": "p.json"}, tmp_path)
   assert [n for n, _ in lk.ramps] == ["a", "b", "outline"]
   assert len(lk.ramps[0][1]) == 2


def _profile(tmp_path):
   (tmp_path / "pal").mkdir()
   (tmp_path / "pal" / "people.json").write_text(json.dumps({"ramps": {"blue": ["#203060", "#4060A0"]}}))
   (tmp_path / "pal" / "bldg.json").write_text(json.dumps({"ramps": {"wood": ["#513930", "#8D6347"]}}))
   prof = tmp_path / "pal" / "kinds.json"
   prof.write_text(json.dumps({"kinds": {"customer": {"file": "people.json", "family": True},
                                         "building": "bldg.json", "food": None}}))
   return prof


def test_profile_picks_kind(tmp_path):
   prof = _profile(tmp_path)
   lk = lock_parse({"profile": str(prof), "kind": "customer"}, None)
   assert lk.family and lk.colors == [(0x20, 0x30, 0x60), (0x40, 0x60, 0xA0)]
   lk2 = lock_parse({"profile": "pal/kinds.json", "kind": "building", "merge_cost": 3}, tmp_path)
   assert not lk2.family and lk2.merge_cost == 3 and lk2.names == ["wood"]
   assert lock_parse({"profile": str(prof), "kind": "food"}, None) is None


def test_profile_bad(tmp_path):
   prof = _profile(tmp_path)
   with pytest.raises(ArtToolError, match="없는 종류"):
      lock_parse({"profile": str(prof), "kind": "decor"}, None)
   with pytest.raises(ArtToolError):
      lock_parse({"profile": str(prof)}, None)
   with pytest.raises(ArtToolError, match="프로필 파일이 없다"):
      lock_parse({"profile": str(tmp_path / "x.json"), "kind": "food"}, None)


SPEC = {
   "canvas": {"size": [40, 24], "origin": [20, 12]},
   "outline": {"mode": "solid", "color": "#2A1A14"},
   "materials": {"pot": {"ramp": ["#2F4A80", "#4F6EB0", "#86A8DA"]},
                 "wood": {"ramp": ["#6B3F2A", "#8E5A3C", "#B07A52"]}},
   "shapes": [{"type": "box", "size": [30, 6, 4], "pos": [0, -6, 0], "material": "wood"},
              {"type": "ellipsoid", "radii": [8, 6, 5], "pos": [0, 2, 6], "material": "pot"}],
}


def test_render_family_report_and_food_profile_off(tmp_path):
   prof = _profile(tmp_path)
   plain, _ = render(parse(dict(SPEC)), "front")
   off, rep_off = render(parse(dict(SPEC, palette_lock={"profile": str(prof), "kind": "food"})), "front")
   assert (plain == off).all() and "locked" not in rep_off
   lk = {"colors": ["#2A1A14"] + ["#%02X%02X%02X" % c for c in FLAT], "family": True}
   arr, rep = render(parse(dict(SPEC, palette_lock=lk)), "front")
   assert rep["lock_kept"] > 0              # 파란 도기는 계열이 없어 남는다
   pot = to_lab(np.array([[0x4F, 0x6E, 0xB0]]))
   solid = arr[:, :, 3] > 0
   cols = np.unique(arr[solid][:, :3], axis=0)
   assert any(np.sqrt(((to_lab(cols) - pot) ** 2).sum(1)) < 1)   # 파랑 그대로


# ── 빛 띠 한 색 (fold mass tone band) ────────────────────────────────────

HAIR = {
   "canvas": {"size": [40, 40], "origin": [20, 20]},
   "outline": {"mode": "none"},
   "materials": {"base": {"ramp": ["#2D2A32", "#3A3640", "#625D6A"], "level": 1},
                 "shine": {"ramp": ["#625D6A"]}},
   "shapes": [{"type": "box", "size": [36, 36, 4], "material": "base"},
              {"type": "box", "size": [2, 36, 4], "pos": [0, 0, 3], "material": "shine"}],
}


def _hair(tone):
   d = json.loads(json.dumps(HAIR))
   d["texture"] = [{"kind": "fold", "style": "mass", "on": ["base", "shine"], "width": 8, "lean": 0, "bend": 0,
                    "strength": 1.0, "tone": tone, "spots": [[14, 6, 6], [24, 6, 6]]}]
   return render(parse(d))[0]


def test_tone_band_is_one_color_and_hides_strands():
   plain = render(parse(json.loads(json.dumps(HAIR))))[0]
   band = _hair("band")
   changed = np.any(band != plain, axis=2)
   assert changed.sum() >= 30
   cols = np.unique(band[changed][:, :3], axis=0)
   assert len(cols) == 1                               # 띠 안 = 한 색
   assert tuple(cols[0]) == (0x62, 0x5D, 0x6A)          # 주색(#3A3640) 한 단 위
   light = _hair("light")
   assert len(np.unique(light[np.any(light != plain, axis=2)][:, :3], axis=0)) > 1   # light 는 줄마다 다른 색


def test_tone_band_deterministic():
   assert np.array_equal(_hair("band"), _hair("band"))
