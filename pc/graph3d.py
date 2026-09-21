"""3차원으로 자라는 신경망 화면 (결정 29·30).

처음 켜면 항목 하나뿐이다. 쓸수록 기억·모듈이 항목으로 쌓이고 서로 이어지면서
제2의 두뇌가 된다.

배치는 3차원이다. 항목이 적을 때는 성기게 퍼져 있다가 **쌓일수록 구에 가까워진다.**
가운데가 세포체, 뻗어 나간 항목들이 수상돌기 — 뉴런과 같은 모양이다. 평면에 늘어놓으면
연결이 서로를 가리지만 구면에서는 깊이로 갈라진다.

말할 때는 그 말이 딛고 있는 항목들이 **순서대로 밝아진다.** 문장 속도에 맞춰 순차로
켜야 말하는 것처럼 보인다 — 한꺼번에 깜빡이면 장식으로 보인다.

성능: 발광 효과는 **말하는 항목에만** 건다. 물리 계산은 자리가 잡히면 멈추고 그 뒤로는
회전·투영만 돈다. 항목마다 효과를 걸어두면 수백 개에서 무거워진다.

색은 여기 없다 — theme.py가 들고 있다.
"""

from __future__ import annotations

import math
import random
import time

from PyQt5.QtCore import QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import (QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen,
                         QRadialGradient)
from PyQt5.QtWidgets import (
    QFrame,
    QWidget,
    QGraphicsDropShadowEffect,
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
)

import logo
import theme

ROOT = "VC"       # 가운데 항목의 이름. 부서는 불칸, 이 AI는 VC
OLD_ROOT = "이비"  # 옛 이름. 켤 때 한 번 옮긴다

# 크기 = 층위. 가운데가 제일 크고, 모듈이 그다음, 지시·자료가 제일 작다.
# 오너 2026-09-20: 항목·로고를 20% 키우고 항목 사이를 조금 벌린다.
# 정수로 두면 7 → 8(14%)이나 9(29%)밖에 못 가 20% 가 안 된다 — 실수로 둔다.
# 손 얹은 항목에 닿은 선. **한 자리에 둔다** — 장면과 덮개 두 곳에서 그리므로
# 값이 흩어지면 언젠가 갈라진다(같은 판단을 두 군데서 하면 갈라진다: `태그인가` 의 교훈).
# 오너 2026-09-20: 「활성화됐을 때 선 두께와 밝기만 줄여줘」 — 굵은 깔개(5px)를 빼고
# 가는 선 하나로. 이어진 것이 112개인 항목이 있어 굵게 밝히면 화면이 통째로 붉어졌다.
손선굵기 = 0.8
손선밝기 = 105

RADIUS = {"agent": 33.6, "skill": 19.2}
RADIUS_OTHER = 8.4


def 껍질(글수: int) -> float:
    """항목이 쌓일수록 커지는 구의 반지름. 세제곱근이라 밀도가 일정하게 유지된다.

    ★ 2026-09-20 오너 지시로 20% 벌렸다(95/46 → 114/55.2). 항목도 같이 20% 커졌으므로
      **빈 틈이 실제로 넓어진다** — 껍질만 키우면 커진 항목이 그만큼 도로 메운다.
    """
    return 114.0 + 55.2 * max(글수 - 1, 1) ** (1 / 3)


# 로고 크기를 재는 **기준 창고 크기**. 이만큼일 때 보이는 로고가 「지금 크기」다.
기준글수 = 150
기준껍질 = 껍질(기준글수)

# 내용을 펼쳐 볼 때의 배율. 고정값이라 언제 봐도 같은 거리에서 보게 된다.
FOCUS_ZOOM = 1.4


def _spread(title: str) -> str:
    """이름을 늘 같은 방식으로 흩는 값. 같은 이름은 늘 같은 값이라 깜박이지 않는다."""
    import hashlib

    return hashlib.blake2b(title.encode("utf-8"), digest_size=8).hexdigest()


class _선위층(QWidget):
    """표식(로고) **위에** 얹는 얇은 덮개. 손 얹은 항목의 선만 여기에 다시 그린다.

    장면에 그리는 선은 뷰포트 자식 위젯인 표식보다 늘 아래에 깔린다. 평소에는 그게
    맞지만(선이 글자를 가로지르면 안 된다), 손을 얹었을 때는 **그 선이 어디로 가는지가
    알고 싶은 것**이라 표식에 끊기면 안 된다. 같은 선을 한 층 위에서 한 번 더 그린다.
    """

    def __init__(self, view) -> None:
        super().__init__()
        self._view = view
        self.setAttribute(Qt.WA_TransparentForMouseEvents)   # 누름은 그대로 아래로 간다
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setAttribute(Qt.WA_TranslucentBackground)

    def paintEvent(self, event) -> None:
        v = self._view
        손 = v.hover
        if not 손 or 손 not in v.nodes:
            return
        q = QPainter(self)
        q.setRenderHint(QPainter.Antialiasing)
        for src, dst in v.edges:
            if 손 not in (src, dst):
                continue
            a, b = v.nodes.get(src), v.nodes.get(dst)
            if not (a and b) or not (a.isVisible() and b.isVisible()):
                continue
            pa, pb = v.mapFromScene(a.pos()), v.mapFromScene(b.pos())
            q.setPen(QPen(theme.rgba(theme.T.ACCENT, 손선밝기), 손선굵기))
            q.drawLine(pa, pb)
        q.end()


def node_radius(title: str, kind: str) -> float:
    if title == ROOT:
        return RADIUS["agent"]
    return RADIUS.get(kind, RADIUS_OTHER)


_LABEL_FONT = QFont()
_LABEL_FONT.setPointSize(9)


class NodeItem(QGraphicsEllipseItem):
    """항목 하나. 3차원 좌표를 들고 있고, 화면 위치는 투영 결과다."""

    def __init__(self, title: str, kind: str) -> None:
        self.title = title
        self.kind = kind
        self.r = node_radius(title, kind)
        super().__init__(-self.r, -self.r, self.r * 2, self.r * 2)

        self.p = [0.0, 0.0, 0.0]  # 3차원 위치
        self.v = [0.0, 0.0, 0.0]
        self.depth = 1.0  # 1이면 앞, 0에 가까울수록 뒤
        self.speaking = 0.0
        self.pulse = 0.0
        self.dim = False  # 초점 밖으로 밀려난 상태
        self.focused = False  # 초점에 든 상태
        self.hovered = False  # 마우스가 이 항목 위에 있다
        self.linked = False   # 손 얹힌 항목과 이어져 있다
        self.near = False     # 맨 앞줄이라 이름표를 늘 보인다

        self.setFlag(QGraphicsItem.ItemIsSelectable)
        self.setPen(QPen(Qt.NoPen))  # paint에서 직접 그린다
        self.setBrush(QBrush(Qt.NoBrush))

        self.label = QGraphicsSimpleTextItem(title, self)
        # 글꼴은 한 번만 만들어 돌려 쓴다. 항목마다 만들면 400개에 그것만 0.1초다.
        self.label.setFont(_LABEL_FONT)
        rect = self.label.boundingRect()
        self.label.setPos(-rect.width() / 2, self.r + 7)
        self._paint_label()

    def _paint_label(self) -> None:
        """이름표는 **평소에 감춘다.** 손을 얹은 것과 그에 이어진 것만 보인다.

        항목이 쌓일수록 이름표가 화면을 뒤덮어 그래프 모양 자체가 안 보인다. 이름은
        알고 싶을 때만 있으면 되고, 평소에 필요한 건 **구조**다.
        """
        if self.dim:
            color = theme.rgba(theme.T.MUTED, 70)
        elif self.hovered or self.speaking > 0.5:
            color = theme.T.ACCENT
        elif self.linked:
            color = theme.T.TEXT
        else:
            color = theme.rgba(theme.T.DIM, int(120 + 90 * self.depth))
        self.label.setBrush(QBrush(color))
        visible = (self.hovered or self.linked or self.focused
                   or self.speaking > 0.05 or self.near)
        self.label.setVisible(visible and not self.dim)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.Antialiasing)
        base = theme.T.MUTED if self.dim else theme.kind_color(self.kind)
        r = self.r
        fog = 0.25 + 0.75 * self.depth  # 뒤로 갈수록 옅게 — 깊이가 보인다
        if self.dim:
            fog *= 0.45  # 초점 밖은 옅은 회색으로 가라앉힌다. 지우지는 않는다

        if self.title == ROOT and not self.dim:
            breath = 0.5 + 0.5 * math.sin(self.pulse)
            painter.setBrush(QBrush(Qt.NoBrush))
            painter.setPen(QPen(theme.rgba(theme.T.ACCENT, int((16 + 26 * breath) * fog)), 1.0))
            painter.drawEllipse(QPointF(0, 0), r + 9 + 3 * breath, r + 9 + 3 * breath)

            # 눈금이 돌아가는 계기 링. VC가 그냥 큰 원이 아니라 코어로 읽히게 한다.
            painter.setPen(QPen(theme.rgba(theme.T.ACCENT, int(70 * fog)), 1.0))
            for i in range(24):
                a = self.pulse * 0.35 + i * math.tau / 24
                long_tick = i % 6 == 0
                r0 = r + 14
                r1 = r0 + (6 if long_tick else 3)
                painter.drawLine(
                    QPointF(math.cos(a) * r0, math.sin(a) * r0),
                    QPointF(math.cos(a) * r1, math.sin(a) * r1),
                )

        fill = QRadialGradient(QPointF(-r * 0.3, -r * 0.4), r * 2.0)
        fill.setColorAt(0.0, theme.rgba(base, int((40 + 70 * self.speaking) * fog)))
        fill.setColorAt(0.55, theme.rgba(theme.T.CARD, int(240 * fog)))
        fill.setColorAt(1.0, theme.rgba(theme.T.BG, int(248 * fog)))
        painter.setBrush(QBrush(fill))

        if self.hovered and not self.dim:
            # 손 얹힌 항목. 둘레에 흐린 띠를 깔아 빛나 보이게 한다.
            painter.setPen(QPen(theme.rgba(theme.T.ACCENT, 55), 6.0))
            painter.setBrush(QBrush(Qt.NoBrush))
            painter.drawEllipse(QPointF(0, 0), r + 2, r + 2)
            painter.setBrush(QBrush(fill))

        if self.speaking > 0.05:
            painter.setPen(QPen(theme.rgba(theme.T.ACCENT, int(255 * self.speaking)), 1.0 + 1.2 * self.speaking))
        elif self.hovered and not self.dim:
            painter.setPen(QPen(theme.T.ACCENT, 1.8))
        elif self.linked and not self.dim:
            painter.setPen(QPen(theme.rgba(theme.T.ACCENT, 190), 1.3))
        else:
            painter.setPen(QPen(theme.rgba(base, int(110 * fog)), 1.0))
        painter.drawEllipse(QPointF(0, 0), r, r)

        painter.setPen(QPen(Qt.NoPen))
        painter.setBrush(QBrush(theme.rgba(base, int((self.speaking > 0.05 and 220 or 150) * fog))))
        painter.drawEllipse(QPointF(0, 0), 2.8, 2.8)

    def set_speaking(self, on: bool, strength: float = 1.0) -> None:
        """말하는 동안만 발광 효과를 붙인다. 끝나면 떼어 낸다(성능)."""
        self.speaking = strength if on else 0.0
        if not on:
            self.setGraphicsEffect(None)
        else:
            glow = QGraphicsDropShadowEffect()
            glow.setColor(theme.rgba(theme.T.ACCENT, int(210 * strength)))
            glow.setBlurRadius(16 + 32 * strength)
            glow.setOffset(0, 0)
            self.setGraphicsEffect(glow)
        self._paint_label()
        self.update()


class 멈칫셈:
    """자전이 얼마나 고르게 도는지. **이미 재고 있던 값을 세어만 둔다.**

    프레임 하나가 밀리는 것 자체는 흔하고 문제가 아니다. 사람 눈에 걸리는 것은
    **바라던 것보다 훨씬 늦게 온 판**이다. 그래서 곱절로 나눠 센다.
    """

    def __init__(self) -> None:
        self.판 = 0
        self.두배 = 0        # 바라던 것의 2배 넘게 걸린 판
        self.다섯배 = 0      # 5배 넘게 — 여기부터는 눈에 띄게 걸린다
        self.제일느린 = 0.0  # 초
        self.요즘판 = 0      # 한 묶음 안에서만 세고 묶음이 차면 비운다
        self.요즘두배 = 0
        self.잰지 = time.perf_counter()
        self.지금간격 = 0.0   # 마지막으로 바라던 간격(초)
        self.걸린합 = 0.0     # 실제로 흐른 시간(초). 초당 몇 판인지 여기서 나온다

    # ★ **켠 뒤로 통째로 쌓으면 어느 구간이 나빴는지 못 가른다.** 세 시간을 켜 두고
    # 그동안 흡수를 두 번 돌린 자리에서 6.0% 가 나왔는데, 그것이 「그냥 켜 두면 6%」인지
    # 「무거운 일을 곁들이면 6%」인지 갈 길이 없었다. 그래서 **요즘 몫**을 따로 센다.
    한묶음 = 3000            # 33ms 기준으로 100초쯤

    def 요즘(self) -> str:
        if not self.요즘판:
            return ""
        몫 = self.요즘두배 / self.요즘판 * 100
        return f" · 요즘 {self.요즘판}판에 두 배 {self.요즘두배}({몫:.1f}%)"

    def 본다(self, gap: float, want: float) -> None:
        self.지금간격 = want
        # 쉬었다 온 판은 안 센다 — 창을 가렸다 켜거나 잠들었다 깨면 몇 초가 그냥 뛴다.
        # 그걸 세면 「멈칫」이 아니라 「안 보고 있었다」를 세게 된다.
        if want <= 0 or gap > 2.0:
            return
        self.판 += 1
        self.요즘판 += 1
        if gap > want * 5:
            self.다섯배 += 1
            self.요즘두배 += 1
        elif gap > want * 2:
            self.두배 += 1
            self.요즘두배 += 1
        self.제일느린 = max(self.제일느린, gap)
        self.걸린합 += gap
        if self.요즘판 >= self.한묶음:
            self.요즘판, self.요즘두배 = 0, 0

    def 말(self) -> str:
        if not self.판:
            return "안 돌았다"
        몫 = lambda n: n / self.판 * 100
        분 = (time.perf_counter() - self.잰지) / 60
        # ★ **「기대보다 얼마나 늦었나」만 말하면 못 읽는다.** 늦춤이 걸려 간격이
        # 늘어나 있으면 밀림 몫은 저절로 내려간다 — 느려진 것이 좋아진 것처럼 보인다.
        # **지금 바라는 간격과 실제 초당 판수**를 같이 찍어야 그 둘이 갈린다.
        초당 = self.판 / self.걸린합 if self.걸린합 else 0.0
        # ★ **바라는 간격과 실제 간격의 차이가 곧 「그리는 값」이다.**
        # 시험하는 쪽이 「초당 16판이면 62ms 인데 지금 간격은 41ms 다. 그 21ms 는
        # 어디서 나나」라고 물었다 — 그 21ms 가 한 판을 그리는 데 드는 값이다.
        # 재깍이는 **일이 끝난 뒤부터** 다음 간격을 세므로 한 판은 늘
        # 「간격 + 그리는 값」이 된다. 그걸 안 적으면 「왜 안 맞나」를 매번 다시 묻는다.
        실제 = self.걸린합 / self.판
        그리는값 = max(0.0, 실제 - self.지금간격)
        return (f"{self.판}판({분:.0f}분) · 초당 {초당:.0f}판"
                f" · 간격 바람 {self.지금간격 * 1000:.0f}ms"
                f" 실제 {실제 * 1000:.0f}ms (그리는 값 {그리는값 * 1000:.0f}ms)"
                f" · 두 배 넘게 밀림 {self.두배}({몫(self.두배):.1f}%)"
                f" · 다섯 배 {self.다섯배}({몫(self.다섯배):.1f}%)"
                f" · 제일 느린 판 {self.제일느린 * 1000:.0f}ms{self.요즘()}")

    # ★ **딴 프로세스가 읽어야 한다.** 이 셈은 창을 그리는 프로세스가 세는데
    # `--report` 는 별도 프로세스로 돈다 — 그래서 174분을 켜 두고도 진단 묶음에는
    # 늘 「안 돌았다」가 찍혔다. 값이 안 쌓인 게 아니라 **딴 자리를 본 것**이다.
    # 그러니 파일에 남긴다. 매 판 쓰면 디스크를 두들기므로 이따금만 쓴다.
    적을때마다 = 300          # 33ms 기준으로 10초쯤에 한 번

    def 적어두기(self, 자는중: bool = False) -> None:
        # 잠들 때는 판 수와 상관없이 한 번 적는다 — 그래야 「자는 중」이 남는다.
        if not 자는중 and self.판 % self.적을때마다:
            return
        try:
            import json

            import paths

            (paths.기계자리("vc-자전.json")).write_text(
                json.dumps({"판": self.판, "두배": self.두배, "다섯배": self.다섯배,
                            "제일느린": self.제일느린, "자는중": 자는중,
                            "말": ("[자는 중 — 아무도 안 봐서 안 그린다] " if 자는중 else "")
                                  + self.말()},
                           ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass          # 못 적어도 그리기가 멈출 이유는 없다

    @staticmethod
    def 읽어오기() -> str:
        """딴 프로세스에서 본 자전 고름. 없으면 「안 돌았다」."""
        try:
            import json

            import paths

            글 = (paths.기계자리("vc-자전.json")).read_text(encoding="utf-8")
            return str(json.loads(글).get("말") or "안 돌았다")
        except Exception:
            return "안 돌았다"


# 창이 하나뿐이라 하나로 둔다. 진단 묶음이 이걸 그대로 적는다.
멈칫 = 멈칫셈()


class GraphView(QGraphicsView):
    """3차원 힘 배치 + 원근 투영. 끌면 돌아가고, 놓아두면 천천히 자전한다."""

    node_clicked = pyqtSignal(str)
    # 빈 곳을 눌렀다. 열린 카드를 닫는 데 쓴다 — 사람이 제일 먼저 해 보는 몸짓이다.
    empty_clicked = pyqtSignal()
    FOCAL = 900.0

    # 가운데 빈자리의 반지름(장면 단위). 여기 표식이 앉고 항목은 이 밖으로 밀린다.
    RING = 150.0
    KEEP_HIDDEN = 300   # 안 보이는 채로 붙들어 둘 노드 수. 다시 나타나면 그대로 되산다
    # 맨 앞줄 이름표 수. 전부 보이면 글자가 화면을 덮고, 하나도 없으면 얼굴이 빈다.
    LABEL_FRONT = 24
    # 이미 보이던 이름표가 막혔을 때 **몇 프레임까지 버티는가.** 도는 동안 남의 원이
    # 스쳐 가는 것만으로 이름표가 사라지는 깜박임을 막는다. 60프레임이 1초쯤이니
    # 열둘이면 0.2초 — 잠깐 겹쳐 보이지만 떴다 사라지는 것보다 훨씬 덜 거슬린다.
    # 맥에서 300프레임을 재서 고른 값이다(짧은 깜박임 횟수):
    #   0 → 59번 · 6 → 31번 · 12 → 17번 · 그 위는 겹쳐 보이는 시간만 길어진다.
    LABEL_GRACE = 12
    # 자리를 옮길 때 한 프레임에 목표까지 가는 비율. 1.0 이면 순간이동(옛 방식).
    # 맥에서 300프레임을 재서 골랐다 — **한 프레임에 20px 넘게 튀는 걸음의 수**:
    #   1.0 → 69번(가장 큰 걸음 68px) · 0.25 → 6번(30px) · 0.15 → **0번(19px)**
    # 더 낮추면(0.08 → 10px) 더 부드럽지만 이름표가 제 점을 늦게 따라간다.
    # 0.15 면 0.25초쯤에 자리를 잡는다.
    LABEL_GLIDE = 0.15
    # 손을 얹고 이만큼 가만히 있으면 멈춘다. 읽으려는 자세로 본다.
    STILL_SEC = 0.35
    # 이만큼 안에서 노는 것은 손 떨림으로 본다. 사람 손은 완전히 안 멈춘다.
    STILL_PX = 4
    # 이만큼 넘게 가만히 있으면 **읽는 게 아니라 자리를 뜬 것**이다. 다시 돈다.
    AWAY_SEC = 6.0
    # 이만큼 아무 일도 없으면 잠든다. 사람이 자리를 비운 것으로 본다.
    잠들때까지 = 90.0
    # 잠들었을 때의 재깍이 간격(ms). 멈추는 대신 늦춘다 — 깨어날 자리가 그대로 남는다.
    잠든간격 = 1000

    def __init__(self) -> None:
        super().__init__()
        self.scene_ = QGraphicsScene(self)
        self.setScene(self.scene_)
        self.setRenderHint(QPainter.Antialiasing)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # 단추를 안 눌러도 마우스 움직임을 받아야 손 얹힘을 알 수 있다.
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)

        self.nodes: dict[str, NodeItem] = {}
        self.edges: list[tuple[str, str]] = []
        # 뜻으로만 이어진 것들. **손으로 적은 선과 섞으면 안 된다** — 하나는 사람이
        # 「이것과 저것은 이어진다」고 말한 것이고, 다른 하나는 우리가 짐작한 것이다.
        self.soft: set[tuple[str, str]] = set()
        self.rng = random.Random(7)  # 같은 그래프가 같은 모양으로 뜨게
        # 바로 앞 정리에서 실제로 보이던 이름표. 자리다툼에서 이쪽을 먼저 앉힌다
        # (`_resolve_labels` 참조). 비어 있으면 첫 프레임이라 평소 차례대로 간다.
        self._전에보임: set[str] = set()
        self._마지막자리: dict[str, tuple[float, float]] = {}   # 마지막으로 잘 앉았던 자리
        self._막힌횟수: dict[str, int] = {}                     # 몇 프레임째 막혀 있는가
        self._그린자리: dict[str, tuple[float, float]] = {}     # 화면에 실제로 그린 자리(미끄러지는 중일 수 있다)
        self.yaw = 0.0
        self.tilt = 0.26
        self._drag: QPointF | None = None
        self._zoom = 1.0
        self._zoom_target = 1.0
        self._center = QPointF(0, 0)
        self._center_target = QPointF(0, 0)
        # 표식을 두 번 눌러 「제자리로」를 했는가. 그동안은 가운데가 원점에 붙는다.
        self._원점에두기 = False
        # 손을 안 댄 채 이만큼 지나면 표식을 저절로 제자리로 되돌린다(초). **0이면 끔.**
        # 값은 설정에서 정하고 `ui` 가 넣어 준다 — 여기 기본은 「아무것도 안 함」이다.
        self.자동제자리초 = 0.0
        # 키보드로도 그래프를 돌 수 있어야 한다(오너 2026-09-20) — 초점을 받게 둔다
        self.setFocusPolicy(Qt.StrongFocus)
        self.focus: set[str] = set()
        # 장면에서 뺀 노드를 한 판 동안 붙들어 두는 자리(위 `load` 설명 참고).
        self._retired: list = []
        self._focus_zoom: float | None = None
        self.hover: str | None = None  # 마우스가 얹힌 항목
        self.tick = 0

        # 가운데 항목 자리에는 표식이 앉는다. 화면 부품이라 장면이 아니라 뷰포트에
        # 얹는다 — 배율이 바뀌어도 선이 안 뭉개지고, 크기는 구멍에 맞춰 따라간다.
        self.mark = logo.VulcanMark(240)
        self.mark.setParent(self.viewport())
        self.mark.show()

        # ★★ **손 얹은 항목의 선만 표식 위로 지나간다**(오너 2026-09-20).
        #   평소 선은 표식을 피해 간다 — 표식은 뒤가 비치는 위젯이라 선이 획 사이로
        #   보여 글자를 가로지르는 것처럼 읽혔다. 그런데 손을 얹었을 때는 그 선이
        #   **어디로 가는지가 알고 싶은 것**이므로 표식이 가리면 안 된다.
        #   장면(선)과 위젯(표식)은 층이 달라 `setZValue` 로는 못 올린다 — 표식 위에
        #   얇은 덮개를 하나 더 얹고 그 선만 여기 다시 그린다.
        self._선위층 = _선위층(self)
        self._선위층.setParent(self.viewport())
        self._선위층.raise_()
        self._선위층.show()

        self.둘레중 = ""      # 이 항목 둘레만 보는 중(로컬 그래프)
        self._settling = 0
        self._last_spin = time.perf_counter()
        self._slow = 0        # 연달아 밀린 프레임 수
        self._깬때 = time.perf_counter()   # 마지막으로 사람 손이 닿은 때
        self._잠듦 = False                 # 자는 중이라고 파일에 적어 뒀나
        # 뒤에서 파일을 훑는 동안은 연출을 쉰다. 그리는 값이 훑기를 굶긴다.
        self._indexing = False
        self._release = QTimer(self)
        self._release.setSingleShot(True)
        self._release.timeout.connect(self.clear_focus)

        self.physics = QTimer(self)
        self.physics.timeout.connect(self.step_layout)
        # 다시 그릴 때마다 새로 만들지 않고 이 하나를 다시 쓴다.
        self._stopper = QTimer(self)
        self._stopper.setSingleShot(True)
        self._stopper.timeout.connect(self.physics.stop)
        self.spin = QTimer(self)
        self.spin.timeout.connect(self._spin)
        self.spin.start(33)

    @property
    def indexing(self) -> bool:
        return self._indexing

    @indexing.setter
    def indexing(self, on: bool) -> None:
        """훑는 동안은 그래프도 표식도 쉰다. 그리기가 훑기를 굶기면 안 된다."""
        self._indexing = on
        self.mark.set_paused(on)

    def _spin(self) -> None:
        """천천히 도는 연출. **그리는 값이 여기 다 실린다.**

        도는 것 자체는 싸지만 매번 화면을 다시 그린다 — 항목 수백 개에 배경·연결선까지
        칠하는 값이다. 그게 화면 실을 채우면 뒤에서 도는 색인이 굶는다(2만 개 첫 색인이
        6초에서 2분으로 늘었다).

        그래서 둘을 건다: **뒤에서 훑는 동안은 쉬고**, 프레임이 밀리면 스스로 간격을
        벌린다. 자전은 읽는 걸 돕는 연출이지 그 자체가 목적이 아니다.
        """
        if self.indexing:
            return

        # ★★ **한동안 손을 안 대면 표식이 저절로 제자리로 온다.** 표식을 두 번 누르는
        #   길만 두면 「가운데가 아닌 줄도 모르고」 그냥 쓰게 된다 — 오너가 그래서
        #   시간을 정할 수 있게 해 달라고 했다. 시간은 설정에서 정한다(0이면 끔).
        #   **재우기보다 앞에 둔다.** 뒤에 두면 잠드는 90초보다 긴 값을 고른 순간
        #   영영 안 돌아온다 — 자는 동안에도 재깍이는 1초에 한 번 여기까지 온다.
        if (self.자동제자리초 > 0 and not self._원점에두기
                and time.perf_counter() - self._깬때 >= self.자동제자리초):
            self.제자리로()          # 제자리로 오면 붙들리므로 다시 안 불린다

        # ★★ **보는 사람이 없으면 그리지 않는다.**
        # 네 시간을 아무도 안 만졌는데 **코어 하나를 91% 태우고 있었다.** 자전은
        # 읽는 걸 돕는 연출인데, 아무도 안 보면 도울 것이 없다. 20년 켜 둘 물건에서
        # 이건 배터리와 팬으로 사람이 바로 느낀다.
        #
        # 창이 가려졌거나(최소화·안 보임) 한참 아무 일도 없으면 **재깍이를 늦춘다.**
        # 멈추지 않고 늦추는 이유는, 깨어날 때 다시 걸 자리를 안 만들기 위해서다 —
        # 1초에 한 번은 사실상 0이다.
        # ★ **표식도 같이 재운다.** 그래프만 재웠더니 「앞에 있고 손 안 댐」이
        # 21% 로만 내려갔다(최소화는 1.8%). 표식이 **불티 1800개를 33ms마다**
        # 따로 그리기 때문이다 — 재우는 자리가 하나 더 있었다.
        # 「그리는 것이 하나뿐」이라고 여긴 것이 틀렸다.
        if not self.isVisible() or self.window().isMinimized():
            self._재우기(True)
            return
        if time.perf_counter() - self._깬때 > self.잠들때까지:
            self._재우기(True)
            return
        if self.spin.interval() >= self.잠든간격:
            self._재우기(False)            # 깨어났다. 처음 빠르기로 되돌린다

        now = time.perf_counter()
        gap = now - self._last_spin
        self._last_spin = now
        want = self.spin.interval()
        # **한 판 밀린 것으로는 안 늦춘다.** 디스크 한 번, 파이썬 청소 한 번이면
        # 프레임은 그냥 밀린다. 그걸 곧장 「감당 밖」으로 읽으면 33→200ms 로 다섯 판
        # 만에 떨어지고 되돌아오는 데는 열 판이 넘게 걸린다 — 오너가 「중간중간
        # 멈칫한다」고 본 것이 이 되돌아오는 구간이다. 연달아 밀릴 때만 늦춘다.
        # ★ **여기서 재고 버리던 값을 남긴다.** 「부드러운가」는 화면을 찍어서 보는
        # 쪽이 구조적으로 못 재는 자리다 — 두 장 사이에 무슨 일이 있었는지 안 남는다.
        # 오너가 「중간중간 멈칫한다」고 본 것을 열다섯 판 동안 아무도 못 봤는데,
        # **간격은 이미 매 판 재고 있었고 쓰고 버렸다.** 세어 두면 숫자가 말한다.
        멈칫.본다(gap, want / 1000.0)
        멈칫.적어두기()
        self._slow = self._slow + 1 if gap > want / 1000.0 * 2.2 else 0
        if self._slow >= 3:
            self._slow = 0
            # 200ms 는 초당 다섯 장이라 그 자체가 멈칫으로 보인다. 훑는 동안은
            # 위에서 통째로 쉬므로 여기까지 늦출 일이 없다.
            self.spin.setInterval(min(120, int(want * 1.6)))
        elif want > 33 and gap < want / 1000.0 * 1.25:
            self.spin.setInterval(max(33, int(want * 0.8)))

        # **손을 얹으면 멈춘다.** 도는 동안에는 겨냥한 점이 이미 옮겨가 있어서 누르면
        # 빗나간다 — 낯선 PC 에서 「큰 원을 겨냥해 누르기도 빗나갔다」로 걸렸고,
        # 어느 종류가 더 큰지 읽을 수도 없었다. 읽으려고 다가온 순간이 멈출 때다.
        # 손을 얹고 **가만히 있을 때만** 멈춘다. 겨누거나 읽는 자세가 그것이다.
        # **빈 자리에 손이 얹혀 있는 것은 겨누는 게 아니다.** `underMouse()` 만 보면
        # 마우스를 그래프 위 아무 데나 두고 손을 떼는 순간 멈췄다 — 오너가 「가만히
        # 냅두면 멈춘다」고 본 것이 이것이다. 겨눌 것이 있을 때만 멈춘다.
        # 오래 가만히 있으면 읽는 게 아니라 자리를 뜬 것이라 다시 돈다.
        섰던지 = now - getattr(self, "_moved_at", 0.0)
        멈출 = (self.hover is not None
                and self.STILL_SEC < 섰던지 < self.AWAY_SEC)
        if self._drag is None and not 멈출:
            self.yaw += 0.0032  # 아주 느리게. 빠르면 읽는 걸 방해한다
        self.tick = (self.tick + 1) % 10000
        root = self.nodes.get(ROOT)
        if root is not None:
            root.pulse += 0.06
        self.project()
        self._apply_view()

    # --- 그래프 ---------------------------------------------------------

    def load(self, graph: dict[str, list[str]], kinds: dict[str, str],
             soft: dict[str, list[str]] | None = None) -> None:
        # **장면을 비우지 않는다.** `scene_.clear()` 는 항목을 C++ 에서 즉시 없애는데,
        # 화면·물리·이름표가 그 항목을 아직 향하고 있으면 프로세스가 통째로 죽는다
        # (파이썬 오류가 아니라 접근 위반이라 잡을 수도 없다).
        #
        # 대신 **있던 것은 다시 쓰고, 없어진 것만 뺀다.** 다시 그릴 때마다 항목을
        # 새로 만들지 않으니 자리도 유지되어 화면이 덜 튄다.
        self.physics.stop()

        titles = set(graph) | {t for links in graph.values() for t in links} | {ROOT}
        # 처음 뿌리는 반지름을 **자리 잡을 반지름 근처로** 잡는다. 좁게 몰아 놓으면
        # 격자 칸이 다 뭉쳐서 첫 걸음들이 전부 대 전부가 된다 — 400개에서 한 걸음이
        # 25ms가 아니라 83ms였다.
        spread = 95.0 + 46.0 * max(len(titles) - 1, 1) ** (1 / 3)

        # **장면에서 빼지 않는다. 보이기만 끈다.**
        #
        # 빼는 순간 파이썬이 그 객체를 없애는데, 아직 그리는 중인 Qt 가 사라진 것을
        # 그리다 프로세스째 죽는다 — 파이썬 오류가 아니라 접근 위반이라 잡히지도
        # 않는다. 한 박자 늦춰 놓아주는 것도 모자랐다.
        #
        # 안 보이는 노드는 물리에서도 빠지므로(아래 `step_layout`) 값이 거의 안 든다.
        # 다시 나타나면 그대로 되살아난다 — 자리도 유지되어 화면이 덜 튄다.
        for gone, node in self.nodes.items():
            if gone not in titles:
                node.setVisible(False)
        self.edges.clear()

        # 안 보이는 것이 끝없이 쌓이면 20년 뒤에는 그것만 수만 개다. 넉넉히 두되
        # 한도를 넘으면 **오래된 것부터** 장면에서 뺀다. 빼는 것은 그리기가 끝난
        # 뒤여야 안전하므로, 다음 번 `load` 에서 놓아준다(`_retired`).
        self._retired.clear()
        hidden = [t for t, n in self.nodes.items() if not n.isVisible()]
        for gone in hidden[:max(0, len(hidden) - self.KEEP_HIDDEN)]:
            node = self.nodes.pop(gone)
            self.scene_.removeItem(node)
            self._retired.append(node)

        for title in sorted(titles):
            old = self.nodes.get(title)
            if old is not None:
                old.kind = kinds.get(title, "note")
                old.focused = False
                old.hovered = False
                old.linked = False
                old.setVisible(True)      # 지난번에 꺼 뒀을 수 있다
                continue
            node = NodeItem(title, kinds.get(title, "note"))
            if title != ROOT:
                # 구면에 고르게 뿌린다. 한 방향에 뭉치면 물리가 풀어내는 데 오래 걸린다.
                theta = self.rng.uniform(0, math.tau)
                phi = math.acos(self.rng.uniform(-1, 1))
                d = spread * self.rng.uniform(0.75, 1.15)
                node.p = [
                    d * math.sin(phi) * math.cos(theta),
                    d * math.sin(phi) * math.sin(theta),
                    d * math.cos(phi),
                ]
            self.scene_.addItem(node)
            self.nodes[title] = node

        seen = set()
        for src, links in graph.items():
            for dst in links:
                key = tuple(sorted((src, dst)))
                if key in seen or src == dst:
                    continue
                seen.add(key)
                self.edges.append((src, dst))

        # **뜻으로 이은 선.** 사람이 안 이어도 그래프가 엮이게 한다 — 닷새를 실제로
        # 쓴 자리에서 항목 528개에 손으로 적은 선이 둘뿐이었다. 흐리게 그려서
        # 「사람이 말한 것」과 「우리가 짐작한 것」을 눈으로 갈라 놓는다.
        self.soft.clear()
        for src, near in (soft or {}).items():
            for dst in near:
                key = tuple(sorted((src, dst)))
                if key in seen or src == dst or dst not in self.nodes:
                    continue
                seen.add(key)
                self.edges.append((src, dst))
                self.soft.add(key)

        self.physics.start(30)
        # 자리가 잡히면 멈춘다. 시간으로만 끊으면 큰 그래프는 덜 자리 잡은 채로 멈추고,
        # 작은 그래프는 다 끝나고도 5초 동안 계산을 돈다 — 둘 다 값을 버린다.
        self._settling = 0
        # 마지막 안전장치. **타이머를 새로 만들지 않는다** — 다시 그릴 때마다
        # `singleShot` 을 걸면 죽은 타이머가 쌓이고, 그것들이 이미 없어진 장면을
        # 향해 울린다(무작위로 눌러 보다 프로세스가 통째로 죽었다).
        self._stopper.start(12000)
        self.project()

    @property
    def shell(self) -> float:
        """항목이 쌓일수록 커지는 구의 반지름. 세제곱근이라 밀도가 일정하게 유지된다.

        가운데 구멍은 여기서 만들지 않는다. 하한을 두면 항목이 90개를 넘을 때까지
        구가 안 자라 "쌓일수록 공 모양"이 사라진다 — 구멍은 투영에서 뚫는다.
        """
        return 껍질(len(self.nodes))

    def step_layout(self) -> None:
        """3차원 힘 배치. 붙은 것끼리 당기고, 가까운 것끼리 밀어내고, 구 껍질로 모은다.

        **밀어내기를 격자로 자른다.** 전부 대 전부로 재면 항목 수의 제곱이라, 4000개에서
        한 걸음에 35초가 걸렸다(실측). 30ms마다 도는 계산이 그러면 창이 통째로 굳는다.

        멀리 있는 것끼리는 어차피 힘이 거리 제곱에 반비례해 거의 0이다. 공간을 칸으로
        나눠 **옆 칸까지만** 재면 결과는 눈에 같고 값은 항목 수에 비례한다.
        """
        items = [n for n in self.nodes.values() if n.isVisible()]
        if not items:
            return
        began = time.perf_counter()
        target = self.shell
        # 반발력을 그대로 두면 항목이 늘수록 그래프가 끝없이 부푼다. 총량을 나눠 쓴다.
        push = 26000.0 * (12.0 / max(len(items), 12)) ** 0.5
        pull, shell_k, damp = 0.006, 0.010, 0.82

        # 칸 크기는 **항목 수에 따라 줄인다.** 고정 크기로 잡으면 항목이 늘수록 한 칸에
        # 다 들어가서 격자가 아무 일도 안 한다 — 처음에 그렇게 만들었다가 4000개에서
        # 19초가 나왔다. 한 칸에 몇 개만 들어가게 잡아야 항목 수에 비례한다.
        cell = max(45.0, target * 2.4 / max(len(items), 8) ** (1 / 3))
        buckets: dict[tuple[int, int, int], list] = {}
        for node in items:
            key = (int(node.p[0] // cell), int(node.p[1] // cell), int(node.p[2] // cell))
            buckets.setdefault(key, []).append(node)

        near = (-1, 0, 1)
        for key, here in buckets.items():
            others = []
            for dx in near:
                for dy in near:
                    for dz in near:
                        others.extend(buckets.get((key[0] + dx, key[1] + dy, key[2] + dz), ()))
            for a in here:
                for b in others:
                    if a is b:
                        continue
                    d = [a.p[i] - b.p[i] for i in range(3)]
                    d2 = max(d[0] * d[0] + d[1] * d[1] + d[2] * d[2], 120.0)
                    f = push / d2 / math.sqrt(d2)
                    a.v[0] += d[0] * f
                    a.v[1] += d[1] * f
                    a.v[2] += d[2] * f

        for src, dst in self.edges:
            a, b = self.nodes.get(src), self.nodes.get(dst)
            if a is None or b is None:
                continue
            for i in range(3):
                delta = (b.p[i] - a.p[i]) * pull
                a.v[i] += delta
                b.v[i] -= delta

        moved = 0.0
        for node in items:
            if node.title == ROOT:
                node.p = [0.0, 0.0, 0.0]  # VC는 한가운데 고정 — 세포체 자리다
                node.v = [0.0, 0.0, 0.0]
                continue
            # 구 껍질 쪽으로 당긴다. 쌓일수록 공 모양이 되는 힘이 이것이다.
            dist = math.sqrt(sum(x * x for x in node.p)) or 1.0
            gap = (target - dist) * shell_k
            for i in range(3):
                node.v[i] += node.p[i] / dist * gap
                node.v[i] *= damp
                node.p[i] += node.v[i]
            moved = max(moved, abs(node.v[0]) + abs(node.v[1]) + abs(node.v[2]))

        # ★★ **무리를 한가운데로 되돌린다**(오너 2026-09-20: 「치우침은 없이」).
        #   VC 는 원점에 못 박혀 있는데 나머지는 그렇지 않아, 격자로 자른 반발력의
        #   작은 비대칭과 처음 뿌린 자리의 쏠림이 **씻겨 나가지 못하고 쌓였다.**
        #   재 보니 무게중심이 (182, -114, -55) 에서 **치우친 채로 안정**됐다 —
        #   그래서 표식이 늘 무리 한쪽에 붙어 보였다. 걸음마다 평균을 빼면
        #   모양은 그대로 두고 자리만 가운데로 온다.
        흐른것 = [n for n in items if n.title != ROOT]
        if 흐른것:
            가운데 = [sum(n.p[i] for n in 흐른것) / len(흐른것) for i in range(3)]
            if abs(가운데[0]) + abs(가운데[1]) + abs(가운데[2]) > 0.5:
                for n in 흐른것:
                    for i in range(3):
                        n.p[i] -= 가운데[i]

        # 거의 안 움직이면 그만둔다. 켜 두는 내내 도는 계산이라 멈추는 게 곧 성능이다.
        self._settling = self._settling + 1 if moved < 0.8 else 0
        if self._settling >= 3:
            self.physics.stop()

        # **한 걸음이 오래 걸리면 간격을 그만큼 벌린다.** 안 벌리면 계산이 화면 실을
        # 꽉 채워서, 뒤에서 도는 색인이 굶는다 — 2만 개 첫 색인이 6초에서 2분으로
        # 늘어난 원인이 이것이었다. 어떤 크기에서도 절반은 비워 둔다.
        spent = time.perf_counter() - began
        self.physics.setInterval(max(30, int(spent * 2000)))

        self.project()

    # --- 초점 -----------------------------------------------------------

    def focus_on(self, titles: list[str], zoom: float | None = None,
                 hold_ms: int = 12000) -> None:
        """맞는 항목만 남기고 나머지는 옅은 회색으로 가라앉힌다.

        검색·지시·항목 열람이 전부 여기로 들어온다. 음성 지시도 같은 문으로 들어오면
        되므로 따로 만들 게 없다.

        zoom이 None이면 **배율을 그대로 둔다** — 검색은 범위를 좁히는 일이지 다가가는
        일이 아니다. 좁힐 때마다 화면이 들썩이면 전체 중 어디를 보고 있는지 놓친다.
        내용을 펼쳐 볼 때만 값을 줘서 다가간다.

        hold_ms가 지나면 저절로 풀려 전체 모습으로 물러난다 — 초점을 잡아 놓고 잊어버리면
        화면이 그 상태로 굳는다.
        """
        wanted = {t for t in titles if t in self.nodes}
        if not wanted:
            return self.clear_focus()

        # 딴 것을 보겠다는 뜻이니 「표식 제자리」 붙들기는 푼다 — 안 풀면 초점을
        # 잡아도 화면이 원점에 붙어 있어, 고른 것이 구석에 뜬다.
        self._원점에두기 = False
        self.focus = wanted
        self._focus_zoom = zoom
        for node in self.nodes.values():
            node.focused = node.title in wanted
            node.dim = not node.focused
            node._paint_label()
            node.update()

        self._release.stop()
        if hold_ms:
            self._release.start(hold_ms)
        self.project()

    def 제자리로(self) -> None:
        """**VC 표식을 화면 한가운데로 되돌린다.** 표식을 두 번 누르면 여기로 온다.

        가운데는 평소 항목들을 감싸는 네모의 중심이라, 항목이 한쪽으로 몰리면 표식이
        구석으로 밀려난다 — 기록이 한두 장뿐인 첫날에 특히 그렇다. 되돌릴 길이 없으면
        **화면을 바로잡을 방법이 아예 없다**(이 그래프는 밀어서 옮기는 것이 없고
        돌리기만 된다). 표식이 곧 VC 이므로 그것을 눌러 제자리로 오게 한다.

        초점도 같이 푼다. 안 풀면 초점 쪽이 가운데를 계속 끌어당겨 **눌러도 아무 일도
        안 일어난 것처럼 보인다.**
        """
        self._원점에두기 = True
        self.clear_focus()
        self._fit()

    def 둘레만(self, title: str, 깊이: int = 1) -> int:
        """**그 항목과 이어진 것만** 남기고 나머지는 감춘다. 남긴 수를 돌려준다.

        옵시디언의 「로컬 그래프」다. 전체 그래프는 139개가 한꺼번에 떠 있어
        「이 글이 무엇과 묶였나」를 눈으로 골라야 한다 — 그 판을 갈아 끼운다.
        ★ 가라앉히는(`focus_on`) 것과 다르다. 흐리게 남겨 두면 여전히 화면을 채운다.
        """
        if title not in self.nodes:
            return 0
        남길 = {title} | set(self.이웃들(title))
        for _ in range(max(깊이 - 1, 0)):
            남길 |= {y for x in list(남길) for y in self.이웃들(x)}
        self.둘레중 = title
        for t, node in self.nodes.items():
            보임 = t in 남길 and t != ROOT
            node.setVisible(보임)
            node.dim = False
            if not 보임:
                node.label.setVisible(False)
            node._paint_label()
        self._키기준 = title
        self.set_hover(title)
        # ★ 남은 것들로 **다시 자리를 잡게** 한다. 안 그러면 139개 틈에 뿌려진 그대로라
        #   구석에 몰려 보인다 — 좁혀 놓은 뜻이 없다(찍어 보고 알았다).
        self._settling = 0
        self.physics.start()
        self.project()
        return len(남길)

    def 둘레풀기(self) -> bool:
        """둘레 보기를 그만두고 전부 되돌린다. 보고 있지 않았으면 거짓."""
        if not getattr(self, "둘레중", ""):
            return False
        self.둘레중 = ""
        for t, node in self.nodes.items():
            node.setVisible(t != ROOT)
            node._paint_label()
        self.project()
        self.physics.start()        # 감춰 둔 동안 멈춰 있던 배치를 다시 돌린다
        return True

    def clear_focus(self) -> None:
        """초점을 풀고 전체가 보이는 기본 모습으로 돌아간다."""
        self._release.stop()
        if not self.focus:
            return
        self.focus = set()
        self._focus_zoom = None
        for node in self.nodes.values():
            node.dim = node.focused = False
            node._paint_label()
            node.update()
        self.project()

    # --- 배율 -----------------------------------------------------------

    def _fit(self) -> None:
        """보여야 할 것이 화면에 꽉 차게 목표 배율·중심을 정한다.

        초점이 없으면 전체가 기본 모습이다. 항목이 늘면 그만큼 물러나 작아진다.
        초점이 걸리면 그 항목들만 재서 다가간다.

        3차원 반지름으로 어림하면 원근·기울기가 눌러 놓은 만큼을 모르고 과하게 물러난다.
        **투영이 끝난 실제 화면 범위**로 재야 여백이 남지 않는다. 가로·세로를 따로 잰다.

        배율은 위치 계산에 안 들어가므로 되먹임이 없다.
        """
        def bounds(items):
            pad = 26.0  # 이름표가 원 밖으로 나가는 만큼
            if not items:
                # **항목이 하나도 없을 때가 실제로 있다** — 기록이 0개인 첫 실행이
                # 그렇다. 예전에는 여기서 `min()` 이 터졌는데, 이 함수는 화면 크기가
                # 바뀔 때(`resizeEvent`) 불려서 **Qt 가 그 예외를 못 받고 프로세스째
                # 죽었다.** 파이썬 오류로도 안 남아 원인을 찾기까지 오래 걸렸다.
                return QPointF(0.0, 0.0), 1.0, 1.0
            xs = [n.pos().x() for n in items]
            ys = [n.pos().y() for n in items]
            reach = max((n.r * n.scale() for n in items), default=1.0)
            return (
                QPointF((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2),
                (max(xs) - min(xs)) / 2 + reach + pad,
                (max(ys) - min(ys)) / 2 + reach + pad,
            )

        # 전체 모습의 배율은 초점과 무관하게 늘 계산해 둔다. 초점을 풀면 여기로 돌아온다.
        # ★ **둘레 보기 중에만 「보이는 것」으로 잰다.** 감춘 항목까지 세면 34개만 띄워
        #   놓고도 139개짜리 배율로 물러나 있어 좁힌 뜻이 없다. 다만 평소에도 이러면
        #   항목이 떴다 잠겼다 할 때마다 배율이 흔들린다 — 검사가 바로 잡아냈다
        #   (「검색인데 배율이 움직였다 0.90 → 0.94」). 그래서 그때만 한다.
        잴것 = list(self.nodes.values())
        if getattr(self, "둘레중", ""):
            잴것 = [n for n in 잴것 if n.isVisible()] or 잴것
        center, half_w, half_h = bounds(잴것)
        overview = min(
            self.viewport().width() / (2 * half_w),
            self.viewport().height() / (2 * half_h),
            1.0,  # 전체 모습에서는 확대하지 않는다
        )

        if self.focus and self._focus_zoom is not None:
            # 내용을 펼쳐 볼 때만 다가간다. 값은 고정 — 항목 수에 따라 배율이 달라지면
            # 같은 동작인데 매번 다른 거리에서 보게 된다.
            lit = [n for n in self.nodes.values() if not n.dim]
            center, _, _ = bounds(lit or list(self.nodes.values()))
            self._zoom_target = self._focus_zoom
        else:
            # 검색만으로는 배율을 건드리지 않는다.
            # ★★ **배치가 꿈틀댄다고 배율까지 따라 흔들리면 안 된다**(2026-09-20).
            #   전체 배율은 항목들의 **화면 범위**로 잡는데, 그 범위는 힘 배치가 자리를
            #   잡는 동안 조금씩 변한다. 항목과 껍질을 20% 키우자 그 흔들림이 커져
            #   **검색 전후로 배율이 0.86 → 0.88 로 움직였다**(검사가 잡았다).
            #   사람 눈에는 「좁혔더니 화면이 들썩」으로 보인다. 눈에 띌 만큼
            #   달라질 때만 따라간다 — 항목이 크게 늘거나 창이 바뀌는 때다.
            옛것 = self._zoom_target
            if 옛것 <= 0 or abs(overview - 옛것) > max(옛것, overview) * 0.05:
                self._zoom_target = overview

        self._center_target = center

        # ★★ **표식이 화면 가운데에 없을 수 있다.** 가운데는 위에서 항목들을 감싸는
        #   네모의 중심으로 잡는데, VC 표식은 원점(0,0)에 못 박혀 있다 — 항목이
        #   한쪽으로 치우치면 그만큼 표식이 밀려난다(오너가 보고 짚었다).
        #   표식을 두 번 누르면(`제자리로`) 다시 원점을 가운데로 삼는다.
        #   초점이 걸려 있을 때는 그쪽을 따라가는 것이 맞으므로 건드리지 않는다.
        if self._원점에두기 and not self.focus:
            self._center_target = QPointF(0.0, 0.0)

    def _apply_view(self) -> None:
        """목표 배율·중심으로 조금씩 다가간다. 한 번에 튀면 어디를 보던 중인지 놓친다."""
        ease = 0.18
        self._zoom += (self._zoom_target - self._zoom) * ease
        self._center += (self._center_target - self._center) * ease
        self.resetTransform()
        self.scale(self._zoom, self._zoom)
        # ★★ **장면 네모를 손수 잡아 준다.** 안 잡으면 Qt 가 「항목들을 감싸는 네모」로
        #   잡는데, 그것이 화면보다 작으면 **스크롤할 데가 없어 `centerOn` 이 아무 일도
        #   안 한다** — 화면 가운데가 우리가 정한 `_center` 가 아니라 **항목 네모의
        #   중심**으로 멋대로 정해진다. 기록이 몇 장뿐이면 늘 이 경우다.
        #   그래서 원점에 못 박힌 VC 표식이 가운데가 아니라 구석에 있었다
        #   (실측: 스크롤 범위 0~0, 표식이 화면 가운데에서 48x84px 빗나감).
        #   초점을 잡아도 그쪽으로 안 가던 것도 같은 뿌리다.
        #   **보이는 만큼의 네모를, 보고 싶은 자리를 한가운데 두고** 잡아 준다.
        보임 = QRectF(0.0, 0.0,
                     self.viewport().width() / self._zoom,
                     self.viewport().height() / self._zoom)
        보임.moveCenter(self._center)
        self.setSceneRect(보임)
        self.centerOn(self._center)
        self._place_mark()

    def _덮개고침(self) -> None:
        """선 덮개를 표식 위에 맞춰 두고 다시 그리게 한다."""
        층 = getattr(self, "_선위층", None)
        if 층 is None:
            return
        if 층.geometry() != self.viewport().rect():
            층.setGeometry(self.viewport().rect())
        층.raise_()
        층.update()

    def _place_mark(self) -> None:
        """표식을 원점 위에 놓고 구멍 크기에 맞춘다.

        불티 링이 그려지는 반지름이 위젯 절반의 0.8배라, 구멍 지름의 2.5배로 잡아야
        불티가 정확히 항목이 밀려난 자리에 앉는다.
        """
        pos = self.mapFromScene(QPointF(0.0, 0.0))
        # 2.5면 불티 링이 항목이 밀려난 자리에 딱 앉는데, 그러면 표식이
        # 화면에서 커 보인다. 24% 줄여 항목 쪽에 자리를 내줬다.
        # 2026-09-20 오너 지시로 20% 키웠다가(1.913 → 2.296), **다음 날 로고만 도로
        # 줄였다** — 항목 크기와 간격은 키운 채로 둔다(오너 2026-09-21 「로고만」).
        #
        # ★★ **자람**: 글이 쌓이면 구가 커지고 `_fit` 이 그만큼 물러나, 로고가 화면에서
        #   작아 보였다(150장 8.3% → 1000장 5.0%). 로고는 「여기가 가운데다」를 알리는
        #   표지라 창고가 클수록 오히려 또렷해야 한다. 구가 커진 만큼 곱해 되돌린다 —
        #   배율이 구 크기에 반비례하므로 상쇄되어 **글 수와 무관하게 같은 크기로 보인다.**
        #   `RING` 은 안 건드린다 — 그것은 항목을 밀어내는 **자리**라 layout 이 바뀐다.
        size = max(140, int(1.913 * self.RING * (self.shell / 기준껍질) * self._zoom))
        섰던자리 = self.mark.geometry()
        self.mark.setFixedSize(size, size)
        self.mark.move(pos.x() - size // 2, pos.y() - size // 2)
        # **비켜난 자리를 손수 지워 준다.** 표식은 뒤가 비치는 자식 위젯인데,
        # `QGraphicsView` 는 바뀐 항목 둘레만 다시 그린다(MinimalViewportUpdate).
        # 표식이 옮겨가면 원래 있던 네모는 「바뀐 항목」이 아니라서 아무도 안 지우고
        # **그 자리에 네모가 남는다** — 오너가 「가운데 로고가 멈칫할 때 사각형이
        # 나왔다 사라진다」고 본 것이다. 옮겨갈 때만 두 자리를 함께 다시 그린다.
        if self.mark.geometry() != 섰던자리:
            self.viewport().update(섰던자리.united(self.mark.geometry()))

    def settle_view(self, steps: int = 80) -> None:
        """전환이 끝난 상태로 즉시 맞춘다. 화면 없이 검사하거나 갈무리할 때 쓴다."""
        for _ in range(steps):
            self._apply_view()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit()
        self._place_mark()
        self._선위층.setGeometry(self.viewport().rect())

    def project(self) -> None:
        """3차원 좌표를 화면으로 옮긴다. 가까울수록 크고 진하게, 앞에 그린다."""
        # 이름이 짧으면 루프 안에서 덮어쓰기 쉽다 — 한 번 그래서 회전이 망가졌다.
        yaw_c, yaw_s = math.cos(self.yaw), math.sin(self.yaw)
        tilt_c, tilt_s = math.cos(self.tilt), math.sin(self.tilt)

        for node in self.nodes.values():
            x, y, z = node.p
            x, z = x * yaw_c - z * yaw_s, x * yaw_s + z * yaw_c  # 세로축 회전
            y, z = y * tilt_c - z * tilt_s, y * tilt_s + z * tilt_c  # 살짝 기울여 입체감

            scale = self.FOCAL / (self.FOCAL + z + 260.0)
            node.depth = max(0.0, min(1.0, (scale - 0.62) / 0.55))
            if node.title == ROOT:
                # VC는 원점에 있어 원근을 받으면 앞으로 나온 항목보다 작아 보인다.
                # 층위가 크기로 읽혀야 하므로 VC만 축소를 면제한다.
                scale, node.depth = 1.0, 1.0
            sx, sy = x * scale, y * scale
            if node.title == ROOT:
                node.setVisible(False)      # 이 자리는 표식이 대신한다
                node.label.setVisible(False)
            else:
                # 구의 앞뒷면 꼭지점은 투영하면 한가운데로 온다 — 3차원에서 밖으로
                # 밀어도 소용없다. **투영이 끝난 자리**에서 밀어야 구멍이 뚫린다.
                # 부드러운 최댓값이라 링에 몰려 쌓이지 않고, 바깥 항목은 거의 그대로다.
                # 불티 링에 딱 붙이면 항목이 불티에 섞여 안 보인다 — 한 뼘 밖으로.
                keep = self.RING * 1.18
                d = math.hypot(sx, sy)
                if d > 1e-6:
                    k = (d ** 6 + keep ** 6) ** (1 / 6) / d
                    sx, sy = sx * k, sy * k
                else:
                    sx, sy = keep, 0.0
            node.setPos(sx, sy)
            node.setScale(scale)
            node.setZValue(-z)
            node._paint_label()
            node.update()

        self._fit()  # 위치가 다 정해진 뒤에 재야 실제 범위가 나온다
        self._name_front()
        self._resolve_labels()
        self.viewport().update()
        self._덮개고침()

    def _name_front(self) -> None:
        """**맨 앞줄 몇 개는 이름표를 늘 보인다.**

        평소엔 손 얹은 것만 보여 줬는데, 항목이 열 개 남짓일 때는 그것으로 화면이
        차서 몰랐다. 백 개가 되자 **점만 남고 글자가 하나도 없는 화면**이 됐다 —
        그래프가 이 프로그램의 얼굴인데 쌓일수록 얼굴이 비어 갔다.

        전부 보이면 이름표가 화면을 덮으므로 앞줄 몇 개만 고른다. 겹치는 것은
        뒤이어 `_resolve_labels` 가 걷어낸다.
        """
        # **누구를 보일지는 안 흔들려야 한다.** 깊이순으로 매 프레임 다시 고르면
        # 그래프가 도는 동안 이름표가 떴다 사라진다 — 500개에서 「한 번에 1~5개,
        # 그나마 깜박인다」로 걸렸다. 개수보다 깜박이는 것이 더 나쁘다.
        #
        # 그래서 **안 바뀌는 잣대**(크기 = 층위, 그다음 이름)로 줄을 세우고,
        # 앞쪽 절반에 있는 것 중에서 고른다. 한 번 뽑힌 것은 뒤로 꽤 넘어가기
        # 전까지 그대로 둔다(문턱을 둘로 나눈다) — 그래야 조금 돌 때마다 안 바뀐다.
        show = 0.45      # 새로 뽑히려면 이만큼 앞에 있어야 한다
        keep = 0.30      # 한 번 뽑힌 것은 이만큼까지는 그대로 둔다
        able = [n for n in self.nodes.values()
                if not n.dim and n.title != ROOT
                and n.depth >= (keep if n.near else show)]
        # 같은 크기끼리는 **이름을 흩어서** 줄 세운다. 이름 그대로로 줄을 세우면
        # 「교육 일지 1·2·3…」처럼 한 틀로 찍어낸 무리가 나란히 붙어 자리를 통째로
        # 차지한다 — 낯선 PC 에서 이름표가 거의 그 두 무리로만 채워졌다.
        # 흩되 **늘 같은 자리로** 흩어야 깜박이지 않으므로, 이름에서 뽑은 고정된 값을 쓴다.
        able.sort(key=lambda n: (-n.r, _spread(n.title)))
        front = {id(n) for n in able[:self.LABEL_FRONT]}
        for node in self.nodes.values():
            was, node.near = node.near, id(node) in front
            if was != node.near:
                node._paint_label()

    def _resolve_labels(self) -> None:
        """겹치는 이름표를 뒤쪽 것부터 지운다. 깊이만으로는 충돌이 남는다.

        우선순위는 VC → 말하는 항목 → 앞에 있는 항목 순이다.
        """
        def priority(node: NodeItem) -> tuple[int, float]:
            if node.hovered:
                rank = 0  # 손 얹힌 것이 자리를 먼저 잡는다
            elif node.focused or node.linked:
                rank = 1  # 찾아낸 것·이어진 것이 그다음
            elif node.speaking > 0.05:
                rank = 2
            else:
                rank = 3
            # **자리 다툼 차례도 안 흔들려야 한다.** 깊이로만 줄을 세우면 그래프가
            # 도는 동안 이기는 쪽이 매번 바뀌어 이름표가 깜박인다. 같은 등급 안에서는
            # **안 바뀌는 잣대**(크기 = 층위, 그다음 이름)로 가른다.
            #
            # ★★ **그것만으로는 모자랐다.** 뽑는 차례는 안 흔들리는데 **겹침 정리가
            #   매 프레임 자리를 처음부터 다시 잡아서**, 조금 도는 것만으로 이름표
            #   열댓 개 중 아홉이 떴다 사라졌다(맥에서 잼). 그래서 같은 등급 안에서는
            #   **바로 앞에 보이던 것을 먼저 앉힌다** — 한번 자리를 잡은 이름은
            #   웬만해선 계속 그 자리에 있고, 새 이름은 남는 틈에만 들어온다.
            #   개수보다 깜박이는 것이 더 나쁘다는 판단은 위와 같다.
            return (rank, 0 if node.title in self._전에보임 else 1, -node.r, node.title)

        # 원은 순서와 무관하게 전부 피해야 한다. 처리하면서 모으면 뒤에 올 원을 놓친다.
        circles = [
            (node, node.mapRectToScene(QRectF(-node.r, -node.r, node.r * 2, node.r * 2)))
            for node in self.nodes.values()
        ]

        placed: list[QRectF] = []
        for node in sorted(self.nodes.values(), key=priority):
            if not node.label.isVisible():
                continue

            size = node.label.boundingRect()
            # 아래가 막히면 위로 올려 본다. 한쪽만 보면 멀쩡한 이름표가 자꾸 사라진다.
            # ★★ **위아래 둘만으로는 모자랐다.** 그래프가 도는 동안 남의 원이 이름표
            #   자리로 들어오는데, 비켜설 데가 두 곳뿐이라 **멀쩡히 앞에 있는 이름표가
            #   그냥 사라졌다** — 열댓 개 중 아홉이 떴다 사라지는 깜박임의 대부분이
            #   여기였다(맥에서 잼: 아홉 중 일곱). 좌우도 대 본다. 비켜설 데가 늘면
            #   지우는 대신 옆으로 물러난다.
            자리들 = [
                (-size.width() / 2, node.r + 7),                          # 아래
                (-size.width() / 2, -node.r - 7 - size.height()),          # 위
                (node.r + 7, -size.height() / 2),                          # 오른쪽
                (-node.r - 7 - size.width(), -size.height() / 2),          # 왼쪽
            ]
            def 앉혀보기(dx: float, dy: float) -> QRectF | None:
                """그 자리에 놓아 보고, 아무것도 안 덮으면 차지한 칸을 돌려준다."""
                node.label.setPos(dx, dy)
                칸 = node.label.sceneBoundingRect().adjusted(-3, -1, 3, 1)
                막힘 = any(o is not node and 칸.intersects(r) for o, r in circles) or any(
                    칸.intersects(other) for other in placed
                )
                return None if 막힘 else 칸

            # ★★ **차례가 「있던 자리 → 버티기 → 옮기기 → 지우기」다.** 이 차례가
            #   핵심이다. 처음엔 매 프레임 「아래부터」 다시 골랐는데, 아래가 잠깐
            #   비는 순간 오른쪽에 있던 글자가 아래로 **툭** 내려왔다 — 깜박임을
            #   줄이려고 비켜설 자리를 넷으로 늘리자 이번엔 **움찔거림**이 생겼다
            #   (300프레임에 210번, 전부 20px 넘게 튐. 오너가 창을 보고 바로 잡아냈다).
            #   있던 자리를 먼저 대는 것만으로 84번까지 줄었지만, **지금 자리가 잠깐
            #   막히기만 해도 곧바로 옆으로 옮기는 것**이 남아 있었다. 그래서 버티기를
            #   「네 자리 다 막혔을 때」가 아니라 **옮기기 바로 앞**에 둔다 —
            #   스쳐 지나가는 원 때문에 자리를 옮기지 않는다.
            옛자리 = self._마지막자리.get(node.title)
            앉았다 = False
            if 옛자리 is not None:
                칸 = 앉혀보기(*옛자리)
                if 칸 is not None:                       # ① 있던 자리가 그대로 비었다
                    placed.append(칸)
                    self._막힌횟수.pop(node.title, None)
                    앉았다 = True
                elif (self._막힌횟수.get(node.title, 0) < self.LABEL_GRACE
                        and node.title in self._전에보임):
                    # ② 잠깐 막힌 것일 수 있다 — 옮기기 전에 그 자리에서 버틴다.
                    #    잠깐 겹쳐 보이는 쪽이 튀거나 사라지는 쪽보다 낫다(줄곧 지켜 온 판단).
                    self._막힌횟수[node.title] = self._막힌횟수.get(node.title, 0) + 1
                    node.label.setPos(*옛자리)
                    # 남이 그 자리를 또 차지하면 진짜로 겹친다 — 자리는 잡아 둔다.
                    placed.append(node.label.sceneBoundingRect().adjusted(-3, -1, 3, 1))
                    앉았다 = True
            if not 앉았다:                                # ③ 버틸 만큼 버텼다. 옮긴다
                for dx, dy in 자리들:
                    칸 = 앉혀보기(dx, dy)
                    if 칸 is not None:
                        placed.append(칸)
                        self._마지막자리[node.title] = (dx, dy)
                        self._막힌횟수.pop(node.title, None)
                        앉았다 = True
                        break
            if not 앉았다:                                # ④ 네 자리 다 남의 것을 덮는다
                self._막힌횟수.pop(node.title, None)
                self._마지막자리.pop(node.title, None)
                node.label.setVisible(False)
                continue

            # ★★ **자리를 옮길 때는 미끄러져 간다.** 위 차례로 옮기는 횟수는 줄였지만
            #   옮길 때마다 20~60px 를 **한 프레임에 순간이동**했다 — 횟수가 적어도
            #   눈은 그 튐을 먼저 쫓는다. 남은 「움찔거림」이 그것이었다.
            #   가야 할 자리는 그대로 두고, 화면에 그리는 자리만 몇 프레임에 걸쳐
            #   따라가게 한다. 겹침을 재는 것은 **가야 할 자리**로 재므로 판단은 안 바뀐다.
            #   새로 뜨는 이름표는 미끄러뜨리지 않는다 — 옛 자리에서 날아오면 더 이상하다.
            목표 = node.label.pos()
            앞선자리 = self._그린자리.get(node.title)
            if 앞선자리 is not None and node.title in self._전에보임:
                nx = 앞선자리[0] + (목표.x() - 앞선자리[0]) * self.LABEL_GLIDE
                ny = 앞선자리[1] + (목표.y() - 앞선자리[1]) * self.LABEL_GLIDE
                if abs(목표.x() - nx) + abs(목표.y() - ny) < 0.5:
                    nx, ny = 목표.x(), 목표.y()
                node.label.setPos(nx, ny)
            self._그린자리[node.title] = (node.label.pos().x(), node.label.pos().y())

        # 다음 정리 때 「먼저 앉힐 것」으로 쓴다. 이 줄이 없으면 위 규칙이 아무 일도 안 한다.
        self._전에보임 = {n.title for n in self.nodes.values() if n.label.isVisible()}

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        painter.setRenderHint(QPainter.Antialiasing)
        center = self.mapToScene(self.viewport().rect().center())
        depth = QRadialGradient(center, max(rect.width(), rect.height()) * 0.62)
        depth.setColorAt(0.0, QColor(theme.T.GLOW_CENTER.red(), theme.T.GLOW_CENTER.green(), theme.T.GLOW_CENTER.blue(), 90))
        depth.setColorAt(1.0, theme.T.BG)
        painter.fillRect(rect, QBrush(theme.T.BG))
        painter.fillRect(rect, QBrush(depth))

        # 격자. HUD처럼 보이게 하는 배경인데 진하면 시선을 뺏는다 — 알파 10.
        step = 46
        painter.setPen(QPen(theme.rgba(theme.T.GRID, 10), 1.0))
        x0 = int(rect.left() // step * step)
        y0 = int(rect.top() // step * step)
        for x in range(x0, int(rect.right()) + step, step):
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
        for y in range(y0, int(rect.bottom()) + step, step):
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))

        # 연결선. 말하는 항목에 닿은 선은 함께 밝아진다 — 말이 어디로 흐르는지 보이게.
        # ★★ **표식에 가려지는 것은 표식 스스로 한다**(오너 2026-09-20).
        #   처음엔 표식 자리를 둥글게 잘라내 선을 피하게 했는데, **잘린 자리가 그대로
        #   둥근 테두리로 보였다** — 오너가 「로고 주변에 원이 생긴다」고 짚었다.
        #   표식은 뷰포트 자식 위젯이라 장면의 선보다 늘 위에 그려진다. 그냥 두면
        #   **획이 있는 자리에서만** 선이 가려진다 — 그것이 바라는 모습이다.
        #   (손 얹은 선만 `_선위층` 이 표식 위에 다시 그려 끊기지 않게 한다.)
        painter.save()

        for src, dst in self.edges:
            a, b = self.nodes.get(src), self.nodes.get(dst)
            if not (a and b):
                continue

            def anchor(node, other):
                """가운데 항목으로 가는 선은 링 가장자리에서 멈춘다.

                가운데 자리에는 표식이 앉아 있다. 원점까지 그으면 선이 표식을 뚫고
                지나가 글자를 가로지른다.
                """
                if node.title != ROOT:
                    return node.pos()
                d = other.pos()
                length = math.hypot(d.x(), d.y()) or 1.0
                edge = self.RING * 0.92
                return QPointF(d.x() / length * edge, d.y() / length * edge)

            pa, pb = anchor(a, b), anchor(b, a)
            if tuple(sorted((src, dst))) in self.soft:
                # 짐작한 선은 **점선으로 아주 옅게.** 있다는 것만 보이면 된다 —
                # 손으로 적은 선과 같은 굵기로 그리면 둘이 같은 말인 줄 안다.
                if not (a.dim or b.dim):
                    # 34 로 뒀더니 **화면 캡처에서 하나도 안 잡혔다.** 「엮임 249」로
                    # 세어지는데 선이 한 줄도 안 보이면 없는 것과 같다. 점선이라
                    # 진하게 해도 손으로 적은 선(이어진 실선)과 안 섞인다.
                    옅음 = 0.3 + 0.7 * min(a.depth, b.depth)
                    painter.setPen(QPen(theme.rgba(theme.T.MUTED, int(96 * 옅음)),
                                        1.0, Qt.DotLine))
                    painter.drawLine(pa, pb)
                continue
            heat = max(a.speaking, b.speaking)
            fog = 0.2 + 0.8 * min(a.depth, b.depth)
            lit = a.hovered or b.hovered
            if a.dim or b.dim:
                # 한쪽이라도 초점 밖이면 선도 가라앉는다. 밝은 선이 남으면 시선이 끌려간다.
                painter.setPen(QPen(theme.rgba(theme.T.MUTED, int(38 * fog)), 1.0))
                painter.drawLine(pa, pb)
                continue
            if lit:
                # 손 얹힌 항목에 닿은 선. 굵은 깔개를 덧대 빛나게 했었는데, 이어진 것이
                # 백 개가 넘는 항목에서는 화면이 통째로 붉어졌다 — 가는 선 하나로 줄였다.
                painter.setPen(QPen(theme.rgba(theme.T.ACCENT, 손선밝기), 손선굵기))
                painter.drawLine(pa, pb)
                continue
            if heat > 0.05:
                grad = QLinearGradient(pa, pb)
                grad.setColorAt(0.0, theme.rgba(theme.T.ACCENT, int(40 + 170 * a.speaking)))
                grad.setColorAt(1.0, theme.rgba(theme.T.ACCENT, int(40 + 170 * b.speaking)))
                painter.setPen(QPen(QBrush(grad), 1.0 + 1.0 * heat))
            else:
                painter.setPen(QPen(theme.rgba(theme.T.ACCENT, int(46 * fog)), 1.0))
            painter.drawLine(pa, pb)

            if heat > 0.05:
                # 밝은 선 위로 점이 흐른다. 선이 그냥 밝아지는 것보다 '지금 오간다'가 읽힌다.
                t = ((self.tick % 26) / 26.0 + (0.0 if a.speaking >= b.speaking else 0.5)) % 1.0
                head, tail = (pa, pb) if a.speaking >= b.speaking else (pb, pa)
                spot = head + (tail - head) * t
                painter.setPen(QPen(Qt.NoPen))
                painter.setBrush(QBrush(theme.rgba(theme.T.ACCENT, int(230 * heat * (1 - t * 0.5)))))
                painter.drawEllipse(spot, 2.2, 2.2)

        painter.restore()      # 표식 자리를 비워 둔 잘라내기를 여기서 푼다

    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:
        """뷰 자체에 걸리는 계기 장식. 화면에 고정돼야 하므로 화면 좌표로 되돌려 그린다."""
        painter.save()
        painter.resetTransform()  # 확대·회전을 벗겨 화면 픽셀 그대로 쓴다
        w, h = self.viewport().width(), self.viewport().height()
        m, c = 10, 16

        painter.setPen(QPen(theme.rgba(theme.T.DIM, 70), 1.2))
        for x, y, dx, dy in ((m, m, 1, 1), (w - m, m, -1, 1), (m, h - m, 1, -1), (w - m, h - m, -1, -1)):
            painter.drawLine(x, y, x + dx * c, y)
            painter.drawLine(x, y, x, y + dy * c)

        # 가장자리 눈금. 회전 중이라는 걸 배경이 조용히 알려준다.
        painter.setPen(QPen(theme.rgba(theme.T.ACCENT, 45), 1.0))
        for i in range(9):
            tx = m + 30 + i * (w - 2 * m - 60) / 8
            painter.drawLine(QPointF(tx, h - m), QPointF(tx, h - m - (7 if i % 4 == 0 else 3)))

        # 각도·배율 숫자는 뺐다. 만드는 사람에게만 쓸모가 있는데 늘 화면에 떠 있었다.
        painter.restore()

    # --- 조작 -----------------------------------------------------------

    def mousePressEvent(self, event) -> None:
        item = self.itemAt(event.pos())
        while item is not None and not isinstance(item, NodeItem):
            item = item.parentItem()
        if isinstance(item, NodeItem):
            self.node_clicked.emit(item.title)
            return
        self.clear_focus()  # 빈 곳을 누르면 볼일이 끝난 것으로 본다
        self.empty_clicked.emit()
        self._drag = event.pos()

    def mouseDoubleClickEvent(self, event) -> None:
        """**표식을 두 번 누르면 제자리로.** 표식 자리가 곧 「가운데로」 단추다.

        표식은 마우스를 안 받는 위젯(`WA_TransparentForMouseEvents`)이라 누름이
        여기까지 그냥 내려온다 — 그 자리인지만 보면 된다. 항목 위를 두 번 눌렀을
        때는 원래 하던 일(한 번 누름)이 이미 돌았으므로 여기서는 아무것도 안 한다.
        """
        if self.mark.isVisible() and self.mark.geometry().contains(event.pos()):
            self.제자리로()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def _node_at(self, pos):
        item = self.itemAt(pos)
        while item is not None and not isinstance(item, NodeItem):
            item = item.parentItem()
        return item if isinstance(item, NodeItem) else None

    # --- 키보드로 그래프 돌기(오너 2026-09-20: 마우스 없이도 써야 한다) ------------
    def 이웃들(self, title: str) -> list[str]:
        """그 항목과 **이어진 것들**(이름순). 없으면 빈 목록."""
        got = set()
        for src, dst in self.edges:
            if src == title:
                got.add(dst)
            elif dst == title:
                got.add(src)
        return sorted(g for g in got if g in self.nodes)

    def 키로시작(self, title: str | None = None) -> str | None:
        """그래프에 손을 얹는다. 고른 것이 없으면 가운데(또는 첫 항목)부터.

        여기서 **기준**을 잡는다 — 이제 ←→ 는 이 기준에 이어진 것들만 돈다.
        """
        if title and title in self.nodes:
            머물 = title
        elif self.hover and self.hover in self.nodes:
            머물 = self.hover
        else:
            보이는 = [t for t, n in self.nodes.items() if not n.dim] or list(self.nodes)
            if not 보이는:
                return None
            머물 = ROOT if ROOT in 보이는 else 보이는[0]
        self._키기준 = 머물
        self.set_hover(머물)
        self.setFocus()
        return 머물

    def _키고리(self) -> list[str]:
        """지금 도는 차례 — **기준과 거기 이어진 것들**. 이어진 게 없으면 온 항목."""
        기준 = getattr(self, "_키기준", None)
        if 기준 not in self.nodes:
            return sorted(self.nodes)
        이웃 = self.이웃들(기준)
        return [기준] + 이웃 if 이웃 else sorted(self.nodes)

    def 키로옮기기(self, 걸음: int) -> str | None:
        """기준에 이어진 것들 사이를 한 칸 옮긴다.

        ★ **차례를 기준에 붙박아 둔다.** 옮길 때마다 「지금 것의 이웃」으로 차례를 다시
          짜면 → 다음 ← 가 **온 자리로 안 돌아온다**(실기에서 잡혔다). 앞뒤가 안 맞는
          움직임은 사람이 길을 잃는다. 이어진 것을 더 파고들려면 Enter 로 들어간다.
        """
        if not self.nodes:
            return None
        if getattr(self, "_키기준", None) not in self.nodes:
            return self.키로시작()
        돌목록 = self._키고리()
        지금 = self.hover if self.hover in 돌목록 else self._키기준
        자리 = 돌목록.index(지금) if 지금 in 돌목록 else 0
        다음 = 돌목록[(자리 + 걸음) % len(돌목록)]
        self.set_hover(다음)
        return 다음

    def keyPressEvent(self, event) -> None:
        """↑↓←→ 로 옮기고 Enter 로 연다. **마우스가 없어도 그래프를 돈다.**"""
        키 = event.key()
        if 키 in (Qt.Key_Left, Qt.Key_Up):
            self.키로옮기기(-1)
            return
        if 키 in (Qt.Key_Right, Qt.Key_Down):
            self.키로옮기기(1)
            return
        if 키 in (Qt.Key_Return, Qt.Key_Enter) and self.hover:
            # 들어간 자리를 **새 기준**으로 삼는다 — 이제 ←→ 는 그것의 이웃을 돈다
            self._키기준 = self.hover
            self.node_clicked.emit(self.hover)
            return
        super().keyPressEvent(event)

    def set_hover(self, title: str | None) -> None:
        """손 얹힌 항목과 **그에 이어진 것들**에 표시를 건다.

        이름표를 평소에 감춰 뒀으므로, 얹은 것과 이어진 것만 이름이 뜬다. 이어진 선도
        같이 밝아져서 무엇과 무엇이 묶여 있는지 한눈에 보인다.
        """
        if title == self.hover:
            return
        self.hover = title
        linked = set()
        if title is not None:
            for src, dst in self.edges:
                if src == title:
                    linked.add(dst)
                elif dst == title:
                    linked.add(src)
        for node in self.nodes.values():
            node.hovered = node.title == title
            node.linked = node.title in linked
            node._paint_label()
            node.update()
        self._name_front()
        self._resolve_labels()
        self.viewport().update()

    def leaveEvent(self, event) -> None:
        self.set_hover(None)
        super().leaveEvent(event)

    def _재우기(self, 잘까: bool) -> None:
        # ★ **자는 동안에도 「자는 중」이 파일에 찍혀야 한다.** 안 찍으면 마지막으로
        # 쓴 값(33ms)이 그대로 남아, 읽는 사람이 **「문턱이 안 걸렸나」로 헤맨다** —
        # 시험하는 쪽이 실제로 그 33ms 를 보고 그리 갈 뻔했고, 판 수를 두 번 세서
        # 갈랐다. 값이 안 바뀌는 것과 「자고 있다」는 다른 말이다.
        if 잘까 and not self._잠듦:
            self._잠듦 = True
            멈칫.적어두기(자는중=True)
        elif not 잘까:
            self._잠듦 = False
        """자전과 표식을 **같이** 재우고 깨운다.

        **그리는 것이 둘이라는 것을 한 번 놓쳤다.** 그래프만 재우니 CPU 가 90%에서
        21% 까지만 내려갔는데, 최소화하면 1.8% 였다 — 그 차이가 표식이었다.
        재우는 자리를 한 함수로 묶어 **다음에 그리는 것이 하나 더 늘어도 여기만 본다.**
        """
        self.spin.setInterval(self.잠든간격 if 잘까 else 33)
        self.mark.set_paused(잘까 or self._indexing)

    def 깨우기(self) -> None:
        """사람 손이 닿았다. 잠들어 있었으면 다시 돈다.

        **깨우는 자리를 한 곳으로 모은다.** 여기저기서 시각을 고치면 한 군데를
        빠뜨렸을 때 **아무도 안 만져도 안 잠들거나, 만져도 안 깨는** 일이 난다.
        """
        self._깬때 = time.perf_counter()

    def mouseMoveEvent(self, event) -> None:
        self.깨우기()
        # **손이 움직이는 동안은 돈다.** 멈춰 세우기만 하면 다음 이름표를 보려고
        # 그래프 밖으로 손을 빼야 하는데, 그걸 아무도 안 배운다 — 낯선 PC 에서
        # 「왜 안 바뀌지 하고 한참 봤다」로 걸렸다.
        # 읽으려면 손을 멈추고, 다음 것을 보려면 손을 움직인다. 배울 것이 없다.
        # **1픽셀 떨림은 「움직임」이 아니다.** 사람이 마우스를 잡고 있으면 손은 완전히
        # 안 멈춘다. 거리 문턱이 없으면 **손을 얹은 채로는 영영 못 멈추고**, 멈추려면
        # 손을 떼야 하는데 그건 「읽으려고 다가온 순간이 멈출 때다」와 정반대가 된다.
        # (낯선 PC 가 1픽셀씩 여섯 번 흔들어 이 자리를 짚었다. 그쪽은 커서를 완전히
        #  정지시킬 수 있어서 못 겪는 자리라, 짐작으로 남기고 넘겨 줬다.)
        자리 = event.pos()
        섰던 = getattr(self, "_still_at", None)
        if 섰던 is None or (abs(자리.x() - 섰던.x()) + abs(자리.y() - 섰던.y())
                            > self.STILL_PX):
            self._still_at = 자리
            self._moved_at = time.perf_counter()
        if self._drag is None:
            node = self._node_at(event.pos())
            self.set_hover(node.title if node is not None else None)
            self.setCursor(Qt.PointingHandCursor if node else Qt.ArrowCursor)
            return
        delta = event.pos() - self._drag
        self._drag = event.pos()
        self.yaw += delta.x() * 0.008
        self.tilt = max(-1.2, min(1.2, self.tilt + delta.y() * 0.006))
        self.project()

    def mouseReleaseEvent(self, event) -> None:
        self._drag = None

    def wheelEvent(self, event) -> None:
        pass  # 확대는 원근을 헝클어뜨린다. 회전만 남긴다

    # --- 말하는 연출 ----------------------------------------------------

    def speak(self, titles: list[str], per_node_ms: int = 420) -> None:
        """항목을 순서대로 밝힌다. VC가 그 항목을 딛고 말하는 중이라는 뜻이다."""
        order = [t for t in titles if t in self.nodes]
        if not order:
            return

        for node in self.nodes.values():
            node.set_speaking(False)

        def light(i: int) -> None:
            if i > 0:
                self.nodes[order[i - 1]].set_speaking(True, 0.3)  # 여운
            if i >= len(order):
                QTimer.singleShot(
                    per_node_ms * 2,
                    lambda: [n.set_speaking(False) for n in self.nodes.values()],
                )
                self.viewport().update()
                return
            self.nodes[order[i]].set_speaking(True, 1.0)
            self._name_front()
            self._resolve_labels()  # 밝아진 항목이 이름표를 되살리므로 다시 정리한다
            self.viewport().update()
            QTimer.singleShot(per_node_ms, lambda: light(i + 1))

        light(0)


def _self_check() -> None:
    app = QApplication.instance() or QApplication(sys.argv)

    # **띄워 본다.** 예전 검사는 만들기만 하고 `show()` 를 안 해서, 기록이 0개인
    # 첫 실행에서 프로세스가 통째로 죽는 것을 못 잡았다(`_fit` 이 빈 목록에 걸렸는데
    # 그리는 도중의 파이썬 예외라 Qt 가 못 받고 죽는다).
    empty = GraphView()
    empty.resize(800, 600)
    empty.show()
    QApplication.instance().processEvents()
    assert not empty.nodes, "빈 그래프인데 항목이 있다"
    empty.close()

    view = GraphView()
    # **자전은 창이 보일 때만 돈다.** 그래서 검사에서도 띄워 놓고 잰다 —
    # 안 띄우면 아래 자전 검사가 전부 「안 보여서 안 돈 것」으로 통과해 버린다.
    view.show()
    view.load({"가": ["나"], "나": []}, {"가": "skill", "나": "note"})
    assert ROOT in view.nodes, "가운데 항목이 없다"
    assert view.nodes[ROOT].r == RADIUS["agent"]

    # 자리가 잡히면 움직임이 잦아든다. 안 잦아들면 항목이 영원히 떠다닌다.
    for _ in range(600):
        view.step_layout()
    speed = max(sum(abs(x) for x in n.v) for n in view.nodes.values())
    assert speed < 1.0, f"아직 떠다닌다 ({speed:.2f})"

    # 가운데 항목은 원점에 못 박혀 있다 — 세포체 자리라 떠다니면 안 된다.
    assert view.nodes[ROOT].p == [0.0, 0.0, 0.0], view.nodes[ROOT].p

    # 초점을 주면 그것만 남고 나머지는 가라앉는다. 지우지는 않는다.
    view.focus_on(["가"], zoom=FOCUS_ZOOM)
    assert view.nodes["나"].dim and not view.nodes["가"].dim
    # 배율은 목표만 정해지고 서서히 다가간다 — 한 번 부른다고 바로 그 값이 아니다.
    view.settle_view()
    assert abs(view._zoom - FOCUS_ZOOM) < 0.02, view._zoom
    view.clear_focus()
    assert not view.nodes["나"].dim

    # ★★ **표식을 두 번 누르면 화면 한가운데로 온다.** 가운데는 평소 항목들을 감싸는
    #   네모의 중심이라, 항목이 한쪽으로 몰리면 VC 표식이 구석으로 밀린다 —
    #   기록이 한두 장뿐인 첫날에 실제로 그랬다(오너가 창을 보고 짚었다).
    #   이 그래프는 밀어서 옮기는 것이 없고 돌리기만 되므로, **되돌릴 길이 여기뿐이다.**
    view._원점에두기 = False
    view._fit()
    치우친가운데 = QPointF(view._center_target)
    view.제자리로()
    assert view._center_target == QPointF(0.0, 0.0), view._center_target
    view.settle_view()
    view._place_mark()
    표식가운데 = view.mark.geometry().center()
    화면가운데 = view.viewport().rect().center()
    빗나감 = max(abs(표식가운데.x() - 화면가운데.x()), abs(표식가운데.y() - 화면가운데.y()))
    assert 빗나감 <= 2, (
        f"표식을 두 번 눌렀는데 가운데로 안 온다: {빗나감}px 빗나감 "
        f"(누르기 전 가운데는 {치우친가운데})")
    # 딴 항목을 고르면 그쪽을 따라가야 한다 — 원점에 붙어 있으면 고른 것이 구석에 뜬다.
    view.focus_on(["가"], zoom=FOCUS_ZOOM)
    assert not view._원점에두기, "초점을 잡았는데도 화면이 원점에 붙어 있다"
    view.clear_focus()

    # ★★ **손을 안 댄 채 정한 시간이 지나면 저절로 제자리로 온다**(설정 → 화면).
    #   두 번 누르는 길만 두면 「가운데가 아닌 줄도 모르고」 그냥 쓴다는 것이 오너 지시다.
    #   `_spin` 을 통째로 불러 **재깍이에 실제로 걸리는지**까지 본다 — 딴 데 넣으면
    #   자는 동안(90초 뒤)에는 안 돌아, 긴 시간을 고른 사람에게만 조용히 안 먹는다.
    view._원점에두기 = False
    view.자동제자리초 = 0.05
    view._깬때 = time.perf_counter()
    view._spin()
    assert not view._원점에두기, "손 댄 지 얼마 안 됐는데 벌써 되돌린다"
    view._깬때 = time.perf_counter() - 1.0
    view._spin()
    assert view._원점에두기, "정한 시간이 지났는데 표식이 제자리로 안 온다"
    view._원점에두기 = False
    view.자동제자리초 = 0.0                      # 「끔」
    view._깬때 = time.perf_counter() - 3600
    view._spin()
    assert not view._원점에두기, "「끔」인데도 저절로 되돌린다"
    view._깬때 = time.perf_counter()

    # **맨 앞줄은 이름이 보이고, 전부는 안 보인다.** 예전에는 손 얹은 것만 보였는데,
    # 항목이 백 개가 되자 점만 남고 글자가 하나도 없는 화면이 됐다 — 그래프가 이
    # 프로그램의 얼굴인데 쌓일수록 얼굴이 비었다. 반대로 전부 보이면 글자가 덮는다.
    many = GraphView()
    many.load({f"글 {i}": [] for i in range(500)},
              {f"글 {i}": "note" for i in range(500)})
    many.resize(900, 700)
    many.show()
    for _ in range(120):
        many.step_layout()
    many.project()
    named = [n for n in many.nodes.values() if n.label.isVisible()]
    assert named, "백 개인데 이름표가 하나도 없다"

    # **한 무리가 이름표를 독차지하면 안 된다.** 같은 크기끼리 이름으로 줄을 세우면
    # 「교육 일지 1·2·3…」처럼 한 틀로 찍어낸 것이 나란히 붙어 자리를 다 먹는다 —
    # 낯선 PC 에서 이름표가 거의 두 무리로만 채워졌다.
    무리 = GraphView()
    묶음 = {}
    for i in range(120):
        묶음[f"교육 일지 {i}"] = []
        묶음[f"납품 확인 {i}"] = []
        묶음[f"진짜 글 {i}"] = []
    무리.load(묶음, {t: "note" for t in 묶음})
    무리.resize(900, 700)
    무리.show()
    for _ in range(120):
        무리.step_layout()
    무리.project()
    뽑힘 = [n.title for n in 무리.nodes.values() if n.near]
    한무리 = max(sum(t.startswith(앞) for t in 뽑힘)
                for 앞 in ("교육 일지", "납품 확인", "진짜 글"))
    assert 한무리 <= len(뽑힘) * 0.7, f"한 무리가 다 먹었다: {한무리}/{len(뽑힘)}"
    무리.close()
    assert len(named) <= GraphView.LABEL_FRONT, len(named)

    # **깜박이면 안 된다.** 깊이순으로 매 프레임 다시 고르면 그래프가 도는 동안
    # 이름표가 떴다 사라진다 — 500개에서 「한 번에 1~5개, 그나마 깜박인다」로 걸렸다.
    # 개수보다 깜박이는 것이 더 나쁘다. 조금 도는 동안 뽑힌 무리가 그대로여야 한다.
    처음 = {n.title for n in many.nodes.values() if n.near}
    for _ in range(60):
        many.yaw += 0.0032        # 화면에서 도는 만큼. 도는 동안 무리가 바뀌면 깜박인다
        many.step_layout()
        many.project()
    나중 = {n.title for n in many.nodes.values() if n.near}
    바뀜 = len(처음 ^ 나중)
    # 솔직히 적어 둔다: **이 검사로 깜박임을 재현하지는 못했다.** 낯선 PC 에서 눈으로
    # 본 깜박임이 여기서는 안 났다(같은 종류만 500개라 자리다툼이 실제만큼 안 빡빡한 듯).
    # 그래서 이 두 줄은 「고침이 깜박임을 잡는다」의 증거가 아니라 **불변식**이다 —
    # 뽑힌 무리와 보이는 이름표가 도는 동안 크게 안 바뀌어야 한다는 것.
    보임 = {n.title for n in many.nodes.values() if n.label.isVisible()}
    assert 바뀜 <= 4, f"뽑힌 무리가 깜박인다: {바뀜}개 갈림"
    # 겹침 정리도 안 흔들려야 한다 — 실제로 눈에 보이는 것은 이쪽이다.
    for _ in range(30):
        many.yaw += 0.0032
        many.step_layout()
        many.project()
    갈림 = len(보임 ^ {n.title for n in many.nodes.values() if n.label.isVisible()})
    assert 갈림 <= 6, f"보이는 이름표가 깜박인다: {갈림}개 갈림"

    # ★★ **띄엄띄엄 견주는 것으로는 깜박임이 안 잡힌다.** 위 두 줄은 30프레임 전후를
    #   한 번 견줄 뿐이라, **두어 프레임 꺼졌다 다시 켜지는 것**(눈에 제일 거슬리는
    #   그것)은 그대로 지나간다. 실제로 위가 통과하는 판에서도 눈으로는 깜박였다.
    #   매 프레임 켜짐/꺼짐을 세고, 그중 **10프레임 안에 다시 뒤집힌 것**만 센다.
    #   맥에서 300프레임을 재서: 고치기 전 59번 → `LABEL_GRACE`·좌우 자리까지
    #   넣은 뒤 17번. 되돌리면(예: `LABEL_GRACE = 0`) 이 줄이 터진다.
    # ★★ 같은 고리에서 **움찔거림**도 같이 잰다. 오너가 창을 보고 「글자 알려주는 쪽이
    #   깜박일 때 움찔거린다」고 잡아냈다 — 깜박임을 줄이려고 비켜설 자리를 넷으로
    #   늘렸더니, 자리를 옮길 때 **한 프레임에 20~68px 를 순간이동**했던 것이다.
    #   횟수가 적어도 눈은 그 튐을 먼저 쫓는다. `LABEL_GLIDE` 로 미끄러뜨려 없앴다.
    #   되돌리면(`LABEL_GLIDE = 1.0`) 이 줄이 터진다: 그때 69번 · 가장 큰 걸음 68px.
    def 지금모습재기():
        모습, 자리 = set(), {}
        for n in many.nodes.values():
            if n.label.isVisible():
                모습.add(n.title)
                자리[n.title] = (n.label.pos().x(), n.label.pos().y())
        return 모습, 자리

    앞모습, 앞자리 = 지금모습재기()
    마지막뒤집힘: dict[str, int] = {}
    짧은깜박 = 큰걸음 = 0
    가장큰걸음 = 0.0
    for 프레임 in range(300):
        many.yaw += 0.0032
        many.step_layout()
        many.project()
        지금모습, 지금자리 = 지금모습재기()
        for 이름 in 앞모습 ^ 지금모습:
            전에 = 마지막뒤집힘.get(이름)
            if 전에 is not None and 프레임 - 전에 <= 10:
                짧은깜박 += 1
            마지막뒤집힘[이름] = 프레임
        for 이름, (x, y) in 지금자리.items():
            옛 = 앞자리.get(이름)
            if 옛 is None:
                continue        # 막 뜬 것은 옮긴 것이 아니다
            걸음 = math.hypot(x - 옛[0], y - 옛[1])
            가장큰걸음 = max(가장큰걸음, 걸음)
            if 걸음 > 20:
                큰걸음 += 1
        앞모습, 앞자리 = 지금모습, 지금자리
    assert 짧은깜박 <= 30, f"이름표가 깜박인다: 300프레임에 짧은 뒤집힘 {짧은깜박}번"
    assert 큰걸음 == 0, (
        f"이름표가 움찔거린다: 한 프레임에 20px 넘게 튄 걸음 {큰걸음}번 · "
        f"가장 큰 걸음 {가장큰걸음:.1f}px")
    many.close()

    # 손을 얹으면 그것과 **이어진 것**의 이름이 뜬다.
    view.set_hover("가")
    assert view.nodes["가"].hovered and view.nodes["나"].linked
    assert view.nodes["가"].label.isVisible() and view.nodes["나"].label.isVisible()
    assert not view.nodes[ROOT].label.isVisible(), "안 이어진 것까지 떴다"

    # **겨눌 것에 손을 얹으면 멈춘다.** 도는 동안 겨냥하면 빗나가고 읽을 수도 없다.
    view.set_hover(None)
    돌기전 = view.yaw
    view._spin()
    assert view.yaw != 돌기전, "손을 안 얹었는데 안 돈다"

    # 아래 멈춤 검사는 전부 **손이 얹혀 있는 것으로** 두고 잰다. 화면 없이 돌리면
    # `underMouse()` 가 늘 거짓이라, 안 그러면 옛 코드에서도 그냥 돌아 버려서
    # 「빈 자리에서도 멈춘다」를 아무 검사도 못 잡는다.
    class _얹힘(type(view)):
        def underMouse(self):
            return True
    본디, view.__class__ = type(view), _얹힘

    # 항목에 손을 얹고 **가만히** 있으면 멈춘다 — 읽고 겨누는 자세다.
    view.set_hover("가")
    view._moved_at = time.perf_counter() - 1.0
    멈춤전 = view.yaw
    view._spin()
    assert view.yaw == 멈춤전, "항목에 손을 얹고 가만히 있는데도 돈다"

    # ★ **빈 자리는 겨누는 게 아니다.** 마우스를 그래프 위 아무 데나 두고 손을 떼면
    # 그대로 멈춰 있었다(오너: 「가만히 냅두면 멈춘다」). 겨눌 것이 없으면 계속 돈다.
    view.set_hover(None)
    view._moved_at = time.perf_counter() - 1.0
    돌기전 = view.yaw
    view._spin()
    assert view.yaw != 돌기전, "빈 자리에 손만 얹혔는데 멈춘다"

    # ★ **오래 가만히 있으면 읽는 게 아니라 자리를 뜬 것**이다. 다시 돈다.
    view.set_hover("가")
    view._moved_at = time.perf_counter() - (view.AWAY_SEC + 1.0)
    돌기전 = view.yaw
    view._spin()
    assert view.yaw != 돌기전, "자리를 뜬 뒤에도 멈춰 있다"

    # **움직이는 동안에는 돈다.** 안 그러면 다음 이름표를 보려고 그래프 밖으로 손을
    # 빼야 하는데 그걸 아무도 안 배운다.
    view._moved_at = time.perf_counter()
    돌기전 = view.yaw
    view._spin()
    assert view.yaw != 돌기전, "손을 움직이는데 안 돈다"
    view.__class__ = 본디

    # ★★ **재고 버리던 값을 남긴다.** 「부드러운가」는 화면을 찍어서 보는 쪽이
    # 구조적으로 못 재는 자리였다. 그런데 간격은 이미 매 판 재고 있었다 —
    # 세어 두기만 하면 사람 눈 대신 숫자가 말한다.
    셈 = 멈칫셈()
    셈.본다(0.033, 0.033)          # 제때 온 판
    셈.본다(0.080, 0.033)          # 두 배 넘게 밀림
    셈.본다(0.300, 0.033)          # 다섯 배 넘게 — 눈에 걸리는 자리
    assert (셈.판, 셈.두배, 셈.다섯배) == (3, 1, 1), (셈.판, 셈.두배, 셈.다섯배)
    assert abs(셈.제일느린 - 0.300) < 1e-9
    # 두 배와 다섯 배를 겹쳐 세지 않는다 — 겹쳐 세면 몫이 100%를 넘는다.
    assert 셈.두배 + 셈.다섯배 <= 셈.판

    # ★ **쉬었다 온 판은 안 센다.** 창을 가렸다 켜면 몇 초가 그냥 뛰는데, 그걸 세면
    # 「멈칫」이 아니라 「안 보고 있었다」를 세게 된다.
    앞 = (셈.판, 셈.다섯배)
    셈.본다(5.0, 0.033)
    assert (셈.판, 셈.다섯배) == 앞, "쉬었다 온 판을 멈칫으로 셌다"

    assert "안 돌았다" in 멈칫셈().말()

    # ★★ **딴 프로세스가 읽을 수 있어야 한다.** 이 셈은 창을 그리는 프로세스가
    # 세는데 `--report` 는 별도 프로세스로 돈다 — 174분을 켜 두고도 진단 묶음에는
    # 늘 「안 돌았다」가 찍혔다. **값이 안 쌓인 게 아니라 딴 자리를 본 것**이었다.
    import os
    import subprocess as 프로세스
    import sys
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as 임시:
        났다 = 프로세스.run(
            [sys.executable, "-c",
             "import graph3d, sys;"
             "s = graph3d.멈칫셈();"
             "s.적을때마다 = 1;"
             "[s.본다(0.033, 0.033) for _ in range(3)];"
             "s.적어두기();"
             "sys.stdout.write(graph3d.멈칫셈.읽어오기())"],
            env=dict(os.environ, VC_DATA=임시, PYTHONIOENCODING="utf-8",
                     PYTHONPATH=str(Path(__file__).resolve().parent)),
            capture_output=True, text=True, encoding="utf-8", timeout=90)
        # 적은 프로세스가 죽지 않았고, 남긴 값을 그 자리에서 도로 읽는다.
        assert "3판" in 났다.stdout, (났다.stdout, 났다.stderr[-300:])

        # **딴 프로세스에서도 같은 값이 보인다.** 이게 이 고침의 핵심이다.
        딴쪽 = 프로세스.run(
            [sys.executable, "-c",
             "import graph3d, sys; sys.stdout.write(graph3d.멈칫셈.읽어오기())"],
            env=dict(os.environ, VC_DATA=임시, PYTHONIOENCODING="utf-8",
                     PYTHONPATH=str(Path(__file__).resolve().parent)),
            capture_output=True, text=True, encoding="utf-8", timeout=90)
        assert "3판" in 딴쪽.stdout, (딴쪽.stdout, 딴쪽.stderr[-300:])

    # 아무것도 안 적힌 자리에서는 「안 돌았다」다 — 없는 값을 지어내지 않는다.
    with tempfile.TemporaryDirectory() as 빈자리:
        빈 = 프로세스.run(
            [sys.executable, "-c",
             "import graph3d, sys; sys.stdout.write(graph3d.멈칫셈.읽어오기())"],
            env=dict(os.environ, VC_DATA=빈자리, PYTHONIOENCODING="utf-8",
                     PYTHONPATH=str(Path(__file__).resolve().parent)),
            capture_output=True, text=True, encoding="utf-8", timeout=90)
        assert 빈.stdout.strip() == "안 돌았다", 빈.stdout
    assert "제일 느린 판 300ms" in 셈.말(), 셈.말()

    # ★★ **「기대보다 얼마나 늦었나」만 말하면 못 읽는다.** 늦춤이 걸려 간격이
    # 늘어나 있으면 밀림 몫은 저절로 내려간다 — **느려진 것이 좋아진 것처럼 보인다.**
    # 시험하는 쪽이 「초당 16판인데 밀림은 10%」를 보고 그 둘을 못 갈랐다.
    빠름 = 멈칫셈()
    for _ in range(100):
        빠름.본다(0.033, 0.033)          # 33ms 목표를 제때 지킴
    느림 = 멈칫셈()
    for _ in range(100):
        느림.본다(0.120, 0.120)          # 늦춰져서 120ms 가 「제때」가 된 자리
    # 둘 다 밀림은 0% 다 — 그것만 보면 같아 보인다.
    assert "밀림 0(0.0%)" in 빠름.말() and "밀림 0(0.0%)" in 느림.말()
    # **그런데 초당 판수와 지금 간격이 갈라 준다.**
    assert "초당 30판" in 빠름.말() and "간격 바람 33ms" in 빠름.말(), 빠름.말()
    assert "초당 8판" in 느림.말() and "간격 바람 120ms" in 느림.말(), 느림.말()
    # ★ **바라는 간격과 실제 간격의 차이가 그리는 값이다.** 시험하는 쪽이
    # 「초당 16판이면 62ms 인데 간격은 41ms — 그 21ms 는 어디서 나나」라고 물었다.
    그림값 = 멈칫셈()
    for _ in range(50):
        그림값.본다(0.055, 0.033)      # 33ms 를 바랐는데 55ms 가 들었다
    assert "그리는 값 22ms" in 그림값.말(), 그림값.말()

    # 진짜 자전이 이 셈을 채우는지 본다. **안 채우면 진단 묶음이 늘 「안 돌았다」다.**
    앞판 = 멈칫.판
    view._last_spin = time.perf_counter() - 0.5
    view._spin()
    assert 멈칫.판 > 앞판, "자전이 도는데 셈이 안 는다"

    # ★ **자전이 파일에도 남겨야 한다.** 세기만 하고 안 남기면 `--report` 는
    # 영영 「안 돌았다」를 본다 — 174분을 켜 두고도 그랬다.
    import paths as _자리9

    # ★ 자리를 **짐작하지 않고 물어본다.** 여기서 `VC_DATA` 나 cwd 로 찍었더니,
    #   `기록자리.txt` 로 창고를 못 박자 기계 파일이 앱 자리로 옮겨가 검사만 깨졌다
    #   (코드는 멀쩡했다). 쓰는 쪽과 **같은 함수**로 묻는 것이 맞다.
    자전표 = _자리9.기계자리("vc-자전.json")
    # **먼저 지운다.** 안 지우면 묵은 파일이 남아 있어, 안 남기게 고쳐 놔도
    # 검사가 통과한다 — 실제로 그렇게 한 번 헛통과했다.
    묵은 = 자전표.read_text(encoding="utf-8") if 자전표.exists() else None
    자전표.unlink(missing_ok=True)
    옛간격, 멈칫.적을때마다 = 멈칫.적을때마다, 1
    try:
        view._last_spin = time.perf_counter() - 0.5
        view._spin()
        assert 자전표.exists(), "자전이 도는데 파일에 안 남는다"
    finally:
        멈칫.적을때마다 = 옛간격
        if 묵은 is None:
            자전표.unlink(missing_ok=True)
        else:
            자전표.write_text(묵은, encoding="utf-8")

    # ★★ **보는 사람이 없으면 안 그린다.** 네 시간을 아무도 안 만졌는데 코어 하나를
    # 91% 태우고 있었다. 20년 켜 둘 물건에서 이건 배터리와 팬으로 사람이 바로 느낀다.
    # 앞 검사가 「손을 얹은 채」로 두고 갔다. 여기서는 자리를 비우고 잰다 —
    # 안 비우면 「멈춤」과 「잠듦」이 섞여서 무엇 때문에 안 도는지 못 가린다.
    view.set_hover(None)
    view.spin.setInterval(33)
    view.깨우기()
    돌기전 = view.yaw
    view._last_spin = time.perf_counter() - 0.5
    view._spin()
    assert view.yaw != 돌기전, "손이 막 닿았는데 안 돈다"

    # 한참 아무 일도 없으면 잠든다 — 멈추는 대신 늦춘다.
    view._깬때 = time.perf_counter() - (view.잠들때까지 + 1)
    잠들기전 = view.yaw
    view._last_spin = time.perf_counter() - 0.5
    view._spin()
    assert view.yaw == 잠들기전, "아무도 안 만지는데 계속 돈다"
    assert view.spin.interval() == view.잠든간격, view.spin.interval()
    # ★★ **그리는 것이 둘이다.** 그래프만 재웠더니 「앞에 있고 손 안 댐」이 21% 로만
    # 내려갔다(최소화는 1.8%). 그 차이가 **표식의 불티 1800개**였다.
    assert view.mark.paused, "그래프는 자는데 표식이 계속 그린다"

    # 손이 닿으면 곧바로 깬다. 안 깨면 사람이 만져도 화면이 굳어 보인다.
    view.깨우기()
    깨기전 = view.yaw
    view._last_spin = time.perf_counter() - 0.5
    view._spin()
    assert view.yaw != 깨기전, "손이 닿았는데 안 깬다"
    assert view.spin.interval() == 33, view.spin.interval()
    assert not view.mark.paused, "손이 닿았는데 표식이 안 깬다"

    # 창이 안 보이면 사람이 만졌든 아니든 안 그린다.
    view.hide()
    view.깨우기()
    가려진뒤 = view.yaw
    view._last_spin = time.perf_counter() - 0.5
    view._spin()
    assert view.yaw == 가려진뒤, "창이 가려졌는데 계속 그린다"
    view.show()
    view.spin.setInterval(33)

    # ★ **한 판 밀린 것으로는 안 늦춘다.** 디스크 한 번이면 프레임은 그냥 밀린다.
    # 곧장 늦추면 되돌아오는 데 열 판이 넘게 걸리고 그 구간이 멈칫으로 보인다.
    view.spin.setInterval(33)
    view._slow = 0
    view._last_spin = time.perf_counter() - 0.5      # 크게 밀린 한 판
    view._spin()
    assert view.spin.interval() == 33, "한 판 밀렸다고 곧장 늦춘다"
    for _ in range(3):                                # 연달아 밀리면 늦춘다
        view._last_spin = time.perf_counter() - 0.5
        view._spin()
    assert view.spin.interval() > 33, "연달아 밀리는데도 안 늦춘다"
    assert view.spin.interval() <= 120, "초당 다섯 장까지 떨어진다"
    view.spin.setInterval(33)
    view._slow = 0

    # ★ **표식이 비켜나면 원래 자리를 손수 지운다.** 뒤가 비치는 자식 위젯이라
    # 안 지우면 옮겨간 자리에 네모가 남는다(오너: 「사각형 박스 나왔다 사라진다」).
    지운자리 = []
    view.viewport().update = lambda *a: 지운자리.append(a)
    view._place_mark()
    assert not 지운자리, "안 옮겼는데 다시 그린다"
    # ★ 로고에는 **하한(140px)** 이 있다. 점 셋짜리 그래프는 거기 눌려 있어서 배율을
    #   바꿔도 크기가 그대로다 — 하한 위로 올려놓고 재야 「옮겨갔는지」를 실제로 본다.
    본배율 = view._zoom
    view._zoom = 1.5
    view._place_mark()
    assert view.mark.width() > 140, f"아직 하한에 눌려 있다: {view.mark.width()}"
    지운자리.clear()
    섰던 = view.mark.geometry()
    view._zoom *= 1.7
    view._place_mark()
    assert 지운자리, "표식이 옮겨갔는데 원래 자리를 안 지운다"
    덮은 = 지운자리[-1][0]
    assert 덮은.contains(섰던), f"비켜난 자리를 덜 지운다: {덮은} ⊅ {섰던}"
    del view.viewport().update
    view._zoom = 본배율
    view._place_mark()

    # ★★ **글이 쌓여도 로고는 같은 크기로 보인다**(오너 2026-09-21).
    #   전에는 구가 커진 만큼 `_fit` 이 물러나 로고가 같이 작아졌다 — 50장 296px 이
    #   1000장에서 하한 168px 까지 내려갔다. 로고는 「여기가 가운데다」를 알리는
    #   표지라 창고가 클수록 오히려 또렷해야 한다.
    잰것 = {}
    for 몇 in (50, 300, 1000):
        재개 = GraphView()
        재개.resize(1000, 700)
        묶음 = {f"글{i}": [] for i in range(몇 - 1)}
        재개.load(묶음, {t: "메모" for t in 묶음})
        재개.settle_view(200)
        잰것[몇] = 재개.mark.width()
        재개.deleteLater()
    assert min(잰것.values()) > 0.9 * max(잰것.values()), \
        f"글이 쌓이니 로고가 작아진다: {잰것}"
    # 하한에 눌려서 「같아 보이는」 것이 아니어야 한다 — 그러면 아무것도 안 잰 셈이다
    assert min(잰것.values()) > 140, f"하한에 눌려 있다: {잰것}"

    # **1픽셀 떨림은 움직임이 아니다.** 사람 손은 완전히 안 멈춘다 — 거리 문턱이 없으면
    # 손을 얹은 채로는 영영 못 멈추고, 멈추려면 손을 떼야 한다. 그건 뜻이 뒤집힌다.
    from PyQt5.QtCore import QEvent
    from PyQt5.QtGui import QMouseEvent

    def 흔들기(dx, dy, from_=(300, 300)):
        return QMouseEvent(QEvent.MouseMove,
                           QPointF(from_[0] + dx, from_[1] + dy),
                           Qt.NoButton, Qt.NoButton, Qt.NoModifier)

    view._still_at = None
    # 떨림은 **항목 위에서** 떠는 것이 문제다. 손끝에 겨눌 것이 있는 자리로 둔다.
    view._node_at = lambda pos: view.nodes["가"]
    view.mouseMoveEvent(흔들기(0, 0))          # 첫 자리를 잡는다
    view._moved_at = time.perf_counter() - 1.0  # 멈춘 지 좀 된 것으로 둔다
    for dx, dy in ((1, 0), (0, 1), (1, 1), (0, 0), (1, 0)):
        view.mouseMoveEvent(흔들기(dx, dy))
    멈춰야 = view.yaw
    view._spin()
    assert view.yaw == 멈춰야, "1픽셀 떨림을 움직임으로 센다"

    view.mouseMoveEvent(흔들기(30, 30))        # 진짜 움직임
    돌아야 = view.yaw
    view._spin()
    assert view.yaw != 돌아야, "정말 움직였는데 안 돈다"
    view.__class__ = GraphView

    # **짐작한 선과 사람이 적은 선은 안 섞인다.** 하나는 「이것과 저것은 이어진다」고
    # 사람이 말한 것이고, 다른 하나는 우리가 벡터로 짐작한 것이다. 같이 그리면
    # 둘이 같은 말인 줄 안다.
    엮임 = GraphView()
    엮임.load({"가": ["나"], "나": [], "다": []},
              {"가": "note", "나": "note", "다": "note"},
              soft={"다": ["가"]})
    assert ("가", "나") in 엮임.edges and ("다", "가") in 엮임.edges, 엮임.edges
    assert tuple(sorted(("다", "가"))) in 엮임.soft, 엮임.soft
    assert tuple(sorted(("가", "나"))) not in 엮임.soft, "사람이 적은 선이 짐작으로 셌다"
    # 이미 사람이 이은 것을 뜻으로 또 잇지 않는다 — 한 줄이면 된다.
    엮임.load({"가": ["나"], "나": [], "다": []},
              {"가": "note", "나": "note", "다": "note"},
              soft={"가": ["나"]})
    assert not 엮임.soft, 엮임.soft
    엮임.close()

    view.set_hover(None)
    assert not any(n.hovered or n.linked for n in view.nodes.values())
    # 손을 떼면 「이어진 것」 표시는 풀린다. 이름표는 맨 앞줄 것이 남는다 —
    # 그게 없으면 백 개짜리 화면이 점만 남는다(위 검사 참고).
    assert not any(n.hovered or n.linked or n.focused for n in view.nodes.values())

    # **선이 달아오른 상태로도 한 번 그려 본다.** 그 가지에만 쓰는 이름이 하나
    # 빠져 있었는데(`QLinearGradient`), 갓 오간 연결이 있어야만 지나는 자리라
    # 낯선 PC 에서 2분에 traceback 329건이 쌓이고서야 드러났다.
    # 그리기는 예외를 못 올려 보낸다 — 여기서 안 밟으면 아무도 안 밟는다.
    from PyQt5.QtGui import QPixmap

    for name in ("가", "나"):
        view.nodes[name].speaking = 1.0
        view.nodes[name].dim = False
    view.resize(400, 300)
    shot = QPixmap(400, 300)
    painter = QPainter(shot)
    try:
        # `render()` 로는 안 된다 — 그리다 난 예외는 Qt 가 삼켜서 검사가 초록불이다.
        # **직접 부른다.** 그래야 터진 것이 여기까지 올라온다.
        view.drawBackground(painter, QRectF(-400, -300, 800, 600))
    finally:
        painter.end()

    # ★★ **무리가 한가운데 앉는다**(오너 2026-09-20: 「치우침은 없이」).
    #   VC 만 원점에 못 박혀 있고 나머지는 그렇지 않아, 반발력의 작은 비대칭과 처음
    #   뿌린 자리의 쏠림이 씻기지 않고 쌓였다 — 재 보니 무게중심이 (182,-114,-55) 에서
    #   **치우친 채 안정**됐고, 표식이 늘 무리 한쪽에 붙어 보였다.
    치우 = GraphView()
    치우.resize(900, 700)
    치우.show()
    치우.load({f"글{i}": [f"글{(i * 7 + 3) % 40}"] for i in range(40)},
             {f"글{i}": "note" for i in range(40)})
    for 점 in 치우.nodes.values():        # 일부러 한쪽으로 몰아 놓는다
        점.p = [점.p[0] + 400.0, 점.p[1] + 250.0, 점.p[2] - 180.0]
    for _ in range(260):
        치우.step_layout()
    흐른 = [x for x in 치우.nodes.values() if x.title != ROOT]
    무게 = [sum(x.p[i] for x in 흐른) / len(흐른) for i in range(3)]
    assert max(abs(v) for v in 무게) < 12, f"무리가 한쪽으로 치우친 채 굳는다: {무게}"
    # 가운데로 옮기면서 모양까지 뭉개면 안 된다 — 껍질 언저리에 남아 있어야 한다
    거리 = sorted(math.sqrt(sum(c * c for c in x.p)) for x in 흐른)
    assert 거리[len(거리) // 2] > 치우.shell * 0.5, f"가운데로 빨려 들어갔다: {거리[len(거리)//2]:.0f}"

    # ★ 항목·표식을 20% 키웠다(오너 2026-09-20). 정수로 두면 7 → 8(14%) 밖에 못 간다.
    assert abs(RADIUS_OTHER - 8.4) < 0.01, RADIUS_OTHER
    assert isinstance(node_radius("아무거나", "note"), float), "정수로 돌아갔다 — 20% 가 안 된다"

    # ★★ **평소 선은 표식을 피하고, 손 얹은 선은 표식 위로 간다**(오너 2026-09-20).
    층 = 치우._선위층
    assert 층.parent() is 치우.viewport(), "덮개가 뷰포트에 안 붙었다"
    assert 층.testAttribute(Qt.WA_TransparentForMouseEvents), "덮개가 누름을 가로챈다"
    자식들 = 치우.viewport().children()
    assert 자식들.index(층) > 자식들.index(치우.mark), "덮개가 표식보다 아래다 — 선이 안 보인다"

    def 그려본(뷰):
        """덮개가 실제로 무엇을 그렸는지 **칠해진 점 수**로 잰다."""
        from PyQt5.QtGui import QImage

        층2 = 뷰._선위층
        층2.setGeometry(뷰.viewport().rect())
        w, h = max(층2.width(), 1), max(층2.height(), 1)
        img = QImage(w, h, QImage.Format_ARGB32)
        img.fill(0)
        q = QPainter(img)
        층2.render(q)
        q.end()
        return sum(1 for y in range(0, h, 3) for x in range(0, w, 3)
                   if img.pixelColor(x, y).alpha() > 0)

    치우.set_hover(None)
    치우.project()
    assert 그려본(치우) == 0, "손을 안 얹었는데 덮개가 뭔가 그린다"
    이은것 = next((a for a, b in 치우.edges
                 if a in 치우.nodes and b in 치우.nodes
                 and 치우.nodes[a].isVisible() and 치우.nodes[b].isVisible()), None)
    assert 이은것 is not None, "이어진 항목이 없어 덮개를 못 잰다"
    치우.set_hover(이은것)
    치우.project()
    assert 그려본(치우) > 0, "손을 얹었는데 표식 위에 선이 안 그려진다"
    # ★ 손 얹은 선의 굵기·밝기는 **한 자리에서** 나와야 한다(오너 2026-09-20 로 줄였다).
    #   장면과 덮개 두 곳에서 그리므로, 값을 각자 적어 두면 한쪽만 고쳐져 갈라진다.
    import pathlib as _길9

    본문 = _길9.Path(__file__).read_text(encoding="utf-8")
    # (검사 글 자체가 세어지지 않게 조각을 붙여 만든다)
    꼴 = "theme.T.ACCENT, " + "손선밝기), " + "손선굵기"
    assert 본문.count(꼴) == 2, f"손 얹은 선을 두 곳에서 따로 그린다: {본문.count(꼴)}군데"
    assert 손선굵기 <= 1.0 and 손선밝기 <= 130, (손선굵기, 손선밝기)
    # ★ **로고 둘레에 원을 그리지 않는다.** 표식 자리를 둥글게 잘라냈더니 그 자리가
    #   테두리로 보였다(오너가 짚었다). 가리는 일은 표식 위젯이 제 모양대로 한다.
    자름 = "set" + "ClipPath"
    assert 자름 not in 본문, "표식 자리를 잘라낸다 — 로고 둘레에 원이 생긴다"

    # ★★ **둘레만 보기**(로컬 그래프 · 오너 2026-09-20). 가라앉히는 것과 다르다 —
    #   흐리게 남겨 두면 여전히 화면을 채운다. **감춰야** 좁힌 뜻이 산다.
    가운데 = next(iter(치우.edges))[0]
    이웃수 = len(치우.이웃들(가운데))
    assert 이웃수 >= 1, 이웃수
    남은 = 치우.둘레만(가운데)
    assert 남은 == 이웃수 + 1, (남은, 이웃수)
    보이는것 = {t for t, x in 치우.nodes.items() if x.isVisible()}
    assert 가운데 in 보이는것, "가운데 항목이 안 보인다"
    assert len(보이는것) <= 이웃수 + 1, f"감춰야 할 것이 남았다: {len(보이는것)}"
    assert len(보이는것) < len(치우.nodes), "아무것도 안 감췄다"
    assert 치우.둘레중 == 가운데, 치우.둘레중
    # 풀면 전부 돌아온다(가운데 표식 자리만 빼고)
    assert 치우.둘레풀기() is True
    돌아온 = {t for t, x in 치우.nodes.items() if x.isVisible()}
    assert len(돌아온) >= len(치우.nodes) - 1, (len(돌아온), len(치우.nodes))
    assert 치우.둘레풀기() is False, "보고 있지도 않은데 풀었다고 한다"
    assert 치우.둘레만("없는 항목ZZZ") == 0, "없는 항목에도 둘레를 연다"

    치우.set_hover(None)
    치우.deleteLater()

    print("graph3d self-check 통과")


if __name__ == "__main__":
    import os
    import sys

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt5.QtWidgets import QApplication

    # QApplication을 변수에 안 담으면 가비지 컬렉션돼 종료할 때 조용히 죽는다.
    app = QApplication(sys.argv)
    _self_check()
