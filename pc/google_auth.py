"""Google 계정 연결 — 설치형 앱 OAuth(루프백 주소 + PKCE), **읽기 전용** (오너 결정 8 — 추천대로 확정 2026-09-13).

구글은 토큰을 붙여 넣는 방식이 아니다. 오너가 Google Cloud 에서 「데스크톱 앱」 OAuth 클라이언트를 **직접 등록**해
클라이언트 ID·비밀을 설정 창에 넣으면, VC 가 브라우저로 로그인 창을 띄우고 이 PC 의 127.0.0.1 로 돌아온 코드를 받는다.

★★ 막이:
- **읽기 전용 범위만** — 드라이브·캘린더 읽기. 쓰기 범위는 요청 자체를 안 한다.
- 받은 **새로고침 토큰·클라이언트 비밀은 운영체제 보관소에만**(`connect:google` · `connect:google-client`). 설정에는 이름만.
- `state` 가 다르면 버린다(남이 끼워 넣은 코드), PKCE 로 가로챈 코드도 못 쓴다.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import threading
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Callable

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPES = ("https://www.googleapis.com/auth/drive.readonly",
          "https://www.googleapis.com/auth/calendar.readonly")
TIMEOUT_SEC = 180


class GoogleAuthError(RuntimeError):
    pass


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)[:96]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def authorize_url(client_id: str, redirect: str, challenge: str, state: str) -> str:
    return AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": client_id, "redirect_uri": redirect, "response_type": "code",
        "scope": " ".join(SCOPES), "code_challenge": challenge, "code_challenge_method": "S256",
        "state": state, "access_type": "offline", "prompt": "consent"})


def _post_form(url: str, 값: dict, opener: Callable) -> dict:
    req = urllib.request.Request(url, data=urllib.parse.urlencode(값).encode(), method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with opener(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:                              # 비밀·토큰이 오류 글에 섞이지 않게 종류만 말한다
        raise GoogleAuthError(f"구글 토큰 교환 실패: {type(e).__name__}") from e


def login(client_id: str, client_secret: str, open_browser: Callable[[str], object],
          opener: Callable = urllib.request.urlopen, timeout: float = TIMEOUT_SEC) -> None:
    """브라우저로 로그인 창을 띄우고 돌아온 코드를 새로고침 토큰으로 바꿔 보관소에 넣는다."""
    import keystore

    if not client_id.strip() or not client_secret.strip():
        raise GoogleAuthError("클라이언트 ID·비밀을 넣어 줘(Google Cloud 「데스크톱 앱」 OAuth 클라이언트)")
    if not keystore.available():
        raise GoogleAuthError("이 운영체제에는 열쇠 보관소가 없어 연결을 안 받는다(평문으로 두지 않는다)")
    verifier, challenge = _pkce()
    state = secrets.token_urlsafe(16)
    받은: dict = {}

    class 받기(BaseHTTPRequestHandler):
        def log_message(self, *a) -> None:
            pass

        def do_GET(self) -> None:
            물음 = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            받은.update({k: v[0] for k, v in 물음.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("VC 에 연결했어. 이 창은 닫아도 된다.".encode("utf-8"))

    서버 = HTTPServer(("127.0.0.1", 0), 받기)
    redirect = f"http://127.0.0.1:{서버.server_address[1]}/"
    서버.timeout = timeout
    실 = threading.Thread(target=서버.handle_request, daemon=True)
    실.start()
    try:
        open_browser(authorize_url(client_id.strip(), redirect, challenge, state))
        실.join(timeout)
    finally:
        서버.server_close()
    if not 받은:
        raise GoogleAuthError("로그인 창에서 돌아오지 않았다(시간 초과)")
    if 받은.get("state") != state:
        raise GoogleAuthError("돌아온 state 가 다르다 — 남이 끼워 넣은 응답이라 버렸다")
    if "code" not in 받은:
        raise GoogleAuthError(f"구글이 거절했다: {받은.get('error', '까닭 모름')}")
    토큰 = _post_form(TOKEN_URL, {"code": 받은["code"], "client_id": client_id.strip(),
                               "client_secret": client_secret.strip(), "redirect_uri": redirect,
                               "grant_type": "authorization_code", "code_verifier": verifier}, opener)
    새로고침 = 토큰.get("refresh_token")
    if not isinstance(새로고침, str) or not 새로고침:
        raise GoogleAuthError("새로고침 토큰을 못 받았다")
    keystore.put("connect:google-client", json.dumps({"id": client_id.strip(), "secret": client_secret.strip()}))
    keystore.put("connect:google", 새로고침)


def access_token(opener: Callable = urllib.request.urlopen) -> str | None:
    """보관소의 새로고침 토큰으로 짧게 쓰는 접근 토큰을 받는다. 연결 안 됐으면 None."""
    import keystore

    새로고침 = keystore.get("connect:google") if keystore.available() else None
    짝 = keystore.get("connect:google-client") if 새로고침 else None
    if not 새로고침 or not 짝:
        return None
    try:
        클 = json.loads(짝)
    except ValueError:
        return None
    답 = _post_form(TOKEN_URL, {"client_id": 클.get("id", ""), "client_secret": 클.get("secret", ""),
                              "refresh_token": 새로고침, "grant_type": "refresh_token"}, opener)
    return 답.get("access_token") if isinstance(답.get("access_token"), str) else None


def _self_check() -> None:
    import io

    import keystore

    보관: dict = {}
    옛 = (keystore.available, keystore.put, keystore.get)
    keystore.available = lambda: True
    keystore.put = lambda 이름, 값: (보관.__setitem__(이름, 값), True)[1]
    keystore.get = lambda 이름: 보관.get(이름)

    class 가짜답(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    보낸폼: list = []

    def 가짜교환(req, timeout=0):
        보낸폼.append(urllib.parse.parse_qs(req.data.decode()))
        폼 = 보낸폼[-1]
        if 폼["grant_type"][0] == "authorization_code":
            return 가짜답(b'{"refresh_token": "1//rt-sample", "access_token": "ya29.a"}')
        return 가짜답(b'{"access_token": "ya29.b"}')

    def 브라우저(주소: str, state_바꾸기: bool = False):
        # 진짜 사람 대신 — 동의 뒤 구글이 돌려보내는 주소로 코드를 던진다
        물음 = urllib.parse.parse_qs(urllib.parse.urlparse(주소).query)
        assert 물음["scope"][0].split() == list(SCOPES) and "readonly" in 물음["scope"][0], 물음["scope"]
        assert 물음["code_challenge_method"] == ["S256"]
        state = "남의것" if state_바꾸기 else 물음["state"][0]
        돌아올 = 물음["redirect_uri"][0] + "?" + urllib.parse.urlencode({"code": "4/code", "state": state})
        threading.Thread(target=lambda: urllib.request.urlopen(돌아올, timeout=5).read(), daemon=True).start()

    try:
        login("id.apps.googleusercontent.com", "비밀값", 브라우저, opener=가짜교환, timeout=10)
        assert 보관["connect:google"] == "1//rt-sample", 보관
        assert json.loads(보관["connect:google-client"])["secret"] == "비밀값"
        assert "code_verifier" in 보낸폼[0] and 보낸폼[0]["code"] == ["4/code"], "PKCE 검증값을 안 보냈다"
        assert access_token(opener=가짜교환) == "ya29.b"
        try:
            login("id", "비밀", lambda 주소: 브라우저(주소, state_바꾸기=True), opener=가짜교환, timeout=10)
        except GoogleAuthError as e:
            assert "state" in str(e), e
        else:
            raise AssertionError("state 가 다른 응답을 받았다")
        try:
            login("", "", 브라우저, opener=가짜교환)
        except GoogleAuthError:
            pass
        else:
            raise AssertionError("클라이언트 ID 없이 로그인을 시작했다")
        보관.clear()
        assert access_token(opener=가짜교환) is None, "연결 안 됐는데 토큰을 준다"
    finally:
        keystore.available, keystore.put, keystore.get = 옛
    print("google_auth self-check 통과")


if __name__ == "__main__":
    import sys

    if "--check" in sys.argv:
        _self_check()
