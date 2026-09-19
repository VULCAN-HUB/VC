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
    까닭: str = ""
    다음: float = 0.0

    @property
    def 몇개(self) -> int:
        return self.새로 + self.고침 + self.지움


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
        있던 = store.read(제목)
        if 있던 is not None and 있던.body == 몸답["text"]:
            continue                      # 같은 글이면 안 쓴다(파일 시각만 바뀌면 또 바뀐 것으로 보인다)
        store.append(제목, 몸답["text"]) if 있던 is None else store.write(
            _같은꼴(store, 있던, 몸답["text"]))
        결과.새로 += 있던 is None
        결과.고침 += 있던 is not None

    # 메인에서 지운 글은 여기서도 지운다 — 사본이 진짜 사본이 되려면 지움도 따라가야 한다.
    for 것 in 답.get("trashed") or []:
        제목 = str(것.get("title") or "").strip()
        if 제목 and store.read(제목) is not None:
            try:
                store.delete(제목)        # 지난 판은 남는다 — 잘못 지워도 되살릴 수 있다
                결과.지움 += 1
            except Exception:
                pass                      # 잠겨 있으면 다음 번에

    _자국쓰기(where, {**자국, "since": 결과.다음, "when": time.time()})
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

        def 부르기(method, path):
            부른것.append(path)
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
        r5 = 한판(손님, lambda *a: None, 자국)
        assert r5.몇개 == 0 and "못 닿았" in r5.까닭, r5
        assert 손님.read("가") is not None, "못 닿았다고 사본을 지웠다"
    print("mirror self-check 통과")


if __name__ == "__main__":
    import sys

    if "--check" in sys.argv:
        _self_check()
