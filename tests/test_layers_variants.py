"""4판-나 : files 무늬 + 사전 꼴 items 묶음이 실제 경로(draw · split · fill · check · view · export)에서 깨지지 않는지."""

from __future__ import annotations

import pytest

from arttool import errors, image, layerset
from arttool.draw.canvas import Canvas
from arttool.jsonio import read_json, write_json
from arttool.sprite import split


from test_layers_ops import run_cli, write_set

W, H = 4, 4
RED, BLUE = (200, 30, 30), (30, 30, 200)


def _variant_set(tmp_path):
   """body · face 두 겹, 파일은 parts/<겹>_{v}.png. hop_smile 은 body 만 고르고(face 없음), face_old 는 아무도 안 고른다."""
   folder = tmp_path / "set"
   (folder / "parts").mkdir(parents=True)
   for name, color in [("body_idle", RED), ("body_hop", RED), ("face_idle", BLUE), ("face_old", BLUE)]:
      arr = image.new(W, H)
      arr[0:2, 0:2] = (*color, 255) if name.startswith("body") else (0, 0, 0, 0)
      if name.startswith("face"):
         arr[3, 3] = (*color, 255)
      image.save(folder / "parts" / f"{name}.png", arr)
   write_json(folder / layerset.FILE_NAME, {
      "version": 2, "canvas": [W, H],
      "layers": [{"name": "body", "kind": "body", "files": "parts/body_{v}.png"}, {"name": "face", "kind": "face", "files": "parts/face_{v}.png"}],
      "items": ["idle", {"name": "hop_smile", "pick": {"body": "hop"}}],
   })
   return folder


def _keeps_v2(folder):
   data = read_json(folder / layerset.FILE_NAME)
   assert [l.get("files") for l in data["layers"]] == ["parts/body_{v}.png", "parts/face_{v}.png"]
   assert {"name": "hop_smile", "pick": {"body": "hop"}} in data["items"]


def test_check_reports_variants_and_unused(tmp_path):
   folder = _variant_set(tmp_path)
   rep = tmp_path / "r.json"
   run_cli(["layers", "check", "--in", str(folder)], rep)
   report = read_json(rep)
   assert report["variants"] == {"body": ["hop", "idle"], "face": ["idle", "old"]}
   codes = [w["rule"] for w in report["warnings"]]
   assert codes.count("unused_variant") == 1
   assert not any("hop_smile" in w["detail"] and "face" in w["detail"] for w in report["warnings"])   # pick 밖 겹은 빈 겹이 아니다


def test_check_variant_size_warns(tmp_path):
   folder = _variant_set(tmp_path)
   image.save(folder / "parts" / "face_big.png", image.new(W + 1, H))
   rep = tmp_path / "r.json"
   run_cli(["layers", "check", "--in", str(folder)], rep)
   assert "variant_size" in [w["rule"] for w in read_json(rep)["warnings"]]


def test_plain_set_report_has_no_variants(tmp_path):
   a = image.new(W, H)
   a[0, 0] = (*RED, 255)
   write_set(tmp_path / "plain", {"a": a})
   rep = tmp_path / "r.json"
   run_cli(["layers", "check", "--in", str(tmp_path / "plain")], rep)
   report = read_json(rep)
   assert list(report) == ["version", "status", "in", "canvas", "layers", "items", "failed", "rules", "warnings"]
   assert all(w["rule"] != "unused_variant" for w in report["warnings"])


def test_canvas_open_save_same_folder_keeps_files_and_pick(tmp_path):
   folder = _variant_set(tmp_path)
   before = image.load(folder / "parts" / "body_hop.png")
   Canvas.open(folder, "hop_smile").save(folder, "hop_smile")
   _keeps_v2(folder)
   assert (image.load(folder / "parts" / "body_hop.png") == before).all()
   assert not (folder / "face").exists() and not (folder / "body").exists()


def test_canvas_open_save_new_folder_keeps_pick(tmp_path):
   folder = _variant_set(tmp_path)
   out = tmp_path / "new"
   Canvas.open(folder, "hop_smile").save(out, "hop_smile")
   data = read_json(out / layerset.FILE_NAME)
   assert data["items"] == [{"name": "hop_smile", "pick": {"body": "hop"}}]
   assert (out / "parts" / "body_hop.png").is_file()
   assert sorted(p.name for p in (out / "parts").iterdir()) == ["body_hop.png"]


def test_canvas_save_refuses_drawing_on_unpicked_layer(tmp_path):
   folder = _variant_set(tmp_path)
   canvas = Canvas.open(folder, "hop_smile")
   canvas._layers["face"].arr[0, 0] = (*BLUE, 255)
   with pytest.raises(errors.ArtToolError, match="pick"):
      canvas.save(folder, "hop_smile")


def test_split_refuses_variant_set(tmp_path):
   folder = _variant_set(tmp_path)
   with pytest.raises(errors.UsageError, match="files"):
      split._refuse_small_set(folder)


def test_fill_writes_variant_files(tmp_path):
   folder = _variant_set(tmp_path)
   out = tmp_path / "out"
   run_cli(["layers", "fill", "--in", str(folder), "--mask", _mask(tmp_path / "m.png", 0, 0, 4, 2),
            "--nearest", "body", "--out", str(out)])
   _keeps_v2(out)
   assert (out / "parts" / "body_hop.png").is_file()
   assert not (out / "parts" / "face_hop_smile.png").exists() and not (out / "face").exists()
   assert image.load(out / "parts" / "body_hop.png")[0:2, 0:4, 3].all()


@pytest.mark.parametrize("argv", [
   ["layers", "view", "--each"],
   ["layers", "export", "--each"],
   ["layers", "check", "--cover", "COVER"],
])
def test_other_commands_survive_unpicked_layer(tmp_path, argv):
   folder = _variant_set(tmp_path)
   cover = _mask(tmp_path / "c.png", 0, 0, 2, 2)
   out_flag = ["--out", str(tmp_path / ("v.png" if argv[1] == "view" else "exp"))] if argv[1] != "check" else []
   argv = [a if a != "COVER" else cover for a in argv]
   assert run_cli([*argv[:2], "--in", str(folder), *argv[2:], *out_flag]) in (0, 1)


def _mask(path, x0, y0, x1, y1):
   arr = image.new(W, H)
   arr[y0:y1, x0:x1] = (255, 255, 255, 255)
   image.save(path, arr)
   return str(path)
