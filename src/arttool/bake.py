"""④ 굽기. 아틀라스 · 슬라이스 · 매니페스트 · ScriptableObject 용 JSON 을 낸다.

검수 보고가 ok 일 때만 돈다. --force 로 넘기면 매니페스트에 forced 가 박힌다.
"""

from __future__ import annotations

from pathlib import Path

from . import image, palette
from .errors import ArtToolError, CheckFailed
from .jsonio import read_json, write_json
from .paths import resolve_root, safe_join
from .profile import Profile

VERSION = 1


def pivot_of(prof: Profile) -> dict:
   """Unity pivot. 두 축 다 「픽셀 중심 좌표 / 프레임 크기」 한 규칙이다.

   x 는 왼쪽에서, y 는 아래에서 센다 (Unity 가 왼쪽 아래 기준이다).
   pivot 이 bottom_center 가 아니면 그 규칙대로 자리를 옮긴다.
   """
   frame_w, frame_h = prof.frame
   baseline = int(prof.canvas["baseline_y"])
   center_x = float(prof.canvas["center_x"])
   from_bottom = frame_h - 1 - baseline

   spot = str(prof.canvas["pivot"])
   if spot == "center":
      center_x = (frame_w - 1) / 2.0
      from_bottom = (frame_h - 1) / 2.0
   if spot == "top_left":
      center_x = 0.0
      from_bottom = frame_h - 1

   return {
      "x": round((center_x + 0.5) / frame_w, 6),
      "y": round((from_bottom + 0.5) / frame_h, 6),
   }


def gate(build: Path, force: bool, report_name: str = "check.json") -> dict:
   """검수 보고가 ok 일 때만 지나간다. --force 면 보고 내용을 그대로 돌려준다."""
   report_file = build / report_name
   if not report_file.is_file():
      if not force:
         raise CheckFailed("검수 보고(check.json)가 없다. 먼저 check 를 돌리거나 --force 를 준다")
      return {"status": None}

   report = read_json(report_file)
   if report.get("status") != "ok" and not force:
      raise CheckFailed(f"검수가 통과하지 않았다 : {', '.join(report.get('failed', []))}")
   return report


def _pack_atlas(prof: Profile, build: Path, index: dict) -> tuple[image.RGBA, list[dict], list[dict]]:
   frame_w, frame_h = prof.frame
   sheets = index["sheets"]
   width = max(int(s["cols"]) for s in sheets) * frame_w
   height = sum(int(s["rows"]) for s in sheets) * frame_h

   atlas = image.new(width, height)
   slices: list[dict] = []
   animations: list[dict] = []
   top = 0
   for sheet in sheets:
      grid = image.split_grid(image.load(build / sheet["file"]), frame_w, frame_h)
      entries, made = _place_sheet(prof, atlas, sheet, grid, top)
      slices += made
      animations.append(
         {
            "name": sheet["anim"],
            "frames": int(sheet["frames"]),
            "directions": list(sheet["directions"]),
            "mirrored": list(sheet.get("mirrored", [])),
            "entries": entries,
         }
      )
      top += int(sheet["rows"]) * frame_h
   return atlas, slices, animations


def _place_sheet(prof: Profile, atlas: image.RGBA, sheet: dict, grid: list, top: int) -> tuple[list[str], list[dict]]:
   """시트 한 장을 아틀라스에 붙이고 이름 목록과 slice 목록을 낸다."""
   frame_w, frame_h = prof.frame
   entries: list[str] = []
   slices: list[dict] = []
   for row, direction in enumerate(sheet["directions"][: len(grid)]):
      for col, frame in enumerate(grid[row]):
         x, y = col * frame_w, top + row * frame_h
         image.paste(atlas, frame, x, y)
         name = f"{sheet['anim']}_{direction}_{col}"
         slices.append({"name": name, "x": x, "y": y, "w": frame_w, "h": frame_h, "pivot": pivot_of(prof)})
         entries.append(name)
   return entries, slices


def _sprite_spec(prof: Profile, namespace: str) -> dict:
   frame_w, frame_h = prof.frame
   return {
      "version": VERSION,
      "namespace": namespace,
      "profile": prof.name,
      "frameWidth": frame_w,
      "frameHeight": frame_h,
      "baselineY": int(prof.canvas["baseline_y"]),
      "centerX": float(prof.canvas["center_x"]),
      "directions": prof.directions,
      "projection": prof.axes["projection"],
      "movement": prof.axes["movement"],
      "pivot": pivot_of(prof),
   }


def bake(prof: Profile, build_dir: str | Path, out_dir: str | Path, namespace: str = "Game.Art", force: bool = False) -> dict:
   build = Path(build_dir)
   if not build.is_dir():
      raise ArtToolError(f"굽기 입력 폴더가 없다 : {build}")
   report = gate(build, force)
   index = read_json(build / "frames.json")
   root = resolve_root(out_dir)

   atlas, slices, animations = _pack_atlas(prof, build, index)
   image.save(safe_join(root, "atlas.png"), atlas)
   write_json(safe_join(root, "atlas_slices.json"), {"version": VERSION, "atlas": "atlas.png", "slices": slices})

   manifest = {
      "version": VERSION,
      "profile": prof.name,
      "namespace": namespace,
      "atlas": "atlas.png",
      "frame": list(prof.frame),
      "baseline_y": int(prof.canvas["baseline_y"]),
      "animations": animations,
      "check": report.get("status"),
      "forced": bool(force),
   }
   write_json(safe_join(root, "sprite_manifest.json"), manifest)

   made = ["atlas.png", "atlas_slices.json", "sprite_manifest.json"]
   made += _bake_anchors(build, root)
   made += _bake_palette(prof, root, namespace)
   write_json(safe_join(root, "SpriteSpecAsset.json"), _sprite_spec(prof, namespace))
   made.append("SpriteSpecAsset.json")

   return {"out": str(root), "files": made, "forced": bool(force), "check": report.get("status")}


def _bake_anchors(build: Path, root: Path) -> list[str]:
   source = build / "anchors.json"
   if not source.is_file():
      return []
   write_json(safe_join(root, "anchors.json"), read_json(source))
   return ["anchors.json"]


def _bake_palette(prof: Profile, root: Path, namespace: str) -> list[str]:
   ramps_path = prof.ramps_path()
   if ramps_path is None or not ramps_path.is_file():
      return []

   ramps = palette.load_ramps(ramps_path)
   asset = palette.ramp_asset_json(ramps)
   asset["namespace"] = namespace
   write_json(safe_join(root, "PaletteRampAsset.json"), asset)
   made = ["PaletteRampAsset.json"]

   if prof.palette["swap"] in ("runtime_lut", "both"):
      palette.save_lut(safe_join(root, "palette_lut.png"), ramps)
      made.append("palette_lut.png")
   return made
