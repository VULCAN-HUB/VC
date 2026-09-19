"""메인 VC 의 글을 이 PC 에 **사본으로** 쌓는다 (오너 결정 30).

오너 2026-09-20:
  · 메인은 내가 지정한 PC 하나. 다른 PC 에서도 **똑같이 검색·쓰기·수정**한다.
  · 쓴 것은 **반드시 메인에도** 남는다.
  · 메인이 **복구 불가능**해지면 다른 PC 의 자료가 살아 있어 **새 메인이 될 수 있어야** 한다.

그래서 손님은 캐시가 아니라 **사본**이다 — 글을 통째로, **옵시디언이 그대로 읽는 파일 꼴**로 쌓는다.
사본이 있으면 메인이 죽어도 자료가 살고, 설정에서 「이 VC 를 메인으로」 하나로 승격된다(옮길 게 없다).

받는 법: 메인의 `GET /eb/v1/changes?since=` 가 **그때 뒤로 바뀐 것**만 준다 →
글마다 `GET /eb/v1/memory/note` 로 몸을 받아 제 창고에 쓴다. 마지막으로 받은 자리를 적어 둔다.

★ **손님이 받은 글을 메인으로 되돌려 보내지 않는다.** 받은 것을 다시 보내면 끝없이 돈다 —
  손님이 보내는 것은 **사람이 이 PC 에서 쓴 것**뿐이다(대기함 길, 결정 28 의 지문 규칙 그대로).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

MEMO = "vc-사본.json"          # 어디까지 받았나
한번에 = 200


@dataclass
class 받은것:
    새로: int = 0
    고침: int = 0
    지움: int = 0
    첨부: int = 0
    까닭: str = ""
    다음: float = 0.0

    @property
    def 몇개(self) -> int:
        return self.새로 + self.고침 + self.지움


@dataclass
class 보낸것:
    보냄: int = 0
    붙임: int = 0          # 부딪혀 「둘 다 남김」으로 간 것
    못보냄: int = 0
    까닭: str = ""


def 지문(글: str) -> str:
    """글의 지문. 메인에 되돌려 보낼 때 「내가 본 판」을 가리키는 데 쓴다(결정 28).

    ※ 메인이 견주는 것은 **제 파일의 몸 그대로**다 — 여기서 다듬으면 늘 「부딪혔다」가 된다.
    """
    import hashlib

    return hashlib.sha256((글 or "").encode("utf-8")).hexdigest()


def _고르게(글: str) -> str:
    """견주기용으로만 다듬는다. **줄끝·꼬리 빈 줄은 저장하며 달라진다** —
    그것 때문에 받아 쌓은 글이 「내가 고친 글」로 잡혀 도로 메인에 갔다(자체점검에서 잡았다)."""
    return (글 or "").replace("\r\n", "\n").rstrip()


def _첨부받기(store, 부르기, 몸: str) -> int:
    """글이 끼운 사진·파일도 받아 둔다. **사본은 사진까지 사본이어야** 메인이 죽어도 온전하다."""
    from notes import EMBED_RE, is_attachment

    받음 = 0
    for m in EMBED_RE.finditer(몸 or ""):
        이름 = m.group(1).strip()
        if not is_attachment(이름) or store.attachment_path(이름) is not None:
            continue                      # 이미 있으면 다시 안 받는다
        바이트 = 부르기("GET", f"/eb/v1/attach?name={이름}", True)
        if not 바이트:
            continue                      # 그 파일만 건너뛴다 — 다음 번에 다시 걸린다
        꼬리 = ("." + 이름.rsplit(".", 1)[-1]) if "." in 이름 else ".bin"
        줄기 = 이름.rsplit(".", 1)[0]
        저장 = store.save_attachment(바이트, 꼬리, 줄기)
        받음 += 1
        if 저장 != 이름:
            # 이름이 바뀌면 글이 가리키는 그림이 안 열린다 — 조용히 넘어가면 안 된다.
            store.append("_VC기록/사본 알림", f"- 첨부 이름이 바뀌었다: {이름} → {저장}")
    return 받음


def _자국(where: Path) -> dict:
    try:
        j = json.loads(where.read_text(encoding="utf-8"))
        return j if isinstance(j, dict) else {}
    except (OSError, ValueError):
        return {}


def _자국쓰기(where: Path, 값: dict) -> None:
    try:
        where.parent.mkdir(parents=True, exist_ok=True)
        where.write_text(json.dumps(값, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass        # 못 적어도 이번 받기는 이미 끝났다 — 다음에 조금 더 받을 뿐이다


def 한판(store, 부르기, where: Path, 한번에수: int = 한번에) -> 받은것:
    """한 번 받아 온다. `부르기(method, path)` 는 메인에 묻는 함수(서버 응답 dict 또는 None).

    ※ 주소·열쇠는 부르는 쪽이 쥔다 — 여기서는 **무엇을 받아 어떻게 쌓을지**만 안다(시험하기 쉽게).
    """
    자국 = _자국(where)
    받은지문: dict[str, str] = dict(자국.get("받은지문") or {})
    뒤로 = float(자국.get("since") or 0)
    답 = 부르기("GET", f"/eb/v1/changes?since={뒤로}&limit={한번에수}")
    if not 답:
        return 받은것(까닭="메인에 못 닿았어", 다음=뒤로)

    결과 = 받은것(다음=float(답.get("next_since") or 뒤로))
    for 것 in 답.get("changes") or []:
        제목 = str(것.get("title") or "").strip()
        if not 제목:
            continue
        몸답 = 부르기("GET", f"/eb/v1/memory/note?title={제목}")
        if not 몸답 or not isinstance(몸답.get("text"), str):
            continue                      # 그 글만 건너뛴다 — 다음 번에 다시 걸린다
        받은몸 = 몸답["text"]
        있던 = store.read(제목)
        # ★ 받은 판의 **지문**을 적어 둔다 — 나중에 이 PC 에서 고쳐 보낼 때 「내가 본 판」으로 쓴다
        #   (결정 28: 그 사이 메인이 바뀌었으면 덮지 않고 둘 다 남긴다).
        받은지문[제목] = {"raw": 지문(받은몸), "norm": 지문(_고르게(받은몸))}
        if 있던 is not None and 있던.body == 받은몸:
            continue                      # 같은 글이면 안 쓴다(파일 시각만 바뀌면 또 바뀐 것으로 보인다)
        store.append(제목, 받은몸) if 있던 is None else store.write(
            _같은꼴(store, 있던, 받은몸))
        결과.새로 += 있던 is None
        결과.고침 += 있던 is not None
        결과.첨부 += _첨부받기(store, 부르기, 받은몸)

    # 메인에서 지운 글은 여기서도 지운다 — 사본이 진짜 사본이 되려면 지움도 따라가야 한다.
    for 것 in 답.get("trashed") or []:
        제목 = str(것.get("title") or "").strip()
        if 제목 and store.read(제목) is not None:
            try:
                store.delete(제목)        # 지난 판은 남는다 — 잘못 지워도 되살릴 수 있다
                결과.지움 += 1
            except Exception:
                pass                      # 잠겨 있으면 다음 번에

    _자국쓰기(where, {**자국, "since": 결과.다음, "when": time.time(), "받은지문": 받은지문})
    return 결과


def 보내기(store, 부르기, where: Path, 한번에수: int = 50) -> 보낸것:
    """**이 PC 에서 사람이 쓴 것**을 메인으로 보낸다(결정 30 ④).

    ★★ 어떻게 「내가 쓴 것」과 「받은 것」을 가리나 — **받을 때 적어 둔 지문**과 견준다.
      몸이 그때 받은 그대로면 내가 쓴 게 아니다(받아서 쌓은 것이다) → 안 보낸다.
      안 그러면 받은 글을 도로 보내고, 그것이 또 바뀐 것으로 잡혀 **끝없이 돈다.**

    보낼 때는 「내가 본 판」의 지문을 함께 싣는다 — 그 사이 메인이 바뀌었으면 메인이
    **덮지 않고 둘 다 남긴다**(결정 28). 여기서 이기고 지는 것을 정하지 않는다.
    """
    자국 = _자국(where)
    받은지문: dict[str, str] = dict(자국.get("받은지문") or {})
    보낸뒤로 = float(자국.get("sent_since") or 0)
    결과 = 보낸것()
    줄들 = store.conn.execute(
        "SELECT title, mtime FROM notes WHERE mtime > ? ORDER BY mtime LIMIT ?",
        (보낸뒤로, 한번에수)).fetchall()
    마지막 = 보낸뒤로
    for r in 줄들:
        제목, 때 = r["title"], float(r["mtime"])
        쪽 = store.read(제목)
        if 쪽 is None:
            마지막 = max(마지막, 때)
            continue
        적힌 = 받은지문.get(제목) or {}
        if isinstance(적힌, str):          # 옛 자국(지문 하나만 적던 때)
            적힌 = {"raw": 적힌, "norm": ""}
        if 적힌.get("norm") == 지문(_고르게(쪽.body)):
            마지막 = max(마지막, 때)      # 받아서 쌓은 그대로다 — 되돌려 보내지 않는다
            continue
        답 = 부르기("POST", "/eb/v1/memory", False,
                  {"title": 제목, "text": 쪽.body, "mode": "replace",
                   "base_hash": 적힌.get("raw", "")})
        if not 답:
            결과.못보냄 += 1
            결과.까닭 = 결과.까닭 or "메인에 못 닿았어"
            break                          # 차례를 지킨다 — 하나 막히면 뒤도 멈춘다
        결과.보냄 += 1
        결과.붙임 += 1 if 답.get("merged") == "appended" else 0
        # 이제 이것이 「메인도 아는 판」이다. 메인은 제 꼴로 저장하므로 raw 는 비워 두고
        # (다음 받기에서 채워진다) 견주기용 지문만 갱신한다 — 안 그러면 또 보낸다.
        받은지문[제목] = {"raw": "", "norm": 지문(_고르게(쪽.body))}
        마지막 = max(마지막, 때)
    _자국쓰기(where, {**자국, "sent_since": 마지막, "받은지문": 받은지문})
    return 결과


def _같은꼴(store, 있던, 새몸: str):
    """있던 글의 갈래·고정 따위는 그대로 두고 **몸만** 갈아 끼운다."""
    from notes import Note

    return Note(title=있던.title, body=새몸, kind=있던.kind, pinned=있던.pinned,
                id=있던.id, created=있던.created, aliases=list(있던.aliases or []),
                extra=dict(있던.extra or {}))


def _self_check() -> None:
    import tempfile

    from notes import Note, Notes

    with tempfile.TemporaryDirectory() as tmp:
        손님 = Notes(Path(tmp) / "손님창고", str(Path(tmp) / "손님.db"))
        자국 = Path(tmp) / MEMO

        메인글 = {"가": "가의 몸", "나": "나의 몸"}
        지운것: list[str] = []
        부른것: list[str] = []

        def 부르기(method, path, 바이트=False, 몸=None):
            부른것.append(path)
            if 바이트:
                return None              # 시험에는 첨부가 없다
            if path.startswith("/eb/v1/changes"):
                뒤로 = float(path.split("since=")[1].split("&")[0])
                바뀜 = [{"title": t, "mtime": 10.0 + i} for i, t in enumerate(메인글)
                       if 10.0 + i > 뒤로]
                return {"changes": 바뀜, "trashed": [{"title": t} for t in 지운것],
                        "next_since": max([c["mtime"] for c in 바뀜], default=뒤로)}
            if path.startswith("/eb/v1/memory/note"):
                제목 = path.split("title=")[1]
                return {"text": 메인글.get(제목, "")} if 제목 in 메인글 else None
            return None

        # ① 처음 받으면 둘 다 새로 생긴다
        r = 한판(손님, 부르기, 자국)
        assert (r.새로, r.고침, r.지움) == (2, 0, 0), r
        assert 손님.read("가").body.strip() == "가의 몸"

        # ② 바뀐 게 없으면 아무 일도 안 한다 — 같은 것을 다시 쓰지 않는다
        r2 = 한판(손님, 부르기, 자국)
        assert r2.몇개 == 0, r2
        assert "since=11.0" in 부른것[-1], 부른것[-1]      # 받은 자리부터 이어서 묻는다

        # ③ 메인에서 고치면 사본도 고쳐진다 — 갈래·고정은 그대로
        손님.write(Note(title="가", body="가의 몸", kind="결정", pinned=True))
        메인글["가"] = "가의 몸 · 고침"
        _자국쓰기(자국, {"since": 0})
        r3 = 한판(손님, 부르기, 자국)
        assert r3.고침 >= 1, r3
        쪽 = 손님.read("가")
        assert "고침" in 쪽.body and 쪽.kind == "결정" and 쪽.pinned, (쪽.kind, 쪽.pinned)

        # ④ 메인에서 지우면 사본에서도 지워진다(지난 판은 남는다)
        지운것.append("나")
        _자국쓰기(자국, {"since": 0})
        r4 = 한판(손님, 부르기, 자국)
        assert r4.지움 == 1 and 손님.read("나") is None, (r4, 손님.read("나"))
        assert any("나" == t for t, *_ in 손님.trashed()), "지운 글의 지난 판이 없다"

        # ⑤ 메인에 못 닿으면 **까닭을 말하고** 아무것도 안 망친다
        r5 = 한판(손님, lambda *a, **k: None, 자국)
        assert r5.몇개 == 0 and "못 닿았" in r5.까닭, r5
        assert 손님.read("가") is not None, "못 닿았다고 사본을 지웠다"
        # --- 이 PC 에서 쓴 것만 메인으로 보낸다(결정 30 ④) ---
        보낸것들: list[dict] = []
        메인응답 = {"title": "", "mode": "append"}

        def 보내는부르기(method, path, 바이트=False, 몸=None):
            if method == "POST" and path == "/eb/v1/memory":
                보낸것들.append(몸)
                return dict(메인응답)
            return 부르기(method, path, 바이트, 몸)

        # ★ 받아서 쌓은 것은 **안 보낸다** — 보내면 그것이 또 바뀐 것으로 잡혀 끝없이 돈다
        _자국쓰기(자국, {**_자국(자국), "sent_since": 0})
        b1 = 보내기(손님, 보내는부르기, 자국)
        assert 보낸것들 == [], [x.get("title") for x in 보낸것들]
        assert b1.보냄 == 0, b1

        # 사람이 이 PC 에서 고치면 그것만 보낸다 — 「내가 본 판」의 지문을 함께
        손님.append("가", "이 PC 에서 보탠 줄")
        b2 = 보내기(손님, 보내는부르기, 자국)
        assert b2.보냄 == 1 and 보낸것들[-1]["title"] == "가", (b2, 보낸것들)
        assert 보낸것들[-1]["base_hash"], "내가 본 판을 안 실었다 — 메인이 덮어쓰기를 막을 수 없다"
        assert "보탠 줄" in 보낸것들[-1]["text"]

        # 한 번 보낸 것은 다시 안 보낸다
        보낸것들.clear()
        assert 보내기(손님, 보내는부르기, 자국).보냄 == 0, 보낸것들

        # 부딪혀 「둘 다 남김」으로 가면 그렇게 센다
        손님.append("가", "또 보탠 줄")
        메인응답 = {"title": "가", "mode": "append", "merged": "appended"}
        b3 = 보내기(손님, 보내는부르기, 자국)
        assert b3.보냄 == 1 and b3.붙임 == 1, b3

        # 메인에 못 닿으면 **자리를 안 넘긴다** — 다음에 그것부터 다시 보낸다
        손님.append("가", "못 보낼 줄")
        b4 = 보내기(손님, lambda *a, **k: None, 자국)
        assert b4.못보냄 == 1 and "못 닿았" in b4.까닭, b4
        보낸것들.clear()
        b5 = 보내기(손님, 보내는부르기, 자국)
        assert b5.보냄 == 1 and "못 보낼 줄" in 보낸것들[-1]["text"], (b5, 보낸것들)

    print("mirror self-check 통과")


if __name__ == "__main__":
    import sys

    if "--check" in sys.argv:
        _self_check()
