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
   return guard_not_folder(safe_join(root, wanted.name))


def guard_not_folder(path: Path) -> Path:
   """파일을 쓸 자리가 이미 있는 폴더면 UsageError. 쓰기 전에 봐서 dry-run 과 진짜 실행이 같이 멈춘다."""
   if path.is_dir():
      raise UsageError(f"파일을 쓸 자리가 이미 있는 폴더다 : {path}. 파일 이름을 준다")
   return path


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


# --- 팔레트 뿌리 ---

PALETTES_ENV = "ARTTOOL_PALETTES"
PALETTES_PREFIX = "$palettes/"


def palettes_root() -> Path | None:
   """환경변수 ARTTOOL_PALETTES 가 가리키는 팔레트 뿌리. 안 켰으면 None.

   믿는 것 : 이 값은 툴을 돌리는 사람이 셸에서 직접 켠 것이다(파일이 아니라서 커밋 · 복사로 따라오지 않는다).
   그래서 감옥을 이 폴더까지 넓혀도 된다고 본다. 대신 절대경로 · 있는 폴더 · 링크 아님만 받는다.
   """
   text = os.environ.get(PALETTES_ENV)
   if not text:
      return None
   raw = Path(text)
   if not raw.is_absolute():
      raise UsageError(f"{PALETTES_ENV} 는 절대경로여야 한다 : {text}")
   if raw.is_symlink():
      raise UsageError(f"{PALETTES_ENV} 가 링크다 : {text}")
   if not raw.is_dir():
      raise UsageError(f"{PALETTES_ENV} 폴더가 없다 : {text}")
   root = resolve_root(raw)
   if root.parent == root:
      # 드라이브 뿌리(C:\ · / · UNC 공유 뿌리)를 믿으면 감옥이 디스크 전체로 넓어진다.
      raise UsageError(f"{PALETTES_ENV} 가 드라이브 뿌리다. 팔레트 폴더를 따로 가리켜야 한다 : {text}")
   return root


def gathered_palettes_root(warnings: list | None = None) -> Path | None:
   """뿌리를 「모을」 때 쓰는 ARTTOOL_PALETTES. 값이 틀리면 그 뿌리만 빼고 경고를 남긴다(실을 자리가 없으면 조용히 뺀다).

   $palettes/ 를 안 쓰는 일까지 환경변수 하나 때문에 죽으면 안 된다. 접두를 실제로 쓰는 자리는 palettes_root() 가 거절한다.
   """
   try:
      return palettes_root()
   except UsageError as exc:
      if warnings is not None:
         from .checks import warning
         warnings.append(warning("palettes.root_ignored", f"{PALETTES_ENV} 를 팔레트 뿌리에서 뺐다 : {exc}"))
      return None


def trusted_ramps(path_text: str, roots, warnings: list | None = None) -> Path | None:
   """template.json 이 적은 램프 절대경로를 믿어도 되는지 본다. 못 믿으면 None (경고 하나 남김).

   template.json 은 작업 폴더의 보통 파일이라 사람이 고치거나 다른 PC 에서 넘어온다.
   그래서 ① 링크까지 푼 실제 경로가 ② 링크 아닌 보통 .json 파일이고 ③ 팔레트 뿌리(roots) 중 하나 아래일 때만 받는다.
   UNC · 다른 드라이브 · '..' 는 ③ 의 접두 비교에서 걸린다(resolve 가 '..' 를 먼저 풀어 둔다).
   """
   raw = Path(str(path_text))
   real = raw.resolve()
   ok = (raw.suffix.casefold() == ".json" and not raw.is_symlink() and is_plain_file(real)
         and any(_under(Path(root), real) for root in roots if root is not None))
   if ok:
      return real
   if warnings is not None:
      from .checks import warning
      warnings.append(warning("template.ramps_outside", f"템플릿의 램프 파일을 못 믿어 프로필 램프로 돌아간다 (팔레트 뿌리 밖 · 링크 · .json 아님 · 없음) : {path_text}"))
   return None
