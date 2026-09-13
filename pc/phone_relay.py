"""폰 중계 — 외부 PC를 내 서버PC에 잇는다. **폰으로 옮겨질 참조 구현이다.**

    외부 PC ──로컬망(핫스팟/같은 와이파이)──> 폰 ──이미 있는 연결──> 서버PC

제3자가 없다. 중계 서버도, 시그널링 서버도 안 쓴다. 폰이 이미 서버PC와 붙어 있고,
외부 PC를 폰 핫스팟에 물리면 그 순간 둘 다 폰에서 닿는 거리에 있기 때문이다.

NAT를 뚫는 게 아니라 **NAT를 피한다**. 이동통신망은 거의 CGNAT라 폰도 인바운드를
못 받지만, 폰이 만든 로컬망 안에서는 폰이 곧 게이트웨이다.

폰이 하는 일은 둘뿐이다:

    문지기   외부 PC 화면의 네 자리를 사람이 폰에서 대조해 승인한다
    배달부   승인 뒤에는 요청을 서버PC로 넘기고 답을 돌려준다. 내용은 안 본다

배달부일 때 **폰의 페어링 토큰을 외부 PC에 주지 않는다.** 외부 PC는 서버PC가 발급한
원격 토큰만 갖고, 그건 허용된 경로에서만 통한다(remote.REMOTE_ALLOWED). 폰 토큰을
넘기면 외부 PC가 폰 권한을 그대로 얻는다 — 스킬 승인·설정 변경까지 열린다.

코틀린으로 옮길 때 바뀌는 건 HTTP 서버 껍데기뿐이다(NanoHTTPD/Ktor). 규약은 그대로다.
"""

from __future__ import annotations

import json
import socket
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

RELAY_PORT = 8770

# 폰이 그대로 넘겨줄 헤더. 나머지는 버린다 — 외부 PC가 보낸 걸 다 믿고 넘기면
# Authorization 위조나 Host 조작이 그대로 서버PC까지 간다.
FORWARD_HEADERS = ("Authorization", "Content-Type")


# 서버(`server.py`)와 같은 한도. 중계가 앞문이라 여기서 먼저 막는다.
MAX_BODY = 8 * 1024 * 1024

class PhoneRelay:
    """폰 쪽 중계. 서버PC 주소와 폰의 페어링 토큰을 들고 있다."""

    def __init__(self, pc_base: str, pair_token: str) -> None:
        self.pc = pc_base.rstrip("/")
        self.token = pair_token
        self.httpd: ThreadingHTTPServer | None = None

    # --- 서버PC에 묻기 ---------------------------------------------------

    def _call(self, method: str, path: str, body: bytes | None = None,
              headers: dict[str, str] | None = None) -> tuple[int, bytes, str]:
        req = urllib.request.Request(f"{self.pc}{path}", data=body, method=method,
                                     headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.status, r.read(), r.headers.get("Content-Type", "application/json")
        except urllib.error.HTTPError as e:
            return e.code, e.read(), e.headers.get("Content-Type", "application/json")
        except (urllib.error.URLError, OSError) as e:
            # 서버PC가 꺼져 있다. 외부 PC에 그대로 알린다 — 조용히 실패하면
            # 사용자는 VC가 고장 난 줄 안다.
            return 503, json.dumps({"error": f"서버PC에 못 닿아: {e}"}).encode(), "application/json"

    def _phone_headers(self, client_ip: str) -> dict[str, str]:
        """폰이 자기 자격으로 부를 때. 중계임을 밝히고 진짜 손님 주소를 넘긴다."""
        return {"Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "X-EB-Client": client_ip}

    # --- 문지기 ----------------------------------------------------------

    def pending(self) -> list[dict]:
        """폰 화면에 "누가 붙으려 한다"를 띄우기 위한 목록."""
        status, body, _ = self._call("GET", "/eb/v1/remote/pending",
                                     headers=self._phone_headers(""))
        return json.loads(body).get("sessions", []) if status == 200 else []

    def approve(self, code: str) -> bool:
        """사람이 외부 PC 화면의 네 자리를 보고 폰에서 눌렀다."""
        payload = json.dumps({"code": code, "by": "폰 중계"}).encode()
        status, body, _ = self._call("POST", "/eb/v1/remote/approve", payload,
                                     self._phone_headers(""))
        return status == 200 and json.loads(body).get("ok") is True

    # --- 배달부 ----------------------------------------------------------

    def serve(self, port: int = RELAY_PORT) -> str:
        relay = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a: Any) -> None:
                pass

            def _proxy(self, method: str) -> None:
                url = urlparse(self.path)
                # ★★ **중계는 토큰 없이 같은 망 누구에게나 열려 있다.** 본문 길이를 믿고 그대로 읽으면
                #   `Content-Length: 4000000000` 한 줄로 폰 메모리를 다 먹는다 — 서버 쪽은 8MB 로 막는데
                #   앞문인 중계는 안 막고 있었다. 같은 한도로 막고, 숫자가 아니면 400.
                try:
                    length = int(self.headers.get("Content-Length") or 0)
                except ValueError:
                    return self._reply(400, b'{"error": "bad Content-Length"}')
                if length < 0 or length > MAX_BODY:
                    self.close_connection = True
                    self._reply(413, b'{"error": "body too large"}')
                    # ★ 안 읽은 본문을 남긴 채 닫으면 RST 로 413 이 안 닿는다 — 0.5초만 비우고 끊는다.
                    try:
                        self.wfile.flush()
                        self.connection.shutdown(socket.SHUT_WR)
                        self.connection.settimeout(0.5)
                        while self.connection.recv(65536):
                            pass
                    except OSError:
                        pass
                    return
                body = self.rfile.read(length) if length else None

                headers = {k: v for k, v in self.headers.items() if k in FORWARD_HEADERS}
                # 진짜 손님 주소. 서버PC는 이걸로 토큰을 묶는다. 폰 IP로 묶으면
                # 같은 핫스팟에 붙은 다른 기기까지 통과한다.
                headers["X-EB-Client"] = self.client_address[0]
                headers["X-EB-Relay"] = relay.token

                path = self.path
                if url.path in ("/", "/remote"):
                    path = "/remote?via=phone"  # QR 대신 네 자리를 띄우게 한다

                status, data, ctype = relay._call(method, path, body, headers)
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _reply(self, status: int, data: bytes) -> None:
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self) -> None:
                self._proxy("GET")

            def do_POST(self) -> None:
                self._proxy("POST")

        self.httpd = ThreadingHTTPServer(("0.0.0.0", port), Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return f"http://{local_ip()}:{self.httpd.server_address[1]}"

    def stop(self) -> None:
        if self.httpd:
            self.httpd.shutdown()
            self.httpd = None


def local_ip() -> str:
    """폰이 로컬망에서 갖는 주소. 외부 PC 브라우저에 손으로 칠 주소다.

    핫스팟이면 대개 192.168.43.1 / 192.168.137.1로 고정이라 외우기 쉽다.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))  # 실제로 안 보낸다. 어느 인터페이스로 나갈지만 본다
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def _self_check() -> None:
    """서버PC 대역과 외부 PC를 흉내 내 전 경로를 돌린다."""
    import tempfile
    from pathlib import Path

    from notes import Notes
    from server import EBServer
    from store import Store

    cfg = {"pair_token": "phone-token",
           "backend": {"kind": "openai_compatible", "base_url": "http://unused/v1"},
           "models": {"chat": "", "vision": "", "stt": "", "voice": ""}}
    tmp = tempfile.TemporaryDirectory()
    pc = EBServer(("127.0.0.1", 0), cfg, Store(":memory:"), Notes(Path(tmp.name) / "notes"))
    threading.Thread(target=pc.serve_forever, daemon=True).start()
    pc_base = f"http://127.0.0.1:{pc.server_address[1]}"

    relay = PhoneRelay(pc_base, cfg["pair_token"])
    url = relay.serve(port=0)
    port = relay.httpd.server_address[1]
    outside = f"http://127.0.0.1:{port}"
    assert url.startswith("http://")

    def ext(method: str, path: str, payload: dict | None = None, token: str | None = None):
        """외부 PC 브라우저. 폰에만 말을 걸고 서버PC 주소는 모른다."""
        req = urllib.request.Request(
            outside + path, method=method,
            data=None if payload is None else json.dumps(payload).encode(),
            headers={"Content-Type": "application/json",
                     **({"Authorization": f"Bearer {token}"} if token else {})})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    # ★★ **중계는 토큰 없이 같은 망에 열려 있다** — 본문 길이를 믿고 읽으면 한 줄로 폰 메모리를 먹는다.
    import socket as _so

    줄끝 = chr(13) + chr(10)          # 역빗금 글자는 도구를 거치며 깨지므로 글자 번호로 짓는다

    def 날것(머리줄들: list[str]) -> bytes:
        with _so.create_connection(("127.0.0.1", port), timeout=5) as c:
            c.sendall((줄끝.join(머리줄들) + 줄끝 + 줄끝).encode("ascii"))
            return c.recv(200)

    큰것 = 날것(["POST /eb/v1/ask HTTP/1.1", "Host: x", "Content-Length: 4000000000"])
    assert b" 413 " in 큰것, f"아주 큰 본문 길이를 안 막는다: {큰것[:40]!r}"
    이상 = 날것(["POST /eb/v1/ask HTTP/1.1", "Host: x", "Content-Length: abc"])
    assert b" 400 " in 이상, f"숫자 아닌 본문 길이에 400 을 안 준다: {이상[:40]!r}"

    # 외부 PC가 폰에 접속한다 — QR이 아니라 네 자리가 뜬다.
    status, html = ext("GET", "/")
    assert status == 200 and "<svg" not in html.decode(), "폰 중계인데 QR이 떴다"
    sid = [s.id for s in pc.gate.pending()][-1]
    code = pc.gate.sessions[sid].code
    assert code in html.decode(), "네 자리가 화면에 없다"

    # 승인 전에는 아무것도 못 한다.
    assert ext("POST", "/eb/v1/ask", {"text": "볼륨 올려"})[0] == 401

    # 폰 화면에 대기가 뜨고, 사람이 눈으로 대조해 승인한다.
    assert sid in [s["id"] for s in relay.pending()]
    assert relay.approve("9999" if code != "9999" else "1111") is False
    assert relay.approve(code) is True

    # 외부 PC가 토큰을 받아 쓴다. 폰은 배달만 하고 내용은 안 본다.
    status, body = ext("GET", f"/eb/v1/remote/status?s={sid}")
    token = json.loads(body)["token"]
    status, body = ext("POST", "/eb/v1/ask", {"text": "볼륨 올려"}, token)
    assert status == 200, body
    out = json.loads(body)
    assert out["text"] == "볼륨 올렸어" and out["artifact"]

    # 결과물을 외부 PC에서 내려받는다.
    status, blob = ext("GET", f"/eb/v1/artifacts/{out['artifact']}?t={token}")
    assert status == 200 and "볼륨 올렸어" in blob.decode()

    # 폰 토큰은 외부 PC에 안 준다. 원격은 허용된 경로만 열린다.
    assert token != cfg["pair_token"]
    assert ext("POST", "/eb/v1/proposals/x/decision", {"decision": "approve"}, token)[0] == 401
    assert ext("GET", "/eb/v1/remote/sessions", None, token)[0] == 401

    # 폰이 붙인 헤더를 외부 PC가 위조해도 안 통한다.
    req = urllib.request.Request(
        outside + "/eb/v1/remote/sessions",
        headers={"Authorization": f"Bearer {token}", "X-EB-Relay": "forged-token"})
    try:
        code_ = urllib.request.urlopen(req, timeout=10).status
    except urllib.error.HTTPError as e:
        code_ = e.code
    assert code_ == 401, "위조 헤더가 통했다"

    # 끊으면 길이 사라진다.
    assert ext("POST", "/eb/v1/remote/close", {"session": sid}, token)[0] == 200
    assert ext("POST", "/eb/v1/ask", {"text": "볼륨 올려"}, token)[0] == 401

    # 서버PC가 꺼지면 외부 PC에 그대로 알린다.
    # shutdown만 하면 듣는 소켓이 남아 연결이 걸린 채 멈춘다. 닫아야 거절된다.
    pc.shutdown()
    pc.server_close()
    assert ext("GET", "/")[0] == 503

    relay.stop()
    print("phone_relay self-check 통과")


if __name__ == "__main__":
    _self_check()
