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


def 맡기기(창고: Notes, 프로젝트: str, 지시: str, 손: str = "claude",
        제한초: int = 0, 뿌리: Path | None = None, 멈춤=None, 손물건=None) -> dict:
    """**남의 에이전트에게 맡긴다.** 돌리고 · 적립하고 · 스킬까지 제안한다.

    `{"돌린것", "적립", "스킬제안", "사람말"}`.

    ★★ 여기가 2단계의 한가운데다. 클로드 코드·Codex 는 이미 껍데기를 다 갖췄으니
       우리는 **맥락을 주고, 한 일을 재고, 창고에 남긴다.**
    ★ **자동으로 되돌리지 않는다.** 돌리기 전부터 고쳐져 있던 파일이 있을 수 있다 —
      되돌릴지는 사람이 정한다(`agentcli` 가 그것을 갈라 준다).
    """
    import agentcli

    돌림 = agentcli.돌리기(프로젝트, 지시, 손, 뿌리=뿌리, 멈춤=멈춤, 손물건=손물건,
                       **({"제한초": 제한초} if 제한초 else {}))
    return 돌린뒤(창고, 프로젝트, 지시, 돌림)


def 돌린뒤(창고: Notes, 프로젝트: str, 지시: str, 돌림: dict) -> dict:
    """이미 돌린 결과를 **창고에 남기고 스킬을 제안한다.**

    ★★ `맡기기` 에서 갈라 두는 까닭: 창은 느린 부름을 **딴 실**에서 돌리는데,
       창고 쓰기까지 거기서 하면 같은 색인을 두 실이 만진다. 느린 일은 실에서,
       **창고 쓰기는 창에서** 한다.
    """
    import agentcli
    import wikilog

    잴것 = {"프로젝트": 프로젝트, "지시": 지시, "돌린것": 돌림}
    잴것["적립"] = {"만든것": []}
    잴것["스킬제안"] = {}
    if not 돌림.get("됐나"):
        # ★ **탈난 것도 남긴다.** 무엇을 시켰는데 왜 안 됐는지가 다음에 쓸모 있다.
        제목 = f"{프로젝트} — 맡겼는데 안 됐다: {지시[:40]}"
        잴것["적립"] = 적립하기(창고, 프로젝트, 오류=[{
            "제목": 제목,
            "몸": f"손: {돌림.get('손')} · 까닭: {돌림.get('왜') or '모름'}\n\n"
                 f"마지막 말: {돌림.get('끝말') or '(없음)'}"}])
        wikilog.적기(창고, "적립", f"맡기기 실패 — {프로젝트}: {돌림.get('왜') or ''}"[:120])
        잴것["사람말"] = agentcli.사람말(돌림)
        return 잴것

    바뀐 = 돌림.get("바뀐파일") or []
    if 바뀐:
        잴것["적립"] = 적립하기(창고, 프로젝트, 작업=[{
            "제목": f"{프로젝트} — {지시[:46]}",
            "몸": f"{돌림.get('손')} 에게 맡겨 {len(바뀐)}개를 고쳤다 "
                 f"({돌림.get('든시간')}초).\n\n"
                 f"바뀐 파일: {' · '.join(바뀐[:10])}"}])
        wikilog.적기(창고, "적립", f"맡기기 — {프로젝트}: {' · '.join(바뀐[:3])}"[:120])
        # ★★ 한 바퀴 돌았으니 **스킬로 뽑아 제안**한다(네 기둥의 둘째).
        import skillgen

        뽑은것 = skillgen.뽑기(창고, 프로젝트, 지시, 쓴파일=바뀐)
        잴것["스킬제안"] = {"사람말": skillgen.사람말(뽑은것), "왜": 뽑은것["왜"],
                       "겹침": 뽑은것["겹침"], "스킬": 뽑은것["스킬"]}
    잴것["사람말"] = agentcli.사람말(돌림)
    return 잴것


리뷰틀 = """너는 방금 난 코드 고침을 **검토**한다. 고치지 마라 — 읽고 말만 한다.

시킨 일: {지시}

바뀐 파일: {파일들}

차이:
```diff
{차이}
```

이렇게 답해라(짧게, 한국어로):
1. **맞나** — 시킨 일을 했나. 안 한 것이 있나.
2. **탈** — 깨질 자리·빠진 자리. 없으면 「없다」.
3. **판정** — `좋다` 또는 `고쳐야 한다` 한 낱말로 끝맺어라.
"""


def 볼말(돌림: dict) -> str:
    """손이 한 말 중 **사람이 읽을 것**. 두 자리에서 쓰니 여기 하나만 둔다.

    ★★ 날것(`나온말`)을 그대로 쓰면 창고의 검토 자리에 토큰 셈이 적힌 JSON 덩이가
       들어앉는다(실기 · 2026-09-24). 손이 껍데기를 벗겨 `읽을말` 에 담아 준다.
    ★ 옛 결과엔 `읽을말` 이 없을 수 있으니 날것으로 **되짚는다** — 말이 사라지진 않게.
    """
    것 = 돌림 or {}
    return ((것.get("읽을말") or "").strip() or (것.get("나온말") or "").strip()
            or (것.get("끝말") or ""))


def 협업돌리기(프로젝트: str, 지시: str, 짓는손: str = "claude", 보는손: str = "codex",
          제한초: int = 0, 뿌리: Path | None = None, 멈춤=None,
          짓는물건=None, 보는물건=None) -> dict:
    """둘을 **돌리기만** 한다 — 창고는 안 만진다. `{"지음", "봄"}`.

    ★★ 창고 쓰기를 여기 넣으면 안 된다. 창은 이것을 **딴 실**에서 부르는데, 같은
       색인을 두 실이 만지면 엉킨다(맡기기를 그렇게 갈라 놓은 까닭과 같다).
    """
    import agentcli

    더 = {"제한초": 제한초} if 제한초 else {}
    지음 = agentcli.돌리기(프로젝트, 지시, 짓는손, 뿌리=뿌리, 멈춤=멈춤,
                       손물건=짓는물건, **더)
    잰것 = {"지음": 지음, "봄": {}}

    # ★★ **바뀐 것이 없으면 보는 손을 안 부른다** — 볼 것이 없는데 부르면 값만 든다
    바뀐 = 지음.get("바뀐파일") or []
    if 지음.get("됐나") and 바뀐:
        말 = 리뷰틀.format(지시=지시, 파일들=" · ".join(바뀐[:10]),
                        차이=(지음.get("차이") or "")[:20000])
        잰것["봄"] = agentcli.돌리기(프로젝트, 말, 보는손, 뿌리=뿌리, 멈춤=멈춤,
                                손물건=보는물건, 읽기전용=True, **더)
    return 잰것


def 협업뒤(창고: Notes, 프로젝트: str, 지시: str, 잰것: dict) -> dict:
    """돌린 결과를 **창고에 적는다.** 창에서는 창 실이 이것을 부른다.

    `{"지음", "봄", "적립", "스킬제안", "사람말"}`.
    """
    잴것 = {"지음": (잰것 or {}).get("지음") or {}, "봄": (잰것 or {}).get("봄") or {},
          "적립": {"만든것": []}, "스킬제안": {}}
    난것 = 돌린뒤(창고, 프로젝트, 지시, 잴것["지음"])
    잴것["적립"] = 난것.get("적립") or {"만든것": []}
    잴것["스킬제안"] = 난것.get("스킬제안") or {}

    # 검토 말을 그 일 글에 **덧붙인다** — 따로 글을 만들면 둘이 흩어진다
    본것 = 잴것["봄"]
    if 본것 and (잴것["적립"].get("만든것") or []):
        제목 = 잴것["적립"]["만든것"][0]
        글 = 창고.read(제목)
        if 글 is not None:
            # ★★ **껍데기를 벗긴 말**을 쓴다. 날것을 그대로 넣었더니 창고의 검토
            #   자리에 토큰 셈이 적힌 JSON 덩이가 들어앉았다(실기 · 2026-09-24).
            말 = 볼말(본것)
            머리 = f"## {본것.get('손')} 가 본 것" + ("" if 본것.get("됐나") else " (검토가 탈남)")
            글.body = (글.body or "").rstrip() + "\n\n" + 머리 + "\n\n" + (
                말[:4000] or f"(말이 없다 — {본것.get('왜') or '까닭 모름'})") + "\n"
            창고.write(글)

    잴것["사람말"] = 사람말협업(잴것)
    return 잴것


def 협업(창고: Notes, 프로젝트: str, 지시: str, 짓는손: str = "claude",
       보는손: str = "codex", 제한초: int = 0, 뿌리: Path | None = None,
       멈춤=None, 짓는물건=None, 보는물건=None) -> dict:
    """**둘이 함께 한다** — 하나가 고치고, 다른 하나가 그 차이를 검토한다.

    돌리고(`협업돌리기`) 적는(`협업뒤`) 두 몫을 한 번에 한다. 창처럼 실이 갈린
    곳에서는 둘을 따로 부른다.

    ★★ **보는 손은 읽기만 한다.** 고치면 짓는 손의 일과 섞여 누구 탓인지 못 가린다.
       말로만 시키지 않고 **git 으로 재서** 고쳤으면 탈로 잡는다(`agentcli.돌리기`).
    ★ 검토는 **적용을 막지 않는다.** 짓는 손은 이미 파일을 고쳤다 — 되돌리기는 git 이다.
      검토는 「무엇을 다시 봐야 하나」를 알려 주는 것이지 문지기가 아니다.
    """
    잰것 = 협업돌리기(프로젝트, 지시, 짓는손, 보는손, 제한초, 뿌리, 멈춤,
                  짓는물건, 보는물건)
    return 협업뒤(창고, 프로젝트, 지시, 잰것)


def 사람말협업(난것: dict) -> str:
    import agentcli

    줄 = ["[지음] " + agentcli.사람말((난것 or {}).get("지음") or {})]
    본것 = (난것 or {}).get("봄") or {}
    if not 본것:
        줄.append("[봄] 바뀐 것이 없어 안 불렀다.")
    else:
        말 = 볼말(본것)
        줄.append(f"[봄] {본것.get('손')} — " + (말[:600] if 본것.get("됐나")
                                             else f"탈남: {본것.get('왜')}"))
    남긴 = ((난것 or {}).get("적립") or {}).get("만든것") or []
    if 남긴:
        줄.append(f"[창고] {' · '.join(남긴[:3])}")
    return "\n".join(줄)


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

    # ★★ **맡기기 — 2단계의 한가운데.** 돌리고 · 적립하고 · 스킬까지 제안한다.
    #   CLI 가 안 깔린 기계에서도 `가짜` 손으로 **전 경로**를 잰다.
    import subprocess as _깃맡

    import agentcli as _시엘아이

    with tempfile.TemporaryDirectory() as tmp맡:
        창고맡 = Notes(Path(tmp맡) / "notes")
        뿌리맡 = Path(tmp맡) / "projects"
        창고맡.write(Note(title=공통규칙글, kind="규칙", body="1. 검사를 준다."))
        창고맡.reindex()
        난것맡 = 차리기(창고맡, "HandOff", "맡기기 시험", 뿌리=뿌리맡)
        자리맡 = Path(난것맡["자리"])
        (자리맡 / "a.py").write_text("x = 1\n", encoding="utf-8")
        _깃맡.run(["git", "-C", str(자리맡), "add", "-A"], capture_output=True)
        _깃맡.run(["git", "-C", str(자리맡), "-c", "user.name=T", "-c", "user.email=t@t",
                  "commit", "-qm", "첫"], capture_output=True)
        창고맡.reindex()

        난것 = 맡기기(창고맡, "HandOff", "a.py 의 x 를 2로 바꿔라", 뿌리=뿌리맡,
                   손물건=_시엘아이.가짜(str(자리맡 / "a.py"), "x = 2\n"))
        assert 난것["돌린것"]["됐나"], 난것["돌린것"]
        assert 난것["돌린것"]["바뀐파일"] == ["a.py"], 난것["돌린것"]["바뀐파일"]
        # ★ 한 일이 창고에 남는다
        assert 난것["적립"]["만든것"], 난것["적립"]
        창고맡.reindex()
        assert 창고맡.read(난것["적립"]["만든것"][0]).kind == "작업"
        # ★★ 한 바퀴 돌았으니 **스킬을 제안**한다 — 다만 저장은 안 한다
        assert 난것["스킬제안"].get("스킬") is not None, 난것["스킬제안"]
        창고맡.reindex()
        assert 창고맡.read(난것["스킬제안"]["스킬"].name) is None, "제안이 저장까지 했다"

        # ★★ **탈난 것도 남긴다** — 왜 안 됐는지가 다음에 쓸모 있다
        난것2 = 맡기기(창고맡, "HandOff", "실패해라", 뿌리=뿌리맡,
                    손물건=_시엘아이.가짜(끝난코드=2))
        assert not 난것2["돌린것"]["됐나"]
        assert 난것2["적립"]["만든것"], 난것2["적립"]
        창고맡.reindex()
        assert 창고맡.read(난것2["적립"]["만든것"][0]).kind == "오류"
        assert 난것2["스킬제안"] == {}, "실패했는데 스킬을 제안한다"
        창고맡.conn.close()

    # ★★ **협업 — 하나가 고치고 하나가 본다.**
    with tempfile.TemporaryDirectory() as tmp둘:
        import subprocess as _깃둘

        import agentcli as _시둘

        창고둘 = Notes(Path(tmp둘) / "notes")
        뿌리둘 = Path(tmp둘) / "projects"
        창고둘.write(Note(title=공통규칙글, kind="규칙", body="1. 검사를 준다."))
        창고둘.reindex()
        자리둘 = Path(차리기(창고둘, "Duet", "협업 시험", 뿌리=뿌리둘)["자리"])
        (자리둘 / "a.py").write_text("x = 1\n", encoding="utf-8")
        _깃둘.run(["git", "-C", str(자리둘), "add", "-A"], capture_output=True)
        _깃둘.run(["git", "-C", str(자리둘), "-c", "user.name=T", "-c", "user.email=t@t",
                  "commit", "-qm", "첫"], capture_output=True)
        창고둘.reindex()

        class _보는가짜(_시둘.가짜):
            """★ 껍데기에 싸서 말하는 손. 진짜 클로드가 이 꼴로 준다."""

            이름 = "보는이"

            def 명령(self, 지시, 읽기전용=False):
                import json as _j
                import sys as _s
                싼것 = _j.dumps({"type": "result", "is_error": False,
                               "result": "좋다 — 고칠 데가 없다", "total_cost_usd": 0.1},
                              ensure_ascii=False)
                return [_s.executable, "-c", f"print({싼것!r})"]

            def 읽을말(self, 나온것):
                return _시둘.클로드().읽을말(나온것)

        난것 = 협업(창고둘, "Duet", "a.py 의 x 를 2로", 뿌리=뿌리둘,
                 짓는물건=_시둘.가짜(str(자리둘 / "a.py"), "x = 2\n"),
                 보는물건=_보는가짜())
        assert 난것["지음"]["바뀐파일"] == ["a.py"], 난것["지음"]
        # ★ 보는 손이 실제로 불렸다 — 그리고 **차이를 받았다**
        assert 난것["봄"] and 난것["봄"]["됐나"], 난것["봄"]
        assert 난것["봄"]["읽기전용"] is True
        # ★★ 검토 말이 **그 일 글에 붙는다** — 따로 만들면 둘이 흩어진다
        창고둘.reindex()
        제목둘 = 난것["적립"]["만든것"][0]
        몸둘 = 창고둘.read(제목둘).body or ""
        assert "가 본 것" in 몸둘, 몸둘[-200:]
        # ★★ **껍데기가 아니라 말이 붙는다.** 날것을 그대로 넣었더니 창고에 토큰 셈이
        #   적힌 JSON 덩이가 들어앉았다(실기 · 2026-09-24).
        assert "좋다 — 고칠 데가 없다" in 몸둘, 몸둘[-300:]
        assert "total_cost_usd" not in 몸둘, "껍데기가 창고에 들어갔다"
        assert "좋다 — 고칠 데가 없다" in 난것["사람말"], 난것["사람말"]
        assert "total_cost_usd" not in 난것["사람말"], 난것["사람말"]

        # ★★ **바뀐 것이 없으면 보는 손을 안 부른다** — 볼 것이 없는데 부르면 값만 든다
        난것2 = 협업(창고둘, "Duet", "가만히 있어라", 뿌리=뿌리둘,
                  짓는물건=_시둘.가짜(), 보는물건=_보는가짜())
        assert 난것2["봄"] == {}, 난것2["봄"]
        assert "안 불렀다" in 난것2["사람말"], 난것2["사람말"]

        # ★★ **보는 손이 고치면 탈로 잡는다.**
        #   ★ 앞 판에서 고친 것을 커밋해 둔다 — 안 그러면 「원래 더럽던 것」으로 잡혀
        #     바뀐 것이 없다고 보고 보는 손을 안 부른다(검사 짜임이 틀렸던 자리다).
        _깃둘.run(["git", "-C", str(자리둘), "add", "-A"], capture_output=True)
        _깃둘.run(["git", "-C", str(자리둘), "-c", "user.name=T", "-c", "user.email=t@t",
                  "commit", "-qm", "둘째"], capture_output=True)
        class _말안듣는보는손(_시둘.손):
            """읽기전용이라 해도 **고치는** 손. 진짜 CLI 가 말을 안 들을 수 있다."""

            이름, 실행파일 = "말안듣", "python3"

            def 있나(self):
                return True

            def 명령(self, 지시, 읽기전용=False):
                import sys as _s
                return [_s.executable, "-c",
                        "open(%r, 'w').write('몰래')" % str(자리둘 / "몰래.py")]

        난것3 = 협업(창고둘, "Duet", "a.py 의 x 를 3으로", 뿌리=뿌리둘,
                  짓는물건=_시둘.가짜(str(자리둘 / "a.py"), "x = 3\n"),
                  보는물건=_말안듣는보는손())
        assert 난것3["봄"], "바뀐 것이 있는데 보는 손을 안 불렀다"
        assert not 난것3["봄"]["됐나"], "읽기만 하라 했는데 고친 것을 통과시켰다"
        assert "읽기만 하라 했는데" in 난것3["봄"]["왜"], 난것3["봄"]["왜"]

        # ★ 볼말은 **한 군데에만** 둔다 — 두 곳에서 따로 고르면 한쪽만 고쳐져 샌다
        assert 볼말({"읽을말": "벗긴 말", "나온말": "{덩이}"}) == "벗긴 말"
        assert 볼말({"나온말": " 옛 결과 "}) == "옛 결과"   # 옛것도 말이 안 사라진다
        assert 볼말({"끝말": "마지막"}) == "마지막"
        assert 볼말({}) == "" and 볼말(None) == ""
        창고둘.conn.close()

    print("hermes self-check 통과")


if __name__ == "__main__":
    import sys

    if "--check" in sys.argv:
        _self_check()
