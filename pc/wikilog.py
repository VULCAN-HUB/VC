"""창고의 **지도**(`index.md`)와 **일지**(`log.md`). 화면은 안 쓴다.

카파시 LLM Wiki 가 위키 옆에 늘 두는 두 장이다.

    index  지금 창고에 무엇이 있나 — 갈래별로 **링크 + 한 줄**
    log    무슨 일이 언제 있었나 — 네 가지 일을 한 줄씩, **덧붙이기만 한다**

오너 볼트도 같은 두 장을 썼다(`index.md` 「vault 전체의 지도」 · `log.md` 「중요한 저장,
ingest, reference, lint 작업이 끝날 때 한 줄씩」). 줄 꼴도 거기 것을 따랐다:

    YYYY-MM-DD HH:mm | 일 | 요약 | 이어진 것

★★ **둘 다 항목으로 안 센다.** 지도는 창고를 비추는 거울이고 일지는 계속 자란다 —
   글로 세면 검색·그래프가 그것들로 덮이고, 일지 한 줄 적을 때마다 「글이 하나 바뀌었다」가 된다.

★ **지도는 바뀌었을 때만 다시 쓴다.** 매번 쓰면 파일 시각이 계속 바뀌어 색인·복제가
  일 없이 돈다(폰과 딴 PC 가 매번 「바뀐 글」로 받아 간다).
"""

from __future__ import annotations

import time
from pathlib import Path

import wiki
from notes import Notes

INDEX = "index.md"
LOG = "log.md"
로그최대 = 4000          # 줄. 넘으면 앞을 버린다 — 20년이면 파일이 감당이 안 된다


def 한줄요약(글, 길이: int = 90) -> str:
    """글 하나를 한 줄로. **표제와 링크 글자는 걷는다** — 지도는 읽으라고 있는 것이다."""
    import re

    몸 = 글.body or ""
    for 줄 in 몸.splitlines():
        말 = 줄.strip()
        if not 말 or 말.startswith(("#", "-", ">", "|", "```")):
            continue
        말 = re.sub(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]", r"\1", 말)      # [[링크]] → 이름
        말 = re.sub(r"\s+", " ", 말).strip()
        if 말:
            return 말 if len(말) <= 길이 else 말[:길이 - 1] + "…"
    return ""


def 지도짓기(창고: Notes) -> str:
    """지금 창고를 비추는 지도 글. 갈래별로 **링크 + 한 줄**."""
    모음: dict[str, list[tuple[str, str]]] = {}
    for 줄 in 창고.conn.execute("SELECT title, kind, path FROM notes ORDER BY title"):
        자리 = Path(줄["path"])
        try:
            첫칸 = 자리.relative_to(창고.root).parts[0]
        except ValueError:
            continue
        if 첫칸 not in (wiki.RAW, wiki.WIKI):
            continue          # 서식·정리 같은 딴 자리는 지도에 안 싣는다
        글 = 창고.read(줄["title"])
        if 글 is None:
            continue
        모음.setdefault(줄["kind"] or wiki.기본갈래, []).append((글.title, 한줄요약(글)))

    글줄 = ["# 이 창고의 지도", "",
          "VC 가 만든다. 손으로 고쳐도 다음에 다시 지어진다 — 고칠 것이 있으면 글을 고친다.", ""]
    if not 모음:
        글줄 += ["아직 아무것도 없다.", ""]
        return chr(10).join(글줄)

    # 갈래 차례는 `wiki.py` 표 그대로 — 사람이 규칙 글에서 본 차례와 같아야 헷갈리지 않는다
    차례 = [k for k in wiki.갈래들 if k in 모음] + sorted(k for k in 모음 if k not in wiki.갈래들)
    글줄 += [f"모두 {sum(len(v) for v in 모음.values())}장 · "
           + " · ".join(f"{k} {len(모음[k])}" for k in 차례), ""]
    for 갈래 in 차례:
        글줄 += [f"## {갈래}  ({len(모음[갈래])})", ""]
        for 제목, 요약 in sorted(모음[갈래]):
            글줄.append(f"- [[{제목}]]" + (f" — {요약}" if 요약 else ""))
        글줄.append("")
    return chr(10).join(글줄)


def 지도쓰기(창고: Notes) -> bool:
    """지도를 다시 짓는다. **바뀌었을 때만 쓴다** — 썼으면 True."""
    어디 = Path(창고.root) / INDEX
    새글 = 지도짓기(창고)
    try:
        if 어디.exists() and 어디.read_text(encoding="utf-8") == 새글:
            return False
        어디.parent.mkdir(parents=True, exist_ok=True)
        어디.write_text(새글, encoding="utf-8")
        return True
    except OSError:
        return False          # 못 써도 창고가 멈출 이유가 없다


def 적기(창고: Notes, 일: str, 요약: str, 이어진것=()) -> bool:
    """일지에 한 줄 **덧붙인다.** 지운 적 없는 기록이라 뒤에만 붙는다.

    `일` 은 `wiki.연산들` 의 이름(모으기·합치기·묻기·살피기)이다.
    """
    어디 = Path(창고.root) / LOG
    줄 = (f"{time.strftime('%Y-%m-%d %H:%M')} | {일} | "
         f"{' '.join((요약 or '').split())}"
         + (" | " + " · ".join(f"[[{t}]]" for t in 이어진것) if 이어진것 else ""))
    try:
        어디.parent.mkdir(parents=True, exist_ok=True)
        있던 = 어디.read_text(encoding="utf-8") if 어디.exists() else ""
        if not 있던:
            있던 = ("# 이 창고의 일지\n\n네 가지 일이 끝날 때 한 줄씩 붙는다 — "
                  "모으기 · 합치기 · 묻기 · 살피기.\n\n"
                  "```text\nYYYY-MM-DD HH:mm | 일 | 요약 | 이어진 것\n```\n\n")
        줄들 = (있던.rstrip() + chr(10) + 줄 + chr(10)).splitlines()
        # 너무 길면 **앞을 버린다.** 최근 것이 쓸모 있고, 머리말은 지키다.
        if len(줄들) > 로그최대:
            머리 = 줄들[:8]
            줄들 = 머리 + ["", f"…(앞 {len(줄들) - 로그최대} 줄 버림)"] + 줄들[-(로그최대 - 10):]
        어디.write_text(chr(10).join(줄들) + chr(10), encoding="utf-8")
        return True
    except OSError:
        return False


def 안세는파일(자리: Path, 뿌리: Path) -> bool:
    """지도·일지인가. 창고 **맨 위**의 그 두 장만 해당한다."""
    try:
        상대 = Path(자리).relative_to(뿌리)
    except ValueError:
        return False
    return 상대.as_posix() in (INDEX, LOG)


def _self_check() -> None:
    import tempfile

    from notes import Note

    with tempfile.TemporaryDirectory() as tmp:
        창고 = Notes(Path(tmp) / "notes")
        # 빈 창고에도 지도는 선다
        assert "아직 아무것도 없다" in 지도짓기(창고)

        창고.write(Note(title="링크 · example.com", body="- https://example.com/a",
                       kind=wiki.원본갈래))
        창고.write(Note(title="온톨로지", body="개념과 관계를 형식으로 적어 둔 것.\n\n"
                                          "원본: [[링크 · example.com]]", kind="개념"))
        창고.write(Note(title="빈 몸", body="# 표제만 있다", kind="메모"))

        지도 = 지도짓기(창고)
        assert "[[온톨로지]]" in 지도 and "[[링크 · example.com]]" in 지도, 지도
        assert "개념과 관계를 형식으로" in 지도, "한 줄 요약이 없다"
        # ★ 표제·목록 줄은 요약으로 안 쓴다 — 「# 표제만 있다」가 요약이면 읽을 것이 없다
        assert "표제만 있다" not in 지도, 지도
        # 갈래 차례는 `wiki.py` 표 그대로
        assert 지도.index("## " + wiki.원본갈래) < 지도.index("## 개념"), "갈래 차례가 표와 다르다"
        assert "모두 3장" in 지도, 지도

        # 바뀌었을 때만 쓴다 — 안 그러면 색인·복제가 일 없이 돈다
        assert 지도쓰기(창고) is True
        assert 지도쓰기(창고) is False, "안 바뀌었는데 또 썼다"
        창고.write(Note(title="새 글", body="몸이다", kind="메모"))
        assert 지도쓰기(창고) is True

        # 일지는 **덧붙이기만** 한다
        assert 적기(창고, "모으기", "링크 하나", ["링크 · example.com"]) is True
        적기(창고, "합치기", "링크 · example.com → 요점")
        글 = (Path(창고.root) / LOG).read_text(encoding="utf-8")
        assert 글.count(" | 모으기 | ") == 1 and 글.count(" | 합치기 | ") == 1, 글
        assert "[[링크 · example.com]]" in 글
        assert 글.startswith("# 이 창고의 일지"), 글[:40]
        적기(창고, "묻기", "무엇을 찾았나")
        글2 = (Path(창고.root) / LOG).read_text(encoding="utf-8")
        assert 글.rstrip() in 글2.rstrip(), "앞에 적은 것이 사라졌다"

        # ★★ **둘 다 항목으로 안 센다** — 세면 검색·그래프가 이것들로 덮인다
        창고.reindex()
        assert 창고.read("index") is None and 창고.read("log") is None, "지도·일지가 항목이 됐다"
        제목들 = {r["title"] for r in 창고.conn.execute("SELECT title FROM notes")}
        assert "index" not in 제목들 and "log" not in 제목들, 제목들

        창고.conn.close()

    print("wikilog self-check 통과")


if __name__ == "__main__":
    import sys

    if "--check" in sys.argv:
        _self_check()
