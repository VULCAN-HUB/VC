"""연결한 바깥 계정에서 **읽기만** 한다 — GitHub · Notion.

오너가 설정 창 「외부 연결」에 넣은 토큰(운영체제 보관소 `connect:이름`)으로 부른다.

★★ 막이 셋:
- **읽기만.** 허용한 길(정규식)만 부른다. GitHub 는 GET 만, Notion 은 읽기용 `POST /search` 하나만 더.
  고치기·지우기 길은 목록에 없어 부를 수가 없다 — 남의 계정을 AI 가 바꾸면 되돌릴 수 없다.
- **토큰은 안 내보낸다.** 답·오류 어디에도 토큰을 싣지 않는다(요청 머리에만 쓴다).
- **적게 준다.** 크레딧이 곧 성능이라 긴 답은 자르고 `cut` 으로 말한다.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

MAX_CHARS = 20_000
TIMEOUT_SEC = 30

_이름 = r"[A-Za-z0-9_.-]+"
ALLOWED: dict[str, dict[str, Any]] = {
    "github": {
        "base": "https://api.github.com",
        "get": (r"^/user$", r"^/user/repos$", rf"^/repos/{_이름}/{_이름}$",
                rf"^/repos/{_이름}/{_이름}/(issues|pulls|commits|readme|branches)$",
                rf"^/repos/{_이름}/{_이름}/issues/\d+$",
                rf"^/repos/{_이름}/{_이름}/contents(/[^?#]*)?$",
                r"^/search/(repositories|issues|code)$"),
        "post": (),
    },
    "notion": {
        "base": "https://api.notion.com/v1",
        "get": (r"^/pages/[A-Za-z0-9-]+$", r"^/blocks/[A-Za-z0-9-]+/children$", r"^/databases/[A-Za-z0-9-]+$"),
        "post": (r"^/search$",),
    },
}


class ConnectError(RuntimeError):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


def _머리(name: str, token: str) -> dict[str, str]:
    if name == "github":
        return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                "User-Agent": "VC", "X-GitHub-Api-Version": "2022-11-28"}
    return {"Authorization": f"Bearer {token}", "Notion-Version": "2022-06-28",
            "Content-Type": "application/json"}


def fetch(name: str, path: str, query: dict[str, str] | None = None, body: dict | None = None,
          opener: Callable = urllib.request.urlopen) -> dict[str, Any]:
    """연결 `name` 에서 `path` 를 읽는다. `{"data": …}` 또는 길면 `{"text": 앞부분, "cut": True, "full_chars": n}`."""
    import keystore

    규칙 = ALLOWED.get(name)
    if 규칙 is None:
        raise ConnectError(404, f"모르는 연결이다: {name}")
    if not isinstance(path, str) or not path.startswith("/") or ".." in path or "//" in path:
        raise ConnectError(400, "path 는 / 로 시작하는 길이다(.. · // 안 됨)")
    길목록 = 규칙["post"] if body is not None else 규칙["get"]
    if not any(re.match(p, path) for p in 길목록):
        raise ConnectError(400, "읽기용으로 허용한 길이 아니다")
    token = keystore.get(f"connect:{name}") if keystore.available() else None
    if not token:
        raise ConnectError(404, f"{name} 은 연결 안 됐다 — 설정 창 「외부 연결」에서 토큰을 넣는다")
    url = 규칙["base"] + urllib.parse.quote(path, safe="/-_.~")
    if query:
        url += "?" + urllib.parse.urlencode({k: v for k, v in query.items() if isinstance(v, str)})
    req = urllib.request.Request(url, headers=_머리(name, token), method="POST" if body is not None else "GET",
                                 data=json.dumps(body).encode("utf-8") if body is not None else None)
    try:
        with opener(req, timeout=TIMEOUT_SEC) as resp:
            글 = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raise ConnectError(e.code, e.read().decode("utf-8", "replace")[:300].replace(token, "(지움)")) from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ConnectError(502, f"바깥에 못 닿았다: {type(e).__name__}") from e
    if len(글) > MAX_CHARS:
        return {"text": 글[:MAX_CHARS], "cut": True, "full_chars": len(글)}
    try:
        return {"data": json.loads(글)}
    except ValueError:
        return {"text": 글}


def _self_check() -> None:
    import io

    import keystore

    보관 = {"connect:github": "ghp_시험토큰"}
    옛 = (keystore.available, keystore.get)
    keystore.available, keystore.get = (lambda: True), (lambda 이름: 보관.get(이름))
    받은: list = []

    class 가짜답(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def 가짜열기(req, timeout=0, _글=b'{"login": "someone"}'):
        받은.append(req)
        return 가짜답(_글)

    try:
        답 = fetch("github", "/user", opener=가짜열기)
        assert 답 == {"data": {"login": "someone"}}, 답
        assert 받은[-1].get_header("Authorization") == "Bearer ghp_시험토큰" and 받은[-1].get_method() == "GET"
        assert "ghp_시험토큰" not in json.dumps(답, ensure_ascii=False), "토큰이 답에 실렸다"
        for 나쁜길 in ("/user/../admin", "/repos/a/b/issues/1/lock", "https://evil", "/orgs/x/members", "//user"):
            try:
                fetch("github", 나쁜길, opener=가짜열기)
            except ConnectError as e:
                assert e.code == 400, (나쁜길, e.code)
            else:
                raise AssertionError(f"허용 안 한 길을 불렀다: {나쁜길}")
        try:
            fetch("github", "/user", body={"x": 1}, opener=가짜열기)     # GitHub 은 POST 가 없다
        except ConnectError as e:
            assert e.code == 400
        else:
            raise AssertionError("GitHub 에 POST 를 보냈다")
        try:
            fetch("notion", "/search", body={"query": "a"}, opener=가짜열기)
        except ConnectError as e:
            assert e.code == 404 and "연결 안 됐다" in str(e), e
        else:
            raise AssertionError("연결 안 한 Notion 을 불렀다")
        보관["connect:notion"] = "secret_노션"
        fetch("notion", "/search", body={"query": "회의"}, opener=가짜열기)
        assert 받은[-1].get_method() == "POST" and 받은[-1].full_url.endswith("/v1/search")
        긴글 = b'{"x": "' + b"a" * (MAX_CHARS + 10) + b'"}'
        답 = fetch("github", "/user/repos", opener=lambda req, timeout=0: 가짜답(긴글))
        assert 답["cut"] is True and len(답["text"]) == MAX_CHARS and 답["full_chars"] > MAX_CHARS, "긴 답을 안 자른다"

        def 거절(req, timeout=0):
            raise urllib.error.HTTPError(req.full_url, 401, "no", {}, io.BytesIO(b"bad token ghp_\xec\x8b\x9c\xed\x97\x98\xed\x86\xa0\xed\x81\xb0"))
        try:
            fetch("github", "/user", opener=거절)
        except ConnectError as e:
            assert e.code == 401 and "ghp_시험토큰" not in str(e), f"오류에 토큰이 실렸다: {e}"
        else:
            raise AssertionError("401 을 삼켰다")
    finally:
        keystore.available, keystore.get = 옛
    print("connectors self-check 통과")


if __name__ == "__main__":
    import sys

    if "--check" in sys.argv:
        _self_check()
