"""③ 검수. 규칙 하나당 함수 하나. 보고는 JSON 이고 status 는 ok 또는 fail.

2026-10-04 개선 설계 7절 · 9-4 끝 : 새 검사 일곱(`checks/`)은 **경고**라 `warnings` 칸에만 들어간다.
`status` · `failed` · `skipped` · 종료 코드 · `bake` 는 기존 다섯 규칙으로만 정한다.
`--template` 을 주면 템플릿 `check` 칸을 프로필 위에 겹치고(9-4 끝 차례), 최소 규칙 `must` 를 본다.
"""

from __future__ import annotations

import copy
import sys
import time
from pathlib import Path

from . import image, palette
from .checks import is_background, long_side, warning
from .checks import loop as loop_check
from .checks import outline as outline_check
from .checks import pixels as pixel_check
from .checks import ramp as ramp_check
from .checks import scale as scale_check
from .errors import ArtToolError, ProfileError, UsageError
from .jsonio import read_json
from .paths import png_files
from .profile import Profile, deep_merge, reject_unknown, validate
from .template import schema

VERSION = 1

# 낱장 모드에서 프레임 규격이 없어 못 도는 규칙들.
LOOSE_SKIPPED = ["baseline", "bbox_drift"]

MODES = ("auto", "sprite", "background")

# 경고 검사가 이 초보다 오래 걸리면 stderr 에 진행을 알린다 (큰 그림 묶음 · 실물 시험 #12-1).
PROGRESS_EVERY = 2.0

# 템플릿 render 가 낸 가이드 · 밑그림 파일. 낱장 모드에서 건너뛴다(설계 8-3).
GUIDE_SUFFIXES = ("_guide", "_preview", "_over")
TEMPLATE_FILE = "template.json"   # 이 파일이 있는 폴더만 render 폴더로 본다

# 템플릿 최소 규칙 낱말. kind 별 기본 목록은 템플릿 처리기(`template/kinds.py` 의 `must_default`)가 정본이다.
MUST_WORDS = schema.MUST_WORDS


def result(rule: str, ok: bool, detail: str, items: list | None = None) -> dict:
   return {"rule": rule, "ok": ok, "detail": detail, "items": items or []}


def load_frames(prof: Profile, build_dir: str | Path) -> tuple[dict, list[dict]]:
   """frames.json 을 읽고 프레임을 다 펼친다."""
   root = Path(build_dir)
   index = read_json(root / "frames.json")
   frame_w, frame_h = prof.frame
   if index.get("frame") != [frame_w, frame_h]:
      raise ArtToolError(f"frames.json 의 프레임이 프로필과 다르다 : {index.get('frame')}")

   frames = []
   for sheet in index["sheets"]:
      grid = image.split_grid(image.load(root / sheet["file"]), frame_w, frame_h)
      directions = sheet["directions"]
      if len(grid) != len(directions):
         raise ArtToolError(f"{sheet['file']} 의 줄이 {len(grid)}개다. 방향 {len(directions)}개와 같아야 한다")
      frames += _sheet_frames(sheet["anim"], grid, directions)
   return index, frames


def _sheet_frames(anim: str, grid: list, directions: list) -> list[dict]:
   out = []
   for row, direction in enumerate(directions):
      for col, arr in enumerate(grid[row]):
         out.append({"anim": anim, "direction": direction, "frame": col, "arr": arr})
   return out


def is_loose(path: str | Path) -> bool:
   """낱장 모드인가. PNG 파일 하나이거나, frames.json 이 없는 폴더면 그렇다."""
   source = Path(path)
   if source.is_file():
      return source.suffix.lower() == ".png"
   return not (source / "frames.json").is_file()


def render_name(folder: Path) -> str | None:
   """`template render` 가 쓴 폴더면 그 템플릿 이름(template.json 의 name), 아니면 None.

   template.json 이 없거나 못 읽거나 name 이 없으면 render 폴더로 보지 않는다 — 그때는 아무 파일도 안 건너뛴다.
   """
   marker = Path(folder) / TEMPLATE_FILE
   if not marker.is_file():
      return None
   try:
      name = read_json(marker).get("name")
   except (ArtToolError, ValueError, OSError, AttributeError):
      return None
   return name if isinstance(name, str) and name else None


def is_guide(path: Path, name: str | None = None) -> bool:
   """템플릿 가이드 · 마스크 · 미리보기 파일인가 (리뷰 R1-H4 로 좁혔다).

   **render 폴더(같은 폴더에 template.json)에서, 그 템플릿 name 이 붙은** `<name>_guide` · `<name>_preview` ·
   `<name>_over` · `<name>_mask_<겹>` 만 가이드로 본다. `game_over.png` · `card_preview.png` 같은 보통 그림은 늘 검수한다.
   name 을 안 주면 path 폴더의 template.json 에서 읽는다.
   """
   if name is None:
      name = render_name(path.parent)
   if name is None:
      return False
   stem = path.stem
   return stem in {name + suffix for suffix in GUIDE_SUFFIXES} or stem.startswith(f"{name}_mask_")


def check_source(path: str | Path) -> Path:
   """입구에서 경로를 본다. 없거나 PNG 아닌 파일이면 그 자리에서 알린다."""
   source = Path(path)
   if not source.exists():
      raise ArtToolError(f"폴더·파일이 없다 : {source}")
   if source.is_file() and source.suffix.lower() != ".png":
      raise ArtToolError(f"검수는 폴더나 PNG 파일만 받는다 : {source}")
   return source


def load_loose(path: str | Path, skipped: list[str] | None = None) -> list[dict]:
   """낱장 PNG 를 이름순으로 읽는다. 파일 하나를 주면 그 한 장만 본다(가이드 이름이어도 본다).

   skipped 목록을 주면 건너뛴 가이드 파일 이름을 거기 더한다 (보고 `skipped_files`).
   """
   source = Path(path)
   files = [source] if source.is_file() else png_files(source)
   if source.is_dir():
      name = render_name(source)
      guides = [f for f in files if is_guide(f, name)] if name else []
      if guides:
         print(f"가이드 파일 {len(guides)}개를 건너뛴다 : {', '.join(f.name for f in guides)}", file=sys.stderr)
         files = [f for f in files if f not in guides]
         if skipped is not None:
            skipped += [f.name for f in guides]
   if not files:
      raise ArtToolError(f"검수할 PNG 가 하나도 없다 : {source}")
   return [{"where": f.name, "arr": image.load(f)} for f in files]


def where(item: dict) -> str:
   """어느 그림인지 한 줄로. UI 쪽은 이미 이름을 갖고 오므로 그것을 그대로 쓴다."""
   if "where" in item:
      return str(item["where"])
   return f"{item['anim']}/{item['direction']}/{item['frame']}"


def rule_max_colors(frames: list[dict], limit: int) -> dict:
   colors: set = set()
   for item in frames:
      colors |= image.opaque_colors(item["arr"])
   ok = len(colors) <= limit
   return result("max_colors", ok, f"쓴 색 {len(colors)}가지 / 한도 {limit}가지")


def rule_max_colors_each(frames: list[dict], limit: int, background_limit: int | None = None) -> dict:
   """낱장 모드용. 낱장은 한 벌이 아니라 제각각이라 장마다 따로 센다.

   배경으로 본 그림(`item["background"]`)은 `check.background.max_colors` 가 있으면 그 한도로 본다.
   """
   items = []
   for i in frames:
      entry = {"where": where(i), "colors": pixel_check.color_count(i["arr"])}
      if i.get("background"):
         entry["background"] = True
      items.append(entry)
   bad = [e for e in items if e["colors"] > _color_limit(e, limit, background_limit)]
   detail = f"한도 {limit}가지를 넘은 그림 {len(bad)}개"
   if background_limit is not None and any(e.get("background") for e in items):
      detail += f" (배경 그림은 {background_limit}가지)"
   return result("max_colors", not bad, detail, items)


def _color_limit(entry: dict, limit: int, background_limit: int | None) -> int:
   if entry.get("background") and background_limit is not None:
      return background_limit
   return limit


def rule_loose_skip(rule: str) -> dict:
   return result(rule, True, "낱장 모드라 건너뛴다")


def rule_ramp_colors(frames: list[dict], ramps, strict: bool = True, missing_file: str | None = None) -> dict:
   """램프 밖 색. 프로필에 램프 파일이 적혔는데 없으면 그 자체가 실패다."""
   if missing_file:
      return result("ramp_colors", False, f"프로필이 가리키는 램프 파일이 없다 : {missing_file}")
   if ramps is None:
      return result("ramp_colors", True, "프로필에 램프 파일이 없어 건너뛴다")

   strays: dict[tuple, str] = {}
   for item in frames:
      for color in palette.outside_colors(item["arr"], ramps):
         strays.setdefault(color, where(item))

   items = [{"color": palette.to_hex(c), "first": w} for c, w in sorted(strays.items())]
   if not strict:
      return result("ramp_colors", True, f"램프 밖 색 {len(items)}가지 (exact_match 가 꺼져 있어 알리기만 한다)", items)
   return result("ramp_colors", not items, f"램프 밖 색 {len(items)}가지", items)


def rule_alpha(frames: list[dict], mode: str) -> dict:
   if mode != "binary":
      return result("alpha", True, "반투명을 허용하는 프로필이다")
   bad = [where(i) for i in frames if image.has_soft_alpha(i["arr"])]
   return result("alpha", not bad, f"반투명 픽셀이 있는 프레임 {len(bad)}개", bad)


def rule_baseline(frames: list[dict], baseline_y: int, tolerance: int) -> dict:
   bad = []
   for item in frames:
      box = image.bbox(item["arr"])
      if box is None:
         bad.append({"where": where(item), "bottom": None})
         continue
      bottom = box[3] - 1
      if abs(bottom - baseline_y) > tolerance:
         bad.append({"where": where(item), "bottom": bottom})
   return result("baseline", not bad, f"baseline {baseline_y} 에서 벗어난 프레임 {len(bad)}개", bad)


def rule_bbox_drift(frames: list[dict], limit: int) -> dict:
   groups: dict[tuple[str, str], list[tuple[int, int, int]]] = {}
   for item in frames:
      box = image.bbox(item["arr"])
      if box is None:
         continue
      groups.setdefault((item["anim"], item["direction"]), []).append((box[0], box[2], box[1]))

   bad = []
   for (anim, direction), boxes in sorted(groups.items()):
      drift = max(max(v) - min(v) for v in zip(*boxes))
      if drift > limit:
         bad.append({"where": f"{anim}/{direction}", "drift": drift})
   return result("bbox_drift", not bad, f"흔들림이 {limit}픽셀을 넘은 줄 {len(bad)}개", bad)


def _pick_ramps(prof: Profile, override: Path | None = None) -> tuple[object | None, str | None]:
   """램프를 읽는다. 프로필에 적혔는데 파일이 없으면 그 이름을 같이 돌려준다.

   override 는 템플릿이 박은 램프 파일(절대 경로, 설계 9-4 ⓓ). 프로필의 상대경로 규칙을 안 거친다.
   """
   if override is not None:
      if override.is_file():
         return palette.load_ramps(override), None
      return None, str(override)
   ramps_path = prof.ramps_path()
   if ramps_path is None:
      return None, None
   if ramps_path.is_file():
      return palette.load_ramps(ramps_path), None
   return None, str(prof.palette["ramps_file"])


def _report(prof: Profile, rules: list[dict], checked: dict, skipped: list[str]) -> dict:
   failed = [r["rule"] for r in rules if not r["ok"]]
   return {
      "version": VERSION,
      "profile": prof.name,
      "status": "fail" if failed else "ok",
      "checked": checked,
      "failed": failed,
      "skipped": skipped,
      "rules": rules,
   }


# --- 템플릿 겹치기 (설계 7-3 · 9-4 끝) ---


def load_template(path: str | Path) -> dict:
   """`template render` 가 쓴 template.json 을 읽는다. 검증 · 추리기는 템플릿 정본(`template.schema.read_rendered`)이 한다."""
   return schema.read_rendered(path)


def _get_path(node: dict, dotted: str):
   for part in dotted.split("."):
      node = node[part]
   return node


def _set_path(node: dict, dotted: str, value) -> None:
   parts = dotted.split(".")
   for part in parts[:-1]:
      node = node.setdefault(part, {})
   node[parts[-1]] = copy.deepcopy(value)


def apply_template(prof: Profile, tpl: dict) -> tuple[Profile, Path | None]:
   """템플릿 check 칸을 프로필 위에 겹친다 (설계 9-4 끝 「겹치는 차례」).

   - `profile_applied` 면 이미 프로필이 이긴 값이라 그대로 겹친다.
   - 아니면 프로필에도 있는 칸(`style.*` · `palette.*` · `tiles.size`)은 프로필 값을 남긴다. 단 `fixed` 칸만 템플릿 값이 이긴다.
   돌려주는 것 : (겹친 프로필, 템플릿이 박은 절대 경로 램프 파일 또는 None)
   """
   layer = copy.deepcopy(tpl["layer"])
   if not tpl["profile_applied"]:
      keep = {dotted: _get_path(layer, dotted) for dotted in tpl["fixed"]}
      layer.pop("style", None)
      layer.pop("palette", None)
      if isinstance(layer.get("tiles"), dict):
         layer["tiles"].pop("size", None)
      for dotted, value in keep.items():
         _set_path(layer, dotted, value)

   ramps_override = None
   ramps_file = (layer.get("palette") or {}).get("ramps_file") if isinstance(layer.get("palette"), dict) else None
   if ramps_file and Path(str(ramps_file)).is_absolute():
      ramps_override = Path(str(ramps_file))
      layer["palette"].pop("ramps_file")

   where = f"템플릿 {tpl['path']}"
   try:
      reject_unknown(layer, where)
      merged = deep_merge(prof.data, layer)
      validate(merged)
   except ProfileError as exc:
      raise UsageError(f"템플릿 check 칸이 프로필 꼴에 안 맞는다 : {exc}") from exc
   return Profile(merged, prof.source), ramps_override


# --- 진입점 ---


def run(prof: Profile, build_dir: str | Path, no_ramps: bool = False, *, warn: bool = True, mode: str = "auto", template=None) -> dict:
   if mode not in MODES:
      raise UsageError(f"--mode 는 {' · '.join(MODES)} 중 하나다 : {mode}")
   tpl = load_template(template) if template else None
   ramps_override = None
   if tpl is not None:
      prof, ramps_override = apply_template(prof, tpl)
   ctx = {"warn": warn, "mode": mode, "template": tpl, "ramps_override": ramps_override}

   source = check_source(build_dir)
   if is_loose(source):
      if source.is_dir():
         # frames.json 이 없어 낱장으로 본 것인지, 앞 단계가 실패한 것인지 사람이 가릴 수 있게 알린다.
         print(f"frames.json 이 없어 낱장 모드로 본다 — 건너뛴 검사 : {', '.join(LOOSE_SKIPPED)}", file=sys.stderr)
      return run_loose(prof, source, no_ramps, **ctx)
   return run_frames(prof, source, no_ramps, **ctx)


def run_frames(prof: Profile, build_dir: str | Path, no_ramps: bool = False, **ctx) -> dict:
   index, frames = load_frames(prof, build_dir)
   if not frames:
      raise ArtToolError("검수할 프레임이 하나도 없다 (frames.json 의 sheets 가 비었다)")
   _mark_background(prof, frames, ctx.get("mode", "auto"))

   ramps, missing = _pick_ramps(prof, ctx.get("ramps_override"))
   rules = [rule_max_colors(frames, int(prof.check["max_colors"]))]
   if not no_ramps:
      rules.append(rule_ramp_colors(frames, ramps, bool(prof.palette["exact_match"]), missing))
   rules += [
      rule_alpha(frames, str(prof.check["allow_alpha"])),
      rule_baseline(frames, int(prof.canvas["baseline_y"]), int(prof.check["baseline_tolerance"])),
      rule_bbox_drift(frames, int(prof.check["bbox_drift"])),
   ]
   skipped = ["ramp_colors"] if no_ramps else []
   report = _report(prof, rules, {"sheets": len(index["sheets"]), "frames": len(frames)}, skipped)
   groups = _frame_groups(frames)
   return _finish(report, prof, frames, groups, ramps, no_ramps, ctx)


def run_loose(prof: Profile, in_path: str | Path, no_ramps: bool = False, **ctx) -> dict:
   """낱장 검수. 프레임 규격을 모르니 baseline · bbox 흔들림은 안 본다."""
   skipped_files: list[str] = []
   frames = load_loose(in_path, skipped_files)
   _mark_background(prof, frames, ctx.get("mode", "auto"))
   ramps, missing = _pick_ramps(prof, ctx.get("ramps_override"))

   background_limit = prof.check["background"].get("max_colors")
   rules = [rule_max_colors_each(frames, int(prof.check["max_colors"]), background_limit)]
   if not no_ramps:
      rules.append(rule_ramp_colors(frames, ramps, bool(prof.palette["exact_match"]), missing))
   rules.append(rule_alpha(frames, str(prof.check["allow_alpha"])))
   rules += [rule_loose_skip(name) for name in LOOSE_SKIPPED]

   # 실제로 안 돈 규칙을 다 적는다. 프로필에 램프가 없어 안 도는 것은 「설정상 없는 검사」라 안 넣는다.
   skipped = list(LOOSE_SKIPPED) + (["ramp_colors"] if no_ramps else [])
   report = _report(prof, rules, {"mode": "loose", "files": len(frames)}, skipped)
   groups = _loose_groups(frames)
   out = _finish(report, prof, frames, groups, ramps, no_ramps, ctx)
   if skipped_files:
      out["skipped_files"] = skipped_files      # 건너뛴 가이드 파일. 검수에서 빠진 것이 보고에 남는다
   return out


def _mark_background(prof: Profile, frames: list[dict], mode: str) -> None:
   """그림마다 배경인가를 정해 `item["background"]` 에 적는다 (설계 7-1 `check.background`)."""
   node = prof.check["background"]
   for item in frames:
      if mode == "background":
         item["background"] = True
      elif mode == "sprite":
         item["background"] = False
      else:
         item["background"] = bool(node["auto"]) and is_background(item["arr"], int(node["min_side"]))


def _frame_groups(frames: list[dict]) -> dict[str, list[dict]]:
   """프레임 모드 : anim/방향 줄마다 프레임 번호 순."""
   groups: dict[str, list[dict]] = {}
   for item in sorted(frames, key=lambda i: (i["anim"], i["direction"], i["frame"])):
      groups.setdefault(f"{item['anim']}/{item['direction']}", []).append(item)
   return groups


def _loose_groups(frames: list[dict]) -> dict[str, list[dict]]:
   """낱장 모드 : 이름이 <anim>_<방향>_<번호>.png 인 것끼리."""
   by_name = {item["where"]: item for item in frames}
   out = {}
   for (anim, direction), members in loop_check.group_loose(list(by_name)).items():
      out[f"{anim}/{direction}"] = [by_name[name] for _num, name in members]
   return out


# --- 경고 · must 묶기 ---


def _finish(report: dict, prof: Profile, frames: list[dict], groups: dict, ramps, no_ramps: bool, ctx: dict) -> dict:
   """기존 보고에 must_failed · warnings 를 더한다. status 등 기존 칸은 안 건드린다."""
   tpl = ctx.get("template")
   cache: dict = {}
   info: list[dict] = []
   warnings: list[dict] = []
   must_lines = _must(prof, frames, ramps, no_ramps, tpl, cache) if tpl else []
   if ctx.get("warn", True):
      warnings = _warnings(prof, frames, groups, ramps, no_ramps, cache, info)
      if tpl:
         warnings += _template_compare(frames, groups, tpl)

   out = {key: report[key] for key in ("version", "profile", "status")}
   out["must_failed"] = [line["rule"].split(".", 1)[1] for line in must_lines]
   out.update({key: value for key, value in report.items() if key not in out})
   out["warnings"] = must_lines + warnings
   if not ctx.get("warn", True):
      out["warnings_off"] = True
   if info:
      out["info"] = info
   if tpl:
      out["template"] = {
         "path": tpl["path"],
         "name": tpl["name"],
         "kind": tpl["kind"],
         "must": tpl["must"],
         "fixed": tpl["fixed"],
         "profile_applied": tpl["profile_applied"],
      }
   return out


def _measure(cache: dict, item: dict, what: str, fn):
   """한 그림의 재기 값을 한 번만 잰다 (경고와 must 가 같은 값을 쓴다)."""
   key = (id(item), what)
   if key not in cache:
      cache[key] = fn()
   return cache[key]


def _scale_of(prof: Profile, item: dict, cache: dict) -> tuple[dict, dict]:
   cfg = prof.warn("integer_scale")
   scale = _measure(cache, item, "scale", lambda: scale_check.measure_scale(item["arr"], item["background"], float(cfg["block_ratio"])))
   smooth = _measure(cache, item, "smooth", lambda: scale_check.measure_smooth(item["arr"]))
   return scale, smooth


def _entry(item: dict, why: list[str], **extra) -> dict:
   entry = {"where": where(item), **({"why": why} if why else {}), **extra}
   if item.get("background"):
      entry["background"] = True
   return entry


def _per_image(rule: str, items: list[dict], what: str) -> list[dict]:
   if not items:
      return []
   return [warning(rule, f"{what} 그림 {len(items)}장", items)]


def _colors_of(item: dict, cache: dict) -> int:
   """불투명 색 가짓수. 한 그림에 한 번만 센다 (max_colors · color_cap · near_colors · 템플릿 대조가 같이 쓴다)."""
   return _measure(cache, item, "colors", lambda: pixel_check.color_count(item["arr"]))


def _near_of(prof: Profile, item: dict, cache: dict):
   """비슷한 색 쌍. 색이 `NEAR_MAX_COLORS` 를 넘으면 None (건너뜀)."""
   if _colors_of(item, cache) > pixel_check.NEAR_MAX_COLORS:
      return None
   delta = int(prof.warn("near_colors")["max_delta"])
   return _measure(cache, item, "near", lambda: pixel_check.measure_near_colors(item["arr"], delta))


def _measure_ahead(prof: Profile, frames: list[dict], cache: dict) -> None:
   """켜진 그림별 검사를 그림 차례로 미리 잰다. 판이 길면(`PROGRESS_EVERY` 초 넘게) stderr 에 진행을 알린다.

   재는 값은 cache 에 들어가고 판정 쪽이 그대로 꺼내 쓴다 — 셈이 두 번 돌지 않는다.
   """
   on = {rule: prof.warn(rule)["enabled"] for rule in ("integer_scale", "outline", "isolated", "color_cap", "near_colors")}
   start = last = time.monotonic()
   for index, item in enumerate(frames, 1):
      if on["integer_scale"]:
         _scale_of(prof, item, cache)
      if on["outline"] and not item["background"]:
         _outline_of(prof, item, cache)
      if on["isolated"]:
         _measure(cache, item, "isolated", lambda: pixel_check.measure_isolated(item["arr"]))
      if on["color_cap"] or on["near_colors"]:
         _colors_of(item, cache)
      if on["near_colors"]:
         _near_of(prof, item, cache)
      now = time.monotonic()
      if now - last >= PROGRESS_EVERY and index < len(frames):
         print(f"경고 검사 {index}/{len(frames)} 장 ({now - start:.0f}초) — {where(item)}", file=sys.stderr, flush=True)
         last = now


def _outline_of(prof: Profile, item: dict, cache: dict) -> dict:
   cfg = prof.warn("outline")
   return _measure(cache, item, "outline", lambda: outline_check.measure_outline(item["arr"], str(prof.style["light"]), float(cfg["black_ratio"])))


def _warnings(prof: Profile, frames: list[dict], groups: dict, ramps, no_ramps: bool, cache: dict, info: list) -> list[dict]:
   out: list[dict] = []
   style = prof.style
   _measure_ahead(prof, frames, cache)

   if prof.warn("integer_scale")["enabled"]:
      cfg = prof.warn("integer_scale")
      items = []
      for item in frames:
         scale, smooth = _scale_of(prof, item, cache)
         why = scale_check.judge_integer_scale(scale, smooth, cfg, int(style["scale"]))
         if why:
            items.append(_entry(item, why, scales=scale["scales"], smooth=smooth["ratio"]))
      out += _per_image("integer_scale", items, "도트 굵기 · 부드러운 확대가 걸린")

   if prof.warn("outline")["enabled"]:
      out += _outline_warnings(prof, frames, info, cache)

   if prof.warn("isolated")["enabled"]:
      cfg = prof.warn("isolated")
      items = []
      for item in frames:
         m = _measure(cache, item, "isolated", lambda: pixel_check.measure_isolated(item["arr"]))
         why = pixel_check.judge_isolated(m, cfg)
         if why:
            items.append(_entry(item, why, ratio=m["ratio"], points=m["points"]))
      out += _per_image("isolated", items, "외톨이 픽셀이 많은")

   if prof.warn("color_cap")["enabled"]:
      table = prof.color_cap_table()
      bg_cap = int(prof.check["background"]["color_cap"])
      items = []
      for item in frames:
         m = {"size": long_side(item["arr"]), "colors": _colors_of(item, cache)}
         cap = bg_cap if item["background"] else pixel_check.cap_for(m["size"], table)[1]
         why = pixel_check.judge_color_cap(m, cap)
         if why:
            items.append(_entry(item, why, size=m["size"], colors=m["colors"], cap=cap))
      out += _per_image("color_cap", items, "권장 색 수를 넘은")

   if prof.warn("near_colors")["enabled"]:
      min_pairs = int(prof.warn("near_colors")["min_pairs"])
      items, too_many = [], []
      for item in frames:
         pairs = _near_of(prof, item, cache)
         if pairs is None:
            too_many.append({"where": where(item), "colors": _colors_of(item, cache)})
            continue
         why = pixel_check.judge_near_colors(pairs, min_pairs)
         if why:
            items.append(_entry(item, why, count=len(pairs), pairs=pairs[: pixel_check.MAX_PAIRS]))
      out += _per_image("near_colors", items, "비슷한 색 쌍이 있는")
      if too_many:
         info.append({"rule": "near_colors.skipped",
                      "detail": f"색이 {pixel_check.NEAR_MAX_COLORS}가지를 넘어 비슷한 색 쌍을 안 센 그림 {len(too_many)}장 (도트가 아닌 그림일 수 있다)",
                      "items": too_many})

   if prof.warn("ramp_shape")["enabled"] and ramps is not None and not no_ramps:
      out += _ramp_warnings(prof, ramps)

   if prof.warn("loop_seam")["enabled"]:
      out += _loop_warnings(prof, groups)
   return out


def _outline_warnings(prof: Profile, frames: list[dict], info: list, cache: dict) -> list[dict]:
   want = str(prof.style["outline"])
   items, seen, notes = [], [], []
   for item in frames:
      if item["background"]:
         continue   # 배경 그림은 가장자리가 없다
      m = _outline_of(prof, item, cache)
      why = outline_check.judge_outline(m, want)
      if why:
         items.append(_entry(item, why, verdict=m["verdict"], black=m["black_ratio"], dark=m["dark_ratio"], lit=m["lit_ratio"]))
      if want == "unset" and m["verdict"] is not None:
         seen.append({"where": where(item), "verdict": m["verdict"]})
      note = outline_check.small_note(m, want)
      if note:
         notes.append({"where": where(item), "note": note})
   if seen:
      info.append({"rule": "outline", "detail": "style.outline 이 unset 이라 판정만 적는다", "items": seen})
   if notes:
      info.append({"rule": "outline.small", "detail": "작은 그림의 외곽선 몫", "items": notes})
   return _per_image("outline", items, "외곽선 방식이 다른")


def _ramp_warnings(prof: Profile, ramps) -> list[dict]:
   cfg = prof.warn("ramp_shape")
   materials = prof.style.get("materials") or {}
   items = []
   for name in ramps.names():
      m = ramp_check.measure_ramp(ramps.ramp(name), ramps.outline)
      why = ramp_check.judge_ramp(m, cfg, materials.get(name))
      if why:
         items.append({"ramp": name, "why": why, "steps": m["steps"], "padded": m["padded"], "hue_steps": m["hue_steps"]})
   if not items:
      return []
   return [warning("ramp_shape", f"모양이 걸린 램프 {len(items)}줄", items)]


def _loop_warnings(prof: Profile, groups: dict) -> list[dict]:
   cfg = prof.warn("loop_seam")
   anims = set(cfg["anims"])
   items = []
   for key, members in groups.items():
      if key.split("/", 1)[0] not in anims:
         continue
      m = loop_check.measure_loop([i["arr"] for i in members])
      if m is None:
         continue
      why = loop_check.judge_loop(m, float(cfg["k"]))
      if why:
         items.append({"where": key, "why": why, **m})
   if not items:
      return []
   return [warning("loop_seam", f"루프 이음새가 걸린 줄 {len(items)}개", items)]


def frame_counts(want: int, data: dict) -> set[int]:
   """템플릿 대조에서 받아 주는 프레임 수.

   cycle 템플릿에 재생 차례(order)가 있으면 (예 : idle 1-2-3-2) 그림은 서로 다른 장 수만큼(3)만
   그려도 되고, 재생 차례대로 다 펼쳐(4) 내도 된다 — 둘 다 받는다.
   """
   order = (data.get("values") or {}).get("order") if data.get("kind") == "cycle" else None
   if isinstance(order, list) and order:
      return {want, len(set(order))}
   return {want}


def _template_compare(frames: list[dict], groups: dict, tpl: dict) -> list[dict]:
   """템플릿 대조 경고 template.frames · template.size · template.colors (설계 7-3)."""
   out: list[dict] = []
   compare = tpl["compare"]
   if "frames" in compare:
      ok = frame_counts(int(compare["frames"]), tpl.get("data") or {})
      rows = {key: len(members) for key, members in groups.items()} or {"(전체)": len(frames)}
      bad = [{"where": key, "frames": count} for key, count in rows.items() if count not in ok]
      if bad:
         shown = " 또는 ".join(str(n) for n in sorted(ok))
         out.append(warning("template.frames", f"프레임 수가 템플릿 {shown}장과 다른 줄 {len(bad)}개", bad))
   if "size" in compare:
      want_w, want_h = (int(v) for v in compare["size"])
      bad = [_entry(i, [], size=list(image.size(i["arr"]))) for i in frames if image.size(i["arr"]) != (want_w, want_h)]
      if bad:
         out.append(warning("template.size", f"크기가 템플릿 {want_w}x{want_h} 와 다른 그림 {len(bad)}장", bad))
   if "colors" in compare:
      want = int(compare["colors"])
      counted = [(i, pixel_check.color_count(i["arr"])) for i in frames]
      bad = [_entry(i, [], colors=n) for i, n in counted if n > want]
      if bad:
         out.append(warning("template.colors", f"색 수가 템플릿 {want}가지를 넘은 그림 {len(bad)}장", bad))
   return out


def _must(prof: Profile, frames: list[dict], ramps, no_ramps: bool, tpl: dict, cache: dict) -> list[dict]:
   """템플릿 최소 규칙 (설계 9-4 끝). 어긴 낱말마다 `"must": true` 경고 한 줄. `--no-warn` 으로 안 꺼진다.

   이미 실패 규칙이 같은 것을 보고 있으면(반투명 binary · 램프 정확일치) 두 번 세지 않는다.
   """
   out: list[dict] = []
   words = tpl["must"]

   if "canvas" in words:
      sizes = _canvas_sizes(prof, tpl)
      if sizes:
         bad = [_entry(i, [], size=list(image.size(i["arr"]))) for i in frames if image.size(i["arr"]) not in sizes]
         if bad:
            shown = " · ".join(f"{w}x{h}" for w, h in sorted(sizes))
            out.append(warning("must.canvas", f"캔버스 크기가 {shown} 가 아닌 그림 {len(bad)}장", bad, must=True))

   if "alpha" in words and str(prof.check["allow_alpha"]) != "binary":
      bad = [_entry(i, []) for i in frames if image.has_soft_alpha(i["arr"])]
      if bad:
         out.append(warning("must.alpha", f"반투명 칸이 있는 그림 {len(bad)}장", bad, must=True))

   if "scale" in words:
      cfg = prof.warn("integer_scale")
      bad = []
      for item in frames:
         scale, smooth = _scale_of(prof, item, cache)
         why = []
         if scale["mixed"]:
            why.append(f"도트 굵기 섞임 ×{' · ×'.join(map(str, scale['scales']))}")
         if scale_check.smooth_hit(smooth, cfg):
            why.append(f"부드러운 확대 흔적 {smooth['ratio']:.3f}")
         if why:
            bad.append(_entry(item, why))
      if bad:
         out.append(warning("must.scale", f"정수 배율이 깨진 그림 {len(bad)}장", bad, must=True))

   if "palette" in words and ramps is not None:
      covered = not no_ramps and bool(prof.palette["exact_match"])
      if not covered:
         strays: dict = {}
         for item in frames:
            for color in palette.outside_colors(item["arr"], ramps):
               strays.setdefault(color, where(item))
         if strays:
            items = [{"color": palette.to_hex(c), "first": w} for c, w in sorted(strays.items())]
            out.append(warning("must.palette", f"팔레트 밖 색 {len(items)}가지", items, must=True))
   return out


def _canvas_sizes(prof: Profile, tpl: dict) -> set[tuple[int, int]]:
   """must.canvas 가 받는 크기들. icon_set 은 ui.icon.sizes 정사각형, 나머지는 템플릿의 고른 크기."""
   if tpl["kind"] == "icon_set":
      return {(int(s), int(s)) for s in prof.ui["icon"]["sizes"]}
   if tpl["size"] is None:
      return set()
   return {tpl["size"]}
