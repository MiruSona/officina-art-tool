"""split 의 색조 규칙(hue · min_sat) 과 --gray-levels. 설계 4-6 (4판-나)."""

from __future__ import annotations

import hashlib
import json

import numpy as np
import pytest

from arttool import cli, image
from arttool.errors import ArtToolError, UsageError
from arttool.sprite import split
from test_split import LAYERS, base_spec, doll, owner_of, spec_of, write_case

BLUE = (40, 90, 220)      # 색상 약 224 도
DEEP = (60, 40, 200)      # 약 247 도
RED2 = (230, 20, 60)      # 약 349 도 — 0 도 근처
GRAY = (120, 120, 125)    # 채도 0.04 — 무채색
PALE = (200, 210, 230)    # 채도 0.13 — min_sat 기본값 0.15 아래


def _cells(*colors):
   """한 줄에 색을 하나씩 늘어놓은 그림."""
   arr = image.new(len(colors), 1)
   for x, rgb in enumerate(colors):
      arr[0, x] = (*rgb, 255)
   return arr


def _spec(rules, **extra):
   return base_spec(colors={}, outline=None, rules=rules, **extra)


def _owners(arr, data):
   parts, info = split.split_array(arr, spec_of(data))
   assert info["roundtrip_diff"] == 0
   return [owner_of(parts, x, 0) for x in range(arr.shape[1])]


# --- 색조 규칙 ---


def test_hue_range_takes_blues():
   arr = _cells(BLUE, DEEP, RED2)
   assert _owners(arr, _spec([{"hue": [200, 260], "to": "shirt"}])) == ["shirt", "shirt", "body"]


def test_hue_range_wraps_past_zero():
   arr = _cells(RED2, (240, 60, 20), BLUE)  # 349 도 · 약 13 도 · 224 도
   assert _owners(arr, _spec([{"hue": [340, 20], "to": "hair"}])) == ["hair", "hair", "body"]


def test_low_saturation_cells_skip_hue_rule():
   """회색·옅은 색은 색상이 흔들리니 hue 규칙이 안 잡는다 → 색 표 · default 로 간다."""
   arr = _cells(GRAY, PALE, BLUE)
   assert _owners(arr, _spec([{"hue": [0, 360], "to": "face"}])) == ["body", "body", "face"]
   assert _owners(arr, _spec([{"hue": [0, 360], "to": "face", "min_sat": 0.1}])) == ["body", "face", "face"]
   assert _owners(arr, _spec([{"hue": [0, 360], "to": "face", "min_sat": 0}])) == ["face", "face", "face"]


def test_zero_saturation_never_taken_by_hue():
   """채도가 정확히 0(검정 · 흰색 · 회색)이면 색조가 없다. min_sat 0 이어도 hue 규칙이 안 잡는다."""
   arr = _cells((0, 0, 0), (255, 255, 255), (128, 128, 128), BLUE)
   assert _owners(arr, _spec([{"hue": [0, 360], "to": "face", "min_sat": 0}])) == ["body", "body", "body", "face"]


def test_hue_rule_skips_outline_color():
   """외곽선 색은 hue 범위 안이어도 hue 규칙이 안 잡고 외곽선 투표로 간다. color 규칙은 그대로 잡는다."""
   arr = _cells(RED2, DEEP, RED2)
   outline = "#%02X%02X%02X" % DEEP
   assert _owners(arr, base_spec(colors={}, outline=outline, rules=[{"hue": [200, 260], "to": "shirt"}])) == ["body", "body", "body"]
   assert _owners(arr, base_spec(colors={}, outline=outline, rules=[{"color": outline, "to": "shirt", "box": [0, 0, 3, 1]}]))[1] == "shirt"


def test_first_rule_wins_and_hue_mixes_with_place():
   arr = image.new(2, 2)
   arr[:, :] = (*BLUE, 255)
   rules = [{"hue": [200, 260], "to": "hair", "above_y": 1}, {"hue": [180, 300], "to": "shirt"}]
   parts, _ = split.split_array(arr, spec_of(_spec(rules)))
   assert [owner_of(parts, 0, 0), owner_of(parts, 0, 1)] == ["hair", "shirt"]


def test_color_rule_before_hue_rule_keeps_order():
   arr = _cells(BLUE, DEEP)
   rules = [{"color": "#285ADC", "to": "face", "box": [0, 0, 1, 1]}, {"hue": [200, 260], "to": "shirt"}]
   assert _owners(arr, _spec(rules)) == ["face", "shirt"]


def test_unmatched_opaque_cell_keeps_default_warning(tmp_path):
   src, spec_file = write_case(tmp_path, _cells(BLUE, RED2), _spec([{"hue": [200, 260], "to": "shirt"}]))
   report = split.run(src, spec_file, tmp_path / "out")
   assert report["unmapped_colors"] == ["#E6143C"]
   assert any("default(body)" in w for w in report["warnings"])


@pytest.mark.parametrize("row", [
   {"hue": [10], "to": "hair"},
   {"hue": "10-20", "to": "hair"},
   {"hue": [-1, 20], "to": "hair"},
   {"hue": [10, 361], "to": "hair"},
   {"hue": [30, 30], "to": "hair"},
   {"hue": [True, 30], "to": "hair"},
   {"hue": [10, 30], "to": "hair", "min_sat": 1.5},
   {"hue": [10, 30], "to": "hair", "min_sat": "0.2"},
   {"color": "#283CDC", "to": "hair", "min_sat": 0.2, "box": [0, 0, 1, 1]},
])
def test_bad_hue_rule_is_usage_error(row):
   with pytest.raises(UsageError):
      spec_of(_spec([row]))


def test_color_and_hue_together_refused():
   with pytest.raises(ArtToolError):
      spec_of(_spec([{"color": "#283CDC", "hue": [200, 260], "to": "hair"}]))


def test_bad_hue_exits_2(tmp_path):
   src, spec_file = write_case(tmp_path, _cells(BLUE), _spec([{"hue": [400, 20], "to": "hair"}]))
   assert cli.main(["split", "--in", str(src), "--spec", str(spec_file), "--out", str(tmp_path / "o")]) == 2


# --- 새 칸을 안 쓰면 예전과 바이트까지 같다 ---

# 이 판 앞(HEAD bb4bbf3) 의 split.py 로 같은 입력을 돌려 얻은 값. 바뀌면 옛 출력이 달라졌다는 뜻이다.
OLD_DIGEST = "eef0ad40d623c78892303edfb445ca9782e8c31ea51819af1138fe44250226a2"


def _digest(root):
   """겹 PNG · layers.json · 보고(경로 칸 out · layers_json 을 뺀 것) 의 바이트를 하나로 묶은 sha256."""
   h = hashlib.sha256()
   for name in LAYERS:
      h.update((root / name / "doll.png").read_bytes())
   h.update((root / "layers.json").read_bytes())
   h.update((root / "anchors.json").read_bytes())
   report = json.loads((root / split.REPORT_NAME).read_text(encoding="utf-8"))
   report.pop("out")
   report.pop("layers_json")
   h.update(json.dumps(report, sort_keys=True, ensure_ascii=False).encode("utf-8"))
   return h.hexdigest()


def test_without_new_keys_output_is_unchanged(tmp_path):
   rules = [{"color": "#FEEACD", "to": "face", "below_y": 12}]
   src, spec_file = write_case(tmp_path, doll(), base_spec(rules=rules))
   split.run(src, spec_file, tmp_path / "out")
   assert _digest(tmp_path / "out") == OLD_DIGEST


# --- --gray-levels ---


def test_gray_levels_after_split(tmp_path):
   src, spec_file = write_case(tmp_path, doll(), base_spec())
   report = split.run(src, spec_file, tmp_path / "out", gray_levels=[255, 180, 60])
   assert report["status"] != "fail" and report["roundtrip_diff"] == 0
   assert report["gray_levels"] == [255, 180, 60]
   shirt = image.load(tmp_path / "out" / "shirt" / "doll.png")
   hair = image.load(tmp_path / "out" / "hair" / "doll.png")
   # 나누기는 원래 색으로 했다 : 윗옷 자리는 그대로 shirt 겹, 값만 회색 단계로.
   assert tuple(shirt[8, 5]) == (60, 60, 60, 255)    # 빨강 밝기 약 102 → 60 (180 보다 가깝다)
   assert tuple(hair[2, 5]) == (60, 60, 60, 255)
   assert hair[10, 5, 3] == 0                         # 빈 칸은 그대로 투명


def test_gray_levels_tie_takes_darker():
   arr = _cells((100, 100, 100))
   assert tuple(split.to_gray_levels(arr, [90, 110])[0, 0]) == (90, 90, 90, 255)


@pytest.mark.parametrize("text", ["255", "255,255", "255,abc", "256,0", "-1,10", "1.5,10", "", "²,10", "１,10", "10,٣"])
def test_bad_gray_levels(text):
   with pytest.raises(UsageError):
      split.parse_gray_levels(text)


def test_cli_gray_levels(tmp_path, capsys):
   src, spec_file = write_case(tmp_path, doll(), base_spec())
   out = tmp_path / "out"
   code = cli.main(["split", "--in", str(src), "--spec", str(spec_file), "--out", str(out), "--gray-levels", "255,180,60", "--json"])
   assert code in (0, 1)
   assert json.loads(capsys.readouterr().out)["gray_levels"] == [255, 180, 60]
   assert cli.main(["split", "--in", str(src), "--spec", str(spec_file), "--out", str(out), "--gray-levels", "9"]) == 2
   assert cli.main(["split", "--in", str(src), "--list-colors", "--gray-levels", "1,2", "--out", str(tmp_path / "c.json")]) == 2
