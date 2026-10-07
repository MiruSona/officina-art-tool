"""provider local 코드 리뷰 반영 시험 : 입력 검증 · 16 배수 덧대기 · 큰 그림 거절 · 나눠 색 맞추기 · 반쯤 쓴 판 · 설정 칸."""

import io
import json

import numpy as np
import pytest
from PIL import Image

from arttool import cli, errors, image, providers
from arttool.jsonio import read_json
from arttool.providers import postproc, workflow
from arttool.providers.local_config import ENV_CONFIG, ENV_ENDPOINT, load_settings
from fake_comfy import FakeComfy, noise_png

MODELS = {"unet": "u", "text_encoder": "t", "vae": "v", "lora": "l", "lora_strength": 1.0}


@pytest.fixture
def fake(monkeypatch):
   monkeypatch.delenv(ENV_CONFIG, raising=False)
   with FakeComfy() as server:
      monkeypatch.setenv(ENV_ENDPOINT, server.url)
      yield server


def prop(tmp_path, **kw) -> providers.ProviderRequest:
   options = {"models": dict(MODELS), **kw.pop("options", {})}
   kw.setdefault("seed", 1)
   return providers.ProviderRequest(kind="prop", out_dir=tmp_path / "out", options=options, **kw)


# --- 입력 검증 (모두 종료 2, 네트워크 전에) ---


@pytest.mark.parametrize("bad", [
   {"size": (0, 64)}, {"size": (64,)}, {"size": (64.0, 64)}, {"size": (1024, 64)},
   {"seed": -1}, {"seed": True}, {"seed": "1"}, {"seed": 2**64 - 1, "variants": 2},
   {"prompt": None}, {"negative": 3}, {"variants": 65},
])
def test_bad_request_exits_2_before_network(fake, tmp_path, bad):
   with pytest.raises(errors.UsageError):
      providers.get("local").make(prop(tmp_path, dry_run=True, **bad))
   assert fake.state.calls == []


def test_largest_seed_still_fits(fake, tmp_path):
   result = providers.get("local").make(prop(tmp_path, seed=2**64 - 2, variants=2, dry_run=True))
   assert read_json(tmp_path / "out" / "local_request.json")["seeds"] == [2**64 - 2, 2**64 - 1]
   assert result.seed == 2**64 - 2


def test_cli_variants_over_cap_exits_2(fake, tmp_path):
   spec = tmp_path / "spec.json"
   spec.write_text(json.dumps({"variants": 65, "models": MODELS}), encoding="utf-8")
   argv = ["provider", "make", "--provider", "local", "--kind", "prop", "--spec", str(spec), "--out", str(tmp_path / "o")]
   assert cli.main(argv) == errors.EXIT_USAGE


# --- 16 배수 ---


@pytest.mark.parametrize("size, work", [((33, 33), (496, 496)), ((48, 32), (480, 320)), ((60, 120), (240, 480))])
def test_latent_size_is_16_multiple_and_result_is_request_size(fake, tmp_path, size, work):
   fake.state.view_body = noise_png(0, size=work[0]) if work[0] == work[1] else None
   result = providers.get("local").make(prop(tmp_path, size=size))
   latent = next(n for n in fake.state.prompts[0].values() if n["class_type"] == "EmptyLatentImage")
   assert (latent["inputs"]["width"], latent["inputs"]["height"]) == work
   assert image.size(image.load(result.images[0])) == size


def test_dry_run_raw_name_uses_padded_width(fake, tmp_path):
   providers.get("local").make(prop(tmp_path, size=(33, 33), dry_run=True))
   assert "raw/prop_000_496.png" in read_json(tmp_path / "out" / "local_request.json")["would_write"]


def test_padded_inpaint_keeps_outside_and_pads_mask_as_keep(fake, tmp_path):
   src = np.zeros((33, 33, 4), dtype=np.uint8)
   src[:, :] = (61, 92, 155, 255)
   mask = np.zeros((33, 33, 4), dtype=np.uint8)
   mask[:, :, 3] = 255
   mask[5:20, 5:20, :3] = 255
   image.save(tmp_path / "src.png", src)
   image.save(tmp_path / "mask.png", mask)
   fake.state.view_body = noise_png(0, size=496)
   req = providers.ProviderRequest(kind="inpaint", out_dir=tmp_path / "out", size=(33, 33), seed=1,
                                   reference=str(tmp_path / "src.png"), mask=str(tmp_path / "mask.png"),
                                   options={"models": dict(MODELS)})
   result = providers.get("local").make(req)
   assert result.meta["outside_changed"] == 0
   sent_mask = np.array(Image.open(io.BytesIO(fake.state.uploads[1].split(b"\r\n\r\n", 3)[3])))
   assert sent_mask.shape[:2] == (496, 496)
   assert sent_mask[495, 495, 0] == 0   # 덧댄 칸은 안 고친다


# --- 받은 그림 크기 ---


def test_too_big_picture_refused_before_decoding():
   big = noise_png(0, size=1100)
   with pytest.raises(errors.ArtToolError, match="너무 크다"):
      postproc.from_png(big, max_side=1024)


def test_decompression_bomb_refused(monkeypatch):
   monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)
   with pytest.raises(errors.ArtToolError, match="압축 폭탄"):
      postproc.from_png(noise_png(0, size=64), max_side=4096)


def test_provider_refuses_huge_server_picture(fake, tmp_path):
   fake.state.view_body = noise_png(0, size=1100)
   with pytest.raises(errors.ArtToolError, match="너무 크다"):
      providers.get("local").make(prop(tmp_path, options={"work_size": 512}))


# --- 색 맞추기 나눠 세기 ---


def test_snap_in_chunks_matches_brute_force():
   rng = np.random.default_rng(1)
   arr = rng.integers(0, 256, size=(100, 100, 4), dtype=np.uint8)   # 10000 칸 > 4096
   area = np.ones((100, 100), dtype=bool)
   colors = [tuple(int(v) for v in rng.integers(0, 256, size=3)) for _ in range(20)]
   out = postproc.snap_colors(arr, area, colors)
   table = np.array(sorted(set(colors)), dtype=np.int32)
   flat = arr[:, :, :3].reshape(-1, 3).astype(np.int32)
   want = table[((flat[:, None, :] - table[None]) ** 2).sum(axis=2).argmin(axis=1)]
   assert np.array_equal(out[:, :, :3].reshape(-1, 3), want.astype(np.uint8))


# --- 반쯤 쓴 판 ---


def test_failure_mid_variants_lists_written_files(fake, tmp_path):
   fake.state.fail_after = 1
   with pytest.raises(errors.ArtToolError) as caught:
      providers.get("local").make(prop(tmp_path, variants=3))
   message = str(caught.value)
   assert "이미 쓴 파일 1장 : prop_000.png" in message and "CUDA" in message
   assert caught.value.exit_code == errors.EXIT_ERROR


def test_failure_on_first_variant_has_no_written_note(fake, tmp_path):
   fake.state.fail_after = 0
   with pytest.raises(errors.ArtToolError) as caught:
      providers.get("local").make(prop(tmp_path, variants=2))
   assert "이미 쓴 파일" not in str(caught.value)


# --- 설정 칸 ---


def write_config(tmp_path, monkeypatch, text):
   path = tmp_path / "local.yaml"
   path.write_text(text, encoding="utf-8")
   monkeypatch.setenv(ENV_CONFIG, str(path))


def test_unknown_config_key_exits_2(tmp_path, monkeypatch):
   write_config(tmp_path, monkeypatch, "timeout: 30\n")
   with pytest.raises(errors.UsageError, match="모르는 칸 : timeout"):
      load_settings("prop", {})


def test_unknown_option_and_workflow_kind_exit_2(tmp_path, monkeypatch):
   monkeypatch.delenv(ENV_CONFIG, raising=False)
   with pytest.raises(errors.UsageError, match="모르는 칸 : seeds"):
      load_settings("prop", {"seeds": 3})
   write_config(tmp_path, monkeypatch, "workflows:\n  props: a.json\n")
   with pytest.raises(errors.UsageError, match="props"):
      load_settings("prop", {})


@pytest.mark.parametrize("text", ["work_size: 0\n", "timeout_s: 0\n"])
def test_zero_is_not_default(tmp_path, monkeypatch, text):
   write_config(tmp_path, monkeypatch, text)
   with pytest.raises(errors.UsageError):
      load_settings("prop", {})


def test_empty_snap_is_refused_not_default(tmp_path, monkeypatch):
   monkeypatch.delenv(ENV_CONFIG, raising=False)
   with pytest.raises(errors.UsageError, match="snap"):
      load_settings("inpaint", {"snap": ""})


# --- 워크플로 파일 ---


def test_workflow_file_with_bom(tmp_path):
   path = tmp_path / "wf.json"
   path.write_bytes(b"\xef\xbb\xbf" + json.dumps({"1": {"class_type": "SaveImage", "inputs": {}}}).encode("utf-8"))
   assert workflow.load_file(path)["1"]["class_type"] == "SaveImage"


def test_missing_workflow_message_shows_name_only(tmp_path):
   with pytest.raises(errors.UsageError) as caught:
      workflow.load_file(tmp_path / "secret_dir" / "none.json")
   assert "none.json" in str(caught.value) and "secret_dir" not in str(caught.value)
