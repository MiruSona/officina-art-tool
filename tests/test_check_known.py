"""2판 D — check --known · --baseline · --fail-on-new (알고 두는 경고 빼기)."""

import copy
import json

import pytest

from arttool import check as check_mod
from arttool import cli, errors, image

import helpers


def _report() -> dict:
   return {
      "version": 1, "profile": "topdown_action", "status": "ok", "must_failed": ["frames"], "failed": [],
      "warnings": [
         {"rule": "must.frames", "ok": False, "detail": "프레임 수", "items": [{"where": "walk/down"}], "must": True},
         {"rule": "outline.gap", "ok": False, "detail": "외곽선 틈 3장",
          "items": [{"where": "idle/left"}, {"where": "idle/right"}, {"where": "walk/down"}]},
         {"rule": "palette.extra", "ok": False, "detail": "팔레트 밖 색", "items": [{"where": "walk/down"}]},
         {"rule": "loop.seam", "ok": False, "detail": "칸 없는 경고", "items": []},
      ],
   }


def _known(*entries) -> list[dict]:
   return check_mod.load_known([], []) + [{"rule": r, "where": w, "note": ""} for r, w in entries]


def _info(report: dict, rule: str) -> dict | None:
   return next((line for line in report.get("info", []) if line["rule"] == rule), None)


def test_whole_line_matches():
   out = check_mod.apply_known(_report(), _known(("palette.extra", "*")))
   assert [line["rule"] for line in out["known"]] == ["palette.extra"]
   assert out["known"][0]["known_by"] == "palette.extra @ *"
   assert all(line["rule"] != "palette.extra" for line in out["warnings"])
   assert out["new_warnings"] == 1 + 3 + 1   # must 1칸 · outline 3칸 · 칸 없는 경고 1


def test_partial_match_splits_line():
   out = check_mod.apply_known(_report(), _known(("outline.gap", "idle/*")))
   kept = next(line for line in out["warnings"] if line["rule"] == "outline.gap")
   moved = next(line for line in out["known"] if line["rule"] == "outline.gap")
   assert kept["items"] == [{"where": "walk/down"}]
   assert moved["items"] == [{"where": "idle/left"}, {"where": "idle/right"}]
   assert moved["detail"] == kept["detail"] == "외곽선 틈 3장"


def test_star_crosses_slash_for_frame_path():
   out = check_mod.apply_known(_report(), _known(("outline.*", "*")))
   assert all(line["rule"] != "outline.gap" for line in out["warnings"])
   none = check_mod.apply_known(_report(), _known(("outline.gap", "idle")))
   assert _info(none, "check.known_stale") is not None
   assert not none["known"]


def test_itemless_warning_needs_star_where():
   out = check_mod.apply_known(_report(), _known(("loop.seam", "idle/*")))
   assert any(line["rule"] == "loop.seam" for line in out["warnings"])
   out = check_mod.apply_known(_report(), _known(("loop.seam", "*")))
   assert [line["rule"] for line in out["known"]] == ["loop.seam"]


def test_stale_entry_goes_to_info():
   out = check_mod.apply_known(_report(), _known(("tone.flat", "run/*"), ("palette.extra", "*")))
   stale = _info(out, "check.known_stale")
   assert stale["items"] == [{"rule": "tone.flat", "where": "run/*"}]


def test_must_cannot_be_known():
   report = _report()
   out = check_mod.apply_known(report, _known(("must.*", "*")))
   assert any(line["rule"] == "must.frames" for line in out["warnings"])
   assert _info(out, "check.known_must")["items"] == [{"rule": "must.*", "where": "*"}]
   assert _info(out, "check.known_stale") is None
   for key in ("status", "must_failed", "failed"):
      assert out[key] == report[key]


def test_status_untouched_without_fail_on_new():
   out = check_mod.apply_known(_report(), _known())
   assert out["status"] == "ok" and out["new_warnings"] > 0
   assert check_mod.apply_known(_report(), _known(), fail_on_new=True)["status"] == "fail"


def test_input_report_not_mutated():
   report = _report()
   before = copy.deepcopy(report)
   check_mod.apply_known(report, _known(("outline.gap", "idle/*")))
   assert report == before


# ---- cli ----

def _argv(tmp_path, *more) -> list[str]:
   loose = tmp_path / "loose"
   if not loose.exists():
      loose.mkdir()
      image.save(loose / "berry.png", helpers.blob(8, 8))
   return ["--profile", "topdown_action", "check", "--in", str(loose), "--report", str(tmp_path / "c.json"), *more]


def _fake(monkeypatch):
   monkeypatch.setattr(check_mod, "_run", lambda *a, **k: _report())


def _write(path, data):
   path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
   return str(path)


def test_cli_fail_on_new_exit_4(tmp_path, monkeypatch):
   _fake(monkeypatch)
   known = _write(tmp_path / "k.json", [{"rule": "outline.gap", "where": "idle/*", "note": "왜"}])
   assert cli.main(_argv(tmp_path, "--known", known)) == errors.EXIT_OK
   assert cli.main(_argv(tmp_path, "--known", known, "--fail-on-new")) == errors.EXIT_CHECK_FAIL
   report = json.loads((tmp_path / "c.json").read_text(encoding="utf-8"))
   assert report["new_warnings"] == 4 and report["known"]   # must 1 · outline 1 · palette 1 · 칸 없는 1


def test_cli_baseline_round_trip(tmp_path, monkeypatch):
   _fake(monkeypatch)
   old = _report()
   old["warnings"][1]["items"][0]["where"] = "idle/[odd]"   # 이름에 [ 가 든 그림
   monkeypatch.setattr(check_mod, "_run", lambda *a, **k: copy.deepcopy(old))
   base = _write(tmp_path / "old.json", old)
   assert cli.main(_argv(tmp_path, "--baseline", base, "--fail-on-new")) == errors.EXIT_CHECK_FAIL   # must 1칸은 못 뺀다
   report = json.loads((tmp_path / "c.json").read_text(encoding="utf-8"))
   assert [line["rule"] for line in report["warnings"]] == ["must.frames"]
   assert report["new_warnings"] == 1
   assert _info(report, "check.known_stale") is None


def test_cli_baseline_round_trip_real_check(tmp_path):
   assert cli.main(_argv(tmp_path)) in (errors.EXIT_OK, errors.EXIT_CHECK_FAIL)
   base = tmp_path / "old.json"
   (tmp_path / "c.json").replace(base)
   assert cli.main(_argv(tmp_path, "--baseline", str(base), "--fail-on-new")) == errors.EXIT_OK
   report = json.loads((tmp_path / "c.json").read_text(encoding="utf-8"))
   assert report["new_warnings"] == 0


def test_cli_no_options_report_unchanged(tmp_path):
   assert cli.main(_argv(tmp_path)) in (errors.EXIT_OK, errors.EXIT_CHECK_FAIL)
   report = json.loads((tmp_path / "c.json").read_text(encoding="utf-8"))
   assert "known" not in report and "new_warnings" not in report


def test_no_options_returns_inner_report_as_is(tmp_path, monkeypatch):
   inner = _report()
   monkeypatch.setattr(check_mod, "_run", lambda *a, **k: inner)
   assert check_mod.run(None, tmp_path) is inner
   assert cli.main(_argv(tmp_path)) == errors.EXIT_OK
   assert (tmp_path / "c.json").read_text(encoding="utf-8") == json.dumps(inner, ensure_ascii=False, indent=2) + "\n"


def test_cli_with_no_warn_is_usage_error(tmp_path):
   known = _write(tmp_path / "k.json", [])
   assert cli.main(_argv(tmp_path, "--known", known, "--no-warn")) == errors.EXIT_USAGE
   assert cli.main(_argv(tmp_path, "--fail-on-new", "--no-warn")) == errors.EXIT_USAGE


@pytest.mark.parametrize("data, word", [
   ({"rule": "x"}, "배열"),
   ([{"rule": "x", "wher": "*"}], "모르는 칸"),
   ([{"where": "*"}], "rule"),
   (["x"], "객체"),
])
def test_bad_known_list_rejected(tmp_path, capsys, data, word):
   known = _write(tmp_path / "k.json", data)
   assert cli.main(_argv(tmp_path, "--known", known)) == errors.EXIT_USAGE
   assert word in capsys.readouterr().err


def test_known_path_guarded_against_report(tmp_path):
   known = _write(tmp_path / "c.json", [])
   assert cli.main(_argv(tmp_path, "--known", known)) == errors.EXIT_USAGE


# ---- 자리 열쇠 (where 없는 칸) ----

def _ramp(*names) -> dict:
   items = [{"ramp": n, "why": "steps", "steps": 2, "padded": False, "hue_steps": [], "luma": []} for n in names]
   return {"version": 1, "profile": "topdown_action", "status": "ok", "must_failed": [], "failed": [],
           "warnings": [{"rule": "ramp_shape", "ok": False, "detail": f"모양이 걸린 램프 {len(items)}줄", "items": items}]}


def test_cell_key_order():
   assert check_mod.cell_key({"where": "a", "ramp": "b"}) == "a"
   assert check_mod.cell_key({"ramp": "skin"}) == "skin"
   assert check_mod.cell_key("idle/0.png") == "idle/0.png"
   assert check_mod.cell_key({"b": 1, "a": "가"}) == '{"a": "가", "b": 1}'


def test_baseline_ramp_does_not_swallow_new_ramp(tmp_path, monkeypatch):
   base = _write(tmp_path / "old.json", _ramp("skin"))
   monkeypatch.setattr(check_mod, "_run", lambda *a, **k: _ramp("skin", "hair"))
   assert cli.main(_argv(tmp_path, "--baseline", base, "--fail-on-new")) == errors.EXIT_CHECK_FAIL
   report = json.loads((tmp_path / "c.json").read_text(encoding="utf-8"))
   assert report["new_warnings"] == 1
   assert [c["ramp"] for c in report["warnings"][0]["items"]] == ["hair"]


def test_known_where_picks_one_ramp():
   out = check_mod.apply_known(_ramp("skin", "hair"), _known(("ramp_shape", "skin")))
   assert [c["ramp"] for c in out["warnings"][0]["items"]] == ["hair"]
   assert [c["ramp"] for c in out["known"][0]["items"]] == ["skin"]
