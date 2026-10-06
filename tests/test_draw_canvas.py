import json

import numpy as np
import pytest

from arttool import image, layerset
from arttool.draw import Canvas, pick, shade
from arttool.errors import ArtToolError
from arttool.palette import load_ramps

CHAR_LAYERS = [
   {"name": "body", "kind": "body"},
   {"name": "face", "kind": "face", "exclusive_with": ["hair"]},
   {"name": "hair", "kind": "hair"},
   {"name": "deco", "kind": "deco", "optional": True},
]


def _ramps(tmp_path, outline="#101018"):
   data = {"version": 1, "name": "t", "ramp_len": 4, "outline": outline,
           "ramps": {"skin": ["#402020", "#804040", "#C08060", "#F0C0A0"], "hair": ["#102040", "#204080", "#3060C0", "#80A0F0"]}}
   path = tmp_path / "pal.json"
   path.write_text(json.dumps(data), encoding="utf-8")
   return path


def test_default_single_body_layer():
   c = Canvas(16)
   assert c.names == ["body"] and c.size == (16, 16)
   assert c["body"].arr.shape == (16, 16, 4)


def test_layers_by_kind_names_and_bad_name():
   c = Canvas((8, 12), layers=["body", "hair", ("eyes", "face")])
   assert c.names == ["body", "hair", "eyes"] and c["eyes"].kind == "face"
   with pytest.raises(ArtToolError, match="kind"):
      Canvas(8, layers=["eyes"])
   with pytest.raises(ArtToolError, match="없는 겹"):
      Canvas(8)["nope"]


def test_size_required_and_mismatch(tmp_path):
   with pytest.raises(ArtToolError, match="크기"):
      Canvas()
   lay = {"version": 1, "canvas": [32, 32], "layers": CHAR_LAYERS, "items": []}
   assert Canvas(template=lay).size == (32, 32)
   with pytest.raises(ArtToolError, match="다르다"):
      Canvas(16, template=lay)


def test_template_folder_reads_layers_guide_style_and_ramps(tmp_path, monkeypatch):
   monkeypatch.setenv("ARTTOOL_PALETTES", str(tmp_path))   # 3판 : 템플릿 램프 절대경로는 팔레트 뿌리 안이어야 믿는다
   pal = _ramps(tmp_path)
   guide_dir = tmp_path / "guide"
   guide_dir.mkdir()
   tpl = {"name": "char_small", "size": [32, 32], "layers": CHAR_LAYERS,
          "guide": {"lines": {"eye": 14}, "boxes": {"head": [8, 4, 24, 18]}},
          "check": {"style": {"outline": "selout", "light": "top_right"}, "palette": {"ramps_file": str(pal)}}}
   (guide_dir / "template.json").write_text(json.dumps(tpl), encoding="utf-8")
   c = Canvas(template=guide_dir)
   assert c.names == ["body", "face", "hair", "deco"]
   assert c.template_name == "char_small"
   assert c.guide.y("eye") == 14 and c.guide.box("head") == (8, 4, 24, 18)
   assert c.outline_mode == "selout" and c.light == "top_right"
   assert c.ramps is not None and c.pick("skin", 2) == "#C08060"


def test_template_name_unknown(tmp_path):
   with pytest.raises(ArtToolError, match="템플릿"):
      Canvas(template="char_small_없는것")
   with pytest.raises(ArtToolError, match="템플릿을 못 찾았다"):
      Canvas(template="no_such_template")


def test_no_soft_alpha_colors():
   layer = Canvas(8)["body"]
   with pytest.raises(ArtToolError, match="반투명"):
      layer.dot(1, 1, (255, 0, 0, 128))
   layer.dot(1, 1, (255, 0, 0, 255)).box(2, 2, 5, 5, "#00FF00")
   assert set(np.unique(layer.arr[:, :, 3]).tolist()) == {0, 255}


def test_drawing_calls_chain_and_hit_cells():
   b = Canvas(16)["body"]
   b.box(0, 0, 4, 4, "#FF0000").line(0, 10, 5, 11, "#00FF00").ellipse(8, 8, 16, 16, "#0000FF")
   assert b.px(0, 0) == "#FF0000" and b.px(4, 4) is None
   assert b.px(0, 10) == "#00FF00" and b.px(5, 11) == "#00FF00"
   assert b.px(12, 12) == "#0000FF"
   b.fill(0, 0, "#FFFFFF")
   assert b.px(3, 3) == "#FFFFFF" and b.px(0, 10) == "#00FF00"
   b.erase()
   assert not b.mask().any()


def test_mirror_and_recolor():
   b = Canvas(6)["body"]
   b.dot(0, 2, "#112233").dot(1, 3, "#112233")
   b.mirror()
   assert b.px(5, 2) == "#112233" and b.px(4, 3) == "#112233"
   b.recolor("#112233", "#445566")
   assert b.px(5, 2) == "#445566"


def test_merged_stacks_bottom_to_top():
   c = Canvas(8, layers=["body", "hair"])
   c["body"].box(0, 0, 8, 8, "#111111")
   c["hair"].box(0, 0, 8, 2, "#222222")
   m = c.merged()
   assert tuple(m[0, 0, :3]) == (0x22, 0x22, 0x22) and tuple(m[5, 5, :3]) == (0x11, 0x11, 0x11)
   assert tuple(c.merged(only=["body"])[0, 0, :3]) == (0x11, 0x11, 0x11)


def test_pick_and_shade(tmp_path):
   ramps = load_ramps(_ramps(tmp_path))
   assert pick(ramps, "hair", 0) == "#102040" and pick(ramps, "hair", -1) == "#80A0F0"
   with pytest.raises(ArtToolError, match="칸"):
      pick(ramps, "hair", 4)
   with pytest.raises(ArtToolError, match="팔레트가 없다"):
      Canvas(8).pick("skin", 1)
   assert len(shade("#C08060", 5)) == 5


def test_report_palette_guide_exclusive_empty(tmp_path):
   c = Canvas(16, template={"version": 1, "canvas": [16, 16], "layers": CHAR_LAYERS, "items": []}, ramps=_ramps(tmp_path))
   assert {w["rule"] for w in c.report()["warnings"]} == {"empty"}  # 다 비었다 (deco 는 optional)
   c["body"].box(2, 2, 14, 14, c.pick("skin", 2))
   c["face"].dot(5, 6, "#123456")          # 팔레트 밖
   c["hair"].box(2, 2, 14, 7, c.pick("hair", 2))   # face 와 (5, 6) 에서 겹침
   c["hair"].dot(0, 0, "#FF00FF")          # 가이드 색
   rep = c.report()
   rules = {w["rule"]: w for w in rep["warnings"]}
   assert rep["status"] == "warn"
   assert set(rules) == {"palette", "guide_color", "exclusive"}
   assert {r["color"] for r in rules["palette"]["items"]} == {"#123456", "#FF00FF"}
   assert rules["exclusive"]["items"][0]["layers"] == ["face", "hair"] and rules["exclusive"]["items"][0]["count"] == 1


def test_report_ok_when_clean(tmp_path):
   c = Canvas(8, ramps=_ramps(tmp_path))
   c["body"].box(1, 1, 7, 7, c.pick("skin", 1))
   assert c.report() == {"status": "ok", "canvas": [8, 8], "layers": {"body": 36}, "palette": "t", "warnings": []}


def test_save_writes_layerset_and_round_trips(tmp_path):
   c = Canvas(16, template={"version": 1, "canvas": [16, 16], "layers": CHAR_LAYERS, "items": [], "template": "char_small"})
   c["body"].box(3, 3, 13, 15, "#C08060")
   c["hair"].box(3, 2, 13, 6, "#3060C0")
   out = c.save(tmp_path / "set")
   assert out.name == "layers.json"
   lay = layerset.load(tmp_path / "set")
   assert lay.names() == ["body", "face", "hair", "deco"] and lay.items == ["idle"] and lay.template == "char_small"
   got = layerset.read_item(tmp_path / "set", lay, "idle")
   assert set(got) == {"body", "face", "hair", "deco"}       # 빈 겹도 투명 그림으로 쓴다
   assert (got["hair"] == c["hair"].arr).all()

   # 같은 묶음에 다른 그림을 더한다
   c.save(tmp_path / "set", item="walk_0")
   assert layerset.load(tmp_path / "set").items == ["idle", "walk_0"]

   back = Canvas.open(tmp_path / "set")
   assert (back.merged() == c.merged()).all() and back.template_name == "char_small"


def test_save_refuses_different_set(tmp_path):
   Canvas(8).save(tmp_path / "set")
   with pytest.raises(ArtToolError, match="다르다"):
      Canvas(8, layers=["body", "hair"]).save(tmp_path / "set")
   with pytest.raises(ArtToolError):
      Canvas(8).save(tmp_path / "set2", item="../bad")


def test_preview_scales_nearest(tmp_path):
   c = Canvas(4)
   c["body"].dot(1, 1, "#FF0000")
   path = c.preview(tmp_path / "p.png", scale=3)
   arr = image.load(path)
   assert arr.shape == (12, 12, 4)
   assert (arr[3:6, 3:6, 0] == 255).all() and arr[2, 2, 3] == 0


def test_open_flags_soft_alpha(tmp_path):
   c = Canvas(4)
   c["body"].dot(0, 0, "#FFFFFF")
   c.save(tmp_path / "set")
   arr = image.load(tmp_path / "set" / "body" / "idle.png")
   arr[1, 1] = (10, 10, 10, 100)
   image.save(tmp_path / "set" / "body" / "idle.png", arr)
   rep = Canvas.open(tmp_path / "set").report()
   assert [w["rule"] for w in rep["warnings"]] == ["alpha"]
