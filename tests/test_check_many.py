"""`check --in` 여럿 (2판 C9) — 입력 딱지 · 합친 보고 · known 은 합친 뒤 한 번 · 하나면 예전과 같다."""

import copy
import json

from arttool import check as check_mod
from arttool import cli, errors, image

import helpers


def _loose(tmp_path, name: str, parent: str = "") -> str:
   folder = tmp_path / parent / name if parent else tmp_path / name
   if not folder.exists():
      folder.mkdir(parents=True)
      image.save(folder / "berry.png", helpers.blob(8, 8))
   return str(folder)


def _argv(report, ins, *more) -> list[str]:
   return ["--profile", "topdown_action", "check", "--in", *ins, "--report", str(report), *more]


def _read(path) -> dict:
   return json.loads(path.read_text(encoding="utf-8"))


def _fake_report(status: str = "ok") -> dict:
   return {
      "version": 1, "profile": "topdown_action", "status": status, "must_failed": [], "failed": [],
      "checked": {"frames": 2}, "skipped": [], "rules": [{"rule": "alpha", "ok": status == "ok", "detail": "", "items": []}],
      "warnings": [
         {"rule": "outline.gap", "ok": False, "detail": "틈", "items": [{"where": "berry.png"}]},
         {"rule": "palette.extra", "ok": False, "detail": "색", "items": [{"color": "#ff0000"}, "글칸"]},
      ],
   }


def test_one_input_is_byte_same_as_before(tmp_path):
   one = _loose(tmp_path, "a")
   assert cli.main(_argv(tmp_path / "new.json", [one])) in (errors.EXIT_OK, errors.EXIT_CHECK_FAIL)
   from arttool.profile import load_profile   # 예전 길 = check.run 하나
   old = check_mod.run(load_profile("topdown_action"), one)
   new_text = (tmp_path / "new.json").read_text(encoding="utf-8")
   cli_old = tmp_path / "old.json"
   from arttool.jsonio import write_json
   write_json(cli_old, old)
   assert new_text == cli_old.read_text(encoding="utf-8")
   assert "inputs" not in json.loads(new_text)


def test_two_inputs_real_check_labels(tmp_path):
   a, b = _loose(tmp_path, "a"), _loose(tmp_path, "b")
   code = cli.main(_argv(tmp_path / "c.json", [a, b]))
   report = _read(tmp_path / "c.json")
   assert code == (errors.EXIT_OK if report["status"] == "ok" else errors.EXIT_CHECK_FAIL)
   assert [i["label"] for i in report["inputs"]] == ["a", "b"]
   assert [i["mode"] for i in report["inputs"]] == ["loose", "loose"]
   assert report["checked"]["inputs"] == 2
   assert {line["input"] for line in report["rules"]} == {"a", "b"}
   for line in report["warnings"]:
      for cell in line.get("items") or []:
         assert check_mod.cell_key(cell).startswith(line["input"] + "/")


def test_same_folder_names_get_numbers():
   assert check_mod.input_labels(["x/a", "y/a", "z/b"]) == ["1:a", "2:a", "b"]


def test_merge_status_any_fail_and_cell_tags():
   merged = check_mod.merge([_fake_report("ok"), _fake_report("fail")], ["a", "b"])
   assert merged["status"] == "fail"
   assert merged["checked"] == {"inputs": 2, "frames": 4}
   keys = [check_mod.cell_key(c) for line in merged["warnings"] for c in line["items"]]
   assert keys == ["a/berry.png", "a/#ff0000", "a/글칸", "b/berry.png", "b/#ff0000", "b/글칸"]


def test_warnings_do_not_change_status():
   merged = check_mod.merge([_fake_report("ok"), _fake_report("ok")], ["a", "b"])
   assert merged["status"] == "ok" and merged["warnings"]


def test_known_glob_by_label_hits_only_that_input(tmp_path, monkeypatch):
   monkeypatch.setattr(check_mod, "_run", lambda *a, **k: copy.deepcopy(_fake_report()))
   a, b = _loose(tmp_path, "a"), _loose(tmp_path, "b")
   known = tmp_path / "k.json"
   known.write_text(json.dumps([{"rule": "*", "where": "a/*", "note": "a 는 알고 둔다"}]), encoding="utf-8")
   assert cli.main(_argv(tmp_path / "c.json", [a, b], "--known", str(known), "--fail-on-new")) == errors.EXIT_CHECK_FAIL
   report = _read(tmp_path / "c.json")
   assert {line["input"] for line in report["known"]} == {"a"}
   assert {line["input"] for line in report["warnings"]} == {"b"}
   assert report["new_warnings"] == 3


def test_report_same_as_one_input_is_refused(tmp_path):
   a = _loose(tmp_path, "a")
   clash = tmp_path / "b.json"
   clash.write_text("{}", encoding="utf-8")
   assert cli.main(_argv(clash, [a, str(clash)])) == errors.EXIT_USAGE
   assert clash.read_text(encoding="utf-8") == "{}"


def test_no_warn_with_known_refused_for_many(tmp_path):
   a, b = _loose(tmp_path, "a"), _loose(tmp_path, "b")
   known = tmp_path / "k.json"
   known.write_text("[]", encoding="utf-8")
   assert cli.main(_argv(tmp_path / "c.json", [a, b], "--no-warn", "--known", str(known))) == errors.EXIT_USAGE


def test_single_input_baseline_matches_every_input(tmp_path, monkeypatch):
   # 입력 하나로 만든 옛 보고(inputs 칸 없음)를 --in 여럿 판의 baseline 으로 주면 모든 입력에 맞는다.
   monkeypatch.setattr(check_mod, "_run", lambda *a, **k: copy.deepcopy(_fake_report()))
   a, b = _loose(tmp_path, "a"), _loose(tmp_path, "b")
   base = tmp_path / "base.json"
   assert cli.main(_argv(base, [a])) in (errors.EXIT_OK, errors.EXIT_CHECK_FAIL)
   assert "inputs" not in _read(base)
   assert cli.main(_argv(tmp_path / "c.json", [a, b], "--baseline", str(base), "--fail-on-new")) == errors.EXIT_OK
   report = _read(tmp_path / "c.json")
   assert report["warnings"] == [] and report["new_warnings"] == 0
   assert {line["input"] for line in report["known"]} == {"a", "b"}


def test_many_input_baseline_on_one_input_says_shape(tmp_path, monkeypatch):
   monkeypatch.setattr(check_mod, "_run", lambda *a, **k: copy.deepcopy(_fake_report()))
   a, b = _loose(tmp_path, "a"), _loose(tmp_path, "b")
   base = tmp_path / "base.json"
   cli.main(_argv(base, [a, b]))
   assert len(_read(base)["inputs"]) == 2
   assert cli.main(_argv(tmp_path / "c.json", [a], "--baseline", str(base), "--fail-on-new")) == errors.EXIT_CHECK_FAIL
   report = _read(tmp_path / "c.json")
   assert report["warnings"]                                    # 딱지 붙은 열쇠라 안 맞는다
   notes = [line for line in report["info"] if line["rule"] == "check.baseline_shape"]
   assert len(notes) == 1 and "입력 2개" in notes[0]["detail"]


def test_labels_resolve_and_sanitize(tmp_path, monkeypatch):
   monkeypatch.chdir(tmp_path)
   (tmp_path / "x[1]").mkdir()
   labels = check_mod.input_labels(["./x[1]", "."])
   assert labels == ["x_1_", tmp_path.name.translate(check_mod.LABEL_UNSAFE)]
   assert all(label for label in check_mod.input_labels(["C:/", "./x[1]"]))


def test_same_path_twice_is_refused(tmp_path):
   a = _loose(tmp_path, "a")
   assert cli.main(_argv(tmp_path / "c.json", [a, a + "/../a"])) == errors.EXIT_USAGE


def test_merge_keeps_common_mode():
   assert check_mod.merge([_fake_report(), _fake_report()], ["a", "b"], modes=["loose", "loose"])["checked"]["mode"] == "loose"
   assert "mode" not in check_mod.merge([_fake_report(), _fake_report()], ["a", "b"], modes=["loose", "frames"])["checked"]


def test_many_loose_reports_mode(tmp_path):
   a, b = _loose(tmp_path, "a"), _loose(tmp_path, "b")
   cli.main(_argv(tmp_path / "c.json", [a, b]))
   assert _read(tmp_path / "c.json")["checked"]["mode"] == "loose"
