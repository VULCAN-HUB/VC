"""살피기(Audit) — 창고가 성한지 본다. **모델도 화면도 안 쓴다.**

카파시 LLM Wiki 의 넷째 일이다(참조 구현은 "Checks index integrity, links, and wiki
health"). 위키는 저절로 자라므로 **스스로 어긋난다** — 가리키는데 없는 글, 아무와도
안 이어진 글, 모아만 두고 안 합친 원본, 지도가 낡은 것.

★★ **여기서는 기계가 확실히 아는 것만 본다.** 모순·낡은 주장처럼 읽어야 아는 것은
   큰 정리(더 좋은 손)에 맡긴다 — 1차가 짐작으로 「어긋났다」고 하면 그 말을 못 믿는다.
   덕분에 **모델이 없어도 돈다.**

★ **고치지 않는다. 보여 주기만 한다.** 위키를 스스로 고치게 하면 사람이 모르는 사이
  글이 바뀐다. 무엇이 어긋났는지 알려 주고 고치는 것은 사람이나 큰 정리가 한다.
"""

from __future__ import annotations

from pathlib import Path

import wiki
import wikilog
from notes import Notes, parse_links, 제목맞춤


def _층(창고: Notes, 자리: str) -> str:
    try:
        첫칸 = Path(자리).relative_to(창고.root).parts[0]
    except (ValueError, IndexError):
        return ""
    return 첫칸 if 첫칸 in (wiki.RAW, wiki.WIKI) else ""


def 살피기(창고: Notes) -> dict[str, list]:
    """창고를 훑어 어긋난 것을 모은다. 갈래마다 목록 하나.

    돌려주는 것(빈 목록이면 성한 것):
      `끊긴링크`  [(글 제목, 가리킨 이름)]  — 가리키는데 그런 글이 없다
      `외톨이`    [제목]                  — 아무도 안 가리키고 아무것도 안 가리킨다
      `안합친원본` [제목]                  — 모아만 두고 요약 쪽이 없다
      `지도밖`    [제목]                  — 지도에 안 실렸다(지도가 낡았다)
      `모르는갈래` [(제목, 갈래)]           — 규칙에 없는 갈래
      `모르는앞머리`[(제목, 이름, 값)]       — 규약에 없는 값(`상태`·`출처`)
    """
    글들, 층of, 갈래of = {}, {}, {}
    for 줄 in 창고.conn.execute("SELECT title, kind, path FROM notes"):
        층 = _층(창고, 줄["path"])
        if not 층:
            continue          # 서식·정리처럼 층 밖에 있는 것은 살피지 않는다
        if 줄["title"] == wiki.가운데항목:
            continue          # 그래프 가운데 항목은 VC 가 만들고 지운다 — 살필 것이 아니다
        글 = 창고.read(줄["title"])
        if 글 is None:
            continue
        글들[글.title] = 글
        층of[글.title] = 층
        갈래of[글.title] = 줄["kind"] or ""

    별칭 = {a: t for a, t in 창고.conn.execute("SELECT alias, title FROM aliases")}

    def 풀기(이름: str) -> str:
        이름 = 제목맞춤(str(이름).split("#")[0].split("|")[0].strip())
        return 이름 if 이름 in 글들 else 별칭.get(이름, "")

    끊긴링크, 가리킨수 = [], {t: 0 for t in 글들}
    나간수 = {t: 0 for t in 글들}
    for 제목, 글 in 글들.items():
        for 가리킨, _ in parse_links(글.body):
            닿은 = 풀기(가리킨)
            if 닿은:
                가리킨수[닿은] = 가리킨수.get(닿은, 0) + 1
                나간수[제목] += 1
            else:
                끊긴링크.append((제목, 제목맞춤(str(가리킨).split("#")[0].split("|")[0].strip())))

    # 외톨이는 **wiki 층만** 본다. 원본은 원래 아무와도 안 이어진 채 들어온다.
    외톨이 = sorted(t for t in 글들
                 if 층of[t] == wiki.WIKI and not 가리킨수.get(t) and not 나간수.get(t))

    # 모아만 두고 안 합친 원본 — 요약 쪽이 없는 것
    import synth

    안합친원본 = sorted(t for t in 글들
                   if 층of[t] == wiki.RAW and synth.요약제목(t) not in 글들)

    # 지도에 실렸나. 지도가 없으면 **전부 지도 밖**이다(아직 한 번도 안 지었다).
    지도 = ""
    지도길 = Path(창고.root) / wikilog.INDEX
    try:
        지도 = 지도길.read_text(encoding="utf-8") if 지도길.exists() else ""
    except OSError:
        지도 = ""
    지도밖 = sorted(t for t in 글들 if f"[[{t}]]" not in 지도)

    모르는갈래 = sorted((t, 갈래of[t]) for t in 글들
                   if 갈래of[t] and not wiki.아는갈래(갈래of[t]))
    모르는앞머리 = []
    for 제목, 글 in 글들.items():
        for 이름, 값들 in wiki.앞머리규약.items():
            값 = str((글.extra or {}).get(이름, "")).strip()
            if 값 and 값 not in 값들:
                모르는앞머리.append((제목, 이름, 값))
    모르는앞머리.sort()

    return {"끊긴링크": sorted(끊긴링크), "외톨이": 외톨이, "안합친원본": 안합친원본,
            "지도밖": 지도밖, "모르는갈래": 모르는갈래, "모르는앞머리": 모르는앞머리}


제목들 = {
    "끊긴링크": "가리키는데 없는 글",
    "외톨이": "아무와도 안 이어진 쪽",
    "안합친원본": "모아만 두고 안 합친 원본",
    "지도밖": "지도에 없는 글",
    "모르는갈래": "규칙에 없는 갈래",
    "모르는앞머리": "규약에 없는 앞머리 값",
}


def 한줄(난것: dict[str, list]) -> str:
    """사람에게 보일 한 줄. 다 성하면 그렇다고 말한다."""
    있는것 = [(제목들[k], len(v)) for k, v in 난것.items() if v]
    if not 있는것:
        return "창고는 성하다 — 어긋난 데가 없어."
    return " · ".join(f"{이름} {수}" for 이름, 수 in 있는것)


def _self_check() -> None:
    import tempfile

    from notes import Note

    with tempfile.TemporaryDirectory() as tmp:
        창고 = Notes(Path(tmp) / "notes")
        # 빈 창고는 성하다
        난것 = 살피기(창고)
        assert all(not v for v in 난것.values()), 난것
        assert "성하다" in 한줄(난것)

        창고.write(Note(title="원본 가", body="- https://a.example/1", kind=wiki.원본갈래))
        창고.write(Note(title="개념 나", body="[[없는 글]] 을 가리킨다", kind="개념"))
        창고.write(Note(title="외톨이 다", body="아무와도 안 이어졌다", kind="메모"))
        창고.write(Note(title="갈래 이상", body="[[개념 나]]", kind="우주선"))
        창고.write(Note(title="옛 갈래 글", body="[[개념 나]]", kind="note"))
        창고.write(Note(title=wiki.가운데항목, body="가운데 항목이다", kind="agent"))
        창고.write(Note(title="앞머리 이상", body="[[개념 나]]", kind="메모",
                       extra={"상태": "몰라요", "출처": "폰"}))

        난것 = 살피기(창고)
        assert ("개념 나", "없는 글") in 난것["끊긴링크"], 난것["끊긴링크"]
        assert "외톨이 다" in 난것["외톨이"], 난것["외톨이"]
        # ★ **원본은 외톨이로 안 센다** — 모은 그대로는 원래 아무와도 안 이어져 있다
        assert "원본 가" not in 난것["외톨이"], 난것["외톨이"]
        assert 난것["안합친원본"] == ["원본 가"], 난것["안합친원본"]
        assert ("갈래 이상", "우주선") in 난것["모르는갈래"], 난것["모르는갈래"]
        assert ("앞머리 이상", "상태", "몰라요") in 난것["모르는앞머리"], 난것["모르는앞머리"]
        # 규약에 있는 값은 안 걸린다
        assert not [x for x in 난것["모르는앞머리"] if x[1] == "출처"], 난것["모르는앞머리"]
        # 지도를 한 번도 안 지었으면 **전부 지도 밖**이다
        # ★ **VC 가 스스로 만드는 것은 안 나무란다** — 가운데 항목과 VC 가 쓰던 옛 갈래
        assert not [x for x in 난것["모르는갈래"] if x[0] == "옛 갈래 글"], 난것["모르는갈래"]
        assert wiki.가운데항목 not in 난것["지도밖"], 난것["지도밖"]
        assert wiki.가운데항목 not in 난것["외톨이"], 난것["외톨이"]
        assert len(난것["지도밖"]) == 6, 난것["지도밖"]
        assert "성하다" not in 한줄(난것) and "가리키는데 없는 글 1" in 한줄(난것), 한줄(난것)

        # 지도를 지으면 지도 밖이 없어진다
        wikilog.지도쓰기(창고)
        assert 살피기(창고)["지도밖"] == [], 살피기(창고)["지도밖"]

        # 요약 쪽을 만들면 「안 합친 원본」에서 빠진다
        import synth

        창고.write(Note(title=synth.요약제목("원본 가"), body="요점.\n\n원본: [[원본 가]]",
                       kind="개념"))
        난것2 = 살피기(창고)
        assert 난것2["안합친원본"] == [], 난것2["안합친원본"]
        # 이어졌으니 원본도 「가리켜진」 것이 된다
        assert "원본 가 요점" not in 난것2["외톨이"], 난것2["외톨이"]

        # ★ **별칭으로 닿는 링크는 끊긴 것이 아니다** — 볼트 링크가 그렇게 이어진다
        창고.write(Note(title="딴 이름 글", body="몸", kind="메모", aliases=["별명"]))
        창고.write(Note(title="별명 부르기", body="[[별명]] 을 가리킨다", kind="메모"))
        끊긴 = {이름 for _, 이름 in 살피기(창고)["끊긴링크"]}
        assert "별명" not in 끊긴, 끊긴

        # ★ **고치지 않는다** — 살피기는 보여 주기만 한다
        전 = 창고.read("개념 나").body
        살피기(창고)
        assert 창고.read("개념 나").body == 전, "살피다가 글을 고쳤다"

        창고.conn.close()

    print("audit self-check 통과")


if __name__ == "__main__":
    import sys

    if "--check" in sys.argv:
        _self_check()
