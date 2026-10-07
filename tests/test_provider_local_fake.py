"""설계 7-1 표 중 실패 길 · 자리표시 · 명령 사슬을 local 제공자 전체로 돌린다. 가짜 ComfyUI 만 부른다."""

import io
import json
import time

import numpy as np
import pytest
from PIL import Image

from arttool import cli, errors, image, providers
from arttool.jsonio import read_json
from arttool.providers.local_config import ENV_CONFIG, ENV_ENDPOINT
from fake_comfy import FakeComfy

MODELS = {"unet": "u", "text_encoder": "t", "vae": "v", "lora": "l", "lora_strength": 1.0}


@pytest.fixture
def fake(monkeypatch):
   monkeypatch.delenv(ENV_CONFIG, raising=False)
   with FakeComfy() as server:
      monkeypatch.setenv(ENV_ENDPOINT, server.url)
      yield server


def prop(tmp_path, **kw) -> providers.ProviderRequest:
   options = {"models": dict(MODELS), **kw.pop("options", {})}
   return providers.ProviderRequest(kind="prop", out_dir=tmp_path / "out", seed=1, options=options, **kw)


def test_quotes_and_newlines_reach_server_intact(fake, tmp_path):
   prompt = 'pixel art "barrel",\nwooden {lid} \\ $5'
   providers.get("local").make(prop(tmp_path, prompt=prompt))
   assert fake.state.prompts[0]["5"]["inputs"]["text"] == prompt


def test_ui_saved_workflow_exits_2(fake, tmp_path):
   path = tmp_path / "ui.json"
   path.write_text(json.dumps({"nodes": [], "links": [], "version": 0.4}), encoding="utf-8")
   with pytest.raises(errors.UsageError, match="API 꼴로 내보내라"):
      providers.get("local").make(prop(tmp_path, options={"workflow": str(path)}))
   assert fake.state.calls == []


def test_node_errors_400_exits_1_with_node(fake, tmp_path):
   fake.state.prompt_status = 400
   fake.state.node_errors = {"1": {"class_type": "UNETLoader", "errors": [{"message": "Value not in list", "details": "unet_name: 'u'"}]}}
   with pytest.raises(errors.ArtToolError, match="UNETLoader") as caught:
      providers.get("local").make(prop(tmp_path))
   assert caught.value.exit_code == errors.EXIT_ERROR


def test_history_error_exits_1(fake, tmp_path):
   fake.state.history = "error"
   with pytest.raises(errors.ArtToolError, match="KSampler : CUDA out of memory") as caught:
      providers.get("local").make(prop(tmp_path))
   assert caught.value.exit_code == errors.EXIT_ERROR


def test_timeout_from_config_interrupts(fake, tmp_path, monkeypatch):
   config = tmp_path / "local.yaml"
   config.write_text("timeout_s: 0.5\n", encoding="utf-8")
   monkeypatch.setenv(ENV_CONFIG, str(config))
   fake.state.history = "never"
   fake.state.queue_running = ["p1"]
   started = time.monotonic()
   with pytest.raises(errors.ArtToolError, match="시간 초과") as caught:
      providers.get("local").make(prop(tmp_path))
   assert caught.value.exit_code == errors.EXIT_ERROR
   assert fake.state.deleted == ["p1"] and "/interrupt" in fake.paths()
   assert time.monotonic() - started < 10


def test_not_png_exits_1_and_writes_nothing(fake, tmp_path):
   fake.state.view_body = b"GIF89a not a png"
   with pytest.raises(errors.ArtToolError, match="PNG 가 아니다"):
      providers.get("local").make(prop(tmp_path))
   assert not (tmp_path / "out").exists()


def sprite_on_white() -> bytes:
   """흰 바탕 가운데 네 색 몸통을 8배로 키우고 살짝 흔든 512 그림 — 모델 날것 흉내."""
   arr = np.full((64, 64, 3), 255, dtype=np.uint8)
   colors = np.array([(200, 60, 50), (60, 140, 200), (40, 40, 60), (240, 200, 120)], dtype=np.uint8)
   pick = np.random.default_rng(3).integers(0, 4, size=(36, 28))
   arr[14:50, 18:46] = colors[pick]
   big = np.repeat(np.repeat(arr, 8, axis=0), 8, axis=1).astype(np.int16)
   jitter = np.random.default_rng(4).integers(-3, 4, size=big.shape)
   body = np.clip(big + jitter, 0, 255).astype(np.uint8)
   body[:16, :16] = 255   # 모서리는 깨끗한 흰색이라 cutout --key corner 가 바탕을 잡는다
   buffer = io.BytesIO()
   Image.fromarray(body, mode="RGB").save(buffer, format="PNG")
   return buffer.getvalue()


def test_chain_make_cutout_merge_check(fake, tmp_path, capsys):
   fake.state.view_body = sprite_on_white()
   spec = tmp_path / "spec.json"
   spec.write_text(json.dumps({"prompt": "barrel", "seed": 1, "models": MODELS}), encoding="utf-8")
   gen, cut, merged = tmp_path / "gen", tmp_path / "cut", tmp_path / "merged"
   assert cli.main(["provider", "make", "--provider", "local", "--kind", "prop", "--spec", str(spec), "--out", str(gen)]) == 0
   (gen / "raw").rename(tmp_path / "raw_kept")   # 다음 명령은 폴더 바로 아래 PNG 만 본다
   assert cli.main(["cutout", "--in", str(gen), "--out", str(cut), "--key", "corner"]) == 0
   assert cli.main(["merge-colors", "--in", str(cut), "--out", str(merged), "--max-colors", "16"]) == 0
   report = tmp_path / "check.json"
   code = cli.main(["check", "--in", str(merged), "--report", str(report)])
   capsys.readouterr()
   assert code == 0, read_json(report)
   assert read_json(report)["status"] in ("ok", "warn")
   out = image.load(merged / "prop_000.png")
   assert out[0, 0, 3] == 0 and image.count_colors(out) <= 16
