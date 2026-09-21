"""헤르메스(2단계) — **바이브코딩 관제탑**. 화면도 모델도 안 쓴다.

1단계가 「기억」이라면 2단계는 **그 기억을 일에 쓰는 것**이다. 관제탑이 하는 일 셋:

    차리기   새 프로젝트를 규칙대로 세운다 — 폴더·git·CLAUDE.md·창고의 엔티티 글
    꺼내기   시작할 때 그 프로젝트의 맥락을 묶어 준다 — 결정·오류·작업·공통 규칙
    적립하기 끝날 때 **추린 것만** 남긴다 — 결정·오류·작업

★★ **왜 이 꼴인가.** 창고 글 「바이브 코딩을 잘하는 법」의 1·2번이 「창고부터 뒤진다」와
   「맥락을 다 준다」이고, 「기억과 접기는 다른 것이다」가 **대화 찌꺼기를 창고에 넣지 말라**고
   한다. 관제탑은 그 두 글을 기계로 옮긴 것뿐이다 — 새 방침이 아니다.

★★ **AI 도구가 문으로 부른다**(오너 2026-09-21). 사람이 창을 옮겨 다니면 맥락이 끊긴다.
   그래서 이 파일은 **화면을 모른다** — 서버가 문을 열고, 창은 나중에 그 위에 붙는다.

★ **편집기·실행은 이 판에 없다.** IDE 는 관제탑이 선 뒤에 얹는다(오너 결정).

★ **전역 규칙이 저절로 지켜진다.** 맥 폴더 이름은 영문(한글 경로가 Qt·Flutter 를 죽인 적이
  있다), git 신원은 브랜드 이름, 오너 개인정보는 어디에도 안 쓴다.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import wiki
from notes import Note, Notes

# 새 프로젝트를 두는 자리. 전역 규칙의 「작업물 저장 위치」다 — 바탕화면은 안 쓴다.
기본뿌리 = Path.home() / "projects"

# git 신원. **오너 실명·실이메일을 쓰지 않는다**(전역 규칙) — 공개해도 되는 것은 브랜드뿐이다.
GIT_이름 = "Unknown"
GIT_메일 = "unknown8563@users.noreply.github.com"

# 차릴 때 `CLAUDE.md` 로 실어 갈 **창고의 규칙 글들.** 없는 것은 조용히 건너뛴다.
#   ★★ **규칙을 여기 새로 적지 않는다.** 두 군데 적으면 갈린다 — 오늘만 세 번 밟았다.
#      창고 글이 바뀌면 다음에 차릴 때 따라온다.
#   무엇을 만드느냐의 잣대 / 어떻게 시키느냐의 잣대, 둘을 같이 싣는다.
규칙글들 = ("프로그램 만들 때 지킬 것", "AI 에게 코딩 시킬 때의 네 가지")
공통규칙글 = 규칙글들[0]

# 꺼내 줄 맥락의 분량. 많이 주면 맥락이 차고, 적게 주면 같은 실수를 되풀이한다.
꺼낼개수 = 6
토막길이 = 400


def 영문이름인가(이름: str) -> bool:
    """맥에서 폴더로 쓸 수 있는 이름인가. **영문·숫자·`-`·`_` 만** 받는다.

    ★★ 한글이 든 경로가 남의 도구를 죽인다 — Qt 가 플러그인 경로의 한글을 `?` 로 버려
       창이 안 떴고, Flutter 분석기는 `FormatException` 으로 통째로 터졌다(Dart SDK 쪽이라
       고칠 수도 없다). 그래서 **차릴 때 막는다** — 나중에 옮기면 링크가 다 끊긴다.
    """
    return bool(re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", 이름 or ""))


def 프로젝트글제목(이름: str) -> str:
    return f"프로젝트 · {이름}"


def _git(자리: Path, *인자: str) -> bool:
    """git 한 번. **없거나 실패해도 프로젝트는 선다** — git 은 있으면 좋은 것이지 조건이 아니다."""
    try:
        난것 = subprocess.run(["git", "-C", str(자리), *인자],
                            capture_output=True, text=True, timeout=30)
        return 난것.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def claude_md(이름: str, 한줄: str, 규칙: str = "", 규칙들: "list[tuple[str, str]] | None" = None) -> str:
    """그 프로젝트용 `CLAUDE.md`. **창고의 규칙 글을 그대로 실어 준다.**

    ★ 규칙을 여기 새로 적지 않는다 — 두 군데 적으면 갈린다. 창고 글을 실어 오고,
      창고 글이 바뀌면 다시 차릴 때 따라온다.
    """
    if 규칙들 is None:
        규칙들 = [(공통규칙글, 규칙)] if 규칙.strip() else []
    줄 = [f"# {이름}", ""]
    if 한줄:
        줄 += [한줄.strip(), ""]
    줄 += [
        "이 파일은 **VC 가 차렸다**. 이 프로젝트에서 AI 가 먼저 읽는 글이다.", "",
        "## 일하는 법", "",
        "1. **창고부터 뒤진다.** 이 프로젝트의 `결정`·`오류`·`작업` 을 먼저 찾는다 —",
        "   같은 오류를 두 번 밟지 않으려고 적어 둔 것이다.",
        f"2. **끝나면 창고에 남긴다.** 결정·오류·작업으로 갈래를 붙인다. 창고 글은 `{프로젝트글제목(이름)}` 에 매인다.",
        "3. **대화 원본은 창고에 안 넣는다.** 남길 것은 다음에 같은 일을 할 때 쓸 일머리다.", "",
        "## 이 기계에서 지킬 것", "",
        "- 폴더 이름은 **영문**으로 짓는다 — 한글 경로가 Qt·Flutter 를 죽인 적이 있다.",
        "- 작업물은 바탕화면에 두지 않는다.",
        f"- git 신원은 `{GIT_이름}` 이다. **실명·실이메일·전화·주소·IP 를 코드·주석·커밋 어디에도 쓰지 않는다.**",
        "- 이 맥의 컴퓨터 이름에 실명이 들어 있다 — 호스트명을 적지 않는다(「맥 2호기」로 부른다).", "",
    ]
    for 제목, 몸 in 규칙들:
        if (몸 or "").strip():
            줄 += [f"## {제목}  (창고에서 옮겨 옴)", "", 몸.strip(), ""]
    return "\n".join(줄) + "\n"


def 차리기(창고: Notes, 이름: str, 한줄: str = "", 뿌리: Path | None = None) -> dict:
    """새 프로젝트를 규칙대로 세운다. `{"자리", "만든것", "왜"}`.

    ★ **이미 있으면 안 덮는다.** 차리기는 되돌리기 어려운 일이라, 있는 것을 건드리지 않는다.
    """
    이름 = (이름 or "").strip()
    if not 영문이름인가(이름):
        return {"자리": "", "만든것": [], "왜": "이름은 영문·숫자·-·_ 로 짓는다(맥에서 한글 경로가 도구를 죽인다)"}
    뿌리 = Path(뿌리) if 뿌리 else 기본뿌리
    자리 = 뿌리 / 이름
    if 자리.exists():
        return {"자리": str(자리), "만든것": [], "왜": "이미 있다 — 안 건드린다"}

    만든것 = []
    try:
        자리.mkdir(parents=True)
    except OSError as e:
        return {"자리": str(자리), "만든것": [], "왜": f"폴더를 못 만들었다: {type(e).__name__}"}
    만든것.append("폴더")

    if _git(자리, "init", "-q"):
        _git(자리, "config", "user.name", GIT_이름)
        _git(자리, "config", "user.email", GIT_메일)
        만든것.append("git")

    실은규칙 = [(t, 글.body) for t in 규칙글들
              for 글 in [창고.read(t)] if 글 is not None]
    (자리 / "CLAUDE.md").write_text(
        claude_md(이름, 한줄, 규칙들=실은규칙), encoding="utf-8")
    만든것.append("CLAUDE.md")
    규칙글 = 창고.read(공통규칙글)

    제목 = 프로젝트글제목(이름)
    if 창고.read(제목) is None:
        몸 = [f"**{이름}** — VC 가 차린 프로젝트.", ""]
        if 한줄:
            몸 += [한줄.strip(), ""]
        몸 += [f"- 자리: `{자리}`", "", "## 지금 상태", "", "차렸다. 아직 아무것도 안 만들었다.", ""]
        if 규칙글 is not None:
            몸 += [f"잣대: [[{공통규칙글}]]", ""]
        창고.write(Note(title=제목, body="\n".join(몸), kind="엔티티",
                       extra={"출처": "VC", "상태": "살아있음"}))
        만든것.append("창고 글")
    return {"자리": str(자리), "만든것": 만든것, "왜": ""}


def _토막(글: Note | None) -> str:
    if 글 is None:
        return ""
    몸 = re.sub(r"\s+", " ", (글.body or "").strip())
    return 몸[:토막길이 - 1] + "…" if len(몸) > 토막길이 else 몸


def 꺼내기(창고: Notes, 이름: str, 몇: int = 꺼낼개수) -> dict:
    """시작할 때 줄 맥락. **그 프로젝트에 매인 것만** 고른다.

    ★ 고르는 기준은 **링크**다 — 제목에 이름이 들었는지로 고르면 「PickOne」 을 물었는데
      「PickOne 얘기를 한 번 한 딴 글」까지 딸려 온다. 창고가 이어 둔 것을 믿는다.
      이어진 것이 없으면 그때만 이름으로 찾는다(막 차린 프로젝트가 그렇다).
    """
    제목 = 프로젝트글제목(이름)
    본체 = 창고.read(제목) or 창고.read(이름)
    모은것: list[str] = []
    if 본체 is not None:
        for 쪽, _ in 창고.backlinks(본체.title):
            if 쪽 not in 모은것:
                모은것.append(쪽)
        for 쪽 in 창고.neighbors(본체.title):
            if 쪽 not in 모은것:
                모은것.append(쪽)
    if not 모은것:
        try:
            모은것 = [r["title"] for r in 창고.search(이름, k=몇 * 2)]
        except Exception:
            모은것 = []

    칸: dict[str, list[tuple[str, str]]] = {"결정": [], "오류": [], "작업": [], "그 밖": []}
    for 쪽제목 in 모은것:
        글 = 창고.read(쪽제목)
        if 글 is None or 글.title == (본체.title if 본체 else ""):
            continue
        # ★ 잣대 글은 **아래 잣대 칸에 따로** 나온다 — 여기 또 실으면 같은 것이 두 번이다
        if 글.title in 규칙글들:
            continue
        칸.setdefault(글.kind if 글.kind in 칸 else "그 밖", []).append((글.title, _토막(글)))
    for k in 칸:
        칸[k] = 칸[k][:몇]

    규칙 = 창고.read(공통규칙글)
    줄 = [f"# {이름} — 시작하기 전에", ""]
    if 본체 is not None:
        줄 += [_토막(본체), ""]
    for 칸이름 in ("결정", "오류", "작업", "그 밖"):
        if 칸[칸이름]:
            줄 += [f"## {칸이름}", ""]
            줄 += [f"- **[[{t}]]** — {요}" for t, 요 in 칸[칸이름]] + [""]
    if 규칙 is not None:
        줄 += [f"## 잣대", "", f"[[{공통규칙글}]] 을 따른다.", ""]
    if not any(칸.values()):
        줄 += ["창고에 아직 이 프로젝트 기록이 없다. 끝나면 남겨 두면 다음에 여기 뜬다.", ""]
    return {"프로젝트": 본체.title if 본체 else "", "칸": 칸,
            "규칙": 공통규칙글 if 규칙 is not None else "", "글": "\n".join(줄)}


_갈래표 = {"결정": "결정", "오류": "오류", "작업": "작업"}


def 적립하기(창고: Notes, 이름: str, 결정=(), 오류=(), 작업=()) -> dict:
    """끝날 때 **추린 것만** 남긴다. `{"만든것": [...], "왜": ...}`.

    받는 꼴은 `{"제목": …, "몸": …}` 목록이다. 대화 원본은 안 받는다 —
    창고가 찌꺼기 창고가 되면 꺼내 쓸 수가 없다.
    """
    제목 = 프로젝트글제목(이름)
    본체 = 창고.read(제목) or 창고.read(이름)
    만든것 = []
    for 칸, 것들 in (("결정", 결정), ("오류", 오류), ("작업", 작업)):
        for 것 in 것들 or ():
            쪽제목 = str((것 or {}).get("제목") or "").strip()
            몸 = str((것 or {}).get("몸") or "").strip()
            if not 쪽제목 or not 몸:
                continue
            줄 = [몸, ""]
            if 본체 is not None:
                줄 += [f"프로젝트: [[{본체.title}]]", ""]
            창고.write(Note(title=쪽제목, body="\n".join(줄), kind=_갈래표[칸],
                           extra={"출처": "VC", "상태": "살아있음"}))
            만든것.append(쪽제목)
    if not 만든것:
        return {"만든것": [], "왜": "남길 것이 없다"}
    return {"만든것": 만든것, "왜": ""}


def _self_check() -> None:
    import tempfile

    assert 영문이름인가("RawBaker") and 영문이름인가("zero-base_2")
    # ★★ 한글 이름은 **차릴 때 막는다** — 나중에 옮기면 링크가 다 끊긴다
    assert not 영문이름인가("제로베이스") and not 영문이름인가("2호기") and not 영문이름인가("")
    assert not 영문이름인가("a b") and not 영문이름인가("a/b")

    with tempfile.TemporaryDirectory() as tmp:
        창고 = Notes(Path(tmp) / "notes")
        창고.write(Note(title=공통규칙글, kind="규칙",
                       body="1. 검사를 준다.\n2. 증거를 보인다."))
        창고.write(Note(title=규칙글들[1], kind="규칙",
                       body="생각 먼저 · 단순함 먼저 · 수술하듯 · 목표로 몰기."))
        창고.reindex()
        뿌리 = Path(tmp) / "projects"

        # --- 차리기 ---
        나쁨 = 차리기(창고, "한글이름", 뿌리=뿌리)
        assert 나쁨["만든것"] == [] and "영문" in 나쁨["왜"], 나쁨

        난것 = 차리기(창고, "TestApp", "한 줄 설명", 뿌리=뿌리)
        자리 = Path(난것["자리"])
        assert 자리.is_dir() and "폴더" in 난것["만든것"], 난것
        claude = (자리 / "CLAUDE.md").read_text(encoding="utf-8")
        assert "TestApp" in claude and "한 줄 설명" in claude
        # ★ 공통 규칙을 **실어 온다** — 두 군데 적으면 갈린다
        assert "검사를 준다" in claude, claude[:400]
        # ★ **규칙 글이 둘 다 실린다** — 무엇을 만드느냐/어떻게 시키느냐, 둘 다 잣대다
        assert "목표로 몰기" in claude, claude[-500:]
        for 제목 in 규칙글들:
            assert 제목 in claude, 제목
        # ★★ **오너 개인정보가 들어가면 안 된다.** 브랜드 이름만 나간다.
        assert GIT_이름 in claude and "@" not in claude.split("git 신원")[1][:40]
        창고.reindex()
        본체 = 창고.read(프로젝트글제목("TestApp"))
        assert 본체 is not None and 본체.kind == "엔티티", 본체
        assert f"[[{공통규칙글}]]" in 본체.body

        # git 이 있으면 신원까지 박는다. 없어도 프로젝트는 선다.
        if "git" in 난것["만든것"]:
            이름난것 = subprocess.run(["git", "-C", str(자리), "config", "user.name"],
                                   capture_output=True, text=True)
            assert 이름난것.stdout.strip() == GIT_이름, 이름난것.stdout
            메일난것 = subprocess.run(["git", "-C", str(자리), "config", "user.email"],
                                   capture_output=True, text=True)
            assert 메일난것.stdout.strip() == GIT_메일

        # ★ **이미 있으면 안 덮는다**
        (자리 / "CLAUDE.md").write_text("내가 고친 것\n", encoding="utf-8")
        다시 = 차리기(창고, "TestApp", 뿌리=뿌리)
        assert 다시["만든것"] == [] and "이미 있다" in 다시["왜"], 다시
        assert (자리 / "CLAUDE.md").read_text(encoding="utf-8") == "내가 고친 것\n"

        # --- 꺼내기(아직 기록이 없을 때) ---
        빈것 = 꺼내기(창고, "TestApp")
        assert "아직 이 프로젝트 기록이 없다" in 빈것["글"], 빈것["글"]

        # --- 적립하기 ---
        난것2 = 적립하기(창고, "TestApp",
                      결정=[{"제목": "TestApp — 창을 PyQt5 로", "몸": "이미 쓰던 것이라."}],
                      오류=[{"제목": "TestApp — 한글 경로에서 Qt 가 안 뜸", "몸": "경로를 못 박아 고쳤다."}],
                      작업=[{"제목": "TestApp — 첫 판 만듦", "몸": "창 하나 띄웠다."}])
        assert len(난것2["만든것"]) == 3, 난것2
        창고.reindex()
        assert 창고.read("TestApp — 창을 PyQt5 로").kind == "결정"
        assert 창고.read("TestApp — 한글 경로에서 Qt 가 안 뜸").kind == "오류"
        # ★ 남긴 글은 프로젝트에 **매인다** — 안 매이면 다음에 못 꺼낸다
        assert 프로젝트글제목("TestApp") in 창고.neighbors("TestApp — 첫 판 만듦")

        # 빈 것은 안 남긴다
        assert 적립하기(창고, "TestApp", 결정=[{"제목": "", "몸": "몸만"}])["만든것"] == []

        # --- 꺼내기(기록이 쌓인 뒤) ---
        난것3 = 꺼내기(창고, "TestApp")
        assert 난것3["프로젝트"] == 프로젝트글제목("TestApp")
        assert [t for t, _ in 난것3["칸"]["결정"]] == ["TestApp — 창을 PyQt5 로"], 난것3["칸"]
        assert [t for t, _ in 난것3["칸"]["오류"]] == ["TestApp — 한글 경로에서 Qt 가 안 뜸"]
        assert "## 결정" in 난것3["글"] and "## 오류" in 난것3["글"]
        assert f"[[{공통규칙글}]]" in 난것3["글"]
        # ★ **딴 프로젝트 것이 섞이면 안 된다** — 이름만 스친 글은 안 딸려 온다
        창고.write(Note(title="딴 글인데 TestApp 얘기를 한 번 함", body="TestApp 좋더라", kind="메모"))
        창고.reindex()
        섞임 = [t for 칸 in 꺼내기(창고, "TestApp")["칸"].values() for t, _ in 칸]
        assert "딴 글인데 TestApp 얘기를 한 번 함" not in 섞임, 섞임

        창고.conn.close()

    print("hermes self-check 통과")


if __name__ == "__main__":
    import sys

    if "--check" in sys.argv:
        _self_check()
