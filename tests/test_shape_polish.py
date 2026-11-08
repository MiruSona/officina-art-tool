"""다듬기 polish table 엔진 (2026-11-08 작은 다듬기 모델 설계 4 · 7절 · P6). 손으로 만든 작은 표로 본다."""

import hashlib
import json

import numpy as np
import pytest

from arttool import cli, image
from arttool.errors import ArtToolError
from arttool.shape.polish import LEVELS, keys, load_model, polish

PAL = np.array([(200, 40, 40), (40, 40, 200), (40, 200, 40)], dtype=np.int64)
HEX = ["#C82828", "#2828C8", "#28C828"]


def _sprite() -> np.ndarray:
   """7×7 : 가운데 5×5 불투명(빨강 근처 색), 둘레 투명. 한 칸은 반투명."""
   arr = np.zeros((7, 7, 4), np.uint8)
   arr[1:6, 1:6] = (210, 50, 30, 255)
   arr[3, 3] = (190, 30, 50, 255)
   arr[1, 1, 3] = 128
   return arr


def _model(tmp_path, tables: dict, engine: str = "table") -> str:
   npz = tmp_path / "t.npz"
   empty = np.zeros(0, np.int64)
   np.savez(npz, **{f"keys{n}": tables.get(n, (empty, empty))[0] for n in range(LEVELS - 1)},
            **{f"vals{n}": tables.get(n, (empty, empty))[1].astype(np.uint8) for n in range(LEVELS - 1)})
   meta = {"version": 1, "kind": "shape_polish", "engine": engine, "file": npz.name,
           "sha256": hashlib.sha256(npz.read_bytes()).hexdigest(), "palette": HEX, "light": "top_left",
           "train": {"seed": 0, "split_sha256": "x"}}
   path = tmp_path / "m.json"
   path.write_text(json.dumps(meta), encoding="utf-8")
   return str(path)


def test_keys_shape_and_transparent():
   arr = _sprite()
   k = keys(arr, PAL)
   assert k.shape == (LEVELS, 7, 7)
   solid = arr[:, :, 3] > 0
   assert (k[:, ~solid] == -1).all() and (k[:, solid] >= 0).all()
   assert (k[-1][solid] == 0).all()   # 마지막 칸 = 입력 색을 붙인 번호 (모두 빨강 근처)


def test_ladder_falls_back_and_colors_in_palette(tmp_path):
   arr = _sprite()
   k = keys(arr, PAL)
   center = int(k[2, 3, 3])
   # 사다리 2칸 표에만 가운데 칸 열쇠 → 파랑. 0 · 1 칸 표는 비었다
   model = load_model(_model(tmp_path, {2: (np.array([center]), np.array([1]))}))
   out, rep = polish(model, arr)
   assert (out[:, :, 3] == arr[:, :, 3]).all()                      # 알파 그대로 (반투명 칸도)
   solid = arr[:, :, 3] > 0
   assert {tuple(c) for c in out[solid][:, :3]} <= {tuple(c) for c in PAL}
   hit = solid & (k[2] == center)
   assert (out[hit][:, :3] == PAL[1]).all() and (out[solid & ~hit][:, :3] == PAL[0]).all()
   assert rep["ladder"] == [0, 0, int(hit.sum()), int((solid & ~hit).sum())]
   assert rep["changed"] == int(solid.sum())                       # 입력 색이 팔레트 밖이라 모두 바뀜


def test_full_key_wins_over_lower_rungs(tmp_path):
   arr = _sprite()
   k = keys(arr, PAL)
   model = load_model(_model(tmp_path, {0: (np.unique(k[0][k[0] >= 0]), np.full(len(np.unique(k[0][k[0] >= 0])), 2)),
                                        2: (np.unique(k[2][k[2] >= 0]), np.full(len(np.unique(k[2][k[2] >= 0])), 1))}))
   out, rep = polish(model, arr)
   solid = arr[:, :, 3] > 0
   assert (out[solid][:, :3] == PAL[2]).all() and rep["ladder"][0] == int(solid.sum())


def test_sha256_mismatch_is_one_line_error(tmp_path):
   path = _model(tmp_path, {})
   (tmp_path / "t.npz").write_bytes((tmp_path / "t.npz").read_bytes() + b"x")
   with pytest.raises(ArtToolError, match="sha256") as err:
      load_model(path)
   assert "\n" not in str(err.value)


def test_onnx_engine_not_yet(tmp_path):
   with pytest.raises(ArtToolError, match="아직 없다"):
      load_model(_model(tmp_path, {}, engine="onnx"))


def test_cli_polish_writes_png_and_report(tmp_path):
   src = tmp_path / "in.png"
   image.save(src, _sprite())
   model = _model(tmp_path, {})
   out = tmp_path / "out.png"
   args = cli.build_parser().parse_args(["shape", "polish", str(src), "--out", str(out), "--model", model, "--ref", str(src)])
   rep = cli.run(args)
   got = image.load(out)
   assert got.shape == (7, 7, 4) and rep["ladder"][-1] == rep["opaque"] and "score" in rep and rep["ms"] >= 0
   with pytest.raises(ArtToolError):   # 원본 덮어쓰기 막음
      cli.run(cli.build_parser().parse_args(["shape", "polish", str(src), "--out", str(src), "--model", model]))
