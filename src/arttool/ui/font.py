"""곁가지 : 글자 뽑기.

대사 텍스트를 훑어 실제로 쓰인 글자만 모은다. 한글 11,172자를 정적 아틀라스 한 장에 못 넣기 때문이다.
JSON·CSV 도 파서 없이 그냥 텍스트로 읽는다. 키 이름 몇 글자가 더 드는 게 파서를 갖는 것보다 싸다.
TMP 폰트 에셋 굽기는 Unity 에디터 몫이라 여기서는 charset.txt 까지만 낸다.
에디터 스크립트(TmpFontBaker.cs)는 ui bake 가 Editor/ 아래에 낸다 - 두 곳에서 내면 같은 타입이 두 벌이 된다.
"""

from __future__ import annotations

from pathlib import Path

from ..errors import ArtToolError
from ..paths import check_relative, ensure_parent, resolve_root, safe_join
from ..profile import Profile, tool_home

BAKER = "TmpFontBaker.cs"
SKIP = {"\n", "\r", "\t", "\x00", "﻿"}


def read_text(path: Path) -> tuple[str, bool]:
   """UTF-8 로 읽고 안 되면 cp949 로 되살린다. 되살렸으면 참을 같이 준다."""
   raw = path.read_bytes()
   try:
      return raw.decode("utf-8-sig"), False
   except UnicodeDecodeError:
      return raw.decode("cp949", errors="replace"), True


def scan_root(prof: Profile, root: str | Path | None) -> Path:
   """훑을 뿌리. --scan-root 가 있으면 그것, 없으면 프로필 파일 폴더, 그것도 없으면 툴 폴더."""
   if root is not None:
      return resolve_root(root)
   if prof.source is not None:
      return resolve_root(prof.source.parent)
   return resolve_root(tool_home())


def collect(scan_dirs: list[str], extensions: list[str], base: Path) -> tuple[set[str], list[str], list[str]]:
   """훑은 글자 · 읽은 파일 목록 · 경고 목록. 뿌리 밖은 안 훑는다."""
   wanted = {str(e).lower() for e in extensions}
   found: set[str] = set()
   files: list[str] = []
   warnings: list[str] = []

   for folder in scan_dirs:
      check_relative(folder)
      root = safe_join(base, folder)
      if not root.is_dir():
         raise ArtToolError(f"훑을 폴더가 없다 : {root}")
      _read_folder(root, wanted, found, files, warnings)

   return found - SKIP, files, warnings


def _read_folder(root: Path, wanted: set[str], found: set[str], files: list[str], warnings: list[str]) -> None:
   for path in sorted(root.rglob("*")):
      if not path.is_file() or path.suffix.lower() not in wanted:
         continue
      text, recovered = read_text(path)
      if recovered:
         warnings.append(f"cp949 로 되살려 읽었다 : {path}")
      found.update(text)
      files.append(str(path))


def charset_text(chars: set[str], always: str) -> str:
   merged = (chars | set(always)) - SKIP
   return "".join(sorted(merged))


def build(prof: Profile, scan_dirs: list[str] | None, out_path: str | Path, root: str | Path | None = None) -> dict:
   font = prof.ui["font"]
   subset = font["subset"]
   folders = scan_dirs or list(subset["scan_dirs"])
   base = scan_root(prof, root)
   chars, files, warnings = collect(folders, list(subset["extensions"]), base)

   text = charset_text(chars, str(subset["always"]))
   if not text:
      raise ArtToolError(f"글자가 0개다. 훑은 파일 {len(files)}개에 글자가 없었다")

   out_file = Path(out_path)
   ensure_parent(out_file)
   out_file.write_text(text + chr(10), encoding="utf-8")

   return {
      "out": str(out_file),
      "chars": len(text),
      "files": len(files),
      "scanned": folders,
      "root": str(base),
      "family": font["family"],
      "native_px": int(font["native_px"]),
      "note": _baker_note(),
      "warnings": warnings,
   }


def _baker_note() -> str:
   """baker 는 ui bake 만 낸다. 여기서도 내면 같은 타입이 두 벌이 되고 네임스페이스도 어긋난다."""
   return f"{BAKER} 는 arttool ui bake 가 Editor/ 아래에 낸다"
