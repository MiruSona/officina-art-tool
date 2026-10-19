"""ComfyUI 클라이언트 단위 시험. 가짜 서버(fake_comfy)만 부른다 — 바깥 네트워크는 안 쓴다."""

import json
import socket

import pytest

from arttool import errors
from arttool.providers import comfy
from arttool.providers.comfy import ComfyClient, parse_endpoint
from fake_comfy import PNG_STUB, FakeComfy


@pytest.fixture
def fake():
   with FakeComfy() as server:
      yield server


def closed_port() -> int:
   sock = socket.socket()
   sock.bind(("127.0.0.1", 0))
   port = sock.getsockname()[1]
   sock.close()
   return port


def test_endpoint_strips_slash_and_shows_host_port_only():
   base, host = parse_endpoint("http://user:pw@mini.lan:8188/")
   assert base == "http://user:pw@mini.lan:8188"
   assert host == "mini.lan:8188"
   assert parse_endpoint("https://comfy.example")[1] == "comfy.example"


@pytest.mark.parametrize("bad", ["ftp://mini:8188", "mini:8188", "file:///etc/passwd", "http://", "http://mini:port"])
def test_endpoint_rejects_other_schemes(bad):
   with pytest.raises(errors.UsageError) as caught:
      parse_endpoint(bad)
   assert caught.value.exit_code == errors.EXIT_USAGE


def test_alive_and_nodes(fake):
   client = ComfyClient(fake.url)
   assert client.system_stats()["system"]["comfyui_version"]
   client.require_nodes(["KSampler", "SaveImage"])
   assert fake.paths() == ["/system_stats", "/object_info"]


def test_missing_node_named(fake):
   with pytest.raises(errors.ArtToolError, match="UnetLoaderGGUF") as caught:
      ComfyClient(fake.url).require_nodes(["KSampler", "UnetLoaderGGUF"])
   assert caught.value.exit_code == errors.EXIT_ERROR


def test_closed_port_exits_5_without_path():
   client = ComfyClient(f"http://127.0.0.1:{closed_port()}/secret/path")
   with pytest.raises(errors.ServerUnreachable) as caught:
      client.system_stats()
   assert caught.value.exit_code == errors.EXIT_NO_EXE
   assert "secret" not in str(caught.value)
   assert "127.0.0.1:" in str(caught.value)


def test_upload_sends_multipart_png(fake):
   name = ComfyClient(fake.url).upload_image(PNG_STUB, "arttool_image.png")
   assert name == "arttool_up1.png"
   body = fake.state.bodies["/upload/image"]
   assert b'name="image"; filename="arttool_image.png"' in body
   assert PNG_STUB in body
   assert b'name="overwrite"' in body


def test_queue_then_wait_then_fetch(fake):
   fake.state.view_body = PNG_STUB
   client = ComfyClient(fake.url, poll_s=0.01)
   prompt_id = client.queue_prompt({"1": {"class_type": "KSampler", "inputs": {"text": '따옴표 " 와\n줄바꿈'}}})
   entry = client.wait(prompt_id)
   image_info = entry["outputs"]["9"]["images"][0]
   data = client.fetch_image(image_info["filename"], image_info["subfolder"])
   assert data == PNG_STUB
   sent = json.loads(fake.state.bodies["/prompt"].decode("utf-8"))
   assert sent["prompt"]["1"]["inputs"]["text"] == '따옴표 " 와\n줄바꿈'


def test_node_errors_400_exits_1_with_node_lines(fake):
   fake.state.prompt_status = 400
   fake.state.node_errors = {
      "3": {"class_type": "UnetLoaderGGUF", "errors": [{"message": "Value not in list", "details": "unet_name: 'x.gguf'"}]},
   }
   with pytest.raises(errors.ArtToolError) as caught:
      ComfyClient(fake.url).queue_prompt({})
   assert caught.value.exit_code == errors.EXIT_ERROR
   assert "3 UnetLoaderGGUF : Value not in list" in str(caught.value)


def test_history_error_exits_1_with_server_message(fake):
   fake.state.history = "error"
   with pytest.raises(errors.ArtToolError, match="CUDA out of memory") as caught:
      ComfyClient(fake.url, poll_s=0.01).wait("p1")
   assert caught.value.exit_code == errors.EXIT_ERROR


def test_timeout_deletes_and_interrupts_only_our_running_job(fake):
   fake.state.history = "never"
   fake.state.queue_running = ["p1"]
   with pytest.raises(errors.ArtToolError, match="시간 초과") as caught:
      ComfyClient(fake.url, timeout_s=0.2, poll_s=0.02).wait("p1")
   assert caught.value.exit_code == errors.EXIT_ERROR
   assert fake.state.deleted == ["p1"]
   assert [json.loads(b) for b in fake.state.interrupts] == [{"prompt_id": "p1"}]
   assert fake.paths().count("/history/p1") >= 2


def test_timeout_leaves_someone_elses_running_job(fake):
   fake.state.history = "never"
   fake.state.queue_running = ["other"]
   with pytest.raises(errors.ArtToolError, match="시간 초과"):
      ComfyClient(fake.url, timeout_s=0.1, poll_s=0.02).wait("p1")
   assert fake.state.deleted == ["p1"]
   assert fake.state.interrupts == []


def test_ctrl_c_cleans_up_and_reraises(fake, monkeypatch):
   fake.state.history = "never"
   fake.state.queue_running = ["p1"]

   def stop(_):
      raise KeyboardInterrupt

   monkeypatch.setattr(comfy.time, "sleep", stop)
   with pytest.raises(KeyboardInterrupt):
      ComfyClient(fake.url).wait("p1")
   assert fake.state.deleted == ["p1"] and len(fake.state.interrupts) == 1


def test_wait_survives_two_cut_responses(fake):
   fake.state.history_cuts = 2
   entry = ComfyClient(fake.url, poll_s=0.01).wait("p1")
   assert entry["status"]["completed"]


def test_third_cut_exits_1_not_5(fake):
   fake.state.history_cuts = 3
   with pytest.raises(comfy.ResponseCut, match="끊겼다") as caught:
      ComfyClient(fake.url, poll_s=0.01).wait("p1")
   assert caught.value.exit_code == errors.EXIT_ERROR


def test_deep_json_is_not_a_crash(fake):
   deep = "[" * 100000 + "]" * 100000
   fake.state.view_body = deep.encode("ascii")
   with pytest.raises(errors.ArtToolError, match="JSON"):
      ComfyClient(fake.url)._json("GET", "/view?filename=x")


def test_server_text_cleaned():
   from arttool.providers.comfy_text import clean, prompt_error
   text = clean("\x1b[31mred\x07\n" + "a" * 300 + "\n1\n2\n3\n4\n5")
   assert "\x1b" not in text and "\x07" not in text
   lines = text.split("\n")
   assert len(lines[1]) == 201 and len(lines) == 6 and lines[-1] == "…"
   body = json.dumps({"node_errors": {"3": {"class_type": "K\x1b]0;x", "errors": [{"message": "m\x1b[2J"}]}}})
   assert "\x1b" not in prompt_error(400, body.encode("utf-8"))



def test_big_response_refused_by_header(fake):
   fake.state.view_length = comfy.MAX_IMAGE_BYTES + 1
   with pytest.raises(errors.ArtToolError, match="너무 크다"):
      ComfyClient(fake.url).fetch_image("out.png")


def test_big_response_refused_by_body(fake, monkeypatch):
   monkeypatch.setattr(comfy, "MAX_IMAGE_BYTES", 16)
   fake.state.view_body = PNG_STUB + b"\x00" * 100
   with pytest.raises(errors.ArtToolError, match="너무 크다"):
      ComfyClient(fake.url).fetch_image("out.png")


def test_not_png_refused(fake):
   fake.state.view_body = b"<html>nope</html>"
   with pytest.raises(errors.ArtToolError, match="PNG 가 아니다"):
      ComfyClient(fake.url).fetch_image("out.png")


def test_view_query_escapes_server_name(fake):
   ComfyClient(fake.url).fetch_image("../x.png", "a b")
   _, path = fake.state.calls[-1]
   assert path.startswith("/view?")
   assert "..%2Fx.png" in path and "a+b" in path


@pytest.mark.parametrize("answer", [{"p1": ["x"]}, {"p1": {"status": "x", "outputs": {}}}])
def test_odd_history_shapes_are_not_attribute_errors(fake, monkeypatch, answer):
   client = ComfyClient(fake.url, timeout_s=0.1, poll_s=0.02)
   monkeypatch.setattr(client, "_json", lambda method, path, **kw: answer if path.startswith("/history") else {})
   entry_or_error = None
   try:
      entry_or_error = client.wait("p1")
   except errors.ArtToolError as exc:
      entry_or_error = exc
   # 리스트 기록은 「아직 없음」으로 보고 시간 초과, 글자 status 는 빈 표로 보고 끝난 판으로 받는다
   if answer["p1"] == ["x"]:
      assert "시간 초과" in str(entry_or_error)
   else:
      assert entry_or_error == answer["p1"]


def test_wait_cancels_on_any_error(fake, monkeypatch):
   client = ComfyClient(fake.url)
   cancelled = []
   monkeypatch.setattr(client, "cancel", cancelled.append)

   def boom(_):
      raise RuntimeError("뜻밖의 오류")

   monkeypatch.setattr(client, "_poll", boom)
   with pytest.raises(RuntimeError):
      client.wait("p1")
   assert cancelled == ["p1"]


def test_wait_survives_brief_unreachable(fake, monkeypatch):
   client = ComfyClient(fake.url, poll_s=0.01)
   real = client._json
   blips = [2]

   def flaky(method, path, **kw):
      if path.startswith("/history") and blips[0]:
         blips[0] -= 1
         raise errors.ServerUnreachable("잠깐 끊김")
      return real(method, path, **kw)

   monkeypatch.setattr(client, "_json", flaky)
   assert client.wait("p1")["status"]["completed"]
   blips[0] = 3
   with pytest.raises(errors.ServerUnreachable):
      client.wait("p1")
