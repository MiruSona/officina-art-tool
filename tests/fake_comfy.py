"""시험용 가짜 ComfyUI. 127.0.0.1 의 빈 포트에 스레드로 띄우고, 부른 길 · 받은 워크플로를 기록한다.

결과 그림은 시드로 만든 512 무작위 PNG 다 — 원본과 어디든 다른 「날것」 흉내라 inpaint 의 밖 0 을 세게 시험한다.
"""

from __future__ import annotations

import io
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import numpy as np
from PIL import Image

PNG_STUB = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def noise_png(seed: int, size: int = 512) -> bytes:
   rng = np.random.default_rng(seed)
   arr = rng.integers(0, 256, size=(size, size, 3), dtype=np.uint8)
   buffer = io.BytesIO()
   Image.fromarray(arr, mode="RGB").save(buffer, format="PNG")
   return buffer.getvalue()


class FakeState:
   """가짜 서버가 어떻게 답할지와 무엇을 받았는지. 시험이 칸을 바꿔 행동을 고른다."""

   def __init__(self):
      self.calls: list[tuple[str, str]] = []
      self.bodies: dict[str, bytes] = {}
      self.prompts: list[dict] = []    # /prompt 로 받은 워크플로 차례대로
      self.uploads: list[bytes] = []
      self.nodes = {name: {} for name in (
         "KSampler", "SaveImage", "LoadImage", "UNETLoader", "CLIPLoader", "VAELoader", "LoraLoaderModelOnly",
         "CLIPTextEncode", "EmptyLatentImage", "VAEDecode", "VAEEncode", "ImageToMask", "SetLatentNoiseMask",
         "ImageCompositeMasked",
      )}
      self.prompt_status = 200
      self.node_errors: dict = {}
      self.history = "done"   # done · never · error
      self.output_name = "out_00001_.png"
      self.view_body: bytes | None = None   # None 이면 받은 시드로 noise_png
      self.view_length: int | None = None   # Content-Length 를 거짓으로 크게 줄 때
      self.views: list[dict] = []            # /view 질의
      self.queue_running: list[str] = []     # GET /queue 가 「돌고 있다」고 답할 prompt_id
      self.deleted: list[str] = []           # POST /queue {"delete": [...]} 로 받은 id
      self.interrupts: list[bytes] = []      # POST /interrupt 몸통
      self.history_cuts = 0                  # 처음 N 번의 /history 응답을 중간에 끊는다
      self.fail_after: int | None = None     # 받은 판이 이 수를 넘으면 history 가 error 를 답한다

   def last_seed(self) -> int:
      if not self.prompts:
         return 0
      for node in self.prompts[-1].values():
         if "seed" in node["inputs"]:
            return int(node["inputs"]["seed"])
      return 0


class FakeHandler(BaseHTTPRequestHandler):
   def log_message(self, *args):
      pass

   def do_GET(self):
      self._record()
      state = self.server.state
      parts = urlsplit(self.path)
      if parts.path == "/system_stats":
         self._send_json({"system": {"comfyui_version": "0.3.1"}})
      elif parts.path == "/object_info":
         self._send_json(state.nodes)
      elif parts.path.startswith("/history/") and state.history_cuts > 0:
         state.history_cuts -= 1
         self._send(b'{"p1": {', "application/json", length=500)   # 약속한 길이보다 적게 보내고 닫는다
         self.close_connection = True
      elif parts.path.startswith("/history/"):
         self._send_json(self._history(parts.path.split("/")[-1]))
      elif parts.path == "/queue":
         running = [[index, pid, {}, {}, []] for index, pid in enumerate(state.queue_running)]
         self._send_json({"queue_running": running, "queue_pending": []})
      elif parts.path == "/view":
         state.views.append({key: values[0] for key, values in parse_qs(parts.query).items()})
         body = state.view_body if state.view_body is not None else noise_png(state.last_seed())
         self._send(body, "image/png", state.view_length)
      else:
         self._send(b"", "text/plain", status=404)

   def do_POST(self):
      self._record()
      state = self.server.state
      length = int(self.headers.get("Content-Length") or 0)
      body = self.rfile.read(length)
      path = urlsplit(self.path).path
      state.bodies[path] = body
      if path == "/upload/image":
         state.uploads.append(body)
         self._send_json({"name": f"arttool_up{len(state.uploads)}.png", "subfolder": "", "type": "input"})
      elif path == "/prompt" and state.prompt_status == 200:
         state.prompts.append(json.loads(body.decode("utf-8"))["prompt"])
         self._send_json({"prompt_id": f"p{len(state.prompts)}", "number": 1, "node_errors": {}})
      elif path == "/prompt":
         answer = {"error": {"message": "Prompt outputs failed validation"}, "node_errors": state.node_errors}
         self._send_json(answer, status=state.prompt_status)
      elif path == "/interrupt":
         state.interrupts.append(body)
         self._send(b"", "text/plain")
      elif path == "/queue":
         state.deleted.extend(json.loads(body.decode("utf-8")).get("delete", []))
         self._send(b"", "text/plain")
      else:
         self._send(b"", "text/plain", status=404)

   def _history(self, prompt_id: str) -> dict:
      state = self.server.state
      if state.history == "never":
         return {}
      if state.history == "error" or (state.fail_after is not None and len(state.prompts) > state.fail_after):
         message = ["execution_error", {"node_type": "KSampler", "exception_message": "CUDA out of memory"}]
         return {prompt_id: {"status": {"status_str": "error", "completed": False, "messages": [message]}, "outputs": {}}}
      save_ids = [nid for nid, node in (state.prompts[-1] if state.prompts else {}).items() if node["class_type"] == "SaveImage"]
      images = [{"filename": state.output_name, "subfolder": "", "type": "output"}]
      outputs = {nid: {"images": images} for nid in save_ids or ["9"]}
      return {prompt_id: {"status": {"status_str": "success", "completed": True}, "outputs": outputs}}

   def _record(self):
      self.server.state.calls.append((self.command, self.path))

   def _send_json(self, data: dict, status: int = 200):
      self._send(json.dumps(data).encode("utf-8"), "application/json", status=status)

   def _send(self, body: bytes, content_type: str, length: int | None = None, status: int = 200):
      self.send_response(status)
      self.send_header("Content-Type", content_type)
      self.send_header("Content-Length", str(length if length is not None else len(body)))
      self.end_headers()
      try:
         self.wfile.write(body)
      except (BrokenPipeError, ConnectionResetError):
         pass   # 클라이언트가 상한을 넘겨 먼저 끊었다


class FakeComfy:
   """with 문으로 띄우고 닫는다. url 은 http://127.0.0.1:<포트>."""

   def __init__(self):
      self.state = FakeState()
      self._server = ThreadingHTTPServer(("127.0.0.1", 0), FakeHandler)
      self._server.state = self.state
      self._thread = threading.Thread(target=self._server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)

   @property
   def url(self) -> str:
      host, port = self._server.server_address[:2]
      return f"http://{host}:{port}"

   def paths(self) -> list[str]:
      return [urlsplit(path).path for _, path in self.state.calls]

   def __enter__(self) -> "FakeComfy":
      self._thread.start()
      return self

   def __exit__(self, *exc):
      self._server.shutdown()
      self._server.server_close()
