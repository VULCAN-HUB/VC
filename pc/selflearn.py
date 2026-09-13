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

갈래들 = ("VC와 나", "기본", "일", "하루", "음식", "취향", "사람", "기기")
최대 = 5
출처 = "VC 대화 분석"


def _낱말(글: str) -> set[str]:
    return {w for w in re.findall(r"[0-9A-Za-z가-힣]{2,}", 글)}


def extract(말들: list[str], chat: Callable[[list[dict]], str]) -> list[tuple[str, str, str]]:
    """오너가 한 말들에서 (갈래, 질문, 답) 짐작을 뽑는다. 막이를 못 넘은 것은 버린다."""
    말들 = [m.strip()[:200] for m in 말들 if isinstance(m, str) and m.strip()]
    if not 말들:
        return []
    질문표 = "\n".join(f"- {갈래}: " + " / ".join(settings.QUESTIONS[갈래]) for 갈래 in 갈래들)
    지시 = ("아래는 한 사람이 비서에게 한 말들이다. 이 사람이 **자기에 대해 분명히 말한 것**만 골라, "
          "질문 목록의 질문에 답하는 꼴로 JSON 배열로만 답하라. 짐작·추측은 넣지 마라. 없으면 [] .\n"
          '꼴: [{"category": "갈래", "question": "질문 그대로", "answer": "짧게"}]\n\n'
          f"질문 목록:\n{질문표}\n\n한 말:\n" + "\n".join(f"- {m}" for m in 말들))
    try:
        답글 = chat([{"role": "user", "content": 지시}])
    except Exception:
        return []
    m = re.search(r"\[.*\]", 답글 or "", re.S)
    if not m:
        return []
    try:
        목록 = json.loads(m.group(0))
    except ValueError:
        return []
    # 낱말 단위로 맞추면 안 된다 — 한국어는 조사가 붙어(「대표님이라고」) 「대표님」이 안 걸린다. 한 말 안에 **글자로** 있나를 본다.
    말글 = " ".join(말들)
    out: list[tuple[str, str, str]] = []
    for 줄 in 목록 if isinstance(목록, list) else []:
        if not isinstance(줄, dict):
            continue
        갈래, 질문, 답 = (줄.get(k) for k in ("category", "question", "answer"))
        if not all(isinstance(x, str) for x in (갈래, 질문, 답)):
            continue
        갈래, 질문, 답 = 갈래.strip(), 질문.strip(), 답.strip()
        if 갈래 not in 갈래들 or 질문 not in settings.QUESTIONS.get(갈래, []) or not 답 or len(답) > 100:
            continue
        if not any(w in 말글 for w in _낱말(답)):
            continue                                  # 한 말에 없는 낱말뿐 — 지어낸 것
        out.append((갈래, 질문, 답))
        if len(out) >= 최대:
            break
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
            보낸.append(msgs[0]["content"])
            return ('설명 없이: [{"category": "VC와 나", "question": "VC가 나를 부를 호칭", "answer": "대표님"},'
                    ' {"category": "음식", "question": "좋아하는 음식", "answer": "냉면"},'
                    ' {"category": "VC와 나", "question": "나의 주요 업무", "answer": "우주선 조종"},'
                    ' {"category": "없는갈래", "question": "x", "answer": "대표님"},'
                    ' {"category": "기본", "question": "지어낸 질문", "answer": "대표님"}]')

        줄들 = [{"ts": "2026-09-13 10:00:00", "order": "앞으로 나를 대표님이라고 불러"},
               {"ts": "2026-09-13 10:01:00", "order": "점심은 냉면 먹을래"},
               {"ts": "2026-09-13 10:02:00", "heard": "회의록 열어"}]
        표시 = Path(tmp) / "vc-스스로짐작.txt"
        settings.save_profile(n, {"음식": {"좋아하는 음식": "국수"}})       # 오너가 이미 답한 것
        assert run(n, 가짜모델, 줄들, 표시) == 1, "짐작 수가 틀렸다(호칭만 새로 적혀야 한다)"
        assert "대표님이라고 불러" in 보낸[0] and "대표님이라고" not in 보낸[0].split("질문 목록")[0], "오너 말이 안 갔다"
        _, 남 = settings.from_body(n.read(settings.PROFILE_TITLE).body)
        짐작 = settings.guesses(남)
        assert 짐작.get(("VC와 나", "VC가 나를 부를 호칭"), "").startswith("대표님"), 짐작
        assert ("VC와 나", "나의 주요 업무") not in 짐작, "한 말에 없는 것(우주선 조종)을 지어냈는데 적었다"
        assert "국수" in n.read(settings.PROFILE_TITLE).body and ("음식", "좋아하는 음식") not in 짐작, "오너 답을 짐작이 덮었다"
        assert run(n, 가짜모델, 줄들, 표시) == 0 and len(보낸) == 1, "본 줄을 또 읽었다"
        assert extract(["아무 말"], lambda m: "모르겠다") == [] and extract(["x"], lambda m: 1 / 0) == []
        n.conn.close()
        del os.environ["VC_DATA"]
    print("selflearn self-check 통과")


if __name__ == "__main__":
    import sys

    if "--check" in sys.argv:
        _self_check()
