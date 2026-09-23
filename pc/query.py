"""묻기(Query) — 창고를 뒤져 **근거를 달아** 답한다. 화면은 안 쓴다.

카파시 LLM Wiki 의 셋째 일이다. 네 가지 일 중 **여기만 비어 있었다**(2026-09-21 확인:
일지에 「묻기」 줄이 프로그램 손으로 남은 적이 한 번도 없다).

★★ **손을 갈아 끼울 수 있게 한 문으로 받는다** — `부르기(말들) -> 글` 하나뿐이다.
   `synth.py` 와 같은 얼굴이라 로컬이든 바깥 AI 든 똑같이 끼운다.

★★ **근거 없이 답하지 않는다.** 찾은 글이 없으면 모델을 부르지도 않는다. 창고는
   「AI 의 바깥 기억」이라, 기억에 없는 것을 지어내면 그 순간 창고를 못 믿게 된다.

★★ **찾기는 두 갈래를 섞는다.** 낱말(FTS)은 이름·번호를 잡고, 뜻(벡터)은 다르게 쓴
   말을 잡는다. 하나만 쓰면 한쪽이 통째로 샌다 — 실측에서 「맥에서 한글 경로 때문에
   터진 일」은 낱말로는 안 걸리고 뜻으로만 걸렸다.

★ **답을 창고에 남기는 것은 따로 부른다**(`남기기`). 물을 때마다 글이 하나씩 쌓이면
  창고가 물음으로 덮인다 — 남길지는 사람이 정한다.
"""

from __future__ import annotations

import re
from typing import Callable

import wiki
from notes import Note, Notes, parse_links

한바퀴 = 5          # 근거로 들이는 글 수. 많이 넣으면 맥락이 차고 답이 흐려진다
토막길이 = 1200     # 글 하나에서 보여 줄 글자 수

# ★★ `/no_think` — 로컬 `qwen3` 는 추론 모델이라 `<think>` 로 답 길이를 다 쓴다.
#   `synth.py` 에서 실측으로 확인한 것과 같은 함정이다.
_생각끄기 = " /no_think"

프롬프트 = """너는 사람의 기록 창고를 읽고 답하는 조수다.

아래 「근거」만 보고 물음에 답해라. 규칙:
1. 근거에 없는 것은 **지어내지 마라.** 모르면 「창고에 없다」고 해라.
2. 답에 쓴 사실마다 어느 글에서 왔는지 `[[글 제목]]` 으로 달아라.
3. 한국어로, 세 문장 안으로 짧게 답해라.

물음: {물음}

근거:
{근거}

답:""" + _생각끄기


def 찾기(창고: Notes, 물음: str, 몇: int = 한바퀴) -> list[str]:
    """낱말과 뜻을 **섞어** 후보 글을 고른다. 차례는 낱말이 먼저다(정확한 것이 앞)."""
    낸다: list[str] = []

    def 넣기(제목: str) -> None:
        if 제목 and 제목 not in 낸다 and 제목 != wiki.가운데항목:
            낸다.append(제목)

    try:
        for r in 창고.search(물음, k=몇):
            넣기(r["title"])
    except Exception:
        pass          # 낱말 검색이 막혀도 뜻으로는 답한다
    try:
        for 제목, _ in 창고.semantic(물음, k=몇):
            넣기(제목)
    except Exception:
        pass
    return 낸다[:몇]


def 근거글(창고: Notes, 제목들: list[str], 물음: str = "") -> str:
    """모델에게 줄 근거 묶음. **제목을 반드시 보인다** — 그래야 링크를 달 수 있다.

    ★★ **한 줄 요약을 주면 안 된다.** 처음에 `notes.요약()` 한 줄만 줬더니 근거가
       「여섯 번 막혔다」 같은 껍데기라, 모델이 **구체적인 글자가 든 엉뚱한 글**로 샜다
       (실측: 한글 경로를 물었는데 git 이력 글을 가리켰다). 글머리를 넉넉히 주고,
       물음에 걸린 줄이 그 안에 없으면 **따로 붙인다** — 맥락과 딱 그 줄을 둘 다 준다.
    """
    import notes as _쪽

    조각 = []
    for 제목 in 제목들:
        글 = 창고.read(제목)
        if 글 is None:
            continue
        몸 = re.sub(r"\s+", " ", (글.body or "").strip()).strip()
        머리 = 몸[:토막길이 - 1] + "…" if len(몸) > 토막길이 else 몸
        try:
            걸린줄 = re.sub(r"\s+", " ", (_쪽.요약(글.body or "", 물음=물음) or "")).strip()
        except Exception:
            걸린줄 = ""
        if 걸린줄 and 걸린줄 not in 머리:
            머리 = (머리 + " … " + 걸린줄)[:토막길이 * 2]
        조각.append(f"### {제목}\n{머리}")
    return "\n\n".join(조각)


def 달린링크(답: str, 본것: list[str]) -> list[str]:
    """답이 실제로 가리킨 글들. **본 것 안에 있는 것만** 센다 — 지어낸 이름은 버린다."""
    낸다 = []
    맞춤 = {t.strip().lower(): t for t in 본것}
    for 이름, _ in parse_links(답 or ""):
        진짜 = 맞춤.get(이름.strip().lower())
        if 진짜 and 진짜 not in 낸다:
            낸다.append(진짜)
    return 낸다


def 가짜링크지우기(답: str, 본것: list[str]) -> str:
    """**근거에 없는 `[[이름]]` 은 링크를 벗긴다.** 글자는 남기고 대괄호만 뗀다.

    ★★ 지어낸 링크를 그대로 보이면 사람이 **눌러 보고서야** 없는 글인 줄 안다.
       실측에서 모델이 근거에 없던 `[[VC]]` 를 달았다 — 근거로는 안 셌지만 답에는
       남아 있었다. 보이는 것과 세는 것이 어긋나면 안 된다.
    """
    맞춤 = {t.strip().lower() for t in 본것}

    def 벗기(m):
        속 = m.group(1).strip()
        보임 = (m.group(3) or "").strip() or 속
        return m.group(0) if 속.lower() in 맞춤 else 보임

    from notes import LINK_RE
    return LINK_RE.sub(벗기, 답 or "")


앞말최대 = 6              # 모델에게 넘길 앞 마디 수. 많이 주면 답이 흐려지고 느려진다


def 앞말다듬기(앞말: list | None, 몇: int = 앞말최대) -> list[dict]:
    """오간 말을 모델이 먹을 꼴로. **믿을 수 있는 것만 추린다.**

    ★★ 바깥에서 들어오는 것이라 꼴을 안 믿는다 — 역할이 이상하면 버린다.
       서버 문으로도 들어오는 값이다.
    """
    나온것 = []
    for 것 in (앞말 or [])[-몇 * 2:]:
        if not isinstance(것, dict):
            continue
        역할 = str(것.get("role") or 것.get("누가") or "").strip().lower()
        말 = str(것.get("content") or 것.get("말") or "").strip()
        역할 = "assistant" if 역할 in ("assistant", "vc", "답") else "user"
        if 말:
            나온것.append({"role": 역할, "content": 말[:4000]})
    return 나온것[-몇:]


def 묻기(창고: Notes, 부르기: Callable[[list[dict]], str] | None, 물음: str,
       몇: int = 한바퀴, 앞말: list | None = None) -> dict:
    """창고를 뒤져 답한다. `{"답", "근거", "본것", "왜"}`.

    ★ 모델이 없으면 **찾은 것만** 돌려준다 — 그것만으로도 사람에게는 쓸모가 있다.
    ★★ `앞말` 은 **모델에게만** 준다. 찾기에는 안 섞는다 — 섞으면 지난 말이 검색을
       끌고 가서, 새로 물은 것과 상관없는 글이 근거로 올라온다.
    """
    물음 = (물음 or "").strip()
    if not 물음:
        return {"답": "", "근거": [], "본것": [], "왜": "물음이 비었다"}

    본것 = 찾기(창고, 물음, 몇)
    if not 본것:
        return {"답": "", "근거": [], "본것": [], "왜": "창고에서 못 찾았다"}
    if 부르기 is None:
        return {"답": "", "근거": [], "본것": 본것, "왜": "모델이 없다"}

    말 = 프롬프트.format(물음=물음, 근거=근거글(창고, 본것, 물음))
    보낼것 = [*앞말다듬기(앞말), {"role": "user", "content": 말}]
    try:
        답 = (부르기(보낼것) or "").strip()
    except Exception as e:
        return {"답": "", "근거": [], "본것": 본것, "왜": f"모델이 답을 못 했다: {type(e).__name__}"}
    답 = re.sub(r"(?s)<think>.*?</think>", "", 답).strip()
    if not 답:
        return {"답": "", "근거": [], "본것": 본것, "왜": "모델이 빈 답을 냈다"}
    근거 = 달린링크(답, 본것)
    return {"답": 가짜링크지우기(답, 본것), "근거": 근거, "본것": 본것, "왜": ""}


def 남길제목(물음: str, 길이: int = 60) -> str:
    """물음을 글 제목으로. 파일 이름이 되므로 **자리표는 뺀다.**"""
    말 = re.sub(r"\s+", " ", (물음 or "").strip()).strip(" ?？!！.。")
    말 = re.sub(r'[\\/:*?"<>|]', " ", 말).strip()
    return (말 if len(말) <= 길이 else 말[:길이 - 1] + "…") or "물음"


def 남기기(창고: Notes, 물음: str, 난것: dict) -> str | None:
    """답을 창고에 **한 장으로 남긴다.** 남길지는 부르는 쪽이 정한다.

    ★ 갈래는 `메모` 다. 답은 아직 안 갈린 것이라 사람이 보고 옮긴다 —
      바로 `개념`·`결정` 으로 넣으면 기계가 지은 것이 사람이 정한 것과 섞인다.
    """
    if not (난것 or {}).get("답"):
        return None
    제목 = 남길제목(물음)
    줄 = [난것["답"], "", f"물음: {물음.strip()}"]
    근거 = 난것.get("근거") or 난것.get("본것") or []
    if 근거:
        줄 += ["", "근거: " + " · ".join(f"[[{t}]]" for t in 근거)]
    창고.write(Note(title=제목, body="\n".join(줄) + "\n", kind=wiki.기본갈래,
                   extra={"출처": "VC", "상태": "살아있음"}))
    return 제목


def _self_check() -> None:
    import tempfile
    from pathlib import Path

    from notes import Note, Notes

    assert 남길제목("맥에서 한글 경로 왜 터지나?") == "맥에서 한글 경로 왜 터지나"
    assert "/" not in 남길제목("a/b:c?")
    assert 남길제목("   ") == "물음"

    with tempfile.TemporaryDirectory() as tmp:
        창고 = Notes(Path(tmp) / "notes")
        창고.write(Note(title="한글 경로 함정", kind="오류",
                       body="맥에서 Qt 플러그인 경로에 한글이 들면 창이 안 뜬다."))
        창고.write(Note(title="딴 이야기", kind="메모", body="점심은 국수."))
        창고.reindex()

        # 모델이 없으면 **찾은 것만** 준다 — 그것만으로도 쓸모가 있다
        난것 = 묻기(창고, None, "한글 경로")
        assert 난것["답"] == "" and 난것["본것"] and 난것["왜"] == "모델이 없다", 난것

        # ★★ **못 찾으면 모델을 부르지도 않는다.** 기억에 없는 것을 지어내면 안 된다.
        부른것 = []
        손 = lambda 말들: 부른것.append(말들) or "아무 말"
        난것 = 묻기(창고, 손, "없는말ZZZ 없는말YYY")
        assert 난것["왜"] == "창고에서 못 찾았다" and not 부른것, 난것

        # 근거에 제목이 실려야 링크를 달 수 있다
        말들 = []
        def 손2(msgs):
            말들.append(msgs[0]["content"])
            return "한글이 들면 창이 안 뜬다 [[한글 경로 함정]]. 그리고 [[없는 글]]."
        난것 = 묻기(창고, 손2, "한글 경로")
        assert "### 한글 경로 함정" in 말들[0], 말들[0][:200]
        assert 난것["답"].startswith("한글이"), 난것["답"]
        # ★ **지어낸 이름은 근거로 안 센다** — 본 것 안에 있는 것만 남는다
        assert 난것["근거"] == ["한글 경로 함정"], 난것["근거"]

        # ★★ **지어낸 링크는 답에서도 벗긴다** — 보이는 것과 세는 것이 어긋나면 안 된다
        assert "[[없는 글]]" not in 난것["답"] and "없는 글" in 난것["답"], 난것["답"]
        assert "[[한글 경로 함정]]" in 난것["답"], 난것["답"]
        assert 가짜링크지우기("[[가|보임]] 과 [[한글 경로 함정]]", ["한글 경로 함정"]) \
            == "보임 과 [[한글 경로 함정]]"

        # `<think>` 는 걷어낸다(로컬 qwen3)
        난것2 = 묻기(창고, lambda m: "<think>음…</think>짧은 답 [[한글 경로 함정]]", "한글 경로")
        assert 난것2["답"].startswith("짧은 답"), 난것2["답"]

        # 빈 답은 답이 아니다
        assert 묻기(창고, lambda m: "   ", "한글 경로")["왜"] == "모델이 빈 답을 냈다"

        # 남기기 — 갈래는 메모, 근거 링크가 달린다
        제목 = 남기기(창고, "한글 경로 왜 터지나?", 난것)
        assert 제목 == "한글 경로 왜 터지나", 제목
        글 = 창고.read(제목)
        assert 글.kind == wiki.기본갈래 and "[[한글 경로 함정]]" in 글.body, 글.body
        assert "물음: 한글 경로 왜 터지나?" in 글.body
        창고.reindex()
        assert 창고.neighbors(제목) == ["한글 경로 함정"], 창고.neighbors(제목)
        # 답이 없으면 안 남긴다
        assert 남기기(창고, "아무거나", {"답": ""}) is None

        # 찾기는 가운데 항목을 안 들인다 — 그건 씨앗이지 근거가 아니다
        창고.write(Note(title=wiki.가운데항목, body="한글 경로 이야기", kind="엔티티"))
        창고.reindex()
        assert wiki.가운데항목 not in 찾기(창고, "한글 경로")

        창고.conn.close()

    # ★★ **앞말은 모델에게만 간다** — 찾기에 섞으면 지난 말이 검색을 끌고 간다
    assert 앞말다듬기(None) == [] and 앞말다듬기([]) == []
    assert 앞말다듬기([{"role": "user", "content": " 안녕 "}]) == [
        {"role": "user", "content": "안녕"}]
    assert 앞말다듬기([{"누가": "VC", "말": "그래"}]) == [
        {"role": "assistant", "content": "그래"}]
    assert 앞말다듬기(["쓰레기", {"role": "user", "content": ""}, 3]) == []
    assert 앞말다듬기([{"role": "sudo", "content": "x"}])[0]["role"] == "user"
    긴것 = [{"role": "user", "content": str(i)} for i in range(40)]
    assert len(앞말다듬기(긴것)) == 앞말최대 and 앞말다듬기(긴것)[-1]["content"] == "39"

    print("query self-check 통과")


if __name__ == "__main__":
    import sys

    if "--check" in sys.argv:
        _self_check()
