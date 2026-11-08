"""P6 고리 3 — 골드 짝 LOO (`train/polish/loo.py`) : 자기 그룹이 학습에서 빠지는지 · 지표 모음 꼴."""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "train" / "polish"))

import loo  # noqa: E402
import table  # noqa: E402
from arttool.shape.polish import keys  # noqa: E402

PAL = np.array([[0, 0, 0], [200, 120, 40], [250, 240, 220]], dtype=np.int64)


def _pair(g: str, shade: int) -> tuple:
   """8×8 불투명 덩이 하나 — 목표는 안쪽만 밝은 색으로 바꾼다."""
   a = np.zeros((8, 8, 4), np.uint8)
   a[1:7, 1:7] = (200, 120, 40, 255)
   a[3:5, 3:5, :3] = shade
   t = np.full((8, 8), table.EMPTY, np.uint8)
   t[1:7, 1:7] = 1
   t[3:5, 3:5] = 2
   return (g, a, t, keys(a, PAL))


def test_loo_leaves_own_group_out(monkeypatch):
   data = [_pair(f"g{i}", 180 + i * 10) for i in range(4)]
   seen = []
   real = table.count

   def spy(key_list, targets, hw, k):
      seen.append({id(t) for t in targets})
      return real(key_list, targets, hw, k)

   monkeypatch.setattr(table, "count", spy)
   out = loo.loo(data, PAL)
   assert len(out) == len(data)
   for i, ids in enumerate(seen):
      assert id(data[i][2]) not in ids and len(ids) == len(data) - 1

   seen.clear()
   loo.loo(data, PAL, size=2, seed=1)
   assert all(len(ids) == 2 for ids in seen)


def test_metric_bundle_shape():
   data = [_pair(f"g{i}", 180 + i * 10) for i in range(3)]
   per = loo.loo(data, PAL)
   base = [loo.metrics(c, "untouched") for c in per]
   got = [loo.metrics(c, "table") for c in per]
   assert all(set(m) == set(loo.METRICS) for m in got)
   s = loo.summarize(got, base)
   assert set(s) == set(loo.METRICS)
   for v in s.values():
      assert set(v) == {"mean", "sd", "delta", "delta_sd", "delta_gt_2sd"}
   # 손 안 댐은 바뀐 칸을 하나도 못 맞히고 다 지킨다
   assert all(b["changed_hit"] == 0 and b["unchanged_keep"] == 1 for b in base)


def test_table_empty_counts_give_empty_tables():
   """짝이 없거나 칸이 다 비어도 count · resolve 가 죽지 않고 빈 표를 낸다."""
   assert all(len(c[0]) == 0 for c in table.count([], [], [], len(PAL)).values())
   tables = table.resolve(table.count([], [], [], len(PAL)), len(PAL))
   assert sorted(tables) == list(range(table.LEVELS - 1))
   assert all(len(t[0]) == 0 and t[1].dtype == np.uint8 for t in tables.values())
