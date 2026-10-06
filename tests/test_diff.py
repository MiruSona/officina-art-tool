"""`diff --alpha-only` (2판 설계 C3)."""

import numpy as np
import pytest

from arttool import cli, image


def _png(path, alpha=255, size=(4, 4), color=(10, 20, 30)):
   arr = np.zeros((size[1], size[0], 4), dtype=np.uint8)
   arr[:, :, :3] = color
   arr[:, :, 3] = alpha
   path.parent.mkdir(parents=True, exist_ok=True)
   image.save(path, arr)
   return arr


def test_same_alpha_ok_and_color_only_ok(tmp_path):
   _png(tmp_path / "a.png")
   _png(tmp_path / "b.png", color=(200, 0, 0))
   assert cli.main(["diff", "--a", str(tmp_path / "a.png"), "--b", str(tmp_path / "b.png"), "--alpha-only"]) == 0


def test_one_alpha_cell_fails(tmp_path):
   arr = _png(tmp_path / "a.png")
   arr[1, 2, 3] = 0
   image.save(tmp_path / "b.png", arr)
   assert cli.main(["diff", "--a", str(tmp_path / "a.png"), "--b", str(tmp_path / "b.png"), "--alpha-only"]) == 4


def test_size_mismatch_fails_and_unpaired_warns(tmp_path):
   _png(tmp_path / "A" / "x.png")
   _png(tmp_path / "B" / "x.png", size=(5, 4))
   _png(tmp_path / "A" / "only.png")
   from arttool.sprite import diff
   args = type("A", (), {"a": str(tmp_path / "A"), "b": str(tmp_path / "B"), "alpha_only": True})()
   report = diff.run(args)
   assert report["status"] == "fail"
   assert [w["rule"] for w in report["warnings"]] == ["diff.unpaired"]


def test_needs_alpha_only(tmp_path):
   _png(tmp_path / "a.png")
   assert cli.main(["diff", "--a", str(tmp_path / "a.png"), "--b", str(tmp_path / "a.png")]) == 2


def test_no_pairs_fails(tmp_path):
   _png(tmp_path / "A" / "x.png")
   _png(tmp_path / "B" / "y.png")
   assert cli.main(["diff", "--a", str(tmp_path / "A"), "--b", str(tmp_path / "B"), "--alpha-only"]) == 4
   from arttool.sprite import diff
   args = type("A", (), {"a": str(tmp_path / "A"), "b": str(tmp_path / "B"), "alpha_only": True})()
   report = diff.run(args)
   assert report["status"] == "fail"
   assert [w["rule"] for w in report["warnings"]] == ["diff.unpaired", "diff.no_pairs"]
