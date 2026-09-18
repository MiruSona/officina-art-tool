import pytest

from arttool import profile
from arttool.errors import ArtToolError
from arttool.ui import bake_ui, font


def prof(**over):
   return profile.load_profile("topdown_action", over)


def make_text(tmp_path):
   folder = tmp_path / "Text"
   folder.mkdir()
   (folder / "story.txt").write_text("안녕 세계", encoding="utf-8")
   (folder / "items.json").write_text('{"name": "물약"}', encoding="utf-8")
   (folder / "skip.md").write_text("여기는 안 읽는다", encoding="utf-8")
   return folder


def test_collect_only_wanted_extensions(tmp_path):
   make_text(tmp_path)
   chars, files, warnings = font.collect(["Text"], [".txt", ".json"], tmp_path)
   assert len(files) == 2
   assert "안" in chars and "물" in chars
   assert "읽" not in chars
   assert warnings == []


def test_collect_missing_dir(tmp_path):
   with pytest.raises(ArtToolError, match="훑을 폴더가 없다"):
      font.collect(["없음"], [".txt"], tmp_path)


def test_newlines_are_dropped(tmp_path):
   folder = tmp_path / "Text"
   folder.mkdir()
   (folder / "a.txt").write_text("가\n나\r\n", encoding="utf-8")
   chars, _files, _warn = font.collect(["Text"], [".txt"], tmp_path)
   assert chars == {"가", "나"}


def test_cp949_fallback_warns(tmp_path):
   folder = tmp_path / "Text"
   folder.mkdir()
   (folder / "old.txt").write_bytes("옛날 파일".encode("cp949"))
   chars, _files, warnings = font.collect(["Text"], [".txt"], tmp_path)
   assert "옛" in chars
   assert warnings and "cp949" in warnings[0]


def test_charset_is_sorted_and_merged():
   text = font.charset_text({"나", "가"}, "01")
   assert text == "01가나"


def test_build_writes_charset_only(tmp_path):
   make_text(tmp_path)
   out = tmp_path / "build" / "charset.txt"
   result = font.build(prof(), ["Text"], out, root=tmp_path)

   assert result["chars"] > 20
   assert result["files"] == 2
   assert result["family"] == "Galmuri11"
   assert result["native_px"] == 11

   text = out.read_text(encoding="utf-8").strip()
   assert "안" in text and "0" in text and "%" in text
   assert text == "".join(sorted(set(text)))
   # baker 는 ui bake 만 낸다 (같은 타입이 두 벌이 되면 Unity 가 컴파일을 못 한다)
   assert not (tmp_path / "build" / "TmpFontBaker.cs").exists()
   assert "ui bake" in result["note"]


def test_build_uses_profile_scan_dirs(tmp_path):
   make_text(tmp_path)
   p = prof(**{"ui.font.subset.scan_dirs": ["Text/"]})
   result = font.build(p, None, tmp_path / "charset.txt", root=tmp_path)
   assert result["scanned"] == ["Text/"]
   assert result["files"] == 2


def test_zero_characters(tmp_path):
   folder = tmp_path / "Text"
   folder.mkdir()
   (folder / "a.txt").write_text("\n\n", encoding="utf-8")
   p = prof(**{"ui.font.subset.always": ""})
   with pytest.raises(ArtToolError, match="글자가 0개다"):
      font.build(p, ["Text"], tmp_path / "charset.txt", root=tmp_path)


def test_baker_file_is_whole():
   text = (bake_ui.unity_dir() / font.BAKER).read_text(encoding="utf-8")
   assert "Tools/ArtTool/Bake UI Font" in text
   assert "GlyphRenderMode.RASTER_HINTED" in text
