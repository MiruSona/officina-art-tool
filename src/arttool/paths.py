"""경로 감옥. 산출물은 정해진 뿌리 밖으로 못 나간다."""

from __future__ import annotations

import os
from pathlib import Path, PureWindowsPath

from .errors import PathJailError, UsageError


def resolve_root(root: str | os.PathLike) -> Path:
   """뿌리를 링크까지 푼 실제 경로로 한 번만 정규화한다.

   폴더는 여기서 안 만든다. 뒤에서 실패하면 빈 폴더가 남기 때문이다.
   첫 쓰기 때 `ensure_parent` 가 만든다.
   """
   return Path(root).resolve()


def _nearest_existing(path: Path) -> Path:
   cur = path
   while True:
      if cur.exists():
         return cur
      parent = cur.parent
      if parent == cur:
         return cur
      cur = parent


def _under(root: Path, real: Path) -> bool:
   root_parts = [p.casefold() for p in root.parts]
   real_parts = [p.casefold() for p in real.parts]
   if len(real_parts) < len(root_parts):
      return False
   return real_parts[: len(root_parts)] == root_parts


def check_relative(rel: str | os.PathLike) -> Path:
   """뿌리 아래로만 갈 수 있는 상대경로인지 본다. 아니면 거절한다."""
   text = str(rel)
   candidate = Path(text)
   # PureWindowsPath 는 'C:foo' 같은 드라이브 상대경로도 drive 를 채운다. 문자열 자리 검사로는 못 잡는다.
   if PureWindowsPath(text).drive or candidate.is_absolute():
      raise PathJailError(f"절대경로·드라이브 경로는 못 쓴다 : {text}")
   if text.startswith(("/", "\\")):
      raise PathJailError(f"절대경로는 못 쓴다 : {text}")
   if ".." in candidate.parts:
      raise PathJailError(f"'..' 로 밖에 나갈 수 없다 : {text}")
   return candidate


def safe_join(root: Path, rel: str | os.PathLike) -> Path:
   """뿌리 아래 경로 하나를 만든다. 밖으로 나가면 거절한다."""
   candidate = check_relative(rel)
   target = root / candidate
   anchor = _nearest_existing(target)

   # 아직 뿌리 아래에 아무것도 없으면 중간에 링크가 낄 자리도 없다.
   if not _under(root, anchor):
      if _under(anchor, root):
         return target
      raise PathJailError(f"뿌리 밖을 가리킨다 : {rel}")

   if not _under(root, anchor.resolve()):
      raise PathJailError(f"뿌리 밖을 가리킨다 : {rel}")
   if anchor != target and anchor.is_symlink():
      raise PathJailError(f"중간 폴더가 링크다 : {rel}")
   return target


def jailed_output(path: str | os.PathLike) -> Path:
   """CLI 가 받은 산출물 파일 경로 하나를 감옥에 태운다. 뿌리는 그 파일의 부모다."""
   wanted = Path(path)
   if ".." in wanted.parts:
      raise PathJailError(f"'..' 가 든 산출물 경로는 못 쓴다 : {path}")
   root = resolve_root(wanted.parent if str(wanted.parent) else ".")
   return safe_join(root, wanted.name)


def ensure_parent(path: Path) -> None:
   path.parent.mkdir(parents=True, exist_ok=True)


def write_text(path: str | os.PathLike, text: str) -> Path:
   """부모 폴더를 만들고 tmp 에 쓴 다음 이름을 바꾼다. 반쯤 쓰인 파일을 남기지 않는다."""
   file = Path(path)
   ensure_parent(file)
   tmp = file.with_name(f"{file.name}.{os.getpid()}.tmp")
   tmp.write_text(text, encoding="utf-8", newline=chr(10))
   os.replace(tmp, file)
   return file


def is_plain_file(path: Path) -> bool:
   if path.is_symlink():
      return False
   return path.is_file()


def same_key(path: str | os.PathLike) -> str:
   """두 경로가 같은 파일인지 견줄 열쇠. 링크를 풀고 윈도 대소문자를 맞춘다."""
   return os.path.normcase(str(Path(path).resolve()))


def guard_overwrite(writes, reads, what: str = "--out") -> None:
   """쓸 경로 가운데 하나라도 읽은 경로와 같으면 UsageError. **아무것도 쓰기 전에** 부른다.

   원본 보호의 한 곳이다 — cutout · trim · intake · sheet · layers · split · ui preview 가 같이 쓴다.
   writes · reads 는 경로 목록(문자열이나 Path). None 은 건너뛴다.
   """
   sources = {same_key(p) for p in reads if p is not None}
   for out in writes:
      if out is not None and same_key(out) in sources:
         raise UsageError(f"{what} 이 원본을 덮어쓴다 : {out}. 다른 자리를 준다")


def guard_outside(writes, folders, what: str = "--out") -> None:
   """쓸 경로가 folders 가운데 하나의 안(그 폴더 자신 포함)이면 UsageError.

   겹 묶음 폴더 안에 미리보기를 쓰거나, 검수할 폴더 안에 비교판을 쓰는 사고를 막는다.
   """
   roots = [Path(f).resolve() for f in folders if f is not None]
   for out in writes:
      if out is None:
         continue
      real = Path(out).resolve()
      for root in roots:
         if _under(root, real):
            raise UsageError(f"{what} 이 읽는 폴더 안이다 : {out} (폴더 {root}). 그 밖에 쓴다")


def png_files(source: Path) -> list[Path]:
   """폴더 바로 아래 PNG 만 이름순으로. 확장자 대소문자는 가리지 않고 하위 폴더는 안 본다.

   check · cutout · trim · ui icons · style extract 가 같이 쓰는 한 곳이다 (sheet 는 링크를 빼는 `is_plain_file` 을 따로 쓴다).
   """
   return sorted(p for p in source.iterdir() if p.is_file() and p.suffix.lower() == ".png")
