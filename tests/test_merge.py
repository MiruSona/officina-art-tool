"""갈래 합치기 시험 (설계 13 ⑱). 따로 만든 갈래가 실제 산출물로 서로 이어지는지 본다.

그림은 모두 코드로 만든 합성 그림이다.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import numpy as np
import pytest
import yaml

from arttool import check, cli, image, layerset
from arttool.checks.outline import measure_outline
from arttool.draw import Canvas, shapes
import importlib

# arttool.draw 는 outline 함수를 같은 이름으로 내보내 모듈을 가린다 — 모듈은 이름으로 연다
draw_outline_mod = importlib.import_module("arttool.draw.outline")
from arttool.errors import UsageError
from arttool.jsonio import read_json
from arttool.profile import load_profile, tool_home
from arttool.template import run as template_run

from test_style_extract import INK, VARIANTS, character


def render(tmp_path: Path, name: str, size: str, *more) -> Path:
   out = tmp_path / f"tpl_{name}"
   assert cli.main(["template", "render", name, "--size", size, "--out", str(out), *more]) == 0
   return out


def profile_file(tmp_path: Path, outline: str = "selout") -> Path:
   shutil.copy(tool_home() / "palettes" / "lpc_cloth.json", tmp_path / "ramps.json")
   path = tmp_path / "game.yaml"
   path.write_text(f"name: game\nstyle:\n  outline: {outline}\n  light: top_right\npalette:\n  ramps_file: ramps.json\n", encoding="utf-8")
   return path


def char_picture(folder: Path, size: int = 32) -> Path:
   folder.mkdir(parents=True, exist_ok=True)
   arr = image.new(size, size)
   shapes.paint(arr, shapes.box((size, size), 10, 6, 22, 30), "#B05030")
   image.save(folder / "hero.png", arr)
   return folder


# --- 1. template render 결과 → check --template ---


def test_rendered_template_without_profile_feeds_check(tmp_path):
   tpl = render(tmp_path, "char_small", "32") / "template.json"
   got = check.load_template(tpl)
   assert got["kind"] == "character" and got["name"] == "char_small"
   assert sorted(got["must"]) == ["alpha", "canvas", "palette", "scale"]
   assert not got["profile_applied"] and got["fixed"] == []
   rep_file = tmp_path / "r.json"
   cli.main(["check", "--in", str(char_picture(tmp_path / "pics")), "--report", str(rep_file), "--template", str(tpl)])
   rep = read_json(rep_file)
   assert rep["template"]["name"] == "char_small" and rep["template"]["kind"] == "character"


def test_rendered_template_with_profile_carries_ramps_and_style(tmp_path):
   prof = profile_file(tmp_path)
   tpl = render(tmp_path, "char_small", "32", "--profile", str(prof)) / "template.json"
   got = check.load_template(tpl)
   assert got["profile_applied"]
   assert got["layer"]["style"]["outline"] == "selout"
   assert Path(got["layer"]["palette"]["ramps_file"]).is_absolute()
   report = check.run(load_profile(None), char_picture(tmp_path / "pics"), template=tpl)
   assert report["template"]["profile_applied"]


def test_rendered_fx_template_keeps_fixed_outline(tmp_path):
   prof = profile_file(tmp_path)
   tpl = render(tmp_path, "fx_ring_burst", "16", "--profile", str(prof)) / "template.json"
   got = check.load_template(tpl)
   assert got["fixed"] == ["style.outline"]
   assert got["layer"]["style"]["outline"] == "none"
   assert got["compare"] == {"frames": 5, "size": [16, 16], "colors": 1}


def test_size_single_number_is_square():
   a = template_run.run(argparse.Namespace(sub="show", name="char_small", size="32", preset=None, profile=None))
   b = template_run.run(argparse.Namespace(sub="show", name="char_small", size="32x32", preset=None, profile=None))
   assert a["size"] == b["size"] == [32, 32]


def test_base_and_material_only_for_palette_kind(tmp_path):
   out = render(tmp_path, "palette_ramp", "16", "--base", "#3070C0", "--material", "metal")
   data = read_json(out / "template.json")
   assert data["name"] == "palette_ramp"
   with pytest.raises(UsageError):
      template_run.build("char_small", "32", None, None, base="#3070C0")
   with pytest.raises(UsageError):
      template_run.build("palette_ramp", "16", None, None, base="#GGGGGG")


# --- 3. draw.Canvas ↔ 실제 템플릿 ---


def test_canvas_opens_template_by_name_and_guide_reads_lines():
   c = Canvas(template="char_small", size=32)
   assert c.size == (32, 32) and c.template_name == "char_small"
   assert "body" in c.names and "hair" in c.names
   assert c.guide.y("eye") == c.guide.y("eye_line_y")
   x0, y0, x1, y1 = c.guide.box("head")
   assert 0 <= x0 < x1 <= 32 and 0 <= y0 < y1 <= 32


def test_canvas_opens_rendered_folder(tmp_path):
   out = render(tmp_path, "char_small", "32")
   c = Canvas(template=out)
   assert c.size == (32, 32) and c.guide.box("head") == Canvas(template="char_small", size=32).guide.box("head")


def test_canvas_save_passes_layers_check_with_template(tmp_path):
   out = render(tmp_path, "char_small", "32")
   c = Canvas(template=out)
   for name in c.names:
      mask_file = out / f"char_small_mask_{name}.png"
      if mask_file.is_file() and name in ("body", "hair"):
         mask = image.load(mask_file)[:, :, 3] > 0
         shapes.paint(c[name].arr, mask & ~c.merged()[:, :, 3].astype(bool), "#B05030" if name == "body" else "#3060C0")
   c.save(tmp_path / "set")
   rep_file = tmp_path / "lc.json"
   code = cli.main(["layers", "check", "--in", str(tmp_path / "set"), "--template", str(out / "template.json"), "--report", str(rep_file)])
   rep = read_json(rep_file)
   assert code == 0 and rep["failed"] == []
   assert layerset.load(tmp_path / "set").template == "char_small"


# --- 5. 템플릿 산출물 꼴 = layers 가 기대한 꼴 ---


def test_render_output_layout_matches_layers_expectation(tmp_path):
   out = render(tmp_path, "char_small", "32")
   data = read_json(out / "template.json")
   ls = layerset.load(out)
   assert data["name"] == "char_small"
   for layer in ls.layers:
      # 고를 수 있는 겹(deco)은 자리가 안 정해져 마스크가 없다
      assert (out / f"char_small_mask_{layer.name}.png").is_file() != layer.optional
   # layers diff --template 이 그 폴더의 마스크 · 순서 · 이름을 읽는다
   base = image.new(32, 32)
   shapes.paint(base, shapes.box((32, 32), 10, 10, 22, 30), "#B05030")
   image.save(tmp_path / "idle.png", base)
   inp = tmp_path / "inp"
   inp.mkdir()
   hair = base.copy()
   shapes.paint(hair, shapes.box((32, 32), 10, 2, 22, 8), "#3060C0")
   image.save(inp / "hair.png", hair)
   rep_file = tmp_path / "d.json"
   assert cli.main(["layers", "diff", "--base", str(tmp_path / "idle.png"), "--in", str(inp), "--out", str(tmp_path / "set"),
                    "--template", str(out / "template.json"), "--report", str(rep_file)]) == 0
   assert layerset.load(tmp_path / "set").template == "char_small"
   assert "outside_mask" in read_json(rep_file)["layers"]["hair"]


# --- 4. draw.outline 으로 두른 모양 = checks.outline 판정 ---


@pytest.mark.parametrize("size", [16, 32, 64])
@pytest.mark.parametrize("light", ["top_left", "top", "top_right"])
@pytest.mark.parametrize("mode", ["black", "selout", "selout+light"])
@pytest.mark.parametrize("where", ["outside", "inside"])
def test_draw_outline_reads_back_same_mode(size, light, mode, where):
   """평면으로 칠한 모양(밝은 머리 + 어두운 몸)에 두른 외곽선은 검사에서 같은 방식으로 읽힌다."""
   arr = image.new(size, size)
   m = size // 8
   shapes.paint(arr, shapes.ellipse((size, size), m, m, size - m, size - m), "#C08060")
   shapes.paint(arr, shapes.box((size, size), size // 2 - m, size // 2, size // 2 + m, size - m), "#3060C0")
   drawn = draw_outline_mod.outline(arr, mode, light=light, where=where)
   assert measure_outline(drawn, light)["verdict"] == mode


@pytest.mark.parametrize("light", ["top_left", "top", "top_right"])
@pytest.mark.parametrize("mode", ["black", "selout", "selout+light"])
@pytest.mark.parametrize("where", ["outside", "inside"])
def test_draw_outline_reads_back_on_shaded_shapes(light, mode, where):
   """안쪽을 램프로 음영 넣은 그림(왼쪽 위가 밝다)도 같은 방식으로 읽힌다 — 빛 쪽 몫을 안쪽 이웃 대비로 재기 때문이다."""
   for extra in VARIANTS:
      drawn = draw_outline_mod.outline(character(**extra), mode, light=light, where=where)
      assert measure_outline(drawn, light)["verdict"] == mode


# --- 7. style extract → 프로필 조각 → template render --profile ---


def test_style_extract_fragment_to_template_render(tmp_path):
   refs = tmp_path / "refs"
   refs.mkdir()
   for i, extra in enumerate(VARIANTS):
      image.save(refs / f"hero{i}.png", character(**extra, outline=INK))
   out = tmp_path / "style"
   assert cli.main(["style", "extract", "--in", str(refs), "--out", str(out)]) in (0, 3)
   frag_text = (out / "refs_profile.yaml").read_text(encoding="utf-8")
   frag = yaml.safe_load(frag_text)
   # 조각은 palette.ramps_file 을 palettes/<이름>.json 으로 적는다 → 프로필 옆 그 자리에 둔다
   game = tmp_path / "game"
   (game / "palettes").mkdir(parents=True)
   shutil.copy(out / "refs_palette.json", game / Path(frag["palette"]["ramps_file"]))
   (game / "game.yaml").write_text("name: game\n" + frag_text, encoding="utf-8")

   tpl = render(tmp_path, "char_small", "32", "--profile", str(game / "game.yaml"))
   data = read_json(tpl / "template.json")
   assert data["profile_applied"]
   assert data["check"]["style"]["outline"] == "black"
   ramps_file = Path(data["check"]["palette"]["ramps_file"])
   assert ramps_file.is_file()
   assert read_json(ramps_file)["ramps"].keys() == read_json(out / "refs_palette.json")["ramps"].keys()
   assert check.load_template(tpl / "template.json")["profile_applied"]


# --- 11. 미리보기 이름표 ---


def test_preview_labels_drop_without_font(tmp_path, monkeypatch, capsys):
   from arttool import image as image_mod

   with_font = render(tmp_path, "char_small", "32")
   wide = image.load(with_font / "char_small_preview.png").shape[1]
   monkeypatch.setattr(image_mod, "has_label_font", lambda: False)
   out = tmp_path / "nofont"
   capsys.readouterr()
   assert cli.main(["template", "render", "char_small", "--size", "32", "--out", str(out), "--json"]) == 0
   result = json.loads(capsys.readouterr().out)
   narrow = image.load(out / "char_small_preview.png").shape[1]
   assert narrow < wide
   assert any("label_font" in w.get("rule", "") for w in result["warnings"])
