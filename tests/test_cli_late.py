"""갈래 0 의 틀 — 새 명령의 인자 등록 · 늦은 부르기 · layers 묶음 · check 새 인자.

새 명령 모듈은 다른 갈래가 만든다. 그래서 여기서는 「없는 모듈」을 표에 꽂아 틀만 본다.
갈래가 모듈을 만들어도 이 시험은 그대로 통과해야 한다.
"""

import sys

import pytest

import helpers
from arttool import cli, errors, image
from arttool.jsonio import read_json

# LATE 표의 명령마다 「최소 인자」와 거기서 나와야 하는 args 칸. 갈래가 맞출 약속이다.
CONTRACT = [
   (["cutout", "--in", "raw", "--out", "clean"], {"in_dir": "raw", "out_dir": "clean", "key": "edge", "tol": 10, "shave": 0, "report": None}),
   (["trim", "--in", "raw", "--out", "t"], {"in_dir": "raw", "out_dir": "t", "pad": 0, "square": False, "common": False, "report": None}),
   (
      ["ui", "preview", "--in", "p.png", "--size", "300x62,96x48", "--out", "p_out.png"],
      {"in_file": "p.png", "border": None, "size": "300x62,96x48", "out_file": "p_out.png", "mode": "stretch", "scale": 1},
   ),
   (
      ["sheet", "--in", "a.png", "b", "--out", "s.png"],
      {"in_paths": ["a.png", "b"], "out_file": "s.png", "kinds": "zoom", "scale": "auto", "tile": 2, "bg": "checker", "label": False, "report": None},
   ),
   (["template", "list"], {"sub": "list", "kind": None}),
   (["template", "show", "char_small", "--size", "32x32"], {"sub": "show", "name": "char_small", "size": "32x32", "preset": None, "base": None, "material": None}),
   (
      ["template", "render", "fx_ring_burst", "--size", "16x16", "--out", "g"],
      {"sub": "render", "name": "fx_ring_burst", "size": "16x16", "out_dir": "g", "preset": None, "scale": None, "over": None, "base": None, "material": None},
   ),
   (
      ["style", "extract", "--in", "a", "--in", "b", "--out", "s"],
      {"sub": "extract", "in_dirs": ["a", "b"], "out_dir": "s", "name": None, "ramp_len": None, "max_colors": None, "mode": "auto", "with_backgrounds": False, "force": False, "by_folder": False},
   ),
   (
      ["layers", "diff", "--base", "b.png", "--in", "inp", "--out", "set"],
      {"sub": "diff", "base": "b.png", "in_dir": "inp", "out_dir": "set", "template": None, "carve": "report", "report": None},
   ),
   (
      ["layers", "mask", "--in", "b.png", "--colors", "#112233,#445566", "--out", "m.png"],
      {"sub": "mask", "in_file": "b.png", "colors": "#112233,#445566", "grow": 0, "out_file": "m.png"},
   ),
   (
      ["layers", "view", "--in", "set", "--out", "v.png"],
      {"sub": "view", "in_dir": "set", "only": None, "hide": None, "each": False, "out_file": "v.png", "scale": 1, "report": None},
   ),
   (["layers", "check", "--in", "set"], {"sub": "check", "in_dir": "set", "original": None, "template": None, "report": None}),
   (
      ["layers", "export", "--in", "set", "--out", "u"],
      {"sub": "export", "in_dir": "set", "out_dir": "u", "flat": False, "each": False, "trim_common": False, "anchor": "bbox_bottom_center", "report": None},
   ),
   (
      ["layers", "diff", "--base", "b.png", "--in", "inp", "--out", "set", "--carve", "common"],
      {"sub": "diff", "carve": "common"},
   ),
   (
      ["intake", "--in", "raw", "--out", "clean"],
      {"in_dir": "raw", "out_dir": "clean", "key": "edge", "tol": 10, "shave": 0, "pad": 0, "square": False, "template": None, "sheet": None, "report": None,
       "no_cutout": False, "no_trim": False, "no_check": False},
   ),
   # 피드백 후속 설계(2026-10-04) 새 명령 10개
   (
      ["style", "ref", "--in", "a.png", "--canvas", "128x128", "--out", "r.png"],
      {"sub": "ref", "in_file": "a.png", "canvas": "128x128", "out_file": "r.png", "crop": None, "colors": 32, "b64": None, "max_kb": 12.0, "report": None},
   ),
   (["bands", "--in", "raw.png"], {"in_file": "raw.png", "axis": "y", "top": 8, "mark": None, "report": None}),
   (
      ["stitch", "--in", "top.png:0-180", "mid.png", "--out", "w.png"],
      {"in_specs": ["top.png:0-180", "mid.png"], "out_file": "w.png", "axis": "y", "report": None},
   ),
   (
      ["tile", "offset", "--in", "g.png", "--out", "s.png", "--mask", "m.png"],
      {"sub": "offset", "in_file": "g.png", "out_file": "s.png", "mask": "m.png", "band": 16, "report": None},
   ),
   (
      ["extend", "period", "--in", "f.png"],
      {"sub": "period", "in_file": "f.png", "axis": "x", "tile": None, "out_file": None, "fit": None, "report": None},
   ),
   (
      ["extend", "ring", "--in", "r.png", "--border", "3", "--size", "40x20", "--out", "o.png"],
      {"sub": "ring", "in_file": "r.png", "border": "3", "size": "40x20", "out_file": "o.png", "snap": False, "report": None},
   ),
   (
      ["extend", "canvas", "--in", "bg.png", "--size", "360x800", "--out", "o.png"],
      {"sub": "canvas", "in_file": "bg.png", "size": "360x800", "out_file": "o.png", "anchor": "bottom", "band": 1, "report": None},
   ),
   (
      ["ui", "glyphs", "--font", "f.ttf", "--text", "가—"],
      {"sub": "glyphs", "font": "f.ttf", "text": "가—", "text_file": None, "size": 16, "report": None},
   ),
   (
      ["reline", "--in", "raw", "--out", "o"],
      # pick · tol 기본(dark · 40)은 reline.run 이 채운다 — 안 준 것과 --from 과 같이 준 것을 가리려고 None 으로 받는다
      {"in_dir": "raw", "out_dir": "o", "color": None, "pick": None, "scope": "ring", "tol": None, "from_colors": None, "report": None},
   ),
   (
      ["tint", "--in", "white", "--colors", "#E85D5D,#5DA0E8", "--out", "t"],
      {"in_dir": "white", "colors": "#E85D5D,#5DA0E8", "out_dir": "t", "sheet": None, "scale": 4, "report": None},
   ),
   # 이미 LATE 인 명령에 붙인 새 인자
   (
      ["layers", "diff", "--base", "b.png", "--in", "inp", "--out", "set", "--drop", "hair:#F2C9A0,#3A5BD9", "--drop", "hat:#112233"],
      {"sub": "diff", "drop": ["hair:#F2C9A0,#3A5BD9", "hat:#112233"], "drop_tol": 24},
   ),
   (["layers", "diff", "--base", "b.png", "--in", "inp", "--out", "set"], {"drop": None, "drop_tol": 24}),
   (["sheet", "--in", "a.png", "--out", "s.png"], {"grid": 0, "grid_color": None}),
   (["sheet", "--in", "a.png", "--out", "s.png", "--grid", "8", "--grid-color", "#00FF00"], {"grid": 8, "grid_color": "#00FF00"}),
]


@pytest.mark.parametrize("argv, expected", CONTRACT, ids=[" ".join(a[:2]) for a, _ in CONTRACT])
def test_late_command_args(argv, expected):
   args = cli.build_parser().parse_args(argv)
   for name, value in expected.items():
      assert getattr(args, name) == value, name
   assert cli._command_key(args) in cli.LATE


def test_every_late_entry_has_a_contract():
   """표에 명령을 더하면 위 CONTRACT 에도 더해야 한다 (갈래가 볼 약속이 빠지지 않게)."""
   covered = {cli._command_key(cli.build_parser().parse_args(a)) for a, _ in CONTRACT}
   assert covered == set(cli.LATE)


def test_check_new_args_parse():
   args = cli.build_parser().parse_args(["check", "--in", "x", "--report", "r.json", "--no-warn", "--mode", "background", "--template", "t.json"])
   assert (args.no_warn, args.mode, args.template) == (True, "background", "t.json")
   args = cli.build_parser().parse_args(["check", "--in", "x", "--report", "r.json"])
   assert (args.no_warn, args.mode, args.template) == (False, "auto", None)


@pytest.mark.parametrize("carve", ["keep", "nope"])
def test_carve_choices_are_report_common_apply(carve):
   with pytest.raises(SystemExit) as caught:
      cli.build_parser().parse_args(["layers", "diff", "--base", "b.png", "--in", "i", "--out", "o", "--carve", carve])
   assert caught.value.code == errors.EXIT_USAGE


def test_view_only_and_hide_together_rejected():
   with pytest.raises(SystemExit) as caught:
      cli.build_parser().parse_args(["layers", "view", "--in", "s", "--out", "v.png", "--only", "a", "--hide", "b"])
   assert caught.value.code == errors.EXIT_USAGE


def test_missing_module_is_not_implemented(monkeypatch, capsys):
   monkeypatch.setitem(cli.LATE, ("cutout", None), ("arttool._no_such_module_for_test", "run"))
   code = cli.main(["cutout", "--in", "raw", "--out", "clean"])
   assert code == errors.EXIT_USAGE
   assert "아직 구현 안 됨" in capsys.readouterr().err


def test_missing_package_is_not_implemented(monkeypatch, capsys):
   monkeypatch.setitem(cli.LATE, ("cutout", None), ("arttool._no_such_pkg_for_test.cutout", "run"))
   assert cli.main(["cutout", "--in", "raw", "--out", "clean"]) == errors.EXIT_USAGE
   assert "아직 구현 안 됨" in capsys.readouterr().err


def test_missing_function_is_not_implemented(monkeypatch, capsys):
   monkeypatch.setitem(cli.LATE, ("cutout", None), ("arttool.errors", "run"))
   assert cli.main(["cutout", "--in", "raw", "--out", "clean"]) == errors.EXIT_USAGE
   assert "아직 구현 안 됨" in capsys.readouterr().err


def _fake_module(tmp_path, monkeypatch, name, body):
   (tmp_path / f"{name}.py").write_text(body, encoding="utf-8")
   monkeypatch.syspath_prepend(str(tmp_path))
   monkeypatch.delitem(sys.modules, name, raising=False)


def test_broken_import_inside_module_is_real_error(tmp_path, monkeypatch, capsys):
   """모듈은 있는데 그 안에서 다른 것이 없으면 「아직 구현 안 됨」으로 가리지 않는다."""
   _fake_module(tmp_path, monkeypatch, "fake_late_broken", "import arttool_no_such_dependency_xyz\n")
   monkeypatch.setitem(cli.LATE, ("cutout", None), ("fake_late_broken", "run"))
   assert cli.main(["cutout", "--in", "raw", "--out", "clean"]) == errors.EXIT_ERROR
   assert "아직 구현 안 됨" not in capsys.readouterr().err


def test_late_run_writes_report_and_maps_status(tmp_path, monkeypatch, capsys):
   body = (
      "def run(args):\n"
      "   return {'status': args.key, 'in': args.in_dir}\n"
   )
   _fake_module(tmp_path, monkeypatch, "fake_late_ok", body)
   monkeypatch.setitem(cli.LATE, ("cutout", None), ("fake_late_ok", "run"))

   report = tmp_path / "r.json"
   assert cli.main(["cutout", "--in", "raw", "--out", "clean", "--key", "warn", "--report", str(report)]) == errors.EXIT_OK
   assert read_json(report) == {"status": "warn", "in": "raw"}
   assert cli.main(["cutout", "--in", "raw", "--out", "clean", "--key", "fail"]) == errors.EXIT_CHECK_FAIL


def test_human_output_counts_warnings(tmp_path, monkeypatch, capsys):
   body = "def run(args):\n   return {'status': 'ok', 'warnings': [{'rule': 'x'}], 'must_failed': ['canvas']}\n"
   _fake_module(tmp_path, monkeypatch, "fake_late_warn", body)
   monkeypatch.setitem(cli.LATE, ("trim", None), ("fake_late_warn", "run"))
   assert cli.main(["trim", "--in", "raw", "--out", "t"]) == errors.EXIT_OK
   out = capsys.readouterr().out
   assert "경고 1건" in out and "꼭 지킬 것 어김 1건 : canvas" in out


def test_layers_compose_matches_old_layers(tmp_path):
   source = tmp_path / "parts"
   for name, color in (("body", (61, 92, 155)), ("hair", (192, 160, 68))):
      folder = source / name
      folder.mkdir(parents=True)
      arr = image.new(16, 16)
      arr[0 if name == "hair" else 1, 0] = (*color, 255)
      image.save(folder / "walk.png", arr)

   code = cli.main(
      ["--profile", "topdown_action", "layers", "compose", "--rig", "humanoid_lpc", "--in", str(source), "--out", str(tmp_path / "m"), "--anim", "walk"]
   )
   assert code == errors.EXIT_OK
   assert image.count_colors(image.load(tmp_path / "m" / "walk.png")) == 2


def test_old_layers_line_is_rejected(tmp_path):
   """옛 줄은 살리지 않는다 (설계 10-4, 사용자 확정 2026-10-04). argparse 가 종료 2."""
   with pytest.raises(SystemExit) as caught:
      cli.main(["layers", "--profile", "topdown_action", "--rig", "humanoid_lpc", "--in", str(tmp_path), "--out", str(tmp_path / "m")])
   assert caught.value.code == errors.EXIT_USAGE


def _loose_dir(tmp_path):
   loose = tmp_path / "loose"
   loose.mkdir()
   image.save(loose / "berry.png", helpers.blob(8, 8))
   return loose


def test_check_new_args_before_check_supports_them(tmp_path, monkeypatch, capsys):
   """check.run 이 새 칸을 아직 안 받으면 새 인자는 「아직 구현 안 됨」, 안 주면 예전 그대로 돈다."""
   from arttool import check as check_mod

   def old_run(prof, build_dir, no_ramps=False):
      return {"status": "ok"}

   monkeypatch.setattr(check_mod, "run", old_run)
   loose = _loose_dir(tmp_path)
   base = ["--profile", "topdown_action", "check", "--in", str(loose), "--report", str(tmp_path / "c.json")]
   assert cli.main(base) == errors.EXIT_OK
   assert cli.main(base + ["--no-warn"]) == errors.EXIT_USAGE
   assert "아직 구현 안 됨" in capsys.readouterr().err


def test_report_must_be_json_and_not_an_input(tmp_path, capsys):
   """--report 가 입력 PNG 를 JSON 으로 덮던 사고를 막는다 (리뷰 R1-M5). 거절하면 원본은 그대로다."""
   loose = _loose_dir(tmp_path)
   png = loose / "berry.png"
   before = png.read_bytes()
   base = ["--profile", "topdown_action", "check", "--in", str(png)]
   assert cli.main(base + ["--report", str(png)]) == errors.EXIT_USAGE
   assert ".json" in capsys.readouterr().err
   assert png.read_bytes() == before
   # 늦은 부르기 명령도 같다 — 출력 그림과 같은 이름은 .json 이 아니라 막힌다
   assert cli.main(["trim", "--in", str(loose), "--out", str(tmp_path / "t"), "--report", str(png)]) == errors.EXIT_USAGE
   assert png.read_bytes() == before
   # .json 이어도 읽는 파일과 같으면 거절
   spec = tmp_path / "spec.json"
   spec.write_text("{}", encoding="utf-8")
   assert cli.main(["layers", "check", "--in", str(loose), "--template", str(spec), "--report", str(spec)]) == errors.EXIT_USAGE
   assert spec.read_text(encoding="utf-8") == "{}"
   assert cli.main(base + ["--report", str(tmp_path / "ok.JSON")]) == errors.EXIT_OK


def test_layers_view_takes_report():
   args = cli.build_parser().parse_args(["layers", "view", "--in", "s", "--out", "v.png", "--report", "v.json"])
   assert args.report == "v.json"


def test_reline_from_through_cli(tmp_path):
   """reline --from 은 CLI 를 거쳐 돈다. --pick · --tol 과 같이 주면 종료 2."""
   src = tmp_path / "in"
   src.mkdir()
   image.save(src / "a.png", helpers.put_on_canvas(helpers.blob(8, 8), 10, 10, 1, 1))
   base = ["reline", "--in", str(src), "--out", str(tmp_path / "o"), "--from", "#%02X%02X%02X" % helpers.DARK, "--color", "#000000"]
   assert cli.main(base + ["--report", str(tmp_path / "r.json")]) == errors.EXIT_OK
   report = read_json(tmp_path / "r.json")
   assert report["from"] == ["#%02X%02X%02X" % helpers.DARK] and report["images"][0]["changed"] > 0
   assert cli.main(base + ["--pick", "all"]) == errors.EXIT_USAGE
   assert cli.main(base + ["--tol", "10"]) == errors.EXIT_USAGE
   assert cli.main(["reline", "--in", str(src), "--out", str(tmp_path / "o2"), "--from", "#GGGGGG"]) == errors.EXIT_USAGE


def test_reline_without_pick_tol_reports_defaults(tmp_path):
   """인자 없이 부르면 보고에 기본 pick dark · tol 40 이 실린다 (argparse 기본을 None 으로 바꾼 뒤에도)."""
   src = tmp_path / "in"
   src.mkdir()
   image.save(src / "a.png", helpers.put_on_canvas(helpers.blob(8, 8), 10, 10, 1, 1))
   assert cli.main(["reline", "--in", str(src), "--out", str(tmp_path / "o"), "--report", str(tmp_path / "r.json")]) == errors.EXIT_OK
   report = read_json(tmp_path / "r.json")
   assert (report["pick"], report["tol"], report["from"]) == ("dark", 40, None)


def test_check_new_args_are_passed_when_supported(tmp_path, monkeypatch):
   from arttool import check as check_mod

   seen = {}

   def new_run(prof, build_dir, no_ramps=False, *, warn=True, mode="auto", template=None):
      seen.update(warn=warn, mode=mode, template=template)
      return {"status": "ok"}

   monkeypatch.setattr(check_mod, "run", new_run)
   loose = _loose_dir(tmp_path)
   argv = ["--profile", "topdown_action", "check", "--in", str(loose), "--report", str(tmp_path / "c.json"), "--no-warn", "--mode", "sprite", "--template", "t.json"]
   assert cli.main(argv) == errors.EXIT_OK
   assert seen == {"warn": False, "mode": "sprite", "template": "t.json"}
