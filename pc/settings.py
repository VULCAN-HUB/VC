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
from notes import Note, Notes, WriteBlocked

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


BACKENDS = {"local": "자체 엔진(이 PC)", "anthropic": "Anthropic(Claude)", "gemini": "Google Gemini",
            "openai_compatible": "OpenAI 호환(주소 입력)"}


def save_backend(kind: str, base_url: str = "", model: str = "", key: str = "") -> str:
    """바깥 AI 제공자를 설정에 적는다(오너 결정 2 추천). 틀리면 까닭 글, 됐으면 빈 글.

    ★ 키는 **운영체제 보관소**에 넣는다(오너 결정 1). 보관소가 없는 OS 에서만 설정 평문으로 둔다.
    키 칸을 비우면 **쓰던 키를 그대로** 둔다 — 모델 이름만 바꾸려는데 키를 다시 치게 하면 안 된다.
    서버는 켤 때 백엔드를 만들므로 **다시 켜야** 적용된다.
    """
    import keystore

    if kind not in BACKENDS:
        return f"모르는 종류다: {kind}"
    cfg = paths.load_config()
    옛 = cfg.get("backend") if isinstance(cfg.get("backend"), dict) else {}
    if kind == "local":
        새 = {**{k: v for k, v in 옛.items() if k == "model_dir"}, "kind": "local"}
    else:
        if not model.strip():
            return "모델 이름을 적어 줘(예: claude-… · gemini-…)"
        if kind == "openai_compatible" and not base_url.strip().startswith(("http://", "https://")):
            return "주소는 http:// 나 https:// 로 시작해야 해"
        새 = {"kind": kind, "model": model.strip()}
        if kind == "openai_compatible":
            새["base_url"] = base_url.strip()
        if key.strip():
            if keystore.available() and keystore.put(keystore.키이름(새), key.strip()) \
                    and keystore.get(keystore.키이름(새)) == key.strip():
                새["api_key_in"] = "keystore"
            else:
                새["api_key"] = key.strip()      # 보관소가 없으면 평문(키를 잃는 것보다 낫다)
        elif 옛.get("kind") == kind:
            새.update({k: 옛[k] for k in ("api_key", "api_key_in") if k in 옛})   # 쓰던 키 그대로
        elif kind != "openai_compatible":
            return "처음 쓰는 제공자는 API 키를 적어 줘"
    paths.save_config({**cfg, "backend": 새})
    return ""


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

    import theme

    창 = QDialog(win)
    창.setWindowTitle("설정 · 내 정보")
    창.resize(640, 620)
    # ★ 칸 이름(탭)을 테마 색으로 못 박는다 — 안 박으면 부모 창 색을 물려받아 **어두운 바탕에 어두운 글자**가 되고,
    #   고른 칸은 흰 바탕에 옅은 글자라 거의 안 읽혔다(그려 보고 찾았다). 칸이 열다섯이라 이름이 안 보이면 못 고른다.
    창.setStyleSheet(
        f"QTabBar::tab {{ color: {theme.T.TEXT.name()}; background: {theme.css(theme.T.ACCENT, 0.06)};"
        f" padding: 5px 10px; border: 1px solid {theme.css(theme.T.ACCENT, 0.18)}; }}"
        f" QTabBar::tab:selected {{ color: {theme.T.BG.name()}; background: {theme.T.ACCENT.name()}; }}")
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

    # 바깥 AI 제공자(오너 결정 2). 키는 보관소로 간다. 다시 켜면 적용된다.
    바깥 = QWidget()
    바깥틀 = QFormLayout(바깥)
    쓰던 = paths.load_config().get("backend") or {}
    창.뒤종류 = QComboBox()
    for 이름, 보일 in BACKENDS.items():
        창.뒤종류.addItem(보일, 이름)
    창.뒤종류.setCurrentIndex(max(0, 창.뒤종류.findData(쓰던.get("kind", "local"))))
    창.뒤주소 = QLineEdit(쓰던.get("base_url", ""))
    창.뒤주소.setPlaceholderText("OpenAI 호환일 때만 — http://…/v1")
    창.뒤모델 = QLineEdit(쓰던.get("model", ""))
    창.뒤모델.setPlaceholderText("바깥 AI 일 때 — 제공자의 모델 이름")
    창.뒤키 = QLineEdit()
    창.뒤키.setEchoMode(QLineEdit.Password)
    창.뒤키.setPlaceholderText("비워 두면 쓰던 키 그대로 · 운영체제 보관소에 넣는다")
    바깥틀.addRow("종류", 창.뒤종류)
    바깥틀.addRow("주소", 창.뒤주소)
    바깥틀.addRow("모델", 창.뒤모델)
    바깥틀.addRow("API 키", 창.뒤키)
    바깥틀.addRow(QLabel("바깥 AI 를 바꾸면 VC 를 다시 켜야 적용된다."))
    창.뒤처음 = (창.뒤종류.currentData(), 창.뒤주소.text(), 창.뒤모델.text())
    판.addTab(바깥, "바깥 AI")

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
        try:
            save_profile(notes, 고친)
        except WriteBlocked:
            # ★ 막혔는데 말이 없으면 「저장」을 눌러도 창만 남고 왜인지 모른다 — 창을 닫지 않고 알린다.
            창.안내.setText("못 저장했어 — 기록 폴더가 잠겼거나 읽기 전용이야. 적은 것은 창에 그대로 있어.")
            return
        방식 = 창.방식.currentText()
        paths.save_config({**paths.load_config(), "화면방식": 방식})
        apply_screen(win, 방식)
        지금뒤 = (창.뒤종류.currentData(), 창.뒤주소.text(), 창.뒤모델.text())
        if 지금뒤 != 창.뒤처음 or 창.뒤키.text().strip():
            틀림 = save_backend(*지금뒤, 창.뒤키.text())
            창.뒤키.clear()                     # 친 키를 창에 남기지 않는다
            if 틀림:
                창.안내.setText(f"바깥 AI 를 못 바꿨어 — {틀림}")
                return
            창.뒤처음 = 지금뒤
            창.안내.setText("저장했어. 바깥 AI 는 VC 를 다시 켜면 적용돼.")
            return                              # 다시 켜야 한다는 말을 보게 창을 둔다
        창.accept()

    단추 = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
    단추.button(QDialogButtonBox.Save).setText("저장")
    단추.button(QDialogButtonBox.Cancel).setText("닫기")
    단추.accepted.connect(저장)
    단추.rejected.connect(창.reject)
    틀 = QVBoxLayout(창)
    안내 = QLabel("내 정보는 창고의 「나에 대해」 글로 남는다. AI 가 꺼내 쓰고, 옵시디언에서 고쳐도 된다.")
    안내.setWordWrap(True)
    창.안내 = 안내
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
            # 저장이 막히면 창을 안 닫고 알린다 — 적은 것이 사라지지 않게
            막힘 = open_dialog(win, n)
            막힘.칸들["음식"]["좋아하는 음식"].setText("라면")
            _옛쓰기 = n.write
            n.write = lambda *a, **k: (_ for _ in ()).throw(WriteBlocked("잠김"))
            try:
                막힘.저장()
            finally:
                n.write = _옛쓰기
            assert "못 저장" in 막힘.안내.text() and 막힘.isVisible(), "저장이 막혔는데 말없이 넘어간다"
            막힘.deleteLater()
            # ★★ 바깥 AI 제공자 — 키는 보관소로(진짜 보관소는 안 건드린다), 비우면 쓰던 키 그대로
            import json

            import keystore

            _가짜보관: dict = {}
            _옛보관 = (keystore.available, keystore.put, keystore.get)
            keystore.available = lambda: True
            keystore.put = lambda 이름, 값: (_가짜보관.__setitem__(이름, 값), True)[1]
            keystore.get = lambda 이름: _가짜보관.get(이름)
            try:
                assert save_backend("anthropic", "", "", "sk-시험") == "모델 이름을 적어 줘(예: claude-… · gemini-…)"
                assert save_backend("openai_compatible", "주소아님", "m", "") .startswith("주소는")
                assert save_backend("gemini", "", "gemini-시험", "") == "처음 쓰는 제공자는 API 키를 적어 줘"
                assert save_backend("anthropic", "", "claude-시험", "sk-시험키") == ""
                _뒤 = paths.load_config()["backend"]
                assert _뒤 == {"kind": "anthropic", "model": "claude-시험", "api_key_in": "keystore"}, _뒤
                assert _가짜보관.get("backend:anthropic") == "sk-시험키", "키가 보관소에 안 갔다"
                assert "sk-시험키" not in json.dumps(paths.load_config(), ensure_ascii=False), "키가 설정 평문에 남았다"
                assert save_backend("anthropic", "", "claude-다른", "") == ""
                assert paths.load_config()["backend"].get("api_key_in") == "keystore", "키 칸을 비웠더니 쓰던 키를 잃었다"
                # 창에서도 — 바꾸면 창을 두고 다시 켜라고 말한다, 친 키는 창에 안 남는다
                뒤창 = open_dialog(win, n)
                뒤창.뒤종류.setCurrentIndex(뒤창.뒤종류.findData("anthropic"))
                뒤창.뒤모델.setText("claude-창에서")
                뒤창.뒤키.setText("sk-창키")
                뒤창.저장()
                assert "다시 켜면" in 뒤창.안내.text() and not 뒤창.뒤키.text(), 뒤창.안내.text()
                assert paths.load_config()["backend"]["model"] == "claude-창에서"
                뒤창.deleteLater()
                assert save_backend("local") == "" and paths.load_config()["backend"]["kind"] == "local"
            finally:
                keystore.available, keystore.put, keystore.get = _옛보관
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
