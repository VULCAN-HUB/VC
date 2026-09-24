"""대충 쓴 메모에서 서식 칸을 AI 가 짐작한다 — 정리 2겹 (편의 기능 1·2번 · 결정 19).

「오늘 김매니저한테 정수기 vcis-689 받음」처럼 칸 없이 적어도 제품 정리에 들어가게 한다.

★ **원래 메모는 안 고친다.** 짐작은 앱 자리 `vc-짐작.json` 에만 둔다(기록 폴더는 메모만 — 결정 17).
★ **이름이면 바로, 애매하면 확인**(결정 19): 짐작한 제품명이 메모 글에 그대로 있으면 정리에 넣고,
  글에 없는 이름을 지어냈으면 「확인 필요」로만 올린다.
★ 한 번 본 메모(같은 몸)는 다시 안 묻는다. 한 바퀴에 몇 장만 — 2만 장 창고에서 모델이 하루 종일 돌면 안 된다.
★ 모델이 없으면 조용히 아무것도 안 한다(1겹만 돈다).
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Callable

import paths
from notes import Notes, parse_tags

import consolidate

MEMO = "vc-짐작.json"
PER_RUN = 10
# 제품을 주고받은 이야기일 법한 말 — 이것도 없고 #제품 도 없으면 모델에 안 묻는다(값이 든다)
HINT = re.compile(r"받았|받음|수령|입고|보냈|보냄|발송|반납|반송|택배|샘플|제품|업체|매니저")

PROMPT = """너는 메모에서 제품을 주고받은 기록을 뽑는다. 메모에 적힌 것만 쓴다. 지어내지 않는다.
JSON 하나만 답한다. 다른 말은 쓰지 않는다.
제품을 받거나 보낸 이야기가 아니면 {"제품": false} 만 답한다.
맞으면 이 꼴로 답한다(모르는 칸은 빈 글자):
{"제품": true, "제품명": "", "종류": "", "받은날": "", "보낸날": "", "업체": "", "상태": ""}
칸의 뜻:
- 제품명: 그 물건만의 모델 번호·이름(예: vcis-689, ap-12, 갤럭시 S25). 「정수기」「샘플」 같은 흔한 이름은 제품명이 아니다. 메모에 없으면 빈 글자.
- 종류: 무슨 물건인지(예: 정수기, 공기청정기, 카메라). 「택배」「샘플」「박스」는 종류가 아니다.
- 업체: 주고받은 회사나 사람.
- 받은날·보낸날: YYYY-MM-DD. 「오늘」은 메모 날짜, 「어제」는 그 전날. 받은 이야기가 없으면 받은날은 빈 글자.
- 상태: 마지막이 받은 것이면 「보유중」, 보낸 것이면 「보냄」.
예) 메모 날짜 2026-10-01 「김매니저가 정수기 vcis-689 보내줌」 → {"제품": true, "제품명": "vcis-689", "종류": "정수기", "받은날": "2026-10-01", "보낸날": "", "업체": "김매니저", "상태": "보유중"}
예) 메모 날짜 2026-10-08 「vcis-689 택배로 돌려보냄」 → {"제품": true, "제품명": "vcis-689", "종류": "", "받은날": "", "보낸날": "2026-10-08", "업체": "", "상태": "보냄"}
/no_think"""


def _hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def _load(where: Path) -> dict:
    try:
        got = json.loads(where.read_text(encoding="utf-8"))
        return got if isinstance(got, dict) else {}
    except (OSError, ValueError):
        return {}


def _json(answer: str) -> dict | None:
    """모델 답에서 JSON 한 덩이를 꺼낸다. `<think>` 나 말이 앞뒤에 붙어도."""
    answer = re.sub(r"(?s)<think>.*?</think>", "", answer or "")
    m = re.search(r"(?s)\{.*\}", answer)
    if not m:
        return None
    try:
        got = json.loads(m.group(0))
    except ValueError:
        return None
    return got if isinstance(got, dict) else None


def guess_one(chat: Callable[[list[dict]], str], title: str, body: str, day: str) -> dict:
    """한 장을 묻는다. 돌려주는 것: {} (제품 아님) 또는 칸 dict(+ `확실`)."""
    got = _json(chat([
        {"role": "system", "content": PROMPT},
        {"role": "user", "content": f"메모 날짜: {day}\n제목: {title}\n\n{body[:2000]}"},
    ]))
    if not got or got.get("제품") is not True:
        return {}
    칸 = {k: str(got.get(k) or "").strip() for k in ("제품명", "종류", "받은날", "보낸날", "업체", "상태")}
    칸 = {k: v for k, v in 칸.items() if v}
    if not 칸.get("제품명"):
        # 제품 이야기인데 이름을 모른다 — 버리지 않고 「확인 필요」로 올린다
        return {**칸, "제품명": "", "확실": False}
    # ★ 이름이 글에 그대로 있어야 믿는다 — 모델이 지어낸 이름으로 제품이 생기면 목록이 더러워진다
    글 = consolidate._key(title + " " + body)
    # 모델 번호처럼 영문·숫자가 섞인 이름이어야 제품 하나를 가리킨다 — 「공기청정기」 만으로는 어느 것인지 모른다
    칸["확실"] = consolidate._key(칸["제품명"]) in 글 and bool(re.search(r"[0-9A-Za-z]", 칸["제품명"]))
    return 칸


def run(store: Notes, chat: Callable[[list[dict]], str] | None, where: Path | None = None,
        per_run: int = PER_RUN) -> dict[str, dict]:
    """칸 없는 메모를 몇 장 물어 짐작을 쌓고, **지금 유효한 짐작 전부**를 {경로: 칸} 로 돌려준다."""
    where = where or paths.기계자리(MEMO)
    memo = _load(where)
    asked = 0
    rows = store.conn.execute("SELECT path, title, created, body FROM notes ORDER BY mtime DESC").fetchall()
    live: dict[str, dict] = {}
    for path, title, created, body in rows:
        if consolidate.FOLDER in Path(path).parts or consolidate.TAG in parse_tags(body):
            continue
        if "이름" in consolidate.props(body):
            continue            # 사람이 칸을 적었다 — 짐작 안 한다
        if "제품" not in parse_tags(body) and not HINT.search(title + body):
            continue
        지문 = _hash(body)
        old = memo.get(path)
        if old and old.get("지문") == 지문:
            if old.get("칸"):
                live[path] = old["칸"]
            continue
        if chat is None or asked >= per_run:
            continue
        asked += 1
        try:
            칸 = guess_one(chat, title, body, str(created)[:10])
        except Exception:
            continue            # 모델이 한 번 실패해도 다음 바퀴에 다시 본다
        memo[path] = {"지문": 지문, "칸": 칸}
        if 칸:
            live[path] = 칸
    if asked:
        # 사라진 글의 짐작은 버린다
        있는 = {r[0] for r in rows}
        memo = {k: v for k, v in memo.items() if k in 있는}
        try:
            where.parent.mkdir(parents=True, exist_ok=True)
            where.write_text(json.dumps(memo, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError:
            pass
    return live


def _self_check() -> None:
    import tempfile

    from notes import Note

    with tempfile.TemporaryDirectory() as tmp:
        n = Notes(Path(tmp) / "창고")
        n.write(Note(title="대충", body="오늘 김매니저한테 정수기 vcis-689 받음", created="2026-10-01T09:00:00"))
        n.write(Note(title="지어냄", body="샘플 하나 받았다 #제품", created="2026-10-02T09:00:00"))
        n.write(Note(title="장보기", body="우유 달걀"))
        n.write(Note(title="칸 있음", body="- 제품명 : ap-12\n- 받은날 : 2026-09-20", created="2026-09-20T09:00:00"))
        불림: list[str] = []

        def 가짜(messages):
            글 = messages[-1]["content"]
            불림.append(글)
            if "vcis" in 글:
                return '<think>음</think>{"제품": true, "제품명": "vcis-689", "종류": "정수기", "받은날": "2026-10-01", "업체": "김매니저", "상태": "보유중"}'
            if "샘플" in 글:
                return '답: {"제품": true, "제품명": "zz-999", "받은날": "2026-10-02"}'
            return '{"제품": false}'

        memo = Path(tmp) / MEMO
        live = run(n, 가짜, memo)
        assert len(불림) == 2, f"칸 있는 글·힌트 없는 글까지 물었다: {len(불림)}"
        대충 = next(v for k, v in live.items() if k.endswith("대충.md"))
        assert 대충["제품명"] == "vcis-689" and 대충["확실"] is True, 대충
        지어냄 = next(v for k, v in live.items() if k.endswith("지어냄.md"))
        assert 지어냄["확실"] is False, "글에 없는 이름을 믿었다"
        assert guess_one(lambda m: '{"제품": true, "제품명": "공기청정기"}', "샘플", "공기청정기 샘플 받음", "2026-10-15")["확실"] is False, \
            "흔한 이름(코드 없음)을 제품 하나로 믿었다"
        모름 = guess_one(lambda m: '{"제품": true, "제품명": "", "종류": "공기청정기"}', "샘플", "모델명 모름", "2026-10-15")
        assert 모름 and 모름["확실"] is False, "이름 모르는 제품 이야기를 버렸다 — 확인 필요로 올려야 한다"
        # 같은 몸이면 다시 안 묻는다
        run(n, 가짜, memo)
        assert len(불림) == 2, "본 글을 또 물었다"
        # 모델이 없어도 쌓인 짐작은 쓴다
        assert len(run(n, None, memo)) == 2
        # 정리에 들어간다 — 확실한 것은 제품으로, 아닌 것은 확인으로
        prods, unsure = consolidate.gather(n, live)
        assert sorted(p.name for p in prods) == ["ap-12", "vcis-689"], [p.name for p in prods]
        v = next(p for p in prods if p.name == "vcis-689")
        assert v.state == "보유중" and v.who == "김매니저" and any("짐작" in e.what for e in v.events), v.events
        assert any("지어냄" in u for u in unsure), unsure
        # 원래 메모는 그대로
        assert n.read("대충").body.strip() == "오늘 김매니저한테 정수기 vcis-689 받음"
        # 몸이 바뀌면 다시 묻는다
        n.write(Note(title="대충", body="오늘 김매니저한테 정수기 vcis-689 받음. 박스 파손"))
        run(n, 가짜, memo)
        assert len(불림) == 3, "고친 글을 다시 안 물었다"
        assert _json("그냥 말") is None and _json("{깨짐") is None
    print("ai_fill self-check 통과")


if __name__ == "__main__":
    if "--check" in sys.argv:
        _self_check()
