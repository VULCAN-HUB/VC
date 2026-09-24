"""VC 의 일을 **바깥 AI 가 도구로 잡게** 해 주는 다리 (MCP · stdio).

여태 채팅은 **말만 했다.** 로컬은 창고를 뒤져 답하고, claude 는 연 프로젝트의 코드만
고쳤다 — 「새 글 만들어」 「그거 고쳐 둬」 같은 **VC 안의 일**은 아무도 안 했다
(오너가 짚었다 · 2026-09-24: 「그냥 답만 한다. 내가 시킨 일을 하지 못한다」).

시키기 자체는 `orders.py` 에 있었지만 **정해진 말끝에만 걸리는 정규식 표**라, 조금만
달리 말하면 검색으로 샜다. 그래서 **무엇을 할지 모델이 고르게** 한다 — 그게 오너가
말한 「LLM 이 VC 안에 있다」는 것이다.

★★ **창고는 VC 문으로만 만진다.** 여기서 파일을 직접 고치면 **쓰는 쪽이 둘**이 된다 —
   색인·잠금·지난 판·`.tmp` 쓸기를 두 프로세스가 같이 만지면 엉킨다(그 병을 이미
   겪었다). 그래서 이 다리는 **HTTP 문만 두드린다.**
★★ **되돌릴 수 있는 것만 시킨다.** 지우기는 VC 가 늘 지난 판을 남기므로 되살릴 수
   있다(`창고_되살리기`). 되돌릴 수 없는 일은 여기 없다.
★ 바깥 꾸러미를 안 쓴다 — JSON-RPC 한 줄씩 주고받는 것이 전부다. 구운 앱에 SDK 를
  하나 더 넣는 것보다 이쪽이 싸고, 프로토콜이 바뀌어도 여기만 고치면 된다.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request

프로토콜 = "2024-11-05"
이름 = "vc"
기본주소 = "http://127.0.0.1:8765"
제한초 = 120


def _열쇠() -> str:
    """페어링 열쇠. **값은 안 찍는다** — 자국에 남으면 그게 새는 것이다."""
    try:
        import paths

        with open(paths.config_path(), encoding="utf-8") as f:
            return str(json.load(f).get("pair_token") or "")
    except Exception:
        return ""


def 두드리기(길: str, 몸: dict | None = None, 방법: str = "POST",
          주소: str = 기본주소, 열쇠: str = "") -> dict:
    """VC 문 하나를 두드린다. **탈이 나도 던지지 않는다** — 까닭을 담아 돌려준다."""
    열쇠 = 열쇠 or _열쇠()
    쿼리 = ""
    자료 = None
    if 방법 == "GET" and 몸:
        쿼리 = "?" + urllib.parse.urlencode({k: v for k, v in 몸.items() if v not in (None, "")})
    elif 몸 is not None:
        자료 = json.dumps(몸, ensure_ascii=False).encode()
    요청 = urllib.request.Request(
        f"{주소}{길}{쿼리}", method=방법, data=자료,
        headers={"Authorization": f"Bearer {열쇠}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(요청, timeout=제한초) as r:
            글 = r.read().decode("utf-8", "replace")
        return json.loads(글) if 글.strip() else {}
    except urllib.error.HTTPError as e:
        try:
            return {"error": json.loads(e.read().decode()).get("error") or str(e)}
        except Exception:
            return {"error": f"HTTP {e.code}"}
    except urllib.error.URLError as e:
        return {"error": f"VC 가 안 떠 있다: {e.reason}"}
    except Exception as e:                       # 무슨 일이 나도 다리는 안 죽는다
        return {"error": f"{type(e).__name__}: {e}"}


def _글(자리: str) -> dict:
    return {"type": "string", "description": 자리}


# ★★ **도구 설명이 곧 지시다.** 모델은 이 글만 보고 고른다 — 여기가 흐리면 엉뚱한
#   것을 부른다. 「언제 쓰는가」를 먼저 적고 「무엇을 하는가」를 뒤에 적는다.
# ★★ **이름과 인자 키는 영문만 쓴다.** 처음엔 한글로 지었다가 실기에서 막혔다 —
#   API 가 「속성 키가 영숫자 규칙에 안 맞다」며 도구를 통째로 거부했고, 클로드는
#   「스키마를 영문 키로 고쳐야 한다」고 되받았다(2026-09-24). 검사로는 안 잡히고
#   **진짜로 불러 봐야 나오던 자리**다. 설명은 한글로 둔다 — 거기는 자유 글이다.
도구들: list[dict] = [
    {
        "name": "note_search",
        "description": "창고에서 글을 찾는다. 무엇을 고칠지·무엇이 이미 있는지 "
                       "모를 때 먼저 이것부터 부른다.",
        "inputSchema": {"type": "object", "properties": {
            "q": _글("찾을 말")}, "required": ["q"]},
        "문": ("GET", "/eb/v1/memory/search", lambda a: {"q": a.get("q", ""), "k": 8}),
    },
    {
        "name": "note_read",
        "description": "글 하나를 통째로 읽는다. 고치기 전에 반드시 읽어 본다 — "
                       "안 읽고 덮으면 적혀 있던 것이 사라진다.",
        "inputSchema": {"type": "object", "properties": {
            "title": _글("글 제목")}, "required": ["title"]},
        "문": ("GET", "/eb/v1/memory/note", lambda a: {"title": a.get("title", "")}),
    },
    {
        "name": "note_write",
        "description": "글을 만들거나 덧붙인다. 없으면 새로 만든다. "
                       "기본은 덧붙이기(append)다 — 덮어쓰려면 mode 를 replace 로 준다. "
                       "덮어쓰기 전에는 반드시 note_read 로 먼저 본다.",
        "inputSchema": {"type": "object", "properties": {
            "title": _글("글 제목"), "text": _글("적을 내용"),
            "kind": _글("갈래(메모·결정·작업·설계…). 모르면 비워 둔다"),
            "mode": {"type": "string", "enum": ["append", "replace"],
                     "description": "append=덧붙이기(기본) · replace=덮어쓰기"},
        }, "required": ["title", "text"]},
        "문": ("POST", "/eb/v1/memory", lambda a: {
            "title": a.get("title", ""), "text": a.get("text", ""),
            **({"kind": a["kind"]} if a.get("kind") else {}),
            "mode": a.get("mode") or "append"}),
    },
    {
        "name": "note_rename",
        "description": "글 제목을 바꾼다. 가리키던 링크도 같이 따라간다.",
        "inputSchema": {"type": "object", "properties": {
            "title": _글("지금 제목"), "new_title": _글("바꿀 제목")},
            "required": ["title", "new_title"]},
        "문": ("POST", "/eb/v1/memory/rename",
              lambda a: {"title": a.get("title", ""), "new_title": a.get("new_title", "")}),
    },
    {
        "name": "note_delete",
        "description": "글을 버린다. 지난 판이 남으므로 note_restore 로 되돌릴 수 있다. "
                       "그래도 사람이 시키지 않았으면 먼저 물어본다.",
        "inputSchema": {"type": "object", "properties": {
            "title": _글("버릴 글 제목")}, "required": ["title"]},
        "문": ("POST", "/eb/v1/memory/delete", lambda a: {"title": a.get("title", "")}),
    },
    {
        "name": "note_restore",
        "description": "버린 글을 되살린다.",
        "inputSchema": {"type": "object", "properties": {
            "title": _글("되살릴 글 제목")}, "required": ["title"]},
        "문": ("POST", "/eb/v1/trash/restore", lambda a: {"title": a.get("title", "")}),
    },
    {
        "name": "daily_log",
        "description": "오늘 일지에 한 줄 남긴다. 날짜 글은 알아서 만들어진다.",
        "inputSchema": {"type": "object", "properties": {
            "text": _글("남길 말")}, "required": ["text"]},
        "문": ("POST", "/eb/v1/daily", lambda a: {"text": a.get("text", "")}),
    },
    {
        "name": "warehouse_ask",
        "description": "창고를 뒤져 근거를 달아 답하게 한다. 여러 글에 흩어진 것을 "
                       "모아 물을 때 쓴다. 한 글만 보면 될 때는 note_read 가 싸다.",
        "inputSchema": {"type": "object", "properties": {
            "question": _글("물을 말")}, "required": ["question"]},
        "문": ("POST", "/eb/v1/wiki/ask", lambda a: {"text": a.get("question", "")}),
    },
    {
        "name": "project_context",
        "description": "그 프로젝트에서 여태 무엇을 정하고 무엇이 탈났는지 꺼낸다. "
                       "코드를 고치기 전에 부르면 같은 실수를 안 되풀이한다.",
        "inputSchema": {"type": "object", "properties": {
            "name": _글("프로젝트 이름(영문)")}, "required": ["name"]},
        "문": ("POST", "/eb/v1/hermes/context", lambda a: {"name": a.get("name", "")}),
    },
    {
        "name": "project_start",
        "description": "새 프로젝트 자리를 차린다(폴더·git·창고 글).",
        "inputSchema": {"type": "object", "properties": {
            "name": _글("프로젝트 이름(영문만)"), "one_line": _글("무엇을 만드는지 한 줄")},
            "required": ["name"]},
        "문": ("POST", "/eb/v1/hermes/start",
              lambda a: {"name": a.get("name", ""), "one_line": a.get("one_line", "")}),
    },
    {
        "name": "project_log",
        "description": "그 프로젝트에서 정한 것·탈난 것을 창고에 남긴다. "
                       "일을 끝내고 반드시 남긴다 — 안 남기면 다음에 또 헤맨다.",
        "inputSchema": {"type": "object", "properties": {
            "name": _글("프로젝트 이름"), "decision": _글("정한 것"),
            "error": _글("탈난 것"), "work": _글("한 일")},
            "required": ["name"]},
        "문": ("POST", "/eb/v1/hermes/log", lambda a: {
            "name": a.get("name", ""),
            **{k: [v] for k, v in (("decisions", a.get("decision")),
                                   ("errors", a.get("error")),
                                   ("works", a.get("work"))) if v}}),
    },
]

도구찾기 = {t["name"]: t for t in 도구들}


def 손잡이(이름_: str, 인자: dict, 주소: str = 기본주소, 열쇠: str = "") -> dict:
    """도구 하나를 실제로 돌린다."""
    도구 = 도구찾기.get(이름_)
    if 도구 is None:
        return {"error": f"그런 도구가 없다: {이름_}"}
    방법, 길, 만들기 = 도구["문"]
    return 두드리기(길, 만들기(인자 or {}), 방법, 주소, 열쇠)


def 알림들() -> list[dict]:
    """`tools/list` 가 내보낼 꼴. **`문` 은 우리끼리 쓰는 것이라 뺀다.**"""
    return [{k: v for k, v in t.items() if k != "문"} for t in 도구들]


def 다뤄주기(요청: dict, 주소: str = 기본주소, 열쇠: str = "") -> dict | None:
    """JSON-RPC 한 마디를 받아 한 마디를 돌려준다. 알림이면 `None`."""
    방법 = 요청.get("method") or ""
    아이디 = 요청.get("id")

    def 답(것: dict) -> dict:
        return {"jsonrpc": "2.0", "id": 아이디, "result": 것}

    if 방법 == "initialize":
        return 답({"protocolVersion": 프로토콜,
                  "capabilities": {"tools": {}},
                  "serverInfo": {"name": 이름, "version": "1"}})
    if 방법 in ("notifications/initialized", "initialized"):
        return None                      # 알림엔 답하지 않는다(답하면 짝이 안 맞는다)
    if 방법 == "tools/list":
        return 답({"tools": 알림들()})
    if 방법 == "tools/call":
        인자 = 요청.get("params") or {}
        난것 = 손잡이(인자.get("name") or "", 인자.get("arguments") or {}, 주소, 열쇠)
        탈 = bool(isinstance(난것, dict) and 난것.get("error"))
        return 답({"content": [{"type": "text",
                              "text": json.dumps(난것, ensure_ascii=False)[:20000]}],
                  "isError": 탈})
    if 아이디 is None:
        return None                      # 모르는 알림은 그냥 흘린다
    return {"jsonrpc": "2.0", "id": 아이디,
            "error": {"code": -32601, "message": f"모르는 방법이다: {방법}"}}


def 돌기(들어옴=None, 나감=None, 주소: str = 기본주소) -> None:
    """stdio 로 한 줄씩 주고받는다. **한 줄이 깨져도 안 죽는다** — 다리가 죽으면
    바깥 AI 는 까닭도 모른 채 도구를 통째로 잃는다."""
    들어옴 = 들어옴 or sys.stdin
    나감 = 나감 or sys.stdout
    열쇠 = _열쇠()
    for 줄 in 들어옴:
        줄 = 줄.strip()
        if not 줄:
            continue
        try:
            요청 = json.loads(줄)
        except ValueError:
            continue
        try:
            답 = 다뤄주기(요청, 주소, 열쇠)
        except Exception as e:           # 무슨 일이 나도 다리는 산다
            답 = {"jsonrpc": "2.0", "id": 요청.get("id"),
                 "error": {"code": -32000, "message": f"{type(e).__name__}: {e}"}}
        if 답 is not None:
            나감.write(json.dumps(답, ensure_ascii=False) + "\n")
            나감.flush()


def 설정글(주소: str = 기본주소) -> dict:
    """`claude --mcp-config` 에 줄 설정. **얼려도 도는 길로 적는다.**

    ★ 구운 앱에는 파이썬이 따로 없다 — 제 실행파일을 `--mcp` 로 다시 부른다.
    """
    import sys as _시

    if getattr(_시, "frozen", False) or getattr(_시, "_MEIPASS", None):
        명령, 인자 = _시.executable, ["--mcp"]
    else:
        명령, 인자 = _시.executable, [str(__file__), "--mcp"]
    return {"mcpServers": {이름: {"command": 명령, "args": 인자,
                                "env": {"VC_MCP_주소": 주소}}}}


def _self_check() -> None:
    import io

    # ★ 도구 설명이 곧 지시다 — 비어 있으면 모델이 못 고른다
    for t in 도구들:
        assert t["name"] and len(t["description"]) > 10, t
        assert t["inputSchema"]["type"] == "object", t
        for 꼭 in t["inputSchema"].get("required", []):
            assert 꼭 in t["inputSchema"]["properties"], (t["name"], 꼭)
    assert len({t["name"] for t in 도구들}) == len(도구들), "도구 이름이 겹친다"
    # ★★ **이름과 인자 키는 영숫자여야 한다.** 한글로 지었다가 실기에서 API 가
    #   도구를 통째로 거부했다 — 검사로는 안 잡히고 진짜로 불러 봐야 나오던 자리다.
    import re as _re9

    맞는꼴 = _re9.compile(r"^[A-Za-z0-9_-]{1,64}$")
    for t in 도구들:
        assert 맞는꼴.match(t["name"]), f"도구 이름에 영숫자 아닌 것이 있다: {t['name']}"
        for 키 in t["inputSchema"]["properties"]:
            assert 맞는꼴.match(키), f"{t['name']} 의 인자 키가 영숫자가 아니다: {키}"
    # ★★ **우리끼리 쓰는 `문` 은 바깥에 안 내보낸다** — 내보내면 모델이 그걸 읽고 헷갈린다
    assert all("문" not in t for t in 알림들()), 알림들()[0]

    # --- JSON-RPC ---
    시작 = 다뤄주기({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert 시작["result"]["protocolVersion"] == 프로토콜, 시작
    assert 시작["result"]["capabilities"]["tools"] == {}, 시작
    # 알림엔 답하지 않는다 — 답하면 짝이 안 맞아 바깥이 멈춘다
    assert 다뤄주기({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    목록 = 다뤄주기({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert len(목록["result"]["tools"]) == len(도구들), 목록
    모름 = 다뤄주기({"jsonrpc": "2.0", "id": 3, "method": "없는것"})
    assert 모름["error"]["code"] == -32601, 모름

    # --- 문 두드리기: 가짜 서버로 **끝까지** 태운다 ---
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    받은: list[tuple] = []

    class _손(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _답(self, 것):
            글 = json.dumps(것, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(글)))
            self.end_headers()
            self.wfile.write(글)

        def do_GET(self):
            받은.append(("GET", self.path, None, self.headers.get("Authorization")))
            self._답({"hits": [{"title": "찾은 글"}]})

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            몸 = json.loads(self.rfile.read(n).decode()) if n else {}
            받은.append(("POST", self.path, 몸, self.headers.get("Authorization")))
            self._답({"ok": True})

    집 = HTTPServer(("127.0.0.1", 0), _손)
    주소 = f"http://127.0.0.1:{집.server_port}"
    실 = threading.Thread(target=집.serve_forever, daemon=True)
    실.start()
    try:
        난것 = 손잡이("note_search", {"q": "한글"}, 주소, "tok-1")
        assert 난것["hits"][0]["title"] == "찾은 글", 난것
        assert 받은[-1][0] == "GET" and "q=" in 받은[-1][1], 받은[-1]
        assert 받은[-1][3] == "Bearer tok-1", 받은[-1][3]
        # ★ HTTP 머리말은 latin-1 만 된다 — 열쇠에 한글이 섞여도 **죽지 말고 말해야** 한다
        탈열쇠 = 손잡이("note_search", {"q": "ㄱ"}, 주소, "열쇠값")
        assert "error" in 탈열쇠, 탈열쇠

        # ★★ **기본은 덧붙이기다.** 덮어쓰기를 기본으로 하면 어제 적은 것이 조용히 지워진다.
        손잡이("note_write", {"title": "ㄱ", "text": "ㄴ"}, 주소, "k")
        assert 받은[-1][2]["mode"] == "append", 받은[-1][2]
        손잡이("note_write", {"title": "ㄱ", "text": "ㄴ", "mode": "replace", "kind": "메모"},
            주소, "k")
        assert 받은[-1][2]["mode"] == "replace" and 받은[-1][2]["kind"] == "메모"
        # 갈래를 안 주면 아예 안 보낸다 — 빈 갈래로 덮어쓰면 갈래가 지워진다
        손잡이("note_write", {"title": "ㄱ", "text": "ㄴ"}, 주소, "k")
        assert "kind" not in 받은[-1][2], 받은[-1][2]

        손잡이("project_log", {"name": "P", "decision": "이렇게 한다"}, 주소, "k")
        assert 받은[-1][2] == {"name": "P", "decisions": ["이렇게 한다"]}, 받은[-1][2]

        # 모든 도구가 **실제로 불린다** — 문 만드는 함수가 터지면 여기서 걸린다
        본보기 = {"q": "ㄱ", "title": "ㄱ", "text": "ㄴ", "new_title": "ㄴ",
               "question": "ㄱ", "name": "P", "one_line": "ㄴ", "decision": "ㄷ"}
        for t in 도구들:
            난것 = 손잡이(t["name"], 본보기, 주소, "k")
            assert "error" not in 난것, (t["name"], 난것)

        # tools/call 이 그대로 흐른다
        불림 = 다뤄주기({"jsonrpc": "2.0", "id": 9, "method": "tools/call",
                    "params": {"name": "daily_log", "arguments": {"text": "했다"}}},
                   주소, "k")
        assert 불림["result"]["isError"] is False, 불림
        assert 받은[-1][1] == "/eb/v1/daily", 받은[-1]

        # ★★ **없는 도구를 불러도 안 죽는다** — 까닭을 담아 돌려준다
        탈 = 다뤄주기({"jsonrpc": "2.0", "id": 10, "method": "tools/call",
                   "params": {"name": "no_such_tool", "arguments": {}}}, 주소, "k")
        assert 탈["result"]["isError"] is True and "없다" in 탈["result"]["content"][0]["text"]

        # --- stdio 한 바퀴 ---
        들어옴 = io.StringIO('{"jsonrpc":"2.0","id":1,"method":"initialize"}\n'
                          '깨진 줄\n'
                          '{"jsonrpc":"2.0","method":"notifications/initialized"}\n'
                          '{"jsonrpc":"2.0","id":2,"method":"tools/list"}\n')
        나감 = io.StringIO()
        돌기(들어옴, 나감, 주소)
        줄들 = [json.loads(x) for x in 나감.getvalue().splitlines() if x.strip()]
        # ★ 깨진 줄·알림에는 답이 없다 — 답을 흘리면 짝이 어긋나 바깥이 멈춘다
        assert [x["id"] for x in 줄들] == [1, 2], 줄들
    finally:
        집.shutdown()

    # VC 가 안 떠 있어도 **까닭을 말한다** — 조용히 실패하지 않는다
    죽은것 = 두드리기("/eb/v1/hello", None, "GET", "http://127.0.0.1:1", "k")
    assert "안 떠 있다" in 죽은것.get("error", ""), 죽은것

    설정 = 설정글()
    assert "vc" in 설정["mcpServers"] and 설정["mcpServers"]["vc"]["command"], 설정

    print("vcmcp self-check 통과")


if __name__ == "__main__":
    if "--check" in sys.argv:
        _self_check()
    elif "--mcp" in sys.argv:
        import os

        돌기(주소=os.environ.get("VC_MCP_주소") or 기본주소)
