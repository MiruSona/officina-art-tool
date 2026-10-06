"""spiral 모양 · fx_swirl 템플릿 (6판 T4)."""
import argparse
import json
from pathlib import Path

import numpy as np
import pytest

from arttool.draw import shapes
from arttool.profile import tool_home
from arttool.template import TemplateError, kinds, run, schema


def _connected_8(mask: np.ndarray) -> bool:
   """칠한 칸이 8방향으로 한 덩이인가."""
   pts = {(int(y), int(x)) for y, x in zip(*np.nonzero(mask))}
   if not pts:
      return False
   todo = [next(iter(pts))]
   seen = {todo[0]}
   while todo:
      y, x = todo.pop()
      for dy in (-1, 0, 1):
         for dx in (-1, 0, 1):
            p = (y + dy, x + dx)
            if p in pts and p not in seen:
               seen.add(p)
               todo.append(p)
   return len(seen) == len(pts)


@pytest.mark.parametrize("size,turns,r0,r1,phase,cw", [
   ((64, 64), 2, 0.0, 30.0, 0.0, True),
   ((64, 64), 4, 3.0, 31.5, 0.37, False),
   ((33, 17), 0.5, 1.0, 8.0, 0.9, True),
   ((128, 128), 3.3, 0.0, 63.5, 0.125, True),
])
def test_one_px_spiral_is_8_connected(size, turns, r0, r1, phase, cw):
   mask = shapes.spiral(size, (size[0] - 1) / 2, (size[1] - 1) / 2, r0, r1, turns, 1, phase, cw)
   assert mask.shape == (size[1], size[0])
   assert _connected_8(mask)


def test_direction_mirrors():
   cw = shapes.spiral((64, 64), 31.5, 31.5, 2, 30, 2, 1, 0.0, True)
   ccw = shapes.spiral((64, 64), 31.5, 31.5, 2, 30, 2, 1, 0.0, False)
   assert not np.array_equal(cw, ccw)
   # y 뒤집기 ≈ 방향 바꾸기. 반올림(0.5 올림)이 위아래로 비대칭이라 칸 몇 개는 어긋난다.
   same = (cw & ccw[::-1, :]).sum()
   assert same >= 0.9 * cw.sum()


def test_width_thickens():
   one = shapes.spiral((64, 64), 31.5, 31.5, 2, 30, 2, 1)
   three = shapes.spiral((64, 64), 31.5, 31.5, 2, 30, 2, 3)
   assert three.sum() > one.sum() and not (one & ~three).any()


def _swirl() -> dict:
   data = schema.load("fx_swirl")
   data.pop("_source")
   return data


def test_fx_swirl_frames_nonzero_and_differ():
   data = _swirl()
   assert data["sizes"] == [[64, 64]] and len(data["frames"]) == 8
   masks = [kinds.Effect()._frame_mask((64, 64), f) for f in data["frames"]]
   assert all(m.sum() > 0 for m in masks)
   assert len({m.tobytes() for m in masks}) == 8


def test_fx_swirl_renders(tmp_path):
   ns = argparse.Namespace(sub="render", name="fx_swirl", size=None, out_dir=str(tmp_path / "o"), preset=None, scale=None, over=None, profile=None)
   run.run(ns)
   assert len(list((tmp_path / "o").rglob("*_f07*"))) >= 1


def _write(tmp_path: Path, spec: dict = None, frames: list = None) -> str:
   data = json.loads((tool_home() / "templates" / "fx_swirl.json").read_text(encoding="utf-8"))
   if spec is not None:
      base = dict(data["frames"][0]["draw"][0])
      base.update(spec)
      base = {k: v for k, v in base.items() if v is not None}
      data["frames"] = [{"draw": [base]}]
      data["check"]["frames"] = 1
   if frames is not None:
      data["frames"] = frames
      data["check"]["frames"] = len(frames)
   path = tmp_path / "t.json"
   path.write_text(json.dumps(data), encoding="utf-8")
   return str(path)


@pytest.mark.parametrize("change", [
   {"turns": 0.4}, {"turns": 4.5}, {"turns": True}, {"turns": "2"}, {"turns": None},
   {"r0": 0.5, "r1": 0.5}, {"r0": 0.6, "r1": 0.5}, {"r1": 1.5}, {"r0": -0.1}, {"r1": None}, {"r1": 10**300},
   {"width": 0}, {"width": 1.5}, {"width": True}, {"width": 33}, {"width": -1},
   {"phase": 1}, {"phase": -0.1}, {"phase": False},
   {"dir": "up"}, {"dir": 1}, {"dx": "1"}, {"spin": 1},
])
def test_bad_spiral_is_template_error(tmp_path, change):
   with pytest.raises(TemplateError):
      schema.load(_write(tmp_path, spec=change))


def test_effect_frame_cap(tmp_path):
   frame = {"draw": [{"shape": "dot", "size": 1}]}
   schema.load(_write(tmp_path, frames=[frame] * kinds.EFFECT_MAX_FRAMES))
   with pytest.raises(TemplateError, match="장까지"):
      schema.load(_write(tmp_path, frames=[frame] * (kinds.EFFECT_MAX_FRAMES + 1)))
