"""outline selout 깊이(steps) 시험 — 2026-11-08 도형 렌더러 보완 고리 1."""

import json
import subprocess
import sys

import numpy as np
import pytest

from arttool import image
from arttool.draw import outline, shapes
from arttool.errors import ArtToolError
from arttool.palette import load_ramps

FILL = (0xF0, 0xC0, 0xA0)


def _ramps(tmp_path):
   data = {"version": 1, "name": "t", "ramp_len": 6, "outline": "#101018",
           "ramps": {"skin": ["#200808", "#301010", "#402020", "#804040", "#C08060", "#F0C0A0"]}}
   path = tmp_path / "pal.json"
   path.write_text(json.dumps(data), encoding="utf-8")
   return load_ramps(path), path


def _square():
   arr = image.new(12, 12)
   shapes.paint(arr, shapes.box((12, 12), 3, 3, 9, 9), FILL)
   return arr


@pytest.mark.parametrize("mode", ["selout", "selout+light"])
def test_steps_none_and_two_match_default(tmp_path, mode):
   ramps, _ = _ramps(tmp_path)
   base = outline(_square(), mode, ramps=ramps)
   assert np.array_equal(base, outline(_square(), mode, ramps=ramps, steps=None))
   if mode == "selout":
      assert np.array_equal(base, outline(_square(), mode, ramps=ramps, steps=2))


def test_steps_four_equals_two_passes_on_outside_ring(tmp_path):
   ramps, _ = _ramps(tmp_path)
   once = outline(_square(), "selout+light", ramps=ramps, steps=4)
   twice = outline(outline(_square(), "selout", ramps=ramps), "selout+light", ramps=ramps, where="inside")
   # 다른 칸은 두 번째 판에서 띠 끝(위 · 왼쪽으로도 빈 칸과 맞닿는 칸)이 빛 쪽으로 읽힌 2칸뿐이다
   diff = np.argwhere(np.any(once != twice, axis=2))
   assert len(diff) <= 2
   assert np.array_equal(once[:, :, 3], twice[:, :, 3])


def test_steps_past_ramp_bottom_falls_to_outline_color(tmp_path):
   ramps, _ = _ramps(tmp_path)
   out = outline(_square(), "selout", ramps=ramps, steps=8)
   ring = (out[:, :, 3] > 0) & ~(_square()[:, :, 3] > 0)
   assert {tuple(int(v) for v in c) for c in out[ring][:, :3]} == {(0x10, 0x10, 0x18)}


@pytest.mark.parametrize("bad", [0, 9, True, 2.5])
def test_bad_steps(tmp_path, bad):
   ramps, _ = _ramps(tmp_path)
   with pytest.raises(ArtToolError, match="steps"):
      outline(_square(), "selout", ramps=ramps, steps=bad)


def _cli(tmp_path, *extra):
   _, pal = _ramps(tmp_path)
   prof = tmp_path / "p.yaml"
   prof.write_text(f"name: t\npreset: topdown_action\npalette:\n  ramp_len: 6\n  outline: \"#101018\"\n  ramps_file: {pal.name}\n",
                   encoding="utf-8")
   image.save(tmp_path / "in.png", _square())
   return subprocess.run([sys.executable, "-m", "arttool", "--json", "--profile", str(prof), "outline", "--in",
                          str(tmp_path / "in.png"), "--out", str(tmp_path / "out.png"), *extra],
                         capture_output=True, text=True, cwd=tmp_path)


def test_cli_steps_reported_and_applied(tmp_path):
   p = _cli(tmp_path, "--mode", "selout", "--steps", "3")
   assert p.returncode == 0, p.stderr
   assert json.loads(p.stdout)["steps"] == 3
   out = image.load(tmp_path / "out.png")
   assert tuple(int(v) for v in out[2, 5, :3]) == (0x40, 0x20, 0x20)     # F0C0A0 에서 세 단 아래


def test_cli_steps_refused_for_other_modes(tmp_path):
   p = _cli(tmp_path, "--mode", "black", "--steps", "3")
   assert p.returncode == 2
