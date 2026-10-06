"""템플릿 스키마 · 셈 (설계 8-6 앞 줄 · 9-4 끝 fixed · must)."""

import copy
import json
from pathlib import Path

import pytest

from arttool.errors import UsageError
from arttool.template import TemplateError, kinds, schema
from arttool.template.run import build, list_templates

FIRST_TWELVE = {
   "char_small", "char_parts", "bg_screen", "ui9_panel", "icon_set", "tile_base",
   "palette_ramp", "cycle_char", "fx_ring_burst", "fx_sparkle", "fx_dust", "motion_guide",
   "building", "machine", "screen_piece", "prop_small", "char_blob", "fx_swirl",
}


def ring_burst() -> dict:
   data = schema.load("fx_ring_burst")
   data.pop("_source")
   return data


def write(tmp_path: Path, data: dict, name: str = "t.json") -> str:
   path = tmp_path / name
   path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
   return str(path)


def test_first_twelve_all_load_and_list():
   listed = list_templates()
   assert {row["name"] for row in listed["templates"]} == FIRST_TWELVE
   assert list_templates("effect")["count"] == 4
   assert list_templates("prop")["count"] == 3
   # 파일 이름 = name 칸 (이름으로 찾기가 맞물리게)
   for row in listed["templates"]:
      assert Path(schema.find(row["name"])).stem == row["name"]


def test_list_rejects_unknown_kind():
   with pytest.raises(UsageError):
      list_templates("monster")


@pytest.mark.parametrize("spot", ["top", "values", "shape"])
def test_unknown_field_rejected(tmp_path, spot):
   data = ring_burst()
   if spot == "top":
      data["colour"] = 1
   elif spot == "values":
      data["values"]["speed"] = 3
   else:
      data["frames"][0]["draw"][0]["radius"] = 2
   with pytest.raises(TemplateError, match="모르는 칸"):
      schema.load(write(tmp_path, data))


def test_unknown_kind_rejected(tmp_path):
   data = ring_burst()
   data["kind"] = "explosion"
   with pytest.raises(TemplateError, match="kind"):
      schema.load(write(tmp_path, data))


def test_size_outside_list_is_usage_error():
   with pytest.raises(UsageError, match="받는 크기"):
      build("fx_ring_burst", "32x32", None, None)
   with pytest.raises(UsageError, match="WxH"):
      build("fx_ring_burst", "16by16", None, None)


def test_name_with_path_chars_rejected():
   with pytest.raises(UsageError):
      schema.find("../profiles/topdown_action")


def test_fixed_path_must_have_template_value(tmp_path):
   data = ring_burst()
   data["fixed"] = ["style.light"]          # 템플릿 check 에 값이 없다
   with pytest.raises(TemplateError, match="값이 없다"):
      schema.load(write(tmp_path, data))


def test_fixed_path_must_be_profile_field(tmp_path):
   data = ring_burst()
   data["fixed"] = ["frames"]               # 템플릿 대조 값이지 프로필 칸이 아니다
   with pytest.raises(TemplateError, match="프로필에 없는"):
      schema.load(write(tmp_path, data))


def test_check_profile_part_is_validated(tmp_path):
   data = ring_burst()
   data["check"]["style"]["outline"] = "thick"
   with pytest.raises(TemplateError, match="outline"):
      schema.load(write(tmp_path, data))


def test_must_empty_keeps_kind_default_and_only_adds(tmp_path):
   data = ring_burst()
   data["must"] = []
   assert schema.effective_must(data) == ["canvas", "alpha", "scale"]
   data["must"] = ["palette"]
   assert schema.effective_must(data) == ["canvas", "alpha", "scale", "palette"]
   data["must"] = ["colors"]
   with pytest.raises(TemplateError, match="must"):
      schema.load(write(tmp_path, data))


def test_must_defaults_by_kind():
   assert build("char_small", "16x16", None, None)[0]["must"] == ["canvas", "alpha", "scale", "palette"]
   assert build("motion_guide", "32x32", "hair", None)[0]["must"] == ["canvas", "alpha", "scale"]
   assert build("palette_ramp", "16x16", None, None)[0]["must"] == []


def test_effect_check_frames_must_match_frame_list(tmp_path):
   data = ring_burst()
   data["check"]["frames"] = 6
   with pytest.raises(TemplateError, match="check.frames"):
      schema.load(write(tmp_path, data))


def test_palette_kind_rejects_layers(tmp_path):
   data = schema.load("palette_ramp")
   data.pop("_source")
   data["layers"] = [{"name": "fx", "kind": "fx"}]
   with pytest.raises(TemplateError, match="layers"):
      schema.load(write(tmp_path, data))


def test_char_small_32_lines():
   """32×32 tall : 등신 3 · 머리 9줄 · 눈 카드 3×3 · 가랑이(턱 아래 몸의 0.33) · 무릎 아래 1/4 를 칸으로 셈."""
   lines = build("char_small", "32x32", "tall", None)[0]["lines"]
   assert lines["top_y"] == 2
   assert lines["baseline_y"] == 29
   assert lines["head"] == [11, 2, 21, 11]          # 머리 10 × 9, 가운데 맞춤
   assert lines["chin_y"] == 10
   assert lines["eye_line_y"] == 6                  # 머리 위(2) ~ 턱(10) 가운데
   assert lines["eye_box_l"] == [12, 5, 15, 8]
   assert lines["eye_box_r"] == [17, 5, 20, 8]
   assert lines["mouth"] == [15, 9, 17, 10]
   assert lines["crotch_y"] == 17                   # 턱 다음 줄 11 + 턱 아래 19줄 × 0.33
   assert lines["knee_y"] == 22                     # 29 − 28 / 4


def test_char_small_16_lines_and_note():
   shown = build("char_small", "16x16", "tall", None)[0]
   lines = shown["lines"]
   assert (lines["top_y"], lines["baseline_y"], lines["head_h"], lines["head_w"]) == (1, 14, 7, 8)
   assert lines["eye_box_l"] == [6, 4, 7, 6]        # 눈 카드 1 × 2
   assert shown["values"]["heads"] == 2
   assert shown["values"]["note"].startswith("16px")


def test_char_small_default_preset_by_size():
   """64 아래 · 세로로 긴 캔버스는 sd(2등신 안팎), 64 는 tall (실물 #25 · 메인 검토 : 32 도 2~2.5등신)."""
   want = {"8x8": "sd", "16x16": "sd", "24x24": "sd", "32x32": "sd", "48x48": "sd", "64x64": "tall",
           "48x64": "sd", "64x80": "sd", "72x88": "sd"}
   for size, preset in want.items():
      assert build("char_small", size, None, None)[0]["preset"] == preset, size
   assert build("char_parts", "48x64", None, None)[0]["preset"] == "sd"
   assert build("char_parts", "32", None, None)[0]["preset"] == "sd"


def test_char_small_32_sd_reads_as_small_sd():
   """32 sd : 머리 폭 14~16 · 높이 13~15, 몸통 폭 10~12, 다리 3~5줄, 눈 2×2 · 사이 3~4 (48×64 sd 를 줄인 인상)."""
   lines = build("char_small", "32", None, None)[0]["lines"]
   hx0, hy0, hx1, hy1 = lines["head"]
   assert 14 <= hx1 - hx0 <= 16 and 13 <= hy1 - hy0 <= 15
   assert 10 <= lines["torso"][2] - lines["torso"][0] <= 12
   assert 3 <= lines["baseline_y"] + 1 - lines["crotch_y"] <= 5
   ex0, ey0, ex1, ey1 = lines["eye_box_l"]
   assert (ex1 - ex0, ey1 - ey0) in ((2, 2), (1, 2))
   assert 3 <= lines["eye_box_r"][0] - ex1 <= 4
   # 고르면 고른 것
   assert build("char_small", "48x64", "tall", None)[0]["preset"] == "tall"


def test_char_small_sd_48x64_matches_real_measure():
   """sd 48×64 : 실물 sd 캐릭터 (머리 y8~39 · 눈 y31~33 · 바닥 58~59 · 몸통 폭 26 · 가랑이 약 52) 에 ±1px."""
   shown = build("char_small", "48x64", "sd", None)[0]
   lines = shown["lines"]
   assert lines["top_y"] == 8 and lines["baseline_y"] == 59
   assert lines["head"] == [5, 8, 43, 39]           # 머리 38 × 31 (몸 52 ÷ 1.7)
   assert lines["eye_box_l"][1:4:2] == [31, 34]     # 눈 줄은 머리의 0.8 자리
   assert lines["torso"][2] - lines["torso"][0] == 26
   assert lines["crotch_y"] == 52
   assert lines["cheeks"] and all(c[1] == lines["eye_box_l"][3] + 1 for c in lines["cheeks"])
   assert "super-deformed" in shown["prompt"]


def test_size_table_exact_key_wins():
   table = {"16": 2, "48x64": 1.7}
   assert kinds.pick(table, (48, 64)) == 1.7
   assert kinds.pick(table, (64, 48)) == 2
   assert kinds.pick(table, (48, 48)) == 2
   assert not kinds.is_table({"48x64": 1})          # 숫자 열쇠가 하나는 있어야 한다


def test_default_preset_must_name_presets(tmp_path):
   data = schema.load("char_small")
   data.pop("_source")
   data["default_preset"] = {"8": "sd", "32": "giant"}
   with pytest.raises(TemplateError, match="giant"):
      schema.load(write(tmp_path, data))
   data["default_preset"] = 3
   with pytest.raises(TemplateError, match="default_preset"):
      schema.load(write(tmp_path, data))


def test_size_table_pick():
   table = {"8": 1, "16": 2, "32": 3}
   assert kinds.pick(table, (24, 24)) == 2
   assert kinds.pick(table, (4, 4)) == 1
   assert kinds.pick(table, (64, 64)) == 3
   assert kinds.pick(5, (8, 8)) == 5


def test_preset_rules():
   with pytest.raises(UsageError, match="없는 프리셋"):
      build("cycle_char", "32x32", "swim", None)
   with pytest.raises(UsageError, match="프리셋이 없다"):
      build("tile_base", "32x32", "walk", None)
   # 안 고르면 첫 프리셋
   assert build("cycle_char", "32x32", None, None)[0]["preset"] == "walk"


def test_cycle_bob_length_checked(tmp_path):
   data = schema.load("cycle_char")
   data.pop("_source")
   data["presets"]["walk"]["bob"] = [0, 1]
   with pytest.raises(TemplateError, match="bob"):
      schema.load(write(tmp_path, data))


def test_cycle_presets_frames_and_ms():
   walk = build("cycle_char", "32x32", "walk", None)[0]
   assert (walk["frames"], walk["frame_ms"]) == (8, 100)
   run = build("cycle_char", "32x32", "run", None)[0]
   assert (run["frames"], run["frame_ms"]) == (8, 80)
   attack = build("cycle_char", "32x32", "attack", None)[0]
   assert attack["frames"] == 7 and attack["values"]["phases"].count("attack") == 3
   idle = build("cycle_char", "16x16", "idle", None)[0]
   assert idle["values"]["order"] == [1, 2, 3, 2]
   assert walk["lines"]["head_top_y"] == [walk["lines"]["top_y"] + b for b in walk["lines"]["bob"]]


def test_effect_preset_overrides_sizes_and_check():
   big = build("fx_sparkle", "17x17", "big", None)[0]
   assert big["frames"] == 7 and big["check"]["check"]["max_colors"] == 3 and big["check"]["colors"] == 3
   small = build("fx_sparkle", "16x16", "small", None)[0]
   assert small["frames"] == 5 and small["check"]["check"]["max_colors"] == 1


def test_motion_points_lag_and_amplitude():
   """점 i 는 점 0 이 밟은 길을 i × delay 장 늦게 밟는다 · 진폭 밖으로 안 나간다."""
   for preset, frames, points in (("hair", 6, 4), ("aura", 4, 4), ("cloth", 6, 3)):
      shown = build("motion_guide", "32x32", preset, None)[0]
      lines, values = shown["lines"], shown["values"]
      assert shown["frames"] == frames and len(lines["points"]) == frames
      assert all(len(row) == points for row in lines["points"])
      sideways = values["path"] == "side"
      axis = 0 if sideways else 1
      moves = [[row[i][axis] - lines["bases"][i][axis] for row in lines["points"]] for i in range(points)]
      for i in range(points):
         assert all(abs(m) <= values["amp"] for m in moves[i])
         lag = i * values["delay"]
         assert moves[i] == [moves[0][(f - lag) % frames] for f in range(frames)]
         # 다른 축은 안 움직인다
         other = 1 - axis
         assert {row[i][other] for row in lines["points"]} == {lines["bases"][i][other]}
      assert max(moves[0]) == values["amp"] and min(moves[0]) == -values["amp"]


def test_prompt_unknown_blank_rejected(tmp_path):
   data = ring_burst()
   data["prompt"] = "ring {speed}"
   with pytest.raises(TemplateError, match="speed"):
      build(write(tmp_path, data), None, None, None)


def test_prompt_drops_palette_clause_without_profile():
   prompt = build("char_small", "32x32", None, None)[0]["prompt"]
   assert "{" not in prompt and "palette" not in prompt
   # 외곽선 방식이 unset 이면 그 마디도 뺀다
   assert "outline" not in prompt
   assert "light from top-left" in prompt


def test_template_copy_not_mutated():
   before = copy.deepcopy(schema.load("cycle_char"))
   build("cycle_char", "32x32", "run", None)
   assert schema.load("cycle_char") == before
