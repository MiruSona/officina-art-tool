"""P4 지름길 검사 — 납작화 입력과 렌더러 출력을 손 특징만으로 가를 수 있나 (설계 3절 끝 · 8절 P4).

두 쪽 :
- 납작화 = CC0 사전학습 검증 그룹(`pretrain_split.json` 씨앗 0 의 val) + 우리 그림(외부 CC0 아닌 것).
  학습 짝과 같은 길로 만든다 : `pairs.blocks` → `pairs.trim` → `pairs.target_of`(팔레트 P 에 붙임) → `flatten(seed)` × 4.
- 렌더러 = 골드 홀 `gold/holes/*.png`. 그룹 = 원천 명세(`holes.json` 의 spec).
둘 다 `pairs.crops` 로 32~48px 조각을 자르고(작은 그림은 통째로), 불투명 몫 ≥ .3 만 둔다. 많은 쪽을 씨앗 고정으로 줄여 수를 맞춘다.

특징(설계 표) + `style.extract.measure_one` 의 숫자 몇 개 → 표준화 → L2 로지스틱 회귀(numpy 뉴턴법), 그룹 단위 5겹 AUC.
통과 AUC ≤ .65. 넘으면 무게 큰 특징을 보고 `flatten.KNOBS`(섞기 범위)만 고쳐 `--attempt N` 으로 다시 잰다.

출력 `train.local/shortcut/report.json`(시도마다 한 칸, 같은 번호는 덮음) · `report.md` · `--sheet` 면 `sheet.html`(두 쪽 조각 12장씩).
사용 (ArtTool 폴더에서) : .venv/Scripts/python -I train/polish/shortcut.py --attempt 1 --sheet
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "train" / "polish"))

from arttool import image  # noqa: E402
from arttool.profile import load_profile  # noqa: E402
from arttool.shape import lock as lock_mod  # noqa: E402
from arttool.shape.flatten import KNOBS, flatten, regions  # noqa: E402
from arttool.style.extract import measure_one  # noqa: E402

import palette as palette_mod  # noqa: E402
import pairs  # noqa: E402

SEEDS_PER_IMAGE = 4
MIN_OPAQUE = 0.3
FOLDS = 5
PASS_AUC = 0.65
L2 = 1.0           # 로지스틱 회귀 벌점 (표준화한 특징 기준) — 특징 수가 적어 작게만 둔다
SHEET_N = 12

FEATURES = (
   ("colors_per_1000", "1000칸당 색 수"),
   ("ramp_steps", "덩어리별 램프 단 수 (평균)"),
   ("outline_colors", "외곽선 색 수"),
   ("outline_top_share", "맨 많은 선 색 몫"),
   ("patch_unique", "3×3 조각 고유 몫"),
   ("opaque", "불투명 몫"),
   ("size", "크기 (√칸 수)"),
   ("m_isolated", "measure_one 외톨이 몫"),
   ("m_outline_share", "measure_one 외곽선 몫"),
   ("m_black_ratio", "measure_one 검은 선 몫"),
)

_DIRS = ((-1, 0), (0, -1), (1, 0), (0, 1))


# --- 특징 ---


def _rim(solid: np.ndarray) -> np.ndarray:
   """투명 칸과 4방향으로 맞닿은 불투명 칸. 조각 끝(캔버스 밖)은 안 센다 — 잘린 자리는 외곽선이 아니다."""
   pad = np.pad(solid, 1, constant_values=True)
   out = np.zeros_like(solid)
   h, w = solid.shape
   for dx, dy in _DIRS:
      out |= ~pad[1 + dy:1 + dy + h, 1 + dx:1 + dx + w]
   return solid & out


def features(arr: np.ndarray, prof=None) -> dict:
   """조각 (H, W, 4) → 손 특징. 불투명 칸이 하나는 있어야 한다."""
   solid = arr[:, :, 3] > 0
   n = int(solid.sum())
   rgb = arr[:, :, :3][solid]
   colors = len(np.unique(rgb, axis=0))
   _, ramp = regions(arr)
   rim = _rim(solid)
   rim_rgb = arr[:, :, :3][rim]
   if len(rim_rgb):
      _, counts = np.unique(rim_rgb, axis=0, return_counts=True)
      out_colors, top = len(counts), counts.max() / counts.sum()
   else:
      out_colors, top = 0, 0.0
   # 3×3 조각 : 가운데가 불투명한 창의 RGBA 바이트 묶음이 몇 가지인가 (몫)
   win = np.lib.stride_tricks.sliding_window_view(arr, (3, 3, 4)).reshape(arr.shape[0] - 2, arr.shape[1] - 2, 36)
   win = win[solid[1:-1, 1:-1]] if arr.shape[0] > 2 and arr.shape[1] > 2 else win.reshape(0, 36)
   patch = len(np.unique(win, axis=0)) / len(win) if len(win) else 1.0
   f = {"colors_per_1000": colors * 1000.0 / n, "ramp_steps": float(np.mean([len(c) for c in ramp])) if ramp else 0.0,
        "outline_colors": float(out_colors), "outline_top_share": float(top), "patch_unique": float(patch),
        "opaque": n / solid.size, "size": float(np.sqrt(solid.size))}
   m = measure_one(arr, False, prof or load_profile(), "crop")
   f["m_isolated"] = float(m.get("isolated") or 0.0)
   f["m_outline_share"] = float(m.get("outline_share") or 0.0)
   f["m_black_ratio"] = float(m.get("black_ratio") or 0.0)
   return f


# --- 분류기 ---


def auc(score: np.ndarray, y: np.ndarray) -> float:
   """ROC AUC (Mann-Whitney, 같은 값은 평균 순위)."""
   order = np.argsort(score, kind="stable")
   ranks = np.empty(len(score))
   s = score[order]
   i = 0
   while i < len(s):
      j = i
      while j + 1 < len(s) and s[j + 1] == s[i]:
         j += 1
      ranks[order[i:j + 1]] = (i + j) / 2.0 + 1.0
      i = j + 1
   pos = y == 1
   n1, n0 = pos.sum(), (~pos).sum()
   return float((ranks[pos].sum() - n1 * (n1 + 1) / 2.0) / (n1 * n0))


def fit_logistic(x: np.ndarray, y: np.ndarray, l2: float = L2, iters: int = 50) -> np.ndarray:
   """L2 로지스틱 회귀 (뉴턴법). x 는 표준화된 (N, D). 돌려주는 w 의 [0] 은 절편 (벌점 없음)."""
   xb = np.hstack([np.ones((len(x), 1)), x])
   w = np.zeros(xb.shape[1])
   reg = np.full(xb.shape[1], l2)
   reg[0] = 0.0
   for _ in range(iters):
      p = 1.0 / (1.0 + np.exp(-np.clip(xb @ w, -30, 30)))
      grad = xb.T @ (p - y) + reg * w
      hess = (xb * (p * (1 - p))[:, None]).T @ xb + np.diag(reg) + 1e-9 * np.eye(len(w))
      step = np.linalg.solve(hess, grad)
      w -= step
      if np.abs(step).max() < 1e-8:
         break
   return w


def _standardize(train: np.ndarray, *others: np.ndarray):
   mu, sd = train.mean(0), train.std(0)
   sd[sd == 0] = 1.0
   return [(a - mu) / sd for a in (train, *others)]


def group_folds(groups: list[str], y: np.ndarray, k: int = FOLDS, seed: int = 0) -> np.ndarray:
   """그룹 단위 k 겹 번호 (칸마다). 쪽(y)마다 그룹을 큰 것부터 가장 작은 겹에 넣어 겹마다 두 쪽이 다 들게 한다."""
   groups = np.asarray(groups)
   fold = np.empty(len(groups), int)
   rng = np.random.default_rng(seed)
   for side in np.unique(y):
      names, counts = np.unique(groups[y == side], return_counts=True)
      tie = rng.random(len(names))
      load = np.zeros(k)
      for i in np.lexsort((tie, -counts)):
         f = int(load.argmin())
         fold[(groups == names[i]) & (y == side)] = f
         load[f] += counts[i]
   return fold


def cv_auc(x: np.ndarray, y: np.ndarray, groups: list[str], k: int = FOLDS, seed: int = 0) -> dict:
   """그룹 단위 k 겹 교차 AUC. {mean, std, folds}."""
   fold = group_folds(groups, y, k, seed)
   scores = []
   for f in range(k):
      te = fold == f
      if len(np.unique(y[te])) < 2 or len(np.unique(y[~te])) < 2:
         continue
      tr_x, te_x = _standardize(x[~te], x[te])
      w = fit_logistic(tr_x, y[~te])
      scores.append(auc(np.hstack([np.ones((te.sum(), 1)), te_x]) @ w, y[te]))
   return {"mean": float(np.mean(scores)), "std": float(np.std(scores)), "folds": [round(s, 4) for s in scores]}


# --- 두 쪽 모으기 ---


def _crops_of(part: np.ndarray, images: list[np.ndarray], rng: np.random.Generator):
   """같은 창으로 images 각각을 자른다. 불투명 몫 ≥ MIN_OPAQUE 만."""
   for y, x, ch, cw in pairs.crops(*part.shape[:2], rng):
      if (part[y:y + ch, x:x + cw, 3] > 0).mean() < MIN_OPAQUE:
         continue
      for im in images:
         yield im[y:y + ch, x:x + cw].copy()


def flat_side(local: Path, ext_root: Path, palette_path: Path, n: int | None = None, split_seed: int = 0,
              limit: int | None = None):
   """납작화 쪽 조각 · 그룹 목록. n 이 있으면 자르기 창을 먼저 다 세고 n 개만 뽑아 그 블록만 납작화한다
   (검증 그룹을 다 납작화하면 조각 7만에 30분 — 렌더러 쪽은 3백이다)."""
   groups = json.loads((local / "groups.json").read_text(encoding="utf-8"))
   val = set(json.loads((local / "pretrain_split.json").read_text(encoding="utf-8"))["splits"][str(split_seed)]["val"])
   ours = json.loads((local / "ours.json").read_text(encoding="utf-8"))
   ours = ours if isinstance(ours, list) else ours["items"]
   pal = np.array(palette_mod.load(palette_path), dtype=np.int64)
   lock = lock_mod.Lock([tuple(int(v) for v in c) for c in pal], family=True)
   items = [(ext_root / it["path"], it["group"], int(it.get("scale") or 1)) for it in groups["items"]
            if it["side"] == "pack" and it["group"] in val]
   # 그룹이 안 매겨진 우리 그림은 한 장 = 한 그룹으로 본다
   items += [(Path(it["path"]), it.get("group") or f"ours-{i}", 1) for i, it in enumerate(ours)
             if it.get("kind") != "cc0" and it.get("origin") != "cc0"]
   if limit:
      items = items[:limit]
   # 1 창 세기 : (그림, 블록, 창, 납작화 씨앗)
   parts, windows = {}, []
   for i, (path, group, s) in enumerate(items):
      arr = image.load(path)[::s, ::s]
      rng = np.random.default_rng([7, i])
      fseeds = (i * 8 + rng.choice(8, SEEDS_PER_IMAGE, replace=False)).tolist()
      for b, block in enumerate(pairs.blocks(arr)):
         part = pairs.trim(block)
         if part is None:
            continue
         parts[i, b] = part
         for y, x, ch, cw in pairs.crops(*part.shape[:2], rng):
            if (part[y:y + ch, x:x + cw, 3] > 0).mean() >= MIN_OPAQUE:
               windows += [(i, b, (y, x, ch, cw), int(f)) for f in fseeds]
   if n and n < len(windows):
      # 그룹을 돌아가며 하나씩 — 고르게 뽑으면 큰 시트 몇 그룹이 다 가져간다
      rng = np.random.default_rng(3)
      by: dict = {}
      for w in windows:
         by.setdefault(items[w[0]][1], []).append(w)
      queues = [list(rng.permutation(len(v))) for v in by.values()]
      lists = list(by.values())
      picked = []
      while len(picked) < n:
         for q, v in zip(queues, lists):
            if q and len(picked) < n:
               picked.append(v[q.pop()])
      windows = picked
   # 2 뽑힌 창의 블록만 P 에 붙이고 납작화 (블록 · 씨앗마다 한 번)
   out, grp, cache = [], [], {}
   for i, b, (y, x, ch, cw), f in windows:
      if (i, b, f) not in cache:
         if (i, b) not in cache:
            cache[i, b] = pairs.target_of(parts[i, b], lock, pal)
         cache[i, b, f] = flatten(cache[i, b], f)[0]
      out.append(cache[i, b, f][y:y + ch, x:x + cw].copy())
      grp.append(items[i][1])
   return out, grp


def hole_side(local: Path):
   """렌더러 쪽 조각 · 그룹(원천 명세) 목록."""
   holes = json.loads((local / "gold" / "holes.json").read_text(encoding="utf-8"))["holes"]
   out, grp = [], []
   for n, h in enumerate(holes):
      arr = image.load(local / "gold" / "holes" / h["png"])
      rng = np.random.default_rng([11, n])
      for block in pairs.blocks(arr):
         part = pairs.trim(block)
         if part is not None:
            for c in _crops_of(part, [part], rng):
               out.append(c)
               grp.append(h["spec"])
   return out, grp


def balance(a: list, ga: list, b: list, gb: list, seed: int = 0):
   """많은 쪽을 씨앗 고정으로 줄여 두 쪽 수를 맞춘다."""
   rng = np.random.default_rng(seed)
   n = min(len(a), len(b))

   def pick(xs, gs):
      keep = np.sort(rng.choice(len(xs), n, replace=False))
      return [xs[i] for i in keep], [gs[i] for i in keep]

   return (*pick(a, ga), *pick(b, gb))


# --- 보고 ---


def measure(flat: list, gflat: list, hole: list, ghole: list) -> dict:
   """두 쪽 조각 → AUC · 특징별 무게 · 두 쪽 평균 · 특징 하나만 쓴 AUC."""
   prof = load_profile()
   names = [k for k, _ in FEATURES]
   x = np.array([[features(c, prof)[k] for k in names] for c in flat + hole])
   y = np.array([0] * len(flat) + [1] * len(hole))
   groups = list(gflat) + [f"hole:{g}" for g in ghole]
   cv = cv_auc(x, y, groups)
   cv_no_size = cv_auc(x[:, [i for i, k in enumerate(names) if k != "size"]], y, groups)
   w = fit_logistic(_standardize(x)[0], y)[1:]
   table = []
   for i, (k, label) in enumerate(FEATURES):
      single = cv_auc(x[:, [i]], y, groups)["mean"]
      table.append({"feature": k, "label": label, "weight": round(float(w[i]), 3), "single_auc": round(single, 3),
                    "flat_mean": round(float(x[y == 0, i].mean()), 3), "hole_mean": round(float(x[y == 1, i].mean()), 3)})
   table.sort(key=lambda r: -abs(r["weight"]))
   return {"n_flat": len(flat), "n_hole": len(hole), "groups_flat": len(set(gflat)), "groups_hole": len(set(ghole)),
           "auc": cv, "auc_no_size": cv_no_size, "pass": cv["mean"] <= PASS_AUC, "features": table}


def write_md(path: Path, report: dict) -> None:
   lines = ["# P4 지름길 검사 결과", "", f"> 통과 AUC ≤ {PASS_AUC} · 로지스틱 회귀 · 그룹 단위 {FOLDS}겹", "",
            "| 시도 | 조각 (납작 / 홀) | 그룹 (납작 / 홀) | AUC | 크기 뺀 AUC | 통과 | knobs |", "| --- | --- | --- | --- | --- | --- | --- |"]
   for k, a in sorted(report["attempts"].items(), key=lambda kv: int(kv[0])):
      lines.append(f"| {k} | {a['n_flat']} / {a['n_hole']} | {a['groups_flat']} / {a['groups_hole']} "
                   f"| {a['auc']['mean']:.3f} ± {a['auc']['std']:.3f} | {a['auc_no_size']['mean']:.3f} ± {a['auc_no_size']['std']:.3f} "
                   f"| {'예' if a['pass'] else '아니오'} | `{json.dumps(a['knobs'], ensure_ascii=False)}` |")
   for k, a in sorted(report["attempts"].items(), key=lambda kv: int(kv[0])):
      lines += ["", f"## 시도 {k} 특징 (무게 큰 차례)", "", "| 특징 | 무게 | 하나만 AUC | 납작 평균 | 홀 평균 |", "| --- | --- | --- | --- | --- |"]
      lines += [f"| {r['label']} | {r['weight']:+.3f} | {r['single_auc']:.3f} | {r['flat_mean']} | {r['hole_mean']} |" for r in a["features"]]
   lines += ["", "무게 + 쪽 = 렌더러(홀) 쪽, − 쪽 = 납작화 쪽. 「하나만 AUC」는 그 특징 하나로 같은 5겹을 돈 값."]
   path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _png_uri(arr: np.ndarray) -> str:
   from PIL import Image
   buf = io.BytesIO()
   Image.fromarray(arr, "RGBA").save(buf, "PNG")
   return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def write_sheet(path: Path, flat: list, hole: list, seed: int = 0) -> None:
   """두 쪽 조각 12장씩 접촉판 (×5 nearest, 회색 바탕)."""
   rng = np.random.default_rng(seed)
   rows = []
   for title, xs in (("납작화", flat), ("렌더러 (골드 홀)", hole)):
      pick = rng.choice(len(xs), min(SHEET_N, len(xs)), replace=False)
      cells = "".join(f'<img src="{_png_uri(xs[i])}" style="width:{xs[i].shape[1] * 5}px;height:{xs[i].shape[0] * 5}px">' for i in pick)
      rows.append(f"<h2>{title}</h2><div class=row>{cells}</div>")
   path.write_text("<!doctype html><meta charset=utf-8><style>body{background:#777;font-family:sans-serif;color:#fff}"
                   ".row{display:flex;flex-wrap:wrap;gap:10px}img{image-rendering:pixelated;background:#888;outline:1px solid #555}</style>"
                   + "".join(rows), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
   ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
   ap.add_argument("--local", default="train.local")
   ap.add_argument("--external", default="external.local")
   ap.add_argument("--palette", default="models.local/polish/palette.json")
   ap.add_argument("--out", default="train.local/shortcut")
   ap.add_argument("--attempt", type=int, default=1, help="시도 번호 (knobs 를 고칠 때마다 +1, 3번까지)")
   ap.add_argument("--limit", type=int, help="납작화 쪽 앞 N 장만 (시험용)")
   ap.add_argument("--sheet", action="store_true", help="두 쪽 조각 접촉판 sheet.html 도 쓴다")
   ap.add_argument("--knobs", help='섞기 범위를 이 프로세스에서만 바꿔 잰다 (JSON, 예 {"ramp": [3, 5]}). flatten.py 는 안 고친다')
   args = ap.parse_args(argv)
   sys.stdout.reconfigure(encoding="utf-8")
   local, out = Path(args.local), Path(args.out)
   out.mkdir(parents=True, exist_ok=True)
   if args.knobs:
      # 같은 파일을 다른 작업이 짝 굽기에 쓰는 중이라, 시도는 프로세스 안에서만 바꾼다 — 통과한 범위만 flatten.py 에 옮긴다
      KNOBS.update({k: tuple(v) for k, v in json.loads(args.knobs).items()})
   started = time.perf_counter()
   hole, ghole = hole_side(local)
   flat, gflat = flat_side(local, Path(args.external), Path(args.palette), n=len(hole), limit=args.limit)
   print(f"조각 : 납작 {len(flat)} ({len(set(gflat))} 그룹) · 홀 {len(hole)} ({len(set(ghole))} 그룹) · {time.perf_counter() - started:.0f}s")
   flat, gflat, hole, ghole = balance(flat, gflat, hole, ghole)
   result = measure(flat, gflat, hole, ghole)
   result["knobs"] = {k: list(v) for k, v in KNOBS.items() if k != "texture"}
   result["seconds"] = round(time.perf_counter() - started, 1)
   report_path = out / "report.json"
   report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {"version": 1, "attempts": {}}
   report["attempts"][str(args.attempt)] = result
   report_path.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
   write_md(out / "report.md", report)
   if args.sheet:
      write_sheet(out / "sheet.html", flat, hole)
   a = result["auc"]
   print(f"시도 {args.attempt} : AUC {a['mean']:.3f} ± {a['std']:.3f} (크기 뺌 {result['auc_no_size']['mean']:.3f}) · "
         f"{'통과' if result['pass'] else '넘음'} · 무게 큰 셋 {[r['feature'] for r in result['features'][:3]]}")
   return 0


if __name__ == "__main__":
   raise SystemExit(main())
