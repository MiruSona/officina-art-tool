"""워크플로 자리표시 · API 꼴 검사 · 내장 본보기 시험."""

import json
import tomllib
from pathlib import Path

import pytest

from arttool import errors
from arttool.providers import workflow

ROOT = Path(__file__).resolve().parents[1]
MODEL_KEYS = {"unet", "text_encoder", "vae", "lora", "lora_strength"}


def tiny() -> dict:
   return {
      "1": {"class_type": "CLIPTextEncode", "inputs": {"text": "$prompt", "clip": ["2", 0]}},
      "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "$text_encoder", "type": "flux2"}},
      "3": {"class_type": "KSampler", "inputs": {"seed": "$seed", "steps": 4, "note": "가격 $5 그대로"}},
      "10": {"class_type": "SaveImage", "inputs": {"images": ["3", 0]}},
      "9": {"class_type": "SaveImage", "inputs": {"images": ["3", 0]}},
   }


def all_values() -> dict:
   values = {name: "x" for name in workflow.BASE_PLACEHOLDERS}
   values.update({"seed": 7, "width": 512, "height": 512, "lora_strength": 0.8})
   values.update({key: f"{key}.safetensors" for key in MODEL_KEYS - {"lora_strength"}})
   return values


def test_quotes_and_newlines_in_prompt_keep_json_valid():
   prompt = 'a "red" barrel\nwith {braces} and \\ slash'
   filled = workflow.fill(tiny(), {"prompt": prompt, "text_encoder": "enc.safetensors", "seed": 42})
   again = json.loads(json.dumps(filled))
   assert again["1"]["inputs"]["text"] == prompt
   assert again["3"]["inputs"]["seed"] == 42 and isinstance(again["3"]["inputs"]["seed"], int)
   assert again["3"]["inputs"]["note"] == "가격 $5 그대로"   # 통째 자리표시가 아니면 안 건드린다
   assert again["1"]["inputs"]["clip"] == ["2", 0]


def test_fill_leaves_template_untouched():
   template = tiny()
   workflow.fill(template, {"prompt": "p", "text_encoder": "e", "seed": 1})
   assert template["1"]["inputs"]["text"] == "$prompt"


def test_user_prompt_starting_with_dollar_is_not_a_placeholder():
   filled = workflow.fill(tiny(), {"prompt": "$lora", "text_encoder": "e", "seed": 1})
   assert filled["1"]["inputs"]["text"] == "$lora"


def test_missing_value_exits_2_with_hint():
   template = tiny()
   template["4"] = {"class_type": "LoraLoaderModelOnly", "inputs": {"lora_name": "$lora"}}
   with pytest.raises(errors.UsageError) as caught:
      workflow.fill(template, {"prompt": "p", "text_encoder": "e", "seed": 1})
   assert caught.value.exit_code == errors.EXIT_USAGE
   assert str(caught.value) == "채울 값이 없다 : $lora (설정 models 에 넣는다)"


def test_ui_saved_form_exits_2():
   ui = {"last_node_id": 3, "nodes": [{"id": 1, "type": "KSampler"}], "links": []}
   with pytest.raises(errors.UsageError, match="API 꼴로 내보내라") as caught:
      workflow.check_api_form(ui)
   assert caught.value.exit_code == errors.EXIT_USAGE


@pytest.mark.parametrize("bad", [[], {}, {"1": "KSampler"}, {"1": {"class_type": "KSampler"}}, {"1": {"inputs": {}}}])
def test_not_api_form_exits_2(bad):
   with pytest.raises(errors.UsageError):
      workflow.check_api_form(bad)


def test_load_file_checks_form(tmp_path):
   good = tmp_path / "wf.json"
   good.write_text(json.dumps(tiny()), encoding="utf-8")
   assert workflow.load_file(good)["1"]["class_type"] == "CLIPTextEncode"
   broken = tmp_path / "broken.json"
   broken.write_text("{nope", encoding="utf-8")
   with pytest.raises(errors.UsageError, match="JSON 이 아니다"):
      workflow.load_file(broken)
   with pytest.raises(errors.UsageError, match="없다"):
      workflow.load_file(tmp_path / "none.json")


def test_class_types_and_save_nodes_in_id_order():
   assert workflow.class_types(tiny()) == ["CLIPLoader", "CLIPTextEncode", "KSampler", "SaveImage"]
   assert workflow.save_nodes(tiny()) == ["9", "10"]


@pytest.mark.parametrize("kind", ["prop", "inpaint"])
def test_builtin_templates_load_and_use_known_placeholders_only(kind):
   template = workflow.load_builtin(kind)
   names = workflow.placeholders(template)
   assert names <= set(workflow.BASE_PLACEHOLDERS) | MODEL_KEYS
   assert {"prompt", "seed", "unet", "text_encoder", "vae", "lora"} <= names
   assert len(workflow.save_nodes(template)) == 1
   filled = workflow.fill(template, all_values())
   assert not workflow.placeholders(filled)
   assert "실물 확인함" in json.dumps(template, ensure_ascii=False)   # L10 실측에서 노드 이름 · 입력을 확인한 표시


def test_inpaint_template_takes_image_and_mask():
   names = workflow.placeholders(workflow.load_builtin("inpaint"))
   assert {"image", "mask"} <= names


def test_builtin_templates_name_no_model_file():
   """모델 · LoRA 파일 이름은 본보기에 박지 않는다 (설정 models 에서만 받는다)."""
   for kind in workflow.BUILTIN:
      text = json.dumps(workflow.load_builtin(kind))
      assert ".safetensors" not in text and ".gguf" not in text


def test_unknown_builtin_kind_exits_2():
   with pytest.raises(errors.UsageError):
      workflow.load_builtin("character")


def test_templates_are_package_data():
   data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["setuptools"]["package-data"]
   assert "workflows/*.json" in data["arttool.providers"]
