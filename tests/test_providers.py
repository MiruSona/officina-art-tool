import pytest

import helpers
from arttool import image, providers
from arttool.errors import ArtToolError
from arttool.jsonio import read_json
from arttool.providers.local import ENV_ENDPOINT
from arttool.providers.pixellab import ENV_COST, ENV_KEY


def clear_env(monkeypatch):
   monkeypatch.delenv(ENV_ENDPOINT, raising=False)
   monkeypatch.delenv(ENV_KEY, raising=False)
   monkeypatch.delenv(ENV_COST, raising=False)


def test_code_always_available(monkeypatch):
   clear_env(monkeypatch)
   assert providers.available_names() == ["code"]
   assert set(providers.all_names()) == {"code", "local", "pixellab"}


def test_key_turns_provider_on(monkeypatch):
   clear_env(monkeypatch)
   monkeypatch.setenv(ENV_KEY, "비밀")
   assert "pixellab" in providers.available_names()


def test_picking_off_provider_is_an_error(monkeypatch):
   clear_env(monkeypatch)
   with pytest.raises(ArtToolError, match="켤 수 없다"):
      providers.get("pixellab")


def test_unknown_provider():
   with pytest.raises(ArtToolError, match="모르는 제공자"):
      providers.get("없음")


def test_bad_kind(tmp_path):
   req = providers.ProviderRequest(kind="없는것", out_dir=tmp_path)
   with pytest.raises(ArtToolError, match="모르는 kind"):
      req.validate()


def test_code_cuts_from_sheet(tmp_path):
   sheet = image.new(32, 16)
   sheet[:, :] = (61, 92, 155, 255)
   image.save(tmp_path / "src.png", sheet)

   req = providers.ProviderRequest(
      kind="character", out_dir=tmp_path / "out", size=(16, 16), directions=1, frames=2, reference=str(tmp_path / "src.png")
   )
   result = providers.get("code").make(req)
   assert len(result.images) == 2
   assert result.cost_usd == 0.0
   assert image.size(image.load(result.images[0])) == (16, 16)


def test_code_cuts_from_folder(tmp_path):
   folder = tmp_path / "assets"
   folder.mkdir()
   for index in range(3):
      image.save(folder / f"a{index}.png", helpers.blob(16, 16))

   req = providers.ProviderRequest(kind="tile", out_dir=tmp_path / "out", size=(16, 16), directions=1, frames=3, reference=str(folder))
   result = providers.get("code").make(req)
   assert len(result.images) == 3


def test_code_needs_reference(tmp_path):
   req = providers.ProviderRequest(kind="character", out_dir=tmp_path / "out")
   with pytest.raises(ArtToolError, match="참조 그림"):
      providers.get("code").make(req)


def test_code_too_few_frames(tmp_path):
   image.save(tmp_path / "src.png", helpers.blob(16, 16))
   req = providers.ProviderRequest(
      kind="character", out_dir=tmp_path / "out", size=(16, 16), directions=1, frames=4, reference=str(tmp_path / "src.png")
   )
   with pytest.raises(ArtToolError, match="장밖에"):
      providers.get("code").make(req)


def test_code_cannot_do_skeleton(tmp_path):
   req = providers.ProviderRequest(kind="skeleton", out_dir=tmp_path / "out")
   with pytest.raises(ArtToolError, match="못 만든다"):
      providers.get("code").make(req)


def test_pixellab_dry_run_writes_request(tmp_path, monkeypatch):
   clear_env(monkeypatch)
   monkeypatch.setenv(ENV_KEY, "비밀")
   monkeypatch.setenv(ENV_COST, "0.05")

   req = providers.ProviderRequest(kind="character", out_dir=tmp_path / "out", directions=4, frames=2, dry_run=True, prompt="슬라임")
   result = providers.get("pixellab").make(req)
   assert result.cost_usd == pytest.approx(0.4)
   assert result.images == []

   written = read_json(tmp_path / "out" / "pixellab_request.json")
   assert written["prompt"] == "슬라임"
   assert "비밀" not in str(written)


def test_pixellab_warns_without_price(tmp_path, monkeypatch):
   clear_env(monkeypatch)
   monkeypatch.setenv(ENV_KEY, "비밀")
   req = providers.ProviderRequest(kind="character", out_dir=tmp_path / "out", dry_run=True)
   result = providers.get("pixellab").make(req)
   assert result.warnings and "단가" in result.warnings[0]


def test_pixellab_refuses_real_call(tmp_path, monkeypatch):
   clear_env(monkeypatch)
   monkeypatch.setenv(ENV_KEY, "비밀")
   req = providers.ProviderRequest(kind="character", out_dir=tmp_path / "out")
   with pytest.raises(ArtToolError, match="아직 안 붙였다"):
      providers.get("pixellab").make(req)


def test_local_needs_endpoint(tmp_path, monkeypatch):
   clear_env(monkeypatch)
   monkeypatch.setenv(ENV_ENDPOINT, "http://mini:8080")
   req = providers.ProviderRequest(kind="tile", out_dir=tmp_path / "out", dry_run=True)
   result = providers.get("local").make(req)
   assert (tmp_path / "out" / "local_request.json").is_file()
   assert result.cost_usd == 0.0


def test_describe_shape(monkeypatch):
   clear_env(monkeypatch)
   rows = {row["name"]: row for row in providers.describe()}
   assert rows["code"]["available"] is True
   assert rows["pixellab"]["available"] is False
   assert "skeleton" in rows["pixellab"]["capabilities"]
