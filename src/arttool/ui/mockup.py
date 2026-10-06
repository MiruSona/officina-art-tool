"""`ui mockup` — 장면 JSON 한 장을 읽어 UI 시안 PNG 한 장을 그린다.

장면 파일은 **믿을 수 없는 입력**으로 본다.
- 그림 · 글꼴 경로는 장면 파일이 있는 폴더 안(감옥)에서만 푼다 (`check_relative` + `safe_join`).
- 모르는 칸 · 모르는 kind 는 거절. 수 칸은 정수만(bool · 실수 · 문자열 거절), 범위도 본다.
- 캔버스 × 배율은 그림을 만들기 전에 `check_pixels` 로 막는다.
그리기 순서 = z 오름차순, 같으면 적은 순서. 글자도 이 순서 안에서 찍혀 패널에 가려질 수 있다.
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np

from .. import image
from ..checks import warning
from ..edit import dry_run_fields, is_dry_run
from ..errors import ArtToolError, UsageError
from ..jsonio import read_json
from ..paths import check_relative, guard_not_folder, guard_overwrite, jailed_output, safe_join
from . import glyphs, ninepatch

VERSION = 1
MAX_BYTES = 256 * 1024     # 장면 파일 크기 상한
MAX_NODES = 512            # 노드 수 상한
MAX_FONTS = 16
MAX_SIDE = 4096            # 캔버스 · 패널 한 변 상한
MAX_COORD = 4096           # at 좌표 절댓값 상한
MAX_NODE_SCALE = 8         # 노드 scale (설계 1~8)
MAX_SCALE = 16             # --scale (다 그린 뒤 통째로)
MAX_FONT_SIZE = 256
MAX_TEXT = 1024            # 글자 노드 한 개 길이
MAX_SETS = 64
MAX_LINES = 2048           # 장면 전체 글자 줄 수 상한

TOP_KEYS = {"version", "canvas", "background", "fonts", "nodes", "meta"}
NODE_KEYS = {
   "image": ({"kind", "src", "at"}, {"z", "scale", "id", "meta"}),
   "panel": ({"kind", "src", "at", "size"}, {"z", "mode", "id", "meta"}),
   "text": ({"kind", "text", "font", "at"}, {"z", "color", "align", "id", "meta"}),
}
HEX = re.compile(r"^#([0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
ID = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


def _int(value, where: str, low: int, high: int) -> int:
   """정수 하나. bool 은 int 의 자식이라 따로 막는다."""
   if isinstance(value, bool) or not isinstance(value, int):
      raise UsageError(f"{where} 는 정수여야 한다 : {value!r}")
   if not low <= value <= high:
      raise UsageError(f"{where} 는 {low}~{high} 이다 : {value}")
   return value


def _pair(value, where: str, low: int, high: int) -> tuple[int, int]:
   if not isinstance(value, list) or len(value) != 2:
      raise UsageError(f"{where} 는 [정수, 정수] 이다 : {value!r}")
   return _int(value[0], f"{where}[0]", low, high), _int(value[1], f"{where}[1]", low, high)


def _color(value, where: str) -> tuple[int, int, int, int]:
   if not isinstance(value, str) or not HEX.match(value):
      raise UsageError(f"{where} 는 #RRGGBB 또는 #RRGGBBAA 이다 : {value!r}")
   digits = value[1:] + ("ff" if len(value) == 7 else "")
   return tuple(int(digits[i : i + 2], 16) for i in range(0, 8, 2))


def _keys(obj, need: set, may: set, where: str) -> None:
   if not isinstance(obj, dict):
      raise UsageError(f"{where} 는 객체여야 한다")
   unknown = sorted(set(obj) - need - may)
   if unknown:
      raise UsageError(f"{where} 에 모르는 칸 : {', '.join(unknown)}")
   missing = sorted(need - set(obj))
   if missing:
      raise UsageError(f"{where} 에 빠진 칸 : {', '.join(missing)}")


def _jail(root: Path, rel, where: str) -> Path:
   """장면 폴더 안 상대 경로만 연다. 절대 · `..` · 드라이브 · 역슬래시는 check_relative · safe_join 이 거절한다."""
   if not isinstance(rel, str) or not rel or "\\" in rel:
      raise UsageError(f"{where} 는 장면 폴더 기준 상대 경로(/ 구분) 글자다 : {rel!r}")
   try:
      check_relative(rel)
      path = safe_join(root, rel)
   except ArtToolError as exc:
      raise UsageError(f"{where} 경로가 장면 폴더 밖이다 : {rel} ({exc})") from None
   if not path.is_file():
      raise UsageError(f"{where} 파일이 없다 : {rel}")
   return path


def _read_scene(scene: Path) -> dict:
   if not scene.is_file():
      raise UsageError(f"--scene 파일이 없다 : {scene}")
   if scene.stat().st_size > MAX_BYTES:
      raise UsageError(f"장면 파일이 너무 크다 : {scene.stat().st_size} 바이트 (한도 {MAX_BYTES})")
   try:
      data = read_json(scene)
   except RecursionError:
      raise UsageError(f"장면 파일이 너무 깊게 겹쳐 있다 : {scene}") from None
   except ArtToolError as exc:
      raise UsageError(f"장면 파일을 못 읽는다 : {exc}") from None
   if not isinstance(data, dict):
      raise UsageError("장면 파일 맨 위는 객체여야 한다")
   return data


def _parse_sets(items) -> dict[str, str]:
   sets: dict[str, str] = {}
   for text in items or []:
      if len(sets) >= MAX_SETS:
         raise UsageError(f"--set 이 너무 많다 (한도 {MAX_SETS})")
      key, sep, value = text.partition("=")
      if not sep or not ID.match(key) or not value:
         raise UsageError(f"--set 은 id=src 꼴이다 : {text}")
      if key in sets:
         raise UsageError(f"--set 에 같은 id 가 두 번 : {key}")
      sets[key] = value
   return sets


def plan(scene_path: Path, sets: dict[str, str]) -> dict:
   """장면을 다 검증하고 그릴 목록을 만든다. 그림은 머리(크기)만 읽고 화소는 아직 안 푼다."""
   data = _read_scene(scene_path)
   root = scene_path.parent.resolve()
   _keys(data, {"version", "canvas", "nodes"}, TOP_KEYS, "장면")
   if _int(data["version"], "version", 0, 1 << 30) != VERSION:
      raise UsageError(f"장면 version 은 {VERSION} 이다 : {data['version']}")
   width, height = _pair(data["canvas"], "canvas", 1, MAX_SIDE)
   reads = [scene_path]

   background = data.get("background")
   bg: dict | None = None
   if isinstance(background, str):
      bg = {"color": _color(background, "background")}
   elif background is not None:
      _keys(background, {"image"}, {"tile"}, "background")
      tile = background.get("tile", False)
      if not isinstance(tile, bool):
         raise UsageError("background.tile 은 true · false 다")
      bg = {"image": _jail(root, background["image"], "background.image"), "tile": tile}
      reads.append(bg["image"])

   fonts_raw = data.get("fonts", {})
   if not isinstance(fonts_raw, dict) or len(fonts_raw) > MAX_FONTS:
      raise UsageError(f"fonts 는 이름 → {{file, size}} 객체, {MAX_FONTS} 개까지다")
   fonts: dict[str, tuple[Path, int]] = {}
   for name, spec in fonts_raw.items():
      _keys(spec, {"file", "size"}, set(), f"fonts.{name}")
      fonts[name] = (_jail(root, spec["file"], f"fonts.{name}.file"), _int(spec["size"], f"fonts.{name}.size", 1, MAX_FONT_SIZE))
      reads.append(fonts[name][0])

   nodes = data["nodes"]
   if not isinstance(nodes, list) or len(nodes) > MAX_NODES:
      raise UsageError(f"nodes 는 배열, {MAX_NODES} 개까지다")
   ids: set[str] = set()
   swappable: set[str] = set()   # --set 으로 그림을 바꿀 수 있는 id (image · panel)
   lines = 0
   items = []
   for i, node in enumerate(nodes):
      where = f"nodes[{i}]"
      kind = node.get("kind") if isinstance(node, dict) else None
      if not isinstance(kind, str) or kind not in NODE_KEYS:   # 목록 · 객체는 해시가 안 돼 먼저 거른다
         raise UsageError(f"{where}.kind 를 모른다 : {kind!r} (image · panel · text)")
      _keys(node, *NODE_KEYS[kind], where)
      item = {"i": i, "kind": kind, "z": _int(node.get("z", 0), f"{where}.z", -MAX_COORD, MAX_COORD),
              "at": _pair(node["at"], f"{where}.at", -MAX_COORD, MAX_COORD)}
      if "id" in node:
         if not isinstance(node["id"], str) or not ID.match(node["id"]) or node["id"] in ids:
            raise UsageError(f"{where}.id 가 틀렸거나 겹친다 : {node['id']!r}")
         ids.add(node["id"])
      if kind in ("image", "panel"):
         if "id" in node:
            swappable.add(node["id"])
         src = sets.get(node.get("id"), node["src"])
         item["src"] = _jail(root, src, f"{where}.src")
         reads.append(item["src"])
      if kind == "image":
         item["scale"] = _int(node.get("scale", 1), f"{where}.scale", 1, MAX_NODE_SCALE)
         try:   # 그리기 전에 그림 머리만 읽어 크기 × scale 을 막는다. 장면 잘못이라 종료 2
            pw, ph = image.read_size(item["src"])
            image.check_pixels(pw * item["scale"], ph * item["scale"], f"{where} 그림 × scale")
         except ArtToolError as exc:
            raise UsageError(str(exc)) from None
      elif kind == "panel":
         item["size"] = _pair(node["size"], f"{where}.size", 1, MAX_SIDE)
         item["mode"] = node.get("mode", "stretch")
         if not isinstance(item["mode"], str) or item["mode"] not in ("stretch", "tile"):
            raise UsageError(f"{where}.mode 는 stretch · tile 이다 : {item['mode']!r}")
         if not item["src"].name.endswith(ninepatch.SUFFIX):
            raise UsageError(f"{where}.src 는 안내선 있는 {ninepatch.SUFFIX} 이다 : {item['src'].name}")
      else:
         text = node["text"]
         if not isinstance(text, str) or len(text) > MAX_TEXT:
            raise UsageError(f"{where}.text 는 {MAX_TEXT} 자까지 글자다")
         lines += text.count("\n") + 1
         if lines > MAX_LINES:
            raise UsageError(f"장면 전체 글자 줄이 너무 많다 (한도 {MAX_LINES} 줄)")
         if not isinstance(node["font"], str) or node["font"] not in fonts:
            raise UsageError(f"{where}.font 가 fonts 에 없다 : {node['font']!r}")
         item.update(text=text, font=node["font"], color=_color(node.get("color", "#000000"), f"{where}.color"),
                     align=node.get("align", "left"))
         if not isinstance(item["align"], str) or item["align"] not in ("left", "center", "right"):
            raise UsageError(f"{where}.align 은 left · center · right 이다 : {item['align']!r}")
      items.append(item)
   unused = sorted(set(sets) - ids)
   if unused:
      raise UsageError(f"--set 의 id 가 장면에 없다 : {', '.join(unused)}")
   wrong = sorted(set(sets) - swappable)
   if wrong:
      raise UsageError(f"--set 은 image · panel 노드의 id 만 받는다 : {', '.join(wrong)}")
   items.sort(key=lambda it: (it["z"], it["i"]))   # 안정 정렬 — 같은 z 는 적은 순서
   return {"size": (width, height), "background": bg, "fonts": fonts, "items": items, "reads": reads}


def _put(canvas: image.RGBA, src: image.RGBA, x: int, y: int) -> bool:
   """캔버스에 알파 합성으로 얹는다. 밖으로 나간 몫은 잘라 낸다. 잘렸으면 True."""
   cw, ch = image.size(canvas)
   sw, sh = image.size(src)
   x0, y0, x1, y1 = max(x, 0), max(y, 0), min(x + sw, cw), min(y + sh, ch)
   if x0 >= x1 or y0 >= y1:
      return True
   image.paste_over(canvas, src[y0 - y : y1 - y, x0 - x : x1 - x], x0, y0)
   return (x0, y0, x1, y1) != (x, y, x + sw, y + sh)


def _load(path: Path) -> image.RGBA:
   try:
      return image.load(path)
   except ArtToolError as exc:
      raise UsageError(f"그림을 못 읽는다 : {path.name} ({exc})") from None


def _background(canvas: image.RGBA, bg: dict | None) -> None:
   if bg is None:
      return
   if "color" in bg:
      canvas[:, :] = bg["color"]
      return
   tile = _load(bg["image"])
   width, height = image.size(canvas)
   tw, th = image.size(tile)
   steps = [(x, y) for y in range(0, height, th) for x in range(0, width, tw)] if bg["tile"] else [(0, 0)]
   for x, y in steps:
      _put(canvas, tile, x, y)


def _text(canvas: image.RGBA, font, item: dict) -> bool:
   """줄마다 줄 크기만 한 0/255 판으로 그려 색을 알파 합성으로 얹는다. 도트 화면이라 흐린 가장자리는 없다.
   글자가 캔버스 밖으로 나가 잘렸으면 True."""
   x, y = item["at"]
   step = font.size + 1 if hasattr(font, "size") else 1
   clipped = False
   for row, line in enumerate(item["text"].split("\n")):
      span = int(round(font.getlength(line))) if line else 0
      lx = x - (span // 2 if item["align"] == "center" else span if item["align"] == "right" else 0)
      mask, mx, my = image.text_line_mask(font, line, lx, y + row * step)
      if not mask.any():
         continue
      ys, xs = np.nonzero(mask >= 128)   # 실제 찍힌 칸만 따져 잘림을 본다
      mask = mask[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]
      ink = np.zeros(mask.shape + (4,), dtype=np.uint8)
      ink[mask >= 128] = item["color"]
      clipped |= _put(canvas, ink, mx + int(xs.min()), my + int(ys.min()))
   return clipped


def run(args) -> dict:
   scene = Path(args.scene)
   scale = _int(args.scale, "--scale", 1, MAX_SCALE)
   sets = _parse_sets(args.set)
   out = guard_not_folder(jailed_output(args.out))
   if out.suffix.lower() != ".png":
      raise UsageError(f"--out 은 .png 파일이다 : {args.out}")
   job = plan(scene, sets)
   width, height = job["size"]
   try:   # 그림을 만들기 전에 막는다. 장면 잘못이라 종료 2
      image.check_pixels(width * scale, height * scale, "목업 캔버스 × --scale")
   except ArtToolError as exc:
      raise UsageError(str(exc)) from None
   guard_overwrite([out], job["reads"])

   fonts = {}
   for name, (file, size) in job["fonts"].items():
      try:
         fonts[name] = glyphs.load_font(file, size)
      except ArtToolError as exc:
         raise UsageError(str(exc)) from None
   canvas = image.new(width, height)
   _background(canvas, job["background"])
   clipped, missing, drawn = [], [], []
   for item in job["items"]:
      if item["kind"] == "image":
         pic = _load(item["src"])   # 크기 × scale 은 plan 에서 머리로 이미 막았다
         if _put(canvas, image.scale_up(pic, item["scale"]), *item["at"]):
            clipped.append(item["i"])
      elif item["kind"] == "panel":
         pic = _load(item["src"])
         try:
            border = ninepatch.read_guides(pic)["border"]
            body = ninepatch.slice_stretch(ninepatch.strip(pic), border, *item["size"], item["mode"])
         except ArtToolError as exc:
            raise UsageError(f"nodes[{item['i']}] 9조각을 못 늘린다 : {exc}") from None
         if _put(canvas, body, *item["at"]):
            clipped.append(item["i"])
      else:
         font = fonts[item["font"]]
         lost, _ = glyphs.find_missing(font, glyphs.wanted_chars(item["text"]), job["fonts"][item["font"]][1])
         missing += [ch for ch in lost if ch not in missing]
         if _text(canvas, font, item):
            clipped.append(item["i"])
      drawn.append({"i": item["i"], "kind": item["kind"], "z": item["z"]})

   warnings = []
   if clipped:
      warnings.append(warning("ui_mockup.clipped", f"캔버스 밖으로 나가 잘린 노드 {len(clipped)} 개", clipped))
   if missing:
      warnings.append(warning("ui_mockup.missing_glyph", f"글꼴에 없는 글자 {len(missing)} 개", missing))
   dry_run = is_dry_run(args)
   if not dry_run:
      out.parent.mkdir(parents=True, exist_ok=True)
      image.save(out, image.scale_up(canvas, scale) if scale > 1 else canvas)
   return {
      "version": VERSION,
      "status": "warn" if warnings else "ok",
      "scene": str(scene),
      "canvas": [width, height],
      "scale": scale,
      "nodes": len(job["items"]),
      "drawn": drawn,
      "images": [str(p) for p in job["reads"][1:]],
      "warnings": warnings,
      "out": None if dry_run else str(out),
      **dry_run_fields(dry_run, [str(out)]),
   }
