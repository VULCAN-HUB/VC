"""VC 화면 — 3D로 자라는 신경망과 말하는 연출.

처음 켜면 빈 화면에 **VC 항목 하나**만 있다. 쓸수록 기억·스킬이 항목으로 쌓이고
서로 이어지면서 제2의 두뇌가 된다(결정 29·30).

배치는 3차원이다. 항목이 적을 때는 성기게 퍼져 있다가 **쌓일수록 구에 가까워진다.**
가운데 VC가 세포체, 뻗어 나간 항목들이 수상돌기 — 뉴런 구조와 같은 모양이다.
평면에 늘어놓으면 연결이 서로를 가리지만, 구면에서는 깊이로 갈라진다.

VC가 말할 때는 그 말이 딛고 있는 항목들이 **순서대로 밝아진다.** 문장 속도에 맞춰
순차로 켜야 말하는 것처럼 보인다 — 한꺼번에 깜빡이면 장식으로 보인다.

성능: 발광 효과는 **말하는 항목에만** 건다. 물리 계산은 자리가 잡히면 멈추고,
그 뒤로는 회전·투영만 돈다. 항목마다 효과를 걸어두면 수백 개에서 무거워진다.

UI는 PC 프로그램의 곁가지다. 본체는 폰이고(결정 25) 여기서는 보고·승인·열람만 한다.
"""

from __future__ import annotations

import html
import json
import math
import functools
import re
import sys
import threading
import time
from pathlib import Path

from typing import Callable

# **PyQt5 보다 먼저 불러온다.** `paths` 가 시스템 C++ 런타임을 붙드는데, Qt 가 제
# 낡은 런타임을 DLL 찾는 자리 앞에 끼워 넣기 전에 해야 한다.
import paths
import report
import settings
import talklog

from PyQt5.QtCore import QEvent, QFileSystemWatcher, QRectF, Qt, QThread, QTimer, pyqtSignal
from PyQt5.QtGui import QKeySequence, QTextCursor
from PyQt5.QtWidgets import (
    QApplication,
    QShortcut,
    QComboBox,
    QFrame,
    QMessageBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QMenu,
    QLayout,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

import theme
from panels import (PROPOSAL_AREA_MIN_H, ActivityFeed, Folded, Gaps, HudPanel, Indexer, Legend,
                    SideReader,
                    ModelPicker, NoteBody, NoteView, ProposalCard, RemoteGateCard,
                    Results, ServerLink, Years)
from graph3d import FOCUS_ZOOM, OLD_ROOT, ROOT, GraphView
import notes as notes_module
import orders
from notes import Note, Notes, WriteBlocked, read_text, flip_task, headings, section
from skills import Skill, SkillStore, analyze
from store import Store


def _키글(키: str) -> str:
    """차림표에 적는 단축키 글. **맥은 Qt 가 Ctrl 을 ⌘ 로 읽는다** — `(Ctrl+,)` 로 적혀 헷갈렸다(오너 2026-09-15)."""
    return 키.replace("Ctrl+", "⌘") if sys.platform == "darwin" else 키

# --- 화면 상수 ----------------------------------------------------------
#
# 색·글꼴은 **여기 없다.** theme.py가 들고 있고 `theme.T.X`로 쓴다 — 통째로 갈아
# 끼워지므로 `from theme import ACCENT`로 가져가면 테마를 바꿔도 옛 색이 남는다.
# 그래프는 graph3d.py, 옆칸 부품은 panels.py에 있다.

LINK_MARK = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")

# 그래프에 한 번에 올리는 항목 수. 물리 계산이 항목 수에 비례해서 수천 개를
# 올리면 창이 굳는다(4000개에 한 걸음 0.53초, 실측). 나머지는 검색·목록으로 닿는다.
GRAPH_LIMIT = 400
# 밖에서 고친 글이 늦어도 이만큼 안에 화면에 온다. 폴더 감시는 「생김」만 알려 주고
# 「고쳐짐」은 안 알려 주기 때문에 틈틈이 직접 물어봐야 한다.
OUTSIDE_POLL_MS = 3000


class VoiceWorker(QThread):
    """마이크를 듣는 별도 실 . 받아쓴 말만 화면 쪽으로 넘긴다.

    **Qt 위젯은 이 실에서 만지지 않는다.** 다른 실에서 위젯을 건드리면 조용히 깨지거나
    한참 뒤에 엉뚱한 곳에서 터진다 — 신호로만 넘긴다.
    """

    heard = pyqtSignal(str)  # 받아쓴 지시
    level = pyqtSignal(float)  # 지금 들어오는 소리 크기(0~1)
    state = pyqtSignal(str)  # 화면에 보여줄 상태 한 줄

    def __init__(self, vocabulary: list[str]) -> None:
        super().__init__()
        self.vocabulary = vocabulary
        self._stop = threading.Event()
        self._pending = False
        self._last: dict = {}  # 방금 들은 것. 답이 나오면 같이 기록한다  # 호출어만 듣고 지시를 기다리는 중

    def run(self) -> None:
        try:
            import voice
        except Exception as e:
            self.state.emit(f"음성을 못 켰어: {e}")
            return

        try:
            ears, mouth = voice.Ears(), voice.Mouth()
            talk = voice.Talk()  # 답한 직후엔 호출어 없이 이어 말할 수 있다
            self.mouth = mouth
            # 받아쓰기 모델을 미리 올린다. 안 그러면 첫 마디를 말하는 동안 모델을
            # 올리느라 그 말을 통째로 놓치고, 사용자는 "말해도 반응이 없다"고 본다.
            self.state.emit("귀를 준비하는 중…")
            ears._load()
            self.state.emit(f'듣는 중. "{voice.WAKE} …" 라고 말해봐')
            while not self._stop.is_set():
                t0 = time.monotonic()
                heard = ears.listen(mouth, on_level=self.level.emit,
                                    vocabulary=self.vocabulary)
                listen_took = time.monotonic() - t0
                if self._stop.is_set():
                    continue
                if not heard:
                    continue
                # 무엇을 들었는지 늘 보여준다. 안 깨어났을 때 호출어를 못 알아들은 건지
                # 아예 소리가 안 들어온 건지 구분할 수 있어야 고칠 수 있다.
                self.state.emit(("들음: " + heard) if not ears.clipped
                                else f"들음: {heard}  (소리가 잘려. 마이크를 조금 낮춰줘)")

                if self._pending:
                    order, woke, self._pending = heard, True, False
                else:
                    woke, order = talk.take(heard)
                    if not woke:
                        # 안 깨어난 것도 소리째 남긴다 — 호출어를 왜 못 잡았는지는
                        # 글자만 봐서는 모른다. 원본을 되돌려 봐야 안다.
                        talklog.record(heard=heard, woke=False,
                                       took={"듣기": round(listen_took, 2)},
                                       stt=f"{ears.device}/{ears.model_size}",
                                       audio=talklog.save_audio(ears.last_audio))
                        continue
                    if not order:
                        # 부르기만 했다. 실행하지 않고 기다린다(결정 11).
                        self._pending = True
                        self.state.emit("응, 말해")
                        talklog.record(heard=heard, woke=True, order="",
                                       reply="응", kind="wake",
                                       took={"듣기": round(listen_took, 2)},
                                       stt=f"{ears.device}/{ears.model_size}")
                        mouth.say("응")
                        continue
                self._last = {"heard": heard, "order": order, "woke": woke,
                              "listen": round(listen_took, 2),
                              "spoke_at": ears.spoke_at,
                              "audio": talklog.save_audio(ears.last_audio),
                              "peak": round(ears.last_peak, 3),
                              "clipped": ears.clipped,
                              "stt": f"{ears.device}/{ears.model_size}"}
                talk.opened()  # 답이 나가는 동안에도 이어 말할 수 있게 미리 연다
                self.heard.emit(order)
        except Exception as e:
            # 마이크가 빠지거나 모델이 터져도 화면은 살아 있어야 한다.
            self.state.emit(f"음성이 멈췄어: {e}")

    def stop(self) -> None:
        self._stop.set()



def _쓰기막히면알림(돌려줄=None):
    """글을 쓰는 자리에서 `WriteBlocked` 가 나면 **말로 알린다.**

    ★★ 파일이 읽기 전용이거나 딴 프로그램이 잡고 있으면 쓰기가 막힌다. 저장(`save_note`)만 그걸
    받고, 말로 덧붙이기·고정·이름 바꾸기·새 글·지우기·할 일 켜기는 안 받아서 **아무 말 없이
    안 써졌다**(창은 훅 덕에 안 죽지만 사람은 됐는 줄 안다). 한 자리에서 받는다.
    ※ 안쪽 함수 이름은 **영문**이어야 한다 — PyQt 가 슬롯 이름(`co_name`)을 ASCII 로 바꾸다
      창이 통째로 강제 종료됐다(한글 `속` 이었을 때 재 봤다).
    """
    def wrap(fn):
        # ★ 단추·메뉴 신호는 `checked` 같은 인자를 덧붙여 부른다. 원래 함수가 안 받는 인자는 **떼고** 넘긴다
        #   — 안 그러면 「지우기」 메뉴를 누를 때 TypeError 로 아무 일도 안 일어난다.
        받는수 = None if fn.__code__.co_flags & 0x04 else fn.__code__.co_argcount - 1

        @functools.wraps(fn)
        def guarded(self, *a, **k):
            if 받는수 is not None:
                a = a[:받는수]
            try:
                return fn(self, *a, **k)
            except WriteBlocked:
                self.report("못 썼어 — 그 파일이 읽기 전용이거나 딴 프로그램이 잡고 있어.", [ROOT])
                return 돌려줄
        return guarded
    return wrap


class MainWindow(QWidget):
    def __init__(self, notes: Notes, store: Store, link: ServerLink | None = None) -> None:
        """화면을 짓는다. 짓는 일은 셋으로 나눠 뒀다 — 한 함수에 437줄이면
        무엇이 무엇을 쓰는지 따라갈 수가 없다. 덩어리를 넘나드는 것은
        `left`(그래프 판)·`scroll`·`rescan`(제안 칸) 셋뿐이라 그것만 주고받는다."""
        super().__init__()
        self.notes = notes
        self.store = store
        self.link = link or ServerLink()
        self.skills = SkillStore(notes)
        self.proposal_cards: list[ProposalCard] = []
        self._empty_hint: QLabel | None = None
        self._total_notes = 0
        self._all_links = 0
        self.setWindowTitle("VC")   # 부서는 불칸, 이 프로그램은 VC
        self.resize(1180, 760)
        # ★ **제 상태줄도 못 보여 줄 만큼 작아지면 안 된다.** 창 최소가 1049 에
        # 갇혀 있던 것을 푸니 이제 300 까지 줄어드는데, 거기서는 **아래 띠가 통째로
        # 사라진다** — 그리고 시험하는 쪽 말대로 **「접힌 것」과 「없는 것」을 사람이
        # 구별할 길이 없다.** 400 이면 보이고 300 이면 안 보였다(재 봤다).
        # 여유를 조금 두고 여기서 바닥을 친다.
        self.setMinimumHeight(430)
        # ★ 지난번에 키워 둔 글자 크기를 그대로 되살린다 — 켤 때마다 다시 키워야 하면
        #   있으나 마나다. 값이 없거나 깨졌으면 1.0 이다(설정 한 줄에 창이 안 죽는다).
        try:
            theme.배율바꾸기(float(paths.load_config().get("글자배율", 1.0)))
        except (TypeError, ValueError):
            theme.배율바꾸기(1.0)
        self._apply_style()

        left = self._build_head()
        scroll, rescan = self._build_proposals()
        self._build_body(left, scroll, rescan)

    def _build_head(self) -> QFrame:
        """이름표·검색칸·마이크·그래프. 돌려주는 것은 그래프가 든 판이다 —
        본문 판이 그 위에 뜨므로 뒤에서 필요하다."""
        self.graph = GraphView()
        self.graph.empty_clicked.connect(lambda: self._later(self.clear_detail))
        self.graph.node_clicked.connect(self.show_note)
        # 표식이 가운데에서 밀렸을 때 저절로 돌아오기까지의 시간(설정 → 화면). 0이면 끔.
        self.graph.자동제자리초 = float(settings.되돌리기초())

        wordmark = QLabel("VC")
        wordmark.setStyleSheet(
            f"color:{theme.T.TEXT.name()}; font-family:{theme.SANS}; font-size:{theme.글자(22)};"
            "font-weight:700; letter-spacing:1px;"
        )
        tagline = QLabel("VULCAN  ·  Local-first Ambient AI Workspace")
        # **글자가 긴 이름표는 창을 밀어낸다.** `QLabel` 의 최소 폭은 글 전체가 들어갈
        # 폭이다. 이 한 줄이 473px 를 밀어 창 최소 폭이 1624 가 됐고, 그러면
        # **1366 짜리 노트북에 안 들어간다.** 이름표는 잘려도 되지만 창은 들어가야 한다.
        tagline.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        tagline.setMinimumWidth(0)
        tagline.setStyleSheet(
            theme.small(theme.T.ACCENT, 0.6)
        )
        self.stats = QLabel()
        # 위 띠도 같은 까닭으로 줄어들게 둔다 — 값이 늘 때마다 창이 못 줄어들면 안 된다.
        self.stats.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.stats.setMinimumWidth(0)
        self.stats.setStyleSheet(
            theme.small(theme.T.DIM, 0.4)
        )
        # 엔진 상태. 어떤 모델이 지금 올라와 있는지 화면에서 바로 보이게 한다(결정 36).
        self.engine_label = QLabel()
        self.engine_label.setStyleSheet(
            f"color:{theme.css(theme.T.ACCENT, 0.55)}; font-family:{theme.MONO}; font-size:{theme.글자(10)};")
        engine_timer = QTimer(self)
        engine_timer.timeout.connect(self.refresh_engine)
        engine_timer.start(4000)
        # 폰 길(테일스케일). "모름" = 아직 안 봤다 · None = 꺼짐.
        self._테일: str | None = "모름"
        self._띠경고 = ""
        테일_timer = QTimer(self)
        # ★ lambda 로 감싼다 — PyQt 는 한글 이름 메서드를 바로 이으면 UnicodeEncodeError 로 터진다.
        테일_timer.timeout.connect(lambda: self._테일보기())
        테일_timer.start(30000)
        self._테일보기()

        # 밖에서 고친 것을 받아들인다.
        #
        # 파일이 원본인 설계라 옵시디언·메모장으로도 고칠 수 있다. 그걸 화면이 모르면
        # **두 곳의 내용이 갈라진다** — 여기서 고친 것과 밖에서 고친 것 중 나중에 쓴
        # 쪽이 상대를 조용히 덮는다.
        #
        # 폴더 하나만 감시한다. 파일마다 걸면 항목이 수만 개일 때 손잡이가 모자란다.
        # 윈도우에서는 폴더 감시가 **생성·내용수정·삭제를 다 잡는다**(실측).
        self._watch = QFileSystemWatcher([str(self.notes.root)], self)
        self._watch.directoryChanged.connect(lambda _: self._outside_timer.start(400))
        # 뿌리만 보면 `연/월` 폴더 안에서 고친 것을 놓친다 — 옵시디언으로 고친 글이
        # 화면에 안 나타났다. 20년을 써도 폴더는 240개 남짓이라 다 봐도 싸다.
        self._rewatch()
        # 훑기는 딴 실에서. 끝나면 바뀐 게 있을 때만 다시 그린다.
        self.indexer = Indexer(self.notes)
        self.indexer.done.connect(self._indexed)
        self.indexer.embedder.connect(self.notes.use_embedder)
        self.indexer.meaning.connect(self._meaning_ready)
        self.indexer.started.connect(lambda: setattr(self.graph, "indexing", True))
        # **끝났을 때만** 연출을 깨운다. 한 바퀴 돌 때마다 깨우면, 이어서 도는 두 번째
        # 바퀴가 그리기에 굶어 몇 배로 늘어진다 — 실제로 7초가 45초 넘게 갔다.
        self.indexer.finished.connect(lambda: setattr(self.graph, "indexing", False))
        self._outside_timer = QTimer(self)
        self._outside_timer.setSingleShot(True)
        self._outside_timer.timeout.connect(self.pull_outside)
        # **폴더 감시는 「고쳐짐」을 안 알려 준다.** 파일이 생기고 없어지는 것만
        # 알려 주기 때문에, 옵시디언으로 글 한 줄 고친 것은 신호가 아예 안 온다 —
        # 낯선 PC 에서 40초를 기다려도 안 왔고, 아무 파일이나 새로 생기자 그제야
        # 밀린 것이 한꺼번에 들어왔다. 그래서 틈틈이 직접 물어본다.
        # 훑기는 안 바뀐 파일을 열지 않으므로(mtime 비교) 2만 개라도 싸다.
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(OUTSIDE_POLL_MS)
        self._poll_timer.timeout.connect(self.pull_outside)
        self._poll_timer.start()
        # 우리가 쓴 것도 감시에 걸린다. 방금 우리가 쓴 거면 다시 읽을 필요가 없다.
        self._wrote_at = 0.0

        # ★★ **창만 보는 사람에게도 「지금 열려 있다」를 알린다.**
        #
        # 자국(`vc-기록.log`)과 `--doctor` 에는 적히지만, **오너는 아이콘을 눌러 켜고
        # 창만 본다.** 시험하는 쪽이 「절반만 닫혔다 — 자국을 열어 보거나 --doctor 를
        # 돌린 사람은 알고, 그냥 켜는 사람은 여전히 모른다」고 짚었다. 여기가 나머지
        # 절반이다. **닫혀 있을 때는 아무 말도 안 한다**(아래 띠와 같은 규칙).
        self.열린자리 = QLabel()
        self.열린자리.setStyleSheet(theme.small(theme.T.WARN, 0.8, 10))
        # ★ **왼쪽 세로 칸은 폭이 100px 도 안 된다** — 거기 놓았더니 「★ 원격 열림 :87」로
        #   잘렸다. 잘린 경고는 경고가 아니다. 위 띄의 빈 자리로 옮겼다.
        self.열린자리.hide()

        head_left = QVBoxLayout()
        head_left.setSpacing(3)
        head_left.addWidget(wordmark)
        head_left.addWidget(tagline)
        head_left.addWidget(self.engine_label)

        # 검색·지시가 한 칸이다. 음성 지시도 결국 같은 문(ask)으로 들어온다.
        self.ask_box = QLineEdit()
        # 이름이 없으면 접근성 트리에 검색칸도 제목칸도 「편집」으로만 보인다 — 자동 시험이
        # 초점이 어디인지 못 가린다(시험 쪽 14).
        self.ask_box.setAccessibleName("검색칸")
        # ★★ **아는 길을 안 알려 주면 없는 것과 같다.** 좁히는 문법(`kind:` · `tag:` ·
        #   따옴표)이 있는데 화면 어디에도 안 적혀 있어, 쓰는 사람이 발견할 길이 없었다.
        #   AI 한테는 인사(`hello`)로 알려 주면서 사람한테는 안 알려 준 셈이다.
        #   [잰 것, AI 쪽] 갈래로 좁히면 한 번에 802 → 617자, 찾은 물음 6/20 → 13/20.
        #   빈 칸에만 보이므로 치기 시작하면 사라진다 — 자리를 안 먹는다.
        self.ask_box.setPlaceholderText("찾거나 시키기    kind:결정   tag:이름   \"그대로\"")
        # 돋보기는 그림이 아니라 단추다 — 붙여 놓고 안 이으면 눌러도 아무 일이 없다.
        find_act = self.ask_box.addAction(
            theme.glyph_icon("search", theme.rgba(theme.T.DIM, 110)), QLineEdit.LeadingPosition)
        find_act.triggered.connect(lambda: self.ask(self.ask_box.text()))
        # ★★ **AI 한테 알려 준 길은 사람한테도 알려 준다.** `year:`·`path:`·빼기(`-kind:`)가
        #   되는데 화면에는 `kind:`·`tag:` 만 적혀 있었다 — 되는데 아무도 모르는 길이
        #   오늘만 다섯 번 나왔다. 자체점검이 이 둘을 견준다(`ui_check`).
        self.ask_box.setToolTip(
            "한 번 치면 관련된 것만 남고, 한 번 더 치면 내용을 연다" + chr(10)
            + "좁히기 — kind:결정 · tag:이름 · year:2026 · path:2026/09 · title:이름(=file:)" + chr(10)
            + "빼기 — -kind:일 (잡담이 준다) · -낱말" + chr(10)
            + '"따옴표" 는 그 구절 그대로' + chr(10)
            + "하나라도 — TODO OR FIXME (또는)" + chr(10)
            + "F1 — 단축키 모두 보기")
        self.ask_box.setObjectName("ask")
        self.ask_box.setFixedWidth(240)
        self.ask_box.returnPressed.connect(lambda: self.ask(self.ask_box.text()))

        # 말로 부르기. 글자 대신 동그란 표시 하나 — 무슨 단추인지는 색과 위치가 말한다.
        self.mic_button = QPushButton()
        self.mic_button.setObjectName("mic")
        self.mic_button.setIcon(theme.glyph_icon("mic", theme.rgba(theme.T.DIM, 140)))
        self.mic_button.setToolTip('말로 부른다. "브이씨, …" 라고 말하면 된다')
        self.mic_button.setCursor(Qt.PointingHandCursor)
        self.mic_button.clicked.connect(self.toggle_voice)
        self.voice: VoiceWorker | None = None
        self.mouth: Any = None  # 말로 물으면 말로 답한다. 켤 때 만든다
        self.mic_level = 0.0

        # **항상 보이는 「새 항목」.** 이것 말고 만드는 자리가 항목 카드 안에만 있었는데,
        # 그 카드는 항목을 골라야 뜬다 — 기록이 0개인 첫 실행이면 만들 길이 사라진다.
        self.head_new = QPushButton("＋ 새 항목")
        self.head_new.setObjectName("quiet")
        self.head_new.setToolTip("빈 항목을 만들고 바로 제목부터 친다  (Ctrl+N)")
        self.head_new.setCursor(Qt.PointingHandCursor)
        self.head_new.clicked.connect(self.new_note)

        head = QHBoxLayout()
        head.addLayout(head_left)
        head.addSpacing(16)
        head.addWidget(self.열린자리, 0, Qt.AlignBottom)
        head.addStretch(1)
        head.addWidget(self.head_new, 0, Qt.AlignBottom)
        head.addSpacing(8)
        head.addWidget(self.ask_box, 0, Qt.AlignBottom)
        head.addSpacing(8)
        head.addWidget(self.mic_button, 0, Qt.AlignBottom)
        head.addSpacing(14)
        head.addWidget(self.stats, 0, Qt.AlignBottom)

        # 말하는 자리. 왼쪽 세로선이 강조색이라 VC가 말하는 중임이 바로 읽힌다.
        self.say = QLabel()
        self.say.setWordWrap(True)
        self.say.setObjectName("say")
        self._say_text = "준비됐어. 항목을 누르면 그 얘기를 해줄게."
        self._caret_on = True
        self._paint_say()
        # 깜빡이는 커서. 멈춘 화면이 아니라 듣고 있는 중이라는 표시다.
        caret = QTimer(self)
        caret.timeout.connect(self._blink)
        caret.start(600)

        legend_row = QHBoxLayout()
        legend_row.addWidget(Legend())
        legend_row.addStretch(1)

        graph_box = QVBoxLayout()
        graph_box.setContentsMargins(24, 20, 24, 18)
        graph_box.setSpacing(11)
        graph_box.addLayout(head)
        graph_box.addWidget(theme.Divider())
        graph_box.addWidget(self.graph, 1)
        graph_box.addLayout(legend_row)
        graph_box.addWidget(self.say)
        left = QFrame()
        left.setLayout(graph_box)
        self.left = left

        return left

    def _build_proposals(self):
        """제안 칸. 스크롤과 '다시 훑기' 단추를 돌려준다."""
        # --- 사이드 ---
        self.proposal_box = QVBoxLayout()
        self.proposal_box.setSpacing(8)
        self.proposal_box.addStretch(1)
        holder = QWidget()
        holder.setLayout(self.proposal_box)
        scroll = QScrollArea()
        scroll.setWidget(holder)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        # 카드가 반만 보이면 단추를 못 누른다. 한 장은 통째로 들어갈 높이를 보장한다.
        # 같은 까닭. 카드 한 장이 들어갈 높이는 보장하되, **그보다 더는 창을 안 민다.**
        scroll.setMinimumHeight(PROPOSAL_AREA_MIN_H)
        scroll.setMaximumHeight(PROPOSAL_AREA_MIN_H * 3)
        # 제안이 있고 없고에 따라 이 칸의 최소 높이를 바꾼다().
        self.proposal_scroll = scroll
        # 카드는 세로로만 쌓인다. 가로 막대를 켜두면 빈 상자가 하나 떠 있는 꼴이 된다.
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        rescan = QPushButton()
        rescan.setObjectName("quiet")
        rescan.setIcon(theme.glyph_icon("inspect", theme.rgba(theme.T.DIM, 130), 16))
        rescan.setToolTip("이력을 훑어 고칠 점을 찾는다.\n"
                          "15분마다 저절로 돌고, 지금 당장 보고 싶을 때 누른다.\n"
                          "아무것도 바꾸지 않는다 — 제안만 만든다")
        rescan.setCursor(Qt.PointingHandCursor)
        rescan.clicked.connect(self.run_analyze)


        return scroll, rescan

    def _build_body(self, left: QFrame, scroll, rescan) -> None:
        """본문 판과 오른쪽 줄을 짓고 창에 앉힌다."""
        # --- 항목 칸: 읽기만 하는 게 아니라 여기서 쓰고 고친다 ---
        #
        # 저장 단추는 없다. 치는 대로 저장된다 — 저장을 눌러야 남는 물건은 결국
        # 안 쓰게 된다. 다만 글자 하나마다 파일을 쓰면 색인이 계속 다시 돌아서,
        # 손을 멈춘 뒤 잠깐 기다렸다가 쓴다.
        self.editing: str | None = None   # 지금 열려 있는 항목의 원래 제목
        self.editing_at: str = ""         # 그 항목의 **파일**. 쌍둥이 제목 때문에 꼭 필요하다
        self._meaning_left = -1           # 뜻 벡터를 아직 못 만든 항목 수(-1 = 모름)
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self.save_note)

        self.detail_kind = QComboBox()
        self.detail_kind.setObjectName("pick")
        for key, label in theme.KIND_LABEL.items():
            self.detail_kind.addItem(label, key)
        self.detail_kind.hide()
        self.detail_kind.currentIndexChanged.connect(lambda _: self.save_note())

        self.detail_title = QLineEdit()
        self.detail_title.setAccessibleName("제목칸")
        self.detail_title.setPlaceholderText("항목을 눌러봐")
        self.detail_title.setObjectName("title")
        self.detail_title.setReadOnly(True)
        # 스타일시트만으로는 Qt 기본 테두리가 남는다 — 직접 끈다.
        self.detail_title.setFrame(False)
        self.detail_title.editingFinished.connect(self.rename_note)

        self.detail_body = NoteBody()
        self.detail_body.setObjectName("body")
        self.detail_body.setAcceptRichText(False)  # 붙여넣기가 서식을 끌고 들어오면 안 된다
        self.detail_body.setPlaceholderText("여기에 내용이 나온다.")
        self.detail_body.setReadOnly(True)
        self.detail_body.setMinimumHeight(150)
        self.detail_body.setFrameShape(QFrame.NoFrame)
        self.detail_body.viewport().setAutoFillBackground(False)
        self.detail_body.textChanged.connect(lambda: self._save_timer.start(700))
        self.detail_body.link_clicked.connect(self.follow_link)
        # `[[`를 치면 그 자리에서 제목을 물어본다(미리 들고 있지 않는다).
        self.detail_body.title_source = lambda part: self.notes.titles_like(part, 12)
        self.detail_body.tag_clicked.connect(self.show_tag)
        self.detail_body.image_pasted.connect(self.paste_image)

        # 읽는 모습과 고치는 모습을 갈아 끼운다. 평소엔 서식이 입혀 보이고,
        # 고칠 때만 원문이 뜬다 — 가끔 보고 고치는 용도에 이게 맞는다.
        self.detail_view = NoteView(find_file=self.notes.attachment_path, find_note=self._끼울몸)
        self.detail_view.link_clicked.connect(self.follow_link)
        self.detail_view.tag_clicked.connect(self.show_tag)
        self.detail_view.task_clicked.connect(self.flip_task)
        self.detail_stack = QStackedWidget()
        self.detail_stack.addWidget(self.detail_view)   # 0 = 읽기
        self.detail_stack.addWidget(self.detail_body)   # 1 = 고치기
        self.detail_stack.setMinimumHeight(150)
        # 읽는 글에 숨 쉴 틈. 줄간격 1.0은 20년치를 읽으라고 내놓을 값이 아니다.
        for box in (self.detail_view, self.detail_body):
            box.setStyleSheet("line-height:160%;")
            doc = box.document()
            doc.setDocumentMargin(14)

        self.side_btn = QPushButton("옆에")
        self.side_btn.setObjectName("quiet")
        self.side_btn.setToolTip("이 항목이 가리키는 것을 옆에 띄워 놓고 본다")
        self.side_btn.setCursor(Qt.PointingHandCursor)
        self.side_btn.clicked.connect(self.open_side_here)
        self.side_btn.hide()

        self.back_btn = QPushButton("←")
        self.back_btn.setObjectName("quiet")
        self.back_btn.setToolTip("앞서 보던 항목으로 (Alt+←)")
        self.back_btn.setCursor(Qt.PointingHandCursor)
        self.back_btn.clicked.connect(self.go_back)
        self.fwd_btn = QPushButton("→")
        self.fwd_btn.setObjectName("quiet")
        self.fwd_btn.setToolTip("다시 앞으로 (Alt+→)")
        self.fwd_btn.setCursor(Qt.PointingHandCursor)
        self.fwd_btn.clicked.connect(self.go_forward)

        # **눈에 보이는 닫는 길이 있어야 한다.** Esc 는 있었지만 아는 사람만 쓴다 —
        # 낯선 PC 실사용에서 「카드를 한 장 열면 닫을 길이 없다. 프로그램을 다시 켜는
        # 것 말고 그래프로 돌아갈 길을 못 찾았다」로 걸렸다. 그것 때문에 그날 재려던
        # 것 하나를 통째로 못 쟀다.
        self.shut_btn = QPushButton("닫기")
        self.shut_btn.setObjectName("quiet")
        self.shut_btn.setToolTip("이 항목을 닫고 그래프로 돌아간다  (Esc)")
        self.shut_btn.setCursor(Qt.PointingHandCursor)
        self.shut_btn.clicked.connect(self.clear_detail)
        self.shut_btn.hide()

        self.edit_btn = QPushButton("고치기")
        self.edit_btn.setObjectName("quiet")
        self.edit_btn.setToolTip("원문을 열어 고친다. 다시 누르면 입힌 모습으로 돌아온다")
        self.edit_btn.setCursor(Qt.PointingHandCursor)
        self.edit_btn.clicked.connect(self.toggle_edit)
        self.edit_btn.hide()

        # 「새 항목」·「지우기」 단추는 머리줄과 `⋯` 메뉴로 옮겼다. 여기에 만들어
        # 두던 위젯은 **어느 칸에도 안 들어가 있었다** — 부모 없는 위젯을 `show()`
        # 하면 그게 그대로 **독립 창**이 된다. 낯선 PC 에서 「지우기」만 든 136x62
        # 조각 창으로 보였고, 주 창을 닫아도 그것 때문에 프로세스가 안 죽었다.
        # 목차. 18만 자짜리 기록에서 원하는 자리로 갈 길이 스크롤뿐이면 안 열게 된다.
        self.toc = QComboBox()
        self.toc.setObjectName("pick")
        self.toc.setToolTip("소제목으로 바로 간다")
        # 남는 폭을 다 먹지 않게 묶는다. 판이 둘로 갈리면 이것들이 늘어나 옆 단추가 잘렸다.
        self.toc.setMinimumWidth(88)
        self.toc.setMaximumWidth(132)
        self.toc.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.toc.hide()
        self.toc.activated.connect(self._jump_heading)

        detail_tools = QHBoxLayout()
        detail_tools.setContentsMargins(0, 0, 0, 0)
        # 지난 판. AI가 대부분을 쓰는 구조라 **어제 것으로 돌아갈 길**이 있어야 한다.
        self.past = QComboBox()
        self.past.setObjectName("pick")
        self.past.setToolTip("지난 판으로 되돌린다")
        self.past.setMinimumWidth(84)
        self.past.setMaximumWidth(124)
        self.past.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.past.hide()
        self.past.activated.connect(self._restore_past)

        detail_tools.addWidget(self.back_btn)
        detail_tools.addWidget(self.fwd_btn)
        detail_tools.addWidget(self.detail_kind)
        detail_tools.addWidget(self.toc)
        detail_tools.addWidget(self.past)
        detail_tools.addStretch(1)
        detail_tools.addWidget(self.side_btn)
        detail_tools.addWidget(self.edit_btn)
        # 자주 안 쓰는 것은 안으로. 판이 둘로 갈리면 폭이 절반이라 단추 열 개가
        # 겹쳐 글자가 잘렸다.
        self.more_btn = QToolButton()
        self.more_btn.setObjectName("quiet")
        self.more_btn.setText("⋯")
        self.more_btn.setToolTip("새 항목 · 서식 · 지우기")
        self.more_btn.setCursor(Qt.PointingHandCursor)
        self.more_btn.setPopupMode(QToolButton.InstantPopup)
        self.more_menu = QMenu(self.more_btn)
        self.more_btn.setMenu(self.more_menu)
        self.more_menu.aboutToShow.connect(self._build_more)
        detail_tools.addWidget(self.more_btn)
        detail_tools.addWidget(self.shut_btn)
        self.years = Years()
        # **목록 단추들은 자기 신호 안에서 자기를 다시 짓는다.** 누르면 목록이
        # 새로 그려지면서 방금 누른 단추가 지워지고, Qt 는 제 밑이 파여 죽는다.
        # 신호를 받는 자리에서 곧장 미룬다 — 한 곳에서 막아야 새로 잇는 것도 안전하다.
        self.years.picked.connect(lambda y: self._later(lambda: self.show_year(y)))

        self.results = Results()
        self.results.picked.connect(lambda t: self._later(lambda: self.show_note(t)))
        self.results.picked_at.connect(lambda w: self._later(lambda: self.show_note_at(w)))
        self.results_head = theme.section("찾은 것", "검색·태그로 걸린 항목. 눌러서 연다")
        self.results_head.hide()
        self.results.hide()

        self.gaps = Gaps()
        self.gaps.picked.connect(lambda n: self._later(lambda: self.fill_gap(n)))

        # 같은 제목이 둘 이상일 때만 뜬다. 어느 파일을 열었는지 밝히는 줄.
        self.twin_note = QLabel()
        self.twin_note.setWordWrap(True)
        self.twin_note.setStyleSheet(theme.small(theme.T.WARN, 0.85, 10))
        self.twin_note.hide()

        self.detail_links = QLabel()
        self.detail_links.setWordWrap(True)
        self.detail_links.setTextFormat(Qt.RichText)
        # 밖으로 나가는 주소가 아니라 우리끼리 쓰는 이름표다. 브라우저를 열면 안 된다.
        self.detail_links.setOpenExternalLinks(False)
        self.detail_links.linkActivated.connect(self._link_row_clicked)
        self.detail_links.setStyleSheet(
            theme.small(theme.T.ACCENT, 0.5)
        )

        # 끼워 넣은 것. 본문 칸은 고칠 수 있어야 하므로 원문(![[…]])을 그대로 두고,
        # 그 내용은 아래에 따로 펼친다 — 옵시디언도 편집 모드에서는 원문을 보여준다.
        self.embeds_head = QLabel("끼워 넣은 것")
        self.embeds_head.setStyleSheet(
            f"color:{theme.css(theme.T.ACCENT, 0.5)}; font-family:{theme.MONO};"
            f"font-size:{theme.글자(10)}; letter-spacing:1px; padding-top:4px;")
        self.embeds_head.hide()
        self.embeds = Results(limit=3)
        self.embeds.picked.connect(self.show_note)
        self.embeds.hide()

        # 누가 나를 가리키나. 나가는 링크(내가 적은 것)와 섞으면 구분이 안 된다.
        self.backs_head = QLabel("가리킨 곳")
        self.backs_head.setStyleSheet(
            f"color:{theme.css(theme.T.ACCENT, 0.5)}; font-family:{theme.MONO};"
            f"font-size:{theme.글자(10)}; letter-spacing:1px; padding-top:4px;")
        self.backs_head.hide()
        self.backs = Results(limit=4)
        self.backs.picked.connect(self.show_note)
        self.backs.hide()
        # 이름은 적었는데 링크로 안 이은 곳 — 옵시디언의 「연결 안 된 언급」. 이어짐을 적고 싶을 때 쓰는 재료다.
        self.mentions_head = QLabel("이름만 적힌 곳 (안 이어짐)")
        self.mentions_head.setStyleSheet(self.backs_head.styleSheet())
        self.mentions_head.hide()
        self.mentions = Results(limit=4)
        self.mentions.picked.connect(self.show_note)
        self.mentions.hide()

        detail_card = self.detail_card = HudPanel(left)  # 그래프 위에 뜨는 본문 판
        detail_card.setObjectName("reader")

        # 옆에 띄우는 읽기 전용 판. 딴 글을 곁에 두고 보면서 쓴다.
        self.side_read = SideReader(left, find_file=self.notes.attachment_path, find_note=self._끼울몸)
        self.side_read.link_clicked.connect(self.follow_link)   # follow_link 가 이미 미룬다
        self.side_read.closed.connect(self.close_side)

        # 열어 본 차례. **앞의 것이 닫히는 게 아니라 되돌아갈 수 있어야 한다.**
        self._trail: list[str] = []
        self._trail_at = -1
        # 옆 판을 열어 뒀는지. **`isVisible()`로 판단하지 않는다** — 창이 아직 안 떴을
        # 때도 자리는 잡혀 있어야 한다.
        self.side_open = False
        detail_card.hide()   # 항목을 열 때만 뜬다
        dbox = QVBoxLayout(detail_card)
        dbox.setContentsMargins(26, 20, 26, 18)
        dbox.setSpacing(8)
        dbox.addLayout(detail_tools)
        dbox.addWidget(self.detail_title)
        dbox.addWidget(self.twin_note)
        dbox.addWidget(self.detail_stack, 1)
        dbox.addWidget(self.detail_links)
        dbox.addWidget(self.embeds_head)
        dbox.addWidget(self.embeds)
        dbox.addWidget(self.backs_head)
        dbox.addWidget(self.backs)
        dbox.addWidget(self.mentions_head)
        dbox.addWidget(self.mentions)

        self.footer = QLabel()
        self.footer.setStyleSheet(
            theme.small(theme.T.DIM, 0.3, 9)
        )
        # ★ **글자가 긴 이름표는 창을 밀어낸다.** `QLabel` 의 최소 폭은 글 전체가
        # 들어갈 폭이라, 아래 띠에 값을 하나 더할 때마다 **창이 그만큼 못 줄어든다.**
        # 여기 하나가 473px 를 밀고 있었고 창 최소 폭이 1624 가 됐다 —
        # 1366 짜리 노트북에는 안 들어간다. **아래 띠는 잘려도 되지만 창은 들어가야 한다.**
        self.footer.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.footer.setMinimumWidth(0)
        # 세는 값(적은 것 · 보임 · 연결)은 늘 볼 것이 아니다 — 「상태·기록」을 펴야 보인다(결정 17).
        self.상태글 = QLabel()
        self.상태글.setStyleSheet(theme.small(theme.T.DIM, 0.3, 9))
        self.상태글.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.상태글.setMinimumWidth(0)

        self.feed = ActivityFeed()
        # 쓸 모델을 고르는 칸. 사양이 다른 PC에서도 각자 맞게 쓴다(결정 42).
        self.models = ModelPicker(self.link, lambda t: self.report(t, [ROOT]))
        # 뜻 모델을 바꾸면 훑는 실이 새 모델로 벡터를 다시 만든다 — 안 이으면
        # 고르는 칸만 있고 **아무 일도 안 일어난다**(그 칸을 낸 날 바로 드러났다).
        self.models.meaning_changed.connect(lambda 자리: self.indexer.뜻모델바꿈(자리))

        # 외부 PC가 붙으려 할 때만 뜬다. 폰이 없거나 안 들고 있을 때 여기서 승인한다.
        self.gate_card = RemoteGateCard(self.link, lambda t: self.report(t, [ROOT]))
        self.gate_card.hide()

        # 매일 보는 것은 펴 두고, 가끔 쓰는 것은 접는다. 예전엔 여섯 칸이 다 펴진 채
        # 세로로 쌓여 **창 최소 높이가 1375px**이었다 — 1080p 화면에 안 들어갔다.
        prop_box = QWidget()
        prop_lay = QVBoxLayout(prop_box)
        prop_lay.setContentsMargins(0, 0, 0, 0)
        prop_lay.setSpacing(6)
        prop_lay.addWidget(rescan, 0, Qt.AlignRight)
        prop_lay.addWidget(scroll)
        self.proposals_fold = Folded("제안", "VC가 스스로 찾은 고칠 점. 승인해야 반영된다", prop_box)
        self.feed_fold = Folded("활동", "방금 한 일. 제안의 근거가 여기 쌓인다", self.feed)
        self.models_fold = Folded("모델", "이 PC 사양에 맞게 자동. 직접 골라도 된다", self.models)

        side = QVBoxLayout()
        side.setContentsMargins(18, 20, 18, 16)
        side.setSpacing(9)
        side.addWidget(self.gate_card)
        side.addWidget(self.results_head)
        side.addWidget(self.results)
        side.addWidget(theme.section("아직 없는 것", "가리키는 링크는 있는데 항목이 없다. 눌러서 만든다"))
        side.addWidget(self.gaps)
        side.addWidget(theme.Divider())
        side.addWidget(theme.section("언제", "해마다 적은 것. 눌러서 그해를 훑는다"))
        side.addWidget(self.years)
        side.addWidget(theme.Divider())
        side.addWidget(self.proposals_fold)
        side.addWidget(self.feed_fold)
        side.addWidget(self.models_fold)
        self.status_fold = Folded("상태·기록", "센 값 — 적은 것 · 보임 · 연결", self.상태글)
        side.addWidget(self.status_fold)
        side.addStretch(1)
        side.addWidget(self.footer)

        side_inner = QWidget()
        side_inner.setLayout(side)
        # **통째로 스크롤 된다.** 칸이 늘어도 창이 화면 밖으로 자라지 않는다.
        side_scroll = QScrollArea()
        side_scroll.setWidget(side_inner)
        side_scroll.setWidgetResizable(True)
        side_scroll.setFrameShape(QFrame.NoFrame)
        side_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # ★ **굴림칸은 굴러야지 창을 밀면 안 된다.** `setWidgetResizable(True)` 면
        # Qt 가 **속 위젯의 최소 높이를 굴림칸의 최소 높이로 삼는다.** 그래서 칸이
        # 길어질수록 창이 못 줄어들었다 — 낯선 PC 에서 창 최소 높이가 **1049** 가 돼
        # 1920x1080 화면에서 작업표시줄에 상태줄이 가렸다(쓸 자리는 1032 다).
        # 여기서 재 보니 못을 박는 것만으로 창 최소가 **636 → 300** 으로 내려간다.
        side_scroll.setMinimumHeight(160)

        side_frame = QFrame()
        side_frame.setObjectName("panel")
        wrap = QVBoxLayout(side_frame)
        wrap.setContentsMargins(0, 0, 0, 0)
        wrap.addWidget(side_scroll)
        side_frame.setFixedWidth(348)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(left, 1)
        outer.addWidget(side_frame)

        # ★★ **뜰 때는 빈 채로 뜬다. 항목은 뜬 뒤에 붙인다.**
        #
        # Qt 는 **창이 뜨는 순간 한 번** 레이아웃이 내놓은 최소를 창에 박는다.
        # 여기서 곧바로 채우면 그 순간 항목이 다 올라와 있어 최소가 크게 잡히고,
        # **그 뒤로는 무엇을 해도 안 풀린다** — 크기를 흔들어도, 레이아웃을 속까지
        # 무르게 해도, `setMinimumSize(0, 0)` 을 여러 번 불러도 안 됐다.
        #
        # 시험하는 쪽이 갈라 준 값이 이걸 못 박았다:
        #
        #     색인 있는 채로 뜸            → 1049 에 갇힌다 (화면 쓸 자리는 1032)
        #     색인 없이 떠서 나중에 채움    → 318. **718개가 다 들어와도 안 커진다**
        #
        # 같은 폴더·같은 파일·같은 판인데 **뜨는 순간에 항목이 있었는지**만으로 갈렸다.
        # 그러니 **모두가 「색인 없이 뜬 사람」의 길을 걷게 한다.**
        #
        # 이건 **오래 쓴 사람에게만 나던 결함**이다 — 갓 깐 사람은 0개로 뜨니 멀쩡하고,
        # 며칠 쓴 사람만 창이 커진 채 갇힌다. 신고가 와도 재현이 잘 안 될 자리다.
        #
        # **다만 「뜨는 일」과 「기록을 손보는 일」은 갈라 둔다.** 가운데 항목을
        # 만들거나 옛 이름을 옮기는 것은 화면과 상관없이 **지금 해야 한다** —
        # 미뤘더니 검사가 「안 옮겨졌다」로 걸렸다. 미룰 것은 그리는 것뿐이다.
        self.ensure_root()
        # 하다 만 이름 바꾸기가 있으면 켤 때 알린다 — 남아 있다는 것은 여러 파일 중
        # 일부만 고쳐졌다는 뜻이라 그물이 반쯤 끊겨 있다.
        if (하다만 := self.notes.이름바꾸다만것()):
            QTimer.singleShot(600, lambda: self.report(
                f"이름 바꾸기를 하다 말았어 — 「{하다만[0]}」 → 「{하다만[1]}」. "
                "가리키던 링크가 반쯤 고쳐졌을 수 있어. 다시 바꿔 주면 마저 고칠게.",
                [ROOT]))
        QTimer.singleShot(0, self.refresh)
        # 서버에 거는 첫 전화는 창이 뜬 **뒤로** 미룬다. 꺼져 있으면 연결을 기다리는
        # 동안 창이 통째로 굳는다 — 켤 때 제일 먼저 보이는 게 굳은 창이면 안 된다.
        self._bind_keys()
        QTimer.singleShot(0, self._greet_server)
        # ★★ **기록자리.txt 를 못 따라 기본 자리로 켰으면 창에서 바로 말한다.** 안 그러면 빈 기록을
        #   보고 「다 사라졌다」고 느낀다(빠진 외장·오타).
        if 쪽지문제 := paths.적어둔자리문제():
            QTimer.singleShot(0, lambda: self.report("★ " + 쪽지문제, [ROOT]))

    def _apply_style(self) -> None:
        # 선택자 없는 속성과 선택자 규칙을 한 문자열에 섞으면 뒤쪽이 통째로 무시된다.
        self.setStyleSheet(f"""
            QWidget {{ background: {theme.T.BG.name()}; color: {theme.T.TEXT.name()};
                       font-family: {theme.SANS}; font-size:{theme.글자(12)}; }}
            QLabel {{ background: transparent; }}
            QFrame#panel {{ background: {theme.T.PANEL.name()};
                            border-left: 1px solid {theme.css(theme.T.ACCENT, 0.12)}; }}
            QFrame#hud {{ background: {theme.css(theme.T.ACCENT, 0.03)};
                          border: 1px solid {theme.css(theme.T.ACCENT, 0.12)}; border-radius: 6px; }}
            QLabel#say {{ color: {theme.T.TEXT.name()}; font-size:{theme.글자(14)}; padding: 12px 16px;
                          background: {theme.css(theme.T.ACCENT, 0.05)};
                          border-left: 2px solid {theme.T.ACCENT.name()}; border-radius: 3px; }}
            QLabel#chip {{ color: {theme.T.ACCENT.name()}; background: {theme.css(theme.T.ACCENT, 0.1)};
                           border: 1px solid {theme.css(theme.T.ACCENT, 0.3)}; border-radius: 3px;
                           padding: 2px 8px; font-family: {theme.MONO}; font-size:{theme.글자(9)};
                           font-weight: 600; letter-spacing: 1px; }}
            QPushButton {{ background: transparent; color: {theme.css(theme.T.DIM, 0.6)};
                           border: 1px solid {theme.css(theme.T.DIM, 0.2)}; border-radius: 3px;
                           padding: 5px 12px; font-family: {theme.MONO}; font-size:{theme.글자(10)};
                           letter-spacing: 1px; }}
            QPushButton:hover {{ color: {theme.T.TEXT.name()}; border-color: {theme.css(theme.T.ACCENT, 0.5)}; }}
            QPushButton#primary {{ color: {theme.T.ACCENT.name()};
                                   border-color: {theme.css(theme.T.ACCENT, 0.4)};
                                   background: {theme.css(theme.T.ACCENT, 0.08)}; }}
            QPushButton#primary:hover {{ background: {theme.css(theme.T.ACCENT, 0.18)}; }}
            /* 곁다리 동작은 테두리를 뺀다. 단추가 여럿이면 뭘 눌러야 할지 헷갈린다. */
            QPushButton#quiet {{ border: none; background: transparent;
                                 color: {theme.css(theme.T.DIM, 0.45)}; padding: 5px 8px; }}
            QPushButton#quiet:hover {{ color: {theme.T.TEXT.name()}; }}
            QPushButton#mic {{ border: 1px solid {theme.css(theme.T.DIM, 0.25)}; border-radius: 4px;
                               color: {theme.css(theme.T.DIM, 0.6)}; padding: 6px 9px; }}
            QPushButton#mic:hover {{ border-color: {theme.css(theme.T.ACCENT, 0.6)};
                                     color: {theme.T.ACCENT.name()}; }}
            QPushButton#mic[listening="true"] {{ border-color: {theme.T.ACCENT.name()};
                                                 color: {theme.T.ACCENT.name()};
                                                 background: {theme.css(theme.T.ACCENT, 0.12)}; }}
            QLineEdit#ask {{ background: {theme.css(theme.T.ACCENT, 0.04)};
                             border: 1px solid {theme.css(theme.T.ACCENT, 0.2)}; border-radius: 3px;
                             padding: 5px 10px; color: {theme.T.TEXT.name()}; font-size:{theme.글자(12)}; }}
            QLineEdit#ask:focus {{ border-color: {theme.css(theme.T.ACCENT, 0.6)};
                                   background: {theme.css(theme.T.ACCENT, 0.08)}; }}
            QComboBox#pick {{ background: {theme.css(theme.T.ACCENT, 0.05)};
                              border: 1px solid {theme.css(theme.T.ACCENT, 0.18)}; border-radius: 3px;
                              padding: 3px 8px; color: {theme.css(theme.T.DIM, 0.75)}; font-size:{theme.글자(11)}; }}
            QComboBox#pick:hover {{ border-color: {theme.css(theme.T.ACCENT, 0.5)}; }}
            QComboBox#pick QAbstractItemView {{ background: {theme.T.PANEL.name()};
                                                color: {theme.T.TEXT.name()};
                                                selection-background-color: {theme.css(theme.T.ACCENT, 0.25)}; }}
            /* `[[` 목록. 콤보 펼침 목록은 입혀 놨는데 여기만 흰 바탕·파란 막대로
               남아, 검은 화면에서 이것만 튀었다. 같은 옷을 입힌다. */
            QListView#link_pop {{ background: {theme.T.PANEL.name()};
                                  color: {theme.T.TEXT.name()};
                                  border: 1px solid {theme.css(theme.T.ACCENT, 0.22)};
                                  outline: none; padding: 2px;
                                  selection-background-color: {theme.css(theme.T.ACCENT, 0.25)};
                                  selection-color: {theme.T.TEXT.name()}; }}
            QListView#link_pop::item {{ padding: 3px 8px; }}
            /* 확인창. 시스템 회색 상자 그대로면 말투만 우리 것이고 모습은 윈도우다. */
            QMessageBox {{ background: {theme.T.PANEL.name()}; }}
            QMessageBox QLabel {{ color: {theme.T.TEXT.name()}; font-size:{theme.글자(12)}; }}
            QMessageBox QPushButton {{ background: {theme.css(theme.T.ACCENT, 0.05)};
                                       border: 1px solid {theme.css(theme.T.ACCENT, 0.22)};
                                       border-radius: 3px; padding: 5px 16px;
                                       color: {theme.css(theme.T.DIM, 0.85)}; font-size:{theme.글자(11)}; }}
            QMessageBox QPushButton:hover {{ border-color: {theme.css(theme.T.ACCENT, 0.6)};
                                             color: {theme.T.TEXT.name()}; }}
            QScrollArea {{ background: transparent; }}
            QScrollBar:vertical {{ background: transparent; width: 5px; margin: 0; }}
            QScrollBar::handle:vertical {{ background: {theme.css(theme.T.ACCENT, 0.25)}; border-radius: 2px; }}
            QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
        """)

    # --- 데이터 ---------------------------------------------------------

    def _뿌리파일있나(self) -> bool:
        """시작 항목이 **파일로** 이미 있나. 색인이 아니라 파일을 본다.

        ★ 색인만 보고 만들었더니 **색인이 없어질 때마다 시작 항목이 하나씩 늘었다.**
        시험하는 쪽이 잡았다 — 색인을 지우고 띄우니 8월 폴더에 `VC.md` 가 있는데도
        9월 폴더에 `VC.md` 를 새로 만들었고, 같은 제목 둘이 되어 ⚠ 가 떴다.
        내용은 글자 하나까지 같았다.

        사람에게도 나는 자리다 — **색인이 깨지거나, 자리를 옮기거나, 기록만
        백업했다 되살릴 때.** 그때마다 「VC」가 하나씩 는다.

        색인은 언제든 다시 만들 수 있는 것이고 **파일이 원본이다.** 그러니
        「있나 없나」는 원본에 물어야 한다. 뿌리가 없을 때만 도는 길이라 값도 싸다.
        """
        try:
            for 파일 in self.notes.notes_files():
                if 파일.stem == ROOT:
                    return True
        except OSError:
            pass          # 못 훑으면 없는 것으로 친다. 하나 더 만드는 편이 낫다
        return False

    def ensure_root(self) -> None:
        """빈 화면에 VC 항목 하나. 여기서부터 자란다.

        옛 이름(이비)으로 쌓아 둔 기록이 있으면 한 번 옮긴다 — 이름만 바꾸고 기록을
        두고 가면, 쓰던 사람의 그래프에서 가운데가 통째로 끊긴다.
        """
        # 새 이름이 이미 있으면 rename이 스스로 거절한다 — 덮어써서 기록을 잃느니
        # 옛 항목을 그대로 남기는 편이 낫다.
        if self.notes.read(OLD_ROOT) is not None:
            self._wrote_at = time.monotonic()
            self.notes.rename(OLD_ROOT, ROOT)
        if self.notes.read(ROOT) is None and not self._뿌리파일있나():
            # 우리가 만든 것이다. 감시가 이걸 "밖에서 바뀜"으로 보고 훑기를 또 돌리면
            # 켤 때마다 훑기를 두 번 한다.
            self._wrote_at = time.monotonic()
            # ★★ **이건 프로그램이 만든 글이다. 그렇다고 적어 둔다.**
            # 안 적었더니 「사람이 손댄 기록」 막이가 이 씨앗을 사람 글로 보고
            # **새 창고의 첫 흡수를 통째로 막았다** — 창을 한 번 켠 것이 죄가 됐다.
            # 사람이 나중에 이 글을 고치면 `edited_by: "사람"` 이 붙어 그때는 지켜진다.
            self.notes.write(Note(
                title=ROOT,
                body="여기서 시작한다. 쓸수록 항목이 늘고 서로 이어진다.",
                kind="agent",
                pinned=True,
                extra={"지은이": "씨앗"},
            ))

    def refresh(self, scan: bool = True) -> None:
        """화면을 다시 그린다.

        `scan=True`면 폴더를 훑어 밖에서 바뀐 것을 잡는다. 그 훑기는 **딴 실에서**
        돈다 — 항목이 쌓이면 훑는 데만 몇 초가 걸려서, 화면 실에서 하면 창이 굳는다.
        """
        self.ensure_root()
        if scan:
            self.indexer.ask()
        # 20년치를 다 그리면 창이 굳는다 — 물리 계산이 항목 수에 비례한다.
        # 고정한 것·최근 본 것부터 채우고, 지금 보고 있는 것은 반드시 남긴다.
        self._total_notes = self.notes.conn.execute(
            "SELECT count(*) AS n FROM notes").fetchone()["n"]
        # 기록 전체에서 사람이 이은 수. 화면에 올라온 것끼리만 세는 값과 나란히 적어
        # **「화면에 안 보이는 것」과 「아예 없는 것」이 갈리게 한다.**
        self._all_links = self.notes.conn.execute(
            "SELECT count(*) AS n FROM links").fetchone()["n"]
        must = {ROOT} | set(self.graph.focus) | ({self.editing} if self.editing else set())
        picked = self.notes.working_set(GRAPH_LIMIT, keep=must)
        # **고른 것의 종류만** 가져온다. 2만 행을 통째로 끌어오면 그것만 0.1초다.
        self.graph.load(self.notes.subgraph(picked), self.notes.kinds_of(picked),
                        self.notes.kin(picked))
        self.load_proposals()


        # 세는 것도 질의 하나로. 행을 다 끌어와 파이썬에서 세면 20년치에서 값이 든다.
        modules = self.notes.conn.execute(
            "SELECT count(*) AS n FROM notes WHERE kind = 'skill'").fetchone()["n"]
        self.stats.setText(
            f"항목 {self._total_notes:02d}   ·   모듈 {modules:02d}   ·   "
            f"제안 {len(self.proposal_cards):02d}"
        )
        self.years.show_years(self.notes.by_year())
        self.gaps.show_gaps(self.notes.unresolved())
        self.feed.show_rows(self.store.recent(9))
        # 일부만 보이면 **보인다고 말한다.** 잘라 놓고 다 보여주는 척하면 안 된다.
        shown = len(self.graph.nodes)
        seen = (f"보임 {shown}/{self._total_notes}"
                if shown < self._total_notes else f"항목 {self._total_notes}")
        # 같은 제목이 두 폴더에 있으면 **어느 쪽을 여는지 우리가 고른다** — 사용자가
        # 2027년 회의를 열었다고 믿고 2026년 것을 고칠 수 있다. 조용히 두면 안 된다.
        dup = self.notes.duplicates()
        if dup:
            # ★ **사람이 알고 싶은 것은 「지울 것이 몇 개인가」다.**
            # 앞서는 `len(dup)`, 곧 **겹친 제목의 가짓수**를 찍었다 — 파일이 둘인데
            # 「1개」로 나왔다. 「제목이 하나 있다」로도 「하나가 겹친다」로도 읽히고,
            # 사람이 「1개」를 보고 파일 하나만 지우면 될 줄 안다. 우연히 맞지만
            # **뜻이 어긋난다.** `duplicates()` 는 (제목, 그 제목의 파일 수)를 준다.
            # **남는 하나를 뺀 나머지**, 곧 손이 갈 수를 적는다.
            군더더기 = sum(n - 1 for _, n in dup)
            이름 = dup[0][0] if len(dup) == 1 else f"{dup[0][0]} 등"
            warn = f"⚠ 이름이 겹친다 — {이름}, 지울 것 {군더더기}개  /  "
        elif self._meaning_left > 0:
            # 뜻 벡터를 만드는 중이라고 말해 준다. 2만 개면 50분짜리 일이라
            # **말없이 돌면 뭐가 잘못된 줄 안다.**
            warn = f"뜻 익히는 중 {self._meaning_left}개 남음  /  "
        else:
            # ★ **아무 일 없을 때는 아무 말도 안 한다.** 「시스템 정상」은 자리만
            # 차지하고 아무것도 안 알린다 — 좁은 창에서는 그것 때문에 **정작 읽어야 할
            # 값이 잘렸다.** 이상할 때만 말하면 그 말이 눈에 띈다.
            warn = ""
        # **무엇을 센 값인지 밝힌다.** 이 수는 화면에 올라온 것들 사이의 선만 센다.
        # 그냥 「연결 75」로 두었더니 `--이음선` 이 뽑아 준 125 와 안 맞아 헷갈렸다 —
        # 둘이 다른 것을 세는데 이름이 같으면 사람이 못 가린다.
        # ★ **같은 낱말이 두 자리에서 다른 수를 내면 사람이 못 읽는다.**
        # 진단 묶음의 「연결 수」는 기록 전체를 세고, 여기 「적은 것」은 **화면에
        # 올라온 것들 사이**만 센다. 그래서 8 대 4, 2 대 0 처럼 갈렸고,
        # 화면만 본 사람은 **「내가 적은 것이 안 세어졌다」**로 읽었다.
        # 이제 **둘을 나란히 적는다** — 「적은 것 0/2」면 「전체엔 둘 있는데 지금
        # 화면에는 안 보인다」로 읽힌다.
        굳은 = len(self.graph.edges) - len(self.graph.soft)
        모두 = self._all_links
        선 = (f"연결 {len(self.graph.edges)} (보이는 것끼리)"
              if shown < self._total_notes else
              f"연결 {len(self.graph.edges)}")
        # ★ **좁아지면 뒤엣것부터 잘린다. 그러니 값진 것을 앞에 둔다.**
        # 앞서는 「보임 → 연결 → 적은 것」 차례라 **사람이 손으로 이은 수가 제일 먼저
        # 사라졌다.** 시험하는 쪽이 짚었다 — 셋 중 그것만이 **사람이 적은 것**이고,
        # 나머지 둘은 프로그램이 센 것이다. 「보임 400/718」은 창을 보면 대충 알지만
        # **「적은 것 0/2」는 다른 데서 볼 길이 없다.**
        # ★ **경고를 맨 앞에 둔다.** 뒤엣것부터 잘리는데 경고가 끝에 있어서,
        # 좁은 창에서 **「⚠」만 남고 무엇이 이상한지는 잘려 나갔다.** 시험하는 쪽이
        # 「⚠ 를 띄웠으면 무엇이 이상한지 볼 길이 하나는 있어야 한다」고 짚었는데,
        # 길은 이미 있었고 **그 길이 잘리고 있었던 것**이다.
        # 값진 것을 앞에 두는 규칙을 아래 띠 가운데에만 쓰고 경고에는 안 썼다.
        self.상태글.setText(f"적은 것 {굳은}/{모두}  /  {seen}  /  {선}")
        # ★ 늘 보이는 한 줄(결정 17)에는 오류 · 준비 중 · 폰 길만 둔다. 센 값은 「상태·기록」을 펴야 보인다.
        self._띠경고 = warn.removesuffix("  /  ")
        self._그리띠()

    # --- 말로 부르기 -----------------------------------------------------

    def _set_mic(self, listening: bool) -> None:
        """색과 이름을 함께 바꾼다. 색은 빨리 읽히고 이름은 확실하다 — 둘 다 쓴다."""
        self.mic_button.setProperty("listening", "true" if listening else "false")
        self.mic_button.setToolTip("듣는 중. 다시 누르면 끈다"
                                   if listening else '말로 부른다. "브이씨, …" 라고 말하면 된다')
        self.mic_button.setIcon(theme.glyph_icon("mic", theme.T.ACCENT if listening else theme.rgba(theme.T.DIM, 140)))
        self.mic_button.style().unpolish(self.mic_button)
        self.mic_button.style().polish(self.mic_button)
        self._light_mark()

    def _light_mark(self, speaking: bool = False) -> None:
        """표식의 상태를 맞춘다 — 쉴 때·들을 때·말할 때.

        소리를 못 듣는 상황에서도 지금 무엇을 하는 중인지 화면만 보고 알아야 한다.
        """
        if speaking:
            state = "speaking"
        elif self.voice is not None:
            state = "listening"
        else:
            state = "idle"
        self.graph.mark.set_state(state)

    def toggle_voice(self) -> None:
        if self.voice is not None:
            self.voice.stop()
            self.voice = None
            self._set_mic(False)
            self.mic_level = 0.0
            self.report("키보드로 돌아왔어.", [ROOT])
            return

        # 아는 낱말을 넘겨준다. 실측에서 이게 결정적이었다 — "볼륨"이 "울렴"으로
        # 흘리던 게 어휘를 일러주자 대부분 제대로 잡혔다. **한글만** 넘긴다:
        # 영어 모듈 이름을 넣으면 받아쓰기 결과에 "volume"이 그대로 튀어나온다.
        vocab = [n.title for n in self.graph.nodes.values()]
        out = self.link.call("GET", "/eb/v1/triggers")
        vocab += (out or {}).get("triggers", [])
        vocab = [w for w in dict.fromkeys(vocab) if re.search(r"[가-힣]", w)]
        if self.mouth is None:
            try:
                from voice import Mouth

                self.mouth = Mouth()
            except Exception:
                self.mouth = None  # 목소리가 없어도 듣기는 된다

        self.voice = VoiceWorker(vocab)
        self.voice.heard.connect(self.ask)
        self.voice.state.connect(lambda t: self.report(t, [ROOT]))
        self.voice.level.connect(self._on_level)
        self.voice.finished.connect(lambda: self._set_mic(False))
        self.voice.start()
        self._set_mic(True)

    def _meaning_ready(self, left: int) -> None:
        """뜻 벡터가 더 만들어졌다. 올려 둔 벡터 덩어리를 버려서 다음 검색에 새로 읽게 한다."""
        self.notes._vec_cache = None
        self._meaning_left = left

    _waiting: list = []

    def _later(self, fn) -> None:
        """신호가 끝난 뒤에 한다.

        글상자·콤보의 신호 **안에서** 그 위젯의 내용을 갈아 끼우면 Qt 가 제 밑을
        파고 죽는다(무작위로 눌러 보다 실제로 세그폴트가 났다). 한 박자 미룬다.

        검사에서는 `settle()` 로 그 한 박자를 돌려 준다 — 미룬 일까지 끝내고 봐야
        "눌렀는데 아무 일도 안 났다"는 헛것을 안 본다.
        """
        self._waiting.append(fn)
        QTimer.singleShot(0, self._run_waiting)

    def _run_waiting(self) -> None:
        """미뤄 둔 일을 차례로 한다. 하다가 하나가 터져도 나머지는 한다.

        **다시 들어오지 않게 막는다.** 미룬 일이 또 미루면 여기가 겹쳐 돌고,
        그 안에서 위젯을 다시 지으면 Qt 가 제 밑을 판다.
        """
        if getattr(self, "_draining", False):
            return
        self._draining = True
        try:
            while self._waiting:
                fn = self._waiting.pop(0)
                try:
                    fn()
                except Exception as e:
                    # 화면 조작 하나가 창을 죽이면 안 된다. 다만 누른 것이 **말없이 안 먹는** 자리라 남긴다.
                    report.trail(f"[화면 조작 실패] {type(e).__name__}: {e}")
        finally:
            self._draining = False

    def settle(self) -> None:
        """미뤄 둔 일을 **지금** 끝낸다. 검사와 시험에서 쓴다.

        `processEvents` 를 부르지 않는다 — 그건 신호 처리 도중에 부르면 되레
        재진입을 만들어, 막으려던 그 죽음을 다시 부른다.
        """
        self._run_waiting()

    def _bind_keys(self) -> None:
        """손이 마우스로 안 가게 한다. 하루에 수십 번 하는 것만 묶는다.

        ★★ **묶어 놓고 안 알려 주면 없는 것과 같다.** 단축키가 열네 개인데 사람이 알 길이
        하나도 없었다(Ctrl+D·Alt+←·Ctrl+\ 를 누가 짐작하나). 표를 **한 자리**에 두고
        묶기와 도움말(F1)이 같은 표를 읽는다 — 따로 적으면 반드시 어긋난다.
        """
        self.단축키표 = (
            ("Ctrl+O", lambda: (self.ask_box.setFocus(), self.ask_box.selectAll()), "찾기칸으로"),
            ("Ctrl+F", lambda: (self.ask_box.setFocus(), self.ask_box.selectAll()), "찾기칸으로"),
            ("Ctrl+E", self.toggle_edit, "읽기 ↔ 고치기"),
            ("Ctrl+N", self.new_note, "새 글"),
            # 치는 대로 저장되지만 Ctrl+S를 누르는 손버릇은 안 없어진다. 눌리면
            # 기다리지 않고 그 자리에서 쓴다 — **아무 일도 안 일어나면 불안하다.**
            ("Ctrl+S", self.save_note, "지금 저장"),
            ("Ctrl+D", self.open_daily, "오늘 일지"),
            ("Alt+Left", self.go_back, "뒤로"),
            ("Alt+Right", self.go_forward, "앞으로"),
            ("Ctrl+\\", self.open_side_here, "곁에 띄우기"),
            # ★ **글자 크기.** 옵시디언과 같은 손버릇이다. `Ctrl+=` 와 `Ctrl++` 둘 다 받는다
            #   — 자판에 따라 어느 쪽이 오는지 다르다.
            ("Ctrl+=", lambda: self.글자키우기(0.1), "글자 키우기"),
            ("Ctrl++", lambda: self.글자키우기(0.1), "글자 키우기"),
            ("Ctrl+-", lambda: self.글자키우기(-0.1), "글자 줄이기"),
            ("Ctrl+0", lambda: self.글자키우기(0), "글자 제자리"),
            # ※ 한글 이름 메서드를 `activated=` 에 곧장 넘기면 PyQt 가 이름을 ASCII 로 바꾸다 터진다.
            ("F1", lambda: self.단축키보기(), "이 목록"),
            ("F11", lambda: settings.toggle_full(self), "전체화면 켜고 끄기"),
            ("Ctrl+,", lambda: settings.open_dialog(self, self.notes), "설정 · 내 정보"),
            ("Esc", self.escape, "닫기 · 목록 접기"),
        )
        for keys, act, _ in self.단축키표:
            QShortcut(QKeySequence(keys), self, activated=act)
        # **Esc 는 앱 전체에서 먼저 본다.** 목록이 뜬 동안 키가 어느 길로 오든
        # 우리가 먼저 잡는다 — 위 `eventFilter` 설명 참고.
        QApplication.instance().installEventFilter(self)

    def _끼울몸(self, 제목: str) -> str | None:
        """끼워 넣은 글의 몸. 읽기 화면이 `![[글]]` 을 펼칠 때 부른다."""
        쪽 = self.notes.read(제목)
        return 쪽.body if 쪽 else None

    def 단축키글(self) -> str:
        """단축키 목록 글. 같은 일을 하는 키는 한 줄로 묶는다(Ctrl+O · Ctrl+F)."""
        묶음: dict[str, list[str]] = {}
        for keys, _, 설명 in self.단축키표:
            묶음.setdefault(설명, []).append(keys)
        return chr(10).join(f"{' · '.join(키들):22}  {설명}" for 설명, 키들 in 묶음.items())

    def 단축키보기(self) -> None:
        # ★ 공백으로 칸을 맞추면 비례 글꼴에서 줄이 들쭉날쭉했고, 한글 글꼴은 `\` 를 `₩` 로 그렸다(그려 보고 찾았다).
        #   표로 그리고 키는 모노 글꼴·강조색으로 — 주 창 계기판 글씨와 같은 결. 검사가 읽는 평문(`단축키글`)은 그대로다.
        import html

        묶음: dict[str, list[str]] = {}
        for keys, _, 설명 in self.단축키표:
            묶음.setdefault(설명, []).append(keys)
        줄들 = "".join(
            f"<tr><td style='padding:3px 18px 3px 0; color:{theme.T.ACCENT.name()}; font-family:{theme.MONO};'>"
            f"{html.escape(' · '.join(키들)).replace(chr(92), '＼')}</td>"   # 한글 글꼴은 \ 를 ₩ 로 그린다 — 보이는 글자만 전각으로
            f"<td style='padding:3px 0; color:{theme.T.TEXT.name()};'>{html.escape(설명)}</td></tr>"
            for 설명, 키들 in 묶음.items())
        box = QMessageBox(QMessageBox.NoIcon, "단축키", f"<table cellspacing='0'>{줄들}</table>",
                          QMessageBox.NoButton, self)
        box.setTextFormat(Qt.RichText)
        box.addButton("닫는다", QMessageBox.RejectRole)
        box.open()          # 창을 붙들지 않는다

    def 글자키우기(self, 만큼: float) -> None:
        """글자를 키우거나 줄인다. `만큼=0` 이면 제자리(1.0)로.

        ★ 화면 곳곳에 크기가 픽셀로 박혀 있어 **키울 길이 아예 없었다** — 4K 화면이나
        눈이 불편한 사람은 쓸 수가 없다. 옵시디언은 `Ctrl +/-` 로 된다.
        바꾼 값은 설정에 남겨 다음에 켤 때 그대로 뜬다.
        """
        새배율 = theme.배율바꾸기(theme.배율() + 만큼 if 만큼 else 1.0)
        self._apply_style()
        for 아이 in self.findChildren(QWidget):
            아이.style().unpolish(아이)
            아이.style().polish(아이)
        try:
            paths.save_config({**paths.load_config(), "글자배율": 새배율})
        except Exception:
            pass        # 못 남겨도 이번 판에는 적용된다
        self.report(f"글자 {round(새배율 * 100)}%", [ROOT])

    def escape(self) -> None:
        """Esc. **`[[` 목록이 떠 있으면 그것부터 닫는다.**"""
        if self.detail_body.pop_open():
            self.detail_body.close_pop()
            return
        self.clear_detail()

    def eventFilter(self, obj, event) -> bool:
        """앱 전체에서 Esc 를 먼저 본다. **`[[` 목록을 닫는 마지막 그물이다.**

        여기까지 온 이유: 낯선 PC 에서 `[[` 목록이 Esc 로 **네 번 연속** 안 닫혔다.
        세 자리를 고쳤는데 셋 다 안 걸렸다 — 글상자의 `keyPressEvent`, 목록에 건
        거름망, 창 단축키. 만든 PC 에서는 세 길 모두 잘 돌아서 **검사는 계속 초록불**
        이었다. 키가 어느 길로 오든 걸리도록 가장 낮은 자리에 하나 더 깐다.

        (이래도 안 닫히면 키가 Qt 까지 오지도 않는 것이다 — 그건 입력기 쪽이다.)
        """
        # ★ **손이 어디에 닿든 그래프를 깨운다.** 그래프는 아무도 안 만지면 잠든다
        # (네 시간을 안 만졌는데 코어 하나를 91% 태우고 있었다). 그런데 사람이 창
        # 어딘가를 만지는데 그래프만 자고 있으면 **화면이 굳은 것으로 보인다.**
        # 깨우는 자리를 여기 하나로 모은다 — 위젯마다 걸면 한 군데를 반드시 빠뜨린다.
        if event.type() in (QEvent.KeyPress, QEvent.MouseButtonPress,
                            QEvent.MouseMove, QEvent.Wheel):
            self.graph.깨우기()
        # 누름이 어디에 떨어졌는지 최근 넷을 들고 있는다 — 친 말이 글로 새면 자국에 같이 적는다.
        if event.type() == QEvent.MouseButtonPress and obj.isWidgetType():
            self._누름들 = (getattr(self, "_누름들", []) +
                         [f"{type(obj).__name__}:{obj.objectName() or '-'}"])[-4:]
        if (event.type() == QEvent.KeyPress and event.key() == Qt.Key_Escape
                and self.detail_body.pop_open()):
            self.detail_body.close_pop()
            return True
        # 읽는 칸에 대고 치거나 붙여넣으면 고치기로 넘긴다. **버리지 않는다.**
        if (event.type() == QEvent.KeyPress
                and self.detail_stack.currentIndex() == 0
                and (obj is self.detail_view or obj is self.detail_stack)
                and self.editing is not None
                and self.읽다가치면(event)):
            return True
        return super().eventFilter(obj, event)

    def _on_level(self, level: float) -> None:
        self.mic_level = level
        self.graph.mark.set_level(level)  # 목소리 크기만큼 불티가 튄다
        self.stats.setStyleSheet(
            theme.small(theme.T.ACCENT if level > 0.012 else theme.T.DIM, 0.4 + min(level * 8, 0.5))
        )

    def closeEvent(self, event) -> None:
        # 훑던 실이 남으면 프로그램이 안 꺼진다.
        self.indexer.again = False
        self.indexer.wait(3000)
        # 창을 닫아도 마이크 실이 남으면 프로그램이 안 꺼진다.
        if self.voice is not None:
            self.voice.stop()
            self.voice.wait(2000)
        super().closeEvent(event)

    def 열린자리알리기(self, host: str, port: int) -> None:
        """**밖에서도 닿는 자리로 열렸다는 것을 창에 적는다.**

        켤 때 콘솔에 찍는 말은 **창용으로 구운 exe 에서는 갈 데가 없다** — 시험하는
        쪽이 「리다이렉트해도 비어 있다」로 잡았다. 그러니 창이 스스로 말해야 한다.
        `127.0.0.1` 로 열렸으면 밖에서 못 닿으니 아무 말도 안 한다.
        """
        if host not in ("0.0.0.0", "::"):
            return
        self.열린자리.setText(f"★ 원격 열림 :{port}")
        self.열린자리.setToolTip(
            f"{host}:{port} 로 듣는다 — 같은 공유기와 테일스케일로 이은 다른 기기에서 닿는다. "
            "토큰 없이 들어오면 401로 막힌다. "
            "원격이 필요 없으면 --no-server 를 붙여 켜라.")
        self.열린자리.show()

    def _greet_server(self) -> None:
        """서버가 떠 있는지 처음 확인한다. 창이 다 뜬 뒤에 부른다."""
        self.refresh_engine()
        self.gate_card.refresh()
        self.models.refresh()

    def _테일보기(self) -> None:
        """테일스케일 주소를 딴 실에서 본다 — 명령이 늦으면 창이 굳으므로. 결과는 4초 타이머가 줄에 그린다."""
        import threading
        import tailnet

        def 일() -> None:
            self._테일 = tailnet.tailscale_ip()
            # 「기계 기록 보기 — 둘 다」면 요약 한 장을 기록 폴더 `_VC기록/` 에도(결정 17). 안 바뀌었으면 안 쓴다.
            if settings.기록보기() == "둘다":
                report.요약쓰기(self.notes.root)
        threading.Thread(target=일, daemon=True).start()

    def _그리띠(self) -> None:
        """늘 보이는 한 줄(결정 17) — 오류 · 준비 중 · 폰 길. **아무 일 없으면 비운다.**"""
        말 = [self._띠경고] if self._띠경고 else []
        # 밖에서 닿게 열렸는데 테일스케일이 꺼졌으면 폰은 집 밖에서 못 닿는다(결정 18·21).
        if not self.열린자리.isHidden() and self._테일 is None:
            말.append("⚠ 테일스케일 꺼짐 — 폰이 밖에서 못 닿는다")
        self.footer.setText("  /  ".join(말))
        # ★ 경고를 흐린 글자로 두면 안 보인다(맥 창을 그려 보고 잡음) — ⚠ 가 있으면 경고색으로.
        경고 = any("⚠" in m for m in 말)
        self.footer.setStyleSheet(theme.small(theme.T.WARN, 0.8, 9) if 경고 else theme.small(theme.T.DIM, 0.3, 9))

    def refresh_engine(self) -> None:
        """엔진이 뭘 올려놨는지. 서버가 꺼져 있으면 그 사실을 그대로 보여준다."""
        # 창이 제 메모리를 파일에 적어 둔다. --report 는 창이 아니라 새 프로세스라
        # 자기를 재면 안 되기 때문이다(시험 25-1). 4초 타이머라 여기서 같이 한다.
        report.메모리찍기()
        self._그리띠()
        out = self.link.call("GET", "/eb/v1/engine")
        if out is None:
            # ★ 「서버 꺼짐」이 원격 줄과 나란히 떠서 **어느 서버가 꺼진 것인지**
            #   헷갈린다고 시험 쪽이 짚었다. 이 줄은 **글 모델**을 말한다.
            # ★ 이 갈래는 **모델이 없다**가 아니라 **서버가 답을 안 했다**이다.
            #   둘을 같은 말로 적었더니 모델을 제대로 넣고도 「안 올라옴」으로 보였다
            #   (시험 쪽이 잡았다). 못 물어본 것과 물어봤더니 없는 것은 다른 말이다.
            self.engine_label.setText("엔진 —  서버에 못 물어봤다")
            return
        if out.get("loaded"):
            # 사진을 보는 모델인지 표시한다. 글자 모델이면 제품 검색이 안 된다.
            eye = "  ·  사진 봄" if out.get("sees_images") else ""
            self.engine_label.setText(f"엔진 {out['kind']}  ·  {out['loaded']} 올라옴{eye}")
        elif out.get("models"):
            self.engine_label.setText(f"엔진 {out['kind']}  ·  모델 {len(out['models'])}개 대기")
        else:
            self.engine_label.setText(f"엔진 {out['kind']}  ·  모델 없음")

    def load_proposals(self) -> None:
        for card in self.proposal_cards:
            card.setParent(None)
        self.proposal_cards.clear()
        if self._empty_hint is not None:
            self._empty_hint.setParent(None)  # 안 지우면 제안이 생겨도 "없음"이 남는다
            self._empty_hint = None

        for row in self.store.pending_proposals():
            card = ProposalCard(row)
            card.decided.connect(self.decide)
            self.proposal_box.insertWidget(self.proposal_box.count() - 1, card)
            self.proposal_cards.append(card)

        if not self.proposal_cards:
            empty = QLabel("아직 제안 없어. 쓰다 보면 내가 먼저 찾아낼게.")
            empty.setWordWrap(True)
            empty.setStyleSheet(f"color:{theme.css(theme.T.DIM, 0.3)}; font-size:{theme.글자(11)}; padding:14px 4px;")
            self.proposal_box.insertWidget(0, empty)
            self._empty_hint = empty

        # ★ **빈 칸이 250px 을 차지하면 안 된다.** 카드 한 장이 통째로 들어갈 높이를
        # 보장하려고 못을 박아 뒀는데, **제안이 하나도 없을 때까지 그 높이를 썼다** —
        # 「아직 제안 없어」 한 줄에 250px 이다. 그것이 옆칸을 길게 만들고,
        # 굴림칸을 거쳐 **창 최소 높이까지 밀어 올렸다**(낯선 PC 에서 1049).
        # 지킬 것은 「카드가 있을 때 반만 보이지 않기」지 빈 자리가 아니다.
        self.proposal_scroll.setMinimumHeight(
            PROPOSAL_AREA_MIN_H if self.proposal_cards else 56)

    def ask(self, text: str) -> None:
        """검색 입구. **여기서 터지면 프로그램이 죽는다** — 그래서 막는다.

        신호(엔터·마이크) 안에서 처리 안 된 예외가 나면 PyQt5 는 `qFatal()` 로
        프로세스를 끝낸다. 낯선 PC 에서 검색 엔터 한 번에 여섯 번 죽었다.
        **찾다 실패하는 것과 프로그램이 죽는 것은 하늘과 땅 차이다.**
        """
        try:
            self._ask(text)
        except Exception as err:
            report.log_crash(err)
            report.trail(f"찾다 실패: {type(err).__name__}: {err}")
            self.report(f"{self._감싸기(text)} 찾다가 문제가 생겼어. 진단 묶음에 남겼어.",
                        [ROOT])

    def _ask(self, text: str) -> None:
        """검색이든 지시든 여기로 들어온다. 음성도 이 문을 쓴다.

        찾은 것에 초점을 맞춘다 — 관련된 것만 남고 나머지는 가라앉는다.
        일정 시간이 지나거나 빈 곳을 누르면 저절로 풀려 전체 모습으로 돌아간다.
        """
        text = text.strip()
        if not text:
            self.graph.clear_focus()
            self.show_results([])
            return
        started = time.monotonic()

        # **시키는 말이면 그대로 한다.** 검색칸이 곧 지시칸이다 — 따로 두면 어느 칸에
        # 쳐야 하는지를 사람이 외워야 한다. 못 알아들으면 `None` 이라 그냥 검색으로 간다.
        # 알아듣는 일은 `orders.py` 가 하고 여기는 시키기만 한다 — 나중에 말로 시킬 때
        # 같은 길을 쓴다.
        order = orders.read_order(text)
        if order is not None and self.do_order(order, started):
            return

        # 먼저 시켜본다. VC는 찾아주는 물건이 아니라 시키는 물건이다 —
        # 모듈이 처리할 수 있는 말이면 검색으로 새지 않고 그대로 실행돼야 한다.
        done = self.link.call("POST", "/eb/v1/ask", {"text": text})
        if done and done.get("kind") == "result":
            module = (done.get("module") or "").strip()
            self.graph.focus_on([module] if module in self.graph.nodes else [ROOT],
                                zoom=FOCUS_ZOOM if module in self.graph.nodes else None)
            self.report(done["text"], [module] if module in self.graph.nodes else [ROOT])
            self._log_turn(text, done["text"], "result", started)
            return
        rows = self.notes.search(text)
        hits = [r["title"] for r in rows]
        # 갈래도 같이 넘긴다 — 결과에 여러 갈래가 섞여 오므로 고를 때 그것이 필요하다.
        self.show_results([(r["title"], r["body"], r["path"], r["kind"]) for r in rows], text)

        # 되묻는다는 건 시킬 말이 아니라는 뜻이다. 찾을 것이 있으면 찾아준다 —
        # "카페"라고 쳤는데 "어느 쪽이야?"가 나오면 검색칸이 아니게 된다.
        if done and done.get("kind") == "clarify" and not hits:
            self.report(done["text"], [ROOT])
            self._log_turn(text, done["text"], "clarify", started)
            return

        if not hits:
            # 시키지도 못하고 찾지도 못했다. 실행이 실패했으면 그 이유를 그대로 전한다.
            miss = done["text"] if done else self._못찾았다고(text)
            self.report(miss, [ROOT])
            self._log_turn(text, miss, done.get("kind", "miss") if done else "miss", started)
            return

        # 이미 초점이 잡힌 상태에서 또 찾는 건 좁히려는 것이다 — 그때 내용을 펼쳐 보여준다.
        narrowing = bool(self.graph.focus)

        # 맞는 것만 남긴다. 이웃까지 밝히면 좁힌 게 아니라 덩어리를 옮긴 것이 된다.
        self.ensure_on_graph(hits)
        self.graph.focus_on(hits, zoom=FOCUS_ZOOM if narrowing else None)

        # ★ **낱말이 하나도 안 걸렸으면 「관련」이라고 하지 않는다.** 뜻 검색이 빈자리를
        #   채운 것이라 어느 글에도 없는 말에도 「관련 4개야」가 떴다(시험 쪽 9). 차례는
        #   그대로 두고 **말만 사실대로** — 문턱으로 자르면 자료가 바뀔 때 무너진다.
        뜻만 = getattr(self.notes, "낱말로찾은수", None) == 0
        if narrowing:
            self.show_note(hits[0], focus=False)
            said = f"{hits[0]} 얘기야."
        elif 뜻만:
            # 조사는 받침을 본다 — 따옴표 밖에 붙이되 받침은 원래 말로 본다
            앞 = f"{self._감싸기(text)}{orders.tail(text.strip(chr(34) + chr(39)), '이/가')} 든 글은 없어."
            said = (f"{앞} 뜻으로 가까운 것 {len(hits)}개야." if len(hits) > 1 else
                    f"{앞} 뜻으로 가장 가까운 건 {orders.josa(hits[0], '이야/야')}.")
            # ★ **여기가 좁히기가 제일 잘 듣는 자리다.** 낱말이 하나도 안 걸려 뜻으로만
            #   채운 물음은, 가장 많은 갈래가 나머지를 밀어내고 있을 때가 많다. 재 보니
            #   갈래로 좁히면 목록 밖이던 글이 1~4등으로 올라왔다(얼린 물음 20개 중 셋).
            #   되는데 안 알려 주면 없는 것과 같아서, 바로 이 자리에서만 한 줄 붙인다.
            #   예로 드는 갈래는 **제일 많은 것 다음**이다 — 밀어내는 쪽(오너 창고는
            #   2373/2794 장이 `일`)을 예로 들면 좁혀도 그대로다.
            갈래들 = [g for g, in self.notes.conn.execute(
                "SELECT kind FROM notes WHERE kind != '' GROUP BY kind "
                "ORDER BY count(*) DESC LIMIT 2")]
            if len(갈래들) > 1:
                said += f" 안 보이면 kind:{갈래들[1]} 처럼 갈래로 좁혀 봐."
        elif len(hits) > 1:
            said = f"{self._감싸기(text)} 관련 {len(hits)}개야. 더 좁히면 내용을 보여줄게."
        else:
            # 조사는 받침을 본다 — 따옴표·`tag:` 가 붙어도 **끝말**로 고른다(시험 쪽 14)
            said = (f"{self._감싸기(text)}{orders.tail(text.strip(chr(34) + chr(39)), '은/는')} "
                    f"{hits[0]} 하나야. 한 번 더 치면 열어줄게.")
        self.report(said, hits[:3])
        self._log_turn(text, said, "search", started)

    @_쓰기막히면알림(돌려줄=True)
    def do_order(self, order: "orders.Order", started: float = 0.0) -> bool:
        """시킨 것을 한다. 못 하면 `False` — 그러면 부르는 쪽이 검색으로 넘긴다.

        **되돌릴 수 없는 것은 되묻는다.** 말로 시킬 때는 더 그렇다 —
        잘못 알아들은 한마디로 글이 사라지면 안 된다.
        """
        what, name, extra = order.what, order.target, order.extra
        started = started or time.monotonic()

        def done(said: str, who: list[str] | None = None) -> bool:
            self.report(said, who or [ROOT])
            self._log_turn(self.ask_box.text() or what, said, "지시", started)
            # **「활동」 칸에도 남긴다.** 그 칸은 서버가 남긴 것만 받고 있어서,
            # 타자로 수십 번 시켜도 한 줄도 안 쌓였다 — 「시켜본 게 여기 쌓인다」고
            # 적어 놓고 안 쌓이면 그 칸은 거짓말을 하는 것이다.
            self._log_deed(what, said, started)
            return True

        if what == "무르기":
            # **잘못 시킨 것을 되돌린다.** 되묻기까지 거쳐 「지워」를 다시 치게 하면
            # 잘못 시키는 것이 무섭다 — 무를 길이 있어야 마음 놓고 시킨다.
            undo, self._undo = getattr(self, "_undo", None), None
            if undo is None:
                return done("무를 게 없어.")
            kind, first, second = undo
            if kind == "만들기":
                try:
                    self.notes.delete(first)
                except WriteBlocked:
                    return done(f"'{first}' 못 물렀어 — 지난 판을 못 남겨서 멈췄어.", [first])
                self.clear_detail()
                self.refresh()
                return done(f"'{first}' 만든 걸 물렀어.")
            if kind == "이름바꾸기":
                self.notes.rename(second, first)
                self.show_note(first)
                return done(f"이름을 '{first}'로 되돌렸어.", [first])
            if kind == "덧붙이기":
                # ★★ **붙인 그 글만 뺀다.** 옛 몸으로 되돌리면 그 사이 AI 가 덧붙인 줄까지 사라졌다.
                with self.notes._글잠금(first):
                    note = self.notes.read(first)
                    if note is not None:
                        붙인 = chr(10) * 2 + second.strip()
                        if note.body.strip() == second.strip():
                            note.body = ""
                        elif 붙인 in note.body:
                            i = note.body.rfind(붙인)
                            note.body = note.body[:i] + note.body[i + len(붙인):]
                        self._wrote_at = time.monotonic()
                        self.notes.write(note, str(self.notes.path_of(first)))
                        self.show_note(first)
                return done(f"'{first}'에 덧붙인 걸 물렀어.", [first])
            return done("무를 게 없어.")

        if what == "찾기":
            # **꼬리말을 뗀 알맹이로 찾는다.** 안 그러면 「찾아줘」가 검색어에 그대로
            # 들어가 낱말 검색이 헛돈다 — 낯선 PC 에서 그렇게 나왔다.
            self.ask_box.setText(name)
            self._ask(name)
            return True
        if what == "닫기":
            self.clear_detail()
            return done("닫았어.")
        if what == "오늘일지":
            self.open_daily()
            return done("오늘 일지 열었어.", [self.editing or ROOT])
        if what == "언제":
            hits = self.notes.written_when(name)
            if not hits:
                return done(f"{name} 쓴 게 없어.")
            self.show_results([(t, b, p) for t, b, p in hits], name)
            self.ensure_on_graph([t for t, _, _ in hits])
            self.graph.focus_on([t for t, _, _ in hits], zoom=FOCUS_ZOOM)
            return done(f"{name} 쓴 것 {len(hits)}개야.", [t for t, _, _ in hits][:3])
        if what == "태그":
            self.show_tag(name)
            return True
        if what == "이어진것":
            hit = self.notes.resolve(name)
            if hit is None:
                return done(f"'{name}'{orders.tail(name, '이/가')} 없어.")
            near = self.notes.neighbors(hit)
            if not near:
                return done(f"'{hit}'에 이어진 게 없어.")
            self.ensure_on_graph([hit] + near)
            self.graph.focus_on([hit] + near, zoom=FOCUS_ZOOM)
            return done(f"'{hit}'에 이어진 것 {len(near)}개야.", [hit] + near[:2])

        # ★ **외딴 글**(옵시디언의 「고아 노트」). 이 창고는 AI 가 3천 장을 붓는 물건이라
        #   안 이어진 글이 쌓이기 쉽고, 그물에서 빠지면 닿을 길이 거의 없다.
        if what == "외딴것":
            외딴 = self.notes.외딴것()
            if not 외딴:
                return done("외딴 글은 없어. 다 이어져 있어.")
            self.show_results([(t, (self.notes.read(t).body if self.notes.read(t) else ""),
                                "", "") for t in 외딴], "")
            # ★ **목록 길이로 말하면 거짓말이 된다.** 오너 창고는 2836장 중 2700장(95%)이
            #   외딴이라 「서른 개야」가 된다. 모두 몇 장인지 세어 **사실대로** 말한다.
            모두 = self.notes.외딴것수()
            꼬리 = f" 최근 {len(외딴)}개만 보여줄게." if 모두 > len(외딴) else ""
            return done(f"링크로 안 이은 글 {모두}개야.{꼬리} 안 이어도 뜻으로는 찾혀.",
                        외딴[:3])

        # 여기부터는 대상이 있어야 한다.
        if what == "만들기":
            if self.notes.read(name) is not None:
                self.show_note(name)
                return done(f"'{name}'{orders.tail(name, '은/는')} 이미 있어서 열었어.", [name])
            self.fill_gap(name)
            self._undo = ("만들기", name, "")
            return done(f"'{name}' 만들었어. (무르려면 「무르고」)", [name])

        if what == "덧붙이기":
            # **진짜 있는 제목을 고른다.** 제목 안에 「에」가 있으면 어디서 잘라야
            # 할지 글자만으로는 못 정한다 — 항목 목록을 아는 우리가 정한다.
            for 제목, 내용 in (order.alts or ((name, extra),)):
                if self.notes.resolve(제목):
                    name, extra = 제목, 내용
                    break

        hit = self.notes.resolve(name) if name else None
        if what in ("열기", "곁에", "덧붙이기", "이름바꾸기", "지우기", "되돌리기",
                    "고정", "고정풀기"):
            if hit is None and name:
                # **없는 것을 시키면 지어내지 않는다.** 찾아 주는 편이 낫다.
                return False
        if what == "열기":
            self.show_note(hit)
            return done(f"{hit} 열었어.", [hit])
        if what == "곁에":
            if hit:
                self.show_note(hit)
            self.open_side_here()
            return done("곁에 띄웠어.", [hit or ROOT])
        if what == "덧붙이기":
            self._wrote_at = time.monotonic()
            self._undo = ("덧붙이기", hit, extra)   # 옛 몸이 아니라 붙인 글을 쥔다(무를 때 그것만 뺀다)
            self.notes.append(hit, extra)
            self.show_note(hit)
            # **어디에 무엇을 붙였는지 그대로 보여 준다.** 「학교에 안 갔다 적어줘」가
            # 「학교」에 「안 갔다」만 쌓는 일이 있다 — 새 글로 적으려던 것인데
            # 「학교」라는 항목이 있다는 이유만으로 잘린다. 사람 뜻과 글자만으로는
            # 못 가르는 자리라, **틀렸을 때 바로 알아채고 무를 수 있게** 하는 쪽을 택했다.
            return done(f"'{hit}'에 「{extra}」 적었어. 새 글로 적으려던 거면 「무르고」",
                        [hit])
        if what == "이름바꾸기":
            if not extra:
                return False
            self.show_note(hit)
            self.detail_title.setText(extra)
            self.rename_note()
            self._undo = ("이름바꾸기", hit, extra)
            return done(f"'{hit}'{orders.tail(hit, '을/를')} "
                        f"'{extra}'{orders.tail(extra, '으로/로')} 바꿨어.", [extra])
        # ★ **고정은 결정 22 로 「늘 먼저」 나오는 힘인데 말로 시키는 길이 없었다** —
        #   화면 단추로만 됐다(옵시디언의 star 자리다). 되돌리기 쉬운 일이라 안 되묻는다.
        if what in ("고정", "고정풀기"):
            if not hit:
                return False
            켬 = what == "고정"
            # 읽고-고치고-쓰기라 잠근다 — 그 사이 AI 가 덧붙인 줄을 옛 몸으로 덮으면 안 된다.
            with self.notes._글잠금(hit):
                쪽 = self.notes.read(hit)
                if 쪽 is None:
                    return False
                if 쪽.pinned == 켬:
                    return done(f"'{hit}'{orders.tail(hit, '은/는')} 이미 "
                                + ("고정돼 있어." if 켬 else "고정 안 돼 있어."))
                쪽.pinned = 켬
                self.notes.write(쪽)
            self.refresh()
            return done(f"'{hit}'{orders.tail(hit, '을/를')} "
                        + ("고정했어. 이제 늘 먼저 나와." if 켬 else "고정 풀었어."), [hit])
        if what == "지우기":
            # **되돌릴 수 없다.** 시킨 말이 맞는지 눈으로 보고 누르게 한다.
            # ★ **가리키던 글이 있으면 그것도 보여 준다.** 세 글이 이 글을 가리키는데
            #   말없이 지우면 그물이 조용히 끊긴다 — 누르기 전에 알아야 할 것이다.
            가리키던 = [t for t, _ in self.notes.backlinks(hit)] if hit else []
            물음 = orders.spoken(order) + (
                f"{chr(10)}{len(가리키던)}장이 이 글을 가리키고 있어: "
                + " · ".join(가리키던[:3]) + (" 외" if len(가리키던) > 3 else "")
                if 가리키던 else "")
            if not self._agreed("지울까?", 물음, "지운다"):
                return done("안 지웠어.")
            try:
                self.notes.delete(hit)
            except WriteBlocked:
                return done(f"'{hit}' 못 지웠어 — 지난 판을 못 남겨서 멈췄어(기록 폴더가 잠겼거나 읽기 전용).", [hit])
            self.clear_detail()
            self.refresh()
            return done(f"'{hit}'{orders.tail(hit, '을/를')} 지웠어.")
        if what == "되돌리기":
            past = self.notes.history(hit) if hit else []
            if not past:
                return done(f"'{hit}'{orders.tail(hit, '은/는')} 지난 판이 없어.")
            when, where = past[-1]
            if not self._agreed("되돌릴까?", f"'{hit}'을 {when} 판으로 되돌린다. "
                                            "지금 글도 한 판 남는다.", "되돌린다"):
                return done("그대로 뒀어.")
            try:
                self.notes.restore(hit, where)
            except WriteBlocked:
                return done(f"'{hit}' 못 되돌렸어 — 지금 글을 못 남겨서 멈췄어(기록 폴더가 잠겼거나 읽기 전용).", [hit])
            self.show_note(hit)
            return done(f"{when} 판으로 되돌렸어.", [hit])
        return False

    def follow_link(self, name: str, heading: str = "") -> None:
        """본문의 [[링크]]를 따라간다. **신호가 끝난 뒤에** 움직인다.

        이 함수는 글상자의 마우스 처리 **안에서** 나온 신호로 불린다. 그 자리에서
        같은 글상자의 문서를 갈아 끼우면 Qt 가 제 밑을 파고 죽는다 — 무작위로
        눌러 보다 실제로 났다. 사용자가 링크를 누르는 흔한 길이다.
        """
        self._later(lambda: self._do_follow_link(name, heading))

    def _do_follow_link(self, name: str, heading: str = "") -> None:
        """아직 없는 이름이면 그 자리에서 만든다.

        `[[노트#소제목]]`으로 불렀으면 그 소제목 자리까지 데려간다 — 긴 문서에서
        맨 위만 보여주면 어디를 보라는 건지 알 수 없다.
        """
        hit = self.notes.resolve(name)
        if hit is None:
            self.fill_gap(name)
            return
        self.show_note(hit)
        if heading:
            # ★ **보이는 쪽에서 옮긴다.** 편집기에서만 옮겨서 읽기 화면(기본)으로 열면 늘 맨 위였다.
            읽기 = self.detail_stack.currentIndex() != 1
            # 편집기 커서는 늘 옮긴다 — 고치기로 넘어가면 그 자리에서 이어 쓰게.
            self.detail_body.go_to_heading(heading)
            box = self.detail_view if 읽기 else self.detail_body
            want = heading
            if 읽기 and heading.startswith("^"):
                # 읽기 화면엔 블록 이름이 안 보인다 — 그 덩이 첫 줄 글자로 찾는다.
                쪽 = self.notes.read(hit)
                토막 = notes_module.block(쪽.body, heading) if 쪽 else ""
                첫 = (토막.splitlines() or [""])[0].strip().lstrip("-*+ ").strip()
                want = re.sub(r"[*_`~\[\]]", "", 첫)[:40] or heading
            box.go_to_heading(want)

    def show_year(self, year: str) -> None:
        """그해에 처음 적은 것들을 늘어놓는다."""
        rows = self.notes.in_year(year)
        self.show_results(rows, "")
        if rows:
            titles = [t for t, _ in rows]
            self.ensure_on_graph(titles[:12])
            self.graph.focus_on(titles[:12])
            self.report(f"{year}년에 적은 게 {len(rows)}개야.", titles[:3])
        else:
            self.report(f"{year}년엔 적은 게 없어.", [ROOT])

    def show_tag(self, tag: str) -> None:
        # 태그도 글상자의 마우스 처리 안에서 눌린다. 같은 이유로 미룬다.
        self._later(lambda: self._do_show_tag(tag))

    def _do_show_tag(self, tag: str) -> None:
        """태그로 묶어 본다. 하위 태그(#할일/출근)는 상위로도 걸린다."""
        titles = self.notes.by_tag(tag)
        rows = [(t, (self.notes.read(t) or Note(title=t, body="")).body) for t in titles]
        self.show_results(rows, "#" + tag)
        if titles:
            self.ensure_on_graph(titles[:GRAPH_LIMIT // 2])
            self.graph.focus_on(titles)
            self.report(f"#{tag} 붙은 게 {len(titles)}개야.", titles[:3])
        else:
            self.report(f"#{tag} 붙은 게 없어.", [ROOT])

    def show_results(self, hits: list[tuple[str, str]], query: str = "") -> None:
        """찾은 것을 옆에 늘어놓는다. 없으면 칸 자체를 접는다 — 빈 상자는 자리만 먹는다."""
        self.results.show_hits(hits, query)
        self.results_head.setVisible(bool(hits))
        self.results.setVisible(bool(hits))

    def ensure_on_graph(self, titles) -> None:
        """찾은 것이 그래프에 없으면 올린다.

        보이는 수를 묶어 두었으니 **방금 찾은 것이 잘려 나갈 수 있다.** 그러면
        "찾았다"고 해 놓고 화면에는 없는 꼴이 된다 — 정확하지 않다.
        """
        missing = [t for t in titles if t and t not in self.graph.nodes]
        if not missing:
            return
        keep = set(missing) | {ROOT} | set(list(self.graph.nodes)[:GRAPH_LIMIT // 2])
        picked = self.notes.working_set(GRAPH_LIMIT, keep=keep)
        self.graph.load(self.notes.subgraph(picked), self.notes.kinds_of(picked),
                        self.notes.kin(picked))

    def show_note(self, title: str, focus: bool = True, trail: bool = True) -> None:
        note = self.notes.read(title)
        if note is None:
            return
        if trail:
            self._mark_trail(title)
        self.ensure_on_graph([title])
        if focus:
            # 항목을 직접 누른 것도 내용을 펼치는 일이다 — 그 항목만 남기고 다가간다.
            self.graph.focus_on([title], zoom=FOCUS_ZOOM)
        self._fill_detail(note)
        self.report(f"{title} 얘기야.", [title] + self.notes.neighbors(title)[:3])

    def _fill_detail(self, note: Note, where: str = "") -> None:
        """항목을 칸에 올린다.

        **대괄호를 벗기지 않는다.** 고칠 수 있는 칸이라, 보이는 글과 저장되는 글이
        다르면 한 번 고치는 순간 링크가 통째로 날아간다.
        """
        self._save_timer.stop()
        self.editing = None            # 채우는 동안의 신호는 저장으로 안 센다
        # 연 **파일**을 들고 있는다. 제목으로 다시 찾으면 쌍둥이 중 엉뚱한 쪽에 쓴다.
        self.editing_at = str(where) if where else str(self.notes.path_of(note.title))
        self.open_reader()
        self.detail_kind.show()
        # **모르는 종류라도 그 값을 지우지 않는다.** 없는 값이면 맨 앞(에이전트)으로
        # 떨어지고, 다음 저장에 그것이 파일에 쓰여 **남이 적어 둔 값이 사라진다.**
        # 자리를 하나 만들어 그대로 돌려보낸다.
        for spare in range(self.detail_kind.count() - 1, len(theme.KIND_LABEL) - 1, -1):
            self.detail_kind.removeItem(spare)          # 앞 항목이 남긴 자리
        at = self.detail_kind.findData(note.kind)
        if at < 0 and note.kind:
            self.detail_kind.addItem(note.kind, note.kind)
            at = self.detail_kind.count() - 1
        self.detail_kind.setCurrentIndex(max(at, 0))
        self.detail_title.setReadOnly(False)
        self.detail_title.setText(note.title)
        self.detail_body.setReadOnly(False)
        self.detail_body.setPlainText(note.body.strip())
        self._opened_body = note.body.strip()   # 저장할 때 밖에서 바뀌었는지 견줄 것
        self.detail_view.show_note(note.body.strip())
        self._fill_toc(note.body)
        self._fill_past(note.title)
        self.side_btn.show()
        self._show_trail_buttons()
        self._show_twin(note.title, where)
        self.detail_stack.setCurrentIndex(0)      # 열 때는 읽는 모습
        self.edit_btn.setText("고치기")
        self.edit_btn.show()
        self.shut_btn.show()
        self.editing = note.title
        self._fill_links(note.title)

    def _link_row_clicked(self, href: str) -> None:
        kind, _, name = href.partition(":")
        (self.show_tag if kind == "tag" else self.show_note)(name)

    # 본문에서 Ctrl로 누른 링크는 (대상, 소제목) 둘을 준다.


    def _fill_links(self, title: str) -> None:
        """이어진 것과 태그를 아래 줄에. **눌러서 갈 수 있어야** 연결이 쓸모가 있다."""
        links = sorted({self.notes.resolve(r["dst"]) or r["dst"]
                        for r in self.notes.conn.execute(
                            "SELECT dst FROM links WHERE src = ?", (title,))} - {title})
        tags = [r["tag"] for r in self.notes.conn.execute(
            "SELECT tag FROM tags WHERE title = ? ORDER BY tag", (title,))]
        color = theme.css(theme.T.ACCENT, 0.75)

        def chip(text, href):
            return f'<a href="{href}" style="color:{color}; text-decoration:none">{text}</a>'

        # 다 늘어놓으면 카드를 밀어낸다. 넷까지만 보이고 나머지는 개수로 접는다.
        parts = []
        if links:
            shown = " · ".join(chip(t, f"note:{t}") for t in links[:4])
            if len(links) > 4:
                shown += f" +{len(links) - 4}"
            parts.append("적어둔 것 " + shown)
        if tags:
            parts.append("태그 " + " ".join(chip("#" + t, f"tag:{t}") for t in tags[:5]))
        # **손으로 안 이어도 곁가지가 있어야 한다.** 이것이 나무위키의 「관련 문서」 자리다 —
        # 여기서 눌러 들어가는 것이 「찾을 낱말을 모를 때」의 유일한 길이다.
        # 이미 적어 둔 것과 겹치는 것은 뺀다 — 같은 말을 두 줄로 하면 둘 다 안 읽는다.
        # 카드는 **단언이 아니라 길**이다. 양쪽이 동의 안 해도 내가 꼽은 1등을 보여 준다 —
        # 갈 길이 하나도 없는 것이 어중간한 길 하나보다 나쁘다. (그래프 선은 맞짝만 긋는다)
        near = [t for t in self.notes.kin([title], 맞짝만=False).get(title, [])
                if t not in links and t != title]
        if near:
            잔한 = theme.css(theme.T.DIM, 0.55)

            def 곁(text):
                return (f'<a href="note:{text}" '
                        f'style="color:{잔한}; text-decoration:none">{text}</a>')

            parts.append("비슷한 것 " + " · ".join(곁(t) for t in near[:3]))
        self.detail_links.setText("&nbsp;&nbsp;&nbsp;".join(parts))

        note = self.notes.read(title)
        shown = []
        for name, heading in (note.embeds() if note else []):
            hit = self.notes.resolve(name)
            target = self.notes.read(hit) if hit else None
            if target is None:
                shown.append((name, "아직 없는 항목이야"))
                continue
            body = section(target.body, heading) if heading else target.body
            label = f"{hit}#{heading}" if heading else hit
            shown.append((label, body or "그 소제목이 비어 있어"))
        self.embeds.show_hits(shown, "", width=110)
        self.embeds_head.setVisible(bool(shown))
        self.embeds.setVisible(bool(shown))

        backs = self.notes.backlinks(title)
        self.backs.show_hits(backs)
        self.backs_head.setVisible(bool(backs))
        self.backs.setVisible(bool(backs))
        언급 = self.notes.언급(title)
        self.mentions.show_hits(언급)
        self.mentions_head.setVisible(bool(언급))
        self.mentions.setVisible(bool(언급))

    def _indexed(self, changed: int) -> None:
        """훑기가 끝났다. 바뀐 게 있을 때만 다시 그린다 — 없으면 화면을 건드릴 이유가 없다."""
        if changed:
            self.refresh(scan=False)
            self._reload_open()
            self._rewatch()          # 새로 생긴 폴더도 지켜본다

    def _rewatch(self) -> None:
        """기록이 든 폴더를 모두 지켜본다. 뿌리만 보면 `연/월` 안의 변화를 놓친다."""
        want = {str(self.notes.root)}
        try:
            # 연결 폴더는 안 따라간다 — 볼트 자신을 가리키는 정션이면 끝없이 들어간다.
            for d in notes_module.훑어내림(self.notes.root, (), 폴더도=True):
                want.add(str(d))
        except OSError:
            pass                     # 훑는 사이 누가 지웠다 — 다음 바퀴에 다시 본다
        now = set(self._watch.directories())
        if add := sorted(want - now):
            self._watch.addPaths(add)
        if gone := sorted(now - want):
            self._watch.removePaths(gone)

    def _reload_open(self) -> None:
        """열어 놓은 항목이 밖에서 바뀌었으면 받아들인다. 치던 중이면 안 덮는다."""
        if self.editing is None:
            return
        fresh = self.notes.read(self.editing)
        if fresh is None:
            self.clear_detail()
            return
        if fresh.body.strip() == self.detail_body.toPlainText().strip():
            return
        # ★ **우리가 방금 쓴 것을 「밖에서 온 것」으로 읽지 않는다.**
        # 저장하면서 본문 맨 앞 `---` 블록이 앞머리로 올라가므로 **디스크 본문은
        # 편집칸 글과 일부러 다르다.** 그걸 모르면 저장할 때마다 파일 감시가
        # 「밖에서도 고쳤어」를 띄운다 — 아무도 안 건드렸는데(시험 쪽 새-④).
        # `_opened_body` 에는 **디스크에 실제로 내려간 글**이 들어 있다.
        if fresh.body.strip() == getattr(self, "_opened_body", None):
            return
        if self._save_timer.isActive() or self.detail_stack.currentIndex() == 1:
            # **고치는 중이면 화면을 안 건드린다.** 갈아 끼우면 읽기로 튕겨 나가
            # 사용자는 왜 편집이 끝났는지 모른다 — 낯선 PC 에서 그렇게 보였다.
            self.report(f"{orders.josa(self.editing, '을/를')} 밖에서도 고쳤어. 네가 치던 게 우선이야. "
                        "밖에서 온 것은 「지난 판」에 남겨 둘게.", [ROOT])
            return
        self._fill_detail(fresh, self.editing_at)

    def pull_outside(self) -> None:
        """밖에서 고친 파일을 읽어 들인다.

        **열어 놓고 고치던 중이면 안 덮는다.** 사용자가 치던 글을 밖에서 온 내용으로
        갈아 끼우면 방금 쓴 문장이 소리 없이 사라진다 — 그건 되돌릴 수도 없다.
        대신 알려만 주고, 손을 뗀 뒤에 눌러서 받게 한다.
        """
        if time.monotonic() - self._wrote_at < 1.5:
            return                       # 방금 우리가 쓴 것이다
        self.indexer.ask()               # 훑기는 딴 실에서. 끝나면 _indexed가 받는다

    def paste_image(self, data: bytes, suffix: str) -> None:
        """붙여넣은 그림을 파일로 저장하고 본문에 표기를 끼운다.

        그림을 본문 안에 통째로 넣지 않는다(base64). 파일이 원본인 설계라, 그림도
        파일이어야 옵시디언·탐색기에서 그대로 열린다.
        """
        if self.editing is None:
            return
        self._wrote_at = time.monotonic()
        name = self.notes.save_attachment(data, suffix, f"{self.editing} 붙임")
        self.detail_body.insertPlainText(f"![[{name}]]")
        self.save_note()
        self.report(f"그림을 넣었어 — {name}", [self.editing])

    def _고치기로(self) -> None:
        """읽기 → 고치기. 이미 고치기면 아무 일도 안 한다."""
        if self.detail_stack.currentIndex() != 1:
            self.detail_stack.setCurrentIndex(1)
            self.edit_btn.setText("읽기")

    def 읽다가치면(self, event) -> bool:
        """읽기 모드에서 글자를 치거나 붙여넣으면 **고치기로 넘기고 그 입력을 살린다.**

        ★ **조용히 버려지던 자리다.** 읽는 칸은 읽기 전용이라 Ctrl+V 가 아무 일도
        안 했다 — 화면도 안 바뀌고 말도 없었다. 시험하는 쪽이 「왜 안 들어가지」로
        몇 번 더 눌렀다. **사람이 넣은 것을 말없이 버리는 것이 이 프로그램에서
        제일 나쁜 짓이다.** 모드를 눈치채게 하는 대신 **모드가 비키게** 한다.
        """
        키 = event.key()
        붙여넣기 = event.matches(QKeySequence.Paste)
        글자 = bool(event.text()) and 키 not in (
            Qt.Key_Escape, Qt.Key_Tab, Qt.Key_Backtab, Qt.Key_Return, Qt.Key_Enter)
        # 단축키(Ctrl+F 따위)는 그대로 흘려보낸다. 붙여넣기만 예외로 잡는다.
        if not 붙여넣기 and (event.modifiers() & (Qt.ControlModifier | Qt.AltModifier)):
            return False
        if not (붙여넣기 or 글자):
            return False
        # ★ **검색칸을 눌렀는데 친 말이 글로 들어가 저장됐다**(만든 PC 재현, 열린 문제 7).
        #   이 길로 글이 바뀔 때 초점·최근 누름을 자국에 남긴다 — 그래야 원인이 갈린다.
        초점 = QApplication.focusWidget()
        report.trail(f"읽다 쳐서 고치기로 — 초점 "
                     f"{type(초점).__name__ + ':' + (초점.objectName() or '-') if 초점 else None}"
                     f" · 최근 누름 {getattr(self, '_누름들', [])}")
        self._고치기로()
        self.detail_body.setFocus()
        if 붙여넣기:
            self.detail_body.paste()
        else:
            self.detail_body.insertPlainText(event.text())
        return True

    def toggle_edit(self) -> None:
        """읽기 ↔ 고치기. 고치기에서 나올 때 반드시 저장한다."""
        if self.detail_stack.currentIndex() == 1:
            self.save_note()
            note = self.notes.read(self.editing) if self.editing else None
            self.detail_view.show_note(note.body.strip() if note else "")
            self.detail_stack.setCurrentIndex(0)
            self.edit_btn.setText("고치기")
            return
        self.detail_stack.setCurrentIndex(1)
        self.edit_btn.setText("읽기")
        self.detail_body.setFocus()

    def save_note(self) -> None:
        """치는 대로 저장한다. 열린 항목이 없으면 아무 일도 안 한다."""
        if self.editing is None:
            return
        # 읽고-견주고-쓰기를 잠금 안에서 — 그 사이 AI 가 덧붙인 줄을 「밖에서 온 것」으로 못 보고 덮지 않게.
        with self.notes._글잠금(self.editing):
            note = self.notes.read_at(self.editing_at)
            if note is None:
                return
            body = self.detail_body.toPlainText()
            kind = self.detail_kind.currentData() or note.kind
            if body == note.body.strip() and kind == note.kind:
                return                      # 바뀐 게 없으면 파일을 안 건드린다
            # **밖에서 바뀐 글을 말없이 덮지 않는다.** 열어 둔 사이 옵시디언이나 동기화가
            # 고쳐 놨으면, 우리 글로 덮기 **전에** 그쪽을 한 판 남긴다 — 낯선 PC 에서
            # 밖에서 온 줄이 파일에도 이력에도 없이 사라졌다(2/2 재현).
            if note.body.strip() not in (getattr(self, "_opened_body", ""), body):
                try:
                    self.notes.keep_history(Path(self.editing_at),
                                            read_text(Path(self.editing_at)), always=True)
                    self.report(f"{orders.josa(note.title, '을/를')} 밖에서도 고쳤길래 "
                                f"그쪽은 「지난 판」에 남겼어.",
                                [note.title])
                except (OSError, ValueError):
                    pass
            note.body, note.kind = body, kind
            # 사람이 손댄 표시. AI가 나중에 통째로 덮어쓰려 하면 서버가 막는다.
            note.edited_by = "사람"
            self._wrote_at = time.monotonic()
            try:
                self.notes.write(note, self.editing_at)
            except WriteBlocked:
                # 사람이 잠가 둔 파일이다. 글은 옆에 남았으니 어디 있는지 말해 준다.
                self.report(f"'{note.title}' 파일이 잠겨 있어 못 썼어. "
                            f"쓰던 글은 옆에 '(못 쓴 글)' 로 남겨 뒀어.", [note.title])
                return
        # **방금 쓴 것이 이제 「연 순간의 글」이다.** 안 고치면 두 번째 저장부터
        # 디스크에 있는 내 글이 `_opened_body`(맨 처음 것)와도 `body`(새로 친 것)와도
        # 달라서, **자기가 쓴 것을 남이 쓴 것으로 본다** — 낯선 PC 에서 아무도 안
        # 건드렸는데 "밖에서도 고쳤길래"가 세 번 중 두 번 떴다(1회차만 정상).
        # ★ **디스크에 실제로 내려간 글을 들고 있어야 한다.** 여기 친 글(`body`)을
        #   그대로 넣으면 안 된다 — 저장하면서 본문 맨 앞의 `---` 블록이 앞머리로
        #   올라가므로 **디스크의 본문은 여기 친 것과 다르다.** 그걸 모르고 친 글을
        #   들고 있으면 다음 저장에서 「밖에서도 고쳤길래」가 뜬다. 아무도 안 건드렸는데.
        #   (시험 쪽 새-④ — 그쪽은 이름 바꾸기를 의심했지만 원인은 이 자리였다)
        self._opened_body = note.body.strip()
        # ★ **글이 바뀌면 목차도 바뀐다.** `_fill_toc` 이 항목을 **열 때만** 불려서,
        # 소제목을 쳐 넣고 저장해도 목차가 0으로 남았다 — 새로 만든 글은 빈 채로
        # 열리므로 **직접 쳐서 만든 글은 목차가 영영 안 떴다**(시험 쪽 다-②).
        # 넓은 창에서도 안 보이던 까닭이 접기가 아니라 이것이었다.
        self._fill_toc(note.body)
        self._place_reader()          # 채운 뒤 접기를 다시 셈한다
        self._fill_links(note.title)
        self.refresh()
        # ★ **저장했다고 말해 준다.** Ctrl+S 를 눌러도 화면이 하나도 안 바뀌어서
        #   시험하는 쪽이 파일을 열어 보고서야 저장된 걸 알았다(다-4). 글을 맡기는
        #   물건에서 「됐나?」가 남으면 사람은 그 물건을 못 믿는다.
        self._저장했다고(note.title)

    @staticmethod
    def _감싸기(text: str) -> str:
        """물음을 따옴표로 감싼다. **이미 따옴표면 그대로 둔다.**

        ★ 사람이 친 큰따옴표를 작은따옴표로 또 감싸서 `'"소리 내어 읽으면"'` 처럼
        두 겹으로 보였다. 처음엔 못 찾았을 때 자리만 고쳤는데 **찾았을 때 자리에도
        같은 것이 있었다**(시험 쪽이 반만 고쳐졌다고 짚었다). 같은 일을 두 군데서
        하면 한 군데는 반드시 남는다 — 그래서 여기 한 자리로 모은다.
        """
        보임 = text.strip()
        return 보임 if 보임.startswith(("'", '"')) else f"'{보임}'"

    def _못찾았다고(self, text: str) -> str:
        """못 찾았을 때 할 말. **따옴표를 쳤으면 떼면 몇 개 있는지도 알려 준다.**

        ★ 따옴표를 친 사람은 **그 말이 있다고 믿고** 친 것이다. 0건이 나오면
        다음 손이 「따옴표를 떼 본다」인데, 그걸 사람이 스스로 떠올려야 했다
        (시험 쪽이 그 자리를 짚었다). 여기서 미리 세어 알려 준다.

        따옴표는 **한 겹만** 보인다. 사람이 친 큰따옴표를 작은따옴표로 또 감싸면
        `'"이런 구절"'` 처럼 두 겹으로 보인다.
        """
        말 = f"{self._감싸기(text)}로는 못 찾겠어."
        # ★ **뜻 모델이 아직 안 올랐으면 그렇다고 말한다.** 켠 뒤 몇 초는 낱말로만 찾아서
        #   자연말 물음이 조용히 0건이 된다 — 사람은 「없구나」 하고 떠난다(서버 1단과 같은 구멍).
        if getattr(self.notes, "_embed", None) is None and self._뜻모델있나():
            말 += " 뜻 검색은 아직 올리는 중이야 — 조금 뒤 다시 쳐 봐."
        if '"' in text:
            헐겁게 = text.replace('"', " ").strip()
            남은 = len(self.notes.search(헐겁게, k=8)) if 헐겁게 else 0
            if 남은:
                말 += f" 따옴표를 떼면 비슷한 게 {남은}개 있어."
        return 말

    def _뜻모델있나(self) -> bool:
        """뜻 모델 파일이 있나. 있는데 아직 안 붙었으면 「올리는 중」이다."""
        try:
            return (paths.meaning_dir(
                (paths.load_config().get("models") or {}).get("meaning", "")) / "model.onnx").is_file()
        except Exception:
            return False

    def _저장했다고(self, title: str) -> None:
        """말풍선으로 「저장했어」. **상태줄을 안 쓴다.**

        ★ 처음엔 상태줄에 썼는데 두 가지가 어긋났다(시험 쪽 마):
        - 상태줄은 **⚠ 경고가 사는 자리**다. 저장할 때마다 1.6초씩 ⚠ 가 가려졌다.
          ⚠ 는 「이상할 때만 말한다」는 자리라 저장에 가리면 안 된다.
        - 말풍선은 **새 말이 생길 때만 바뀌는데 저장은 말풍선을 안 건드렸다.**
          그래서 지나간 경고가 계속 떠 있었다 — 다음 글로 넘어가도 그대로였다.

        말풍선으로 옮기니 둘 다 풀린다. 소리로는 안 읽는다 — 저장할 때마다
        말하면 시끄럽다.
        """
        self.report(f"저장했어 — {title}", [], aloud=False)

    # --- 오간 자취 ------------------------------------------------------

    def _mark_trail(self, title: str) -> None:
        """열어 본 차례를 남긴다. 되돌아간 뒤 새로 열면 그 앞의 앞길은 지운다 —
        브라우저와 같다. 안 그러면 '앞으로'가 엉뚱한 데로 간다."""
        if 0 <= self._trail_at < len(self._trail) and self._trail[self._trail_at] == title:
            return
        del self._trail[self._trail_at + 1:]
        self._trail.append(title)
        # 20년을 켜 둬도 자취가 무한정 자라면 안 된다.
        if len(self._trail) > 100:
            self._trail = self._trail[-100:]
        self._trail_at = len(self._trail) - 1
        self._show_trail_buttons()

    def _show_trail_buttons(self) -> None:
        self.back_btn.setEnabled(self._trail_at > 0)
        self.fwd_btn.setEnabled(self._trail_at < len(self._trail) - 1)

    def _walk_trail(self, step: int) -> None:
        at = self._trail_at + step
        if not 0 <= at < len(self._trail):
            return
        self._trail_at = at
        self.show_note(self._trail[at], trail=False)
        self._show_trail_buttons()

    def go_back(self) -> None:
        self._walk_trail(-1)

    def go_forward(self) -> None:
        self._walk_trail(1)

    # --- 옆 판 ----------------------------------------------------------

    def open_side_here(self) -> None:
        """지금 글이 가리키는 것 중 첫째를 옆에 띄운다. 없으면 앞서 보던 것."""
        if self.editing is None:
            return
        out = [d for d, _ in self.notes.links_of(self.editing)] if hasattr(
            self.notes, "links_of") else []
        if not out:
            note = self.notes.read(self.editing)
            out = [d for d, _ in (note.links() if note else [])]
        want = next((t for t in out if self.notes.read(t) is not None), "")
        if not want and self._trail_at > 0:
            want = self._trail[self._trail_at - 1]
        if want:
            self.open_side(want)

    def open_side(self, title: str) -> None:
        note = self.notes.read(title)
        if note is None:
            return
        self.side_open = True
        self.side_read.show_note(title, note.body.strip())
        self._place_reader()

    def close_side(self) -> None:
        self.side_open = False
        self.side_read.hide()
        self._place_reader()

    def show_note_at(self, where: str) -> None:
        """**그 파일**을 연다. 제목이 겹칠 때 우리가 몰래 고르지 않는다."""
        note = self.notes.read_at(where)
        if note is None:
            return
        self._mark_trail(note.title)
        self.ensure_on_graph([note.title])
        self._fill_detail(note, where)
        self.report(f"{note.title} 얘기야.", [note.title])

    def _fill_toc(self, body: str) -> None:
        """목차를 채운다. 소제목이 둘 미만이면 안 띄운다 — 한 줄짜리 목차는 짐이다."""
        heads = headings(body)
        self.toc.clear()
        if len(heads) < 2:
            self.toc.hide()
            return
        self.toc.addItem(f"목차 ({len(heads)})", "")
        for depth, text in heads:
            self.toc.addItem("   " * (depth - 1) + text, text)
        self.toc.setCurrentIndex(0)
        self.toc.show()
        # ★ **채운 뒤에는 접기를 다시 셈한다.** 안 하면 폭을 안 보고 무조건 띄워서,
        # 좁은 카드에서 항목을 열면 목차가 **있으면 안 될 자리에 떠 있다**(위 줄이
        # 밀려 글자가 겹치는 것을 막으려고 접는 것인데 그게 무력해진다).
        # 시험 쪽은 이걸 「나란히 보기를 끈 뒤 목차가 안 돌아온다」로 봤는데,
        # 실은 **끈 뒤가 맞고 처음부터 떠 있던 쪽이 틀린 것**이었다.
        if (폭 := self.detail_card.width()) > 40:
            self._trim_tools(폭)

    def open_daily(self) -> None:
        """오늘 일지. 없으면 서식대로 만들어 연다."""
        # ★ 단축키·차림표 신호에서 불린다 — 쓰기 막힘이 새면 PyQt 가 프로세스를 끝낸다(ask 설명 참고).
        #   장식은 이런 자리에서 창 검사를 강제 종료시킨 적이 있어(new_note 참고) 직접 받는다.
        try:
            note = self.notes.daily()
        except WriteBlocked:
            self.report("오늘 일지를 못 만들었어 — 기록 폴더가 읽기 전용이거나 딴 프로그램이 잡고 있어.", [ROOT])
            return
        self.notes.reindex()
        self.show_note(note.title)
        # 일지는 열자마자 쓰려는 것이다 — 새 글과 같은 까닭(시험 쪽 다-3).
        self._고치기로()
        self.detail_body.setFocus()

    def make_report(self) -> None:
        """진단 묶음을 만들고 어디 뒀는지 말해 준다.

        **딴 PC 에서 난 일은 우리가 못 본다.** 쓰는 사람이 폴더를 뒤질 필요 없이
        파일 하나를 보내면 되게 한다. 기록 내용·토큰·사용자 이름은 안 담는다.
        """
        try:
            made = report.bundle()
        except OSError as err:
            self.report(f"진단 묶음을 못 만들었어: {err}", [ROOT])
            return
        self.report(f"진단 묶음을 만들었어 → {made.name}  (앱 자리에 있어)", [ROOT])
        # `QMessageBox.information` 은 **손도 안 댄 윈도우 기본 대화상자**로 뜬다 —
        # 파란 i 아이콘·기본 고딕·「OK」. VC 안에서 제일 이질적이라는 지적을 받았다.
        # 확인창과 같은 길로 보낸다.
        self._told("진단 묶음",
                   "이 파일 하나만 보내면 된다:" + chr(10) * 2 + str(made) + chr(10) * 2
                   + "기록 내용·토큰·사용자 이름은 안 들어 있다.")

    def _build_more(self) -> None:
        """`⋯` 차림표. 열 때마다 새로 짓는다 — 서식이 늘거나 줄 수 있다."""
        self.more_menu.clear()
        self.more_menu.addAction(f"새 항목  ({_키글('Ctrl+N')})", self.new_note)
        self.more_menu.addAction(f"오늘 일지  ({_키글('Ctrl+D')})", self.open_daily)
        # ★ **접힌 목차를 여기로 옮긴다.** 카드가 좁으면 위 줄에서 목차를 숨기는데,
        # 여기에도 안 넣어서 **소제목으로 갈 길이 통째로 사라졌다**(시험 쪽 라-③ —
        # 「목차 UI 가 안 보이고 ⋯ 메뉴에도 없다」). 접는 것은 자리를 아끼려는
        # 것이지 **기능을 없애려는 것이 아니다.** 옵시디언도 좁으면 접어 넣지 없애지 않는다.
        # `isHidden()` 을 쓴다 — `isVisible()` 은 **부모 카드가 안 떠 있을 때도**
        # False 라, 위 줄에 멀쩡히 있는 목차를 차림표에 겹쳐 넣게 된다.
        if self.toc.count() > 1 and self.toc.isHidden():
            차례 = self.more_menu.addMenu(self.toc.itemText(0))
            for i in range(1, self.toc.count()):
                차례.addAction(self.toc.itemText(i),
                             lambda _=False, n=i: self._jump_heading(n))
        names = self.notes.templates()
        if names and self.editing is not None:
            forms = self.more_menu.addMenu("서식 넣기")
            for name in names:
                forms.addAction(name, lambda n=name: self._put_template(n))
        if self.editing is not None:
            self.more_menu.addSeparator()
            gone = self.more_menu.addAction("지우기", self.drop_note)
            gone.setToolTip("이 항목을 지운다. 파일이 사라진다")
        self.more_menu.addSeparator()
        self.more_menu.addAction(f"설정 · 내 정보  ({_키글('Ctrl+,')})",
                                 lambda: self._later(lambda: settings.open_dialog(self, self.notes)))
        self.more_menu.addAction("전체화면  (F11)", lambda: settings.toggle_full(self))
        self.more_menu.addAction("문제 알리기 (진단 묶기)", self.make_report)

    def _put_template(self, name: str) -> None:
        # 차림표에서 불린다. 여기서 글을 갈아 끼우면 차림표가 제 밑을 파므로 미룬다.
        self._later(lambda: self._do_put_template(name))

    def _do_put_template(self, name: str) -> None:
        """서식을 지금 글 **끝에** 끼운다. 덮어쓰지 않는다 — 쓰던 글이 사라지면
        되돌릴 길을 찾느라 서식을 다시는 안 쓴다."""
        if not name or self.editing is None:
            return
        text = self.notes.fill_slots(self.notes.template(name), self.editing)
        if not text:
            return
        if self.detail_stack.currentIndex() != 1:
            self.toggle_edit()
        cur = self.detail_body.textCursor()
        cur.movePosition(QTextCursor.End)
        self.detail_body.setTextCursor(cur)
        self.detail_body.insertPlainText(chr(10) * 2 + text + chr(10))
        self.save_note()

    def _show_twin(self, title: str, where: str = "") -> None:
        """같은 제목이 둘 이상이면 **어느 파일인지 밝힌다.**

        조용히 하나를 골라 열면, 2027년 회의를 열었다고 믿고 2026년 것을 고친다.
        """
        twins = self.notes.twins(title)
        if not twins:
            self.twin_note.hide()
            return
        here = Path(where) if where else self.notes.path_of(title)
        try:
            shown = here.relative_to(self.notes.root).as_posix()
        except ValueError:
            shown = here.name
        self.twin_note.setText(f"⚠ 같은 제목 {len(twins)}개 · 지금 연 것: {shown}")
        self.twin_note.setToolTip(chr(10).join(str(t) for t in twins))
        self.twin_note.show()

    def _fill_past(self, title: str) -> None:
        """지난 판 목록을 채운다. 없으면 안 띄운다."""
        self.past.clear()
        rows = self.notes.history(title)
        if not rows:
            self.past.hide()
            return
        self.past.addItem(f"지난 판 ({len(rows)})", "")
        for when, path in rows:
            self.past.addItem(when, str(path))
        self.past.setCurrentIndex(0)
        self.past.show()

    def _restore_past(self, at: int) -> None:
        """되돌리기는 **신호가 끝난 뒤에** 한다.

        이 함수는 콤보의 `activated` 신호로 불린다. 그 안에서 항목을 다시 열면
        `_fill_past` 가 같은 콤보를 `clear()` 하는데, **자기 신호를 처리하는 중에
        자기를 비우면 Qt 가 접근 위반으로 죽는다.** 무작위로 눌러 보다 실제로
        세그폴트가 났다. 한 박자 미뤄서 신호를 먼저 끝낸다.
        """
        self._later(lambda: self._do_restore_past(at))

    @_쓰기막히면알림()
    def _do_restore_past(self, at: int) -> None:
        where = self.past.itemData(at)
        self.past.setCurrentIndex(0)
        if not where or self.editing is None:
            return
        when = self.past.itemText(at)
        if not self._agreed(
                "지난 판으로 되돌리기",
                f"'{self.editing}'을 {when} 판으로 되돌린다. "
                "지금 글도 한 판 남으니 다시 돌아올 수 있다.", "되돌린다"):
            return
        title = self.editing
        if self.notes.restore(title, Path(where)):
            self.show_note(title)
            self.report(f"{when} 판으로 되돌렸어.", [title])

    def _jump_heading(self, at: int) -> None:
        # 콤보의 신호 안에서 콤보를 건드리지 않는다(위 `_restore_past` 설명 참고).
        self._later(lambda: self._do_jump_heading(at))

    def _do_jump_heading(self, at: int) -> None:
        want = self.toc.itemData(at)
        if not want:
            return
        box = (self.detail_body if self.detail_stack.currentIndex() == 1
               else self.detail_view)
        box.go_to_heading(want)
        self.toc.setCurrentIndex(0)     # 다음에 또 같은 데를 고를 수 있어야 한다

    def flip_task(self, nth: int) -> None:
        """읽는 화면에서 할 일 표를 눌렀다. 신호가 끝난 뒤에 뒤집는다."""
        self._later(lambda: self._do_flip_task(nth))

    @_쓰기막히면알림()
    def _do_flip_task(self, nth: int) -> None:
        """원문을 뒤집고 바로 저장한다.

        `고치기`로 들어가 글자를 바꾸게 하면 할 일 목록은 안 쓰게 된다.
        """
        if self.editing is None:
            return
        # 뒤집고 쓰는 사이 덧붙인 줄이 이력 없이 사라지지 않게 잠근다.
        with self.notes._글잠금(self.editing):
            note = self.notes.read_at(self.editing_at)
            if note is None:
                return
            out = flip_task(note.body, nth)
            if out is None:
                return
            note.body, note.edited_by = out[0], "사람"
            self._wrote_at = time.monotonic()
            self.notes.write(note, self.editing_at)
            # 보이는 것도 같이 바꾼다. 눌렀는데 그대로면 안 먹은 줄 안다.
        at = self.detail_view.verticalScrollBar().value()
        self.detail_view.show_note(note.body)
        self.detail_view.verticalScrollBar().setValue(at)
        # **고치는 칸도 같이 고친다.** 안 하면 다음에 「고치기」로 들어갔다 나올 때
        # 네모를 모르는 옛 글이 덮어써서 체크가 풀린다 — 낯선 PC 에서 그렇게 났다.
        self.detail_body.setPlainText(note.body.strip())

    @_쓰기막히면알림()
    def rename_note(self) -> None:
        """제목을 바꾸면 **가리키던 링크도 같이 옮긴다**(notes.rename)."""
        # ★ 친 제목을 **저장될 꼴**로 먼저 맞춘다(맥 한글·`? :` 같은 글자는 전각). 안 맞추면
        #   화면이 들고 있는 이름과 파일의 이름이 달라져 그물·뒤로가기가 옛 글자를 찾는다.
        new = notes_module.제목맞춤(self.detail_title.text().strip())
        if self.editing is None or not new or new == self.editing:
            return
        self.detail_title.setText(new)
        if not self.notes.rename(self.editing, new):
            self.detail_title.setText(self.editing)   # 이미 있는 이름이면 되돌린다
            self.report(f"'{new}'{orders.tail(new, '은/는')} 이미 있어. 다른 이름으로 해줘.", [ROOT])
            return
        # ★ **뒤로가기 줄에 옛 이름이 남으면** 뒤로 갔을 때 없는 글을 찾는다. 같이 옮긴다.
        self._trail = [new if t == self.editing else t for t in self._trail]
        self.editing = new
        # **연 파일도 같이 옮겨졌다.** 옛 자리를 계속 들고 있으면 그 뒤로 저장이
        # 조용히 실패한다 — `read_at()` 이 없는 파일에 None 을 주고 그대로 돌아선다.
        # 낯선 PC 에서 "쓴 글이 디스크에 안 내려간다"로 잡힌 자리다.
        self.editing_at = str(self.notes.path_of(new))
        self.refresh()
        self._fill_links(new)

    def _told(self, head: str, body: str) -> None:
        """알리기만 하는 창. Qt 기본 것은 파란 아이콘·영문 단추로 혼자 튄다."""
        box = QMessageBox(QMessageBox.NoIcon, head, body, QMessageBox.NoButton, self)
        box.addButton("알았어", QMessageBox.AcceptRole)
        box.exec_()

    def _agreed(self, head: str, body: str, yes_word: str) -> bool:
        """한국어 확인창. Qt 기본 단추는 `Yes`/`No` 영문이라 여기만 튀었다.

        단추에 **무슨 일이 일어나는지**를 적는다 — "예/아니오"보다 "지운다/그만둔다"가
        누르기 전에 읽힌다.
        """
        box = QMessageBox(QMessageBox.NoIcon, head, body, QMessageBox.NoButton, self)
        go = box.addButton(yes_word, QMessageBox.AcceptRole)
        box.addButton("그만둔다", QMessageBox.RejectRole)
        box.setDefaultButton(box.buttons()[1])
        box.exec_()
        return box.clickedButton() is go

    def new_note(self) -> None:
        """빈 항목을 만들고 제목부터 치게 한다."""
        title, n = "새 항목", 2
        # ※ 이 메서드는 장식(`_쓰기막히면알림`)을 못 씌운다 — 씌우면 창 검사가 강제 종료됐다(가르기로 찾음).
        #   그래서 여기서 직접 받는다.
        # ★ 「없다」고 본 뒤 쓰기 전에 AI 가 같은 제목을 쓰면 빈 글로 덮는다 — 잠그고 다시 본다.
        while True:
            with self.notes._글잠금(title):
                if self.notes.read(title) is None:
                    try:
                        self.notes.write(Note(title=title, body="", kind="note"))
                    except WriteBlocked:
                        self.report("못 썼어 — 기록 폴더가 읽기 전용이거나 딴 프로그램이 잡고 있어.", [ROOT])
                        return
                    break
            title, n = f"새 항목 {n}", n + 1
        self.refresh()
        self._fill_detail(self.notes.read(title))
        # ★ **새로 만든 글은 쓰려고 만든 것이다.** 읽기 모드로 열면 「고치기」를 한 번
        #   더 눌러야 본문을 칠 수 있다 — 옵시디언은 Ctrl+N 하면 바로 쓴다. 매일 쓰는
        #   동작이라 여기 한 번이 제일 먼저 지겨워진다(시험 쪽 다-1·7).
        self._고치기로()
        self.detail_title.setFocus()
        self.detail_title.selectAll()
        self.graph.focus_on([title], zoom=FOCUS_ZOOM)

    @_쓰기막히면알림()
    def fill_gap(self, title: str) -> None:
        """비어 있던 이름으로 항목을 만든다.

        가리키던 링크가 곧바로 이어진다 — 제목이 열쇠라서 만들기만 하면 붙는다.
        """
        # ★ 「없다」고 본 뒤 쓰기 전에 AI 가 같은 제목을 쓰면 빈 글로 덮는다 — 잠그고 다시 본다.
        with self.notes._글잠금(title):
            있음 = self.notes.read(title) is not None
            if not 있음:
                self._wrote_at = time.monotonic()
                self.notes.write(Note(title=title, body="", kind="note"))
        if 있음:
            self.show_note(title)
            return
        self.refresh()
        self._fill_detail(self.notes.read(title))
        self.detail_body.setFocus()
        self.graph.focus_on([title], zoom=FOCUS_ZOOM)
        self.report(f"{title} 만들었어. 뭘 적을까?", [title])

    @_쓰기막히면알림()
    def drop_note(self) -> None:
        """지운다. 파일이 사라지므로 한 번 묻는다."""
        if self.editing is None:
            return
        gone = self.editing
        가리키던 = [t for t, _ in self.notes.backlinks(gone)]
        꼬리 = (f"{chr(10)}{len(가리키던)}장이 이 글을 가리키고 있어: "
                + " · ".join(가리키던[:3]) + (" 외" if len(가리키던) > 3 else "")) if 가리키던 else ""
        if not self._agreed("지울까?", f"'{gone}' 항목을 지운다. 파일이 사라진다." + 꼬리, "지운다"):
            return
        self._save_timer.stop()
        self.editing = None
        self._wrote_at = time.monotonic()
        self.notes.delete(gone)
        self.clear_detail()
        self.refresh()
        self.report(f"{gone} 지웠어.", [ROOT])

    def open_reader(self) -> None:
        """본문 판을 그래프 위에 띄운다."""
        self._place_reader()
        self.detail_card.show()
        self.detail_card.raise_()

    def _place_reader(self) -> None:
        """그래프 한가운데 자리를 잡는다.

        폭은 **읽을 수 있는 폭**에서 끊는다. 창을 넓힌다고 글줄이 같이 넓어지면
        눈이 줄 끝에서 다음 줄 앞을 못 찾는다(65~75자).
        """
        g = self.graph.geometry()
        if g.width() < 40:
            return
        h = max(280, int(g.height() * 0.88))
        top = g.y() + (g.height() - h) // 2
        if self.side_open:
            # 둘로 나눈다. 글줄 폭은 각자 620에서 끊는다 — 좁아도 읽을 수는 있어야 한다.
            span = min(1300, int(g.width() * 0.94))
            gap = 12
            each = max(300, (span - gap) // 2)
            x = g.x() + (g.width() - (each * 2 + gap)) // 2
            self.detail_card.setGeometry(x, top, each, h)
            self.side_read.setGeometry(x + each + gap, top, each, h)
            self._trim_tools(each)
        else:
            w = min(880, max(420, int(g.width() * 0.74)))
            # 좌표는 부모(left) 기준이다 — graph.geometry()가 그 기준이라 그대로 쓴다.
            self.detail_card.setGeometry(g.x() + (g.width() - w) // 2, top, w, h)
            self._trim_tools(w)

    def _trim_tools(self, width: int) -> None:
        """카드가 좁으면 위 줄에서 덜 급한 것부터 접는다.

        곁에 띄우면 폭이 절반이 되는데, 그때 위 줄 항목들이 서로 밀려 **글자가
        겹쳐 잘린다** — 낯선 PC 에서 「지난 판 (2」로 괄호가 잘리고 「열매」가
        「열애」로 보였다. 넓을 때는 안 드러나고 좁힐 때만 드러나는 자리다.

        접는 차례는 **덜 쓰는 것부터**다. 「고치기」와 `⋯` 는 끝까지 남긴다.
        """
        tight = width < 560
        for widget in (self.past, self.toc):
            widget.setVisible(widget.count() > 1 and not tight)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.detail_card.isVisible() or self.side_open:
            self._place_reader()

    def clear_detail(self) -> None:
        self.detail_card.hide()
        self.shut_btn.hide()
        self.toc.clear()
        self.toc.hide()
        self.past.clear()
        self.past.hide()
        self.side_btn.hide()
        self.side_open = False
        self.side_read.hide()
        self.twin_note.hide()
        self._save_timer.stop()
        self.editing = None
        self.editing_at = ""
        self.detail_kind.hide()
        self.detail_title.clear()
        self.detail_title.setReadOnly(True)
        self.detail_body.clear()
        self.detail_body.setReadOnly(True)
        self.detail_view.clear()
        self.detail_stack.setCurrentIndex(0)
        self.edit_btn.hide()
        self.detail_links.clear()
        self.embeds.show_hits([])
        self.embeds_head.hide()
        self.embeds.hide()
        self.backs.show_hits([])
        self.backs_head.hide()
        self.backs.hide()
        self.mentions.show_hits([])
        self.mentions_head.hide()
        self.mentions.hide()

    def _paint_say(self) -> None:
        """말하는 칸을 다시 그린다. **커서는 색만 껐다 켠다.**

        ★★ 전에는 꼬리를 켜짐 `"  ▍"` · 꺼짐 `"   "` 로 **바꿔 찍었다.** 두 꼬리의
        폭이 11.3px 다르다 — 줄바꿈이 켜진 칸이라 그 차이가 **높이 40 ↔ 46px** 로
        번지고, 이 칸이 세로로 쌓여 있어 **0.6초마다 위의 그래프까지 통째로 밀렸다.**
        오너가 창을 보고 「깜박일 때마다 움찔거린다」고 두 번 짚은 자리다.

        같은 폭의 안 보이는 글자를 찾아봤지만 없다(정확히 같은 폭은 블록 글자뿐인데
        그건 보인다). 그래서 **글자는 늘 그 자리에 두고 색만 바꾼다** — 폭이 안 변하니
        높이도 안 변하고, 아무것도 안 흔들린다.

        ※ 서식 글이라 `<`·`&` 는 감싸 주고, 줄바꿈은 `<br>` 로 바꾼다. 빈칸 둘은
          서식 글에서 하나로 줄어들어 `&nbsp;` 로 적는다.
        """
        빛 = theme.T.TEXT.name() if self._caret_on else "transparent"
        몸 = html.escape(self._say_text).replace("\n", "<br>")
        self.say.setText(f'{몸}&nbsp;&nbsp;<span style="color:{빛}">▍</span>')

    def _blink(self) -> None:
        self._caret_on = not self._caret_on
        self._paint_say()

    def _log_deed(self, what: str, said: str, started: float) -> None:
        """시킨 것을 「활동」 칸에 한 줄 남긴다. 화면이 하는 일도 활동이다."""
        try:
            self.store.add_log({
                "instruction_id": f"손-{int(started * 1000)}",
                "seq": 0,
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "phase": "done",
                "tier": "pc",
                "outcome": "success",
                "module": what,
                "step": said[:60],
                "latency_ms": int((time.monotonic() - started) * 1000),
                "detail": {},
            })
            # **써 넣기만 하면 화면은 모른다.** 그 칸은 훑기가 끝날 때 다시 그려지는데,
            # 시킴말은 훑기를 안 거치는 길이라 영영 안 그려졌다 — 기록은 쌓이는데
            # 화면만 빈 채로 남았다. 여기서 바로 넘긴다.
            self.feed.show_rows(self.store.recent(9))
        except Exception as err:
            # **말없이 삼키지 않는다.** 이 칸이 빈 채로 남았을 때, 못 쓴 것인지 쓰고도
            # 화면이 안 읽은 것인지 갈 길이 없어서 한 판을 헛돌았다. 시킨 일은 그대로
            # 두되(남기다 실패했다고 무를 이유는 없다) **왜 못 썼는지는 남긴다.**
            report.log_crash(err)

    def _log_turn(self, order: str, reply: str, kind: str, started: float) -> None:
        """무엇을 듣고 뭐라 답했는지 남긴다. 음성이 이상할 때 여기만 보면 갈린다."""
        last = getattr(self.voice, "_last", {}) if self.voice is not None else {}
        took = {"처리": round(time.monotonic() - started, 2)}
        if last.get("spoke_at"):
            # 말이 끝난 뒤 답까지 — 사용자가 느끼는 지연은 이것 하나다.
            took["지연"] = round(time.monotonic() - last["spoke_at"], 2)
        if last.get("listen"):
            took["대기+듣기"] = last["listen"]
        talklog.record(
            heard=last.get("heard", order), woke=last.get("woke", True),
            order=order, reply=reply, kind=kind, took=took,
            stt=last.get("stt", "키보드"), audio=last.get("audio", ""),
            peak=last.get("peak"), clipped=last.get("clipped"),
        )
        if self.voice is not None:
            self.voice._last = {}

    def report(self, text: str, touching: list[str], aloud: bool = True) -> None:
        """VC가 말한다. 딛고 있는 항목들이 순서대로 밝아진다.

        음성으로 켜져 있으면 소리로도 답한다 — 말로 물었는데 글자로만 답하면
        화면을 봐야 하고, 그럼 손을 안 쓰는 의미가 없다.
        """
        self._say_text = text
        self._caret_on = True
        self._paint_say()
        self.graph.speak(touching)

        # 말하는 동안만 달아오른다. 글자 길이로 시간을 어림한다 — 실제 말이 끝나는
        # 시각은 딴 실에 있고, 그걸 기다리자고 화면을 붙잡을 수는 없다.
        self._light_mark(speaking=True)
        QTimer.singleShot(max(1200, 90 * len(text)), self._light_mark)

        if aloud and self.voice is not None and self.mouth is not None:
            # UI를 붙잡지 않게 딴 실에서 말한다. 입은 하나라 겹쳐 말하지 않는다.
            threading.Thread(target=self.mouth.say, args=(text,), daemon=True).start()

    # --- 동작 -----------------------------------------------------------

    def run_analyze(self) -> None:
        found = analyze(self.store.conn)
        made = 0
        for p in found:
            made += self.store.add_proposal_if_new(p)   # 서버 주기 분석과 겹쳐도 하나만(한 문장)
        self.refresh()
        self.report(
            f"점검했어. 고칠 만한 걸 {made}개 찾았어." if made else "점검했어. 지금은 고칠 게 없어.",
            [ROOT],
        )

    def decide(self, pid: str, decision: str) -> None:
        row = self.store.proposal(pid)
        if row is None:
            return

        applied = None
        decl = json.loads(row["declaration"] or "{}")
        # ★ 카드 단추 신호에서 불린다 — 스킬 저장이 막혀 `WriteBlocked` 가 새면 PyQt 가 프로세스를 끝낸다.
        #   막히면 결정을 안 적고(제안은 그대로 남아 다시 누를 수 있다) 까닭을 말한다.
        try:
            if decision.startswith("pick:"):
                # 사용자가 고른 모듈에 그 말을 배운다. 후보 목록은 버린다.
                chosen = decision.split(":", 1)[1]
                applied = self.skills.save(
                    Skill(name=chosen, examples=decl.get("examples", []))
                )
            elif decision == "approve" and decl.get("name"):
                applied = self.skills.save(Skill(**{k: v for k, v in decl.items()
                                                    if k in Skill.__dataclass_fields__}))
        except WriteBlocked:
            self.report("스킬을 못 저장했어 — 기록 폴더가 읽기 전용이거나 딴 프로그램이 잡고 있어. 제안은 그대로 둘게.",
                        [ROOT])
            return
        self.store.decide(pid, decision)
        self.refresh()

        if applied and applied.examples:
            self.report(f"'{applied.examples[-1]}'"
                        f"{orders.tail(applied.examples[-1], '은/는')} {applied.name}. "
                        f"이제 안 물어볼게.",
                        [applied.name, ROOT])
        elif applied:
            self.report(f"{applied.name}, 다음부터 그렇게 할게.", [applied.name, ROOT])
        else:
            self.report("알겠어, 넘어갈게.", [ROOT])


def main() -> None:
    app = QApplication(sys.argv)
    notes = Notes("data/notes", "notes_index.db")
    win = MainWindow(notes, Store("eb.db"))
    win.show()
    sys.exit(app.exec_())


def _self_check() -> None:
    """자체점검은 `ui_check.py` 에 있다 — 여기 두면 722줄이라 정작 돌아가는 코드가
    안 보인다. 부르는 길은 그대로다(`python ui.py --check`)."""
    import ui_check

    ui_check.run()


if __name__ == "__main__":
    if "--check" in sys.argv:
        _self_check()
    else:
        main()
