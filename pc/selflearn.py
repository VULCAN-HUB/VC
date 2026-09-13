"""VC 가 **스스로** 대화에서 오너 정보를 짐작한다 (오너 결정 9 — 추천대로 확정 2026-09-13).

오너가 질문 창을 다 채우지 않아도 쓰다 보면 채워지게. 대화 기록(`talk.jsonl`)의 **오너가 한 말만** 로컬 대화 모델에
주고 「이 사람에 대해 확실히 말한 것」을 JSON 으로 받는다.

★★ 막이 넷(1.5B 모델은 잘 지어낸다):
- **짐작으로만 적는다** — `settings.learn` 이라 오너가 적은 답은 절대 안 덮고, 질문 창에서 확인받는다.
- **아는 질문에만** — 질문 목록에 없는 갈래·질문은 버린다.
- **말한 것만** — 답의 낱말이 오너가 실제로 한 말에 하나도 없으면 지어낸 것으로 보고 버린다.
- **새 줄만 · 한 번에 조금** — 지난번 본 자리(시각)부터, 한 번에 다섯 개까지.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable

import settings

# ponytail: 질문 6개에 한 번씩 부른다(1.5B 로 2~4초). 갈래를 늘리면 부르는 수가 는다 — 새 대화가 있을 때만 돈다
갈래들 = ("VC와 나", "기본", "일", "음식")
최대 = 5
묶음 = 6          # 한 번에 묻는 질문 수 — 1.5B 모델은 목록이 길면 아무것도 안 뽑았다
출처 = "VC 대화 분석"


def _낱말(글: str) -> set[str]:
    return {w for w in re.findall(r"[0-9A-Za-z가-힣]{2,}", 글)}


def extract(말들: list[str], chat: Callable[[list[dict]], str]) -> list[tuple[str, str, str]]:
    """오너가 한 말들에서 (갈래, 질문, 답) 짐작을 뽑는다. 막이를 못 넘은 것은 버린다."""
    말들 = [m.strip()[:200] for m in 말들 if isinstance(m, str) and m.strip()]
    if not 말들:
        return []
    # ★ [잰 것, qwen2.5-1.5b] 질문 목록을 통째로 주고 배열로 달라면 늘 `[]` 였다. 질문을 **몇 개씩** 주고
    #   「질문: 답」 객체로 달라니 호칭·업무·음식을 제대로 뽑았다(2초). 그 꼴로 나눠 묻는다.
    어디 = {q: 갈래 for 갈래 in 갈래들 for q in settings.QUESTIONS[갈래]}
    질문들 = list(어디)
    # 낱말 단위로 맞추면 안 된다 — 한국어는 조사가 붙어(「대표님이라고」) 「대표님」이 안 걸린다. 한 말 안에 **글자로** 있나를 본다.
    말글 = " ".join(말들)
    out: list[tuple[str, str, str]] = []
    for i in range(0, len(질문들), 묶음):
        조각 = 질문들[i:i + 묶음]
        지시 = ("다음 말들을 읽고 각 질문의 답을 JSON 객체로만 답하라. 말에 없으면 빈 글자.\n"
              + "\n".join(f"- {q}" for q in 조각) + '\n꼴: {"질문": "답"}\n말:\n' + "\n".join(말들))
        try:
            답글 = chat([{"role": "user", "content": 지시}]) or ""
        except Exception:
            return out
        for 덩이 in re.findall(r"\{[^{}]*\}", 답글):
            try:
                줄 = json.loads(덩이)
            except ValueError:
                continue
            if not isinstance(줄, dict):
                continue
            질문 = 줄.get("질문", 줄.get("question"))
            답 = 줄.get("답", 줄.get("answer"))
            if not isinstance(질문, str) or not isinstance(답, str):
                continue
            질문, 답 = 질문.strip(), 답.strip()
            if 질문 not in 조각 or not 답 or len(답) > 100:
                continue                              # 모르는 질문 · 빈 답 · 너무 긴 답
            if not any(w in 말글 for w in _낱말(답)):
                continue                              # 한 말에 없는 낱말뿐 — 지어낸 것
            # ★★ 낱말이 **다른 말**에 있기만 해도 넘었다 — [잰 것] 「맡기고 싶은 일: 점심 냉면 먹기」·「하면 안 되는 일: 회의록 열기」.
            #   그 답이 든 말 한 줄과 질문을 다시 보여 주고 「예」일 때만 받는다(짧은 물음이라 1초 안팎).
            근거 = next((m for m in 말들 if any(w in m for w in _낱말(답))), "")
            try:
                확인 = chat([{"role": "user", "content":
                            f"말: {근거}\n질문: {질문}\n답: {답}\n이 말이 이 질문의 답을 분명히 말하나? 예 또는 아니오로만."}]) or ""
            except Exception:
                return out
            if "아니" in 확인 or "예" not in 확인:
                continue
            if (어디[질문], 질문, 답) not in out:
                out.append((어디[질문], 질문, 답))
            if len(out) >= 최대:
                return out
    return out


def run(notes, chat: Callable[[list[dict]], str], 줄들: list[dict], 표시: Path) -> int:
    """지난번 본 시각 뒤의 새 대화만 읽어 짐작을 적는다. 새로 적은 수."""
    try:
        지난 = 표시.read_text(encoding="utf-8").strip()
    except OSError:
        지난 = ""
    새 = [r for r in 줄들 if isinstance(r, dict) and str(r.get("ts", "")) > 지난]
    if not 새:
        return 0
    말들 = [str(r.get("order") or r.get("heard") or "") for r in 새]
    적음 = sum(settings.learn(notes, 갈래, 질문, 답, 출처) == "saved" for 갈래, 질문, 답 in extract(말들, chat))
    try:
        표시.write_text(max(str(r.get("ts", "")) for r in 새), encoding="utf-8")
    except OSError:
        pass
    return 적음


def _self_check() -> None:
    import os
    import tempfile

    from notes import Notes

    with tempfile.TemporaryDirectory() as tmp:
        os.environ["VC_DATA"] = tmp
        n = Notes(Path(tmp) / "notes")
        보낸: list = []

        def 가짜모델(msgs):
            # 진짜 1.5B 모델이 낸 꼴 그대로 — 배열이 아니라 객체를 이어 붙이고, 질문 이름 앞에 빈칸이 끼기도 한다
            보낸.append(msgs[0]["content"])
            if msgs[0]["content"].startswith("말: "):          # 확인 물음 — 제대로 짝지은 것만 「예」
                글 = msgs[0]["content"]
                맞다 = ("호칭" in 글 and "대표님" in 글) or ("좋아하는 음식" in 글 and "냉면" in 글)
                return "예" if 맞다 else "아니오"
            나온 = []
            for q, a in (("VC가 나를 부를 호칭", "대표님"), (" 좋아하는 음식", "냉면"),
                         ("나의 주요 업무", "우주선 조종"), ("지어낸 질문", "대표님"),
                         ("VC에게 가장 맡기고 싶은 일", "냉면"),):          # 낱말은 말에 있지만 짝이 엉뚱한 것
                if q.strip() in msgs[0]["content"]:
                    나온.append(json.dumps({"질문": q, "답": a}, ensure_ascii=False))
            return "```json\n" + "\n\n".join(나온) + "\n```"

        줄들 = [{"ts": "2026-09-13 10:00:00", "order": "앞으로 나를 대표님이라고 불러"},
               {"ts": "2026-09-13 10:01:00", "order": "점심은 냉면 먹을래"},
               {"ts": "2026-09-13 10:02:00", "heard": "회의록 열어"}]
        표시 = Path(tmp) / "vc-스스로짐작.txt"
        settings.save_profile(n, {"음식": {"좋아하는 음식": "국수"}})       # 오너가 이미 답한 것
        assert run(n, 가짜모델, 줄들, 표시) == 1, "짐작 수가 틀렸다(호칭만 새로 적혀야 한다)"
        assert "대표님이라고 불러" in 보낸[0], "오너 말이 안 갔다"
        _, 남 = settings.from_body(n.read(settings.PROFILE_TITLE).body)
        짐작 = settings.guesses(남)
        assert 짐작.get(("VC와 나", "VC가 나를 부를 호칭"), "").startswith("대표님"), 짐작
        assert ("VC와 나", "나의 주요 업무") not in 짐작, "한 말에 없는 것(우주선 조종)을 지어냈는데 적었다"
        assert ("VC와 나", "VC에게 가장 맡기고 싶은 일") not in 짐작, "낱말만 겹치고 짝이 엉뚱한 것(맡길 일: 냉면)을 적었다"
        assert "국수" in n.read(settings.PROFILE_TITLE).body and ("음식", "좋아하는 음식") not in 짐작, "오너 답을 짐작이 덮었다"
        _부른수 = len(보낸)
        assert run(n, 가짜모델, 줄들, 표시) == 0 and len(보낸) == _부른수, "본 줄을 또 읽었다"
        assert extract(["아무 말"], lambda m: "모르겠다") == [] and extract(["x"], lambda m: 1 / 0) == []
        n.conn.close()
        del os.environ["VC_DATA"]
    print("selflearn self-check 통과")


if __name__ == "__main__":
    import sys

    if "--check" in sys.argv:
        _self_check()
