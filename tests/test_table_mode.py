"""3판-가 소단계 3 — 색 한도 표 table_mode · profile show 줄(한도 · 외곽선) 시험 (설계 2-2 · 2-3 · 시험 목록 5 · 6)."""
import copy
import json

import pytest
import yaml

from arttool import check, cli, image
from arttool import profile as P
from arttool.errors import ProfileError, UsageError

DEFAULT_KEYS = (8, 16, 32, 48, 64, 128, 256)


def _prof(tmp_path, cap: dict | None = None, **extra):
   data = {"name": "t", **extra}
   if cap is not None:
      data["check"] = {"warn": {"color_cap": cap}}
   path = tmp_path / "t.yaml"
   path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
   return P.load_profile(str(path))


def _tpl(layer: dict) -> dict:
   return {"layer": layer, "profile_applied": False, "fixed": [], "path": "tpl.json"}


def _cap_layer(cap: dict) -> dict:
   return {"check": {"warn": {"color_cap": cap}}}


# ---- 옛 뜻 그대로 ----

def test_old_profile_without_table_is_unchanged(tmp_path):
   prof = _prof(tmp_path)
   assert "table_mode" not in prof.as_dict()["check"]["warn"]["color_cap"]
   assert prof.color_cap_table()[48] == 44
   assert prof.cap_left is None and P.cap_left_line(prof) is None


def test_merge_keeps_old_meaning_48_is_44(tmp_path):
   prof = _prof(tmp_path, {"table": {128: 40, 256: 60}})
   table = prof.color_cap_table()
   assert table[48] == 44 and table[128] == 40 and table[256] == 60
   assert prof.cap_left == (8, 16, 32, 48, 64)
   # 옛 뜻 : 겹친 결과가 deep_merge 그대로다
   assert table == {int(k): int(v) for k, v in P.deep_merge(P.DEFAULTS, {"check": {"warn": {"color_cap": {"table": {128: 40, 256: 60}}}}})["check"]["warn"]["color_cap"]["table"].items()}


def test_explicit_merge_equals_no_mode(tmp_path):
   a = _prof(tmp_path, {"table": {128: 40}}).color_cap_table()
   b = _prof(tmp_path, {"table": {128: 40}, "table_mode": "merge"}).color_cap_table()
   assert a == b


# ---- replace ----

def test_replace_uses_only_profile_table(tmp_path):
   prof = _prof(tmp_path, {"table": {128: 48, 256: 64}, "table_mode": "replace"})
   assert prof.color_cap_table() == {128: 48, 256: 64}
   assert prof.cap_left == () and P.cap_left_line(prof) is None


def test_replace_48px_gets_smallest_slot(tmp_path):
   arr = image.new(48, 48)
   for i in range(46):
      arr[i, 0:48] = (i * 5, 40, 90, 255)                  # 48px 에 46색
   pics = tmp_path / "pics"
   pics.mkdir()
   image.save(pics / "a.png", arr)
   merged = check.run(_prof(tmp_path, {"table": {128: 40}}), pics, no_ramps=True)
   cap = next(w for w in merged["warnings"] if w["rule"] == "color_cap")["items"][0]
   assert cap["cap"] == 44                                  # merge : 기본 48 칸
   assert any(i["rule"] == "color_cap.table_merged" for i in merged.get("info", []))
   replaced = check.run(_prof(tmp_path, {"table": {128: 30, 256: 64}, "table_mode": "replace"}), pics, no_ramps=True)
   cap = next(w for w in replaced["warnings"] if w["rule"] == "color_cap")["items"][0]
   assert cap["cap"] == 30                                  # replace : 가장 작은 칸
   assert not any(i["rule"] == "color_cap.table_merged" for i in replaced.get("info", []))


def test_old_profile_check_report_has_no_new_info(tmp_path):
   arr = image.new(16, 16)
   arr[2:14, 2:14] = (90, 120, 160, 255)
   pics = tmp_path / "pics"
   pics.mkdir()
   image.save(pics / "a.png", arr)
   report = check.run(_prof(tmp_path), pics, no_ramps=True)
   assert not any(i["rule"].startswith("color_cap.") for i in report.get("info", []))


# ---- 틀린 꼴 ----

def test_unknown_table_mode_fails(tmp_path):
   with pytest.raises(ProfileError, match="table_mode"):
      _prof(tmp_path, {"table": {128: 40}, "table_mode": "swap"})


def test_replace_without_table_fails(tmp_path):
   with pytest.raises(ProfileError, match="replace"):
      _prof(tmp_path, {"table_mode": "replace"})


def test_table_mode_typo_key_still_rejected(tmp_path):
   with pytest.raises(ProfileError, match="모르는 항목"):
      _prof(tmp_path, {"table": {128: 40}, "table_mod": "replace"})


# ---- 템플릿 겹 ----

def test_template_replace_wins_last(tmp_path):
   prof = _prof(tmp_path, {"table": {128: 40}})
   out, _ = check.apply_template(prof, _tpl(_cap_layer({"table": {"64": 20}, "table_mode": "replace"})))
   assert out.color_cap_table() == {64: 20} and out.cap_left == ()


def test_template_merge_over_profile_replace(tmp_path):
   prof = _prof(tmp_path, {"table": {128: 40}, "table_mode": "replace"})
   out, _ = check.apply_template(prof, _tpl(_cap_layer({"table": {"64": 20}})))
   assert out.color_cap_table() == {64: 20, 128: 40} and out.cap_left == ()


def test_template_table_on_old_profile_counts_left(tmp_path):
   out, _ = check.apply_template(_prof(tmp_path), _tpl(_cap_layer({"table": {"48": 30}})))
   assert out.color_cap_table()[48] == 30 and 48 not in out.cap_left and 8 in out.cap_left


def test_template_bad_mode_is_usage_error(tmp_path):
   with pytest.raises(UsageError):
      check.apply_template(_prof(tmp_path), _tpl(_cap_layer({"table": {"48": 30}, "table_mode": "x"})))


def test_template_without_cap_keeps_profile(tmp_path):
   prof = _prof(tmp_path, {"table": {128: 40}})
   out, _ = check.apply_template(prof, _tpl({"check": {"warn": {"isolated": {"max_ratio": 0.1}}}}))
   assert out.color_cap_table() == prof.color_cap_table() and out.cap_left == prof.cap_left


# ---- profile show 줄 ----

def test_show_lines_merge_notice_and_outline(tmp_path):
   prof = _prof(tmp_path, {"table": {128: 40, 256: 60}}, style={"outline": "selout"})
   prof.data["check"]["warn"]["outline"]["accept"] = ["solid", "selout+light"]
   lines = P.show_lines(prof)
   assert lines[1] == "색 한도 표 : 기본 표 8·16·32·48·64 가 겹쳐 남았다 (통째로 쓰려면 table_mode: replace)"
   assert lines[-1] == "외곽선 : selout (+ 받기 solid, selout+light)"


def test_show_lines_replace_has_no_notice(tmp_path):
   prof = _prof(tmp_path, {"table": {128: 48, 256: 64}, "table_mode": "replace"})
   lines = P.show_lines(prof)
   assert lines[0] == "색 한도 표 : 128→48 · 256→64 (replace)"
   assert len(lines) == 2 and lines[1].startswith("외곽선 : ")


def test_profile_show_only_adds_show_lines(tmp_path, capsys):
   path = tmp_path / "t.yaml"
   path.write_text("name: t\n", encoding="utf-8")
   assert cli.main(["profile", "show", "--profile", str(path), "--json"]) == 0
   shown = json.loads(capsys.readouterr().out)
   lines = shown.pop("show_lines")
   assert shown == json.loads(json.dumps(P.load_profile(str(path)).as_dict(), ensure_ascii=False))     # 더해진 줄 말고는 예전과 같다
   assert lines[0].endswith("(merge)") and lines[-1].startswith("외곽선 : ")


def test_template_string_keys_become_int(tmp_path):
   """JSON 템플릿의 표 열쇠는 글자다. 겹치기 전에 int 로 맞춰 프로필 표와 한 표가 된다."""
   prof = _prof(tmp_path, {"table": {16: 9}})
   out, _ = check.apply_template(prof, _tpl(_cap_layer({"table": {"16": 7, "32": 12}})))
   table = out.color_cap_table()
   assert table[16] == 7 and table[32] == 12 and all(isinstance(k, int) for k in table)


def test_template_non_int_key_is_usage_error(tmp_path):
   with pytest.raises(UsageError, match="정수"):
      check.apply_template(_prof(tmp_path), _tpl(_cap_layer({"table": {"big": 7}})))


def test_override_table_mode_is_usage_error():
   """인자 겹에는 table_mode 가 닿지 않는다 — 말없이 무시하지 않고 거절한다."""
   with pytest.raises(UsageError, match="table_mode"):
      P.load_profile(None, {"check.warn.color_cap.table_mode": "replace"})


def test_preset_table_mode_is_profile_error(monkeypatch):
   real = P.load_preset
   def fake(name):
      data = copy.deepcopy(real(name))
      data.setdefault("check", {}).setdefault("warn", {}).setdefault("color_cap", {})["table_mode"] = "replace"
      return data
   monkeypatch.setattr(P, "load_preset", fake)
   with pytest.raises(ProfileError, match="프리셋"):
      P.load_profile(None)
