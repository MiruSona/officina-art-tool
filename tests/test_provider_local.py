"""local 제공자 prop 흐름 · 계약 · dry-run 시험. 가짜 ComfyUI(fake_comfy)만 부른다."""

import json

import pytest

from arttool import errors, image, providers
from arttool.jsonio import read_json
from arttool.providers import workflow
from arttool.providers.local_config import ENV_CONFIG, ENV_ENDPOINT
from fake_comfy import FakeComfy

MODELS = {"unet": "u.safetensors", "text_encoder": "t.safetensors", "vae": "v.safetensors", "lora": "l.safetensors", "lora_strength": 0.9}


@pytest.fixture
def fake(monkeypatch):
   monkeypatch.delenv(ENV_CONFIG, raising=False)
   with FakeComfy() as server:
      monkeypatch.setenv(ENV_ENDPOINT, server.url + "/")
      yield server


def prop(tmp_path, **kw) -> providers.ProviderRequest:
   options = {"models": dict(MODELS), **kw.pop("options", {})}
   return providers.ProviderRequest(kind="prop", out_dir=tmp_path / "out", prompt="barrel", options=options, **kw)


def ksampler_seeds(fake) -> list[int]:
   seeds = []
   for wf in fake.state.prompts:
      seeds.append(next(node["inputs"]["seed"] for node in wf.values() if "seed" in node["inputs"]))
   return seeds


def test_prop_one_image(fake, tmp_path):
   result = providers.get("local").make(prop(tmp_path, seed=1000))
   assert len(result.images) == 1
   assert image.size(image.load(result.images[0])) == (64, 64)
   assert result.cost_usd == 0.0 and result.seed == 1000
   raw = result.meta["raw"][0]
   assert raw.replace("\\", "/").endswith("out/raw/prop_000_512.png")
   assert image.size(image.load(raw)) == (512, 512)
   assert result.meta["workflow"] == "klein_prop.json"
   assert result.meta["endpoint"] == fake.url.split("//")[1]
   assert result.meta["seconds"] >= 0
   assert fake.paths()[:2] == ["/system_stats", "/object_info"]


def test_prop_variants_use_next_seeds(fake, tmp_path):
   result = providers.get("local").make(prop(tmp_path, seed=1000, variants=3))
   assert len(result.images) == 3 and len(result.meta["raw"]) == 3
   assert ksampler_seeds(fake) == [1000, 1001, 1002]
   assert {p.replace("\\", "/").rsplit("/", 1)[1] for p in result.images} == {"prop_000.png", "prop_001.png", "prop_002.png"}


def test_prop_fills_prompt_models_and_work_size(fake, tmp_path):
   providers.get("local").make(prop(tmp_path, seed=5, negative="blurry", options={"work_size": 256}))
   sent = json.dumps(fake.state.prompts[0])
   assert "u.safetensors" in sent and "barrel" in sent and "blurry" in sent
   latent = next(n for n in fake.state.prompts[0].values() if n["class_type"] == "EmptyLatentImage")
   assert latent["inputs"]["width"] == 256 and latent["inputs"]["height"] == 256
   assert not workflow.placeholders(fake.state.prompts[0])


def test_non_square_keeps_integer_factor(fake, tmp_path):
   result = providers.get("local").make(prop(tmp_path, seed=1, size=(48, 32)))
   latent = next(n for n in fake.state.prompts[0].values() if n["class_type"] == "EmptyLatentImage")
   assert (latent["inputs"]["width"], latent["inputs"]["height"]) == (480, 320)
   assert image.size(image.load(result.images[0])) == (48, 32)


def test_server_file_name_never_used_for_saving(fake, tmp_path):
   fake.state.output_name = "../../evil.png"
   result = providers.get("local").make(prop(tmp_path, seed=1))
   assert fake.state.views[-1]["filename"] == "../../evil.png"   # 질의에만 쓴다
   assert not (tmp_path / "evil.png").exists()
   assert all("evil" not in p for p in result.images + result.meta["raw"])


def test_missing_model_exits_2_before_network(fake, tmp_path):
   req = providers.ProviderRequest(kind="prop", out_dir=tmp_path / "out", options={"models": {"unet": "u"}})
   with pytest.raises(errors.UsageError, match=r"채울 값이 없다 : .*\$lora") as caught:
      providers.get("local").make(req)
   assert caught.value.exit_code == errors.EXIT_USAGE
   assert fake.state.calls == []


def test_dry_run_calls_nothing_and_writes_filled_workflow(fake, tmp_path):
   result = providers.get("local").make(prop(tmp_path, seed=7, variants=2, dry_run=True))
   assert fake.state.calls == []
   assert result.images == []
   written = read_json(tmp_path / "out" / "local_request.json")
   assert len(written["workflows"]) == 2
   assert written["seeds"] == [7, 8]
   assert "prop_001.png" in written["would_write"] and "raw/prop_000_512.png" in written["would_write"]
   assert written["endpoint"] == fake.url.split("//")[1]
   assert "http://" not in json.dumps(written)
   assert sorted((tmp_path / "out").iterdir()) == [tmp_path / "out" / "local_request.json"]


def test_user_workflow_file_overrides_builtin(fake, tmp_path):
   wf = {
      "1": {"class_type": "KSampler", "inputs": {"seed": "$seed", "text": "$prompt"}},
      "2": {"class_type": "SaveImage", "inputs": {"images": ["1", 0]}},
   }
   path = tmp_path / "mine.json"
   path.write_text(json.dumps(wf), encoding="utf-8")
   result = providers.get("local").make(prop(tmp_path, seed=3, options={"workflow": str(path)}))
   assert result.meta["workflow"] == "mine.json"
   assert fake.state.prompts[0]["1"]["inputs"] == {"seed": 3, "text": "barrel"}


def test_missing_node_on_server_exits_1(fake, tmp_path):
   del fake.state.nodes["UNETLoader"]
   with pytest.raises(errors.ArtToolError, match="UNETLoader") as caught:
      providers.get("local").make(prop(tmp_path, seed=1))
   assert caught.value.exit_code == errors.EXIT_ERROR
   assert "/prompt" not in fake.paths()
