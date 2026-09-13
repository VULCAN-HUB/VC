"""`ui.py` 자체점검.

화면 없이 띄워 구조만 확인한다. 창을 못 여는 환경에서도 깨지면 바로 안다.

**따로 뒀다.** 검사가 722줄이라 `ui.py` 안에 두면 정작 돌아가는 코드가 안 보인다.
부르는 길은 그대로다 — `python ui.py --check`.
"""
from __future__ import annotations

import math
import os
import pathlib
import sys
import tempfile
import time
from pathlib import Path

from PyQt5.QtCore import QEvent, Qt
from PyQt5.QtGui import QTextCursor
from PyQt5.QtWidgets import QApplication, QComboBox, QShortcut, QToolButton

# 앱을 여기 붙들어 둔다 — 창보다 늦게 죽어야 한다(아래 `run` 설명 참고).
_앱 = None

import notes as notes_module
import paths
import talklog
import theme
import ui
from graph3d import FOCUS_ZOOM, OLD_ROOT, ROOT
from notes import Note, Notes, flip_task, headings, section
from panels import ServerLink
from store import Store
from ui import GRAPH_LIMIT, MainWindow
from ui import ModelPicker, QLabel, QPushButton, RemoteGateCard

from panels import PROPOSAL_AREA_MIN_H
from PyQt5.QtCore import QRectF

def run() -> None:
    """화면 없이 띄워 구조만 확인한다. 창을 못 여는 환경에서도 깨지면 바로 안다."""
    import os
    import tempfile

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    # ★ **앱이 창보다 먼저 죽으면 프로세스가 통째로 끝난다.**
    # `app` 을 이 함수의 지역 변수로만 두면, 함수가 끝날 때 앱이 먼저 죽고 남은
    # 창들이 그 뒤에 죽는다 — Qt 가 이미 없는 것을 만져 접근 위반이 난다.
    # 여덟 번 돌려 세 번 그랬고, 자국은 늘 `run()` 이 끝난 자리를 가리켰다.
    #
    # 모듈에 붙들어 **맨 마지막에 죽게** 한다. (창을 먼저 `deleteLater` 로 치우는
    # 쪽도 재 봤는데 **여덟에 여덟이 죽어서** 더 나빴다. 그건 안 쓴다.)
    global _앱
    _앱 = QApplication.instance() or QApplication([])
    app = _앱

    with tempfile.TemporaryDirectory() as tmp:
        notes = Notes(Path(tmp) / "notes")
        store = Store(":memory:")
        # 검사가 진짜 대화 기록을 더럽히면 안 된다. 사용자 파일은 사용자 것이다.
        talklog.LOG_PATH = Path(tmp) / "talk.jsonl"

        # 옛 이름으로 쌓아 둔 기록은 켤 때 한 번 옮겨진다 — 쓰던 사람의 그래프에서
        # 가운데가 통째로 끊기면 안 된다. 자기 기록으로만 검사한다.
        from graph3d import OLD_ROOT
        old = Notes(Path(tmp) / "옛기록")
        old.write(Note(title=OLD_ROOT, body="옛 기록.", kind="agent", pinned=True))
        old.write(Note(title="옛 메모", body=f"[[{OLD_ROOT}]]", kind="note"))
        MainWindow(old, Store(":memory:"), ServerLink(config=Path(tmp) / "없는설정.json"))
        assert old.read(OLD_ROOT) is None and old.read(ROOT) is not None, "안 옮겨졌다"

        # ★★ **색인이 없어져도 시작 항목이 하나 더 생기면 안 된다.**
        # 색인만 보고 만들었더니 **색인을 지울 때마다 「VC」가 하나씩 늘었다** —
        # 8월 폴더에 있는데 9월 폴더에 또 만들고, 같은 제목 둘이 되어 ⚠ 가 떴다.
        # 사람에게도 나는 자리다: 색인이 깨지거나, 자리를 옮기거나,
        # 기록만 백업했다 되살릴 때. **색인은 다시 만들 수 있고 파일이 원본이다.**
        뿌리자리 = Path(tmp) / "뿌리"
        첫판 = Notes(뿌리자리)
        MainWindow(첫판, Store(":memory:"), ServerLink(config=Path(tmp) / "없는설정.json"))
        만든것 = list(뿌리자리.rglob(f"{ROOT}.md"))
        assert len(만든것) == 1, [str(x) for x in 만든것]

        # 딴 달 폴더로 옮겨 둔다 — 같은 달이면 덮어써져서 이 결함이 안 드러난다.
        딴달 = 만든것[0].parent.parent / "01"
        딴달.mkdir(parents=True, exist_ok=True)
        만든것[0].rename(딴달 / f"{ROOT}.md")
        # **색인 없이** 다시 뜬다. 진짜 앱이 그렇게 뜬다(`index_now=False`).
        둘째판 = Notes(뿌리자리, index_now=False)
        MainWindow(둘째판, Store(":memory:"), ServerLink(config=Path(tmp) / "없는설정.json"))
        남은것 = list(뿌리자리.rglob(f"{ROOT}.md"))
        assert len(남은것) == 1, ["시작 항목이 늘었다"] + [str(x) for x in 남은것]
        assert old.neighbors("옛 메모") == [ROOT], "옛 링크가 옛 이름을 가리킨다"

        # ★★ **이름이 겹칠 때 「지울 것이 몇 개인지」를 적어야 한다.**
        # 앞서는 **겹친 제목의 가짓수**를 적었다 — 파일이 둘인데 「1개」로 나와,
        # 사람이 파일 하나만 지우면 될 줄 알게 했다. 우연히 맞지만 **뜻이 어긋난다.**
        # 사람이 알고 싶은 것은 **손이 갈 수**다.
        겹친자리 = Path(tmp) / "겹침"
        겹 = Notes(겹친자리)
        # **셋을 만든다.** 둘이면 「제목 가짓수」와 「지울 파일 수」가 똑같이 1 이라
        # 두 셈이 안 갈린다 — 처음에 둘로 만들었더니 검사가 아무것도 못 잡았다.
        for 달 in ("07", "08", "09"):
            칸 = 겹친자리 / "2026" / 달
            칸.mkdir(parents=True, exist_ok=True)
            겹.write(Note(title="회의록", body=f"{달}월 것", kind="note"),
                     at=칸 / "회의록.md")
        겹침 = 겹.duplicates()
        assert 겹침 and 겹침[0][1] == 3, 겹침
        # 「제목 가짓수」(1)가 아니라 **「지울 파일 수」(2)** 다.
        assert len(겹침) == 1 and sum(n - 1 for _, n in 겹침) == 2, 겹침
        창 = MainWindow(겹, Store(":memory:"), ServerLink(config=Path(tmp) / "없는설정.json"))
        # **아래 띠는 `refresh` 가 그린다.** 창을 만든 것만으로는 아직 비어 있어서,
        # 안 부르고 읽으면 이 검사가 그 줄을 아예 안 밟는다 — 실제로 그랬다.
        창.refresh(scan=False)
        띠 = 창.footer.text()
        assert "겹친다" in 띠, 띠
        assert "지울 것 2개" in 띠, 띠

        # **아무것도 안 고른 첫 화면에서 만들 길이 있어야 한다.** 만드는 단추가
        # 항목 카드 안에만 있으면, 카드는 항목을 골라야 뜨므로 처음 받은 사람은
        # 아무것도 못 만든다. 실제로 낯선 PC 에서 그렇게 막혔다.
        fresh = Notes(Path(tmp) / "첫실행")
        first = MainWindow(fresh, Store(":memory:"),
                           ServerLink(config=Path(tmp) / "없는설정.json"))
        first.show()
        first.settle()
        assert not first.detail_card.isVisible(), "고른 것이 없는데 카드가 떠 있다"
        assert first.head_new.isVisible(), "고른 것이 없으면 만들 단추가 사라진다"
        first.head_new.click()
        first.settle()
        assert first.detail_card.isVisible(), "새 항목을 눌렀는데 카드가 안 뜬다"
        assert first.detail_title.text().startswith("새 항목"), first.detail_title.text()
        # **이름을 바꾼 뒤에도 저장돼야 한다.** 이름을 바꾸면 파일이 옮겨지는데
        # 연 파일 자리를 안 고치면 그 뒤 저장이 **조용히** 실패한다 — 낯선 PC 에서
        # "쓴 글이 디스크에 안 내려간다"로 잡혔다. Ctrl+N 하고 제목부터 치는
        # 가장 흔한 길이라 새로 받은 사람이 첫 글부터 잃는다.
        first.new_note()
        first.settle()
        # ★ **새로 만든 글은 고치기 모드로 열린다.** 읽기로 열면 「고치기」를 한 번 더
        #   눌러야 본문을 칠 수 있다 — 매일 하는 동작이라 거기가 제일 먼저 지겨워진다
        #   (시험 쪽 다-1·7). 옵시디언은 Ctrl+N 하면 바로 쓴다.
        assert first.detail_stack.currentIndex() == 1, "새 글이 읽기 모드로 열렸다"
        first.detail_title.setText("이름 바꾼 것")
        first.rename_note()
        first.settle()
        assert Path(first.editing_at).exists(), first.editing_at
        first.detail_body.setPlainText("고친 본문")
        first.toggle_edit()          # 읽기로 나오면서 저장된다
        first.settle()
        wrote = fresh.read("이름 바꾼 것")
        assert wrote is not None and wrote.body.strip() == "고친 본문", "이름 바꾼 뒤 저장이 샌다"
        # ── 읽기 모드에서 친 글자·붙여넣기를 버리지 않는다 ────────────────────
        # ★★ **조용히 버려지던 자리다.** 읽는 칸은 읽기 전용이라 Ctrl+V 가 아무 일도
        #    안 했다 — 화면도 안 바뀌고 말도 없었다. 시험하는 쪽이 「왜 안 들어가지」로
        #    몇 번 더 눌렀다(다-2). **사람이 넣은 것을 말없이 버리는 것**이 이 프로그램
        #    에서 제일 나쁜 짓이라, 모드를 눈치채게 하는 대신 모드가 비키게 했다.
        from PyQt5.QtGui import QKeyEvent

        def 읽기로():
            """어느 모드에 있든 읽기로 맞춘다. toggle 로만 다루면 앞 시험이 어느
            모드로 끝났느냐에 시험이 매달린다."""
            if first.detail_stack.currentIndex() == 1:
                first.toggle_edit()
            first.settle()

        읽기로()
        assert first.detail_stack.currentIndex() == 0, "읽기 모드가 아니다"
        # ★ **메서드를 직접 부르면 배선을 안 잰다.** 앱 거름망(eventFilter)에서 빼도
        #   통과해 버렸다 — 실제로 그랬다. 그래서 **진짜 길**(sendEvent)로 보낸다.
        쳤다 = QKeyEvent(QEvent.KeyPress, Qt.Key_A, Qt.NoModifier, "가")
        QApplication.sendEvent(first.detail_view, 쳤다)
        first.settle()
        assert first.detail_stack.currentIndex() == 1, "치면 고치기로 넘어가야 한다"
        assert "가" in first.detail_body.toPlainText(), "친 글자가 버려졌다"

        # 붙여넣기도 같다. 클립보드에 넣고 실제로 들어오는지 본다.
        읽기로()
        QApplication.clipboard().setText("붙인 글")
        붙임 = QKeyEvent(QEvent.KeyPress, Qt.Key_V, Qt.ControlModifier, "\x16")
        QApplication.sendEvent(first.detail_view, 붙임)
        first.settle()
        assert "붙인 글" in first.detail_body.toPlainText(), "붙여넣은 글이 버려졌다"

        # 단축키는 그대로 흘려보낸다 — Ctrl+F 가 글자로 박히면 안 된다.
        읽기로()
        찾기 = QKeyEvent(QEvent.KeyPress, Qt.Key_F, Qt.ControlModifier, "\x06")
        QApplication.sendEvent(first.detail_view, 찾기)
        first.settle()
        assert first.detail_stack.currentIndex() == 0, "단축키에 고치기로 넘어갔다"

        # ── 아무도 안 건드렸는데 「밖에서도 고쳤길래」가 뜨면 안 된다 ──────────
        # ★ 앞머리를 본문에서 끌어올리면서 **디스크의 본문이 여기 친 것과 달라진다.**
        #   그걸 모르고 친 글을 비교값으로 들고 있으면 다음 저장에서 헛경고가 뜬다.
        #   시험 쪽이 실사용에서 봤다(새-④). 그쪽은 이름 바꾸기를 의심했지만
        #   원인은 이 자리였다 — **관측은 맞았고 짐작은 틀렸다.**
        말한것: list[str] = []
        원래말 = first.report
        first.report = lambda t, touching=(), aloud=True: 말한것.append(t)
        try:
            first.new_note()
            first.settle()
            앞머리 = ("---" + chr(10) + "type: 시험" + chr(10) + "status: 진행"
                      + chr(10) + "---" + chr(10) + "## 첫째" + chr(10) + "몸이다.")
            first.detail_body.setPlainText(앞머리)
            first.save_note()          # 첫 저장 — 여기서 앞머리가 올라간다
            first.settle()
            first.detail_body.setPlainText(앞머리 + chr(10) + "한 줄 더.")
            first.save_note()          # 두 번째 저장 — 헛경고가 나던 자리
            first.settle()

            # ★★ **파일 감시 쪽도 같은 자리에서 태운다.** 실사용에서 뜬 경고는
            #    `save_note` 가 아니라 **`_reload_open`(폴더 감시)** 문구였다 —
            #    처음 고친 자리가 원인이 아니었다. 저장하며 앞머리가 올라가면
            #    디스크 본문이 편집칸 글과 일부러 달라지고, 감시가 그 차이를
            #    「밖에서 고쳤다」로 읽는다(시험 쪽이 「앞머리 없으면 안 난다」로 좁혔다).
            #
            # ★ 이 검사는 **`report` 를 되돌리기 전**에 있어야 한다. 밖에 두었더니
            #   `finally` 가 먼저 돌아 말을 못 듣고 **조용히 통과**했다.
            first.detail_body.setPlainText(앞머리 + chr(10) + "또 한 줄.")
            first.save_note()
            # 사이에 `settle()` 을 넣지 않는다 — 넣으면 감시가 먼저 돌아 편집칸을
            # 디스크 글로 갈아 끼워서 재려던 상태를 스스로 지운다.
            first._reload_open()       # 폴더 감시가 부르는 바로 그 길
        finally:
            first.report = 원래말
        헛것 = [t for t in 말한것 if "밖에서도 고쳤" in t]
        assert not 헛것, "아무도 안 건드렸는데 헛경고가 떴다: " + str(헛것)


        # ── 못 찾았을 때 할 말 ────────────────────────────────────────────
        # ★ 따옴표를 친 사람은 그 말이 있다고 믿고 친 것이다. 0건이면 다음 손이
        #   「따옴표를 떼 본다」인데 사람이 스스로 떠올려야 했다(시험 쪽 다).
        #   그리고 따옴표가 두 겹으로 보이던 것도 여기서 잡는다.
        fresh.write(Note(title="말투 정리", body="소리 내어 읽으면 좋다"))
        fresh.write(Note(title="딴 글", body="소리도 나고 읽으면 좋다"))
        fresh.reindex()
        말 = first._못찾았다고('"소리 읽으면"')
        assert "'\"" not in 말 and "\"'" not in 말, "따옴표가 두 겹이다: " + 말
        assert "따옴표를 떼면" in 말, 말
        민말 = first._못찾았다고("그냥 없는말")
        assert "따옴표를 떼면" not in 민말, 민말
        # 감싸기는 한 자리에서만 한다 — 이미 따옴표면 그대로 둔다
        assert first._감싸기('"이미 따옴표"') == '"이미 따옴표"'
        assert first._감싸기("맨 물음") == "'맨 물음'"
        # ★ **같은 일을 두 군데서 하면 한 군데는 반드시 남는다.** 처음엔 못 찾았을
        #   때만 고쳤고 **찾았을 때 자리에 그대로 남아 있었다**(시험 쪽이 「반만
        #   고쳐졌다」고 짚었다). 날것 감싸기가 다시 생기면 여기서 잡는다.
        군 = pathlib.Path(__file__).with_name("ui.py").read_text(encoding="utf-8")
        assert "f\"'{text}'" not in 군, "따옴표를 손으로 감싸는 자리가 다시 생겼다"
        fresh.delete("말투 정리"); fresh.delete("딴 글")

        fresh.delete("이름 바꾼 것")
        first.refresh()

        first.hide()

        # 검사는 바깥 상태에 기대면 안 된다. 진짜 VC가 떠 있으면 화면이 거기 붙어
        # 결과가 달라진다 — 닿을 수 없는 링크를 쥐여 준다.
        win = MainWindow(notes, store, ServerLink(config=Path(tmp) / "없는설정.json"))

        # **검색이 터져도 프로그램은 살아야 한다.** 신호 안에서 처리 안 된 예외가
        # 나면 PyQt5 는 프로세스를 죽인다 — 낯선 PC 에서 검색 엔터 한 번에 여섯 번
        # 죽었고, 죽음 기록에는 한 줄도 안 남았다.
        import report as report_module
        os.environ["VC_DATA"] = tmp
        try:
            boom = win._ask
            win._ask = lambda text: (_ for _ in ()).throw(RuntimeError("찾다 터졌다"))
            win.ask("아무거나")           # 여기서 예외가 새 나가면 실전에선 죽는다
            win._ask = boom
            died = (Path(tmp) / report_module.DEATH).read_text(encoding="utf-8")
            assert "찾다 터졌다" in died, "찾다 죽은 것이 안 남았다"
        finally:
            del os.environ["VC_DATA"]

        # **`연/월` 폴더도 지켜봐야 한다.** 뿌리만 보면 옵시디언으로 고친 글이
        # 화면에 영영 안 나타난다 — 낯선 PC 에서 그렇게 잡혔다.
        first.new_note()
        first.settle()
        deep = Path(first.editing_at).parent
        assert deep != fresh.root, "새 항목이 연/월 폴더에 안 들어갔다"
        first._rewatch()
        assert str(deep) in first._watch.directories(), first._watch.directories()

        # **떠 있는 창은 주 창 하나뿐이어야 한다.** 어느 칸에도 안 넣은 위젯을
        # `show()` 하면 그게 독립 창이 된다 — 낯선 PC 에서 「지우기」만 든 조각 창이
        # 뜨고, 주 창을 닫아도 그것 때문에 프로세스가 안 죽었다.
        first.new_note()
        first.settle()
        loose = [w for w in QApplication.topLevelWidgets()
                 if w.isVisible() and w is not first and not w.parent()]
        assert not loose, [type(w).__name__ + ":" + w.windowTitle() for w in loose]

        # **Esc 는 `[[` 목록부터 닫는다.** 창 단축키가 글상자보다 먼저 발동하므로,
        # 목록 쪽에만 Esc 를 넣으면 그 자리를 영영 안 지난다 — 낯선 PC 에서 세 번
        # 연속으로 "Esc 로 안 닫힌다"가 돌아왔다.
        fresh.write(Note(title="이을 것", body="본문", kind="note"))
        first.show_note("이을 것")
        first.settle()
        first.toggle_edit()
        first.settle()
        first.detail_body.setPlainText("[[이")
        cur = first.detail_body.textCursor()
        cur.movePosition(cur.End)
        first.detail_body.setTextCursor(cur)
        first.detail_body._offer_links()
        assert first.detail_body.pop_open(), "목록이 안 떴다"
        # **키가 어느 길로 오든 닫혀야 한다.** 낯선 PC 에서 네 번 연속 안 닫혔고,
        # 고친 세 자리가 셋 다 안 걸렸다. 앱 전체 그물까지 같이 확인한다.
        from PyQt5.QtGui import QKeyEvent

        first.eventFilter(first.detail_body,
                          QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))
        assert not first.detail_body.pop_open(), "앱 전체 그물이 목록을 안 닫는다"
        first.detail_body._offer_links()
        assert first.detail_body.pop_open()

        first.escape()                     # 창 단축키가 부르는 바로 그 길
        first.settle()
        assert not first.detail_body.pop_open(), "Esc 가 목록을 안 닫는다"
        assert first.editing == "이을 것", "목록만 닫아야 하는데 항목까지 닫혔다"
        first.escape()                     # 목록이 닫힌 뒤엔 카드를 닫는다
        first.settle()
        assert first.editing is None, "두 번째 Esc 가 카드를 안 닫는다"
        fresh.delete("이을 것")
        first.refresh()

        # **밖에서 온 글을 말없이 덮지 않는다.** 고치는 중에 옵시디언이 같은 파일을
        # 고쳐 놓으면, 우리 글로 덮기 전에 그쪽을 한 판 남겨야 한다 — 낯선 PC 에서
        # 밖에서 온 줄이 파일에도 이력에도 없이 사라졌다.
        fresh.write(Note(title="같이 고친 것", body="처음 글", kind="note"))
        first.show_note("같이 고친 것")
        first.settle()
        first.toggle_edit()
        first.settle()
        first.detail_body.setPlainText("내가 친 글")
        Path(first.editing_at).write_text(
            Path(first.editing_at).read_text(encoding="utf-8").replace("처음 글", "밖에서 온 글"),
            encoding="utf-8")
        first.save_note()
        first.settle()
        assert fresh.read("같이 고친 것").body.strip() == "내가 친 글"
        assert any("밖에서 온 글" in f.read_text(encoding="utf-8")
                   for _, f in fresh.history("같이 고친 것")), "밖에서 온 글이 사라졌다"
        fresh.delete("같이 고친 것")
        first.refresh()

        # **자기가 쓴 것을 남이 쓴 것으로 보면 안 된다.** 두 번째 저장부터 디스크의
        # 내 글이 「연 순간의 글」과도 「새로 친 글」과도 달라서 헛뜬다 —
        # 낯선 PC 에서 아무도 안 건드렸는데 세 번 중 두 번 안내가 떴다.
        fresh.write(Note(title="혼자 고친 것", body="처음", kind="note"))
        first.show_note("혼자 고친 것")
        first.settle()
        first.toggle_edit()
        first.settle()
        said = []
        spoke = first.report
        first.report = lambda text, who=None, aloud=True: said.append(text)
        try:
            for turn in ("첫 고침", "둘째 고침", "셋째 고침"):
                first.detail_body.setPlainText(turn)
                first.save_note()
                first.settle()
        finally:
            first.report = spoke
        assert not [t for t in said if "밖에서도" in t], said
        assert fresh.read("혼자 고친 것").body.strip() == "셋째 고침"
        fresh.delete("혼자 고친 것")
        first.refresh()

        # **모르는 종류를 만나도 그 값을 안 지운다.** 없는 값이면 맨 앞으로 떨어지고
        # 다음 저장에 그것이 파일에 쓰여 남이 적어 둔 값이 사라진다.
        fresh.write(Note(title="남의 종류", body="본문", kind="장소"))
        first.show_note("남의 종류")
        first.settle()
        assert first.detail_kind.currentData() == "장소", first.detail_kind.currentData()
        first.toggle_edit()
        first.settle()
        first.detail_body.setPlainText("고친 본문")
        first.toggle_edit()
        first.settle()
        assert fresh.read("남의 종류").kind == "장소", fresh.read("남의 종류").kind
        # 다음 항목으로 넘어가면 그 자리는 치운다
        fresh.write(Note(title="우리 종류", body="본문", kind="note"))
        first.show_note("우리 종류")
        first.settle()
        assert first.detail_kind.count() == len(theme.KIND_LABEL), first.detail_kind.count()
        fresh.delete("남의 종류")
        fresh.delete("우리 종류")
        first.refresh()

        # **타자로 시킨 말이 실제로 돌아야 한다.** 알아듣는 것(orders.py)과 하는 것을
        # 갈라 뒀으니, 여기서는 「시킨 것이 진짜 벌어지나」만 본다.
        # 나중에 말로 시킬 때 같은 길을 지난다.
        fresh.write(Note(title="회의록", body="처음 줄", kind="note"))
        first.settle()

        first.ask("회의록 열어줘")
        first.settle()
        assert first.editing == "회의록", first.editing

        first.ask("회의록에 두 번째 줄 적어줘")
        first.settle()
        assert "두 번째 줄" in fresh.read("회의록").body, fresh.read("회의록").body

        # **제목 안에 「에」가 있어도 덧붙는다.** 앞에서부터 자르면 제목이 「곁」이
        # 되어 못 찾고 조용히 검색으로 떨어진다 — 사용자는 적힌 줄 안다.
        fresh.write(Note(title="학교에 가는 길", body="처음", kind="note"))
        first.settle()
        first.ask("학교에 가는 길에 우산 챙기기 적어줘")
        first.settle()
        assert "우산 챙기기" in fresh.read("학교에 가는 길").body,             fresh.read("학교에 가는 길").body

        # **짧은 제목이 있어도 긴 쪽을 고른다.** 「학교」와 「학교에 가는 길」이 둘 다
        # 있을 때 짧은 쪽에 붙으면 조각만 엉뚱한 항목에 쌓인다.
        fresh.write(Note(title="학교", body="처음", kind="note"))
        first.settle()
        first.ask("학교에 가는 길에 물병 적어줘")
        first.settle()
        assert "물병" in fresh.read("학교에 가는 길").body, "짧은 제목에 붙었다"
        assert "물병" not in fresh.read("학교").body

        # 붙인 자리와 붙인 글을 그대로 말해 줘야 한다 — 사람 뜻과 글자만으로는
        # 못 가르는 자리라, 틀렸을 때 바로 알아채는 것이 유일한 방어다.
        말 = []
        했던말, first.report = first.report, lambda t, who=None: 말.append(t)
        try:
            first.ask("학교에 안 갔다 적어줘")
            first.settle()
        finally:
            first.report = 했던말
        assert 말 and "안 갔다" in 말[-1] and "무르고" in 말[-1], 말
        fresh.delete("학교")
        fresh.delete("학교에 가는 길")
        first.refresh()

        # **시킨 것이 「활동」 칸에 남아야 한다.** 그 칸은 서버가 남긴 것만 받고 있어서,
        # 타자로 수십 번 시켜도 한 줄도 안 쌓였다 — 「시켜본 게 여기 쌓인다」고 적어
        # 놓고 안 쌓이면 그 칸은 거짓말을 하는 것이다.
        앞 = len(first.store.recent(9))
        # **화면을 비워 놓고 잰다.** 안 그러면 앞서 시킨 것이 남긴 줄이 그대로 있어서,
        # 이번 것이 안 닿아도 검사가 통과한다 — 실제로 그렇게 통과하고 있었다.
        first.feed.show_rows([])
        first.ask("활동칸시험 만들어")
        first.settle()
        assert len(first.store.recent(9)) > 앞, "시킨 것이 활동 칸에 안 남았다"
        # **저장소만 보면 안 된다.** 기록은 쌓이는데 화면이 그것을 안 읽으면 사람에게는
        # 여전히 빈 칸이다 — 낯선 PC 에서 「기록은 164줄인데 화면은 빈 채」로 걸렸다.
        # 시킴말은 **화면을 다시 그린 뒤에** 남기는 길이라, 남기고 나서 따로 넘겨야 한다.
        assert first.feed.rows, "활동 칸 화면이 여전히 비어 있다"
        fresh.delete("활동칸시험")
        first.refresh()

        first.ask("장보기 만들어")
        first.settle()
        assert fresh.read("장보기") is not None, "만들라는데 안 만들었다"

        first.ask("회의록이랑 이어진 것 보여줘")   # 이어진 게 없어도 안 죽어야 한다
        first.settle()

        first.ask("오늘 쓴 것 보여줘")
        first.settle()
        assert first.results.isVisibleTo(first), "오늘 쓴 것이 안 나왔다"

        # **찾는 말은 지시로 새면 안 된다.** 여기가 제일 중요하다 —
        # 검색칸이 곧 지시칸이라, 새면 찾는 길이 막힌다.
        first.ask("처음 줄")
        first.settle()
        assert fresh.read("처음 줄") is None, "찾는 말인데 항목을 만들어 버렸다"

        # **잘못 시킨 것을 무를 수 있어야 한다.** 되묻기까지 거쳐 「지워」를 다시
        # 치게 하면 잘못 시키는 것이 무서워진다 — 무를 길이 있어야 마음 놓고 시킨다.
        first.ask("잘못 만든 것 만들어")
        first.settle()
        assert fresh.read("잘못 만든 것") is not None
        first.ask("무르고")
        first.settle()
        assert fresh.read("잘못 만든 것") is None, "만든 걸 안 물렀다"

        first.ask("회의록에 물러날 줄 적어줘")
        first.settle()
        assert "물러날 줄" in fresh.read("회의록").body
        fresh.append("회의록", "그 사이 AI 가 보탠 줄")   # 무르기 전에 남이 쌓는다
        first.ask("방금 것 취소해")
        first.settle()
        assert "물러날 줄" not in fresh.read("회의록").body, "덧붙인 걸 안 물렀다"
        assert "그 사이 AI" in fresh.read("회의록").body, "무르면서 그 사이 남이 덧붙인 줄까지 지웠다"

        # ★ 말로 시킨 쓰기가 막히면 까닭을 말하고, 죽음 기록에는 안 넣는다.
        말2, 죽음 = [], []
        _옛말, first.report = first.report, lambda t, who=None: 말2.append(t)
        _옛덧, first.notes.append = first.notes.append, lambda *a, **k: (_ for _ in ()).throw(
            notes_module.WriteBlocked("잠김"))
        _옛죽음, ui.report.log_crash = ui.report.log_crash, lambda e: 죽음.append(e)
        try:
            first.ask("회의록에 막힐 줄 적어줘")
            first.settle()
        finally:
            first.report, first.notes.append, ui.report.log_crash = _옛말, _옛덧, _옛죽음
        assert any("못 썼어" in t for t in 말2), f"쓰기가 막혔는데 까닭을 안 말한다: {말2}"
        assert not 죽음, "쓰기 막힘을 죽음 기록에 넣었다"

        first.ask("무르고")            # 두 번 무르면 무를 게 없다
        first.settle()

        for gone in ("회의록", "장보기"):
            fresh.delete(gone)
        first.refresh()

        # **닫는 길이 눈에 보여야 한다.** Esc 는 아는 사람만 쓴다 — 낯선 PC 에서
        # 「카드를 한 장 열면 닫을 길이 없다. 다시 켜는 것 말고 그래프로 돌아갈 길을
        # 못 찾았다」로 걸렸고, 그것 때문에 그날 재려던 것 하나를 통째로 못 쟀다.
        first.show_note(ROOT)
        first.settle()
        assert first.shut_btn.isVisibleTo(first.detail_card), "닫기 단추가 안 보인다"
        first.shut_btn.click()
        first.settle()
        assert not first.detail_card.isVisible(), "닫기 단추가 안 닫는다"

        # 빈 곳을 누르는 것도 닫는 길이다 — 사람이 제일 먼저 해 보는 몸짓이다.
        first.show_note(ROOT)
        first.settle()
        first.graph.empty_clicked.emit()
        first.settle()
        assert not first.detail_card.isVisible(), "빈 곳을 눌러도 안 닫힌다"

        # **아래 줄이 무엇을 센 값인지 밝혀야 한다.** 그냥 「연결 75」로 두었더니
        # `--이음선` 이 뽑아 준 125 와 안 맞아, 시험자가 「72에서 75로 늘었네」로 읽고
        # 헷갈렸다 — 둘이 다른 것을 세는데 이름이 같으면 사람이 못 가린다.
        win.refresh()
        win.settle()
        적힘 = win.footer.text()
        assert "연결" in 적힘 and "적은 것" in 적힘, 적힘

        # ★★ **밖에서 닿는 자리로 열렸으면 창이 그걸 말해야 한다.**
        # 자국과 `--doctor` 에만 적혀 있었는데, 오너는 아이콘을 눌러 켜고 창만 본다.
        # 그리고 **창용 exe 는 콘솔이 없어 켤 때 찍는 말이 갈 데가 없다**(시험 쪽이 잼).
        assert win.열린자리.isHidden(), "안 열렸는데 열렸다고 한다"
        win.열린자리알리기("127.0.0.1", 8765)
        assert win.열린자리.isHidden(), "안에서만 듣는데 밖에 열렸다고 한다"
        win.열린자리알리기("0.0.0.0", 8765)
        assert not win.열린자리.isHidden(), "밖에서 닿는데 창이 아무 말도 안 한다"
        assert "8765" in win.열린자리.text(), win.열린자리.text()

        # ★★ **이름표는 잘려도 되지만 창은 화면에 들어가야 한다.**
        # 위·아래 띄에 값을 하나 더할 때마다 창 최소 폭이 그만큼 커졌고, 한 번은
        # **1624** 까지 가 1366 짜리 노트북에 안 들어갔다. 지금까지는 그 교훈이 주석에만
        # 있었다 — **주석은 다음에 값을 더하는 사람을 안 막는다.** 재어서 막는다.
        잠 = win.minimumSizeHint()
        assert 잠.width() <= 1366, f"창 최소 폭 {잠.width()} — 1366 짜리 화면에 안 들어간다"
        assert 잠.height() <= 1032, f"창 최소 높이 {잠.height()} — 1080 화면에 안 들어간다"

        # 빈 화면에서 VC 하나로 시작한다.
        assert list(win.graph.nodes) == [ROOT], list(win.graph.nodes)
        assert notes.read(ROOT) is not None and notes.read(ROOT).pinned
        # ★ 씨앗은 **프로그램이 만든 글**이라고 적혀 있어야 한다. 안 적으면 흡수의
        #   「사람 손질」 막이가 이걸 사람 글로 보고 첫 흡수를 통째로 막는다.
        assert notes.read(ROOT).extra.get("지은이") == "씨앗", notes.read(ROOT).extra
        assert "항목 01" in win.stats.text()

        # 크기가 층위를 나타낸다: VC > 모듈 > 그 외.
        notes.write(Note(title="카페 단골", body="아이스만. [[VC]]", kind="preference"))
        notes.write(Note(title="제품 검색", body="물건 식별. [[VC]]", kind="skill"))
        win.refresh()
        r_eb = win.graph.nodes[ROOT].r
        r_mod = win.graph.nodes["제품 검색"].r
        r_etc = win.graph.nodes["카페 단골"].r
        assert r_eb > r_mod > r_etc, (r_eb, r_mod, r_etc)
        assert "모듈 01" in win.stats.text()

        # 3차원으로 놓인다 — 한 평면에 눌려 있으면 안 된다.
        for _ in range(120):
            win.graph.step_layout()
        assert win.graph.nodes[ROOT].p == [0.0, 0.0, 0.0], "VC가 한가운데를 벗어났다"
        assert any(abs(n.p[2]) > 1.0 for n in win.graph.nodes.values()), "깊이가 0이면 평면이다"

        # 쌓일수록 구 껍질이 커진다.
        small = win.graph.shell
        for i in range(24):
            notes.write(Note(title=f"자료 {i}", body="[[VC]]", kind="note"))
        win.refresh()
        assert win.graph.shell > small, "항목이 늘어도 구가 안 커진다"

        # 구에 가까워지는가 — 중심에서의 거리가 고르게 모여야 한다.
        for _ in range(400):
            win.graph.step_layout()
        dists = [math.sqrt(sum(x * x for x in n.p))
                 for n in win.graph.nodes.values() if n.title != ROOT]
        avg = sum(dists) / len(dists)
        spread = max(abs(d - avg) for d in dists) / avg
        assert spread < 0.5, f"구 껍질에 안 모였다 (편차 {spread:.2f})"

        # 항목이 늘면 전체가 화면에 담기게 줌 아웃된다 — 대신 하나하나는 작아진다.
        win.graph.settle_view()
        assert win.graph._zoom < 1.0, "항목이 늘었는데 줌 아웃이 안 됐다"
        z = win.graph._zoom
        wide = max(abs(n.pos().x()) + n.r * n.scale() for n in win.graph.nodes.values())
        tall = max(abs(n.pos().y()) + n.r * n.scale() for n in win.graph.nodes.values())
        assert 2 * wide * z <= win.graph.viewport().width() + 1, "가로로 잘린다"
        assert 2 * tall * z <= win.graph.viewport().height() + 1, "세로로 잘린다"
        # 여백만 남기고 물러나면 안 된다 — 한 축은 화면을 절반 넘게 채워야 한다.
        fill = max(2 * wide * z / win.graph.viewport().width(),
                   2 * tall * z / win.graph.viewport().height())
        assert fill > 0.5, f"너무 많이 물러났다 (채움 {fill:.0%})"

        # 회전하면 화면 위치가 바뀐다 — 투영이 실제로 돈다.
        before = win.graph.nodes["제품 검색"].pos()
        win.graph.yaw += 0.9
        win.graph.project()
        assert win.graph.nodes["제품 검색"].pos() != before, "회전이 안 먹는다"

        # 뒤로 간 항목은 작고 흐리게 그려진다.
        scales = [n.scale() for n in win.graph.nodes.values()]
        assert max(scales) > min(scales), "원근이 안 걸렸다"

        # 화면에서도 VC가 제일 크다 — 원근 때문에 뒤집히면 층위가 안 읽힌다.
        def screen_r(node):
            return node.r * node.scale()

        eb_screen = screen_r(win.graph.nodes[ROOT])
        assert all(screen_r(n) < eb_screen for n in win.graph.nodes.values() if n.title != ROOT)

        # 이름표가 서로 겹치지 않고, 남의 원도 덮지 않는다.
        shown = [n for n in win.graph.nodes.values() if n.label.isVisible()]
        boxes = [n.label.sceneBoundingRect() for n in shown]
        overlaps = [(i, j) for i in range(len(boxes)) for j in range(i + 1, len(boxes))
                    if boxes[i].intersects(boxes[j])]
        assert not overlaps, f"이름표가 {len(overlaps)}쌍 겹친다"

        circles = {n.title: n.mapRectToScene(QRectF(-n.r, -n.r, n.r * 2, n.r * 2))
                   for n in win.graph.nodes.values()}
        covered = [(a.title, t) for a, box in zip(shown, boxes)
                   for t, c in circles.items() if t != a.title and box.intersects(c)]
        assert not covered, f"이름표가 남의 원을 덮는다: {covered[:3]}"

        # --- 시키는 말은 실행되고, 찾는 말은 검색된다 ---
        win.graph.clear_focus()
        class Runner:
            """지시만 받아주는 가짜 서버. 나머지 경로는 서버 꺼진 것처럼 군다."""

            reply = {"kind": "result", "text": "볼륨 올렸어", "module": "volume"}

            def call(self, method, path, payload=None):
                return self.reply if path == "/eb/v1/ask" else None

        runner = Runner()
        real_link, win.link = win.link, runner
        win.ask("볼륨 올려")
        assert "볼륨 올렸어" in win.say.text(), win.say.text()

        # 되묻는 말이어도 찾을 게 있으면 검색으로 간다 — 검색칸이 아니게 되면 안 된다.
        runner.reply = {"kind": "clarify", "text": "어느 쪽이야?", "module": None}
        win.ask("카페")
        assert "어느 쪽이야" not in win.say.text(), win.say.text()
        assert win.graph.focus, "검색으로 안 넘어갔다"

        # 찾을 것도 없으면 되묻는 말을 그대로 전한다.
        win.graph.clear_focus()
        win.ask("없는말")
        assert "어느 쪽이야" in win.say.text()
        win.link = real_link
        win.graph.clear_focus()
        win.clear_detail()  # 다음 검사가 깨끗한 상태에서 시작하게

        # --- 초점: 맞는 것만 남고 나머지는 가라앉는다 ---
        win.graph.clear_focus()
        overview_zoom = win.graph._zoom
        win.ask("카페")
        assert win.graph.focus, "초점이 안 잡혔다"
        assert not win.graph.nodes["카페 단골"].dim, "찾은 항목이 가라앉았다"
        assert win.graph.nodes[ROOT].dim, "안 맞는 항목은 이어져 있어도 가라앉아야 한다"
        far = [n for n in win.graph.nodes.values() if n.dim]
        assert far, "나머지가 안 가라앉았다"
        assert all(not n.label.isVisible() for n in far), "가라앉은 항목 이름표가 남았다"
        # 찾아낸 것은 뒤에 있어도 이름이 보여야 한다 — 뭐가 걸렸는지 못 읽으면 소용없다.
        assert win.graph.nodes["카페 단골"].label.isVisible(), "찾은 항목 이름이 안 보인다"

        # 검색만으로는 배율이 고정이다 — 좁힐 때마다 화면이 들썩이면 안 된다.
        win.graph.project()
        win.graph.settle_view()
        assert abs(win.graph._zoom - overview_zoom) < 0.02, (
            f"검색인데 배율이 움직였다 ({overview_zoom:.2f} → {win.graph._zoom:.2f})"
        )
        assert win.detail_title.text() != "카페 단골", "첫 검색은 내용을 펼치지 않는다"

        # 추가 검색 = 좁히기. 이때 내용을 펼치고 1.4로 다가간다.
        win.ask("카페")
        win.graph.project()
        win.graph.settle_view()
        assert abs(win.graph._zoom - FOCUS_ZOOM) < 0.02, f"1.4로 안 갔다 ({win.graph._zoom:.2f})"
        assert win.detail_title.text() == "카페 단골", "내용이 안 펼쳐졌다"

        # 볼일이 끝나면 전체 모습으로 돌아간다.
        win.graph.clear_focus()
        win.graph.settle_view()
        assert not any(n.dim for n in win.graph.nodes.values()), "회색이 안 풀렸다"
        assert abs(win.graph._zoom - overview_zoom) < 0.05, "전체 모습으로 안 돌아왔다"

        # 항목을 직접 누르는 것도 내용을 펼치는 일이다 — 같은 배율로 간다.
        win.show_note("제품 검색")
        win.graph.project()
        win.graph.settle_view()
        assert abs(win.graph._zoom - FOCUS_ZOOM) < 0.02
        assert win.graph.focus == {"제품 검색"}, win.graph.focus
        win.graph.clear_focus()

        # 못 찾으면 초점을 건드리지 않는다 — 엉뚱한 데를 비추면 안 된다.
        win.ask("없는말")
        assert not win.graph.focus and "못 찾겠어" in win.say.text()

        # 말할 때만 발광 효과가 붙는다(성능). 말이 끝나면 떼어 낸다.
        for node in win.graph.nodes.values():
            node.set_speaking(False)
        assert all(n.graphicsEffect() is None for n in win.graph.nodes.values())
        win.show_note("카페 단골")
        lit = [n for n in win.graph.nodes.values() if n.graphicsEffect() is not None]
        assert lit and lit[0].title == "카페 단골", "발광이 딴 데 붙었다"
        assert win.say.text().startswith("카페 단골 얘기야."), win.say.text()
        assert win.detail_kind.currentData() == "preference"

        # 고칠 수 있는 칸이라 본문은 **파일에 있는 그대로** 보인다. 대괄호를 벗겨
        # 보여주면 한 번 고치는 순간 링크가 통째로 날아간다.
        assert "[[" in win.detail_body.toPlainText(), "링크가 사라진 채로 보인다"

        # 제안 승인이 스킬로 남고 화면이 갱신된다.
        store.add_proposal(dict(
            proposal_id="p1", type="skill_update", title="product_search는 pc부터",
            summary="낭비 제거", based_on=["i1", "i2", "i3"],
            declaration={"name": "product_search", "start_tier": "pc"},
        ))
        win.load_proposals()
        assert len(win.proposal_cards) == 1
        win.proposal_cards[0].decided.emit("p1", "approve")
        assert win.proposal_cards == []
        assert win.skills.load("product_search").start_tier == "pc"
        assert "product_search" in win.graph.nodes, "새 모듈이 그래프에 안 떴다"

        # 고르라는 제안은 후보마다 단추가 나오고, 고른 쪽이 그 말을 배운다.
        store.add_proposal(dict(
            proposal_id="p2", type="intervention_proposal", title="매번 되묻는 표현이 있어",
            summary="'그거 좀 해줘'를 3번 되물었어.", based_on=["c1", "c2", "c3"],
            declaration={"candidates": ["제품 검색", "번역"], "examples": ["그거 좀 해줘"]},
        ))
        win.load_proposals()
        # 카드가 반만 보이면 단추를 못 누른다 — 한 장은 온전히 들어가야 한다.
        assert win.proposal_cards[0].sizeHint().height() <= PROPOSAL_AREA_MIN_H, (
            win.proposal_cards[0].sizeHint().height())
        win.proposal_cards[0].decided.emit("p2", "pick:번역")
        learned = win.skills.load("번역")
        assert learned and learned.examples == ["그거 좀 해줘"], learned
        assert "안 물어볼게" in win.say.text()

        # --- 원격 승인 칸: 폰이 없을 때 여기서 문을 연다 ---
        calls: list[tuple] = []

        class FakeLink(ServerLink):
            def __init__(self):
                self.waiting = []

            def call(self, method, path, payload=None):
                calls.append((method, path, payload))
                if path == "/eb/v1/remote/pending":
                    return {"sessions": self.waiting}
                if path == "/eb/v1/engine":
                    return {"kind": "local", "models": ["a", "b"], "loaded": "a"}
                if path == "/eb/v1/remote/approve":
                    return {"ok": payload["code"] == "4242"}
                return None

        fake = FakeLink()
        card = RemoteGateCard(fake, lambda t: None)
        assert not card.isVisible(), "붙으려는 데가 없는데 칸이 떴다"

        fake.waiting = [{"id": "s1", "from": "192.168.43.9", "waiting": 3}]
        card.refresh()
        assert "192.168.43.9" in card.title.text()

        # 네 자리를 다 안 치면 아무 일도 없다.
        calls.clear()
        card.code.setText("42")
        card.approve()
        assert not any(p == "/eb/v1/remote/approve" for _, p, _ in calls), "덜 친 코드가 나갔다"

        # 코드는 사람이 외부 PC 화면을 보고 쳐야 한다 — 서버가 안 알려준다.
        assert all("code" not in str(out or "") for out in [fake.call("GET", "/eb/v1/remote/pending")])

        card.code.setText("4242")
        card.approve()
        assert ("POST", "/eb/v1/remote/approve", {"code": "4242", "by": "내 PC"}) in calls
        assert card.code.text() == "", "친 코드가 화면에 남았다"

        # 서버가 꺼져 있어도 화면은 안 죽는다.
        dead = RemoteGateCard(ServerLink(config="없는파일.json"), lambda t: None)
        dead.refresh()
        assert not dead.isVisible()

        # --- 말로 부르기: 받아쓴 지시가 ask로 그대로 들어간다 ---
        assert win.voice is None and win.mic_button.property("listening") in (None, "false")
        spoken: list[str] = []

        class FakeMouth:
            def say(self, text):
                spoken.append(text)

        win.mouth = FakeMouth()

        class FakeVoice:
            def __init__(self):
                self.stopped = False

            def stop(self):
                self.stopped = True

        win.voice = FakeVoice()  # 켜진 척만 한다 — 검사에 마이크를 쓰지 않는다
        win.report("들었어", [ROOT])
        for _ in range(20):  # 말하는 실이 끝날 때까지
            if spoken:
                break
            time.sleep(0.05)
        assert spoken == ["들었어"], spoken

        # 화면에만 띄우고 싶을 때는 소리를 안 낸다.
        spoken.clear()
        win.report("조용히", [ROOT], aloud=False)
        assert spoken == []

        # 끄면 실을 멈춘다 — 안 멈추면 창을 닫아도 프로그램이 안 꺼진다.
        stub = win.voice
        win.toggle_voice()
        assert stub.stopped and win.voice is None
        assert win.mic_button.property("listening") == "false"
        # 글자를 뺐으니 그림과 설명이 늘 붙어 있어야 한다.
        assert not win.mic_button.icon().isNull()
        assert "말로 부른다" in win.mic_button.toolTip()
        win._set_mic(True)
        assert "듣는 중" in win.mic_button.toolTip()
        win._set_mic(False)

        # 주고받은 것이 기록된다 — 음성이 이상할 때 이 기록만 보면 원인이 갈린다.
        win.link = runner
        runner.reply = {"kind": "result", "text": "볼륨 올렸어", "module": "volume"}
        win.ask("볼륨 올려")
        rows = talklog.read()
        assert rows and rows[0]["order"] == "볼륨 올려", rows
        # 검사는 사용자 기록 파일을 건드리면 안 된다.
        assert talklog.LOG_PATH != Path("data/talk.jsonl")
        assert rows[0]["reply"] == "볼륨 올렸어" and rows[0]["stt"] == "키보드"
        assert "처리" in rows[0]["took"]
        win.link = real_link

        # 모델 고르기: 목록·자동값이 뜨고, 고르면 서버로 나간다(결정 42).
        class ModelLink:
            sent: list = []
            data = {"installed": {"chat": ["a-3b", "b-7b"], "vision": ["v-3b"],
                                  "stt": ["small", "base"], "voice": ["ko-kss"]},
                    "using": {"chat": "a-3b", "vision": "v-3b", "stt": "small", "voice": "ko-kss"},
                    "auto": {"chat": "a-3b", "vision": "v-3b", "stt": "small", "voice": "ko-kss"},
                    "hardware": {"gpu": "테스트GPU", "vram_mb": 4096, "tier": "low",
                                 "note": "4~8GB"}}

            dl = {"catalog": [
                      {"key": "big", "role": "chat", "label": "큰 모델", "size_mb": 5000,
                       "note": "", "installed": False, "heavy": True},
                      {"key": "small", "role": "chat", "label": "작은 모델", "size_mb": 1100,
                       "note": "", "installed": False, "heavy": False},
                      {"key": "gone", "role": "chat", "label": "이미 있음", "size_mb": 100,
                       "note": "", "installed": True, "heavy": False}],
                  "state": "idle", "key": "", "label": "", "percent": 0,
                  "done_mb": 0, "total_mb": 0, "error": "", "busy": False}

            def call(self, method, path, payload=None):
                if path == "/eb/v1/models/download":
                    if method == "GET":
                        return self.dl
                    ModelLink.sent.append(payload)
                    return {"ok": True}
                if path == "/eb/v1/models" and method == "GET":
                    return self.data
                if path == "/eb/v1/models":
                    ModelLink.sent.append(payload)
                    return {"ok": True, "using": self.data["using"]}
                return None

        picker = ModelPicker(ModelLink(), lambda t: None)
        assert "테스트GPU" in picker.hardware.text() and "low" in picker.hardware.text()
        # 첫 항목은 늘 "자동" — 사양이 바뀌면 따라가야 하니 되돌릴 길이 있어야 한다.
        assert picker.boxes["chat"].itemData(0) == ""
        assert "자동" in picker.boxes["chat"].itemText(0)
        assert picker.boxes["chat"].count() == 3, picker.boxes["chat"].count()

        picker.boxes["chat"].setCurrentIndex(2)  # b-7b
        picker._chose("chat")
        assert ModelLink.sent[-1] == {"role": "chat", "name": "b-7b"}, ModelLink.sent

        # 받을 목록: 이미 있는 건 안 보여주고, 버거운 건 표시한다(막지는 않는다).
        labels = [picker.get_list.itemText(i) for i in range(picker.get_list.count())]
        assert len(labels) == 2 and all("이미 있음" not in x for x in labels), labels
        assert any("버거움" in x for x in labels), labels

        ModelLink.sent.clear()
        picker.get_list.setCurrentIndex(1)  # 작은 모델
        picker._get_clicked()
        assert ModelLink.sent[-1] == {"key": "small"}, ModelLink.sent

        # 받는 중에는 진행률만 보이고 목록을 못 건드린다 — 잘못 눌러 둘을 받으면 안 된다.
        picker.link.dl = dict(picker.link.dl, busy=True, state="downloading",
                              label="작은 모델", percent=42, done_mb=462, total_mb=1100)
        picker.refresh_downloads()
        assert "42%" in picker.get_label.text() and not picker.get_list.isEnabled()
        assert picker.get_button.text() == "멈추기"

        ModelLink.sent.clear()
        picker._get_clicked()
        assert ModelLink.sent[-1] == {"cancel": True}

        # 서버가 꺼져 있어도 화면은 안 죽는다.
        blind = ModelPicker(ServerLink(config=Path(tmp) / "없는설정.json"), lambda t: None)
        assert "서버 꺼짐" in blind.hardware.text()
        assert not blind.get_box.isVisible()

        # 엔진 상태가 화면에 뜬다. 서버가 없으면 없다고 말한다(결정 36).
        win.link = fake
        win.refresh_engine()
        assert "a 올라옴" in win.engine_label.text(), win.engine_label.text()
        win.link = ServerLink(config="없는파일.json")
        win.refresh_engine()
        # ★ 「서버 꺼짐」이라고 쓰면 바로 옆 「★ 원격 열림 :8765」와 나란히 떠서
        #   **어느 서버가 꺼진 것인지** 헷갈린다(시험 쪽 지적). 이 줄은 글 모델을 말한다.
        # 서버가 답을 안 하는 갈래다. **모델이 없다고 말하면 안 된다** — 못 물어본 것뿐이다.
        assert "못 물어봤다" in win.engine_label.text(), win.engine_label.text()
        assert "모델" not in win.engine_label.text(), "못 물어본 것을 모델 탓으로 적는다"

        # 활동 흐름이 실제 계측 기록을 읽어 온다 — 근거 없이 굴러가는 것처럼 보이면 안 된다.
        assert win.feed.rows == []
        from eb_protocol import LogEvent

        store.add_log(LogEvent(instruction_id="i9", seq=1, phase="module_run",
                               tier="phone", outcome="failure", module="제품 검색",
                               failure_point="vision_model"))
        win.refresh()
        assert len(win.feed.rows) == 1 and win.feed.rows[0]["module"] == "제품 검색"

        # --- 쓰고 고칠 수 있어야 실무로 쓴다 ---
        win.new_note()
        assert win.editing == "새 항목" and notes.read("새 항목") is not None
        assert not win.detail_body.isReadOnly(), "새로 만들었는데 못 친다"

        # 치면 저장된다. 저장 단추는 없다 — 손을 멈추면 알아서 쓴다.
        win.detail_body.setPlainText("납품 일정 정리. [[카페 단골]] #업무")
        win.save_note()
        again = notes.read("새 항목")
        assert "납품 일정" in again.body, "친 내용이 안 남는다"
        assert notes.by_tag("업무") == ["새 항목"], "태그가 색인에 안 들어갔다"
        assert "카페 단골" in notes.neighbors("새 항목"), "링크가 안 이어졌다"

        # 종류를 바꾸면 그래프 색이 바뀐다 — 색이 곧 정보다.
        win.detail_kind.setCurrentIndex(win.detail_kind.findData("skill"))
        assert notes.read("새 항목").kind == "skill"

        # 제목을 바꾸면 가리키던 링크도 따라간다.
        win.detail_title.setText("납품 일정")
        win.rename_note()
        assert notes.read("새 항목") is None and notes.read("납품 일정") is not None
        assert win.editing == "납품 일정"

        # 이미 있는 이름으로는 못 바꾼다 — 덮어쓰면 기록이 사라진다.
        win.detail_title.setText("카페 단골")
        win.rename_note()
        assert win.editing == "납품 일정", "덮어썼다"
        assert win.detail_title.text() == "납품 일정", "칸이 옛 이름으로 안 돌아왔다"

        # --- 찾고, 눌러서 따라가는 길 ---
        notes.write(Note(title="8월 계획", body="[[카페 단골]] 확인. #팔월/일정", kind="note"))
        notes.write(Note(title="주간 보고", body="정리함. #팔월/일정 #보고", kind="note"))
        win.refresh()

        # 찾으면 제목만이 아니라 **걸린 자리 한 줄**이 같이 뜬다.
        win.ask("아이스")
        assert win.results.items, "찾은 것 목록이 비어 있다"
        assert not win.results.isHidden(), "찾았는데 목록 칸이 접혀 있다"
        assert any("아이스" in w.text() for w in win.results.items if isinstance(w, QLabel)),             "걸린 자리가 안 보인다"

        # ★★ **찾은 것을 눌러 열 수 있어야 한다.** 사람이 제일 많이 하는 일인데
        #   목록이 떴는지만 보고 **누르는 것은 안 재고 있었다.** 카드가 들고 다니는 값이
        #   바뀔 때(갈래를 더하는 등) 조용히 끊길 수 있는 자리다.
        단추 = [w for w in win.results.items if isinstance(w, QPushButton)]
        assert 단추, "찾았는데 누를 단추가 없다"
        win.editing = None
        단추[0].click()
        win.settle()
        assert win.editing == "카페 단골", f"찾은 것을 눌렀는데 안 열린다: {win.editing}"
        # 갈래도 같이 보인다 — 여러 갈래가 섞여 오므로 고를 때 그것이 필요하다.
        줄들 = " ".join(w.text() for w in win.results.items if isinstance(w, QLabel))
        assert "·" in 줄들, f"갈래가 안 보인다: {줄들!r}"

        # 본문의 [[링크]]를 Ctrl로 누르면 그리로 간다.
        win.show_note("8월 계획")
        body = win.detail_body.toPlainText()
        assert win.detail_body._token_at(body, body.index("카페") + 1) == ("link", "카페 단골", "")
        win.follow_link("카페 단골")
        win.settle()
        assert win.editing == "카페 단골", "링크를 따라가지 않았다"

        # 소제목까지 부르면 그 자리로 데려간다 — 긴 글에서 맨 위만 보여주면 소용없다.
        long_body = chr(10).join(["## 7월", "지난 달", "", "## 8월 정산", "여기 봐야 한다"])
        notes.write(Note(title="보고서", body=long_body, kind="note"))
        win.refresh()
        win.follow_link("보고서", "8월 정산")
        win.settle()
        assert win.editing == "보고서"
        assert win.detail_body.textCursor().position() == long_body.index("## 8월 정산"),             win.detail_body.textCursor().position()
        # ★ **읽기 화면(기본)도 그 자리로 가야 한다.** 편집기만 옮겨 읽기 화면은 늘 맨 위였다.
        if win.detail_stack.currentIndex() != 1:
            assert "8월 정산" in win.detail_view.textCursor().block().text(),                 f"읽기 화면이 소제목으로 안 간다: {win.detail_view.textCursor().block().text()!r}"
        notes.delete("보고서")

        # 나가는 링크와 들어오는 링크는 따로 보인다.
        # "내가 적은 것"과 "나를 부른 것"은 다른 정보다.
        win.show_note("카페 단골")
        assert not win.backs.isHidden(), "가리킨 곳이 있는데 칸이 접혀 있다"
        callers = [w.text() for w in win.backs.items if isinstance(w, QPushButton)]
        assert "8월 계획" in callers, callers
        assert "8월 계획" not in win.detail_links.text(), "가리킨 곳이 적어둔 것에 섞였다"

        win.show_note("주간 보고")   # 아무도 안 가리키는 항목
        assert win.backs.isHidden(), "가리킨 곳이 없는데 칸이 떠 있다"

        # 태그를 누르면 그 태그가 붙은 것끼리 모인다. 하위 태그는 상위로도 걸린다.
        win.show_tag("팔월")
        win.settle()
        titles = [w.text() for w in win.results.items if isinstance(w, QPushButton)]
        assert set(titles) == {"8월 계획", "주간 보고"}, titles

        # 없는 이름을 따라가면 그 자리에서 만든다 — 끊긴 채로 두지 않는다.
        win.follow_link("없던 항목")
        win.settle()
        assert notes.read("없던 항목") is not None and win.editing == "없던 항목"
        for gone in ("8월 계획", "주간 보고", "없던 항목"):
            notes.delete(gone)
        win.show_results([])
        win.refresh()

        # --- 많아져도 굳지 않는다 ---
        #
        # 20년치를 다 그리면 물리 계산이 항목 수에 비례해 창이 굳는다. 보이는 수를
        # 묶되, **찾은 것은 반드시 올린다** — 잘려서 안 보이면 "찾았다"가 거짓말이 된다.
        for i in range(GRAPH_LIMIT + 30):
            notes.write(Note(title=f"쌓인 것 {i}", body=f"내용 {i}", kind="note"))
        win.refresh()
        # 상한은 **보이는 것**에 건다. 안 보이는 노드는 다시 나타날 때를 대비해
        # 붙들어 두는 것이라 그리는 값이 안 든다.
        shown = [n for n in win.graph.nodes.values() if n.isVisible()]
        assert len(shown) <= GRAPH_LIMIT, len(shown)
        assert win._total_notes > GRAPH_LIMIT
        assert "보임" in win.footer.text(), win.footer.text()

        # 잘려 나간 항목을 열면 그래프에 올라온다.
        far = "쌓인 것 0"
        if far in win.graph.nodes:
            far = next(t for t in (f"쌓인 것 {i}" for i in range(GRAPH_LIMIT + 30))
                       if t not in win.graph.nodes)
        win.show_note(far)
        assert far in win.graph.nodes, "찾은 것이 그래프에 없다"

        for i in range(GRAPH_LIMIT + 30):
            notes.delete(f"쌓인 것 {i}")
        win.clear_detail()
        win.refresh()

        # --- 첨부 ---
        #
        # 붙여넣은 그림은 **파일로 저장**하고 본문엔 표기만 남는다. 본문 안에 통째로
        # 넣으면(base64) 옵시디언·탐색기에서 못 연다 — 파일이 원본인 설계가 깨진다.
        notes.write(Note(title="사진 글", body="현장:"))
        win.refresh(); win.show_note("사진 글"); win.toggle_edit()
        png = bytes.fromhex("89504e470d0a1a0a") + b"fake"
        win.paste_image(png, ".png")
        body = notes.read("사진 글").body
        assert "![[" in body and ".png]]" in body, body
        name = body.split("![[")[1].split("]]")[0]
        assert notes.attachment_path(name).read_bytes() == png, "파일로 안 남았다"
        assert name not in dict(notes.unresolved()), "첨부가 미해결로 샜다"

        # 읽기 모습에서는 진짜 그림으로 들어간다.
        md = win.detail_view.to_markdown(body)
        assert "(file:" in md, md
        notes.delete("사진 글")
        win.clear_detail(); win.refresh()

        # 읽기/고치기 전환 — 평소엔 서식이 입혀 보이고 고칠 때만 원문이 뜬다.
        notes.write(Note(title="서식 시험", body=chr(10).join(
            ["# 큰 제목", "", "- 하나", "- 둘", "", "**굵게** 와 [[카페 단골]] 와 #표시"])))
        win.refresh()
        win.show_note("서식 시험")
        assert win.detail_stack.currentIndex() == 0, "열자마자 원문이 보인다"
        html = win.detail_view.toHtml()
        assert "<h1" in html and "<li" in html, "서식이 안 입혀졌다"
        assert "[[" not in win.detail_view.toPlainText(), "대괄호가 그대로 보인다"

        win.toggle_edit()
        assert win.detail_stack.currentIndex() == 1
        assert "[[카페 단골]]" in win.detail_body.toPlainText(), "고칠 땐 원문이어야 한다"

        # 고쳐서 나오면 저장되고, 입힌 모습이 갱신된다.
        win.detail_body.setPlainText("## 바뀐 제목")
        win.toggle_edit()
        assert win.detail_stack.currentIndex() == 0
        assert notes.read("서식 시험").body.strip() == "## 바뀐 제목", "나오면서 저장이 안 됐다"
        assert "바뀐 제목" in win.detail_view.toPlainText()
        notes.delete("서식 시험")
        win.clear_detail()
        win.refresh()

        # 끼워 보기 — 본문은 원문 그대로 두고, 내용은 아래에 펼친다.
        notes.write(Note(title="정산서", body=chr(10).join(
            ["## 7월", "지난달", "", "## 8월", "이번달 잔금 확인"])))
        notes.write(Note(title="요약본", body="핵심: ![[정산서#8월]]"))
        win.refresh()
        win.show_note("요약본")
        assert "![[" in win.detail_body.toPlainText(), "본문에서 원문이 사라졌다"
        assert not win.embeds.isHidden(), "끼운 게 있는데 칸이 접혀 있다"
        pulled = [w.text() for w in win.embeds.items if isinstance(w, QLabel)]
        assert any("잔금" in t for t in pulled), pulled
        assert not any("지난달" in t for t in pulled), "다른 토막까지 끌고 왔다"

        # 없는 것을 끼우면 그렇다고 말한다 — 조용히 비면 왜 안 나오는지 모른다.
        notes.write(Note(title="빈끼움", body="![[없는문서]]"))
        win.refresh()
        win.show_note("빈끼움")
        assert any("아직 없는" in w.text() for w in win.embeds.items if isinstance(w, QLabel))

        for gone in ("정산서", "요약본", "빈끼움"):
            notes.delete(gone)
        win.clear_detail()
        win.refresh()

        # 시간으로도 훑는다 — 20년치에서 "작년 그거"는 글자로 못 찾는다.
        notes.write(Note(title="재작년 견적", body="지난 건", created="2024-05-02T09:00:00Z"))
        win.refresh()
        assert "24" in [b.text() for b in win.years.buttons], [b.text() for b in win.years.buttons]
        win.show_year("2024")
        found = [w.text() for w in win.results.items if isinstance(w, QPushButton)]
        assert found == ["재작년 견적"], found
        notes.delete("재작년 견적")
        win.show_results([])
        win.refresh()

        # 없는 것을 가리키면 "아직 없는 것"에 뜬다 — 사람이 채울 자리 목록이다.
        notes.write(Note(title="계획", body="[[납품 일정]]과 [[견적서]] 확인"))
        notes.write(Note(title="회의", body="[[견적서]] 다시 봄"))
        win.refresh()
        gaps = dict(notes.unresolved())
        assert gaps.get("견적서") == 2, gaps      # 두 곳에서 가리킨다
        assert [b.text().split()[0] for b in win.gaps.buttons][0] == "견적서", "많이 불린 게 위로 안 온다"

        # 눌러서 만들면 가리키던 링크가 곧바로 이어진다.
        win.fill_gap("견적서")
        assert notes.read("견적서") is not None and win.editing == "견적서"
        assert "회의" in notes.neighbors("견적서"), "만들었는데 안 이어진다"
        assert "견적서" not in dict(notes.unresolved()), "만들었는데 아직 없는 것에 남아 있다"

        for gone in ("계획", "회의", "견적서"):
            notes.delete(gone)
        notes.delete("납품 일정")
        win.clear_detail()
        assert win.editing is None and win.detail_body.isReadOnly()
        win.refresh()

        # --- 같은 제목이 두 폴더에 ---
        # **이 길이 막히면 자료가 깨진다**: 2027년 것을 열어 놓고 고쳤는데 2026년
        # 파일에 저장되는 일이 실제로 가능했다.
        for year, what in (("2026", "예산 얘기"), ("2027", "인사 얘기")):
            folder = notes.root / year / "01"
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "회의.md").write_text(what, encoding="utf-8")
        notes.reindex()
        pair = notes.twins("회의")
        assert len(pair) == 2, pair
        keep = pair[0].read_text(encoding="utf-8")
        win.show_note_at(str(pair[1]))
        assert win.editing_at == str(pair[1]), win.editing_at
        assert win.twin_note.isVisibleTo(win.detail_card), "어느 파일인지 안 밝혔다"
        win.toggle_edit()
        win.detail_body.setPlainText("인사 얘기. 덧붙임.")
        win.save_note()
        assert "덧붙임" in pair[1].read_text(encoding="utf-8"), "연 파일에 안 썼다"
        assert pair[0].read_text(encoding="utf-8") == keep, "★ 엉뚱한 파일이 바뀌었다"
        win.clear_detail()
        for gone in pair:
            gone.unlink()
        notes.reindex()

        # --- 할 일 · 목차 · 지난 판 · 옆 판 · 오늘 일지 ---
        notes.write(Note(title="점검표", body="# 큰 제목" + chr(10) * 2
                         + "- [ ] 하나" + chr(10) + "- [x] 둘" + chr(10) * 2
                         + "## 작은 제목" + chr(10) + "끝"))
        notes.reindex()
        win.show_note("점검표")
        assert "☐ 하나" in win.detail_view.toPlainText()
        # ★ **약속이 바뀌었다.** 예전엔 「채우면 보인다」였는데 이제 **폭도 본다** —
        #   좁은 카드에서 목차가 위 줄을 밀어 글자가 겹치는 것을 막으려고 접기 때문이다.
        #   그러니 여기서는 **채워졌나**를 재고, 보임 여부는 폭을 넓혀 놓고 잰다.
        assert win.toc.count() == 3, win.toc.count()
        win._trim_tools(900)
        assert win.toc.isVisibleTo(win.detail_card), "넓은데 목차가 안 보인다"
        win.flip_task(0)
        win.settle()
        assert "- [x] 하나" in notes.read("점검표").body
        assert win.detail_view.toPlainText().count("☑") == 2

        # 오간 자취 — 앞의 것이 닫히는 게 아니라 되돌아갈 수 있어야 한다
        win.show_note("카페 단골")
        assert win._trail[-2:] == ["점검표", "카페 단골"], win._trail
        win.go_back()
        assert win.editing == "점검표", win.editing
        win.go_forward()
        assert win.editing == "카페 단골"

        # 옆에 나란히 — 겹치면 안 된다
        win.resize(1366, 768)
        win.open_side("점검표")
        assert win.side_read.isVisibleTo(win.left)
        # **좁아지면 위 줄이 겹쳐 글자가 잘린다.** 곁에 띄우면 폭이 절반이라 바로
        # 드러난다 — 낯선 PC 에서 「지난 판 (2」로 괄호가 잘리고 「열매」가 「열애」로
        # 보였다. 넓을 때는 안 드러나고 좁힐 때만 드러나는 자리라, 넓은 쪽도 같이 잰다.
        long_note = chr(10).join(["머리말", "", "## 하나", "가", "", "## 둘", "나"])
        gap = notes_module.HISTORY_GAP_SEC
        notes_module.HISTORY_GAP_SEC = 0
        try:
            for turn in ("처음", long_note):
                notes.write(Note(title="넓고 좁고", body=turn, kind="note"))
        finally:
            notes_module.HISTORY_GAP_SEC = gap
        win.show_note("넓고 좁고")
        win.settle()
        win._trim_tools(900)
        assert win.past.isVisibleTo(win.detail_card), "넓은데 지난 판이 접혔다"
        assert win.toc.isVisibleTo(win.detail_card), "넓은데 목차가 접혔다"
        win._trim_tools(400)
        assert not win.past.isVisibleTo(win.detail_card), "좁은데 지난 판이 안 접혔다"
        assert not win.toc.isVisibleTo(win.detail_card), "좁은데 목차가 안 접혔다"
        # ★ **접었으면 「…」 로 갈 길이 있어야 한다.** 좁은 카드에서 목차를 숨기면서
        #   차림표에도 안 넣어 **소제목으로 갈 길이 통째로 사라졌다**(시험 쪽 라-③).
        #   접는 것은 자리를 아끼려는 것이지 기능을 없애려는 것이 아니다.
        if win.toc.count() > 1:
            win._build_more()
            차림 = [a.text() for a in win.more_menu.actions()]
            assert any(t.startswith("목차") for t in 차림),                 "좁아서 접었는데 「…」에도 목차가 없다: " + str(차림)
            win._trim_tools(900)
            win._build_more()
            넓은차림 = [a.text() for a in win.more_menu.actions()]
            assert not any(t.startswith("목차") for t in 넓은차림),                 "위 줄에 있는데 차림표에도 겹쳐 넣었다: " + str(넓은차림)
        # ★ **글이 바뀌면 목차도 바뀐다.** `_fill_toc` 이 항목을 **열 때만** 불려서,
        #   새 글에 소제목을 쳐 넣고 저장해도 목차가 0으로 남았다 — 새 글은 빈 채로
        #   열리므로 **직접 쳐서 만든 글은 목차가 영영 안 떴다**(시험 쪽 다-②).
        #   넓은 창에서도 안 보이던 까닭이 접기가 아니라 이것이었다.
        win.new_note()
        win.settle()
        assert win.toc.count() == 0, "새 글인데 목차가 이미 있다"
        win.detail_body.setPlainText("## 하나" + chr(10) + "가" + chr(10)
                                     + "## 둘" + chr(10) + "나")
        win.save_note()
        win.settle()
        assert win.toc.count() > 1, "소제목을 쳐 넣고 저장했는데 목차가 안 생겼다"
        # ★ **항목을 열 때도 폭을 본다.** 안 보면 좁은 카드에서 목차가 **있으면 안 될
        #   자리에 떠 있고**, 나란히 보기를 켰다 끈 뒤에야 접힌다 — 앞뒤가 다르다.
        #   시험 쪽은 이걸 「끈 뒤 안 돌아온다」로 봤는데 **끈 뒤가 맞는 쪽**이었다.
        win._trim_tools(400)
        접힘 = win.toc.isHidden()
        win.show_note("넓고 좁고")          # 좁은 채로 다시 연다
        win.settle()
        assert win.toc.isHidden() == 접힘, "좁은데 항목을 여니 목차가 도로 떴다"

        notes.delete("넓고 좁고")
        win.refresh()
        left_box, right_box = win.detail_card.geometry(), win.side_read.geometry()
        assert left_box.right() < right_box.left(), (left_box, right_box)
        assert right_box.right() <= win.left.width()
        win.close_side()
        assert not win.side_read.isVisibleTo(win.left)

        # 지난 판
        note = notes.read("점검표")
        note.body += chr(10) + "덧붙인 줄"
        gap = notes_module.HISTORY_GAP_SEC
        notes_module.HISTORY_GAP_SEC = 0
        try:
            notes.write(note)
            win.show_note("점검표")
            assert win.past.isVisibleTo(win.detail_card), "지난 판이 있는데 안 뜬다"
            where = win.past.itemData(win.past.count() - 1)
            assert notes.restore("점검표", Path(where))
            assert "덧붙인 줄" not in notes.read("점검표").body
        finally:
            notes_module.HISTORY_GAP_SEC = gap

        # 오늘 일지 — 두 번 눌러도 덮어쓰지 않는다
        forms = notes.template_root()
        forms.mkdir(parents=True, exist_ok=True)
        (forms / "일지.md").write_text("# {{날짜}}" + chr(10) + "- [ ] ", encoding="utf-8")
        win.open_daily()
        today = time.strftime("%Y-%m-%d")
        assert win.editing == today, win.editing
        notes.write(Note(title=today, body=notes.read(today).body + chr(10) + "손으로"))
        win.open_daily()
        assert "손으로" in notes.read(today).body, "일지를 덮어썼다"
        notes.delete("점검표")
        notes.delete(today)
        win.clear_detail()

        # --- 뜻으로 찾기: 배선만 확인한다 ---
        # 모델 파일이 있어야 도는 검사는 다른 PC에서 그냥 안 돈다. 여기서는
        # **훑는 실이 올린 임베더가 화면 쪽까지 오는지**와 진행 표시만 본다.
        assert getattr(notes, "_embed", None) is None

        def fake(texts, prefix="query: "):
            return [[float(len(t)), 1.0] for t in texts]

        win.indexer.embedder.emit(fake)
        assert getattr(notes, "_embed", None) is fake, "임베더가 화면 쪽에 안 왔다"

        # 뜻을 익히는 중이면 **말해 준다.** 2만 개면 몇 시간짜리 일이라
        # 말없이 돌면 뭐가 잘못된 줄 안다.
        win._meaning_ready(37)
        win.refresh()
        assert "37" in win.footer.text(), win.footer.text()
        win._meaning_ready(0)
        win.refresh()
        assert "37" not in win.footer.text()
        notes.use_embedder(None)


    app.quit()

    # ★ **값 바로 뒤에 조사를 박지 않는다.** 받침을 안 보고 붙인 「연결 메모을 밖에서도 고쳤어」·
    #   「"링크 왕복"는 … 하나야」가 실사용에서 걸렸다(시험 쪽 14). 조사는 `orders.josa/tail` 이 고른다.
    #   구운 판에는 소스가 없다 — 그때는 건너뛴다(없어서 못 재는 것과 재서 틀린 것은 다른 말이다).
    from pathlib import Path as _P

    try:
        본문 = _P(__file__).with_name("ui.py").read_text(encoding="utf-8")
    except OSError:
        본문 = ""
        print("  (구운 판이라 조사 검사는 건너뛴다)")
    for 박힌 in ("}은 ", "}는 ", "}을 ", "}를 ", "}이 ", "}가 "):
        assert not 본문 or 박힌 not in 본문, f"값 뒤에 조사를 박았다 — 받침을 안 본다: 「{박힌}」"

    # ★ **아는 길을 안 알려 주면 없는 것과 같다.** 좁히는 문법이 화면 어디에도 없으면
    #   쓰는 사람이 발견할 길이 없다 — AI 한테는 인사로 알려 주면서 사람한테는 안 알려 줬다.
    # ★★ **AI 한테 알려 준 길은 사람한테도 알려 준다.** `notes.NARROW` 의 이름이 늘면
    #   화면 안내도 같이 늘어야 한다 — 되는데 아무도 모르는 길이 오늘만 다섯 번 나왔다.
    #   서버 쪽은 `hello` 의 `how` 를 같은 규칙으로 지킨다(`server._self_check`).
    import notes as _n

    안내 = win.ask_box.placeholderText() + " " + win.ask_box.toolTip()
    안적힌 = [이름 for 이름 in _n.NARROW if 이름.isascii() and f"{이름}:" not in 안내]
    assert not 안적힌, f"검색칸이 좁히는 법을 안 알려 준다: {sorted(안적힌)}"
    assert "-kind:" in 안내, "빼는 법을 안 알려 준다 — 잡담이 많은 창고에서 제일 쓸모 있다"
    assert " OR " in 안내, "하나라도 든 것을 찾는 법을 안 알려 준다 (옵시디언은 그게 된다)"
    # ★ **낱말이 하나도 안 걸린 물음**이 좁히기가 제일 잘 듣는 자리다(밖이던 것이 1~4등).
    #   그 자리에서만 갈래로 좁혀 보라고 한 줄 붙인다 — 그 줄이 사라지면 여기서 터진다.
    #   (소스 글자를 세는 검사는 제 몸도 센다. 진짜 코드 1 + 이 줄 1 = 2다.)
    좁히라는말 = "처럼 갈래로 좁혀 봐"
    assert not 본문 or 본문.count(좁히라는말) >= 1,         "뜻으로만 찾았을 때 갈래로 좁히라는 말이 없다"

    # ★★ **글자 크기를 한 자리에서 곱한다.** 전에는 `font-size:11px` 이 서른다섯 군데
    #   박혀 있어 4K 화면이나 눈이 불편한 사람이 키울 길이 없었다(옵시디언은 Ctrl +/-).
    #   바꾸다 **f-string 이 아닌 자리**를 건드리면 스타일시트에 `{theme.글자(11)}` 이
    #   글자 그대로 남아 그 칸의 크기가 통째로 죽는다 — 눈으로는 잘 안 보인다. 여기서 센다.
    import theme as _theme
    from PyQt5.QtWidgets import QWidget as _QWidget

    남은것 = [type(w).__name__ for w in [win] + win.findChildren(_QWidget)
             if "글자(" in w.styleSheet()]
    assert not 남은것, f"스타일시트에 치환 안 된 글자 크기가 남았다: {남은것[:5]}"
    앞 = _theme.글자(12)
    _theme.배율바꾸기(1.5)
    assert _theme.글자(12) == "18px", _theme.글자(12)
    _theme.배율바꾸기(1.0)
    assert _theme.글자(12) == 앞, "배율을 되돌려도 안 돌아온다"
    # ★ **키운 글자가 다음에 켤 때 그대로여야 한다.** 켤 때마다 다시 키워야 하면 있으나 마나다.
    import paths as _paths

    # ★★ **검사는 진짜 설정을 건드리면 안 된다.** 처음엔 기록 자리를 안 바꾸고 불러서
    #   소스 폴더의 `pc/eb_config.json`(git 이 따라가는 파일)에 `글자배율` 이 써졌고
    #   **커밋에 섞였다.** 잠깐 쓰는 자리로 돌려놓고 잰다.
    with tempfile.TemporaryDirectory() as _잠깐:
        _옛 = os.environ.get("VC_DATA")
        os.environ["VC_DATA"] = _잠깐
        try:
            win.글자키우기(0.2)
            assert abs(_paths.load_config().get("글자배율", 0) - 1.2) < 0.001,                 f"키운 글자를 안 남긴다: {_paths.load_config().get('글자배율')}"
            win.글자키우기(0)                     # 제자리로
            assert abs(_theme.배율() - 1.0) < 0.001, _theme.배율()
        finally:
            if _옛 is None:
                os.environ.pop("VC_DATA", None)
            else:
                os.environ["VC_DATA"] = _옛

    # ★ **이름을 바꾸면** 저장될 꼴(`?`→전각)로 맞추고, 뒤로가기 줄의 옛 이름도 옮겨야 한다.
    notes.write(Note(title="바꿀 이름 시험", body="몸"))
    win.show_note("바꿀 이름 시험")
    win.detail_title.setText("바뀐? 이름 시험")
    win.rename_note()
    assert win.editing == "바뀐？ 이름 시험", f"바꾼 제목을 저장될 꼴로 안 맞춘다: {win.editing}"
    assert "바꿀 이름 시험" not in win._trail, f"뒤로가기 줄에 옛 이름이 남았다: {win._trail}"

    # ★ **뜻 모델이 아직 안 올랐으면 못 찾았다는 말에 그 사실을 붙인다.** 켠 뒤 몇 초는 자연말이
    #   조용히 0건이라 사람이 「없구나」 하고 떠났다.
    _옛임베더 = getattr(notes, "_embed", None)
    notes._embed = None
    _옛있나 = win._뜻모델있나
    try:
        win._뜻모델있나 = lambda: True
        assert "올리는 중" in win._못찾았다고("아무 말"), "뜻 모델이 오르는 중이라고 안 말한다"
        win._뜻모델있나 = lambda: False
        assert "올리는 중" not in win._못찾았다고("아무 말"), "모델이 없는데 올리는 중이라고 한다"
    finally:
        win._뜻모델있나 = _옛있나
        notes._embed = _옛임베더

    # ★★ **쓰기가 막히면 말로 알려야 한다** — 전엔 말로 덧붙이기가 아무 말 없이 안 써졌다.
    import orders as _orders6
    import os as _os6
    import stat as _stat6

    notes.write(Note(title="잠긴 글 시험", body="몸"))
    _잠긴 = notes.path_of("잠긴 글 시험")
    _os6.chmod(_잠긴, _stat6.S_IREAD)
    try:
        _한것 = win.do_order(_orders6.read_order("잠긴 글 시험에 덧붙일 줄 적어줘"))
        assert _한것 is True, "쓰기가 막혔는데 검색으로 흘러갔다"
        assert "못 썼어" in win.say.text(), f"쓰기가 막혔는데 말하지 않는다: {win.say.text()!r}"
    finally:
        _os6.chmod(_잠긴, _stat6.S_IWRITE)

    # ★ 메뉴 신호는 `checked` 를 덧붙여 부른다 — 장식 씌운 슬롯이 그걸 받아도 안 터져야 한다.
    win.clear_detail()
    win.drop_note(False)            # 연 글이 없으면 조용히 돌아선다(TypeError 가 나면 안 된다)
    win.rename_note()

    # ★★ **묶은 단축키는 다 알려야 한다.** 열네 개를 묶어 놓고 사람이 알 길이 없었다.
    #   표 하나를 묶기와 도움말이 같이 읽는다 — 설명이 빈 키가 생기면 여기서 터진다.
    도움글 = win.단축키글()
    for 키, _, 설명 in win.단축키표:
        assert 설명.strip(), f"설명 없는 단축키가 있다: {키}"
        assert 키 in 도움글, f"도움말에 {키} 가 없다"
    assert "F1" in win.ask_box.toolTip(), "단축키 보는 법(F1)을 안 알려 준다"
    # 전체화면·설정 창으로 가는 길이 키와 「⋯」 둘 다 있어야 한다.
    _키들 = {키 for 키, _, _ in win.단축키표}
    assert {"F11", "Ctrl+,"} <= _키들, f"전체화면·설정 단축키가 없다: {_키들}"
    win._build_more()
    _차림 = [a.text() for a in win.more_menu.actions()]
    assert any(t.startswith("설정") for t in _차림) and any(t.startswith("전체화면") for t in _차림), _차림
    # ★ 오늘 일지(Ctrl+D)가 쓰기 막힘에 죽지 않고 까닭을 말한다 — 신호 안 예외는 프로세스를 끝낸다.
    _일지말: list = []
    _옛말2, win.report = win.report, lambda t, who=None: _일지말.append(t)
    _옛일지, win.notes.daily = win.notes.daily, lambda *a, **k: (_ for _ in ()).throw(
        notes_module.WriteBlocked("잠김"))
    try:
        win.open_daily()
    finally:
        win.report, win.notes.daily = _옛말2, _옛일지
    assert any("못 만들었어" in t for t in _일지말), f"오늘 일지가 막혔는데 까닭을 안 말한다: {_일지말}"
    # ★ 제안 카드 승인이 스킬 저장 막힘에 죽지 않고, 제안은 결정 안 된 채 남는다.
    win.store.add_proposal(dict(proposal_id="막힐승인", type="skill_proposal", title="막힐 승인", summary="",
                                based_on=[], declaration={"name": "막힐 스킬"}))
    _승인말: list = []
    _옛말3, win.report = win.report, lambda t, who=None: _승인말.append(t)
    _옛저장, win.skills.save = win.skills.save, lambda *a, **k: (_ for _ in ()).throw(
        notes_module.WriteBlocked("잠김"))
    try:
        win.decide("막힐승인", "approve")
    finally:
        win.report, win.skills.save = _옛말3, _옛저장
    assert any("못 저장했어" in t for t in _승인말), f"승인이 막혔는데 까닭을 안 말한다: {_승인말}"
    assert win.store.proposal("막힐승인")["decision"] is None, "저장이 막혔는데 결정을 적었다(제안이 사라진다)"

    print("ui self-check 통과", flush=True)
    # ★★ **통과하고도 0 이 아닌 채 끝나는 일이 있었다** — 세 번에 한 번쯤 Qt 가 정리하다
    #   세그폴트를 냈다(파이썬이 위젯을 먼저 거두고 C++ 쪽이 그걸 다시 만지는 자리다).
    #   `--모두검사` 에서는 그것이 「✘ ui_check」로 보여, 검사가 터진 줄 알고 딴 데를 팠다.
    #   **검사는 이미 다 끝났다.** 끝났다고 말한 뒤 곧장 나간다 — 정리는 OS 가 한다.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)




if __name__ == "__main__":
    run()
