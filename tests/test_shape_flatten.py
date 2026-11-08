"""render 쪼개기(trace + finish)와 납작화 flatten (2026-11-08 작은 다듬기 모델 설계 3절 · P3)."""

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from arttool import cli, image
from arttool.shape import parse, render
from arttool.shape.flatten import KNOBS, flatten, knobs, regions
from arttool.shape.spec import load

EXAMPLE = Path(__file__).resolve().parent.parent / "Example" / "slime.shape.json"

# 합성 명세 셋 — 쪼개기 전후 같음 · 눈 확인에 같이 쓴다. 기능(선 · 안쪽 선 · 질감 · 잠금 · 디더 · 옆 보기)을 골고루 켠다.
POT = {
   "version": 1, "canvas": {"size": [48, 48], "origin": [24, 40]}, "dither": 0.25, "max_colors": 16,
   "outline": {"mode": "selout", "inner_gap": 2},
   "materials": {
      "clay": {"ramp": ["#5A2E1C", "#8A4A2C", "#B8693E", "#D88C5A"], "ambient": 0.35},
      "lid": {"ramp": ["#3C4A5C", "#5C708A", "#8AA2BC"], "ambient": 0.4, "highlight": {"color": "#E6F0FA", "above": 0.95}},
   },
   "shapes": [
      {"type": "lathe", "material": "clay", "profile": [[0, 0], [10, 0], [15, 8], [14, 18], [9, 24], [0, 24]]},
      {"type": "sphere", "material": "lid", "r": 4, "pos": [0, 27, 0]},
   ],
   "texture": [{"kind": "mottle", "on": "clay", "cell": 2, "share": 0.3, "seed": 3}],
}
MUSHROOM = {
   "version": 1, "canvas": {"size": [48, 48], "origin": [24, 44]}, "max_colors": 20,
   "outline": {"mode": "solid", "color": "#1C1418", "inner_gap": 1.5},
   "materials": {
      "cap": {"ramp": ["#6A1420", "#A82434", "#D8404C", "#F07A70"], "ambient": 0.3, "rim": {"below": 0.25, "index": 1},
              "highlight": {"color": "#FFE0D8", "above": 0.96}},
      "stem": {"ramp": ["#9C8A6C", "#D0C0A0", "#F0E6CC"], "ambient": 0.5},
   },
   "shapes": [
      {"type": "capsule", "material": "stem", "r": 5, "length": 10, "pos": [0, 7, 0]},
      {"type": "ellipsoid", "material": "cap", "radii": [17, 9, 17], "pos": [0, 22, 0]},
   ],
   "texture": [{"kind": "hue_side", "on": "*", "shift": 10, "share": 0.35, "seed": 1}],
}
CRATE = {
   "version": 1, "canvas": {"size": [48, 48], "origin": [24, 24]}, "dither": 0.5,
   "outline": {"mode": "selout+light", "inner_gap": 3},
   "views": {"three": 35},
   "materials": {
      "wood": {"ramp": ["#4A2E18", "#6E4626", "#966238", "#BC844E"], "ambient": 0.45},
      "iron": {"ramp": ["#2C3034", "#555C64", "#8A949E"], "ambient": 0.3},
   },
   "shapes": [
      {"type": "box", "material": "wood", "size": [26, 26, 26], "round": 1},
      {"type": "box", "material": "iron", "size": [28, 4, 28], "pos": [0, 8, 0]},
   ],
   "texture": [{"kind": "wood_grain", "on": "wood", "density": 0.4, "length": 5, "seed": 2}],
   "palette_lock": {"colors": ["#4A2E18", "#6E4626", "#966238", "#BC844E", "#2C3034", "#555C64", "#8A949E", "#D4A870"],
                    "family": True},
}
SPECS = {"pot": POT, "mushroom": MUSHROOM, "crate": CRATE}

# 쪼개기 전(render 한 몸일 때) 코드로 뽑은 RGBA 바이트의 sha256 앞 16자. 쪼갠 뒤에도 칸까지 같아야 한다.
GOLDEN = {
   ("pot", "front"): "f405eaa8c83cc23b",
   ("mushroom", "front"): "bbfe416af1965294",
   ("crate", "three"): "088e298ce2a5a2ba",
   ("slime", "front"): "ff0e547429f601e3",
   ("slime", "left"): "5000fa845000e40d",
   ("slime", "back"): "030034a278a5b919",
}


def _digest(arr: np.ndarray) -> str:
   return hashlib.sha256(np.ascontiguousarray(arr).tobytes() + str(arr.shape).encode()).hexdigest()[:16]


def _rendered(name: str, view: str) -> np.ndarray:
   spec = load(EXAMPLE) if name == "slime" else parse(json.loads(json.dumps(SPECS[name])))
   return render(spec, view)[0]


@pytest.mark.parametrize("name, view", sorted(GOLDEN))
def test_render_split_keeps_pixels(name, view):
   assert _digest(_rendered(name, view)) == GOLDEN[(name, view)]


# --- 납작화 ---


@pytest.fixture(scope="module")
def pot() -> np.ndarray:
   return _rendered("pot", "front")


def test_flatten_keeps_size_and_alpha(pot):
   for seed in range(8):
      out, report = flatten(pot, seed)
      assert out.shape == pot.shape and out.dtype == np.uint8
      assert np.array_equal(out[:, :, 3], pot[:, :, 3]), seed
      assert report["seed"] == seed


def test_flatten_same_seed_same_result(pot):
   a, ra = flatten(pot, 5)
   b, rb = flatten(pot, 5)
   assert np.array_equal(a, b) and ra["knobs"] == rb["knobs"]


def test_flatten_other_seed_differs(pot):
   outs = [flatten(pot, s)[0] for s in range(4)]
   assert any(not np.array_equal(outs[0], o) for o in outs[1:])


def test_knob_ranges():
   for seed in range(200):
      k = knobs(seed)
      assert 2 <= k["ramp"] <= 4
      assert 0.3 <= k["ambient"] <= 0.9
      assert k["dither"] in (0.0, 0.25, 0.5)
      assert k["outline"] in KNOBS["outline"]
      assert k["inner_gap"] is None or 1 <= k["inner_gap"] <= 3
      assert isinstance(k["rim"], bool) and isinstance(k["highlight"], bool) and isinstance(k["lock"], bool)
      assert len(k["texture"]) <= 2 and all(0.25 <= t["strength"] <= 0.5 for t in k["texture"])
      assert 8 <= k["max_colors"] <= 16
      assert 0 <= k["blur"] <= 2
   share = sum(not knobs(s)["texture"] for s in range(400)) / 400
   assert 0.5 < share < 0.7   # 질감 없음 60%


def test_regions_cover_opaque_and_follow_materials(pot):
   labels, colors = regions(pot)
   solid = pot[:, :, 3] > 0
   assert np.all(labels[solid] >= 0) and np.all(labels[~solid] == -1)
   assert len(colors) == labels.max() + 1
   # 렌더러 출력(재질 둘)을 넣으면 덩어리 수가 재질 수 언저리
   big = [i for i in range(len(colors)) if (labels == i).sum() >= 8]
   assert 2 <= len(big) <= 6


def test_texture_runs_on_fake_hits(pot):
   """설계 3절 위험 — texture.apply 가 가짜 Hits 에서 돈다 (질감 켠 씨앗을 찾아 돌려 본다)."""
   seed = next(s for s in range(100) if knobs(s)["texture"])
   _, report = flatten(pot, seed)
   assert report["knobs"]["texture"] and "textured" in report["render"]


def test_cli_flatten_file_and_folder(tmp_path, pot):
   src = tmp_path / "in"
   src.mkdir()
   image.save(src / "a.png", pot)
   image.save(src / "b.png", _rendered("mushroom", "front"))
   one = tmp_path / "one.png"
   assert cli.main(["shape", "flatten", str(src / "a.png"), "--out", str(one), "--seed", "3"]) == 0
   assert np.array_equal(image.load(one), flatten(pot, 3)[0])
   out = tmp_path / "out"
   out.mkdir()
   assert cli.main(["shape", "flatten", str(src), "--out", str(out), "--seed", "3"]) == 0
   assert sorted(p.name for p in out.iterdir()) == ["a.png", "b.png"]
   # 폴더 입력에 --out 이 있는 파일이면 사용 오류 (파일 아래로 들어가 makedirs 가 깨지던 것)
   assert cli.main(["shape", "flatten", str(src), "--out", str(one), "--seed", "3"]) != 0


# --- 고리 1 : 불투명 타일 · 작은 부품 (P6 실측에서 갈색 판 + 노란 눈알이 노란 판으로 바뀌던 것) ---

BROWN, YELLOW = (112, 84, 60), (232, 196, 40)


def _plate_with_eye() -> np.ndarray:
   """24×24 불투명 갈색 판 + 가운데 4×4 노란 점 (손으로 만든 타일)."""
   arr = np.zeros((24, 24, 4), np.uint8)
   arr[:, :] = (*BROWN, 255)
   arr[10:14, 10:14] = (*YELLOW, 255)
   return arr


def _changed(a: np.ndarray, b: np.ndarray) -> float:
   solid = b[:, :, 3] > 0
   return float(np.any(a[solid][:, :3] != b[solid][:, :3], axis=1).mean())


def _delta_e(a, b) -> float:
   from arttool.shape.lock import to_lab
   return float(np.linalg.norm(to_lab(np.array([a])) - to_lab(np.array([b]))))


def test_regions_keep_small_part_on_opaque_tile():
   labels, colors = regions(_plate_with_eye())
   assert len(colors) == 2
   assert labels[0, 0] != labels[11, 11]


def _floor_tile() -> np.ndarray:
   """32×32 불투명 바닥 타일 : 연갈색 판 + 어두운 난간 두 줄 + 한 칸 잡티 몇 개 (P6 에서 난간이 사라지던 꼴)."""
   arr = np.zeros((32, 32, 4), np.uint8)
   arr[:, :] = (200, 170, 120, 255)
   arr[6:8, :] = (60, 40, 30, 255)
   arr[22:24, :] = (60, 40, 30, 255)
   arr[14, 5::7] = (176, 146, 100, 255)
   return arr


def _mode_color(arr: np.ndarray, own: np.ndarray):
   cols, n = np.unique(arr[own][:, :3], axis=0, return_counts=True)
   return tuple(int(v) for v in cols[n.argmax()])


@pytest.mark.parametrize("name", ["plate", "floor", "pot", "mushroom", "crate"])
def test_flatten_keeps_region_colors(name):
   """덩어리마다 납작화 뒤 가장 많은 색이 원본 그 자리 가장 많은 색과 가깝다(ΔE < 15). 덩어리 수도 그대로.

   불투명 타일(plate · floor)은 바뀐 칸 몫도 .35 아래 — 음영이 없는 그림이라 납작화가 거의 안 바꿔야 한다.
   (렌더러 그림은 음영 단이 많아 「음영이 빠지면」 칸이 많이 바뀌는 게 맞으니 몫은 안 잰다.)
   """
   src = {"plate": _plate_with_eye, "floor": _floor_tile}.get(name, lambda: _rendered(name, {"crate": "three"}.get(name, "front")))()
   labels, colors = regions(src)
   shares = []
   for seed in range(16):
      out, report = flatten(src, seed)
      if report["knobs"]["texture"] or report["knobs"]["lock"]:
         continue   # 질감 · 잠금은 일부러 색을 더 바꾸는 손잡이라 대표색 비교에서 뺀다
      assert len(regions(out)[1]) >= len(colors) or name not in ("plate", "floor"), (name, seed)
      shares.append(_changed(out, src))
      for i in range(labels.max() + 1):
         own = labels == i
         if own.sum() >= 12:
            assert _delta_e(_mode_color(out, own), _mode_color(src, own)) < 15, (name, seed, i)
   assert shares
   if name in ("plate", "floor"):
      assert np.mean(shares) <= 0.35, (name, shares)
