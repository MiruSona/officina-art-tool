"""P1 ① 중복 거르기 · 그룹 만들기 → `train.local/groups.json`.

입력 둘 :
- 우리 그림 목록 `ours.json` — [{path, group, kind, origin, skip?}]. 경로는 그 파일에만 있다.
- 바깥 묶음 목록 `sources.json` — [{name, license, file, sha256, extract}]. `license == "CC0-1.0"` 이고
  zip sha256 이 맞는 묶음만 읽는다.

묶는 규칙 (설계 1-2) :
1. 우리 그림만 : 같은 폴더 + 이름 끝 숫자만 다름 → 한 그룹. 바깥 묶음은 `tile_0001` 처럼
   번호가 「다른 그림」이라 이 규칙을 안 쓴다.
1-b. 우리 그림만 : 크기와 불투명 칸 모양이 똑같으면 한 그룹 (같은 틀 색바꿈. `--no-silhouette` 로 끈다).
2. dHash · pHash 64비트 둘 다 해밍 ≤ LINK 면 잇는다. 투명 칸은 중간 회색 바탕에 얹어 잰다.
3. union-find 로 추이 묶기.
4. 우리 그림이 하나라도 든 그룹은 「우리 쪽」. 거기 끌려 온 바깥 그림은 사전학습에서 뺀다.

1칸 = 1화소 맞춤 : `style.extract.not_pixel_reasons()` 가 까닭을 내면 빼고, `checks.scale.measure_scale()`
배율이 2 이상이면 `draw.grid.shrink_cells()` 로 줄인 뒤 해시를 잰다.

사용 (ArtTool 폴더에서) : python -I train/polish/groups.py [--ours …] [--sources …] [--out …]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from PIL import Image

from arttool import image
from arttool.checks.scale import measure_scale
from arttool.draw.grid import shrink_cells
from arttool.errors import ArtToolError
from arttool.style.extract import not_pixel_reasons

LINK = 5             # 이 해밍 이하면 같은 그림으로 본다 (dHash · pHash 둘 다)
NEAR = 8             # 검수용 경계 쌍 위끝
NEAR_KEEP = 400      # groups.json 에 남길 경계 쌍 수 상한 (우리 그림이 낀 쌍 먼저)
GREY = 128
CC0 = "CC0-1.0"
FRAME_TAIL = re.compile(r"[_\-\s]*(f|frame|fr)?\d+$", re.I)


# ── 해시 ─────────────────────────────────────────────

def _grey(arr: np.ndarray) -> Image.Image:
   """투명 칸을 중간 회색 바탕에 얹은 흑백 그림. 투명이 많은 작은 그림이 서로 닮아 보이지 않게."""
   rgb = arr[:, :, :3].astype(np.float64)
   a = arr[:, :, 3:4].astype(np.float64) / 255.0
   mixed = rgb * a + GREY * (1.0 - a)
   lum = mixed @ np.array([0.299, 0.587, 0.114])
   return Image.fromarray(np.clip(lum + 0.5, 0, 255).astype(np.uint8), mode="L")


def _bits(flags: np.ndarray) -> int:
   out = 0
   for bit in flags.ravel():
      out = (out << 1) | int(bit)
   return out


def dhash(arr: np.ndarray) -> int:
   """옆 칸보다 밝은가 64비트 (9×8 로 줄여 가로 이웃 비교)."""
   small = np.asarray(_grey(arr).resize((9, 8), Image.Resampling.BOX), dtype=np.int16)
   return _bits(small[:, 1:] > small[:, :-1])


def _dct_matrix(n: int) -> np.ndarray:
   k = np.arange(n)[:, None]
   x = np.arange(n)[None, :]
   m = np.cos(np.pi * (2 * x + 1) * k / (2 * n)) * np.sqrt(2.0 / n)
   m[0] /= np.sqrt(2.0)
   return m


DCT32 = _dct_matrix(32)


def phash(arr: np.ndarray) -> int:
   """32×32 DCT 의 낮은 주파수 8×8 이 중앙값보다 큰가 64비트. 중앙값은 DC 를 빼고 잡는다."""
   small = np.asarray(_grey(arr).resize((32, 32), Image.Resampling.BOX), dtype=np.float64)
   low = (DCT32 @ small @ DCT32.T)[:8, :8].ravel()
   return _bits(low > np.median(low[1:]))


def hamming(a: int, b: int) -> int:
   return (a ^ b).bit_count()


def _popcount(values: np.ndarray) -> np.ndarray:
   return np.unpackbits(values.view(np.uint8).reshape(-1, 8), axis=1).sum(axis=1)


# ── union-find ───────────────────────────────────────

class UnionFind:
   def __init__(self, n: int):
      self.parent = list(range(n))

   def find(self, x: int) -> int:
      while self.parent[x] != x:
         self.parent[x] = self.parent[self.parent[x]]
         x = self.parent[x]
      return x

   def union(self, a: int, b: int) -> None:
      a, b = self.find(a), self.find(b)
      if a != b:
         self.parent[max(a, b)] = min(a, b)   # 작은 번호를 뿌리로 — 결과가 넣은 순서에만 달린다


def silhouette_key(arr: np.ndarray) -> str:
   """크기 + 불투명 칸 모양이 똑같으면 같은 열쇠. 같은 틀을 색만 바꿔 구운 우리 아이콘을 한 그룹으로 —
   흑백 해시는 색 바꿈을 반쯤만 이어(이어진 쌍 · 안 이어진 쌍이 섞임) 시험 그룹에 같은 틀이 샌다."""
   mask = np.packbits(arr[:, :, 3] > 0)
   return f"mask:{arr.shape[1]}x{arr.shape[0]}:{hashlib.sha1(mask.tobytes()).hexdigest()}"


def meta_stem(path: str) -> str:
   """같은 폴더 + 이름 끝 숫자(프레임 · 변형 번호)를 뗀 이름."""
   p = Path(path)
   return f"{p.parent.as_posix()}/{FRAME_TAIL.sub('', p.stem)}"


# ── 1칸 = 1화소 ─────────────────────────────────────

def to_cells(arr: np.ndarray) -> tuple[np.ndarray | None, str | None, int]:
   """(1칸=1화소 그림, 뺀 까닭, 배율). 빼면 그림은 None."""
   if not (arr[:, :, 3] > 0).any():
      return None, "빈 그림", 1
   why, _ = not_pixel_reasons(arr)
   if why:
      return None, "도트 아님 : " + "; ".join(why), 1
   background = bool((arr[:, :, 3] == 255).all())
   found = measure_scale(arr, background)
   if found["mixed"]:
      # 글자(1배)와 그림(N배)이 한 장에 붙은 비교판 · 미리보기. 한 배율로 줄이면 어느 한쪽이 깨진다
      return None, f"배율 섞임 {found['scales']} (비교판 · 미리보기)", 1
   if not found["scales"] and max(arr.shape[:2]) > 256:
      return None, "배율을 못 잼 (큰 그림인데 판정할 덩어리 없음)", 1
   scale = found["scale"] or 1
   if scale > 1:
      arr = shrink_cells(arr, int(scale))
   return arr, None, int(scale)


def _load_cells(path: Path) -> tuple[np.ndarray | None, str | None, int]:
   try:
      arr = image.load(path)
   except ArtToolError as exc:
      return None, f"못 읽음 : {exc}", 1
   return to_cells(arr)


# ── 재료 모으기 ─────────────────────────────────────

def _sha256(path: Path) -> str:
   h = hashlib.sha256()
   with open(path, "rb") as fh:
      for chunk in iter(lambda: fh.read(1 << 20), b""):
         h.update(chunk)
   return h.hexdigest()


def pack_files(sources_path: Path) -> tuple[list[dict], list[dict]]:
   """CC0 를 확인한 묶음의 PNG 목록과 묶음별 요약. CC0 아님 · zip 해시 다름 · 풀린 폴더 없음은 안 읽는다."""
   base = sources_path.parent
   files, report = [], []
   for src in json.loads(sources_path.read_text(encoding="utf-8")):
      row = {"name": src["name"], "license": src.get("license"), "used": False}
      report.append(row)
      if src.get("license") != CC0:
         row["why"] = "CC0 아님"
         continue
      if _sha256(base / src["file"]) != src.get("sha256"):
         row["why"] = "zip sha256 다름"
         continue
      folder = base / src.get("extract", "")
      if not src.get("extract") or not folder.is_dir():
         row["why"] = "풀린 폴더 없음"
         continue
      pngs = sorted(p for p in folder.rglob("*") if p.suffix.lower() == ".png")
      row.update(used=True, files=len(pngs))
      files += [{"pack": src["name"], "path": p.relative_to(base).as_posix(), "abs": p} for p in pngs]
   return files, report


# ── 묶기 ─────────────────────────────────────────────

def link_by_hash(hashes: np.ndarray, uf: UnionFind, owners: list[str]) -> list[dict]:
   """dHash · pHash 둘 다 ≤ LINK 인 쌍을 잇고, 경계 쌍(큰 쪽 거리 LINK~NEAR)을 돌려준다.

   hashes : (n, 2) uint64 [dhash, phash]. owners : 칸마다 "ours" / "pack" (경계 쌍 고르기에만 쓴다)."""
   near = []
   for i in range(len(hashes) - 1):
      rest = hashes[i + 1:]
      dist_d = _popcount(rest[:, 0] ^ hashes[i, 0])
      dist_p = _popcount(rest[:, 1] ^ hashes[i, 1])
      worst = np.maximum(dist_d, dist_p)
      for j in np.nonzero(worst <= LINK)[0]:
         uf.union(i, i + 1 + int(j))
      for j in np.nonzero((worst >= LINK) & (worst <= NEAR))[0]:
         k = i + 1 + int(j)
         near.append({"a": i, "b": k, "d": int(dist_d[j]), "p": int(dist_p[j]),
                      "ours": owners[i] == "ours" or owners[k] == "ours"})
   near.sort(key=lambda n: (not n["ours"], max(n["d"], n["p"]), n["a"], n["b"]))
   return near


def _majority_kind(kinds: list[str]) -> str:
   """그룹 종류 = 가장 많은 종류. 동점이면 외부 CC0 가 아닌 쪽, 그다음 이름순."""
   count = Counter(kinds)
   return sorted(count, key=lambda k: (-count[k], k == "cc0", k))[0]


def build(ours: list[dict], packs: list[dict], load=_load_cells, silhouette: bool = True) -> dict:
   """groups.json 내용. `load(path) -> (그림|None, 까닭|None, 배율)` 은 시험에서 바꿔 낀다."""
   items, skipped, hashes, masks = [], [], [], []
   for row in ours:
      if row.get("skip"):
         skipped.append({"path": row["path"], "side": "ours", "reason": row["skip"]})
         continue
      arr, why, scale = load(Path(row["path"]))
      if arr is None:
         skipped.append({"path": row["path"], "side": "ours", "reason": why})
         continue
      items.append({"side": "ours", "path": row["path"], "kind": row["kind"], "origin": row["origin"],
                    "size": [arr.shape[1], arr.shape[0]], "scale": scale})
      hashes.append((dhash(arr), phash(arr)))
      if silhouette:
         masks.append(silhouette_key(arr) if (arr[:, :, 3] == 0).any() else f"solid:{len(items)}")  # 꽉 찬 그림은 모양이 없다
   for f in packs:
      arr, why, scale = load(f["abs"])
      if arr is None:
         skipped.append({"path": f["path"], "side": "pack", "pack": f["pack"], "reason": why})
         continue
      items.append({"side": "pack", "path": f["path"], "pack": f["pack"], "kind": "pretrain",
                    "size": [arr.shape[1], arr.shape[0]], "scale": scale})
      hashes.append((dhash(arr), phash(arr)))

   uf = UnionFind(len(items))
   by_stem = defaultdict(list)
   for i, it in enumerate(items):
      if it["side"] == "ours":
         by_stem[meta_stem(it["path"])].append(i)
   for i, key in enumerate(masks):         # 우리 그림이 items 앞쪽에 있어 번호가 같다
      by_stem[key].append(i)
   for members in by_stem.values():
      for m in members[1:]:
         uf.union(members[0], m)
   table = np.array(hashes, dtype=np.uint64).reshape(-1, 2)
   near = link_by_hash(table, uf, [it["side"] for it in items])

   for i, it in enumerate(items):
      it["dhash"], it["phash"] = f"{hashes[i][0]:016x}", f"{hashes[i][1]:016x}"
   return {"version": 1, "link": LINK, "silhouette": silhouette, "items": items, "skipped": skipped,
           "groups": _groups(items, uf), "near_pairs": near[:NEAR_KEEP], "near_total": len(near)}


def _groups(items: list[dict], uf: UnionFind) -> list[dict]:
   members = defaultdict(list)
   for i in range(len(items)):
      members[uf.find(i)].append(i)
   out = []
   for idx in sorted(members.values(), key=lambda m: m[0]):
      ours = [i for i in idx if items[i]["side"] == "ours"]
      side = "ours" if ours else "pack"
      gid = f"{side[0]}{len(out):05d}"
      group = {"id": gid, "side": side, "members": idx}
      if ours:
         group["kind"] = _majority_kind([items[i]["kind"] for i in ours])
         pulled = [i for i in idx if items[i]["side"] == "pack"]
         if pulled:
            group["pulled_from_packs"] = pulled   # 우리 그림과 겹쳐 사전학습에서 뺀 바깥 그림 (설계 9절 결정 7)
      else:
         group["packs"] = sorted({items[i]["pack"] for i in idx})
      for i in idx:
         items[i]["group"] = gid
      out.append(group)
   return out


def summary(result: dict) -> dict:
   ours = [g for g in result["groups"] if g["side"] == "ours"]
   return {
      "items": len(result["items"]),
      "skipped": len(result["skipped"]),
      "ours_groups": len(ours),
      "ours_by_kind": dict(Counter(g["kind"] for g in ours)),
      "pack_groups": sum(g["side"] == "pack" for g in result["groups"]),
      "pulled_from_packs": sum(len(g.get("pulled_from_packs", [])) for g in ours),
      "near_total": result["near_total"],
   }


def main(argv: list[str] | None = None) -> int:
   ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
   ap.add_argument("--ours", default="train.local/ours.json")
   ap.add_argument("--sources", default="external.local/sources.json")
   ap.add_argument("--out", default="train.local/groups.json")
   ap.add_argument("--no-silhouette", action="store_true", help="같은 틀 색바꿈 묶기(규칙 1-b)를 끈다 — 설계 그대로의 수")
   args = ap.parse_args(argv)

   ours_path = Path(args.ours)
   ours = json.loads(ours_path.read_text(encoding="utf-8"))
   packs, pack_report = pack_files(Path(args.sources))
   result = build(ours, packs, silhouette=not args.no_silhouette)
   result["sources"] = pack_report

   group_of = {it["path"]: it["group"] for it in result["items"] if it["side"] == "ours"}
   for row in ours:
      row["group"] = group_of.get(row["path"])   # 뺀 그림은 None
   ours_path.write_text(json.dumps(ours, ensure_ascii=False, indent=1), encoding="utf-8")
   Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
   print(json.dumps({"summary": summary(result), "sources": pack_report}, ensure_ascii=False, indent=1))
   return 0


if __name__ == "__main__":
   sys.exit(main())
