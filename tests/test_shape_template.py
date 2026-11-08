"""도형 명세 틀(template) — 값 치환 · 색 식($shade · $mix) · 켜고 끄는 부품($if) · preset · load 연결."""

import json

import numpy as np
import pytest

from arttool.errors import ArtToolError
from arttool.palette import shade, to_hex
from arttool.shape import expand, expand_template, load, parse, render


def _template(**extra):
   data = {
      "template_version": 1,
      "params": {
         "skin": {"type": "color", "default": "#808080"},
         "light": {"type": "color", "default": {"$shade": "$skin", "steps": 3, "base": 1, "pick": 2}},
         "dot": {"type": "bool", "default": False},
         "kind": {"type": "choice", "choices": ["none", "a", "b"], "default": "none"},
      },
      "presets": {"red": {"skin": "#C03030"}},
      "spec": {
         "version": 1,
         "canvas": {"size": [8, 8], "origin": [0, 0]},
         "materials": {"m": {"ramp": ["$skin", "$light"], "ambient": 1.0}},
         "shapes": [{"type": "extrude", "material": "m", "y_down": True, "depth": 2,
                     "points": [[1, 1], [7, 1], [7, 7], [1, 7]]}],
         "stamps": [
            {"$if": "dot", "on": "m", "at": [4, -4], "grid": ["d"], "legend": {"d": "#000000"}},
            {"$if": {"kind": ["a", "b"]}, "on": "m", "at": [2, -2], "grid": ["k"], "legend": {"k": "#FFFFFF"}},
         ],
      },
   }
   data.update(extra)
   return data


def test_defaults_fill_values_and_shade_ramp():
   out = expand_template(_template())
   ramp = out["materials"]["m"]["ramp"]
   assert ramp == ["#808080", to_hex(shade("#808080", 3, base_index=1)[2])]
   assert out["stamps"] == []          # $if 거짓인 칸은 목록에서 빠진다


def test_preset_then_params_override_in_order():
   out = expand_template(_template(), "red", {"dot": True})
   assert out["materials"]["m"]["ramp"][0] == "#C03030"
   # light 기본은 preset 의 skin 으로 다시 계산된다
   assert out["materials"]["m"]["ramp"][1] == to_hex(shade("#C03030", 3, base_index=1)[2])
   assert len(out["stamps"]) == 1 and "$if" not in out["stamps"][0]


def test_choice_condition_list_and_none_is_false():
   assert len(expand_template(_template(), None, {"kind": "b"})["stamps"]) == 1
   tpl = _template()
   tpl["spec"]["stamps"][1]["$if"] = "kind"
   assert expand_template(tpl, None, {"kind": "none"})["stamps"] == []
   assert len(expand_template(tpl, None, {"kind": "a"})["stamps"]) == 1


def test_negated_condition_and_dict_value_drop():
   tpl = _template()
   tpl["spec"]["materials"]["m"]["line"] = {"$if": "!dot", "color": "#111111"}
   assert expand_template(tpl)["materials"]["m"]["line"] == {"color": "#111111"}
   assert "line" not in expand_template(tpl, None, {"dot": True})["materials"]["m"]


def test_mix_blends_rgb():
   tpl = _template()
   tpl["params"]["light"]["default"] = {"$mix": ["$skin", "#FFFFFF", 0.5]}
   assert expand_template(tpl)["materials"]["m"]["ramp"][1] == "#C0C0C0"


def test_params_may_use_expressions_and_colors_are_normalized():
   out = expand_template(_template(), None, {"skin": "#a0b0c0", "light": {"$mix": ["$skin", "#000000", 1]}})
   assert out["materials"]["m"]["ramp"] == ["#A0B0C0", "#000000"]


@pytest.mark.parametrize("params, word", [
   ({"nope": 1}, "틀에 없는 이름"),
   ({"skin": "red"}, "skin"),
   ({"dot": "yes"}, "true / false"),
   ({"kind": "c"}, "중 하나"),
])
def test_bad_params_say_where(params, word):
   with pytest.raises(ArtToolError, match=word):
      expand_template(_template(), None, params)


def test_unknown_preset_and_ref_are_errors():
   with pytest.raises(ArtToolError, match="없는 묶음"):
      expand_template(_template(), "blue")
   tpl = _template()
   tpl["spec"]["materials"]["m"]["ramp"][0] = "$nope"
   with pytest.raises(ArtToolError, match="모르는 값 이름"):
      expand_template(tpl)


def test_required_param_without_default():
   tpl = _template()
   del tpl["params"]["skin"]["default"]
   with pytest.raises(ArtToolError, match="꼭 줘야"):
      expand_template(tpl)


def test_expanded_spec_renders_and_toggle_changes_pixels():
   off, _ = render(parse(expand_template(_template())))
   on, _ = render(parse(expand_template(_template(), None, {"dot": True})))
   assert (off != on).any()
   assert tuple(on[4, 4, :3]) == (0, 0, 0)


def test_load_follows_template_path_relative_to_spec(tmp_path):
   kits = tmp_path / "kits"
   kits.mkdir()
   (kits / "box.template.json").write_text(json.dumps(_template()), encoding="utf-8")
   spec_file = tmp_path / "a.shape.json"
   spec_file.write_text(json.dumps({"template": "kits/box.template.json", "preset": "red"}), encoding="utf-8")
   arr, _ = render(load(spec_file))
   plain, _ = render(parse(expand_template(_template(), "red")))
   assert np.array_equal(arr, plain)


def test_template_spec_only_takes_known_keys(tmp_path):
   (tmp_path / "t.json").write_text(json.dumps(_template()), encoding="utf-8")
   with pytest.raises(ArtToolError, match="template · preset · params"):
      expand({"template": "t.json", "shapes": []}, tmp_path)
   with pytest.raises(ArtToolError, match="틀 파일이 없다"):
      expand({"template": "missing.json"}, tmp_path)


def test_template_cannot_point_to_another_template(tmp_path):
   (tmp_path / "t.json").write_text(json.dumps({"template": "u.json"}), encoding="utf-8")
   with pytest.raises(ArtToolError, match="다른 틀"):
      expand({"template": "t.json"}, tmp_path)
