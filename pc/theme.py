"""화면의 색·글꼴·공통 부품 (결정 43).

**색은 취향이다.** 사양이 사람마다 다르듯 보기 좋은 것도 다르다 — 그래서 코드에 색을
박지 않고 테마로 뺐다. 화면에서 골라 바꾸고, 새 테마는 여기 한 덩어리만 더하면 된다.

    theme.use("midnight")        # 바꾸기
    theme.T.BG, theme.T.ACCENT   # 쓰기

`T`는 통째로 갈아 끼워지므로 **반드시 `theme.T.X`로 쓴다.** `from theme import BG`로
가져가면 테마를 바꿔도 옛 색이 남는다.
"""

from __future__ import annotations

import paths
import wiki as _위키
import json
from pathlib import Path
from types import SimpleNamespace

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QBrush, QColor, QIcon, QLinearGradient, QPainter, QPen, QPixmap
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

# ★ **창을 만들기 전에 Qt 플러그인 자리를 박는다.** 경로에 한글이 있으면 Qt 가 제
#   플러그인 폴더를 스스로 못 찾아 `cocoa`·`offscreen` 둘 다 없다며 죽는다.
#   이 파일은 창을 그리는 모듈이 다 불러 가므로 여기서 한 번 박으면 같이 산다.
#   (창을 띄우는 자리에서도 따로 부른다 — 여러 번 불러도 된다.)
paths.pin_qt_plugins()

# 고른 테마를 남기는 자리. 시험이 바꿔 끼운다 — **비어 있으면 부를 때 앱 자리를 본다.**
# 불러올 때 정하면 옛 창고 옮기기 전 자리에 박혀, 옮긴 뒤에도 기록 폴더에 테마 파일을 다시 만든다.
THEME_FILE: Path | None = None


def _theme_file() -> Path:
    return THEME_FILE or paths.기계자리("theme.json")

# 글꼴: 한글은 JetBrains Mono·Consolas에 글리프가 없어 대체 폰트로 떨어지며 자간이
# 흐트러진다. 한글 폰트를 앞에 둬야 계기판처럼 읽히면서도 안 깨진다.
#
# ★ **맥에는 「Malgun Gothic」 이 없다**(윈도우 한글 글꼴이다). 그냥 두면 Qt 가
#   아무 글꼴로나 떨어져 글자 너비가 달라진다 — 그래프 이름표 겹침 정리가 그 너비로
#   재기 때문에 **이름표가 깜박이는 것으로 나타났다**(자체점검이 「9개 갈림」으로 잡음).
#   맥 글꼴을 뒤에 붙인다: 윈도우는 앞엣것을 먼저 찾으므로 그대로고, 맥만 이쪽을 쓴다.
#   ★ 맥에서는 맥 글꼴을 **맨 앞에** 둔다 — 없는 글꼴이 앞에 있으면 Qt 가 켤 때마다
#   글꼴 목록을 뒤지느라 0.2초를 쓰고 「Malgun Gothic 없음」 경고를 찍는다.
import sys as _sys
_맥 = _sys.platform == "darwin"
MONO = ('"Apple SD Gothic Neo", "Menlo", monospace' if _맥 else
        '"Malgun Gothic", "Apple SD Gothic Neo", "Consolas", "Menlo", monospace')

# ★★ **글자 크기를 키울 길이 없었다.** 화면 곳곳에 크기가 픽셀로 **서른다섯 군데**
# 박혀 있어서, 4K 화면이나 눈이 불편한 사람은 쓸 수가 없다 — 옵시디언은 `Ctrl +/-` 로 된다.
# 한 자리에서 곱한다. 쓰는 쪽은 `theme.글자(11)` 로 적고, 배율만 바꾸면 다 같이 큰다.
#   ※ 배율은 화면이 켜질 때 설정에서 읽어 넣는다(`theme.배율바꾸기`).
_배율 = 1.0
# ★ 맥 레티나에서 픽셀로 박힌 9~11px 글씨가 너무 작았다(2026-09-18 창 점검). 설정에 값이 없을 때의 시작 배율.
기본배율 = 1.2 if _맥 else 1.0


def 배율바꾸기(값: float) -> float:
    """글자 배율을 바꾸고 지금 값을 돌려준다. 0.7~2.5 로 조인다."""
    global _배율
    _배율 = max(0.7, min(2.5, round(값, 2)))
    return _배율


def 배율() -> float:
    return _배율


def 글자(px: float) -> str:
    """`font-size` 에 넣을 글자. 배율을 곱한다."""
    return f"{max(7, round(px * _배율))}px"
SANS = ('"Apple SD Gothic Neo", sans-serif' if _맥 else
        '"Malgun Gothic", "Apple SD Gothic Neo", "Segoe UI", sans-serif')

THEMES: dict[str, dict] = {
    "vulcan": {
        "label": "불칸",
        "note": "검정 바탕에 달아오른 붉은빛. 불칸의 기본 얼굴",
        "dark": True,
        "BG": "#0a0a0b", "BG_DEEP": "#050505", "GLOW_CENTER": "#2a0d06",
        "PANEL": "#0e0d0e", "CARD": "#151314",
        "TEXT": "#f2e6e0", "DIM": "#cfc4be", "ACCENT": "#ff3d1f",
        "MUTED": "#8b7f7a", "GRID": "#cfc4be",
        # 붉은색이 주인공이라 실패를 빨강으로 쓰면 안 구분된다 — 실패는 노랑 쪽으로 뺀다.
        "WARN": "#ffb454",
    },
    "hud": {
        "label": "계기판",
        "note": "검정 바탕에 청록. 정보가 많을 때 눈이 덜 피로하다",
        "dark": True,
        "BG": "#05080f", "BG_DEEP": "#02040a", "GLOW_CENTER": "#002b33",
        "PANEL": "#070b12", "CARD": "#0d1219",
        "TEXT": "#ccf7ff", "DIM": "#e6e6e6", "ACCENT": "#00d9ff",
        "MUTED": "#5b6672", "GRID": "#e6e6e6", "WARN": "#ff8fae",
    },
    "midnight": {
        "label": "심야",
        "note": "남보라 바탕에 연보라. 오래 켜둬도 덜 차갑다",
        "dark": True,
        "BG": "#0d0b16", "BG_DEEP": "#07060d", "GLOW_CENTER": "#241a3d",
        "PANEL": "#100e1b", "CARD": "#171426",
        "TEXT": "#e6dcff", "DIM": "#d8d2e8", "ACCENT": "#a78bfa",
        "MUTED": "#5d5674", "GRID": "#d8d2e8", "WARN": "#f9a8d4",
    },
    "paper": {
        "label": "종이",
        "note": "밝은 바탕. 낮에 창가에서 보기 좋다",
        "dark": False,
        "BG": "#f4f2ee", "BG_DEEP": "#e8e5df", "GLOW_CENTER": "#dfe7ea",
        "PANEL": "#eceae5", "CARD": "#ffffff",
        "TEXT": "#1c2430", "DIM": "#3f4a58", "ACCENT": "#0f6f8c",
        "MUTED": "#a8a49c", "GRID": "#1c2430", "WARN": "#b34a6b",
    },
}

# ★★ **갈래마다 고정 색상각(hue).** 테마마다 손으로 열둘을 칠하면 테마를 하나 더할
#   때마다 열두 번 틀린다 — 각도만 정하고 밝기·진하기는 테마의 밝고 어두움에서 뽑는다.
#   갈래를 늘리면 여기 한 줄만 더하면 되고, 안 더해도 무채색으로는 나온다.
#
#   2026-09-21 에 이걸 고쳤다. 그전에는 이름표가 **옛 갈래**(에이전트·모듈·선호·장소·
#   물건·메모)뿐이라, 창고를 카파시 기준으로 옮긴 뒤 **글 151장이 전부 색을 잃고**
#   범례도 없는 이름만 늘어놓고 있었다(창을 찍어 보고 알았다).
#   `None` 은 무채색이다.
갈래색상각: dict[str, int | None] = {
    "원본": 28, "엔티티": 198, "개념": 262, "출처요약": 216, "결정": 44,
    "오류": 352, "작업": 142, "규칙": 300, "설계": 174, "skill": 226,
    "일지": 96, "메모": None,
    # 옛 갈래 — 쓰던 글이 색을 잃으면 안 된다. 범례에는 안 싣는다.
    "agent": 198, "preference": 32, "place": 168, "thing": 352, "note": None,
}

# 이름표는 **갈래 이름 그대로**다 — `wiki.갈래들` 이 이미 한국어라 옮길 것이 없다.
# 차례도 그 표를 따른다(사람이 규칙 글에서 본 차례와 같아야 헷갈리지 않는다).
KIND_LABEL = {갈래: 갈래 for 갈래 in _위키.갈래들}

T = SimpleNamespace()
name = "vulcan"


def use(theme_name: str, save: bool = False) -> bool:
    """테마를 갈아 끼운다. 모르는 이름이면 안 바꾸고 False."""
    global T, name
    spec = THEMES.get(theme_name)
    if spec is None:
        return False
    name = theme_name
    T = SimpleNamespace(
        key=theme_name, label=spec["label"], note=spec["note"], dark=spec["dark"],
        **{k: QColor(v) for k, v in spec.items()
           if k not in ("label", "note", "dark")},
    )
    if save:
        try:
            _theme_file().write_text(json.dumps({"theme": theme_name}), encoding="utf-8")
        except OSError:
            pass  # 저장 못 해도 이번 판은 바뀐 채로 돈다
    return True


def load() -> None:
    """저장해 둔 테마가 있으면 그걸로 시작한다. 없거나 깨졌으면 기본값."""
    try:
        use(json.loads(_theme_file().read_text(encoding="utf-8")).get("theme", "vulcan"))
    except (OSError, ValueError, AttributeError):
        use("vulcan")


def listing() -> list[dict]:
    return [{"key": k, "label": v["label"], "note": v["note"]} for k, v in THEMES.items()]


# --- 색 다루기 ----------------------------------------------------------


def rgba(color: QColor, alpha: int) -> QColor:
    c = QColor(color)
    c.setAlpha(alpha)
    return c


def css(color: QColor, alpha: float = 1.0) -> str:
    return f"rgba({color.red()}, {color.green()}, {color.blue()}, {alpha})"


def kind_color(kind: str) -> QColor:
    """갈래의 색. **모르는 갈래도 색이 나온다** — 무채색으로 떨어진다."""
    각 = 갈래색상각.get(kind, 갈래색상각.get(_위키.기본갈래))
    if 각 is None:
        return QColor(T.DIM) if getattr(T, "dark", True) else QColor(T.MUTED)
    진하기, 밝기 = (135, 148) if getattr(T, "dark", True) else (160, 96)
    return QColor.fromHsl(int(각) % 360, 진하기, 밝기)


# --- 공통 부품 ----------------------------------------------------------


def glyph_icon(kind: str, color: QColor, size: int = 15) -> QIcon:
    """단추 그림을 직접 그린다.

    이모지·아이콘 폰트는 PC마다 다르게 나오거나 네모로 뜬다. 선 몇 개면 되는 그림이라
    그리는 편이 확실하다. 크기에 비례해 그려서 어느 크기로도 안 무너진다.
    """
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(color, 1.4))
    p.setBrush(QBrush(Qt.NoBrush))
    s, m = float(size), size / 2.0

    if kind == "mic":  # 알약 + 받침 + 대
        p.setPen(QPen(Qt.NoPen))
        p.setBrush(QBrush(color))
        p.drawRoundedRect(QRectF(m - 2.5, 2, 5, 7.5), 2.5, 2.5)
        p.setBrush(QBrush(Qt.NoBrush))
        p.setPen(QPen(color, 1.3))
        p.drawArc(QRectF(m - 5, m - 3.5, 10, 9), 200 * 16, 140 * 16)
        p.drawLine(QPointF(m, s - 3.5), QPointF(m, s - 1.5))
    elif kind == "inspect":  # 검사표 + 체크. 도는 화살표는 "되돌리기"로 읽힌다
        p.setPen(QPen(color, 1.2))
        p.drawRoundedRect(QRectF(s * 0.17, s * 0.17, s * 0.66, s * 0.72), 1.6, 1.6)
        p.setPen(QPen(Qt.NoPen))
        p.setBrush(QBrush(color))
        p.drawRoundedRect(QRectF(s * 0.34, s * 0.08, s * 0.32, s * 0.16), 1.2, 1.2)
        p.setBrush(QBrush(Qt.NoBrush))
        p.setPen(QPen(color, 1.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPolyline(QPointF(s * 0.32, s * 0.56), QPointF(s * 0.45, s * 0.69),
                       QPointF(s * 0.70, s * 0.40))
    elif kind == "search":  # 돋보기
        p.drawEllipse(QRectF(2.5, 2.5, s - 7, s - 7))
        p.drawLine(QPointF(s - 4.5, s - 4.5), QPointF(s - 2, s - 2))
    elif kind == "panel":  # 패널 여닫기: 네모 + 세로선
        p.drawRoundedRect(QRectF(2, 2.5, s - 4, s - 5), 2, 2)
        p.drawLine(QPointF(s * 0.62, 3.5), QPointF(s * 0.62, s - 3.5))
    elif kind == "theme":  # 반쪽 채운 원
        p.drawEllipse(QRectF(2, 2, s - 4, s - 4))
        p.setPen(QPen(Qt.NoPen))
        p.setBrush(QBrush(color))
        p.drawPie(QRectF(2, 2, s - 4, s - 4), 90 * 16, 180 * 16)
    p.end()
    return QIcon(pix)


class Divider(QFrame):
    """가운데만 밝은 가로선."""

    def __init__(self) -> None:
        super().__init__()
        self.setFixedHeight(1)

    def paintEvent(self, event) -> None:
        grad = QLinearGradient(0, 0, self.width(), 0)
        grad.setColorAt(0.0, QColor(0, 0, 0, 0))
        grad.setColorAt(0.5, rgba(T.DIM, 52))
        grad.setColorAt(1.0, QColor(0, 0, 0, 0))
        QPainter(self).fillRect(self.rect(), QBrush(grad))


def section_title(text: str) -> QLabel:
    label = QLabel(f"// {text}")
    label.setStyleSheet(
        f"color:{css(T.ACCENT, 0.6)}; font-family:{MONO}; font-size:{글자(11)};"
        "font-weight:600; letter-spacing:1px; padding:2px 2px 4px 2px;")
    return label


def section(text: str, hint: str = "", action: QWidget | None = None) -> QWidget:
    """구역 이름 + 한 줄 설명. 이름만 있으면 무슨 칸인지 눌러봐야 안다.

    단추는 이름과 같은 줄, 설명은 아랫줄 통째로 — 한 줄에 다 넣으면 설명이 접히면서
    단추와 겹친다.
    """
    box = QWidget()
    lay = QVBoxLayout(box)
    lay.setContentsMargins(2, 2, 2, 4)
    lay.setSpacing(1)

    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.addWidget(section_title(text))
    row.addStretch(1)
    if action is not None:
        row.addWidget(action)
    lay.addLayout(row)

    if hint:
        sub = QLabel(hint)
        sub.setWordWrap(True)
        sub.setStyleSheet(f"color:{css(T.DIM, 0.32)}; font-size:{글자(10)};")
        lay.addWidget(sub)
    return box


def small(color, alpha: float = 1.0, size: int = 10) -> str:
    """계기판 글씨 한 줄. 같은 문자열이 네 군데 흩어져 있어 하나로 모았다."""
    return f"color:{css(color, alpha)}; font-family:{MONO}; font-size:{글자(size)}; letter-spacing:1px;"


def pop_css() -> str:
    """`[[` 목록에 **직접** 입힐 옷.

    그 목록은 주 창의 자식이 아니라 별개 최상위 창이라, 주 창에 건 스타일시트가
    안 내려간다. 검은 화면 위에 흰 바탕·파란 막대로 그것만 튀었다.
    """
    return f"""
        QListView {{ background: {T.PANEL.name()}; color: {T.TEXT.name()};
                     border: 1px solid {css(T.ACCENT, 0.22)};
                     outline: none; padding: 2px; font-size:{글자(12)};
                     selection-background-color: {css(T.ACCENT, 0.25)};
                     selection-color: {T.TEXT.name()}; }}
        QListView::item {{ padding: 3px 8px; }}
        QScrollBar:vertical {{ background: transparent; width: 5px; margin: 0; }}
        QScrollBar::handle:vertical {{ background: {css(T.ACCENT, 0.25)}; border-radius: 2px; }}
        QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
    """


def stylesheet() -> str:
    """창 전체 스타일. 테마를 바꾸면 이 문자열만 다시 만들어 붙이면 된다."""
    return f"""
        QWidget {{ background: {T.BG.name()}; color: {T.TEXT.name()};
                   font-family: {SANS}; font-size:{글자(12)}; }}
        QLabel {{ background: transparent; }}
        QFrame#panel {{ background: {css(T.PANEL, 0.96)};
                        border-left: 1px solid {css(T.ACCENT, 0.12)}; }}
        QFrame#hud {{ background: {css(T.ACCENT, 0.03)};
                      border: 1px solid {css(T.ACCENT, 0.12)}; border-radius: 8px; }}
        /* 그래프 위에 뜨는 본문 판. **비치면 안 된다** — 뒤의 점과 선이 글자를
           파고들어 읽을 수가 없다. */
        QFrame#reader {{ background: {css(T.CARD, 0.99)};
                         border: 1px solid {css(T.ACCENT, 0.22)}; border-radius: 10px; }}
        QLabel#chip {{ color: {T.ACCENT.name()}; background: {css(T.ACCENT, 0.1)};
                       border: 1px solid {css(T.ACCENT, 0.3)}; border-radius: 3px;
                       padding: 2px 8px; font-family: {MONO}; font-size:{글자(9)};
                       font-weight: 600; letter-spacing: 1px; }}
        QPushButton {{ background: transparent; color: {css(T.DIM, 0.6)};
                       border: 1px solid {css(T.DIM, 0.2)}; border-radius: 4px;
                       padding: 5px 12px; font-family: {MONO}; font-size:{글자(10)};
                       letter-spacing: 1px; }}
        QPushButton:hover {{ color: {T.TEXT.name()}; border-color: {css(T.ACCENT, 0.5)}; }}
        QPushButton#primary {{ color: {T.ACCENT.name()};
                               border-color: {css(T.ACCENT, 0.4)};
                               background: {css(T.ACCENT, 0.08)}; }}
        QPushButton#primary:hover {{ background: {css(T.ACCENT, 0.18)}; }}
        QPushButton#quiet {{ border: none; background: transparent;
                             color: {css(T.DIM, 0.45)}; padding: 5px 8px; }}
        QPushButton#quiet:hover {{ color: {T.TEXT.name()}; }}
        QPushButton#mic {{ border: 1px solid {css(T.DIM, 0.25)}; border-radius: 4px;
                           color: {css(T.DIM, 0.6)}; padding: 6px 9px; }}
        QPushButton#mic:hover {{ border-color: {css(T.ACCENT, 0.6)};
                                 color: {T.ACCENT.name()}; }}
        QPushButton#mic[listening="true"] {{ border-color: {T.ACCENT.name()};
                                             color: {T.ACCENT.name()};
                                             background: {css(T.ACCENT, 0.12)}; }}
        QLineEdit#title {{ background: transparent; border: none; padding: 0;
                           color: {T.TEXT.name()}; font-family: {SANS};
                           font-size:{글자(15)}; font-weight: 600; }}
        QLineEdit#title:focus {{ background: {css(T.ACCENT, 0.07)};
                                 border-bottom: 1px solid {css(T.ACCENT, 0.5)}; }}
        QTextBrowser {{ background: transparent; border: none;
                        color: {css(T.TEXT, 0.85)}; font-size:{글자(12)}; }}
        QTextEdit#body {{ background: transparent; border: none;
                          color: {css(T.DIM, 0.75)}; font-size:{글자(12)}; }}
        QTextEdit#body:focus {{ background: {css(T.ACCENT, 0.04)};
                                border: 1px solid {css(T.ACCENT, 0.18)};
                                border-radius: 4px; }}
        QLineEdit#ask {{ background: {css(T.ACCENT, 0.04)};
                         border: 1px solid {css(T.ACCENT, 0.2)}; border-radius: 4px;
                         padding: 6px 10px; color: {T.TEXT.name()}; font-size:{글자(12)}; }}
        QLineEdit#ask:focus {{ border-color: {css(T.ACCENT, 0.6)};
                               background: {css(T.ACCENT, 0.08)}; }}
        QComboBox#pick {{ background: {css(T.ACCENT, 0.05)};
                          border: 1px solid {css(T.ACCENT, 0.18)}; border-radius: 3px;
                          padding: 3px 8px; color: {css(T.DIM, 0.75)}; font-size:{글자(11)}; }}
        QComboBox#pick:hover {{ border-color: {css(T.ACCENT, 0.5)}; }}
        QComboBox#pick QAbstractItemView {{ background: {T.PANEL.name()};
                                            color: {T.TEXT.name()};
                                            selection-background-color: {css(T.ACCENT, 0.25)}; }}
        QScrollArea {{ background: transparent; }}
        QScrollBar:vertical {{ background: transparent; width: 5px; margin: 0; }}
        QScrollBar::handle:vertical {{ background: {css(T.ACCENT, 0.25)}; border-radius: 2px; }}
        QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
    """


load()


def _self_check() -> None:
    import tempfile

    global THEME_FILE

    # 테마마다 필요한 색이 다 있어야 한다. 하나 빠지면 그 테마에서만 터진다.
    need = {"BG", "BG_DEEP", "GLOW_CENTER", "PANEL", "CARD", "TEXT", "DIM",
            "ACCENT", "MUTED", "GRID", "WARN"}
    for key, spec in THEMES.items():
        missing = need - set(spec)
        assert not missing, f"{key}에 {missing}가 없다"
        assert "KIND" not in spec, f"{key} 에 낡은 갈래 색표가 남았다 — 색은 색상각에서 뽑는다"

    # 기본은 불칸이다.
    load()
    assert T.key == "vulcan" and T.ACCENT.name() == "#ff3d1f", T.key
    # 붉은 테마에서 실패색이 강조색과 겹치면 못 알아본다.
    assert T.WARN.name() != T.ACCENT.name()

    assert use("midnight") and T.key == "midnight"
    assert T.ACCENT.name() == "#a78bfa"
    # ★★ **갈래 색은 색상각에서 뽑는다**(2026-09-21). 테마마다 손으로 칠하던 것을
    #   걷어냈다 — 창고를 카파시 기준으로 옮긴 뒤 글 151장이 **색을 통째로 잃고** 있었다.
    import wiki as _위9

    for 갈 in _위9.갈래들:
        assert 갈 in KIND_LABEL, f"갈래 「{갈}」 이 이름표에 없다"
        assert kind_color(갈).isValid(), 갈
    # 갈래마다 **다른 색**이어야 한다 — 같으면 색이 정보가 아니다(무채색 하나는 뺀다)
    색들 = [kind_color(갈).name() for 갈 in _위9.갈래들 if 갈래색상각.get(갈) is not None]
    assert len(set(색들)) == len(색들), f"갈래 색이 겹친다: {색들}"
    # 모르는 갈래도 색이 나온다 — 화면이 비면 안 된다
    assert kind_color("없는갈래ZZZ").isValid()
    # 옛 갈래도 색을 잃지 않는다 — 쓰던 글이 있다
    assert kind_color("agent").isValid() and kind_color("note").isValid()
    # 범례에는 **지금 갈래만** 싣는다 — 옛 갈래까지 늘어놓으면 해독표가 아니라 목록이다
    assert "agent" not in KIND_LABEL and "thing" not in KIND_LABEL, KIND_LABEL
    assert T.ACCENT.name() in stylesheet(), "스타일시트가 지금 테마 색을 안 쓴다"

    assert use("paper") and T.dark is False
    assert not use("없는테마") and T.key == "paper", "모르는 이름에 바뀌었다"

    # 고른 테마는 다시 켜도 그대로다.
    old = THEME_FILE
    try:
        with tempfile.TemporaryDirectory() as tmp:
            THEME_FILE = Path(tmp) / "theme.json"
            use("midnight", save=True)
            use("hud")
            load()
            assert T.key == "midnight", "저장한 테마가 안 돌아왔다"

            # 파일이 깨져도 기본값으로 뜬다 — 테마 하나 때문에 안 뜨면 안 된다.
            THEME_FILE.write_text("깨진 내용", encoding="utf-8")
            load()
            assert T.key == "vulcan", "깨진 파일인데 기본 테마로 안 갔다"
    finally:
        THEME_FILE = old
        use("vulcan")

    assert len(listing()) == len(THEMES)
    for k in ("mic", "inspect", "search", "panel", "theme"):
        assert not glyph_icon(k, T.ACCENT).isNull(), k

    print("theme self-check 통과")


if __name__ == "__main__":
    import os
    import sys

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt5.QtWidgets import QApplication

    # QApplication을 변수에 담지 않으면 가비지 컬렉션돼 종료할 때 죽는다.
    # 출력까지 통째로 날아가 "조용한 실패"로 보인다.
    app = QApplication(sys.argv)
    _self_check()
