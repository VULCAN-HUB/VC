"""자가 스킬 생성 — **방금 한 일에서 스킬을 뽑는다.** 화면도 모델도 안 쓴다.

VC 네 기둥의 둘째가 이것이다: 「지시를 수행하고 **해결 과정을 스킬로 코드화해 저장**하며
스스로 능력을 확장한다」. 헤르메스가 일을 한 바퀴 돌 때마다 그 과정을 선언문으로 뽑는다.

★★ **이력이 없어도 돈다.** `skills.py` 의 분석기는 「같은 일이 여러 번 났나」를 보는데,
   그건 쌓인 뒤에야 쓸모가 있다(그 파일도 「지금은 제안할 이력 자체가 없다」고 적어 뒀다).
   그래서 여기는 **방금 끝난 일 하나**에서 뽑는다 — 첫날부터 배운다.

★★ **제안이지 저장이 아니다.** 뽑은 것을 바로 저장하면 창고가 쓰다 만 스킬로 찬다.
   `뽑기` 는 만들어 보여 주기만 하고, `남기기` 를 불러야 들어간다(제안 → 승인 → 기록).

★★ **이미 아는 일이면 안 뽑는다.** 같은 반응을 가진 스킬이 있으면 그것을 **고쳐야지**
   같은 것을 또 만들면 안 된다 — 창고가 겹친 스킬로 덮인다(합치기에서 겪은 그 병이다).

★ 스킬은 **코드가 아니라 데이터**다(`skills.py`). 사람이 읽고, 틀리면 지우고, 돌리기
  전에 검증할 수 있다 — 생성된 코드는 셋 다 안 된다.
"""

from __future__ import annotations

import re

import hermes
from notes import Notes
from skills import Skill, SkillStore

이름최대 = 40
예시최대 = 5

# 지시에서 **일감 이름**을 뽑을 때 버리는 말. 남는 것이 그 일의 뼈대다.
군말 = ("좀", "해줘", "해라", "해", "주라", "줘", "바꿔라", "바꿔", "고쳐라", "고쳐",
       "만들어라", "만들어", "please", "그리고", "다시", "이제")

# ★ 파일 이름을 떼면 **조사가 혼자 남는다** — 「greet.py 의 인사말을」 → 「의 인사말을」.
#   홀로 선 조사는 뜻이 없으니 버린다(붙어 있는 조사는 낱말의 일부라 안 건드린다).
홀로조사 = ("의", "에", "에서", "를", "을", "이", "가", "은", "는", "로", "으로", "와", "과")


def 일감이름(지시: str, 길이: int = 이름최대) -> str:
    """지시에서 사람이 알아볼 이름을 뽑는다. **모델 없이** 한다 — 이름 하나에 값을 쓰지 않는다."""
    말 = re.sub(r"\s+", " ", (지시 or "").strip())
    말 = re.sub(r"[`'\"]", "", 말)
    낱말 = [w for w in 말.split(" ") if w and w not in 군말]
    이름 = " ".join(낱말) or 말
    return 이름 if len(이름) <= 길이 else 이름[:길이 - 1] + "…"


def 반응만들기(지시: str) -> list[str]:
    """이 스킬이 반응할 말. **파일 이름은 뺀다** — 다음엔 딴 파일에 같은 일을 한다.

    ★ 트리거는 글자 그대로 맞아야 하므로 짧고 일반적이어야 한다. 파일 이름이 박히면
      그 파일에만 반응하는 쓸모없는 스킬이 된다.
    """
    말 = re.sub(r"\s+", " ", (지시 or "").strip())
    말 = re.sub(r"\S*\.\w{1,6}\b", "", 말)          # 파일 이름을 뺀다
    말 = re.sub(r"[`'\"]", "", 말).strip()
    낱말 = [w for w in 말.split(" ") if w and w not in 군말 and w not in 홀로조사]
    뼈대 = " ".join(낱말[:6]).strip()
    return [뼈대] if len(뼈대) >= 2 else []


def 이미있나(책: SkillStore, 반응: list[str], 프로젝트: str = "") -> str:
    """같은 반응을 가진 스킬이 이미 있나. 있으면 그 이름.

    ★★ 겹친 스킬을 또 만들면 **어느 것이 도는지 알 수 없게 된다.** 합치기에서
       같은 원본에 요약이 둘 생겨 겪은 그 병이다.
    """
    맞출 = {t.strip().lower() for t in 반응 if t.strip()}
    if not 맞출:
        return ""
    # ★ 스킬이 들고 있는 것은 **프로젝트 글 제목**이다(`프로젝트 · X`). 바깥에서는
    #   맨 이름(`X`)으로 부르므로 여기서 맞춰 준다 — 안 맞추면 제 스킬을 못 알아보고
    #   같은 것을 또 만든다(검사가 잡았다).
    매인것 = hermes.프로젝트글제목(프로젝트) if 프로젝트 else ""
    for s in 책.all():
        if 매인것 and s.project and s.project != 매인것:
            continue
        if {t.strip().lower() for t in s.triggers} & 맞출:
            return s.name
    return ""


def 뽑기(창고: Notes, 프로젝트: str, 지시: str, 안: dict | None = None,
       쓴파일: list[str] | None = None) -> dict:
    """방금 한 일에서 스킬을 뽑는다. **저장은 안 한다.**

    `{"스킬": Skill|None, "왜": str, "겹침": str}`.
    """
    지시 = (지시 or "").strip()
    if not hermes.영문이름인가(프로젝트):
        return {"스킬": None, "왜": "그런 프로젝트가 없다", "겹침": ""}
    if not 지시:
        return {"스킬": None, "왜": "지시가 비었다", "겹침": ""}

    파일들 = list(쓴파일 or [])
    if not 파일들 and 안:
        파일들 = [것.get("파일") for 것 in (안.get("고침") or []) if 것.get("파일")]
    if not 파일들:
        # ★ 아무것도 안 바꾼 일은 스킬이 아니다 — 되풀이할 일머리가 없다
        return {"스킬": None, "왜": "바뀐 파일이 없다 — 되풀이할 일이 아니다", "겹침": ""}

    반응 = 반응만들기(지시)
    if not 반응:
        return {"스킬": None, "왜": "반응할 말을 못 뽑았다 — 지시가 너무 짧다", "겹침": ""}

    책 = SkillStore(창고)
    겹침 = 이미있나(책, 반응, 프로젝트)
    if 겹침:
        return {"스킬": None, "왜": f"이미 아는 일이다 — 「{겹침}」 을 고쳐라", "겹침": 겹침}

    스킬 = Skill(
        name=f"{프로젝트} · {일감이름(지시)}",
        triggers=반응,
        examples=[지시][:예시최대],
        # ★ 단계는 **바이브코딩 한 번**이다. 무엇을 고칠지는 그때 지시가 정하고,
        #   여기 적힌 파일은 「지난번엔 여기였다」는 자취다.
        steps=[{"module": "vibe", "params": {"지시틀": 지시, "지난파일": 파일들}}],
        project=hermes.프로젝트글제목(프로젝트),
    )
    return {"스킬": 스킬, "왜": "", "겹침": ""}


def 남기기(창고: Notes, 스킬: Skill) -> str:
    """뽑은 스킬을 창고에 넣는다. 승인한 뒤에 부른다."""
    if 스킬 is None:
        return ""
    SkillStore(창고).save(스킬)
    return 스킬.name


def 사람말(난것: dict) -> str:
    """제안을 사람이 읽는 한 덩이로."""
    스킬 = (난것 or {}).get("스킬")
    if 스킬 is None:
        return (난것 or {}).get("왜") or "뽑을 것이 없다"
    줄 = [f"스킬로 남길까 — **{스킬.name}**", "",
         f"- 반응: {', '.join(스킬.triggers)}",
         f"- 배운 말: {', '.join(스킬.examples)}"]
    for i, s in enumerate(스킬.steps, 1):
        줄.append(f"- {i}단계: {s['module']} {s.get('params', {})}")
    return "\n".join(줄)


def _self_check() -> None:
    import tempfile
    from pathlib import Path

    from notes import Note

    assert 일감이름("greet.py 의 인사말을 한국어로 바꿔라") == "greet.py 의 인사말을 한국어로"
    assert 일감이름("좀 해줘") == "좀 해줘" or len(일감이름("좀 해줘")) >= 1
    # 파일 이름은 반응에서 뺀다 — 다음엔 딴 파일에 같은 일을 한다
    assert "greet.py" not in " ".join(반응만들기("greet.py 의 인사말을 한국어로 바꿔라"))
    assert 반응만들기("인사말을 한국어로 바꿔라") == ["인사말을 한국어로"]
    assert 반응만들기("a") == []

    with tempfile.TemporaryDirectory() as tmp:
        창고 = Notes(Path(tmp) / "notes")
        옛뿌리 = hermes.기본뿌리
        hermes.기본뿌리 = Path(tmp) / "projects"
        try:
            (hermes.기본뿌리 / "SkillApp").mkdir(parents=True)
            창고.write(Note(title=hermes.프로젝트글제목("SkillApp"), kind="엔티티", body="시험."))
            창고.reindex()

            안 = {"고침": [{"파일": "greet.py", "새글": "x\n"}]}
            난것 = 뽑기(창고, "SkillApp", "greet.py 의 인사말을 한국어로 바꿔라", 안)
            스킬 = 난것["스킬"]
            assert 스킬 is not None and 난것["왜"] == "", 난것
            assert 스킬.name.startswith("SkillApp · "), 스킬.name
            assert 스킬.triggers == ["인사말을 한국어로"], 스킬.triggers
            assert 스킬.steps[0]["module"] == "vibe"
            assert 스킬.steps[0]["params"]["지난파일"] == ["greet.py"]
            assert 스킬.project == hermes.프로젝트글제목("SkillApp")
            # ★★ **아직 저장 안 했다**
            창고.reindex()
            assert 창고.read(스킬.name) is None, "뽑기가 저장까지 했다"

            # 사람이 읽는 꼴
            말 = 사람말(난것)
            assert "스킬로 남길까" in 말 and "인사말을 한국어로" in 말, 말

            # --- 남기기 ---
            이름 = 남기기(창고, 스킬)
            창고.reindex()
            글 = 창고.read(이름)
            assert 글 is not None and 글.kind == "skill", 글
            # ★ 프로젝트에 매인다 — 안 매면 배워 놓고 다시 못 찾는다
            assert hermes.프로젝트글제목("SkillApp") in 창고.neighbors(이름), 창고.neighbors(이름)
            # 헤르메스가 맥락을 꺼낼 때 스킬도 같이 뜬다
            맥락 = hermes.꺼내기(창고, "SkillApp")
            assert any(이름 == t for 칸 in 맥락["칸"].values() for t, _ in 칸), 맥락["칸"]

            # ★★ **같은 일을 또 뽑지 않는다** — 겹친 스킬은 어느 것이 도는지 모르게 한다
            다시 = 뽑기(창고, "SkillApp", "인사말을 한국어로 바꿔라", 안)
            assert 다시["스킬"] is None and 다시["겹침"] == 이름, 다시

            # 바뀐 파일이 없으면 스킬이 아니다
            빈것 = 뽑기(창고, "SkillApp", "뭔가 해봐라", {"고침": []})
            assert 빈것["스킬"] is None and "바뀐 파일이 없다" in 빈것["왜"], 빈것
            # 모르는 프로젝트
            assert 뽑기(창고, "한글", "뭐든", 안)["스킬"] is None
        finally:
            hermes.기본뿌리 = 옛뿌리
        창고.conn.close()

    print("skillgen self-check 통과")


if __name__ == "__main__":
    import sys

    if "--check" in sys.argv:
        _self_check()
