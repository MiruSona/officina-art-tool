"""09-18 보류 1 — FREE_MAPS 무늬 맞추기와 그 회귀 시험.

고치기 전에 지나가던 프로필 · 프리셋이 고친 뒤에도 그대로 지나가는지 먼저 못 박는다.
"""
from pathlib import Path

import pytest

from arttool import profile as P
from arttool.errors import ProfileError

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("path", sorted((ROOT / "profiles").glob("*.yaml")), ids=lambda p: p.name)
def test_shipped_profiles_still_load(path):
   assert P.load_profile(str(path)).name


@pytest.mark.parametrize("name", sorted(p.stem for p in (ROOT / "profiles" / "presets").glob("*.yaml")))
def test_shipped_presets_still_load(name):
   P.reject_unknown(P.load_preset(name), name)


def test_star_pattern_matches_one_segment():
   assert P._is_free(('rigs', 'blob', 'marker_colors'))
   assert P._is_free(('rigs', 'humanoid', 'anchor_z'))
   assert not P._is_free(('rigs', 'marker_colors'))
   assert not P._is_free(('rigs', 'blob', 'anchors'))


def test_dotted_rig_name_passes_like_before():
   """rig 이름에 점이 들어도(rigs.a.b) 옛날처럼 지나간다 — 자리를 글로 쪼개던 퇴행 못 박기."""
   rig = {"method": "marker", "marker_colors": {"head": "#FF0000"}, "anchor_z": {"head": 1}}
   P.reject_unknown({"rigs": {"a.b": rig}}, "시험")
   assert P._is_free(("rigs", "a.b", "marker_colors"))


def test_dotted_rig_name_still_rejects_dict_anchors():
   with pytest.raises(ProfileError, match="이름 목록"):
      P.reject_unknown({"rigs": {"a.b": {"anchors": {"x": 1}}}}, "시험")


def test_rig_free_maps_take_any_key():
   raw = {"rigs": {"blob": {"method": "anchor", "anchors": ["a"],
                            "marker_colors": {"a": "#FF00FF"}, "anchor_z": {"a": {"south": 10, "default": 0}}}}}
   P.reject_unknown(raw, "시험")


def test_scalar_spot_with_dict_fails():
   with pytest.raises(ProfileError, match="값 하나 자리"):
      P.reject_unknown({"palette": {"ramps_file": {"a": 1}}}, "시험")


def test_dict_under_unknown_schema_fails():
   # 예전엔 빈 꼴 사전이 「자유」 로 읽혀 rig 안 아무 사전이나 지나갔다.
   with pytest.raises(ProfileError, match="이름 목록 자리"):
      P.reject_unknown({"rigs": {"blob": {"anchors": {"oops": 1}}}}, "시험")
   with pytest.raises(ProfileError, match="rigs.blob.layer_order 는 이름 목록 자리"):
      P.reject_unknown({"rigs": {"blob": {"layer_order": {"body": 1}}}}, "시험")
   with pytest.raises(ProfileError, match="모르는 항목"):
      P.reject_unknown({"rigs": {"blob": {"parts": {"oops": 1}}}}, "시험")


def test_old_free_spots_kept():
   P.reject_unknown({"sprite": {"mirror_east_from_west": True}, "style": {"materials": {"a": "metal"}}}, "시험")
   P.reject_unknown({"check": {"warn": {"color_cap": {"table": {16: 8}}}}}, "시험")
