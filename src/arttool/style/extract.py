"""`arttool style extract` — 기준 그림 폴더에서 화풍을 숫자로 뽑는다 (설계 9-2 · 9-3 · 9-5).

결과 넷 : `NAME_palette.json` · `NAME_swatch.png` · `NAME_profile.yaml`(프로필에 붙일 조각) · `NAME_report.json`.
`--by-folder` 면 `--in` 아래 하위 폴더(종류)마다 따로 넷을 내고 `NAME_kinds.json` 요약 표를 더한다.

- 장마다 **「도트 아님」을 먼저** 가른다(싼 셈부터). 그런 장은 무거운 재기(배율 · 비슷한 색)를 건너뛴다 —
  도트가 아닌 큰 그림은 색이 수만 가지라 비슷한 색 쌍 찾기가 한 장에 수 초 걸린다.
- 재기는 검사(`arttool.checks`)의 `measure_*` 를 그대로 부르고, 문턱도 프로필의 같은 값을 쓴다.
- 그림 배열은 장마다 재고 나면 바로 놓아 주고 「한 장 요약」(색별 칸 수 · 맞닿은 색 쌍)만 쥔다 (실물 #12).
- 원본 그림은 읽기만 한다. 프로필 파일은 `--profile` 로 받아도 읽기만 한다.
"""

from __future__ import annotations

import math
import os
import re
import sys
from collections import Counter
from pathlib import Path

import numpy as np

from .. import image, palette
from ..check import is_guide
from ..checks import is_background, long_side, raw_edge, warning
from ..checks.outline import measure_outline
from ..checks.pixels import cap_for, measure_isolated, measure_near_colors
from ..checks.scale import measure_scale, measure_smooth
from ..errors import ArtToolError, UsageError
from ..jsonio import write_json
from ..paths import png_files, resolve_root, safe_join, write_text
from ..profile import STYLE_OUTLINES, Profile, load_profile_args
from . import output, ramps
from .light import estimate_light

VERSION = 1
MODES = ("auto", "sprite", "background")

# 「도트 아님」 문턱 (설계 9-5, 셋 다 실측)
SOFT_EDGE = 0.2           # 가장자리 칸 중 반투명(알파 1~254) 몫
SMALL_SIDE = 256          # 이 크기 이하인데
SMALL_COLORS = 128        # 색이 이보다 많으면. 실물 기준 그림은 최대 72색 — 256 → 128 로 도트 아님 무리 95.1% → 97.4% (실물 #10)
SMOOTH = 0.3              # 부드러운 확대 비율
# 넷째 문턱 (설계에 없음 — 갈래 G 가 더함) : 크기와 상관없이 색이 이보다 많으면 도트 아님.
# 256px 넘는 사진 · 그러데이션 · 크게 키운 그림은 위 셋을 다 빠져나가 장마다 수 초씩 무거운 재기를 탔다.
# 배경 도트도 색 수 경고 한도가 64 라 4096 은 넉넉하다
MANY_COLORS = 4096

NEAR_COLOR_LIMIT = 4096   # 색이 이보다 많은 장은 비슷한 색 쌍을 안 잰다 (시간 지킴)
MAJORITY = 0.6            # 표에서 이 몫을 넘어야 조각에 적는다
MIN_IMAGES = 5            # 도트 그림이 이보다 적으면 「적다」 — check.warn 제안을 안 낸다
MIN_BIN = 5               # 색 수 표의 크기 칸마다 이 장 수 이상일 때만 제안
DEFAULT_MAX_COLORS = 64   # 전체 색 상한 기본값. 32 면 기준 무리 전체에서 램프 82개가 잘렸다 (실물 #5)
CAP_HINT = 16             # 상한으로 뺀 색이 이 이상이면 「종류별로 나눠 뽑아라」 를 덧붙인다
NAME_RE = re.compile(r"[\w.-]+")
OUTLINE_WITH_COLOR = "black"
SHOWN = 10                # 경고 detail 에 적는 파일 이름 수 (items 에는 다 적는다)


def run(args) -> dict:
   opts = _options(args)
   in_dirs = [_check_in(d) for d in args.in_dirs]
   out_root = _out_root(args.out_dir, in_dirs)
   name = _name(getattr(args, "name", None), in_dirs[0])
   if getattr(args, "by_folder", False):
      return _run_kinds(in_dirs, out_root, name, opts)
   return extract(in_dirs, out_root, name, opts)


def extract(in_dirs: list[Path], out_root: Path, name: str, opts: dict) -> dict:
   """폴더 묶음 하나에서 뽑아 결과 넷을 쓰고 보고 dict 를 돌려준다."""
   prof, length = opts["prof"], opts["length"]
   warnings: list[dict] = []
   items = _measure_all(in_dirs, prof, opts["mode"], warnings, opts["force"])
   if not items:
      raise UsageError(f"쓸 수 있는 기준 그림이 0장이다 : {', '.join(str(d) for d in in_dirs)}")

   summary = _summarize(items, prof)
   pal = _palette(items, length, opts, summary, warnings)
   _warn_limits(items, summary, warnings, in_dirs)

   files = {k: safe_join(out_root, f"{name}_{k}{ext}") for k, ext in
            (("palette", ".json"), ("swatch", ".png"), ("profile", ".yaml"), ("report", ".json"))}
   if pal is not None and pal["ramps"]:
      _write_palette(files, name, pal, summary)
   else:
      files.pop("palette")
      files.pop("swatch")

   entries, head, notes = _fragment(prof, summary, pal, name, length)
   write_text(files["profile"], output.fragment_text(entries, head, notes))

   report = _report(name, items, summary, pal, warnings, files, length)
   write_json(files["report"], report)
   return report


# --- 인자 ---


def _options(args) -> dict:
   prof = load_profile_args(args)
   value = getattr(args, "max_colors", None)
   max_colors = DEFAULT_MAX_COLORS if value is None else int(value)
   if max_colors < 1:
      raise UsageError(f"--max-colors 는 1 이상이다 : {max_colors}")
   mode = getattr(args, "mode", "auto") or "auto"
   if mode not in MODES:
      raise UsageError(f"--mode 는 {' · '.join(MODES)} 중 하나다 : {mode}")
   return {"prof": prof, "length": _ramp_len(args, prof), "max_colors": max_colors, "mode": mode,
           "force": bool(getattr(args, "force", False)),
           "with_backgrounds": bool(getattr(args, "with_backgrounds", False))}


def _ramp_len(args, prof: Profile) -> int:
   value = getattr(args, "ramp_len", None)
   value = int(value) if value is not None else int(prof.palette.get("ramp_len") or 6)
   if value < 2:
      raise UsageError(f"램프 길이는 2 이상이다 : {value}")
   return value


def _check_in(path: str) -> Path:
   folder = Path(path)
   if not folder.is_dir():
      raise UsageError(f"--in 은 PNG 폴더여야 한다 : {path}")
   return folder


def _same(a: Path, b: Path) -> bool:
   return os.path.normcase(str(a.resolve())) == os.path.normcase(str(b.resolve()))


def _out_root(out_dir: str, in_dirs: list[Path]) -> Path:
   root = resolve_root(out_dir)
   if root.is_file():
      raise UsageError(f"--out 은 폴더여야 한다 : {out_dir}")
   for folder in in_dirs:
      if _same(folder, root):
         raise UsageError(f"--out 이 --in 과 같다 : {out_dir}. 원본 폴더에 쓰지 않는다")
   return root


def _clean_name(text: str) -> str:
   return re.sub(r"[^\w.-]", "_", text).lstrip(".")


def _name(given: str | None, first: Path) -> str:
   if given:
      if not NAME_RE.fullmatch(given) or given.startswith("."):
         raise UsageError(f"--name 은 글자 · 숫자 · _ · - · . 만 쓴다 : {given}")
      return given
   return _clean_name(first.resolve().name) or "style"


def kind_dirs(folder: Path) -> list[Path]:
   """바로 아래 하위 폴더 중 PNG 가 하나라도 바로 들어 있는 것 (이름순)."""
   return sorted(p for p in folder.iterdir() if p.is_dir() and png_files(p))


# --- 종류별 뽑기 (실물 #9) ---


def _run_kinds(in_dirs: list[Path], out_root: Path, name: str, opts: dict) -> dict:
   """`--in` 아래 하위 폴더마다 따로 뽑고 요약 표 `NAME_kinds.json` 을 쓴다."""
   kinds: list[tuple[str, Path]] = []
   taken: Counter = Counter()
   for folder in in_dirs:
      for sub in kind_dirs(folder):
         if _same(sub, out_root):
            continue
         base = _clean_name(sub.name) or "kind"
         taken[base] += 1
         kinds.append((base if taken[base] == 1 else f"{base}_{taken[base]}", sub))
   if not kinds:
      raise UsageError("--by-folder 인데 --in 아래에 PNG 가 든 하위 폴더가 없다 : " + ", ".join(str(d) for d in in_dirs))

   rows, warnings = [], []
   loose = [str(d) for d in in_dirs if png_files(d)]
   if loose:
      warnings.append(warning("by_folder_loose", f"--in 바로 아래 PNG 는 --by-folder 에서 안 쓴다 : {', '.join(loose)}", loose))
   for kind, sub in kinds:
      print(f"[{kind}] 뽑는 중 …", file=sys.stderr)
      try:
         report = extract([sub], out_root, f"{name}_{kind}", opts)
      except UsageError as exc:
         rows.append({"kind": kind, "status": "skip", "detail": str(exc)})
         continue
      rows.append(_kind_row(kind, report))

   summary_file = safe_join(out_root, f"{name}_kinds.json")
   result = {
      "version": VERSION,
      "status": "warn" if warnings or any(r["status"] != "ok" for r in rows) else "ok",
      "name": name,
      "kinds": rows,
      "warnings": warnings,
      "out": {"kinds": str(summary_file)},
   }
   write_json(summary_file, result)
   for row in rows:
      print(_kind_line(row), file=sys.stderr)
   return result


def _kind_row(kind: str, report: dict) -> dict:
   pal = report.get("palette") or {}
   return {
      "kind": kind,
      "status": report["status"],
      **report["summary"],
      "outline": report["outline"]["pick"],
      "outline_table": report["outline"]["table"],
      "light": report["light"]["pick"],
      "light_table": report["light"]["table"],
      "scale": report["scale"]["pick"],
      "ramps": len(pal.get("ramps") or []),
      "singles": len(pal.get("singles") or []),
      "colors": pal.get("colors"),
      "removed_ramps": len(pal.get("removed_ramps") or []),
      "hue_step": pal.get("hue_step"),
      "held": report.get("held"),
      "warnings": [w["rule"] for w in report["warnings"]],
      "report": report["out"]["report"],
   }


def _kind_line(row: dict) -> str:
   if row["status"] == "skip":
      return f"{row['kind']:<12} 건너뜀 — {row['detail']}"
   return (f"{row['kind']:<12} {row['pixel']:>3}/{row['images']:<3}장 · 외곽선 {row['outline'] or '갈림'} · "
           f"빛 {row['light'] or '갈림'} · 램프 {row['ramps']} (한 색 {row['singles']}) · 색 {row['colors']}")


# --- 장마다 재기 ---


def _measure_all(in_dirs: list[Path], prof: Profile, mode: str, warnings: list[dict], force: bool) -> list[dict]:
   items = []
   unreadable, empty = [], []
   for folder in in_dirs:
      files = png_files(folder)
      guides = [f for f in files if is_guide(f)]
      if guides:
         print(f"가이드 파일 {len(guides)}개를 건너뛴다 : {', '.join(f.name for f in guides)}", file=sys.stderr)
      for file in (f for f in files if not is_guide(f)):
         where = f"{folder.name}/{file.name}"
         try:
            arr = image.load(file)
         except ArtToolError as exc:
            unreadable.append(f"{where} - {exc}")
            continue
         if long_side(arr) == 0:
            empty.append(where)
            continue
         item = measure_one(arr, _is_background(arr, prof, mode), prof, where)
         # 팔레트 재료는 「한 장 요약」 만 쥐고 그림은 놓아 준다. 도트가 아닌 장(--force 일 때만 재료)은 줄인 표본으로 요약한다
         if item["pixel"]:
            item["stats"] = ramps.stats_of(ramps.key_map(arr))
         elif force:
            item["stats"] = ramps.stats_of(ramps.sample_keys(arr))
            item["sampled"] = True
         del arr
         items.append(item)
   if unreadable:
      warnings.append(warning("unreadable", f"못 읽어 뺀 그림 {len(unreadable)}장", unreadable))
   if empty:
      warnings.append(warning("empty", f"빈 그림이라 뺀 그림 {len(empty)}장", empty))
   return items


def _is_background(arr, prof: Profile, mode: str) -> bool:
   if mode != "auto":
      return mode == "background"
   node = prof.check["background"]
   return bool(node["auto"]) and is_background(arr, int(node["min_side"]))


def count_colors(arr) -> int:
   """불투명 색 가짓수. `measure_colors` 의 `colors` 와 같은 값(알파 > 0 칸의 RGB)인데,
   색을 정수 하나로 묶어 세서 백만 칸 그림에서도 빠르다 — 「도트 아님」 가르기가 맨 앞에서 부르므로."""
   keys = ramps.key_map(arr)
   seen = np.zeros(1 << 24, dtype=bool)       # 색 열쇠 2²⁴ 칸 표시판 (16MB). 정렬하는 np.unique 보다 큰 그림에서 열 배쯤 빠르다
   seen[keys[keys >= 0]] = True
   return int(np.count_nonzero(seen))


def not_pixel_reasons(arr) -> tuple[list[str], dict]:
   """「도트 아님」 까닭 목록과 잰 값. 싼 셈부터 하고 하나라도 걸리면 거기서 멈춘다."""
   seen: dict = {}
   edge = raw_edge(arr)
   if edge.any():
      alpha = arr[:, :, 3][edge]
      soft = float(((alpha > 0) & (alpha < 255)).mean())
      seen["soft_edge"] = round(soft, 4)
      if soft > SOFT_EDGE:
         return [f"가장자리 반투명 {soft:.2f} > {SOFT_EDGE}"], seen
   size = long_side(arr)
   colors = count_colors(arr)
   seen["colors"] = colors
   if size <= SMALL_SIDE and colors > SMALL_COLORS:
      return [f"{size}px 인데 색 {colors}가지 > {SMALL_COLORS}"], seen
   if colors > MANY_COLORS:
      return [f"색 {colors}가지 > {MANY_COLORS}"], seen
   smooth = measure_smooth(arr)
   seen["smooth"] = smooth["ratio"]
   if smooth["ratio"] > SMOOTH:
      return [f"부드러운 확대 비율 {smooth['ratio']:.2f} > {SMOOTH}"], seen
   return [], seen


def measure_one(arr, background: bool, prof: Profile, where: str) -> dict:
   """한 장 재기. 도트가 아니면 가른 까닭만 적고 무거운 재기는 건너뛴다. 그림 배열은 돌려주는 dict 에 안 넣는다."""
   why, seen = not_pixel_reasons(arr)
   item = {"file": where, "background": background, "size": long_side(arr), "pixel": not why}
   if why:
      item["not_pixel"] = why
      item.update({k: v for k, v in seen.items() if k in ("soft_edge", "colors")})
      return item

   colors = seen["colors"]
   scale = measure_scale(arr, background, float(prof.warn("integer_scale")["block_ratio"]))
   isolated = measure_isolated(arr)
   item.update(colors=colors, smooth=seen["smooth"], scale=scale["scale"], scale_mixed=scale["mixed"],
               scales=scale["scales"], isolated=isolated["ratio"])
   item["near_pairs"] = None
   if colors <= NEAR_COLOR_LIMIT:
      item["near_pairs"] = len(measure_near_colors(arr, int(prof.warn("near_colors")["max_delta"])))
   if not background:
      outline = measure_outline(arr, prof.style["light"], float(prof.warn("outline")["black_ratio"]))
      item.update(outline=outline["verdict"], outline_share=outline["share"], black_ratio=outline["black_ratio"])
      if outline["edge_top"] is not None:
         # 가장자리 최빈 색과 그 칸 수 — 무리 판정이 solid 면 이것들을 모아 외곽선 색을 고른다
         item.update(edge_color=palette.to_hex(tuple(outline["edge_top"])), edge_color_count=outline["edge_top_count"])
      item["light"] = estimate_light(arr)["light"]
   return item


# --- 표 ---


def _pick(table: Counter, total: int) -> tuple[str | int | None, int]:
   """가장 많은 값과 그 장 수. 몫이 MAJORITY 를 못 넘으면 값은 None."""
   if not table or total == 0:
      return None, 0
   value, count = sorted(table.items(), key=lambda kv: (-kv[1], str(kv[0])))[0]
   return (value if count / total > MAJORITY else None), count


def _summarize(items: list[dict], prof: Profile) -> dict:
   pixel = [i for i in items if i["pixel"]]
   sprites = [i for i in pixel if not i["background"]]
   # 모르는 판정 값(예 X1 의 새 `solid`)도 그대로 센다
   outline = Counter(str(i["outline"]) for i in sprites if i.get("outline"))
   # solid 로 잰 장들의 가장자리 최빈 색을 칸 수로 더한다 — 무리가 solid 면 가장 많은 색이 외곽선 색
   solid_colors: Counter = Counter()
   for i in sprites:
      if i.get("outline") == "solid" and i.get("edge_color"):
         solid_colors[i["edge_color"]] += int(i.get("edge_color_count", 0))
   light = Counter(i["light"] for i in sprites)
   scale = Counter(i["scale"] for i in pixel if i["scale"] is not None)
   scale_pick = sorted(scale.items(), key=lambda kv: (-kv[1], kv[0]))[0][0] if scale else None
   return {
      "images": len(items),
      "pixel": len(pixel),
      "not_pixel": len(items) - len(pixel),
      "sprites": len(sprites),
      "backgrounds": sum(1 for i in pixel if i["background"]),
      "outline": {"table": dict(outline), "pick": _pick(outline, sum(outline.values())), "total": sum(outline.values()),
                  "solid_color": (sorted(solid_colors.items(), key=lambda kv: (-kv[1], kv[0]))[0][0] if solid_colors else None)},
      "light": {"table": dict(light), "pick": _pick(light, len(sprites)), "total": len(sprites)},
      "scale": {"table": {str(k): v for k, v in scale.items()}, "pick": scale_pick, "count": scale.get(scale_pick, 0),
                "total": sum(scale.values())},
      "size_bins": _size_bins(sprites, prof),
      "stats": _stats(pixel, sprites),
   }


def _split_tables(summary: dict) -> list[str]:
   """하나로 못 고른 표 이름. 외곽선은 잰 장이 있는데 고른 값이 None 이면,
   빛은 「모름」 을 뺀 방향들끼리 다수가 없으면 갈린 것이다 — 평면 그림은 빛이 「모름」 인 게 맞아서 그것만으로는 안 갈린다."""
   split = []
   if summary["outline"]["total"] and summary["outline"]["pick"][0] is None:
      split.append("outline")
   known = Counter({k: v for k, v in summary["light"]["table"].items() if k != "unknown"})
   if known and _pick(known, sum(known.values()))[0] is None:
      split.append("light")
   return split


def held_reason(summary: dict) -> str | None:
   """check.warn 문턱 제안을 보류할 까닭 (실물 #11). 도트가 아닌 그림이 절반을 넘거나(팔레트 보류와 같은 조건),
   기준 그림이 적거나, 외곽선 · 빛 표가 갈렸으면 보류."""
   if summary["not_pixel"] * 2 > summary["images"]:
      return f"도트가 아닌 그림이 절반을 넘는다 ({summary['not_pixel']}/{summary['images']}장)"
   if summary["pixel"] < MIN_IMAGES:
      return f"도트 그림이 {summary['pixel']}장뿐이다 (< {MIN_IMAGES})"
   split = _split_tables(summary)
   if split:
      return f"{' · '.join(split)} 표가 갈렸다 — 종류가 섞인 무리로 보인다"
   return None


def _size_bins(sprites: list[dict], prof: Profile) -> list[dict]:
   """불투명 bbox 긴 변을 color_cap 표의 칸으로 나눠 칸마다 장 수 · 색 수 p50 · p90."""
   table = prof.color_cap_table()
   top = max(table)
   bins: dict[str, list[int]] = {}
   for item in sprites:
      key = str(cap_for(item["size"], table)[0]) if item["size"] <= top else "above"
      bins.setdefault(key, []).append(item["colors"])
   order = [str(k) for k in table] + ["above"]
   return [{"bin": key, "images": len(bins[key]), "colors_p50": ramps.percentile(bins[key], 50),
            "colors_p90": ramps.percentile(bins[key], 90), "cap": table.get(int(key)) if key != "above" else None}
           for key in order if key in bins]


def _stats(pixel: list[dict], sprites: list[dict]) -> dict:
   """「이 게임의 평소 값」 p50 · p95 (설계 9-3 ⑥)."""
   columns = {
      "isolated": [i["isolated"] for i in pixel],
      "near_pairs": [i["near_pairs"] for i in pixel if i["near_pairs"] is not None],
      "outline_share": [i["outline_share"] for i in sprites if i.get("outline_share") is not None],
      "smooth": [i["smooth"] for i in pixel],
   }
   return {k: {"p50": ramps.percentile(v, 50), "p95": ramps.percentile(v, 95), "n": len(v)} for k, v in columns.items()}


# --- ① 팔레트 ---


def _palette(items, length, opts, summary, warnings) -> dict | None:
   prof, max_colors, force, with_backgrounds = opts["prof"], opts["max_colors"], opts["force"], opts["with_backgrounds"]
   if summary["not_pixel"] * 2 > summary["images"] and not force:
      warnings.append(warning("palette_held", f"도트가 아닌 그림이 절반을 넘는다 ({summary['not_pixel']}/{summary['images']}장) — "
                                              "팔레트를 안 냈다. --force 면 낸다"))
      return None
   # --force 면 도트가 아닌 장도 (줄인 표본으로) 팔레트 재료로 넣는다 (사람이 그래도 내라고 했으므로)
   usable = [i for i in items if "stats" in i]
   sources = [i for i in usable if with_backgrounds or not i["background"]]
   backs = [i for i in usable if i["background"] and not with_backgrounds]
   background_colors = ramps.top_colors([i["stats"] for i in backs]) if backs else []
   if not sources:
      warnings.append(warning("no_sprites", "팔레트를 뽑을 스프라이트가 없다" + (" — 배경 색도 쓰려면 --with-backgrounds" if backs else "")))
      return {"ramps": [], "background_colors": background_colors, "outline": None, "outline_candidate": None}

   # 외곽선 표가 검정이거나 갈렸으면(보류) 검정 후보를 램프 파일의 outline 칸에 넣는다.
   # solid 면 외곽선 칸 최빈 색을 넣는다. selout · none 이면 비운다
   verdict = summary["outline"]["pick"][0]
   use_black = verdict == OUTLINE_WITH_COLOR or verdict is None
   line_color = None
   solid_hex = summary["outline"].get("solid_color")
   if verdict == "solid" and solid_hex:
      # 한 색 선 : 그 무리에서 외곽선 칸에 가장 많이 쓰인 한 색을 외곽선 색으로, 램프에서는 뺀다
      r, g, b = palette.parse_hex(solid_hex)
      line_color = (r << 16) | (g << 8) | b
   pal = ramps.build_palette([i["stats"] for i in sources], length, max_colors,
                             int(prof.warn("near_colors")["max_delta"]), use_black, line_color=line_color)
   pal["background_colors"] = background_colors
   pal["sources"] = len(sources)
   pal["sampled"] = sum(1 for i in sources if i.get("sampled"))
   if pal["removed_ramps"]:
      detail = (f"색 상한 {max_colors} 를 넘어 램프 {len(pal['removed_ramps'])}개(색 {pal['removed_colors']}가지)를 뺐다")
      if pal["removed_colors"] >= CAP_HINT:
         detail += " — 종류가 섞인 무리면 종류별로 나눠 뽑는다(--by-folder 또는 폴더마다 --in). 아니면 --max-colors 를 올린다"
      warnings.append(warning("palette_cap", detail, [r["name"] for r in pal["removed_ramps"]]))
   if not pal["ramps"]:
      warnings.append(warning("no_ramps", "남은 램프가 없어 팔레트를 안 냈다"))
   return pal


def _write_palette(files: dict, name: str, pal: dict, summary: dict) -> None:
   outline = ramps.to_rgb(pal["outline"]) if pal["outline"] is not None else None
   ramp_set = palette.Ramps(name, {r["name"]: [ramps.to_rgb(k) for k in r["colors"]] for r in pal["ramps"]},
                            outline, len(pal["ramps"][0]["colors"]))
   comment = (f"arttool style extract 가 기준 그림 {pal['sources']}장에서 뽑았다. 맞닿은 색끼리 묶은 램프다 — "
              "보고 고쳐서 palettes/ 나 게임 저장소로 옮긴다")
   extra = {"comment": comment, "usage": pal["usage"], "hue_step": pal["hue_step"]}
   if pal["singles"]:
      # 한 색 + 채운 칸 램프 : 그림자 · 하이라이트 칸이 없다. selout 이 맨 아래 칸에서 멈추니 손으로 채우거나 빼는 자리
      extra["singles"] = pal["singles"]
   if pal["outline_candidate"] is not None and pal["outline"] is None:
      extra["outline_candidate"] = ramps.to_hex(pal["outline_candidate"])
   palette.save_ramps(files["palette"], ramp_set, extra)
   discarded = pal["dropped_keys"][: ramps.DROPPED_SHOWN]
   shown_outline = pal["outline"] if pal["outline"] is not None else pal["outline_candidate"]
   image.save(files["swatch"], output.swatch(pal["ramps"], shown_outline, discarded, summary["scale"]["pick"] or 1))


# --- 경고 ---


def _names(files: list[str]) -> str:
   return ", ".join(files[:SHOWN]) + (" …" if len(files) > SHOWN else "")


def _warn_limits(items: list[dict], summary: dict, warnings: list[dict], in_dirs: list[Path]) -> None:
   if summary["pixel"] < MIN_IMAGES:
      warnings.append(warning("few_images", f"기준 그림이 적다 — 도트 그림 {summary['pixel']}장 < {MIN_IMAGES}. check.warn 제안은 안 낸다"))
   off = [i["file"] for i in items if not i["pixel"]]
   if off:
      warnings.append(warning("not_pixel", f"도트가 아닌 그림 {len(off)}장을 재기에서 뺐다 : {_names(off)}", off))
   mixed = [i["file"] for i in items if i.get("scale_mixed")]
   if mixed:
      warnings.append(warning("mixed_scale", f"한 장 안에 도트 굵기가 섞인 그림 {len(mixed)}장 : {_names(mixed)}", mixed))
   split = _split_tables(summary)
   if split:
      subs = [str(p) for d in in_dirs for p in kind_dirs(d)]
      how = (f"--by-folder 로 하위 폴더 {len(subs)}개를 따로 뽑는다" if subs
             else "종류별 폴더로 나눠 폴더마다 따로 뽑는다")
      warnings.append(warning("by_kind", f"{' · '.join(split)} 표가 갈렸다 — 종류가 섞인 무리로 보인다. {how}", subs))


# --- 조각 YAML ---


def _of(count: int, total: int) -> str:
   return f"{total}장 중 {count}장 ({round(100 * count / total)}%)" if total else "잰 장 없음"


def _fragment(prof: Profile, summary: dict, pal: dict | None, name: str, length: int):
   """(entries, head, notes). 프로필에 지금 있는 값과 같은 값은 안 적고 주석으로만 남긴다."""
   entries: list = []
   notes: dict[str, list[str]] = {"palette": [], "style": [], "check.warn": []}
   head = [f"기준 그림 {summary['images']}장 — 도트 {summary['pixel']}장 (스프라이트 {summary['sprites']} · 배경 {summary['backgrounds']}) · 도트 아님 {summary['not_pixel']}장"]

   def put(path: tuple, value, note: str, current) -> None:
      if value == current:
         notes[path[0] if path[0] != "check" else "check.warn"].append(f"{'.'.join(path)} : {_scalar_note(value)} — 프로필과 같아 뺐다 ({note})")
         return
      entries.append((path, value, note))

   if pal is not None and pal.get("ramps"):
      entries.append((("palette", "ramp_len"), length, "팔레트 파일과 짝"))
      verdict = summary["outline"]["pick"][0]
      if verdict == OUTLINE_WITH_COLOR and pal["outline"] is not None:
         put(("palette", "outline"), ramps.to_hex(pal["outline"]), "순흑 외곽선", prof.palette.get("outline"))
      elif verdict == "solid" and pal["outline"] is not None:
         put(("palette", "outline"), ramps.to_hex(pal["outline"]), "한 색 외곽선 — 외곽선 칸에 가장 많이 쓰인 색",
             prof.palette.get("outline"))
      elif verdict in ("selout", "selout+light", "none"):
         put(("palette", "outline"), None, f"외곽선 {verdict} — 따로 쓰는 외곽선 색이 없다", prof.palette.get("outline"))
      elif pal["outline"] is not None:
         notes["palette"].append(f"외곽선 판정 보류 — 검정 후보 {ramps.to_hex(pal['outline'])} 를 팔레트 파일 outline 칸에만 넣었다")
      entries.append((("palette", "ramps_file"), f"palettes/{name}.json", "팔레트를 그 자리로 옮긴 뒤"))
      if pal.get("singles"):
         notes["palette"].append(f"한 색짜리 램프 {len(pal['singles'])}개 : {', '.join(pal['singles'])} — 그늘 칸을 채우거나 뺀다")
   else:
      notes["palette"].append("팔레트를 안 냈다 — 보고 warnings 를 본다")

   _style_entries(prof, summary, put, notes)
   held = held_reason(summary)
   if held is None:
      _warn_entries(prof, summary, put)
   else:
      notes["check.warn"].append(f"판정 보류 — {held}. 문턱 제안을 안 낸다")
   return entries, head, notes


def _scalar_note(value) -> str:
   return "null" if value is None else str(value)


def _style_entries(prof: Profile, summary: dict, put, notes: dict) -> None:
   out = summary["outline"]
   value, count = out["pick"]
   if value is None:
      notes["style"].append(f"outline : 정하지 못함 ({_table_text(out['table'])}) — 프로필 값 그대로")
   elif value not in STYLE_OUTLINES:
      notes["style"].append(f"outline : {value} ({_of(count, out['total'])}) — 프로필이 받는 값이 아니라 안 적었다")
   else:
      put(("style", "outline"), value, _of(count, out["total"]), prof.style["outline"])

   light = summary["light"]
   value, count = light["pick"]
   unknown = light["table"].get("unknown", 0)
   if value in ("top_left", "top", "top_right"):
      put(("style", "light"), value, f"{_of(count, light['total'])} · 모름 {unknown}장", prof.style["light"])
   else:
      notes["style"].append(f"light : 정하지 못함 ({_table_text(light['table'])}) — 프로필 값 그대로")

   scale = summary["scale"]
   if scale["pick"] is not None:
      put(("style", "scale"), int(scale["pick"]), _of(scale["count"], scale["total"]), prof.style["scale"])


def _table_text(table: dict) -> str:
   return " · ".join(f"{k} {v}" for k, v in sorted(table.items(), key=lambda kv: -kv[1])) or "잰 장 없음"


def _warn_entries(prof: Profile, summary: dict, put) -> None:
   current = prof.color_cap_table()
   proposal = {}
   for row in summary["size_bins"]:
      if row["bin"] == "above" or row["images"] < MIN_BIN:
         continue
      want = int(math.ceil(row["colors_p90"]))
      if want != current[int(row["bin"])]:
         proposal[int(row["bin"])] = want
   if proposal:
      put(("check", "warn", "color_cap", "table"), proposal, f"크기 칸마다 {MIN_BIN}장 이상일 때만, p90 올림", None)

   stats = summary["stats"]
   for rule, key, column, digits in (("isolated", "max_ratio", "isolated", 3), ("integer_scale", "smooth_ratio", "smooth", 2)):
      p95 = stats[column]["p95"]
      now = float(prof.warn(rule)[key])
      if p95 is not None and p95 > now:
         put(("check", "warn", rule, key), min(1.0, ramps.ceil_to(p95, digits)), f"지금 {now} → p95", now)


# --- 보고 ---


HIDDEN = ("dropped_keys", "ramps", "outline", "outline_candidate")


def _report(name, items, summary, pal, warnings, files, length) -> dict:
   rows = [{k: v for k, v in i.items() if k != "stats"} for i in items]
   palette_part = None
   if pal is not None:
      palette_part = {k: v for k, v in pal.items() if k not in HIDDEN}
      palette_part["ramps"] = [{"name": r["name"], "colors": [ramps.to_hex(k) for k in r["colors"]],
                                "padded": r["padded"], "usage": r["usage"]} for r in pal.get("ramps", [])]
      for key in ("outline", "outline_candidate"):
         palette_part[key] = ramps.to_hex(pal[key]) if pal.get(key) is not None else None
      palette_part["ramp_len"] = length
   return {
      "version": VERSION,
      "status": "warn" if warnings else "ok",
      "name": name,
      "summary": {k: summary[k] for k in ("images", "pixel", "not_pixel", "sprites", "backgrounds")},
      "outline": {"table": summary["outline"]["table"], "pick": summary["outline"]["pick"][0]},
      "light": {"table": summary["light"]["table"], "pick": summary["light"]["pick"][0]},
      "scale": {"table": summary["scale"]["table"], "pick": summary["scale"]["pick"]},
      "held": held_reason(summary),
      "size_bins": summary["size_bins"],
      "stats": summary["stats"],
      "palette": palette_part,
      "images": rows,
      "warnings": warnings,
      "out": {k: str(v) for k, v in files.items()},
   }
