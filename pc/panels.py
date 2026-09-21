"""옆칸에 들어가는 화면 부품들.

판·범례·기록·모델 고르기·원격 승인·제안 카드. 전부 **테마 색만 쓰고** 자기 색을
안 들고 있다 — 색은 theme.py 한 곳에 모여 있다.
"""

from __future__ import annotations

import paths
import json
import re
import time
from pathlib import Path
import urllib.error
import urllib.request

from typing import Callable

from PyQt5.QtCore import (QBuffer, QEvent, QIODevice, QPointF, QStringListModel, Qt, QThread, QTimer, QUrl,
                          pyqtSignal)
from PyQt5.QtGui import (QBrush, QFont, QImage, QPainter, QPalette, QPen,
                         QTextCharFormat, QTextCursor, QTextDocument)
from PyQt5.QtWidgets import (
    QComboBox,
    QCompleter,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QTextBrowser,
    QTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

import notes
import theme

# 제안 카드 한 장이 통째로 들어갈 높이. 반만 보이면 단추를 못 누른다.
PROPOSAL_AREA_MIN_H = 250

# 할 일 표기. 목록 기호 뒤의 `[ ]`/`[x]`만 잡는다 — 본문 중간의 대괄호는 건드리지
# 않는다(`[[링크]]`나 배열 `x[0]`이 망가지면 안 된다).
TASK_RE = re.compile(r"(?m)^(\s*[-*+] )\[([ xX])\]\s+")
TASK_MARKS = ("☐", "☑")   # ☐ 안 한 일 · ☑ 한 일


class HudPanel(QFrame):
    """모서리에 브래킷이 걸린 판. JARVIS 계열 화면의 뼈대다."""

    def __init__(self, parent=None, corner: int = 11) -> None:
        super().__init__(parent)
        # 모서리 길이는 정수여야 한다. 예전에 `HudPanel(left)`처럼 부모를 첫 자리에
        # 넘겨 여기에 위젯이 들어갔고, 그리는 중에 통째로 죽었다(0xC0000409).
        assert isinstance(corner, int), corner
        self.corner = corner
        self.setObjectName("hud")

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setPen(QPen(theme.rgba(theme.T.DIM, 100), 1.4))
        w, h, c = self.width(), self.height(), self.corner
        for x, y, dx, dy in ((1, 1, 1, 1), (w - 2, 1, -1, 1), (1, h - 2, 1, -1), (w - 2, h - 2, -1, -1)):
            painter.drawLine(x, y, x + dx * c, y)
            painter.drawLine(x, y, x, y + dy * c)


class Legend(QWidget):
    """종류별 색 범례. 색이 정보인데 해독표가 없으면 그냥 알록달록한 점일 뿐이다."""

    # **차례는 한 곳에서만 정한다.** 여기 따로 적어 두었더니 콤보와 순서가 어긋났다
    # (콤보는 …선호·장소·물건…, 표시줄은 …장소·물건·선호…). 사소하지만 같은 것을
    # 두 군데 적으면 언젠가 갈린다.
    ORDER = tuple(theme.KIND_LABEL)

    def __init__(self) -> None:
        super().__init__()
        self.setFixedHeight(14)
        # 기본 sizeHint는 0에 가까워 옆에 stretch를 두면 폭이 안 잡히고 아무것도 안 그려진다.
        self.setMinimumWidth(430)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        font = QFont()
        font.setPointSize(7)
        painter.setFont(font)

        x = 0.0
        for kind in self.ORDER:
            painter.setPen(QPen(Qt.NoPen))
            painter.setBrush(QBrush(theme.rgba(theme.kind_color(kind), 200)))
            painter.drawEllipse(QPointF(x + 3, self.height() / 2), 3.0, 3.0)
            painter.setPen(QPen(theme.rgba(theme.T.DIM, 110)))
            text = theme.KIND_LABEL[kind]
            painter.drawText(QPointF(x + 10, self.height() / 2 + 3), text)
            x += 14 + painter.fontMetrics().width(text) + 10


class ActivityFeed(QWidget):
    """VC가 무엇을 했는지 시간순으로. 계측 로그를 그대로 읽어 보여준다.

    학습이 근거 없이 굴러가는 것처럼 보이지 않으려면, 근거가 된 기록이 보여야 한다.
    """

    TIER_MARK = {"phone": "폰", "pc": "PC", "api": "API"}

    def __init__(self) -> None:
        super().__init__()
        self.rows: list = []
        self.setMinimumHeight(120)

    def show_rows(self, rows) -> None:
        self.rows = list(rows)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        font = QFont()
        font.setPointSize(7)
        painter.setFont(font)

        if not self.rows:
            painter.setPen(QPen(theme.rgba(theme.T.DIM, 70)))
            painter.drawText(4, 18, "아직 기록 없어. 시키면 여기 쌓인다.")
            return

        y = 12.0
        for row in self.rows:
            if y > self.height() - 2:
                break
            ok = row["outcome"] == "success"
            # 실패색은 테마가 정한다. 불칸처럼 강조색이 붉은 테마에서 실패를 빨강으로
            # 쓰면 성공과 구분이 안 된다 — theme.T.WARN이 테마마다 다른 이유다.
            color = theme.T.ACCENT if ok else theme.T.WARN

            painter.setPen(QPen(Qt.NoPen))
            painter.setBrush(QBrush(theme.rgba(color, 190)))
            painter.drawEllipse(QPointF(4, y - 3), 2.4, 2.4)

            painter.setPen(QPen(theme.rgba(theme.T.DIM, 90)))
            painter.drawText(QPointF(14, y), (row["ts"] or "")[11:19])

            painter.setPen(QPen(theme.rgba(theme.T.ACCENT, 130)))
            painter.drawText(QPointF(72, y), self.TIER_MARK.get(row["tier"], row["tier"]))

            painter.setPen(QPen(theme.rgba(theme.T.DIM, 150) if ok else theme.rgba(color, 200)))
            label = row["module"] or row["phase"]
            if not ok and row["failure_point"]:
                label += f" — {row['failure_point']}"
            painter.drawText(QPointF(104, y), label)
            y += 15


class NoteView(QTextBrowser):
    """읽는 모습. 마크다운을 입혀 보여주고 링크·태그는 눌린다.

    평소에는 이쪽을 보고, 고칠 때만 원문 칸으로 바꾼다. 치는 동안에도 서식을 입히는
    방식(실시간 미리보기)은 커서 자리·문단 선택·되돌리기가 얽혀서, 가끔 고치는
    용도에는 값이 안 맞는다.

    `[[링크]]`와 `#태그`는 마크다운이 아니라서 **미리 마크다운 링크로 바꿔** 넣는다.
    """

    link_clicked = pyqtSignal(str, str)
    tag_clicked = pyqtSignal(str)
    task_clicked = pyqtSignal(int)    # 몇 번째 할 일 표를 눌렀나 (0부터)

    def __init__(self, find_file=None, find_note=None) -> None:
        super().__init__()
        # 첨부 이름을 실제 파일 자리로 바꿔 주는 사람. 없으면 그림은 이름만 보인다.
        self.find_file = find_file
        # 끼워 넣은 글(`![[글#소제목]]`)의 **몸**을 찾는 길. 없으면 예전처럼 고리표만 보인다.
        self.find_note = find_note
        self.limit = self.RENDER_START
        self.setOpenLinks(False)          # 브라우저를 열면 안 된다. 우리끼리 쓰는 이름표다
        self.setOpenExternalLinks(False)
        self.anchorClicked.connect(self._went)
        self.setFrameShape(QFrame.NoFrame)

    @staticmethod
    def _주소(글: str) -> str:
        """마크다운 주소 자리에 넣을 꼴로 감싼다.

        ★ **빈칸이 든 주소는 Qt 가 링크로 안 만든다.** `[안 먹는 말투](note:안 먹는 말투)`
        가 화면에 **글자 그대로** 나왔다 — 괄호도 `note:` 도 다 보였다(시험 쪽 라-②).
        제목에 빈칸이 있는 것이 보통이라 **거의 모든 이음선이 날것으로 보이고 있었다.**
        링크가 핵심인 물건에서 링크가 안 눌린 것이다.

        마크다운은 주소를 `<...>` 로 감싸면 빈칸을 허락한다. 원문은 안 건드린다.
        """
        return "<" + 글.replace("<", "%3C").replace(">", "%3E") + ">"

    #: 바깥으로 여는 주소들. 우리끼리 쓰는 이름표(`note:`·`tag:`)와 갈라야 한다.
    바깥꼴 = ("http", "https", "mailto")

    @classmethod
    def 바깥주소인가(cls, raw: str) -> bool:
        """브라우저·메일 앱으로 열 주소인가. `note:`·`tag:` 는 우리 것이라 아니다."""
        return str(raw).split(":", 1)[0].lower() in cls.바깥꼴

    def 바깥열기(self, raw: str) -> None:
        """기본 브라우저로 연다. 시험에서는 이 함수를 갈아 끼운다."""
        from PyQt5.QtCore import QUrl
        from PyQt5.QtGui import QDesktopServices

        QDesktopServices.openUrl(QUrl(str(raw)))

    def 링크메뉴(self, 주소: str):
        """우클릭 메뉴에 얹을 것. 바깥 주소가 아니면 `None`.

        ★ 누르면 바로 열리지만 **우클릭 길도 둔다** — 새 창에 열거나 주소만 복사하고
          싶을 때가 있고, 잘못 눌러 브라우저가 뜨는 것이 싫은 사람도 있다(오너 2026-09-20).
        """
        if not self.바깥주소인가(주소):
            return None
        from PyQt5.QtWidgets import QMenu

        메뉴 = QMenu(self)
        메뉴.addAction("브라우저로 열기", lambda: self.바깥열기(주소))
        메뉴.addAction("주소 복사", lambda: self._주소복사(주소))
        return 메뉴

    @staticmethod
    def _주소복사(주소: str) -> None:
        from PyQt5.QtWidgets import QApplication

        QApplication.clipboard().setText(str(주소))

    def contextMenuEvent(self, event) -> None:
        """링크 위에서 우클릭하면 **열기·복사**를 맨 위에 붙인다."""
        주소 = self.anchorAt(event.pos())
        메뉴 = self.링크메뉴(주소) if 주소 else None
        if 메뉴 is None:
            return super().contextMenuEvent(event)
        기본 = self.createStandardContextMenu(event.pos())
        메뉴.addSeparator()
        for act in 기본.actions():
            메뉴.addAction(act)
        메뉴.exec_(event.globalPos())

    def _went(self, url) -> None:
        raw = url.toString()
        # ★★ **인터넷 주소는 브라우저로 연다**(오너 2026-09-20). 전에는 `setOpenLinks(False)` 로
        #   전부 막아 두고 우리 이름표(`note:`·`tag:`)만 다뤄서, 글에 남긴 주소를 눌러도
        #   **아무 일도 안 났다** — 링크를 남겨 두는 뜻이 없었다.
        if self.바깥주소인가(raw):
            return self.바깥열기(raw)
        kind, _, rest = raw.partition(":")
        if kind == "tag":
            self.tag_clicked.emit(rest)
        elif kind == "note":
            name, _, heading = rest.partition("#")
            self.link_clicked.emit(name, heading)
        elif kind == "file":
            # 📎 첨부 고리(영상·녹음·heic·pdf) — 컴퓨터의 기본 앱으로 연다.
            from PyQt5.QtGui import QDesktopServices
            QDesktopServices.openUrl(url)

    # `- 제품명 : vcis-689` 같은 항목 줄 — 목록 점 대신 **굵은 이름 · 값** 으로(2026-09-18 창 점검)
    _항목꼴 = re.compile(r"^[ \t]*[-*][ \t]+([^:：\n\[\]]{1,24}?)[ \t]*[:：][ \t]*(.*)$", re.M)

    def to_markdown(self, body: str) -> str:
        """우리 표기를 마크다운으로 바꾼다. 순서가 중요하다 — 끼움이 링크를 품는다.

        첨부는 **진짜 그림**으로 넣는다. 이름만 보여주면 사진을 붙인 의미가 없다.
        """
        body = re.sub(r"(?s)%%.*?%%", "", body)   # 옵시디언 주석(사진 글자)은 안 보인다
        body = self._항목꼴.sub(lambda m: f"**{m.group(1).strip()}** · {m.group(2).strip() or '—'}  ", body)
        def embed(m):
            name, head = m.group(1).strip(), (m.group(2) or "").strip()
            if notes.is_attachment(name):
                path = self.find_file(name) if self.find_file else None
                if path is None:
                    return f"⟨없는 첨부: {name}⟩"
                # ★ 그림만 그림으로 넣는다. 폰 사진(.heic)·영상·녹음·pdf 를 그림 칸에 넣으면 **깨진 그림**이 뜬다 —
                #   고리로 두고 누르면 컴퓨터의 기본 앱이 연다(4단계).
                if Path(name).suffix.lower() not in notes.IMAGE_EXT:
                    return f"[📎 {name}]({Path(path).as_uri()})"
                return f"![{name}]({Path(path).as_uri()})"
            label = f"{name}#{head}" if head else name
            고리 = f"[⟨{label}⟩]({self._주소('note:' + label)})"
            # ★★ **옵시디언은 끼워 넣은 글을 그 자리에 펼쳐 보인다.** 우리는 고리표만 보여서
            #   「이번 달: ![[보고서#8월 정산]]」이 읽기 화면에서 **내용 없는 이름표**였다.
            #   한 겹만 펼친다 — 펼친 속의 `![[…]]` 는 고리로 둔다(서로 끼우면 끝없이 돈다).
            몸 = self.find_note(name) if self.find_note else None
            if not 몸:
                return 고리
            토막 = notes.section(몸, head) if head else 몸
            토막 = notes.EMBED_RE.sub(lambda mm: f"⟨{mm.group(1)}⟩", 토막).strip()
            if not 토막:
                return 고리
            if len(토막) > 1500:
                토막 = 토막[:1500] + "…"
            인용 = chr(10).join("> " + 줄 for 줄 in 토막.splitlines())
            return chr(10) + chr(10) + 고리 + chr(10) + chr(10) + 인용 + chr(10) + chr(10)

        def link(m):
            name, head = m.group(1).strip(), (m.group(2) or "").strip()
            shown = (m.group(3) or "").strip() or (f"{name} › {head}" if head else name)
            겨냥 = "note:" + name + ("#" + head if head else "")
            return f"[{shown}]({self._주소(겨냥)})"

        # ★ 코드 울타리·홑따옴표 안은 **예시**다. 안 가리면 규칙 글의 `[[링크]]` 가
        #   화면에서 `[링크](<note:링크>)` 로 깨져 보인다(2026-09-21 재서 봤다).
        out = notes.코드밖만(notes.EMBED_RE, body, embed)
        out = notes.코드밖만(notes.LINK_RE, out, link)
        # 블록 이름(`^a1b2`)은 **가리키는 표지**지 읽을 글이 아니다. 옵시디언도 안 보여 준다.
        # 지우지 말고 화면에서만 감춘다 — 원본 파일에는 그대로 있어야 링크가 닿는다.
        out = chr(10).join(notes.BLOCK_RE.sub("", 줄) for 줄 in out.splitlines())
        # 칠하는 판단도 뽑는 판단과 **같은 자리**를 쓴다. 따로 두면 갈라진다 —
        # 목록엔 안 들어가는 색상 코드가 본문에서만 태그처럼 칠해지고 있었다.
        def 태그(m):
            이름 = notes.태그인가(m.group(1))
            if not 이름:
                return m.group(0)      # 태그가 아니면 원문 그대로 둔다
            return f"[#{m.group(1)}]({self._주소('tag:' + 이름)})"

        return notes.TAG_RE.sub(태그, out)

    # 한 번에 입혀 그릴 글자 수. 넘으면 앞부분만 그린다.
    #
    # 서식 입히기는 글 길이에 비례한다 — 18만 자짜리 기록 하나에 **1.49초**가 걸려
    # 창이 그대로 굳었다(실제 기록으로 재봄). 20년치면 이런 글이 계속 생긴다.
    # 고치기 칸은 원문 전체를 그대로 열고, 그쪽은 5ms다.
    RENDER_LIMIT = 20_000
    RENDER_FLOOR = 1_500     # 이보다 더는 안 줄인다. 너무 조금 보이면 쓸모가 없다
    # **적게 시작해서 빠르면 늘린다.** 크게 시작하면 처음 여는 한 번이 1.5초 굳는다 —
    # 켜고 처음 누른 항목에서 굳으면 그게 첫인상이 된다.
    RENDER_START = 4_000
    RENDER_BUDGET = 0.25     # 한 번 그리는 데 이 이상 걸리면 다음엔 덜 그린다

    def show_note(self, body: str) -> None:
        """마크다운을 입혀 보여준다.

        링크 색은 **만들어진 HTML을 고쳐** 넣는다. 팔레트로도 스타일시트로도 안 먹는데,
        Qt가 마크다운을 옮기면서 앵커 안쪽 span에 `color:#0000ff`를 직접 박기 때문이다.
        그 색을 갈아 끼우지 않으면 테마가 무슨 색이든 링크만 파랗게 따로 논다.
        """
        # 팔레트도 같이 준다. HTML에서 색을 빼면 Qt가 **팔레트의 기본 파랑**으로
        # 되돌려 칠한다 — 둘 중 하나만 고치면 계속 파랗다.
        pal = self.palette()
        pal.setColor(QPalette.Link, theme.T.ACCENT)
        pal.setColor(QPalette.LinkVisited, theme.T.ACCENT)
        self.setPalette(pal)

        # **길이를 스스로 줄인다.** 서식 입히기 값은 글자 수만으로 안 정해진다 —
        # 같은 2만 자라도 표 기호가 잔뜩인 기록은 1.33초가 걸렸다(실제 기록으로 재봄).
        # 그래서 길이로 못 박지 않고, 오래 걸리면 다음번에 덜 그린다.
        # Qt의 마크다운은 **할 일 목록을 모른다.** `- [ ]`와 `- [x]`가 둘 다 그냥
        # 점으로 바뀌어 한 일과 안 한 일이 똑같이 보였다(실제 기록에 29줄).
        # 표기를 미리 글자로 바꿔 넣는다.
        body = TASK_RE.sub(
            lambda m: f"{m.group(1)}{'☑' if m.group(2).lower() == 'x' else '☐'} ", body)
        limit = self.limit
        cut = body[:limit]
        if len(body) > limit:
            cut += (chr(10) * 2 + "---" + chr(10) * 2
                    + f"*너무 길어 앞 {limit:,}자만 입혀 보여준다. "
                      f"전체는 `고치기`에서 볼 수 있다 (총 {len(body):,}자).*")
        began = time.perf_counter()
        self.setMarkdown(self.to_markdown(cut))
        spent = time.perf_counter() - began
        if spent > self.RENDER_BUDGET and self.limit > self.RENDER_FLOOR:
            self.limit = max(self.RENDER_FLOOR, int(self.limit * self.RENDER_BUDGET / spent))
        elif spent < self.RENDER_BUDGET / 3 and self.limit < self.RENDER_LIMIT:
            self.limit = min(self.RENDER_LIMIT, self.limit * 3 + 500)
        self._dress()

    def mousePressEvent(self, event) -> None:
        """할 일 표를 누르면 켜고 끈다.

        **표 자리를 눌렀을 때만** 움직인다. 줄 아무 데나 눌러도 켜지면 글자를 고르려다
        할 일이 뒤집힌다. 몇 번째냐로 세어 원문을 찾는다 — 보이는 글은 서식이 벗겨져
        원문과 글자가 다르지만, 차례는 같다(뒤가 잘려도 앞은 그대로다).
        """
        cur = self.cursorForPosition(event.pos())
        block = cur.block()
        text = block.text()
        if text[:1] in TASK_MARKS and cur.positionInBlock() <= 1:
            nth = 0
            walk = self.document().begin()
            while walk.isValid() and walk.blockNumber() < block.blockNumber():
                if walk.text()[:1] in TASK_MARKS:
                    nth += 1
                walk = walk.next()
            self.task_clicked.emit(nth)
            return
        super().mousePressEvent(event)

    def go_to_heading(self, heading: str) -> None:
        """소제목이 있는 줄로 데려간다.

        입혀진 글에는 `#`이 없다 — 글자만 맞춰 찾는다. 없으면 맨 위에 둔다.
        """
        want = heading.strip()
        block = self.document().begin()
        while block.isValid():
            if block.text().strip() == want:
                cur = self.textCursor()
                cur.setPosition(block.position())
                self.setTextCursor(cur)
                # 찾은 줄을 화면 맨 위로. 가운데나 아래에 두면 어디를 보라는 건지 모른다.
                bar = self.verticalScrollBar()
                bar.setValue(bar.value() + self.cursorRect(cur).top())
                return
            block = block.next()
        # ★ 블록(`^이름`)은 입힌 글에 이름이 안 보인다 — 부르는 쪽이 그 덩이 첫 줄 글자를 넘긴다.
        #   목록 표지·꾸밈이 벗겨져 딱 맞지 않을 수 있어 **그 글자로 시작하는 줄**까지 본다.
        if len(want) >= 2:
            block = self.document().begin()
            while block.isValid():
                if block.text().strip().startswith(want):
                    cur = self.textCursor()
                    cur.setPosition(block.position())
                    self.setTextCursor(cur)
                    bar = self.verticalScrollBar()
                    bar.setValue(bar.value() + self.cursorRect(cur).top())
                    return
                block = block.next()
        self.verticalScrollBar().setValue(0)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit_images()          # 칸 폭이 바뀌면 사진도 따라 줄인다

    def _dress(self) -> None:
        self._recolor_links()
        self._fit_images()

    def _fit_images(self) -> None:
        """사진을 칸 폭에 맞춘다.

        원래 크기로 그리면 사진 한 장에 4000픽셀짜리도 있어서 칸을 뚫고 나간다 —
        가로 막대가 생기고 글이 안 읽힌다. 작은 사진은 키우지 않는다.
        """
        room = max(120, self.viewport().width() - 24)
        cur = QTextCursor(self.document())
        block = self.document().begin()
        while block.isValid():
            it = block.begin()
            while not it.atEnd():
                frag = it.fragment()
                fmt = frag.charFormat()
                if fmt.isImageFormat():
                    img = fmt.toImageFormat()
                    real = QImage(QUrl(img.name()).toLocalFile())
                    wide = real.width() or int(img.width()) or room
                    tall = real.height() or int(img.height()) or 0
                    if wide > room and tall:
                        img.setWidth(room)
                        img.setHeight(tall * room / wide)
                        cur.setPosition(frag.position())
                        cur.setPosition(frag.position() + frag.length(), QTextCursor.KeepAnchor)
                        cur.setCharFormat(img)
                it += 1
            block = block.next()

    def _recolor_links(self) -> None:
        """링크 글자의 서식을 직접 바꾼다.

        HTML 문자열을 치환하는 방식은 못 쓴다 — 어느 span이 링크인지 글자만 보고는
        가릴 수 없어서, 링크는 파란 채로 두고 **뒤따르는 글자만** 물들이는 일이 났다.
        문서를 훑으며 `isAnchor`인 조각만 고치면 그런 착각이 없다.
        """
        cur = QTextCursor(self.document())
        cur.movePosition(QTextCursor.Start)
        block = self.document().begin()
        while block.isValid():
            it = block.begin()
            while not it.atEnd():
                frag = it.fragment()
                fmt = frag.charFormat()
                if fmt.isAnchor():
                    fmt.setForeground(theme.T.ACCENT)
                    fmt.setUnderlineStyle(QTextCharFormat.NoUnderline)
                    cur.setPosition(frag.position())
                    cur.setPosition(frag.position() + frag.length(), QTextCursor.KeepAnchor)
                    cur.setCharFormat(fmt)
                it += 1
            block = block.next()


class NoteBody(QTextEdit):
    """고칠 수 있으면서 링크도 눌리는 본문 칸.

    **Ctrl을 누른 채 눌러야** 이동한다. 그냥 누르면 글자 자리를 잡아야 하기 때문이다 —
    고치는 칸에서 클릭이 이동이 되면 커서를 옮길 수가 없다.
    """

    link_clicked = pyqtSignal(str, str)   # 대상, 소제목("" 이면 맨 위)
    tag_clicked = pyqtSignal(str)

    image_pasted = pyqtSignal(bytes, str)   # 원본 바이트, 확장자

    # `[[`를 치면 제목을 물어볼 곳. 붙기 전에는 아무것도 안 뜬다.
    title_source: Callable[[str], list[str]] | None = None

    def __init__(self, *a, **kw) -> None:
        super().__init__(*a, **kw)
        # 모델을 **직접 들고 있는다.** QCompleter가 알아서 만든 모델은 파이썬 쪽에
        # 붙드는 것이 없어 치우다가 통째로 죽는다(0xC0000409).
        self._pop_model = QStringListModel([], self)
        self._pop = QCompleter(self._pop_model, self)
        self._pop.setWidget(self)
        # 거르는 일은 SQL이 한다 — 2만 개를 파이썬으로 들고 거를 이유가 없다.
        self._pop.setCompletionMode(QCompleter.UnfilteredPopupCompletion)
        # 기본 7줄이라 방금 만든 글이 안 보여 "없어진 줄 알았다"는 말이 나왔다.
        # 목록은 12개까지 주므로 그만큼은 한눈에 보여야 스크롤할 일이 없다.
        self._pop.setMaxVisibleItems(12)
        self._pop.activated[str].connect(self._put_link)
        # **Esc 는 목록이 직접 받는다.** 목록이 뜨면 글상자로 키가 안 온다 —
        # `keyPressEvent` 에서 막아 봤자 그 자리를 안 지난다(낯선 PC 에서 두 번
        # 눌러도 안 닫혔다). 우리 거름망을 나중에 달아 Qt 것보다 먼저 보게 한다.
        # **옷은 목록에 직접 입힌다.** 이 목록은 주 창의 자식이 아니라 **별개
        # 최상위 창**(`Qt5152QWindowPopupDropShadowSaveBits`)이라, 주 창에 건
        # 스타일시트가 안 내려간다 — 검은 화면 위에 흰 바탕·파란 막대로 이것만
        # 튀었다. 콤보 펼침 목록은 주 창 트리 안이라 이미 입혀져 있었다.
        self._pop.popup().setStyleSheet(theme.pop_css())
        self._pop.popup().installEventFilter(self)

    def pop_open(self) -> bool:
        """`[[` 목록이 떠 있나. 창 단축키가 Esc 를 가로채기 전에 물어본다."""
        return self._pop.popup().isVisible()

    def close_pop(self) -> None:
        self._pop.popup().hide()

    def eventFilter(self, obj, event) -> bool:
        if (obj is self._pop.popup() and event.type() == QEvent.KeyPress
                and event.key() == Qt.Key_Escape):
            self._pop.popup().hide()
            return True      # 여기서 끝낸다 — 고치기 밖으로 나가면 안 된다
        return super().eventFilter(obj, event)

    # --- [[ 자동완성 ---------------------------------------------------

    def _typing_link(self) -> str | None:
        """커서 바로 앞이 아직 안 닫힌 `[[`이면 지금까지 친 글자, 아니면 None."""
        before = self.toPlainText()[: self.textCursor().position()]
        at = before.rfind("[[")
        if at < 0:
            return None
        part = before[at + 2:]
        # 이미 닫았거나 줄이 바뀌었으면 링크를 치는 중이 아니다.
        if "]]" in part or chr(10) in part or len(part) > 60:
            return None
        return part

    def _put_link(self, title: str) -> None:
        """고른 제목으로 갈아 끼우고 `]]`까지 닫는다. 닫는 것까지 해야 손이 안 간다."""
        part = self._typing_link()
        if part is None:
            return
        cur = self.textCursor()
        for _ in range(len(part)):
            cur.deletePreviousChar()
        # 사용자가 `]]`를 미리 쳐 뒀으면 또 붙이지 않는다.
        tail = self.toPlainText()[cur.position():]
        cur.insertText(title + ("" if tail.startswith("]]") else "]]"))
        self.setTextCursor(cur)

    def keyPressEvent(self, event) -> None:
        # 목록이 떠 있는 동안 위/아래·엔터·탭은 목록 몫이다. 여기서 먹으면
        # 엔터가 줄바꿈이 되어 **고르는 길이 없어진다.**
        if self._pop.popup().isVisible():
            if event.key() == Qt.Key_Escape:
                self._pop.popup().hide()      # 여기까지 오는 경우도 막아 둔다
                return
            if event.key() in (Qt.Key_Enter, Qt.Key_Return, Qt.Key_Tab,
                               Qt.Key_Up, Qt.Key_Down):
                event.ignore()
                return
        super().keyPressEvent(event)
        self._offer_links()

    def _offer_links(self) -> None:
        part = self._typing_link()
        if part is None or self.title_source is None:
            self._pop.popup().hide()
            return
        names = self.title_source(part)
        if not names:
            self._pop.popup().hide()
            return
        self._pop_model.setStringList(names)
        self._pop.popup().setCurrentIndex(self._pop_model.index(0, 0))
        rect = self.cursorRect()
        rect.setWidth(self._pop.popup().sizeHintForColumn(0)
                      + self._pop.popup().verticalScrollBar().sizeHint().width() + 12)
        self._pop.complete(rect)

    def insertFromMimeData(self, source) -> None:
        """붙여넣기. **그림이면 파일로 저장하고 표기를 끼운다.**

        서식 있는 글은 평문으로만 받는다 — 마크다운이 원본인데 서식이 딸려 들어오면
        파일에 쓰레기가 쌓인다.
        """
        if source.hasImage():
            img = source.imageData()
            buf = QBuffer()
            buf.open(QIODevice.WriteOnly)
            QImage(img).save(buf, "PNG")
            self.image_pasted.emit(bytes(buf.data()), ".png")
            return
        self.insertPlainText(source.text())

    def mousePressEvent(self, event) -> None:
        if event.modifiers() & Qt.ControlModifier:
            at = self.cursorForPosition(event.pos()).position()
            hit = self._token_at(self.toPlainText(), at)
            if hit is not None:
                kind, name, extra = hit
                if kind == "link":
                    self.link_clicked.emit(name, extra)
                else:
                    self.tag_clicked.emit(name)
                return
        super().mousePressEvent(event)

    @staticmethod
    def _token_at(text: str, at: int):
        """글자 자리 위에 있는 [[링크]] 또는 #태그. 없으면 None."""
        for m in notes.LINK_RE.finditer(text):
            if m.start() <= at <= m.end():
                return "link", m.group(1).strip(), (m.group(2) or "").strip()
        for m in notes.TAG_RE.finditer(text):
            if m.start() <= at <= m.end() and notes.태그인가(m.group(1)):
                return "tag", notes.태그인가(m.group(1)), ""
        return None

    def go_to_heading(self, heading: str) -> None:
        """소제목이 있는 줄로 데려간다.

        `[[노트#소제목]]`으로 불렀는데 맨 위만 보여주면, 긴 문서에서 어디를 보라는
        건지 알 수 없다. 없는 소제목이면 맨 위에 둔다 — 못 찾았다고 아무 데나
        떨어뜨리면 더 헷갈린다.
        """
        cur = self.textCursor()
        cur.movePosition(QTextCursor.Start)
        self.setTextCursor(cur)
        if not heading:
            return
        want = heading.strip().lower()
        at = 0
        # ★ `[[글#^이름]]` 은 소제목이 아니라 **줄 끝 블록 이름**이다. `#` 줄만 찾으면 맨 위에 떨어졌다.
        블록 = want[1:] if want.startswith("^") else ""
        for line in self.toPlainText().splitlines():
            if 블록:
                m = notes.BLOCK_RE.search(line)
                if m and m.group(1).lower() == 블록:
                    cur.setPosition(at)
                    self.setTextCursor(cur)
                    self.ensureCursorVisible()
                    return
                at += len(line) + 1
                continue
            bare = line.lstrip("#").strip().lower()
            if bare == want and line.lstrip().startswith("#"):
                cur.setPosition(at)
                self.setTextCursor(cur)
                self.ensureCursorVisible()
                return
            at += len(line) + 1


class Folded(QWidget):
    """접었다 펴는 칸.

    제안·활동·모델은 **평소에 비어 있거나 안 쓴다.** 그런데도 늘 펼쳐 두면 세 칸이
    600px을 먹고, 정작 매일 보는 것이 아래로 밀린다. 눌러야 펴지게 한다.
    """

    def __init__(self, title: str, hint: str, body: QWidget, open_: bool = False) -> None:
        super().__init__()
        self.body = body
        self.head = QPushButton()
        self.head.setObjectName("quiet")
        self.head.setCursor(Qt.PointingHandCursor)
        self.head.setToolTip(hint)
        self.head.setStyleSheet(
            f"QPushButton{{color:{theme.css(theme.T.ACCENT, 0.55)}; font-family:{theme.MONO};"
            f"font-size:{theme.글자(10)}; letter-spacing:2px; text-align:left; border:none; padding:3px 0;}}"
            f"QPushButton:hover{{color:{theme.T.ACCENT.name()};}}")
        self._title = title
        self.head.clicked.connect(lambda: self.set_open(not self.body.isVisible()))
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(4)
        box.addWidget(self.head)
        box.addWidget(body)
        self.set_open(open_)

    def set_open(self, on: bool) -> None:
        self.body.setVisible(on)
        self.head.setText(f"// {self._title}  {'−' if on else '+'}")


class SideReader(HudPanel):
    """옆에 띄우는 **읽기 전용** 판.

    고치는 판은 하나뿐이다. 두 곳에서 같은 글을 고치면 어느 쪽이 이기는지 알 수 없고,
    그걸 제대로 하려면 판마다 저장 상태를 따로 들고 있어야 한다. 여기서 필요한 건
    **딴 글을 곁에 두고 보면서 쓰는 것**이라 읽기만 되면 된다.
    """

    link_clicked = pyqtSignal(str, str)
    closed = pyqtSignal()

    def __init__(self, parent=None, find_file=None, find_note=None) -> None:
        super().__init__(parent)
        self.setObjectName("reader")
        self.title = QLabel()
        self.title.setObjectName("title")
        self.view = NoteView(find_file=find_file, find_note=find_note)
        self.view.link_clicked.connect(self.link_clicked)
        shut = QPushButton("닫기")
        shut.setObjectName("quiet")
        shut.setCursor(Qt.PointingHandCursor)
        shut.clicked.connect(self.closed)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.addWidget(self.title, 1)
        head.addWidget(shut)
        box = QVBoxLayout(self)
        box.setContentsMargins(20, 16, 20, 16)
        box.setSpacing(8)
        box.addLayout(head)
        box.addWidget(self.view, 1)
        self.hide()

    def show_note(self, title: str, body: str) -> None:
        self.title.setText(title)
        self.view.show_note(body)
        self.show()
        self.raise_()


_꾸밈글자 = re.compile(r"(\*\*|__|~~|`)")
# 줄머리 우물 정. `## 첫째` 가 미리보기에 `## 첫째` 로 그대로 나왔다.
_소제목 = re.compile(r"(?m)^#{1,6}\s*")


def _꾸밈벗기기(글: str) -> str:
    """사람에게 보일 때만 표시 글자를 뗀다. **원문은 파일에 그대로 있다.**

    ★ 처음엔 `**굵게**` 만 뗐는데, **미리보기에서 `[[링크]]` 와 `##` 는 그대로
    나왔다**(시험 쪽). 카드 읽기 모드는 링크로 잘 그리는데 미리보기만 원문이라,
    **링크를 고친 값이 절반만 왔다** — 미리보기는 **찾을 때마다 보는 자리**다.

    ★★ 또 **같은 일이 두 군데**였다. 카드 쪽(`NoteView.to_markdown`)과 여기가
    따로 논다. 지난 판 태그(뽑기/색칠), 그 전 따옴표 감싸기(네 군데)와 같은 결이다.
    여기는 「글자로 펴기」, 저기는 「누를 수 있게 그리기」라 하는 일이 정말 달라
    합치지 않았다 — 대신 **무엇을 떼는지**를 이 한 자리에 모아 둔다.
    """
    글 = _꾸밈글자.sub("", 글)
    글 = _소제목.sub("", 글)
    # `[[제목|보임]]` 은 보이는 쪽을, `[[제목#소제목]]` 은 「제목 › 소제목」으로.
    글 = notes.LINK_RE.sub(
        lambda m: (m.group(3) or "").strip()
        or (f"{m.group(1).strip()} › {m.group(2).strip()}" if m.group(2)
            else m.group(1).strip()),
        글)
    return 글


def 줄제목(단추) -> str:
    """결과 줄 단추가 **진짜로 가리키는 제목.**

    ★ 보이는 글자만 보면 안 된다 — 긴 제목은 칸에 맞춰 `…` 로 줄여 그리므로
      `text()` 는 제목의 앞부분일 뿐이다. 누르면 열리는 것은 여기 적힌 제목이다.
    """
    있는것 = 단추.property("vc_title")
    return str(있는것) if 있는것 else 번호뗀말(단추.text())


def 번호뗀말(말: str) -> str:
    """줄 앞에 붙인 번호(`3. `)를 뗀 **제목 그대로**. 번호는 보여 주려고만 붙인다."""
    앞, 점, 뒤 = 말.partition(". ")
    return 뒤 if 앞.isdigit() and 뒤 else 말


class Results(QWidget):
    """찾은 것 목록. 제목과 **걸린 자리 한 줄**을 같이 보여준다.

    제목만 늘어놓으면 어느 게 내가 찾던 것인지 눌러 봐야 안다. 20년치가 쌓이면
    같은 이름이 여럿이라 더 그렇다 — 걸린 문장을 보여줘야 고르는 값이 싸진다.
    """

    picked = pyqtSignal(str)
    picked_at = pyqtSignal(str)   # 그 파일을 콕 집어 열 때(제목이 겹칠 수 있다)

    def __init__(self, limit: int = 8, 번호매김: bool = False) -> None:
        super().__init__()
        self.limit = limit
        # ★ 찾은 것 목록만 줄 앞에 번호를 적는다(오너 2026-09-20 · 마우스 없이 쓰기).
        #   `Ctrl+1`~`9` 로 바로 여는데 **번호가 안 보이면 줄을 세어야 한다** — 그럼 안 쓴다.
        #   최근 목록에는 안 적는다: 거기 숫자키는 아무 데도 안 걸려서 거짓말이 된다.
        self.번호매김 = 번호매김
        self.rows = QVBoxLayout(self)
        self.rows.setContentsMargins(2, 0, 2, 0)
        self.rows.setSpacing(1)
        self.items: list[QWidget] = []

    @staticmethod
    def snippet(body: str, query: str, width: int = 46, title: str = "") -> str:
        """걸린 낱말 둘레만 잘라 온다. 없으면 앞머리를 준다.

        **먼저 자르고 그 다음에 다듬는다.** 통째로 다듬으면(공백 정리) 18만 자짜리
        기록에서 검색 한 번이 0.8초가 된다 — 실제 기록으로 재보고 알았다.

        본문 첫머리가 제목을 그대로 되풀이하면 그만큼 건너뛴다. 그 줄이 보여 주는 것이
        **제목을 두 번 읽는 것뿐**이라 한 줄이 통째로 헛돈다 — 낯선 PC 에서 여덟 줄 중
        여섯이 그 꼴이었다. 사람도 「회의록 2026-09-01」 아래 첫 줄에 날짜를 또 적는다.
        """
        # ★ **꾸미는 글자는 벗기고 보여 준다.** 제목에서는 벗겼는데 미리보기에서는
        # 안 벗겨서 「…정답 **4등** 시켜도 안 되던 **안 먹는 말투**…」처럼 별표가
        # 그대로 나왔다(시험 쪽 새-②). 사람이 읽을 자리라 원문 그대로일 이유가 없다 —
        # 원문은 파일에 그대로 있고, **사람에게 보일 때만 접는다.**
        body = _꾸밈벗기기(body)
        if title:
            벗김 = body.lstrip()
            if 벗김.startswith(title):
                남은 = 벗김[len(title):].lstrip(" 	:·-—") 
                if 남은.strip():          # 제목뿐인 글은 그대로 둔다. 지우면 빈 줄만 남는다
                    body = 남은
        # ★★ **물음을 통째로 찾으면 긴 물음은 절대 안 맞는다.** 사람이 문장으로 물으면
        #   그 글자열이 본문에 그대로 있을 리 없어, 늘 앞머리만 보여 주고 있었다 —
        #   「걸린 낱말 둘레만 잘라 온다」는 이 함수의 뜻이 긴 물음에서는 죽어 있었다.
        #   통째로 먼저 보고, 없으면 **긴 낱말부터** 찾는다(긴 것이 더 또렷하다).
        at = body.lower().find(query.lower()) if query else -1
        if at < 0 and query:
            낮 = body.lower()
            from notes import 물음낱말

            for 말 in 물음낱말(query):
                at = 낮.find(말.lower())
                if at >= 0:
                    query = 말       # 아래에서 이 낱말 둘레로 자른다
                    break
        if at < 0:
            return " ".join(body[:width * 4].split())[:width] + ("…" if len(body) > width else "")
        # 걸린 낱말이 발췌 앞쪽에 오게 잡는다. 가운데에 두면 잘라낼 때 밀려 나간다.
        start = max(0, at - width // 3)
        cut = " ".join(body[start:at + width * 2].split())
        head = "…" if start else ""
        return head + cut[:width] + ("…" if len(cut) > width else "")

    def show_hits(self, hits: list[tuple[str, str]], query: str = "",
                  width: int = 46) -> None:
        for w in self.items:
            self.rows.removeWidget(w)
            w.setParent(None)
            w.deleteLater()
        self.items = []
        for 몇, hit in enumerate(hits[:self.limit]):
            # 파일 자리까지 온 것은 **그 파일**을 연다. 제목만 보고 다시 찾으면
            # 같은 이름이 둘일 때 엉뚱한 쪽이 열린다.
            title, body, where = (tuple(hit) + ("", ""))[:3]
            갈래 = (tuple(hit) + ("", "", "", ""))[3]
            # 번호는 아홉까지만 — 열째부터는 누를 키가 없으니 적지 않는다(없는 길을 알리지 않는다)
            보일말 = f"{몇 + 1}. {title}" if self.번호매김 and 몇 < 9 else title
            b = QPushButton(보일말)
            b.setObjectName("quiet")
            # ★★ **긴 제목이 칸을 밀어내지 않게 한다.** 단추는 줄바꿈을 못 해서
            #   `minimumSizeHint` 로 **제목 전체 폭**을 요구한다. 옵시디언 볼트를 들이고
            #   나서야 드러났다 — 제목이 길어지자 속 최소폭이 144 → 455 로 뛰어
            #   칸(348)을 넘겼고, 오른쪽 칸 글자가 **112px 씩 창 밖으로 잘려 나갔다.**
            #   최소폭을 풀고, 보이는 글자는 칸에 맞춰 `…` 로 줄인다(아래 `줄임다시`).
            #   ※ 크기 정책을 `Ignored` 로도 바꿔 봤는데 **재 보니 아무 차이가 없었다**(275 그대로).
            #     줄인 글자는 `sizeHint` 자체가 작아지므로 최소폭을 따로 풀 것이 없다. 뺐다.
            b.setMinimumWidth(1)
            b.설명 = 보일말                # 줄이기 전 온전한 글자
            b.setProperty("vc_title", title)   # 누르면 열리는 진짜 제목
            b.setToolTip(title)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet("text-align:left; padding:2px 6px;")
            if where:
                b.setToolTip(str(where))
                b.clicked.connect(lambda _, w=where: self.picked_at.emit(str(w)))
            else:
                b.clicked.connect(lambda _, t=title: self.picked.emit(t))
            # ★★ **갈래를 보여 준다.** 찾기가 갈래를 돌아가며 뽑으므로(한 갈래가 목록을
            #   다 차지하던 것을 고쳤다) 결과에 결정·규칙·잡담이 섞여 온다. 그런데 사람은
            #   어느 것이 어느 갈래인지 **볼 길이 없었다** — AI 는 1단에서 `kind` 를 받는데.
            #   고를 때 제일 필요한 것이 이것이다. 기본값(`note`)은 안 적는다 — 다 그러면
            #   줄만 길어진다.
            앞 = f"{갈래} · " if 갈래 and 갈래 != "note" else ""
            line = QLabel(앞 + self.snippet(body, query, width, title))
            line.setWordWrap(True)
            line.setStyleSheet(
                f"color:{theme.css(theme.T.DIM, 0.4)}; font-size:{theme.글자(10)}; padding:0 8px 3px 8px;")
            for w in (b, line):
                self.rows.addWidget(w)
                self.items.append(w)
        self.줄임다시()

    def 줄임다시(self) -> None:
        """줄 글자를 칸 폭에 맞춰 `…` 로 줄인다. **뚝 끊기면 무슨 글인지 모른다.**

        Qt 는 단추 글자를 저절로 줄여 주지 않는다 — 폭이 모자라면 그냥 잘라서
        「신규 대형 프로젝트 착수 — AR-AI 에이전트 (그릴」 처럼 말끝이 사라진다.
        """
        # ★ 줄 자신의 폭이 아니라 **칸 폭**으로 잰다. 줄은 칸에 맞춰 늘어나므로 갓 만든
        #   줄은 아직 옛 폭을 들고 있다 — 그걸 믿으면 칸이 좁아져도 안 줄어든다.
        쓸폭 = max(40, self.width() - 16)
        for w in self.items:
            온말 = getattr(w, "설명", None)
            if 온말 is None:
                continue
            w.setText(w.fontMetrics().elidedText(온말, Qt.ElideRight, 쓸폭))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.줄임다시()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.줄임다시()      # 처음 보일 때 칸 폭이 정해진다


class Indexer(QThread):
    """파일 훑기를 딴 실에서 돈다.

    `reindex`는 폴더를 통째로 훑어 바뀐 파일을 찾는다. **항목 10만 개면 4초**가 걸린다
    (실측). 그걸 화면 실에서 하면 켤 때마다 4초 동안 창이 굳는다 — 20년 쓸 물건에서
    매번 4초는 그냥 안 쓰게 되는 이유가 된다.

    색인은 WAL이라 딴 실에서 써도 읽는 쪽이 안 막힌다.
    """

    done = pyqtSignal(int)      # 바뀐 파일 수
    meaning = pyqtSignal(int)      # 뜻 벡터를 아직 못 만든 항목 수
    # 올린 임베더를 화면 쪽에도 넘긴다. **두 번 올리지 않는다** — 같은 모델을 두 벌
    # 올리면 메모리도 두 배고 켜는 데도 두 번 걸린다. 추론은 실 사이에 안전하다.
    embedder = pyqtSignal(object)

    def __init__(self, notes, model_dir: str = "") -> None:
        super().__init__()
        # 뜻 검색은 **받은 큰 모델이 있으면 그걸** 쓴다.
        self.model_dir = model_dir or str(paths.meaning_dir())
        self._embed_tried = False
        # **제 연결을 연다.** 화면 실과 sqlite 연결 하나를 같이 쓰면, 주 실이 그 연결을
        # 건드릴 때만 이쪽이 제대로 도는 얽힘이 생긴다 — 2만 개 첫 색인이 6초와 30초+를
        # 오갔다. sqlite 연결은 실마다 하나가 원칙이다.
        self.notes = notes.__class__(notes.root, notes.index_path, index_now=False)
        self.again = False   # 도는 중에 또 부탁받았다

    def 뜻모델바꿈(self, 새자리: str) -> None:
        """뜻 모델이 바뀌었다. **다음 훑기에 새 모델로 다시 만든다.**

        ★★ 예전에는 `model_dir` 을 **만들 때 한 번** 정하고 `_embed_tried` 로 잠갔다 —
        화면에서 뜻 모델을 바꿔도, **다시 켜도** 옛 모델을 계속 썼다(고르는 칸을 낸
        그날 바로 드러났다). 크기가 다르면 `use_embedder` 가 옛 벡터를 버리므로
        **처음부터 다시 만든다** — 2794장에 3분쯤이다. 그 말은 부르는 쪽이 한다.
        """
        if 새자리 and 새자리 != self.model_dir:
            self.model_dir = 새자리
            self._embed_tried = False
            self.notes.use_embedder(None)      # 옛 임베더를 놓는다
            self.ask()

    def run(self) -> None:
        while True:
            self.again = False
            try:
                changed = self.notes.reindex()
            except Exception as e:
                changed = 0   # 훑다 실패해도 창이 죽으면 안 된다
                # ★ 말없이 0 으로 넘기면 구운 판(콘솔 없음)에서는 **아무도 모른다** — 기록에 남긴다.
                notes._알림(f"[색인 실 실패] 훑기 — {type(e).__name__}: {e}")
            self.done.emit(changed)
            self._build_meaning()
            if not self.again:
                return

    def _build_meaning(self) -> None:
        """뜻 벡터를 **조금씩** 만든다.

        2만 개면 50분이 걸리는 일이라 한 번에 하면 안 된다. 몇 개씩 만들고 중간에
        빠져나갈 길을 둔다 — 훑어 달라는 부탁이 오면 그쪽이 먼저다.

        모델이 없으면 아무 일도 안 한다. **뜻 검색이 없다고 프로그램이 못 쓰게 되면
        안 된다** — 낱말 검색은 그대로 돈다.
        """
        if not self._embed_tried:
            self._embed_tried = True
            try:
                from brain import onnx_embedder, pin_runtime

                from notes import EMBED_TOKENS

                # **못 쓸 상황이면 아예 안 올린다.** Qt 가 딸고 온 2019년 런타임이
                # 먼저 올라온 뒤에 onnxruntime 을 불러오면 프로세스가 통째로 죽는다.
                # 뜻 검색이 꺼지는 것이 프로그램이 죽는 것보다 낫다.
                if not pin_runtime():
                    return
                got = onnx_embedder(self.model_dir, max_tokens=EMBED_TOKENS)
            except Exception as e:
                got = None
                notes._알림(f"[색인 실 실패] 뜻 모델 올리기 — {type(e).__name__}: {e}")
            if got is None:
                return
            self.notes.use_embedder(got)
            # 모델을 바꿨으면 옛 벡터를 버린다. 차원이 달라 섞이면 안 된다.
            try:
                width = len(got(["크기 재기"], "query: ")[0])
                if self.notes.drop_vectors_if_changed(width):
                    self.meaning.emit(self.notes.vec_left())
            except Exception as e:
                notes._알림(f"[색인 실 실패] 뜻 모델 폭 재기 — {type(e).__name__}: {e}")
                return
            self.embedder.emit(got)
        if getattr(self.notes, "_embed", None) is None:
            return
        while not self.again:
            try:
                got = self.notes.embed_some(8)
            except Exception as e:
                notes._알림(f"[색인 실 실패] 뜻 벡터 만들기 — {type(e).__name__}: {e}")
                return   # 벡터를 못 만들어도 검색은 낱말로 돈다
            if not got:
                break
            self.meaning.emit(self.notes.vec_left())
        self.meaning.emit(self.notes.vec_left())

    def ask(self) -> None:
        """훑어 달라고 부탁한다. 이미 돌고 있으면 끝난 뒤 한 번 더 돈다."""
        if self.isRunning():
            self.again = True
            return
        self.start()


class Years(QWidget):
    """해마다 몇 개인지. 눌러서 그 해를 훑는다.

    20년치가 쌓이면 글자 검색만으로는 "작년 그 프로젝트"를 못 찾는다 — 그때 자기가
    쓴 표현을 기억해야 하기 때문이다. **시간은 사람이 확실히 기억하는 축**이다.
    """

    picked = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__()
        self.grid = QHBoxLayout(self)
        self.grid.setContentsMargins(2, 0, 2, 0)
        self.grid.setSpacing(3)
        # 빈칸은 **한 번만** 넣는다. 그릴 때마다 넣으면 빈칸이 쌓여 단추가 가운데로 밀린다.
        self.grid.addStretch(1)
        self.buttons: list[QPushButton] = []

    def show_years(self, years: list[tuple[str, int]], limit: int = 8) -> None:
        for b in self.buttons:
            self.grid.removeWidget(b)
            b.setParent(None)
            b.deleteLater()
        self.buttons = []
        for year, count in years[:limit]:
            b = QPushButton(year[2:])            # 25, 24 … 좁은 칸이라 뒤 두 자리만
            b.setObjectName("quiet")
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip(f"{year}년에 적은 것 {count}개")
            b.setStyleSheet("padding:2px 5px;")
            b.clicked.connect(lambda _, y=year: self.picked.emit(y))
            self.grid.insertWidget(len(self.buttons), b)   # 빈칸 앞에 넣는다
            self.buttons.append(b)


class Gaps(QWidget):
    """아직 없는 것 — 가리키는 링크는 있는데 항목이 없는 이름들.

    AI가 기록을 쌓다 보면 `[[납품 일정]]`처럼 아직 안 만든 것을 가리키게 된다.
    그 목록이 곧 **사람이 채울 자리**다. 여러 곳에서 가리킬수록 위로 올라온다 —
    많이 불린 이름이 먼저 필요한 것이다.
    """

    picked = pyqtSignal(str)

    def __init__(self, limit: int = 5) -> None:
        super().__init__()
        self.limit = limit
        self.rows = QVBoxLayout(self)
        self.rows.setContentsMargins(2, 0, 2, 0)
        self.rows.setSpacing(2)
        self.empty = QLabel("빈 데 없어. 가리키는 것마다 다 있어.")
        self.empty.setStyleSheet(f"color:{theme.css(theme.T.DIM, 0.35)}; font-size:{theme.글자(11)};")
        self.rows.addWidget(self.empty)
        self.buttons: list[QPushButton] = []

    def show_gaps(self, gaps: list[tuple[str, int]]) -> None:
        for b in self.buttons:
            # deleteLater만 부르면 지우는 게 미뤄져서 **옛 단추가 자리에 남는다** —
            # 다시 그릴 때마다 목록이 두 배로 늘어난다. 자리에서 먼저 뺀다.
            self.rows.removeWidget(b)
            b.setParent(None)
            b.deleteLater()
        self.buttons = []
        self.empty.setVisible(not gaps)
        for name, count in gaps[:self.limit]:
            b = QPushButton(f"{name}   ×{count}" if count > 1 else name)
            b.setObjectName("quiet")
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip(f"'{name}'을 가리키는 곳이 {count}군데. 눌러서 만든다")
            b.setStyleSheet("text-align:left; padding:3px 6px;")
            b.clicked.connect(lambda _, t=name: self.picked.emit(t))
            self.rows.addWidget(b)
            self.buttons.append(b)


class ModelPicker(HudPanel):
    """쓸 모델을 고르는 칸 (결정 42).

    **개발용 PC 사양으로 굳으면 안 된다.** 사양을 재서 자동으로 고르되, 사용자가 고른 게
    있으면 그게 이긴다. 새 모델을 `models/`에 넣으면 목록에 뜬다 — 코드는 안 바뀐다.
    """

    ROLE_LABEL = {"chat": "글자", "vision": "사진", "stt": "받아쓰기", "voice": "목소리",
                  "meaning": "뜻 검색"}
    meaning_changed = pyqtSignal(str)      # 뜻 모델을 바꿨다 — 새 모델 자리

    def __init__(self, link: "ServerLink", say: Callable[[str], None]) -> None:
        super().__init__(corner=8)
        self.link = link
        self.say = say
        self.boxes: dict[str, QComboBox] = {}

        self.hardware = QLabel()
        self.hardware.setWordWrap(True)
        self.hardware.setStyleSheet(f"color:{theme.css(theme.T.DIM, 0.4)}; font-size:{theme.글자(10)};")

        box = QVBoxLayout(self)
        box.setContentsMargins(14, 12, 14, 12)
        box.setSpacing(6)
        box.addWidget(self.hardware)

        # 받기 칸. 없는 모델을 앱 안에서 받는다 — 파일을 손으로 넣게 하면 대부분 안 한다.
        self.get_label = QLabel("받을 모델")
        self.get_label.setWordWrap(True)
        self.get_label.setStyleSheet(f"color:{theme.css(theme.T.DIM, 0.5)}; font-size:{theme.글자(10)};")
        self.get_list = QComboBox()
        self.get_list.setObjectName("pick")
        self.get_button = QPushButton("받기")
        self.get_button.setObjectName("quiet")
        self.get_button.setCursor(Qt.PointingHandCursor)
        self.get_button.clicked.connect(self._get_clicked)
        get_row = QHBoxLayout()
        get_row.setSpacing(6)
        get_row.addWidget(self.get_list, 1)
        get_row.addWidget(self.get_button)

        self.get_box = QWidget()
        get_layout = QVBoxLayout(self.get_box)
        get_layout.setContentsMargins(0, 0, 0, 4)
        get_layout.setSpacing(4)
        get_layout.addWidget(self.get_label)
        get_layout.addLayout(get_row)
        box.addWidget(self.get_box)

        for role, label in self.ROLE_LABEL.items():
            row = QHBoxLayout()
            row.setSpacing(6)
            name = QLabel(label)
            name.setFixedWidth(52)
            name.setStyleSheet(f"color:{theme.css(theme.T.DIM, 0.55)}; font-size:{theme.글자(11)};")
            combo = QComboBox()
            combo.setObjectName("pick")
            combo.activated.connect(lambda _, r=role: self._chose(r))
            self.boxes[role] = combo
            row.addWidget(name)
            row.addWidget(combo, 1)
            box.addLayout(row)
        self.refresh()

    def refresh(self) -> None:
        out = self.link.call("GET", "/eb/v1/models")
        if out is None:
            self.hardware.setText("서버 꺼짐 — 모델을 못 읽는다")
            for c in self.boxes.values():
                c.clear()
            return

        hw = out["hardware"]
        self.hardware.setText(
            f"{hw['gpu'] or 'GPU 없음'} · VRAM {hw['vram_mb']}MB · 등급 {hw['tier']}"
            + chr(10) + hw["note"])
        for role, combo in self.boxes.items():
            combo.blockSignals(True)  # 채우는 동안 고른 것으로 오해하면 안 된다
            combo.clear()
            auto = out["auto"].get(role) or "없음"
            combo.addItem(f"자동 ({auto})", "")
            for name in out["installed"].get(role, []):
                combo.addItem(name, name)
            using = out["using"].get(role, "")
            chosen = combo.findData(using)
            combo.setCurrentIndex(chosen if using and chosen > 0 else 0)
            combo.blockSignals(False)

    def refresh_downloads(self) -> None:
        """받을 수 있는 목록과 진행률. 받는 중에는 진행률만 보여준다."""
        out = self.link.call("GET", "/eb/v1/models/download")
        if out is None:
            self.get_box.hide()
            return
        self.get_box.show()

        if out["busy"] or out["state"] == "downloading":
            self.get_label.setText(
                f"{out['label']} 받는 중 {out['percent']}% "
                f"({out['done_mb']}/{out['total_mb']}MB)")
            self.get_button.setText("멈추기")
            self.get_list.setEnabled(False)
            return

        if out["state"] == "failed":
            self.get_label.setText(f"못 받았어: {out['error'][:60]}")
        elif out["state"] == "cancelled":
            self.get_label.setText("멈췄어. 받다 만 파일은 지웠어")
        else:
            self.get_label.setText("받을 모델")

        self.get_button.setText("받기")
        self.get_list.setEnabled(True)
        self.get_list.blockSignals(True)
        self.get_list.clear()
        for row in out["catalog"]:
            if row["installed"]:
                continue  # 이미 있는 건 안 보여준다
            heavy = "  ⚠ 이 PC엔 버거움" if row["heavy"] else ""
            self.get_list.addItem(f"{row['label']}  {row['size_mb']}MB{heavy}", row["key"])
        if self.get_list.count() == 0:
            self.get_list.addItem("다 받았어", "")
        self.get_list.blockSignals(False)

    def _get_clicked(self) -> None:
        if self.get_button.text() == "멈추기":
            self.link.call("POST", "/eb/v1/models/download", {"cancel": True})
            self.refresh_downloads()
            return
        key = self.get_list.currentData()
        if not key:
            return
        out = self.link.call("POST", "/eb/v1/models/download", {"key": key})
        self.say("받기 시작했어. 다 받으면 목록에 뜬다." if out and out.get("ok")
                 else "지금은 못 받아.")
        self.refresh_downloads()

    def _chose(self, role: str) -> None:
        name = self.boxes[role].currentData() or ""
        out = self.link.call("POST", "/eb/v1/models", {"role": role, "name": name})
        if out is None or not out.get("ok"):
            self.say("그 모델은 못 쓰겠어.")
            self.refresh()
            return
        label = self.ROLE_LABEL[role]
        if role == "meaning":
            # ★ **뜻 모델은 바꾸면 벡터를 처음부터 다시 만든다.** 크기가 달라 섞일 수
            #   없어서다. 2794장에 3분쯤 — 그 말을 안 하면 「멈췄나」 싶다.
            self.meaning_changed.emit(str(paths.meaning_dir(name)))
            self.say(f"{label} 모델을 {name or '자동'}(으)로 바꿨어."
                     " 뜻 벡터를 처음부터 다시 만들어 — 글이 많으면 몇 분 걸려.")
        else:
            self.say(f"{label} 모델을 {name or '자동'}(으)로 바꿨어."
                     " 받아쓰기·목소리는 다시 켤 때 적용돼.")
        self.refresh()
        self.refresh_downloads()
        # 받는 동안 진행률이 움직여야 멈춘 건지 도는 건지 안다.
        self._tick = QTimer(self)
        self._tick.timeout.connect(self.refresh_downloads)
        self._tick.start(1500)


class ServerLink:
    """이 화면에서 서버로 거는 전화. 서버가 꺼져 있어도 화면은 그대로 돌아야 한다.

    원격 세션은 서버 프로세스 안에만 있어서(메모리) 파일로는 못 본다. HTTP로 묻는다.
    """

    def __init__(self, base: str = "http://127.0.0.1:8765",
                 config: str | Path = "") -> None:
        self.base = base.rstrip("/")
        self.token = ""
        # ★★ **아무도 자리를 안 알려 주면 스스로 찾는다.**
        # 예전에는 기본값이 빈 글자라 `Path("")` 을 읽다 조용히 실패했고, 그러면
        # 토큰이 없어 `call()` 이 **아무것도 안 걸고 None 을 돌려줬다** — 창은 서버가
        # 멀쩡히 답하는데도 「서버에 못 물어봤다」만 말했다(시험 쪽이 잡았다).
        # 창을 띄우는 자리에서 아무도 자리를 안 넘겼으니 **여기가 고칠 자리다.**
        config = config or paths.config_path()
        # 서버가 꺼져 있을 때 매번 기다리지 않으려는 장치.
        #
        # 같은 PC 안이라 서버가 살아 있으면 곧바로 답한다. 꺼져 있을 때만 오래
        # 걸리는데, 실제 기록으로 재보니 **창 뜨는 데 4초, 검색 한 번에 2초**가
        # 통째로 이 기다림이었다. 한 번 실패하면 잠깐 쉬었다 다시 건다.
        self.down_until = 0.0
        try:
            self.token = json.loads(Path(config).read_text(encoding="utf-8"))["pair_token"]
        except (OSError, KeyError, TypeError, json.JSONDecodeError):   # 설정이 목록·글자로 망가져도 창은 뜬다
            pass  # 서버를 아직 한 번도 안 띄운 상태. 원격 칸만 비어 보인다

    QUIET_SEC = 5.0      # 실패한 뒤 이만큼은 안 건다
    # 같은 PC 안이다. 살아 있으면 몇 ms 안에 답한다. 꺼져 있을 때 **연결을 기다리는
    # 그 시간이 그대로 창이 굳는 시간**이라, 짧게 끊는다 — 실측에서 1초짜리 대기
    # 하나가 창 뜨는 데 1006ms를 통째로 먹었다.
    TIMEOUT = 0.35

    # ★ **못 건 까닭을 남긴다.** 「서버에 못 물어봤다」만 적고 까닭을 삼켰더니,
    #   구운 판에서 서버는 밖에서 부르면 12ms 에 답하는데 창만 못 거는 것을
    #   아무도 가를 수 없었다. 부드럽게 실패하되 **그 길로 갔다는 것은 보인다.**
    last_fail = ""

    def call(self, method: str, path: str, payload: dict | None = None) -> dict | None:
        if not self.token:
            self.last_fail = "토큰이 없다 (설정 파일을 못 읽었다)"
            return None
        if time.monotonic() < self.down_until:
            return None          # 쉬는 중 — 까닭은 앞서 실패한 것이 들고 있다
        req = urllib.request.Request(
            f"{self.base}{path}", method=method,
            data=None if payload is None else json.dumps(payload, ensure_ascii=False).encode(),
            headers={"Authorization": f"Bearer {self.token}",
                     "Content-Type": "application/json"})
        t0 = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=self.TIMEOUT) as r:
                raw = r.read().decode()
                self.down_until = 0.0
                return json.loads(raw) if raw else {}
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
            self.last_fail = (f"{method} {path} {type(e).__name__}: {e}"
                              f" ({(time.monotonic() - t0) * 1000:.0f}ms)")
            self.down_until = time.monotonic() + self.QUIET_SEC
            return None


class RemoteGateCard(HudPanel):
    """외부 PC가 붙으려 할 때 뜨는 칸. 폰이 없을 때 여기서 승인한다.

    **코드는 서버가 안 알려준다.** 외부 PC 화면에 뜬 네 자리를 사람이 보고 쳐야 한다 —
    목록만 보고 승인하게 하면 그 자리에 없어도 문이 열린다.
    """

    def __init__(self, link: ServerLink, say: Callable[[str], None]) -> None:
        super().__init__(corner=8)
        self.link = link
        self.say = say

        self.title = QLabel()
        self.title.setWordWrap(True)
        self.title.setStyleSheet(f"color:{theme.T.TEXT.name()}; font-size:{theme.글자(12)};")

        self.code = QLineEdit()
        self.code.setPlaceholderText("외부 PC 화면의 네 자리")
        self.code.setMaxLength(4)
        self.code.setObjectName("ask")
        self.code.returnPressed.connect(self.approve)

        self.button = QPushButton("승인")
        self.button.setObjectName("primary")
        self.button.setCursor(Qt.PointingHandCursor)
        self.button.clicked.connect(self.approve)

        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(self.code, 1)
        row.addWidget(self.button)

        box = QVBoxLayout(self)
        box.setContentsMargins(14, 12, 14, 12)
        box.setSpacing(8)
        box.addWidget(self.title)
        box.addLayout(row)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(2000)
        self.refresh()

    def refresh(self) -> None:
        out = self.link.call("GET", "/eb/v1/remote/pending")
        waiting = (out or {}).get("sessions", [])
        self.setVisible(bool(waiting))  # 붙으려는 데가 없으면 칸 자체를 숨긴다
        if waiting:
            where = ", ".join(sorted({s["from"] for s in waiting}))
            self.title.setText(f"{where} 에서 붙으려고 해. 화면의 네 자리를 확인해줘.")

    def approve(self) -> None:
        code = self.code.text().strip()
        if len(code) != 4:
            return
        self.code.clear()
        out = self.link.call("POST", "/eb/v1/remote/approve", {"code": code, "by": "내 PC"})
        if out and out.get("ok"):
            self.say("연결했어. 외부 PC에서 쓸 수 있어.")
        else:
            self.say("코드가 안 맞아. 세 번 틀리면 그 접속은 끊긴다.")
        self.refresh()


class ProposalCard(HudPanel):
    """제안 하나. 승인 버튼이 카드 안에 있어 무엇을 승인하는지 헷갈리지 않는다."""

    decided = pyqtSignal(str, str)  # proposal_id, decision

    def __init__(self, row) -> None:
        super().__init__(corner=8)
        self.pid = row["proposal_id"]

        title = QLabel(row["title"])
        title.setWordWrap(True)
        title.setStyleSheet(f"color:{theme.T.TEXT.name()}; font-family:{theme.SANS}; font-size:{theme.글자(13)}; font-weight:600;")

        summary = QLabel(row["summary"])
        summary.setWordWrap(True)
        summary.setStyleSheet(f"color:{theme.css(theme.T.DIM, 0.6)}; font-size:{theme.글자(11)};")

        evidence = len(json.loads(row["based_on"] or "[]"))
        meta = QLabel(f"근거 {evidence}건" if evidence else "근거 없음")
        meta.setStyleSheet(
            f"color:{theme.css(theme.T.DIM, 0.4)}; font-family:{theme.MONO}; font-size:{theme.글자(10)}; letter-spacing:1px;"
        )

        reject = QPushButton("거절")
        reject.setObjectName("quiet")
        reject.setCursor(Qt.PointingHandCursor)
        reject.clicked.connect(lambda: self.decided.emit(self.pid, "reject"))

        row_btn = QHBoxLayout()
        row_btn.setSpacing(6)
        row_btn.addWidget(meta)
        row_btn.addStretch(1)
        row_btn.addWidget(reject)

        # 고르라는 제안이면 후보마다 단추를 낸다. 승인 단추 하나만 두면 고를 방법이 없어
        # VC가 영영 되묻는다.
        decl = json.loads(row["declaration"] or "{}")
        picks = decl.get("candidates") or []
        if picks and not decl.get("name"):
            for name in picks[:3]:
                btn = QPushButton(name)
                btn.setObjectName("primary")
                btn.setCursor(Qt.PointingHandCursor)
                btn.clicked.connect(lambda _, n=name: self.decided.emit(self.pid, f"pick:{n}"))
                row_btn.addWidget(btn)
        else:
            approve = QPushButton("승인")
            approve.setObjectName("primary")
            approve.setCursor(Qt.PointingHandCursor)
            approve.clicked.connect(lambda: self.decided.emit(self.pid, "approve"))
            row_btn.addWidget(approve)

        box = QVBoxLayout(self)
        box.setContentsMargins(14, 13, 14, 12)
        box.setSpacing(7)
        box.addWidget(title)
        box.addWidget(summary)
        # ★★ **무엇을 승인하는지는 우리가 선언문에서 직접 뽑아 보인다.** 요약은 제안한 쪽이 적은 글이라
        #   바깥 스킬이면 거짓일 수 있다(「무해함」이라 적고 딴 모듈을 부를 수 있다). 부르는 것을 그대로 적는다.
        단계 = [s for s in (decl.get("steps") or []) if isinstance(s, dict)]
        if 단계:
            바깥 = json.loads(row["based_on"] or "[]") == ["바깥"]
            self.steps_label = QLabel(("바깥에서 온 스킬 · " if 바깥 else "") + "부르는 것: " + " → ".join(
                f"{s.get('module')}({', '.join(f'{k}={v}' for k, v in (s.get('params') or {}).items())})"
                for s in 단계[:6]))
            self.steps_label.setWordWrap(True)
            self.steps_label.setStyleSheet(
                f"color:{theme.css(theme.T.WARN if 바깥 else theme.T.DIM, 0.8)}; font-family:{theme.MONO}; font-size:{theme.글자(10)};")
            box.addWidget(self.steps_label)
        box.addLayout(row_btn)


def _self_check() -> None:
    panel = HudPanel()
    assert panel.objectName() == "hud"

    # ★ 바깥 스킬 제안 카드는 요약이 아니라 **실제로 부르는 모듈**을 보여 준다.
    _카드 = ProposalCard({"proposal_id": "ext-1", "title": "바깥 스킬: 집에 가기", "summary": "무해함",
                         "based_on": '["바깥"]',
                         "declaration": '{"name": "집에 가기", "steps": [{"module": "navigate", "params": {"to": "집"}}]}'})
    _글 = _카드.steps_label.text()
    assert "navigate(to=집)" in _글 and "바깥" in _글, f"승인할 것이 카드에 안 보인다: {_글}"

    # ★ 색인 실이 훑다 실패하면 기록 파일에 남는다 — 구운 판은 콘솔이 없어 말없이 넘기면 아무도 모른다.
    import os as _os9
    import tempfile as _tf9

    with _tf9.TemporaryDirectory() as _곳:
        _옛 = _os9.environ.get("VC_DATA")
        _os9.environ["VC_DATA"] = _곳
        try:
            _색 = Indexer(notes.Notes(Path(_곳) / "notes", index_now=False), model_dir=str(Path(_곳) / "없는모델"))
            _색.notes.reindex = lambda: 1 / 0
            _색._embed_tried = True            # 모델 올리기는 건너뛴다(이 검사는 훑기 실패만 본다)
            _색.run()
            _기록길 = Path(_곳) / "vc-기록.log"
            _기록 = _기록길.read_text(encoding="utf-8") if _기록길.exists() else ""
            assert "[색인 실 실패] 훑기" in _기록, f"색인 실 실패가 기록에 안 남는다: {_기록[-200:]}"
            _색.notes.conn.close()
        finally:
            if _옛 is None:
                _os9.environ.pop("VC_DATA", None)
            else:
                _os9.environ["VC_DATA"] = _옛

    # ★★ **창은 서버에 걸 수 있어야 한다.** 자리를 아무도 안 넘기면 스스로 찾는다.
    # 예전 기본값은 빈 글자라 토큰을 못 읽었고, 토큰이 없으면 `call()` 이 아예
    # 안 걸고 None 을 준다 — 서버가 멀쩡한데 창만 「못 물어봤다」고 했다.
    import json as _json
    import os as _os
    import tempfile as _tf

    with _tf.TemporaryDirectory() as 잠깐설정:
        옛자리 = _os.environ.get("VC_DATA")
        _os.environ["VC_DATA"] = 잠깐설정
        try:
            paths.config_path().write_text(
                _json.dumps({"pair_token": "시험토큰"}), encoding="utf-8")
            assert ServerLink().token == "시험토큰", "창이 서버 토큰을 못 읽는다"
        finally:
            if 옛자리 is None:
                _os.environ.pop("VC_DATA", None)
            else:
                _os.environ["VC_DATA"] = 옛자리

    legend = Legend()
    assert legend.height() > 0
    # 표시줄과 콤보의 차례가 같아야 한다 — 같은 것을 두 군데 적어 두면 갈린다.
    assert Legend.ORDER == tuple(theme.KIND_LABEL), Legend.ORDER

    import tempfile
    from pathlib import Path as _Path
    import notes as _notes
    with tempfile.TemporaryDirectory() as _tmp:
        store = _notes.Notes(_Path(_tmp) / "n")
        store.write(_notes.Note(title="가", body="ㄱ"))
        idx = Indexer(store)
        seen = []
        idx.done.connect(seen.append)
        idx.ask()
        idx.wait(5000)
        app.processEvents()
        assert seen, "훑고 나서 알려주지 않는다"
        # 도는 중에 또 부탁하면 끝난 뒤 한 번 더 돈다 — 부탁이 씹히면 안 된다.
        idx.again = False
        idx.ask()
        idx.wait(5000)
        app.processEvents()
        assert len(seen) >= 2

    years = Years()
    years.show_years([("2026", 12), ("2025", 40), ("2024", 3)])
    assert [b.text() for b in years.buttons] == ["26", "25", "24"]
    picked = []
    years.picked.connect(picked.append)
    years.buttons[1].click()
    assert picked == ["2025"], picked
    years.show_years([("2026", 1)])
    assert len(years.buttons) == 1, "다시 그렸는데 옛 단추가 남았다"
    # 빈칸이 쌓이면 단추가 왼쪽에 안 붙고 가운데로 밀린다.
    assert years.grid.count() == 2, f"빈칸이 쌓였다: {years.grid.count()}"

    # ★★ **글에 남긴 인터넷 주소는 눌러서 브라우저로 연다**(오너 2026-09-20).
    #   전에는 `setOpenLinks(False)` 로 전부 막아 두고 우리 이름표만 다뤄 **눌러도 아무 일이 없었다**.
    _뷰 = NoteView()
    열린것 = []
    _뷰.바깥열기 = 열린것.append
    assert _뷰.바깥주소인가("https://example.com/a?b=1")
    assert _뷰.바깥주소인가("http://100.1.2.3:8765") and _뷰.바깥주소인가("mailto:a@b.c")
    # 우리끼리 쓰는 이름표는 바깥으로 안 나간다 — 나가면 글 열기·태그 고르기가 브라우저로 샌다
    assert not _뷰.바깥주소인가("note:회의록") and not _뷰.바깥주소인가("tag:할일")
    assert not _뷰.바깥주소인가("file:/tmp/a.png") and not _뷰.바깥주소인가("회의록")
    from PyQt5.QtCore import QUrl as _QUrl

    _뷰._went(_QUrl("https://example.com/글"))
    assert 열린것 == ["https://example.com/글"], 열린것
    _뷰._went(_QUrl("note:회의록"))          # 이건 안 열린다(글 열기 신호로 간다)
    assert len(열린것) == 1, 열린것
    # 우클릭 메뉴 — 링크 위에서만 「열기·복사」가 붙는다
    메뉴 = _뷰.링크메뉴("https://example.com")
    assert 메뉴 is not None and [a.text() for a in 메뉴.actions()] == ["브라우저로 열기", "주소 복사"], 메뉴
    assert _뷰.링크메뉴("note:회의록") is None and _뷰.링크메뉴("") is None
    메뉴.actions()[0].trigger()
    assert 열린것[-1] == "https://example.com", 열린것
    # 민 주소도 Qt 가 링크로 그린다 — 마크다운을 안 써도 눌린다
    _뷰.setMarkdown(_뷰.to_markdown("여기 https://quasarzone.com/bbs/qn_hardware/views/2065297 참고"))
    assert "<a href" in _뷰.toHtml() and "quasarzone" in _뷰.toHtml()

    view = NoteView()
    src = "제목 [[가#머리]] 와 [[나|보임]] 와 ![[다]] 와 #태그/하위"
    md = view.to_markdown(src)
    # ★ **빈칸이 든 주소는 Qt 가 링크로 안 만든다.** 그래서 `<...>` 로 감싼다.
    #   안 감싸면 `[안 먹는 말투](note:안 먹는 말투)` 가 화면에 글자 그대로 나온다 —
    #   제목에 빈칸이 흔해서 **거의 모든 이음선이 날것으로 보이고 있었다**(시험 쪽 라-②).
    빈칸 = view.to_markdown("[[안 먹는 말투]] 와 [[조사 어긋나감]]")
    assert "(<note:안 먹는 말투>)" in 빈칸, 빈칸
    view.show_note("이어보기 [[안 먹는 말투]] 와 #할 일 태그.")
    보임 = view.toPlainText()
    assert "note:" not in 보임 and "](" not in 보임, "링크가 날것으로 보인다: " + 보임
    assert "<a " in view.toHtml(), "앵커가 안 생겼다"
    assert "안 먹는 말투" in 보임, 보임
    assert "(note:가#머리)" in md.replace("<", "").replace(">", "") and "가 › 머리" in md, md
    assert "[보임](<note:나>)" in md, md
    assert "(<note:다>)" in md and "⟨다⟩" in md, md
    assert "(<tag:태그/하위>)" in md, md
    # ★ **색상 코드는 태그가 아니다.** 뽑는 쪽만 거르고 칠하는 쪽은 안 걸러서,
    #   목록엔 안 들어가는 `#0E1116` 이 본문에서는 태그와 같은 붉은색으로 칠해졌다
    #   (시험 쪽 「뽑기와 색칠이 따로 논다」). 이제 판단이 한 자리다.
    색 = view.to_markdown("배경은 #0E1116 이고 태그는 #할일 이다.")
    assert "#0E1116 " in 색 and "tag:0E1116" not in 색, 색
    assert "[#할일](<tag:할일>)" in 색, 색
    # ★ 미리보기에서도 `[[ ]]`·`##` 를 편다. 카드 읽기 모드는 링크로 그리는데
    #   미리보기만 원문이라 **링크를 고친 값이 절반만 왔다**(시험 쪽).
    #   미리보기는 찾을 때마다 보는 자리다.
    폄 = Results.snippet("## 첫째 소제목" + chr(10)
                         + "[[안 먹는 말투]] 과 [[기록]] 과 [[안 먹는 말투#첫째]] 다.",
                         "기록", 70)
    assert "[[" not in 폄 and "##" not in 폄, 폄
    assert "안 먹는 말투 › 첫째" in 폄, 폄
    # 아주 긴 글은 앞부분만 그린다. 통째로 그리면 18만 자에서 1.5초 동안 창이 굳는다.
    import time as _t
    huge = ("긴 글입니다. " * 20000)
    _t0 = _t.perf_counter(); view.show_note(huge); _spent = _t.perf_counter() - _t0
    assert _spent < 0.6, f"긴 글에서 굳는다: {_spent:.2f}s"
    assert "앞" in view.toPlainText() and "고치기" in view.toPlainText(), "잘랐다고 말 안 한다"
    # 오래 걸리면 스스로 덜 그린다. 글자 수만으로는 못 정한다 — 내용에 따라 값이 다르다.
    view.RENDER_BUDGET = 0.0
    view.show_note(huge)
    assert view.limit < NoteView.RENDER_START, "느린데도 안 줄인다"
    assert view.limit >= NoteView.RENDER_FLOOR, "너무 줄여 쓸모가 없다"
    view.RENDER_BUDGET = 999.0
    for _ in range(20):
        view.show_note("짧은 글")
    assert view.limit == NoteView.RENDER_LIMIT, "빨라졌는데 안 돌아온다"

    view.show_note(chr(10).join(["# 큰 제목", "", "- 하나", "- 둘", "", "[[가]] 와 #태그"]))
    html = view.toHtml()
    assert "<h1" in html and "<li" in html, "마크다운이 안 입혀진다"
    # 링크가 기본 파랑으로 남으면 테마가 무슨 색이든 그것만 따로 논다.
    # 링크 글자만 테마 색이어야 한다. 문자열 치환으로는 뒤따르는 글자가 물들었다.
    assert "color:#0000ff" not in html.lower(), "링크 색이 기본 파랑 그대로다"
    assert theme.T.ACCENT.name() in html.lower(), "링크에 테마 색이 안 들어갔다"
    plain = view.toPlainText()
    hit = plain.index("가")
    c = QTextCursor(view.document()); c.setPosition(hit + 1)
    assert c.charFormat().foreground().color().name() == theme.T.ACCENT.name(), "링크 글자 색이 안 바뀐다"
    after = plain.index("와", hit)
    c.setPosition(after + 1)
    assert c.charFormat().foreground().color().name() != theme.T.ACCENT.name(),         "링크가 아닌 글자까지 물들었다"
    # HTML만 고치면 Qt가 팔레트의 기본 파랑으로 되돌려 칠한다.
    assert view.palette().color(QPalette.Link).name() == theme.T.ACCENT.name()
    got = []
    # 첨부는 진짜 그림으로 들어간다. 못 찾으면 그렇다고 말한다.
    import tempfile as _tf
    with _tf.TemporaryDirectory() as _d:
        shot = Path(_d) / "사진.png"
        big = QImage(2400, 1200, QImage.Format_RGB888)
        big.fill(0)
        big.save(str(shot))
        v2 = NoteView(find_file=lambda nm: shot if nm == "사진.png" else None)
        md2 = v2.to_markdown("현장 ![[사진.png]] 과 ![[없는것.png]]")
        assert "![사진.png](file:" in md2, md2
        assert "없는 첨부" in md2, md2
        # ★ 폰 사진(.heic)·영상·녹음은 그림 칸에 넣으면 깨진다 — 📎 고리로(4단계).
        영상 = Path(_d) / "IMG_0001.mov"
        영상.write_bytes(b"mov")
        v3 = NoteView(find_file=lambda nm: 영상 if nm == "IMG_0001.mov" else None)
        md3 = v3.to_markdown("받은 제품 ![[IMG_0001.mov]]")
        assert "[📎 IMG_0001.mov](file:" in md3 and "![IMG_0001.mov]" not in md3, md3
        # 항목 줄은 목록 점 대신 굵은 이름 · 값(2026-09-18 창 점검)
        md4 = v3.to_markdown("- 제품명 : vcis-689\n- 보낸날 : \n- [[회의]] 보기")
        assert "**제품명** · vcis-689" in md4 and "**보낸날** · —" in md4, md4
        assert "송장" not in v3.to_markdown("받음\n%%\n사진 글자: 송장 7788\n%%"), "숨은 글자가 보인다"
        # ★★ **코드 안의 `[[…]]` 는 예시다.** 안 가리면 「이 창고를 쓰는 법」 같은 규칙 글이
        #   화면에서 `[링크](<note:링크>)` 로 깨져 보인다(2026-09-21 재서 봤다).
        깨짐 = v3.to_markdown("```\n[[링크]] 처럼 적는다\n```\n\n홑따옴 `[[링크]]` 도.\n\n진짜 [[VC]].")
        assert "```\n[[링크]] 처럼" in 깨짐, f"코드 울타리 안의 예시를 고쳤다:\n{깨짐}"
        assert "`[[링크]]`" in 깨짐, f"홑따옴 안의 예시를 고쳤다:\n{깨짐}"
        assert "[VC](<note:VC>)" in 깨짐, f"진짜 링크를 안 고쳤다:\n{깨짐}"

        # 큰 사진은 칸 폭에 맞춰 줄인다. 원래 크기로 두면 칸을 뚫고 나간다.
        v2.resize(320, 240)
        v2.show_note("![[사진.png]]")
        widths = []
        blk = v2.document().begin()
        while blk.isValid():
            i = blk.begin()
            while not i.atEnd():
                f = i.fragment().charFormat()
                if f.isImageFormat():
                    widths.append(f.toImageFormat().width())
                i += 1
            blk = blk.next()
        # 창을 안 띄운 위젯은 resize가 뷰포트까지 안 내려가므로, 뷰포트 폭을 기준으로 본다.
        assert widths, "사진이 문서에 안 들어갔다"
        assert widths[0] <= v2.viewport().width(), (widths, v2.viewport().width())
        assert widths[0] < 2400, "원래 크기 그대로다 — 칸을 뚫고 나간다"

    view.link_clicked.connect(lambda n, h: got.append((n, h)))
    view.tag_clicked.connect(lambda t: got.append(("태그", t)))
    from PyQt5.QtCore import QUrl
    view._went(QUrl("note:회사#8월"))
    view._went(QUrl("tag:업무"))
    assert got == [("회사", "8월"), ("태그", "업무")], got

    body = NoteBody()
    text = "[[납품 일정]]까지 확인. #업무 로 묶음"
    body.setPlainText(text)
    assert body._token_at(text, 3) == ("link", "납품 일정", "")
    assert body._token_at(text, text.index("#업무") + 1) == ("tag", "업무", "")
    # 소제목까지 같이 읽어야 그 자리로 데려갈 수 있다.
    with_head = "[[보고서#8월 정산]] 참고"
    assert NoteBody._token_at(with_head, 4) == ("link", "보고서", "8월 정산")

    # **`[[` 목록은 Esc 로 닫혀야 한다.** 목록이 뜨면 키가 글상자로 안 온다 —
    # 낯선 PC 에서 Esc 를 두 번 눌러도 안 닫혔다. 목록에 직접 건 거름망이 받는다.
    from PyQt5.QtGui import QKeyEvent

    body.title_source = lambda part: ["납품 일정", "납기"]
    body.setPlainText("[[납")
    cur = body.textCursor()
    cur.movePosition(cur.End)
    body.setTextCursor(cur)
    body._offer_links()
    assert body._pop.popup().isVisible(), "목록이 안 떴다"
    # **옷이 목록 자체에 걸려 있어야 한다.** 이 목록은 별개 최상위 창이라 주 창
    # 스타일시트가 안 내려간다 — 낯선 PC 에서 두 판 연속 흰 바탕·파란 막대였다.
    assert theme.T.PANEL.name() in body._pop.popup().styleSheet(), "목록에 옷이 안 걸렸다"
    # 12개를 주는데 7줄만 보이면 방금 만든 글이 안 보인다 — 실사용에서 나온 말이다.
    assert body._pop.maxVisibleItems() >= 12, body._pop.maxVisibleItems()
    body.eventFilter(body._pop.popup(),
                     QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))
    assert not body._pop.popup().isVisible(), "Esc 를 눌러도 목록이 안 닫힌다"

    long_note = chr(10).join(["머리말", "", "## 7월 정산", "내용", "", "## 8월 정산", "여기"])
    body.setPlainText(long_note)
    body.go_to_heading("8월 정산")
    assert body.textCursor().position() == long_note.index("## 8월 정산"), body.textCursor().position()
    body.go_to_heading("없는 소제목")
    assert body.textCursor().position() == 0, "못 찾았으면 맨 위에 둬야 한다"
    assert body._token_at(text, text.index("확인")) is None, "아무 데나 눌러도 이동하면 안 된다"

    # 서버가 꺼져 있으면 **한 번만** 기다리고 잠깐 쉰다. 매번 기다리면 창이 굳는다.
    link = ServerLink(base="http://127.0.0.1:1", config="없는설정.json")
    link.token = "dummy"   # 헤더는 아스키만 실린다
    t = time.perf_counter()
    for _ in range(5):
        assert link.call("GET", "/eb/v1/status") is None
    spent = time.perf_counter() - t
    assert spent < ServerLink.TIMEOUT * 2 + 0.5, f"매번 기다린다: {spent:.1f}s"
    assert link.down_until > time.monotonic(), "실패를 기억 안 한다"

    res = Results()
    res.show_hits([("납품 일정", "8월 3일까지 [[견적서]] 보내고 확인"),
                   ("회의록", "견적서 다시 검토하기로 함")], "견적")
    assert len(res.items) == 4, "제목과 걸린 줄이 짝으로 안 나온다"
    # 걸린 낱말 둘레를 잘라 온다 — 앞머리만 주면 왜 걸렸는지 모른다.
    assert "견적서" in res.snippet("가" * 200 + " 견적서 보냄 " + "나" * 200, "견적서")
    # ★ **긴 물음으로도 걸린 자리를 집어야 한다.** 예전에는 물음을 통째로 찾아서
    #   문장으로 물으면 늘 앞머리만 보여 줬다 — 「걸린 낱말 둘레」라는 뜻이 죽어 있었다.
    #   조사도 넘는다: 물음 「견적서를」 · 본문 「견적서」.
    긴것 = res.snippet("가" * 200 + " 견적서 보냄 " + "나" * 200,
                      "지난주에 보낸 견적서를 어디에 뒀나")
    assert "견적서" in 긴것, f"긴 물음에서 걸린 자리를 못 집는다: {긴것}"
    assert res.snippet("짧은 글", "없는말") == "짧은 글"
    got = []
    res.picked.connect(got.append)
    res.items[0].click()
    assert got == ["납품 일정"]
    # ★ **갈래를 보여 준다.** 결과에 여러 갈래가 섞여 오는데 사람은 볼 길이 없었다.
    res.show_hits([("결정 27", "엔진을 직접 만들기로 했다", "", "결정"),
                   ("잡담", "그냥 해 본 말", "", "일")], "엔진")
    글자 = " ".join(w.text() for w in res.items if hasattr(w, "text"))
    assert "결정 ·" in 글자, f"갈래를 안 보여 준다: {글자!r}"
    res.show_hits([("보통 글", "기본 갈래는 안 적는다", "", "note")], "기본")
    글자 = " ".join(w.text() for w in res.items if hasattr(w, "text"))
    assert "note ·" not in 글자, f"기본 갈래까지 적어 줄만 길어진다: {글자!r}"

    # ★★ **뜻 모델을 바꾸면 훑는 실이 새 모델을 써야 한다.** 예전에는 `model_dir` 을
    #   만들 때 한 번 정하고 `_embed_tried` 로 잠가서, 바꿔도 **다시 켜도** 옛 모델을
    #   계속 썼다 — 고르는 칸만 있고 아무 일도 안 일어났다.
    import tempfile as _t
    with _t.TemporaryDirectory() as _tmp:
        from notes import Notes as _N
        idx = Indexer(_N(Path(_tmp) / "n", ":memory:", index_now=False), model_dir="옛자리")
        idx._embed_tried = True
        idx.뜻모델바꿈("옛자리")
        assert idx._embed_tried, "같은 자리인데 괜히 다시 만든다"
        idx.뜻모델바꿈("새자리")
        assert idx.model_dir == "새자리" and not idx._embed_tried,             "뜻 모델을 바꿨는데 훑는 실이 옛 모델을 그대로 쓴다"

    res.show_hits([], "")
    assert res.rows.count() == 0, "다시 그렸는데 옛 결과가 남았다"

    gaps = Gaps()
    gaps.show_gaps([("납품 일정", 3), ("견적서", 1)])
    # 창이 안 떠 있으면 isVisible은 늘 거짓이다. 직접 숨겼는지로 본다.
    assert len(gaps.buttons) == 2 and gaps.empty.isHidden()
    got = []
    gaps.picked.connect(got.append)
    gaps.buttons[0].click()
    assert got == ["납품 일정"], got
    # 다시 그려도 안 쌓인다. 미뤄서 지우면 옛 단추가 자리에 남아 목록이 두 배가 된다.
    gaps.show_gaps([("납품 일정", 3), ("견적서", 1)])
    assert gaps.rows.count() == 1 + 2, f"단추가 쌓였다: {gaps.rows.count()}"

    gaps.show_gaps([])
    assert not gaps.empty.isHidden(), "빈 목록인데 안내가 안 뜬다"
    assert gaps.rows.count() == 1, "빈 목록인데 단추가 남았다"

    feed = ActivityFeed()
    feed.show_rows([{"ts": "2026-08-27T09:00:00", "tier": "pc", "module": "볼륨",
                     "phase": "실행", "outcome": "success", "failure_point": None}])
    assert len(feed.rows) == 1

    # 실패색이 강조색과 같으면 성공·실패를 눈으로 못 가른다.
    for key in ("vulcan", "hud", "midnight", "paper"):
        theme.use(key)
        assert theme.T.WARN.name() != theme.T.ACCENT.name(), key
    theme.use("vulcan")

    # 옆 판 — 읽기만 된다. 고치는 길이 열려 있으면 두 곳에서 같은 글을 고치게 된다.
    side = SideReader(find_file=lambda n: None)
    side.show_note("곁글", "# 곁글" + chr(10) * 2 + "곁에 두고 보는 글")
    assert side.title.text() == "곁글"
    assert "곁에 두고 보는 글" in side.view.toPlainText()
    assert side.view.isReadOnly()

    # 할 일 목록. 한 일과 안 한 일이 **같아 보이면 안 된다** — Qt 마크다운은 둘 다
    # 그냥 점으로 바꿔 버린다.
    look = NoteView(find_file=lambda n: None)
    look.show_note("- [ ] 안 한 일" + chr(10) + "- [x] 한 일" + chr(10)
                   + "- 그냥 항목" + chr(10) * 2 + "[[링크]] 와 배열 x[0]" + chr(10))
    shown = look.toPlainText()
    assert "☐ 안 한 일" in shown, shown
    assert "☑ 한 일" in shown, shown
    assert "x[0]" in shown, "본문 중간 대괄호는 안 건드린다"

    # `[[` 자동완성. 뜨는 것보다 **안 떠야 할 때 안 뜨는 것**이 중요하다 —
    # 아무 대괄호에나 목록이 튀어나오면 글을 못 쓴다.
    body = NoteBody()
    body.title_source = lambda part: [t for t in ("회의록", "회의 준비", "계약서")
                                      if part in t][:5]

    def typed(text: str) -> bool:
        body.setPlainText(text)
        cur = body.textCursor()
        cur.movePosition(QTextCursor.End)
        body.setTextCursor(cur)
        body._offer_links()
        return body._pop.popup().isVisible()

    assert typed("관련: [[회의")
    assert body._pop_model.stringList() == ["회의록", "회의 준비"]
    assert not typed("[[회의]] 뒤에 글")          # 이미 닫혔다
    assert not typed("그냥 [대괄호] 하나")         # 대괄호 하나
    assert not typed("[[없는이름ZZZ")             # 맞는 게 없다
    assert not typed("[[회의" + chr(10) + "다음줄")  # 줄이 바뀌었다
    body.setPlainText("관련: [[회의")
    cur = body.textCursor()
    cur.movePosition(QTextCursor.End)
    body.setTextCursor(cur)
    body._put_link("회의록")
    assert body.toPlainText() == "관련: [[회의록]]", body.toPlainText()
    # `]]`를 미리 쳐 뒀으면 겹쳐 붙이지 않는다.
    body.setPlainText("관련: [[회의]]")
    cur = body.textCursor()
    cur.setPosition(len("관련: [[회의"))
    body.setTextCursor(cur)
    body._put_link("회의록")
    assert body.toPlainText() == "관련: [[회의록]]", body.toPlainText()

    # **첫 줄이 제목을 되풀이하면 그 줄은 헛돈다.** 낯선 PC 에서 찾은 것 여덟 줄 중
    # 여섯이 「설비 보수 236 / 설비 보수 236 빠뜨린 것이 없는지…」 꼴이었다.
    조각 = Results.snippet("설비 보수 236 빠뜨린 것이 없는지 한 번 더 본다", "",
                           46, "설비 보수 236")
    assert 조각.startswith("빠뜨린"), 조각
    # 제목뿐인 글은 그대로 둔다 — 지우면 빈 줄만 남아 더 못 읽는다.
    assert Results.snippet("회의록", "", 46, "회의록").startswith("회의록")
    # 제목과 안 겹치는 글은 건드리지 않는다.
    assert Results.snippet("아침에 뛰었다", "", 46, "달리기").startswith("아침에")
    # ★ 꾸미는 글자는 미리보기에 안 남는다 — 제목에서는 벗겼는데 여기서 안 벗겨서
    #   「**안 먹는 말투**」가 별표째 나왔다(시험 쪽 새-②).
    조 = Results.snippet("정답은 **안 먹는 말투** 이고 `코드` 도 있다", "말투", 46)
    assert "**" not in 조 and "`" not in 조, 조
    assert "안 먹는 말투" in 조, 조

    # ★★ **끼워 넣은 글은 그 자리에 펼친다**(옵시디언과 같다). 고리표만 보이면 내용 없는 이름표다.
    #   한 겹만 — 펼친 속의 `![[…]]` 는 다시 안 펼친다(서로 끼우면 끝없이 돈다).
    몸들 = {"보고서": "## 7월" + chr(10) + "지난달" + chr(10) + "## 8월 정산" + chr(10) + "정산 끝 ![[보고서]]"}
    펼침 = NoteView(find_file=lambda n: None, find_note=몸들.get)
    글 = 펼침.to_markdown("이번 달: ![[보고서#8월 정산]] 참고")
    assert "정산 끝" in 글, f"끼워 넣은 글을 안 펼친다: {글}"
    assert "지난달" not in 글, "다른 토막까지 펼쳤다"
    assert 글.count("정산 끝") == 1, "펼친 속을 또 펼쳤다 — 서로 끼우면 끝없이 돈다"
    assert "없는글" in NoteView(find_file=lambda n: None, find_note=몸들.get).to_markdown("![[없는글]]"),         "없는 글을 끼우면 고리표라도 남아야 한다"

    # ★ **`[[글#^이름]]` 으로 가면 그 줄로 가야 한다.** 편집기는 `#` 소제목만 찾아 맨 위에 떨어졌다.
    쓸몸 = NoteBody()
    쓸몸.setPlainText("첫 줄" + chr(10) * 30 + "여기가 답이다. ^답칸" + chr(10) + "끝")
    쓸몸.go_to_heading("^답칸")
    assert 쓸몸.textCursor().block().text().startswith("여기가 답"), "블록 이름으로 그 줄에 안 간다(편집기)"
    읽몸 = NoteView(find_file=lambda n: None)
    읽몸.setMarkdown("첫 줄" + chr(10) * 2 + "- 둘째 항목 이다" + chr(10) * 2 + "끝")
    읽몸.go_to_heading("둘째 항목")
    assert 읽몸.textCursor().block().text().strip().startswith("둘째 항목"), "읽기 화면이 덩이 첫 줄로 안 간다"

    # ★★ **긴 제목이 칸을 밀어내면 안 된다**(오너 2026-09-20 · 볼트를 들이고 드러났다).
    #   단추는 줄바꿈을 못 해 제목 전체 폭을 최소폭으로 요구했다. 옵시디언 볼트 119장이
    #   들어오자 오른쪽 칸 최소폭이 144 → 455 로 뛰어 칸(348)을 넘겼고, **칸 전체가
    #   창 밖으로 112px 밀려 글자가 잘렸다.** 실기 화면을 찍어 보고서야 알았다.
    긴제목 = "신규 대형 프로젝트 착수 — AR-AI 에이전트 (그릴링 진행 중, 미결) 그리고 더 긴 꼬리"
    목록 = Results(번호매김=True)
    목록.resize(200, 300)
    목록.show()          # 보여야 레이아웃이 돈다 — 안 그러면 줄이 칸 폭을 못 본다
    목록.show_hits([(긴제목, "몸", "", "dev-task"), ("짧은 글", "몸", "", "")], "")
    app9 = QApplication.instance()
    for _ in range(5):
        if app9 is not None:
            app9.processEvents()
    단추들 = 목록.findChildren(QPushButton)
    assert 단추들, "줄이 안 그려졌다"
    긴것 = 단추들[0]
    # **줄여 그리되 진짜 제목은 온전해야 한다** — 누르면 열리는 것이 이것이다
    assert 줄제목(긴것) == 긴제목, f"진짜 제목이 안 남았다: {줄제목(긴것)}"
    assert 긴것.text().endswith("…"), f"긴 제목이 안 줄었다({긴것.width()}px): {긴것.text()}"
    assert len(긴것.text()) < len(긴제목), "줄인 티가 안 난다"
    # 폭 요구를 안 하는지 — 이게 칸을 밀어내던 것이다
    assert 목록.minimumSizeHint().width() <= 200, (
        f"줄이 칸보다 넓은 폭을 요구한다: {목록.minimumSizeHint().width()}")
    # 칸이 넓어지면 **다시 온전히** 보인다 — 줄인 채로 굳으면 안 된다
    목록.resize(900, 300)
    for _ in range(5):
        if app9 is not None:
            app9.processEvents()
    assert not 단추들[0].text().endswith("…"), f"넓어졌는데 그대로 줄어 있다: {단추들[0].text()}"

    print("panels self-check 통과")


if __name__ == "__main__":
    import os
    import sys

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt5.QtWidgets import QApplication

    app = QApplication(sys.argv)
    _self_check()
