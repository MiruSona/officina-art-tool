"""`tint` — 흰 겹 × 색 곱하기 (2026-10-04 피드백후속설계 3-6). 그림은 전부 코드로 만든다."""

from __future__ import annotations

import argparse

import numpy as np
import pytest

from arttool import image
from arttool.errors import UsageError
from arttool.sprite import tint

WHITE = (255, 255, 255)
GRAY = (200, 200, 200)


def _args(in_path, out_path, colors="#E85D5D,#5DA0E8", **over):
   values = {"in_dir": str(in_path), "out_dir": str(out_path), "colors": colors, "sheet": None, "scale": 4, "report": None}
   values.update(over)
   return argparse.Namespace(**values)


def _layer():
   """6×6. 흰 칸 · 밝은 회색 칸 · 반투명 칸 하나, 나머지 투명."""
   arr = image.new(6, 6)
   arr[1:5, 1:3] = (*WHITE, 255)
   arr[1:5, 3:5] = (*GRAY, 255)
   arr[0, 0] = (*WHITE, 128)
   return arr


def _save(tmp_path, arr, name="hair.png"):
   folder = tmp_path / "white"
   folder.mkdir(exist_ok=True)
   image.save(folder / name, arr)
   return folder


def test_tint_multiplies_rgb_keeps_alpha(tmp_path):
   src = _save(tmp_path, _layer())
   tint.run(_args(src, tmp_path / "t", colors="#808080"))
   out = image.load(tmp_path / "t" / "hair_808080.png")
   assert np.array_equal(out[:, :, 3], _layer()[:, :, 3])
   assert tuple(out[1, 3, :3]) == (100, 100, 100)          # 200 × 128 / 255 = 100.4
   assert tuple(out[2, 0]) == (0, 0, 0, 0)                  # 투명 칸은 그대로


def test_tint_white_becomes_color(tmp_path):
   src = _save(tmp_path, _layer())
   tint.run(_args(src, tmp_path / "t", colors="#E85D5D"))
   out = image.load(tmp_path / "t" / "hair_E85D5D.png")
   assert tuple(out[1, 1, :3]) == (0xE8, 0x5D, 0x5D)
   assert tuple(out[0, 0]) == (0xE8, 0x5D, 0x5D, 128)


def test_tint_names_per_color(tmp_path):
   src = _save(tmp_path, _layer())
   _save(tmp_path, _layer(), "cloth.png")
   rep = tint.run(_args(src, tmp_path / "t", colors="#e85d5d, #5DA0E8"))
   names = sorted(p.name for p in (tmp_path / "t").iterdir())
   assert names == ["cloth_5DA0E8.png", "cloth_E85D5D.png", "hair_5DA0E8.png", "hair_E85D5D.png"]
   assert rep["colors"] == ["#E85D5D", "#5DA0E8"]
   assert rep["status"] == "ok"


def test_tint_sheet_written(tmp_path):
   src = _save(tmp_path, _layer())
   rep = tint.run(_args(src, tmp_path / "t", sheet=str(tmp_path / "s.png")))
   board = image.load(tmp_path / "s.png")
   # 한 줄 = 원본 + 색 둘, 배율 4 · 칸 사이 2
   assert image.size(board) == (3 * 6 * 4 + 2 * 2, 6 * 4)
   assert rep["sheet"] == str(tmp_path / "s.png")


def test_tint_dark_source_warns(tmp_path):
   arr = image.new(4, 4, (90, 90, 90, 255))
   src = _save(tmp_path, arr)
   rep = tint.run(_args(src, tmp_path / "t"))
   assert rep["status"] == "warn"
   assert [w["rule"] for w in rep["warnings"]] == ["tint.dark_source"]


def test_tint_bad_hex_exit2(tmp_path):
   src = _save(tmp_path, _layer())
   for colors in ("#E85D5", "red", "", " , "):
      with pytest.raises(UsageError):
         tint.run(_args(src, tmp_path / "t", colors=colors))
   with pytest.raises(UsageError):
      tint.run(_args(src, tmp_path / "t", colors="#E85D5D,#e85d5d"))   # 같은 이름이 둘
   assert not (tmp_path / "t").exists()


def test_tint_refuses_in_place(tmp_path):
   src = _save(tmp_path, _layer())
   with pytest.raises(UsageError):
      tint.run(_args(src, src))
   with pytest.raises(UsageError):
      tint.run(_args(src, tmp_path / "t", sheet=str(src / "s.png")))
   assert sorted(p.name for p in src.iterdir()) == ["hair.png"]


# ── --gif (2판 C5) ──

def test_tint_gif_frames_duration_transparency(tmp_path):
   from PIL import Image
   folder = _save(tmp_path, _layer())
   gif = tmp_path / "anim.gif"
   result = tint.run(_args(folder, tmp_path / "out", gif=str(gif), duration=90))
   assert result["gif"]["frames"] == 2 and result["gif"]["duration"] == 90 and result["gif"]["path"]
   with Image.open(gif) as im:
      assert im.n_frames == 2
      assert im.size == (6, 6)
      assert im.info["duration"] == 90
      assert im.info["transparency"] == 0
      assert im.getpixel((5, 5)) == 0                  # 투명 칸 = 0번
      im.seek(1)
      rgba = np.array(im.convert("RGBA"))
   assert rgba[5, 5, 3] == 0
   assert tuple(rgba[2, 1]) == (0x5D, 0xA0, 0xE8, 255)   # 둘째 프레임 = 둘째 색 × 흰
   assert any(w["rule"] == "tint.gif_alpha" for w in result["warnings"])   # (0,0) 알파 128


def test_tint_gif_default_duration(tmp_path):
   from PIL import Image
   arr = _layer()
   arr[0, 0] = (0, 0, 0, 0)
   folder = _save(tmp_path, arr)
   gif = tmp_path / "anim.gif"
   result = tint.run(_args(folder, tmp_path / "out", gif=str(gif)))
   assert result["gif"]["duration"] == 110
   assert not any(w["rule"] == "tint.gif_alpha" for w in result["warnings"])
   with Image.open(gif) as im:
      assert im.info["duration"] == 110


def test_tint_duration_without_gif_exit2(tmp_path):
   folder = _save(tmp_path, _layer())
   with pytest.raises(UsageError):
      tint.run(_args(folder, tmp_path / "out", duration=90))


def test_tint_no_gif_report_unchanged(tmp_path):
   folder = _save(tmp_path, _layer())
   result = tint.run(_args(folder, tmp_path / "out"))
   assert "gif" not in result


def test_save_gif_over_255_colors_refused(tmp_path):
   from arttool.errors import ArtToolError
   arr = image.new(16, 17)
   for i in range(256):
      arr[i // 16, i % 16] = (i, 0, 0, 255)
   with pytest.raises(ArtToolError):
      image.save_gif([arr], tmp_path / "x.gif", 100)
   with pytest.raises(ArtToolError):
      image.save_gif([arr], tmp_path / "x.gif", 100, write=False)
   assert not (tmp_path / "x.gif").exists()


def test_tint_gif_refused_leaves_no_files(tmp_path):
   from arttool.errors import ArtToolError
   arr = image.new(16, 17)
   for i in range(256):
      arr[i // 16, i % 16] = (255, 255, i, 255)                 # 흰 쪽 256색 — 곱해도 255색을 넘는다
   folder = _save(tmp_path, arr)
   out = tmp_path / "out"
   with pytest.raises(ArtToolError):
      tint.run(_args(folder, out, colors="#FFFFFF", sheet=str(tmp_path / "s.png"), gif=str(tmp_path / "a.gif")))
   assert not out.exists() or not any(out.iterdir())
   assert not (tmp_path / "s.png").exists() and not (tmp_path / "a.gif").exists()


def test_tint_gif_needs_gif_suffix(tmp_path):
   folder = _save(tmp_path, _layer())
   with pytest.raises(UsageError):
      tint.run(_args(folder, tmp_path / "out", gif=str(tmp_path / "anim.png")))
   tint.run(_args(folder, tmp_path / "out", gif=str(tmp_path / "anim.GIF")))


def test_tint_gif_merged_frames_reported(tmp_path):
   from PIL import Image
   _save(tmp_path, _layer(), "a.png")
   folder = _save(tmp_path, _layer(), "b.png")                  # 같은 그림 둘 · 색 하나 → 같은 장이 연달아
   gif = tmp_path / "anim.gif"
   result = tint.run(_args(folder, tmp_path / "out", colors="#E85D5D", gif=str(gif)))
   with Image.open(gif) as im:
      assert im.n_frames == result["gif"]["frames"] == 1
   assert any(w["rule"] == "tint.gif_merged" for w in result["warnings"])
