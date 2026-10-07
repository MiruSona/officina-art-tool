"""provider make --provider local 의 CLI · YAML 설정 · 앞이 이기는 차례 시험."""

import json
import shutil
from pathlib import Path

import pytest

from arttool import cli, errors, image, providers
from arttool.jsonio import read_json
from arttool.providers.local_config import ENV_CONFIG, ENV_ENDPOINT, load_settings
from fake_comfy import FakeComfy

ROOT = Path(__file__).resolve().parents[1]
MODELS = {"unet": "u.sft", "text_encoder": "t.sft", "vae": "v.sft", "lora": "l.sft", "lora_strength": 0.7}


@pytest.fixture
def fake(monkeypatch):
   monkeypatch.delenv(ENV_CONFIG, raising=False)
   with FakeComfy() as server:
      monkeypatch.setenv(ENV_ENDPOINT, server.url)
      yield server


def write_config(tmp_path, monkeypatch, text: str) -> Path:
   path = tmp_path / "conf" / "local.yaml"
   path.parent.mkdir(exist_ok=True)
   path.write_text(text, encoding="utf-8")
   monkeypatch.setenv(ENV_CONFIG, str(path))
   return path


def make(tmp_path, spec: dict, *extra) -> list[str]:
   spec_file = tmp_path / "spec.json"
   spec_file.write_text(json.dumps(spec), encoding="utf-8")
   return ["--json", "provider", "make", "--provider", "local", "--kind", "prop",
           "--spec", str(spec_file), "--out", str(tmp_path / "out"), *extra]


def test_cli_passes_new_spec_fields(fake, tmp_path, capsys):
   spec = {"size": [32, 32], "prompt": "p", "negative": "n", "seed": 10, "variants": 2, "models": MODELS, "work_size": 256}
   assert cli.main(make(tmp_path, spec)) == errors.EXIT_OK
   result = json.loads(capsys.readouterr().out)
   assert len(result["images"]) == 2
   assert image.size(image.load(result["images"][0])) == (32, 32)
   latent = next(n for n in fake.state.prompts[0].values() if n["class_type"] == "EmptyLatentImage")
   assert latent["inputs"]["width"] == 256
   assert [wf["8"]["inputs"]["seed"] for wf in fake.state.prompts] == [10, 11]


def test_cli_dry_run_zero_network(fake, tmp_path):
   assert cli.main(make(tmp_path, {"prompt": "p", "seed": 1, "models": MODELS}, "--dry-run")) == errors.EXIT_OK
   assert fake.state.calls == []
   assert read_json(tmp_path / "out" / "local_request.json")["workflow"] == "klein_prop.json"


def test_cli_server_down_exits_5(monkeypatch, tmp_path, capsys):
   monkeypatch.delenv(ENV_CONFIG, raising=False)
   monkeypatch.setenv(ENV_ENDPOINT, "http://127.0.0.1:9")
   assert cli.main(make(tmp_path, {"prompt": "p", "seed": 1, "models": MODELS})) == errors.EXIT_NO_EXE
   assert "닿지 않는다" in capsys.readouterr().err


def test_config_supplies_models_workflow_and_heavy(fake, tmp_path, monkeypatch):
   wf = {"1": {"class_type": "KSampler", "inputs": {"seed": "$seed", "m": "$unet"}}, "2": {"class_type": "SaveImage", "inputs": {}}}
   write_config(tmp_path, monkeypatch, "models:\n  unet: from_config\nworkflows:\n  prop: mine.json\nheavy: [mine.json]\n")
   (tmp_path / "conf" / "mine.json").write_text(json.dumps(wf), encoding="utf-8")
   req = providers.ProviderRequest(kind="prop", out_dir=tmp_path / "out", seed=1)
   result = providers.get("local").make(req)
   assert fake.state.prompts[0]["1"]["inputs"]["m"] == "from_config"
   assert result.meta["workflow"] == "mine.json"
   assert any("무거운 판" in w for w in result.warnings)


def test_spec_beats_config_beats_default(tmp_path, monkeypatch):
   write_config(tmp_path, monkeypatch, "models:\n  unet: a\n  vae: b\nwork_size: 256\ntimeout_s: 30\n")
   settings = load_settings("prop", {"models": {"unet": "spec"}})
   assert settings.models == {"unet": "spec", "vae": "b"}
   assert settings.work_size == 256 and settings.timeout_s == 30.0
   assert load_settings("prop", {"work_size": 1024}).work_size == 1024


def test_env_endpoint_beats_config(tmp_path, monkeypatch):
   write_config(tmp_path, monkeypatch, "endpoint: http://from-config:8188\n")
   monkeypatch.delenv(ENV_ENDPOINT, raising=False)
   assert load_settings("prop", {}).host == "from-config:8188"
   assert "local" in providers.available_names()
   monkeypatch.setenv(ENV_ENDPOINT, "http://from-env:1/")
   assert load_settings("prop", {}).host == "from-env:1"


def test_example_config_copied_as_is_leaves_models_missing(fake, tmp_path, monkeypatch):
   path = write_config(tmp_path, monkeypatch, "")
   shutil.copyfile(ROOT / "local.example.yaml", path)
   req = providers.ProviderRequest(kind="prop", out_dir=tmp_path / "out", dry_run=True)
   with pytest.raises(errors.UsageError, match="채울 값이 없다"):
      providers.get("local").make(req)


@pytest.mark.parametrize("text", ["work_size: 10\n", "work_size: big\n", "timeout_s: -1\n", "models: [a]\n", "[1, 2]\n", "a: [\n"])
def test_bad_config_exits_2(tmp_path, monkeypatch, text):
   write_config(tmp_path, monkeypatch, text)
   with pytest.raises(errors.UsageError):
      load_settings("prop", {})


def test_broken_config_hides_provider_instead_of_crashing(tmp_path, monkeypatch):
   monkeypatch.delenv(ENV_ENDPOINT, raising=False)
   write_config(tmp_path, monkeypatch, "a: [\n")
   assert "local" not in providers.available_names()


def test_missing_config_file_exits_2(tmp_path, monkeypatch):
   monkeypatch.setenv(ENV_CONFIG, str(tmp_path / "none.yaml"))
   with pytest.raises(errors.UsageError, match="설정 파일이 없다"):
      load_settings("prop", {})


def test_bad_snap_exits_2(tmp_path, monkeypatch):
   monkeypatch.delenv(ENV_CONFIG, raising=False)
   with pytest.raises(errors.UsageError, match="snap"):
      load_settings("inpaint", {"snap": "box"})
