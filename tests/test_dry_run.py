"""공통 인자 `--dry-run` · `--force` · `--provider` 를 받아 놓고 조용히 무시하지 않는다 (2026-10-05 dry-run 판).

- 쓰는 명령 넷(cutout · trim · reline · tint)과 merge-colors 는 dry-run 이면 아무것도 안 쓰고 보고만 낸다.
- 파일을 안 쓰는 명령은 dry-run 을 그대로 받는다(해가 없다).
- 그 밖에 쓰는 명령은 cli 가 종료 2 로 거절한다. 공통 인자 표가 파서의 명령 목록과 어긋나면 시험이 깨진다.
- 2026-10-06 에 넓힌 명령(한 장 쓰는 것 · intake)과 「안 씀」 9개의 실제 확인은 test_dry_run_wide.
"""

import argparse

import pytest

import helpers
from arttool import cli, errors, image
from arttool.jsonio import read_json


def _files(folder):
   return sorted(p.name for p in folder.rglob("*") if p.is_file())


def _src(tmp_path, name="in"):
   src = tmp_path / name
   src.mkdir()
   image.save(src / "a.png", helpers.put_on_canvas(helpers.blob(8, 8), 10, 10, 1, 1))
   image.save(src / "b.png", helpers.put_on_canvas(helpers.blob(6, 6), 10, 10, 2, 2))
   return src


def _white(tmp_path):
   src = tmp_path / "in"
   src.mkdir()
   arr = image.new(4, 4)
   arr[1:3, 1:3] = (230, 230, 230, 255)
   image.save(src / "w.png", arr)
   return src


# --- 표가 파서와 맞나 ---


def _parser_keys() -> set:
   """파서에 등록된 (명령, 하위 명령) 전부."""
   keys = set()
   top = next(a for a in cli.build_parser()._actions if isinstance(a, argparse._SubParsersAction))
   for name, node in top.choices.items():
      inner = [a for a in node._actions if isinstance(a, argparse._SubParsersAction)]
      if inner:
         keys |= {(name, sub) for sub in inner[0].choices}
      else:
         keys.add((name, None))
   return keys


def test_dry_run_tables_cover_every_command():
   """새 명령을 더하고 세 무리(지원 · 안 씀 · 거절) 중 어디에도 안 넣으면 깨진다. 한 명령은 한 무리에만."""
   keys = _parser_keys()
   groups = [cli.DRY_RUN_TAKES, cli.DRY_RUN_HARMLESS, cli.DRY_RUN_REFUSED]
   assert set().union(*groups) == keys
   assert sum(len(g) for g in groups) == len(keys)


def test_force_provider_tables_name_real_commands():
   keys = _parser_keys()
   assert cli.FORCE_TAKES <= keys and cli.PROVIDER_TAKES <= keys


# --- 거절 ---


@pytest.mark.parametrize("front", [False, True])
def test_refused_command_with_dry_run_exits_2_and_writes_nothing(tmp_path, capsys, front):
   src = _src(tmp_path)
   out = tmp_path / "o"
   argv = ["tile", "blob", "--in", str(src), "--out", str(out)]
   argv = ["--dry-run", *argv] if front else [*argv, "--dry-run"]
   assert cli.main(argv) == errors.EXIT_USAGE
   assert not out.exists()
   err = capsys.readouterr().err
   assert "이 명령(tile blob)은 --dry-run 인자를 안 받는다 (받는 명령 :" in err
   assert "cutout" in err and "merge-colors" in err


def test_force_on_command_that_ignores_it_exits_2(tmp_path, capsys):
   src = _src(tmp_path)
   assert cli.main(["cutout", "--in", str(src), "--out", str(tmp_path / "o"), "--force"]) == errors.EXIT_USAGE
   assert not (tmp_path / "o").exists()
   assert "이 명령(cutout)은 --force 인자를 안 받는다 (받는 명령 : bake · style extract · ui bake)" in capsys.readouterr().err


def test_force_front_position_is_refused_too(tmp_path):
   src = _src(tmp_path)
   assert cli.main(["--force", "trim", "--in", str(src), "--out", str(tmp_path / "o")]) == errors.EXIT_USAGE


def test_provider_on_command_that_ignores_it_exits_2(tmp_path, capsys):
   src = _src(tmp_path)
   assert cli.main(["cutout", "--in", str(src), "--out", str(tmp_path / "o"), "--provider", "code"]) == errors.EXIT_USAGE
   assert "이 명령(cutout)은 --provider 인자를 안 받는다 (받는 명령 : provider make)" in capsys.readouterr().err
   assert cli.main(["--provider", "code", "trim", "--in", str(src), "--out", str(tmp_path / "o")]) == errors.EXIT_USAGE


def test_provider_make_still_takes_provider_and_default(tmp_path, monkeypatch):
   """provider make 는 --provider 를 받는다(앞 · 뒤 어디든). 안 주면 기본 제공자. --provider 없는 provider list 도 그대로 돈다."""
   asked = []

   class Stub:
      def make(self, req):
         class Done:
            def to_json(self):
               return {"dry_run": req.dry_run}
         return Done()

   monkeypatch.setattr(cli.providers, "get", lambda name: asked.append(name) or Stub())
   make = ["provider", "make", "--kind", "character", "--out", str(tmp_path / "g"), "--dry-run"]
   assert cli.main([*make, "--provider", "local"]) == errors.EXIT_OK
   assert cli.main(["--provider", "pixellab", *make]) == errors.EXIT_OK
   assert cli.main(make) == errors.EXIT_OK
   assert asked == ["local", "pixellab", cli.providers.DEFAULT]
   assert cli.main(["provider", "list"]) == errors.EXIT_OK
   assert cli.main(["provider", "list", "--provider", "local"]) == errors.EXIT_USAGE


# --- 안 쓰는 명령은 받는다 ---


def test_check_with_dry_run_is_same_as_before(tmp_path):
   src = _src(tmp_path)
   assert cli.main(["check", "--in", str(src), "--report", str(tmp_path / "a.json")]) in (errors.EXIT_OK, errors.EXIT_CHECK_FAIL)
   code = cli.main(["check", "--in", str(src), "--report", str(tmp_path / "b.json"), "--dry-run"])
   assert code in (errors.EXIT_OK, errors.EXIT_CHECK_FAIL)
   a, b = read_json(tmp_path / "a.json"), read_json(tmp_path / "b.json")
   assert (a["status"], a.get("failed"), len(a.get("warnings", []))) == (b["status"], b.get("failed"), len(b.get("warnings", [])))


# --- 지원 넷 ---


CASES = {
   "cutout": lambda src, out: ["cutout", "--in", str(src), "--out", str(out)],
   "trim": lambda src, out: ["trim", "--in", str(src), "--out", str(out), "--pad", "1"],
   "reline": lambda src, out: ["reline", "--in", str(src), "--out", str(out), "--color", "#000000"],
}


def _same_verdict(real: dict, dry: dict) -> None:
   assert real["status"] == dry["status"]
   assert real["warnings"] == dry["warnings"]


@pytest.mark.parametrize("name", sorted(CASES))
def test_dry_run_writes_nothing_and_matches_real(tmp_path, name):
   src = _src(tmp_path)
   out = tmp_path / "o"
   assert cli.main([*CASES[name](src, out), "--dry-run", "--report", str(tmp_path / "dry.json")]) == errors.EXIT_OK
   assert not out.exists()
   dry = read_json(tmp_path / "dry.json")
   assert dry["dry_run"] is True
   assert all(row["out"] is None for row in dry["images"])

   assert cli.main([*CASES[name](src, out), "--report", str(tmp_path / "real.json")]) == errors.EXIT_OK
   real = read_json(tmp_path / "real.json")
   assert "dry_run" not in real and "would_write" not in real      # dry-run 이 아닐 때 보고 꼴은 그대로
   _same_verdict(real, dry)
   assert sorted(dry["would_write"]) == sorted(row["out"] for row in real["images"] if row["out"])
   assert _files(out) == ["a.png", "b.png"]


def test_tint_dry_run_writes_nothing_and_matches_real(tmp_path):
   src = _white(tmp_path)
   out, sheet = tmp_path / "o", tmp_path / "s.png"
   base = ["tint", "--in", str(src), "--out", str(out), "--colors", "#E85D5D,#5DA0E8", "--sheet", str(sheet)]
   assert cli.main([*base, "--dry-run", "--report", str(tmp_path / "dry.json")]) == errors.EXIT_OK
   assert not out.exists() and not sheet.exists()
   dry = read_json(tmp_path / "dry.json")
   assert dry["dry_run"] is True and dry["sheet"] is None

   assert cli.main([*base, "--report", str(tmp_path / "real.json")]) == errors.EXIT_OK
   real = read_json(tmp_path / "real.json")
   assert "dry_run" not in real
   _same_verdict(real, dry)
   wrote = [str(out.resolve() / f) for f in _files(out)] + [real["sheet"]]
   assert sorted(dry["would_write"]) == sorted(wrote)


def test_trim_dry_run_skipped_image_is_not_in_would_write(tmp_path):
   src = tmp_path / "in"
   src.mkdir()
   image.save(src / "empty.png", image.new(4, 4))
   image.save(src / "full.png", helpers.blob(4, 4))
   assert cli.main(["trim", "--in", str(src), "--out", str(tmp_path / "o"), "--dry-run", "--report", str(tmp_path / "r.json")]) == errors.EXIT_OK
   rep = read_json(tmp_path / "r.json")
   assert [p.rsplit("\\", 1)[-1].rsplit("/", 1)[-1] for p in rep["would_write"]] == ["full.png"]
   assert rep["status"] == "warn"


@pytest.mark.parametrize("name", sorted(CASES))
def test_dry_run_still_refuses_overwriting_source(tmp_path, name):
   src = _src(tmp_path)
   assert cli.main([*CASES[name](src, src), "--dry-run"]) == errors.EXIT_USAGE


def test_tint_dry_run_still_refuses_sheet_inside_input(tmp_path):
   src = _white(tmp_path)
   argv = ["tint", "--in", str(src), "--out", str(tmp_path / "o"), "--colors", "#E85D5D", "--sheet", str(src / "s.png"), "--dry-run"]
   assert cli.main(argv) == errors.EXIT_USAGE


def test_merge_colors_dry_run_has_would_write(tmp_path):
   src = _src(tmp_path)
   out, sheet = tmp_path / "o", tmp_path / "s.png"
   base = ["merge-colors", "--in", str(src), "--out", str(out), "--sheet", str(sheet)]
   assert cli.main([*base, "--dry-run", "--report", str(tmp_path / "dry.json")]) == errors.EXIT_OK
   dry = read_json(tmp_path / "dry.json")
   assert not out.exists() and not sheet.exists()
   assert sorted(dry["would_write"]) == sorted([str(out.resolve() / "a.png"), str(out.resolve() / "b.png"), str(sheet.resolve())])
   assert cli.main([*base, "--report", str(tmp_path / "real.json")]) == errors.EXIT_OK
   real = read_json(tmp_path / "real.json")
   assert real["dry_run"] is False and "would_write" not in real


def test_trim_common_empty_dry_run_matches_real(tmp_path):
   """--common 에서 한 장만 비었을 때도 dry-run 과 진짜 실행의 경고(trim.empty) · status 가 같다 (리뷰 빈틈 ①)."""
   src = tmp_path / "in"
   src.mkdir()
   image.save(src / "empty.png", image.new(6, 6))
   image.save(src / "full.png", helpers.put_on_canvas(helpers.blob(3, 3), 6, 6, 1, 1))
   base = ["trim", "--in", str(src), "--out", str(tmp_path / "o"), "--common"]
   assert cli.main([*base, "--dry-run", "--report", str(tmp_path / "dry.json")]) == errors.EXIT_OK
   assert not (tmp_path / "o").exists()
   assert cli.main([*base, "--report", str(tmp_path / "real.json")]) == errors.EXIT_OK
   dry, real = read_json(tmp_path / "dry.json"), read_json(tmp_path / "real.json")
   assert [w["rule"] for w in dry["warnings"]] == ["trim.empty"]
   _same_verdict(real, dry)
   assert len(dry["would_write"]) == 2


def test_reline_dry_run_still_refuses_out_inside_input(tmp_path):
   """입력 폴더 안에 쓰는 것을 막는 guard_outside 도 dry-run 에서 돈다 (리뷰 빈틈 ②)."""
   src = _src(tmp_path)
   argv = ["reline", "--in", str(src), "--out", str(src / "sub"), "--color", "#000000", "--dry-run"]
   assert cli.main(argv) == errors.EXIT_USAGE
   assert not (src / "sub").exists()


def test_provider_make_empty_name_is_unknown(tmp_path, capsys):
   """--provider "" 는 기본 제공자로 몰래 가지 않고 「모르는 제공자」 오류다. 안 준 것(None)만 기본값."""
   argv = ["provider", "make", "--kind", "character", "--out", str(tmp_path / "g"), "--dry-run", "--provider", ""]
   assert cli.main(argv) == errors.EXIT_ERROR
   assert "모르는 제공자" in capsys.readouterr().err
   assert not (tmp_path / "g").exists()


# --- reline : 프로필 outline: null ---


def test_reline_profile_outline_empty_text_falls_back_like_merge(tmp_path):
   """outline: '' (빈 글)도 null 처럼 고리의 어두운 색으로 간다 — merge-colors 가 빈 글을 「지키지 않음」으로 읽는 것과 같다."""
   src = _src(tmp_path)
   prof = tmp_path / "p.yaml"
   prof.write_text("name: p\npalette:\n  outline: ''\n", encoding="utf-8")
   argv = ["reline", "--in", str(src), "--out", str(tmp_path / "o"), "--profile", str(prof), "--report", str(tmp_path / "r.json")]
   assert cli.main(argv) == errors.EXIT_OK
   assert read_json(tmp_path / "r.json")["images"][0]["target"] == "#%02X%02X%02X" % helpers.DARK


def test_reline_profile_outline_null_falls_back_to_ring(tmp_path):
   """도움말 순서 : --color > 프로필 palette.outline > 고리의 어두운 색. null 이면 셋째로 간다 (전에는 종료 2)."""
   src = _src(tmp_path)
   prof = tmp_path / "p.yaml"
   prof.write_text("name: p\npalette:\n  outline: null\n", encoding="utf-8")
   argv = ["reline", "--in", str(src), "--out", str(tmp_path / "o"), "--profile", str(prof), "--report", str(tmp_path / "r.json")]
   assert cli.main(argv) == errors.EXIT_OK
   rep = read_json(tmp_path / "r.json")
   assert rep["images"][0]["target"] == "#%02X%02X%02X" % helpers.DARK
