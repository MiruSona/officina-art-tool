"""local 제공자 inpaint 흐름 시험 : 밖 바이트 동일 · 안쪽 색 · 크기 검사 · 손질 함수."""

import io
import os

import numpy as np
import pytest
from PIL import Image

from arttool import errors, image, providers
from arttool.jsonio import read_json
from arttool.providers import postproc
from arttool.providers.local_config import ENV_CONFIG, ENV_ENDPOINT
from arttool.providers.local_plan import UPLOAD_BACKGROUND
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
   assert f'filename="arttool_image_{os.getpid()}.png"'.encode() in fake.state.uploads[0]   # 프로세스마다 다른 이름 + overwrite
   assert f'filename="arttool_mask_{os.getpid()}.png"'.encode() in fake.state.uploads[1]
   assert b"\x89PNG" in fake.state.uploads[0]


def sent_picture(body: bytes) -> np.ndarray:
   """multipart 몸통에서 PNG 를 꺼내 RGBA 배열로."""
   return np.array(Image.open(io.BytesIO(body[body.index(b"\x89PNG"):])).convert("RGBA"))


def test_uploaded_source_has_no_transparent_cells(fake, tmp_path):
   src, _ = write_source(tmp_path)
   providers.get("local").make(inpaint(tmp_path))
   sent = sent_picture(fake.state.uploads[0])
   assert sent.shape[:2] == (512, 512)
   assert (sent[:, :, 3] == 255).all()
   factor = 512 // 64
   clear = np.repeat(np.repeat(src[:, :, 3] == 0, factor, axis=0), factor, axis=1)
   assert clear.any()
   assert (sent[clear][:, :3] == UPLOAD_BACKGROUND).all()
   assert np.array_equal(sent[~clear][:, :3], np.repeat(np.repeat(src, factor, 0), factor, 1)[~clear][:, :3])


def test_half_transparent_cell_is_blended_onto_background(fake, tmp_path):
   src = np.zeros((64, 64, 4), dtype=np.uint8)
   src[:, :] = (40, 40, 40, 255)
   src[0, 0] = (61, 92, 155, 128)
   mask = np.zeros((64, 64, 4), dtype=np.uint8)
   mask[:, :, 3] = 255
   mask[30:40, 30:40, :3] = 255
   image.save(tmp_path / "src.png", src)
   image.save(tmp_path / "mask.png", mask)
   providers.get("local").make(inpaint(tmp_path))
   sent = sent_picture(fake.state.uploads[0])
   want = np.rint(np.array([61, 92, 155]) * 128 / 255 + np.array(UPLOAD_BACKGROUND) * 127 / 255)
   assert (sent[:8, :8, :3] == want).all()   # 64 → 512 라 8배로 키운 칸
   assert (sent[:8, :8, 3] == 255).all()


def test_padded_cells_get_background_too(fake, tmp_path):
   src = np.zeros((33, 33, 4), dtype=np.uint8)
   src[:, :] = (40, 40, 40, 255)
   mask = np.zeros((33, 33, 4), dtype=np.uint8)
   mask[:, :, 3] = 255
   mask[5:10, 5:10, :3] = 255
   image.save(tmp_path / "src.png", src)
   image.save(tmp_path / "mask.png", mask)
   factor, work = postproc.work_layout((33, 33), 512)
   scaled = 33 * factor
   assert work[0] > scaled   # 33 × 15 = 495 → 496 으로 덧댄다
   providers.get("local").make(inpaint(tmp_path, size=(33, 33)))
   sent = sent_picture(fake.state.uploads[0])
   assert sent.shape[:2] == (work[1], work[0])
   assert (sent[:, :, 3] == 255).all()
   assert (sent[scaled:, :, :3] == UPLOAD_BACKGROUND).all()
   assert (sent[:, scaled:, :3] == UPLOAD_BACKGROUND).all()
   assert (sent[:scaled, :scaled, :3] == (40, 40, 40)).all()


def test_transparent_outside_mask_stays_transparent(fake, tmp_path):
   src, area = write_source(tmp_path)
   result = providers.get("local").make(inpaint(tmp_path))
   out = image.load(result.images[0])
   clear_outside = (src[:, :, 3] == 0) & ~area
   assert clear_outside.any()
   assert (out[clear_outside][:, 3] == 0).all()
   assert result.meta["outside_changed"] == 0


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
   assert written["upload_background"] == [255, 255, 255]
   loads = [n["inputs"]["image"] for n in written["workflows"][0].values() if n["class_type"] == "LoadImage"]
   assert all(name.startswith("<올릴 그림") for name in loads)


# --- 올림 바탕(흰색) 되돌리기. 설계 : Docs/Design/2026-10-12-inpaint흰칸되돌리기설계.md ---

WHITE = (255, 255, 255)
DARK = (40, 40, 40)


def white_scene(tmp_path, rim: bool = False) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
   """64 원본 : 위는 투명, 32~48줄 · 16~48칸만 불투명 덩어리. 마스크 : 16~40줄 · 16~48칸.

   마스크 안 위쪽 16줄(512칸)은 원본이 투명이다. 모델 결과는 처음엔 온통 흰색 — 시험이 고쳐 쓴다.
   """
   src = np.zeros((64, 64, 4), dtype=np.uint8)
   src[32:48, 16:48] = (*DARK, 255)
   if rim:
      src[32, 16:48] = (230, 230, 230, 255)   # 10-12 통 그림의 밝은 테두리 흉내
   mask = np.zeros((64, 64, 4), dtype=np.uint8)
   mask[:, :, 3] = 255
   mask[16:40, 16:48, :3] = 255
   image.save(tmp_path / "src.png", src)
   image.save(tmp_path / "mask.png", mask)
   area = mask[:, :, 0] == 255
   model = np.zeros((64, 64, 3), dtype=np.uint8)
   model[:, :] = WHITE
   return src, area, model


def serve(fake, model: np.ndarray) -> None:
   """64 모델 결과를 8배로 키워 가짜 서버가 돌려주게 한다. BOX 축소하면 그대로 돌아온다."""
   big = np.repeat(np.repeat(model, 8, axis=0), 8, axis=1)
   buffer = io.BytesIO()
   Image.fromarray(big, mode="RGB").save(buffer, format="PNG")
   fake.state.view_body = buffer.getvalue()


def test_white_on_clear_cells_turns_clear(fake, tmp_path):
   src, area, model = white_scene(tmp_path)
   serve(fake, model)
   result = providers.get("local").make(inpaint(tmp_path))
   out = image.load(result.images[0])
   was_clear = area & (src[:, :, 3] == 0)
   assert np.array_equal(out[was_clear], src[was_clear])   # 원본과 바이트 같은 투명
   assert np.array_equal(out, src)                          # 불투명 칸은 snap source 로 원본 색
   assert result.meta["cleared"] == [512]
   assert result.meta["outside_changed"] == 0


def test_drawn_dark_object_on_clear_cells_stays(fake, tmp_path):
   src, area, model = white_scene(tmp_path)
   model[20:28, 24:40] = (60, 60, 60)   # 투명 자리에 새로 그린 쇠판 흉내
   serve(fake, model)
   result = providers.get("local").make(inpaint(tmp_path))
   out = image.load(result.images[0])
   assert (out[20:28, 24:40, 3] == 255).all()
   assert (out[20:28, 24:40, :3] == DARK).all()
   assert result.meta["cleared"] == [512 - 8 * 16]


def test_enclosed_white_stays_and_warns(fake, tmp_path):
   src, area, model = white_scene(tmp_path)
   model[18:30, 20:36] = (60, 60, 60)
   model[20:28, 22:34] = WHITE   # 그린 덩어리 안에 갇힌 흰 반짝임
   serve(fake, model)
   result = providers.get("local").make(inpaint(tmp_path, options={"snap": "none"}))
   out = image.load(result.images[0])
   assert (out[20:28, 22:34] == (*WHITE, 255)).all()
   assert result.meta["cleared"] == [512 - 12 * 16]
   warned = [w for w in result.warnings if "inpaint_000" in w and "이어져" in w]
   assert len(warned) == 1 and "96" in warned[0]


def test_white_on_opaque_source_is_not_cleared(fake, tmp_path):
   src, area, model = white_scene(tmp_path)
   serve(fake, model)
   result = providers.get("local").make(inpaint(tmp_path, options={"snap": "none"}))
   out = image.load(result.images[0])
   was_opaque = area & (src[:, :, 3] == 255)
   assert (out[was_opaque] == (*WHITE, 255)).all()   # snap none 이라 모델 흰색 그대로
   assert (out[area & (src[:, :, 3] == 0)][:, 3] == 0).all()


def test_clear_runs_before_snap_source(fake, tmp_path):
   src, area, model = white_scene(tmp_path, rim=True)
   serve(fake, model)
   was_clear = area & (src[:, :, 3] == 0)
   result = providers.get("local").make(inpaint(tmp_path))
   out = image.load(result.images[0])
   assert (out[was_clear][:, 3] == 0).all()   # 가장 밝은 원본 색 #E6E6E6 으로 안 눌린다
   off_req = inpaint(tmp_path, options={"clear_background": False})
   off_req.out_dir = tmp_path / "off"   # 같은 폴더에 다시 쓰면 지난 판 보호로 멈춘다
   off = providers.get("local").make(off_req)
   out_off = image.load(off.images[0])
   assert (out_off[was_clear] == (230, 230, 230, 255)).all()   # 끄면 10-12 부작용 그대로


@pytest.mark.parametrize("bad", [{"clear_tol": 300}, {"clear_tol": "a"}, {"clear_tol": True}, {"clear_tol": -1},
                                 {"clear_background": "yes"}, {"clear_background": 1}])
def test_clear_background_bad_values_exit_2(fake, tmp_path, bad):
   write_source(tmp_path)
   with pytest.raises(errors.UsageError, match="clear_") as caught:
      providers.get("local").make(inpaint(tmp_path, options=bad))
   assert "모르는 칸" not in str(caught.value)
   assert fake.state.calls == []


def test_clear_background_off_and_dry_run(fake, tmp_path):
   src, area, model = white_scene(tmp_path)
   serve(fake, model)
   result = providers.get("local").make(inpaint(tmp_path, options={"clear_background": False, "snap": "none"}))
   out = image.load(result.images[0])
   assert (out[area] == (*WHITE, 255)).all()   # 끄면 지금처럼 흰 불투명
   assert result.meta["cleared"] == [0]
   providers.get("local").make(inpaint(tmp_path, dry_run=True))
   assert read_json(tmp_path / "out" / "local_request.json")["clear_background"] == {"color": [255, 255, 255], "tol": 16}
   providers.get("local").make(inpaint(tmp_path, dry_run=True, options={"clear_tol": 0}))
   assert read_json(tmp_path / "out" / "local_request.json")["clear_background"]["tol"] == 0
   providers.get("local").make(inpaint(tmp_path, dry_run=True, options={"clear_background": False}))
   assert read_json(tmp_path / "out" / "local_request.json")["clear_background"] is None
   prop = providers.ProviderRequest(kind="prop", out_dir=tmp_path / "prop", prompt="barrel", dry_run=True,
                                    options={"models": dict(MODELS)})
   providers.get("local").make(prop)
   assert read_json(tmp_path / "prop" / "local_request.json")["clear_background"] is None


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


def test_clear_background_seeds_from_canvas_edge():
   """마스크 밖 투명이 없어도 캔버스 가장자리에 닿은 흰 칸은 되돌린다. 반투명 원본 칸은 대상이 아니다."""
   source = np.zeros((6, 6, 4), dtype=np.uint8)
   source[:, 3:] = (40, 40, 40, 255)
   source[2, 1] = (40, 40, 40, 128)
   area = np.zeros((6, 6), dtype=bool)
   area[:, :3] = True
   result = np.full((6, 6, 4), 255, dtype=np.uint8)
   result[:, 3:] = (40, 40, 40, 255)
   result[0, 0] = (250, 245, 255, 255)   # 흰색과 채널 차이 10 — tol 16 안
   out, cleared, enclosed = postproc.clear_background(result, source, area, (255, 255, 255), 16)
   assert int(cleared.sum()) == 17 and enclosed == 0   # 18칸 중 반투명 1칸 빼고
   assert not cleared[2, 1]
   assert (out[cleared] == source[cleared]).all()
   assert (out[2, 1] == 255).all()
   _, strict, _ = postproc.clear_background(result, source, area, (255, 255, 255), 5)
   assert not strict[0, 0]


def test_bad_color_exits_2():
   with pytest.raises(errors.UsageError):
      postproc.parse_colors(["#zzzzzz"], "extra_colors")
   with pytest.raises(errors.UsageError):
      postproc.parse_colors([[1, 2, 300]], "extra_colors")
