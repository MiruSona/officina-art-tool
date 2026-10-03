"""tile preview — 그림은 전부 코드로 만든다. 설계 6-4 의 preview 줄을 하나씩 박는다."""

from __future__ import annotations

import json

import numpy as np
import pytest

from arttool import cli, image
from arttool.errors import ArtToolError, PathJailError, UsageError
from arttool.tiles import preview

GREEN = (40, 160, 60, 255)
DARK = (20, 90, 30, 255)
BROWN = (120, 80, 40, 255)


def flat(color, w=4, h=4):
   arr = image.new(w, h)
   arr[:, :] = color
   return arr


def setup_tiles(tmp_path, extra=None):
   tiles = tmp_path / "tiles"
   image.save(tiles / "grass_0.png", flat(GREEN))
   image.save(tiles / "grass_1.png", flat(DARK))
   image.save(tiles / "dirt.png", flat(BROWN))
   for name, arr in (extra or {}).items():
      image.save(tiles / f"{name}.png", arr)
   return tiles


def run_layout(tmp_path, layout, **kw):
   tiles = setup_tiles(tmp_path, kw.pop("extra", None))
   spec = tmp_path / "layout.json"
   spec.write_text(json.dumps(layout), encoding="utf-8")
   return preview.run(spec, tiles, tmp_path / "out" / "preview.png", **kw)


def test_weights_same_seed_same_result(tmp_path):
   layout = {"size": [6, 5], "weights": {"grass_0": 6, "grass_1": 2, "dirt": 1}, "seed": 3}
   first = run_layout(tmp_path, layout)
   pic1 = image.load(tmp_path / "out" / "preview.png")
   second = run_layout(tmp_path, layout)
   pic2 = image.load(tmp_path / "out" / "preview.png")
   assert first["grid"] == second["grid"]
   assert np.array_equal(pic1, pic2)
   assert sum(first["counts"].values()) == 30
   assert image.size(pic1) == (24, 20)


def test_weights_seed_changes_grid(tmp_path):
   base = {"size": [8, 8], "weights": {"grass_0": 1, "grass_1": 1, "dirt": 1}}
   grids = {json.dumps(run_layout(tmp_path, {**base, "seed": s})["grid"]) for s in range(4)}
   assert len(grids) > 1


def test_weights_zero_never_used(tmp_path):
   report = run_layout(tmp_path, {"size": [5, 5], "weights": {"grass_0": 1, "dirt": 0}, "seed": 1})
   assert report["counts"].get("dirt", 0) == 0
   assert report["counts"]["grass_0"] == 25


def test_weights_seed_defaults_to_zero(tmp_path):
   a = run_layout(tmp_path, {"size": [4, 4], "weights": {"grass_0": 1, "dirt": 1}})
   b = run_layout(tmp_path, {"size": [4, 4], "weights": {"grass_0": 1, "dirt": 1}, "seed": 0})
   assert a["grid"] == b["grid"]
   assert a["seed"] == 0


def test_cells_exact_positions(tmp_path):
   layout = {"size": [3, 2], "cells": [["grass_0", "grass_1", "grass_0"], ["dirt", None, "dirt"]]}
   report = run_layout(tmp_path, layout)
   pic = image.load(tmp_path / "out" / "preview.png")
   assert image.size(pic) == (12, 8)
   assert tuple(pic[0, 0]) == GREEN
   assert tuple(pic[0, 4]) == DARK
   assert tuple(pic[4, 0]) == BROWN
   assert tuple(pic[4, 4]) == (0, 0, 0, 0)  # 빈 칸은 투명
   assert report["grid"][1][1] is None
   assert report["counts"] == {"grass_0": 2, "grass_1": 1, "dirt": 2}


def test_cells_size_optional_but_must_match(tmp_path):
   report = run_layout(tmp_path, {"cells": [["grass_0", "dirt"]]})
   assert report["size"] == [2, 1]
   with pytest.raises(ArtToolError, match="size"):
      run_layout(tmp_path, {"size": [3, 1], "cells": [["grass_0", "dirt"]]})


def test_cells_ragged_rows_rejected(tmp_path):
   with pytest.raises(ArtToolError):
      run_layout(tmp_path, {"cells": [["grass_0", "dirt"], ["dirt"]]})


def test_mixed_sizes_rejected(tmp_path):
   with pytest.raises(ArtToolError, match="크기"):
      run_layout(tmp_path, {"cells": [["grass_0", "big"]]}, extra={"big": flat(GREEN, 5, 4)})


def test_unknown_name_rejected(tmp_path):
   with pytest.raises(ArtToolError, match="nope"):
      run_layout(tmp_path, {"size": [2, 2], "weights": {"grass_0": 1, "nope": 1}})
   with pytest.raises(ArtToolError, match="nope"):
      run_layout(tmp_path, {"cells": [["grass_0", "nope"]]})


def test_name_with_png_suffix_ok(tmp_path):
   report = run_layout(tmp_path, {"cells": [["grass_0.png"]]})
   assert report["counts"] == {"grass_0.png": 1}


def test_name_escaping_folder_rejected(tmp_path):
   with pytest.raises(PathJailError):
      run_layout(tmp_path, {"cells": [["../grass_0"]]})


@pytest.mark.parametrize(
   "layout",
   [
      {"size": [2, 2]},                                                        # 둘 다 없음
      {"size": [2, 2], "weights": {"grass_0": 1}, "cells": [["grass_0"]]},     # 둘 다 있음
      {"size": [2, 2], "weights": {"grass_0": 1}, "colour": 1},                # 모르는 칸
      {"size": [0, 2], "weights": {"grass_0": 1}},                             # 0 칸
      {"size": [2], "weights": {"grass_0": 1}},                                # 꼴이 틀림
      {"weights": {"grass_0": 1}},                                             # weights 인데 size 없음
      {"size": [2, 2], "weights": {"grass_0": -1, "dirt": 2}},                 # 음수 무게
      {"size": [2, 2], "weights": {"grass_0": 0}},                             # 무게 합 0
      {"size": [2, 2], "weights": {"grass_0": True}},                          # bool 무게
      {"size": [2, 2], "weights": {"grass_0": 1}, "seed": "a"},                # 정수 아닌 seed
      {"size": [2, 2], "cells": [["grass_0"]], "seed": 1},                     # cells 에 seed
      {"size": [2, 2], "weights": {}},                                         # 빈 무게
   ],
)
def test_bad_layout_rejected(tmp_path, layout):
   with pytest.raises(ArtToolError):
      run_layout(tmp_path, layout)


def test_too_big_rejected(tmp_path):
   with pytest.raises(ArtToolError, match="크다"):
      run_layout(tmp_path, {"size": [1000, 1000], "weights": {"grass_0": 1}})


def test_scale(tmp_path):
   run_layout(tmp_path, {"cells": [["grass_0", "dirt"]]}, scale=3)
   pic = image.load(tmp_path / "out" / "preview.png")
   assert image.size(pic) == (24, 12)
   with pytest.raises(UsageError):
      run_layout(tmp_path, {"cells": [["grass_0"]]}, scale=0)


def test_cli_tile_preview(tmp_path, capsys):
   tiles = setup_tiles(tmp_path)
   spec = tmp_path / "layout.json"
   spec.write_text(json.dumps({"size": [3, 3], "weights": {"grass_0": 2, "dirt": 1}, "seed": 7}), encoding="utf-8")
   out = tmp_path / "preview.png"
   code = cli.main(["tile", "preview", "--layout", str(spec), "--in", str(tiles), "--out", str(out), "--scale", "2", "--json"])
   assert code == 0
   data = json.loads(capsys.readouterr().out)
   assert data["status"] == "ok"
   assert image.size(image.load(out)) == (24, 24)


# --- 리뷰 뒤 더한 시험 ---


def test_pixels_over_limit_rejected(tmp_path):
   """칸은 한도 안이지만 픽셀이 넘친다. 100px 타일 한 장만 만들고 캔버스는 안 잡는다."""
   big = flat(GREEN, 100, 100)
   with pytest.raises(ArtToolError, match="미리보기가"):
      run_layout(tmp_path, {"size": [100, 100], "weights": {"big": 1}}, extra={"big": big})


@pytest.mark.parametrize("raw", ["NaN", "Infinity", "-Infinity"])
def test_weights_not_finite_rejected(tmp_path, raw):
   tiles = setup_tiles(tmp_path)
   spec = tmp_path / "layout.json"
   spec.write_text('{"size": [2, 2], "weights": {"grass_0": 1, "dirt": %s}}' % raw, encoding="utf-8")
   with pytest.raises(ArtToolError, match="weights"):
      preview.run(spec, tiles, tmp_path / "out.png")


def test_weights_sum_overflow_rejected(tmp_path):
   with pytest.raises(ArtToolError, match="weights"):
      run_layout(tmp_path, {"size": [2, 2], "weights": {"grass_0": 1e308, "dirt": 1e308}})


@pytest.mark.parametrize("name", ["sub/c", "sub\\c"])
def test_name_with_folder_rejected(tmp_path, name):
   image.save(tmp_path / "tiles" / "sub" / "c.png", flat(GREEN))
   with pytest.raises(ArtToolError, match="이름"):
      run_layout(tmp_path, {"cells": [[name]]})
