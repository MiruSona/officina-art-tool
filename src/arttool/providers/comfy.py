"""ComfyUI HTTP 클라이언트. 그림 처리는 모른다 — bytes 와 JSON 만 주고받는다.

호출 차례 · 실패 때 종료 코드는 `Docs/Design/2026-10-07-provider-local설계.md` 4-3 표를 따른다.
"""

from __future__ import annotations

import http.client
import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from ..errors import ArtToolError, ServerUnreachable, UsageError
from .comfy_text import clean, history_error, multipart, prompt_error

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
MAX_IMAGE_BYTES = 64 * 1024 * 1024
MAX_JSON_BYTES = 64 * 1024 * 1024   # object_info 는 노드가 많으면 수 MB 라 그림과 같은 상한을 쓴다
STATS_TIMEOUT_S = 5.0
CALL_TIMEOUT_S = 60.0
POLL_RETRIES = 2   # wait 폴링이 응답 끊김을 몇 번까지 견디나


def parse_endpoint(endpoint: str) -> tuple[str, str]:
   """주소를 검사해 (끝 / 뗀 주소, 로그용 host:port) 를 돌려준다. http · https 만 받는다."""
   parts = urllib.parse.urlsplit(endpoint.strip())
   if parts.scheme not in ("http", "https") or not parts.hostname:
      raise UsageError("ComfyUI 주소는 http:// 나 https:// 로 시작해야 한다")
   try:
      port = parts.port
   except ValueError:
      raise UsageError("ComfyUI 주소의 포트가 숫자가 아니다") from None
   host = parts.hostname
   if port:
      host = f"{host}:{port}"
   return endpoint.strip().rstrip("/"), host


class ResponseCut(ArtToolError):
   """연결은 됐는데 응답을 읽다 끊겼다. 서버가 없는 것(종료 5)과 갈라 종료 1 로 둔다."""


class ComfyClient:
   def __init__(self, endpoint: str, timeout_s: float = 600.0, poll_s: float = 1.0):
      self.base, self.host = parse_endpoint(endpoint)
      self.timeout_s = timeout_s
      self.poll_s = poll_s
      # 같은 망의 서버를 부르므로 환경변수 · 레지스트리의 프록시를 타지 않는다
      self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

   def system_stats(self) -> dict:
      return self._json("GET", "/system_stats", timeout=STATS_TIMEOUT_S)

   def object_info(self) -> dict:
      return self._json("GET", "/object_info")

   def require_nodes(self, class_types: list[str]) -> None:
      known = self.object_info()
      missing = [name for name in class_types if name not in known]
      if missing:
         raise ArtToolError(clean(f"이 노드가 서버에 없다 : {', '.join(missing)}"))

   def upload_image(self, data: bytes) -> str:
      """그림 한 장을 input 폴더에 올리고 LoadImage 에 넣을 이름을 돌려준다."""
      name = f"arttool_{uuid.uuid4().hex[:12]}.png"
      boundary = uuid.uuid4().hex
      headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
      answer = self._json("POST", "/upload/image", body=multipart(boundary, name, data), headers=headers)
      saved = str(answer.get("name", name))
      subfolder = answer.get("subfolder") or ""
      if subfolder:
         return f"{subfolder}/{saved}"
      return saved

   def queue_prompt(self, workflow: dict) -> str:
      payload = {"prompt": workflow, "client_id": uuid.uuid4().hex}
      body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
      headers = {"Content-Type": "application/json"}
      try:
         answer = self._json("POST", "/prompt", body=body, headers=headers, raw_http=True)
      except urllib.error.HTTPError as exc:
         raise ArtToolError(prompt_error(exc.code, _read_error_body(exc))) from None
      prompt_id = answer.get("prompt_id")
      if not prompt_id:
         raise ArtToolError(f"ComfyUI 가 prompt_id 를 안 줬다 : {self.host}")
      return str(prompt_id)

   def wait(self, prompt_id: str) -> dict:
      """끝날 때까지 /history 를 폴링해 그 판의 기록을 돌려준다. 시간 초과 · Ctrl+C 면 우리 판을 치우고 멈춘다."""
      try:
         return self._poll(prompt_id)
      except KeyboardInterrupt:
         self.cancel(prompt_id)
         raise

   def cancel(self, prompt_id: str) -> None:
      """줄에서 우리 판을 지우고, 이미 돌고 있으면 그 판만 멈춘다. 남의 판은 안 건드린다. 실패해도 조용히 넘어간다."""
      headers = {"Content-Type": "application/json"}
      try:
         self._call("POST", "/queue", body=json.dumps({"delete": [prompt_id]}).encode("utf-8"), headers=headers)
         running = self._json("GET", "/queue").get("queue_running") or []
         ours = any(isinstance(item, list) and len(item) > 1 and item[1] == prompt_id for item in running)
         if ours:
            body = json.dumps({"prompt_id": prompt_id}).encode("utf-8")
            self._call("POST", "/interrupt", body=body, headers=headers)
      except ArtToolError:
         pass   # 치우기는 덤이다. 실패해도 원래 오류를 그대로 낸다

   def fetch_image(self, filename: str, subfolder: str = "", kind: str = "output") -> bytes:
      query = urllib.parse.urlencode({"filename": filename, "subfolder": subfolder, "type": kind})
      data = self._call("GET", "/view?" + query, limit=MAX_IMAGE_BYTES)
      if not data.startswith(PNG_SIGNATURE):
         raise ArtToolError("ComfyUI 가 준 그림이 PNG 가 아니다")
      return data

   def _poll(self, prompt_id: str) -> dict:
      deadline = time.monotonic() + self.timeout_s
      path = "/history/" + urllib.parse.quote(prompt_id, safe="")
      cuts = 0
      while True:
         try:
            entry = self._json("GET", path).get(prompt_id)
         except ResponseCut:
            cuts += 1
            if cuts > POLL_RETRIES:
               raise
            entry = None
         if entry:
            status = entry.get("status") or {}
            if status.get("status_str") == "error":
               raise ArtToolError(f"ComfyUI 판이 실패했다 : {history_error(status)}")
            if status.get("completed", True):
               return entry
         if time.monotonic() >= deadline:
            self.cancel(prompt_id)
            raise ArtToolError(f"시간 초과 : {self.timeout_s:g}초 안에 안 끝났다 (우리 판을 줄에서 치웠다)")
         time.sleep(self.poll_s)

   def _json(self, method, path, body=None, headers=None, timeout=CALL_TIMEOUT_S, raw_http=False) -> dict:
      data = self._call(method, path, body=body, headers=headers, timeout=timeout, raw_http=raw_http)
      shown = path.split("?")[0]
      try:
         answer = json.loads(data.decode("utf-8")) if data else {}
      except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
         raise ArtToolError(f"ComfyUI 응답이 JSON 이 아니다 : {method} {shown}") from None
      if not isinstance(answer, dict):
         raise ArtToolError(f"ComfyUI 응답 꼴이 다르다 : {method} {shown}")
      return answer

   def _call(self, method, path, body=None, headers=None, timeout=CALL_TIMEOUT_S,
             limit=MAX_JSON_BYTES, raw_http=False) -> bytes:
      """요청 하나. 연결이 안 되면 종료 5, 읽다 끊기면 종료 1(ResponseCut), HTTP 오류면 종료 1.

      raw_http 면 HTTPError 를 부른 쪽에 넘긴다.
      """
      request = urllib.request.Request(self.base + path, data=body, headers=headers or {}, method=method)
      shown = path.split("?")[0]
      try:
         response = self._opener.open(request, timeout=timeout)
      except urllib.error.HTTPError as exc:
         if raw_http:
            raise
         raise ArtToolError(f"ComfyUI 가 오류를 냈다 : {method} {shown} → {exc.code}") from None
      except urllib.error.URLError as exc:
         raise ServerUnreachable(f"ComfyUI 에 닿지 않는다 : {self.host} (ARTTOOL_LOCAL_ENDPOINT 를 본다)") from exc
      except (http.client.HTTPException, socket.timeout, ConnectionError, OSError):
         raise ResponseCut(f"ComfyUI 응답이 끊겼다 : {method} {shown}") from None
      with response:
         try:
            return _read_capped(response, limit)
         except (http.client.HTTPException, socket.timeout, ConnectionError, OSError):
            raise ResponseCut(f"ComfyUI 응답이 끊겼다 : {method} {shown}") from None


def _read_capped(response, limit: int) -> bytes:
   length = response.headers.get("Content-Length")
   if length and length.isdigit() and int(length) > limit:
      raise ArtToolError(f"ComfyUI 응답이 너무 크다 : {int(length)} 바이트 (상한 {limit})")
   data = response.read(limit + 1)
   if len(data) > limit:
      raise ArtToolError(f"ComfyUI 응답이 너무 크다 (상한 {limit} 바이트)")
   # read(n) 은 연결이 먼저 닫혀도 받은 만큼만 조용히 돌려준다. 약속한 길이와 견줘 끊김을 잡는다
   if length and length.isdigit() and len(data) < int(length):
      raise http.client.IncompleteRead(data, int(length) - len(data))
   return data


def _read_error_body(exc: urllib.error.HTTPError) -> bytes:
   try:
      return exc.read(MAX_JSON_BYTES)
   except (http.client.HTTPException, OSError):
      return b""
