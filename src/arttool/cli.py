"""명령 등록만 한다. 셈은 다른 모듈이 하고 여기서는 인자를 넘겨 부르기만 한다."""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from pathlib import Path

from . import bake as bake_mod
from . import check as check_mod
from . import providers
from .errors import EXIT_CHECK_FAIL, EXIT_ERROR, EXIT_OK, ArtToolError
from .jsonio import read_json, write_json
from .paths import jailed_output
from .profile import load_profile
from .sprite import anchors as anchors_mod
from .sprite import layers as layers_mod
from .sprite import normalize as normalize_mod
from .tiles import blob as blob_mod
from .tiles import ldtk as ldtk_mod
from .tiles import place as place_mod
from .ui import bake_ui as ui_bake_mod
from .ui import check_ui as ui_check_mod
from .ui import font as ui_font_mod
from .ui import frame as ui_frame_mod
from .ui import icons as ui_icons_mod
from .ui import ninepatch as ui_import_mod
from .ui import screen as ui_screen_mod


def _common() -> argparse.ArgumentParser:
   """어느 명령 뒤에도 붙일 수 있는 공통 인자. 안 주면 값을 안 넣어 앞의 값이 남는다."""
   node = argparse.ArgumentParser(add_help=False, argument_default=argparse.SUPPRESS)
   node.add_argument("--profile")
   node.add_argument("--provider")
   node.add_argument("--dry-run", action="store_true")
   node.add_argument("--force", action="store_true")
   node.add_argument("--json", action="store_true", dest="as_json")
   node.add_argument("--directions", type=int)
   return node


COMMON = _common()


def build_parser() -> argparse.ArgumentParser:
   parser = argparse.ArgumentParser(prog="arttool", description="2D 그림 규격 맞추기 · 앵커 · 검수 · 굽기")
   parser.add_argument("--profile", help="프로필 이름 또는 yaml 경로")
   parser.add_argument("--provider", default=providers.DEFAULT, help="그림을 만들 제공자")
   parser.add_argument("--dry-run", action="store_true", help="부르지 말고 견적만")
   parser.add_argument("--force", action="store_true", help="검수를 건너뛴다")
   parser.add_argument("--json", action="store_true", dest="as_json", help="사람용 표 대신 JSON")
   parser.add_argument("--directions", type=int, help="방향 수를 덮어쓴다")

   subs = parser.add_subparsers(dest="command", required=True)
   _add_profile(subs)
   _add_normalize(subs)
   _add_anchors(subs)
   _add_check(subs)
   _add_bake(subs)
   _add_layers(subs)
   _add_tile(subs)
   _add_ui(subs)
   _add_provider(subs)
   return parser


def _add_profile(subs) -> None:
   node = subs.add_parser("profile", help="프로필 보기")
   inner = node.add_subparsers(dest="sub", required=True)
   inner.add_parser("show", help="겹쳐진 최종 값을 찍는다", parents=[COMMON])


def _add_normalize(subs) -> None:
   node = subs.add_parser("normalize", help="① 규격 맞추기", parents=[COMMON])
   node.add_argument("--in", dest="in_dir", required=True)
   node.add_argument("--out", dest="out_dir", required=True)
   node.add_argument("--anim", action="append", help="이 애니메이션만. 여러 번 줄 수 있다")


def _add_anchors(subs) -> None:
   node = subs.add_parser("anchors", help="② 앵커 뽑기", parents=[COMMON])
   node.add_argument("--in", dest="in_dir", required=True, help="규격 맞춘 시트 폴더")
   node.add_argument("--rig", required=True)
   node.add_argument("--from", dest="source", default="marker", choices=["marker", "skeleton"])
   node.add_argument("--markers", help="마커 시트 폴더 (marker 일 때)")
   node.add_argument("--skeleton", help="estimate-skeleton JSON (skeleton 일 때)")
   node.add_argument("--out", dest="out_file", required=True)


def _add_check(subs) -> None:
   node = subs.add_parser("check", help="③ 검수", parents=[COMMON])
   node.add_argument("--in", dest="in_dir", required=True, help="frames.json 이 있는 폴더, 또는 낱장 PNG 폴더·파일")
   node.add_argument("--report", dest="report", required=True)
   node.add_argument("--no-ramps", dest="no_ramps", action="store_true", help="램프 규칙을 건너뛴다 (팔레트 미정일 때)")


def _add_bake(subs) -> None:
   node = subs.add_parser("bake", help="④ 굽기", parents=[COMMON])
   node.add_argument("--in", dest="in_dir", required=True)
   node.add_argument("--out", dest="out_dir", required=True)
   node.add_argument("--namespace", default="Game.Art")


def _add_layers(subs) -> None:
   node = subs.add_parser("layers", help="LPC 층 겹치기", parents=[COMMON])
   node.add_argument("--in", dest="in_dir", required=True)
   node.add_argument("--out", dest="out_dir", required=True)
   node.add_argument("--rig", required=True)
   node.add_argument("--anim", action="append")


def _add_tile(subs) -> None:
   node = subs.add_parser("tile", help="타일 명령 묶음")
   inner = node.add_subparsers(dest="sub", required=True)

   grow = inner.add_parser("blob", help="② 템플릿 6장 → 47장", parents=[COMMON])
   grow.add_argument("--in", dest="in_dir", required=True)
   grow.add_argument("--out", dest="out_dir", required=True)

   put = inner.add_parser("place", help="③ 배치 (DeBroglie)", parents=[COMMON])
   put.add_argument("--tileset", required=True, help="tileset.json")
   put.add_argument("--rules", required=True)
   put.add_argument("--size", required=True, help="예 : 64x64")
   put.add_argument("--out", dest="out_dir", required=True)
   put.add_argument("--exe", help="DeBroglie 실행 파일")
   put.add_argument("--seed", type=int)

   to_ldtk = inner.add_parser("ldtk", help="맵 JSON → LDtk 파일", parents=[COMMON])
   to_ldtk.add_argument("--map", dest="map_file", required=True)
   to_ldtk.add_argument("--tileset", required=True)
   to_ldtk.add_argument("--out", dest="out_file", required=True)


def _add_ui(subs) -> None:
   node = subs.add_parser("ui", help="UI 명령 묶음")
   inner = node.add_subparsers(dest="sub", required=True)

   draw = inner.add_parser("frame", help="①ㄱ 프레임 그리기", parents=[COMMON])
   draw.add_argument("--kind", required=True, choices=list(ui_frame_mod.KINDS))
   draw.add_argument("--size", help="예 : 16x16. 안 주면 프로필의 ui.frame.source")
   draw.add_argument("--out", dest="out_dir", required=True)

   bring = inner.add_parser("import", help="①ㄴ .9.png 들여오기", parents=[COMMON])
   bring.add_argument("--in", dest="in_dir", required=True)
   bring.add_argument("--out", dest="out_dir", required=True)

   cut = inner.add_parser("icons", help="①ㄷ 아이콘 들이기", parents=[COMMON])
   cut.add_argument("--in", dest="in_file", required=True, help="아이콘 시트 PNG, 또는 낱장 PNG 폴더")
   cut.add_argument("--cell", type=int, help="시트를 자를 칸 크기. 시트 파일에만 쓴다")
   cut.add_argument("--family", help="아이콘 가족 이름. 안 주면 시트·폴더 이름")
   cut.add_argument("--fit", type=int, help="낱장을 N×N 가운데에 맞춘다. 폴더에만 쓰고, 제자리면 원본을 덮어쓴다")
   cut.add_argument("--out", dest="out_dir", required=True)

   look = inner.add_parser("check", help="② UI 검수", parents=[COMMON])
   look.add_argument("--in", dest="in_dir", required=True)
   look.add_argument("--report", required=True)
   look.add_argument("--manifest", default=None, help="구워 둔 ui_manifest.json. 주면 PPU 를 대조한다")

   burn = inner.add_parser("bake", help="③ UI 굽기", parents=[COMMON])
   burn.add_argument("--in", dest="in_dir", required=True)
   burn.add_argument("--out", dest="out_dir", required=True)
   burn.add_argument("--namespace", default="Game.UI")
   burn.add_argument("--assets-root", dest="assets_root", default=None)

   page = inner.add_parser("screen", help="화면 JSON → UXML · USS", parents=[COMMON])
   page.add_argument("--spec", required=True)
   page.add_argument("--out", dest="out_dir", required=True)
   page.add_argument("--manifest", default=None)
   page.add_argument("--assets-root", dest="assets_root", default=None)

   glyph = inner.add_parser("font", help="글자 뽑기", parents=[COMMON])
   glyph.add_argument("--scan", action="append", help="훑을 폴더. 뿌리 아래 상대경로만. 여러 번 줄 수 있다")
   glyph.add_argument("--scan-root", dest="scan_root", default=None, help="훑을 뿌리. 안 주면 프로필 파일 폴더")
   glyph.add_argument("--out", dest="out_file", required=True)


def _add_provider(subs) -> None:
   node = subs.add_parser("provider", help="제공자")
   inner = node.add_subparsers(dest="sub", required=True)
   inner.add_parser("list", help="켜진 제공자 목록", parents=[COMMON])

   make = inner.add_parser("make", help="그림 만들기 요청", parents=[COMMON])
   make.add_argument("--kind", required=True, choices=list(providers.KINDS))
   make.add_argument("--spec", help="ProviderRequest JSON 파일")
   make.add_argument("--out", dest="out_dir", required=True)


def _profile(args):
   overrides = {}
   if args.directions:
      overrides["axes.directions"] = args.directions
   return load_profile(args.profile, overrides)


def run(args) -> dict:
   table = {
      "profile": _run_profile,
      "normalize": _run_normalize,
      "anchors": _run_anchors,
      "check": _run_check,
      "bake": _run_bake,
      "layers": _run_layers,
      "tile": _run_tile,
      "ui": _run_ui,
      "provider": _run_provider,
   }
   return table[args.command](args)


def _run_profile(args) -> dict:
   return _profile(args).as_dict()


def _run_normalize(args) -> dict:
   return normalize_mod.normalize(_profile(args), args.in_dir, args.out_dir, args.anim)


def _run_anchors(args) -> dict:
   prof = _profile(args)
   in_dir = Path(args.in_dir)
   if args.source == "skeleton":
      if not args.skeleton:
         raise ArtToolError("--from skeleton 이면 --skeleton 파일이 있어야 한다")
      data = anchors_mod.from_skeleton_json(prof, read_json(args.skeleton), args.rig)
   else:
      if not args.markers:
         raise ArtToolError("--from marker 이면 --markers 폴더가 있어야 한다")
      index = read_json(in_dir / "frames.json")
      data = anchors_mod.extract(prof, index, args.markers, args.rig, art_dir=in_dir)
   out = jailed_output(args.out_file)
   write_json(out, data)
   return {"out": str(out), "points": len(data["points"])}


def _run_check(args) -> dict:
   report = check_mod.run(_profile(args), args.in_dir, args.no_ramps)
   write_json(jailed_output(args.report), report)
   return report


def _run_bake(args) -> dict:
   return bake_mod.bake(_profile(args), args.in_dir, args.out_dir, args.namespace, args.force)


def _run_layers(args) -> dict:
   return layers_mod.compose_sheets(_profile(args), args.rig, args.in_dir, args.out_dir, args.anim)


def _run_tile(args) -> dict:
   if args.sub == "blob":
      data = blob_mod.build(_profile(args), args.in_dir, args.out_dir)
      return {"out": args.out_dir, "count": data["count"], "tile_size": data["tile_size"]}
   if args.sub == "place":
      return place_mod.place(
         _profile(args), args.tileset, args.rules, args.size, args.out_dir, args.exe, args.seed, args.dry_run
      )
   out = jailed_output(args.out_file)
   ldtk_mod.write_ldtk(read_json(args.map_file), read_json(args.tileset), out)
   return {"out": str(out)}


def _run_ui(args) -> dict:
   prof = _profile(args)
   table = {
      "frame": _ui_frame,
      "import": _ui_import,
      "icons": _ui_icons,
      "check": _ui_check,
      "bake": _ui_bake,
      "screen": _ui_screen,
      "font": _ui_font,
   }
   return table[args.sub](prof, args)


def _ui_frame(prof, args) -> dict:
   size = place_mod.parse_size(args.size) if args.size else prof.ui_frame_size()
   return ui_frame_mod.build(prof, args.kind, size, args.out_dir)


def _ui_import(prof, args) -> dict:
   return ui_import_mod.import_dir(prof, args.in_dir, args.out_dir)


def _ui_icons(prof, args) -> dict:
   """길이 둘이라 한쪽에서만 쓰는 인자가 있다. 조용히 무시하지 않고 거절한다."""
   if args.fit is not None and args.fit <= 0:
      raise ArtToolError(f"--fit 은 양수여야 한다 : {args.fit}")
   if Path(args.in_file).is_dir():
      if args.cell is not None:
         raise ArtToolError("--cell 은 시트를 자를 때만 쓴다. --in 이 폴더면 낱장 들이기라 쓸 데가 없다")
      return ui_icons_mod.gather(prof, args.in_file, args.out_dir, args.family, args.fit)
   if args.fit is not None:
      raise ArtToolError("--fit 은 낱장 폴더에만 쓴다. --in 이 시트 파일이면 --cell 로 칸 크기를 준다")
   return ui_icons_mod.cut(prof, args.in_file, args.out_dir, args.cell, args.family)


def _ui_check(prof, args) -> dict:
   report = ui_check_mod.run(args.in_dir, prof, args.manifest)
   write_json(jailed_output(args.report), report)
   return report


def _ui_bake(prof, args) -> dict:
   where = args.assets_root or ui_bake_mod.uss.ASSETS_ROOT
   return ui_bake_mod.bake(prof, args.in_dir, args.out_dir, args.namespace, args.force, where)


def _ui_screen(prof, args) -> dict:
   return ui_screen_mod.build(prof, args.spec, args.out_dir, args.manifest, args.assets_root)


def _ui_font(prof, args) -> dict:
   return ui_font_mod.build(prof, args.scan, jailed_output(args.out_file), args.scan_root)


def _run_provider(args) -> dict:
   if args.sub == "list":
      return {"default": providers.DEFAULT, "providers": providers.describe()}

   spec = read_json(args.spec) if args.spec else {}
   req = providers.ProviderRequest(
      kind=args.kind,
      out_dir=Path(args.out_dir),
      size=tuple(spec.get("size", (64, 64))),
      projection=spec.get("projection", "quarter"),
      directions=int(spec.get("directions", 4)),
      frames=int(spec.get("frames", 1)),
      reference=spec.get("reference"),
      prompt=spec.get("prompt", ""),
      seed=spec.get("seed"),
      dry_run=args.dry_run,
   )
   return providers.get(args.provider).make(req).to_json()


def _print_human(data) -> None:
   if isinstance(data, dict) and isinstance(data.get("providers"), list):
      for row in data["providers"]:
         mark = "켜짐" if row["available"] else "꺼짐"
         print(f"{row['name']:<10} {mark:<4} {', '.join(row['capabilities'])}")
      return
   if isinstance(data, dict) and isinstance(data.get("checked"), dict) and data["checked"].get("mode") == "loose":
      print("낱장 모드")
   print(json.dumps(data, ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> int:
   args = build_parser().parse_args(argv)
   try:
      result = run(args)
   except ArtToolError as exc:
      print(f"오류 : {exc}", file=sys.stderr)
      return exc.exit_code
   except Exception as exc:
      # 여기까지 온 것은 우리가 예상 못 한 것이다. 역추적은 ARTTOOL_DEBUG=1 일 때만 보여준다.
      if os.environ.get("ARTTOOL_DEBUG") == "1":
         traceback.print_exc()
      print(f"오류 : {type(exc).__name__} : {exc}", file=sys.stderr)
      return EXIT_ERROR

   if args.as_json:
      print(json.dumps(result, ensure_ascii=False, indent=2))
   else:
      _print_human(result)
   if isinstance(result, dict) and result.get("status") == "fail":
      return EXIT_CHECK_FAIL
   return EXIT_OK


if __name__ == "__main__":
   raise SystemExit(main())
