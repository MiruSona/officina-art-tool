"""`template list · show · render` 명령 (설계 8-3 · 9-4 · 10-3, 명령 약속 12-1).

`run(args)` 가 `args.sub` 로 셋을 나눈다. 돌려주는 사전의 `status` 는 ok · warn(경고가 있을 때).

화풍 입히기(`--profile`, 9-4)
- ⓐ 견본 띠 : `_preview.png` 아래에 그 게임의 램프를 한 줄씩. 1배 가이드에는 안 넣는다.
- ⓑ 프롬프트 빈칸 `{palette}` · `{outline}` · `{light}` 를 채운다. 채울 값이 없으면 그 빈칸이 든 마디(쉼표 사이)를 뺀다.
- ⓒ `palette_ramp` : 프로필에 램프가 있고 `--base` 가 없으면 그 램프를 견본으로 내고 모양을 재 본다.
  `--base` 가 있으면 프로필 팔레트의 `ramp_len` · `hue_step` 으로 새 램프를 만든다.
- ⓓ `template.json` 의 `check` 에 `palette.ramps_file`(절대 경로) · `palette.outline` · `style` 을 박는다.

겹치는 차례 : 템플릿 값 → 프로필 값 → `fixed` 칸만 다시 템플릿. 프로필을 줬으면 `"profile_applied": true`.
"""

from __future__ import annotations

import copy
import re
from pathlib import Path

from .. import image, layerset, paths
from ..checks import ramp as ramp_check
from ..draw import shapes
from ..errors import ArtToolError, UsageError
from ..jsonio import read_json, write_json
from ..palette import parse_hex, ramps_from_data, to_hex
from ..paths import resolve_root, safe_join
from ..profile import deep_merge, load_profile_args
from . import TemplateError, guide, schema
from .kinds import KINDS, Ctx, handler, resolve_values

VERSION = 1
TEMPLATE_FILE = "template.json"
SPLIT_FILE = "split.json"
PALETTE_SHOWN = 8

OUTLINE_TEXT = {
   "none": "no outline",
   "black": "black 1px outline",
   "solid": "single dark color outline (not black), same color all around",
   "selout": "selective outline, darker shade of each fill color",
   "selout+light": "selective outline, darker shade of each fill color, lighter on the lit side",
}
LIGHT_TEXT = {"top_left": "light from top-left", "top": "light from top", "top_right": "light from top-right"}


def run(args) -> dict:
   sub = getattr(args, "sub", None)
   if sub == "list":
      return list_templates(getattr(args, "kind", None))
   if sub == "show":
      shown, warnings, _ = build(args.name, getattr(args, "size", None), _preset(args), _profile(args), getattr(args, "base", None), _material(args))
      return {**shown, "status": "warn" if warnings else "ok", "warnings": warnings}
   if sub == "render":
      return render(args)
   raise UsageError(f"template 하위 명령은 list · show · render 다 : {sub}")


def _material(args) -> str | None:
   return getattr(args, "material", None) or None


def _preset(args) -> str | None:
   """`--material` 은 palette 템플릿의 재질 프리셋 이름이다(cloth · stone · metal …). `--preset` 과 같은 칸이라 둘이 다르면 거절."""
   preset, material = getattr(args, "preset", None), _material(args)
   if preset and material and preset != material:
      raise UsageError(f"--preset {preset} 과 --material {material} 이 다르다. 하나만 준다")
   return preset or material


def _profile(args):
   """`--profile` 을 줬을 때만 화풍을 입힌다. 안 주면 None — 기본값 프로필로 템플릿 값을 덮지 않는다."""
   if not getattr(args, "profile", None):
      return None
   return load_profile_args(args)


# ── list ─────────────────────────────────────────────


def list_templates(kind: str | None = None) -> dict:
   if kind and kind not in KINDS:
      raise UsageError(f"--kind 는 {' · '.join(KINDS)} 중 하나다 : {kind}")
   rows = []
   for tpl in schema.list_all():
      if kind and tpl["kind"] != kind:
         continue
      rows.append({
         "name": tpl["name"],
         "kind": tpl["kind"],
         "title": tpl["title"],
         "sizes": tpl["sizes"],
         "presets": schema.preset_names(tpl),
      })
   return {"status": "ok", "dir": str(schema.templates_dir()), "count": len(rows), "templates": rows}


# ── 크기 · 팔레트 ─────────────────────────────────────


def _profile_sizes(kind_name: str, prof) -> list[tuple[int, int]]:
   """프로필이 정하는 크기. 타일 크기 · 아이콘 크기 · 9조각 원본 크기는 게임 전체의 결정이라 프로필이 이긴다."""
   if prof is None:
      return []
   if kind_name == "tile":
      side = int(prof.tiles["size"])
      return [(side, side)]
   if kind_name == "icon_set":
      return [(int(s), int(s)) for s in prof.ui["icon"]["sizes"]]
   if kind_name == "ui9":
      return [prof.ui_frame_size()]
   return []


def _pick_size(tpl: dict, size_text: str | None, prof) -> tuple[int, int]:
   own = schema.size_list(tpl)
   from_prof = _profile_sizes(tpl["kind"], prof)
   allowed = own + [s for s in from_prof if s not in own]
   if not size_text:
      return from_prof[0] if from_prof else own[0]
   size = schema.parse_size(size_text)
   if size not in allowed:
      shown = ", ".join(f"{w}x{h}" for w, h in allowed)
      raise UsageError(f"{tpl['name']} 가 받는 크기가 아니다 : {size[0]}x{size[1]} (받는 것 : {shown})")
   return size


def palette_info(prof, warnings: list) -> dict | None:
   """프로필의 램프 파일. 없으면 None. 경로는 있는데 파일이 없으면 경고 하나."""
   if prof is None:
      return None
   path = prof.ramps_path()
   if path is None:
      return None
   if not path.is_file():
      warnings.append(_warn("template.palette_missing", f"프로필의 램프 파일이 없어 화풍 색을 건너뛴다 : {path}"))
      return None
   raw = read_json(path)
   ramps = ramps_from_data(raw, path)
   info = {
      "ramps_file": str(path.resolve()),
      "ramps": {name: [to_hex(c) for c in ramps.ramp(name)] for name in ramps.names()},
      "outline": to_hex(ramps.outline) if ramps.outline else prof.palette.get("outline"),
      "ramp_len": ramps.ramp_len,
      "hue_step": raw.get("hue_step"),
   }
   usage = raw.get("usage")
   if isinstance(usage, dict) and usage:
      # style extract 가 몫(쓰인 비율)을 적어 두면 몫 큰 순으로 고른다
      ranked = sorted(usage.items(), key=lambda kv: (-float(kv[1]), str(kv[0])))
      info["prompt_colors"] = [str(k).upper() for k, _ in ranked[:PALETTE_SHOWN]]
   else:
      info["prompt_colors"] = [colors[len(colors) // 2] for colors in info["ramps"].values()]
   return info


def _warn(rule: str, detail: str, items=None) -> dict:
   return {"rule": rule, "ok": False, "detail": detail, "items": items or []}


# ── check 칸 겹치기 (9-4 ⓓ · 끝) ──────────────────────


def _set_path(node: dict, dotted: str, value) -> None:
   parts = dotted.split(".")
   for part in parts[:-1]:
      node = node.setdefault(part, {})
   node[parts[-1]] = copy.deepcopy(value)


def build_check(tpl: dict, size, frames: int | None, values: dict, prof, palette: dict | None) -> dict:
   """템플릿 check → 프로필 값 → fixed 칸만 다시 템플릿. 대조 값 frames · size · colors 를 채운다."""
   check = copy.deepcopy(tpl.get("check") or {})
   if frames is not None:
      check["frames"] = frames
   check["size"] = [size[0], size[1]]
   if "colors" in values and "colors" not in check:
      check["colors"] = values["colors"]
   if prof is None:
      return check

   style = copy.deepcopy(prof.style)
   if style.get("outline") == "unset":
      # 「아직 안 정함」은 값이 아니다 — 템플릿 값을 남긴다
      style.pop("outline")
   check["style"] = deep_merge(check.get("style") or {}, style)
   if palette is not None:
      node = check.setdefault("palette", {})
      node["ramps_file"] = palette["ramps_file"]
      node["outline"] = prof.palette.get("outline")
   if tpl["kind"] == "tile" or "tiles" in check:
      check.setdefault("tiles", {})["size"] = int(prof.tiles["size"])
   if tpl["kind"] == "icon_set":
      check.setdefault("ui", {}).setdefault("icon", {})["sizes"] = list(prof.ui["icon"]["sizes"])
   for dotted in tpl.get("fixed", []):
      _set_path(check, dotted, schema._dig(tpl["check"], dotted))
   return check


# ── 프롬프트 (9-4 ⓑ) ─────────────────────────────────


class _Strict(dict):
   def __missing__(self, key):
      raise TemplateError(f"프롬프트 빈칸 {{{key}}} 를 채울 값이 없다")


def fill_prompt(text: str, fields: dict, style: dict, palette: dict | None) -> str:
   outline = OUTLINE_TEXT.get(style.get("outline", "unset"))
   light = LIGHT_TEXT.get(style.get("light", "top_left"))
   blanks = {"palette": " ".join(palette["prompt_colors"]) if palette else None, "outline": outline, "light": light}
   kept = []
   for clause in text.split(", "):
      if any(f"{{{key}}}" in clause and value is None for key, value in blanks.items()):
         continue
      kept.append(clause)
   table = _Strict({**fields, **{k: v for k, v in blanks.items() if v is not None}})
   try:
      return ", ".join(kept).format_map(table)
   except (ValueError, IndexError) as exc:
      raise TemplateError(f"프롬프트 꼴이 잘못됐다 : {text} - {exc}") from exc


def fill_step(text: str, fields: dict) -> str:
   """그리는 순서 한 줄의 빈칸 `{이름}` 을 셈 값으로 채운다 (예 `--border {border_text}` → `--border 14,20,14,12`).

   모르는 이름은 그대로 둔다 — 순서 글은 사람이 읽는 것이라 프롬프트처럼 거절하지 않는다.
   """
   return re.sub(r"\{(\w+)\}", lambda m: str(fields[m.group(1)]) if m.group(1) in fields else m.group(0), text)


def _scalars(node: dict) -> dict:
   return {k: v for k, v in node.items() if isinstance(v, (int, float, str)) and not isinstance(v, bool)}


# ── show ─────────────────────────────────────────────


def _ramp_report(ramps: dict[str, list[str]], outline: str | None = None) -> dict:
   """프로필 램프의 모양을 잰다 — 검사 ⑥ ramp_shape 의 재기 함수 그대로 (단 수 · 채운 칸 · 밝기 오름 · 칸마다 색조 차)."""
   edge = parse_hex(outline) if outline else None
   return {name: ramp_check.measure_ramp([parse_hex(h) for h in colors], edge) for name, colors in ramps.items()}


def build(name: str, size_text: str | None, preset: str | None, prof, base: str | None = None,
          material: str | None = None) -> tuple[dict, list, dict]:
   """템플릿 하나를 크기 · 프리셋 · 프로필에 맞춰 셈한다. (show 사전, 경고, 그리기 재료).

   base · material 은 palette 템플릿에만 준다(`--base #hex` · `--material 재질`). material 은 부르는 쪽이 이미 preset 에 넣었다.
   """
   warnings: list = []
   loaded = schema.load(name)
   if (base or material) and loaded["kind"] != "palette":
      raise UsageError(f"--base · --material 은 palette 템플릿에만 준다 : {loaded['name']} 은 {loaded['kind']}")
   if base:
      try:
         parse_hex(base)
      except ArtToolError as exc:
         raise UsageError(f"--base 는 #RRGGBB 다 : {base}") from exc
   if preset is None and loaded.get("default_preset") is not None:
      # 크기에 따른 기본 프리셋 (예 char_small : 작은 캔버스 · 세로로 긴 캔버스는 sd)
      preset = schema.default_preset(loaded, _pick_size(loaded, size_text, prof))
   tpl, chosen = schema.apply_preset(loaded, preset)
   kind = handler(tpl["kind"])
   size = _pick_size(tpl, size_text, prof)
   values = resolve_values(tpl.get("values") or {}, size)
   kind.check_values(values, size, tpl, loaded["_source"])
   palette = palette_info(prof, warnings)

   extra = {}
   profile_ramps = kind.name == "palette" and palette is not None and not base
   if kind.name == "palette" and not profile_ramps:
      extra = {"base": base}
      if palette is not None:
         extra.update({"steps": palette["ramp_len"], "hue_step": palette["hue_step"]})
   ctx = Ctx(tpl, size, values, prof, extra)
   if profile_ramps:
      calc = {"mode": "profile", "ramps": palette["ramps"], "report": _ramp_report(palette["ramps"], palette.get("outline"))}
   else:
      calc = kind.compute(ctx)
      if kind.name == "palette":
         calc = {**calc, "mode": "base", "ramp": [to_hex(c) for c in calc["ramp"]]}
   frames = kind.frame_count(ctx)
   check = build_check(tpl, size, frames, values, prof, palette)

   style = {"outline": "unset", "light": "top_left", **(check.get("style") or {})}
   fields = {**_scalars(values), **_scalars(calc), "w": size[0], "h": size[1]}
   if frames is not None:
      fields["frames"] = frames
   prompt = fill_prompt(tpl["prompt"], fields, style, palette)

   if kind.name == "tile" and prof is not None and size[0] != int(prof.tiles["size"]):
      warnings.append(_warn("template.tile_size", f"고른 크기 {size[0]} 가 프로필 tiles.size {prof.tiles['size']} 와 다르다"))

   shown = {
      "version": VERSION,
      "name": tpl["name"],
      "kind": tpl["kind"],
      "title": tpl["title"],
      "size": [size[0], size[1]],
      "preset": chosen,
      "presets": schema.preset_names(loaded),
      "values": values,
      "lines": calc,
      "frames": frames,
      "frame_ms": values.get("frame_ms"),
      "prompt": prompt,
      "steps": [fill_step(step, fields) for step in tpl["steps"]],
      "check": check,
      "fixed": list(tpl.get("fixed", [])),
      "must": schema.effective_must(tpl),
      "layers": copy.deepcopy(tpl.get("layers") or []),
      "profile_applied": prof is not None,
      "profile": prof.name if prof is not None else None,
      "palette": palette,
      "sources": list(tpl["sources"]),
      "template_file": loaded["_source"],
   }
   return shown, warnings, {"tpl": tpl, "kind": kind, "ctx": ctx, "calc": calc, "palette": palette}


# ── render ───────────────────────────────────────────


def render(args) -> dict:
   prof = _profile(args)
   shown, warnings, made = build(args.name, args.size, _preset(args), prof, getattr(args, "base", None), _material(args))
   kind, ctx, calc, palette = made["kind"], made["ctx"], made["calc"], made["palette"]
   size = ctx.size
   scale = getattr(args, "scale", None) or guide.auto_scale(size)
   if scale < 1 or scale > 64:
      raise UsageError(f"--scale 은 1 ~ 64 다 : {scale}")

   root = resolve_root(Path(args.out_dir))
   name = shown["name"]
   files: list[str] = []
   over = getattr(args, "over", None)
   _guard_sources(root, name, shown["template_file"], over)
   old_set = _existing_set(root, shown) if kind.name != "palette" else None

   def save_png(file_name: str, arr) -> None:
      path = safe_join(root, file_name)
      image.save(path, arr)
      files.append(str(path))

   band = None
   if palette is not None:
      band = guide.swatch_band([_rgb_list(c) for c in palette["ramps"].values()], max(8, scale * 2))

   if kind.name == "palette":
      _render_palette(shown, calc, prof, scale, root, files, save_png)
   else:
      guide_arr = guide.paint(kind.guide(ctx, calc))
      save_png(f"{name}_guide.png", guide_arr)
      frames = kind.frames(ctx, calc)
      for i, frame in enumerate(frames):
         save_png(f"{name}_f{i:02d}.png", frame)
      masks = _write_masks(shown, kind, ctx, calc, save_png, warnings)
      if kind.name == "parts":
         _write_split(shown, masks, root, files)
      preview = _preview(kind.preview, guide_arr, frames, scale)
      preview = _label_preview(preview, kind, calc, shown, frames, scale, warnings)
      if band is not None:
         preview = guide.vstack(preview, band, scale * guide.GAP)
      save_png(f"{name}_preview.png", preview)
      # 이미 그린 묶음 폴더에 다시 render 해도 그림 목록(items)을 지우지 않는다 (리뷰 R2-M2)
      # 옛 묶음의 meta(맨 위 · 겹)도 이어 쓴다 — version 1 고정으로 덮으면 meta 를 잃는다
      path = layerset.save(root, layerset.carry_meta(old_set, layerset.from_dict({
         "version": 1, "canvas": [size[0], size[1]], "layers": shown["layers"],
         "items": list(old_set.items) if old_set else [], "template": name,
      })))
      files.append(str(path))
      if over:
         picture = image.load(over)
         if image.size(picture) != size:
            pw, ph = image.size(picture)
            warnings.append(_warn(
               "template.over_size",
               f"--over 그림 {pw}x{ph} 이 템플릿 크기 {size[0]}x{size[1]} 와 다르다 — 아래 가운데에 맞춰 "
               f"{max(pw, size[0])}x{max(ph, size[1])} 판에 얹었다",
               [str(over)],
            ))
         save_png(f"{name}_over.png", guide.over(picture, guide_arr, scale))

   template_path = safe_join(root, TEMPLATE_FILE)
   write_json(template_path, shown)
   files.append(str(template_path))
   return {
      "status": "warn" if warnings else "ok",
      "name": name,
      "size": shown["size"],
      "preset": shown["preset"],
      "scale": scale,
      "out": str(root),
      "template": str(template_path),
      "profile_applied": shown["profile_applied"],
      "files": files,
      "warnings": warnings,
   }


def _guard_sources(root: Path, name: str, template_file: str, over) -> None:
   """render 가 쓸 파일이 원본을 덮지 않게 막는다 (리뷰 R2-M1). 원본 보호 공용 함수 `paths.guard_overwrite` 를 쓴다.

   - 쓸 고정 이름 : template.json · layers.json · split.json — 템플릿 원본 · `--over` 그림과 같으면 거절.
   - `--over` 그림이 이 폴더의 `<name>_*.png` 이면 render 가 쓰는 그림 이름과 겹칠 수 있어 그것도 쓸 자리로 센다.
   """
   writes = [root / TEMPLATE_FILE, root / layerset.FILE_NAME, root / SPLIT_FILE]
   same_folder = bool(over) and paths.same_key(Path(over).parent) == paths.same_key(root)
   if same_folder and Path(over).name.lower().startswith(f"{name.lower()}_"):
      writes.append(root / Path(over).name)
   paths.guard_overwrite(writes, [template_file, over], what="--out")


def _existing_set(root: Path, shown: dict) -> layerset.LayerSet | None:
   """폴더에 layers.json 이 이미 있으면 그 묶음(그림 목록 · meta 를 이어 쓰려고). 겹 목록 · 크기가 다르면 거절 — Canvas.save 와 같은 규칙.

   겹 meta 는 견주지 않는다 — render 는 meta 를 모르니, 옛 겹 meta 는 다르다고 거절하지 않고 이어 쓴다.
   """
   existing = root / layerset.FILE_NAME
   if not existing.is_file():
      return None
   old = layerset.load(existing)
   # render 는 files 무늬를 모른다. 다시 구우면 무늬를 조용히 잃으니 split 처럼 거절한다 (지원 안 함).
   patterned = [l.name for l in old.layers if l.files is not None]
   if patterned:
      raise UsageError(f"files 무늬를 쓰는 묶음({', '.join(patterned)})에는 template render 를 다시 못 한다. 다른 폴더에 render 한다 : {existing}")
   new = layerset.from_dict({"version": 1, "canvas": shown["size"], "layers": shown["layers"]}, "(render)")
   def bare(rows):
      return [{k: v for k, v in l.to_dict().items() if k != "meta"} for l in rows]
   same = old.canvas == new.canvas and bare(old.layers) == bare(new.layers)
   if not same:
      if not old.items:
         return None     # 그림이 없는 밑판 폴더 — 새 겹 목록으로 다시 써도 잃는 것이 없다
      raise UsageError(f"폴더의 layers.json 과 겹 목록 · 크기가 다르고 그린 그림({', '.join(old.items)})이 있다. 다른 폴더에 render 한다 : {existing}")
   return old


def _rgb_list(hexes: list[str]) -> list[tuple[int, int, int]]:
   return [tuple(int(h[i : i + 2], 16) for i in (1, 3, 5)) for h in hexes]


def _preview(mode: str, guide_arr, frames: list, scale: int):
   if mode == "frames" and frames:
      return guide.hstack([guide.enlarge(f, scale) for f in frames], scale * guide.GAP)
   if mode == "overlay":
      return guide.enlarge(guide.overlay(guide_arr, frames), scale)
   if mode == "tile2x2":
      return guide.enlarge(guide.tile2x2(guide_arr), scale)
   return guide.enlarge(guide_arr, scale)


def _frame_names(shown: dict, count: int) -> list[str]:
   phases = shown["values"].get("phases")
   if isinstance(phases, list) and len(phases) == count and all(isinstance(p, str) for p in phases):
      return [f"{i} {p}" for i, p in enumerate(phases)]
   return [f"f{i:02d}" for i in range(count)]


def _label_preview(preview, kind, calc: dict, shown: dict, frames: list, scale: int, warnings: list):
   """미리보기에 이름표를 붙인다 — 오른쪽에 줄 · 상자 이름, frames 판이면 아래에 프레임 번호. 글꼴이 없으면 빼고 경고."""
   rows = guide.marks(kind.labels, calc, scale)
   under = kind.preview == "frames" and bool(frames)
   if not rows and not under:
      return preview
   if not image.has_label_font():
      warnings.append(_warn("template.label_font", f"딱지 글꼴이 없어 미리보기 이름표를 뺐다 (설치가 깨졌다) : {image.LABEL_FONT}"))
      return preview
   if under:
      step = shown["size"][0] * scale + scale * guide.GAP
      preview = guide.label_under(preview, _frame_names(shown, len(frames)), [i * step for i in range(len(frames))])
   return guide.label_side(preview, rows)


def _write_masks(shown: dict, kind, ctx, calc, save_png, warnings: list) -> dict[str, str]:
   """겹별 마스크(흰 = 그릴 자리). 템플릿 layers 에 없는 이름 · 빈 마스크는 안 쓴다."""
   if not kind.mask_files:
      return {}
   names = [row["name"] for row in shown["layers"]]
   written = {}
   for layer, mask in kind.masks(ctx, calc).items():
      if layer not in names:
         warnings.append(_warn("template.mask_layer", f"처리기 마스크 {layer} 가 템플릿 layers 에 없어 건너뛴다"))
         continue
      if not mask.any():
         # 그릴 자리가 0칸 — 이 크기 · 프리셋 비율이 너무 작다 (리뷰 R2-H1). 마스크를 안 쓰고 알린다
         warnings.append(_warn("template.mask_empty", f"겹 {layer} 의 마스크가 비었다 (크기 {ctx.w}x{ctx.h} 에서 자리가 0칸)", [layer]))
         continue
      file_name = f"{shown['name']}_mask_{layer}.png"
      save_png(file_name, shapes.to_image(mask, "#FFFFFF"))
      written[layer] = file_name
   return written


def _write_split(shown: dict, masks: dict[str, str], root: Path, files: list) -> None:
   """`split` 이 그대로 읽는 나누기 표 초안. 마스크가 겹 주인을 정하고, 마스크 밖은 default 겹으로."""
   names = [row["name"] for row in shown["layers"]]
   data = {
      "version": 1,
      "layers": names,
      "default": "body" if "body" in names else names[0],
      "masks": masks,
   }
   path = safe_join(root, SPLIT_FILE)
   write_json(path, data)
   files.append(str(path))


def _render_palette(shown: dict, calc: dict, prof, scale: int, root: Path, files: list, save_png) -> None:
   cell = max(8, shown["size"][0])

   def rows(names: list[str]) -> list:
      # 견본 띠 한 줄 = 램프 하나. 줄 가운데 높이에 램프 이름
      if not image.has_label_font():
         return []
      return [(1 + i * (cell + 1) + cell // 2, text, guide.CHIPS["dot"]) for i, text in enumerate(names)]

   if calc["mode"] == "profile":
      band = guide.swatch_band([_rgb_list(c) for c in calc["ramps"].values()], cell)
      save_png(f"{shown['name']}_preview.png", guide.label_side(band, rows(list(calc["ramps"]))))
      return
   ramp_name = shown["values"].get("ramp_name") or shown["preset"] or "ramp"
   outline = prof.palette.get("outline") if prof is not None else "#000000"
   data = {"version": 1, "name": ramp_name, "ramp_len": calc["steps"], "outline": outline, "ramps": {ramp_name: calc["ramp"]}}
   path = safe_join(root, f"{shown['name']}_ramp.json")
   write_json(path, data)
   files.append(str(path))
   band = guide.swatch_band([_rgb_list(calc["ramp"])], cell)
   text = f"{ramp_name} {calc['steps']}단 · 바탕 {calc['base']}{' · 금속' if calc['metal'] else ''}"
   save_png(f"{shown['name']}_preview.png", guide.label_side(band, rows([text])))
