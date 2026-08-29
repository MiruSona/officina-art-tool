"""③ 검수. 규칙 하나당 함수 하나. 보고는 JSON 이고 status 는 ok 또는 fail."""

from __future__ import annotations

from pathlib import Path

from . import image, palette
from .errors import ArtToolError
from .jsonio import read_json
from .profile import Profile

VERSION = 1


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


def run(prof: Profile, build_dir: str | Path) -> dict:
   index, frames = load_frames(prof, build_dir)
   if not frames:
      raise ArtToolError("검수할 프레임이 하나도 없다 (frames.json 의 sheets 가 비었다)")

   ramps = None
   missing = None
   ramps_path = prof.ramps_path()
   if ramps_path is not None and ramps_path.is_file():
      ramps = palette.load_ramps(ramps_path)
   if ramps_path is not None and not ramps_path.is_file():
      missing = str(prof.palette["ramps_file"])

   rules = [
      rule_max_colors(frames, int(prof.check["max_colors"])),
      rule_ramp_colors(frames, ramps, bool(prof.palette["exact_match"]), missing),
      rule_alpha(frames, str(prof.check["allow_alpha"])),
      rule_baseline(frames, int(prof.canvas["baseline_y"]), int(prof.check["baseline_tolerance"])),
      rule_bbox_drift(frames, int(prof.check["bbox_drift"])),
   ]
   failed = [r["rule"] for r in rules if not r["ok"]]
   return {
      "version": VERSION,
      "profile": prof.name,
      "status": "fail" if failed else "ok",
      "checked": {"sheets": len(index["sheets"]), "frames": len(frames)},
      "failed": failed,
      "rules": rules,
   }
