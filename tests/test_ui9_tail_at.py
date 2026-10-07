"""ui9_panel 꼬리 자리 `tail_at` (7판-다-2). 템플릿 사본을 tmp 에 써서 값만 바꿔 본다."""

import argparse

import pytest

from arttool.template import TemplateError
from arttool.jsonio import read_json, write_json
from arttool.template import schema
from arttool.template.run import build, render


def _copy(tmp_path, name, tail_at="__keep__", **values):
   """ui9_panel.json 사본. bubble 프리셋 값에서 tail_at 을 바꾸거나(None = 칸을 뺀다) 다른 값을 얹는다."""
   data = read_json(schema.find("ui9_panel"))
   bubble = data["presets"]["bubble"]["values"]
   if tail_at is None:
      # 옛 파일 그대로 : tail_at 칸이 없고 프롬프트는 「bottom center」 글자 (기본 파일이 이미 그렇다면 바뀌는 것 없음)
      bubble.pop("tail_at", None)
      preset = data["presets"]["bubble"]
      preset["prompt"] = preset["prompt"].replace("bottom {tail_at}", "bottom center")
   elif tail_at != "__keep__":
      bubble["tail_at"] = tail_at
   bubble.update(values)
   path = tmp_path / f"{name}.json"
   write_json(path, data)
   return str(path)


@pytest.mark.parametrize("tail_at, x0", [("left", 14), ("right", 54 - 14 - 8), ("center", (54 - 8) // 2)])
def test_tail_at_moves_tail_box(tmp_path, tail_at, x0):
   shown, _, _ = build(_copy(tmp_path, f"t_{tail_at}", tail_at), "54x34", "bubble", None)
   tx0, ty0, tx1, ty1 = shown["lines"]["tail"]
   assert (tx0, tx1) == (x0, x0 + 8)
   assert (ty0, ty1) == (34 - 7, 34)


@pytest.mark.parametrize("tail_at", ["left", "center", "right"])
def test_tail_at_renders(tmp_path, tail_at):
   path = _copy(tmp_path, f"r_{tail_at}", tail_at)
   ns = argparse.Namespace(sub="render", name=path, size="54x34", out_dir=str(tmp_path / f"out_{tail_at}"),
                           preset="bubble", scale=None, over=None, profile=None)
   result = render(ns)
   assert result["status"] == "ok"
   shown = read_json(result["template"])
   tx0 = shown["lines"]["tail"][0]
   assert tx0 == {"left": 14, "center": 23, "right": 32}[tail_at]


def test_tail_at_default_center_same_as_old(tmp_path):
   """tail_at 칸이 없는 옛 값과 center 를 준 값은 셈 결과 · 그림이 같다."""
   old = _copy(tmp_path, "old", None)
   new = _copy(tmp_path, "new", "center")
   shown_old, shown_new = build(old, "54x34", "bubble", None)[0], build(new, "54x34", "bubble", None)[0]
   assert shown_old["lines"] == shown_new["lines"]
   assert shown_old["prompt"] == shown_new["prompt"] and "bottom center" in shown_new["prompt"]
   outs = {}
   for key, path in (("old", old), ("new", new)):
      ns = argparse.Namespace(sub="render", name=path, size="64x40", out_dir=str(tmp_path / f"o_{key}"),
                              preset="bubble", scale=None, over=None, profile=None)
      render(ns)
      outs[key] = tmp_path / f"o_{key}"
   for png in ("ui9_panel_guide.png", "ui9_panel_preview.png"):
      assert (outs["old"] / png).read_bytes() == (outs["new"] / png).read_bytes()


@pytest.mark.parametrize("bad", ["middle", "LEFT", 1, None])
def test_tail_at_bad_value_refused(tmp_path, bad):
   data = read_json(schema.find("ui9_panel"))
   data["presets"]["bubble"]["values"]["tail_at"] = bad
   path = tmp_path / "bad.json"
   write_json(path, data)
   with pytest.raises(TemplateError):
      build(str(path), "54x34", "bubble", None)


@pytest.mark.parametrize("tail_at", ["left", "right"])
def test_tail_at_side_must_fit_between_borders(tmp_path, tail_at):
   """54 - 14 - 14 = 26 칸 사이에 꼬리 27 은 안 들어간다."""
   path = _copy(tmp_path, f"wide_{tail_at}", tail_at, tail_w=27)
   with pytest.raises(TemplateError):
      build(path, "54x34", "bubble", None)
   ok = _copy(tmp_path, f"fit_{tail_at}", tail_at, tail_w=26)
   tx0, _, tx1, _ = build(ok, "54x34", "bubble", None)[0]["lines"]["tail"]
   assert (tx0, tx1) == (14, 40)
