"""`python -m arttool` 로도 부를 수 있게 한다. 설치 연기 시험이 이 길을 쓴다."""

from .cli import main

if __name__ == "__main__":
   raise SystemExit(main())
