"""설정 창 — 화면 방식(창·최대화·전체화면)과 「내 정보」.

★★ **내 정보는 설정 파일이 아니라 창고의 글(`나에 대해`)로 남긴다.** 창고는 AI 의 바깥 기억이다 —
설정 파일에 넣으면 AI 가 꺼낼 길이 없다. 옵시디언에서 고쳐도 된다.
★ **고정하지 않는다.** 답이 쌓이면 낱말이 많아 웬만한 검색에 걸리는데, 고정 글은 걸리면 맨 앞이라
물음마다 글자를 태우고 정답을 밀어낸다. AI 에게는 `hello` 가 제목을 알려 주고 필요할 때 펼친다.
질문은 여기 목록에서 오고, 사람이 더한 질문과 모르는 소제목은 **지우지 않고 그대로 둔다.**
"""

from __future__ import annotations

import re

import paths
from notes import Note, Notes

MODES = ("창", "최대화", "전체화면")
PROFILE_TITLE = "나에 대해"

QUESTIONS: dict[str, list[str]] = {
    "기본": [
        "불리고 싶은 이름", "나이대", "사는 지역(대략)", "쓰는 언어", "시간대",
        "성격을 한 줄로", "MBTI 같은 자기 유형", "나를 세 낱말로",
    ],
    "일": [
        "하는 일(직업)", "일하는 분야", "맡은 역할", "일하는 시간대", "주로 쓰는 도구·프로그램",
        "지금 하고 있는 일·프로젝트", "일에서 제일 중요하게 보는 것", "일하며 자주 막히는 것",
        "보고·문서 쓰는 방식 선호", "회의·연락 방식 선호",
    ],
    "하루": [
        "일어나는 시간", "자는 시간", "집중이 잘 되는 때", "하루에 꼭 하는 일", "쉬는 날 보내는 법",
        "출퇴근·이동 방법", "일정 관리 방식", "알림 받기 좋은 때", "방해받기 싫은 때",
    ],
    "건강": [
        "운동 습관", "조심하는 음식·알레르기", "지병·복용 중인 약(적고 싶은 만큼만)",
        "잠 습관", "스트레스 푸는 법", "건강 목표",
    ],
    "음식": [
        "좋아하는 음식", "싫어하는 음식", "커피·차 취향", "술 마시는 편인가", "자주 가는 식당 종류",
        "요리하는 편인가", "식사 시간",
    ],
    "취향": [
        "취미", "좋아하는 음악", "좋아하는 영화·드라마", "좋아하는 책·작가", "즐겨 하는 게임",
        "좋아하는 운동·경기", "좋아하는 색", "좋아하는 계절·날씨", "여행 취향", "모으는 것",
    ],
    "사람": [
        "함께 사는 사람", "반려동물", "자주 연락하는 사람(관계만)", "챙겨야 할 날(생일·기념일)",
        "선물 고르는 취향", "사람을 만날 때 편한 방식",
    ],
    "배움": [
        "요즘 배우는 것", "배우고 싶은 것", "잘하는 것", "서툰 것", "배우기 좋은 방식(글·영상·손으로)",
        "관심 있는 주제", "자주 찾아보는 곳",
    ],
    "돈": [
        "소비 성향", "아끼고 싶은 곳", "돈 쓰는 데 망설이지 않는 곳", "자주 사는 것",
        "구독 중인 서비스", "살 때 보는 기준(값·품질·브랜드)",
    ],
    "목표": [
        "올해 목표", "5년 뒤 모습", "지키고 싶은 가치", "요즘 고민", "피하고 싶은 것",
        "이루면 기쁠 작은 일", "나에게 동기가 되는 것",
    ],
    "AI에게": [
        "원하는 말투(반말·존댓말)", "대답 길이(짧게·자세히)", "설명 수준(쉽게·전문적으로)",
        "먼저 물어봐 주면 좋은 것", "하지 말았으면 하는 것", "틀렸을 때 알려 주는 방식",
        "결정은 누가(추천만·대신 골라)", "기억해 줬으면 하는 것", "잊어 줬으면 하는 것",
    ],
    "기기": [
        "쓰는 컴퓨터·운영체제", "쓰는 휴대폰", "쓰는 메모·일정 앱", "쓰는 메신저",
        "자주 쓰는 사이트", "집·일터 인터넷 환경",
    ],
    "장소": [
        "자주 가는 곳", "좋아하는 동네", "일하는 곳 종류(사무실·집·카페)", "가 보고 싶은 곳",
    ],
}

_줄꼴 = re.compile(r"^- \*\*(.+?)\*\*:\s?(.*)$")


def from_body(body: str) -> tuple[dict[str, dict[str, str]], dict[str, list[str]]]:
    """글에서 답을 읽는다. 답 줄이 아닌 것은 소제목별로 **그대로** 돌려준다(지우지 않으려고)."""
    답: dict[str, dict[str, str]] = {}
    남: dict[str, list[str]] = {}
    칸 = None
    for 줄 in body.splitlines():
        if 줄.startswith("## "):
            칸 = 줄[3:].strip()
            답.setdefault(칸, {})
            남.setdefault(칸, [])
            continue
        if 칸 is None:
            continue          # 머리말은 다시 짓는다
        m = _줄꼴.match(줄)
        if m and m.group(2).strip():
            답[칸][m.group(1).strip()] = m.group(2).strip()
        elif 줄.strip():
            남[칸].append(줄)
    return 답, 남


def to_body(답: dict[str, dict[str, str]], 남: dict[str, list[str]] | None = None) -> str:
    남 = 남 or {}
    out = [f"# {PROFILE_TITLE}", "",
           "VC 설정의 「내 정보」에서 적는다. AI 가 나를 알고 답하게 하는 글이다. 여기서 고쳐도 된다.", ""]
    for 칸 in [*QUESTIONS, *[k for k in [*답, *남] if k not in QUESTIONS]]:
        알려진 = QUESTIONS.get(칸, [])
        쌍 = 답.get(칸, {})
        차례 = [q for q in 알려진 if 쌍.get(q)] + [q for q in 쌍 if q not in 알려진 and 쌍[q]]
        줄들 = [f"- **{q}**: {쌍[q]}" for q in 차례] + 남.get(칸, [])
        if 줄들 and 칸 not in {"", None}:
            out += [f"## {칸}", *줄들, ""]
    return chr(10).join(out).rstrip() + chr(10)


def save_profile(notes: Notes, 고친: dict[str, dict[str, str]]) -> None:
    """고친 칸만 덮는다. 잠금 안에서 다시 읽어, 그 사이 밖·AI 가 보탠 줄을 안 지운다."""
    with notes._글잠금(PROFILE_TITLE):
        옛 = notes.read(PROFILE_TITLE)
        답, 남 = from_body(옛.body if 옛 else "")
        for 칸, 쌍 in 고친.items():
            for q, a in 쌍.items():
                if a.strip():
                    답.setdefault(칸, {})[q] = a.strip()
                else:
                    답.get(칸, {}).pop(q, None)
        notes.write(Note(title=PROFILE_TITLE, body=to_body(답, 남), kind="preference"))


def apply_screen(win, mode: str) -> None:
    {"최대화": win.showMaximized, "전체화면": win.showFullScreen}.get(mode, win.showNormal)()


def toggle_full(win) -> str:
    """F11. 전체화면이면 켜기 전 방식으로, 아니면 전체화면으로. 고른 것을 남긴다."""
    if win.isFullScreen():
        mode = getattr(win, "_앞화면방식", "창")
    else:
        win._앞화면방식 = "최대화" if win.isMaximized() else "창"
        mode = "전체화면"
    apply_screen(win, mode)
    paths.save_config({**paths.load_config(), "화면방식": mode})
    return mode


def open_dialog(win, notes: Notes):
    from PyQt5.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
                                 QLabel, QLineEdit, QPushButton, QScrollArea, QTabWidget,
                                 QVBoxLayout, QWidget)

    창 = QDialog(win)
    창.setWindowTitle("설정 · 내 정보")
    창.resize(640, 620)
    판 = QTabWidget()

    화면 = QWidget()
    화면틀 = QFormLayout(화면)
    창.방식 = QComboBox()
    창.방식.addItems(MODES)
    지금 = "전체화면" if win.isFullScreen() else "최대화" if win.isMaximized() else "창"
    창.방식.setCurrentText(paths.load_config().get("화면방식", 지금) if 지금 == "창" else 지금)
    창.방식.setToolTip("F11 로 전체화면을 켜고 끈다")
    화면틀.addRow("화면 방식", 창.방식)
    판.addTab(화면, "화면")

    옛 = notes.read(PROFILE_TITLE)
    답, _ = from_body(옛.body if 옛 else "")
    창.칸들: dict[str, dict[str, QLineEdit]] = {}

    def 칸만들기(이름: str, 질문들: list[str]) -> None:
        속 = QWidget()
        틀 = QFormLayout(속)
        창.칸들[이름] = {}

        def 줄더하기(q: str) -> None:
            if not q or q in 창.칸들[이름]:
                return
            칸 = QLineEdit(답.get(이름, {}).get(q, ""))
            칸.setPlaceholderText("비워 두면 안 적는다")
            창.칸들[이름][q] = 칸
            틀.insertRow(틀.rowCount() - 1, q, 칸)

        새질문 = QLineEdit()
        새질문.setPlaceholderText("내 질문 더하기")
        더함 = QPushButton("더하기")
        더함.clicked.connect(lambda: (줄더하기(새질문.text().strip()), 새질문.clear()))
        줄 = QHBoxLayout()
        줄.addWidget(새질문, 1)
        줄.addWidget(더함)
        틀.addRow(줄)
        for q in [*질문들, *[q for q in 답.get(이름, {}) if q not in 질문들]]:
            줄더하기(q)
        창.칸들[이름]["__더하기"] = 새질문
        창.칸들[이름]["__줄더하기"] = 줄더하기
        굴림 = QScrollArea()
        굴림.setWidgetResizable(True)
        굴림.setWidget(속)
        판.addTab(굴림, 이름)

    for 이름, 질문들 in QUESTIONS.items():
        칸만들기(이름, 질문들)
    for 이름 in 답:
        if 이름 not in QUESTIONS:
            칸만들기(이름, [])

    def 저장() -> None:
        고친 = {칸: {q: w.text() for q, w in 쌍.items() if not q.startswith("__")}
               for 칸, 쌍 in 창.칸들.items()}
        save_profile(notes, 고친)
        방식 = 창.방식.currentText()
        paths.save_config({**paths.load_config(), "화면방식": 방식})
        apply_screen(win, 방식)
        창.accept()

    단추 = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
    단추.button(QDialogButtonBox.Save).setText("저장")
    단추.button(QDialogButtonBox.Cancel).setText("닫기")
    단추.accepted.connect(저장)
    단추.rejected.connect(창.reject)
    틀 = QVBoxLayout(창)
    안내 = QLabel("내 정보는 창고의 「나에 대해」 글로 남는다. AI 가 꺼내 쓰고, 옵시디언에서 고쳐도 된다.")
    안내.setWordWrap(True)
    틀.addWidget(안내)
    틀.addWidget(판, 1)
    틀.addWidget(단추)
    창.저장 = 저장
    창.open()
    return 창


def _self_check() -> None:
    import os
    import tempfile
    from pathlib import Path

    전체 = [q for qs in QUESTIONS.values() for q in qs]
    assert len(전체) >= 90, f"질문이 적다: {len(전체)}"
    for 칸, qs in QUESTIONS.items():
        assert len(qs) == len(set(qs)), f"{칸} 에 같은 질문이 두 번"

    # 읽고 쓰기 왕복 + 모르는 소제목·손으로 적은 줄은 안 지운다
    몸 = to_body({"기본": {"불리고 싶은 이름": "알파"}, "일": {"내가 더한 질문": "답"}})
    답, 남 = from_body(몸 + "## 손으로 쓴 칸\n그냥 메모 줄\n")
    assert 답["기본"]["불리고 싶은 이름"] == "알파" and 답["일"]["내가 더한 질문"] == "답", 답
    assert "그냥 메모 줄" in to_body(답, 남), "손으로 적은 줄이 사라진다"
    assert "## 건강" not in 몸, "빈 칸까지 적는다"

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt5.QtWidgets import QApplication, QWidget

    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as tmp:
        옛자리 = os.environ.get("VC_DATA")
        os.environ["VC_DATA"] = tmp
        try:
            n = Notes(Path(tmp) / "notes")
            n.write(Note(title=PROFILE_TITLE, body=to_body({}, {"밖에서": ["옵시디언에서 적은 줄"]})))
            win = QWidget()
            창 = open_dialog(win, n)
            창.칸들["음식"]["좋아하는 음식"].setText("국수")
            창.칸들["AI에게"]["__줄더하기"]("부를 때 붙일 말")
            창.칸들["AI에게"]["부를 때 붙일 말"].setText("없음")
            창.방식.setCurrentText("전체화면")
            창.저장()
            글 = n.read(PROFILE_TITLE)
            assert not 글.pinned and 글.kind == "preference", (글.pinned, 글.kind)
            assert "- **좋아하는 음식**: 국수" in 글.body and "부를 때 붙일 말" in 글.body, 글.body
            assert "옵시디언에서 적은 줄" in 글.body, "밖에서 적은 칸을 지웠다"
            assert paths.load_config().get("화면방식") == "전체화면"
            assert win.isFullScreen(), "저장한 화면 방식이 안 먹는다"
            다시 = open_dialog(win, n)
            assert 다시.칸들["음식"]["좋아하는 음식"].text() == "국수", "다시 열면 답이 안 보인다"
            assert "부를 때 붙일 말" in 다시.칸들["AI에게"], "더한 질문이 다시 열면 사라진다"
            다시.칸들["음식"]["좋아하는 음식"].setText("")
            다시.저장()
            assert "좋아하는 음식" not in n.read(PROFILE_TITLE).body, "비운 답이 남는다"
            assert toggle_full(win) == "창" and not win.isFullScreen()
            assert toggle_full(win) == "전체화면" and win.isFullScreen()
            assert paths.load_config().get("화면방식") == "전체화면"
            창.deleteLater(); 다시.deleteLater(); win.deleteLater()
            n.conn.close()
        finally:
            if 옛자리 is None:
                os.environ.pop("VC_DATA", None)
            else:
                os.environ["VC_DATA"] = 옛자리
    del app
    print("settings self-check 통과")


if __name__ == "__main__":
    import sys

    if "--check" in sys.argv:
        _self_check()
