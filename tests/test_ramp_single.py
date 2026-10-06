"""3판 설계 2-5 (가) — 끝 되풀이 접기 · 한 색 램프 알림 · style extract 의 `ramp_info`."""
import json

import pytest

import helpers
from arttool import check, cli, image, jsonio
from arttool.checks import ramp as ramp_check
from arttool.style import extract

ONCE = {"check.warn.ramp_shape.report": "once"}
CFG = {"steps": [4, 6], "hue_min": 5, "hue_max": 30}


def loose_dir(tmp_path, count=2):
   out = tmp_path / "loose"
   out.mkdir(parents=True, exist_ok=True)
   for index in range(count):
      image.save(out / f"icon_{index}.png", helpers.blob(8, 8))
   return out


def add_single_ramp(prof, tmp_path, monkeypatch, name="eye"):
   """프로필 램프 파일의 복사본에 한 색 램프 한 줄을 더하고 프로필이 그 복사본을 보게 한다.

   원본(`palettes/lpc_cloth.json`)은 저장소 파일이라 절대 고치지 않는다.
   """
   data = jsonio.read_json(prof.ramps_path())
   path = tmp_path / "lpc_cloth.json"
   monkeypatch.setattr(prof, "ramps_path", lambda *a, **k: path)
   first = next(iter(data["ramps"].values()))
   data["ramps"][name] = [first[len(first) // 2]] * len(first)
   path.write_text(json.dumps(data), encoding="utf-8")
   return path


def single_info(report):
   return [line for line in report.get("info", []) if line["rule"] == "ramp_shape.single"]


def shape_ramps(report):
   return [item["ramp"] for w in report["warnings"] if w["rule"] == "ramp_shape" for item in w["items"]]


def test_end_repeat_is_folded_into_real_steps():
   """밝은 끝 색 되풀이는 채움 — 4단 + 채운 2칸이면 단 수 4 로 잰다."""
   colors = [(40, 20, 60), (80, 40, 90), (140, 90, 120), (200, 160, 140), (200, 160, 140), (200, 160, 140)]
   m = ramp_check.measure_ramp(colors)
   assert (m["steps"], m["padded"]) == (4, 2)
   assert not any("단 수" in why for why in ramp_check.judge_ramp(m, CFG))


def test_single_color_ramp_has_no_shape_warning():
   m = ramp_check.measure_ramp([(120, 60, 60)] * 6)
   assert ramp_check.is_single(m)
   assert ramp_check.judge_ramp(m, CFG) == []
   assert ramp_check.judge_ramp(m, CFG, "gem") == []


def test_each_mode_moves_single_ramp_to_info(tmp_path, monkeypatch):
   prof = helpers.tiny_profile(tmp_path)
   add_single_ramp(prof, tmp_path, monkeypatch)
   report = check.run(prof, loose_dir(tmp_path))
   assert "eye" not in shape_ramps(report)
   assert single_info(report)[0]["items"] == ["eye"]


def test_once_mode_lists_single_in_palette_block(tmp_path, monkeypatch):
   prof = helpers.tiny_profile(tmp_path, **ONCE)
   add_single_ramp(prof, tmp_path, monkeypatch)
   report = check.run(prof, loose_dir(tmp_path))
   entry = next(iter(report["palette"].values()))
   assert entry["single"] == ["eye"]
   assert not any(line.startswith("eye:") for line in entry["ramp_shape"])


def test_old_ramp_file_reports_have_no_new_fields(tmp_path):
   """한 색 램프가 없는 옛 램프 파일 — 그림 보고 · palette 칸 · palette check 어디에도 새 칸이 안 붙는다."""
   src = loose_dir(tmp_path)
   each = check.run(helpers.tiny_profile(tmp_path), src)
   assert single_info(each) == []
   once = check.run(helpers.tiny_profile(tmp_path, **ONCE), src)
   assert all(set(entry) == {"ramp_shape", "used_by"} for entry in once["palette"].values())


def test_palette_check_shows_single(tmp_path, monkeypatch):
   monkeypatch.chdir(tmp_path)
   prof = helpers.tiny_profile(tmp_path)
   (tmp_path / "r.json").write_bytes(add_single_ramp(prof, tmp_path, monkeypatch).read_bytes())
   assert cli.main(["palette", "check", "--ramps", "r.json", "--report", "p.json"]) == 0
   assert jsonio.read_json(tmp_path / "p.json")["palette"]["r.json"]["single"] == ["eye"]


def test_extract_ramp_info_only_for_padded_ramps():
   rows = [
      {"name": "skin", "colors": [0x281438, 0x502850, 0x8C5A78, 0xC8A08C]},
      {"name": "cloth", "colors": [0x281438, 0x502850, 0x8C5A78, 0x8C5A78]},
      {"name": "eye", "colors": [0x783C3C] * 4},
   ]
   assert extract.ramp_info(rows) == {
      "cloth": {"steps": 3, "kind": "padded"},
      "eye": {"steps": 1, "kind": "single"},
   }
   assert extract.ramp_info(rows[:1]) == {}


def test_extract_ramp_info_counts_middle_repeat_as_padded():
   """끝 색 되풀이만이 아니다 — 가운데 이어진 같은 색(`[A, B, B, A]`)도 접어 세어 padded 로 적는다."""
   rows = [{"name": "mid", "colors": [0x281438, 0x8C5A78, 0x8C5A78, 0x281438]}]
   assert extract.ramp_info(rows) == {"mid": {"steps": 3, "kind": "padded"}}


@pytest.mark.parametrize("changes", [{}, ONCE], ids=["each", "once"])
def test_single_ramp_in_known_is_stale(tmp_path, monkeypatch, changes):
   """한 색 램프는 ramp_shape 로 안 걸린다 — `--known` 에 적어 두면 아무 경고와도 안 맞아 known_stale 로 뜬다."""
   prof = helpers.tiny_profile(tmp_path, **changes)
   add_single_ramp(prof, tmp_path, monkeypatch)
   known = tmp_path / "known.json"
   known.write_text(json.dumps([{"rule": "ramp_shape", "where": "eye"}]), encoding="utf-8")
   report = check.run(prof, loose_dir(tmp_path), known=[str(known)])
   stale = [i for i in report.get("info", []) if i["rule"] == "check.known_stale"]
   assert len(stale) == 1 and len(stale[0]["items"]) == 1
   assert "eye" in json.dumps(stale[0], ensure_ascii=False)
