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

# 손을 안 댄 채 이만큼 지나면 VC 표식이 저절로 화면 한가운데로 돌아온다.
# 화면 가운데는 항목들을 감싸는 네모의 중심이라, 항목이 한쪽으로 몰리면 표식이
# 구석으로 밀린다 — 두 번 눌러 되돌릴 수는 있지만 **가운데가 아닌 줄도 모르고**
# 그냥 쓰게 된다(오너 지시 2026-09-15). 기본은 30초.
되돌리기때 = (("끔", 0), ("10초", 10), ("30초", 30), ("1분", 60), ("3분", 180), ("10분", 600))
되돌리기기본 = 30


def 되돌리기초() -> int:
    """설정에 적힌 「표식 되돌리기」 초. 값이 없거나 깨졌으면 기본값. 0이면 끔.

    설정 한 줄이 깨졌다고 창이 안 뜨면 안 된다 — 아는 값만 받고 나머지는 기본으로 돌린다.
    """
    try:
        값 = int(paths.load_config().get("표식되돌리기초", 되돌리기기본))
    except (TypeError, ValueError):
        return 되돌리기기본
    return 값 if 값 in [초 for _, 초 in 되돌리기때] else 되돌리기기본


# 기계 기록(자국·죽음·상태)을 어디서 보나(결정 17). 원본은 늘 앱 자리다.
# 「둘 다」면 사람이 읽는 요약을 기록 폴더 `_VC기록/` 에도 적는다 — VC 가 꺼져도 폰 파일 앱·옵시디언에서 보인다.
기록보기때 = (("한 곳 + VC 화면", "한곳"), ("둘 다 — 기록 폴더 _VC기록/ 에도 요약", "둘다"))
기록보기기본 = "한곳"


def 기록보기() -> str:
    """설정의 「기계 기록 보기」. 모르는 값이면 기본(한 곳)."""
    값 = paths.load_config().get("기계기록보기", 기록보기기본)
    return 값 if 값 in [v for _, v in 기록보기때] else 기록보기기본
PROFILE_TITLE = "나에 대해"

QUESTIONS: dict[str, list[str]] = {
    # ★ 맨 앞 — VC 가 **이 사람을 위해 어떻게 일할지**를 정하는 질문(오너: 사소한 취향보다 이게 먼저 필요하다)
    "VC와 나": [
        "VC가 나를 부를 호칭", "나의 주요 업무", "직책·역할", "지금 제일 중요한 일·프로젝트",
        "VC에게 가장 맡기고 싶은 일", "VC가 절대 하면 안 되는 일", "VC가 혼자 정해도 되는 범위",
        "꼭 나에게 물어봐야 하는 일", "보고받고 싶은 때·방식", "급한 일로 치는 기준",
        "일에서 자주 쓰는 용어·약어", "함께 일하는 사람·팀(관계만)", "잘했다고 볼 기준",
        "VC를 주로 쓰는 때(출근·작업 중·밤)", "VC를 주로 쓰는 곳(PC·폰·원격)", "VC에게 기대하는 역할(비서·동료·검토자)",
        "틀린 답보다 싫은 것(느림·장황함·확신 없는 말)", "알림이 오면 좋은 일", "절대 알림 받기 싫은 때",
        "내 대신 써도 되는 말투(메일·메시지)", "내 이름으로 보내면 안 되는 것", "비밀로 다룰 주제",
        "VC가 스스로 배워도 되는 것", "VC가 기억하면 안 되는 것", "한 번에 맡길 수 있는 일의 크기",
        "일이 막혔을 때 먼저 할 것", "하루를 시작할 때 VC가 알려 줬으면 하는 것", "하루를 마칠 때 정리받고 싶은 것",
    ],
    "기본": [
        "불리고 싶은 이름", "나이대", "사는 지역(대략)", "쓰는 언어", "시간대",
        "성격을 한 줄로", "MBTI 같은 자기 유형", "나를 세 낱말로",
    ],
    "일": [
        "하는 일(직업)", "일하는 분야", "맡은 역할", "일하는 시간대", "주로 쓰는 도구·프로그램",
        "지금 하고 있는 일·프로젝트", "일에서 제일 중요하게 보는 것", "일하며 자주 막히는 것",
        "보고·문서 쓰는 방식 선호", "회의·연락 방식 선호",
        "주로 다루는 자료 형식(문서·표·코드·사진)", "쓰는 프로그래밍 언어·프레임워크", "일하는 회사·조직 종류",
        "마감이 잦은 일", "반복되는 귀찮은 일", "일 기록을 남기는 곳", "품질 기준·검사 방식", "배포·발행하는 곳",
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
        "쓰는 클라우드·저장소(깃허브·구글 드라이브 등, 계정 이름 말고 서비스만)", "쓰는 AI 서비스", "쓰는 글래스·웨어러블",
        "자료를 모아 두는 곳(옵시디언·노션 등)", "백업하는 곳",
    ],
    "장소": [
        "자주 가는 곳", "좋아하는 동네", "일하는 곳 종류(사무실·집·카페)", "가 보고 싶은 곳",
    ],
}

_줄꼴 = re.compile(r"^- \*\*(.+?)\*\*:\s?(.*)$")
지침칸 = "VC에게 바라는 지침"
# ★★ 오너가 안 채워도 **쓰다 보면 채워지게**(오너 지시). VC 를 쓰는 AI 가 대화에서 알게 된 것을 여기 적는다.
#   오너가 적은 답은 **절대 안 덮는다** — 짐작은 따로 두고, 질문 창에서 빈 칸에 흐리게 보여 오너가 확인한다.
알아낸칸 = "VC가 알아낸 것"
_짐작꼴 = re.compile(r"^- \*\*(.+?) / (.+?)\*\*:\s?(.*)$")


def guesses(남: dict[str, list[str]]) -> dict[tuple[str, str], str]:
    """「VC가 알아낸 것」 줄들을 (갈래, 질문) → 「답 (출처 · 날짜)」 로."""
    out = {}
    for 줄 in 남.get(알아낸칸, []):
        if m := _짐작꼴.match(줄):
            out[(m.group(1).strip(), m.group(2).strip())] = m.group(3).strip()
    return out


def learn(notes: Notes, 갈래: str, 질문: str, 답: str, 출처: str = "") -> str:
    """AI 가 알게 된 것을 짐작으로 적는다. `"saved"` · `"owner"`(오너가 이미 답함 — 안 덮음)."""
    import time as _t

    with notes._글잠금(PROFILE_TITLE):
        옛 = notes.read(PROFILE_TITLE)
        오너답, 남 = from_body(옛.body if 옛 else "")
        if 오너답.get(갈래, {}).get(질문, "").strip():
            return "owner"
        꼬리 = " · ".join(x for x in (출처.strip(), _t.strftime("%Y-%m-%d")) if x)
        새줄 = f"- **{갈래} / {질문}**: {답.strip()} ({꼬리})"
        남[알아낸칸] = [줄 for 줄 in 남.get(알아낸칸, [])
                    if not ((m := _짐작꼴.match(줄)) and (m.group(1).strip(), m.group(2).strip()) == (갈래, 질문))]
        남[알아낸칸].append(새줄)
        notes.write(Note(title=PROFILE_TITLE, body=to_body(오너답, 남), kind="preference"))
    return "saved"

# 외부 계정 연결. **토큰은 운영체제 보관소에만** 둔다(설정 파일에는 연결 이름만). 보관소가 없으면 안 받는다 —
# 남의 계정 열쇠를 평문으로 두느니 연결을 안 하는 쪽이 낫다.
CONNECTIONS = {"github": "GitHub (개인 액세스 토큰)", "notion": "Notion (통합 토큰)"}


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
        if 칸 in (지침칸, 알아낸칸):
            # 지침은 사람이 쓴 글 그대로, 짐작은 `- **갈래 / 질문**:` 꼴이라 질문·답 줄로 뜯으면 **답으로 섞인다** — 원문 줄로 둔다
            남[칸].append(줄)
            continue
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
    지침 = "\n".join(남.get(지침칸, [])).strip()
    if 지침:
        out += [f"## {지침칸}", 지침, ""]       # 맨 앞 — AI 가 이 글을 펴면 지침부터 읽는다
    for 칸 in [*QUESTIONS, *[k for k in [*답, *남] if k not in QUESTIONS and k != 지침칸]]:
        알려진 = QUESTIONS.get(칸, [])
        쌍 = 답.get(칸, {})
        차례 = [q for q in 알려진 if 쌍.get(q)] + [q for q in 쌍 if q not in 알려진 and 쌍[q]]
        줄들 = [f"- **{q}**: {쌍[q]}" for q in 차례] + 남.get(칸, [])
        if 줄들 and 칸 not in {"", None}:
            out += [f"## {칸}", *줄들, ""]
    return chr(10).join(out).rstrip() + chr(10)


def save_connection(name: str, token: str) -> str:
    """외부 계정 토큰을 보관소에 넣고 설정에는 **연결 이름만** 적는다. 틀리면 까닭 글, 됐으면 빈 글."""
    import keystore

    if name not in CONNECTIONS:
        return f"모르는 연결이다: {name}"
    if not token.strip():
        return "토큰을 적어 줘"
    if not keystore.available():
        return "이 운영체제에는 열쇠 보관소가 없어 연결을 안 받는다(평문으로 두지 않는다)"
    if not keystore.put(f"connect:{name}", token.strip()) or keystore.get(f"connect:{name}") != token.strip():
        return "보관소에 못 넣었다"
    cfg = paths.load_config()
    paths.save_config({**cfg, "connections": sorted({*(cfg.get("connections") or []), name})})
    return ""


def remove_connection(name: str) -> None:
    import keystore

    keystore.delete(f"connect:{name}")
    cfg = paths.load_config()
    paths.save_config({**cfg, "connections": [c for c in (cfg.get("connections") or []) if c != name]})


def save_profile(notes: Notes, 고친: dict[str, dict[str, str]], 지침: str | None = None) -> None:
    """고친 칸만 덮는다. 잠금 안에서 다시 읽어, 그 사이 밖·AI 가 보탠 줄을 안 지운다."""
    with notes._글잠금(PROFILE_TITLE):
        옛 = notes.read(PROFILE_TITLE)
        답, 남 = from_body(옛.body if 옛 else "")
        if 지침 is not None:
            남[지침칸] = 지침.strip().splitlines()
        for 칸, 쌍 in 고친.items():
            for q, a in 쌍.items():
                if a.strip():
                    답.setdefault(칸, {})[q] = a.strip()
                    # 오너가 직접 답했으면 그 짐작은 치운다 — 확인된 것이다
                    남[알아낸칸] = [줄 for 줄 in 남.get(알아낸칸, [])
                                if not ((m := _짐작꼴.match(줄)) and (m.group(1).strip(), m.group(2).strip()) == (칸, q))]
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


def _dialog_css(theme) -> str:
    """설정 창 옷. 주 창과 같은 결(어두운 바탕 · 붉은 강조 · 모노 계기판 글씨)에 창만의 몇 줄을 더한다.

    ★ 처음엔 윈도우 기본 탭·폼 그대로라 **이 창만 옛날 프로그램처럼** 보였다(오너: 「너무 올드하다」).
    주 창의 `theme.stylesheet()` 를 그대로 입히고 목록·칸·콤보만 같은 말투로 맞춘다.
    """
    T, css, 글자, MONO = theme.T, theme.css, theme.글자, theme.MONO
    return theme.stylesheet() + f"""
        QDialog {{ background: {T.BG.name()}; }}
        QFrame#hud {{ background: {css(T.ACCENT, 0.03)}; border: 1px solid {css(T.ACCENT, 0.14)};
                      border-radius: 8px; }}
        QListWidget#nav {{ background: transparent; border: none; outline: none;
                           font-family: {MONO}; font-size:{글자(11)}; }}
        QListWidget#nav::item {{ color: {css(T.DIM, 0.6)}; padding: 7px 10px; margin: 1px 0;
                                 border-left: 2px solid transparent; }}
        QListWidget#nav::item:hover {{ color: {T.TEXT.name()}; background: {css(T.ACCENT, 0.05)}; }}
        QListWidget#nav::item:selected {{ color: {T.ACCENT.name()}; background: {css(T.ACCENT, 0.10)};
                                          border-left: 2px solid {T.ACCENT.name()}; }}
        QLabel#ask_label {{ color: {css(T.DIM, 0.62)}; font-family: {MONO}; font-size:{글자(10)};
                            letter-spacing: 1px; padding-top: 4px; }}
        QLineEdit#field {{ background: {css(T.ACCENT, 0.03)}; border: none;
                           border-bottom: 1px solid {css(T.ACCENT, 0.18)}; border-radius: 0;
                           padding: 5px 2px; color: {T.TEXT.name()}; font-size:{글자(12)}; }}
        QLineEdit#field:focus {{ background: {css(T.ACCENT, 0.07)}; border-bottom: 1px solid {T.ACCENT.name()}; }}
        QPlainTextEdit#field {{ background: {css(T.ACCENT, 0.03)}; border: 1px solid {css(T.ACCENT, 0.18)};
                                border-radius: 4px; padding: 6px; color: {T.TEXT.name()}; font-size:{글자(12)}; }}
        QPlainTextEdit#field:focus {{ border-color: {T.ACCENT.name()}; background: {css(T.ACCENT, 0.06)}; }}
        QComboBox#pick {{ min-height: 22px; }}
        QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}   /* 안 입히면 체크무늬로 그려졌다 */
        QLabel#note {{ color: {css(T.DIM, 0.45)}; font-size:{글자(10)}; }}
        QLabel#say {{ color: {T.TEXT.name()}; font-size:{글자(11)}; padding: 8px 12px;
                      background: {css(T.ACCENT, 0.05)}; border-left: 2px solid {T.ACCENT.name()}; }}
    """


def open_dialog(win, notes: Notes):
    from PyQt5.QtWidgets import (QComboBox, QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
                                 QListWidget, QPlainTextEdit, QPushButton, QScrollArea, QStackedWidget,
                                 QVBoxLayout, QWidget)

    import theme

    창 = QDialog(win)
    창.setWindowTitle("설정 · 내 정보")
    창.resize(760, 620)
    창.setStyleSheet(_dialog_css(theme))

    # ── 왼쪽 목록 · 오른쪽 쪽. 갈래가 열다섯이라 위 탭 줄에 넣으면 이름이 잘리고 화살표로 넘겨야 했다.
    창.목록 = QListWidget()
    창.목록.setObjectName("nav")
    창.목록.setFixedWidth(150)
    창.쪽들 = QStackedWidget()
    창.목록.currentRowChanged.connect(창.쪽들.setCurrentIndex)
    창.갈래이름: list[str] = []

    def 쪽(이름: str, 풀이: str) -> tuple[QVBoxLayout, QWidget]:
        """소제목(`// 이름`) + 한 줄 설명 + 굴림 칸. 주 창 옆칸과 같은 꼴이다."""
        속 = QWidget()
        틀 = QVBoxLayout(속)
        틀.setContentsMargins(18, 14, 18, 14)
        틀.setSpacing(8)
        틀.addWidget(theme.section(이름, 풀이))
        굴림 = QScrollArea()
        굴림.setWidgetResizable(True)
        굴림.setFrameShape(QFrame.NoFrame)
        굴림.setWidget(속)
        창.쪽들.addWidget(굴림)
        창.목록.addItem(이름)
        창.갈래이름.append(이름)
        return 틀, 속

    def 줄(틀: QVBoxLayout, 이름: str, 칸) -> None:
        말 = QLabel(이름)
        말.setObjectName("ask_label")
        틀.addWidget(말)
        틀.addWidget(칸)

    # ── 화면
    화면틀, _ = 쪽("화면", "창 · 최대화 · 전체화면. F11 로 언제든 켜고 끈다.")
    창.방식 = QComboBox()
    창.방식.setObjectName("pick")
    창.방식.addItems(MODES)
    지금 = "전체화면" if win.isFullScreen() else "최대화" if win.isMaximized() else "창"
    창.방식.setCurrentText(paths.load_config().get("화면방식", 지금) if 지금 == "창" else 지금)
    줄(화면틀, "화면 방식", 창.방식)

    # 표식이 가운데에서 밀렸을 때 저절로 돌아오기까지의 시간. 표식을 두 번 누르면 바로 온다.
    창.되돌리기 = QComboBox()
    창.되돌리기.setObjectName("pick")
    for 보일, 초 in 되돌리기때:
        창.되돌리기.addItem(보일, 초)
    창.되돌리기.setCurrentIndex(max(0, 창.되돌리기.findData(되돌리기초())))
    줄(화면틀, "표식이 가운데로 돌아오기까지 (손 안 댄 시간)", 창.되돌리기)
    # 기계 기록 보기(결정 17). 기록 폴더는 메모만 — 「둘 다」일 때만 요약 한 장을 `_VC기록/` 에 둔다.
    창.기록보기 = QComboBox()
    창.기록보기.setObjectName("pick")
    for 보일, 값 in 기록보기때:
        창.기록보기.addItem(보일, 값)
    창.기록보기.setCurrentIndex(max(0, 창.기록보기.findData(기록보기())))
    줄(화면틀, "기계 기록(자국·오류) 보기", 창.기록보기)
    화면틀.addStretch(1)

    # ── 바깥 AI 제공자(오너 결정 2). 키는 보관소로 간다. 다시 켜면 적용된다.
    바깥틀, _ = 쪽("바깥 AI", "자체 엔진 대신 클라우드 모델을 쓴다. 키는 운영체제 보관소에 들어가고, 바꾸면 다시 켜야 적용된다.")
    쓰던 = paths.load_config().get("backend") or {}
    창.뒤종류 = QComboBox()
    창.뒤종류.setObjectName("pick")
    for 이름, 보일 in BACKENDS.items():
        창.뒤종류.addItem(보일, 이름)
    창.뒤종류.setCurrentIndex(max(0, 창.뒤종류.findData(쓰던.get("kind", "local"))))
    창.뒤주소 = QLineEdit(쓰던.get("base_url", ""))
    창.뒤주소.setPlaceholderText("OpenAI 호환일 때만 — http://…/v1")
    창.뒤모델 = QLineEdit(쓰던.get("model", ""))
    창.뒤모델.setPlaceholderText("제공자의 모델 이름")
    창.뒤키 = QLineEdit()
    창.뒤키.setEchoMode(QLineEdit.Password)
    창.뒤키.setPlaceholderText("비워 두면 쓰던 키 그대로")
    for 칸 in (창.뒤주소, 창.뒤모델, 창.뒤키):
        칸.setObjectName("field")
    for 이름, 칸 in (("종류", 창.뒤종류), ("주소", 창.뒤주소), ("모델", 창.뒤모델), ("API 키", 창.뒤키)):
        줄(바깥틀, 이름, 칸)
    바깥틀.addStretch(1)
    창.뒤처음 = (창.뒤종류.currentData(), 창.뒤주소.text(), 창.뒤모델.text())

    # ── VC 에게 바라는 지침 — 여러 줄 그대로. 「나에 대해」 글 맨 앞에 남아 AI 가 먼저 읽는다.
    지침틀, _ = 쪽("지침", "VC 가 늘 지켰으면 하는 것을 자유롭게 적는다. 줄 그대로 「나에 대해」 글 맨 앞에 남는다.")
    _옛글 = notes.read(PROFILE_TITLE)
    _, _옛남 = from_body(_옛글.body if _옛글 else "")
    창.지침 = QPlainTextEdit("\n".join(_옛남.get(지침칸, [])).strip())
    창.지침.setObjectName("field")
    창.지침.setPlaceholderText("예) 결론부터 한 줄로 말해 줘 · 모르면 모른다고 해 · 내 파일은 묻고 지워")
    창.지침.setMinimumHeight(260)
    지침틀.addWidget(창.지침)
    지침틀.addStretch(1)

    # ── 외부 연결 — 토큰은 운영체제 보관소에만. 설정 파일·AI 에게는 연결 이름만 간다.
    연결틀, _ = 쪽("외부 연결", "VC 가 바깥 자료를 읽을 계정. 토큰은 운영체제 보관소에만 넣고, AI 에게는 연결된 이름만 알린다.")
    이어진 = set(paths.load_config().get("connections") or [])
    창.연결칸: dict[str, QLineEdit] = {}
    for 이름, 보일 in CONNECTIONS.items():
        칸 = QLineEdit()
        칸.setObjectName("field")
        칸.setEchoMode(QLineEdit.Password)
        칸.setPlaceholderText("연결됨 — 바꾸려면 새 토큰" if 이름 in 이어진 else "토큰을 붙여 넣는다")
        창.연결칸[이름] = 칸
        줄(연결틀, 보일 + ("  · 연결됨" if 이름 in 이어진 else ""), 칸)
    # Google — 설치형 OAuth(오너 결정 8). 오너가 Google Cloud 에 「데스크톱 앱」 클라이언트를 등록해 ID·비밀을 넣고 로그인한다.
    구글풀이 = QLabel("Google (드라이브·캘린더 읽기 전용) — Google Cloud 콘솔에서 「데스크톱 앱」 OAuth 클라이언트를 만들어 "
                    "ID·비밀을 넣고 로그인한다. 받은 토큰은 보관소에만 들어간다."
                    + ("  · 연결됨" if "google" in 이어진 else ""))
    구글풀이.setObjectName("ask_label")
    구글풀이.setWordWrap(True)
    연결틀.addWidget(구글풀이)
    창.구글아이디 = QLineEdit()
    창.구글아이디.setObjectName("field")
    창.구글아이디.setPlaceholderText("클라이언트 ID (…apps.googleusercontent.com)")
    창.구글비밀 = QLineEdit()
    창.구글비밀.setObjectName("field")
    창.구글비밀.setEchoMode(QLineEdit.Password)
    창.구글비밀.setPlaceholderText("클라이언트 비밀")
    연결틀.addWidget(창.구글아이디)
    연결틀.addWidget(창.구글비밀)
    구글단추 = QPushButton("구글 로그인")
    구글단추.setObjectName("primary")

    def 구글로그인() -> None:
        import threading
        import webbrowser

        from PyQt5.QtCore import QTimer

        import google_auth

        결과: dict = {}

        def 뒤() -> None:
            try:
                google_auth.login(창.구글아이디.text(), 창.구글비밀.text(), webbrowser.open)
                결과["됨"] = True
            except google_auth.GoogleAuthError as e:
                결과["틀림"] = str(e)
            except Exception as e:
                결과["틀림"] = type(e).__name__

        창.안내.setText("브라우저에서 구글 로그인을 마쳐 줘(3분 안)…")
        구글단추.setEnabled(False)
        threading.Thread(target=뒤, daemon=True).start()
        시계 = QTimer(창)

        def 보기() -> None:                          # 뒤 실은 창을 못 만진다 — 창 실에서 결과만 읽는다
            if not 결과:
                return
            시계.stop()
            구글단추.setEnabled(True)
            창.구글비밀.clear()
            if 결과.get("됨"):
                cfg = paths.load_config()
                paths.save_config({**cfg, "connections": sorted({*(cfg.get("connections") or []), "google"})})
                창.안내.setText("구글을 연결했어(읽기 전용). AI 에게는 이름만 알린다.")
            else:
                창.안내.setText(f"구글 연결을 못 했어 — {결과['틀림']}")

        시계.timeout.connect(보기)
        시계.start(400)
        창._구글시계 = 시계

    구글단추.clicked.connect(구글로그인)
    창.구글단추 = 구글단추
    구글줄 = QHBoxLayout()
    구글줄.addStretch(1)
    구글줄.addWidget(구글단추)
    연결틀.addLayout(구글줄)
    연결틀.addStretch(1)

    # ── 폰 연결 — 폰 브라우저가 PC 서버의 /app 을 연다. 열쇠는 QR 주소의 # 뒤에만 실어 서버에 안 간다.
    import phone_app
    import phone_relay

    폰틀, _ = 쪽("폰 연결", "폰 VC 앱 「QR 찍기」(또는 폰 카메라 → 브라우저)로 QR 을 찍으면 폰에서 이 창고를 보고, "
                         "폰에서 적은 것이 여기 저장된다. 폰과 이 컴퓨터 둘 다 테일스케일이 켜져 있으면 어디서나 붙는다.")
    import tailnet

    # ★★ QR 에는 테일스케일 주소를 담는다(결정 18). 집 와이파이 주소를 담으면 폰이 다른 망으로 옮기는 순간 못 닿는다.
    #   시험이 바꿔 끼울 수 있게 창에 달아 둔다.
    창.테일주소 = tailnet.tailscale_ip
    _테일 = 창.테일주소()
    폰주소 = QLabel(f"폰 주소: {phone_app.app_url(_테일)}" if _테일
                    else "폰 주소: 테일스케일이 꺼져 있다 — 이 컴퓨터에서 켜고 창을 다시 연다")
    폰주소.setObjectName("ask_label")
    from PyQt5.QtCore import Qt

    폰주소.setTextInteractionFlags(Qt.TextSelectableByMouse)
    폰틀.addWidget(폰주소)
    폰풀이 = QLabel("QR 에는 이 컴퓨터의 열쇠가 들어 있다 — 남이 찍지 않게 2분 뒤 사라진다. "
                  "안 열리면 폰과 이 컴퓨터의 테일스케일이 같은 계정으로 켜져 있는지, 방화벽이 VC 를 막지 않는지 본다.")
    폰풀이.setObjectName("note")
    폰풀이.setWordWrap(True)
    폰틀.addWidget(폰풀이)
    창.폰QR = QLabel()
    창.폰QR.hide()
    폰단추 = QPushButton("QR 보이기")
    폰단추.setObjectName("primary")

    창.폰경고 = QLabel("")
    창.폰경고.setObjectName("note")
    창.폰경고.setWordWrap(True)
    창.폰경고.hide()
    폰집단추 = QPushButton("집 와이파이 주소로 보이기")
    폰집단추.hide()

    def _QR그리기(주소: str) -> None:
        from PyQt5.QtCore import QTimer
        from PyQt5.QtGui import QPixmap

        그림 = QPixmap()
        그림.loadFromData(phone_app.qr_png(phone_app.pair_url(주소, paths.load_config()["pair_token"])))
        창.폰QR.setPixmap(그림)
        창.폰QR.show()
        QTimer.singleShot(120_000, lambda: (창.폰QR.clear(), 창.폰QR.hide()))

    def QR보이기() -> None:
        테일 = 창.테일주소()
        if not 테일:
            # ★ 조용히 집 주소로 넘어가지 않는다(결정 21) — 알리고, 사람이 알고 고르게 한다
            창.폰QR.clear()
            창.폰QR.hide()
            창.폰경고.setText("테일스케일이 꺼져 있다 — 이 컴퓨터와 폰에서 켜고 다시 누른다. "
                            "급하면 아래 단추로 집 와이파이 주소를 보인다(같은 와이파이에서만 붙는다).")
            창.폰경고.show()
            폰집단추.show()
            return
        창.폰경고.hide()
        폰집단추.hide()
        _QR그리기(테일)

    def 집QR보이기() -> None:
        _QR그리기(phone_relay.local_ip())
        창.폰경고.setText("집 와이파이 주소로 보였다 — 폰이 같은 와이파이일 때만 붙는다.")
        창.폰경고.show()

    폰단추.clicked.connect(QR보이기)
    폰집단추.clicked.connect(집QR보이기)
    창.폰단추 = 폰단추
    창.폰집단추 = 폰집단추
    폰틀.addWidget(폰단추)
    폰틀.addWidget(창.폰경고)
    폰틀.addWidget(폰집단추)
    폰틀.addWidget(창.폰QR)
    폰틀.addStretch(1)

    # ── 내 정보 갈래들
    옛 = notes.read(PROFILE_TITLE)
    답, _옛남2 = from_body(옛.body if 옛 else "")
    짐작 = guesses(_옛남2)
    창.칸들: dict[str, dict[str, QLineEdit]] = {}

    def 칸만들기(이름: str, 질문들: list[str]) -> None:
        틀, _속 = 쪽(이름, "비워 두면 안 적는다. 적은 것만 창고의 「나에 대해」 글로 남는다.")
        창.칸들[이름] = {}
        꼬리 = QHBoxLayout()                       # 「내 질문 더하기」 — 늘 맨 아래

        def 줄더하기(q: str) -> None:
            if not q or q in 창.칸들[이름]:
                return
            칸 = QLineEdit(답.get(이름, {}).get(q, ""))
            칸.setObjectName("field")
            if (이름, q) in 짐작:
                칸.setPlaceholderText(f"VC 짐작: {짐작[(이름, q)]} — 맞으면 그대로 적어 확인")
            창.칸들[이름][q] = 칸
            말 = QLabel(q)
            말.setObjectName("ask_label")
            자리 = 틀.indexOf(꼬리위젯)
            틀.insertWidget(자리, 말)
            틀.insertWidget(자리 + 1, 칸)

        새질문 = QLineEdit()
        새질문.setObjectName("field")
        새질문.setPlaceholderText("+ 내 질문 더하기")
        더함 = QPushButton("더하기")
        더함.setObjectName("quiet")
        더함.clicked.connect(lambda: (줄더하기(새질문.text().strip()), 새질문.clear()))
        꼬리.setContentsMargins(0, 10, 0, 0)
        꼬리.addWidget(새질문, 1)
        꼬리.addWidget(더함)
        꼬리위젯 = QWidget()
        꼬리위젯.setLayout(꼬리)
        틀.addWidget(꼬리위젯)
        틀.addStretch(1)
        for q in [*질문들, *[q for q in 답.get(이름, {}) if q not in 질문들]]:
            줄더하기(q)
        창.칸들[이름]["__더하기"] = 새질문
        창.칸들[이름]["__줄더하기"] = 줄더하기

    for 이름, 질문들 in QUESTIONS.items():
        칸만들기(이름, 질문들)
    for 이름 in 답:
        if 이름 not in QUESTIONS:
            칸만들기(이름, [])

    def 셈다시() -> None:
        """목록에 갈래마다 적은 수를 붙인다 — 어디를 채웠는지 한눈에 보인다."""
        for i, 이름 in enumerate(창.갈래이름):
            쌍 = {q: w for q, w in 창.칸들.get(이름, {}).items() if not q.startswith("__")}
            적음 = sum(1 for w in 쌍.values() if w.text().strip())
            창.목록.item(i).setText(f"{이름}  {적음}/{len(쌍)}" if 쌍 else 이름)

    for 쌍 in 창.칸들.values():
        for q, w in 쌍.items():
            if not q.startswith("__"):
                w.textChanged.connect(셈다시)
    셈다시()
    창.목록.setCurrentRow(0)

    def 저장() -> None:
        고친 = {칸: {q: w.text() for q, w in 쌍.items() if not q.startswith("__")}
               for 칸, 쌍 in 창.칸들.items()}
        try:
            save_profile(notes, 고친, 창.지침.toPlainText())
        except WriteBlocked:
            # ★ 막혔는데 말이 없으면 「저장」을 눌러도 창만 남고 왜인지 모른다 — 창을 닫지 않고 알린다.
            창.안내.setText("못 저장했어 — 기록 폴더가 잠겼거나 읽기 전용이야. 적은 것은 창에 그대로 있어.")
            return
        방식 = 창.방식.currentText()
        되돌림 = int(창.되돌리기.currentData())
        paths.save_config({**paths.load_config(),
                           "화면방식": 방식, "표식되돌리기초": 되돌림,
                           "기계기록보기": str(창.기록보기.currentData())})
        apply_screen(win, 방식)
        # **바로 먹게 한다.** 다시 켜야 적용되면 골라 놓고도 그대로인 줄 안다.
        그래프 = getattr(win, "graph", None)
        if 그래프 is not None:
            그래프.자동제자리초 = float(되돌림)
        for 이름, 칸 in 창.연결칸.items():
            if 칸.text().strip():
                틀림 = save_connection(이름, 칸.text())
                칸.clear()                          # 친 토큰을 창에 남기지 않는다
                if 틀림:
                    창.안내.setText(f"{CONNECTIONS[이름]} 연결을 못 했어 — {틀림}")
                    return
                칸.setPlaceholderText("연결됨 — 바꾸려면 새 토큰")
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

    틀 = QVBoxLayout(창)
    틀.setContentsMargins(18, 16, 18, 14)
    틀.setSpacing(10)
    틀.addWidget(theme.section("설정 · 내 정보", "내 정보는 창고의 「나에 대해」 글로 남는다. AI 가 꺼내 쓰고, 옵시디언에서 고쳐도 된다."))

    판 = QFrame()
    판.setObjectName("hud")
    판틀 = QHBoxLayout(판)
    판틀.setContentsMargins(8, 8, 8, 8)
    판틀.setSpacing(0)
    판틀.addWidget(창.목록)
    판틀.addWidget(창.쪽들, 1)
    틀.addWidget(판, 1)

    안내 = QLabel("")
    안내.setObjectName("say")
    안내.setWordWrap(True)
    안내.hide()
    창.안내 = 안내
    원래setText = 안내.setText
    안내.setText = lambda 글: (원래setText(글), 안내.setVisible(bool(글)))[0]   # 말할 게 있을 때만 띠를 띄운다

    닫기 = QPushButton("닫기")
    닫기.setObjectName("quiet")
    닫기.clicked.connect(창.reject)
    저장단추 = QPushButton("저장")
    저장단추.setObjectName("primary")
    저장단추.setDefault(True)
    저장단추.setMinimumWidth(96)
    저장단추.clicked.connect(저장)
    틀.addWidget(안내)                            # 말할 게 있을 때만 뜨는 띠 — 단추 줄과 따로
    단추줄 = QHBoxLayout()
    단추줄.addStretch(1)                          # 단추는 오른쪽에 붙인다(늘어나지 않게)
    단추줄.addWidget(닫기)
    단추줄.addWidget(저장단추)
    틀.addLayout(단추줄)

    # 빈 칸 안내 글은 흐리게 — 스타일시트로는 못 바꿔서 팔레트로 준다. 안 하면 적은 값처럼 밝게 보였다.
    from PyQt5.QtGui import QPalette

    for 칸 in [*창.findChildren(QLineEdit), *창.findChildren(QPlainTextEdit)]:
        색 = 칸.palette()
        색.setColor(QPalette.PlaceholderText, theme.rgba(theme.T.DIM, 90))
        칸.setPalette(색)
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

    paths.pin_qt_plugins()      # 한글 경로면 `offscreen` 조차 못 찾는다
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
            # ★ 표식이 저절로 가운데로 돌아오기까지의 시간도 여기서 고른다.
            창.되돌리기.setCurrentIndex(창.되돌리기.findData(60))
            # 기계 기록 보기(결정 17): 기본은 「한 곳」, 여기서 「둘 다」로 바꿔 저장한다.
            assert 창.기록보기.currentData() == "한곳", 창.기록보기.currentData()
            창.기록보기.setCurrentIndex(창.기록보기.findData("둘다"))
            # 값이 바로 먹는지 보려고 그래프인 척하는 것을 하나 달아 둔다.
            win.graph = type("가짜그래프", (), {"자동제자리초": 0.0})()
            창.저장()
            글 = n.read(PROFILE_TITLE)
            assert not 글.pinned and 글.kind == "preference", (글.pinned, 글.kind)
            assert "- **좋아하는 음식**: 국수" in 글.body and "부를 때 붙일 말" in 글.body, 글.body
            assert "옵시디언에서 적은 줄" in 글.body, "밖에서 적은 칸을 지웠다"
            assert paths.load_config().get("화면방식") == "전체화면"
            assert win.isFullScreen(), "저장한 화면 방식이 안 먹는다"

            # ★★ **고른 시간이 저장되고 곧바로 먹어야 한다.** 다시 켜야 적용되면
            #   골라 놓고도 그대로인 줄 안다.
            assert paths.load_config().get("표식되돌리기초") == 60, paths.load_config()
            assert 되돌리기초() == 60, 되돌리기초()
            assert win.graph.자동제자리초 == 60.0, "고른 시간이 그래프에 바로 안 먹는다"
            assert 기록보기() == "둘다", paths.load_config().get("기계기록보기")
            paths.save_config({**paths.load_config(), "기계기록보기": "엉뚱"})
            assert 기록보기() == 기록보기기본, "모르는 값을 그대로 받는다"
            paths.save_config({**paths.load_config(), "기계기록보기": "둘다"})
            # 설정 한 줄이 깨져도 창이 죽으면 안 된다 — 아는 값만 받고 나머지는 기본으로.
            for 엉뚱 in ("스물", None, -5, 7):
                paths.save_config({**paths.load_config(), "표식되돌리기초": 엉뚱})
                assert 되돌리기초() == 되돌리기기본, f"{엉뚱!r} 를 그대로 받는다"
            paths.save_config({**paths.load_config(), "표식되돌리기초": 60})
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
                # ★ 외부 연결 — 토큰은 보관소에만, 설정에는 이름만
                _옛지움 = keystore.delete
                keystore.delete = lambda 이름: bool(_가짜보관.pop(이름, None))
                try:
                    assert save_connection("github", "") == "토큰을 적어 줘"
                    assert save_connection("없는곳", "x").startswith("모르는 연결")
                    assert save_connection("github", "ghp_시험토큰") == ""
                    assert paths.load_config()["connections"] == ["github"]
                    assert _가짜보관.get("connect:github") == "ghp_시험토큰"
                    assert "ghp_시험토큰" not in json.dumps(paths.load_config(), ensure_ascii=False), "토큰이 설정에 남았다"
                    remove_connection("github")
                    assert paths.load_config()["connections"] == [] and "connect:github" not in _가짜보관
                    keystore.available = lambda: False
                    assert "보관소가 없어" in save_connection("github", "ghp_x"), "보관소 없는 OS 에서 토큰을 받는다"
                    keystore.available = lambda: True
                finally:
                    keystore.delete = _옛지움
            finally:
                keystore.available, keystore.put, keystore.get = _옛보관

            # ★★ 지침 · VC가 알아낸 것(짐작) — 오너 답은 안 덮고, 오너가 답하면 짐작을 치운다
            save_profile(n, {}, "결론부터 한 줄로\n모르면 모른다고")
            _몸 = n.read(PROFILE_TITLE).body
            assert _몸.split("## ", 1)[1].startswith("VC에게 바라는 지침"), f"지침이 맨 앞 소제목이 아니다: {_몸[:120]}"
            assert "모르면 모른다고" in _몸
            assert learn(n, "VC와 나", "VC가 나를 부를 호칭", "대표님", "대화") == "saved"
            save_profile(n, {"음식": {"좋아하는 음식": "국수"}})    # 앞 검사에서 비웠다 — 오너 답을 다시 둔다
            assert learn(n, "음식", "좋아하는 음식", "냉면", "대화") == "owner", "오너가 적은 답을 짐작이 덮는다"
            assert "국수" in n.read(PROFILE_TITLE).body and "냉면" not in n.read(PROFILE_TITLE).body
            _, _남3 = from_body(n.read(PROFILE_TITLE).body)
            assert guesses(_남3).get(("VC와 나", "VC가 나를 부를 호칭"), "").startswith("대표님")
            짐작창 = open_dialog(win, n)
            assert "VC 짐작: 대표님" in 짐작창.칸들["VC와 나"]["VC가 나를 부를 호칭"].placeholderText()
            assert "모르면 모른다고" in 짐작창.지침.toPlainText(), "다시 열면 지침이 안 보인다"
            짐작창.칸들["VC와 나"]["VC가 나를 부를 호칭"].setText("대표님")
            짐작창.저장()
            _, _남4 = from_body(n.read(PROFILE_TITLE).body)
            assert ("VC와 나", "VC가 나를 부를 호칭") not in guesses(_남4), "오너가 확인했는데 짐작이 남는다"
            assert "모르면 모른다고" in n.read(PROFILE_TITLE).body, "저장하니 지침이 사라졌다"
            짐작창.deleteLater()

            # ★ 구글 로그인 단추 — 뒤 실에서 로그인하고 창은 타이머로 결과를 받아 연결 이름을 적는다(진짜 구글은 안 부른다)
            import time as _t

            import google_auth

            _옛로그인 = google_auth.login
            google_auth.login = lambda *a, **k: None
            try:
                구글창 = open_dialog(win, n)
                구글창.구글아이디.setText("id.apps.googleusercontent.com")
                구글창.구글비밀.setText("비밀")
                구글창.구글단추.click()
                끝 = _t.monotonic() + 5
                while "google" not in (paths.load_config().get("connections") or []) and _t.monotonic() < 끝:
                    app.processEvents()
                    _t.sleep(0.05)
                assert "google" in paths.load_config().get("connections", []), "구글 로그인 뒤 연결 이름을 안 적었다"
                assert "구글을 연결했어" in 구글창.안내.text() and not 구글창.구글비밀.text(), 구글창.안내.text()
                구글창.deleteLater()
            finally:
                google_auth.login = _옛로그인
            # ★ 폰 연결 — QR 은 단추를 눌러야 뜨고, 담긴 주소는 열쇠를 # 뒤에만 싣는다
            paths.save_config({**paths.load_config(), "pair_token": "폰열쇠시험"})
            폰창 = open_dialog(win, n)
            assert "폰 연결" in 폰창.갈래이름 and 폰창.폰QR.isHidden(), "QR 이 단추 없이 떠 있다"
            폰창.폰단추.click()
            assert not 폰창.폰QR.isHidden() and not 폰창.폰QR.pixmap().isNull(), "QR 을 못 그렸다"
            폰창.deleteLater()
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
