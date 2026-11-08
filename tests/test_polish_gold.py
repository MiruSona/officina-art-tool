"""train/polish/gold.py — 골드 홀 생성 · 짝 목록 검증 · 얼림. 합성 명세 · 합성 그림만 쓴다."""

import json
import sys
from pathlib import Path

import numpy as np
import pytest

from arttool import image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "train" / "polish"))
import gold  # noqa: E402

SPEC = {
   "version": 1,
   "canvas": {"size": [24, 20], "origin": [12, 18]},
   "outline": {"mode": "solid", "color": "#202020"},
   "materials": {"m": {"color": "#C08040", "steps": 3, "ambient": 0.3}},
   "shapes": [{"type": "ellipsoid", "material": "m", "radii": [8, 7, 6], "pos": [-1, 8, 0]},
              {"type": "box", "material": "m", "size": [4, 6, 4], "pos": [6, 4, 0]}],
}


def _sources(tmp_path: Path, n: int = 1, views=("front", "back")) -> list[dict]:
   (tmp_path / "blob.shape.json").write_text(json.dumps(SPEC), encoding="utf-8")
   return [{"spec": "blob.shape.json", "name": f"blob{i}", "views": list(views)} for i in range(n)]


def test_holes_count_size_and_files(tmp_path):
   rows, dup = gold.make_holes(_sources(tmp_path), tmp_path, tmp_path / "holes", seeds=3)
   assert dup == 0
   assert len(rows) == 2 * 3                    # 보는 방향 둘 × seed 셋
   for row in rows:
      assert row["size"] == [24, 20]
      arr = image.load(tmp_path / "holes" / row["png"])
      assert arr.shape == (20, 24, 4) and (arr[:, :, 3] > 0).any()


def test_holes_are_deterministic(tmp_path):
   a, _ = gold.make_holes(_sources(tmp_path), tmp_path, tmp_path / "a", seeds=2)
   b, _ = gold.make_holes(_sources(tmp_path), tmp_path, tmp_path / "b", seeds=2)
   assert [r["sha256"] for r in a] == [r["sha256"] for r in b]
   for r in a:
      assert (tmp_path / "a" / r["png"]).read_bytes() == (tmp_path / "b" / r["png"]).read_bytes()


def test_seed_changes_picture_and_duplicates_are_dropped(tmp_path):
   rows, dup = gold.make_holes(_sources(tmp_path, n=2, views=("front",)), tmp_path, tmp_path / "h", seeds=2)
   # 같은 명세 둘 → 둘째는 모두 겹쳐서 버린다. seed 0 과 1 은 그림이 다르다
   assert len(rows) == 2 and dup == 2
   assert rows[0]["sha256"] != rows[1]["sha256"]


def test_empty_picture_is_dropped(tmp_path):
   far = dict(SPEC, shapes=[dict(SPEC["shapes"][0], pos=[100, 8, 0])])   # 캔버스 밖 → 빈 그림
   (tmp_path / "far.shape.json").write_text(json.dumps(far), encoding="utf-8")
   rows, dropped = gold.make_holes([{"spec": "far.shape.json", "views": ["front"]}], tmp_path, tmp_path / "h", seeds=1)
   assert rows == [] and dropped == 1


def test_reseed_keeps_original_and_shifts_texture_seed():
   data = dict(SPEC, texture=[{"kind": "mottle", "on": "*", "seed": 4}])
   assert gold.reseed(data, 0) == data
   moved = gold.reseed(data, 2)
   assert moved["texture"][0]["seed"] == 4 + 2 * gold.SEED_STEP
   assert data["texture"][0]["seed"] == 4      # 원본은 그대로
   assert gold.reseed(SPEC, 1)["texture"][0]["kind"] == "mottle"


def _pair(tmp_path: Path, cut: int = 0) -> dict:
   ref = np.zeros((10, 10, 4), np.uint8)
   ref[2:8, 2:8] = (200, 100, 50, 255)
   img = ref.copy()
   img[2:2 + cut, 2:8] = 0                      # 위 줄을 잘라 iou 를 낮춘다
   image.save(tmp_path / "src.png", ref)
   image.save(tmp_path / "render.png", img)
   (tmp_path / "spec.json").write_text("{}", encoding="utf-8")
   iou = round(float((img[:, :, 3] > 0).sum()) / 36.0, 4)
   return {"group": "g1", "kind": "icon", "src": str(tmp_path / "src.png"), "spec": str(tmp_path / "spec.json"),
           "render": str(tmp_path / "render.png"), "silhouette_iou": iou, "ok": iou >= 0.85}


def test_verify_pairs_passes_and_catches_problems(tmp_path):
   good = _pair(tmp_path)
   assert gold.verify_pairs({"iou_min": 0.85, "pairs": [good]}) == []

   wrong_iou = dict(good, silhouette_iou=0.5)
   assert any("다시 셈" in p for p in gold.verify_pairs({"pairs": [wrong_iou]}))

   wrong_ok = dict(good, ok=False)
   assert any("ok=" in p for p in gold.verify_pairs({"pairs": [wrong_ok]}))

   missing = dict(good, render=str(tmp_path / "nope.png"))
   assert any("render 파일이 없다" in p for p in gold.verify_pairs({"pairs": [missing]}))

   no_pair = dict(good, spec=None, render=None, silhouette_iou=None, ok=False)
   assert gold.verify_pairs({"pairs": [no_pair]}) == []


def test_verify_low_iou_pair_must_be_not_ok(tmp_path):
   low = _pair(tmp_path, cut=2)                 # 24 / 36 = .667
   assert low["ok"] is False
   assert gold.verify_pairs({"pairs": [low]}) == []


def test_freeze_writes_hashes_and_refuses_overwrite(tmp_path):
   (tmp_path / "pairs.json").write_text("{}", encoding="utf-8")
   (tmp_path / "holes.json").write_text("[]", encoding="utf-8")
   out = gold.freeze(tmp_path, refreeze=False)
   assert set(out["files"]) == {"pairs.json", "holes.json"}
   with pytest.raises(SystemExit):
      gold.freeze(tmp_path, refreeze=False)
   assert gold.freeze(tmp_path, refreeze=True) == out
