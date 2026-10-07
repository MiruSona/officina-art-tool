"""7판-라-1 — `layers check --dents` 아래에서 비는 칸을 위 겹이 덮나 (설계 2026-10-07 10-1 · 10-4 장면 1~4)."""

from __future__ import annotations

from arttool import errors, image
from arttool.sprite import layers as layers_mod

from test_layers_check7 import GRAY, RED, BLUE, W, H, _box, check, write_v2
from test_layers_ops import run_cli


def _body():
   """몸통 네모 (2,2)-(10,10). 위 테두리를 바깥과 이어지게 판 칸 (5,2)·(6,2)·(5,3)·(6,3) — 안쪽 구멍이 아니다."""
   body = _box(2, 2, 10, 10, GRAY)
   body[2:4, 5:7] = 0
   return body


def _lid(short=False):
   lid = _box(5, 2, 7, 4, RED)
   if short:
      lid[3, 6] = 0   # 한 칸 모자란 뚜껑 — (6, 3) 이 빈다
   return lid


def _case(tmp_path, short=False):
   """사례 6 꼴 : 원본 = 몸통 + 다 덮는 뚜껑. short 면 묶음의 뚜껑만 한 칸 줄인다."""
   body = _body()
   rows = [{"name": "body", "kind": "content"}, {"name": "lid", "kind": "deco"}]
   folder = write_v2(tmp_path / "set", rows, {"f0": {"body": body, "lid": _lid(short)}})
   original = tmp_path / "f0.png"
   full = {"body": body, "lid": _lid()}
   image.save(original, layers_mod.compose(list(full), full))
   return folder, original


def _dents(rep):
   return [w for w in rep["warnings"] if w["rule"] == "layer_dent"]


def test_dent_fully_covered_by_lid(tmp_path):
   folder, original = _case(tmp_path)
   code, rep = check(folder, "--original", str(original), "--holes", "--dents")
   assert code == errors.EXIT_OK
   assert rep["holes"] == []                         # 바깥과 이어진 패인 자리는 --holes 가 못 잡는다
   assert rep["dents"] == [{"item": "f0", "layer": "body", "bare": 4, "bare_outside": 0, "covered_by": {"lid": 4}, "open": 0}]
   assert _dents(rep) == []


def test_dent_open_cell_warns_and_original_fails(tmp_path):
   folder, original = _case(tmp_path, short=True)
   code, rep = check(folder, "--original", str(original), "--dents")
   assert code == errors.EXIT_CHECK_FAIL
   assert rep["failed"] == ["original"]
   assert rep["dents"] == [{"item": "f0", "layer": "body", "bare": 4, "bare_outside": 0, "covered_by": {"lid": 3}, "open": 1}]
   line = _dents(rep)
   assert len(line) == 1 and line[0]["items"] == [[6, 3]]
   assert "body" in line[0]["detail"]


def test_dent_two_upper_layers_both_listed(tmp_path):
   body = _body()
   mid = _box(5, 2, 7, 4, RED)
   top = _box(5, 2, 7, 4, BLUE)
   rows = [{"name": "body", "kind": "content"}, {"name": "mid", "kind": "deco"}, {"name": "top", "kind": "deco"}]
   parts = {"body": body, "mid": mid, "top": top}
   folder = write_v2(tmp_path / "set", rows, {"f0": parts})
   original = tmp_path / "f0.png"
   image.save(original, layers_mod.compose(list(parts), parts))
   _, rep = check(folder, "--original", str(original), "--dents")
   rows_out = rep["dents"]
   assert [r["layer"] for r in rows_out] == ["body", "mid"]          # 맨 위 겹은 뺀다
   assert rows_out[0]["covered_by"] == {"mid": 4, "top": 4}
   assert sum(rows_out[0]["covered_by"].values()) > rows_out[0]["bare"]
   assert rows_out[1] == {"item": "f0", "layer": "mid", "bare": 0, "bare_outside": 0, "covered_by": {}, "open": 0}
   assert _dents(rep) == []


def test_dents_needs_original(tmp_path):
   folder, _ = _case(tmp_path)
   assert run_cli(["layers", "check", "--in", str(folder), "--dents"]) == errors.EXIT_USAGE


def test_dents_needs_two_painted_layers(tmp_path):
   rows = [{"name": "body", "kind": "content"}, {"name": "tier1", "kind": "mask"}]
   body = _body()
   folder = write_v2(tmp_path / "set", rows, {"f0": {"body": body, "tier1": _box(2, 2, 10, 10, RED)}})
   original = tmp_path / "f0.png"
   image.save(original, body)
   assert run_cli(["layers", "check", "--in", str(folder), "--original", str(original), "--dents"]) == errors.EXIT_USAGE


def test_dents_skipped_when_original_size_differs(tmp_path):
   folder, _ = _case(tmp_path)
   original = tmp_path / "f0.png"
   image.save(original, image.new(W + 1, H))
   code, rep = check(folder, "--original", str(original), "--dents")
   assert code == errors.EXIT_CHECK_FAIL
   assert "dents" not in rep and _dents(rep) == []


def test_no_dents_flag_no_dents_key(tmp_path):
   folder, original = _case(tmp_path, short=True)
   _, rep = check(folder, "--original", str(original))
   assert "dents" not in rep and _dents(rep) == []


# --- 7판-라 리뷰 : bbox 안으로 좁힘 · open 한 줄만 · 없는 겹 · 마스크 겹 ---


def _three(tmp_path, parts, original_parts=None, kinds=None):
   names = list(parts)
   kinds = kinds or {}
   rows = [{"name": n, "kind": kinds.get(n, "content")} for n in names]
   folder = write_v2(tmp_path / "set", rows, {"f0": parts})
   full = original_parts or parts
   painted = [n for n in full if kinds.get(n) != "mask"]
   original = tmp_path / "f0.png"
   image.save(original, layers_mod.compose(painted, {n: full[n] for n in painted}))
   return folder, original


def test_dent_bare_only_inside_layer_bbox(tmp_path):
   """뚜껑이 몸통 상자 위로 2줄 튀어나와도 그 칸은 패인 자리가 아니다 — bare_outside 로만 센다."""
   body = _body()
   lid = _box(5, 0, 7, 4, RED)   # (5..6, 0..1) 은 몸통 상자 (2,2)-(10,10) 밖
   folder, original = _three(tmp_path, {"body": body, "lid": lid})
   _, rep = check(folder, "--original", str(original), "--dents")
   assert rep["dents"] == [{"item": "f0", "layer": "body", "bare": 4, "bare_outside": 4, "covered_by": {"lid": 4}, "open": 0}]


def test_dent_open_cell_only_on_lowest_layer(tmp_path):
   """(6,3) 은 몸통 줄에서 처음 빈다 — 가운데 겹 줄에는 되풀이하지 않는다."""
   body = _body()
   mid = _box(5, 2, 7, 4, RED)
   mid[3, 6] = 0
   top = _box(5, 2, 6, 3, BLUE)
   full = {"body": body, "mid": _box(5, 2, 7, 4, RED), "top": top}
   folder, original = _three(tmp_path, {"body": body, "mid": mid, "top": top}, original_parts=full)
   _, rep = check(folder, "--original", str(original), "--dents")
   rows = {r["layer"]: r for r in rep["dents"]}
   assert rows["body"]["open"] == 1 and rows["mid"]["bare"] == 1 and rows["mid"]["open"] == 0
   line = _dents(rep)
   assert len(line) == 1 and line[0]["items"] == [[6, 3]] and "body" in line[0]["detail"]


def test_dent_missing_lower_layer_has_no_row(tmp_path):
   mid = _box(5, 2, 7, 4, RED)
   top = _box(5, 2, 7, 4, BLUE)
   rows = [{"name": n, "kind": "content"} for n in ("body", "mid", "top")]
   folder = write_v2(tmp_path / "set", rows, {"f0": {"mid": mid, "top": top}})
   original = tmp_path / "f0.png"
   image.save(original, layers_mod.compose(["mid", "top"], {"mid": mid, "top": top}))
   _, rep = check(folder, "--original", str(original), "--dents")
   assert [r["layer"] for r in rep["dents"]] == ["mid"]


def test_dent_missing_upper_layer_skipped(tmp_path):
   """그 장에 뚜껑 겹이 없으면 덮개가 없다 — covered_by 는 비고 open 이 bare 와 같다."""
   rows = [{"name": "body", "kind": "content"}, {"name": "lid", "kind": "deco"}]
   folder = write_v2(tmp_path / "set", rows, {"f0": {"body": _body()}})
   original = tmp_path / "f0.png"
   full = {"body": _body(), "lid": _lid()}
   image.save(original, layers_mod.compose(list(full), full))
   _, rep = check(folder, "--original", str(original), "--dents")
   assert rep["dents"] == [{"item": "f0", "layer": "body", "bare": 4, "bare_outside": 0, "covered_by": {}, "open": 4}]
   assert len(_dents(rep)) == 1


def test_dent_mask_layer_between_is_ignored(tmp_path):
   """사이에 낀 마스크 겹은 줄도 안 만들고 덮개로도 안 센다."""
   body = _body()
   tier = _box(5, 2, 7, 4, BLUE)   # 패인 칸을 칠했지만 마스크라 덮개가 아니다
   lid = _lid()
   folder, original = _three(tmp_path, {"body": body, "tier1": tier, "lid": lid}, kinds={"tier1": "mask"})
   _, rep = check(folder, "--original", str(original), "--dents")
   assert rep["dents"] == [{"item": "f0", "layer": "body", "bare": 4, "bare_outside": 0, "covered_by": {"lid": 4}, "open": 0}]
