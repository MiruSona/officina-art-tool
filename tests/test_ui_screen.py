import pytest

import test_ui_icons
from arttool import profile
from arttool.errors import ArtToolError
from arttool.jsonio import write_json
from arttool.ui import bake_ui, check_ui, frame, icons, screen, uss, uxml

PAUSE_MENU = {
   "screen": "pause_menu",
   "root": {
      "id": "root",
      "type": "column",
      "pad": 8,
      "gap": 4,
      "bg": "panel_normal",
      "size": [120, 80],
      "children": [
         {"id": "title", "type": "label", "text": "멈춤"},
         {"id": "btn_resume", "type": "button", "text": "이어하기", "bg": "button_normal"},
         {"id": "spacer", "type": "spacer", "grow": True},
         {"id": "btn_quit", "type": "button", "text": "나가기", "bg": "button_normal"},
      ],
   },
}

WANT_UXML = """<ui:UXML xmlns:ui="UnityEngine.UIElements">
  <ui:VisualElement name="root" class="ui-column bg-panel_normal">
    <ui:Label name="title" text="멈춤" class="ui-label" />
    <ui:Button name="btn_resume" text="이어하기" class="ui-button bg-button_normal" />
    <ui:VisualElement name="spacer" class="ui-spacer" />
    <ui:Button name="btn_quit" text="나가기" class="ui-button bg-button_normal" />
  </ui:VisualElement>
</ui:UXML>
"""


def prof():
   return profile.load_profile("topdown_action")


def test_uxml_matches_design():
   assert uxml.to_uxml(PAUSE_MENU["root"]) == WANT_UXML


def test_validate_passes():
   assert screen.validate(PAUSE_MENU["root"])["id"] == "root"


def test_duplicate_id():
   bad = {"id": "a", "type": "column", "children": [{"id": "a", "type": "label", "text": "x"}]}
   with pytest.raises(ArtToolError, match="id 가 겹친다"):
      screen.validate(bad)


def test_unknown_type():
   with pytest.raises(ArtToolError, match="모르는 type"):
      screen.validate({"id": "a", "type": "scroll"})


def test_unknown_key():
   with pytest.raises(ArtToolError, match="모르는 칸"):
      screen.validate({"id": "a", "type": "label", "색": 1})


def test_label_cannot_have_children():
   bad = {"id": "a", "type": "label", "text": "x", "children": [{"id": "b", "type": "label", "text": "y"}]}
   with pytest.raises(ArtToolError, match="children 을 못 가진다"):
      screen.validate(bad)


def test_text_only_on_label_and_button():
   with pytest.raises(ArtToolError, match="text 는 label"):
      screen.validate({"id": "a", "type": "column", "text": "x"})


def test_bad_pad_and_size():
   with pytest.raises(ArtToolError, match="pad 는"):
      screen.validate({"id": "a", "type": "column", "pad": [1, 2]})
   with pytest.raises(ArtToolError, match="size 는"):
      screen.validate({"id": "a", "type": "column", "size": [1, 2, 3]})


def test_missing_id():
   with pytest.raises(ArtToolError, match="id 가 없는"):
      screen.validate({"type": "column"})


def test_load_needs_screen_name(tmp_path):
   write_json(tmp_path / "s.json", {"root": {"id": "a", "type": "column"}})
   with pytest.raises(ArtToolError, match="screen 이름이 없다"):
      screen.load(tmp_path / "s.json")


def test_screen_uss_rules():
   text = uss.screen_uss(prof(), PAUSE_MENU["root"])
   assert "#root { padding: 8px; width: 120px; height: 80px; }" in text
   assert "#root > * { margin-bottom: 4px; }" in text
   assert "#spacer { flex-grow: 1; }" in text
   assert ".ui-spacer { flex-grow: 1; }" in text


def test_row_gap_uses_margin_right():
   tree = {"id": "bar", "type": "row", "gap": 2, "children": [{"id": "a", "type": "label", "text": "x"}]}
   assert "#bar > * { margin-right: 2px; }" in uss.screen_uss(prof(), tree)


def test_pad_four_values():
   tree = {"id": "a", "type": "column", "pad": [1, 2, 3, 4]}
   assert "padding: 1px 2px 3px 4px;" in uss.screen_uss(prof(), tree)


def test_build_writes_files(tmp_path):
   spec = tmp_path / "pause_menu.json"
   write_json(spec, PAUSE_MENU)
   result = screen.build(prof(), spec, tmp_path / "out")

   assert result["screen"] == "pause_menu"
   assert result["nodes"] == 5
   assert (tmp_path / "out" / "pause_menu.uxml").read_text(encoding="utf-8") == WANT_UXML
   assert (tmp_path / "out" / "pause_menu.uss").is_file()


def test_build_checks_backgrounds(tmp_path):
   p = prof()
   build = tmp_path / "ui"
   frame.build(p, "panel", (16, 16), build)
   frame.build(p, "button", (32, 16), build)
   icons.cut(p, test_ui_icons.make_sheet(tmp_path), build)
   write_json(build / "check.json", check_ui.run(build, p))
   out = tmp_path / "unity"
   bake_ui.bake(p, build, out)

   spec = tmp_path / "pause_menu.json"
   write_json(spec, PAUSE_MENU)
   assert screen.build(p, spec, out)["screen"] == "pause_menu"


def test_build_rejects_unknown_background(tmp_path):
   p = prof()
   build = tmp_path / "ui"
   frame.build(p, "panel", (16, 16), build)
   write_json(build / "check.json", check_ui.run(build, p))
   out = tmp_path / "unity"
   bake_ui.bake(p, build, out)

   spec = tmp_path / "s.json"
   write_json(spec, {"screen": "s", "root": {"id": "root", "type": "column", "bg": "no_such_frame"}})
   with pytest.raises(ArtToolError, match="없는 bg"):
      screen.build(p, spec, out)
