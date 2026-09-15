"""폰 앱 — PC 서버가 띄우는 웹앱(`GET /app`). 폰에 따로 설치하지 않는다.

    폰 카메라로 설정 창 「폰 연결」의 QR 을 찍는다 → 폰 브라우저가 `http://PC:8765/app#t=열쇠` 를 연다
    → 앱이 열쇠를 폰에 적어 두고 주소에서 지운다 → 그 뒤로는 홈 화면 바로가기로 연다.

첫 판이 하는 일은 둘뿐이다(오너 2026-09-14: 「처음은 AI 가 답하는 것보다 PC 에 저장된 자료를 보고,
앱에서 적은 것이 PC 에 저장되게」):
    보기   PC 창고를 찾고 글을 펼친다     `memory/search` → `memory/note`
    적기   폰에서 적은 것을 PC 창고에      `POST memory` (같은 제목이면 덧붙기)

까닭(추천대로):
- 안드로이드·아이폰을 **한 벌로** 덮는다. 실기·SDK 없이 이 PC 에서 만들고 잰다(크로스플랫폼 방침).
- 프로토콜이 이미 폰↔PC HTTP+JSON 이라 **새 길을 안 판다.**
- 묻기(AI)·원격 승인·폰 중계는 다음 판. 중계·카메라가 필요해지면 그때 네이티브 앱을 짓는다.

★ 막이:
- **열쇠는 주소의 `#` 뒤에만** 싣는다. `#` 뒤는 브라우저가 서버로 안 보내므로 요청줄·로그에 안 남는다.
- 페이지에는 열쇠가 **안 들어 있다**(누구나 `/app` 을 열 수 있다). 자료는 열쇠를 단 API 로만 온다.
- 받은 글은 `textContent` 로만 넣는다 — 창고 글에 `<script>` 가 있어도 폰에서 안 돈다.
- 못 적었으면 친 글을 칸에 그대로 둔다. 바깥에서 아무것도 안 받는다(서버의 CSP 가 막는다).
"""

from __future__ import annotations

import io
import urllib.parse

PORT = 8765          # eb.py 의 `HOST, PORT` 와 같아야 한다 — 자체점검이 대조한다


def app_url(ip: str, port: int = PORT) -> str:
    return f"http://{ip}:{port}/app"


def pair_url(ip: str, token: str, port: int = PORT) -> str:
    """QR 에 담을 주소. 열쇠는 `#t=` 뒤에만 — 서버로 안 간다."""
    return app_url(ip, port) + "#t=" + urllib.parse.quote(token, safe="")


def qr_png(payload: str, scale: int = 6) -> bytes:
    import segno

    buf = io.BytesIO()
    segno.make(payload, error="m").save(buf, kind="png", scale=scale, border=2)
    return buf.getvalue()


def page() -> bytes:
    return PAGE.encode("utf-8")


PAGE = """<!doctype html><html lang="ko"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="theme-color" content="#05080f">
<title>VC</title>
<style>
 *{box-sizing:border-box}
 body{margin:0;background:#05080f;color:#ccf7ff;font:15px/1.6 "Malgun Gothic","Apple SD Gothic Neo",sans-serif;
      padding-bottom:calc(64px + env(safe-area-inset-bottom))}
 header{position:sticky;top:0;background:#05080fee;padding:12px 16px 8px;border-bottom:1px solid rgba(0,217,255,.15)}
 h1{margin:0;font-size:18px;letter-spacing:2px;color:#00d9ff}
 #state{font-size:12px;color:#78899f}
 main{padding:12px 16px}
 [hidden]{display:none!important}
 input,textarea,button{font:inherit;color:inherit}
 input,textarea{width:100%;background:rgba(0,217,255,.05);border:1px solid rgba(0,217,255,.25);
               border-radius:6px;padding:10px;margin:4px 0}
 textarea{min-height:40vh;resize:vertical}
 button{background:rgba(0,217,255,.12);color:#00d9ff;border:1px solid rgba(0,217,255,.45);
        border-radius:6px;padding:9px 16px;margin:4px 0}
 button.quiet{background:none;border-color:rgba(120,137,159,.4);color:#78899f}
 .row{display:flex;gap:8px;align-items:center}.row input{flex:1}
 .card{border-left:2px solid #00d9ff;background:rgba(0,217,255,.04);padding:8px 10px;margin:8px 0}
 .card b{display:block;color:#e6fbff}
 .card small{display:block;color:#78899f}
 .say{white-space:pre-wrap;word-break:break-word}
 .dim{color:#78899f;font-size:13px}
 nav{position:fixed;left:0;right:0;bottom:0;display:flex;background:#070c16;
     border-top:1px solid rgba(0,217,255,.15);padding-bottom:env(safe-area-inset-bottom)}
 nav button{flex:1;margin:0;border:0;border-radius:0;background:none;color:#78899f;padding:14px 0}
 nav button.on{color:#00d9ff;box-shadow:inset 0 2px #00d9ff}
</style>
<header><h1>VC</h1><div id="state">잇는 중…</div></header>
<main>
 <section id="pair" hidden>
  <p class="say">PC 에서 VC 를 켜고 <b>설정 → 폰 연결</b> 의 QR 을 폰 카메라로 찍어 줘.</p>
  <p class="dim">열리면 브라우저 메뉴의 「홈 화면에 추가」로 앱처럼 쓴다. PC·맥과 폰 모두 테일스케일이 켜져 있어야 한다(같은 와이파이면 집 주소로도 된다).</p>
 </section>
 <section id="find">
  <div class="row"><input id="q" placeholder="찾을 말 (비우면 창고 앞머리)" enterkeyhint="search"><button id="go">찾기</button></div>
  <div id="hits"></div>
  <div id="note" hidden><button class="quiet" id="back">← 목록</button><b id="noteTitle"></b>
   <p class="say" id="noteText"></p></div>
 </section>
 <section id="write" hidden>
  <input id="wt" placeholder="제목(비우면 오늘 날짜)">
  <textarea id="wx" placeholder="적을 것 — 같은 제목이 있으면 뒤에 덧붙는다"></textarea>
  <button id="save">PC 에 적기</button> <span class="dim" id="saved"></span>
 </section>
</main>
<nav><button data-tab="find" class="on">보기</button><button data-tab="write">적기</button></nav>
<script>
const $ = id => document.getElementById(id);
const KEY = 'vc_token';
let token = '';
try { token = localStorage.getItem(KEY) || ''; } catch (e) {}
if (location.hash.startsWith('#t=')) {
  token = decodeURIComponent(location.hash.slice(3));
  try { localStorage.setItem(KEY, token); } catch (e) {}
  history.replaceState(null, '', location.pathname);      // 열쇠를 주소창·방문 기록에 안 남긴다
}

function el(tag, cls, text) {                              // 받은 글은 늘 textContent 로
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}

function unpaired(why) {
  token = '';
  try { localStorage.removeItem(KEY); } catch (e) {}
  $('state').textContent = why;
  show('pair');
}

async function api(method, path, body) {
  if (!token) { unpaired('아직 짝을 안 지었어'); return null; }
  let r;
  try {
    r = await fetch(path, {method, headers: {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'},
                           body: body === undefined ? undefined : JSON.stringify(body)});
  } catch (e) {
    $('state').textContent = '컴퓨터에 못 닿았어 — 테일스케일과 VC 가 켜져 있는지 봐 줘';
    return null;
  }
  if (r.status === 401) { unpaired('열쇠가 안 맞아 — QR 을 다시 찍어 줘'); return null; }
  let j = {};
  try { j = await r.json(); } catch (e) {}
  j._status = r.status;
  return j;
}

function show(tab) {
  for (const s of document.querySelectorAll('main section')) s.hidden = s.id !== tab;
  for (const b of document.querySelectorAll('nav button')) b.classList.toggle('on', b.dataset.tab === tab);
}
for (const b of document.querySelectorAll('nav button')) b.onclick = () => show(b.dataset.tab);

async function hello() {
  const j = await api('GET', '/eb/v1/hello');
  if (!j) return;
  const n = j.store && j.store.notes;
  $('state').textContent = n != null ? `PC 에 이어짐 · 창고 ${n}장` : 'PC 에 이어짐';
  find();
}

async function find() {
  const q = $('q').value.trim();
  $('note').hidden = true;
  $('hits').hidden = false;
  $('hits').replaceChildren(el('p', 'dim', '찾는 중…'));
  const j = await api('GET', '/eb/v1/memory/search?k=20&q=' + encodeURIComponent(q));
  if (!j) return;
  const list = j.results || [];
  $('hits').replaceChildren(...(list.length ? [] : [el('p', 'dim', j.error || '안 나왔어 — 말을 바꿔 봐')]));
  if (j.hint) $('hits').append(el('p', 'dim', j.hint));
  for (const r of list) {
    const c = el('div', 'card');
    c.append(el('b', '', r.title), el('span', 'say', r.summary || ''),
             el('small', '', [r.created, r.kind, r.folder].filter(Boolean).join(' · ')));
    c.onclick = () => openNote(r, q);
    $('hits').append(c);
  }
}

async function openNote(r, q) {
  let path = '/eb/v1/memory/note?title=' + encodeURIComponent(r.title);
  if (q) path += '&q=' + encodeURIComponent(q);
  if (r.folder) path += '&folder=' + encodeURIComponent(r.folder);
  const j = await api('GET', path);
  if (!j) return;
  $('noteTitle').textContent = r.title;
  $('noteText').textContent = j.text || j.error || '';
  if (j.cut) $('noteText').append(el('p', 'dim', `(일부만 보였어 — 전체 ${j.full_chars}자)`));
  $('hits').hidden = true;
  $('note').hidden = false;
}
$('back').onclick = () => { $('note').hidden = true; $('hits').hidden = false; };
$('go').onclick = find;
$('q').onkeydown = e => { if (e.key === 'Enter') find(); };

$('save').onclick = async () => {
  const text = $('wx').value.trim();
  if (!text) return;
  const title = $('wt').value.trim() || new Date().toLocaleDateString('sv-SE');   // 2026-09-14 꼴
  $('save').disabled = true;
  const j = await api('POST', '/eb/v1/memory', {title, text});
  $('save').disabled = false;
  if (!j) return;
  if (j._status === 200 || j._status === 201) {        // 새 글은 201, 덧붙기는 200
    $('wx').value = '';
    $('saved').textContent = `PC 의 「${j.saved_as || title}」에 적었어`;
  } else {
    $('saved').textContent = '못 적었어 — ' + (j.error || j._status);       // 친 글은 칸에 그대로 둔다
  }
};

if (token) hello(); else unpaired('아직 짝을 안 지었어');
</script>
</html>"""


def _self_check() -> None:
    import json
    import re
    import tempfile
    import threading
    import urllib.error
    import urllib.request
    from pathlib import Path

    from notes import Notes
    from server import EBServer
    from store import Store

    # 주소 — 열쇠는 # 뒤에만, 글자가 섞여도 깨지지 않게
    주소 = pair_url("192.168.0.5", "a/b+c")
    assert 주소 == "http://192.168.0.5:8765/app#t=a%2Fb%2Bc", 주소
    assert qr_png(주소)[:8] == b"\x89PNG\r\n\x1a\n", "QR 이 PNG 가 아니다"

    # eb.py 의 문 번호와 같은가(소스가 있을 때만 — 구운 판에는 없다)
    eb소스 = Path(__file__).with_name("eb.py")
    if eb소스.is_file():
        찾음 = re.search(r'^HOST, PORT = "[^"]+", (\d+)', eb소스.read_text(encoding="utf-8"), re.M)
        assert 찾음 and int(찾음.group(1)) == PORT, "eb.py 의 PORT 와 어긋났다 — QR 주소가 틀린 문을 가리킨다"

    글 = page().decode()
    assert "src=" not in 글 and "http" not in 글.split("<script>")[1], "바깥에서 뭘 받아오거나 주소를 박았다"
    assert ".innerHTML" not in 글, "받은 글을 innerHTML 로 넣으면 창고 글의 스크립트가 폰에서 돈다"
    assert "history.replaceState" in 글, "열쇠를 주소창에 남긴다"
    assert "j._status === 201" in 글, "새 글(201)을 실패로 보여 준다"
    # 앱이 부르는 길 — 이름이 어긋나면 폰에서 조용히 404 다. 첫 판은 보기·적기만(AI 묻기 없음)
    부르는길 = set(re.findall(r"'(/eb/v1/[a-z/]+)", 글))
    assert 부르는길 == {"/eb/v1/hello", "/eb/v1/memory/search", "/eb/v1/memory/note", "/eb/v1/memory"}, 부르는길

    cfg = {"pair_token": "phone-token",
           "backend": {"kind": "openai_compatible", "base_url": "http://unused/v1"},
           "models": {"chat": "", "vision": "", "stt": "", "voice": ""}}
    tmp = tempfile.TemporaryDirectory()
    pc = EBServer(("127.0.0.1", 0), cfg, Store(":memory:"), Notes(Path(tmp.name) / "notes"))
    threading.Thread(target=pc.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{pc.server_address[1]}"

    def 부름(method, path, body=None, token="phone-token"):
        req = urllib.request.Request(base + path, method=method,
                                     data=None if body is None else json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json",
                                              **({"Authorization": f"Bearer {token}"} if token else {})})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, r.headers, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.headers, e.read()

    try:
        상태, 머리, 몸 = 부름("GET", "/app", token=None)
        assert 상태 == 200 and "text/html" in 머리["Content-Type"], 상태
        assert "phone-token" not in 몸.decode(), "페이지에 열쇠가 들었다"
        assert "default-src 'none'" in (머리["Content-Security-Policy"] or ""), "CSP 가 없다"
        # 열쇠 없이 자료는 못 본다 · 못 적는다
        assert 부름("GET", "/eb/v1/memory/search?q=a", token=None)[0] == 401
        assert 부름("POST", "/eb/v1/memory", {"title": "x", "text": "y"}, token=None)[0] == 401
        # 앱이 쓰는 차례 그대로: 적기 → 같은 제목에 또 적기(덧붙기) → 찾기 → 펼치기
        assert 부름("POST", "/eb/v1/memory", {"title": "폰메모", "text": "주차 B2 기둥 17"})[0] == 201, "새 글이 201 이 아니다 — 앱은 200·201 을 성공으로 본다"
        assert 부름("POST", "/eb/v1/memory", {"title": "폰메모", "text": "출구는 3번"})[0] in (200, 201)
        몸글 = pc.notes.read("폰메모").body
        assert "B2" in 몸글 and "3번" in 몸글, f"두 번째 적기가 첫 글을 덮었다: {몸글}"
        상태, _, 몸 = 부름("GET", "/eb/v1/memory/search?k=20&q=" + urllib.parse.quote("주차"))
        assert 상태 == 200 and any(r["title"] == "폰메모" for r in json.loads(몸)["results"]), 몸[:200]
        상태, _, 몸 = 부름("GET", "/eb/v1/memory/search?k=20&q=")          # 빈 찾기 = 첫 화면 목록
        assert 상태 == 200 and json.loads(몸)["results"], "빈 찾기에 목록이 안 온다 — 첫 화면이 빈다"
        상태, _, 몸 = 부름("GET", "/eb/v1/memory/note?title=" + urllib.parse.quote("폰메모"))
        assert 상태 == 200 and "B2" in json.loads(몸)["text"]
    finally:
        pc.shutdown()
        pc.server_close()
        pc.notes.conn.close()

    # ★★ 폰 전송 대기함 — 같은 client_id 는 한 번만 받는다. 서버를 다시 켜도, 쓰는 사이 꺼졌어도.
    기록 = Path(tmp.name) / "재시작"
    노트 = Notes(기록 / "notes")

    def 켜기():
        s = EBServer(("127.0.0.1", 0), cfg, Store(str(기록 / "eb.db")), 노트)
        threading.Thread(target=s.serve_forever, daemon=True).start()
        return s

    def 보내기(s, 몸글):
        req = urllib.request.Request(f"http://127.0.0.1:{s.server_address[1]}/eb/v1/memory", method="POST",
                                     data=json.dumps(몸글).encode(),
                                     headers={"Content-Type": "application/json", "Authorization": "Bearer phone-token"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def 끄기(s):
        s.shutdown()
        s.server_close()
        s.store.conn.close()

    가 = 켜기()
    글 = {"title": "폰글", "text": "응답이 끊겨도 한 줄", "client_id": "a1b2c3d4e5f6a7b8"}
    assert 보내기(가, 글)[0] == 201
    상태, 답 = 보내기(가, 글)                                  # 응답을 못 받아 다시 보냈다
    assert 상태 == 200 and 답.get("duplicate") is True, (상태, 답)
    끄기(가)
    나 = 켜기()                                                # 서버 재시작
    상태, 답 = 보내기(나, 글)
    assert 상태 == 200 and 답.get("duplicate") is True, f"서버를 다시 켜니 같은 글을 또 받았다: {상태} {답}"
    assert 노트.read("폰글").body.count("응답이 끊겨도 한 줄") == 1, 노트.read("폰글").body
    # 쓰기 시작 표시만 남기고 꺼진 경우 — 글에 이미 들어갔으면 다시 붙이지 않는다
    나.store.client_write_begin("crash-00000001", "폰글")
    노트.append("폰글", "쓰다가 꺼진 줄")
    상태, 답 = 보내기(나, {"title": "폰글", "text": "쓰다가 꺼진 줄", "client_id": "crash-00000001"})
    assert 상태 == 200 and 답.get("duplicate") is True, (상태, 답)
    assert 노트.read("폰글").body.count("쓰다가 꺼진 줄") == 1, "쓰는 사이 꺼진 글이 두 번 붙었다"
    # 쓰기 시작 표시만 있고 글엔 없으면 — 이제 쓴다
    나.store.client_write_begin("crash-00000002", "새폰글")
    assert 보내기(나, {"title": "새폰글", "text": "못 쓰고 꺼졌던 줄", "client_id": "crash-00000002"})[0] == 201
    assert "못 쓰고 꺼졌던 줄" in 노트.read("새폰글").body
    # 같은 제목에 다른 글(다른 id)은 따로 붙는다 — 중복 막이가 정상 글을 삼키면 안 된다
    assert 보내기(나, {**글, "client_id": "b1b2c3d4e5f6a7b8"})[0] == 201
    assert 노트.read("폰글").body.count("응답이 끊겨도 한 줄") == 2
    assert 보내기(나, {**글, "client_id": "짧"})[0] == 400
    assert 보내기(나, {**글, "client_id": 12345678})[0] == 400
    끄기(나)
    노트.conn.close()
    print("phone_app self-check 통과")


if __name__ == "__main__":
    import sys

    if "--check" in sys.argv:
        _self_check()
