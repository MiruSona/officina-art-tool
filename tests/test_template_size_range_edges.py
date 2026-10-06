"""6판 T1 리뷰 뒤 — 프리셋 크기 목록 존중 · 범위 귀퉁이 · 망가진 값 거절 (2026-10-07)."""
import argparse
import json
from pathlib import Path

import pytest

from arttool.errors import UsageError
from arttool.profile import tool_home
from arttool.template import TemplateError, schema
from arttool.template import run


def _render(name, size, out, preset=None):
   ns = argparse.Namespace(sub="render", name=name, size=size, out_dir=str(out), preset=preset, scale=None, over=None, profile=None)
   return run.run(ns)


def _load(name) -> dict:
   return json.loads((tool_home() / "templates" / f"{name}.json").read_text(encoding="utf-8"))


def _write(tmp_path, data) -> str:
   path = tmp_path / f"{data['name']}.json"
   path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
   return str(path)


def _ranged():
   names = sorted(p.stem for p in (tool_home() / "templates").glob("*.json"))
   return [n for n in names if "size_range" in _load(n)]


def _presets_with_sizes(name):
   data = _load(name)
   return [(p, node["sizes"]) for p, node in (data.get("presets") or {}).items()
           if isinstance(node, dict) and "sizes" in node and not schema.handler(data["kind"]).flat_presets]


# ── 1. 프리셋이 자기 크기 목록을 가져도 맨 위 size_range 는 듣는다 (범위 안·목록 밖 = 경고). 범위가 없으면 종료 2 ──

def _owned_cases():
   names = sorted(p.stem for p in (tool_home() / "templates").glob("*.json"))
   cases = []
   for name in names:
      top = [tuple(s) for s in _load(name)["sizes"]]
      for preset, sizes in _presets_with_sizes(name):
         own = [tuple(s) for s in sizes]
         cases += [(name, preset, f"{w}x{h}") for w, h in top if (w, h) not in own]
   return cases


#  프리셋 목록 밖·범위 안인데 프리셋 값(테두리 등)이 그 크기에 안 맞아 거절되는 것 (6c 실측)
PRESET_MISFIT = {("ui9_panel", "bubble", s) for s in ("16x16", "24x24", "32x32", "48x32", "64x32")}


@pytest.mark.parametrize("name,preset,size", _owned_cases())
def test_preset_list_is_respected(tmp_path, name, preset, size):
   # 맨 위 size_range 가 있으면 프리셋 목록 밖이라도 범위 안이면 받고 경고, 없으면 옛 판처럼 종료 2
   if "size_range" not in _load(name):
      with pytest.raises(UsageError, match=f"이 프리셋은 .* 만 받는다 : {preset}") as info:
         _render(name, size, tmp_path / "out", preset)
      assert "사이" not in str(info.value)
      return
   if (name, preset, size) in PRESET_MISFIT:
      with pytest.raises(UsageError, match=f"이 크기에서는 안 맞는다 : {size} — ") as info:
         _render(name, size, tmp_path / "out", preset)
      assert "사이" not in str(info.value)
      return
   report = _render(name, size, tmp_path / "out", preset)
   free = [w["detail"] for w in report["warnings"] if w["rule"] == "template.size_free"]
   assert len(free) == 1 and f"{size} 은 이 프리셋({preset})의 정해진 크기가 아니다" in free[0]


@pytest.mark.parametrize("size", ["32x32", "16x16", "8x8", "24x24", "40x20"])
def test_bubble_misfit_inside_range_names_the_reason(tmp_path, size):
   # bubble 테두리(L14 B20 R14 T12)가 안 들어가는 작은 크기 — 까닭을 적고 「사이」 안내는 없다
   with pytest.raises(UsageError, match=f"이 크기에서는 안 맞는다 : {size} — .*테두리") as info:
      _render("ui9_panel", size, tmp_path / "out", "bubble")
   assert "사이" not in str(info.value)


def test_outside_range_with_preset_lists_range(tmp_path):
   # 범위 밖은 프리셋을 골라도 「받는 것 … 또는 8x8 ~ 256x256 사이」
   for preset in (None, "button"):
      with pytest.raises(UsageError, match=r"받는 것 : .* · 또는 8x8 ~ 256x256 사이"):
         _render("ui9_panel", "300x300", tmp_path / "out", preset)


# ── 2. 범위 안인데 값이 안 맞으면 까닭을 적고 「범위 사이」 안내는 안 붙인다 ──

def test_value_misfit_inside_range_names_the_reason(tmp_path):
   # 범위를 1x1 까지 넓힌다. 3x3 은 범위 안이지만 panel 테두리 4px 가 안 들어간다
   data = _load("ui9_panel")
   data["size_range"] = [[1, 1], [256, 256]]
   with pytest.raises(UsageError, match="이 크기에서는 안 맞는다 : 3x3 — .*테두리") as info:
      _render(_write(tmp_path, data), "3x3", tmp_path / "out", "panel")
   assert "사이" not in str(info.value)


# ── 3. 경고의 열쇠 판정은 프리셋을 합친 값으로 한다 ──

def test_free_size_warning_sees_preset_value_keys(tmp_path):
   report = _render("char_small", "20x20", tmp_path / "out", "sd")
   free = [w["detail"] for w in report["warnings"] if w["rule"] == "template.size_free"]
   assert free and '"16"' in free[0]   # heads 등은 sd 프리셋 값 표에만 있다


# ── 4ⓐ 범위 네 귀퉁이는 그려지고, 바로 밖 1칸은 거절 ──

def _corner_cases():
   cases = []
   for name in _ranged():
      (lw, lh), (hw, hh) = _load(name)["size_range"]
      cases += [(name, w, h) for w, h in dict.fromkeys([(lw, lh), (hw, hh), (lw, hh), (hw, lh)])]
   return cases


#  범위 귀퉁이인데 값이 안 맞아 깨끗이 거절되는 것 (리뷰 뒤 실측 — 머리 장식이 낮은 캔버스 위로 나간다)
#  ui9_panel 기본(panel) 테두리 4px 는 한 변 8 에 안 들어간다 (6c 실측)
CORNER_MISFIT = {("char_blob", 128, 16), ("ui9_panel", 8, 8), ("ui9_panel", 8, 256), ("ui9_panel", 256, 8)}


@pytest.mark.parametrize("name,w,h", _corner_cases())
def test_range_corner_renders(tmp_path, name, w, h):
   out = tmp_path / "out"
   if (name, w, h) in CORNER_MISFIT:
      with pytest.raises(UsageError, match=f"이 크기에서는 안 맞는다 : {w}x{h}"):
         _render(name, f"{w}x{h}", out)
      return
   report = _render(name, f"{w}x{h}", out)
   assert report["size"] == [w, h]
   assert json.loads((out / "template.json").read_text(encoding="utf-8"))["size"] == [w, h]


def _outside_cases():
   cases = []
   for name in _ranged():
      data = _load(name)
      (lw, lh), (hw, hh) = data["size_range"]
      listed = [tuple(s) for s in data["sizes"]]
      for w, h in [(lw - 1, lh), (lw, lh - 1), (hw + 1, hh), (hw, hh + 1)]:
         if w > 0 and h > 0 and (w, h) not in listed:
            cases.append((name, w, h))
   return cases


@pytest.mark.parametrize("name,w,h", _outside_cases())
def test_one_step_outside_range_is_refused(tmp_path, name, w, h):
   with pytest.raises(UsageError, match="받는 크기가 아니다"):
      _render(name, f"{w}x{h}", tmp_path / "out")


# ── 4ⓒ char_blob · fx_swirl 의 틀린 값은 깨끗한 TemplateError ──

@pytest.mark.parametrize("key,value", [
   ("body_w_ratio", 0), ("body_w_ratio", -0.5), ("body_w_ratio", 1.5), ("body_h_ratio", 0),
   ("face_w_ratio", 1.2), ("eye_gap_ratio", -0.1), ("frames", []),
])
def test_char_blob_bad_value_is_template_error(tmp_path, key, value):
   data = _load("char_blob")
   data["values"][key] = value
   with pytest.raises(TemplateError):
      _render(_write(tmp_path, data), "32x32", tmp_path / "out")


@pytest.mark.parametrize("change", [
   {"turns": 0}, {"turns": -1}, {"turns": 1000}, {"r0": 0.9, "r1": 0.1}, {"r0": 0.5, "r1": 0.5},
   {"r0": -0.1}, {"r1": 1.5},
])
def test_fx_swirl_bad_spiral_is_template_error(tmp_path, change):
   data = _load("fx_swirl")
   for frame in data["frames"]:
      frame["draw"][0].update(change)
   with pytest.raises(TemplateError):
      _render(_write(tmp_path, data), "64x64", tmp_path / "out")


def test_fx_swirl_empty_frames_is_template_error(tmp_path):
   data = _load("fx_swirl")
   data["frames"] = []
   with pytest.raises(TemplateError):
      _render(_write(tmp_path, data), "64x64", tmp_path / "out")


# ── 4ⓓ char_small heads 끝 값 (리뷰 뒤 실측) ──

def _char_small_heads(tmp_path, heads) -> str:
   data = _load("char_small")
   for node in data["presets"].values():
      node["values"]["heads"] = heads
   return _write(tmp_path, data)


def test_char_small_heads_half_is_template_error(tmp_path):
   # 1 미만 등신은 머리가 몸보다 큰 셈이라 거절한다 (6판 「막지 않는다」를 2026-10-07 뒤집음)
   with pytest.raises(TemplateError, match="1 이상 등신"):
      _render(_char_small_heads(tmp_path, 0.5), "32x32", tmp_path / "out")


def test_char_small_heads_one_renders(tmp_path):
   # 경계 : 1 등신은 받는다 — 머리 높이가 머리 자리(head_room)로 잘려 그려진다
   report = _render(_char_small_heads(tmp_path, 1), "32x32", tmp_path / "out")
   assert report["size"] == [32, 32]


def test_char_small_heads_twelve_is_template_error(tmp_path):
   # 12 등신은 머리가 작아져 눈 카드가 턱 아래로 나간다 — 불러올 때 깨끗이 거절
   with pytest.raises(TemplateError, match="턱 아래"):
      _render(_char_small_heads(tmp_path, 12), "32x32", tmp_path / "out")
