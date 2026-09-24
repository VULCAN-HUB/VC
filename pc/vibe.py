"""바이브코딩 — **바깥 AI(API)가 코드를 고친다.** 화면은 안 쓴다.

헤르메스의 셋째 조각이다. 관제탑이 맥락을 꺼내 주고, 여기서 그 맥락으로 **고칠 안**을
만들어 사람에게 보이고, 승인하면 적용한다.

    고칠안   지시 + 프로젝트 맥락 + 파일 내용  →  AI 가 「이렇게 고치자」를 낸다
    차이     무엇이 어떻게 바뀌는지 **줄 단위로** 보여 준다
    적용     승인한 것만 파일에 쓴다

★★ **제안 → 승인 → 기록.** 이 프로그램이 제 규칙으로 적어 둔 결이다(결정 18).
   한 번에 여러 파일을 잘못 고치면 되돌리기가 사람 일이 된다 — 보이고 나서 쓴다.

★★ **손을 갈아 끼울 수 있게 한 문으로 받는다** — `부르기(말들) -> 글` 하나뿐이다.
   `synth.py`·`query.py` 와 같은 얼굴이라 로컬이든 클로드든 제미나이든 똑같이 끼운다.

★★ **파일은 통째로 받는다.** 조각 기움(patch)은 줄 번호가 한 칸만 어긋나도 엉뚱한 데
   붙는다 — 모델이 자주 틀리는 자리다. 통째로 받으면 **틀리면 통째로 틀려서** 차이로
   바로 보인다. 대신 큰 파일은 안 넣는다.

★ **쓰는 길은 `codefiles` 하나다.** 자리를 벗어나지 못하게 막는 곳이 한 자리여야 한다.
★ **되돌리기는 git 이 맡는다.** `차리기` 가 `git init` 을 먼저 하는 까닭이다.
"""

from __future__ import annotations

import difflib
import json
import re
from typing import Callable

import codefiles
import hermes
from notes import Notes

한번에 = 4              # 한 번에 고칠 파일 수. 많으면 모델이 흐려지고 차이도 못 읽는다
넣을크기 = 60_000       # 이보다 큰 파일은 안 넣는다(맥락이 찬다)

_생각끄기 = " /no_think"

프롬프트 = """너는 사람의 코드를 고치는 조수다. 아래 지시대로 **파일을 통째로 다시 써서** 낸다.

규칙:
1. **JSON 하나만** 낸다. 설명은 `왜` 안에 한국어로 짧게 적는다.
2. `고침` 은 바꿀 파일만 담는다. **안 바꿀 파일은 넣지 마라.**
3. `새글` 은 그 파일의 **전체 내용**이다. 조각이나 `...` 를 쓰지 마라.
4. 시키지 않은 기능을 넣지 마라. 상관없는 데를 「개선」하지 마라.
5. 못 하겠으면 `고침` 을 비우고 `왜` 에 까닭을 적어라.

낼 꼴:
{{"왜": "무엇을 왜 고쳤는지 한두 문장", "고침": [{{"파일": "상대/경로.py", "새글": "파일 전체"}}]}}

## 프로젝트
{맥락}

## 지금 파일
{파일들}

## 지시
{지시}
""" + _생각끄기


def _낱말들(글: str) -> list[str]:
    return [x for x in re.split(r"[^\w./\\-]+", 글 or "") if len(x) > 1]


def 고를파일(프로젝트: str, 지시: str, 몇: int = 한번에) -> list[str]:
    """지시에 이름이 나온 파일을 고른다. **없으면 빈 손** — 아무거나 고치지 않는다.

    ★ 「알아서 찾아 고쳐라」를 하려면 코드를 읽고 판단해야 하는데, 그건 다음 조각이다.
      지금은 **무엇을 고칠지 사람이 말한다** — 잘못 고칠 자리를 좁힌다.
    """
    난것 = codefiles.나무(프로젝트)
    있는것 = 난것["파일"]
    if not 있는것:
        return []
    낱말 = [w.lower() for w in _낱말들(지시)]
    점수: list[tuple[int, str]] = []
    for 상대 in 있는것:
        낮은 = 상대.lower()
        꼬리 = 낮은.rsplit("/", 1)[-1]
        값 = 0
        for w in 낱말:
            if w == 낮은 or w == 꼬리:
                값 += 10
            elif w and (w in 낮은):
                값 += 3
            elif 꼬리.startswith(w) and len(w) >= 3:
                값 += 1
        if 값:
            점수.append((값, 상대))
    점수.sort(key=lambda x: (-x[0], len(x[1])))
    return [상대 for _, 상대 in 점수[:몇]]


def 파일묶음(프로젝트: str, 파일들: list[str]) -> tuple[str, list[str]]:
    """모델에게 줄 파일 내용. 못 읽거나 너무 큰 것은 **빼고 그 사실을 알린다.**"""
    조각, 넣은것 = [], []
    for 상대 in 파일들:
        난것 = codefiles.읽기(프로젝트, 상대)
        if 난것["왜"]:
            조각.append(f"### {상대}\n(못 읽었다: {난것['왜']})")
            continue
        글 = 난것["글"]
        if len(글) > 넣을크기:
            조각.append(f"### {상대}\n(너무 커서 안 넣었다: {len(글)}자)")
            continue
        조각.append(f"### {상대}\n```\n{글}\n```")
        넣은것.append(상대)
    return "\n\n".join(조각), 넣은것


def _json풀기(답: str) -> dict | None:
    글 = re.sub(r"(?s)<think>.*?</think>", "", 답 or "").strip()
    글 = re.sub(r"^```(?:json)?|```$", "", 글.strip(), flags=re.M).strip()
    처음 = 글.find("{")
    if 처음 < 0:
        return None
    깊이 = 0
    for i in range(처음, len(글)):
        깊이 += (글[i] == "{") - (글[i] == "}")
        if 깊이 == 0:
            try:
                난것 = json.loads(글[처음:i + 1])
            except json.JSONDecodeError:
                return None
            return 난것 if isinstance(난것, dict) else None
    return None


def 고칠안(창고: Notes, 부르기: Callable[[list[dict]], str] | None, 프로젝트: str,
        지시: str, 파일들: list[str] | None = None) -> dict:
    """고칠 안을 만든다. `{"왜", "고침": [{"파일","새글"}], "본파일", "탈"}`.

    아무것도 쓰지 않는다 — 쓰는 것은 `적용` 이다.
    """
    지시 = (지시 or "").strip()
    if not hermes.영문이름인가(프로젝트):
        return {"왜": "", "고침": [], "본파일": [], "탈": "그런 프로젝트가 없다"}
    if not 지시:
        return {"왜": "", "고침": [], "본파일": [], "탈": "지시가 비었다"}
    고를것 = list(파일들) if 파일들 else 고를파일(프로젝트, 지시)
    if not 고를것:
        return {"왜": "", "고침": [], "본파일": [],
                "탈": "고칠 파일을 못 골랐다 — 지시에 파일 이름을 넣어라"}
    if 부르기 is None:
        return {"왜": "", "고침": [], "본파일": 고를것, "탈": "모델이 없다"}

    맥락 = hermes.꺼내기(창고, 프로젝트)["글"]
    묶음, 넣은것 = 파일묶음(프로젝트, 고를것)
    말 = 프롬프트.format(맥락=맥락, 파일들=묶음, 지시=지시)
    try:
        답 = 부르기([{"role": "user", "content": 말}]) or ""
    except Exception as e:
        return {"왜": "", "고침": [], "본파일": 넣은것, "탈": f"모델이 답을 못 했다: {type(e).__name__}"}
    난것 = _json풀기(답)
    if 난것 is None:
        return {"왜": "", "고침": [], "본파일": 넣은것, "탈": "모델이 JSON 을 안 냈다"}

    고침 = []
    for 것 in 난것.get("고침") or []:
        상대 = str((것 or {}).get("파일") or "").strip()
        새글 = (것 or {}).get("새글")
        if not 상대 or not isinstance(새글, str):
            continue
        # ★★ **모델이 고르지 않은 파일은 안 받는다.** 안 보여 준 파일을 「고쳤다」고 내면
        #   내용을 통째로 지어낸 것이다 — 그대로 쓰면 파일이 날아간다.
        if 상대 not in 넣은것:
            continue
        if codefiles.안전한자리(프로젝트, 상대) is None:
            continue
        고침.append({"파일": 상대, "새글": 새글})
    return {"왜": str(난것.get("왜") or "").strip(), "고침": 고침,
            "본파일": 넣은것, "탈": "" if 고침 else "바꿀 것이 없다고 한다"}


def 차이(프로젝트: str, 안: dict) -> str:
    """사람이 볼 차이. **줄 단위로** 보인다 — 무엇이 바뀌는지 보고 승인한다."""
    줄 = []
    for 것 in (안 or {}).get("고침") or []:
        상대 = 것["파일"]
        옛 = codefiles.읽기(프로젝트, 상대)["글"]
        새 = 것["새글"]
        조각 = list(difflib.unified_diff(
            옛.splitlines(keepends=True), 새.splitlines(keepends=True),
            fromfile=f"a/{상대}", tofile=f"b/{상대}", n=2))
        줄.append("".join(조각) if 조각 else f"(바뀐 것 없음: {상대})\n")
    return "".join(줄)


def 잰것(프로젝트: str, 안: dict) -> dict:
    """얼마나 바뀌나. 승인하기 전에 **크기를 먼저 본다** — 큰 고침은 더 봐야 한다."""
    더함 = 뺌 = 0
    for 것 in (안 or {}).get("고침") or []:
        옛 = codefiles.읽기(프로젝트, 것["파일"])["글"].splitlines()
        새 = 것["새글"].splitlines()
        for 줄 in difflib.ndiff(옛, 새):
            더함 += 줄.startswith("+ ")
            뺌 += 줄.startswith("- ")
    return {"파일": len((안 or {}).get("고침") or []), "더한줄": 더함, "뺀줄": 뺌}


def 적용(프로젝트: str, 안: dict, 고를것: list[str] | None = None) -> dict:
    """승인한 것만 파일에 쓴다. `{"쓴것": [...], "못쓴것": [...]}`.

    `고를것` 을 주면 그 파일만 쓴다 — 안 중 일부만 승인할 수 있다.
    """
    쓴것, 못쓴것 = [], []
    for 것 in (안 or {}).get("고침") or []:
        상대 = 것["파일"]
        if 고를것 is not None and 상대 not in 고를것:
            continue
        난것 = codefiles.쓰기(프로젝트, 상대, 것["새글"])
        (쓴것 if 난것["됐나"] else 못쓴것).append(상대 if 난것["됐나"] else f"{상대}: {난것['왜']}")
    return {"쓴것": 쓴것, "못쓴것": 못쓴것}


def _self_check() -> None:
    import tempfile
    from pathlib import Path

    from notes import Note

    with tempfile.TemporaryDirectory() as tmp:
        창고 = Notes(Path(tmp) / "notes")
        뿌리 = Path(tmp) / "projects"
        옛뿌리 = hermes.기본뿌리
        hermes.기본뿌리 = 뿌리
        try:
            바닥 = 뿌리 / "VibeApp"
            (바닥 / "src").mkdir(parents=True)
            (바닥 / "src" / "main.py").write_text("x = 1\n", encoding="utf-8")
            (바닥 / "README.md").write_text("# VibeApp\n", encoding="utf-8")
            창고.write(Note(title=hermes.프로젝트글제목("VibeApp"), kind="엔티티",
                           body="시험용."))
            창고.reindex()

            # --- 파일 고르기 ---
            assert 고를파일("VibeApp", "src/main.py 를 고쳐라") == ["src/main.py"]
            assert 고를파일("VibeApp", "main.py 에 함수 하나") == ["src/main.py"]
            # ★ 이름이 안 나오면 **빈 손** — 아무거나 고치지 않는다
            assert 고를파일("VibeApp", "뭔가 좋게 해 줘") == []

            # 모델이 없으면 아무것도 안 쓴다
            난것 = 고칠안(창고, None, "VibeApp", "main.py 를 고쳐라")
            assert 난것["탈"] == "모델이 없다" and 난것["고침"] == []

            # 고칠 파일을 못 고르면 모델을 부르지도 않는다
            부른것 = []
            손 = lambda 말들: 부른것.append(말들) or "{}"
            난것 = 고칠안(창고, 손, "VibeApp", "뭔가 좋게 해 줘")
            assert "못 골랐다" in 난것["탈"] and not 부른것, 난것

            # --- 고칠안 ---
            말들 = []

            def 손2(msgs):
                말들.append(msgs[0]["content"])
                return json.dumps({"왜": "x 를 2로",
                                   "고침": [{"파일": "src/main.py", "새글": "x = 2\n"}]},
                                  ensure_ascii=False)

            안 = 고칠안(창고, 손2, "VibeApp", "src/main.py 의 x 를 2로")
            assert 안["탈"] == "" and 안["왜"] == "x 를 2로", 안
            assert 안["고침"] == [{"파일": "src/main.py", "새글": "x = 2\n"}]
            # 맥락과 파일 내용이 모델에게 갔다
            assert "### src/main.py" in 말들[0] and "x = 1" in 말들[0]
            assert "VibeApp" in 말들[0]
            # ★★ **아직 아무것도 안 썼다**
            assert (바닥 / "src" / "main.py").read_text(encoding="utf-8") == "x = 1\n"

            # --- 차이·크기 ---
            차 = 차이("VibeApp", 안)
            assert "-x = 1" in 차 and "+x = 2" in 차, 차
            assert 잰것("VibeApp", 안) == {"파일": 1, "더한줄": 1, "뺀줄": 1}, 잰것("VibeApp", 안)

            # --- 적용 ---
            난것 = 적용("VibeApp", 안)
            assert 난것["쓴것"] == ["src/main.py"] and not 난것["못쓴것"], 난것
            assert (바닥 / "src" / "main.py").read_text(encoding="utf-8") == "x = 2\n"

            # ★ **일부만 승인**할 수 있다
            안2 = {"고침": [{"파일": "src/main.py", "새글": "x = 3\n"},
                          {"파일": "README.md", "새글": "# 바뀜\n"}]}
            난것 = 적용("VibeApp", 안2, 고를것=["README.md"])
            assert 난것["쓴것"] == ["README.md"], 난것
            assert (바닥 / "src" / "main.py").read_text(encoding="utf-8") == "x = 2\n", "승인 안 한 것을 썼다"

            # ★★ **안 보여 준 파일을 고쳤다고 하면 안 받는다** — 내용을 지어낸 것이다
            손3 = lambda m: json.dumps(
                {"왜": "딴 데도", "고침": [{"파일": "src/main.py", "새글": "x = 9\n"},
                                     {"파일": "몰래.py", "새글": "나쁜 것\n"}]}, ensure_ascii=False)
            안3 = 고칠안(창고, 손3, "VibeApp", "src/main.py 고쳐")
            assert [것["파일"] for 것 in 안3["고침"]] == ["src/main.py"], 안3["고침"]
            assert not (바닥 / "몰래.py").exists()

            # ★★ **자리를 벗어난 파일은 안 받는다**
            손4 = lambda m: json.dumps(
                {"왜": "밖으로", "고침": [{"파일": "../../밖.py", "새글": "나쁜 것\n"}]},
                ensure_ascii=False)
            assert 고칠안(창고, 손4, "VibeApp", "src/main.py 고쳐")["고침"] == []

            # 모델이 헛소리를 하면 조용히 실패한다
            헛것 = 고칠안(창고, lambda m: "무슨 말인지", "VibeApp", "main.py 고쳐")
            assert 헛것["탈"] == "모델이 JSON 을 안 냈다", 헛것
            # `<think>` 는 걷어낸다
            손5 = lambda m: '<think>음</think>{"왜":"ㅇ","고침":[]}'
            assert 고칠안(창고, 손5, "VibeApp", "main.py 고쳐")["탈"] == "바꿀 것이 없다고 한다"
        finally:
            hermes.기본뿌리 = 옛뿌리
        창고.conn.close()

    print("vibe self-check 통과")


if __name__ == "__main__":
    import sys

    if "--check" in sys.argv:
        _self_check()
