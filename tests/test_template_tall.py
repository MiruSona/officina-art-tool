"""6판 T3 — 큰 사람 120×240 겹 · 걷기 (char_parts · cycle_char · char_small 의 "120" 열쇠, 2026-10-07)."""
import argparse
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from arttool.errors import UsageError
from arttool.profile import tool_home
from arttool.template import TemplateError, run

W, H = 120, 240
BODY = 214            # 키(위 여백 26 · 아래 0)


def _render(name, size, out, preset=None):
   ns = argparse.Namespace(sub="render", name=name, size=size, out_dir=str(out), preset=preset, scale=None, over=None, profile=None)
   rep = run.run(ns)
   return rep, json.loads((Path(out) / "template.json").read_text(encoding="utf-8"))


def _near(got, want):
   assert abs(got - want) <= 1, (got, want)


@pytest.mark.parametrize("name", ["char_parts", "cycle_char", "char_small"])
def test_tall_stand_proportions(tmp_path, name):
   _, tpl = _render(name, "120x240", tmp_path / "out")
   ln, v = tpl["lines"], tpl["values"]
   assert ln["top_y"] == 26 and ln["baseline_y"] == H - 1 and ln["body_h"] == BODY
   head = ln["head"][3] - ln["head"][1]
   torso = ln["crotch_y"] - ln["chin_y"] - 1
   legs = ln["baseline_y"] - ln["crotch_y"] + 1
   _near(head, 0.40 * BODY)
   _near(torso, 0.23 * BODY)
   _near(legs, 0.37 * BODY)
   assert head + torso + legs == BODY
   _near(ln["head_w"], 0.44 * W)
   # 눈 13×8 · 눈 줄은 머리 꼭대기에서 머리 높이의 0.22
   for box in (ln["eye_box_l"], ln["eye_box_r"]):
      assert box[2] - box[0] == 13 and box[3] - box[1] == 8
   _near(ln["eye_line_y"] - ln["top_y"], 0.22 * head)
   assert v["eye_w"] == 13 and v["eye_h"] == 8


def test_tall_parts_layers_and_masks(tmp_path):
   out = tmp_path / "out"
   _, tpl = _render("char_parts", "120x240", out)
   assert [l["name"] for l in tpl["layers"]] == ["body", "cloth_bottom", "cloth_top", "face", "hair", "deco"]
   for layer in ("body", "cloth_bottom", "cloth_top", "face", "hair"):
      mask = np.asarray(Image.open(out / f"char_parts_mask_{layer}.png"))
      assert mask.shape[:2] == (H, W)
      assert mask.any(), layer
   # 몸 마스크 바닥은 baseline(맨 아래 줄)에 닿는다
   body = np.asarray(Image.open(out / "char_parts_mask_body.png").convert("L")) > 0
   assert np.nonzero(body.any(axis=1))[0].max() == H - 1


@pytest.mark.parametrize("preset,frames", [("walk", 8), ("walk6", 6), ("walk12", 12)])
def test_tall_walk_frames_keep_baseline(tmp_path, preset, frames):
   _, tpl = _render("cycle_char", "120x240", tmp_path / "out", preset=preset)
   ln = tpl["lines"]
   assert tpl["frames"] == frames and len(ln["head_top_y"]) == frames
   assert ln["baseline_y"] == H - 1        # 바닥 줄은 프레임마다 같다(머리만 bob 만큼 오르내린다)
   assert [t - ln["top_y"] for t in ln["head_top_y"]] == ln["bob"]


def _bad_copy(tmp_path, name, key, value, preset=None):
   data = json.loads((tool_home() / "templates" / f"{name}.json").read_text(encoding="utf-8"))
   table = data["presets"][preset]["values"] if preset else data["values"]
   table[key] = dict(table[key], **{"120": value})
   path = tmp_path / f"{name}.json"
   path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
   return str(path)


@pytest.mark.parametrize("key,value", [
   ("heads", -1), ("heads", True), ("heads", "2.5"), ("top_ratio", 1.5), ("top_ratio", -0.1),
   ("eye_w", 0), ("eye_w", 1.5), ("eye_h", True), ("eye_gap", -1), ("eye_ratio", 2),
   ("eye_w", 10**9), ("eye_h", 241), ("eye_gap", 121),
])
def test_tall_bad_values_refused(tmp_path, key, value):
   path = _bad_copy(tmp_path, "cycle_char", key, value)
   with pytest.raises((TemplateError, UsageError)):
      _render(path, "120x240", tmp_path / "out")


@pytest.mark.parametrize("size", ["60x120", "8x8", "240x240", "120x240", "121x239"])
def test_char_small_other_sizes_do_not_crash(tmp_path, size):
   rep, tpl = _render("char_small", size, tmp_path / "out")
   assert rep["status"] in ("ok", "warn")      # 목록 밖 크기는 size_range 경고(warn)
   w, h = map(int, size.split("x"))
   assert tpl["lines"]["baseline_y"] < h and tpl["lines"]["head"][2] <= w


def test_tall_unlisted_size_still_refused_for_parts(tmp_path):
   with pytest.raises(UsageError):
      _render("char_parts", "60x120", tmp_path / "out")
