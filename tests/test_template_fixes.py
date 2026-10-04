"""템플릿 보강 (리뷰 2차 R2-H1 · M1 · M2 · L1 · L7 · 실물 시험 #25 ~ #36) 시험. 그림은 모두 합성."""

import argparse
from pathlib import Path

import numpy as np
import pytest

from arttool import image, layerset
from arttool.draw import shapes
from arttool.errors import UsageError
from arttool.jsonio import read_json
from arttool.template import guide, schema
from arttool.template.kinds import handler
from arttool.template.run import build, list_templates, render


def args(name, size, out, **extra):
   base = {"sub": "render", "name": name, "size": size, "out_dir": str(out), "preset": None, "scale": None, "over": None, "profile": None}
   base.update(extra)
   return argparse.Namespace(**base)


def _all_cases():
   """(템플릿, 프리셋, 크기 글자) — 모든 템플릿 × 프리셋(없으면 None) × 그 프리셋의 크기."""
   cases = []
   for row in list_templates()["templates"]:
      loaded = schema.load(row["name"])
      for preset in schema.preset_names(loaded) or [None]:
         tpl, _ = schema.apply_preset(loaded, preset)
         for w, h in tpl["sizes"]:
            cases.append((row["name"], preset, f"{w}x{h}"))
   return cases


NOT_BOXES = {"borders", "frames", "points", "path"}   # 네 정수지만 상자가 아닌 칸 (변 두께 · 점 목록)


def _boxes(node):
   """셈 결과 안의 네 정수 상자 [x0, y0, x1, y1) 를 모두 꺼낸다."""
   if isinstance(node, dict):
      for k, v in node.items():
         if k not in NOT_BOXES:
            yield from _boxes(v)
   elif isinstance(node, list):
      if len(node) == 4 and all(isinstance(v, int) and not isinstance(v, bool) for v in node):
         yield node
      else:
         for v in node:
            yield from _boxes(v)


@pytest.mark.parametrize("name,preset,size", _all_cases())
def test_sweep_every_size_and_preset(name, preset, size):
   """모든 크기 × 프리셋 : 셈이 되고, 상자가 비지 않고 캔버스 안이며, 마스크가 비지 않는다 (R2-H1)."""
   shown, _warnings, made = build(name, size, preset, None)
   w, h = shown["size"]
   kind = made["kind"]
   if kind.name == "palette":
      return
   boxes = [] if kind.name in ("cycle", "motion") else _boxes(made["calc"])
   for x0, y0, x1, y1 in boxes:
      assert 0 <= x0 < x1 <= w and 0 <= y0 < y1 <= h, (name, preset, size, [x0, y0, x1, y1])
   if kind.mask_files:
      layers = {row["name"] for row in shown["layers"]}
      for layer, mask in kind.masks(made["ctx"], made["calc"]).items():
         assert layer in layers, (name, preset, size, layer)
         assert mask.any(), (name, preset, size, layer)
   kind.guide(made["ctx"], made["calc"])


def test_mask_empty_is_warned_not_written(tmp_path, monkeypatch):
   """빈 마스크는 파일을 안 쓰고 template.mask_empty 로 알린다 (R2-H1)."""
   kind = handler("parts")
   real = kind.masks

   def with_empty(ctx, calc):
      out = real(ctx, calc)
      out["face"] = shapes.empty(ctx.size)
      return out

   monkeypatch.setattr(kind, "masks", with_empty)
   got = render(args("char_parts", "32", tmp_path / "o"))
   assert any(w["rule"] == "template.mask_empty" and w["items"] == ["face"] for w in got["warnings"])
   assert not (tmp_path / "o" / "char_parts_mask_face.png").exists()
   assert got["status"] == "warn"


# ── R2-M1 · M2 : 원본 보호 · 그림 목록 지키기 ─────────


def test_render_refuses_to_overwrite_template_source(tmp_path):
   out = tmp_path / "o"
   out.mkdir()
   src = out / "template.json"
   src.write_text(Path(schema.find("tile_base")).read_text(encoding="utf-8"), encoding="utf-8")
   with pytest.raises(UsageError):
      render(args(str(src), "16", out))
   assert read_json(src)["name"] == "tile_base"     # 원본 그대로


def test_render_refuses_over_picture_with_render_name(tmp_path):
   out = tmp_path / "o"
   out.mkdir()
   pic = out / "char_small_guide.png"
   image.save(pic, image.new(32, 32, (10, 20, 30, 255)))
   with pytest.raises(UsageError):
      render(args("char_small", "32", out, over=str(pic)))
   assert image.load(pic)[0, 0, 0] == 10


def test_render_keeps_items_of_drawn_set(tmp_path):
   out = tmp_path / "o"
   render(args("char_small", "32", out))
   data = read_json(out / "layers.json")
   data["items"] = ["idle", "walk0"]
   (out / "layers.json").write_text(__import__("json").dumps(data), encoding="utf-8")
   render(args("char_small", "32", out))
   assert layerset.load(out).items == ["idle", "walk0"]
   # 겹 목록이 다른 템플릿을 그린 그림 위에 쓰면 거절
   with pytest.raises(UsageError):
      render(args("char_parts", "32", out))


# ── #28 · #29 : --over 아래 가운데 · 경고 수 ─────────


def test_over_bottom_center_grows_canvas():
   pic = image.new(48, 64, (200, 0, 0, 255))
   g = image.new(64, 64)
   out = guide.over(pic, g, 1)
   assert out.shape[:2] == (64, 64)
   assert out[0, 8, 0] == 200 and out[63, 55, 0] == 200        # x 8 ~ 55 에 그림
   assert out[0, 7, 0] != 200 and out[0, 56, 0] != 200
   big = guide.over(image.new(80, 40, (0, 200, 0, 255)), image.new(64, 64), 1)
   assert big.shape[:2] == (64, 80) and big[63, 0, 1] == 200 and big[23, 0, 1] != 200


def test_over_size_warning_counts_once(tmp_path):
   pic = tmp_path / "pic.png"
   image.save(pic, image.new(48, 64, (200, 0, 0, 255)))
   got = render(args("char_small", "64", tmp_path / "o", over=str(pic)))
   rules = [w["rule"] for w in got["warnings"]]
   assert rules.count("template.over_size") == 1 and got["status"] == "warn"
   assert "아래 가운데" in got["warnings"][rules.index("template.over_size")]["detail"]
   assert image.size(image.load(tmp_path / "o" / "char_small_over.png"))[0] >= 64


# ── #25 · #26 · #27 : 캐릭터 프리셋 · 크기 ─────────


@pytest.mark.parametrize("size", ["48x64", "64x80", "72x88"])
def test_char_small_tall_sizes_use_sd(size):
   shown, _, _ = build("char_small", size, None, None)
   assert shown["preset"] == "sd"
   lines = shown["lines"]
   head = lines["head"]
   # sd : 머리가 몸 높이의 절반 가까이
   assert (head[3] - head[1]) * 2.4 >= lines["baseline_y"] - lines["top_y"]


def test_char_parts_waist_splits_cloth():
   shown, _, made = build("char_parts", "48x64", "sd", None)
   masks = made["kind"].masks(made["ctx"], made["calc"])
   top, bottom = masks["cloth_top"], masks["cloth_bottom"]
   assert top.any() and bottom.any() and not (top & bottom).any()
   assert np.nonzero(bottom)[0].min() >= shown["lines"]["waist_y"]


# ── #30 · #31 · #34 · #35 · R2-L7 : 크기 · 값 ─────────


@pytest.mark.parametrize("name,size", [("icon_set", "28"), ("icon_set", "56"), ("tile_base", "64"), ("tile_base", "128"),
                                       ("tile_base", "256"), ("fx_dust", "12"), ("fx_dust", "48"), ("fx_dust", "64")])
def test_new_sizes_build(name, size):
   shown, _, _ = build(name, size, None, None)
   assert shown["size"] == [int(size)] * 2


def test_fx_dust_default_preset_by_size():
   assert build("fx_dust", "12", None, None)[0]["preset"] == "small"
   assert build("fx_dust", "64", None, None)[0]["preset"] == "big"


def test_palette_hue_step_default_auto_and_zero_kept():
   # 기본은 "auto" — 칸 수에 맞춘 걸음 (6칸 7.2°). 10° 고정이면 6칸 처음 ~ 끝이 50° 라 style extract 가 둘로 갈랐다
   shown, _, made = build("palette_ramp", None, None, None, base="#808040")
   assert shown["values"]["hue_step"] == "auto"
   from arttool.palette import auto_hue_step
   steps = made["calc"]["steps"]
   assert made["calc"]["hue_step"] == auto_hue_step(steps) and auto_hue_step(6) == 7.2 and auto_hue_step(4) == 10.0
   ctx = made["ctx"]
   ctx.extra = {"base": "#808040", "hue_step": 0.0, "steps": 5}
   flat = made["kind"].compute(ctx)["ramp"]
   from arttool.palette import parse_hex
   import colorsys
   hues = {round(colorsys.rgb_to_hsv(*[c / 255 for c in (parse_hex(x) if isinstance(x, str) else x)])[0], 2) for x in flat}
   assert len(hues) == 1      # 0.0 을 「없음」으로 읽지 않는다 (R2-L1)


def test_fx_sparkle_big_uses_r5():
   frames = schema.load("fx_sparkle")["presets"]["big"]["frames"]
   assert {"shape": "plus", "r": 5, "hollow": 2} in [d for f in frames for d in f["draw"]]


# ── #32 : ui9 변마다 테두리 · 말풍선 꼬리 · 직사각 ─────────


def test_ui9_bubble_sides_and_tail():
   shown, _, made = build("ui9_panel", "54x34", None, None)
   assert shown["preset"] == "bubble"
   lines = shown["lines"]
   assert lines["border_text"] == "14,20,14,12"
   tx0, ty0, tx1, ty1 = lines["tail"]
   assert ty1 == 34 and tx1 - tx0 == 8 and ty1 - ty0 == 7
   assert "--border 14,20,14,12" in " ".join(shown["steps"])


def test_ui9_button_and_rect_sizes():
   assert build("ui9_panel", "36x36", None, None)[0]["preset"] == "button"
   for size in ("48x32", "64x32"):
      shown, _, _ = build("ui9_panel", size, "panel", None)
      assert shown["size"] == [int(v) for v in size.split("x")]


def test_ui9_side_borders_must_leave_center():
   with pytest.raises(Exception):
      tpl = schema.load("ui9_panel")
      tpl["values"]["border_l"] = 30
      tpl["values"]["border_r"] = 30
      handler("ui9").validate_values(tpl, "(시험)")


# ── #33 · #36 : 실내 배경 · 새 템플릿 ─────────


@pytest.mark.parametrize("size", ["540x960", "540x1200"])
def test_bg_indoor_bands(size):
   shown, _, made = build("bg_screen", size, "indoor", None)
   lines = shown["lines"]
   h = shown["size"][1]
   assert lines["scene"] == "indoor"
   assert abs(lines["floor_y"] / h - 0.56) < 0.02
   assert 0.15 <= lines["ceiling_end_y"] / h <= 0.2
   masks = made["kind"].masks(made["ctx"], made["calc"])
   assert set(masks) >= {"ceiling", "wall", "floor"}
   total = masks["ceiling"].astype(int) + masks["wall"] + masks["floor"]
   assert (total == 1).all()        # 띠 셋이 판을 빈틈 · 겹침 없이 나눈다


def test_new_templates_listed_and_complete():
   names = {row["name"] for row in list_templates()["templates"]}
   assert {"building", "machine", "screen_piece"} <= names
   for name in ("building", "machine", "screen_piece"):
      tpl = schema.load(name)
      assert tpl["layers"] and tpl["steps"] and tpl["prompt"] and tpl["sources"] and "must" in tpl


@pytest.mark.parametrize("size", ["92x77", "135x144", "212x241", "250x203"])
def test_building_ground_and_door(size):
   shown, _, made = build("building", size, None, None)
   lines = shown["lines"]
   w, h = shown["size"]
   assert lines["baseline_y"] >= h - 1 - round(h * 0.05)
   door = lines["door_box"]
   assert door[3] == lines["baseline_y"] + 1          # 문은 바닥선에 붙는다
   assert lines["outline_px"] == (1 if min(w, h) < 128 else 2)
   masks = made["kind"].masks(made["ctx"], made["calc"])
   assert not (masks["door"] & masks["wall"]).any() and not (masks["roof"] & masks["wall"]).any()
   assert lines["baseline_y"] == h - 1 and "shadow" not in masks      # 실물 건물은 판 맨 아래가 땅, 그림자 없음


@pytest.mark.parametrize("name, size, words", [
   ("building", "92x77", ["지붕 칸", "벽 칸"]),
   ("machine", "104x110", ["위판 칸", "몸통 칸", "받침 칸"]),
])
def test_prop_band_labels_have_meaning(name, size, words):
   """미리보기 이름표가 「칸 1」「칸 2」 가 아니라 bands 겹 이름에서 온 뜻 있는 이름이다."""
   _, _, made = build(name, size, None, None)
   texts = [text for _, text, _ in guide.marks(made["kind"].labels, made["calc"], 1)]
   assert [t for t in texts if t.endswith(" 칸") and not t.startswith("문")] == words
   assert not any(t.startswith("칸 ") for t in texts)


def test_machine_fits_real_margins():
   """실물 208×220 큰 물건 : 위 8 · 왼쪽 16 여백, 바닥선 y199 (±1px)."""
   shown, _, made = build("machine", "208x220", None, None)
   lines = shown["lines"]
   assert abs(lines["top_y"] - 8) <= 1 and abs(lines["body"][0] - 16) <= 1 and abs(lines["baseline_y"] - 199) <= 1
   masks = made["kind"].masks(made["ctx"], made["calc"])
   assert masks["shadow"].any() and np.nonzero(masks["shadow"])[0].min() > lines["baseline_y"]


def test_machine_three_bands_cover_body():
   shown, _, made = build("machine", "208x220", None, None)
   lines = shown["lines"]
   names = [b[0] for b in lines["bands"]]
   assert names == ["top", "body", "foot"]
   x0, y0, x1, y1 = lines["body"]
   masks = made["kind"].masks(made["ctx"], made["calc"])
   total = masks["top"].astype(int) + masks["body"] + masks["foot"]
   assert (total[y0:y1, x0:x1] == 1).all() and total.sum() == (x1 - x0) * (y1 - y0)
   assert lines["outline_px"] == 2 and "2px" in shown["prompt"]


def test_prop_rejects_bad_bands():
   tpl = schema.load("machine")
   tpl["values"]["bands"] = [["top", 0.7], ["body", 0.5], ["foot", 0.1]]
   with pytest.raises(Exception):
      handler("prop").validate_values(tpl, "(시험)")


def test_screen_piece_has_no_safe_area(tmp_path):
   shown, _, made = build("screen_piece", "540x720", None, None)
   assert shown["lines"]["safe"] is None and shown["lines"]["scene"] == "indoor"
   g = made["kind"].guide(made["ctx"], made["calc"])
   assert not g.keep.any()
   got = render(args("screen_piece", "540x60", tmp_path / "o"))
   assert (tmp_path / "o" / "screen_piece_mask_floor.png").is_file() and got["status"] == "ok"
