"""③ UI 굽기. 아틀라스 · ui_manifest.json · ui.uss · Unity 에디터 스크립트 · UiSpecAsset.

검수 보고가 ok 일 때만 돈다. --force 면 매니페스트에 forced 가 박힌다.
`ui/` 밖은 border 를 모른다. 여기서 매니페스트 칸을 만들어 넘기고 끝이다.

C# 은 `<out>/Editor/` 아래로 간다. 에디터 전용 API 를 쓰므로 플레이어 빌드에 들어가면 안 된다.
"""

from __future__ import annotations

import re
from pathlib import Path

from .. import bake as common
from .. import image
from ..errors import ArtToolError
from ..jsonio import read_json, write_json
from ..paths import resolve_root, safe_join, write_text
from ..profile import Profile
from . import check_ui, manifest, uss

VERSION = 1
EDITOR_DIR = "Editor"
UNITY_FILES = ("UiImportSettings.cs", "TmpFontBaker.cs", "UiManifestData.cs")
FONT_DIR = "Fonts"
CHARSET_NAME = "charset.txt"

NAMESPACE_SHAPE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")


def unity_dir() -> Path:
   return Path(__file__).resolve().parent / "unity"


def check_namespace(value: str) -> str:
   """C# 소스에 그대로 박히는 값이라 이름 꼴을 좁힌다."""
   if not isinstance(value, str) or not NAMESPACE_SHAPE.match(value):
      raise ArtToolError(f"namespace 는 Game.UI 같은 이름이어야 한다 : {value!r}")
   return value


def _read_lists(build: Path) -> tuple[list[dict], list[dict]]:
   frames = read_json(build / "border.json")["frames"] if (build / "border.json").is_file() else []
   icons = read_json(build / "icons.json")["icons"] if (build / "icons.json").is_file() else []
   if not frames and not icons:
      raise ArtToolError(f"구울 것이 없다. {build} 에 border.json 도 icons.json 도 없다")
   return frames, icons


def _paint_atlas(build: Path, data: dict, sources: dict[str, str]) -> image.RGBA:
   width, height = data["atlas_size"]
   atlas = image.new(width, height)
   for entry in data["frames"] + data["icons"]:
      x1, y1, _x2, _y2 = entry["rect"]
      image.paste(atlas, image.load(build / sources[entry["name"]]), x1, y1)
   return atlas


def _ui_spec(prof: Profile, namespace: str) -> dict:
   ui = prof.ui
   return {
      "version": VERSION,
      "namespace": namespace,
      "profile": prof.name,
      "ppu": int(ui["ppu"]),
      "referenceWidth": int(ui["reference"][0]),
      "referenceHeight": int(ui["reference"][1]),
      "scaleMode": ui["scale_mode"],
      "letterbox": bool(ui["letterbox"]),
      "sliceScale": prof.slice_scale(),
      "fontFamily": ui["font"]["family"],
      "fontNativePx": int(ui["font"]["native_px"]),
      "fontSizesPx": [int(s) for s in ui["font"]["sizes_px"]],
   }


def font_settings(prof: Profile, namespace: str, assets_root: str) -> dict:
   """폰트 굽기에 쓰는 경로는 여기서만 정한다. 에디터 스크립트가 이 JSON 을 읽는다."""
   font = prof.ui["font"]
   family = font["family"]
   where = assets_root.strip("/")
   return {
      "sourceFont": f"{where}/{FONT_DIR}/{family}.ttf",
      "charsetPath": f"{where}/{FONT_DIR}/{CHARSET_NAME}",
      "outputPath": f"{where}/{FONT_DIR}/{family} SDF.asset",
      "nativePx": int(font["native_px"]),
      "atlasMax": int(font["subset"]["atlas_max"]),
      "namespace": namespace,
   }


def bake(
   prof: Profile,
   build_dir: str | Path,
   out_dir: str | Path,
   namespace: str = "Game.UI",
   force: bool = False,
   assets_root: str = uss.ASSETS_ROOT,
) -> dict:
   check_namespace(namespace)
   uss.check_assets_root(assets_root)

   build = Path(build_dir)
   if not build.is_dir():
      raise ArtToolError(f"굽기 입력 폴더가 없다 : {build}")

   report = common.gate(build, force, "check.json")
   frames, icons = _read_lists(build)
   sources = {e["name"]: e["file"] for e in frames + icons}
   data = manifest.build(prof, frames, icons)
   data["forced"] = bool(force)
   data["check"] = report.get("status")
   _check_ppu(prof, data)

   root = resolve_root(out_dir)
   image.save(safe_join(root, manifest.ATLAS_NAME), _paint_atlas(build, data, sources))
   manifest.save(safe_join(root, "ui_manifest.json"), data)

   text = uss.base_rules(prof, assets_root) + "\n" + uss.bg_rules(data, assets_root)
   write_text(safe_join(root, "ui.uss"), text)
   write_json(safe_join(root, "UiSpecAsset.json"), _ui_spec(prof, namespace))
   settings = font_settings(prof, namespace, assets_root)
   write_json(safe_join(root, "font_bake.json"), settings)

   made = [manifest.ATLAS_NAME, "ui_manifest.json", "ui.uss", "UiSpecAsset.json", "font_bake.json"]
   copied, warnings = _copy_unity(root, namespace)
   return {
      "out": str(root),
      "files": made + copied,
      "forced": bool(force),
      "check": report.get("status"),
      "atlas_size": data["atlas_size"],
      "warnings": warnings,
      "notes": [_dynamic_atlas_note(), _charset_note(settings["charsetPath"])],
   }


def _check_ppu(prof: Profile, data: dict) -> None:
   """설계 8-3 : 프로필 · 매니페스트 · 임포터가 같은 PPU 를 쓴다."""
   want = int(prof.ui["ppu"])
   if int(data["ppu"]) != want:
      raise ArtToolError(f"매니페스트 ppu {data['ppu']} 가 프로필 ui.ppu {want} 와 다르다")


def _copy_unity(root: Path, namespace: str) -> tuple[list[str], list[str]]:
   """C# 을 Editor/ 아래로 옮긴다. 사람이 고쳐 둔 파일은 덮지 않고 .new 로 옆에 쓴다."""
   source = unity_dir()
   made: list[str] = []
   warnings: list[str] = []
   for name in UNITY_FILES:
      wanted = _with_namespace(source / name, namespace)
      target = safe_join(root, f"{EDITOR_DIR}/{name}")

      if target.is_file() and target.read_text(encoding="utf-8") != wanted:
         write_text(target.with_name(name + ".new"), wanted)
         warnings.append(f"{EDITOR_DIR}/{name} 을 사람이 고쳤다. 안 덮고 {name}.new 로 옆에 뒀다")
         made.append(f"{EDITOR_DIR}/{name}.new")
         continue

      write_text(target, wanted)
      made.append(f"{EDITOR_DIR}/{name}")
   return made, warnings


def _with_namespace(path: Path, namespace: str) -> str:
   """첫 namespace 줄만 바꾼다. 나머지 글자는 안 건드린다."""
   lines = path.read_text(encoding="utf-8").splitlines()
   for index, line in enumerate(lines):
      if line.startswith("namespace "):
         lines[index] = f"namespace {namespace}"
         break
   return "\n".join(lines) + "\n"


def _dynamic_atlas_note() -> str:
   """UI Toolkit 동적 아틀라스가 Point 텍스처를 흐리게 만든다. Unity 6 에서 고쳐졌는지 확인 못 했다."""
   return "PanelSettings 의 DynamicAtlasSettings 에서 UI 아틀라스를 뺀다 (Point 텍스처가 흐려진다)"


def _charset_note(charset_path: str) -> str:
   return f"arttool ui font 의 --out 을 {charset_path} 로 준다 (font_bake.json 이 그 자리를 가리킨다)"


def run(prof: Profile, build_dir: str | Path, out_dir: str | Path, namespace: str, force: bool) -> dict:
   """검수까지 한 번에 돌리고 싶을 때 쓴다. check.json 을 만들고 이어서 굽는다."""
   build = Path(build_dir)
   report = check_ui.run(build, prof)
   write_json(build / "check.json", report)
   return bake(prof, build, out_dir, namespace, force)
