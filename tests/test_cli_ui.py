import test_ui_icons
import test_ui_screen
from arttool import cli, errors
from arttool.jsonio import read_json, write_json


def run(*args):
   return cli.main(list(args))


def test_ui_frame_and_check_and_bake(tmp_path, capsys):
   build = tmp_path / "ui"
   for kind in ("panel", "button"):
      assert run("--profile", "topdown_action", "ui", "frame", "--kind", kind, "--out", str(build)) == 0

   sheet = test_ui_icons.make_sheet(tmp_path)
   assert run("--profile", "topdown_action", "ui", "icons", "--in", str(sheet), "--out", str(build)) == 0

   report = build / "check.json"
   assert run("--profile", "topdown_action", "ui", "check", "--in", str(build), "--report", str(report)) == 0
   assert read_json(report)["status"] == "ok"

   out = tmp_path / "unity"
   assert run("--profile", "topdown_action", "ui", "bake", "--in", str(build), "--out", str(out), "--namespace", "Game.UI") == 0
   assert (out / "ui_manifest.json").is_file()
   assert (out / "ui.uss").is_file()
   assert (out / "Editor" / "UiImportSettings.cs").is_file()


def test_ui_frame_size_argument(tmp_path):
   build = tmp_path / "ui"
   assert run("--profile", "topdown_action", "ui", "frame", "--kind", "bar", "--size", "32x8", "--out", str(build)) == 0
   entry = next(f for f in read_json(build / "border.json")["frames"] if f["name"] == "bar_normal")
   assert entry["size"] == [32, 8]
   assert entry["border"] == [2, 0, 2, 0]


def test_ui_check_fail_exit_code(tmp_path):
   build = tmp_path / "ui"
   run("--profile", "topdown_action", "ui", "frame", "--kind", "panel", "--out", str(build))
   data = read_json(build / "border.json")
   data["frames"] = [f for f in data["frames"] if f["state"] != "pressed"]
   write_json(build / "border.json", data)

   code = run("--profile", "topdown_action", "ui", "check", "--in", str(build), "--report", str(build / "check.json"))
   assert code == errors.EXIT_CHECK_FAIL


def test_ui_bake_needs_check(tmp_path, capsys):
   build = tmp_path / "ui"
   run("--profile", "topdown_action", "ui", "frame", "--kind", "panel", "--out", str(build))
   code = run("--profile", "topdown_action", "ui", "bake", "--in", str(build), "--out", str(tmp_path / "unity"))
   assert code == errors.EXIT_CHECK_FAIL
   assert "검수 보고" in capsys.readouterr().err


def test_ui_import_cli(tmp_path):
   import test_ui_ninepatch
   from arttool import image

   raw = tmp_path / "raw"
   raw.mkdir()
   image.save(raw / "window_normal.9.png", test_ui_ninepatch.make_nine())
   out = tmp_path / "ui"
   assert run("--profile", "topdown_action", "ui", "import", "--in", str(raw), "--out", str(out)) == 0
   assert (out / "window_normal.png").is_file()


def test_ui_screen_cli(tmp_path):
   spec = tmp_path / "pause_menu.json"
   write_json(spec, test_ui_screen.PAUSE_MENU)
   out = tmp_path / "unity"
   assert run("--profile", "topdown_action", "ui", "screen", "--spec", str(spec), "--out", str(out)) == 0
   assert (out / "pause_menu.uxml").read_text(encoding="utf-8") == test_ui_screen.WANT_UXML


def test_ui_font_cli(tmp_path):
   folder = tmp_path / "Text"
   folder.mkdir()
   (folder / "a.txt").write_text("가나다", encoding="utf-8")
   out = tmp_path / "charset.txt"
   assert run("--profile", "topdown_action", "ui", "font", "--scan-root", str(tmp_path),
              "--scan", "Text", "--out", str(out)) == 0
   assert "가" in out.read_text(encoding="utf-8")


def test_ui_icons_loose_folder_cli(tmp_path):
   """--in 이 폴더면 자르지 않고 낱장을 그대로 들인다."""
   folder = test_ui_icons.make_loose(tmp_path, side=32, count=2)
   out = tmp_path / "ui"
   assert run("--profile", "topdown_action", "ui", "icons", "--in", str(folder), "--out", str(out), "--fit", "32") == 0

   data = read_json(out / "icons.json")
   assert [e["name"] for e in data["icons"]] == ["berry_0", "berry_1"]
