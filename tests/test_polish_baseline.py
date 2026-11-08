"""P5 바닥 셈 (train/polish/baseline.py) — 합성 자료로 bootstrap 구간 · KID · C2ST 가 제 뜻대로 도는지."""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "train" / "polish"))

import baseline as b  # noqa: E402


def _counts(rng, seeds=5, pairs=20, rate=0.3):
   """(씨앗, 짝, 7) 칸 수 : 바뀐 칸 중 rate 를 맞힌 짝들."""
   cells = rng.integers(200, 400, size=(seeds, pairs))
   changed = cells // 2
   hit = rng.binomial(changed, rate)
   keep = cells - changed
   near = rng.uniform(0.5, 0.7, size=(seeds, pairs))
   return np.stack([cells, changed, hit, cells - changed, keep, hit + keep, near], -1).astype(float)


def test_pooled_matches_hand_count():
   c = np.array([[[10, 4, 2, 6, 6, 8, 0.5], [10, 6, 3, 4, 2, 5, 0.7]]], float)
   got = b.pooled(c)[0]
   assert np.allclose(got, [5 / 10, 8 / 10, 0.6, 13 / 20])


def test_bootstrap_interval_holds_truth_and_shrinks_with_more_groups():
   rng = np.random.default_rng(0)
   few, many = _counts(rng, pairs=8), _counts(rng, pairs=80)
   lo, hi = np.array(b.interval(b.bootstrap(many))).T
   assert lo[0] < 0.3 < hi[0]
   width = lambda c: np.diff(np.array(b.interval(b.bootstrap(c))), axis=1)[0, 0]   # noqa: E731
   assert width(many) < width(few)


def test_bootstrap_of_identical_pairs_is_a_point():
   c = np.repeat(_counts(np.random.default_rng(1), pairs=1), 10, axis=1)
   lo, hi = np.array(b.interval(b.bootstrap(c))).T
   assert np.allclose(lo, hi)


def test_kid_near_zero_for_same_distribution():
   rng = np.random.default_rng(2)
   same = b.kid(rng.normal(size=(300, 6)), rng.normal(size=(300, 6)))
   shifted = b.kid(rng.normal(size=(300, 6)), rng.normal(1.0, 1.0, size=(300, 6)))
   assert abs(same) < 0.05 * shifted
   assert shifted > 1.0


def _grouped(rng, shift):
   groups = np.repeat([f"g{i:02d}" for i in range(20)], 15)
   y = np.isin(groups, [f"g{i:02d}" for i in range(10)]).astype(int)
   x = rng.normal(size=(len(y), 6)) + shift * y[:, None]
   return x, y, groups


def test_c2st_half_for_same_distribution():
   accs = [b.c2st(*_grouped(np.random.default_rng(s), 0.0), seed=s)[0] for s in range(5)]
   assert 0.4 <= np.mean(accs) <= 0.6


def test_c2st_high_for_different_distribution():
   acc, w = b.c2st(*_grouped(np.random.default_rng(3), 1.5))
   assert acc > 0.85
   assert w.shape == (6,)
