"""오류 종류와 종료 코드.

| 코드 | 뜻 |
| --- | --- |
| 0 | 잘 됨 |
| 1 | 일반 오류 |
| 2 | 인자가 잘못됨 |
| 3 | 프로필이 잘못됨 |
| 4 | 검수 실패 |
| 5 | 바깥 실행 파일 없음 |
| 6 | 경로 감옥 위반 |
"""

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_PROFILE = 3
EXIT_CHECK_FAIL = 4
EXIT_NO_EXE = 5
EXIT_PATH = 6


class ArtToolError(Exception):
   """툴이 스스로 내는 오류. 메시지는 한국어 한 줄."""

   exit_code = EXIT_ERROR


class UsageError(ArtToolError):
   exit_code = EXIT_USAGE


class ProfileError(ArtToolError):
   exit_code = EXIT_PROFILE


class CheckFailed(ArtToolError):
   exit_code = EXIT_CHECK_FAIL


class MissingExecutable(ArtToolError):
   exit_code = EXIT_NO_EXE


class PathJailError(ArtToolError):
   exit_code = EXIT_PATH
