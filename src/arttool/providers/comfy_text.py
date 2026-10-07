"""ComfyUI 와 주고받는 글 손질 : 멀티파트 몸통 만들기 · 서버 오류 메시지를 짧고 안전한 줄로 바꾸기."""

from __future__ import annotations

import json
import unicodedata

MAX_LINE = 200
MAX_LINES = 5


def clean(text: str) -> str:
   """서버가 준 글을 터미널에 찍어도 되게 다듬는다. 제어문자(ESC 포함) 제거 · 줄마다 200자 · 5줄까지."""
   kept = "".join(ch for ch in str(text) if ch == "\n" or unicodedata.category(ch) != "Cc")
   lines = []
   for line in kept.split("\n"):
      if len(line) > MAX_LINE:
         line = line[:MAX_LINE] + "…"
      lines.append(line)
   if len(lines) > MAX_LINES:
      lines = lines[:MAX_LINES] + ["…"]
   return "\n".join(lines).strip()


def multipart(boundary: str, filename: str, data: bytes) -> bytes:
   """/upload/image 용 멀티파트 몸통. 칸은 image(파일) · type=input · overwrite=true."""
   parts = []
   for key, value in (("type", "input"), ("overwrite", "true")):
      field = f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'
      parts.append(field.encode("utf-8"))
   head = (
      f"--{boundary}\r\n"
      f'Content-Disposition: form-data; name="image"; filename="{filename}"\r\n'
      "Content-Type: image/png\r\n\r\n"
   )
   parts.append(head.encode("utf-8") + data + b"\r\n")
   parts.append(f"--{boundary}--\r\n".encode("utf-8"))
   return b"".join(parts)


def prompt_error(code: int, body: bytes) -> str:
   """/prompt 400 의 node_errors 를 「노드 class : 메시지」 조각으로 묶는다."""
   try:
      answer = json.loads(body.decode("utf-8"))
   except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
      return f"ComfyUI 가 워크플로를 거절했다 ({code})"
   if not isinstance(answer, dict):
      return f"ComfyUI 가 워크플로를 거절했다 ({code})"
   parts = []
   node_errors = answer.get("node_errors")
   if isinstance(node_errors, dict):
      for node_id, info in sorted(node_errors.items()):
         parts.extend(_node_lines(node_id, info))
   if not parts:
      error = answer.get("error")
      message = error.get("message", "") if isinstance(error, dict) else ""
      parts.append(str(message) or f"HTTP {code}")
   return "ComfyUI 가 워크플로를 거절했다 : " + clean(" ; ".join(parts))


def _node_lines(node_id: str, info) -> list[str]:
   if not isinstance(info, dict):
      return []
   lines = []
   for err in info.get("errors") or []:
      if isinstance(err, dict):
         line = f"{node_id} {info.get('class_type', '?')} : {err.get('message', '')} {err.get('details', '')}"
         lines.append(line.strip())
   return lines


def history_error(status: dict) -> str:
   for item in status.get("messages") or []:
      if not isinstance(item, list) or len(item) != 2:
         continue
      kind, info = item
      if kind == "execution_error" and isinstance(info, dict):
         return clean(f"{info.get('node_type', '?')} : {str(info.get('exception_message', '')).strip()}")
   return "까닭을 안 알려 줬다"
