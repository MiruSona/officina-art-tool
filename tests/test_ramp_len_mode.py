"""3판-나 소단계 8 — 램프 파일 `ramp_len_mode: max` (길이 다른 램프 받기).

저장소 `palettes/` 원본은 절대 고쳐 쓰지 않는다 — 늘 tmp_path 에 복사해 쓴다.
"""
import json
import shutil

import pytest

from arttool import palette
from arttool.draw.canvas import pick
from arttool.errors import ArtToolError
from arttool.profile import tool_home


def _copy_sample(tmp_path, **changes):
   """lpc_cloth.json 을 tmp_path 로 복사하고, 칸을 바꿀 게 있으면 바꿔 쓴다."""
   src = tool_home() / "palettes" / "lpc_cloth.json"
   dst = tmp_path / "lpc_cloth.json"
   shutil.copyfile(src, dst)
   if changes:
      data = json.loads(dst.read_text(encoding="utf-8-sig"))
      data.update(changes)
      dst.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
   return dst


def _mixed(tmp_path, ramp_len=6, mode="max", ramps=None):
   ramps = ramps or {
      "one": ["#808080"],
      "three": ["#100000", "#200000", "#300000"],
      "six": ["#000010", "#000020", "#000030", "#000040", "#000050", "#000060"],
   }
   data = {"version": 1, "name": "mixed", "ramp_len": ramp_len, "outline": "#000000", "ramps": ramps}
   if mode is not None:
      data["ramp_len_mode"] = mode
   file = tmp_path / "mixed.json"
   file.write_text(json.dumps(data), encoding="utf-8")
   return file


def _pixels(lut):
   return [[tuple(int(v) for v in px) for px in row] for row in lut]


# --- 옛 동작 그대로 -----------------------------------------------------------------

def test_fixed_default_has_no_new_fields(tmp_path):
   ramps = palette.load_ramps(_copy_sample(tmp_path))
   assert ramps.mode == "fixed"
   assert "rampLens" not in palette.ramp_asset_json(ramps)
   out = palette.save_ramps(tmp_path / "back.json", ramps, {"comment": "c"})
   data = json.loads(out.read_text(encoding="utf-8"))
   # 칸 차례까지 옛 꼴 그대로 — ramp_len_mode 칸이 생기지 않는다.
   assert list(data) == ["version", "name", "ramp_len", "outline", "ramps", "comment"]


def test_max_on_same_length_file_gives_same_outputs(tmp_path):
   old = palette.load_ramps(_copy_sample(tmp_path))
   (tmp_path / "m").mkdir()
   new = palette.load_ramps(_copy_sample(tmp_path / "m", ramp_len_mode="max"))
   names = old.names()
   assert palette.build_lut(old, names).tobytes() == palette.build_lut(new, names).tobytes()
   asset_new = palette.ramp_asset_json(new)
   assert asset_new.pop("rampLens") == {n: 6 for n in names}
   assert asset_new == palette.ramp_asset_json(old)


def test_fixed_file_still_rejects_mixed_lengths(tmp_path):
   with pytest.raises(ArtToolError, match="램프 one 의 길이가 1 다. 6 이어야 한다"):
      palette.load_ramps(_mixed(tmp_path, mode=None))
   with pytest.raises(ArtToolError, match="서로 다르다"):
      palette.load_ramps(_mixed(tmp_path, ramp_len=0, mode="fixed"))


# --- max ------------------------------------------------------------------------------

def test_max_loads_mixed_lengths(tmp_path):
   ramps = palette.load_ramps(_mixed(tmp_path))
   assert ramps.mode == "max" and ramps.ramp_len == 6
   assert ramps.lengths() == {"one": 1, "three": 3, "six": 6}


def test_max_without_ramp_len_takes_longest(tmp_path):
   assert palette.load_ramps(_mixed(tmp_path, ramp_len=0)).ramp_len == 6


def test_max_lut_pads_right_with_last_color(tmp_path):
   ramps = palette.load_ramps(_mixed(tmp_path))
   rows = _pixels(palette.build_lut(ramps, ["one", "three", "six"]))
   assert len(rows[0]) == 6
   assert rows[0] == [(0x80, 0x80, 0x80, 255)] * 6
   assert rows[1] == [(0x10, 0, 0, 255), (0x20, 0, 0, 255)] + [(0x30, 0, 0, 255)] * 4
   assert rows[2][5] == (0, 0, 0x60, 255)


def test_max_asset_keeps_ramplen_as_lut_width(tmp_path):
   asset = palette.ramp_asset_json(palette.load_ramps(_mixed(tmp_path)))
   assert asset["rampLen"] == 6
   assert asset["rampLens"] == {"one": 1, "three": 3, "six": 6}
   assert [len(r["colors"]) for r in asset["ramps"]] == [1, 3, 6]


def test_max_save_round_trip(tmp_path):
   ramps = palette.load_ramps(_mixed(tmp_path))
   out = palette.save_ramps(tmp_path / "back.json", ramps)
   data = json.loads(out.read_text(encoding="utf-8"))
   assert data["ramp_len_mode"] == "max"
   back = palette.load_ramps(out)
   assert back.ramps == ramps.ramps and back.mode == "max" and back.ramp_len == 6


def test_max_save_checks_lengths(tmp_path):
   ramps = palette.load_ramps(_mixed(tmp_path))
   ramps.ramp_len = 7
   with pytest.raises(ArtToolError, match="가장 긴 램프"):
      palette.save_ramps(tmp_path / "bad.json", ramps)


@pytest.mark.parametrize("ramp_len, ramps, message", [
   (3, None, "1 ~ ramp_len 3"),
   (8, None, "가장 긴 램프가 6"),
   (6, {"empty": [], "six": ["#000000"] * 6}, "empty=0"),
])
def test_max_rejects_bad_lengths(tmp_path, ramp_len, ramps, message):
   with pytest.raises(ArtToolError, match=message):
      palette.load_ramps(_mixed(tmp_path, ramp_len=ramp_len, ramps=ramps))


def test_unknown_mode_rejected(tmp_path):
   with pytest.raises(ArtToolError, match="ramp_len_mode"):
      palette.load_ramps(_mixed(tmp_path, mode="longest"))


def test_save_rejects_mode_as_extra(tmp_path):
   ramps = palette.load_ramps(_copy_sample(tmp_path))
   with pytest.raises(ArtToolError, match="본 칸과 겹친다"):
      palette.save_ramps(tmp_path / "x.json", ramps, {"ramp_len_mode": "max"})


def test_pick_on_short_ramp_refuses_clearly(tmp_path):
   ramps = palette.load_ramps(_mixed(tmp_path))
   assert pick(ramps, "three", -1) == "#300000"
   with pytest.raises(ArtToolError, match="three 은 3 칸"):
      pick(ramps, "three", 5)


def test_max_asset_ramplens_follow_names_order(tmp_path):
   """names 로 고른 부분집합 — rampLens 의 차례와 칸이 names 를 따른다."""
   asset = palette.ramp_asset_json(palette.load_ramps(_mixed(tmp_path)), ["six", "one"])
   assert list(asset["rampLens"].items()) == [("six", 6), ("one", 1)]
   assert [r["name"] for r in asset["ramps"]] == ["six", "one"]


def test_max_selout_darker_on_short_ramp(tmp_path):
   """max 파일(3칸 · 6칸 섞음) — selout 의 `_darker` 는 짧은 램프 안에서 내려가고, 맨 아래면 outline 색을 쓴다."""
   from arttool.draw.outline import _darker
   ramps = palette.load_ramps(_mixed(tmp_path))
   assert _darker((0x30, 0, 0), 1, ramps) == ((0x20, 0, 0), False)
   assert _darker((0x30, 0, 0), 2, ramps) == ((0x10, 0, 0), False)
   assert _darker((0x20, 0, 0), 2, ramps) == ((0x10, 0, 0), False)      # 칸 밖으로 안 나간다 — 맨 아래에서 멈춘다
   assert _darker((0x10, 0, 0), 1, ramps) == ((0, 0, 0), True)          # 맨 아래 → outline
   assert _darker((0, 0, 0x60), 2, ramps) == ((0, 0, 0x40), False)
   assert _darker((0x80, 0x80, 0x80), 1, ramps) == ((0, 0, 0), True)    # 한 칸 램프


# --- max 의 ramp_shape 단 수 판정 -------------------------------------------------------

SHAPE_CFG = {"steps": [4, 6], "hue_min": 5, "hue_max": 30}
WARM3 = [(40, 20, 60), (120, 60, 70), (210, 170, 120)]


def test_judge_max_drops_only_too_few_steps():
   from arttool.checks import ramp as ramp_check
   short = ramp_check.measure_ramp(WARM3)
   fixed = ramp_check.judge_ramp(short, SHAPE_CFG)
   assert any(w.startswith("단 수 3") for w in fixed)
   # fixed 는 이름을 줘도 안 줘도 한 글자도 같다.
   assert ramp_check.judge_ramp(short, SHAPE_CFG, None, "fixed") == fixed
   assert ramp_check.judge_ramp(short, SHAPE_CFG, None, "max") == [w for w in fixed if not w.startswith("단 수")]
   # 너무 많은 쪽은 max 에서도 낸다.
   long = ramp_check.measure_ramp([(10 + 30 * i, 5 + 25 * i, 40 + 20 * i) for i in range(8)])
   assert any(w.startswith("단 수 8") for w in ramp_check.judge_ramp(long, SHAPE_CFG, None, "max"))
   assert ramp_check.judge_ramp(long, SHAPE_CFG, None, "max") == ramp_check.judge_ramp(long, SHAPE_CFG)


@pytest.mark.parametrize("mode", ["fixed", "max"])
def test_check_and_palette_check_share_max_rule(tmp_path, monkeypatch, mode):
   """check(ramp_items) 와 palette check 가 같은 판정을 지난다 — max 면 「단 수 3」 이 없고 fixed 면 있다."""
   import helpers
   from arttool import check, cli, jsonio
   monkeypatch.chdir(tmp_path)
   prof = helpers.tiny_profile(tmp_path)
   hexes = ["#%02x%02x%02x" % c for c in WARM3]
   (tmp_path / "r.json").write_bytes(_mixed(tmp_path, ramp_len=3, mode=mode, ramps={"three": hexes}).read_bytes())
   items = check.ramp_items(prof, palette.load_ramps(tmp_path / "r.json"))
   whys = [w for item in items for w in item["why"]]
   assert cli.main(["palette", "check", "--ramps", "r.json", "--report", "p.json"]) == 0
   lines = jsonio.read_json(tmp_path / "p.json")["palette"]["r.json"]["ramp_shape"]
   assert any("단 수 3" in w for w in whys) == (mode == "fixed")
   assert any("단 수 3" in line for line in lines) == (mode == "fixed")
