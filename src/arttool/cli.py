"""명령 등록만 한다. 셈은 다른 모듈이 하고 여기서는 인자를 넘겨 부르기만 한다.

새 명령(2026-10-04 개선 설계)은 늦게 부른다 — 아래 `LATE` 표. 각 갈래는 표의 모듈 파일과 함수만 만들면 바로 붙는다.
모듈이나 함수가 아직 없으면 「아직 구현 안 됨」을 종료 2 로 알린다.

약속 (설계 문서 12-1 과 같다) :
- 함수 꼴은 `run(args) -> dict`. `args` 는 argparse 결과 그대로다. 인자 이름(dest)은 `_add_*` 함수에 있다.
- 프로필이 필요하면 `arttool.profile.load_profile_args(args)` 로 읽는다(`--profile` · `--directions` 처리).
- 돌려주는 dict 의 `status` 는 `ok` · `warn` · `fail`. `fail` 이면 종료 4, 나머지는 0.
- `args.report` 가 있으면 돌려준 dict 를 cli 가 그 파일에 쓴다. 모듈은 보고 파일을 따로 안 쓴다.
- 잘못된 인자는 `UsageError`(종료 2), 그 밖의 막힘은 `ArtToolError`(종료 1)로 올린다.

| 명령 | 모듈.함수 |
| --- | --- |
| `cutout` | `arttool.edit.cutout.run` |
| `trim` | `arttool.edit.trim.run` |
| `ui preview` | `arttool.ui.ninepatch.run_preview` |
| `sheet` | `arttool.sheet.run` |
| `template list` · `show` · `render` | `arttool.template.run.run` (`args.sub` 로 가른다) |
| `style extract` | `arttool.style.extract.run` |
| `layers diff` · `mask` · `view` · `check` · `export` | `arttool.sprite.layerops.run` (`args.sub` 로 가른다) |
| `intake` | `arttool.intake.run` |
| `layers compose` | 여기서 `sprite.layers.compose_sheets` 를 바로 부른다 (옛 `layers`) |
| `check --no-warn · --mode · --template` | `check.run(prof, in_dir, no_ramps, *, warn, mode, template)` — 그 세 칸을 받게 되면 넘긴다 |
"""

from __future__ import annotations

import argparse
import importlib
import inspect
import json
import os
import sys
import traceback
from pathlib import Path

from . import bake as bake_mod
from . import check as check_mod
from . import providers
from .errors import EXIT_CHECK_FAIL, EXIT_ERROR, EXIT_OK, ArtToolError, UsageError
from .jsonio import read_json, write_json
from .paths import guard_overwrite, jailed_output
from .profile import load_profile_args
from .sprite import anchors as anchors_mod
from .sprite import layers as layers_mod
from .sprite import normalize as normalize_mod
from .sprite import recolor as recolor_mod
from .sprite import split as split_mod
from .tiles import blob as blob_mod
from .tiles import inspect as inspect_mod
from .tiles import ldtk as ldtk_mod
from .tiles import place as place_mod
from .tiles import preview as preview_mod
from .tiles import seam as seam_mod
from .ui import bake_ui as ui_bake_mod
from .ui import check_ui as ui_check_mod
from .ui import font as ui_font_mod
from .ui import frame as ui_frame_mod
from .ui import icons as ui_icons_mod
from .ui import ninepatch as ui_import_mod
from .ui import screen as ui_screen_mod

# (명령, 하위 명령) → (모듈, 함수). 하위 명령이 없는 명령은 None.
LATE: dict[tuple[str, str | None], tuple[str, str]] = {
   ("cutout", None): ("arttool.edit.cutout", "run"),
   ("trim", None): ("arttool.edit.trim", "run"),
   ("ui", "preview"): ("arttool.ui.ninepatch", "run_preview"),
   ("sheet", None): ("arttool.sheet", "run"),
   ("template", "list"): ("arttool.template.run", "run"),
   ("template", "show"): ("arttool.template.run", "run"),
   ("template", "render"): ("arttool.template.run", "run"),
   ("style", "extract"): ("arttool.style.extract", "run"),
   ("layers", "diff"): ("arttool.sprite.layerops", "run"),
   ("layers", "mask"): ("arttool.sprite.layerops", "run"),
   ("layers", "view"): ("arttool.sprite.layerops", "run"),
   ("layers", "check"): ("arttool.sprite.layerops", "run"),
   ("layers", "export"): ("arttool.sprite.layerops", "run"),
   ("intake", None): ("arttool.intake", "run"),
}

# check.run 이 이 세 칸을 키워드로 받게 되면(D 갈래) 새 인자를 넘긴다.
CHECK_NEW_KWARGS = ("warn", "mode", "template")
CHECK_MODES = ("auto", "sprite", "background")
CUTOUT_KEY_HELP = "edge(네 변에서 번짐, 기본) · corner(네 모서리에서 번짐) · #RRGGBB(그 색을 그림 전체에서)"


def _utf8_streams() -> None:
   """파이프 · 파일로 나갈 때도 UTF-8 로 쓴다. Windows 는 기본이 cp949 라 한글이 깨지고 `—` 에서 죽는다.

   PYTHONIOENCODING 을 준 사람은 그 값을 따른다(비상구). backslashreplace 라 어떤 글자가 와도 안 죽는다.
   """
   if os.environ.get("PYTHONIOENCODING"):
      return
   for stream in (sys.stdout, sys.stderr):
      reconfigure = getattr(stream, "reconfigure", None)
      if reconfigure is None:
         continue
      try:
         reconfigure(encoding="utf-8", errors="backslashreplace")
      except (ValueError, OSError):
         # 이미 읽기 · 쓰기가 시작돼 바꿀 수 없는 흐름이면 그대로 둔다.
         continue


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
   _add_split(subs)
   _add_recolor(subs)
   _add_tile(subs)
   _add_ui(subs)
   _add_provider(subs)
   _add_cutout(subs)
   _add_trim(subs)
   _add_sheet(subs)
   _add_template(subs)
   _add_style(subs)
   _add_intake(subs)
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
   node.add_argument("--no-warn", dest="no_warn", action="store_true", help="이번 한 판만 경고 검사를 끈다 (status 는 그대로)")
   node.add_argument("--mode", dest="mode", default="auto", choices=list(CHECK_MODES), help="배경 판정을 덮어쓴다 (기본 auto)")
   node.add_argument("--template", dest="template", help="template render 가 낸 template.json. 그 값을 검사 문턱으로 겹친다")


def _add_bake(subs) -> None:
   node = subs.add_parser("bake", help="④ 굽기", parents=[COMMON])
   node.add_argument("--in", dest="in_dir", required=True)
   node.add_argument("--out", dest="out_dir", required=True)
   node.add_argument("--namespace", default="Game.Art")


def _add_layers(subs) -> None:
   node = subs.add_parser("layers", help="겹 묶음 명령 (compose · diff · mask · view · check · export)")
   inner = node.add_subparsers(dest="sub", required=True)

   stack = inner.add_parser("compose", help="프로필 rig 의 layer_order 로 층을 겹친다 (옛 `layers`)", parents=[COMMON])
   stack.add_argument("--in", dest="in_dir", required=True)
   stack.add_argument("--out", dest="out_dir", required=True)
   stack.add_argument("--rig", required=True)
   stack.add_argument("--anim", action="append")

   diff = inner.add_parser("diff", help="기본체와 inpaint 결과의 차이로 겹을 뗀다", parents=[COMMON])
   diff.add_argument("--base", dest="base", required=True, help="기본체 PNG")
   diff.add_argument("--in", dest="in_dir", required=True, help="inpaint 결과 폴더. 파일 이름 = 겹 이름")
   diff.add_argument("--out", dest="out_dir", required=True, help="겹 묶음 폴더")
   diff.add_argument("--template", dest="template", help="template.json. 마스크 밖이 바뀐 칸을 센다")
   diff.add_argument("--carve", dest="carve", default="report", choices=["report", "common", "apply"],
                     help="깎인 윤곽 : report 본체 그대로 · 세기만(기본) · common 모든 겹이 깎은 칸만 뺀다 · apply 하나라도 깎은 칸을 다 뺀다")
   diff.add_argument("--report", dest="report", help="보고 JSON")

   mask = inner.add_parser("mask", help="기본체에서 이 색 칸만 마스크로", parents=[COMMON])
   mask.add_argument("--in", dest="in_file", required=True, help="기본체 PNG")
   mask.add_argument("--colors", dest="colors", required=True, help="#RRGGBB[,#RRGGBB…]")
   mask.add_argument("--grow", dest="grow", type=int, default=0, help="N 칸 넓힌다 (기본 0)")
   mask.add_argument("--out", dest="out_file", required=True, help="마스크 PNG")

   view = inner.add_parser("view", help="겹을 켜고 끄며 합친 그림", parents=[COMMON])
   view.add_argument("--in", dest="in_dir", required=True, help="겹 묶음 폴더")
   pick = view.add_mutually_exclusive_group()
   pick.add_argument("--only", dest="only", help="이 겹만 (쉼표로)")
   pick.add_argument("--hide", dest="hide", help="이 겹을 빼고 (쉼표로)")
   view.add_argument("--each", dest="each", action="store_true", help="겹마다 한 칸 + 합친 것 한 칸")
   view.add_argument("--out", dest="out_file", required=True)
   view.add_argument("--scale", dest="scale", type=int, default=1)
   view.add_argument("--report", dest="report", help="보고 JSON")

   look = inner.add_parser("check", help="겹 묶음 검사 (경고, --original 다름만 fail)", parents=[COMMON])
   look.add_argument("--in", dest="in_dir", required=True, help="겹 묶음 폴더")
   look.add_argument("--original", dest="original", help="합친 결과와 견줄 원본 PNG")
   look.add_argument("--template", dest="template", help="template.json")
   look.add_argument("--report", dest="report", help="보고 JSON")

   ship = inner.add_parser("export", help="합친 한 장 · 겹별 PNG 로 내보내기", parents=[COMMON])
   ship.add_argument("--in", dest="in_dir", required=True, help="겹 묶음 폴더")
   ship.add_argument("--out", dest="out_dir", required=True)
   ship.add_argument("--flat", dest="flat", action="store_true", help="합친 한 장")
   ship.add_argument("--each", dest="each", action="store_true", help="겹별 PNG (캔버스 그대로)")
   ship.add_argument("--trim-common", dest="trim_common", action="store_true", help="겹 전체에 bbox 하나로 잘라 offsets.json")
   ship.add_argument("--anchor", dest="anchor", default=split_mod.ANCHOR_KINDS[0], choices=list(split_mod.ANCHOR_KINDS))
   ship.add_argument("--report", dest="report", help="보고 JSON")


def _add_cutout(subs) -> None:
   node = subs.add_parser("cutout", help="배경 지우기", parents=[COMMON])
   node.add_argument("--in", dest="in_dir", required=True, help="PNG 한 장 또는 폴더(바로 아래 .png)")
   node.add_argument("--out", dest="out_dir", required=True, help="결과 폴더")
   node.add_argument("--key", dest="key", default="edge", help=CUTOUT_KEY_HELP)
   node.add_argument("--tol", dest="tol", type=int, default=10, help="가까운 색 폭. RGB 각 칸 차이의 최댓값 (기본 10)")
   node.add_argument("--shave", dest="shave", type=int, default=0, help="지우기 전에 바깥 N 칸을 투명으로 (기본 0)")
   node.add_argument("--report", dest="report", help="보고 JSON")


def _add_trim(subs) -> None:
   node = subs.add_parser("trim", help="여백 걷기", parents=[COMMON])
   node.add_argument("--in", dest="in_dir", required=True, help="PNG 한 장 또는 폴더(바로 아래 .png)")
   node.add_argument("--out", dest="out_dir", required=True, help="결과 폴더")
   node.add_argument("--pad", dest="pad", type=int, default=0, help="자른 뒤 둘레에 투명 N 칸 (기본 0)")
   node.add_argument("--square", dest="square", action="store_true", help="긴 변에 맞춰 정사각으로 채운다")
   node.add_argument("--common", dest="common", action="store_true", help="폴더 전체에 bbox 하나")
   node.add_argument("--report", dest="report", help="보고 JSON")


def _add_sheet(subs) -> None:
   node = subs.add_parser("sheet", help="비교판 (확대 · 실루엣 · 4색 · 흐림 · 타일)", parents=[COMMON])
   node.add_argument("--in", dest="in_paths", required=True, nargs="+", help="PNG 또는 폴더 여럿. 그림 하나 = 한 줄")
   node.add_argument("--out", dest="out_file", required=True, help="비교판 PNG")
   node.add_argument("--kinds", dest="kinds", default="zoom", help="zoom,silhouette,colors4,blur,tile 중 쉼표로 (기본 zoom)")
   node.add_argument("--scale", dest="scale", default="auto", help="auto 또는 정수 배 (기본 auto)")
   node.add_argument("--tile", dest="tile", type=int, default=2, choices=[2, 4], help="tile 판의 반복 수 (기본 2)")
   node.add_argument("--bg", dest="bg", default="checker", help="checker 또는 #RRGGBB (기본 checker)")
   node.add_argument("--label", dest="label", action="store_true", help="이름 · 크기 · 색 수 딱지")
   node.add_argument("--report", dest="report", help="보고 JSON")


def _add_template(subs) -> None:
   node = subs.add_parser("template", help="템플릿 (그리기 전 밑판)")
   inner = node.add_subparsers(dest="sub", required=True)

   listing = inner.add_parser("list", help="템플릿 목록", parents=[COMMON])
   listing.add_argument("--kind", dest="kind", help="이 kind 만")

   show = inner.add_parser("show", help="크기에 맞춘 값 · 프롬프트 · 순서", parents=[COMMON])
   show.add_argument("name", help="템플릿 이름 또는 JSON 경로")
   show.add_argument("--size", dest="size", help="예 : 32x32 · 32 (정사각)")
   show.add_argument("--preset", dest="preset", help="presets 안 이름")
   show.add_argument("--base", dest="base", help="palette 템플릿 : 바탕색 #RRGGBB")
   show.add_argument("--material", dest="material", help="palette 템플릿 : 재질 프리셋 (cloth · stone · metal …)")

   draw = inner.add_parser("render", help="가이드 겹 · 마스크 · 미리보기 · template.json 쓰기", parents=[COMMON])
   draw.add_argument("name", help="템플릿 이름 또는 JSON 경로")
   draw.add_argument("--size", dest="size", required=True, help="예 : 32x32 · 32 (정사각)")
   draw.add_argument("--out", dest="out_dir", required=True)
   draw.add_argument("--preset", dest="preset", help="presets 안 이름")
   draw.add_argument("--base", dest="base", help="palette 템플릿 : 바탕색 #RRGGBB")
   draw.add_argument("--material", dest="material", help="palette 템플릿 : 재질 프리셋 (cloth · stone · metal …)")
   draw.add_argument("--scale", dest="scale", type=int, help="미리보기 배율")
   draw.add_argument("--over", dest="over", help="가이드를 이 그림 위에 얹은 확대판도 낸다")


def _add_style(subs) -> None:
   node = subs.add_parser("style", help="화풍")
   inner = node.add_subparsers(dest="sub", required=True)

   pull = inner.add_parser("extract", help="기준 그림 폴더에서 화풍 뽑기", parents=[COMMON])
   pull.add_argument("--in", dest="in_dirs", required=True, action="append", help="기준 PNG 폴더. 여러 번 줄 수 있다")
   pull.add_argument("--out", dest="out_dir", required=True)
   pull.add_argument("--name", dest="name", help="결과 이름 (기본 첫 --in 폴더 이름)")
   pull.add_argument("--ramp-len", dest="ramp_len", type=int, help="램프 길이 (기본 프로필 palette.ramp_len)")
   pull.add_argument("--max-colors", dest="max_colors", type=int, default=None, help="전체 색 상한 (기본 64)")
   pull.add_argument("--by-folder", dest="by_folder", action="store_true",
                     help="--in 아래 하위 폴더(종류)마다 따로 뽑고 NAME_kinds.json 요약 표를 낸다")
   pull.add_argument("--mode", dest="mode", default="auto", choices=list(CHECK_MODES))
   pull.add_argument("--with-backgrounds", dest="with_backgrounds", action="store_true", help="배경 그림 색도 팔레트에 섞는다")


def _add_intake(subs) -> None:
   node = subs.add_parser("intake", help="받은 그림 한 번에 손질 (cutout → trim → check → sheet)", parents=[COMMON])
   node.add_argument("--in", dest="in_dir", required=True, help="PNG 한 장 또는 폴더")
   node.add_argument("--out", dest="out_dir", required=True, help="손질한 그림 폴더")
   node.add_argument("--key", dest="key", default="edge", help=CUTOUT_KEY_HELP)
   node.add_argument("--tol", dest="tol", type=int, default=10)
   node.add_argument("--shave", dest="shave", type=int, default=0)
   node.add_argument("--pad", dest="pad", type=int, default=0)
   node.add_argument("--square", dest="square", action="store_true")
   node.add_argument("--template", dest="template", help="template.json (check 에 넘긴다)")
   node.add_argument("--sheet", dest="sheet", help="주면 비교판 PNG 도 낸다")
   node.add_argument("--no-cutout", dest="no_cutout", action="store_true", help="바탕 지우기를 건너뛴다")
   node.add_argument("--no-trim", dest="no_trim", action="store_true", help="여백 걷기를 건너뛴다")
   node.add_argument("--no-check", dest="no_check", action="store_true", help="검수를 건너뛴다")
   node.add_argument("--report", dest="report", help="보고 JSON (넷을 묶은 것)")


def _add_split(subs) -> None:
   node = subs.add_parser("split", help="한 장 → 겹 여러 장 (나누기 표)", parents=[COMMON])
   node.add_argument("--in", dest="in_file", required=True, help="한 장 PNG")
   node.add_argument("--spec", help="나누기 표 split.json")
   node.add_argument("--out", dest="out", required=True, help="겹 폴더. --list-colors 면 색 목록 JSON 파일")
   node.add_argument("--rig", help="주면 프로필 rigs.<rig>.layer_order 와 표의 layers 가 같아야 한다")
   node.add_argument("--min-piece", dest="min_piece", type=int, help=f"떨어진 조각 기본 크기 (기본 {split_mod.DEFAULT_MIN_PIECE})")
   node.add_argument("--list-colors", dest="list_colors", action="store_true", help="나누지 않고 색 목록만 낸다")


def _add_recolor(subs) -> None:
   node = subs.add_parser("recolor", help="겹 + 색표 → N장", parents=[COMMON])
   node.add_argument("--in", dest="in_dir", required=True, help="밑감 겹 폴더")
   node.add_argument("--spec", required=True, help="색표 recolor.json")
   node.add_argument("--out", dest="out_dir", required=True)
   node.add_argument("--sheet", help="구운 그림과 조합을 늘어놓은 미리보기 PNG")
   node.add_argument("--scale", type=int, help="미리보기 배율 (--sheet 와 같이)")


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

   show = inner.add_parser("preview", help="낱장 여러 장 → 실제 칸 수로 조립한 미리보기", parents=[COMMON])
   show.add_argument("--layout", required=True, help="배치표 layout.json (weights+seed 또는 cells)")
   show.add_argument("--in", dest="in_dir", required=True, help="타일 PNG 폴더. 배치표 이름 = 파일 이름")
   show.add_argument("--out", dest="out_file", required=True, help="미리보기 PNG")
   show.add_argument("--scale", type=int, help="배율 (기본 1, NEAREST)")

   look = inner.add_parser("inspect", help="낱장 한 표 (크기 · bbox · 반투명 · 네 변 · 넘친 픽셀)", parents=[COMMON])
   look.add_argument("--in", dest="in_dir", required=True, help="타일 PNG 폴더 또는 PNG 한 장")
   look.add_argument("--report", required=True)
   look.add_argument("--size", type=int, help="타일 한 변. 안 주면 프로필 tiles.size")

   join = inner.add_parser("seam", help="이음매 검사 (3×3 이어 붙이기)", parents=[COMMON])
   join.add_argument("--in", dest="in_dir", required=True, help="타일 PNG 폴더 또는 PNG 한 장")
   join.add_argument("--report", required=True)
   join.add_argument("--k", type=float, default=seam_mod.DEFAULT_K, help=f"이음 줄 차이가 안쪽 평균의 몇 배를 넘으면 실패 (기본 {seam_mod.DEFAULT_K})")
   join.add_argument("--pairs", action="store_true", help="변종끼리 모든 순서쌍(A 오른쪽 ↔ B 왼쪽, A 아래 ↔ B 위)도 본다")
   join.add_argument("--sheet", help="3×3 으로 이은 그림을 늘어놓은 PNG")
   join.add_argument("--scale", type=int, help="--sheet 배율")


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

   stretch = inner.add_parser("preview", help="안내선 없는 9조각을 늘려 본다", parents=[COMMON])
   stretch.add_argument("--in", dest="in_file", required=True, help="판넬 PNG (.9.png 면 --border 를 빼도 된다)")
   stretch.add_argument("--border", dest="border", help="N 또는 L,B,R,T ([왼, 아래, 오른, 위])")
   stretch.add_argument("--size", dest="size", required=True, help="WxH[,WxH…] 여럿이면 옆으로 나란히")
   stretch.add_argument("--out", dest="out_file", required=True)
   stretch.add_argument("--mode", dest="mode", default="stretch", choices=["stretch", "tile"], help="stretch(Unity Sliced, 기본) · tile")
   stretch.add_argument("--scale", dest="scale", type=int, default=1, help="배율 (기본 1)")


def _add_provider(subs) -> None:
   node = subs.add_parser("provider", help="제공자")
   inner = node.add_subparsers(dest="sub", required=True)
   inner.add_parser("list", help="켜진 제공자 목록", parents=[COMMON])

   make = inner.add_parser("make", help="그림 만들기 요청", parents=[COMMON])
   make.add_argument("--kind", required=True, choices=list(providers.KINDS))
   make.add_argument("--spec", help="ProviderRequest JSON 파일")
   make.add_argument("--out", dest="out_dir", required=True)


def _profile(args):
   return load_profile_args(args)


def _command_key(args) -> tuple[str, str | None]:
   return args.command, getattr(args, "sub", None)


def _import_late(module_name: str, label: str):
   """모듈을 부를 때 읽는다. 그 모듈(또는 그 위 꾸러미)이 아직 없을 때만 「아직 구현 안 됨」으로 바꾼다.

   모듈 안에서 다른 것이 없어 난 ModuleNotFoundError 는 진짜 오류라 그대로 올린다.
   """
   try:
      return importlib.import_module(module_name)
   except ModuleNotFoundError as exc:
      missing = exc.name or ""
      if missing and (module_name == missing or module_name.startswith(missing + ".")):
         raise UsageError(f"아직 구현 안 됨 : {label} ({module_name} 이 없다)") from exc
      raise


def _run_late(args, module_name: str, func_name: str) -> dict:
   label = " ".join(part for part in _command_key(args) if part)
   func = getattr(_import_late(module_name, label), func_name, None)
   if not callable(func):
      raise UsageError(f"아직 구현 안 됨 : {label} ({module_name}.{func_name} 이 없다)")
   result = func(args)
   report = getattr(args, "report", None)
   if report and isinstance(result, dict):
      write_json(jailed_output(report), result)
   return result


# --report 와 견줄 인자들 — 읽는 파일 · 쓰는 그림. 보고 JSON 이 이 중 하나를 덮으면 안 된다 (리뷰 R1-M5)
REPORT_GUARDED = ("in_dir", "in_file", "base", "original", "template", "spec", "manifest", "layout", "tileset",
                  "rules", "map_file", "skeleton", "markers", "out_file", "out_dir", "sheet", "out")


def _guard_report(args) -> None:
   """`--report` 는 `.json` 만 받고, 입력 · 출력 경로와 같으면 거절한다. 명령을 돌리기 **전에** 본다.

   PNG 를 --report 로 주면 원본 그림이 JSON 으로 바뀌던 사고를 막는다. 같은 경로 견주기는 `paths.guard_overwrite` 한 곳을 쓴다.
   """
   report = getattr(args, "report", None)
   if not report:
      return
   if Path(str(report)).suffix.lower() != ".json":
      raise UsageError(f"--report 는 .json 파일만 받는다 : {report}")
   reads = []
   for name in REPORT_GUARDED:
      value = getattr(args, name, None)
      for one in value if isinstance(value, (list, tuple)) else [value]:
         if isinstance(one, (str, os.PathLike)):
            reads.append(one)
   guard_overwrite([report], reads, "--report")


def run(args) -> dict:
   _guard_report(args)
   late = LATE.get(_command_key(args))
   if late is not None:
      return _run_late(args, *late)

   table = {
      "profile": _run_profile,
      "normalize": _run_normalize,
      "anchors": _run_anchors,
      "check": _run_check,
      "bake": _run_bake,
      "layers": _run_layers,
      "split": _run_split,
      "recolor": _run_recolor,
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


def _check_takes_new_args() -> bool:
   params = inspect.signature(check_mod.run).parameters
   return all(name in params for name in CHECK_NEW_KWARGS)


def _run_check(args) -> dict:
   extra = {}
   if _check_takes_new_args():
      extra = {"warn": not args.no_warn, "mode": args.mode, "template": args.template}
   elif args.no_warn or args.mode != "auto" or args.template:
      raise UsageError("아직 구현 안 됨 : check --no-warn · --mode · --template")
   report = check_mod.run(_profile(args), args.in_dir, args.no_ramps, **extra)
   write_json(jailed_output(args.report), report)
   return report


def _run_bake(args) -> dict:
   return bake_mod.bake(_profile(args), args.in_dir, args.out_dir, args.namespace, args.force)


def _run_layers(args) -> dict:
   """`layers compose` 만 여기로 온다. 나머지 하위 명령은 LATE 표로 간다."""
   return layers_mod.compose_sheets(_profile(args), args.rig, args.in_dir, args.out_dir, args.anim)


def _run_split(args) -> dict:
   """두 길이 인자를 나눠 쓴다. 한쪽 인자를 다른 길에 주면 조용히 무시하지 않고 거절한다."""
   if args.list_colors:
      if args.spec or args.rig or args.min_piece is not None:
         raise UsageError("--list-colors 는 --spec · --rig · --min-piece 와 같이 못 쓴다")
      return split_mod.run_list_colors(args.in_file, args.out)
   if not args.spec:
      raise UsageError("--spec 나누기 표가 있어야 한다 (색 목록만 보려면 --list-colors)")
   order, prof_name = None, None
   if args.rig:
      prof = _profile(args)
      order, prof_name = layers_mod.layer_order(prof, args.rig), prof.name
   min_piece = split_mod.DEFAULT_MIN_PIECE if args.min_piece is None else args.min_piece
   return split_mod.run(args.in_file, args.spec, args.out, order, args.rig, prof_name, min_piece)


def _run_recolor(args) -> dict:
   return recolor_mod.run(args.in_dir, args.spec, args.out_dir, args.sheet, args.scale)


def _run_tile(args) -> dict:
   if args.sub == "blob":
      data = blob_mod.build(_profile(args), args.in_dir, args.out_dir)
      return {"out": args.out_dir, "count": data["count"], "tile_size": data["tile_size"]}
   if args.sub == "place":
      return place_mod.place(
         _profile(args), args.tileset, args.rules, args.size, args.out_dir, args.exe, args.seed, args.dry_run
      )
   if args.sub == "preview":
      return preview_mod.run(args.layout, args.in_dir, args.out_file, args.scale)
   if args.sub == "inspect":
      report = inspect_mod.run(_profile(args), args.in_dir, args.size)
      write_json(jailed_output(args.report), report)
      return report
   if args.sub == "seam":
      report = seam_mod.run(args.in_dir, args.k, args.pairs, args.sheet, args.scale)
      write_json(jailed_output(args.report), report)
      return report
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
   if isinstance(data, dict) and isinstance(data.get("must_failed"), list) and data["must_failed"]:
      print(f"꼭 지킬 것 어김 {len(data['must_failed'])}건 : {', '.join(map(str, data['must_failed']))}")
   if isinstance(data, dict) and isinstance(data.get("warnings"), list):
      print(f"경고 {len(data['warnings'])}건")
   print(json.dumps(data, ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> int:
   _utf8_streams()
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
