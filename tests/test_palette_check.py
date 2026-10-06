"""3판-가 5 — `palette check` · 보고 `palette` 칸 · `ramp_shape.report: once` (설계 2-4 · 시험 목록 7)."""
import json

import pytest

import helpers
from arttool import check, cli, errors, image, jsonio
from arttool.errors import ProfileError

ONCE = {"check.warn.ramp_shape.report": "once"}


def loose_dir(tmp_path, count=3, name="loose"):
   out = tmp_path / name
   out.mkdir(parents=True, exist_ok=True)
   for index in range(count):
      image.save(out / f"icon_{index}.png", helpers.blob(8, 8))
   return out


def ramp_lines(report):
   return [w for w in report["warnings"] if w["rule"] == "ramp_shape"]


def test_each_is_default_and_report_has_no_palette(tmp_path):
   """report 를 안 적은 옛 프로필 = each. 그림 보고의 옛 줄이 그대로 있고 `palette` 칸은 안 붙는다."""
   report = check.run(helpers.tiny_profile(tmp_path), loose_dir(tmp_path))
   assert len(ramp_lines(report)) == 1
   assert "palette" not in report


def test_old_profile_report_is_byte_identical_to_explicit_each(tmp_path):
   """새 칸을 안 쓴 보고와 each 를 적은 보고가 바이트까지 같다 (옛 동작 보존)."""
   src = loose_dir(tmp_path)
   old = check.run(helpers.tiny_profile(tmp_path), src)
   each = check.run(helpers.tiny_profile(tmp_path, **{"check.warn.ramp_shape.report": "each"}), src)
   assert json.dumps(old, ensure_ascii=False, sort_keys=False) == json.dumps(each, ensure_ascii=False, sort_keys=False)


def test_once_moves_ramp_shape_to_palette_block(tmp_path):
   report = check.run(helpers.tiny_profile(tmp_path, **ONCE), loose_dir(tmp_path, count=3))
   assert ramp_lines(report) == []                         # 그림 줄에서 빠진다
   (name, entry), = report["palette"].items()
   assert name.endswith(".json")                           # 열쇠는 램프 파일 이름
   assert entry["used_by"] == 3
   assert entry["ramp_shape"] and all(": " in line for line in entry["ramp_shape"])
   assert report["status"] == check.run(helpers.tiny_profile(tmp_path), loose_dir(tmp_path, count=3))["status"]


def test_once_with_many_inputs_measures_once_and_sums_used_by(tmp_path):
   prof = helpers.tiny_profile(tmp_path, **ONCE)
   report = check.run_many(prof, [loose_dir(tmp_path, 2, "a"), loose_dir(tmp_path, 3, "b")])
   (entry,) = report["palette"].values()
   assert entry["used_by"] == 5
   assert ramp_lines(report) == []


def test_once_skips_palette_when_no_ramps_or_no_warn(tmp_path):
   prof = helpers.tiny_profile(tmp_path, **ONCE)
   assert "palette" not in check.run(prof, loose_dir(tmp_path), no_ramps=True)
   assert "palette" not in check.run(prof, loose_dir(tmp_path), warn=False)


def test_bad_report_value_is_profile_error(tmp_path):
   with pytest.raises(ProfileError):
      helpers.tiny_profile(tmp_path, **{"check.warn.ramp_shape.report": "twice"})


def test_palette_check_from_profile_matches_check_block(tmp_path, monkeypatch):
   monkeypatch.chdir(tmp_path)
   assert cli.main(["palette", "check", "--profile", "topdown_action", "--report", "p.json"]) == 0
   data = jsonio.read_json(tmp_path / "p.json")
   assert data["status"] == "warn"
   (name, entry), = data["palette"].items()
   assert "used_by" not in entry                           # 그림 없이 재니 사용 수는 없다
   block = check.run(helpers.tiny_profile(tmp_path, **ONCE), loose_dir(tmp_path))["palette"]
   assert block[name]["ramp_shape"] == entry["ramp_shape"]  # check 와 같은 판정


def test_palette_check_with_ramps_file(tmp_path, monkeypatch):
   monkeypatch.chdir(tmp_path)
   src = helpers.tiny_profile(tmp_path).ramps_path()
   (tmp_path / "r.json").write_bytes(src.read_bytes())
   assert cli.main(["palette", "check", "--ramps", "r.json", "--report", "p.json"]) == 0
   assert list(jsonio.read_json(tmp_path / "p.json")["palette"]) == ["r.json"]


def test_palette_check_report_cannot_overwrite_ramps(tmp_path, monkeypatch):
   """--report 가 --ramps 와 같은 파일이면 거절한다 — 램프 파일을 덮어쓰지 않는다."""
   monkeypatch.chdir(tmp_path)
   body = helpers.tiny_profile(tmp_path).ramps_path().read_bytes()
   (tmp_path / "rr.json").write_bytes(body)
   assert cli.main(["palette", "check", "--ramps", "rr.json", "--report", "rr.json"]) != 0
   assert (tmp_path / "rr.json").read_bytes() == body


def test_once_ramp_shape_is_not_stale_known(tmp_path):
   """report: once 면 ramp_shape 는 palette 칸에 있다 — 그 판정과 맞는 known 항목은 stale 로 세지 않는다."""
   prof = helpers.tiny_profile(tmp_path, **ONCE)
   src = loose_dir(tmp_path)
   each = check.run(helpers.tiny_profile(tmp_path), src)
   ramps = [cell["ramp"] for line in ramp_lines(each) for cell in line["items"]]
   assert ramps
   known = tmp_path / "known.json"
   rows = [{"rule": "ramp_shape", "where": r, "note": "알고 둔다"} for r in ramps] + [{"rule": "ramp_shape", "where": "없는램프"}]
   known.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
   report = check.run(prof, src, known=[str(known)])
   stale = [i for i in report.get("info", []) if i["rule"] == "check.known_stale"]
   assert len(stale) == 1 and len(stale[0]["items"]) == 1          # 맞는 항목은 빠지고 없는 램프 하나만 남는다
   assert "없는램프" in json.dumps(stale[0], ensure_ascii=False)
   assert report["palette"]                                       # 판정 글은 palette 칸에 그대로


@pytest.mark.parametrize("name, body", [("missing.json", None), ("bad.json", "{ 깨짐"), ("r.txt", "{}")])
def test_palette_check_file_errors_exit_2(tmp_path, monkeypatch, name, body):
   monkeypatch.chdir(tmp_path)
   if body is not None:
      (tmp_path / name).write_text(body, encoding="utf-8")
   assert cli.main(["palette", "check", "--ramps", name]) == errors.EXIT_USAGE


def test_palette_check_takes_dry_run(tmp_path, monkeypatch):
   monkeypatch.chdir(tmp_path)
   assert cli.main(["palette", "check", "--profile", "topdown_action", "--dry-run"]) == 0


# --- 합칠 때 열쇠 가르기 : 전체 경로 · 판정이 같아야 한 열쇠 ---


def assert_no_leak(report, *paths):
   """보고 JSON 글에 임시 칸 이름과 절대경로가 없다."""
   text = json.dumps(report, ensure_ascii=False)
   assert check.PALETTE_PATH not in text
   for path in paths:
      assert str(path) not in text and json.dumps(str(path))[1:-1] not in text


def ramps_copy(tmp_path, folder):
   """기본 램프 파일을 `<folder>/ramps.json` 으로 베낀다 — 이름은 같고 폴더만 다른 파일."""
   src = helpers.tiny_profile(tmp_path).ramps_path()
   out = tmp_path / folder / "ramps.json"
   out.parent.mkdir(parents=True, exist_ok=True)
   out.write_bytes(src.read_bytes())
   return out


def test_merge_same_ramp_same_verdict_is_one_key(tmp_path):
   """① 같은 램프 · 같은 판정인 두 입력 → 열쇠 하나, used_by 합. 열쇠는 옛 꼴(파일 이름) 그대로."""
   prof = helpers.tiny_profile(tmp_path, **ONCE)
   report = check.run_many(prof, [loose_dir(tmp_path, 2, "a"), loose_dir(tmp_path, 3, "b")])
   (name, entry), = report["palette"].items()
   assert name == prof.ramps_path().name
   assert list(entry) == ["ramp_shape", "used_by"] and entry["used_by"] == 5
   assert_no_leak(report, prof.ramps_path().resolve())


def test_merge_same_ramp_different_verdict_keeps_both(tmp_path):
   """② 같은 램프 파일인데 프로필마다 ramp_shape 설정이 달라 판정이 다르다 → 열쇠 둘, 둘 다의 판정이 남는다."""
   one = helpers.tiny_profile(tmp_path, **ONCE)
   two = helpers.tiny_profile(tmp_path, **ONCE, **{"check.warn.ramp_shape.hue_min": 0})
   reports = [check.run(one, loose_dir(tmp_path, 2, "a"), _keep_paths=True),
              check.run(two, loose_dir(tmp_path, 3, "b"), _keep_paths=True)]
   first, second = (next(iter(r["palette"].values()))["ramp_shape"] for r in reports)
   assert first != second                                   # 설정이 달라 판정이 정말 다르다
   merged = check.drop_palette_paths(check.merge(reports, ["a", "b"]))
   name = one.ramps_path().name
   assert merged["palette"] == {f"{name} · a": {"ramp_shape": first, "used_by": 2},
                                f"{name} · b": {"ramp_shape": second, "used_by": 3}}
   assert_no_leak(merged, one.ramps_path().resolve())


def test_merge_same_name_other_folder_keeps_both(tmp_path):
   """③ 폴더만 다르고 이름이 같은 램프 둘 → 열쇠 둘 (판정이 같아도 다른 파일이다)."""
   reports = []
   files = [ramps_copy(tmp_path, "pa"), ramps_copy(tmp_path, "pb")]
   for index, file in enumerate(files):
      prof = helpers.tiny_profile(tmp_path, **ONCE)
      object.__setattr__(prof, "ramps_path", lambda file=file: file)   # 이 판만 다른 폴더의 같은 이름 파일을 보게
      reports.append(check.run(prof, loose_dir(tmp_path, 1 + index, f"in{index}"), _keep_paths=True))
   assert all(next(iter(r["palette"].values()))[check.PALETTE_PATH] for r in reports)
   merged = check.drop_palette_paths(check.merge(reports, ["x", "y"]))
   assert sorted(merged["palette"]) == ["ramps.json · x", "ramps.json · y"]
   assert [e["used_by"] for e in merged["palette"].values()] == [1, 2]
   assert_no_leak(merged, *(f.resolve() for f in files), tmp_path)


def test_profile_map_splits_verdicts_and_hides_paths(tmp_path):
   """② · ④ 지도 길 : 같은 램프 파일을 두 프로필이 다른 ramp_shape 설정으로 잰다 → 프로필 딱지로 열쇠 둘, 경로는 안 샌다."""
   from arttool import profile_map as pm
   ramps = ramps_copy(tmp_path, "profiles")
   once = "    ramp_shape: { report: once%s }\n"
   head = "palette:\n  ramps_file: ramps.json\ncheck:\n  warn:\n"
   (tmp_path / "profiles" / "base.yaml").write_text("name: base\n" + head + once % "", encoding="utf-8")
   (tmp_path / "profiles" / "body.yaml").write_text("name: body\n" + head + once % ", hue_min: 0", encoding="utf-8")
   map_file = tmp_path / "map.yaml"
   map_file.write_text('version: 1\ndefault: profiles/base.yaml\nrules:\n  - match: "body*"\n    profile: profiles/body.yaml\n',
                       encoding="utf-8")
   art, art2 = tmp_path / "art", tmp_path / "art2"
   for folder in (art, art2):
      folder.mkdir()
      image.save(folder / "head.png", helpers.blob(8, 8))
      image.save(folder / "body.png", helpers.blob(8, 8))
   report = check.run(None, art, profile_map=pm.load(map_file))
   assert len(report["palette"]) == 2 and all(name.startswith("ramps.json · ") for name in report["palette"])
   assert len({tuple(e["ramp_shape"]) for e in report["palette"].values()}) == 2
   assert_no_leak(report, ramps.resolve())
   many = check.run_many(None, [art, art2], profile_map=pm.load(map_file))   # 지도 묶음을 다시 --in 여럿으로
   assert len(many["palette"]) == 2                          # 프로필끼리는 갈리고, 입력끼리는 같은 판정이라 합쳐진다
   assert [e["used_by"] for e in many["palette"].values()] == [2, 2]
   assert_no_leak(many, ramps.resolve())


def test_single_run_report_has_no_temp_field(tmp_path):
   """④ 입력 하나 · 지도 없음 보고에도 임시 칸 · 절대경로가 없다."""
   prof = helpers.tiny_profile(tmp_path, **ONCE)
   report = check.run(prof, loose_dir(tmp_path))
   (entry,) = report["palette"].values()
   assert list(entry) == ["ramp_shape", "used_by"]
   assert_no_leak(report, prof.ramps_path().resolve())
