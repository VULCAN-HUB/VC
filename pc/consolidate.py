"""흩어진 메모를 정리 글로 모은다 — 1겹, AI 없이 (편의 기능 1·5번 · 결정 19).

오너 목표: 「아무 날에나 대충 메모하거나 사진과 함께 기록했을 때 알아서 깔끔하게 정리」.
예 — 제품을 받고(10/1) · 보내고(10/8) · 다른 업체에서 또 받는다(10/15). 메모는 세 장이지만
지금 가진 것은 한 개다. 그 셋을 **제품마다 한 장**으로 모으고, 전체를 **「제품 보유 목록」 한 장**으로 편다.

1겹은 서식 칸(`- 제품명 : …`)을 읽는다. 대충 쓴 글에서 칸을 짐작하는 것은 2겹(AI)이 채워 넣는다.

★ 정리 글은 **VC 가 다시 쓰는 글**이다. 사람이 고치면 다음 정리 때 덮인다 — 글 머리에 그렇게 적는다.
  덮기 전 판은 `.이력/` 에 남는다(Notes.write). 원래 메모는 절대 안 건드린다.
★ 줄마다 **근거 메모 링크**(`[[원래 글]]`)를 단다 — 정리가 틀렸을 때 사람이 따라가 고친다.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from notes import Note, Notes, parse_attachments, parse_tags, IMAGE_EXT

FOLDER = "_정리"                 # 정리 글이 사는 자리(항목으로 센다 — 사람이 보는 결과물이다)
LIST_TITLE = "제품 보유 목록"
TAG = "제품정리"                 # 정리 글에 붙는 태그 — 입력으로 다시 안 읽는다

_PROP = re.compile(r"^[ \t]*[-*][ \t]+([^:：\n\[\]]{1,24}?)[ \t]*[:：][ \t]*(.*)$", re.M)
_DATE = re.compile(r"(\d{4})\s*[-./년]\s*(\d{1,2})\s*[-./월]\s*(\d{1,2})")

# 사람이 쓰는 여러 이름을 한 칸으로
ALIAS = {
    "이름": ("제품명", "제품", "제품 이름", "모델", "모델명", "품명", "상품명"),
    "종류": ("종류", "분류", "카테고리"),
    "받은날": ("받은날", "받은 날", "입고일", "입고", "수령일", "받음"),
    "보낸날": ("보낸날", "보낸 날", "발송일", "반납일", "반송일", "보냄"),
    "업체": ("업체", "업체명", "보낸 곳", "보낸곳", "거래처", "받은 곳", "보낸 사람", "담당"),
    "상태": ("상태",),
}
_KEY = {a.replace(" ", ""): k for k, names in ALIAS.items() for a in names}

HAVE = "보유중"
GONE = "보냄"


def props(body: str) -> dict[str, str]:
    """`- 키 : 값` 줄을 한 칸 이름으로 읽는다. 같은 칸이 둘이면 뒤엣것."""
    got: dict[str, str] = {}
    for m in _PROP.finditer(body):
        key = _KEY.get(m.group(1).replace(" ", ""))
        if key and m.group(2).strip():
            got[key] = m.group(2).strip()
    return got


def ymd(text: str) -> str:
    """`2026년 10월 1일` · `2026.10.1` → `2026-10-01`. 날짜가 없으면 빈 글."""
    m = _DATE.search(text or "")
    if not m:
        return ""
    y, mo, d = (int(x) for x in m.groups())
    if not (1 <= mo <= 12 and 1 <= d <= 31):
        return ""
    return f"{y:04d}-{mo:02d}-{d:02d}"


def _key(name: str) -> str:
    """묶는 열쇠 — 대소문자·띄어쓰기·밑줄 차이는 같은 제품이다(vcis-689 · VCIS 689)."""
    return re.sub(r"[\s_\-·.]+", "", name).lower()


def _state_word(v: str) -> str:
    v = v.replace(" ", "")
    if any(w in v for w in ("보냄", "보냈", "발송", "반납", "반송", "송부", "작송", "넘김")):
        return GONE
    if any(w in v for w in ("보유", "받음", "받았", "있음", "가지고")):
        return HAVE
    return v


@dataclass
class Event:
    day: str          # YYYY-MM-DD 또는 ""
    what: str         # 받음 · 보냄 · 메모
    who: str
    source: str       # 근거 글 제목


@dataclass
class Product:
    name: str
    kind: str = ""
    who: str = ""
    state: str = ""
    got: str = ""
    sent: str = ""
    images: list[str] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    state_i: int = -1   # 상태 칸을 적은 글의 차례
    move_i: int = -1    # 받음·보냄을 적은 마지막 글의 차례
    move: str = ""

    @property
    def title(self) -> str:
        return f"제품 · {self.name}"


def _is_summary(note: Note, path: str) -> bool:
    return FOLDER in Path(path).parts or TAG in parse_tags(note.body) or note.extra.get("정리") == "VC"


def gather(store: Notes) -> tuple[list[Product], list[str]]:
    """창고를 훑어 제품마다 모은다. (제품들, 확인 필요한 글 제목들)."""
    rows = store.conn.execute("SELECT path, title, created FROM notes ORDER BY created, title").fetchall()
    by: dict[str, Product] = {}
    unsure: list[str] = []
    for i, (path, title, created) in enumerate(rows):
        note = store.read_at(path)
        if note is None or _is_summary(note, path):
            continue
        p = props(note.body)
        tags = parse_tags(note.body)
        if "이름" not in p:
            # 제품 태그는 있는데 이름 칸이 없다 — 짐작하지 않고 확인으로 올린다(이름이면 바로 · 애매하면 확인 — 결정 19)
            if "제품" in tags:
                unsure.append(title)
            continue
        k = _key(p["이름"])
        prod = by.setdefault(k, Product(name=p["이름"]))
        prod.sources.append(title)
        prod.kind = p.get("종류", prod.kind)
        prod.who = p.get("업체", prod.who)
        for a in parse_attachments(note.body):
            if Path(a).suffix.lower() in IMAGE_EXT | {".heic", ".heif"} and a not in prod.images:
                prod.images.append(a)
        got, sent = ymd(p.get("받은날", "")), ymd(p.get("보낸날", ""))
        # 날짜 칸에 「보냈음」처럼 날짜 없이 적었으면 그 글을 쓴 날로
        wrote = str(created)[:10]
        if "받은날" in p:
            prod.events.append(Event(got or wrote, "받음", p.get("업체", ""), title))
            prod.got = got or wrote
            prod.move_i, prod.move = i, HAVE
        if "보낸날" in p:
            prod.events.append(Event(sent or wrote, "보냄", p.get("업체", ""), title))
            prod.sent = sent or wrote
            # 한 글에 받은날·보낸날이 둘 다 있으면 늦은 날이 지금이다
            if not ("받은날" in p and (got or wrote) > (sent or wrote)):
                prod.move_i, prod.move = i, GONE
        if "상태" in p:
            prod.state = _state_word(p["상태"])
            prod.state_i = i
            if "받은날" not in p and "보낸날" not in p:
                prod.events.append(Event(wrote, f"상태 {p['상태']}", p.get("업체", ""), title))
    for prod in by.values():
        prod.events.sort(key=lambda e: e.day)
        # 지금 상태 — 더 늦게 쓴 글이 이긴다. 같은 글이면 사람이 적은 상태 칸이 이긴다.
        if prod.move_i > prod.state_i:
            prod.state = prod.move
        elif not prod.state:
            prod.state = HAVE
    return sorted(by.values(), key=lambda p: p.name.lower()), unsure


def _body(p: Product) -> str:
    rows = [f"| {e.day or '—'} | {e.what}{f' ({e.who})' if e.who else ''} | [[{e.source}]] |" for e in p.events]
    parts = [
        f"> VC 가 메모에서 모아 **다시 쓰는** 글이다. 고치려면 원래 메모를 고친다 — 여기를 고치면 다음 정리 때 덮인다.",
        "",
        f"- 제품명 : {p.name}",
        f"- 종류 : {p.kind}",
        f"- 지금 상태 : {p.state}",
        f"- 업체 : {p.who}",
        f"- 마지막 받은날 : {p.got}",
        f"- 마지막 보낸날 : {p.sent}",
        "",
        f"#{TAG}",
        "",
    ]
    if p.images:
        parts += ["## 사진", ""] + [f"![[{a}]]" for a in p.images] + [""]
    parts += ["## 주고받은 기록", "", "| 날 | 일 | 근거 |", "|---|---|---|"] + rows + [""]
    parts += ["## 근거 메모", ""] + [f"- [[{s}]]" for s in dict.fromkeys(p.sources)] + [""]
    return "\n".join(parts)


def _list_body(prods: list[Product], unsure: list[str]) -> str:
    def table(items: list[Product]) -> list[str]:
        out = ["| 제품 | 종류 | 업체 | 받은날 | 보낸날 |", "|---|---|---|---|---|"]
        out += [f"| [[{p.title}\\|{p.name}]] | {p.kind} | {p.who} | {p.got} | {p.sent} |" for p in items]
        return out
    have = [p for p in prods if p.state == HAVE]
    gone = [p for p in prods if p.state == GONE]
    other = [p for p in prods if p.state not in (HAVE, GONE)]
    parts = ["> VC 가 메모에서 모아 **다시 쓰는** 목록이다. 고치려면 원래 메모를 고친다.", "",
             f"지금 가진 것 **{len(have)}** · 보낸 것 **{len(gone)}**" + (f" · 확인 필요 **{len(unsure)}**" if unsure else ""),
             "", f"#{TAG}", "", f"## 보유중 ({len(have)})", ""] + table(have) + [""]
    if other:
        parts += [f"## 그 밖 상태 ({len(other)})", ""] + table(other) + [""]
    parts += [f"## 보낸 것 ({len(gone)})", ""] + table(gone) + [""]
    if unsure:
        parts += ["## 확인 필요 — 제품명 칸이 없다", "", "메모에 `- 제품명 : …` 을 적으면 다음 정리 때 들어간다.", ""]
        parts += [f"- [[{t}]]" for t in unsure] + [""]
    return "\n".join(parts)


def run(store: Notes) -> dict:
    """정리 글을 새로 쓴다. 바뀐 글만 쓴다(같으면 안 건드려 이력·동기화가 안 흔들린다)."""
    prods, unsure = gather(store)
    folder = store.root / FOLDER
    written = []

    def put(title: str, body: str, sub: str, pinned: bool = False) -> None:
        at = folder / sub / f"{title.replace('/', '∕')}.md"
        old = store.read_at(at) if at.exists() else None
        if old is not None and old.body.strip() == body.strip():
            return
        at.parent.mkdir(parents=True, exist_ok=True)
        store.write(Note(title=title, body=body, kind="thing" if sub else "note", pinned=pinned,
                         extra={"정리": "VC"}), at=at)
        written.append(title)

    if not prods and not unsure:
        return {"products": 0, "written": []}
    for p in prods:
        put(p.title, _body(p), "제품")
    put(LIST_TITLE, _list_body(prods, unsure), "", pinned=True)
    return {"products": len(prods), "have": sum(p.state == HAVE for p in prods),
            "unsure": len(unsure), "written": written}


def _self_check() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        n = Notes(Path(tmp) / "창고")
        # 오너 예: 받고 → 보내고 → 다른 업체에서 또 받음. 날짜 적는 법도 제각각.
        n.write(Note(title="정수기 받음", body="- 제품명 : vcis-689\n- 종류 : 정수기\n- 받은날 : 2026년 10월 1일\n- 업체 : 김매니저\n\n![[정수기.jpg]]\n#제품", created="2026-10-01T09:00:00"))
        n.write(Note(title="정수기 보냄", body="- 제품명 : VCIS 689\n- 보낸날 : 2026.10.8\n- 업체 : 김매니저", created="2026-10-08T09:00:00"))
        n.write(Note(title="정수기 다시", body="- 모델 : vcis-689\n- 받은 날 : 2026-10-15\n- 보낸 곳 : 박대리", created="2026-10-15T09:00:00"))
        n.write(Note(title="청정기", body="- 제품명 : ap-12\n- 종류 : 공기청정기\n- 받은날 : 2026-09-20\n- 상태 : 반납했음", created="2026-09-20T09:00:00"))
        n.write(Note(title="대충 쓴 것", body="오늘 뭐 하나 받았음 #제품", created="2026-10-02T09:00:00"))
        n.write(Note(title="장보기", body="- 우유\n- 달걀"))
        # 상태 칸을 적은 뒤, 더 늦게 「보낸날」만 적은 메모가 오면 보낸 것이다
        n.write(Note(title="의자 받음", body="- 제품명 : bb-2\n- 상태 : 보유중", created="2026-09-01T09:00:00"))
        n.write(Note(title="의자 보냄", body="- 제품명 : bb-2\n- 보낸날 : 2026-09-05", created="2026-09-05T09:00:00"))

        prods, unsure = gather(n)
        assert [p.name for p in prods] == ["ap-12", "bb-2", "vcis-689"], [p.name for p in prods]
        assert prods[1].state == GONE, "상태 칸 뒤에 늦게 보낸 것을 안 따른다"
        v = prods[2]
        assert v.state == HAVE and v.who == "박대리" and v.got == "2026-10-15" and v.sent == "2026-10-08", v
        assert [e.what for e in v.events] == ["받음", "보냄", "받음"], v.events
        assert v.images == ["정수기.jpg"] and v.kind == "정수기", v
        assert prods[0].state == GONE, prods[0].state
        assert unsure == ["대충 쓴 것"], unsure

        got = run(n)
        assert got["products"] == 3 and got["have"] == 1 and got["unsure"] == 1, got
        목록 = n.read(LIST_TITLE)
        assert 목록 is not None and 목록.pinned, "목록이 없거나 고정이 안 됐다"
        assert "지금 가진 것 **1**" in 목록.body and "[[제품 · vcis-689\\|vcis-689]]" in 목록.body, 목록.body
        장 = n.read("제품 · vcis-689")
        assert "[[정수기 보냄]]" in 장.body and "- 지금 상태 : 보유중" in 장.body and "![[정수기.jpg]]" in 장.body, 장.body
        # 정리 글은 다시 입력으로 안 읽힌다 — 두 번 돌려도 제품이 안 는다
        assert run(n)["written"] == [], "안 바뀌었는데 또 쓴다"
        assert len(gather(n)[0]) == 3
        # 원래 메모는 그대로
        assert "![[정수기.jpg]]" in n.read("정수기 받음").body
        # 새 메모가 오면 반영
        n.write(Note(title="정수기 또 보냄", body="- 제품명 : vcis-689\n- 상태 : 발송", created="2026-10-20T09:00:00"))
        run(n)
        assert "- 지금 상태 : 보냄" in n.read("제품 · vcis-689").body
        assert "지금 가진 것 **0**" in n.read(LIST_TITLE).body
        assert ymd("2026년 13월 1일") == "" and ymd("받음") == ""
    print("consolidate self-check 통과")


if __name__ == "__main__":
    if "--check" in sys.argv:
        _self_check()
