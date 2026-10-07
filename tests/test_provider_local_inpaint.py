"""local 제공자 inpaint 흐름 시험 : 밖 바이트 동일 · 안쪽 색 · 크기 검사 · 손질 함수."""

import numpy as np
import pytest

from arttool import errors, image, providers
from arttool.jsonio import read_json
from arttool.providers import postproc
from arttool.providers.local_config import ENV_CONFIG, ENV_ENDPOINT
from fake_comfy import FakeComfy

MODELS = {"unet": "u", "text_encoder": "t", "vae": "v", "lora": "l", "lora_strength": 1.0}
SOURCE_COLORS = [(61, 92, 155), (230, 200, 120), (40, 40, 40)]


@pytest.fixture
def fake(monkeypatch):
   monkeypatch.delenv(ENV_CONFIG, raising=False)
   with FakeComfy() as server:
      monkeypatch.setenv(ENV_ENDPOINT, server.url)
      yield server


def write_source(tmp_path, seed: int = 0, size: int = 64):
   """세 가지 색과 투명 칸이 섞인 원본, 무작위 네모 마스크."""
   rng = np.random.default_rng(seed)
   src = np.zeros((size, size, 4), dtype=np.uint8)
   picks = rng.integers(0, len(SOURCE_COLORS) + 1, size=(size, size))
   for index, rgb in enumerate(SOURCE_COLORS):
      src[picks == index] = (*rgb, 255)
   mask = np.zeros((size, size, 4), dtype=np.uint8)
   mask[:, :, 3] = 255
   x, y = rng.integers(0, size // 2, size=2)
   w, h = rng.integers(4, size // 2, size=2)
   mask[y:y + h, x:x + w, :3] = 255
   image.save(tmp_path / "src.png", src)
   image.save(tmp_path / "mask.png", mask)
   return src, mask[:, :, 0] == 255


def inpaint(tmp_path, **kw) -> providers.ProviderRequest:
   options = {"models": dict(MODELS), **kw.pop("options", {})}
   return providers.ProviderRequest(
      kind="inpaint", out_dir=tmp_path / "out", reference=str(tmp_path / "src.png"), mask=str(tmp_path / "mask.png"),
      prompt="lid open", seed=1, options=options, **kw,
   )


@pytest.mark.parametrize("seed", [0, 1, 2, 3, 4])
def test_outside_mask_is_byte_identical(fake, tmp_path, seed):
   src, area = write_source(tmp_path, seed)
   result = providers.get("local").make(inpaint(tmp_path))
   out = image.load(result.images[0])
   assert np.array_equal(out[~area], src[~area])
   assert result.meta["outside_changed"] == 0
   inside = {tuple(px[:3]) for px in out[area]}
   assert inside <= set(SOURCE_COLORS)
   assert (out[area][:, 3] == 255).all()


def test_extra_colors_join_snap_table(fake, tmp_path):
   _, area = write_source(tmp_path)
   result = providers.get("local").make(inpaint(tmp_path, options={"extra_colors": ["#00ff00", [255, 0, 0]]}))
   inside = {tuple(px[:3]) for px in image.load(result.images[0])[area]}
   assert inside <= set(SOURCE_COLORS) | {(0, 255, 0), (255, 0, 0)}


def test_snap_profile_uses_palette_only(fake, tmp_path):
   _, area = write_source(tmp_path)
   result = providers.get("local").make(inpaint(tmp_path, options={"snap": "profile", "palette": ["#112233", "#ddeeff"]}))
   inside = {tuple(px[:3]) for px in image.load(result.images[0])[area]}
   assert inside <= {(0x11, 0x22, 0x33), (0xDD, 0xEE, 0xFF)}


def test_snap_profile_without_palette_exits_2(fake, tmp_path):
   write_source(tmp_path)
   with pytest.raises(errors.UsageError, match="palette"):
      providers.get("local").make(inpaint(tmp_path, options={"snap": "profile"}))
   assert fake.state.calls == []


def test_snap_none_keeps_raw_colors_inside(fake, tmp_path):
   src, area = write_source(tmp_path)
   result = providers.get("local").make(inpaint(tmp_path, options={"snap": "none"}))
   out = image.load(result.images[0])
   assert np.array_equal(out[~area], src[~area])
   assert len({tuple(px[:3]) for px in out[area]}) > len(SOURCE_COLORS)


def test_uploads_source_and_mask_scaled_up(fake, tmp_path):
   write_source(tmp_path)
   providers.get("local").make(inpaint(tmp_path))
   assert len(fake.state.uploads) == 2
   sent = fake.state.prompts[0]
   names = {node["inputs"]["image"] for node in sent.values() if node["class_type"] == "LoadImage"}
   assert names == {"arttool_up1.png", "arttool_up2.png"}
   assert b"\x89PNG" in fake.state.uploads[0]


def test_size_mismatch_exits_2(fake, tmp_path):
   write_source(tmp_path)
   with pytest.raises(errors.UsageError, match="요청 size"):
      providers.get("local").make(inpaint(tmp_path, size=(32, 32)))
   image.save(tmp_path / "mask.png", image.new(32, 32, (255, 255, 255, 255)))
   with pytest.raises(errors.UsageError, match="마스크 크기"):
      providers.get("local").make(inpaint(tmp_path))
   assert fake.state.calls == []


def test_empty_mask_exits_2(fake, tmp_path):
   write_source(tmp_path)
   image.save(tmp_path / "mask.png", image.new(64, 64, (0, 0, 0, 255)))
   with pytest.raises(errors.UsageError, match="흰 칸"):
      providers.get("local").make(inpaint(tmp_path))


def test_inpaint_needs_mask(fake, tmp_path):
   write_source(tmp_path)
   req = inpaint(tmp_path)
   req.mask = None
   with pytest.raises(errors.UsageError, match="마스크"):
      providers.get("local").make(req)


def test_inpaint_dry_run_lists_uploads(fake, tmp_path):
   write_source(tmp_path)
   providers.get("local").make(inpaint(tmp_path, dry_run=True))
   assert fake.state.calls == []
   written = read_json(tmp_path / "out" / "local_request.json")
   assert len(written["uploads"]) == 2 and "512x512" in written["uploads"][0]
   loads = [n["inputs"]["image"] for n in written["workflows"][0].values() if n["class_type"] == "LoadImage"]
   assert all(name.startswith("<올릴 그림") for name in loads)


# --- 손질 함수 ---


def test_box_downscale_of_nearest_upscale_is_identity():
   rng = np.random.default_rng(9)
   arr = rng.integers(0, 256, size=(16, 24, 4), dtype=np.uint8)
   arr[:, :, 3] = 255   # 모델 결과는 불투명이다. 반투명은 PIL 이 알파를 곱해 줄여 반올림이 어긋난다
   assert np.array_equal(postproc.downscale_box(postproc.upscale_nearest(arr, 8), (24, 16)), arr)


def test_work_layout_prefers_16_multiples():
   assert postproc.work_layout((64, 64), 512) == (8, (512, 512))
   assert postproc.work_layout((48, 32), 512) == (10, (480, 320))
   assert postproc.work_layout((60, 120), 512) == (4, (240, 480))   # 배율 4 라야 60 이 16 의 배수가 된다
   assert postproc.work_layout((33, 33), 512) == (15, (496, 496))   # 맞는 배율이 없어 495 → 496 으로 덧댄다


def test_composite_and_count():
   source = np.zeros((4, 4, 4), dtype=np.uint8)
   result = np.full((4, 4, 4), 200, dtype=np.uint8)
   area = np.zeros((4, 4), dtype=bool)
   area[1:3, 1:3] = True
   assert postproc.count_outside_changed(result, source, area) == 12
   merged = postproc.composite_outside(result, source, area)
   assert postproc.count_outside_changed(merged, source, area) == 0
   assert (merged[area] == 200).all()


def test_bad_color_exits_2():
   with pytest.raises(errors.UsageError):
      postproc.parse_colors(["#zzzzzz"], "extra_colors")
   with pytest.raises(errors.UsageError):
      postproc.parse_colors([[1, 2, 300]], "extra_colors")
