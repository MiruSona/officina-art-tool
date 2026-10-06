"""`ui mockup` — 장면 JSON → 목업 PNG. 감옥 · 값 검사 · z 순서 · 9조각 · 글자."""
import json
import shutil
from pathlib import Path

import pytest

from arttool import cli, image

SYSTEM_FONT = Path("C:/Windows/Fonts/arial.ttf")


def _scene(work: Path, data: dict) -> Path:
   path = work / "scene.json"
   path.write_text(json.dumps(data), encoding="utf-8")
   return path


def _run(scene: Path, out: Path, *extra) -> int:
   return cli.main(["ui", "mockup", "--scene", str(scene), "--out", str(out), *extra])


def _result(capsys) -> dict:
   """경고가 있으면 앞에 「경고 N건」 줄이 붙는다. JSON 몫만 읽는다."""
   out = capsys.readouterr().out
   return json.loads(out[out.index("{"):])


def _pics(work: Path) -> None:
   image.save(work / "red.png", image.new(2, 2, (255, 0, 0, 255)))
   image.save(work / "blue.png", image.new(2, 2, (0, 0, 255, 255)))
   # 4x4 판넬 + 1px 안내선 = 6x6. 가운데 한 칸만 늘어난다
   arr = image.new(6, 6)
   arr[1:5, 1:5] = (0, 255, 0, 255)
   arr[0, 2] = arr[2, 0] = (0, 0, 0, 255)
   image.save(work / "p.9.png", arr)


def _base(**more) -> dict:
   return {"version": 1, "canvas": [6, 6], "background": "#101010", "nodes": [], **more}


def test_z_order_and_pixels(tmp_path, capsys):
   _pics(tmp_path)
   scene = _scene(tmp_path, _base(nodes=[
      {"kind": "image", "src": "blue.png", "at": [1, 1], "z": 5},
      {"kind": "image", "src": "red.png", "at": [1, 1]},               # z 0 → 먼저, 파랑에 가려짐
      {"kind": "image", "src": "red.png", "at": [4, 4], "scale": 2},   # 잘림
      {"kind": "panel", "src": "p.9.png", "at": [0, 2], "size": [4, 4], "z": 1}]))
   out = tmp_path / "o" / "m.png"
   assert _run(scene, out) == 0                                     # 경고만 있으면 종료 0
   result = _result(capsys)
   assert result["status"] == "warn" and result["warnings"][0]["rule"] == "ui_mockup.clipped"
   arr = image.load(out)
   assert tuple(arr[1, 1]) == (0, 0, 255, 255)
   assert tuple(arr[0, 0]) == (16, 16, 16, 255)
   assert tuple(arr[5, 5]) == (255, 0, 0, 255)
   assert tuple(arr[5, 0]) == (0, 255, 0, 255)


def test_scale_and_set(tmp_path):
   _pics(tmp_path)
   scene = _scene(tmp_path, _base(nodes=[{"kind": "image", "id": "slot", "src": "red.png", "at": [0, 0]}]))
   out = tmp_path / "m.png"
   assert _run(scene, out, "--scale", "2", "--set", "slot=blue.png") == 0
   arr = image.load(out)
   assert image.size(arr) == (12, 12) and tuple(arr[3, 3]) == (0, 0, 255, 255)
   assert _run(scene, out, "--set", "nope=blue.png") == 2


@pytest.mark.parametrize("src", ["../red.png", "/etc/passwd", "C:/Windows/win.ini", "a\\..\\red.png",
                                 "//server/share/x.png", "sub/../../red.png", "", 3])
def test_jail(tmp_path, src):
   work = tmp_path / "w"
   work.mkdir()
   _pics(tmp_path)
   scene = _scene(work, _base(nodes=[{"kind": "image", "src": src, "at": [0, 0]}]))
   assert _run(scene, tmp_path / "m.png") == 2


@pytest.mark.parametrize("node", [
   {"kind": "image", "src": "red.png", "at": [True, 0]},
   {"kind": "image", "src": "red.png", "at": [1.5, 0]},
   {"kind": "image", "src": "red.png", "at": ["1", 0]},
   {"kind": "image", "src": "red.png", "at": [0, 0], "scale": 9},
   {"kind": "image", "src": "red.png", "at": [0, 0], "scale": -1},
   {"kind": "image", "src": "red.png", "at": [10 ** 30, 0]},
   {"kind": "image", "src": "red.png", "at": [0, 0], "what": 1},
   {"kind": "video", "src": "red.png", "at": [0, 0]},
   {"kind": "panel", "src": "red.png", "at": [0, 0], "size": [3, 3]},
   {"kind": "panel", "src": "p.9.png", "at": [0, 0], "size": [3, 3], "mode": "warp"},
   {"kind": "text", "text": "a", "font": "none", "at": [0, 0]},
   "string",
   {"kind": [], "src": "red.png", "at": [0, 0]},                     # 해시 안 되는 값 → 종료 2 (예전엔 1)
   {"kind": {}, "src": "red.png", "at": [0, 0]},
   {"kind": "text", "text": "a", "font": [], "at": [0, 0]},
   {"kind": "text", "text": "a", "font": {}, "at": [0, 0]},
   {"kind": "panel", "src": "p.9.png", "at": [0, 0], "size": [3, 3], "mode": []},
   {"kind": "image", "src": [], "at": [0, 0]},
   {"kind": "image", "src": "red.png", "at": [0, 0], "id": []},
])
def test_bad_nodes(tmp_path, node):
   _pics(tmp_path)
   assert _run(_scene(tmp_path, _base(nodes=[node])), tmp_path / "m.png") == 2


def test_bad_scene(tmp_path):
   assert _run(_scene(tmp_path, _base(extra=1)), tmp_path / "m.png") == 2
   assert _run(_scene(tmp_path, _base(version=2)), tmp_path / "m.png") == 2
   assert _run(_scene(tmp_path, _base(canvas=[5000, 5])), tmp_path / "m.png") == 2
   assert _run(_scene(tmp_path, _base(canvas=[4096, 4096])), tmp_path / "m.png", "--scale", "3") == 2
   deep = tmp_path / "scene.json"
   deep.write_text("[" * 100000 + "]" * 100000, encoding="utf-8")
   assert _run(deep, tmp_path / "m.png") == 2
   big = tmp_path / "big.json"
   big.write_text(" " * (300 * 1024) + "{}", encoding="utf-8")
   assert _run(big, tmp_path / "m.png") == 2


def test_out_same_as_input(tmp_path):
   _pics(tmp_path)
   scene = _scene(tmp_path, _base(nodes=[{"kind": "image", "id": "s", "src": "red.png", "at": [0, 0]}]))
   before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
   assert _run(scene, tmp_path / "red.png") == 2                    # 장면이 읽는 그림
   assert _run(scene, scene) == 2                                   # 장면 JSON 자체
   assert _run(scene, tmp_path / "blue.png", "--set", "s=blue.png") == 2   # --set 으로 읽게 된 그림
   assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before


@pytest.mark.parametrize("src", ["../red.png", "/etc/passwd", "C:/Windows/win.ini", "sub/../../red.png"])
def test_set_jail(tmp_path, src):
   work = tmp_path / "w"
   work.mkdir()
   _pics(tmp_path)
   _pics(work)
   scene = _scene(work, _base(nodes=[{"kind": "image", "id": "s", "src": "red.png", "at": [0, 0]}]))
   assert _run(scene, tmp_path / "m.png", "--set", f"s={src}") == 2
   assert not (tmp_path / "m.png").exists()


@pytest.mark.skipif(not SYSTEM_FONT.is_file(), reason="시험 글꼴 없음")
def test_set_only_image_and_panel(tmp_path):
   _pics(tmp_path)
   shutil.copy(SYSTEM_FONT, tmp_path / "f.ttf")
   scene = _scene(tmp_path, _base(fonts={"b": {"file": "f.ttf", "size": 8}}, nodes=[
      {"kind": "text", "id": "t", "text": "a", "font": "b", "at": [0, 0]},
      {"kind": "panel", "id": "p", "src": "p.9.png", "at": [0, 0], "size": [4, 4]}]))
   assert _run(scene, tmp_path / "m.png", "--set", "t=red.png") == 2
   assert _run(scene, tmp_path / "m.png", "--set", "p=p.9.png") == 0


def test_big_image_times_scale_rejected_before_drawing(tmp_path):
   _pics(tmp_path)
   image.save(tmp_path / "big.png", image.new(2048, 2048))
   scene = _scene(tmp_path, _base(nodes=[
      {"kind": "image", "src": "red.png", "at": [0, 0]},
      {"kind": "image", "src": "big.png", "at": [0, 0], "scale": 8}]))
   assert _run(scene, tmp_path / "m.png") == 2
   assert not (tmp_path / "m.png").exists()


def test_alpha_over(tmp_path):
   image.save(tmp_path / "half.png", image.new(2, 2, (0, 0, 255, 128)))
   scene = _scene(tmp_path, _base(background="#ffffff", nodes=[{"kind": "image", "src": "half.png", "at": [0, 0]}]))
   assert _run(scene, tmp_path / "m.png") == 0
   assert tuple(image.load(tmp_path / "m.png")[0, 0]) == (127, 127, 255, 255)   # 흰 바탕과 섞인다, 구멍 없음
   del_bg = _base(nodes=[{"kind": "image", "src": "half.png", "at": [0, 0]},
                         {"kind": "image", "src": "half.png", "at": [0, 0]}])
   del del_bg["background"]
   assert _run(_scene(tmp_path, del_bg), tmp_path / "n.png") == 0
   px = image.load(tmp_path / "n.png")[0, 0]
   assert tuple(px[:3]) == (0, 0, 255) and px[3] == 192                       # 투명 바탕 : 0.5 + 0.5·0.5


def test_dry_run_writes_nothing(tmp_path):
   _pics(tmp_path)
   scene = _scene(tmp_path, _base(nodes=[{"kind": "image", "src": "red.png", "at": [0, 0]}]))
   before = sorted(p.name for p in tmp_path.rglob("*"))
   assert _run(scene, tmp_path / "o" / "m.png", "--dry-run") == 0
   assert sorted(p.name for p in tmp_path.rglob("*")) == before


@pytest.mark.skipif(not SYSTEM_FONT.is_file(), reason="시험 글꼴 없음")
def test_text_hidden_by_panel_and_hard_alpha(tmp_path):
   _pics(tmp_path)
   shutil.copy(SYSTEM_FONT, tmp_path / "f.ttf")
   fonts = {"body": {"file": "f.ttf", "size": 12}}
   text = {"kind": "text", "text": "W\u4e00", "font": "body", "at": [0, 0], "color": "#ffffff", "z": 0}
   cover = {"kind": "panel", "src": "p.9.png", "at": [0, 0], "size": [20, 20], "z": 1}
   scene = _scene(tmp_path, {"version": 1, "canvas": [20, 20], "fonts": fonts, "nodes": [text, cover]})
   out = tmp_path / "m.png"
   _run(scene, out)
   arr = image.load(out)
   assert not (arr[:, :, :3] == 255).all(axis=2).any()          # 패널(z 1)이 글자(z 0)를 가린다
   scene = _scene(tmp_path, {"version": 1, "canvas": [20, 20], "fonts": fonts, "nodes": [text]})
   _run(scene, out)
   arr = image.load(out)
   assert set(arr[:, :, 3].ravel().tolist()) <= {0, 255}
   assert (arr[:, :, 3] == 255).any()


@pytest.mark.skipif(not SYSTEM_FONT.is_file(), reason="시험 글꼴 없음")
def test_text_rgba_clip_and_line_cap(tmp_path, capsys):
   shutil.copy(SYSTEM_FONT, tmp_path / "f.ttf")
   fonts = {"b": {"file": "f.ttf", "size": 12}}
   text = {"kind": "text", "text": "W", "font": "b", "at": [2, 2], "color": "#0000ff80"}
   scene = _scene(tmp_path, {"version": 1, "canvas": [20, 20], "background": "#ffffff", "fonts": fonts, "nodes": [text]})
   assert _run(scene, tmp_path / "m.png") == 0
   arr = image.load(tmp_path / "m.png")
   colors = {tuple(p) for p in arr.reshape(-1, 4).tolist()}
   assert colors == {(255, 255, 255, 255), (127, 127, 255, 255)}            # 글자 모양은 0/255, 색 알파는 섞임
   capsys.readouterr()
   text.update(at=[15, 2], color="#000000")                                  # 오른쪽 밖으로 나간다
   scene = _scene(tmp_path, {"version": 1, "canvas": [20, 20], "fonts": fonts, "nodes": [text]})
   assert _run(scene, tmp_path / "m.png") == 0
   result = _result(capsys)
   assert result["status"] == "warn" and result["warnings"][0]["rule"] == "ui_mockup.clipped"
   many = [{"kind": "text", "text": "a\n" * 999, "font": "b", "at": [0, 0]} for _ in range(3)]   # 1000 × 3 줄
   scene = _scene(tmp_path, {"version": 1, "canvas": [20, 20], "fonts": fonts, "nodes": many})
   assert _run(scene, tmp_path / "x.png") == 2
   assert not (tmp_path / "x.png").exists()
