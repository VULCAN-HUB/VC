"""EB PC 서버 — 폰이 붙는 창구 (protocol.md).

폰이 오케스트레이터 본체이고 PC는 서버다(결정 25). PC가 하는 일은 셋뿐이다:
로컬 AI 구동(창구 제공), 분석·성장, 기억 창고.

표준 라이브러리만 쓴다. 붙는 클라이언트가 사용자 본인의 폰 하나뿐이라
웹 프레임워크를 더할 이유가 없다. 동시 접속이 문제가 되면 그때 바꾼다.
전송 보안·NAT 통과는 Tailscale이 담당한다(결정 16).
"""

from __future__ import annotations

import os
import tempfile
import base64
import hashlib
import hmac
import json
import queue
import re
import time
from dataclasses import asdict
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import paths

import backends
import brain
import model_store
import models_config
import notes
import plugins as 확장들
import remote
import skills
from eb_protocol import PROTOCOL_VERSION, Hello, LogEvent
from modules import build_modules
from notes import Notes
from orchestrator import Orchestrator
from skills import SkillStore
import keystore
from store import Store

# ★★ 설정 자리는 **부를 때** 정한다(`paths.config_path()`). 불러올 때 박아 두면 옛 창고 옮기기 **전** 자리를 가리켜,
#   원본을 지운 뒤 「없다」고 보고 **새 열쇠로 옛 자리에 다시 만들었다** — 업그레이드 첫 켜기에 폰 짝짓기가 풀리고
#   기록 폴더에 열쇠 파일이 생겼다(⑦ 실기 2026-09-15).
MAX_IMAGE_BYTES = 12 * 1024 * 1024  # 폰 사진 한 장이 이보다 크면 줄여서 보내야 한다
# 글 한 편을 통째로 줄 때의 상한. **넉넉하다** — 오너 창고에서 제일 긴 글이 3,241자다.
# 아껴서 답을 자르면 AI 가 다시 부르므로 되레 손해고, 상한이 없으면 5만 자도 그대로 나간다.
# `full=1` 로 뚫는다. 자르면 `cut` 으로 말한다.
# 한 번에 돌려주는 장 수의 위. `k=99999`·`k=-1` 로 창고가 통째로 나가던 것을 막는다.
# 제목만 주는 `brief=1` 은 한 장이 싸므로(60장에 4,080자) 훨씬 높게 둔다 — 목록 훑기가 그 길이다.
MAX_HITS = 50
MAX_HITS_BRIEF = 200

MAX_NOTE_CHARS = 20000


def _알림(말: str) -> None:
    """콘솔에 찍고 **기록 파일에도** 남긴다 — 구운 판은 콘솔이 없어 `print` 가 사라진다."""
    print(말)
    try:
        import report

        report.trail(말)
    except Exception:
        pass


def load_config(path: Path | None = None) -> dict[str, Any]:
    """설정이 없으면 페어링 토큰을 만들어 저장한다. 이 토큰이 QR에 실린다(결정 16)."""
    path = path or paths.config_path()
    if path.exists():
        # ★★ **설정이 깨져도 켜져야 한다.** `json.loads` 가 그대로 터져 서버·창이 아예 안 켜졌다.
        #   깨졌으면 지우지 않고 `.깨짐-<시각>` 으로 옆에 치우고 새로 만든다(열쇠가 새로 나오니
        #   폰은 다시 짝지어야 한다 — 안 켜지는 것보다 낫다). 열쇠만 빠졌으면 열쇠만 채운다.
        try:
            cfg = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(cfg, dict):
                raise ValueError("설정이 사전이 아니다")
        except (ValueError, OSError) as 깨짐:
            try:
                path.replace(path.with_name(f"{path.name}.깨짐-{time.strftime('%Y%m%d-%H%M%S')}"))
            except OSError:
                pass
            _알림(f"[설정] 깨져서 옆에 치우고 새로 만든다 ({type(깨짐).__name__}) — 폰은 다시 짝지어야 한다")
        else:
            바꿈 = False
            if not isinstance(cfg.get("pair_token"), str) or not cfg.get("pair_token"):
                cfg["pair_token"] = secrets.token_urlsafe(32)
                바꿈 = True
            # ★★ 바깥 AI 키가 평문으로 있으면 운영체제 보관소로 옮기고 설정에서는 지운다(오너 결정 1).
            #   설정 파일은 진단 묶음·백업·동기화로 쉽게 밖에 나간다. 못 옮기면 그대로 둔다(키를 잃지 않게).
            if isinstance(cfg.get("backend"), dict) and keystore.평문키옮기기(cfg["backend"]):
                바꿈 = True
            if 바꿈:
                path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
            return cfg
    cfg = {
        "pair_token": secrets.token_urlsafe(32),
        # 기본은 VC 자체 엔진(결정 36). 사용자는 Ollama를 따로 깔지 않는다.
        # 클라우드로 바꾸려면 kind를 anthropic·gemini·openai_compatible로.
        "backend": {"kind": "local", "model_dir": str(paths.models_dir())},
        # 역할별 모델. **비우면 사양을 재서 자동으로 고른다**(결정 42).
        # 사용자가 고른 값이 있으면 그게 이긴다. 새 모델은 파일만 넣고 이름을 적으면 된다.
        "models": {"chat": "", "vision": "", "stt": "", "voice": ""},
    }
    path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return cfg


class Hub:
    """폰으로 밀어 보낼 제안 큐. 폰이 SSE로 붙어 있으면 바로, 아니면 다음 접속 때."""

    def __init__(self) -> None:
        self._subs: list[queue.Queue] = []
        self._lock = threading.Lock()

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        with self._lock:
            self._subs.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)

    def publish(self, event: dict[str, Any]) -> None:
        with self._lock:
            subs = list(self._subs)
        for q in subs:
            q.put(event)


카드미리보기 = notes.카드미리보기   # 폰 카드 · 맥 VC 최근 글이 같이 쓴다


def 앞머리(path: str) -> str:
    """글 파일의 앞머리(`---` 사이) 글자. 색인 몸에는 앞머리가 없어 파일에서 읽는다."""
    try:
        with open(path, encoding="utf-8") as f:
            첫 = f.readline()
            if 첫.strip() != "---":
                return ""
            줄 = []
            for 한 in f:
                if 한.strip() == "---":
                    break
                줄.append(한)
                if len(줄) > 60:
                    break
            return "".join(줄)
    except OSError:
        return ""


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "EB/" + PROTOCOL_VERSION

    # --- 공통 -----------------------------------------------------------

    def log_message(self, fmt: str, *args: Any) -> None:
        pass  # 접근 로그는 안 남긴다. 학습 로그가 따로 있다.

    def _bearer(self) -> str:
        header = self.headers.get("Authorization", "")
        return header[7:] if header.startswith("Bearer ") else ""

    @staticmethod
    def _같은열쇠(온것: str, 우리것: str) -> bool:
        """열쇠 두 개가 같은가. **바이트로 견준다.**

        ★★ `hmac.compare_digest` 는 글자열끼리는 **ASCII 만** 견준다 — 한글이 섞이면
        `TypeError: comparing strings with non-ASCII characters` 로 터져, 열쇠가 틀렸다는
        401 대신 **500 이 나가고 연결이 끊겼다.** 폰에는 그것이 「컴퓨터에 못 닿았어」로 보여
        「테일스케일이 문젠가」를 한참 뒤졌다(2026-09-19 실기에서 잡았다).
        바이트로 견주면 아무 글자나 와도 안 터지고, 견주는 시간도 그대로 일정하다.
        """
        return hmac.compare_digest(온것.encode("utf-8", "surrogatepass"),
                                   우리것.encode("utf-8", "surrogatepass"))

    def _authorized(self, path: str = "") -> bool:
        """폰·내 PC는 페어링 토큰으로, 외부 PC는 폰이 승인한 원격 토큰으로 들어온다.

        원격 토큰은 허용된 경로에서만 통한다 — 검사는 remote.RemoteGate가 한다.
        """
        token = self._bearer()
        if token and self._같은열쇠(token, self.server.cfg["pair_token"]):
            self.session = None
            return True

        # 브라우저는 헤더를 못 붙이는 자리(내려받기 링크)가 있어 ?t= 도 받는다.
        token = token or (parse_qs(urlparse(self.path).query).get("t") or [""])[0]
        self.session = self.server.gate.check(token, path or urlparse(self.path).path,
                                              self._client_ip())
        return self.session is not None

    def _client_ip(self) -> str:
        """토큰을 묶을 주소. 폰이 중계 중이면 폰 IP가 아니라 진짜 손님 주소를 쓴다.

        폰 IP로 묶으면 같은 핫스팟에 붙은 다른 기기까지 통과한다. 헤더를 믿되,
        **폰의 페어링 토큰을 함께 제시했을 때만** 믿는다 — 안 그러면 외부 PC가
        헤더 한 줄로 IP 고정을 무력화한다.
        """
        relay = self.headers.get("X-EB-Relay", "")
        claimed = self.headers.get("X-EB-Client", "")
        if claimed and relay and self._같은열쇠(relay, self.server.cfg["pair_token"]):
            return claimed
        return self.client_address[0]

    def _비우고끊기(self) -> None:
        """거절한 뒤 **받은 본문 앞머리를 잠깐(0.5초) 비우고** 끊는다.

        ★ 안 읽은 바이트가 남은 채 닫으면 윈도우가 RST 를 보내 **상대가 413 을 못 읽고 「연결 끊김」만 본다**
        (재 봤다: 60번 중 4번). 4GB 를 다 읽는 게 아니다 — 0.5초만 보고 끊는다.
        """
        import socket

        try:
            self.wfile.flush()
            self.connection.shutdown(socket.SHUT_WR)
            self.connection.settimeout(0.5)
            끝 = time.monotonic() + 0.5
            while time.monotonic() < 끝 and self.connection.recv(65536):
                pass
        except OSError:
            pass

    def _memory_write(self, title: str, text: str, mode: str, body: dict) -> None:
        """`/eb/v1/memory` 쓰기 몸. 부르는 쪽이 글 잠금을 쥔 채 부른다."""
        old = self.server.notes.read(title)

        # **사람이 고쳐 놓은 것을 관찰이 덮으면 안 된다.** 틀린 걸 바로잡았는데
        # 다음 기록이 되돌려 놓으면 사람은 이 물건을 못 믿는다(결정 22와 같은 결).
        #
        # ★★ **`edited_by` 만 보면 못 막는다.** 그 표시는 **화면에서 고칠 때만** 붙는다 —
        #   옵시디언·메모장으로 고친 것에는 안 붙는데, 이 물건은 **옵시디언 대용**이라
        #   밖에서 고치는 것이 주된 길이다. 실제로 재 보니 밖에서 보탠 줄을 AI 가
        #   `force` 없이 통째로 지웠다(201 이 떨어졌다).
        #   ※ `notes._남의손인가` 가 지문으로 그것을 가려내긴 한다 — 그래서 **지난 판은
        #     반드시 남는다.** 다만 그건 「덮은 뒤에 되살릴 수 있다」이지 「안 덮는다」가 아니다.
        #   → **덮어쓰기는 늘 `force` 를 받는다.** 되돌리기 어려운 일은 명시적으로 한다.
        #   기본은 `append` 라 대부분은 이 길로 안 온다. 덧붙이기는 아무것도 안 지운다.
        # ★★ **`force` 는 진짜 참(`true`)일 때만 뚫는다.** `bool()` 로 읽으니 글자 `"false"`·`"0"` 도
        #   참이 되어 **사람이 고친 글을 덮었다** — 덮어쓰기 막이가 글자 한 줄에 무너졌다.
        # ★★ **오프라인에서 고친 글 되돌려 보내기(오너 결정 28).** 폰은 제가 본 판의 지문
        #   (`base_hash`)을 함께 보낸다. 그 사이 컴퓨터 쪽 글이 그대로면 **조용히 덮고**,
        #   바뀌었으면 **아무것도 안 지우고 둘 다 남긴다** — 폰이 고친 판을 글 끝에 붙이고
        #   「둘이 달라 붙여 뒀다」고 알린다. 사람이 보고 정리한다(덮어쓰기는 늘 명시적이다).
        base = body.get("base_hash")
        if mode == "replace" and old is not None and isinstance(base, str) and base:
            지금 = hashlib.sha256(old.body.encode("utf-8")).hexdigest()
            if 지금 == base:
                body = {**body, "force": True}          # 내가 본 그 판 그대로다 — 덮어도 안전하다
            else:
                언제 = time.strftime("%Y-%m-%d %H:%M")
                붙임 = f"\n\n## 폰에서 고친 판 ({언제})\n\n{text}"
                경로 = self.server.notes.append(title, 붙임, old.kind, pinned=old.pinned)
                self.server.notes.embed_one(경로)
                self.server.notes._vec_cache = None
                실림2 = getattr(self.server, "plugins", None)
                if 실림2:
                    실림2.fire_saved(notes.제목맞춤(title), log=_알림)
                return self._send(201, {
                    "title": title, "mode": "append", "merged": "appended",
                    "hint": "폰에서 고치는 사이 컴퓨터 쪽 글도 바뀌어, 덮지 않고 글 끝에 붙였다"})

        if mode == "replace" and old is not None and body.get("force") is not True:
            return self._send(409, {
                "error": "이미 있는 글을 통째로 덮으려 한다. force 가 필요하다",
                "title": title, "chars": len(old.body),
                "edited_by": old.edited_by or "(모름 — 밖에서 고쳤을 수 있다)",
                "hint": "덧붙이려면 mode 를 빼라(기본 append). 정말 덮으려면 force: true"})

        # ★★ **없는 글에 처음 덧붙이는 것도 `append` 로 보낸다.** 전에는 「없으면 새로 쓰기」로 갈라져
        #   잠금 밖이었다 — 두 AI 가 같은 새 글에 동시에 쌓으면 서로 덮어 줄이 사라졌다(재 봤다).
        if mode == "append":
            path = self.server.notes.append(title, text,
                                            body.get("kind", old.kind if old else "note"),
                                            pinned=body.get("pinned") is True)
        else:
            note = notes.Note(
                title=title,
                body=text,
                kind=body.get("kind", old.kind if old else "note"),
                pinned=body.get("pinned") is True or bool(old and old.pinned),   # "false" 는 거짓
                aliases=old.aliases if old else [],
            )
            path = self.server.notes.write(note)
        # ★★ **방금 쓴 글은 바로 뜻으로도 찾혀야 한다.** 안 그러면 AI 가 제가 저장한 것을
        #   못 찾아 **다시 검색한다** — 그게 800자다. 뒤에서 도는 실은 30초마다라 그
        #   사이가 빈다.
        #   ★ **`embed_some(1)` 로는 안 된다** — 그 차례의 첫 키가 `used_at DESC` 라
        #   검색으로 읽힌 글들이 앞선다. 빈 창고에서는 됐는데(읽힌 글이 없었다) 실무
        #   창고에서 검색을 스무 번 돌린 뒤에는 **엉뚱한 글이 채워졌다.**
        #   `embed_one` 으로 **이 글만** 콕 집는다. 10ms 쯤이라 쓰기 길에 얹어도 된다.
        #   ※ 임베더가 아직 없으면(모델 없음·아직 안 올림) 아무 일도 안 한다.
        try:
            self.server.notes.embed_one(path)
            self.server.notes._vec_cache = None
        except Exception as e:
            # 벡터를 못 만들어도 저장은 끝났다. 다만 **방금 쓴 글이 뜻으로 안 찾히는 것**이라 남긴다.
            _알림(f"[뜻 벡터] 방금 쓴 글을 못 만들었다 — {type(e).__name__}: {e}")
        # 확장에 「글이 저장됐다」고 알린다(결정 23). **확장이 터져도 저장은 이미 끝났다** —
        # 예외는 `fire_saved` 안에서 잡혀 자국으로만 간다.
        저장제목 = notes.제목맞춤(title)
        실림 = getattr(self.server, "plugins", None)
        if 실림:
            실림.fire_saved(저장제목, log=_알림)
        # ★ 절대 경로는 안 싣는다 — 집 폴더(사용자 이름)가 들어 있고, AI 는 제목으로 부르므로 쓸 데가 없다(쓸 때마다 글자만 탄다).
        답 = {"title": title, "mode": mode}
        # ★ 파일에 못 쓰는 글자(? : / …)는 전각으로 바뀌어 저장된다. **바뀐 제목을 알려 준다** —
        #   AI 가 다음에 그 제목으로 부르거나 [[링크]] 로 이을 때 헷갈리지 않게.
        if 저장제목 != title:
            답["saved_as"] = 저장제목
        # ★ **쓴 자리에서 뜻이 가까운 글을 알려 준다**(제목 셋, 60자쯤). 잇기는 **선택**이다 —
        #   저장소 규칙 1조가 「[[링크]] 를 일부러 넣을 필요 없다, 뜻 검색·비슷한 것 줄이 대신한다」
        #   이고 실제로 뜻 검색은 안 이은 글도 찾는다(20물음 13). 처음엔 「안 이으면 못 찾는다」고
        #   적었는데 **틀린 말**이었다. 사람·AI 가 이어짐을 **말하고 싶을 때** 쓸 재료만 준다.
        try:
            가까운 = [t for t, _ in self.server.notes.semantic(text[:600], k=4)
                    if t != title][:3]
            if 가까운:
                답["link_to"] = 가까운
                답["hint"] = "뜻이 가까운 글이다. 이어짐을 적고 싶을 때만 [[제목]] — 안 이어도 뜻 검색이 찾는다"
        except Exception:
            pass        # 이을 곳을 못 찾아도 저장은 끝났다
        # ★★ **force 로 덮었으면 되돌릴 자리를 알려 준다.** 지난 판은 남지만
        #   AI 가 그것을 볼 길이 없었다(화면에서만 된다) — 안전망이 반쪽이었다.
        #   덮은 그 자리에서 「되돌리려면 여기」를 주면 AI 가 스스로 고칠 수 있다.
        if mode == "replace" and old is not None:
            지난판 = self.server.notes.history(title)
            if 지난판:
                언제, 파일 = 지난판[0]
                답["undo"] = {"when": 언제, "path": str(파일),
                              "chars": len(old.body),
                              "how": "그 파일의 몸을 읽어 mode=replace · force 로 다시 쓴다"}
        return self._send(201, 답)

    def _send(self, code: int, payload: Any = None) -> None:
        self._보낸코드 = code          # 쓰기가 성공했는지 부른 쪽이 본다(폰 새 글 한 번만 받기)
        body = b"" if payload is None else json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _send_html(self, body: bytes) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        # 원격 화면은 바깥에서 아무것도 안 받아온다. 그걸 브라우저에도 못 박아 둔다.
        self.send_header("Content-Security-Policy",
                         "default-src 'none'; style-src 'unsafe-inline'; "
                         "script-src 'unsafe-inline'; connect-src 'self'; img-src 'self' data:")
        self.end_headers()
        self.wfile.write(body)

    # 한 번에 받는 본문의 한도. 서버는 0.0.0.0에 열려 있어서 **같은 공유기의 누구든**
    # 말을 걸 수 있다. 예전엔 Content-Length를 그대로 믿고 읽어서, 4GB라고 적어 보내면
    # 그만큼 읽으려다 굳었다. 기록 하나가 8MB를 넘을 일은 없다.
    MAX_BODY = 8 * 1024 * 1024

    class TooBig(ValueError):
        """본문이 한도를 넘었다."""

    class BadLength(ValueError):
        """Content-Length 가 숫자가 아니거나 음수다."""

    def _body(self) -> Any:
        # ★ 음수·글자 Content-Length 는 둘 다 500(까닭 없음)이었다 [잰 것]. 음수는 `rfile.read(-5)` 가
        #   끝까지 읽으려 들 수 있는 자리라 믿지 않는다. 둘 다 400 으로 끊는다(같은 공유기 누구든 보낼 수 있다).
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise self.BadLength(self.headers.get("Content-Length"))
        if length < 0:
            raise self.BadLength(length)
        if length > self.MAX_BODY:
            raise self.TooBig(length)
        # 적어 낸 길이보다 적게 오는 경우도 있다 — read는 오는 만큼만 준다.
        return json.loads(self.rfile.read(length) or b"{}")

    # --- 라우팅 ---------------------------------------------------------

    # ★★ **틀린 길·틀린 이름에 「not found」만 주면 AI 는 짐작으로 다시 두드린다** —
    #   한 번이 800자다. 재 보니 `search?query=` 는 **조용히 빈 검색**(창고 앞머리)을 줬고,
    #   `search` 를 POST 로 부르면 그냥 404 였다. **무엇이 틀렸는지 말해 준다.**
    GET_PATHS = ("/eb/v1/hello", "/eb/v1/status", "/eb/v1/templates", "/eb/v1/attach", "/eb/v1/trash", "/eb/v1/folders", "/eb/v1/plugins", "/eb/v1/changes", "/eb/v1/memory/search", "/eb/v1/memory/note", "/eb/v1/graph")
    POST_PATHS = ("/eb/v1/memory", "/eb/v1/memory/delete", "/eb/v1/memory/rename", "/eb/v1/skills/propose",
                  "/eb/v1/me/learn",
                  "/eb/v1/ask", "/eb/v1/log", "/eb/v1/attach", "/eb/v1/assist", "/eb/v1/memory/mark", "/eb/v1/trash/restore", "/eb/v1/daily", "/eb/v1/memory/task")

    def _길없다(self, path: str) -> dict:
        답 = {"error": "not found", "path": path}
        딴쪽 = self.POST_PATHS if self.command == "GET" else self.GET_PATHS
        if path in 딴쪽:
            답["hint"] = ("그 길은 POST 다" if self.command == "GET" else "그 길은 GET 이다")
            return 답
        이쪽 = self.GET_PATHS if self.command == "GET" else self.POST_PATHS
        가까운 = [c for c in 이쪽 if c.startswith(path.rsplit("/", 1)[0])]
        답["paths"] = 가까운 or list(이쪽)
        return 답

    def do_GET(self) -> None:
        # ★ 읽는 쪽도 마찬가지다 — 파일이 읽는 사이 사라지거나(밖에서 지움) 깨져 있으면
        #   예외가 그대로 새 나가 **답도 없이 연결이 끊긴다.** 끊긴 연결은 아무 말도 안 한다.
        try:
            return self._get()
        except notes.Vanished as 사라짐:
            return self._send(410, {"error": "읽는 사이에 없어졌다", "where": str(사라짐)})
        except OSError as 못읽음:
            return self._send(500, {"error": "못 읽었다", "why": type(못읽음).__name__})
        except Exception as 뜻밖:
            # ★ **예상 못 한 예외도 답은 한다.** 새로 넣은 조회에서 SQL 이 틀렸을 때 서버가
            #   답도 없이 연결을 끊었다 — 부르는 쪽은 무엇이 틀렸는지 모른다. 이름만 알려 준다.
            # ★ 경로만 찍는다 — 브라우저 링크는 `?t=토큰` 을 달고 오므로 통째로 찍으면 열쇠가 샌다.
            _알림(f"[서버] GET {urlparse(self.path).path[:80]} 에서 뜻밖의 예외: {type(뜻밖).__name__}: {뜻밖}")
            return self._send(500, {"error": "서버 안에서 뜻밖의 일이 났다", "why": type(뜻밖).__name__})

    def _get(self) -> None:
        url = urlparse(self.path)

        # 인증 앞에 오는 둘. 여기서 QR을 받아 폰에 보여주는 게 원격의 시작이다.
        if url.path in ("/", "/remote"):
            session = self.server.gate.open(self._client_ip())
            via_phone = (parse_qs(url.query).get("via") or [""])[0] == "phone"
            return self._send_html(remote.page(session, via_phone))

        # 폰 앱 껍데기. 열쇠는 안 들어 있고 자료는 열쇠를 단 API 로만 온다(phone_app.py).
        if url.path == "/app":
            import phone_app

            return self._send_html(phone_app.page())

        if url.path == "/eb/v1/remote/status":
            sid = (parse_qs(url.query).get("s") or [""])[0]
            return self._send(200, self.server.gate.status(sid))

        if not self._authorized(url.path):
            return self._send(401, {"error": "unauthorized"})

        # 폴더 보기(편의 기능 29번 · 원노트 공책·애플 노트 폴더) — 폴더마다 글 수. 기계 자리는 뺀다.
        if url.path == "/eb/v1/folders":
            뿌리 = str(self.server.notes.root)
            셈: dict[str, int] = {}
            for (경로,) in self.server.notes.conn.execute("SELECT path FROM notes"):
                안 = Path(경로).parent
                try:
                    이름 = 안.relative_to(뿌리).as_posix()
                except ValueError:
                    continue
                if 이름 in (".", ""):
                    이름 = "/"
                if any(x.startswith((".", "_")) for x in 이름.split("/")):
                    continue
                셈[이름] = 셈.get(이름, 0) + 1
            return self._send(200, {"folders": [{"path": k, "notes": v}
                                                for k, v in sorted(셈.items())]})

        if url.path == "/eb/v1/trash":
            return self._send(200, {"trash": [
                {"id": self._휴지통id(판), "title": t, "when": w}
                for t, w, 판, _ in self.server.notes.trashed()[:100]]})

        # 첨부 받아 보기 — 폰 글 보기가 사진을 그린다(오너 실기 2026-09-16: 앱에서 사진이 안 보였다).
        # 이름만 받는다 — 경로 성분은 버리고 첨부 꼴만, 창고 안에서만 찾는다.
        if url.path == "/eb/v1/attach":
            물음 = parse_qs(url.query)
            name = (물음.get("name") or [""])[0]
            path = self.server.notes.attachment_path(Path(name).name) if name else None
            if path is None or not path.is_file():
                return self._send(404, {"error": "없는 첨부", "name": name[:80]})
            # ★★ **목록 카드는 작은 사진을 받는다**(`w=320`). 전에는 카드마다 **원본을 통째로**
            #   받아 갔다 — 폰에서 목록만 훑어도 몇 MB 씩 나갔다. 못 줄이는 꼴(HEIC 등)이면
            #   원본을 그대로 준다 — 폰이 그것을 제 자리에 넣어 **두 번은 안 받는다.**
            try:
                넓이 = int((물음.get("w") or ["0"])[0])
            except ValueError:
                넓이 = 0
            if 넓이:
                작은 = self.server.notes.thumbnail_path(Path(name).name, 넓이)
                if 작은 is not None:
                    path = 작은
            import mimetypes

            data = path.read_bytes()
            꼴 = ("image/heic" if path.suffix.lower() in (".heic", ".heif")
                 else mimetypes.guess_type(path.name)[0] or "application/octet-stream")
            self.send_response(200)
            self.send_header("Content-Type", 꼴)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "private, max-age=86400")
            self.end_headers()
            self.wfile.write(data)
            return None

        # 서식을 폰까지(5단계 · 결정 19) — 폰 적기 탭이 부른다. `{{날짜}}` 같은 자리는 폰이 **적는 순간** 채운다.
        if url.path == "/eb/v1/templates":
            n = self.server.notes
            return self._send(200, {"templates": [{"name": t, "body": n.template(t)} for t in n.templates()]})

        # ★★ **바뀐 것만 내어 준다**(결정 30 · 딴 PC 의 VC 가 사본을 쌓는 문).
        #   메인이 죽어도 손님 PC 의 자료가 살아 새 메인이 될 수 있어야 한다 — 그러려면
        #   손님이 **글을 통째로 들고** 있어야 한다. 매번 전부 받으면 못 쓰니 **그때 뒤로 바뀐 것**만.
        #   ※ 지운 글은 「지난 판은 있는데 글이 없는 것」(휴지통)으로 알아낸다 — VC 는 지울 때 늘 한 판 남긴다.
        if url.path == "/eb/v1/changes":
            물음 = parse_qs(url.query)
            try:
                뒤로 = float((물음.get("since") or ["0"])[0])
            except ValueError:
                return self._send(400, {"error": "since 는 숫자(초)여야 한다"})
            몇개 = max(1, min(500, int((물음.get("limit") or ["200"])[0] or 200)))
            n = self.server.notes
            줄들 = n.conn.execute(
                "SELECT path, title, mtime, kind FROM notes WHERE mtime > ? ORDER BY mtime LIMIT ?",
                (뒤로, 몇개)).fetchall()
            바뀜 = [{"title": r["title"], "path": r["path"], "mtime": r["mtime"], "kind": r["kind"]}
                  for r in 줄들]
            지움 = [{"title": t, "when": 언제} for t, 언제, _마지막, _자리 in n.trashed()[:100]]
            # 다음에 어디서부터 받을지 — 받은 것 중 가장 늦은 때. 없으면 물어본 자리 그대로.
            다음 = max((r["mtime"] for r in 줄들), default=뒤로)
            return self._send(200, {"changes": 바뀜, "trashed": 지움, "next_since": 다음,
                                    "more": len(줄들) >= 몇개})

        # 확장 플러그인(결정 23 · 편의 기능 31번) — **보기만** 한다.
        # ★ 폰에서 확장을 켜고 끄는 길은 일부러 안 낸다 — 코드가 도는 곳은 컴퓨터이고,
        #   「이 컴퓨터에서 코드가 돈다」 경고를 보고 켜는 일은 그 컴퓨터 앞에서 한다(안전 원칙).
        if url.path == "/eb/v1/plugins":
            실림 = getattr(self.server, "plugins", None)
            정보 = 실림.infos if 실림 else 확장들.find(cfg=self.server.cfg)
            return self._send(200, {"plugins": [
                {"name": i.name, "version": i.version, "note": i.note,
                 "on": i.enabled, "error": i.error} for i in 정보]})

        # 「상태·기록」(결정 17 ③) — 폰 ⋮ 메뉴가 부른다. 기록 내용·글 이름·집 경로는 가린다.
        if url.path == "/eb/v1/status":
            import report

            return self._send(200, report.상태요약())

        if url.path == "/eb/v1/hello":
            cfg = self.server.cfg
            hello = Hello(
                models=[m for m in self.server.picked["using"].values() if m],
                capabilities=["inference", "log", "memory", "skills"],
            )
            몸 = dict(hello.__dict__)
            # ★★ **창고가 무엇을 아는지 한 번에 알려 준다.** 이게 없으면 AI 는 이 창고에
            #   무엇이 들었는지 모른 채 **헛검색을 여러 번** 한다 — 한 번이 800자다.
            #   오너 창고에서 재 본 갈래: 일 2373 · 규칙 271 · 결정 120 · 일정 30.
            #   이 몇 줄(수백 자)을 보면 「결정 쪽을 좁혀 묻자」가 바로 나온다.
            #   ※ 좁히는 문법도 같이 적는다 — **아는 길을 안 알려 주면 없는 것과 같다.**
            #     (오너 지시 2026-09-12: 크레딧을 줄이는 것이 성능이다.)
            try:
                import settings

                c = self.server.notes.conn
                갈래 = {r[0]: r[1] for r in c.execute(
                    "SELECT kind, count(*) FROM notes GROUP BY kind "
                    "ORDER BY 2 DESC LIMIT 12")}
                # ★ **더 잘 찾는 길이 있으면 AI 도 알아야 한다.** 큰 뜻 모델을 받으면
                #   같은 창고에서 찾은 물음이 10 → 12 였다(오너 창고 2794장·얼린 물음 20개).
                #   AI 가 이걸 보면 오너에게 알려 줄 수 있다 — 안 알려 주면 있는 줄도 모른다.
                큰모델있나 = paths.meaning_dir("e5-base").name == "e5-base"      # exe 옆에 받은 것까지 본다
                몸["store"] = {
                    "notes": c.execute("SELECT count(*) FROM notes").fetchone()[0],
                    "kinds": 갈래,
                    # ★ 하다 만 이름 바꾸기가 있으면 **링크가 반쯤 끊긴 상태**다.
                    #   창만 그것을 봤다 — 서버로만 쓰는 AI 는 모른 채 그물을 믿는다.
                    **({"broken_rename": " → ".join(하다만)}
                       if (하다만 := self.server.notes.이름바꾸다만것()) else {}),
                    # ★ **안 이어진 글이 몇 장인가.** 오너 창고는 2820장 중 2700장(95%)이라
                    #   (링크는 선택이다 — 저장소 규칙 1조: 뜻 검색이 안 이은 글도 찾는다.)
                    "orphans": self.server.notes.외딴것수(),
                    # ★ 사람이 설정에서 적은 「내 정보」 글. 고정하지 않으니 **제목을 알려 줘야** AI 가 찾아 편다.
                    **({"me": settings.PROFILE_TITLE}
                       if self.server.notes.read(settings.PROFILE_TITLE) is not None else {}),
                    # 오너가 설정에서 연결한 바깥 계정 **이름만**(토큰은 보관소에만 있다)
                    **({"connections": 연결} if (연결 := paths.load_config().get("connections")) else {}),
                    # ★ 기록자리.txt 를 못 따라 기본 자리로 켰으면 AI 도 알아야 한다(창고가 비어 보인다).
                    **({"data_dir_warning": 쪽지} if (쪽지 := paths.적어둔자리문제()) else {}),
                    "tags": [r[0] for r in c.execute(
                        "SELECT tag FROM tags GROUP BY tag ORDER BY count(*) DESC LIMIT 12")],
                    "how": ("search?q= 로 찾는다. 좁히려면 q 에 kind:결정 · tag:이름 을 섞고, "
                            "-kind:일 처럼 빼기도 된다. "
                            "year:2026 · path:2026/09 · title:회의록(=file:, 제목만 본다) 도 된다. "
                            "\"따옴표\" 는 그 구절 그대로다. A OR B(또는) 는 하나라도 든 것. /정규식/ 은 그 꼴이 든 것. k= 로 개수(기본 5, 위 50). "
                            "몸은 안 온다 — memory/note?title=..&heading=.. 로 고른 것만 펼친다 "
                            "(heading=^이름 은 블록 한 덩이. 같은 제목이 여럿이면 카드의 folder 를 folder= 로) "
                            "(2만 자에서 자르고 cut 으로 말한다. full=1 로 뚫는다). "
                            "목록만 훑을 때는 brief=1 (제목만, 3배 싸다). "
                            "긴 글은 note 에 q= 를 주면 걸린 자리 둘레만 온다(자르면 cut=true). "
                            # ★ 인사는 **세션마다 한 번** 나가는 값이다. 이 줄은 한 번의
                            #   헛검색(800자)을 막아 주므로 남기되, 잰 값은 짧게만 적는다.
                            "★ 안 나오면 위 kinds 중 하나로 좁혀 다시 물어라(kind:결정) — 가장 많은 갈래가 밀어내서 "
                            "목록 밖에 있던 글이 1~4등으로 올라온다. "
                            "쓰기는 memory 에 POST(덧붙기가 기본). link_to 는 뜻이 가까운 글(잇기는 선택). "
                            "통째로 덮으려면 mode=replace 와 force 가 둘 다 있어야 한다. "
                            "치우기는 memory/delete(되돌릴 자리를 준다) · 제목 고치기는 memory/rename(링크도 고친다). "
                            "대화에서 오너에 대해 알게 되면 me/learn 에 POST(category·question·answer·source) — 오너 답은 안 덮는다. "
                            "connections 가 있으면 connect/이름?path=/user/repos 처럼 읽기만 된다."
                            + ("" if 큰모델있나 else
                               " ※ 더 잘 찾으려면 큰 뜻 모델 e5-base 를 받으라고 "
                               "사람에게 알려라(화면 「받을 모델」 칸, 296MB). "
                               "[잰 것] 같은 창고에서 찾은 물음 10 → 12.")),
                }
            except Exception as e:
                # 판을 못 만들어도 인사는 해야 한다. 다만 판이 빠진 인사는 AI 를 헛검색으로 이끈다 — 남긴다.
                _알림(f"[인사 판 실패] {type(e).__name__}: {e}")
            return self._send(200, 몸)

        if url.path == "/eb/v1/memory/search":
            # ★★ **꺼내기는 두 단이다.** 예전엔 걸린 여덟 장의 **몸을 통째로** 준다 —
            # 재 보니 한 번에 46,000자(≈ 18,000토큰)가 나가는데 읽는 것은 몇 줄이었다.
            #   1단(여기)  제목 · 한 줄 요약 · 소제목 목록 · 글자 수   — 여덟 장에 몇백 자
            #   2단         `/eb/v1/memory/note?title=..&heading=..` 로 **고른 구획만**
            # 예전처럼 몸까지 받으려면 `full=1` 을 붙인다 — 붙여 쓰던 쪽을 안 깨린다.
            args = parse_qs(url.query)
            q = (args.get("q") or [""])[0]
            # ★ **딴 이름으로 물어도 받아 준다.** `query=`·`text=`·`search=` 로 부르면
            #   전에는 **조용히 빈 검색**이 돌아 창고 앞머리를 줬다 — AI 는 그것이 답인 줄 안다.
            if not q:
                for 딴이름 in ("query", "text", "search", "찾기"):
                    if args.get(딴이름):
                        q = args[딴이름][0]
                        break
            # ★★ **기본을 다섯으로 둔다.** 여덟을 주면 한 번에 1272자가 나가는데,
            #   오너 창고(2794장)·얼린 물음 20개로 재 보니 **6~8등에 정답이 하나도 없었다**
            #   — 다섯으로 줄여도 맞힌 물음 수가 그대로(6/20)이고 글자만 802자로 준다(37% ↓).
            #   더 줄이면 손해다: 셋이면 4/20 으로 떨어진다. 더 필요하면 `k=` 로 올려 다시 묻는다.
            # ★★ **k 를 조인다.** 험한 물음을 던져 보니 세 군데가 새고 있었다:
            #   `k=99999` 는 474,124자를 한 방에 내보냈고(크레딧이 그대로 탄다),
            #   `k=-1` 은 SQL `LIMIT -1` 이라 **창고를 통째로**(182,114자) 줬고,
            #   `k=abc` 는 `int()` 가 터져 **서버가 답도 없이 연결을 끊었다.**
            #   위는 쉰으로 조인다 — 그보다 많이 필요하면 `brief=1` 로 훑고 고른 것만 펼친다.
            try:
                k = int((args.get("k") or ["5"])[0])
            except ValueError:
                k = 5           # 숫자가 아니면 기본값. 터뜨리는 것보다 낫다
            간추려 = (args.get("brief") or ["0"])[0] not in ("0", "", "false")
            k = max(1, min(k, MAX_HITS_BRIEF if 간추려 else MAX_HITS))
            통째로 = (args.get("full") or ["0"])[0] not in ("0", "", "false")
            카드 = (args.get("card") or ["0"])[0] not in ("0", "", "false")
            보관함 = (args.get("archived") or ["0"])[0] not in ("0", "", "false")
            # ★★ **훑을 때는 제목만 있으면 된다.** 「무슨 결정들이 있었나」처럼 목록을 보는
            #   일은 흔한데, 지금은 장마다 요약·날짜·이음선까지 실어 보낸다.
            #   [잰 것, 오너 창고] `kind:결정` 120장 — 지금 20,233자 · 제목만 6,586자(3배).
            #   AI 는 목록을 보고 **고른 것만** 다시 묻는다. 그때 요약이 필요하면 그때 준다.
            rows = self.server.notes.search(q, k * 3 if 카드 else k)
            if 카드:
                # 폰 목록 — 보관한 글은 보관함에서만(킵). AI 길은 그대로 다 본다.
                def 보관됨(r) -> bool:
                    return bool(re.search(r"(?m)^보관:\s*true\s*$", 앞머리(r["path"])))
                rows = [r for r in rows if 보관됨(r) == 보관함][:k]
            out = []
            for r in rows:
                몸 = r["body"]
                # ★★ **빈 칸과 기본값은 안 보낸다.** 여덟 장이면 그것만으로 수백 자다.
                #   재 본 값(오너 창고 2794장·물음 20개): 한 장 195자 중
                #   `created` 33 · `pinned` 15 · `headings` 14 · `links` 11 · `kind` 11 —
                #   이 창고에서는 `headings`·`links` 가 **거의 다 빈 배열**이었다.
                #   JSON 에서 빠진 칸은 「없다」로 읽힌다. 없는 것을 굳이 적어 보낼 이유가 없다.
                #   ※ **오너 지시(2026-09-12): 크레딧을 줄이는 것이 성능이다.**
                #     AI 가 한 번 꺼낼 때 나가는 글자가 곧 값이다.
                if 간추려:
                    작은장 = {"title": r["title"], "chars": len(몸)}
                    if r["kind"] and r["kind"] != "note":
                        작은장["kind"] = r["kind"]
                    out.append(작은장)
                    continue
                한장 = {
                    "title": r["title"],
                    # 물음을 넘겨 **그 물음에 걸린 줄**을 요약으로 받는다. 글자 수는 같은데
                    # AI 가 「이 글이 답하나」를 1단에서 가릴 수 있어 2단 호출이 준다.
                    "summary": notes.요약(몸, 물음=q),
                    "chars": len(몸),
                }
                if r["kind"] and r["kind"] != "note":
                    한장["kind"] = r["kind"]           # 보통은 note 다
                if r["pinned"]:
                    한장["pinned"] = True              # 거짓은 안 보낸다
                if r["created"]:
                    한장["created"] = str(r["created"])[:10]   # 날짜면 족하다. 시·분은 안 쓴다
                # 소제목은 **펼칠 자리의 목록**이다. 이름만 준다 — 깊이는 2단에서 안 쓴다.
                if 머리 := [h for _, h in notes.headings(몸)][:20]:
                    한장["headings"] = 머리
                if 이웃 := self.server.notes.neighbors(r["title"]):
                    한장["links"] = 이웃
                # ★ **같은 제목이 다른 폴더에 또 있으면 폴더를 붙인다.** 옵시디언은 `가/회의.md` 와
                #   `나/회의.md` 를 둘 다 둔다. 카드가 제목만 같으면 AI 는 어느 쪽인지 **못 고르고**
                #   둘 다 펼친다(값 두 배). 겹칠 때만 싣는다 — 대부분의 카드는 그대로다.
                if self.server.notes.twins(r["title"]):
                    try:
                        한장["folder"] = str(Path(r["path"]).parent.relative_to(
                            self.server.notes.root)).replace(chr(92), "/")
                    except ValueError:
                        pass
                if 통째로:
                    한장["body"] = 몸
                # 폰 목록 카드(`card=1`) — 사람이 훑기 좋게 태그 · 첫 사진 · 깔끔한 미리보기 · 고친 날.
                #   AI 가 부르는 기본 길에는 안 싣는다(크레딧).
                if 카드:
                    if 태그들 := notes.parse_tags(몸)[:6]:
                        한장["tags"] = 태그들
                    if 사진 := next((a for a in notes.parse_attachments(몸)
                                   if Path(a).suffix.lower() in notes.IMAGE_EXT | {".heic", ".heif"}), None):
                        한장["image"] = 사진
                    if 첨부수 := len(notes.parse_attachments(몸)):
                        한장["files"] = 첨부수
                    한장["preview"] = 카드미리보기(몸)
                    머리 = 앞머리(r["path"])
                    if m := re.search(r"(?m)^색:\s*\"?([^\"\s]+)\"?\s*$", 머리):   # 앞머리는 따옴표로 적힌다
                        한장["color"] = m.group(1)
                    try:
                        한장["updated"] = time.strftime("%Y-%m-%d", time.localtime(Path(r["path"]).stat().st_mtime))
                    except OSError:
                        pass
                out.append(한장)
            답 = {"results": out}
            # 뜻 검색이 아직 못 도는 때만 말한다(다 올랐으면 한 글자도 안 싣는다).
            상태 = getattr(self.server, "뜻상태", "")
            if 상태 == "올리는 중":
                답["meaning"] = "loading"
                답["hint"] = "뜻 모델을 올리는 중이라 낱말로만 찾았다. 몇 초 뒤 다시 물어라"
            elif 상태 == "없음":
                답["meaning"] = "none"
                답["hint"] = "뜻 모델이 없어 낱말로만 찾는다 — 말을 바꿔 물으면 안 걸릴 수 있다"
            elif 상태 == "됨" and getattr(self.server.notes, "_embed", None) is not None:
                # ★ **모델은 올랐는데 벡터가 많이 비어 있으면**(색인을 새로 만든 뒤·처음 부은 뒤 몇 분)
                #   뜻으로는 덜 찾힌다 — 그것도 말한다. 재 봤다: 깨진 색인을 다시 만든 뒤 25초에
                #   2794장 중 240장만 벡터가 있었다. 1할 넘게 비었을 때만 싣는다.
                try:
                    남음 = self.server.notes.vec_left()
                    전체 = self.server.notes.conn.execute("SELECT count(*) FROM notes").fetchone()[0]
                    if 전체 and 남음 > max(50, 전체 // 10):
                        답["meaning"] = "partial"
                        답["hint"] = f"뜻 벡터를 채우는 중이다({남음}/{전체}장 남음) — 뜻으로는 덜 찾힌다. 조금 뒤 다시"
                except Exception:
                    pass
            return self._send(200, 답)

        if url.path == "/eb/v1/memory/note":
            # 꺼내기 2단. 소제목을 주면 **그 토막만**, 안 주면 글 한 편을 그대로 준다.
            # 한 편을 달라는 것은 **고른 것**이라 막지 않는다 — 1단이 글자 수를 이미 보였다.
            args = parse_qs(url.query)
            title = (args.get("title") or [""])[0].strip()
            heading = (args.get("heading") or [""])[0].strip()
            if not title:
                return self._send(400, {"error": "title required"})
            note = self.server.notes.read(title)
            # 같은 제목이 여럿이면 `folder=` 로 고른다(1단 카드의 `folder` 를 그대로 넘기면 된다).
            if 폴더 := (args.get("folder") or [""])[0].strip().strip("/"):
                note = None
                for 자리 in self.server.notes.twins(title) or []:
                    try:
                        if str(자리.parent.relative_to(self.server.notes.root)).replace(chr(92), "/") == 폴더:
                            note = self.server.notes.read_at(자리)
                    except ValueError:
                        continue
            if note is None:
                # ★★ **없다고만 하면 AI 는 처음부터 다시 찾는다 — 그게 800자다.**
                #   제목을 조금 틀리게 적는 것은 AI 가 흔히 하는 실수인데(앞을 잘라 보내거나
                #   괄호를 빼먹는다), 지금까지는 아무 실마리 없이 404 만 돌려줬다.
                #   **없는 소제목에는 이미 있는 소제목 목록을 주고 있었다** — 제목도 같아야 한다.
                #   `titles_like` 는 `[[` 를 칠 때 쓰던 것이라 값이 더 안 든다.
                가까운 = self.server.notes.titles_like(title, k=5)
                답 = {"error": "no such note", "title": title}
                if 가까운:
                    답["did_you_mean"] = 가까운
                return self._send(404, 답)
            if heading:
                토막 = notes.section(note.body, heading)
                if not 토막:
                    # 없는 소제목에 **글 통째**를 돌려주면 아끼려던 것이 그대로 나간다.
                    # 없다고 말하고 **있는 소제목을 보여 준다.**
                    # ★ `#^이름` 은 블록이다 — 그때는 **있는 블록 이름**을 보여 줘야 쓸모가 있다.
                    #   소제목 목록을 주면 AI 가 없는 길을 또 두드린다.
                    블록이냐 = heading.strip().startswith("^")
                    없다 = {"error": "no such block" if 블록이냐 else "no such heading",
                           "title": title, "heading": heading}
                    있는것 = (notes.blocks(note.body) if 블록이냐
                            else [h for _, h in notes.headings(note.body)])[:20]
                    if 있는것:
                        없다["blocks" if 블록이냐 else "headings"] = 있는것
                    return self._send(404, 없다)
                return self._send(200, {"title": title, "heading": heading, "text": 토막,
                                        "chars": len(토막)})
            # ★★ **`q=` 를 주면 그 둘레만 준다.** 긴 글은 소제목이 없으면 통째로 나가는데,
            #   오너 창고에서 1000자 넘는 글 199장 중 소제목이 있는 것은 7장뿐이다 —
            #   `heading=` 으로 고르는 길이 사실상 없다. AI 가 필요한 건 몇 줄인데 1301자를 태운다.
            #   ※ 넉넉히 준다. 아껴서 답을 자르면 통째로 다시 부르므로 되레 손해다.
            물음 = (args.get("q") or [""])[0]
            글, 잘랐나 = notes.둘레(note.body, 물음)
            # ★★ **`q=` 없이 부르면 통째로 나간다 — 아주 긴 글이면 그것만으로 값이 날아간다.**
            #   흡수를 두드려 보니 **5만 자짜리 한 줄**도 그대로 들어온다(자르지 않는다 —
            #   원본이 원본이라 그게 맞다). 그 글을 AI 가 통째로 부르면 2만 토큰이다.
            #   넉넉한 상한을 두고 **잘랐다고 말한다** — AI 는 `q=` 로 좁혀 다시 부르면 된다.
            #   통째가 꼭 필요하면 `full=1` 로 뚫는다.
            통째로달라 = (args.get("full") or ["0"])[0] not in ("0", "", "false")
            if not 통째로달라 and len(글) > MAX_NOTE_CHARS:
                글, 잘랐나 = 글[:MAX_NOTE_CHARS], True
            답 = {"title": title, "text": 글, "chars": len(글),
                  "headings": [h for _, h in notes.headings(note.body)][:20]}
            if 잘랐나:
                # **자른 것을 말한다.** 안 말하면 AI 가 글 전체를 본 줄 안다.
                답["cut"] = True
                답["full_chars"] = len(note.body)
            if not 답["headings"]:
                del 답["headings"]
            # ★ **이름만 적고 안 이은 글**(연결 안 된 언급). 창고의 95%가 외딴이라 AI 가 이 목록을 보고
            #   `[[제목]]` 을 넣으면 그물이 자란다. 있을 때만 싣는다(제목 다섯 개).
            if 언급 := [t for t, _ in self.server.notes.언급(note.title, k=5)]:
                답["unlinked"] = 언급
            # 이 글을 가리키는 글(편의 기능 19번 · 옵시디언 백링크) — 사람이 보는 폰 글 보기용. 열두 장까지.
            if (args.get("back") or ["0"])[0] not in ("0", "", "false"):
                if 뒤 := list(dict.fromkeys(t for t, _ in self.server.notes.backlinks(note.title)))[:12]:
                    답["backlinks"] = 뒤
            return self._send(200, 답)

        if url.path == "/eb/v1/graph":
            return self._send(200, {"nodes": self.server.notes.graph()})

        if url.path.startswith("/eb/v1/connect/"):
            # ★ 오너가 연결한 바깥 계정에서 **읽기만**(connectors.py 의 허용 길만). 토큰은 보관소에서 꺼내 머리에만 쓴다.
            #   원격 PC 는 못 부른다 — 오너 계정 자료다.
            if self.session is not None:
                return self._send(403, {"error": "원격에서는 연결한 계정을 못 읽는다"})
            import connectors

            이름 = url.path[len("/eb/v1/connect/"):]
            인자 = {k: v[0] for k, v in parse_qs(url.query).items()}
            길 = 인자.pop("path", "")
            try:
                return self._send(200, connectors.fetch(이름, 길, 인자 or None))
            except connectors.ConnectError as e:
                return self._send(e.code if 400 <= e.code < 600 else 502, {"error": str(e)})

        if url.path == "/eb/v1/proposals":
            return self._send(
                200, {"proposals": [dict(r) for r in self.server.store.pending_proposals()]}
            )

        if url.path == "/eb/v1/skills":
            # 폰이 받아 오케스트레이터에 반영한다. 승인된 것만 여기 있다.
            return self._send(200, {"skills": [asdict(s) for s in self.server.skills.all()]})

        if url.path == "/eb/v1/events":
            return self._stream_events()

        if url.path.startswith("/eb/v1/artifacts/"):
            return self._artifact(url.path[len("/eb/v1/artifacts/"):])

        if url.path == "/eb/v1/artifacts":
            return self._send(200, {"files": sorted(
                p.name for p in self.server.artifacts.glob("*") if p.is_file())})

        if url.path == "/eb/v1/triggers":
            # 받아쓰기에 일러줄 낱말. 아는 말을 미리 알면 오인식이 크게 준다.
            # 모듈마다 대표 낱말 하나씩만. 많이 주면 조용할 때 지어낸 말까지 확신한다.
            words = [m.triggers[0] for m in self.server.eb.modules.values() if m.triggers]
            return self._send(200, {"triggers": words})

        if url.path == "/eb/v1/models/download":
            pr = self.server.downloader.progress
            return self._send(200, {
                "catalog": model_store.listing(self.server.downloader.model_dir,
                                               self.server.picked["hardware"]["vram_mb"], also=paths.models_dir()),
                "state": pr.state, "key": pr.key, "label": pr.label,
                "percent": pr.percent, "done_mb": round(pr.done_mb),
                "total_mb": round(pr.total_mb), "error": pr.error,
                "busy": self.server.downloader.busy,
            })

        if url.path == "/eb/v1/models":
            # 화면이 목록을 보여주고 사용자가 고른다. 사양과 자동 추천도 같이 준다.
            p = self.server.picked
            return self._send(200, {"installed": p["installed"], "using": p["using"],
                                    "auto": p["auto"], "hardware": p["hardware"]})

        if url.path == "/eb/v1/engine":
            # 화면이 "지금 뭐가 올라와 있나"를 본다. 자체 엔진일 때만 값이 찬다.
            eng = self.server.backend
            return self._send(200, {
                "kind": eng.name,
                "models": getattr(eng, "available", lambda: [])(),
                "loaded": getattr(eng, "loaded", ""),
                "sees_images": getattr(eng, "sees_images", True),
            })

        if url.path == "/eb/v1/remote/pending":
            # 폰이 "누가 붙으려 하나"를 본다. **코드는 안 준다** — 폰은 외부 PC 화면을
            # 눈으로 보고 대조해야 한다. 코드를 내려주면 그 자리에 없어도 승인된다.
            if self.session is not None:
                return self._send(403, {"error": "폰에서만 볼 수 있다"})
            return self._send(200, {"sessions": [
                {"id": s.id, "from": s.from_ip, "waiting": round(time.time() - s.created)}
                for s in self.server.gate.pending()]})

        if url.path == "/eb/v1/remote/sessions":
            # 폰이 "지금 누가 붙어 있나"를 본다. 원격에서는 못 본다.
            if self.session is not None:
                return self._send(403, {"error": "폰에서만 볼 수 있다"})
            return self._send(200, {"sessions": [
                {"id": s.id, "from": s.from_ip, "bound": s.bound_ip, "log": s.log}
                for s in self.server.gate.active()]})

        return self._send(404, self._길없다(url.path))

    def do_POST(self) -> None:
        # ★★ **쓰기가 막히면 서버가 답도 없이 끊겼다.** 읽기 전용 파일·잠긴 파일·꽉 찬
        #   디스크에서 `WriteBlocked` 가 그대로 새 나간다 — 창은 잡는데(ui.py) 문은 안 잡았다.
        #   AI 는 성공인지 실패인지도 모른 채 다음 일을 한다. **왜 못 썼는지 말한다.**
        try:
            return self._post()
        except notes.WriteBlocked as 막힘:
            return self._send(507, {"error": "못 썼다 — 그 자리에 쓸 수 없다",
                                    "where": str(막힘),
                                    "hint": "읽기 전용이거나 잠겼거나 자리가 없다"})
        except Exception as 뜻밖:
            _알림(f"[서버] POST {urlparse(self.path).path[:80]} 에서 뜻밖의 예외: {type(뜻밖).__name__}: {뜻밖}")
            return self._send(500, {"error": "서버 안에서 뜻밖의 일이 났다", "why": type(뜻밖).__name__})

    # 첨부 한 개의 한도(4단계). 폰 사진은 수 MB, 짧은 영상은 수십 MB 다. 글(8MB)보다 넉넉히, 그래도 끝은 있다.
    MAX_ATTACH = 200 * 1024 * 1024

    def _휴지통id(self, 판: Path) -> str:
        """휴지통 한 장의 이름표 — 경로를 밖에 안 내보낸다."""
        import hashlib

        return hashlib.sha1(str(판).encode("utf-8")).hexdigest()[:16]

    def _attach(self, url) -> None:
        """폰이 찍은 사진·영상·음성을 `_첨부/연/월/` 에 저장하고 **본문에 쓸 이름**을 준다(4단계).

        ★ 글에 붙이는 일은 안 한다 — 폰이 받은 이름으로 `![[이름]]` 을 적어 **기존 글 쓰기 길**로 보낸다.
          그래야 덧붙이기 · 같은 글 두 번 막기 · 글 잠금을 새로 만들지 않는다.
        """
        # ★ 몸이 크니 **읽기 전에** 열쇠를 본다. 틀린 열쇠로 200MB 를 받아 줄 까닭이 없다 — 끊는다.
        if not self._authorized(url.path):
            self.close_connection = True
            return self._send(401, {"error": "unauthorized"})
        q = parse_qs(url.query)
        name = (q.get("name") or [""])[0]
        stem = (q.get("title") or [""])[0].strip()
        cid = (q.get("client_id") or [""])[0]
        if not name or not notes.is_attachment(name):
            self.close_connection = True
            return self._send(400, {"error": "받는 파일 꼴이 아니다", "name": name[:80]})
        if cid and not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", cid):
            self.close_connection = True
            return self._send(400, {"error": "client_id 는 영문·숫자·-_ 8~80자다"})
        try:
            length = int(self.headers.get("Content-Length") or -1)
        except ValueError:
            length = -1
        if length <= 0:
            self.close_connection = True
            return self._send(400, {"error": "Content-Length 가 없거나 0 이다"})
        if length > self.MAX_ATTACH:
            self.close_connection = True
            self._send(413, {"error": "첨부가 너무 크다", "max_mb": self.MAX_ATTACH // (1024 * 1024)})
            return self._비우고끊기()
        # ★★ 폰 대기함은 응답이 끊기면 같은 파일을 다시 보낸다 — `client_id` 로 한 번만 받는다(글과 같은 표).
        store = self.server.store
        if cid and (전 := store.client_write(cid)) is not None and self.server.notes.attachment_path(전["title"]):
            self.close_connection = True          # 몸은 안 받는다 — 이미 있다
            return self._send(200, {"name": 전["title"], "duplicate": True})
        data = self.rfile.read(length)
        if len(data) != length:
            return self._send(400, {"error": "몸이 덜 왔다", "got": len(data), "want": length})
        try:
            saved = self.server.notes.save_attachment(data, Path(name).suffix.lower(), stem=stem)
        except OSError as 못씀:
            return self._send(507, {"error": "못 썼다 — 첨부 자리에 쓸 수 없다", "why": type(못씀).__name__})
        if cid:
            store.client_write_begin(cid, saved)
            store.client_write_done(cid)
        return self._send(201, {"name": saved, "bytes": length})

    def _post(self) -> None:
        url = urlparse(self.path)

        # 첨부는 몸이 JSON 이 아니라 **파일 바이트 그대로**다 — JSON 읽기 앞에서 가른다.
        if url.path == "/eb/v1/attach":
            return self._attach(url)

        # 인증보다 먼저 본문을 읽어 비운다. 안 읽고 401을 보내면 남은 바이트가 소켓에
        # 남아 다음 요청이 그걸 요청줄로 읽고 연결이 끊긴다(keep-alive라 더 잘 터진다).
        try:
            body = self._body()
        except self.TooBig:
            # 크다고 읽어 비우지 않는다 — 그게 바로 상대가 노리는 것이다. 연결을 끊는다.
            self.close_connection = True
            self._send(413, {"error": "본문이 너무 크다"})
            return self._비우고끊기()
        except self.BadLength:
            self.close_connection = True
            self._send(400, {"error": "Content-Length 가 숫자가 아니거나 음수다"})
            return self._비우고끊기()
        except json.JSONDecodeError:
            body = None

        if not self._authorized(url.path):
            return self._send(401, {"error": "unauthorized"})
        if body is None:
            return self._send(400, {"error": "bad json"})

        # --- 원격 문지기 ---
        if url.path == "/eb/v1/remote/approve":
            # 폰만 승인할 수 있다. 원격 토큰으로 자기 자신을 승인시키면 문이 무너진다.
            if self.session is not None:
                return self._send(403, {"error": "폰에서만 승인할 수 있다"})
            # ★ 글자가 아닌 값이 오면 답 없이 500 이었다(문은 안 열렸지만 왜 안 되는지 모른다).
            if any(not isinstance(body.get(k, ""), str) for k in ("code", "session", "nonce", "by")):
                return self._send(400, {"error": "code·session·nonce·by 는 글자여야 한다"})
            by = body.get("by") or "폰"
            if body.get("code"):
                ok = self.server.gate.approve_code(body["code"], by)  # 폰 중계 경로
            else:
                ok = self.server.gate.approve(body.get("session", ""),
                                              body.get("nonce", ""), by)  # QR 경로
            return self._send(200 if ok else 400, {"ok": bool(ok)})

        if url.path == "/eb/v1/remote/deny":
            if self.session is not None:
                return self._send(403, {"error": "폰에서만 거절할 수 있다"})
            if not isinstance(body.get("session", ""), str):
                return self._send(400, {"error": "session 은 글자여야 한다"})
            return self._send(200, {"ok": self.server.gate.deny(body.get("session", ""))})

        if url.path == "/eb/v1/remote/close":
            # 외부 PC는 자기 세션만 끊을 수 있다. 폰은 어느 것이든 끊는다.
            sid = body.get("session", "")
            if not isinstance(sid, str):
                return self._send(400, {"error": "session 은 글자여야 한다"})
            if self.session is not None and self.session.id != sid:
                return self._send(403, {"error": "남의 연결이다"})
            return self._send(200, {"ok": self.server.gate.close(sid, "끊음")})

        if url.path == "/eb/v1/models/download":
            # 몇 GB를 받는 일이라 원격에서는 못 시킨다. 남의 디스크를 채우면 안 된다.
            if self.session is not None:
                return self._send(403, {"error": "여기서는 못 받는다"})
            if body.get("cancel"):
                self.server.downloader.cancel()
                return self._send(200, {"ok": True})
            if not self.server.downloader.start(body.get("key", "")):
                busy = self.server.downloader.busy
                return self._send(409 if busy else 400,
                                  {"ok": False,
                                   "error": "받는 중이다" if busy else "그런 모델이 없다"})
            return self._send(202, {"ok": True})

        if url.path == "/eb/v1/models":
            # 모델 바꾸기는 폰·내 PC에서만. 원격에서 남의 엔진을 갈아 끼우면 안 된다.
            if self.session is not None:
                return self._send(403, {"error": "여기서는 못 바꾼다"})
            if not self.server.set_model(body.get("role", ""), body.get("name", "")):
                return self._send(400, {"ok": False, "error": "그런 모델이 없다"})
            return self._send(200, {"ok": True, "using": self.server.picked["using"]})

        if url.path == "/eb/v1/ask":
            return self._ask(body)

        if url.path == "/v1/chat/completions":
            return self._chat(body)

        # 글 요약·번역(편의 기능 1·3번) — 폰 글 보기 ⋮ · PC 글 ⋯ 메뉴가 부른다. 로컬 모델이 먼저다.
        if url.path == "/eb/v1/assist":
            what = body.get("action")
            title = body.get("title")
            if what not in ("summary", "translate") or not isinstance(title, str) or not title.strip():
                return self._send(400, {"error": "action 은 summary·translate, title 은 글 제목"})
            lang = body.get("lang") if isinstance(body.get("lang"), str) and body.get("lang") else "영어"
            글 = self.server.notes.read(title.strip())
            if 글 is None:
                return self._send(404, {"error": "없는 글", "title": title[:80]})
            try:
                return self._send(200, {"text": self.server.assist(what, 글.body, lang)})
            except self.server.NoModel as 없음:
                return self._send(503, {"error": str(없음)})
            except backends.BackendError as 못함:
                # ★★ **기계 이름을 사람 화면에 내보내지 않는다.** 폰에 「AI 가 답을 못 했다 — BackendError」 가
                #   그대로 떴다(2026-09-18 시뮬레이터 실기) — 그 글자를 본 사람은 **무엇을 해야 할지 모른다.**
                #   할 일을 적어 주고, 기계 이름은 자국에만 남긴다.
                _알림(f"[AI 도움] 엔진이 답을 못 했다 — {type(못함).__name__}: {못함}")
                return self._send(502, {
                    "error": "AI 엔진이 답을 못 했다 — 자체 모델이 올라와 있는지, 바깥 AI 를 쓴다면 주소·키가 맞는지 본다",
                    "why": str(못함)[:120]})
            except Exception as e:
                _알림(f"[AI 도움] 뜻밖의 일 — {type(e).__name__}: {e}")
                return self._send(502, {"error": "AI 가 답을 못 했다 — 잠시 뒤 다시 해 본다"})

        if url.path == "/eb/v1/log":
            try:
                event = LogEvent(**body)
            except (TypeError, ValueError) as e:
                # 형식이 어긋난 로그는 받지 않는다. 조용히 삼키면 분석이 거짓말을 한다.
                return self._send(400, {"error": str(e)})
            self.server.store.add_log(event)
            return self._send(202)

        if url.path == "/eb/v1/memory":
            # ★★ **글자가 아닌 것이 오면 `.strip()` 이 터져 서버가 답도 없이 끊었다.**
            #   `{"title": 12345}` · `{"text": ["가","나"]}` 로 실제로 그랬다 — 부르는 쪽은
            #   무엇이 잘못됐는지 모른 채 끊긴 연결만 본다. **틀렸다고 말해 주는 것**이 값이다.
            title, text = body.get("title", ""), body.get("text", "")
            if not isinstance(title, str) or not isinstance(text, str):
                return self._send(400, {"error": "title and text must be text",
                                        "got": {"title": type(title).__name__,
                                                "text": type(text).__name__}})
            title, text = title.strip(), text.strip()
            if not title or not text:
                return self._send(400, {"error": "title and text required"})
            # ★ **갈래도 글자여야 한다.** 목록·null 이 오면 `"None"`·`"['가', '나']"` 같은 갈래로
            #   조용히 저장돼 `kind:` 좁히기에 영영 안 걸렸다(재 봤다).
            if "kind" in body and not isinstance(body["kind"], str):
                return self._send(400, {"error": "kind must be text",
                                        "got": type(body["kind"]).__name__})
            # 기본은 **덧붙이기**다. 덮어쓰기를 기본으로 하면 어제 적은 것이 오늘
            # 적은 것에 조용히 지워져, 기억이 아니라 최신값 저장소가 된다.
            mode = body.get("mode", "append")
            if mode not in ("append", "replace"):
                return self._send(400, {"error": "mode must be append or replace"})
            # ★★ **읽고-막고-쓰기를 한 잠금 안에서.** 밖이면 없던 글을 두 AI 가 동시에 덮거나,
            #   읽은 뒤 남이 덧붙인 줄을 `force` 없이 통째로 지웠다(막이가 본 `old` 가 낡았다).
            # ★★ **폰의 전송 대기함은 같은 글을 다시 보낸다** — 서버엔 써졌는데 응답이 끊기면 폰은 실패로 안다.
            #   덧붙이기라 그대로 받으면 같은 줄이 두 번 붙는다. `client_id`(글마다 하나)로 한 번만 받는다.
            #   받은 표시는 eb.db 에 남아 서버를 다시 켜도 산다.
            cid = body.get("client_id")
            if cid is not None and (not isinstance(cid, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", cid)):
                return self._send(400, {"error": "client_id 는 영문·숫자·-_ 8~80자다"})
            with self.server.notes._글잠금(title):
                if cid:
                    store = self.server.store
                    전 = store.client_write(cid)
                    if 전 is not None:
                        # 쓰기 시작 표시만 있고 끝 표시가 없으면, 글을 쓰는 사이 꺼졌을 수 있다 — 글에 그 몸이 있으면 받은 것이다
                        있던글 = self.server.notes.read(전["title"])
                        몸 = (lambda s: s.replace(chr(13) + chr(10), chr(10)).strip())
                        if 전["done"] or (있던글 is not None and 몸(text) in 몸(있던글.body)):
                            store.client_write_done(cid)
                            답 = {"title": 전["title"], "mode": mode, "duplicate": True}
                            if (저장제목 := notes.제목맞춤(전["title"])) != 전["title"]:
                                답["saved_as"] = 저장제목
                            return self._send(200, 답)
                    else:
                        store.client_write_begin(cid, title)
                self._memory_write(title, text, mode, body)
                if cid and getattr(self, "_보낸코드", 0) in (200, 201):
                    self.server.store.client_write_done(cid)
                return

        # ★★ **AI 가 제가 잘못 쓴 글을 못 지우고, 제목도 못 고쳤다.** 화면에서는 둘 다 되는데
        #   문이 없었다 — 옵시디언에서는 당연한 일이고, 창고가 AI 의 바깥 기억이라면
        #   **잘못 넣은 것을 치우는 길**이 없는 쪽이 이상하다.
        #   지우기는 **되돌릴 수 있다**(지우기 전에 한 판 남긴다) — 그래서 승인 없이 연다.
        #   이름 바꾸기는 **가리키던 링크까지 따라 고친다**(`rename`) — 옵시디언과 같다.
        # 고정 · 보관 · 색(편의 기능 18·27·30번) — 폰 카드 길게 누르기·밀기가 부른다
        if url.path == "/eb/v1/memory/mark":
            title = body.get("title")
            if not isinstance(title, str) or not title.strip():
                return self._send(400, {"error": "title required"})
            고름 = {}
            for k in ("pinned", "archived"):
                if k in body:
                    if not isinstance(body[k], bool):
                        return self._send(400, {"error": f"{k} 는 true·false"})
                    고름[k] = body[k]
            if "color" in body:
                if not isinstance(body["color"], str):
                    return self._send(400, {"error": "color 는 글자", "colors": list(notes.Notes.COLORS)})
                고름["color"] = body["color"]
            try:
                g = self.server.notes.mark(title.strip(), **고름)
            except ValueError as e:
                return self._send(400, {"error": str(e), "colors": list(notes.Notes.COLORS)})
            if g is None:
                return self._send(404, {"error": "no such note", "title": title[:80]})
            return self._send(200, {"title": g.title, "pinned": g.pinned,
                                    "archived": g.extra.get("보관") is True, "color": g.extra.get("색", "")})

        # 휴지통 되살리기(편의 기능 28번) — 목록의 id 로만(경로를 받지 않는다)
        if url.path == "/eb/v1/trash/restore":
            want = body.get("id")
            for i, (_, _, 판, _) in enumerate(self.server.notes.trashed()):
                if want == self._휴지통id(판):
                    제목 = self.server.notes.untrash(판)
                    if 제목:
                        return self._send(200, {"title": 제목, "restored": True})
            return self._send(404, {"error": "휴지통에 없다"})

        # 오늘 일지(편의 기능 23번 · 옵시디언 일일 노트) — 없으면 서식 `_서식/일지` 로 만든다
        if url.path == "/eb/v1/daily":
            day = body.get("day") if isinstance(body.get("day"), str) else ""
            글 = self.server.notes.daily(day.strip())
            return self._send(200, {"title": 글.title})

        # 할 일 체크(편의 기능 26번) — 보이는 줄이 아니라 **원문**을 뒤집는다
        if url.path == "/eb/v1/memory/task":
            title, nth = body.get("title"), body.get("nth")
            if not isinstance(title, str) or not title.strip() or not isinstance(nth, int) or nth < 0:
                return self._send(400, {"error": "title 과 nth(0부터)가 필요하다"})
            글 = self.server.notes.read(title.strip())
            if 글 is None:
                return self._send(404, {"error": "no such note", "title": title[:80]})
            바뀜 = notes.flip_task(글.body, nth)
            if 바뀜 is None:
                return self._send(404, {"error": "그 자리에 할 일 표가 없다", "nth": nth})
            글.body, 한일 = 바뀜
            self.server.notes.write(글)
            return self._send(200, {"title": 글.title, "nth": nth, "done": 한일})

        if url.path == "/eb/v1/memory/delete":
            title = body.get("title", "")
            if not isinstance(title, str) or not title.strip():
                return self._send(400, {"error": "title required"})
            title = title.strip()
            # ★★ **가리키던 글들이 허공을 보게 된다.** 세 글이 `[[중요글]]` 로 가리키는데
            #   말없이 지워지면 그물이 조용히 끊긴다 — 지우는 쪽은 그 사실을 모른다.
            #   막지는 않는다(지우기는 되돌릴 수 있다). **말은 해 준다.**
            가리키던 = [t for t, _ in self.server.notes.backlinks(title)][:10]
            지난판 = self.server.notes.history(title)
            if not self.server.notes.delete(title):
                가까운 = self.server.notes.titles_like(title, k=5)
                답 = {"error": "no such note", "title": title}
                if 가까운:
                    답["did_you_mean"] = 가까운
                return self._send(404, 답)
            답 = {"title": title, "deleted": True}
            if 가리키던:
                답["was_linked_from"] = 가리키던
                답["warn"] = f"{len(가리키던)}장이 이 글을 가리키고 있었다 — 이제 허공을 가리킨다"
            지난판 = self.server.notes.history(title) or 지난판
            if 지난판:
                언제, 파일 = 지난판[0]
                답["undo"] = {"when": 언제, "path": str(파일),
                              "how": "그 파일의 몸을 읽어 memory 에 다시 쓴다"}
            return self._send(200, 답)

        if url.path == "/eb/v1/memory/rename":
            old_t, new_t = body.get("title", ""), body.get("to", "")
            if not isinstance(old_t, str) or not isinstance(new_t, str)                     or not old_t.strip() or not new_t.strip():
                return self._send(400, {"error": "title and to required"})
            old_t, new_t = old_t.strip(), new_t.strip()
            if self.server.notes.read(new_t) is not None:
                return self._send(409, {"error": "그 제목은 이미 있다", "title": new_t})
            if not self.server.notes.rename(old_t, new_t):
                # ★ 이름 바꾸기는 새 이름 잠금을 기다린다 — 그 사이 새 제목이 생겨 물러났으면 404 가 아니라 409 다.
                #   「없는 글」이라 답하면 AI 는 멀쩡히 있는 옛 글을 다시 찾아 헤맨다.
                if self.server.notes.read(new_t) is not None:
                    return self._send(409, {"error": "그 제목은 이미 있다", "title": new_t})
                return self._send(404, {"error": "no such note", "title": old_t})
            return self._send(200, {"title": notes.제목맞춤(new_t), "was": old_t,
                                    "note": "가리키던 [[링크]]도 같이 고쳤다"})

        if url.path == "/eb/v1/me/learn":
            # ★★ **오너가 안 채워도 쓰다 보면 채워지게**(오너 지시). AI 가 대화에서 알게 된 오너 정보를
            #   「나에 대해」 글의 「VC가 알아낸 것」에 짐작으로 적는다. 오너가 적은 답은 절대 안 덮고(200 owner),
            #   질문 창 빈 칸에 흐리게 보여 오너가 확인한다. 원격 PC 는 못 적는다.
            if self.session is not None:
                return self._send(403, {"error": "원격에서는 오너 정보를 못 적는다"})
            import settings

            갈래, 질문, 답, 출처 = (body.get(k, "") for k in ("category", "question", "answer", "source"))
            if not all(isinstance(x, str) for x in (갈래, 질문, 답, 출처)) or not 질문.strip() or not 답.strip():
                return self._send(400, {"error": "category·question·answer(·source) 는 글자다",
                                        "categories": list(settings.QUESTIONS)})
            if len(질문) > 80 or len(답) > 300 or len(출처) > 60 or len(갈래) > 20:
                return self._send(400, {"error": "question 80 · answer 300 · source 60 자 안"})
            갈래 = 갈래.strip() if 갈래.strip() in settings.QUESTIONS else "기타"
            결과 = settings.learn(self.server.notes, 갈래, 질문.strip(), 답, 출처)
            return self._send(201 if 결과 == "saved" else 200,
                              {"result": 결과, "category": 갈래, "title": settings.PROFILE_TITLE})

        if url.path == "/eb/v1/skills/propose":
            # ★★ **바깥에서 만든 스킬을 들이는 문**(오너 결정 3 추천: 선언문만 · 승인 게이트 · 코드 실행 없음).
            #   바로 스킬로 저장하지 않는다 — 제안 줄에 넣고 사람이 승인해야 스킬이 된다(결정 18).
            #   부를 수 있는 것은 **이미 있는 모듈뿐**이다. 모르는 이름·경로 꼴은 400 에 아는 이름을 준다.
            if self.session is not None:
                return self._send(403, {"error": "원격에서는 스킬을 못 들인다"})
            if not isinstance(body, dict):
                return self._send(400, {"error": "선언문은 JSON 객체다"})

            def 글줄(값: Any, 최대: int) -> bool:
                return isinstance(값, list) and len(값) <= 최대 and all(
                    isinstance(x, str) and 0 < len(x) <= 200 for x in 값)

            아는것 = sorted(self.server.eb.base_modules)
            name, steps = body.get("name"), body.get("steps")
            triggers, examples = body.get("triggers", []), body.get("examples", [])
            if not isinstance(name, str) or not name.strip() or len(name) > 80:
                return self._send(400, {"error": "name 은 80자 안의 글자다"})
            if not 글줄(triggers, 50) or not 글줄(examples, 50):
                return self._send(400, {"error": "triggers·examples 는 200자 안 글자 목록(50개까지)이다"})
            if (not isinstance(steps, list) or not 0 < len(steps) <= 20
                    or not all(isinstance(s, dict) and s.get("module") in 아는것
                               and isinstance(s.get("params", {}), dict) for s in steps)):
                return self._send(400, {"error": "steps 는 아는 모듈만 부르는 1~20단계 목록이다",
                                        "known": 아는것})
            summary = body.get("summary") if isinstance(body.get("summary"), str) else ""
            제안 = dict(
                proposal_id="ext-" + secrets.token_hex(6), type="skill_proposal",
                title=f"바깥 스킬: {name.strip()}",
                summary=summary[:300] or f"{len(steps)}단계 · 반응 {', '.join(triggers[:3]) or '없음'}",
                based_on=["바깥"],
                declaration={"name": name.strip(), "triggers": triggers, "examples": examples,
                             "steps": [{"module": s["module"], "params": s.get("params", {})}
                                       for s in steps]})
            self.server.store.add_proposal(제안)
            self.server.hub.publish(제안)
            return self._send(202, {"proposal_id": 제안["proposal_id"], "status": "승인 기다림",
                                    "how": "사람이 proposals/{id}/decision 에 approve 해야 스킬이 된다"})

        if url.path == "/eb/v1/analyze":
            return self._analyze()

        parts = url.path.strip("/").split("/")
        if len(parts) == 5 and parts[:3] == ["eb", "v1", "proposals"] and parts[4] == "decision":
            decision = body.get("decision") or ""
            if not isinstance(decision, str):
                return self._send(400, {"error": "decision 은 글자여야 한다"})
            # "pick:번역" 은 후보 중 하나를 고른 것이다(되묻던 표현을 그 모듈에 배운다).
            if decision not in ("approve", "reject", "revert") and not decision.startswith("pick:"):
                return self._send(400, {"error": "bad decision"})
            return self._decide(parts[3], decision)

        return self._send(404, self._길없다(url.path))

    # --- 성장 루프 (결정 17·18) -----------------------------------------

    def _ask(self, body: Any) -> None:
        """지시를 받아 실제로 돌린다. 결과는 파일로도 남겨 어디서든 내려받게 한다."""
        if not isinstance(body.get("text") or "", str):
            return self._send(400, {"error": "text must be text", "got": type(body.get("text")).__name__})
        text = (body.get("text") or "").strip()
        if not text:
            return self._send(400, {"error": "text required"})

        context = {}
        if body.get("image"):
            try:
                raw = base64.b64decode(body["image"], validate=True)
            except (ValueError, TypeError):
                return self._send(400, {"error": "image must be base64"})
            if len(raw) > MAX_IMAGE_BYTES:
                # 큰 사진은 받아 봐야 모델이 거절한다. 메모리만 먹기 전에 막는다.
                return self._send(413, {"error": "사진이 너무 크다"})
            context["image"] = raw

        reply = self.server.eb.handle(text, context)
        # 어느 모듈이 처리했는지 같이 준다 — 화면이 그 항목을 비추는 데 쓴다.
        out = {"text": reply.text, "kind": reply.kind, "module": reply.module}

        if reply.kind == "result":
            name = f"{time.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(3)}.txt"
            (self.server.artifacts / name).write_text(
                f"{text}\n\n{reply.text}\n", encoding="utf-8"
            )
            out["artifact"] = name
        return self._send(200, out)

    def _artifact(self, name: str) -> None:
        """결과물 내려받기. 이름에 경로가 섞여 들어오면 디스크 전체가 열린다."""
        safe = Path(name).name  # 디렉터리 성분을 전부 버린다
        path = self.server.artifacts / safe
        if not safe or not path.is_file():
            return self._send(404, {"error": "not found"})

        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Disposition", f'attachment; filename="{safe}"')
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _analyze(self) -> None:
        """이력을 훑어 제안을 만든다. 자동 적용은 없다 — 만들어서 큐에 넣을 뿐이다."""
        found, fresh = self.server.analyze()
        return self._send(200, {"created": fresh, "found": found})

    def _decide(self, proposal_id: str, decision: str) -> None:
        row = self.server.store.proposal(proposal_id)
        if row is None:
            return self._send(404, {"ok": False})

        applied = None
        decl = json.loads(row["declaration"] or "{}")
        name = decl.get("name")

        if decision.startswith("pick:"):
            chosen = decision.split(":", 1)[1].strip()
            if chosen not in (decl.get("candidates") or []):
                return self._send(400, {"ok": False, "error": "후보에 없는 모듈이다"})
            applied = asdict(self.server.skills.save(
                skills.Skill(name=chosen, examples=decl.get("examples", []))
            ))
        elif decision == "approve" and row["type"] in ("skill_proposal", "skill_update") and name:
            # 선언문에 모르는 칸이 섞여도(바깥 제안·손으로 고친 줄) 승인에서 500 이 나지 않게 아는 칸만 받는다.
            applied = asdict(self.server.skills.save(skills.Skill(
                **{k: v for k, v in decl.items() if k in skills.Skill.__dataclass_fields__})))
        elif decision == "revert" and name:
            reverted = self.server.skills.revert(name)
            if reverted is None:
                return self._send(409, {"ok": False, "error": "되돌릴 이전 버전이 없다"})
            applied = asdict(reverted)

        self.server.store.decide(proposal_id, decision)
        return self._send(200, {"ok": True, "applied": applied})

    # --- 처리 -----------------------------------------------------------

    def _chat(self, body: dict[str, Any]) -> None:
        """OpenAI 호환 창구. 폰에게 PC는 백엔드 하나로 보인다(결정 25)."""
        messages = body.get("messages")
        if not messages:
            return self._send(400, {"error": "messages required"})
        if not isinstance(messages, list) or not all(isinstance(m, dict) for m in messages):
            return self._send(400, {"error": "messages must be a list of objects"})
        # 요청이 모델을 지정하지 않으면 지금 쓰기로 정해진 글자 모델을 쓴다(결정 42).
        if not isinstance(body.get("model") or "", str):
            return self._send(400, {"error": "model 은 글자여야 한다"})
        model = body.get("model") or self.server.picked["using"]["chat"]
        try:
            text = self.server.backend.chat(messages, model)
        except backends.BackendError as e:
            # 폰이 이걸 보고 3단(API)으로 승격할지 정한다(결정 24).
            return self._send(502, {"error": str(e)})
        return self._send(
            200,
            {
                "model": model,
                "choices": [{"index": 0, "message": {"role": "assistant", "content": text}}],
            },
        )

    def _stream_events(self) -> None:
        """SSE. 밀린 제안을 먼저 보내고 그다음부터 실시간으로 흘린다."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

        q = self.server.hub.subscribe()
        try:
            for row in self.server.store.pending_proposals():
                self._sse(dict(row))
            while True:
                try:
                    self._sse(q.get(timeout=15))
                except queue.Empty:
                    self.wfile.write(b": keepalive\n\n")  # 유휴 연결이 끊기지 않게
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass  # 폰이 끊었다. 정상이다.
        finally:
            self.server.hub.unsubscribe(q)

    def _sse(self, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, ensure_ascii=False)
        self.wfile.write(f"data: {data}\n\n".encode("utf-8"))
        self.wfile.flush()


def _모델자리(설정된: str) -> str:
    """설정에 적힌 자리에 `.gguf` 가 있으면 거기, 없으면 **사람이 넣는 자리(exe 옆)**.

    ★ 설정 파일은 처음 켤 때 `models_dir()` 을 박아 두는데, 구운 판에서 그건
      `_internal\\models`(프로그램 속)다. 사람은 exe 옆 `models` 에 넣는다 —
      그래서 명령줄 흡수는 모델을 찾는데 **서버·창은 「모델 없음」**이었다(시험 쪽이 잡았다).
    ★ 「기본값과 같으면」으로 가르지 않는다. 판을 다른 폴더로 옮기면 설정에는
      **옛 폴더** 자리가 남는다 — 거기 gguf 가 없다는 것이 가르는 기준이다.
    """
    p = Path(설정된) if 설정된 else None
    if p is not None and p.is_dir() and any(p.glob("*.gguf")):
        return str(p)
    return str(paths.gguf_dir())


#: 지금 떠 있는 서버. **설정 창이 확장을 켜고 끈 뒤 곧바로 다시 싣기 위해서만** 쓴다
#: (창 쪽은 서버 객체를 안 들고 있었다 — 없으면 「다시 켜야 적용된다」밖에 할 말이 없다).
RUNNING: "EBServer | None" = None


class EBServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, addr, cfg: dict[str, Any], store: Store, note_store: Notes) -> None:
        super().__init__(addr, Handler)
        뒤 = cfg.setdefault("backend", {"kind": "local"})
        if 뒤.get("kind") == "local":
            # 여기 한 자리에서 정한다 — 아래 모델 자리를 읽는 곳이 셋이다
            뒤["model_dir"] = _모델자리(뒤.get("model_dir", ""))
        self.cfg = cfg
        self.store = store
        self.notes = note_store
        self.skills = SkillStore(note_store)
        self.hub = Hub()
        self.backend = backends.build(cfg["backend"])
        # 자체 엔진이면 가진 모델을 설정보다 우선한다 — 모델 이름을 손으로 적게 하면
        # 파일명을 그대로 옮겨야 해서 오타 한 번에 "모델이 없다"가 뜬다.
        # 무엇을 쓸지 여기서 정한다. 사용자 선택 > 사양 자동 (결정 42)
        model_dir = (cfg.get("backend") or {}).get("model_dir", str(paths.models_dir()))
        self.picked = models_config.resolve(cfg, model_dir)
        # ★★ **바깥 AI 면 그 제공자의 모델 이름을 쓴다.** 고르는 목록은 이 PC 에 깐 gguf 뿐이라,
        #   클라우드로 바꿔도 `llama-8b` 같은 파일 이름이 Anthropic·Gemini 에 그대로 나갔다.
        if 뒤.get("kind") != "local" and isinstance(뒤.get("model"), str) and 뒤["model"].strip():
            self.picked["using"]["chat"] = self.picked["using"]["vision"] = 뒤["model"].strip()
        # ★ 받는 자리는 **판을 올려도 남는 곳**(설치본은 exe 옆 models) — 프로그램 속에 받으면 새 판을 풀 때 지워졌다
        self.downloader = model_store.Downloader(paths.fetched_dir())
        if hasattr(self.backend, "n_gpu_layers"):
            self.backend.n_gpu_layers = self.picked["gpu_layers"]
        self.gate = remote.RemoteGate()
        self._정리잠금 = threading.Lock()   # 뒤 실과 「지금 정리」가 겹치지 않게
        # ★ 작업 폴더에 기대지 않는다 — 딴 폴더에서 켜면 거기 만들다 접근 거부로 **아예 안 떴다**(시험 쪽).
        self.artifacts = Path(cfg.get("artifact_dir") or paths.기계자리("data/artifacts"))
        self.artifacts.mkdir(parents=True, exist_ok=True)

        # ★★ 확장 플러그인(결정 23 · 편의 기능 31번) — **켜 둔 것만** 싣는다.
        #   싣다가 터진 확장은 그것만 안 실리고 까닭이 자국에 남는다(VC 는 산다).
        #   ※ `plugins_dir` 은 검사용 — 평소에는 앱 자리 `plugins/` 를 본다.
        self.plugins = 확장들.load(cfg.get("plugins_dir") or None, store=note_store, cfg=cfg, log=_알림)

        # 원격에서 들어온 지시를 처리할 오케스트레이터. 폰과 같은 부품·같은 1단 모델을 쓴다.
        mods = build_modules(self.backend, self.picked["using"]["vision"]
                             or self.picked["using"]["chat"])
        mods += self._확장부품(self.plugins)
        self.eb = Orchestrator(mods, brain=brain.build(mods, self.skills.all()),
                               log=self.store.add_log)
        self.eb.load_skills(self.skills.all())

        global RUNNING
        RUNNING = self

    def reload_plugins(self) -> "확장들.Loaded":
        """설정에서 켜고 끈 뒤 다시 싣는다 — VC 를 다시 켜지 않아도 저장 알림·명령이 바로 바뀐다.

        ※ **지시에 반응하는 부품은 다시 켤 때 붙는다** — 오케스트레이터는 켤 때 한 번 짜인다.
          설정 창이 그렇게 적어 준다(할 수 없는 것을 된다고 말하지 않는다).
        """
        self.plugins = 확장들.load(self.cfg.get("plugins_dir") or None,
                                 store=self.notes, cfg=None, log=_알림)
        return self.plugins

    @staticmethod
    def _확장부품(실림: 확장들.Loaded) -> list:
        """확장이 낸 부품을 오케스트레이터의 `ModuleSpec` 으로 옮긴다.

        ★ **부품이 터져도 지시 처리는 계속된다** — 확장 함수를 감싸 까닭만 답한다.
          감싸지 않으면 확장 하나의 오타가 「지시를 못 받는 VC」가 된다.
        """
        from orchestrator import ModuleSpec

        만든것 = []
        for 확장, m in 실림.modules:
            def 감싸기(글, _m=m, _확장=확장):
                try:
                    return str(_m.run(getattr(글, "text", 글)))
                except Exception as e:
                    _알림(f"[확장 {_확장}] 부품 「{_m.name}」 이 터졌다 — {type(e).__name__}: {e}")
                    return f"확장 「{_확장}」 이 답을 못 냈다"
            만든것.append(ModuleSpec(name=f"확장:{m.name}", triggers=m.triggers,
                                    run=감싸기, tiers=["pc"]))
        return 만든것

    def set_model(self, role: str, name: str) -> bool:
        """사용자가 고른 모델을 저장하고 바로 반영한다.

        받아쓰기·목소리는 다음에 켤 때 잡히고, 글자·비전 모델은 다음 호출에 올라온다 —
        지금 올라와 있는 걸 내리기만 하면 된다(상주 제어가 알아서 다시 올린다).
        """
        model_dir = (self.cfg.get("backend") or {}).get("model_dir", str(paths.models_dir()))
        if not models_config.choose(self.cfg, role, name, model_dir):
            return False
        # ★★ **들고 있던 사본으로 파일을 통째로 덮지 않는다.** 서버는 켤 때 읽은 설정을 들고 있는데,
        #   그 사이 화면이 같은 파일에 글자 크기·화면 방식을 적는다 — 통째로 쓰면 그것들이 말없이 지워졌다.
        #   지금 파일을 다시 읽어 **고른 모델 칸만** 바꿔 쓴다.
        try:
            지금 = json.loads(paths.config_path().read_text(encoding="utf-8")) if paths.config_path().exists() else {}
            if not isinstance(지금, dict):
                지금 = {}
        except (OSError, ValueError):
            지금 = {}
        paths.config_path().write_text(json.dumps({**지금, "models": self.cfg.get("models", {})},
                                          ensure_ascii=False, indent=2), encoding="utf-8")
        self.picked = models_config.resolve(self.cfg, model_dir)
        if role in ("chat", "vision"):
            unload = getattr(self.backend, "unload", None)
            if unload:
                unload()
            self.eb = Orchestrator(
                build_modules(self.backend, self.picked["using"]["vision"]
                              or self.picked["using"]["chat"]),
                brain=self.eb.brain, log=self.store.add_log)
            self.eb.load_skills(self.skills.all())
        return True

    def analyze(self) -> tuple[int, list[str]]:
        """이력을 훑어 새 제안만 큐에 넣는다. 반환은 (찾은 수, 새로 만든 제목들)."""
        found = skills.analyze(self.store.conn)
        fresh = []
        for p in found:
            # 같은 제안을 매번 다시 띄우지 않는다. 「있나 보고 넣기」는 한 문장이라 화면 「점검」과 겹쳐도 하나다.
            if not self.store.add_proposal_if_new(p):
                continue
            self.hub.publish(p)
            fresh.append(p["title"])
        return len(found), fresh

    def start_housekeeping(self, every_sec: int = 60) -> None:
        """놀고 있는 모델을 내리고 죽은 원격 세션을 치운다.

        `sweep()`을 아무도 안 부르면 VRAM을 영영 붙들고 있어서 다른 모델이 못 올라온다.
        """
        sweep = getattr(self.backend, "sweep", None)

        def loop() -> None:
            while True:
                time.sleep(every_sec)
                try:
                    self.gate.sweep()
                    # 다 받은 모델이 목록에 바로 뜨게 한다.
                    if self.downloader.progress.state == "done" and not self.downloader.busy:
                        self.downloader.progress.state = "idle"
                        model_dir = (self.cfg.get("backend") or {}).get("model_dir", str(paths.models_dir()))
                        self.picked = models_config.resolve(self.cfg, model_dir)
                        _알림("[모델] 새로 받은 것을 목록에 넣었다")
                    if sweep is not None and sweep():
                        _알림("[엔진] 놀아서 모델을 내렸다")
                except Exception as e:  # 청소가 실패해도 서버는 계속 떠 있어야 한다
                    _알림(f"[청소 실패] {e}")

        threading.Thread(target=loop, daemon=True).start()

    def start_embedding(self, every_sec: int = 30) -> None:
        """뜻 벡터를 뒤에서 채운다. **창이 없어도 자라야 한다.**

        ★★ 채우는 길이 화면(`panels.Indexer`)에만 있었다. 그래서 `--no-ui` 로 서버만
        띄우면 — 도움말이 「폰만 쓰거나 원격만 쓸 때」라고 적어 둔 정식 쓰임이다 —
        새 글의 뜻 벡터가 **영영 안 만들어진다.** AI 가 `/eb/v1/memory/search` 로만
        꺼내 쓰면 낱말로 걸리는 것만 보이고, 그것을 알 길이 없다.

        같은 사고를 잣대에서 겪었다: 글을 고쳐 놓고 벡터를 안 만든 채 재고서
        「글을 고쳐도 안 찾는다」고 적었다. **안 채우는 것은 조용히 틀린다.**

        `Indexer` 와 **같은 차례**를 밟는다 — 안 그러면 화면이 만든 벡터와 여기서
        만든 벡터가 갈린다. `use_embedder` 가 폭을 재서 크기가 달라졌으면 옛것을 버린다.
        """
        # ★★ **뜻 모델이 오르는 동안(켠 뒤 3~5초) 찾으면 조용히 0장이었다.** AI 는 그것을
        #   「없다」로 읽는다 — 재 보니 2.1초에 0장, 5.2초에 5장. 상태를 들고 있다가 1단이 말한다.
        self.뜻상태 = "올리는 중"

        def loop() -> None:
            from brain import onnx_embedder, pin_runtime

            from notes import EMBED_TOKENS

            # Qt 가 딸고 온 2019년 런타임 위에서 onnxruntime 을 올리면 통째로 죽는다.
            # 뜻 검색이 꺼지는 것이 서버가 죽는 것보다 낫다.
            if not pin_runtime():
                self.뜻상태 = "없음"
                return
            # ★★ **구운 판에는 콘솔이 없다.** `--noconsole` 로 구우면 `print` 가 조용히
            #   사라져, 넣어 둔 알림을 **아무도 못 본다** — 시험 쪽이 v0.1.94 에서
            #   `--no-ui` stdout 을 파일로 받았는데 `[뜻 벡터]` 줄이 하나도 안 남았다.
            #   그러니 **기록 파일에도 같이 남긴다.** 거기는 창이 없어도 읽을 수 있다.
            def 알린다(말: str) -> None:
                print(말)
                try:
                    import report

                    report.trail(말)
                except Exception:
                    pass        # 알리다 죽으면 안 된다

            # 사람이 화면 「뜻 검색」 칸에서 고른 것이 있으면 그것을 쓴다.
            고른것 = (self.cfg.get("models") or {}).get("meaning", "")
            embed = onnx_embedder(paths.meaning_dir(고른것), max_tokens=EMBED_TOKENS)
            if embed is None:
                알린다("[뜻 벡터] 안 돈다 — 모델이 없다: " + str(paths.meaning_dir()))
                self.뜻상태 = "없음"
                return          # 낱말 검색은 그대로 돈다
            # ★★ **찾는 쪽에도 임베더를 붙인다.** 처음엔 이 실의 제 연결에만 붙였는데,
            #   그러면 **벡터는 자라는데 뜻 검색은 영영 0건**이다 — `search` 가 쓰는
            #   `self.notes` 는 `_embed` 가 None 이라 `semantic()` 이 늘 빈 목록을 준다.
            #   시험 쪽이 `--no-ui` 에서 그걸 잡았다: 본문에 있는 낱말은 나오는데
            #   뜻으로 물으면 네 가지가 다 0건이었다. **자란 것과 쓰이는 것은 다른 말이다.**
            self.notes.use_embedder(embed)
            self.뜻상태 = "됨"
            # sqlite 연결은 실마다 하나가 원칙이다 — 쓰는 것은 제 연결로 한다.
            내것 = self.notes.__class__(self.notes.root, self.notes.index_path,
                                        index_now=False)
            내것.use_embedder(embed)
            처음 = True
            while True:
                try:
                    내것.reindex()
                    남음 = 내것.vec_left()
                    if 처음:
                        알린다(f"[뜻 벡터] 항목 {내것.conn.execute('SELECT count(*) FROM notes').fetchone()[0]}"
                               f" · 새로 만들 {남음}")
                        처음 = False
                    if 남음:
                        while 내것.embed_some(16):
                            pass
                        알린다(f"[뜻 벡터] 다 찼다 — 못 만든 것 {내것.vec_left()}개")
                        # ★ **찾는 쪽 캐시를 비운다.** 안 비우면 새로 만든 벡터를
                        #   `semantic()` 이 못 본다 — 캐시는 한 번 읽고 들고 있다.
                        self.notes._vec_cache = None
                except Exception as e:  # 못 채워도 서버는 계속 떠 있어야 한다
                    알린다(f"[뜻 벡터 실패] {e}")
                time.sleep(every_sec)

        threading.Thread(target=loop, daemon=True).start()

    class NoModel(RuntimeError):
        """쓸 대화 모델이 없다."""

    _도움말 = {
        "summary": ("아래 메모를 읽고 무슨 일이 있었는지 한국어로 **새로 써서** 요약한다. 원문 줄을 그대로 옮기지 않는다. "
                    "2~4줄 목록(- )으로 쓰고, 마지막 줄은 「- 지금: …」 으로 지금 상태를 쓴다. "
                    "메모에 없는 것은 쓰지 않는다. 앞말 없이 목록만. /no_think"),
        "translate": "아래 메모를 {lang}(으)로 옮긴다. 목록·표·줄바꿈 꼴은 그대로 둔다. `[[…]]` · `![[…]]` · `#태그` 는 그대로 둔다. 옮긴 글만 답한다. /no_think",
    }

    def assist(self, what: str, body: str, lang: str = "영어") -> str:
        """글 한 장을 요약하거나 옮긴다. 모델이 없으면 NoModel."""
        모델 = (self.picked.get("using") or {}).get("chat") or ""
        if not 모델:
            raise self.NoModel("대화 모델이 없다 — 설정 › 모델에서 받거나 바깥 AI 키를 넣는다")
        말 = [{"role": "system", "content": self._도움말[what].format(lang=lang)},
              {"role": "user", "content": body[:6000]}]
        곁 = {"temperature": 0.2, "max_tokens": 900} if (self.cfg.get("backend") or {}).get("kind") == "local" else {}
        답 = self.backend.chat(말, 모델, **곁)
        return re.sub(r"(?s)<think>.*?</think>", "", 답 or "").strip()

    def consolidate_now(self) -> dict:
        """흩어진 메모를 정리 글로 모은다(편의 기능 1·5번 · 1겹 — AI 없이 서식 칸으로)."""
        import consolidate

        import ai_fill

        with self._정리잠금:
            # 2겹 — 로컬 대화 모델이 있으면 칸 없는 메모를 몇 장 짐작한다(없으면 쌓인 짐작만 쓴다)
            모델 = (self.picked.get("using") or {}).get("chat") or ""
            chat = None
            if 모델 and (self.cfg.get("backend") or {}).get("kind") == "local":
                chat = lambda 말: self.backend.chat(말, 모델, temperature=0, max_tokens=300)
            try:
                짐작 = ai_fill.run(self.notes, chat)
            except Exception as e:
                _알림(f"[정리 짐작 실패] {type(e).__name__}")
                짐작 = {}
            got = consolidate.run(self.notes, 짐작)
            # 녹음 받아쓰기(편의 기능 14번) — 붙은 녹음을 몇 개씩. 요약은 대화 모델이 있을 때만
            try:
                import transcribe

                요약 = None
                if chat is not None:
                    요약 = lambda 글: self.assist("summary", 글)
                if 들음 := transcribe.run(self.notes, transcribe.whisper, 요약):
                    _알림(f"[받아쓰기] 녹음 {len(들음)}개를 글 끝에 붙였다")
            except Exception as e:
                _알림(f"[받아쓰기 실패] {type(e).__name__}")
        if got.get("written"):
            _알림(f"[정리] 제품 {got['products']}개 · 새로 쓴 정리 글 {len(got['written'])}장")
        return got

    # --- 딴 PC 사본(결정 30) -------------------------------------------------
    def 손님설정(self) -> dict:
        """이 VC 가 손님이면 {`main_url`, `main_token`}, 메인이면 빈 표."""
        got = self.cfg.get("사본") or {}
        if not isinstance(got, dict) or got.get("역할") != "손님":
            return {}
        주소, 열쇠 = str(got.get("main_url") or "").strip(), str(got.get("main_token") or "").strip()
        return {"main_url": 주소, "main_token": 열쇠} if 주소 and 열쇠 else {}

    def _메인부르기(self, 설정: dict):
        """메인에 묻는 함수를 만든다. `(method, path, 바이트=False, 몸=None)` → dict·bytes·None."""
        import urllib.error
        import urllib.parse
        import urllib.request

        뿌리 = 설정["main_url"].rstrip("/")

        def 부르기(method: str, path: str, 바이트: bool = False, 몸: Any = None):
            앞, _, 뒤 = path.partition("?")
            주소 = 뿌리 + 앞 + (("?" + urllib.parse.urlencode(
                {k: v[0] for k, v in parse_qs(뒤, keep_blank_values=True).items()})) if 뒤 else "")
            req = urllib.request.Request(
                주소, method=method,
                data=None if 몸 is None else json.dumps(몸).encode(),
                headers={"Authorization": f"Bearer {설정['main_token']}",
                         "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    raw = r.read()
                    if 바이트:
                        return raw
                    return json.loads(raw.decode()) if raw else {}
            except (urllib.error.URLError, OSError, ValueError):
                # 못 닿아도 **사본은 그대로 둔다** — 부르는 쪽이 까닭을 말한다.
                return None

        return 부르기

    def 사본한판(self) -> str:
        """메인에서 받고, 이 PC 에서 쓴 것을 보낸다. 사람에게 보일 한 줄."""
        import mirror

        설정 = self.손님설정()
        if not 설정:
            return "이 VC 는 메인이야 — 받을 곳이 없다."
        자국 = paths.기계자리(mirror.MEMO)
        부르기 = self._메인부르기(설정)
        받 = mirror.한판(self.notes, 부르기, 자국)
        보 = mirror.보내기(self.notes, 부르기, 자국)
        if 받.까닭 or 보.까닭:
            return f"메인({설정['main_url']})에 못 닿았어."
        말 = []
        if 받.몇개:
            말.append(f"받음 새로 {받.새로} · 고침 {받.고침} · 지움 {받.지움}"
                     + (f" · 사진 {받.첨부}" if 받.첨부 else ""))
        if 보.보냄:
            말.append(f"보냄 {보.보냄}" + (f"(둘 다 남김 {보.붙임})" if 보.붙임 else ""))
        return " · ".join(말) if 말 else "메인과 같아 — 주고받을 게 없다."

    def start_mirror(self, every_sec: int = 60) -> None:
        """손님이면 주기적으로 메인과 주고받는다. 메인이면 아무 일도 안 한다."""
        def loop() -> None:
            while True:
                try:
                    if self.손님설정():
                        말 = self.사본한판()
                        if 말 and "주고받을 게 없다" not in 말 and "메인이야" not in 말:
                            _알림(f"[사본] {말}")
                except Exception as e:      # 사본이 실패해도 VC 는 계속 떠 있어야 한다
                    _알림(f"[사본 실패] {type(e).__name__}: {e}")
                time.sleep(every_sec)

        threading.Thread(target=loop, daemon=True).start()

    def start_consolidate(self, every_sec: int = 120) -> None:
        """메모가 바뀌면 **2분쯤 모았다가** 정리 글을 새로 쓴다(결정 19). 하루 한 번은 바뀐 게 없어도 돈다.

        단추는 없다(결정 26) — 뒤에서 돌고, 확인할 것은 「제품 보유 목록」의 「확인 필요」에 올린다.
        """
        def 지문() -> tuple:
            return tuple(self.notes.conn.execute(
                "SELECT count(*), max(mtime) FROM notes WHERE path NOT LIKE ?", ("%_정리%",)).fetchone())

        def loop() -> None:
            본것, 마지막 = None, 0.0
            while True:
                try:
                    지금 = 지문()
                    if 지금 != 본것 or time.time() - 마지막 > 86400:
                        self.consolidate_now()
                        본것, 마지막 = 지문(), time.time()
                except Exception as e:  # 정리가 실패해도 서버는 계속 떠 있어야 한다
                    _알림(f"[정리 실패] {type(e).__name__}: {e}")
                time.sleep(every_sec)

        threading.Thread(target=loop, daemon=True).start()

    def start_analyzer(self, every_sec: int = 900) -> None:
        """주기적으로 스스로 돌아본다. 사용자가 시키지 않아도 성장은 계속된다.

        ponytail: 고정 주기 스레드. 지시가 뜸한 시간대를 학습해 그때 돌리는 것은
        개입 등급(결정 23)이 자리 잡은 뒤에 붙인다.
        """

        def loop() -> None:
            while True:
                time.sleep(every_sec)
                try:
                    self.analyze()
                except Exception as e:  # 분석이 실패해도 서버는 계속 떠 있어야 한다
                    _알림(f"[분석 실패] {e}")
                # ★ 오너 결정 9: 로컬 대화 모델이 있으면 새 대화에서 오너 정보를 **짐작으로만** 뽑는다(오너 답 안 덮음)
                try:
                    모델 = self.picked["using"].get("chat") or ""
                    if (self.cfg.get("backend") or {}).get("kind") == "local" and 모델:
                        import selflearn
                        import talklog

                        적음 = selflearn.run(self.notes, lambda 말: self.backend.chat(말, 모델),
                                            talklog.read(60), paths.기계자리("vc-스스로짐작.txt"))
                        if 적음:
                            _알림(f"[스스로 짐작] 대화에서 오너 정보 {적음}개를 짐작으로 적었다(질문 창에서 확인)")
                except Exception as e:
                    _알림(f"[스스로 짐작 실패] {type(e).__name__}")

        threading.Thread(target=loop, daemon=True).start()


def serve(host: str = "0.0.0.0", port: int = 8765) -> None:
    cfg = load_config()
    store = Store()
    note_store = Notes(cfg.get("notes_dir", "data/notes"), "notes_index.db")
    server = EBServer((host, port), cfg, store, note_store)
    server.start_analyzer(cfg.get("analyze_every_sec", 900))
    server.start_housekeeping()
    server.start_embedding()   # 창이 없어도 뜻 벡터가 자라야 한다
    server.start_consolidate()  # 흩어진 메모 → 제품 정리 글
    server.start_mirror()       # 손님이면 메인과 주고받는다(결정 30)
    print(f"EB 서버 시작 {host}:{port} (프로토콜 {PROTOCOL_VERSION})")
    print(f"페어링 열쇠: {paths.config_path()} 의 pair_token")   # 값은 안 찍는다(파일로 받으면 샌다)
    server.serve_forever()


def _self_check() -> None:
    """서버를 실제로 띄우고 폰이 하는 호출을 그대로 해본다."""
    import urllib.error
    import urllib.parse
    import urllib.request

    cfg = {
        "pair_token": "test-token",
        "backend": {"kind": "openai_compatible", "base_url": "http://unused/v1"},
        "models": {"chat": "", "vision": "", "stt": "", "voice": ""},
    }
    import tempfile

    tmp = tempfile.TemporaryDirectory()
    store = Store(":memory:")
    note_store = Notes(Path(tmp.name) / "notes")
    # ★ 결과물 자리를 준다 — 안 주면 진짜 기록 자리에 `data/artifacts/*.txt` 가 검사마다 쌓였다(2026-09-15, 33개).
    cfg["artifact_dir"] = str(Path(tmp.name) / "artifacts")
    # 확장도 검사 자리에서만 본다 — 진짜 앱 자리의 확장이 검사에 끼면 안 된다
    cfg["plugins_dir"] = str(Path(tmp.name) / "plugins")
    server = EBServer(("127.0.0.1", 0), cfg, store, note_store)
    assert paths.data_dir() not in server.artifacts.parents, "자체점검이 진짜 기록 자리에 결과물을 남긴다"

    class FakeBackend(backends.Backend):
        fail = False

        def chat(self, messages, model):
            if self.fail:
                raise backends.BackendError("engine down")
            return f"echo:{messages[-1]['content']}"

    fake = FakeBackend()
    server.backend = fake
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"

    def call(method, path, payload=None, token="test-token"):
        req = urllib.request.Request(
            base + path,
            data=None if payload is None else json.dumps(payload).encode(),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                raw = r.read().decode()
                return r.status, (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as e:
            raw = e.read().decode()
            return e.code, (json.loads(raw) if raw else None)

    # 토큰은 헤더에 실리므로 ASCII다(token_urlsafe). 틀린 값도 ASCII로 시험한다.
    assert call("GET", "/eb/v1/hello", token="wrong-token")[0] == 401
    assert call("GET", "/eb/v1/hello", token="")[0] == 401

    # 큰 본문을 **적어 내기만** 해도 굳으면 안 된다. 서버가 0.0.0.0에 열려 있어서
    # 같은 공유기의 누구든 이걸 보낼 수 있다.
    import http.client

    # ★ 여러 번 던진다 — 비우지 않고 끊으면 가끔(60번 중 4번) 413 대신 「연결 끊김」이 났다.
    for _번 in range(40):
        conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
        conn.putrequest("POST", "/eb/v1/memory")
        conn.putheader("Authorization", "Bearer test-token")
        conn.putheader("Content-Length", str(4 * 1024 * 1024 * 1024))
        conn.endheaders()
        conn.send(b'{"text":"x"}')
        time.sleep(0.02)
        began = time.time()
        try:
            _받음 = conn.getresponse().status
        except OSError as e:
            _받음 = type(e).__name__
        assert _받음 == 413, f"413 대신 {_받음} ({_번 + 1}번째)"
        assert time.time() - began < 2.0, "413을 늦게 주면 막은 게 아니다"
        conn.close()
    # 막고 나서도 멀쩡해야 한다
    assert call("GET", "/eb/v1/hello")[0] == 200
    # ★ Content-Length 가 음수면 상대가 닫을 때까지 읽어 실을 붙들었고, 글자면 500 이었다 — 둘 다 바로 400.
    for _길이 in ("-5", "abc"):
        conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=3)
        conn.putrequest("POST", "/eb/v1/memory")
        conn.putheader("Authorization", "Bearer test-token")
        conn.putheader("Content-Length", _길이)
        conn.endheaders()
        conn.send(b'{"text":"x"}')
        began = time.time()
        try:
            _받음 = conn.getresponse().status
        except OSError as e:
            _받음 = type(e).__name__
        assert _받음 == 400, f"Content-Length {_길이} 에 400 대신 {_받음}"
        assert time.time() - began < 2.0, f"Content-Length {_길이} 에 늦게 답한다(실을 붙들었다)"
        conn.close()
    assert call("GET", "/eb/v1/hello")[0] == 200
    # 「상태·기록」 문: 열쇠가 있어야 열리고, 집 경로가 안 샌다.
    assert call("GET", "/eb/v1/status", token="wrong-token")[0] == 401
    _상, _몸 = call("GET", "/eb/v1/status")
    assert _상 == 200 and isinstance(_몸.get("trail"), list) and "deaths" in _몸, _몸
    assert str(Path.home()) not in json.dumps(_몸, ensure_ascii=False), "상태에 집 경로가 샌다"

    # --- 글 요약·번역(편의 기능 1·3번) ---
    call("POST", "/eb/v1/memory", {"title": "요약 시험", "text": "긴 회의 메모 [[회의]] #일"})
    _옛 = server.picked
    server.picked = {**_옛, "using": {**_옛["using"], "chat": ""}}
    assert call("POST", "/eb/v1/assist", {"action": "summary", "title": "요약 시험"})[0] == 503, "모델 없는데 조용히 빈 답"
    server.picked = {**_옛, "using": {**_옛["using"], "chat": "시험모델"}}
    fake.fail = False
    _상, _답 = call("POST", "/eb/v1/assist", {"action": "translate", "title": "요약 시험", "lang": "일본어"})
    assert _상 == 200 and "긴 회의 메모" in _답["text"], (_상, _답)
    # ★ 엔진이 거절하면 **사람 말로** 알린다 — 클래스 이름(BackendError 따위)은 화면에 안 나간다
    fake.fail = True
    _상, _못 = call("POST", "/eb/v1/assist", {"action": "summary", "title": "요약 시험"})
    assert _상 == 502, _상
    _영단어 = max((len(w) for w in "".join(c if (c.isascii() and c.isalpha()) else " "
                                      for c in _못["error"]).split()), default=0)
    assert _영단어 <= 2, f"기계 이름이 화면 문구에 샌다: {_못['error']}"   # 「AI」 까지만 봐준다
    assert "본다" in _못["error"], _못["error"]
    fake.fail = False
    assert call("POST", "/eb/v1/assist", {"action": "지우기", "title": "요약 시험"})[0] == 400
    assert call("POST", "/eb/v1/assist", {"action": "summary", "title": "없는 글"})[0] == 404
    assert call("POST", "/eb/v1/assist", {"action": "summary", "title": "요약 시험"}, token="wrong-token")[0] == 401
    server.picked = _옛

    # --- 흩어진 메모 → 제품 정리 글(편의 기능 1·5번) ---
    # 사진 속 글자(폰이 숨은 주석으로 붙임)는 찾기에 걸리고 카드 미리보기엔 안 보인다(편의 기능 13번)
    call("POST", "/eb/v1/memory", {"title": "송장 사진", "text": "택배 보냄\n\n%%\n사진 글자 (a.jpg):\n운송장 55667788\n%%"})
    _송 = call("GET", "/eb/v1/memory/search?q=55667788&card=1")[1]["results"]
    assert any(x["title"] == "송장 사진" for x in _송), "사진 글자로 못 찾는다"
    assert all("5566" not in x.get("preview", "") for x in _송), "숨은 글자가 미리보기에 보인다"
    call("POST", "/eb/v1/memory", {"title": "정리 시험 받음", "text": "- 제품명 : zz-1\n- 받은날 : 2026-10-01"})
    _정리 = server.consolidate_now()
    assert _정리["products"] >= 1 and server.notes.read("제품 · zz-1") is not None, _정리
    assert server.notes.read("제품 보유 목록").pinned, "보유 목록이 고정이 아니다"

    # --- 폴더 보기(편의 기능 29번) ---
    _폴 = call("GET", "/eb/v1/folders")[1]["folders"]
    assert _폴 and all("/" != f["path"][0] or f["path"] == "/" for f in _폴), _폴
    assert all(not any(x.startswith(("_", ".")) for x in f["path"].split("/")) for f in _폴), "기계 자리가 폴더로 나온다"
    assert sum(f["notes"] for f in _폴) >= 1
    assert call("GET", "/eb/v1/folders", token="wrong-token")[0] == 401

    # --- 손님 모드로 메인과 주고받기(결정 30) ---
    # 메인 자리에서는 아무 일도 안 한다 — 제 창고를 제가 베끼면 안 된다
    assert "메인이야" in server.사본한판(), server.사본한판()
    assert server.손님설정() == {}
    # 주소·열쇠가 반쪽이면 손님이 아니다(빈 주소로 부르다 터지는 것을 막는다)
    server.cfg["사본"] = {"역할": "손님", "main_url": "", "main_token": "k"}
    assert server.손님설정() == {}
    # 닿지 않는 메인이면 **까닭을 말하고 창고는 그대로 둔다**
    server.cfg["사본"] = {"역할": "손님", "main_url": "http://127.0.0.1:9", "main_token": "k"}
    _장수 = server.notes.conn.execute("SELECT count(*) FROM notes").fetchone()[0]
    assert "못 닿았어" in server.사본한판(), server.사본한판()
    assert server.notes.conn.execute("SELECT count(*) FROM notes").fetchone()[0] == _장수, "못 닿았다고 창고가 줄었다"
    server.cfg.pop("사본", None)

    # --- 바뀐 것만 내어 주기(결정 30) — 딴 PC 의 VC 가 사본을 쌓는 문 ---
    _처음 = call("GET", "/eb/v1/changes?since=0")[1]
    assert isinstance(_처음.get("changes"), list) and _처음["changes"], _처음
    assert "next_since" in _처음 and _처음["next_since"] > 0, _처음
    # 받은 자리 뒤로는 **아무것도 안 준다** — 매번 전부 주면 사본이 못 쓴다
    _다음 = call("GET", f"/eb/v1/changes?since={_처음['next_since']}")[1]
    assert _다음["changes"] == [], _다음["changes"][:2]
    # 새 글을 쓰면 그 자리에 걸린다
    call("POST", "/eb/v1/memory", {"title": "사본 시험 글", "text": "딴 PC 로 갈 글"})
    _새 = call("GET", f"/eb/v1/changes?since={_처음['next_since']}")[1]
    assert any(c["title"] == "사본 시험 글" for c in _새["changes"]), _새["changes"]
    # 지운 글도 알려 준다 — 사본에서도 지워야 진짜 사본이다
    call("POST", "/eb/v1/memory/delete", {"title": "사본 시험 글"})
    _지움 = call("GET", "/eb/v1/changes?since=0")[1]
    assert any(t["title"] == "사본 시험 글" for t in _지움["trashed"]), _지움["trashed"][:3]
    assert call("GET", "/eb/v1/changes?since=0", token="wrong-token")[0] == 401
    assert call("GET", "/eb/v1/changes?since=abc")[0] == 400

    # --- 확장 플러그인(결정 23 · 편의 기능 31번) ---
    _확장자리 = Path(tmp.name) / "plugins"
    확장들.write_sample(_확장자리)
    # ★ 폴더에 있는 것만으로는 **안 돈다.** 목록에는 뜨고 `on` 은 거짓이다.
    server.plugins = 확장들.load(_확장자리, store=server.notes, cfg={}, log=lambda _: None)
    _확 = call("GET", "/eb/v1/plugins")[1]["plugins"]
    assert [x["name"] for x in _확] == ["글자수"] and _확[0]["on"] is False, _확
    assert _확[0]["note"] and not _확[0]["error"], _확
    assert call("GET", "/eb/v1/plugins", token="wrong-token")[0] == 401
    # 켜면 저장 뒤 알림이 온다
    _확말 = []
    server.plugins = 확장들.load(_확장자리, store=server.notes, cfg={"확장": {"글자수": True}}, log=_확말.append)
    assert call("GET", "/eb/v1/plugins")[1]["plugins"][0]["on"] is True
    _확말.clear()
    assert call("POST", "/eb/v1/memory", {"title": "확장 알림 시험", "text": "한 줄"})[0] == 201
    assert any("저장됨 — 확장 알림 시험" in x for x in _확말), _확말
    # ★★ **확장이 터져도 저장은 된다.** 확장 하나가 글 쓰기를 막으면 안 된다.
    _터짐자리 = _확장자리 / "터지는것"
    _터짐자리.mkdir(parents=True, exist_ok=True)
    (_터짐자리 / "plugin.json").write_text('{"name": "터지는것"}', encoding="utf-8")
    (_터짐자리 / "main.py").write_text(
        "def register(vc):\n    vc.on_saved(lambda 제목: 1 / 0)\n", encoding="utf-8")
    server.plugins = 확장들.load(_확장자리, store=server.notes,
                              cfg={"확장": {"글자수": True, "터지는것": True}}, log=_확말.append)
    assert call("POST", "/eb/v1/memory", {"title": "확장 터짐 시험", "text": "두 줄"})[0] == 201, "확장이 터져 저장이 막혔다"
    assert server.notes.read("확장 터짐 시험") is not None
    # 확장이 낸 부품은 `확장:` 이름으로 오케스트레이터에 붙는다(터지면 까닭만 답한다)
    _부품자리 = _확장자리 / "부품낸것"
    _부품자리.mkdir(parents=True, exist_ok=True)
    (_부품자리 / "plugin.json").write_text('{"name": "부품낸것"}', encoding="utf-8")
    (_부품자리 / "main.py").write_text(
        "def register(vc):\n    vc.module('나쁜부품', ['부품시험'], lambda 글: 1 / 0)\n", encoding="utf-8")
    _실림 = 확장들.load(_확장자리, store=server.notes, cfg={"확장": {"부품낸것": True}}, log=_확말.append)
    _옮김 = EBServer._확장부품(_실림)
    assert [m.name for m in _옮김] == ["확장:나쁜부품"] and _옮김[0].matches("부품시험 해줘"), _옮김
    assert "답을 못 냈다" in _옮김[0].run("부품시험"), "부품이 터져 지시 처리가 멈춘다"
    server.plugins = 확장들.load(_확장자리, store=server.notes, cfg={}, log=lambda _: None)  # 뒤 검사에 끼지 않게 다 끈다

    # --- 오늘 일지 · 할 일 체크(편의 기능 23·26번) ---
    _상, _오늘 = call("POST", "/eb/v1/daily", {})
    assert _상 == 200 and len(_오늘["title"]) == 10 and _오늘["title"][4] == "-", _오늘
    assert call("POST", "/eb/v1/daily", {})[1]["title"] == _오늘["title"], "부를 때마다 새로 만든다"
    call("POST", "/eb/v1/memory", {"title": "할 일 시험", "text": "- [ ] 우유 사기\n- [ ] 필터 갈기"})
    assert call("POST", "/eb/v1/memory/task", {"title": "할 일 시험", "nth": 1})[1]["done"] is True
    assert "- [x] 필터 갈기" in server.notes.read("할 일 시험").body, server.notes.read("할 일 시험").body
    assert call("POST", "/eb/v1/memory/task", {"title": "할 일 시험", "nth": 1})[1]["done"] is False, "다시 누르면 풀려야 한다"
    assert call("POST", "/eb/v1/memory/task", {"title": "할 일 시험", "nth": 9})[0] == 404
    assert call("POST", "/eb/v1/memory/task", {"title": "할 일 시험"})[0] == 400

    # --- 백링크(편의 기능 19번) — back=1 일 때만 ---
    call("POST", "/eb/v1/memory", {"title": "가리키는 글", "text": "[[백링크 대상]] 참고"})
    call("POST", "/eb/v1/memory", {"title": "백링크 대상", "text": "몸"})
    _뒤 = call("GET", "/eb/v1/memory/note?title=" + urllib.parse.quote("백링크 대상") + "&back=1")[1]
    assert "가리키는 글" in _뒤.get("backlinks", []), _뒤
    assert "backlinks" not in call("GET", "/eb/v1/memory/note?title=" + urllib.parse.quote("백링크 대상"))[1], "AI 길에 백링크가 실린다"

    # --- 고정 · 보관 · 색 · 휴지통(편의 기능 18·27·28·30번) ---
    call("POST", "/eb/v1/memory", {"title": "표시 카드", "text": "보관할 글 표시카드낱말"})
    assert call("POST", "/eb/v1/memory/mark", {"title": "표시 카드", "color": "검정"})[0] == 400
    assert call("POST", "/eb/v1/memory/mark", {"title": "표시 카드", "pinned": "yes"})[0] == 400
    assert call("POST", "/eb/v1/memory/mark", {"title": "없는 글", "pinned": True})[0] == 404
    _상, _표 = call("POST", "/eb/v1/memory/mark", {"title": "표시 카드", "pinned": True, "color": "노랑"})
    assert _상 == 200 and _표["pinned"] and _표["color"] == "노랑", _표
    _카 = [x for x in call("GET", "/eb/v1/memory/search?q=" + urllib.parse.quote("표시카드낱말") + "&card=1")[1]["results"]]
    assert _카 and _카[0].get("color") == "노랑" and _카[0].get("pinned"), _카
    call("POST", "/eb/v1/memory/mark", {"title": "표시 카드", "archived": True})
    assert not call("GET", "/eb/v1/memory/search?q=" + urllib.parse.quote("표시카드낱말") + "&card=1")[1]["results"], "보관한 글이 목록에 나온다"
    assert call("GET", "/eb/v1/memory/search?q=" + urllib.parse.quote("표시카드낱말") + "&card=1&archived=1")[1]["results"], "보관함에 없다"
    assert call("GET", "/eb/v1/memory/search?q=" + urllib.parse.quote("표시카드낱말"))[1]["results"], "AI 길에서 보관 글이 사라졌다"
    call("POST", "/eb/v1/memory/delete", {"title": "표시 카드"})
    _휴 = [x for x in call("GET", "/eb/v1/trash")[1]["trash"] if x["title"] == "표시 카드"]
    assert _휴 and "/" not in _휴[0]["id"], "휴지통에 없거나 경로가 샌다"
    assert call("POST", "/eb/v1/trash/restore", {"id": "없는id"})[0] == 404
    assert call("POST", "/eb/v1/trash/restore", {"id": _휴[0]["id"]})[0] == 200
    assert server.notes.read("표시 카드") is not None, "휴지통에서 못 되살렸다"
    assert call("GET", "/eb/v1/trash", token="wrong-token")[0] == 401

    # --- 서식을 폰까지(5단계): 창고 `_서식/` 의 틀을 열쇠 단 문으로 준다. 자리는 채우지 않고 그대로 ---
    server.notes.template_root().mkdir(parents=True, exist_ok=True)
    (server.notes.template_root() / "시험서식.md").write_text(
        "제품명 : \n받은날 : {{날짜}}\n", encoding="utf-8")
    assert call("GET", "/eb/v1/templates", token="wrong-token")[0] == 401
    _상, _틀 = call("GET", "/eb/v1/templates")
    _시험틀 = [t for t in (_틀 or {}).get("templates", []) if t["name"] == "시험서식"]
    assert _상 == 200 and _시험틀, _틀
    assert "{{날짜}}" in _시험틀[0]["body"], "서식 자리를 서버가 미리 채웠다 — 폰이 적는 날짜가 아니게 된다"

    # --- 첨부 올리기(4단계): 폰이 찍은 사진을 바이트 그대로 올리고, 받은 이름으로 글을 쓴다 ---
    def 올리기(name, data, title="사진 시험", cid=None, token="test-token"):
        import urllib.parse
        q = urllib.parse.urlencode({"name": name, "title": title, **({"client_id": cid} if cid else {})})
        req = urllib.request.Request(base + "/eb/v1/attach?" + q, data=data, method="POST",
                                     headers={"Authorization": f"Bearer {token}",
                                              "Content-Type": "application/octet-stream"})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            raw = e.read().decode()
            return e.code, (json.loads(raw) if raw else None)

    assert 올리기("사진.jpg", b"\xff\xd8fake", token="wrong-token")[0] == 401
    assert 올리기("실행.exe", b"MZ")[0] == 400, "아무 파일이나 받는다"
    _s1, _a1 = 올리기("IMG_0001.HEIC", b"heic-bytes", cid="attach-test-0001")
    assert _s1 == 201 and _a1["name"].endswith(".heic"), (_s1, _a1)
    _p1 = server.notes.attachment_path(_a1["name"])
    assert _p1 is not None and _p1.read_bytes() == b"heic-bytes", _p1
    _s2, _a2 = 올리기("IMG_0001.HEIC", b"heic-bytes", cid="attach-test-0001")
    assert _s2 == 200 and _a2.get("duplicate") and _a2["name"] == _a1["name"], "폰이 다시 보내면 사진이 두 장 생긴다"
    call("POST", "/eb/v1/memory", {"title": "사진 시험", "text": f"받은 제품\n\n![[{_a1['name']}]]"})
    assert _a1["name"] in server.notes.read("사진 시험").attachments(), "받은 이름으로 쓴 글이 첨부를 안 가리킨다"
    # 폰 글 보기가 사진을 받아 그린다 — 열쇠가 있어야 하고, 올린 바이트 그대로, 창고 밖은 못 연다
    import urllib.parse
    _req = urllib.request.Request(base + "/eb/v1/attach?" + urllib.parse.urlencode({"name": _a1["name"]}),
                                  headers={"Authorization": "Bearer test-token"})
    with urllib.request.urlopen(_req, timeout=5) as _r:
        assert _r.read() == b"heic-bytes", "올린 사진과 받은 사진이 다르다"
        assert _r.headers["Content-Type"] == "image/heic", _r.headers["Content-Type"]
    assert call("GET", "/eb/v1/attach?" + urllib.parse.urlencode({"name": _a1["name"]}), token="wrong-token")[0] == 401
    assert call("GET", "/eb/v1/attach?name=..%2F..%2Feb_config.json")[0] == 404, "창고 밖 파일을 연다"
    # 폰 목록 카드(card=1): 첫 사진 · 태그 · 기호 걷은 미리보기. AI 기본 길에는 안 실린다.
    call("POST", "/eb/v1/memory", {"title": "사진 시험", "text": "- 종류 : 정수기\n\n#제품"})
    _c = [x for x in call("GET", "/eb/v1/memory/search?q=" + urllib.parse.quote("사진 시험") + "&card=1")[1]["results"]
          if x["title"] == "사진 시험"][0]
    assert _c.get("image") == _a1["name"] and "제품" in _c.get("tags", []), _c
    assert "![[" not in _c["preview"] and "종류: 정수기" in _c["preview"], _c["preview"]
    assert 카드미리보기("[[정수기 vcis-689]] 먼저 · [[회의#8월|8월 회의]]") == "정수기 vcis-689 먼저 · 8월 회의"
    _ai = [x for x in call("GET", "/eb/v1/memory/search?q=" + urllib.parse.quote("사진 시험"))[1]["results"]
           if x["title"] == "사진 시험"][0]
    assert "preview" not in _ai and "image" not in _ai, "AI 기본 길에 카드 칸이 실린다(크레딧)"

    # ★★ **아스키가 아닌 열쇠가 와도 터지지 않는다.** `hmac.compare_digest` 는 글자열끼리는
    #   ASCII 만 견뎌, 한글이 섞인 열쇠가 오면 401 대신 **500 으로 터지고 연결이 끊겼다** —
    #   폰에는 그것이 「컴퓨터에 못 닿았어」로 보여 엉뚱한 곳(테일스케일)을 뒤지게 했다(2026-09-19 실기).
    #   ※ 머리글은 latin-1 로 오간다 — 폰이 UTF-8 로 실어 보낸 바이트가 서버에는 이 꼴로 보인다.
    _한글열쇠 = "한글열쇠".encode("utf-8").decode("latin-1")
    assert call("GET", "/eb/v1/hello", token=_한글열쇠)[0] == 401, "아스키 아닌 열쇠에 401 이 아니라 500 이 난다"
    assert call("GET", "/eb/v1/hello", token="🔑".encode().decode("latin-1"))[0] == 401

    # --- 오프라인에서 고친 글 되돌려 보내기(결정 28) · 작은 사진(결정 27) ---
    import hashlib as _hl

    call("POST", "/eb/v1/memory", {"title": "오프라인 글", "text": "처음 줄"})
    _본 = server.notes.read("오프라인 글").body
    _지문 = _hl.sha256(_본.encode()).hexdigest()
    # ① 그 사이 아무도 안 건드렸다 → force 없이도 덮는다(폰이 본 그 판이니까)
    _상, _답 = call("POST", "/eb/v1/memory",
                   {"title": "오프라인 글", "text": "폰에서 고친 줄", "mode": "replace", "base_hash": _지문})
    assert _상 == 201 and _답.get("merged") is None, _답
    assert server.notes.read("오프라인 글").body.strip() == "폰에서 고친 줄", server.notes.read("오프라인 글").body
    # ② 그 사이 컴퓨터 쪽이 바뀌었다 → **덮지 않는다.** 둘 다 남기고 알린다
    call("POST", "/eb/v1/memory", {"title": "오프라인 글", "text": "컴퓨터에서 보탠 줄"})
    _상, _답 = call("POST", "/eb/v1/memory",
                   {"title": "오프라인 글", "text": "폰에서 또 고친 줄", "mode": "replace", "base_hash": _지문})
    assert _상 == 201 and _답.get("merged") == "appended", _답
    _몸 = server.notes.read("오프라인 글").body
    assert "컴퓨터에서 보탠 줄" in _몸, "컴퓨터에서 쓴 줄을 지웠다"
    assert "폰에서 또 고친 줄" in _몸 and "## 폰에서 고친 판" in _몸, _몸
    # ③ 지문 없이 덮으려 하면 예전처럼 막힌다(force 가 필요하다)
    assert call("POST", "/eb/v1/memory",
                {"title": "오프라인 글", "text": "그냥 덮기", "mode": "replace"})[0] == 409

    # 작은 사진 — 목록 카드가 원본을 통째로 안 받게(결정 27)
    import io as _io

    from PIL import Image as _Image

    _버퍼 = _io.BytesIO()
    _Image.new("RGB", (1600, 1200), (30, 90, 200)).save(_버퍼, "JPEG", quality=95)
    _상, _사진 = 올리기("큰사진.jpg", _버퍼.getvalue(), title="사진 시험")
    assert _상 == 201, (_상, _사진)

    def 내려받기(이름, 너비=0):
        import urllib.parse as _up
        칸 = {"name": 이름, **({"w": str(너비)} if 너비 else {})}
        요청 = urllib.request.Request(base + "/eb/v1/attach?" + _up.urlencode(칸),
                                    headers={"Authorization": "Bearer test-token"})
        with urllib.request.urlopen(요청, timeout=5) as 답:
            return 답.read()

    _원본 = 내려받기(_사진["name"])
    _작은 = 내려받기(_사진["name"], 320)
    assert len(_작은) * 4 < len(_원본), (len(_작은), len(_원본))
    assert _작은[:3] == b"\xff\xd8\xff", "작은 사진이 JPEG 가 아니다"
    # 모르는 너비·못 줄이는 꼴이면 원본을 그대로 준다(사진이 안 보이는 것보다 낫다)
    assert 내려받기(_사진["name"], 999) == _원본
    assert 내려받기(_a1["name"], 320) == b"heic-bytes", "못 줄이는 꼴인데 빈 것을 준다"

    status, hello = call("GET", "/eb/v1/hello")
    # ★★ **방금 쓴 글은 바로 뜻으로도 찾혀야 한다.** 안 그러면 AI 가 제가 저장한 것을
    #   못 찾아 다시 검색한다 — 그게 800자다. 뒤에서 도는 실은 30초마다라 그 사이가 빈다.
    #   (이 자체점검 서버는 임베더가 없어 뜻 검색이 안 돈다 — **벡터 표에 줄이 생겼는지**로 잰다.)
    class 가짜임베더:
        def __call__(self, 글들, 앞=""):
            return [[0.1] * 8 for _ in 글들]
    쓰던것 = getattr(server.notes, "_embed", None)
    server.notes.use_embedder(가짜임베더())
    # ★★ **읽힌 글이 앞선 상태에서 재야 한다.** `vec_pending` 의 첫 키가 `used_at DESC` 라
    #   검색으로 읽힌 글들이 앞선다 — 빈 창고에서는 그런 글이 없어 **우연히 통과한다.**
    #   실무 창고에서 검색을 스무 번 돌린 뒤에는 엉뚱한 글이 채워졌다.
    #   여기서도 먼저 검색을 한 번 돌려 `used_at` 을 찍어 두고 잰다.
    call("POST", "/eb/v1/memory", {"title": "방금 쓴 글", "text": "이 글은 바로 벡터가 생겨야 한다."})
    있나 = server.notes.conn.execute(
        "SELECT count(*) FROM vectors v JOIN notes n ON n.path = v.path "
        "WHERE n.title = ?", ("방금 쓴 글",)).fetchone()[0]
    assert 있나 == 1, "쓴 직후 벡터가 안 생긴다 — AI 가 제가 저장한 것을 뜻으로 못 찾는다"
    server.notes.use_embedder(쓰던것) if 쓰던것 else setattr(server.notes, "_embed", None)

    # ★ **창고 판이 인사에 실려야 한다.** 없으면 AI 는 이 창고에 무엇이 들었는지 모른 채
    #   헛검색을 여러 번 한다 — 한 번이 800자다. 좁히는 문법도 같이 적는다.
    판 = hello.get("store") or {}
    assert 판.get("notes") is not None, f"창고 판이 없다: {hello}"
    # ★ **인사는 세션마다 한 번 나가는 고정 세금이다.** 여기에 설명을 계속 붙이면
    #   창고를 한 번도 안 쓰는 세션까지 그 값을 낸다. 늘리려면 그만한 값을 재고 늘린다.
    #   (여기 작은 창고에서 789자. 덩치의 거의 전부가 `how` 글이라 실무 창고에서도
    #    비슷하다 — 오너 창고 936자를 말을 줄여 820자대로 되돌린 뒤 이 막이를 뒀다.)
    import json as _j

    인사글자 = len(_j.dumps(hello, ensure_ascii=False))
    assert 인사글자 <= 1200, f"인사가 너무 커졌다: {인사글자}자 — 붙일 만한 값인지 재 봐라"
    assert "kinds" in 판 and "how" in 판, f"갈래나 쓰는 법이 빠졌다: {판}"
    assert "kind:" in 판["how"] and "k=" in 판["how"], f"좁히는 법을 안 알려 준다: {판['how']}"
    # ★ 「내 정보」 글은 고정하지 않으니 인사가 제목을 알려 줘야 AI 가 편다. 없으면 안 싣는다.
    assert "me" not in 판, f"내 정보 글이 없는데 me 를 싣는다: {판}"
    server.notes.write(notes.Note(title="나에 대해", body="## 음식" + chr(10) + "- **좋아하는 음식**: 국수"))
    _판2 = (call("GET", "/eb/v1/hello")[1] or {}).get("store") or {}
    assert _판2.get("me") == "나에 대해", f"내 정보 글이 있는데 인사가 안 알려 준다: {_판2}"
    server.notes.delete("나에 대해")
    # ★★ **안내가 실제 길과 어긋나면 AI 를 잘못 이끈다.** 새 길을 내고 `how` 를 안 고치면
    #   그 길은 없는 것과 같고(아무도 안 부른다), 없앤 길을 적어 두면 AI 가 헛걸음한다.
    #   그래서 **적힌 길은 다 실제로 돌아야 한다** — 여기서 한 번씩 불러 본다.
    # ★ **빼는 길도 알려 준다.** 오너 창고는 대화 조각(`kind: 일`)이 2373/2794 장이라
    #   그것만 빼도 찾은 물음이 12 → 13 이었다(글자는 거의 같다). 되는데 안 알려 주면
    #   없는 것과 같다 — 오늘만 몇 번째다.
    for 길 in ("brief=1", "q=", "k=", "-kind:", "year:", "path:"):
        assert 길 in 판["how"], f"안내에 「{길}」 이 없다 — 만든 길을 AI 가 모른다"
    # ★★ **빗나갔을 때 무엇을 할지도 알려 준다.** 한 번 물어 못 찾으면 AI 는 같은 말을
    #   조금씩 바꿔 가며 여러 번 묻는다 — 한 번이 800자다. 갈래로 좁히면 목록 밖이던 글이
    #   1~4등으로 올라온다는 것을 재 봤다(오너 창고 2794장·얼린 물음 20개 중 셋이 살아났다,
    #   `시험기록/실험-갈래로좁히면.py`). 그 한 줄이 없으면 AI 는 계속 넓게만 묻는다.
    #   ※ 처음엔 「한 번 더」로 셌는데 그 말이 안내에 **두 번** 있어, 앞엣것을 지워도
    #     안 터졌다. 세는 글자는 **한 자리에만 있는 것**으로 고른다.
    다시물어 = "밖에 있던 글이"
    assert 다시물어 in 판["how"], f"빗나갔을 때 갈래로 다시 물으라는 말이 없다: {판['how']}"
    # ★★ **좁히는 이름이 늘면 안내도 같이 늘어야 한다.** 오늘만 다섯 번, 되는데 아무도
    #   모르는 길이 나왔다(좁히기 · 지난 판 · 큰 모델 · 갈래 빼기 · 해·경로).
    #   이름을 하나 더하고 안내를 안 고치면 **그 길은 없는 것과 같다** — 여기서 막는다.
    #   (한글 이름은 같은 것의 딴 이름이라 하나만 적혀 있으면 된다.)
    import notes as _n

    영문이름 = {이름 for 이름 in _n.NARROW if 이름.isascii()}
    안적힌 = [이름 for 이름 in 영문이름 if f"{이름}:" not in 판["how"]]
    assert not 안적힌, f"좁히는 이름이 안내에 없다 — 되는데 AI 가 모른다: {sorted(안적힌)}"
    assert "/정규식/" in 판["how"], "정규식 검색이 되는데 안내에 없다"
    # ★ 인사의 창고 판을 못 만들면 인사는 하되 **기록에 남긴다** — 판 없는 인사는 AI 를 헛검색으로 이끈다.
    _들은: list = []
    _옛알림, _옛외딴 = globals()["_알림"], server.notes.외딴것수
    globals()["_알림"] = _들은.append
    server.notes.외딴것수 = lambda: 1 / 0
    try:
        _상태, _인사 = call("GET", "/eb/v1/hello")
    finally:
        globals()["_알림"], server.notes.외딴것수 = _옛알림, _옛외딴
    assert _상태 == 200 and "store" not in _인사, (_상태, _인사.get("store"))
    assert any("[인사 판 실패]" in 말 for 말 in _들은), f"인사 판 실패가 기록에 안 남는다: {_들은}"
    # ★★ **큰 뜻 모델이 없으면 그 사실을 AI 에게 말해야 한다.** 받으면 같은 창고에서
    #   찾은 물음이 10 → 12 였다(오너 창고 2794장·얼린 물음 20개). AI 가 이걸 봐야
    #   사람에게 알려 줄 수 있다 — **있는 줄도 모르면 없는 것과 같다.**
    #   이 PC 에는 그 모델이 있을 수 있으니 **없는 자리**를 만들어 잰다.
    옛모델자리 = os.environ.get("VC_MODELS")
    with tempfile.TemporaryDirectory() as 빈자리:
        os.environ["VC_MODELS"] = 빈자리
        _, 큰것없을때 = call("GET", "/eb/v1/hello")
        assert "e5-base" in (큰것없을때.get("store") or {}).get("how", ""),             f"큰 모델이 없는데 알려 주지 않는다: {(큰것없을때.get('store') or {}).get('how', '')}"
    if 옛모델자리 is None:
        os.environ.pop("VC_MODELS", None)
    else:
        os.environ["VC_MODELS"] = 옛모델자리
    _, 큰것있을때 = call("GET", "/eb/v1/hello")
    assert "e5-base" not in (큰것있을때.get("store") or {}).get("how", "")         or paths.meaning_dir("e5-base").name != "e5-base",         "이미 받았는데 또 받으라고 한다"
    st_b, _ = call("GET", "/eb/v1/memory/search?brief=1&q=" + urllib.parse.quote("VC"))
    assert st_b == 200, f"안내가 brief=1 을 말하는데 안 돈다: {st_b}"
    assert status == 200 and hello["protocol"] == PROTOCOL_VERSION
    # 지금 쓰기로 정해진 모델들이 나온다(사양 자동 또는 사용자 선택).
    assert isinstance(hello["models"], list)

    status, out = call("POST", "/v1/chat/completions", {"messages": [{"role": "user", "content": "안녕"}]})
    assert status == 200 and out["choices"][0]["message"]["content"] == "echo:안녕"
    assert call("POST", "/v1/chat/completions", {})[0] == 400

    fake.fail = True
    assert call("POST", "/v1/chat/completions", {"messages": [{"role": "user", "content": "x"}]})[0] == 502
    fake.fail = False

    good = dict(instruction_id="01J", seq=1, phase="intent", tier="phone", outcome="success")
    assert call("POST", "/eb/v1/log", good)[0] == 202
    assert call("POST", "/eb/v1/log", good)[0] == 202  # 재전송
    assert len(store.instruction("01J")) == 1
    bad = dict(good, seq=2, outcome="failure")  # failure_point 없음
    assert call("POST", "/eb/v1/log", bad)[0] == 400, "형식 어긋난 로그가 저장됐다"

    # 연결이 실려 오는지 보려면 가리키는 쪽이 실제로 있어야 한다. 없는 것을 가리키는
    # 링크는 이제 연결이 아니라 **미해결**로 따로 샌다(notes.unresolved).
    assert call("POST", "/eb/v1/memory", {"title": "VC", "text": "여기서 시작한다."})[0] == 201
    mem = {"title": "카페 단골", "text": "난 아이스만 마신다. [[VC]]", "pinned": True}
    assert call("POST", "/eb/v1/memory", mem)[0] == 201
    assert call("POST", "/eb/v1/memory", {"text": "제목 없음"})[0] == 400
    # 검색어는 퍼센트 인코딩(UTF-8)해서 보낸다. URL은 ASCII만 실을 수 있다.
    status, found = call("GET", "/eb/v1/memory/search?q=" + urllib.parse.quote("아이스"))
    assert status == 200 and len(found["results"]) == 1
    assert found["results"][0]["links"] == ["VC"], "연결이 안 실려 온다"

    # ★★ **1단은 AI 가 크레딧을 태우는 자리다**(오너 지시 2026-09-12: 크레딧을 줄이는 것이
    #   성능이다). 재 본 값(오너 창고 2794장·얼린 물음 20개): 한 장 195자 중 `created` 33 ·
    #   `pinned` 15 · `headings` 14 · `links` 11 — 이 창고에서는 뒤 둘이 **거의 다 빈 배열**이라
    #   그것만 빼도 1716 → 1272자였다. **빈 칸과 기본값은 안 보낸다.** 없는 칸은 「없다」로 읽힌다.
    #   (위 「카페 단골」은 일부러 `pinned: True` 로 넣은 글이라 그것으로는 못 잰다 —
    #    안 꽂힌 보통 글로 잰다.)
    call("POST", "/eb/v1/memory",
         {"title": "긴 회의", "text": "첫 줄은 인사다." + chr(10) * 2
                                    + "예산은 삼천만 원으로 정했다." + chr(10) * 2 + "끝."})
    status, 걸린 = call("GET", "/eb/v1/memory/search?q=" + urllib.parse.quote("예산"))
    골라 = [r for r in 걸린["results"] if r["title"] == "긴 회의"]
    assert 골라, "방금 넣은 글을 못 찾는다"
    한장 = 골라[0]
    assert "pinned" not in 한장, "거짓인 pinned 를 실어 보낸다"
    assert "kind" not in 한장, "기본값 note 를 실어 보낸다"
    assert len(한장.get("created", "")) <= 10, f"1단이 시각까지 실어 보낸다: {한장.get('created')}"
    assert "headings" not in 한장 and "links" not in 한장, "빈 목록을 실어 보낸다"
    # ★ **요약은 물음에 걸린 줄을 고른다.** 첫 문장만 주면 AI 가 「이 글이 답하나」를 못 가려
    #   2단을 여러 번 부른다 — 그게 값이다. 글자 수는 그대로인데 고를 수 있게 된다.
    assert "삼천만" in 한장["summary"], f"요약이 물음을 안 본다: {한장['summary']}"

    # ★★ **긴 글은 `q=` 로 둘레만.** 오너 창고에서 1000자 넘는 글 199장 중 소제목이 있는
    #   것은 7장뿐이라 `heading=` 으로 고르는 길이 사실상 없다 — AI 가 1301자를 통째로 태운다.
    #   [잰 것] 긴 글 30장: 41,583 → 24,615자(41% 감).
    긴몸 = ("머리말이 길게 이어진다." + chr(10)) * 60 + "예산은 삼천만 원으로 정했다." + (chr(10) + "꼬리말이 길게 이어진다.") * 60
    call("POST", "/eb/v1/memory", {"title": "아주 긴 글", "text": 긴몸})
    status, 둘 = call("GET", "/eb/v1/memory/note?title=" + urllib.parse.quote("아주 긴 글")
                     + "&q=" + urllib.parse.quote("예산을 얼마로 정했나"))
    assert status == 200, status
    assert "삼천만" in 둘["text"], f"물음이 걸린 자리를 안 준다: {둘['text'][:60]}"
    assert 둘["chars"] < len(긴몸), f"둘레만 달랬는데 통째로 준다: {둘['chars']}"
    assert 둘.get("cut") and 둘.get("full_chars", 0) > 둘["chars"],         f"자른 것을 안 말한다 — AI 가 글 전체를 본 줄 안다: { {k: v for k, v in 둘.items() if k != 'text'} }"
    status, 온통 = call("GET", "/eb/v1/memory/note?title=" + urllib.parse.quote("아주 긴 글"))
    assert 온통["chars"] == 둘["full_chars"] and "cut" not in 온통, "q 가 없는데 잘랐다"
    # ★★ **아주 긴 글은 `q=` 없이 불러도 상한이 있다.** 흡수는 5만 자짜리 한 줄도
    #   그대로 들인다(원본이 원본이다) — 그 글을 통째로 주면 2만 토큰이 한 번에 나간다.
    call("POST", "/eb/v1/memory", {"title": "어마어마한 글", "text": "가" * (MAX_NOTE_CHARS + 5000)})
    status, 큰것 = call("GET", "/eb/v1/memory/note?title=" + urllib.parse.quote("어마어마한 글"))
    assert 큰것["chars"] <= MAX_NOTE_CHARS, f"상한을 안 지킨다: {큰것['chars']}"
    assert 큰것.get("cut"), "잘라 놓고 말을 안 한다"
    status, 뚫음2 = call("GET", "/eb/v1/memory/note?full=1&title="
                        + urllib.parse.quote("어마어마한 글"))
    assert 뚫음2["chars"] > MAX_NOTE_CHARS, "full=1 로도 통째를 못 받는다"

    # ★ **훑을 때는 제목만.** 「무슨 결정들이 있었나」처럼 목록을 보는 일은 흔한데
    #   장마다 요약·날짜·이음선까지 실으면 세 배가 든다(오너 창고 120장: 20,233 → 6,586자).
    status, 간 = call("GET", "/eb/v1/memory/search?brief=1&q=" + urllib.parse.quote("예산"))
    assert status == 200 and 간["results"], 간
    첫 = 간["results"][0]
    assert set(첫) <= {"title", "chars", "kind"}, f"brief 인데 딴 것도 실어 보낸다: {첫}"
    assert "summary" not in 첫, "brief 인데 요약을 보낸다"


    # ★★ **꺼내기는 두 단이다.** 1단은 몸을 안 준다 — 생기다 말면 여덟 장에
    # 46,000자가 다시 나간다(재 본 값: 평균 5,814자 · 최대 184,467자).
    달 = chr(10)
    긴글 = (f"머리말{달}{달}## 첫 칸{달}" + "가" * 3000
            + f"{달}{달}## 둘째 칸{달}여기만 읽고 싶다{달}")
    assert call("POST", "/eb/v1/memory", {"title": "긴 기록", "text": 긴글})[0] == 201
    status, 찾 = call("GET", "/eb/v1/memory/search?q=" + urllib.parse.quote("둘째"))
    assert status == 200 and 찾["results"], 찾
    한장 = 찾["results"][0]
    assert "body" not in 한장, "1단이 몸을 통째로 준다"
    assert 한장["summary"] and len(한장["summary"]) <= 120, 한장["summary"]
    assert "둘째 칸" in 한장["headings"], 한장["headings"]
    assert 한장["chars"] > 3000, "얼만큼 큰지를 안 밝히면 펼칠지 고를 수가 없다"
    assert len(json.dumps(찾, ensure_ascii=False)) < 1500, "1단이 무거워졌다"

    # 2단 — 고른 구획만 펼친다
    status, 토막 = call("GET", "/eb/v1/memory/note?title=" + urllib.parse.quote("긴 기록")
                        + "&heading=" + urllib.parse.quote("둘째 칸"))
    assert status == 200 and 토막["text"].strip() == "여기만 읽고 싶다", 토막
    assert "가가가" not in 토막["text"], "다른 칸까지 딸려왔다"
    # 없는 소제목은 **글 통째로 바꾸지 않고** 없다고 말하며 있는 것을 보인다
    # ★ **없다고만 하면 AI 는 처음부터 다시 찾는다 — 그게 800자다.** 제목을 조금 틀리게
    #   적는 것은 AI 가 흔히 하는 실수다(앞을 자르거나 괄호를 빼먹는다). 실마리를 준다.
    status, 틀림 = call("GET", "/eb/v1/memory/note?title=" + urllib.parse.quote("긴 기"))
    assert status == 404, status
    assert "긴 기록" in (틀림.get("did_you_mean") or []),         f"제목을 틀렸을 때 가까운 것을 안 알려 준다: {틀림}"

    status, 없음 = call("GET", "/eb/v1/memory/note?title=" + urllib.parse.quote("긴 기록")
                        + "&heading=" + urllib.parse.quote("없는 칸"))
    assert status == 404 and "둘째 칸" in 없음["headings"], 없음

    # ★ **블록 참조**(`#^이름`) — 소제목이 없는 긴 글에서 한 자리를 가리키는 길이다.
    #   오너 창고는 1000자 넘는 글 199장 중 소제목이 있는 것이 일곱 장뿐이라 값이 크다.
    블록몸 = 달.join(["앞 문단.", "", "여기가 답이다. ^답칸", "", "뒤 문단."])
    assert call("POST", "/eb/v1/memory", {"title": "블록 기록", "text": 블록몸})[0] == 201
    status, 블 = call("GET", "/eb/v1/memory/note?title=" + urllib.parse.quote("블록 기록")
                     + "&heading=" + urllib.parse.quote("^답칸"))
    assert status == 200 and 블["text"] == "여기가 답이다.", 블
    assert "뒤 문단" not in 블["text"], "블록 밖까지 딸려왔다"
    # 없는 블록에는 **있는 블록 이름**을 준다. 소제목 목록을 주면 없는 길을 또 두드린다.
    status, 블없 = call("GET", "/eb/v1/memory/note?title=" + urllib.parse.quote("블록 기록")
                       + "&heading=" + urllib.parse.quote("^없는칸"))
    assert status == 404 and 블없.get("blocks") == ["답칸"], 블없
    # ★★ **k 는 조여야 한다.** 험한 물음을 던져 보니 셋이 샜다(실제로 잰 것):
    #   `k=99999` 474,124자 · `k=-1` 182,114자(SQL LIMIT -1 은 무제한) ·
    #   `k=abc` 는 int() 가 터져 **서버가 답도 없이 연결을 끊었다.**
    #   창고가 통째로 나가는 것은 이 물건이 막으려던 바로 그것이다.
    #   ※ **작은 창고는 이 검사를 우연히 통과시킨다** — 걸릴 글이 쉰 장보다 적으면
    #     안 조여도 쉰 장이 안 나온다. 그래서 여기서 예순 장을 만들어 두고 잰다.
    for _i in range(60):
        assert call("POST", "/eb/v1/memory",
                    {"title": f"조임 시험 {_i}", "text": "조이는지 보려고 만든 글이다."})[0] == 201
    status, 많이 = call("GET", "/eb/v1/memory/search?k=99999&q=" + urllib.parse.quote("조이는지"))
    assert status == 200 and len(많이["results"]) <= 50, f"k 를 안 조인다: {len(많이['results'])}장"
    status, 음수 = call("GET", "/eb/v1/memory/search?k=-1&q=" + urllib.parse.quote("조이는지"))
    assert status == 200 and len(음수["results"]) <= 50, f"음수 k 가 창고를 통째로 준다: {len(음수['results'])}장"
    status, 글자 = call("GET", "/eb/v1/memory/search?k=abc&q=" + urllib.parse.quote("조이는지"))
    assert status == 200, f"숫자 아닌 k 에 서버가 터진다: {status}"
    # 제목만 주는 훑기는 한 장이 싸다 — 여기는 높게 둬야 목록 훑기가 산다
    status, 훑 = call("GET", "/eb/v1/memory/search?brief=1&k=60&q=")
    assert status == 200, 훑

    # ★ **글자가 아닌 것이 와도 답은 해야 한다.** `{"title": 12345}` 에 `.strip()` 이 터져
    #   서버가 답도 없이 연결을 끊었다 — 부르는 쪽은 무엇이 틀렸는지 알 길이 없다.
    for 나쁜몸 in ({"title": 12345, "text": "숫자 제목"},
                 {"title": "리스트 몸", "text": ["가", "나"]},
                 {"title": None, "text": "없는 제목"}):
        상태, 답 = call("POST", "/eb/v1/memory", 나쁜몸)
        assert 상태 == 400, f"글자 아닌 것에 400 을 안 준다: {상태} {답}"

    # ★★ **잘못 넣은 것을 치우는 길**과 **제목 고치는 길**. 화면에서는 둘 다 되는데 문이 없었다 —
    #   창고가 AI 의 바깥 기억이라면 잘못 넣은 것을 못 치우는 쪽이 이상하다.
    assert call("POST", "/eb/v1/memory", {"title": "지울 글", "text": "잘못 넣었다"})[0] == 201
    상태, 지움 = call("POST", "/eb/v1/memory/delete", {"title": "지울 글"})
    assert 상태 == 200 and 지움.get("deleted"), 지움
    assert 지움.get("undo"), "지우고 되돌릴 자리를 안 알려 준다"
    assert call("GET", "/eb/v1/memory/note?title=" + urllib.parse.quote("지울 글"))[0] == 404
    # ★ 가리키던 글이 있으면 **말은 해 준다**(막지는 않는다 — 지우기는 되돌릴 수 있다).
    assert call("POST", "/eb/v1/memory", {"title": "가리켜지는 글", "text": "몸"})[0] == 201
    assert call("POST", "/eb/v1/memory", {"title": "가리키는 쪽", "text": "[[가리켜지는 글]] 본다"})[0] == 201
    상태, 지움2 = call("POST", "/eb/v1/memory/delete", {"title": "가리켜지는 글"})
    assert 상태 == 200 and 지움2.get("was_linked_from") == ["가리키는 쪽"],         f"가리키던 글을 안 알려 준다: {지움2}"

    assert call("POST", "/eb/v1/memory/delete", {"title": "없는 글이다"})[0] == 404
    assert call("POST", "/eb/v1/memory/delete", {"title": "  "})[0] == 400

    assert call("POST", "/eb/v1/memory", {"title": "옛 이름", "text": "몸"})[0] == 201
    assert call("POST", "/eb/v1/memory", {"title": "가리키는 글", "text": "여기 [[옛 이름]] 본다"})[0] == 201
    상태, 바꿈 = call("POST", "/eb/v1/memory/rename", {"title": "옛 이름", "to": "새 이름"})
    assert 상태 == 200, 바꿈
    상태, 따라감 = call("GET", "/eb/v1/memory/note?title=" + urllib.parse.quote("가리키는 글"))
    assert "[[새 이름]]" in 따라감["text"], f"가리키던 링크를 안 따라 고쳤다: {따라감['text']}"
    assert call("POST", "/eb/v1/memory/rename", {"title": "새 이름", "to": "가리키는 글"})[0] == 409

    # ★ **하다 만 이름 바꾸기**는 링크가 반쯤 끊긴 상태다. 창만 그것을 봤다 —
    #   서버로만 쓰는 AI 는 모른 채 그물을 믿는다. 인사에 실어야 알 수 있다.
    (note_store.root.parent / "vc-이름바꾸다만것.txt").write_text(
        "옛 이름" + chr(9) + "새 이름" + chr(10), encoding="utf-8")
    try:
        _, 하다만인사 = call("GET", "/eb/v1/hello")
        assert (하다만인사.get("store") or {}).get("broken_rename"),             f"하다 만 이름 바꾸기를 안 알려 준다: {하다만인사.get('store')}"
    finally:
        (note_store.root.parent / "vc-이름바꾸다만것.txt").unlink(missing_ok=True)
    _, 멀쩡인사 = call("GET", "/eb/v1/hello")
    assert "broken_rename" not in (멀쩡인사.get("store") or {}), "멀쩡한데 끊겼다고 한다"

    # ★ **같은 제목이 두 폴더에** 있으면 1단 카드가 폴더를 싣고, 2단은 `folder=` 로 고른다.
    (note_store.root / "쌍둥이가").mkdir(parents=True, exist_ok=True)
    (note_store.root / "쌍둥이나").mkdir(parents=True, exist_ok=True)
    (note_store.root / "쌍둥이가" / "쌍둥이 회의.md").write_text("가 쪽 쌍둥이 몸", encoding="utf-8")
    (note_store.root / "쌍둥이나" / "쌍둥이 회의.md").write_text("나 쪽 쌍둥이 몸", encoding="utf-8")
    note_store.reindex()
    _, 쌍 = call("GET", "/eb/v1/memory/search?q=" + urllib.parse.quote("쌍둥이"))
    폴더들 = sorted(c.get("folder", "") for c in 쌍["results"] if c["title"] == "쌍둥이 회의")
    assert 폴더들 == ["쌍둥이가", "쌍둥이나"], f"같은 제목 카드에 폴더가 없다: {쌍['results']}"
    _, 골라 = call("GET", "/eb/v1/memory/note?title=" + urllib.parse.quote("쌍둥이 회의")
                 + "&folder=" + urllib.parse.quote("쌍둥이가"))
    assert 골라.get("text", "").startswith("가 쪽"), f"folder= 로 못 고른다: {골라}"

    # ★ **뜻밖의 예외도 답은 한다.** 새 조회의 SQL 이 틀렸을 때 서버가 답도 없이 끊었다.
    _진짜언급 = note_store.언급
    note_store.언급 = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("시험용 고장"))
    try:
        assert call("POST", "/eb/v1/memory", {"title": "고장 시험 글", "text": "몸"})[0] == 201
        상태, 고장 = call("GET", "/eb/v1/memory/note?title=" + urllib.parse.quote("고장 시험 글"))
        assert 상태 == 500 and 고장.get("why") == "RuntimeError", f"뜻밖의 예외에 답을 안 한다: {상태} {고장}"
    finally:
        note_store.언급 = _진짜언급

    # ★★ **뜻 모델이 오르는 동안** 찾으면 조용히 0장이었다 — 그 사실을 1단이 말해야 한다.
    server.뜻상태 = "올리는 중"
    _, 올림 = call("GET", "/eb/v1/memory/search?q=" + urllib.parse.quote("아무 뜻"))
    assert 올림.get("meaning") == "loading", f"뜻 모델을 올리는 중이라고 안 말한다: {올림}"
    server.뜻상태 = "됨"
    _, 됨 = call("GET", "/eb/v1/memory/search?q=" + urllib.parse.quote("아무 뜻"))
    assert "meaning" not in 됨, "다 올랐는데 아직이라고 한다"
    # ★ 모델은 올랐는데 벡터가 많이 비었으면 「덜 찾힌다」고 말한다(색인을 새로 만든 뒤 몇 분).
    _진짜남음 = note_store.vec_left
    _진짜임베더 = getattr(note_store, "_embed", None)
    note_store.vec_left = lambda: 10_000
    _진짜뜻 = note_store.semantic
    note_store._embed = object()          # 모델이 붙어 있다고 치고
    note_store.semantic = lambda *a, **k: []   # 그 가짜 모델을 부르지 않게
    try:
        _, 덜 = call("GET", "/eb/v1/memory/search?q=" + urllib.parse.quote("아무 뜻"))
        assert 덜.get("meaning") == "partial", f"벡터가 비었는데 말하지 않는다: {덜}"
    finally:
        note_store.vec_left = _진짜남음
        note_store._embed = _진짜임베더
        note_store.semantic = _진짜뜻

    # ★ 2단이 **이름만 적고 안 이은 글**을 알려 준다.
    assert call("POST", "/eb/v1/memory", {"title": "언급 대상 글", "text": "몸"})[0] == 201
    assert call("POST", "/eb/v1/memory", {"title": "말만 한 쪽", "text": "언급 대상 글 이야기"})[0] == 201
    _, 펼 = call("GET", "/eb/v1/memory/note?title=" + urllib.parse.quote("언급 대상 글"))
    assert "말만 한 쪽" in (펼.get("unlinked") or []), f"연결 안 된 언급을 안 알려 준다: {펼}"

    # ★★ **틀렸을 때 무엇이 틀렸는지 말해 준다.** 안 그러면 AI 가 짐작으로 다시 두드린다.
    상태, 다른이름 = call("GET", "/eb/v1/memory/search?query=" + urllib.parse.quote("조이는지"))
    assert 상태 == 200 and 다른이름["results"], "q 를 딴 이름으로 줬더니 빈 검색이 돌았다"
    상태, 길틀림 = call("GET", "/eb/v1/memory/delete?title=x")
    assert 상태 == 404 and "POST" in (길틀림.get("hint") or ""), f"메서드가 틀렸다고 안 말한다: {길틀림}"
    상태, 없는길 = call("GET", "/eb/v1/memory/all")
    assert 상태 == 404 and 없는길.get("paths"), f"있는 길을 안 알려 준다: {없는길}"

    # ★★ **`force: "false"` 로는 못 덮는다.** `bool("false")` 가 참이라 덮어쓰기 막이가 뚫렸다.
    _쓴답 = call("POST", "/eb/v1/memory", {"title": "뚫기 시험", "text": "처음"})
    assert _쓴답[0] == 201
    # 쓰기 답에 절대 경로(집 폴더·사용자 이름)가 실리면 안 된다
    assert "path" not in _쓴답[1] and str(Path.home()) not in json.dumps(_쓴답[1], ensure_ascii=False), _쓴답[1]
    for 가짜참 in ("false", "0", 1, "yes"):
        상태, _ = call("POST", "/eb/v1/memory",
                     {"title": "뚫기 시험", "text": "덮기", "mode": "replace", "force": 가짜참})
        assert 상태 == 409, f"force={가짜참!r} 로 덮어쓰기 막이가 뚫렸다: {상태}"
    assert call("POST", "/eb/v1/memory", {"title": "고정 시험", "text": "몸", "pinned": "false"})[0] == 201
    assert not note_store.read("고정 시험").pinned, '"false" 글자로 고정됐다'
    # ★★ 덮어쓰기 막이는 잠금 안에서 본다 — 읽은 뒤 남이 만든·덧붙인 글을 force 없이 덮으면 안 된다.
    _경주: list = []
    with note_store._글잠금("경주 시험"):
        _실 = threading.Thread(target=lambda: _경주.append(call(
            "POST", "/eb/v1/memory", {"title": "경주 시험", "text": "통째로", "mode": "replace"})))
        _실.start()
        time.sleep(0.5)
        note_store.append("경주 시험", "사람이 먼저 적은 줄")
    _실.join()
    assert _경주 and _경주[0][0] == 409, f"읽은 뒤 생긴 글을 force 없이 덮었다: {_경주}"
    assert "사람이 먼저" in note_store.read("경주 시험").body
    # ★ 이름 바꾸기가 기다리는 사이 새 제목이 생기면 409 — 「없는 글」(404)로 답하면 AI 가 헤맨다.
    note_store.write(notes.Note(title="옮길 원격 글", body="몸"))
    _이름답: list = []
    with note_store._글잠금("생길 제목"):
        _실 = threading.Thread(target=lambda: _이름답.append(call(
            "POST", "/eb/v1/memory/rename", {"title": "옮길 원격 글", "to": "생길 제목"})))
        _실.start()
        time.sleep(0.5)
        note_store.write(notes.Note(title="생길 제목", body="먼저 생김"))
    _실.join()
    assert _이름답 and _이름답[0][0] == 409, f"기다리다 물러난 이름 바꾸기를 404 로 답한다: {_이름답}"
    assert note_store.read("옮길 원격 글") is not None

    # ★ **글자가 아닌 값에는 400 과 까닭을 준다**(전엔 500 — 문은 안 열렸지만 왜 안 되는지 몰랐다).
    for 길, 몸 in (("/eb/v1/ask", {"text": 123}),
                 ("/v1/chat/completions", {"messages": "안녕"}),
                 ("/eb/v1/remote/approve", {"code": 1234}),
                 ("/eb/v1/remote/approve", {"session": ["가"], "nonce": "x"}),
                 ("/eb/v1/remote/deny", {"session": 5}),
                 ("/eb/v1/remote/close", {"session": ["가"]}),
                 ("/eb/v1/log", {"instruction_id": "i", "seq": 1, "phase": "module_run",
                                 "tier": "pc", "outcome": "성공"}),
                 ("/eb/v1/models/download", {"key": ["qwen"]}),
                 ("/eb/v1/models", {"role": 1, "name": ""}),
                 ("/v1/chat/completions", {"messages": [{"role": "user", "content": "안녕"}], "model": 5}),
                 ("/eb/v1/proposals/nope/decision", {"decision": 1})):
        상태, _ = call("POST", 길, 몸)
        assert 상태 == 400, f"{길} {몸} → {상태} (400 이어야 한다)"

    # ★ 갈래가 글자가 아니면 400 — 조용히 "None" 같은 갈래로 저장되면 좁히기에 영영 안 걸린다.
    for 나쁜갈래 in (["가", "나"], None, 123):
        상태, _ = call("POST", "/eb/v1/memory", {"title": "갈래 시험", "text": "몸", "kind": 나쁜갈래})
        assert 상태 == 400, f"글자 아닌 갈래를 받았다: {나쁜갈래!r} → {상태}"

    # ★★ **깨진 설정에서도 켜져야 한다** — json.loads 가 터져 안 켜졌다.
    with tempfile.TemporaryDirectory() as _설곳:
        _설 = Path(_설곳) / "eb_config.json"
        _설.write_text("{깨진", encoding="utf-8")
        _새 = load_config(_설)
        assert isinstance(_새.get("pair_token"), str) and _새["pair_token"], "깨진 설정에서 새 설정을 못 만든다"
        assert list(Path(_설곳).glob("eb_config.json.깨짐-*")), "깨진 설정을 옆에 안 치웠다"
        _설.write_text(json.dumps({"backend": {"kind": "local"}}), encoding="utf-8")
        assert load_config(_설).get("pair_token"), "열쇠가 빠진 설정에 열쇠를 안 채운다"
        # ★★ 평문 API 키는 운영체제 보관소로 옮기고 설정 파일에서는 지운다(오너 결정 1).
        #   ※ 시험 종류 이름을 따로 쓴다 — `anthropic` 으로 재면 사람이 넣어 둔 진짜 키를 덮는다.
        if keystore.available():
            _가짜 = "sk-시험-" + secrets.token_hex(8)
            _뒤 = {"kind": "시험종류-" + secrets.token_hex(4), "api_key": _가짜}
            try:
                _설.write_text(json.dumps({"pair_token": "t", "backend": _뒤}), encoding="utf-8")
                _읽음 = load_config(_설)
                # 글자로 찾으면 안 된다 — json 이 한글을 \uXXXX 로 적어 늘 「없다」가 된다. 읽어서 본다.
                assert "api_key" not in json.loads(_설.read_text(encoding="utf-8"))["backend"], \
                    "평문 API 키가 설정 파일에 남는다"
                assert _읽음["backend"].get("api_key_in") == "keystore", _읽음
                assert keystore.키꺼내기(_읽음["backend"]) == _가짜, "옮긴 키를 못 꺼낸다"
            finally:
                keystore.delete(keystore.키이름(_뒤))

    # ★ **못 쓰면 못 썼다고 말해야 한다.** 읽기 전용 파일에서 `WriteBlocked` 가 그대로
    #   새 나가 서버가 답도 없이 연결을 끊었다 — AI 는 성공인지 실패인지도 모른다.
    import os as _os
    import stat as _stat

    assert call("POST", "/eb/v1/memory", {"title": "막힌 글", "text": "첫 판"})[0] == 201
    막힌파일 = note_store.path_of("막힌 글")
    # ★ **막는 방법이 운영체제마다 다르다.** 윈도우는 파일만 읽기 전용이면 자리 바꾸기가
    #   막히는데, **맥·리눅스는 `os.replace` 가 폴더 권한만 봐서 그냥 써진다** —
    #   맥에서 그대로 재니 201(썼다)이 나와 이 검사가 터졌다. 폴더도 같이 잠근다.
    막힌폴더 = 막힌파일.parent
    _옛파일 = _stat.S_IMODE(_os.stat(막힌파일).st_mode)
    _옛폴더 = _stat.S_IMODE(_os.stat(막힌폴더).st_mode)
    _os.chmod(막힌파일, _stat.S_IREAD)
    if _os.name != "nt":
        _os.chmod(막힌폴더, 0o500)
    try:
        상태, 못씀 = call("POST", "/eb/v1/memory",
                        {"title": "막힌 글", "text": "둘째 판", "mode": "replace", "force": True})
        assert 상태 == 507, f"못 쓰고도 그렇게 말하지 않는다: {상태} {못씀}"
        assert 못씀.get("hint"), 못씀
    finally:
        if _os.name != "nt":
            _os.chmod(막힌폴더, _옛폴더)
        _os.chmod(막힌파일, _옛파일 | _stat.S_IWRITE)

    # ★★ **쓴 자리에서 이을 곳을 알려 준다.** 오너 창고는 2820장 중 2700장(95%)이 아무 데도
    #   안 이어져 있다 — AI 가 글을 붓기만 하고 잇지 않기 때문이다. 이어지지 않은 글은
    #   뜻 검색 말고는 닿을 길이 없다. 강제하지 않고 **알려만 준다**(제목 세 개, 60자쯤).
    #   ※ 뜻 모델이 없으면 조용히 아무것도 안 붙는다. 그때는 이 검사도 건너뛴다.
    assert call("POST", "/eb/v1/memory", {"title": "이을 곳 하나", "text": "등대가 배를 이끈다"})[0] == 201
    상태, 쓴것 = call("POST", "/eb/v1/memory",
                    {"title": "이을 곳 둘", "text": "등대는 밤에 배를 이끄는 표지다"})
    assert 상태 == 201, 쓴것
    if note_store.semantic("등대", k=1):
        assert 쓴것.get("link_to"), f"이을 곳을 안 알려 준다: {쓴것}"
        assert "이을 곳 둘" not in 쓴것["link_to"], "제 글을 이으라고 한다"

    # 붙여 쓰던 쪽은 안 깨진다 — `full=1` 이면 예전처럼 몸이 온다
    status, 통째 = call("GET", "/eb/v1/memory/search?full=1&q=" + urllib.parse.quote("둘째"))
    assert status == 200 and 통째["results"][0]["body"], "full=1 이 안 먹는다"

    # 기본은 덧붙이기다 — 어제 적은 것이 오늘 것에 지워지면 기억이 아니다.
    assert call("POST", "/eb/v1/memory", {"title": "카페 단골", "text": "요즘은 따뜻한 것도 마신다"})[0] == 201
    grown = note_store.read("카페 단골")
    assert "아이스만" in grown.body and "따뜻한" in grown.body, grown.body

    # 다시 써도 신원(식별자·만든 날짜)은 그대로다. 20년 뒤 "언제 처음 적었나"에 답해야 한다.
    first = note_store.read("카페 단골")
    call("POST", "/eb/v1/memory", {"title": "카페 단골", "text": "한 줄 더"})
    assert note_store.read("카페 단골").created == first.created
    assert note_store.read("카페 단골").id == first.id

    # ★★ 두 AI 가 **없던 글에 동시에** 덧붙여도 줄이 안 사라진다.
    import threading as _th8

    #   ※ 틈은 **첫 줄**에만 있다(둘째부터는 글이 있어 잠긴 길로 간다) — 새 글 여럿에 한꺼번에 첫 줄을 던진다.
    _문 = _th8.Barrier(3)

    def _보내기(표):
        for _i in range(12):
            _문.wait()
            call("POST", "/eb/v1/memory", {"title": f"동시에 새로 쌓는 글 {_i}", "text": f"{표}줄"})
    _실들 = [_th8.Thread(target=_보내기, args=(x,)) for x in "가나다"]
    [t.start() for t in _실들]; [t.join() for t in _실들]
    _남 = sum(1 for _i in range(12) for x in "가나다"
             if f"{x}줄" in note_store.read(f"동시에 새로 쌓는 글 {_i}").body)
    assert _남 == 36, f"새 글에 동시에 쌓은 첫 줄이 사라진다: 36 중 {_남}"
    assert call("POST", "/eb/v1/memory", {"title": "처음부터 고정", "text": "가", "pinned": True})[0] == 201
    assert note_store.read("처음부터 고정").pinned, "새 글 pinned 가 안 먹는다"

    # 사람이 고친 항목은 관찰이 덮지 못한다.
    fixed = note_store.read("카페 단골")
    fixed.body, fixed.edited_by = "정정: 나는 라떼만 마신다", "사람"
    note_store.write(fixed)
    blocked = call("POST", "/eb/v1/memory",
                   {"title": "카페 단골",
                    "text": "관찰: 아메리카노", "mode": "replace"})
    assert blocked[0] == 409, blocked
    # ★★ **밖에서(옵시디언·메모장) 고친 것도 지켜야 한다.** `edited_by` 는 화면에서
    #   고칠 때만 붙는데 이 물건은 옵시디언 대용이라 밖에서 고치는 것이 주된 길이다.
    #   예전에는 그 손질을 AI 가 force 없이 통째로 지웠다 — 201 이 떨어졌다.
    call("POST", "/eb/v1/memory", {"title": "밖에서 고친 글", "text": "AI 가 처음 쓴 것."})
    밖파일 = note_store.path_of("밖에서 고친 글")
    밖파일.write_text(밖파일.read_text(encoding="utf-8").rstrip()
                    + chr(10) + "사람이 손으로 보탠 줄." + chr(10), encoding="utf-8")
    note_store.reindex()
    막힘 = call("POST", "/eb/v1/memory", {"title": "밖에서 고친 글",
                                        "text": "통째로 갈아치운다.", "mode": "replace"})
    assert 막힘[0] == 409, f"밖에서 고친 것을 그냥 덮는다: {막힘}"
    assert "사람이 손으로" in note_store.read("밖에서 고친 글").body, "사람 손질이 지워졌다"
    assert "force" in json.dumps(막힘[1], ensure_ascii=False), f"뚫는 법을 안 알려 준다: {막힘[1]}"
    assert note_store.read("카페 단골").body.startswith("정정"), "사람 손질이 덮였다"
    # 정말 덮어야 할 때는 force로 뚫는다 — 다만 눌러서 뚫는 길이 있어야 한다.
    뚫음 = call("POST", "/eb/v1/memory", {"title": "카페 단골", "text": "새로 씀",
                                        "mode": "replace", "force": True})
    assert 뚫음[0] == 201, 뚫음
    # ★★ **덮었으면 되돌릴 자리를 알려 준다.** 지난 판은 남는데(밖에서 고친 글은
    #   `_남의손인가` 가 지문으로 가려내 반드시 남긴다) AI 가 **그것을 볼 길이 없었다** —
    #   화면에서만 된다. 안전망이 반쪽이었다. 덮은 그 자리에서 되돌릴 곳을 준다.
    덮음 = call("POST", "/eb/v1/memory", {"title": "밖에서 고친 글",
                                        "text": "정말 갈아치운다.",
                                        "mode": "replace", "force": True})
    assert 덮음[0] == 201, 덮음
    되돌 = 덮음[1].get("undo") or {}
    assert 되돌.get("path") and Path(되돌["path"]).is_file(), f"되돌릴 자리를 안 준다: {덮음[1]}"
    assert "사람이 손으로" in Path(되돌["path"]).read_text(encoding="utf-8"),         "지난 판에 사람 손질이 없다 — 덮으면 영영 사라진다"

    # 바로 위에서 「카페 단골」을 통째로 덮어 링크가 사라졌다. 이을 것을 하나 만들고 잰다.
    call("POST", "/eb/v1/memory", {"title": "이음 시험", "text": "[[카페 단골]] 을 가리킨다"})
    status, graph = call("GET", "/eb/v1/graph")
    # ★ **이은 마디만 온다.** 빈 마디를 같이 보내면 오너 창고(2794장)에서 98,425자가
    #   나가는데 그중 쓸모 있는 것이 하나도 없었다 — AI 가 38,000토큰을 태우고 꽝이다.
    assert status == 200, status
    assert all(graph["nodes"].values()), f"이음선 없는 마디가 실려 온다: {graph['nodes']}"
    assert "이음 시험" in graph["nodes"], f"이은 마디가 빠졌다: {graph['nodes']}"

    assert call("POST", "/eb/v1/proposals/p1/decision", {"decision": "그만"})[0] == 400
    assert call("POST", "/eb/v1/proposals/nope/decision", {"decision": "approve"})[0] == 404

    # --- 성장 루프: 낭비 감지 → 제안 → 승인 → 스킬로 남는다 (결정 17·18) ---
    assert call("POST", "/eb/v1/analyze", {}) == (200, {"created": [], "found": 0})

    for i in range(3):
        ev = dict(instruction_id=f"i{i}", phase="module_run", module="product_search")
        assert call("POST", "/eb/v1/log", dict(ev, seq=1, tier="phone",
                                               outcome="failure", failure_point="vision_model"))[0] == 202
        assert call("POST", "/eb/v1/log", dict(ev, seq=2, tier="pc", outcome="success"))[0] == 202

    status, made = call("POST", "/eb/v1/analyze", {})
    assert status == 200 and len(made["created"]) == 1, made
    # 두 번 돌려도 같은 제안이 또 쌓이지 않는다.
    assert call("POST", "/eb/v1/analyze", {})[1]["created"] == []

    pending = store.pending_proposals()
    assert len(pending) == 1
    pid = pending[0]["proposal_id"]

    # 승인 전에는 스킬이 없다 — 자동 적용이 없다는 뜻이다.
    assert server.skills.load("product_search") is None
    status, out = call("POST", f"/eb/v1/proposals/{pid}/decision", {"decision": "approve"})
    assert status == 200 and out["applied"]["start_tier"] == "pc"
    saved = server.skills.load("product_search")
    assert saved is not None and saved.start_tier == "pc" and saved.version == 1

    # 되돌릴 이전 버전이 없으면 거부한다 — 조용히 성공했다고 하지 않는다.
    assert call("POST", f"/eb/v1/proposals/{pid}/decision", {"decision": "revert"})[0] == 409

    # 후보 중 하나를 고르면 그 모듈이 그 말을 배운다. 후보에 없는 걸 고르면 막는다.
    store.add_proposal(dict(
        proposal_id="pk", type="intervention_proposal", title="매번 되묻는 표현",
        summary="'그거 좀 해줘'를 3번 되물었어.", based_on=["c1", "c2", "c3"],
        declaration={"candidates": ["product_search", "translate"], "examples": ["그거 좀 해줘"]},
    ))
    assert call("POST", "/eb/v1/proposals/pk/decision", {"decision": "pick:없는모듈"})[0] == 400
    status, out = call("POST", "/eb/v1/proposals/pk/decision", {"decision": "pick:translate"})
    assert status == 200 and out["applied"]["examples"] == ["그거 좀 해줘"], out

    # ★★ 바깥 스킬 문 — 선언문만 받는다 · 승인 전엔 스킬이 아니다 · 모르는 모듈은 막는다.
    for 나쁜것 in ({"name": "나쁜", "steps": [{"module": "../../etc/passwd"}]},
                  {"name": "나쁜", "steps": "글자"},
                  {"name": 12, "steps": [{"module": "navigate"}]},
                  {"name": "나쁜", "steps": [{"module": "navigate", "params": "rm -rf"}]},
                  {"name": "나쁜", "triggers": "글자", "steps": [{"module": "navigate"}]}):
        상태, 답 = call("POST", "/eb/v1/skills/propose", 나쁜것)
        assert 상태 == 400, f"나쁜 선언문을 받았다: {나쁜것} → {상태} {답}"
    assert "navigate" in call("POST", "/eb/v1/skills/propose",
                              {"name": "나쁜", "steps": [{"module": "없는것"}]})[1]["known"]
    상태, 제안 = call("POST", "/eb/v1/skills/propose",
                    {"name": "바깥 길 안내", "triggers": ["집에 가자"],
                     "steps": [{"module": "navigate", "params": {"to": "집"}}]})
    assert 상태 == 202 and 제안["proposal_id"].startswith("ext-"), 제안
    assert server.skills.load("바깥 길 안내") is None, "승인 전에 바깥 스킬이 스킬이 됐다"
    상태, out = call("POST", f"/eb/v1/proposals/{제안['proposal_id']}/decision", {"decision": "approve"})
    assert 상태 == 200 and server.skills.load("바깥 길 안내").steps[0]["module"] == "navigate", out
    store.add_proposal(dict(proposal_id="odd", type="skill_proposal", title="모르는 칸", summary="",
                            based_on=[], declaration={"name": "모르는 칸", "exec": "rm -rf"}))
    assert call("POST", "/eb/v1/proposals/odd/decision", {"decision": "approve"})[0] == 200, \
        "선언문에 모르는 칸이 섞이면 승인이 터진다"

    # ★★ 쓰다 보면 채워지는 오너 정보 — 짐작으로 적고, 오너 답은 안 덮는다
    import settings as _설정

    assert call("POST", "/eb/v1/me/learn", {"category": "VC와 나", "question": "", "answer": "x"})[0] == 400
    assert call("POST", "/eb/v1/me/learn", {"category": "VC와 나", "question": "q", "answer": 5})[0] == 400
    상태, 답 = call("POST", "/eb/v1/me/learn", {"category": "VC와 나", "question": "나의 주요 업무",
                                             "answer": "앱 개발", "source": "대화"})
    assert 상태 == 201 and 답["result"] == "saved", 답
    _, _남 = _설정.from_body(note_store.read(_설정.PROFILE_TITLE).body)
    assert _설정.guesses(_남).get(("VC와 나", "나의 주요 업무"), "").startswith("앱 개발"), _남
    _설정.save_profile(note_store, {"음식": {"좋아하는 음식": "국수"}})
    상태, 답 = call("POST", "/eb/v1/me/learn", {"category": "음식", "question": "좋아하는 음식", "answer": "냉면"})
    assert 상태 == 200 and 답["result"] == "owner", f"오너 답을 짐작이 덮으려 한다: {답}"
    assert "냉면" not in note_store.read(_설정.PROFILE_TITLE).body
    assert call("POST", "/eb/v1/me/learn", {"category": "없는갈래", "question": "q", "answer": "a"})[1]["category"] == "기타"
    note_store.delete(_설정.PROFILE_TITLE)

    # ★ 연결한 계정 읽기 — 허용 길만, 연결 안 됐으면 404, 모르는 연결 404(바깥으로는 안 나간다)
    import keystore as _보관

    _옛보관 = (_보관.available, _보관.get)
    _보관.available, _보관.get = (lambda: True), (lambda 이름: None)
    try:
        상태, 답 = call("GET", "/eb/v1/connect/github?path=" + urllib.parse.quote("/user"))
        assert 상태 == 404 and "연결 안 됐다" in 답["error"], (상태, 답)
        assert call("GET", "/eb/v1/connect/github?path=" + urllib.parse.quote("/orgs/x/members"))[0] == 400
        assert call("GET", "/eb/v1/connect/" + urllib.parse.quote("없는곳") + "?path=/user")[0] == 404
    finally:
        _보관.available, _보관.get = _옛보관

    # ★★ 바깥 AI 로 켜면 그 제공자의 모델 이름을 쓴다(깐 gguf 이름이 클라우드로 나가면 안 된다)
    with tempfile.TemporaryDirectory() as _바깥곳:
        _바깥 = EBServer(("127.0.0.1", 0), {"pair_token": "t", "backend": {"kind": "anthropic", "model": "claude-시험"},
                         "artifact_dir": str(Path(_바깥곳) / "a")},
                        Store(":memory:"), Notes(Path(_바깥곳) / "n", index_now=False))
        try:
            assert _바깥.picked["using"]["chat"] == "claude-시험" == _바깥.picked["using"]["vision"], _바깥.picked["using"]
        finally:
            _바깥.server_close()
            _바깥.notes.conn.close()

    # --- 모델 선택: 사용자가 고르고, 없는 건 못 고른다 (결정 42) ---
    status, out = call("GET", "/eb/v1/models")
    assert status == 200 and set(out) == {"installed", "using", "auto", "hardware"}, out
    assert out["hardware"]["tier"] in ("high", "mid", "low", "cpu")
    # ★★ **뜻 모델도 고르는 자리에 있어야 한다.** 예전에는 없어서 화면에서 바꿀 길이
    #   통째로 없었다(열린 문제 15) — 받아 두고도 못 되돌리고, 받으면 좋다는 것도 몰랐다.
    #   [잰 것 2026-09-13] 큰 것(e5-base)이면 오너 창고에서 찾은 물음이 10 → 12 다.
    assert set(out["using"]) == {"chat", "vision", "stt", "voice", "meaning"}, out["using"]
    assert "meaning" in out["installed"], f"뜻 모델을 목록에 안 준다: {list(out['installed'])}"
    # ★★ **화면이 적는 것과 실제로 쓰는 것이 같아야 한다.** 자동 추천은 목록 첫 번째를
    #   쓰는데, 그 차례가 `paths.MEANING_ORDER` 와 어긋나 있었다 — 화면은 「딸려 온 것」
    #   이라 적는데 실제로는 큰 것을 쓰고 있었다. **조용히 어긋나는 자리다.**
    if out["installed"]["meaning"]:
        자동 = out["auto"]["meaning"]
        실제 = paths.meaning_dir()
        같나 = (실제 == paths.models_dir()) if 자동.startswith("딸려 온 것") else (실제.name == 자동)
        assert 같나, f"화면은 「{자동}」 이라는데 실제로는 「{실제}」 를 쓴다"
    # 받아쓰기는 파일이 아니라 이름이라 어느 PC에서든 고를 수 있다.
    # ★★ 모델을 골라도 **화면이 같은 설정 파일에 적은 칸**(글자 크기 등)이 안 지워져야 한다 —
    #   서버가 켤 때 들고 있던 사본으로 통째로 덮어 말없이 지웠다.
    _설정원문 = paths.config_path().read_text(encoding="utf-8") if paths.config_path().exists() else None
    try:
        _지금 = json.loads(_설정원문) if _설정원문 else {}
        paths.config_path().write_text(json.dumps({**_지금, "글자배율": 1.3, "화면방식": "최대화"},
                                          ensure_ascii=False), encoding="utf-8")
        assert call("POST", "/eb/v1/models", {"role": "stt", "name": "medium"})[0] == 200
        _뒤 = json.loads(paths.config_path().read_text(encoding="utf-8"))
        assert _뒤.get("글자배율") == 1.3 and _뒤.get("화면방식") == "최대화", \
            f"모델을 고르니 화면이 적은 설정이 지워졌다: {sorted(_뒤)}"
        assert _뒤.get("models", {}).get("stt") == "medium", _뒤.get("models")
    finally:
        if _설정원문 is None:
            paths.config_path().unlink(missing_ok=True)
        else:
            paths.config_path().write_text(_설정원문, encoding="utf-8")
        assert call("POST", "/eb/v1/models", {"role": "stt", "name": "medium"})[0] == 200
    assert call("GET", "/eb/v1/models")[1]["using"]["stt"] == "medium"
    # 없는 것·없는 역할은 막는다.
    assert call("POST", "/eb/v1/models", {"role": "stt", "name": "huge-v9"})[0] == 400
    assert call("POST", "/eb/v1/models", {"role": "없는역할", "name": "x"})[0] == 400
    # 빈 값은 자동으로 되돌리기.
    assert call("POST", "/eb/v1/models", {"role": "stt", "name": ""})[0] == 200

    # 모델 받기: 목록이 나오고, 없는 건 못 받고, 원격은 못 시킨다.
    status, dl = call("GET", "/eb/v1/models/download")
    assert status == 200 and dl["catalog"] and dl["state"] == "idle", dl
    assert {"key", "role", "label", "size_mb", "installed", "heavy"} <= set(dl["catalog"][0])
    assert call("POST", "/eb/v1/models/download", {"key": "없는모델"})[0] == 400

    # 놀고 있는 모델을 내리고 죽은 세션을 치운다 — 안 부르면 VRAM이 안 풀린다.
    class SweepBackend(FakeBackend):
        swept = False

        def sweep(self):
            # 진짜 엔진처럼 한 번만 내려간다. 매번 True면 로그가 도배된다.
            already, SweepBackend.swept = SweepBackend.swept, True
            return not already

    housekeeper = EBServer(("127.0.0.1", 0), cfg, Store(":memory:"),
                           Notes(Path(tmp.name) / "hk"))
    housekeeper.backend = SweepBackend()
    housekeeper.start_housekeeping(every_sec=0.05)
    dead = housekeeper.gate.open("1.2.3.4")
    dead.created -= remote.QR_TTL + 1
    time.sleep(0.3)
    assert SweepBackend.swept, "엔진 청소가 안 돌았다"
    assert dead.id not in housekeeper.gate.sessions, "죽은 세션이 안 치워졌다"
    housekeeper.server_close()

    # --- 원격 접속: 외부 PC → 폰 승인 → 직접 연결 ---
    import re

    def raw(method, path, payload=None, token=None):
        req = urllib.request.Request(
            base + path, method=method,
            data=None if payload is None else json.dumps(payload).encode(),
            headers={"Content-Type": "application/json",
                     **({"Authorization": f"Bearer {token}"} if token else {})},
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    # 외부 PC가 페이지를 연다 — 인증 없이 QR만 받는다.
    status, html = raw("GET", "/remote")
    assert status == 200 and b"<svg" in html, "QR 페이지가 안 나온다"
    sid = re.search(r"const SID = '([\w-]+)'", html.decode()).group(1)

    # 승인 전에는 아무것도 못 한다.
    assert raw("POST", "/eb/v1/ask", {"text": "볼륨 올려"})[0] == 401
    assert json.loads(raw("GET", f"/eb/v1/remote/status?s={sid}")[1])["state"] == "pending"

    # 폰이 QR을 찍어 승인한다. nonce가 있어야 한다.
    nonce = server.gate.sessions[sid].nonce
    assert raw("POST", "/eb/v1/remote/approve", {"session": sid, "nonce": "틀림"},
               cfg["pair_token"])[0] == 400
    assert raw("POST", "/eb/v1/remote/approve", {"session": sid, "nonce": nonce},
               cfg["pair_token"])[0] == 200

    # 외부 PC가 토큰을 받아 직접 연결한다.
    remote_token = json.loads(raw("GET", f"/eb/v1/remote/status?s={sid}")[1])["token"]
    status, out = raw("POST", "/eb/v1/ask", {"text": "볼륨 올려"}, remote_token)
    assert status == 200, out
    result = json.loads(out)
    assert result["text"] == "볼륨 올렸어" and result["artifact"]

    # 결과물은 외부 PC에서도 내려받을 수 있다.
    status, blob = raw("GET", f"/eb/v1/artifacts/{result['artifact']}", token=remote_token)
    assert status == 200 and "볼륨 올렸어" in blob.decode()

    # 원격은 허용된 경로만. 스킬 승인·설정은 폰과 내 PC에서만 한다.
    assert raw("POST", "/eb/v1/proposals/p1/decision", {"decision": "approve"},
               remote_token)[0] == 401
    assert raw("GET", "/eb/v1/remote/sessions", token=remote_token)[0] == 401
    # 몇 GB를 남의 디스크에 받게 하면 안 된다.
    assert raw("POST", "/eb/v1/models/download", {"key": "qwen3-8b"}, remote_token)[0] == 401
    assert raw("POST", "/eb/v1/models", {"role": "chat", "name": ""}, remote_token)[0] == 401
    # ★ 원격 문은 `/eb/v1/skills` 를 앞머리로 열어 두므로 `skills/propose` 까지 닿는다 — 거기서 막아야 한다.
    assert raw("POST", "/eb/v1/skills/propose",
               {"name": "원격 스킬", "steps": [{"module": "navigate"}]}, remote_token)[0] == 403, \
        "원격 PC 가 스킬 제안을 넣는다"
    assert raw("GET", "/eb/v1/connect/github?path=/user", token=remote_token)[0] in (401, 403), \
        "원격 PC 가 오너가 연결한 계정을 읽는다"
    # 원격 토큰으로 자기 자신을 승인시킬 수 없다.
    s2 = server.gate.open("9.9.9.9")
    assert raw("POST", "/eb/v1/remote/approve",
               {"session": s2.id, "nonce": s2.nonce}, remote_token)[0] == 401

    # 경로를 섞어 넣어도 디스크가 안 열린다.
    assert raw("GET", "/eb/v1/artifacts/../../eb_config.json", token=remote_token)[0] in (400, 404)

    # 끊으면 길이 사라진다.
    assert raw("POST", "/eb/v1/remote/close", {"session": sid}, remote_token)[0] == 200
    assert raw("POST", "/eb/v1/ask", {"text": "볼륨 올려"}, remote_token)[0] == 401

    # 폰이 승인된 스킬을 받아 간다 — 여기서 학습이 실제 동작으로 넘어간다.
    status, got = call("GET", "/eb/v1/skills")
    assert status == 200 and got["skills"][0]["start_tier"] == "pc"

    tmp.cleanup()

    server.shutdown()

    # ★ 설정의 모델 자리에 gguf 가 없으면 exe 옆(사람이 넣는 자리)을 본다.
    #   구운 판에서 설정이 `_internal\models` 를 가리켜 서버·창이 「모델 없음」이었다.
    import tempfile as _tf

    with _tf.TemporaryDirectory() as 빈자리:
        assert _모델자리(빈자리) == str(paths.gguf_dir()), "gguf 없는 자리를 그대로 믿는다"
        (Path(빈자리) / "m.gguf").write_bytes(b"")
        assert _모델자리(빈자리) == 빈자리, "gguf 있는 자리를 버린다"
    assert _모델자리("") == str(paths.gguf_dir())

    # ★ 작업 폴더에 기대지 않는다 — 딴 폴더에서 켜면 결과물 폴더를 거기 만들다 접근 거부로
    #   **아예 안 떴다**(시험 쪽). 기록 자리와 작업 폴더를 **갈라 놓아야** 잡힌다 —
    #   소스로 돌 때는 둘이 같은 자리라 옛 코드도 통과한다.
    import os as _os

    with _tf.TemporaryDirectory() as 기록, _tf.TemporaryDirectory() as 딴데:
        옛기록, 옛자리 = _os.environ.get("VC_DATA"), _os.getcwd()
        _os.environ["VC_DATA"] = 기록
        _os.chdir(딴데)
        try:
            s2 = EBServer(("127.0.0.1", 0), {"pair_token": "t", "backend": {"kind": "local"}},
                          Store(":memory:"), Notes(Path(기록) / "n", index_now=False))
            try:
                assert Path(기록) in s2.artifacts.parents, f"결과물 폴더가 작업 폴더를 따른다: {s2.artifacts}"
                assert not (Path(딴데) / "data").exists(), "작업 폴더에 data 를 만들었다"
            finally:
                s2.server_close()
        finally:
            _os.chdir(옛자리)
            if 옛기록 is None:
                _os.environ.pop("VC_DATA", None)
            else:
                _os.environ["VC_DATA"] = 옛기록
    # ★ **뜻 벡터를 채우는 실은 서버에도 있어야 한다.** 예전에는 화면(`panels.Indexer`)에만
    #   있어서 `--no-ui` 로 띄우면 새 글의 벡터가 영영 안 만들어졌다 — 안 채우는 것은
    #   **조용히** 틀린다(잣대에서 같은 사고로 곁실험 넷이 무너졌다).
    #   정의 한 곳과 부르는 자리 둘, 합쳐 셋이 다 있어야 한다.
    #   구운 판에는 소스가 없다 — 그때는 건너뛴다(없어서 못 재는 것과 재서 틀린 것은 다른 말이다).
    글 = ""
    for 이름 in ("server.py", "eb.py"):
        try:
            글 += Path(__file__).with_name(이름).read_text(encoding="utf-8")
        except OSError:
            글 = ""
            print("  (구운 판이라 벡터 실 검사는 건너뛴다)")
            break
    #   ★★ **세는 검사는 제 몸을 센다.** 처음에 `count("start_embedding(") >= 3` 으로 썼더니
    #   이 검사문 안의 글자까지 세어 **부르는 자리를 지워도 통과했다.** 되돌려 보고서야 알았다.
    #   자리마다 **따로** 센다 — 코드 한 번 + 이 검사문 한 번이라 **둘** 이 바닥이다.
    for 있어야, 까닭 in (
            ("def start_embedding(", "벡터를 채우는 실이 서버에 없다"),
            ("eb.start_embedding()", "창 있는 판이 벡터 실을 안 띄운다"),
            ("server.start_embedding()", "--no-ui 로 띄우면 뜻 벡터가 안 자란다"),
            ("eb.start_consolidate()", "창 있는 판이 정리 실을 안 띄운다"),
            ("server.start_consolidate()", "--no-ui 로 띄우면 메모가 정리되지 않는다"),
            # 사본 실(결정 30) — 안 띄우면 손님으로 골라 놔도 **아무것도 안 받는다**
            ("def start_mirror(", "사본 실이 서버에 없다"),
            ("eb.start_mirror()", "창 있는 판이 사본 실을 안 띄운다"),
            ("server.start_mirror()", "--no-ui 로 띄우면 사본이 안 자란다"),
            # ★★ **자라는 것과 쓰이는 것은 다른 말이다.** 처음엔 이 실의 제 연결에만
            #   임베더를 붙였다 — 벡터는 자라는데 `search` 가 쓰는 `self.notes` 는
            #   `_embed` 가 None 이라 **뜻 검색이 영영 0건**이었다(시험 쪽이 --no-ui 에서 잡음).
            ("self.notes.use_embedder(embed)", "찾는 쪽에 임베더가 안 붙어 뜻 검색이 0건이 된다"),
            # 새로 만든 벡터를 `semantic()` 이 보려면 찾는 쪽 캐시를 비워야 한다.
            ("self.notes._vec_cache = None", "찾는 쪽 캐시를 안 비워 새 벡터가 안 보인다"),
            # 구운 판에는 콘솔이 없다 — print 만으로는 알림이 아무 데도 안 남는다.
            ("report.trail(말)", "알림이 기록 파일에 안 남아 구운 판에서 못 본다"),
            ):
        assert not 글 or 글.count(있어야) >= 2, f"{까닭} ({글.count(있어야)}군데)"

    # ★★ **원격에 열어 둔 길은 다 실재해야 한다.** `/eb/v1/notes` 가 목록에 있었는데
    #   그런 길이 없었다(옛 이름이 남았다) — 나중에 그 이름을 만들면 **의도치 않게
    #   원격에 열린다.** 여기서 목록과 진짜 길을 견준다.
    import remote as _r

    소스 = Path(__file__).read_text(encoding="utf-8", errors="replace")
    for 길 in _r.REMOTE_ALLOWED:
        assert f'"{길}"' in 소스, f"원격에 열어 둔 길이 실재하지 않는다: {길}"

    # ★★ **옛 창고 옮기기 뒤 첫 켜기에 열쇠가 바뀌면 안 된다**(⑦ 실기 2026-09-15). 설정 자리를 불러올 때 박아 두면
    #   옮기기 전 옛 자리를 가리켜, 원본을 지운 뒤 새 열쇠로 옛 자리에 다시 만들었다 — 폰 짝짓기가 풀리고 기록 폴더에 열쇠 파일이 생겼다.
    import os as _os7
    with tempfile.TemporaryDirectory() as _t7:
        _기록7, _앱7 = Path(_t7) / "기록", Path(_t7) / "앱"
        _기록7.mkdir()
        (_기록7 / "eb_config.json").write_text(json.dumps({"pair_token": "옛열쇠-옮기기시험"}), encoding="utf-8")
        _옛7 = {k: _os7.environ.get(k) for k in ("VC_DATA", "VC_STATE")}
        _os7.environ["VC_DATA"], _os7.environ["VC_STATE"] = str(_기록7), str(_앱7)
        try:
            assert "eb_config.json" in paths.기계파일옮기기()["옮김"]
            assert load_config().get("pair_token") == "옛열쇠-옮기기시험", "옮긴 뒤 첫 켜기에 열쇠가 바뀌었다 — 폰 짝짓기가 풀린다"
            assert not (_기록7 / "eb_config.json").exists(), "옮긴 뒤 기록 폴더에 설정(열쇠)이 다시 생겼다"
        finally:
            for _k, _v in _옛7.items():
                if _v is None:
                    _os7.environ.pop(_k, None)
                else:
                    _os7.environ[_k] = _v

    print("server self-check 통과")


if __name__ == "__main__":
    import sys

    if "--check" in sys.argv:
        _self_check()
    else:
        serve()
