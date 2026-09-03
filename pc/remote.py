"""외부 PC에서 내 VC를 쓰는 길 — 폰이 문지기다.

    첫 접속   외부 PC → (QR) → 폰 → 내 서버.   폰이 승인해야 길이 열린다
    그 뒤     외부 PC → 내 서버 직접.          폰은 데이터 경로에 없다
    끊으면    길을 지운다.                     토큰도 세션도 남기지 않는다
    다시 붙을 때마다 QR을 새로 찍는다.          토큰 재사용 없음

폰이 승인 채널인 이유: 폰은 이미 서버와 붙어 있어 따로 인증할 게 없고, 물리적으로
사용자 손에 있다. 외부 PC 화면의 QR을 폰 카메라로 찍는다는 것 자체가 "그 자리에 내가
있다"는 증거다 — 비밀번호를 외부 PC에 입력하는 것보다 안전하다.

지키는 선:

    승인 없이는 아무것도 못 한다      대기 세션은 상태 조회만 되고 그 외 전부 401
    QR은 2분이면 죽는다              찍히지 않은 QR이 화면에 남아도 쓸모없다
    토큰은 처음 쓴 IP에 묶인다        어깨너머로 토큰을 봐도 다른 데선 안 된다
    원격은 읽기·지시·내려받기만       스킬 승인·설정 변경은 폰과 내 PC에서만(결정 18)
    30분 놀면 저절로 끊긴다           외부 PC에 열어두고 자리를 뜨는 게 제일 흔한 사고

**주의**: 이 서버가 외부 PC에서 닿아야 한다. 같은 와이파이면 그대로 되고, 밖에서
쓰려면 공유기 포트포워딩이나 터널이 필요하다. 그건 배포 문제라 코드가 아니라 설정이다.
"""

from __future__ import annotations

import hmac
import json
import secrets
import time
from dataclasses import dataclass, field

QR_TTL = 120  # QR이 살아 있는 시간(초). 짧아야 화면에 남은 QR이 무해하다
IDLE_TTL = 1800  # 마지막 요청 뒤 이만큼 놀면 끊는다
MAX_SESSIONS = 8  # 대기 세션이 무한히 쌓이지 않게

# 원격에서 허용하는 경로. 여기 없는 건 폰과 내 PC에서만 한다(결정 18: 승인 게이트).
REMOTE_ALLOWED = (
    "/eb/v1/hello",
    "/eb/v1/ask",
    "/eb/v1/graph",
    "/eb/v1/notes",
    "/eb/v1/skills",
    "/eb/v1/artifacts",
    "/eb/v1/remote/close",
    "/eb/v1/remote/status",
)


@dataclass
class Session:
    """접속 하나의 수명. 승인 전에는 nonce·code만, 승인 뒤에 token이 붙는다.

    승인 방법이 둘이다. 어느 쪽이든 **사람이 그 자리에 있다**는 증거를 요구한다:

        nonce  QR을 폰 카메라로 찍었을 때만 알 수 있다 (P2P·중계 경로)
        code   외부 PC 화면의 네 자리를 폰에서 눈으로 대조 (폰 중계 경로)

    폰 중계일 때 QR을 못 쓰는 이유: 외부 PC와 폰이 같은 로컬망이라 폰이 서버 노릇을
    하는데, 그러면 QR을 띄우는 쪽이 폰이고 찍을 카메라가 외부 PC에 없다.
    """

    id: str
    nonce: str
    code: str
    created: float
    from_ip: str
    state: str = "pending"  # pending | active | closed
    tries: int = 0  # 코드 대조 실패 횟수. 네 자리는 무차별 대입이 되므로 막는다
    token: str | None = None
    bound_ip: str | None = None  # 토큰을 처음 쓴 곳. 이후 그 IP만 허용한다
    last_seen: float = 0.0
    approved_by: str = ""
    log: list[str] = field(default_factory=list)

    def expired(self, now: float) -> bool:
        if self.state == "pending":
            return now - self.created > QR_TTL
        if self.state == "active":
            return now - (self.last_seen or self.created) > IDLE_TTL
        return True


class RemoteGate:
    """세션 장부. 서버가 이걸 통해 원격 요청을 통과시킬지 정한다."""

    def __init__(self) -> None:
        self.sessions: dict[str, Session] = {}

    # --- 외부 PC 쪽 -----------------------------------------------------

    def open(self, from_ip: str) -> Session:
        """외부 PC가 페이지를 열었다. QR에 담을 세션을 만든다."""
        self.sweep()
        pending = [s for s in self.sessions.values() if s.state == "pending"]
        if len(pending) >= MAX_SESSIONS:
            # 제일 오래된 대기 세션을 버린다. 안 그러면 남이 대기열을 채워 QR을 막는다.
            oldest = min(pending, key=lambda s: s.created)
            self.sessions.pop(oldest.id, None)

        s = Session(
            id=secrets.token_urlsafe(9),
            nonce=secrets.token_urlsafe(12),
            code=f"{secrets.randbelow(10000):04d}",
            created=time.time(),
            from_ip=from_ip,
        )
        self.sessions[s.id] = s
        return s

    def status(self, session_id: str) -> dict:
        """외부 PC가 승인됐는지 물어본다. 토큰은 **한 번만** 넘겨준다."""
        s = self.sessions.get(session_id)
        now = time.time()
        if s is None or s.expired(now):
            self.sessions.pop(session_id, None)
            return {"state": "expired"}
        if s.state != "active":
            return {"state": s.state, "waiting": round(QR_TTL - (now - s.created))}

        out = {"state": "active", "approved_by": s.approved_by}
        if s.token and s.bound_ip is None:
            out["token"] = s.token  # 아직 안 쓴 토큰만 내준다
        return out

    # --- 폰 쪽 ----------------------------------------------------------

    def approve(self, session_id: str, nonce: str, by: str = "폰") -> Session | None:
        """폰이 QR을 찍어 승인했다. nonce가 맞아야 한다 — 세션 번호만으로는 못 연다."""
        s = self.sessions.get(session_id)
        if s is None or s.state != "pending" or s.expired(time.time()):
            return None
        # compare_digest는 비ASCII 문자열을 못 받는다. 바이트로 넘겨야 한다.
        if not hmac.compare_digest(s.nonce.encode(), (nonce or "").encode()):
            return None

        s.state = "active"
        s.token = secrets.token_urlsafe(32)
        s.approved_by = by
        s.last_seen = time.time()
        s.log.append(f"{_stamp()} 폰이 승인")
        return s

    def approve_code(self, code: str, by: str = "폰") -> Session | None:
        """폰 중계 경로. 외부 PC 화면의 네 자리를 폰에서 눈으로 대조해 승인한다.

        네 자리는 짧아서 찍으면 맞는다 — 세션마다 시도 횟수를 막고, 틀리면 그 세션을
        아예 죽인다. 2분 만료와 합치면 실질적으로 한 번 기회다.
        """
        code = (code or "").strip()
        now = time.time()
        for s in list(self.sessions.values()):
            if s.state != "pending" or s.expired(now):
                continue
            if hmac.compare_digest(s.code.encode(), code.encode()):
                return self.approve(s.id, s.nonce, by)
            s.tries += 1
            if s.tries >= 3:
                self.close(s.id, "코드 대조 실패")
        return None

    def deny(self, session_id: str) -> bool:
        return self.close(session_id, "폰이 거절")

    def pending(self) -> list[Session]:
        """폰이 "지금 누가 붙으려 하나"를 본다. 코드는 넘기지 않는다 — 폰은 눈으로 대조한다."""
        self.sweep()
        return [s for s in self.sessions.values() if s.state == "pending"]

    # --- 통과 검사 -------------------------------------------------------

    def check(self, token: str, path: str, from_ip: str) -> Session | None:
        """원격 요청을 통과시킬지 본다. 토큰·경로·IP가 다 맞아야 한다."""
        if not token or not any(path.startswith(p) for p in REMOTE_ALLOWED):
            return None

        now = time.time()
        for s in list(self.sessions.values()):
            if s.state != "active" or not s.token:
                continue
            if not hmac.compare_digest(s.token.encode(), token.encode()):
                continue
            if s.expired(now):
                self.close(s.id, "시간 초과")
                return None
            if s.bound_ip is None:
                s.bound_ip = from_ip  # 처음 쓴 곳에 묶는다
                s.log.append(f"{_stamp()} 연결 시작")
            elif s.bound_ip != from_ip:
                return None  # 토큰이 새 나갔다
            s.last_seen = now
            return s
        return None

    def close(self, session_id: str, why: str = "끊음") -> bool:
        """길을 지운다. 토큰도 세션도 남기지 않는다."""
        s = self.sessions.pop(session_id, None)
        if s is None:
            return False
        s.state = "closed"
        s.token = None
        s.log.append(f"{_stamp()} {why}")
        return True

    def sweep(self) -> int:
        now = time.time()
        dead = [sid for sid, s in self.sessions.items() if s.expired(now)]
        for sid in dead:
            self.close(sid, "시간 초과")
        return len(dead)

    def active(self) -> list[Session]:
        self.sweep()
        return [s for s in self.sessions.values() if s.state == "active"]


def _stamp() -> str:
    return time.strftime("%H:%M:%S")


# --- 외부 PC가 보는 페이지 -------------------------------------------------


def qr_svg(payload: str, scale: int = 6) -> str:
    """QR을 SVG 문자열로. 이미지 파일도, 외부 요청도 없이 페이지에 그대로 박는다."""
    import io

    import segno

    buf = io.BytesIO()  # segno는 SVG도 바이트로 쓴다
    segno.make(payload, error="m").save(buf, kind="svg", scale=scale, dark="#0b1118",
                                        light="#ffffff", border=2, xmldecl=False, svgns=True)
    return buf.getvalue().decode()


def qr_payload(session: Session) -> str:
    """QR에 담는 것. **서버 주소를 넣지 않는다** — 폰은 이미 내 서버를 알고 있고,
    QR이 사진에 찍히거나 어깨너머로 보여도 주소가 새 나가면 안 된다."""
    return json.dumps({"eb": "remote", "s": session.id, "n": session.nonce},
                      ensure_ascii=False, separators=(",", ":"))


def page(session: Session, via_phone: bool = False) -> bytes:
    """대기 화면. 승인되면 스스로 본 화면으로 넘어간다.

    via_phone이면 폰이 중계 중이라 QR을 찍을 카메라가 외부 PC에 없다 — 대신 네 자리를
    크게 띄우고 폰에서 눈으로 대조하게 한다.
    """
    payload = qr_payload(session)
    if via_phone:
        gate = f"""<div class="code">{session.code}</div>
  <p>폰에 뜬 숫자와 같으면 폰에서 승인을 눌러줘.</p>"""
    else:
        gate = f"""<div class="qr">{qr_svg(payload)}</div>
  <p>폰의 VC 앱으로 이 QR을 찍어줘.</p>"""
    html = f"""<!doctype html><html lang="ko"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>VC 원격</title>
<style>
 body{{margin:0;background:#05080f;color:#ccf7ff;font-family:"Malgun Gothic",sans-serif;
      display:flex;min-height:100vh;align-items:center;justify-content:center}}
 .box{{text-align:center;padding:32px}}
 h1{{font-size:20px;letter-spacing:1px;margin:0 0 6px}}
 p{{color:#78899f;font-size:13px;margin:4px 0}}
 .qr{{background:#fff;padding:14px;border-radius:8px;display:inline-block;margin:20px 0}}
 .qr svg{{display:block;width:236px;height:236px}}
 .code{{font-size:64px;letter-spacing:14px;color:#00d9ff;margin:24px 0 12px;
        font-variant-numeric:tabular-nums}}
 #s{{color:#00d9ff;font-size:12px;letter-spacing:1px}}
 #app{{display:none;text-align:left;width:min(760px,92vw)}}
 textarea,button{{font:inherit}}
 #ask{{width:100%;box-sizing:border-box;background:rgba(0,217,255,.05);color:#ccf7ff;
       border:1px solid rgba(0,217,255,.25);border-radius:4px;padding:10px}}
 button{{background:rgba(0,217,255,.1);color:#00d9ff;border:1px solid rgba(0,217,255,.4);
        border-radius:4px;padding:7px 14px;cursor:pointer;margin-top:8px}}
 #out{{white-space:pre-wrap;margin-top:16px;font-size:13px;line-height:1.7}}
 a{{color:#00d9ff}}
</style>
<div class="box" id="wait">
  <h1>VC 원격 접속</h1>
  {gate}
  <p id="s">대기 중…</p>
</div>
<div class="box" id="app">
  <h1>VC</h1>
  <p id="who"></p>
  <input id="ask" placeholder="시켜봐" autocomplete="off">
  <button onclick="send()">보내기</button>
  <button onclick="bye()">연결 끊기</button>
  <div id="out"></div>
</div>
<script>
const SID = {session.id!r};
let token = null;
async function poll() {{
  const r = await fetch(`/eb/v1/remote/status?s=${{SID}}`);
  const j = await r.json();
  if (j.state === 'expired') {{ document.getElementById('s').textContent = 'QR이 만료됐어. 새로고침해줘.'; return; }}
  if (j.state === 'active' && j.token) {{
    token = j.token;
    document.getElementById('wait').style.display = 'none';
    document.getElementById('app').style.display = 'block';
    // 받침 유무로 조사가 갈리므로 붙이지 않는다 — "폰 중계이 승인했어"가 나온다.
    document.getElementById('who').textContent = j.approved_by + '에서 승인했어. 끊으면 이 길은 사라져.';
    return;
  }}
  document.getElementById('s').textContent = `대기 중… ${{j.waiting ?? ''}}초`;
  setTimeout(poll, 1000);
}}
async function api(path, opts = {{}}) {{
  opts.headers = Object.assign({{'Authorization': 'Bearer ' + token,
                                 'Content-Type': 'application/json'}}, opts.headers || {{}});
  return fetch(path, opts);
}}
async function send() {{
  const box = document.getElementById('ask');
  const text = box.value.trim();
  if (!text) return;
  box.value = '';
  const r = await api('/eb/v1/ask', {{method: 'POST', body: JSON.stringify({{text}})}});
  const j = await r.json();
  const out = document.getElementById('out');
  let line = `> ${{text}}\\nVC: ${{j.text || j.error || ''}}`;
  if (j.artifact) line += `  [<a href="/eb/v1/artifacts/${{j.artifact}}?t=${{token}}" download>내려받기</a>]`;
  out.innerHTML = line + '\\n\\n' + out.innerHTML;
}}
async function bye() {{
  await api('/eb/v1/remote/close', {{method: 'POST', body: JSON.stringify({{session: SID}})}});
  token = null;
  document.body.innerHTML = '<div class="box"><h1>끊었어</h1><p>길을 지웠어. 다시 쓰려면 새로고침하고 QR을 다시 찍어줘.</p></div>';
}}
poll();
</script>
</html>"""
    return html.encode()


def _self_check() -> None:
    gate = RemoteGate()

    # 승인 전에는 아무것도 안 된다.
    s = gate.open("10.0.0.9")
    assert gate.status(s.id)["state"] == "pending"
    assert gate.check("아무거나", "/eb/v1/ask", "10.0.0.9") is None

    # nonce가 틀리면 세션 번호를 알아도 못 연다.
    assert gate.approve(s.id, "틀린nonce") is None
    assert gate.approve("없는세션", s.nonce) is None

    # 폰이 승인하면 토큰이 나온다. 토큰은 한 번만 넘겨준다.
    approved = gate.approve(s.id, s.nonce)
    assert approved is not None and approved.token
    token = gate.status(s.id)["token"]
    assert token == approved.token

    # 원격은 허용된 경로만 된다.
    assert gate.check(token, "/eb/v1/ask", "10.0.0.9") is not None
    assert gate.check(token, "/eb/v1/config", "10.0.0.9") is None, "설정까지 열렸다"
    assert gate.check(token, "/eb/v1/proposals/x/decision", "10.0.0.9") is None

    # 토큰은 처음 쓴 IP에 묶인다.
    assert gate.check(token, "/eb/v1/ask", "1.2.3.4") is None, "다른 데서도 됐다"
    assert "token" not in gate.status(s.id), "쓴 토큰을 또 내줬다"

    # 끊으면 길이 사라진다.
    assert gate.close(s.id)
    assert gate.check(token, "/eb/v1/ask", "10.0.0.9") is None
    assert gate.status(s.id)["state"] == "expired"

    # QR은 시간이 지나면 죽는다.
    old = gate.open("10.0.0.9")
    old.created -= QR_TTL + 1
    assert gate.status(old.id)["state"] == "expired"
    assert gate.approve(old.id, old.nonce) is None

    # 붙어 있어도 놀면 끊긴다.
    idle = gate.open("10.0.0.9")
    gate.approve(idle.id, idle.nonce)
    tok2 = gate.status(idle.id)["token"]
    assert gate.check(tok2, "/eb/v1/ask", "10.0.0.9")
    gate.sessions[idle.id].last_seen -= IDLE_TTL + 1
    assert gate.check(tok2, "/eb/v1/ask", "10.0.0.9") is None, "놀아도 안 끊긴다"

    # 대기 세션이 무한히 쌓이지 않는다.
    for _ in range(MAX_SESSIONS + 3):
        gate.open("10.0.0.9")
    assert len([x for x in gate.sessions.values() if x.state == "pending"]) <= MAX_SESSIONS

    # 접속마다 새 QR — 토큰을 다시 쓸 수 없다.
    a = gate.open("10.0.0.9")
    b = gate.open("10.0.0.9")
    assert a.id != b.id and a.nonce != b.nonce

    # --- 폰 중계 경로: 네 자리를 눈으로 대조해 승인한다 ---
    c = gate.open("192.168.43.51")
    assert len(c.code) == 4 and c.code.isdigit()
    assert gate.approve_code("0000" if c.code != "0000" else "1111") is None
    ok = gate.approve_code(c.code)
    assert ok is not None and ok.id == c.id

    # 네 자리는 짧다. 세 번 틀리면 그 세션을 죽인다.
    d = gate.open("192.168.43.51")
    wrong = "0000" if d.code != "0000" else "1111"
    for _ in range(3):
        gate.approve_code(wrong)
    assert gate.status(d.id)["state"] == "expired", "틀려도 세션이 살아 있다"
    assert gate.approve_code(d.code) is None, "죽은 세션이 승인됐다"

    # 폰은 대기 목록을 보되 코드는 못 받는다 — 화면을 눈으로 봐야 한다.
    e = gate.open("192.168.43.51")
    assert e.id in [s.id for s in gate.pending()]

    # 폰 중계 화면에는 QR 대신 네 자리가 뜬다.
    via = page(e, via_phone=True).decode()
    assert e.code in via and "<svg" not in via
    assert e.code not in page(e).decode(), "QR 화면에 코드가 새 나갔다"

    # QR에는 세션과 nonce만 담는다 — 서버 주소가 새 나가면 안 된다.
    payload = json.loads(qr_payload(a))
    assert set(payload) == {"eb", "s", "n"} and payload["s"] == a.id

    # 페이지에 QR이 그대로 박힌다. 외부 요청이 없어야 오프라인에서도 뜬다.
    html = page(a).decode()
    assert "<svg" in html and a.id in html
    assert "src=" not in html and "cdn" not in html, "바깥에서 뭘 받아오고 있다"

    print("remote self-check 통과")


if __name__ == "__main__":
    _self_check()
