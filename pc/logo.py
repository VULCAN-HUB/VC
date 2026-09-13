"""불칸 표식 — VC 마크와 둘레를 도는 불꽃 (결정 44).

말할 때 **로고가 달아오르고 불티가 흩날린다.** 화면 어디를 보고 있든 "지금 불칸이
말하는 중"이 보이게 하는 게 목적이다. 소리를 못 듣는 상황에서도 상태가 읽혀야 한다.

    쉴 때    실낱같이 도는 불티, 로고는 은은하게
    들을 때  불티가 조금 밝아지고 링이 촘촘해진다
    말할 때  로고가 달아오르고 불티가 튄다

**이미지 파일을 안 쓴다.** 선과 점으로 그리면 테마 색을 따라가고, 어느 크기에서도
안 뭉개지고, 배포에 파일이 안 딸려간다.

불티는 미리 만들어 두고 각도만 돌린다 — 매 프레임 새로 뽑으면 반짝임이 춤을 춘다.
"""

from __future__ import annotations

import math
import random

from PyQt5.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt5.QtGui import (QBrush, QColor, QPainter, QPainterPath, QPen, QPixmap,
                         QRadialGradient)
from PyQt5.QtWidgets import QWidget

import theme

SPARKS = 1800  # 불티 개수. 많을수록 링이 촘촘하지만 그리는 값이 든다


CLUSTERS = 5  # 불티가 뭉치는 자리 수. 고르게 뿌리면 링이 아니라 점선 원이 된다
CLUSTER_ANGLES = [i * math.tau / CLUSTERS for i in range(CLUSTERS)]
CLUSTER_WEIGHTS = [5, 1, 4, 1, 3]  # 무리마다 밀도가 다르다


class Ember:
    """불티 하나. 무리를 이뤄 궤도를 돌고 밝기가 오르내린다.

    고르게 흩뿌리면 기계로 찍은 원처럼 보인다. **몇 군데로 뭉쳐야** 불티가 날리는
    것처럼 읽힌다 — 참조한 그림도 성긴 데와 빽빽한 데가 갈린다.
    """

    __slots__ = ("angle", "radius", "size", "speed", "phase", "life", "trail")

    def __init__(self, rng: random.Random) -> None:
        # 무리 중심 근처에 몰아 놓는다. 가끔은 무리를 벗어난 놈도 둔다.
        # 무리마다 무게가 다르다. 빽빽한 데와 성긴 데가 갈려야 흩날려 보인다.
        seed_angle = rng.choices(CLUSTER_ANGLES, CLUSTER_WEIGHTS)[0]
        spread = 0.22 if rng.random() < 0.90 else 0.6
        self.angle = seed_angle + rng.gauss(0, spread)

        # 링은 가늘어야 원으로 읽힌다. 두꺼우면 뿌연 띠가 된다 — 대부분 같은 반지름에
        # 두고 일부만 안팎으로 흘린다.
        self.radius = rng.gauss(1.0, 0.013) if rng.random() < 0.94 else rng.gauss(1.0, 0.06)
        self.size = rng.uniform(0.16, 0.55) if rng.random() < 0.90 else rng.uniform(0.7, 1.2)
        self.speed = rng.uniform(0.06, 0.26) * rng.choice((1, 1, 1, -1))
        self.phase = rng.uniform(0, math.tau)
        self.life = 1.0 if rng.random() < 0.08 else rng.uniform(0.30, 0.85)
        self.trail = rng.random() < 0.10  # 몇 개만 꼬리를 남긴다


_DOTS: dict[tuple, QPixmap] = {}


def _dot(color: QColor, size: float, alpha: int) -> QPixmap:
    """불티 한 점을 미리 그려 둔다.

    입자마다 브러시를 새로 만들어 원을 그리면 1800개에 16ms가 든다 — 프레임 예산의
    절반이다. 크기와 밝기를 잘게 나눠 **미리 그린 점을 찍는 것**으로 바꾸면 눈에는
    같고 값은 몇 분의 일이다. 종류가 수백 개를 넘지 않아 캐시가 커지지 않는다.
    """
    key = (round(size * 4), alpha >> 3, color.rgb())
    px = _DOTS.get(key)
    if px is None:
        r = max(0.35, key[0] / 4.0)
        d = int(math.ceil(r * 2)) + 2
        px = QPixmap(d, d)
        px.fill(Qt.transparent)
        q = QPainter(px)
        q.setRenderHint(QPainter.Antialiasing)
        q.setPen(QPen(Qt.NoPen))
        q.setBrush(QBrush(theme.rgba(color, min(255, (key[1] << 3) + 4))))
        q.drawEllipse(QPointF(d / 2, d / 2), r, r)
        q.end()
        _DOTS[key] = px
    return px


class VulcanMark(QWidget):
    """가운데 표식. `state`로 쉴 때/들을 때/말할 때를 바꾼다."""

    STATES = ("idle", "listening", "speaking")

    def __init__(self, size: int = 220) -> None:
        super().__init__()
        self.setMinimumSize(size, size)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        # 위젯이 제 배경을 칠하면 검은 화면 위에 밝은 네모가 뜬다. 뒤가 비쳐야 한다.
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet("background: transparent;")
        self.rng = random.Random(11)  # 같은 모양으로 뜨게
        self.embers = [Ember(self.rng) for _ in range(SPARKS)]
        self.state = "idle"
        self.heat = 0.0  # 0~1. 상태가 바뀌면 이 값이 천천히 따라간다
        self.t = 0.0
        self.level = 0.0  # 마이크 크기. 말할 때 불티가 그만큼 튄다
        self.paused = False

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)

    # --- 상태 ---------------------------------------------------------

    def set_state(self, state: str) -> None:
        if state in self.STATES:
            self.state = state

    def set_level(self, level: float) -> None:
        self.level = max(0.0, min(level * 6.0, 1.0))

    @property
    def target_heat(self) -> float:
        return {"idle": 0.18, "listening": 0.45, "speaking": 1.0}[self.state]

    def set_paused(self, paused: bool) -> None:
        """연출을 재운다.

        불티 1800개를 33ms마다 다시 그리는 값이 만만치 않다. 뒤에서 파일을 훑는 동안
        그리기가 화면 실을 채우면 훑기가 굶는다 — 2만 개 첫 색인이 7초에서 45초 넘게
        늘어난 원인의 절반이 이것이었다.
        """
        self.paused = paused

    def _tick(self) -> None:
        if self.paused:
            return
        # 갑자기 켜고 끄면 깜빡이는 표시등처럼 보인다. 달아오르고 식는 데 시간을 준다.
        self.heat += (self.target_heat - self.heat) * 0.12
        self.t += 0.033
        self.update()

    # --- 그리기 -------------------------------------------------------

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        base = min(w, h) / 2
        heat = self.heat + self.level * 0.35 * (self.state == "speaking")
        accent = theme.T.ACCENT

        # 작은 자리에서는 불티를 접고 표식만 키운다.
        #
        # 창 아이콘·작업표시줄은 16~48px다. 그 크기에 링을 그리면 불티가 자리를 다
        # 먹고 VC는 얼룩이 된다 — 실제로 깔아 보니 96px까지도 글자가 안 읽혔다.
        # 더 작아지면 속 빈 윤곽선이 1픽셀 밑으로 내려가 사라지므로 통째로 채운다.
        if base >= 64:
            self._draw_haze(p, cx, cy, base, heat, accent)
            self._draw_embers(p, cx, cy, base * 0.80, heat, accent)
            self._draw_mark(p, cx, cy, base * 0.30, heat, accent)
        else:
            # 표식이 가로로 1.383배 넓다. r은 **세로 절반**이라 가로가 자리를
            # 넘지 않게 그 배율로 나눠야 한다 — 안 나누면 좌우가 잘린다.
            fit = base * 0.94 / self._RATIO
            self._draw_mark(p, cx, cy, fit, heat, accent, solid=base < 20)
        p.end()

    def _draw_haze(self, p, cx, cy, base, heat, accent) -> None:
        """뒤에 깔리는 열기.

        가운데를 밝히면 붉은 공이 떠 있는 꼴이 된다. 참조한 그림처럼 **가운데는 어둡고
        링을 따라 은은해야** 불티가 도는 것으로 읽힌다 — 그래서 도넛 모양으로 깐다.
        """
        # 빛은 **위젯 안에서 0으로 잦아들어야** 한다. 넘치면 위젯 네모가 밝은 사각형으로
        # 드러난다 — 실제로 그렇게 보였다.
        outer = base * 0.99
        ring = base * 0.80
        glow = QRadialGradient(QPointF(cx, cy), outer)
        glow.setColorAt(0.0, QColor(0, 0, 0, 0))
        glow.setColorAt(max(0.0, ring / outer - 0.22), theme.rgba(accent, int(0 + 2 * heat)))
        glow.setColorAt(min(0.995, ring / outer), theme.rgba(accent, int(2 + 7 * heat)))
        glow.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setPen(QPen(Qt.NoPen))
        p.setBrush(QBrush(glow))
        p.drawEllipse(QPointF(cx, cy), outer, outer)

        # 표식 바로 뒤에만 아주 옅게. 글자가 검은 구멍에 떠 있지 않게 하는 정도다.
        core = QRadialGradient(QPointF(cx, cy), base * 0.38)
        core.setColorAt(0.0, theme.rgba(accent, int(1 + 5 * heat)))
        core.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setBrush(QBrush(core))
        p.drawEllipse(QPointF(cx, cy), base * 0.38, base * 0.38)

    def _draw_embers(self, p, cx, cy, ring, heat, accent) -> None:
        p.setRenderHint(QPainter.Antialiasing, False)  # 점은 미리 그려 뒀다
        p.setPen(QPen(Qt.NoPen))
        for e in self.embers:
            # 반짝임. 불티마다 위상이 달라야 무리가 살아 있는 것처럼 보인다.
            twinkle = 0.5 + 0.5 * math.sin(self.t * 2.2 + e.phase)
            bright = e.life * (0.18 + 0.70 * heat) * (0.30 + 0.70 * twinkle)
            if bright < 0.04:
                continue

            angle = e.angle + self.t * e.speed
            # 말할 때 바깥으로 튄다. 숨 쉬듯 안팎으로 흔들리는 것과 겹친다.
            spread = 1.0 + 0.05 * math.sin(self.t * 1.3 + e.phase) + 0.10 * heat
            r = ring * e.radius * spread
            x, y = cx + math.cos(angle) * r, cy + math.sin(angle) * r

            size = e.size * (0.85 + 0.4 * heat)
            alpha = int(255 * min(bright, 1.0))

            if e.trail:
                # 도는 방향으로 짧은 꼬리. 몇 개만 있어야 흩날리는 느낌이 산다.
                back = angle - 0.05 * (1 if e.speed > 0 else -1)
                p.setPen(QPen(theme.rgba(accent, int(alpha * 0.35)), size * 0.9))
                p.drawLine(QPointF(x, y),
                           QPointF(cx + math.cos(back) * r, cy + math.sin(back) * r))
                p.setPen(QPen(Qt.NoPen))

            px = _dot(accent, size, alpha)
            h = px.width() / 2
            p.drawPixmap(QPointF(x - h, y - h), px)
        p.setRenderHint(QPainter.Antialiasing, True)

    # 표식 획. **원본 그림에서 직접 뽑아 곧게 폈다.**
    #
    # 원본은 채워진 도형이 아니라 **선 그림**이다 — 아래 혀처럼 어디에도 안 닿고
    # 끝나는 획이 있어서, 안쪽을 채우는 방식으로는 통째로 무너진다. 그래서
    # ① 밝은 화소를 1픽셀로 깎아(Zhang-Suen 세선화) 선의 한가운데를 뽑고
    # ② 마디마다 직선을 맞춘 뒤 **각도를 통일**하고
    # ③ 꼭짓점을 두 직선의 교점으로 다시 잡았다.
    #
    # ②가 없으면 화소 격자의 흔들림이 그대로 남아 그림판으로 그린 선처럼 울퉁불퉁하다.
    # 각도를 재보니 **0도·60도·120도 셋뿐**이었다 — 가로와 좌우 대각선. 설계가 그렇게
    # 짜여 있어서 그 값으로 딱 맞췄다.
    #
    # ④ 다른 획에 얹혀 겹쳐 그려지던 토막 넷을 지웠다 — 눈에는 안 보이지만
    #    **토막의 끝 마감이 드러나** 선 한가운데에 혹처럼 튀어나왔다.
    #
    # 뽑는 스크립트: scratchpad/skel.py + straight.py + clean.py
    # 세로를 1로 놓은 값이고 가로는 1.371이다.
    _STROKES = (
        (
            (0.0, 0.0049), (0.1956, 0.0), (0.5678, 0.6449),
            (0.8406, 0.1726), (1.0788, 0.1726), (1.1635, 0.3193),
            (1.3659, 0.3193), (1.1832, 0.0028), (0.7244, 0.0028),
            (0.4723, 0.4394),
        ),
        (
            (0.5794, 0.981), (0.5869, 0.9939), (1.1833, 0.9939),
            (1.3674, 0.675), (1.1728, 0.675), (1.0854, 0.8266),
            (0.7905, 0.8266),
        ),
        (
            (0.0, 0.0049), (0.5681, 1.0), (1.0421, 0.179),
        ),
    )
    _RATIO = 1.3674

    def _mark_paths(self, cx, cy, r):
        """VC 획들. r은 표식의 **세로 절반**이다."""
        path = QPainterPath()
        half_w = r * self._RATIO
        for stroke in self._STROKES:
            for i, (u, v) in enumerate(stroke):
                x = cx - half_w + u * 2 * r
                y = cy - r + v * 2 * r
                path.moveTo(x, y) if i == 0 else path.lineTo(x, y)
        return (path,)

    def _draw_mark(self, p, cx, cy, r, heat, accent, solid: bool = False) -> None:
        """네온처럼 긋는다 — 진한 테두리 위에 밝은 마루.

        원본에서 색을 재보니 선 마루가 `#f58672`(밝은 살구빛)이고 그 바로 밖 1px이
        `#a6382b`(진한 붉은색)이었다. **한 가지 색으로 그으면 그냥 주황 선**이 되고
        네온으로 안 읽힌다 — 밝은 속과 진한 가장자리, 둘이 있어야 빛나 보인다.

        마루 색은 강조색에 흰색을 섞어 만든다. 테마를 바꿔도 같은 방식으로 빛난다.
        """
        (mark,) = self._mark_paths(cx, cy, r)
        # 원본 실측: 밝은 띠가 6~7px (세로 172 기준). 테두리까지 합친 값이라
        # 마루는 그보다 얇다.
        wide = max(1.0, r * 0.047)

        edge = QColor(accent)
        core = QColor(
            round(edge.red() + (255 - edge.red()) * 0.42),
            round(edge.green() + (255 - edge.green()) * 0.42),
            round(edge.blue() + (255 - edge.blue()) * 0.36),  # 파랑을 덜 섞어 따뜻하게
        )

        if solid:
            # 아주 작을 때. 마루와 테두리가 한 픽셀 안에서 뭉치면 얼룩이라 한 겹만
            # 굵게 긋는다. 채우기는 못 쓴다 — 닫힌 도형이 아니라 선 그림이라서.
            p.setBrush(QBrush(Qt.NoBrush))
            p.setPen(QPen(theme.rgba(core, int(210 + 45 * heat)), max(1.0, r * 0.14),
                          Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawPath(mark)
            return

        p.setBrush(QBrush(Qt.NoBrush))
        # 번짐. 달아오를수록 밖으로 샌다.
        # 원본에서 잰 번짐: 선 2px 밖이 (109,8,2), 10px 밖이 (62,14,14).
        for mult, alpha in ((4.6, int(6 + 14 * heat)), (2.3, int(12 + 30 * heat))):
            p.setPen(QPen(theme.rgba(edge, alpha), wide * mult,
                          Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawPath(mark)

        # 원본 실측: 밝은 마루 6.5px, 진한 테두리까지 합쳐 8.5px (세로 172 기준).
        # **끝은 둥글게, 이음매는 각지게.** 원본을 확대해 보니 자유로운 끝(혀의 왼쪽
        # 끝 같은 것)은 둥글고, 획이 꺾이는 자리는 뾰족하다. 둘 다 둥글게 하면 V의
        # 바닥 꼭짓점과 위 왼쪽 모서리가 뭉개진다.
        for color, width in ((edge, wide * 1.31), (core, wide)):
            pen = QPen(theme.rgba(color, int(200 + 55 * heat) if color is edge
                                  else int(190 + 65 * heat)), width,
                       Qt.SolidLine, Qt.RoundCap, Qt.MiterJoin)
            # 꺾이는 각이 60도라 뾰족한 끝이 획 두께의 2배까지 나간다. Qt 기본 한계가
            # 딱 2라 그대로 두면 모서리가 잘려 뭉툭해진다.
            pen.setMiterLimit(6)
            p.setPen(pen)
            p.drawPath(mark)


def _self_check() -> None:
    import os
    import sys

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt5.QtWidgets import QApplication

    # QApplication을 변수에 안 담으면 가비지 컬렉션돼 종료할 때 조용히 죽는다.
    app = QApplication.instance() or QApplication(sys.argv)

    mark = VulcanMark(200)
    assert len(mark.embers) == SPARKS
    assert mark.state == "idle" and mark.heat == 0.0

    # 상태가 바뀌면 열이 목표를 향해 **서서히** 오른다. 한 번에 켜지면 표시등처럼 보인다.
    mark.set_state("speaking")
    assert mark.target_heat == 1.0
    first = None
    for _ in range(40):
        mark._tick()
        first = first if first is not None else mark.heat
    assert 0.0 < first < 1.0, f"한 번에 튀었다: {first}"
    assert mark.heat > 0.9, mark.heat

    # 모르는 상태는 무시한다 — 오타 하나에 표식이 꺼지면 안 된다.
    mark.set_state("없는상태")
    assert mark.state == "speaking"

    mark.set_state("idle")
    for _ in range(80):
        mark._tick()
    assert mark.heat < 0.25, mark.heat

    # 마이크 크기는 0~1로 눌러 담는다. 큰 소리에 불티가 화면을 뒤덮으면 안 된다.
    mark.set_level(5.0)
    assert mark.level == 1.0
    mark.set_level(-1)
    assert mark.level == 0.0

    # 실제로 그려진다. 테마를 바꿔도 그려진다 — 색을 코드에 안 박았으니까.
    from PyQt5.QtGui import QImage

    for key in ("vulcan", "paper"):
        theme.use(key)
        img = QImage(200, 200, QImage.Format_ARGB32)
        img.fill(Qt.transparent)
        p = QPainter(img)
        mark.render(p)
        p.end()
        assert img.width() == 200
    theme.use("vulcan")

    print("logo self-check 통과")


if __name__ == "__main__":
    _self_check()
