"""train/polish/shortcut.py — 지름길 검사의 특징 · AUC · 그룹 겹 나누기 (합성 자료만)."""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "train" / "polish"))

import shortcut  # noqa: E402


def _blob(size: int = 32, colors: int = 3, seed: int = 0) -> np.ndarray:
   """가운데 원 + 검은 테. 안쪽은 colors 가지 띠."""
   rng = np.random.default_rng(seed)
   arr = np.zeros((size, size, 4), np.uint8)
   ys, xs = np.mgrid[0:size, 0:size]
   d = np.hypot(ys - size / 2, xs - size / 2)
   inside = d < size * 0.4
   ramp = rng.integers(40, 220, (colors, 3))
   band = np.minimum((ys / size * colors).astype(int), colors - 1)
   arr[inside, :3] = ramp[band[inside]]
   arr[inside, 3] = 255
   edge = inside & (d >= size * 0.4 - 1)
   arr[edge, :3] = 0
   return arr


def test_features_ranges():
   f = shortcut.features(_blob())
   assert set(f) == {k for k, _ in shortcut.FEATURES}
   for k in ("opaque", "outline_top_share", "patch_unique", "m_isolated"):
      assert 0.0 <= f[k] <= 1.0, k
   assert f["colors_per_1000"] > 0
   assert f["outline_colors"] >= 1
   assert f["outline_top_share"] == 1.0   # 테는 검정 하나
   assert f["ramp_steps"] >= 1
   assert f["size"] == 32.0


def test_features_full_tile_has_no_outline():
   tile = np.full((16, 16, 4), 255, np.uint8)
   f = shortcut.features(tile)
   assert f["opaque"] == 1.0 and f["outline_colors"] == 0 and f["outline_top_share"] == 0.0


def test_auc_basic():
   y = np.array([0, 0, 1, 1])
   assert shortcut.auc(np.array([0.1, 0.2, 0.3, 0.4]), y) == 1.0
   assert shortcut.auc(np.array([0.4, 0.3, 0.2, 0.1]), y) == 0.0
   assert shortcut.auc(np.array([1.0, 1.0, 1.0, 1.0]), y) == 0.5


def _data(shift: float, seed: int = 0):
   rng = np.random.default_rng(seed)
   n = 400
   x = rng.normal(size=(2 * n, 4))
   x[n:, 0] += shift
   y = np.array([0] * n + [1] * n)
   groups = [f"a{i % 40}" for i in range(n)] + [f"b{i % 40}" for i in range(n)]
   return x, y, groups


def test_cv_auc_same_distribution_is_half():
   x, y, g = _data(0.0)
   r = shortcut.cv_auc(x, y, g)
   assert abs(r["mean"] - 0.5) < 0.1
   assert len(r["folds"]) == shortcut.FOLDS


def test_cv_auc_different_distribution_is_high():
   x, y, g = _data(4.0)
   assert shortcut.cv_auc(x, y, g)["mean"] > 0.9


def test_group_folds_no_overlap_and_both_sides():
   _, y, g = _data(0.0)
   fold = shortcut.group_folds(g, y)
   g = np.array(g)
   for name in np.unique(g):
      assert len(np.unique(fold[g == name])) == 1   # 한 그룹은 한 겹에만
   for f in range(shortcut.FOLDS):
      assert set(y[fold == f]) == {0, 1}


def test_balance_equal_sizes():
   a, ga, b, gb = shortcut.balance(list(range(10)), ["x"] * 10, list(range(4)), ["y"] * 4)
   assert len(a) == len(b) == len(ga) == len(gb) == 4
