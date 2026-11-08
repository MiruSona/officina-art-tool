"""train/polish 의 중복 거르기 · 그룹 · 분할. 합성 작은 그림만 쓴다."""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "train" / "polish"))
import groups as g  # noqa: E402
import split as s  # noqa: E402


def _blob(seed: int, size: int = 16, color=(200, 60, 60), cut: int = 0) -> np.ndarray:
   """투명 바탕에 씨앗마다 다른 무늬 덩어리."""
   rng = np.random.default_rng(seed)
   arr = np.zeros((size, size, 4), np.uint8)
   arr[3:13, 3:13, :3] = color
   arr[3:13, 3:13, 3] = 255
   spots = rng.integers(3, 13, size=(12, 2))
   arr[spots[:, 0], spots[:, 1], :3] = (20, 20, 20)
   arr[3:3 + cut, 3:3 + cut] = 0     # 모서리를 잘라 모양(실루엣)을 다르게
   return arr


def _fake_loader(table: dict):
   return lambda path: (table[Path(path).as_posix()], None, 1)


def test_hash_same_image_is_zero_and_differs_from_other():
   a, b = _blob(1), _blob(2)
   assert g.hamming(g.dhash(a), g.dhash(a.copy())) == 0
   assert g.hamming(g.phash(a), g.phash(a.copy())) == 0
   assert max(g.hamming(g.dhash(a), g.dhash(b)), g.hamming(g.phash(a), g.phash(b))) > g.LINK


def test_transparent_cells_sit_on_grey():
   empty = np.zeros((8, 8, 4), np.uint8)
   grey = np.asarray(g._grey(empty))
   assert (grey == g.GREY).all()


def test_union_find_is_transitive():
   uf = g.UnionFind(5)
   uf.union(0, 1)
   uf.union(1, 2)
   uf.union(3, 4)
   assert uf.find(2) == uf.find(0) == 0
   assert uf.find(4) == 3 and uf.find(3) != uf.find(0)


def test_meta_stem_strips_trailing_number_in_same_folder():
   assert g.meta_stem("x/a/walk_01.png") == g.meta_stem("x/a/walk_2.png") == "x/a/walk"
   assert g.meta_stem("x/a/walk_01.png") != g.meta_stem("x/b/walk_01.png")


def _row(path, kind="icon", origin="pil"):
   return {"path": path, "group": None, "kind": kind, "origin": origin}


def test_build_groups_meta_hash_silhouette_and_pack_overlap():
   red, recolor = _blob(1), _blob(2, color=(60, 160, 60))   # 같은 틀(모양) · 다른 색과 무늬 → 해시로는 안 이어짐
   images = {
      "o/a/frame_1.png": _blob(10, cut=1), "o/a/frame_2.png": _blob(11, cut=2),       # 메타 그룹
      "o/b/red.png": red, "o/b/green.png": recolor,                     # 모양 같음 → 1-b
      "o/c/solo.png": _blob(20, cut=3),
      "p/dup.png": _blob(20, cut=3),                                     # 우리 그림과 같음 → 끌려 옴
      "p/tile_0001.png": _blob(30), "p/tile_0002.png": _blob(31),        # 바깥은 번호 규칙 안 씀
   }
   ours = [_row(p) for p in images if p.startswith("o/")] + [_row("o/skip.png") | {"skip": "손으로 뺌"}]
   packs = [{"pack": "kit", "path": p, "abs": p} for p in images if p.startswith("p/")]
   result = g.build(ours, packs, load=_fake_loader(images))

   group = {it["path"]: it["group"] for it in result["items"]}
   assert group["o/a/frame_1.png"] == group["o/a/frame_2.png"]
   assert group["o/b/red.png"] == group["o/b/green.png"]
   assert group["o/c/solo.png"] == group["p/dup.png"]
   assert group["p/tile_0001.png"] != group["p/tile_0002.png"]
   assert result["skipped"] == [{"path": "o/skip.png", "side": "ours", "reason": "손으로 뺌"}]
   ours_groups = [x for x in result["groups"] if x["side"] == "ours"]
   assert len(ours_groups) == 3
   assert sum(len(x.get("pulled_from_packs", [])) for x in ours_groups) == 1

   plain = g.build(ours, packs, load=_fake_loader(images), silhouette=False)
   group = {it["path"]: it["group"] for it in plain["items"]}
   assert group["o/b/red.png"] != group["o/b/green.png"]


def test_to_cells_shrinks_integer_upscale():
   small = _blob(5)
   big = small.repeat(3, axis=0).repeat(3, axis=1)
   arr, why, scale = g.to_cells(big)
   assert why is None and scale == 3
   assert (arr == small).all()


def test_to_cells_drops_soft_edge_picture():
   arr = _blob(5)
   arr[3:13, 3, 3] = 128     # 가장자리 반투명 → 도트 아님
   arr[3:13, 12, 3] = 128
   arr[3, 3:13, 3] = 128
   arr[12, 3:13, 3] = 128
   out, why, _ = g.to_cells(arr)
   assert out is None and why.startswith("도트 아님")


def _groups(kinds: dict[str, int]) -> list[dict]:
   out = []
   for kind, n in kinds.items():
      out += [{"id": f"{kind}{i:02d}", "side": "ours", "kind": kind, "members": [0]} for i in range(n)]
   return out + [{"id": "p0", "side": "pack", "members": [1], "packs": ["kit"]}]


def test_split_is_stratified_seeded_and_disjoint():
   groups = _groups({"icon": 20, "building": 6, "character": 10, "cc0": 4})
   a, b = s.split_groups(groups), s.split_groups(list(reversed(groups)))
   assert a["train"] == b["train"] and a["test"] == b["test"]          # 씨앗 고정 · 넣는 순서 무관
   total = 40
   assert len(a["test"]) == round(total * 0.15) == len(a["val"])
   assert set(a["train"]).isdisjoint(a["val"]) and set(a["val"]).isdisjoint(a["test"])
   assert len(a["train"]) + len(a["val"]) + len(a["test"]) == total
   assert a["by_kind"]["icon"]["test"] == 3 and a["by_kind"]["icon"]["train"] == 14
   assert a["pretrain_groups"] == ["p0"]
   assert s.split_groups(groups, seed=1)["test"] != a["test"]


def test_quota_gives_small_strata_their_remainder():
   got = s._quota({"a": 7, "b": 2, "c": 2}, 0.15)
   assert sum(got.values()) == round(11 * 0.15) == 2
   assert got["a"] == 1


def test_split_main_refuses_to_refreeze(tmp_path):
   import json
   gp = tmp_path / "groups.json"
   gp.write_text(json.dumps({"groups": _groups({"icon": 10})}), encoding="utf-8")
   args = ["--groups", str(gp), "--out", str(tmp_path / "split.json"), "--frozen", str(tmp_path / "frozen.json")]
   assert s.main(args) == 0
   frozen = json.loads((tmp_path / "frozen.json").read_text(encoding="utf-8"))
   assert set(frozen["files"]) == {"groups.json", "split.json"}
   assert s.main(args) == 2
   assert s.main(args + ["--refreeze"]) == 0
