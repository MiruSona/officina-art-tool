"""③ 검수. 규칙 하나당 함수 하나. 보고는 JSON 이고 status 는 ok 또는 fail."""

from __future__ import annotations

import sys
from pathlib import Path

from . import image, palette
from .errors import ArtToolError
from .jsonio import read_json
from .profile import Profile

VERSION = 1

# 낱장 모드에서 프레임 규격이 없어 못 도는 규칙들.
LOOSE_SKIPPED = ["baseline", "bbox_drift"]


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


def png_files(source: Path) -> list[Path]:
   """폴더 바로 아래 PNG 만 이름순으로. 확장자 대소문자는 가리지 않고 하위 폴더는 안 본다."""
   return sorted(p for p in source.iterdir() if p.is_file() and p.suffix.lower() == ".png")


def check_source(path: str | Path) -> Path:
   """입구에서 경로를 본다. 없거나 PNG 아닌 파일이면 그 자리에서 알린다."""
   source = Path(path)
   if not source.exists():
      raise ArtToolError(f"폴더·파일이 없다 : {source}")
   if source.is_file() and source.suffix.lower() != ".png":
      raise ArtToolError(f"검수는 폴더나 PNG 파일만 받는다 : {source}")
   return source


def load_loose(path: str | Path) -> list[dict]:
   """낱장 PNG 를 이름순으로 읽는다. 파일 하나를 주면 그 한 장만 본다."""
   source = Path(path)
   files = [source] if source.is_file() else png_files(source)
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


def rule_max_colors_each(frames: list[dict], limit: int) -> dict:
   """낱장 모드용. 낱장은 한 벌이 아니라 제각각이라 장마다 따로 센다."""
   items = [{"where": where(i), "colors": image.count_colors(i["arr"])} for i in frames]
   bad = [i for i in items if i["colors"] > limit]
   return result("max_colors", not bad, f"한도 {limit}가지를 넘은 그림 {len(bad)}개", items)


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


def _pick_ramps(prof: Profile) -> tuple[object | None, str | None]:
   """램프를 읽는다. 프로필에 적혔는데 파일이 없으면 그 이름을 같이 돌려준다."""
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


def run(prof: Profile, build_dir: str | Path, no_ramps: bool = False) -> dict:
   source = check_source(build_dir)
   if is_loose(source):
      if source.is_dir():
         # frames.json 이 없어 낱장으로 본 것인지, 앞 단계가 실패한 것인지 사람이 가릴 수 있게 알린다.
         print(f"frames.json 이 없어 낱장 모드로 본다 — 건너뛴 검사 : {', '.join(LOOSE_SKIPPED)}", file=sys.stderr)
      return run_loose(prof, source, no_ramps)
   return run_frames(prof, source, no_ramps)


def run_frames(prof: Profile, build_dir: str | Path, no_ramps: bool = False) -> dict:
   index, frames = load_frames(prof, build_dir)
   if not frames:
      raise ArtToolError("검수할 프레임이 하나도 없다 (frames.json 의 sheets 가 비었다)")

   ramps, missing = _pick_ramps(prof)
   rules = [rule_max_colors(frames, int(prof.check["max_colors"]))]
   if not no_ramps:
      rules.append(rule_ramp_colors(frames, ramps, bool(prof.palette["exact_match"]), missing))
   rules += [
      rule_alpha(frames, str(prof.check["allow_alpha"])),
      rule_baseline(frames, int(prof.canvas["baseline_y"]), int(prof.check["baseline_tolerance"])),
      rule_bbox_drift(frames, int(prof.check["bbox_drift"])),
   ]
   skipped = ["ramp_colors"] if no_ramps else []
   return _report(prof, rules, {"sheets": len(index["sheets"]), "frames": len(frames)}, skipped)


def run_loose(prof: Profile, in_path: str | Path, no_ramps: bool = False) -> dict:
   """낱장 검수. 프레임 규격을 모르니 baseline · bbox 흔들림은 안 본다."""
   frames = load_loose(in_path)
   ramps, missing = _pick_ramps(prof)

   rules = [rule_max_colors_each(frames, int(prof.check["max_colors"]))]
   if not no_ramps:
      rules.append(rule_ramp_colors(frames, ramps, bool(prof.palette["exact_match"]), missing))
   rules.append(rule_alpha(frames, str(prof.check["allow_alpha"])))
   rules += [rule_loose_skip(name) for name in LOOSE_SKIPPED]

   # 실제로 안 돈 규칙을 다 적는다. 프로필에 램프가 없어 안 도는 것은 「설정상 없는 검사」라 안 넣는다.
   skipped = list(LOOSE_SKIPPED) + (["ramp_colors"] if no_ramps else [])
   return _report(prof, rules, {"mode": "loose", "files": len(frames)}, skipped)
