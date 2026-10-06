"""`--dry-run` 넓히기 (2026-10-06). 표 분류를 코드 읽기가 아니라 실제로 돌려 폴더 앞뒤를 견줘 못박는다.

- 「안 씀이라 받음」 명령 : dry-run 이든 아니든 작업 폴더에 아무것도 안 생기고 안 바뀐다.
- 새로 받는 명령 : dry-run 이면 작업 폴더가 그대로이고 `would_write` 가 진짜로 돌렸을 때 쓴 파일과 같다.
- `intake --dry-run` : 손질 · 검수 · 비교판을 다 돌되 아무것도 안 쓴다.
보고(`--report`)는 dry-run 에서도 cli 가 쓰므로 작업 폴더 밖(rep/)에 둔다.
"""

import json
import tempfile

import numpy as np
import pytest

import helpers
import test_cli
import test_layers_ops
import test_ui_icons
from arttool import cli, errors, image
from arttool.jsonio import read_json


def _snap(root):
   """폴더 아래 모든 파일 · 폴더의 (크기, 수정 시각). 하나라도 생기거나 바뀌면 달라진다."""
   rows = {}
   for path in sorted(root.rglob("*")):
      stat = path.stat()
      rows[str(path.relative_to(root))] = ("dir", 0, 0) if path.is_dir() else ("file", stat.st_size, stat.st_mtime_ns)
   return rows


@pytest.fixture
def work(tmp_path, monkeypatch):
   """작업 폴더. 현재 폴더도 여기로 옮겨 상대경로로 몰래 쓰는 것까지 잡는다."""
   folder = tmp_path / "w"
   folder.mkdir()
   (tmp_path / "rep").mkdir()
   monkeypatch.chdir(folder)
   return folder


def _rep(work, name):
   return str(work.parent / "rep" / name)


def _png(path, arr):
   image.save(path, arr)
   return str(path)


def _two(work):
   a = _png(work / "a.png", helpers.put_on_canvas(helpers.blob(8, 8), 10, 10, 1, 1))
   b = _png(work / "b.png", helpers.put_on_canvas(helpers.blob(6, 6), 10, 10, 2, 2))
   return a, b


def _flat(side, rgb=(40, 120, 60)):
   arr = image.new(side, side)
   arr[:, :] = (*rgb, 255)
   arr[::3, ::2] = (60, 140, 80, 255)
   return arr


def _strip(work):
   """가로 6칸마다 되풀이하는 띠 (24x4)."""
   unit = image.new(6, 4)
   unit[:, :] = (200, 200, 200, 255)
   unit[:, 0] = (20, 20, 20, 255)
   unit[1, 3] = (120, 60, 30, 255)
   return _png(work / "strip.png", np.ascontiguousarray(np.concatenate([unit] * 4, axis=1)))


# --- 1. 「안 씀이라 받음」 9개 : 실제로 안 쓰나 ---


def _harmless_cases(work):
   a, _b = _two(work)
   src = work
   tiles = work / "tiles"
   tiles.mkdir()
   _png(tiles / "t.png", _flat(8))
   test_layers_ops.write_set(work / "set", test_layers_ops.three_layers())
   build = work / "ui"
   assert cli.main(["--profile", "topdown_action", "ui", "icons", "--in", str(test_ui_icons.make_sheet(work)), "--out", str(build)]) == 0
   return {
      ("profile", "show"): ["profile", "show"],
      ("check", None): ["check", "--in", str(src), "--report", _rep(work, "c.json")],
      ("layers", "check"): ["layers", "check", "--in", str(work / "set")],
      ("tile", "inspect"): ["tile", "inspect", "--in", str(tiles), "--report", _rep(work, "i.json"), "--size", "8"],
      ("ui", "check"): ["--profile", "topdown_action", "ui", "check", "--in", str(build), "--report", _rep(work, "u.json")],
      ("ui", "glyphs"): ["ui", "glyphs", "--font", str(image.LABEL_FONT), "--text", "가나"],
      ("template", "list"): ["template", "list"],
      ("template", "show"): ["template", "show", "char_small", "--size", "32x32"],
      ("provider", "list"): ["provider", "list"],
   }


def test_harmless_cases_cover_the_table(work):
   assert set(_harmless_cases(work)) == cli.DRY_RUN_HARMLESS


@pytest.mark.parametrize("key", sorted(cli.DRY_RUN_HARMLESS, key=lambda k: (k[0], k[1] or "")))
@pytest.mark.parametrize("dry", [True, False])
def test_harmless_command_writes_nothing(work, key, dry):
   if key == ("ui", "glyphs") and not image.has_label_font():
      pytest.skip("시험 글꼴(Pretendard)이 없다")
   argv = _harmless_cases(work)[key]
   before = _snap(work)
   code = cli.main([*argv, "--dry-run"] if dry else argv)
   assert code in (errors.EXIT_OK, errors.EXIT_CHECK_FAIL)
   assert _snap(work) == before


# --- 2. 새로 받는 명령 : 안 쓰고 보고만, would_write = 진짜로 쓴 것 ---


def _case_stitch(work):
   a, b = _two(work)
   return ["stitch", "--in", a, b, "--out", "o.png"], ["o.png"]


def _case_sheet(work):
   a, b = _two(work)
   return ["sheet", "--in", a, b, "--out", "s.png", "--label"], ["s.png"]


def _case_bands(work):
   a, _b = _two(work)
   return ["bands", "--in", a, "--mark", "m.png"], ["m.png"]


def _case_period(work):
   return ["extend", "period", "--in", _strip(work), "--out", "u.png"], ["u.png"]


def _case_ring(work):
   a, _b = _two(work)
   return ["extend", "ring", "--in", a, "--border", "2", "--size", "14x14", "--out", "r.png"], ["r.png"]


def _case_canvas(work):
   a, _b = _two(work)
   return ["extend", "canvas", "--in", a, "--size", "10x14", "--out", "c.png"], ["c.png"]


def _case_style_ref(work):
   a, _b = _two(work)
   return ["style", "ref", "--in", a, "--canvas", "10x10", "--out", "p.png", "--b64", "p.b64"], ["p.png", "p.b64"]


def _case_offset(work):
   t = _png(work / "t.png", _flat(16))
   return ["tile", "offset", "--in", t, "--out", "o.png", "--mask", "m.png", "--band", "4"], ["o.png", "m.png"]


def _case_ui_preview(work):
   a, _b = _two(work)
   return ["ui", "preview", "--in", a, "--border", "2", "--size", "14x14,20x12", "--out", "v.png"], ["v.png"]


def _case_mask(work):
   a, _b = _two(work)
   return ["layers", "mask", "--in", a, "--colors", "#%02X%02X%02X" % helpers.BODY, "--out", "m.png"], ["m.png"]


def _case_view(work):
   test_layers_ops.write_set(work / "set", test_layers_ops.three_layers())
   return ["layers", "view", "--in", str(work / "set"), "--out", "v.png", "--each"], ["v.png"]


def _case_tile_preview(work):
   tiles = work / "tiles"
   tiles.mkdir()
   _png(tiles / "g.png", _flat(8))
   (work / "layout.json").write_text(json.dumps({"size": [3, 2], "weights": {"g": 1}, "seed": 1}), encoding="utf-8")
   return ["tile", "preview", "--layout", "layout.json", "--in", str(tiles), "--out", "p.png"], ["p.png"]


def _case_ldtk(work):
   (work / "map.json").write_text(json.dumps({"width": 1, "height": 1, "grid": [[0]]}), encoding="utf-8")
   (work / "ts.json").write_text(json.dumps({"tile_size": 16, "count": 1, "tiles": [{"x": 0, "y": 0}]}), encoding="utf-8")
   return ["tile", "ldtk", "--map", "map.json", "--tileset", "ts.json", "--out", "l.ldtk"], ["l.ldtk"]


def _case_seam(work):
   tiles = work / "tiles"
   tiles.mkdir()
   _png(tiles / "t.png", _flat(8))
   return ["tile", "seam", "--in", str(tiles), "--sheet", "s.png", "--report", _rep(work, "seam.json")], ["s.png"]


def _case_anchors(work):
   prof = test_cli.write_tiny_profile(work)
   skel = {"points": [{"anim": "walk", "direction": "south", "frame": 0, "point": "head_top", "x": 0.5, "y": 0.24, "z": 10}]}
   (work / "skel.json").write_text(json.dumps(skel), encoding="utf-8")
   argv = ["--profile", prof, "anchors", "--in", str(work), "--rig", "blob", "--from", "skeleton", "--skeleton", "skel.json", "--out", "a.json"]
   return argv, ["a.json"]


def _case_ui_font(work):
   (work / "Text").mkdir()
   (work / "Text" / "a.txt").write_text("가나다", encoding="utf-8")
   argv = ["--profile", "topdown_action", "ui", "font", "--scan-root", str(work), "--scan", "Text", "--out", "charset.txt"]
   return argv, ["charset.txt"]


TAKES_CASES = {
   ("stitch", None): _case_stitch,
   ("sheet", None): _case_sheet,
   ("bands", None): _case_bands,
   ("extend", "period"): _case_period,
   ("extend", "ring"): _case_ring,
   ("extend", "canvas"): _case_canvas,
   ("style", "ref"): _case_style_ref,
   ("tile", "offset"): _case_offset,
   ("ui", "preview"): _case_ui_preview,
   ("layers", "mask"): _case_mask,
   ("layers", "view"): _case_view,
   ("tile", "preview"): _case_tile_preview,
   ("tile", "ldtk"): _case_ldtk,
   ("tile", "seam"): _case_seam,
   ("anchors", None): _case_anchors,
   ("ui", "font"): _case_ui_font,
}


def test_new_takes_are_in_the_table():
   assert set(TAKES_CASES) <= cli.DRY_RUN_TAKES


def _run_json(capsys, argv):
   """--report 가 없는 명령도 있어 stdout JSON 으로 받는다."""
   capsys.readouterr()
   code = cli.main([*argv, "--json"])
   return code, json.loads(capsys.readouterr().out)


@pytest.mark.parametrize("key", sorted(TAKES_CASES, key=lambda k: (k[0], k[1] or "")))
def test_dry_run_writes_nothing_and_lists_real_outputs(work, capsys, key):
   argv, outs = TAKES_CASES[key](work)
   before = _snap(work)
   code, dry = _run_json(capsys, [*argv, "--dry-run"])
   assert code in (errors.EXIT_OK, errors.EXIT_CHECK_FAIL)
   assert _snap(work) == before
   assert dry["dry_run"] is True
   assert sorted(dry["would_write"]) == sorted(str((work / name).resolve()) for name in outs)
   for field in ("out", "mark", "mask", "b64", "sheet"):
      assert dry.get(field) is None

   real_code, real = _run_json(capsys, argv)
   assert real_code == code
   assert "dry_run" not in real and "would_write" not in real      # dry-run 이 아닐 때 보고 꼴은 그대로
   assert all((work / name).is_file() for name in outs)
   assert real.get("status") == dry.get("status")
   assert [w.get("rule") if isinstance(w, dict) else w for w in real.get("warnings", [])] == \
          [w.get("rule") if isinstance(w, dict) else w for w in dry.get("warnings", [])]


def test_period_without_out_dry_run_has_empty_would_write(work):
   assert cli.main(["extend", "period", "--in", _strip(work), "--dry-run", "--report", _rep(work, "r.json")]) == errors.EXIT_OK
   rep = read_json(_rep(work, "r.json"))
   assert rep["dry_run"] is True and rep["would_write"] == [] and rep["period"] == 6


def test_dry_run_still_refuses_overwriting_source(work):
   a, b = _two(work)
   before = _snap(work)
   assert cli.main(["stitch", "--in", a, b, "--out", a, "--dry-run"]) == errors.EXIT_USAGE
   assert cli.main(["extend", "canvas", "--in", a, "--size", "10x14", "--out", a, "--dry-run"]) == errors.EXIT_USAGE
   assert _snap(work) == before


# --- 3. intake ---


def test_intake_dry_run_writes_nothing_and_matches_real(work):
   _two(work)
   src = work / "in"
   src.mkdir()
   for name in ("a.png", "b.png"):
      (work / name).replace(src / name)
   base = ["intake", "--in", str(src), "--out", "o", "--sheet", "s.png"]
   before = _snap(work)
   code = cli.main([*base, "--dry-run", "--report", _rep(work, "dry.json")])
   assert _snap(work) == before
   dry = read_json(_rep(work, "dry.json"))
   assert dry["dry_run"] is True
   assert all(row["out"] is None for row in dry["images"])
   assert dry["steps"]["sheet"]["out"] is None

   assert cli.main([*base, "--report", _rep(work, "real.json")]) == code
   real = read_json(_rep(work, "real.json"))
   assert "dry_run" not in real and "would_write" not in real
   assert (real["status"], real["ran"], real["failed_step"]) == (dry["status"], dry["ran"], dry["failed_step"])
   assert [w["rule"] for w in real["warnings"]] == [w["rule"] for w in dry["warnings"]]
   assert real["steps"]["check"]["status"] == dry["steps"]["check"]["status"]
   wrote = [row["out"] for row in real["images"]] + [real["steps"]["sheet"]["out"]]
   assert sorted(dry["would_write"]) == sorted(wrote)


def test_intake_dry_run_keeps_old_files_out_of_check(work):
   """--out 에 지난 판 PNG 가 있으면 진짜 실행처럼 not_checked 에 적고 검수에서 뺀다. 그 폴더도 안 바뀐다."""
   a, _b = _two(work)
   (work / "o").mkdir()
   _png(work / "o" / "old.png", helpers.blob(4, 4))
   before = _snap(work)
   assert cli.main(["intake", "--in", a, "--out", "o", "--dry-run", "--report", _rep(work, "r.json")]) in (errors.EXIT_OK, errors.EXIT_CHECK_FAIL)
   assert _snap(work) == before
   rep = read_json(_rep(work, "r.json"))
   assert rep["steps"]["check"]["not_checked"] == ["old.png"]
   assert rep["steps"]["check"]["checked_files"] == ["a.png"]
   assert rep["would_write"] == [str((work / "o" / "a.png").resolve())]


def test_intake_dry_run_leaves_no_temp_folder(work, tmp_path, monkeypatch):
   """작업 폴더 스냅숏이 못 보는 시스템 임시 폴더도 본다 — intake 가 만든 arttool-intake* 가 안 남는다."""
   temp = tmp_path / "systemp"
   temp.mkdir()
   monkeypatch.setattr(tempfile, "tempdir", str(temp))
   a, _b = _two(work)
   assert cli.main(["intake", "--in", a, "--out", "o", "--sheet", "s.png", "--dry-run"]) in (errors.EXIT_OK, errors.EXIT_CHECK_FAIL)
   assert list(temp.iterdir()) == []


# --- 리뷰 반영 (2026-10-06) : dry-run 의 status · 경고 · 종료 코드는 진짜 실행과 같다 ---


def _same_exit(argv):
   """dry-run 과 진짜 실행의 종료 코드를 같이 돌려준다 (dry-run 먼저)."""
   return cli.main([*argv, "--dry-run"]), cli.main(argv)


def test_seam_dry_run_checks_sheet_size(work):
   tiles = work / "t"
   tiles.mkdir()
   _png(tiles / "t.png", _flat(8))
   argv = ["tile", "seam", "--in", str(tiles), "--sheet", "ss.png", "--scale", "2000", "--report", _rep(work, "s.json")]
   assert _same_exit(argv) == (errors.EXIT_ERROR, errors.EXIT_ERROR)
   assert not (work / "ss.png").exists()


def test_bands_dry_run_checks_mark_size(work, monkeypatch):
   a, _b = _two(work)
   monkeypatch.setattr(image, "MAX_PIXELS", 300)      # 10x10 의 ×2 눈금 그림이 넘치게
   assert _same_exit(["bands", "--in", a, "--mark", "m.png"]) == (errors.EXIT_ERROR, errors.EXIT_ERROR)


def test_tint_merge_dry_run_check_sheet_size(work):
   """같은 구멍이 앞 판의 tint · merge-colors 비교판에도 있었다."""
   src = work / "in"
   src.mkdir()
   _png(src / "w.png", _flat(4, (230, 230, 230)))
   tint = ["tint", "--in", str(src), "--out", "o", "--colors", "#E85D5D,#5DA0E8", "--sheet", "s.png", "--scale", "3000"]
   assert _same_exit(tint) == (errors.EXIT_ERROR, errors.EXIT_ERROR)
   merge = ["merge-colors", "--in", str(src), "--out", "o2", "--sheet", "s2.png", "--scale", "3000"]
   assert _same_exit(merge) == (errors.EXIT_ERROR, errors.EXIT_ERROR)


def test_intake_dry_run_sees_frames_json_in_out(work):
   """진짜 실행이 --out 을 바로 검수하면 그 폴더의 frames.json 도 본다. dry-run 도 같은 조건으로 본다."""
   a, _b = _two(work)
   (work / "o2").mkdir()
   (work / "o2" / "frames.json").write_text(json.dumps({"frame": [99, 99]}), encoding="utf-8")
   before = _snap(work)
   dry = cli.main(["intake", "--in", a, "--out", "o2", "--dry-run"])
   assert _snap(work) == before
   assert dry == cli.main(["intake", "--in", a, "--out", "o2"]) == errors.EXIT_ERROR


def test_intake_dry_run_report_has_no_temp_path(work, capsys):
   a, b = _two(work)
   src = work / "in"
   src.mkdir()
   for name in ("a.png", "b.png"):
      (work / name).replace(src / name)
   base = ["intake", "--in", str(src), "--out", "o", "--sheet", "s.png"]
   code, dry = _run_json(capsys, [*base, "--dry-run"])
   text = json.dumps(dry, ensure_ascii=False)
   assert "arttool-intake-dry" not in text
   _code, real = _run_json(capsys, base)
   assert [i["path"] for i in dry["steps"]["sheet"]["items"]] == [i["path"] for i in real["steps"]["sheet"]["items"]]


@pytest.mark.parametrize("argv", [
   ["extend", "canvas", "--in", "a.png", "--size", "12x16", "--out", "dir.png"],
   ["stitch", "--in", "a.png", "b.png", "--out", "dir.png"],
   ["cutout", "--in", "a.png", "--out", "dir.png"],
])
def test_out_that_is_existing_folder_is_refused_same_way(work, argv):
   _two(work)
   (work / "dir.png").mkdir()
   before = _snap(work)
   assert _same_exit(argv) == (errors.EXIT_USAGE, errors.EXIT_USAGE)
   assert _snap(work) == before          # dir.png.<pid>.tmp 찌꺼기도 없다


def test_tint_out_name_that_is_existing_folder_is_refused(work):
   """tint 는 --out 폴더 안에 이름을 지어 쓴다. 그 이름이 이미 폴더면 같은 종료 2 (2026-10-06)."""
   src = work / "in"
   src.mkdir()
   _png(src / "w.png", _flat(4, (230, 230, 230)))
   (work / "o" / "w_E85D5D.png").mkdir(parents=True)
   before = _snap(work)
   argv = ["tint", "--in", str(src), "--out", "o", "--colors", "#E85D5D,#5DA0E8"]
   assert _same_exit(argv) == (errors.EXIT_USAGE, errors.EXIT_USAGE)
   assert _snap(work) == before          # 앞 색(5DA0E8)도 안 쓰고 tmp 찌꺼기도 없다


@pytest.mark.parametrize("out", ["map.json", "ts.json", "./MAP.JSON", "절대"])
def test_ldtk_out_on_input_json_is_refused(work, out):
   """tile ldtk 의 --out 이 --map · --tileset 자신이면 덮기 전에 종료 2. 대소문자 · ./ · 절대경로 꼴도 같은 파일로 본다."""
   _case_ldtk(work)
   if out == "절대":
      out = str(work / "map.json")
   before = _snap(work)
   argv = ["tile", "ldtk", "--map", "map.json", "--tileset", "ts.json", "--out", out]
   assert _same_exit(argv) == (errors.EXIT_USAGE, errors.EXIT_USAGE)
   assert _snap(work) == before


@pytest.mark.parametrize("out", ["skel.json", "./SKEL.json"])
def test_anchors_out_on_skeleton_json_is_refused(work, out):
   argv, _outs = _case_anchors(work)
   argv = [*argv[:-1], out]
   before = _snap(work)
   assert _same_exit(argv) == (errors.EXIT_USAGE, errors.EXIT_USAGE)
   assert _snap(work) == before


def test_anchors_out_on_frames_json_is_refused(work):
   """marker 길은 --in 의 frames.json 을 읽는다. --out 이 그 파일이면 종료 2.
   끝까지 성공하는 장면이라 가드가 없으면 (0, 0) 으로 frames.json 을 덮는다 — 종료 코드와 스냅숏 둘 다로 잡는다."""
   prof = test_cli.write_tiny_profile(work)
   helpers.write_singles(work / "raw", helpers.tiny_profile(work))
   assert cli.main(["--profile", prof, "normalize", "--in", "raw", "--out", "build", "--anim", "walk"]) == errors.EXIT_OK
   helpers.write_markers(work / "markers", helpers.tiny_profile(work))
   assert cli.main(["--profile", prof, "anchors", "--in", "build", "--rig", "blob", "--markers", "markers", "--out", "ok.json"]) == errors.EXIT_OK
   (work / "ok.json").unlink()            # 같은 장면이 --out 만 다르면 성공한다
   before = _snap(work)
   argv = ["--profile", prof, "anchors", "--in", "build", "--rig", "blob", "--markers", "markers", "--out", "build/frames.json"]
   assert _same_exit(argv) == (errors.EXIT_USAGE, errors.EXIT_USAGE)
   assert _snap(work) == before


def test_intake_dry_run_still_refuses_sheet_inside_out(work):
   a, _b = _two(work)
   before = _snap(work)
   assert cli.main(["intake", "--in", a, "--out", "o", "--sheet", "o/s.png", "--dry-run"]) == errors.EXIT_USAGE
   assert _snap(work) == before


def test_intake_unstage_replaces_posix_form_too(tmp_path):
   """임시 경로가 `/` 꼴로 보고에 들어가도 --out 경로로 바뀐다 (리뷰 10-06)."""
   from pathlib import Path

   from arttool import intake
   stage, out = tmp_path / "stage", tmp_path / "out"
   report = {"a": str(stage / "x.png"), "b": [stage.as_posix() + "/y.png"], "c": stage.resolve().as_posix() + "/z.png"}
   got = intake._unstage(report, Path(stage), out)
   assert got == {"a": str(out / "x.png"), "b": [out.as_posix() + "/y.png"], "c": out.as_posix() + "/z.png"}
