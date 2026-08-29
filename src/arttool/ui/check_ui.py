"""② UI 검수. 규칙 다섯과 경고 둘.

팔레트 밖 색·반투명은 공용 `check.py` 의 규칙을 그대로 가져다 쓴다. UI 것만 여기서 더한다.
"""

from __future__ import annotations

from pathlib import Path

from .. import check as common
from .. import image
from ..errors import ArtToolError
from ..jsonio import read_json
from ..profile import Profile
from . import frame as frame_mod
from . import manifest as manifest_mod

VERSION = 1


def load_pieces(build_dir: str | Path) -> tuple[list[dict], list[dict]]:
   """border.json 과 icons.json 을 읽고 그림도 같이 붙여 온다."""
   root = Path(build_dir)
   frames = _load_frames(root)
   icons = _load_icons(root)
   if not frames and not icons:
      raise ArtToolError(f"검수할 것이 없다. {root} 에 border.json 도 icons.json 도 없다")
   return frames, icons


def _load_frames(root: Path) -> list[dict]:
   path = root / "border.json"
   if not path.is_file():
      return []
   entries = read_json(path).get("frames", [])
   for entry in entries:
      entry["arr"] = image.load(root / entry["file"])
      entry["where"] = entry["name"]
   return entries


def _load_icons(root: Path) -> list[dict]:
   path = root / "icons.json"
   if not path.is_file():
      return []
   entries = read_json(path).get("icons", [])
   for entry in entries:
      entry["arr"] = image.load(root / entry["file"])
      entry["where"] = entry["name"]
   return entries


def rule_min_size(frames: list[dict]) -> dict:
   bad = []
   for entry in frames:
      width, height = image.size(entry["arr"])
      want_w, want_h = entry["min_size"]
      if width < want_w or height < want_h:
         bad.append({"where": entry["name"], "size": [width, height], "min_size": [want_w, want_h]})
   return common.result("ui_min_size", not bad, f"최소 크기보다 작은 프레임 {len(bad)}개", bad)


def rule_even_size(frames: list[dict], require: bool) -> dict:
   if not require:
      return common.result("ui_even_size", True, "홀수를 허용하는 프로필이다")
   bad = []
   for entry in frames:
      width, height = image.size(entry["arr"])
      if width % 2 or height % 2:
         bad.append({"where": entry["name"], "size": [width, height]})
   return common.result("ui_even_size", not bad, f"홀수 크기 프레임 {len(bad)}개", bad)


def rule_states(frames: list[dict], want_states: list[str]) -> dict:
   groups: dict[str, set[str]] = {}
   for entry in frames:
      groups.setdefault(entry["group"], set()).add(entry["state"])

   bad = []
   for group, states in sorted(groups.items()):
      missing = [s for s in want_states if s not in states]
      if missing:
         bad.append({"where": group, "missing": missing})
   return common.result("ui_states", not bad, f"상태가 빠진 묶음 {len(bad)}개", bad)


def warn_atlas_size(frames: list[dict], icons: list[dict], atlas_max: int) -> dict:
   if not frames and not icons:
      return common.result("ui_atlas_size", True, "아틀라스에 넣을 것이 없다")
   items = [(f"frame:{f['name']}", *image.size(f["arr"])) for f in frames]
   items += [(f"icon:{i['name']}", *image.size(i["arr"])) for i in icons]
   _spots, (width, height) = manifest_mod.pack(items)
   ok = width <= atlas_max and height <= atlas_max
   return common.result("ui_atlas_size", ok, f"아틀라스 {width}x{height} / 한도 {atlas_max}")


def warn_icon_family(icons: list[dict]) -> dict:
   families: dict[str, set[int]] = {}
   for entry in icons:
      families.setdefault(entry["family"], set()).add(int(entry["size"]))

   mixed = [{"where": name, "sizes": sorted(sizes)} for name, sizes in sorted(families.items()) if len(sizes) > 1]
   return common.result("ui_icon_family", not mixed, f"크기가 섞인 아이콘 가족 {len(mixed)}개", mixed)


def rule_ppu(manifest_path: Path | None, want: int) -> dict:
   """설계 8-3 : 매니페스트와 임포터가 쓰는 PPU 가 프로필과 같은지 본다.

   매니페스트는 굽기가 만든다. 아직 없으면 대조할 것이 없으니 지나간다.
   굽기 자체도 `bake_ui._check_ppu` 로 한 번 더 본다.
   """
   if manifest_path is None or not manifest_path.is_file():
      return common.result("ui_ppu", True, f"대조할 매니페스트가 없다. 프로필 ppu 는 {want}")

   data = read_json(manifest_path)
   if "ppu" not in data:
      return common.result("ui_ppu", False, f"매니페스트에 ppu 칸이 없다 : {manifest_path.name}")

   got = int(data["ppu"])
   return common.result("ui_ppu", got == want, f"매니페스트 ppu {got} / 프로필 ui.ppu {want}")


def find_manifest(build_dir: Path, manifest_path=None) -> Path | None:
   if manifest_path:
      wanted = Path(manifest_path)
      if not wanted.is_file():
         raise ArtToolError(f"매니페스트 파일이 없다 : {wanted}")
      return wanted

   near = build_dir / "ui_manifest.json"
   if near.is_file():
      return near
   return None


def run(build_dir: str | Path, prof: Profile | None = None, manifest_path=None) -> dict:
   from ..profile import load_profile

   # 프로필을 안 주면 툴 기본값으로 본다. 특정 프로필 이름을 코드에 박지 않는다.
   prof = prof or load_profile()
   frames, icons = load_pieces(build_dir)
   ui_check = prof.ui["check"]
   pieces = frames + icons

   ramps = None
   if ui_check["palette_strict"]:
      ramps = frame_mod.load_ui_ramps(prof)

   rules = [
      rule_min_size(frames),
      rule_even_size(frames, bool(ui_check["require_even"])),
      common.rule_ramp_colors(pieces, ramps, bool(ui_check["palette_strict"])),
      common.rule_alpha(pieces, str(ui_check["allow_alpha"])),
      rule_states(frames, list(prof.ui["generator"]["states"])),
      rule_ppu(find_manifest(Path(build_dir), manifest_path), int(prof.ui["ppu"])),
   ]
   warnings = [
      warn_atlas_size(frames, icons, int(ui_check["atlas_max"])),
      warn_icon_family(icons),
   ]

   failed = [r["rule"] for r in rules if not r["ok"]]
   return {
      "version": VERSION,
      "profile": prof.name,
      "status": "fail" if failed else "ok",
      "checked": {"frames": len(frames), "icons": len(icons)},
      "failed": failed,
      "rules": rules,
      "warnings": [w for w in warnings if not w["ok"]],
   }
