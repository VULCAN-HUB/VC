"""**기계마다 제 창고, 닿으면 서로 본다** — 행성 (오너 2026-09-26/27).

지금까지는 딴 PC 가 붙으면 기록이 한 덩어리로 합쳐졌다. 그래서 그래프만 봐서는
이 글이 맥에서 쓴 건지 윈도우에서 쓴 건지 알 수 없었다.

바꾼 것: **기계마다 제 로고(행성)를 갖고 제 기록만 거느린다.** 닿아 있으면
남의 행성 글도 여기서 그대로 보고 고친다 — 오너의 말로 「어느 PC 에 있는 자료든
연결되어 있다면 어디서 보든 상관없이 동일하게 볼 수 있어야 함」.

## 왜 사본을 받아 둬도 괜찮은가

베끼기가 어려운 까닭은 보통 **양쪽이 다 쓰기** 때문이다. 여기는 **글마다 주인이
하나**다(제 기계). 그래서 규칙 둘이면 충돌이 **구조적으로** 안 난다:

  1. 받아 둔 것은 **읽기용**. 고치면 주인 기계로 보낸다
  2. 주인이 꺼져 있으면 **읽기만** 된다

한 글을 쓰는 쪽이 늘 하나뿐이라 「어느 쪽이 참이냐」를 정할 일이 안 생긴다.

★ 받는 일은 새로 안 짰다 — `mirror.한판` 이 이미 **창고·부르는 법·자국 자리**를
  밖에서 받게 되어 있어서, 이웃마다 그 셋을 갈아 끼우기만 하면 된다.
★ 행성 이름에 **기계 이름을 쓰지 않는다.** 컴퓨터 이름에 사람 이름이 들어 있다
  (전역 규칙). 주소만 쓴다.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import mirror
import paths
from notes import Notes

기본포트 = 8765
부르기제한초 = 20.0        # 남의 기계에 묻고 기다리는 한도


def 안전한이름(주소: str) -> str:
    """주소를 폴더 이름으로. `100.64.0.1` → `100-64-0-1`.

    ★ 콜론이 든 IPv6 는 윈도우에서 폴더 이름이 못 된다 — 그래서 다 바꾼다.
    """
    return re.sub(r"[^0-9a-zA-Z]+", "-", 주소).strip("-") or "모름"


def 자리(주소: str) -> Path:
    """그 행성의 사본이 사는 곳."""
    return paths.state_dir() / "행성" / 안전한이름(주소)


def 창고(주소: str) -> Notes:
    """그 행성의 사본 창고. 색인은 **기계마다 따로** 만든다."""
    곳 = 자리(주소)
    return Notes(곳 / "notes", str(곳 / "색인.db"))


def 사는행성들() -> list[str]:
    """사본이 있는 행성들(폴더 이름). 꺼져 있어도 남아 있다."""
    뿌리 = paths.state_dir() / "행성"
    if not 뿌리.is_dir():
        return []
    return sorted(ㄱ.name for ㄱ in 뿌리.iterdir() if ㄱ.is_dir())


def 부르는이(주소: str, 열쇠: str, 포트: int = 기본포트):
    """그 이웃에게 묻는 함수를 만든다. `mirror.한판` 이 이걸 받아 쓴다."""
    바탕 = f"http://{주소}:{포트}"

    def 부르기(방법: str, 길: str, 바이트: bool = False, 몸=None):
        # ★ 제목에 띄어쓰기·한글이 든다. **그대로 주소에 박으면 안 된다.**
        쪼갬 = urllib.parse.urlsplit(길)
        인자 = urllib.parse.parse_qsl(쪼갬.query, keep_blank_values=True)
        다듬은 = urllib.parse.urlunsplit(
            ("", "", 쪼갬.path, urllib.parse.urlencode(인자), ""))
        요청 = urllib.request.Request(
            바탕 + 다듬은, method=방법,
            data=None if 몸 is None else json.dumps(몸, ensure_ascii=False).encode(),
            headers={"Authorization": f"Bearer {열쇠}",
                     **({} if 몸 is None else {"Content-Type": "application/json"})})
        try:
            with urllib.request.urlopen(요청, timeout=부르기제한초) as 답:
                생것 = 답.read()
        except (urllib.error.URLError, OSError, ValueError):
            return None            # 꺼져 있거나 못 닿는다 — 조용히 넘긴다
        if 바이트:
            return 생것
        try:
            return json.loads(생것.decode()) if 생것 else {}
        except ValueError:
            return None

    return 부르기


def 따라잡기(주소: str, 열쇠: str, 포트: int = 기본포트, 한번에수: int = mirror.한번에):
    """그 행성에서 **바뀐 것만** 받아 사본을 맞춘다.

    ★ 끊겨 있던 동안 바뀐 것도 여기서 따라잡는다 — 자국(`vc-사본.json`)이
      어디까지 받았는지 들고 있어서, 신호를 놓쳐도 다음에 붙을 때 메워진다.
    """
    곳 = 자리(주소)
    곳.mkdir(parents=True, exist_ok=True)
    사본 = 창고(주소)
    try:
        return mirror.한판(사본, 부르는이(주소, 열쇠, 포트), 곳, 한번에수)
    finally:
        try:
            사본.conn.close()      # 이웃마다 열고 닫는다 — 열어 둔 채 쌓이면 샌다
        except Exception:
            pass


def 고치기보내기(주소: str, 열쇠: str, 제목: str, 몸: str, 갈래: str = "",
              포트: int = 기본포트) -> dict:
    """남의 행성 글을 고친다 — **사본이 아니라 주인 기계에 보낸다.**

    ★★ 사본은 **읽기용**이다. 여기서 고쳐 두면 주인 것과 갈라지고, 그 순간부터
       「어느 쪽이 참이냐」를 정해야 한다. 주인에게 보내면 쓰는 쪽이 늘 하나라
       그 물음 자체가 안 생긴다.
    ★★ **사본을 여기서 고치지 않는다.** 주인이 받으면 곧바로 신호를 쏘고,
       우리 귀가 그걸 듣고 받아 온다 — 참은 한 군데서만 흐른다.
    ★ 주인이 꺼져 있으면 **못 고친다고 말한다.** 조용히 사본만 고쳐 두면
      사람은 고쳐진 줄 알고, 주인이 켜지는 순간 제 것이 사라진다.
    """
    답 = 부르는이(주소, 열쇠, 포트)(
        "POST", "/eb/v1/memory",
        몸={"title": 제목, "text": 몸, **({"kind": 갈래} if 갈래 else {})})
    if 답 is None:
        return {"됐나": False, "왜": "그 기계가 꺼져 있거나 안 닿는다 — 켜져 있을 때만 고칠 수 있다"}
    if 답.get("error"):
        return {"됐나": False, "왜": str(답["error"])}
    return {"됐나": True, "왜": ""}


def 지우기보내기(주소: str, 열쇠: str, 제목: str, 포트: int = 기본포트) -> dict:
    """남의 행성 글을 지운다 — 주인 기계에서 지운다(사본은 신호를 듣고 따라온다)."""
    답 = 부르는이(주소, 열쇠, 포트)("POST", "/eb/v1/memory/delete", 몸={"title": 제목})
    if 답 is None:
        return {"됐나": False, "왜": "그 기계가 꺼져 있거나 안 닿는다 — 켜져 있을 때만 지울 수 있다"}
    if 답.get("error"):
        return {"됐나": False, "왜": str(답["error"])}
    return {"됐나": True, "왜": ""}


# 행성 마디의 갈래. 켜져 있으면 색이 붙고, 꺼져 있으면 **무채색으로 떨어진다**
# (`theme.kind_color` 는 모르는 갈래를 그렇게 그린다 — 따로 색을 안 적는다).
갈래 = "행성"
꺼진갈래 = "행성꺼짐"


def 마디키(행성이름: str, 제목: str) -> str:
    """그래프에서 이 글을 가리키는 이름. **`행성/제목`.**

    ★ 제목에는 `/` 가 못 들어간다 — `notes.제목맞춤` 이 전각 `／` 로 바꾼다.
      그래서 남의 글 이름이 내 글과 똑같아도 **한 마디로 합쳐지지 않는다.**
    """
    return f"{행성이름}/{제목}"


def 키풀기(마디: str) -> tuple[str, str]:
    """`행성/제목` 을 (행성이름, 제목) 으로. 내 글이면 ("", 제목)."""
    행성, 사이, 제목 = 마디.partition("/")
    return (행성, 제목) if 사이 else ("", 마디)


def 그릴것(행성이름: str, 한도: int) -> dict:
    """그 행성 사본에서 **그래프 조각**을 뜬다.

    돌려주는 것: `허브`(행성 마디 이름) · `그림`(이은 것) · `갈래` · `매달기`(허브에서
    글로 가는 흐린 선) · `제목`(마디 → 원래 제목).

    ★ **사본이 없어도 행성은 그린다.** 한 번도 못 받았거나 꺼져 있으면 **알맹이 없는
      행성 하나**만 나온다 — 오너의 말로 「안 보인다, 회색 행성으로만」.
    ★ 사본 창고를 **열고 바로 닫는다.** 행성마다 열어 둔 채 쌓으면 샌다
      (`따라잡기` 도 같은 결로 닫는다).
    """
    허브 = 안전한이름(행성이름)
    빈것 = {"허브": 허브, "그림": {허브: []}, "갈래": {허브: 갈래},
          "매달기": {}, "제목": {}}
    if not (자리(허브) / "색인.db").exists():
        return 빈것
    사본 = 창고(허브)
    try:
        고른 = 사본.working_set(한도)
        조각 = 사본.subgraph(고른)
        갈래들 = 사본.kinds_of(고른)
    except Exception:
        return 빈것              # 색인이 깨졌어도 행성은 보여야 한다
    finally:
        try:
            사본.conn.close()
        except Exception:
            pass

    그림: dict[str, list[str]] = {허브: []}
    for 시, 들 in 조각.items():
        그림.setdefault(마디키(허브, 시), []).extend(마디키(허브, ㄱ) for ㄱ in 들)
    return {
        "허브": 허브,
        "그림": 그림,
        "갈래": {허브: 갈래,
               **{마디키(허브, ㄱ): 갈래들.get(ㄱ, "note") for ㄱ in 고른}},
        # 허브에서 제 글로 가는 선. **사람이 그은 선이 아니므로 흐리게** 간다 —
        # 안 매달면 남의 글이 내 구름 속으로 흩어져서 어느 기계 것인지 안 보인다.
        "매달기": {허브: [마디키(허브, ㄱ) for ㄱ in 고른]},
        "제목": {마디키(허브, ㄱ): ㄱ for ㄱ in 고른},
    }


def _self_check() -> None:
    import tempfile

    # 이름 짓기 — 콜론·점이 폴더 이름에 남으면 윈도우에서 못 만든다
    assert 안전한이름("100.64.0.1") == "100-64-0-1"
    assert ":" not in 안전한이름("fd7a:115c:a1e0::1")
    assert 안전한이름("") == "모름"

    옛자리 = paths.state_dir
    곳 = Path(tempfile.mkdtemp())
    paths.state_dir = lambda: 곳
    try:
        assert 사는행성들() == [], "빈 자리인데 행성이 있다"

        # ★★ **제목에 띄어쓰기가 들어간다.** 주소에 그대로 박으면 요청 줄이 깨진다 —
        #   VC 제목은 「카페 단골」처럼 띄어 쓰는 것이 흔하다.
        본것: list[str] = []

        def 가짜서버(방법, 길, 바이트=False, 몸=None):
            본것.append(길)
            return None

        옛열기 = urllib.request.urlopen
        try:
            urllib.request.urlopen = lambda *ㄱ, **ㄴ: (_ for _ in ()).throw(OSError("꺼짐"))
            부르기 = 부르는이("100.64.0.1", "열쇠")
            assert 부르기("GET", "/eb/v1/memory/note?title=카페 단골&full=1") is None, \
                "못 닿는데 무언가를 돌려준다"
        finally:
            urllib.request.urlopen = 옛열기

        # 주소를 제대로 다듬는지 — 요청을 만들어만 보고 본다
        만든것 = {}
        옛요청 = urllib.request.Request

        def 엿보기(주소, **ㄴ):
            만든것["주소"] = 주소
            return 옛요청(주소, **ㄴ)

        urllib.request.Request = 엿보기
        try:
            urllib.request.urlopen = lambda *ㄱ, **ㄴ: (_ for _ in ()).throw(OSError("꺼짐"))
            부르는이("100.64.0.1", "열쇠")("GET", "/eb/v1/memory/note?title=카페 단골&full=1")
        finally:
            urllib.request.Request = 옛요청
            urllib.request.urlopen = 옛열기
        assert " " not in 만든것["주소"], f"띄어쓰기가 주소에 그대로 갔다: {만든것['주소']}"
        assert "full=1" in 만든것["주소"], 만든것["주소"]
        assert "%EC%B9%B4%ED%8E%98" in 만든것["주소"], f"한글을 안 감쌌다: {만든것['주소']}"

        # 못 닿는 이웃은 조용히 넘어간다 — 하나 꺼져 있다고 나머지가 멈추면 안 된다
        urllib.request.urlopen = lambda *ㄱ, **ㄴ: (_ for _ in ()).throw(OSError("꺼짐"))
        try:
            난것 = 따라잡기("100.64.0.9", "열쇠")
        finally:
            urllib.request.urlopen = 옛열기
        assert 난것.까닭, "못 닿았는데 까닭이 비었다"
        assert 사는행성들() == ["100-64-0-9"], 사는행성들()

        # ★★ **한쪽 끝에서 다른 쪽 끝까지 한 번 태운다.** 조각마다 도는 것과
        #   이어 도는 것은 다르다 — 진짜 창고를 세우고, 진짜 문을 흉내 내어
        #   「바뀐 것만 받아 사본에 쌓인다」를 끝까지 본다.
        from notes import Note

        본점자리 = Path(tempfile.mkdtemp())
        본점 = Notes(본점자리 / "notes", ":memory:")
        본점.write(Note(title="카페 단골", body="띄어쓰기 든 제목이다.\n", kind="메모"))
        본점.write(Note(title="긴 글", body="가" * 25000, kind="메모"))

        def 이웃흉내(방법, 길, 바이트=False, 몸=None):
            쪼갬 = urllib.parse.urlsplit(길)
            인자 = urllib.parse.parse_qs(쪼갬.query)
            if 쪼갬.path == "/eb/v1/changes":
                return {"changes": [{"title": "카페 단골", "mtime": 10.0},
                                    {"title": "긴 글", "mtime": 11.0}],
                        "trashed": [], "next_since": 11.0}
            if 쪼갬.path == "/eb/v1/memory/note":
                글 = 본점.read((인자.get("title") or [""])[0])
                if 글 is None:
                    return None
                몸글 = 글.body
                통째 = (인자.get("full") or ["0"])[0] not in ("0", "", "false")
                if not 통째 and len(몸글) > 20000:     # 진짜 문과 같은 규칙
                    return {"text": 몸글[:20000], "cut": True}
                return {"text": 몸글}
            return None

        이웃 = "100.64.0.7"
        자리(이웃).mkdir(parents=True, exist_ok=True)
        사본 = 창고(이웃)
        난것 = mirror.한판(사본, 이웃흉내, 자리(이웃))
        assert (난것.새로, 난것.까닭) == (2, ""), 난것
        for 제목 in ("카페 단골", "긴 글"):
            받은 = 사본.read(제목)
            본 = 본점.read(제목)
            assert 받은 is not None, f"사본에 {제목} 이 없다"
            assert 받은.body.rstrip() == 본.body.rstrip(), \
                f"{제목} 이 원본과 다르다 ({len(받은.body)} / {len(본.body)}자)"
        # ★ 두 번 돌려도 같은 것을 또 안 받는다 — 자국이 어디까지 받았는지 안다
        다시 = mirror.한판(사본, 이웃흉내, 자리(이웃))
        assert (다시.새로, 다시.고침) == (0, 0), f"이미 받은 것을 또 받는다: {다시}"

        # ★★ **고치기는 주인에게 간다 — 사본을 여기서 안 고친다.**
        #   사본을 고쳐 두면 주인 것과 갈라지고, 그 순간부터 「어느 쪽이 참이냐」를
        #   정해야 한다. 주인에게 보내면 쓰는 쪽이 늘 하나라 그 물음이 안 생긴다.
        보낸것: list = []

        def 보내는흉내(방법, 길, 바이트=False, 몸=None):
            보낸것.append((방법, urllib.parse.urlsplit(길).path, 몸))
            return {"ok": True}

        옛부르는이 = globals()["부르는이"]
        globals()["부르는이"] = lambda *ㄱ, **ㄴ: 보내는흉내
        try:
            난것 = 고치기보내기(이웃, "열쇠", "카페 단골", "고친 몸", "메모")
            assert 난것["됐나"], 난것
            assert 보낸것[-1][:2] == ("POST", "/eb/v1/memory"), 보낸것[-1]
            assert 보낸것[-1][2]["title"] == "카페 단골", 보낸것[-1]
            # 사본은 **안 건드린다** — 주인이 신호를 쏘면 그때 받아 온다
            사본2 = 창고(이웃)
            assert 사본2.read("카페 단골").body.rstrip() == "띄어쓰기 든 제목이다.", \
                "주인에게 보내면서 사본을 먼저 고쳤다"
            사본2.conn.close()
            난것 = 지우기보내기(이웃, "열쇠", "카페 단골")
            assert 난것["됐나"] and 보낸것[-1][1] == "/eb/v1/memory/delete", 보낸것[-1]
        finally:
            globals()["부르는이"] = 옛부르는이

        # ★★ **주인이 꺼져 있으면 못 고친다고 말한다.** 조용히 사본만 고쳐 두면
        #   사람은 고쳐진 줄 알고, 주인이 켜지는 순간 제 것이 사라진다.
        urllib.request.urlopen = lambda *ㄱ, **ㄴ: (_ for _ in ()).throw(OSError("꺼짐"))
        try:
            난것 = 고치기보내기(이웃, "열쇠", "카페 단골", "몰래 고친 몸")
        finally:
            urllib.request.urlopen = 옛열기
        assert not 난것["됐나"] and "꺼져" in 난것["왜"], 난것
        사본3 = 창고(이웃)
        assert 사본3.read("카페 단골").body.rstrip() == "띄어쓰기 든 제목이다.", \
            "주인이 꺼졌는데 사본을 몰래 고쳤다"
        사본3.conn.close()

        # ★★ **그려 낼 조각.** 사본이 있어도 화면이 그릴 꼴로 안 나오면 아무것도
        #   안 보인다. 그래서 「받았다」와 따로 **「그릴 수 있다」를 잰다.**
        조각 = 그릴것(이웃, 50)
        허브 = 조각["허브"]
        assert 허브 == "100-64-0-7", 허브
        assert set(조각["제목"]) == {f"{허브}/카페 단골", f"{허브}/긴 글"}, 조각["제목"]
        assert 조각["제목"][f"{허브}/긴 글"] == "긴 글", 조각["제목"]
        assert 조각["갈래"][허브] == 갈래 and 조각["갈래"][f"{허브}/긴 글"] == "메모", 조각["갈래"]
        # ★ 허브에 **매달려** 있어야 한다. 안 매달면 남의 글이 내 구름 속으로
        #   흩어져서 「어느 기계 것인가」가 화면에서 사라진다.
        assert sorted(조각["매달기"][허브]) == sorted(조각["제목"]), 조각["매달기"]
        # ★★ **이름이 내 글과 같아도 다른 마디다.** 그래프는 마디를 이름으로 세므로,
        #   맨 제목을 그대로 쓰면 내 「긴 글」과 남의 「긴 글」이 **한 마디로 합쳐진다** —
        #   그러면 남의 것을 누르고 내 것을 고치게 된다.
        assert "긴 글" not in 조각["그림"] and "긴 글" not in 조각["갈래"], 조각["그림"]
        assert 키풀기(f"{허브}/긴 글") == (허브, "긴 글")
        assert 키풀기("내 글") == ("", "내 글")

        # ★ **한 번도 못 받은 행성도 그려진다** — 알맹이 없는 하나로.
        #   아예 빼면 「어제 저기서 쓴 것이 있었다」는 사실 자체가 화면에서 사라진다.
        #   (`100-64-0-9` 는 위에서 **못 닿아서** 빈 사본만 남은 행성이다.)
        빈행성 = 그릴것("100-64-0-9", 50)
        assert 빈행성["그림"] == {"100-64-0-9": []}, 빈행성["그림"]
        assert not 빈행성["제목"], 빈행성
        assert not 빈행성["매달기"].get("100-64-0-9"), 빈행성["매달기"]
        # 한 번도 이름조차 못 들어 본 행성 — 창고 폴더가 아예 없다
        못본것 = 그릴것("100-64-0-3", 50)
        assert 못본것["그림"] == {"100-64-0-3": []} and not 못본것["제목"], 못본것

        사본.conn.close()
        본점.conn.close()
    finally:
        paths.state_dir = 옛자리

    print("행성 self-check 통과")


if __name__ == "__main__":
    import sys

    if "--check" in sys.argv:
        _self_check()
