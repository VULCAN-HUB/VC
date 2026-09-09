"""VC — 이것 하나만 실행하면 된다.

    python -X utf8 eb.py

서버와 화면을 같이 띄운다. 사용자가 창을 둘 열고 순서를 맞출 이유가 없다.

**서버가 이미 떠 있으면 화면만 띄운다.** VC를 두 번 실행해도 포트 충돌로 죽지 않고,
먼저 뜬 쪽에 붙는다 — 폰이 이미 그쪽과 이야기하고 있을 수 있다.

옵션:
    --no-ui       화면 없이 서버만 (폰만 쓰거나 원격만 쓸 때)
    --no-server   화면만 (서버가 딴 PC에 있을 때)
"""

from __future__ import annotations

import io
import os
import pathlib
import re
import sys

import paths
import report
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import server as srv

HOST, PORT = "0.0.0.0", 8765


def server_alive(port: int = PORT, timeout: float = 0.6) -> bool:
    """이미 떠 있는지 본다. 인증이 필요한 응답(401)이면 그것도 살아 있다는 뜻이다."""
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/eb/v1/hello", timeout=timeout)
        return True
    except urllib.error.HTTPError:
        return True
    except (urllib.error.URLError, OSError):
        return False


def start_server(cfg: dict) -> srv.EBServer:
    store = srv.Store(cfg.get("db_path") or str(paths.store_path()))
    # 훑지 않고 연다. 항목이 쌓이면 훑는 데만 몇 십 초가 드는데, 그동안 서버가
    # 안 뜨면 폰이 붙지 못한다. 색인은 화면 쪽이 뒤에서 채운다(같은 파일을 본다).
    notes = srv.Notes(cfg.get("notes_dir") or str(paths.notes_dir()),
                      cfg.get("notes_index") or str(paths.index_path()),
                      index_now=False)
    eb = srv.EBServer((HOST, PORT), cfg, store, notes)
    eb.start_analyzer(cfg.get("analyze_every_sec", 900))
    eb.start_housekeeping()
    threading.Thread(target=eb.serve_forever, daemon=True).start()
    return eb


def _log_crash(err: BaseException) -> None:
    """죽은 이유를 파일로 남긴다.

    설치본은 콘솔이 없다. 그래서 **아무 말 없이 사라진다** — 쓰는 사람이 할 수 있는
    게 없고, 우리도 원인을 못 듣는다. 기록 자리에 남겨 두면 물어볼 것이 생긴다.
    """
    import traceback

    try:
        note = paths.data_dir() / "vc-오류.txt"
        with note.open("a", encoding="utf-8") as f:
            f.write(f"--- {time.strftime('%Y-%m-%d %H:%M:%S')}" + chr(10))
            traceback.print_exception(type(err), err, err.__traceback__, file=f)
    except Exception:
        pass   # 남기다 또 죽으면 그냥 넘어간다


def _지문(글: str) -> str:
    """조각 하나의 지문. 흡수가 겹침을 볼 때 쓰는 것과 같은 셈이다."""
    import hashlib as _h

    굳힌 = " ".join((글 or "").split())
    return _h.blake2b(굳힌.encode("utf-8"), digest_size=16).hexdigest() if 굳힌 else ""


def _휴지통지문() -> set[str]:
    """휴지통에 든 조각들의 지문. **여기 있는 것은 다시 안 물어본다.**"""
    자리 = paths.휴지통자리()
    if not 자리.is_dir():
        return set()
    본것 = set()
    for f in 자리.glob("*.md"):
        try:
            글 = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        몸 = 글.split(chr(10) + "---" + chr(10), 1)[-1] if 글.startswith("---") else 글
        지 = _지문(몸)
        if 지:
            본것.add(지)
    return 본것


def _휴지통에담기(막힌, 뿌리) -> int:
    """문지기가 버린 조각을 휴지통에 남긴다. 몇 개 남겼는지 돌려준다.

    ★ **지우지 않는다.** 되살릴 수 있어야 버리는 일이 무섭지 않다 —
    사람이 파일 하나를 글 폴더로 옮기면 그대로 항목이 된다(파일이 원본이다).
    ★ 기록 폴더 **밖**이라 찾기·색인·그물에 안 들어간다.
      「찾으라고 하기 전까지 안 찾는다」(오너 결정 2026-09-09).
    """
    import re as _re

    if not 막힌:
        return 0
    자리 = paths.휴지통자리()
    자리.mkdir(parents=True, exist_ok=True)
    이미 = _휴지통지문()
    담은 = 0
    이제 = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    for c in 막힌:
        지 = _지문(c.몸)
        if not 지 or 지 in 이미:
            continue                    # 같은 것을 두 번 담지 않는다
        이미.add(지)
        이름 = _re.sub(r'[\/:*?"<>|]', "_", (c.제목 or Path(c.출처).stem or "조각"))[:60].strip()
        길 = 자리 / f"{이름 or '조각'} {지[:8]}.md"
        앞머리 = [
            "---",
            'kind: "휴지통"',
            '지은이: "문지기"',
            f'출처: "{뿌리 / c.출처}"',
            f"줄: {c.줄}",
            f'버린날: "{이제}"',
            '까닭: "문지기가 버렸다"',
            f'지문: "{지}"',
            "---",
            "",
        ]
        try:
            길.write_text(chr(10).join(앞머리) + c.몸 + chr(10), encoding="utf-8")
            담은 += 1
        except OSError:
            pass                        # 한 조각 못 담았다고 흡수를 멈추지 않는다
    return 담은


def _사람이손댄것(뿌리) -> list[str]:
    """사람이 만들었거나 고친 항목의 이름. 흡수분(문지기·그대로)은 뺀다.

    ★ **파일을 본다. 색인이 아니라.** 색인기는 mtime 으로 무엇을 다시 읽을지
    고르는데 SMB 볼트에서는 그것이 조용히 낡을 수 있다. 되돌릴 수 없는 일
    직전에는 **파생물이 아니라 진실**을 본다.
    """
    from pathlib import Path as _P

    남 = []
    for f in _P(뿌리).rglob("*.md"):
        조각 = f.relative_to(뿌리).parts
        if ".이력" in 조각 or "_서식" in 조각:
            continue
        try:
            글 = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        머리 = 글.split(chr(10) + "---", 1)[0]
        # 흡수가 만든 것에는 지은이가 「문지기」 또는 「그대로」로 박힌다.
        # ★ 「씨앗」은 **창을 처음 켤 때 프로그램이 만드는 글**이다. 사람 손이 안 닿았다.
        #   이걸 사람 글로 세면 새 창고의 첫 흡수가 통째로 막힌다(시험 쪽이 잡았다).
        사람손 = 'edited_by: "사람"' in 머리
        # ★ `kind: "agent"` 도 프로그램이 만든 것이다 — **표시가 없던 옛 씨앗**까지
        #   덮는다. 이미 만들어진 창고를 다시 만들게 하지 않으려고 같이 본다.
        if ('지은이: "문지기"' in 머리 or '지은이: "그대로"' in 머리
                or (('지은이: "씨앗"' in 머리 or 'kind: "agent"' in 머리) and not 사람손)):
            continue
        # ★★ **`출처:` 가 있으면 흡수해 온 것이다 — 지은이가 없어도.**
        # 지은이는 나중에 생긴 칸이라 **옛 판이 들인 항목에는 아예 없다.**
        # 그걸 안 보면 옛 기록이 통째로 「사람 손질」로 잡힌다 —
        # 실제로 시험 PC 에서 **552개**가 그렇게 잡혀 세는 것까지 막혔다.
        # 사람이 창에서 만든 글에는 출처가 없다. 그것이 가르는 자리다.
        if "출처:" in 머리 and not 사람손:
            continue
        남.append(f.stem)
    return 남


# 아는 스위치 전부. **여기 없는 것을 주면 안 돈다.**
아는스위치 = {
    "--check", "--doctor", "--진단", "--진단모음", "--report", "--reindex", "--색인다시",
    "--재보기", "--ingest", "--흡수", "--write", "--쓴다", "--그래도쓴다", "--손댄것도쓴다",
    "--score", "--찾기점수", "--without", "--빼고", "--제목벡터빼고",
    "--links", "--이음선", "--그물시험", "--bench", "--net-test", "--log-test",
    "--사본치우기", "--판올리기", "--휴지통",
    "--예외시험", "--no-ui", "--no-server", "--도움말", "--help", "-h",
}
# 뒤에 값이 하나 딸리는 것. 그 값은 스위치가 아니다.
값받는스위치 = {"--빼고", "--without"}


def _모르는스위치(argv: list[str]) -> list[str]:
    """아는 것에 없는 `--무엇`. 값으로 딸려 온 것은 뺀다."""
    모름, 건너뛸 = [], False
    for a in argv:
        if 건너뛸:
            건너뛸 = False
            continue
        if a in 값받는스위치:
            건너뛸 = True
            continue
        if a.startswith("--") and a not in 아는스위치:
            모름.append(a)
    return 모름


def 콘솔안전() -> None:
    """못 찍는 글자 하나가 프로그램을 죽이지 않게 한다.

    한국어 윈도우 콘솔은 기본이 **cp949** 라 U+26A0(경고 세모) 같은 글자를 못 찍는다.
    켜질 때 그 글자를 한 번 찍었더니 **UnicodeEncodeError 로 창이 아예 안 떴다** —
    **알리려고 넣은 말이 프로그램을 죽였다.** 글자는 흘려보내고 프로그램은 산다.

    글자 하나를 바꾸는 것으로는 모자란다 — **다음에 누가 또 넣으면 또 죽는다.**
    말하는 자리를 전부 고치는 대신 **말이 나가는 문** 하나를 막는다.
    """
    for 이름 in ("stdout", "stderr"):
        짝 = getattr(sys, 이름, None)
        if 짝 is None:
            continue          # 창 모드에선 아예 없다
        try:
            짝.reconfigure(errors="backslashreplace")
            continue
        except Exception:
            pass
        # ★★ **`reconfigure` 가 안 먹는 자리가 있다** — 구운 판에서는 이게 터지고
        # 난 그걸 조용히 삼켰다. 그래서 소스로는 멀줦했는데 **exe 는 그대로 죽었다**
        # (시험하는 쪽에서 `—` 하나로 사본치우기가 통째로 입을 닫았다).
        # 안 먹으면 **새로 감싼다.**
        try:
            속 = getattr(짝, "buffer", None)
            if 속 is not None:
                setattr(sys, 이름, io.TextIOWrapper(
                    속, encoding=(getattr(짝, "encoding", None) or "utf-8"),
                    errors="backslashreplace", line_buffering=True))
        except Exception:
            pass


def main(argv: list[str] | None = None) -> int:
    콘솔안전()
    argv = sys.argv[1:] if argv is None else argv
    # ★★ **모르는 스위치를 조용히 무시하지 않는다.**
    #
    # 예전에는 모르는 것을 그냥 흘려보내고 **창을 띄웠다.** 그래서 시험하는 쪽이
    # 아직 그 스위치가 없는 판에 `--제목벡터빼고` 를 주고 재면 **그냥 잰 값과
    # 똑같은 숫자**가 나왔다. 그걸 그대로 읽으면 「빼도 안 좋아진다 = 고치지 마라」가
    # 되는데 **정반대의 거짓말**이다 — **참한 고침을 죽일 뻔했다.**
    #
    # 값이 똑같이 나오는 것이 「달라진 게 없다」가 아니라 **「안 먹은 것」**일 수 있다.
    # 그걸 사람이 매번 의심하게 두지 말고 **여기서 막는다.**
    if {"--도움말", "--help", "-h"} & set(argv):
        # 명령줄로 물었으면 **명령줄로 답한다.** 창을 띄우면 답이 아니다.
        print("VC — 쓸 수 있는 것")
        for 줄 in ("  (없이)                그냥 켠다",
                   "  --doctor            무엇이 어디 있는지 적는다 (--진단)",
                   "  --report            진단 묶음을 만든다",
                   "  --색인다시           색인만 다시 만든다 (기록은 안 건드린다)",
                   "  --흡수 <폴더> [--쓴다]   폴더를 들인다. --쓴다 없으면 세어만 본다",
                   "  --찾기점수 [물음파일] [--빼고 <출처조각>] [--제목벡터빼고]",
                   "        물음 한 줄 꼴 : 물음 | 정답   또는   물음 | 정답1; 정답2",
                   "  --이음선             맞짝 이음선을 적는다",
                   "  --휴지통 [찾을말]      버린 조각을 모아 둔 자리를 뒤진다",
                   "  --check             자체점검"):
            print(줄)
        return 0
    if 모름 := _모르는스위치(argv):
        print("모르는 것이다: " + " ".join(모름))
        print("아는 것: " + " ".join(sorted(아는스위치 - {"-h"})))
        return 2
    want_ui = "--no-ui" not in argv
    want_server = "--no-server" not in argv

    cfg = srv.load_config()
    if want_server and not server_alive():
        start_server(cfg)
        print(f"VC 서버 {HOST}:{PORT} (프로토콜 {srv.PROTOCOL_VERSION})")
        print(f"페어링 토큰: {cfg['pair_token']}")
        # ★★ **열려 있다는 것을 말한다.** 시험하는 쪽이 방화벽 물음을 보고서야
        # 알았다 — 「모르는 새 열린다」가 문제였다. 막이는 있지만(토큰 없으면 401)
        # **같은 공유기의 다른 기기에서 닿는다는 사실 자체**를 쓰는 사람이 알아야 한다.
        if HOST == "0.0.0.0":
            print("  ★ 같은 공유기의 다른 기기에서도 이 자리에 닿는다"
                  " (토큰 없으면 401로 막힌다).")
            print("  원격이 필요 없으면  VC.exe --no-server  로 켜라.")
        report.trail(f"서버 열었다 {HOST}:{PORT}")
    elif want_server:
        print(f"서버가 이미 떠 있어 그쪽에 붙는다 (:{PORT})")

    if not want_ui:
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            return 0

    # 화면은 여기서 처음 불러온다. 서버만 쓸 때 PyQt5가 없어도 돌아가야 한다.
    #
    # **Qt보다 먼저 시스템 C++ 런타임을 붙든다.** 5ms 든다. 안 하면 PyQt5가 딸고 온
    # 2019년 판을 onnxruntime이 물어 뜻 검색이 조용히 꺼진다. 무거운 onnxruntime
    # 자체는 뒤에서 도는 실이 필요할 때 올린다 — 여기서 올리면 창이 1초 늦게 뜬다.
    from brain import pin_runtime

    # **딴 PC 에서 난 일은 우리가 못 본다.** 자국과 죽음을 파일로 남겨 둔다 —
    # 파이썬 예외로 안 잡히는 죽음까지 받는다(빈 그래프에서 실제로 그랬다).
    report.watch_deaths()
    report.catch_slot_deaths()
    # **같은 기록을 두 벌이 만지면 서로 덮어쓴다.** 작업표시줄에서 못 찾고 다시 켜는
    # 흔한 실수라, 조용히 두 벌이 뜨는 대신 알리고 그만둔다.
    if not paths.only_one():
        report.trail("이미 떠 있어서 그만뒀다")
        try:
            from PyQt5.QtWidgets import QApplication, QMessageBox

            app = QApplication.instance() or QApplication(sys.argv)
            QMessageBox.information(
                None, "VC", "VC가 이미 떠 있어. 작업표시줄을 봐.  "
                "같은 기록을 둘이 만지면 글이 섞인다.")
        except Exception:
            print("VC가 이미 떠 있다.")
        return 0
    report.trail(f"켬 · 설치본={paths.frozen()} · 런타임={pin_runtime()}")

    from PyQt5.QtWidgets import QApplication

    import ui

    app = QApplication(sys.argv)
    # 창부터 띄우고 훑기는 뒤에서 돈다 — 2만 개면 훑는 데 6초, 10만 개면 30초다.
    win = ui.MainWindow(ui.Notes(paths.notes_dir(), str(paths.index_path()), index_now=False),
                        ui.Store(str(paths.store_path())))
    # ★ 창만 보는 사람에게도 열린 자리를 알린다 — 콘솔에 찍는 말은 창용 exe 에서
    #   갈 데가 없다. 서버를 안 켰으면 아무 말도 안 한다.
    if want_server:
        win.열린자리알리기(HOST, PORT)
    win.show()
    report.trail("창 떴다")
    code = app.exec_()
    report.trail(f"끔 ({code})")
    report.stop_watching()
    return code


def _소스글() -> str:
    """이 파일의 글. **구운 판에는 없다** — 그때는 빈 글을 준다.

    소스를 세어 보는 검사들이 여럿 있는데, 구운 판에서 `__file__` 을 읽으면 터져
    `--check` 가 통째로 실패했다(시험 쪽이 잡았다). **소스가 없는 자리에서
    소스 검사는 할 일이 아니다** — 건너뛰되, 건너뛴 것을 말한다.
    """
    try:
        return pathlib.Path(__file__).read_text(encoding="utf-8")
    except OSError:
        말하기("  (구운 판이라 소스 세기 검사는 건너뛴다)")
        return ""


def _self_check() -> None:
    import tempfile

    # 안 떠 있으면 안 떠 있다고 한다. 잘못 알면 두 번째 VC가 포트를 뺏으려다 죽는다.
    assert server_alive(port=59999, timeout=0.2) is False

    with tempfile.TemporaryDirectory() as tmp:
        cfg = srv.load_config(Path(tmp) / "cfg.json")
        assert cfg["pair_token"] and cfg["backend"]["kind"] == "local"

        # 실제로 띄워 살아 있음을 확인한다.
        store, notes = srv.Store(":memory:"), srv.Notes(Path(tmp) / "notes")
        eb = srv.EBServer(("127.0.0.1", 0), cfg, store, notes)
        port = eb.server_address[1]
        threading.Thread(target=eb.serve_forever, daemon=True).start()
        try:
            assert server_alive(port=port) is True, "떠 있는데 못 찾는다"
        finally:
            eb.shutdown()
            eb.server_close()

        # 닫으면 다시 안 떠 있다고 나온다.
        assert server_alive(port=port, timeout=0.3) is False

    # **창 프로그램에는 `sys.stdout` 이 없다.** `print` 는 조용히 넘어가지만
    # `flush()` 는 터지고, 그러면 PyInstaller 가 오류창을 띄운다 — 그 창은 다른 창
    # 뒤에 가려져 보이지도 않는데 아무도 안 눌러서 **프로세스가 영영 안 나간다.**
    # 소스로 돌리면 stdout 이 진짜 파일이라 안 드러난다. 그래서 여기서 없애고 잰다.
    했던것, sys.stdout = sys.stdout, None
    try:
        말하기("이건 아무 데도 안 나가야 한다")
    finally:
        sys.stdout = 했던것

    # **그물이 진짜 도는지 여기서도 잰다.** 스위치가 터졌을 때 자국에 남기고 곧바로
    # 나가야 한다 — 안 그러면 안 보이는 오류창이 떠서 프로세스가 서 있는다.
    import subprocess
    import tempfile as 임시

    with 임시.TemporaryDirectory() as tmp:
        났다 = subprocess.run(
            [sys.executable, __file__, "--그물시험"],
            env=dict(os.environ, VC_DATA=tmp, PYTHONIOENCODING="utf-8"),
            capture_output=True, timeout=90)
        # 나가기만 하면 된다 — 멈추지 않는 것이 핵심이라 종료값은 안 본다.
        죽음, 자국 = Path(tmp) / report.DEATH, Path(tmp) / report.TRAIL
        assert 죽음.exists(), "스위치가 터졌는데 죽음 기록이 아예 안 생겼다"
        assert "일부러 터뜨린" in 죽음.read_text(encoding="utf-8"), "죽음 기록에 안 남았다"
        assert 자국.exists() and "스위치에서 죽음" in 자국.read_text(encoding="utf-8"),             "자국에 안 남았다"

    # ── ★★ 인자 없이 띄우는 길이 성한가 ────────────────────────────────────
    #
    # **이걸 안 재서 안 뜨는 판을 내보냈다.** `--doctor` 같은 스위치는 다 됐는데
    # **인자 없이 띄우면 시작하자마자 터졌다** — 고치다 `main()` 의 매개변수를
    # 통째로 덮어써서 본문이 쓰는 `argv` 가 사라졌는데, 검사 열셋이 전부 통과했다.
    # **제일 흔한 길(그냥 두 번 눌러 켜기)을 아무도 안 밟고 있었다.**
    #
    # 창을 실제로 띄우진 않는다(검사 자리에 창이 뜨면 사람 손이 필요해진다).
    # 대신 **부를 수 있는 꼴인지**를 본다 — 터진 자리가 바로 여기였다.
    import inspect

    자리 = inspect.signature(main).parameters
    assert "argv" in 자리, f"main 이 argv 를 안 받는다 — 인자 없이 켜면 터진다: {자리}"
    assert 자리["argv"].default is None, "argv 에 기본값이 없다 — 인자 없이 못 부른다"
    # 본문이 쓰는 이름과 매개변수 이름이 어긋나면 `UnboundLocalError` 가 난다.
    # ★ **구운 판에는 소스가 없다.** `getsource` 가 OSError 로 터져 `--check` 가
    #   통째로 실패했다(시험 쪽이 잡았다). 소스가 있을 때만 본다 —
    #   소스가 없는 자리에서 이 검사는 애초에 할 일이 아니다.
    try:
        몸 = inspect.getsource(main)
    except (OSError, TypeError):
        몸 = ""
        말하기("  (구운 판이라 소스 검사는 건너뛴다)")
    for 이름 in re.findall(r"\b(argv)\b", 몸):
        assert 이름 in 자리, 이름
    # ※ 실제로 `main()` 을 불러 보진 않는다 — 서버·창을 붙들어 검사가 안 끝난다.
    #   서명과 본문만 봐도 이번 것은 잡힌다(매개변수가 사라진 것이 원인이었다).

    # ★ **`--doctor` 에도 판 적합률이 있어야 한다.** 창이 안 뜨는 판에서는 그것만
    #   돌아가는데 그때 이 값이 제일 필요하다(시험 쪽이 짚었다).
    # ★ 사본 치우기는 **미리보기가 기본**이고 `--쓴다` 가 있어야 움직인다.
    #   그리고 **지우지 않고 `.이력/` 으로 치운다** — `delete()` 는 파일을 그냥
    #   없애서 되돌릴 수가 없다. 실측: 3183장에서 388장(12.2%)이 본문이 똑같았고,
    #   치운 뒤 그물의 near-중복이 40% → 9% 로 떨어졌다.
    # ※ **소스를 잘라 보지 않는다.** 잘라 봤더니 **검사 코드 자체에 같은 글자가
    #   들어 있어** 자르는 자리가 어긋났고, 고침을 빼도 「통과」가 나왔다.
    #   그 자리에만 있는 글자로 본다.
    본문3 = _소스글()
    # ★★ **소스가 없으면 소스 검사는 아예 안 한다.** 구운 판에서 빈 글을 세면
    # 0 이 나와 **멀쩡한 판이 「검사 실패」로 보인다** — 실제로 오류 상자가 떴다.
    # 「없어서 못 잰 것」과 「재 봤더니 틀린 것」은 다른 말이다.
    소스있다 = bool(본문3)
    # ★ **빈 글끼리는 사본이 아니다.** 비어 있는 두 글은 같은 내용을 가진 게 아니라
    #   내용이 없는 것이다. 바닥값을 넣으며 이 줄을 지웠더니 **제목 밑동 예외가
    #   바닥값을 뚫고** 빈 글끼리 묶였다 — 창에서 만들어 두고 아직 안 쓴 글이
    #   사본으로 치워질 뻔했다(시험 쪽이 잡았다).
    # (검사문이 한 번 쓰므로 **둘 이상**이어야 진짜 코드가 있는 것이다)
    빈것뺌 = 본문3.count("            if not 몸:")
    assert not 소스있다 or 빈것뺌 >= 2, f"빈 글을 짝짓기에서 안 뺀다 ({빈것뺌}군데)"
    # ★★ **못 찍는 글자가 프로그램을 죽이면 안 된다.** 실제로 죽였다 —
    #   v0.1.78 은 스위치 없이 그냥 켜면 cp949 콘솔에서 바로 터졌다.
    #   내 자리는 UTF-8 이라 **안 보였다.** 그래서 검사가 cp949 로 찍어 본다.
    바탕 = io.TextIOWrapper(io.BytesIO(), encoding="cp949")
    진짜밖 = sys.stdout
    sys.stdout = 바탕
    try:
        콘솔안전()
        print("★ " + chr(0x26A0) + " 같은 공유기의 다른 기기에서도 닿는다")
        sys.stdout.flush()
    finally:
        sys.stdout = 진짜밖

    # ★★ **막이가 안 먹는 자리에서도 말은 나가야 한다.**
    # 구운 판에선 `reconfigure` 가 터졌고, 그러자 `—`(em dash) 하나로
    # `--사본치우기`·`--판올리기` 가 **아무 말도 안 하고 끝났다**(종료값 0).
    # 그랬 때는 `말하기` 가 한 번 더 받아 낸다. 그걸 여기서 재다 —
    # 바꿔치기를 못 하게 막아 놓고 재야 진짜로 나가는지 안다.
    class _고집센콘솔(io.TextIOBase):
        """`reconfigure` 를 거절하고 cp949 로만 받는 콘솔. 구운 판이 이랬했다."""
        encoding = "cp949"

        def __init__(self):
            self.받은 = []

        def reconfigure(self, **_):
            raise OSError("안 먹는다")

        def write(self, 글):
            글.encode("cp949")          # 못 찍는 글자면 여기서 터진다
            self.받은.append(글)
            return len(글)

    고집센 = _고집센콘솔()
    진짜밖 = sys.stdout
    sys.stdout = 고집센
    try:
        콘솔안전()
        말하기("사본 치우기 — 항목 0장")     # em dash — 예전엔 여기서 통째로 삼켰다
    finally:
        sys.stdout = 진짜밖
    assert any("사본 치우기" in 글 for 글 in 고집센.받은),         "막이가 안 먹는 콘솔에서 말이 통째로 사라졌다"

    # 그리고 애초에 **켜질 때 그 글자를 안 쓴다** (`★` 는 cp949 에 있다).
    # 글자를 그대로 적으면 검사문이 제 꺼를 세므로 번호로 찾는다.
    assert not 소스있다 or 본문3.count(chr(0x26A0)) == 0, "cp949 가 못 찍는 글자가 eb.py 에 있다"

    # ★★ **버린 것은 지우지 않고 휴지통에 모으고, 다시 안 물어본다.**
    #   예전엔 같은 폴더를 열 번 부으면 버린 조각을 열 번 문지기에게 물어봤다
    #   (시험 쪽이 「후보 5는 다시 모델 검사를 받는다」로 잰 그 자리다).
    #   ★ 그리고 휴지통은 **기록 폴더 밖**이라 찾기·색인·그물이 안 본다 —
    #     「찾으라고 하기 전까지 안 찾는다」(오너 결정).
    import tempfile as _tf2

    import ingest as _ing

    with _tf2.TemporaryDirectory() as 잠깐휴지:
        옛자리2 = os.environ.get("VC_DATA")
        os.environ["VC_DATA"] = 잠깐휴지
        try:
            버린조각 = [_ing.조각(제목="버릴 것", 몸="이건 과정 소음이다. " * 8,
                              출처="어디/에서.md", 줄=3)]
            assert _휴지통에담기(버린조각, pathlib.Path(잠깐휴지)) == 1
            assert _휴지통에담기(버린조각, pathlib.Path(잠깐휴지)) == 0, "같은 것을 두 번 담는다"
            담긴 = list(paths.휴지통자리().glob("*.md"))
            assert len(담긴) == 1, 담긴
            # 휴지통은 글 폴더 밖이어야 한다 — 안에 있으면 색인에 딸려 들어간다
            assert paths.notes_dir() not in paths.휴지통자리().parents, "휴지통이 글 폴더 안이다"
            # 그리고 다음 흡수 때 「이미 본 것」으로 잡혀 다시 안 물어본다
            지문들 = _휴지통지문()
            assert 지문들 and _지문(버린조각[0].몸) in 지문들, "휴지통에 있는데 또 물어본다"
            _조각들, 셈 = _ing.들일것(pathlib.Path(잠깐휴지), 지문들)
        finally:
            if 옛자리2 is None:
                os.environ.pop("VC_DATA", None)
            else:
                os.environ["VC_DATA"] = 옛자리2

    # ★★ **창을 한 번 켜는 것이 죄가 되면 안 된다.**
    #   창이 처음 켜질 때 만드는 씨앗 글을 「사람이 손넄 기록」으로 세서
    #   **새 창고의 첫 흡수가 통째로 막혔다**(시험 쪽이 잡았다). 사람이 그 글을
    #   실제로 고치면 `edited_by: "사람"` 이 붙고, 그때는 지켜야 한다.
    import tempfile as _tf

    with _tf.TemporaryDirectory() as 잠깐씨앗:
        씨앗자리 = pathlib.Path(잠깐씨앗)
        (씨앗자리 / "VC.md").write_text(
            '---' + chr(10) + '지은이: "씨앗"' + chr(10) + 'kind: "agent"' + chr(10)
            + '---' + chr(10) + "여기서 시작한다." + chr(10), encoding="utf-8")
        (씨앗자리 / "사람 글.md").write_text(
            '---' + chr(10) + 'kind: "note"' + chr(10) + '---' + chr(10) + "내가 썼다." + chr(10),
            encoding="utf-8")
        assert _사람이손댄것(씨앗자리) == ["사람 글"],             f"씨앗을 사람 글로 센다: {_사람이손댄것(씨앗자리)}"
        # 그러나 사람이 씨앗을 고쳐 놓았으면 지켜야 한다
        (씨앗자리 / "VC.md").write_text(
            '---' + chr(10) + '지은이: "씨앗"' + chr(10) + 'kind: "agent"' + chr(10)
            + 'edited_by: "사람"' + chr(10) + '---' + chr(10) + "내가 고쳤다." + chr(10),
            encoding="utf-8")
        assert "VC" in _사람이손댄것(씨앗자리), "사람이 고친 씨앗을 안 지킨다"

    # ★ 모델이 없을 때 **넣을 자리를 바로 말하고, 센 것도 같이 말한다.**
    #   예전엔 `_internal\models`(프로그램 속)을 가리켰고, 멈추면서 센 것을 안 보였다.
    for 있어야, 몇, 까닭 in ((' / "models"', 2, "넣을 자리로 exe 옆을 안 말한다"),
                          ('센 것: {s}', 2, "멈추면서 센 것을 안 보인다")):
        assert not 소스있다 or 본문3.count(있어야) >= 몇, f"{까닭} ({본문3.count(있어야)}군데)"

    # ★ 열려 있는 자리를 말한다 — 「모르는 새 열린다」가 문제였다
    for 있어야, 몇, 까닭 in ((' 다른 기기에서도', 3, "듣는 자리를 안 알린다"),):
        assert not 소스있다 or 본문3.count(있어야) >= 몇, f"{까닭} ({본문3.count(있어야)}군데)"

    # ★★ **세어서 본다. 「들어 있나」로 보면 검사가 제 꼬리를 문다** —
    #   검사문에 적은 그 글자가 스스로를 만족시켜, **고침을 빼도 통과했다.**
    #   검사 자신이 한 번 쓰므로 **진짜 코드까지 두 번**이어야 한다.
    for 있어야, 몇번, 까닭 in (
            ('n.keep_history(길,', 2, "치우기 전에 지난 판을 안 남긴다 — 되돌릴 수가 없다"),
            ('FROM links WHERE dst = ?", (길.stem,)', 2,
             "가리키는 것을 안 본다 — 치우면 그 이음이 허공을 가리킨다"),
            ('사람것 = _사람이손댄것(뿌리)', 2, "사람 손질을 안 본다"),
            ('치울것, 지킨것, 건너뛴것', 2, "사본 치우기 자리가 없다")):
        assert not 소스있다 or 본문3.count(있어야) >= 몇번, f"{까닭} ({본문3.count(있어야)}군데)"

    # ★ **짝짓기에 바닥값이 있어야 한다.** 본문만 보고 짝을 지었더니 **두 글자짜리
    #   본문 셋**이 한 뭉치가 되어 제목이 서로 다른 딴 글이 「치울 것」에 들어갔다
    #   (시험 쪽이 잡았다). 13071자가 같은 것과 두 글자가 같은 것은 다른 일이다.
    #   (검사문이 한 번 쓰므로 **둘 이상**이어야 진짜 코드가 있는 것이다)
    짝바닥 = 본문3.count("< ingest.짧은조각")
    assert not 소스있다 or 짝바닥 >= 2, f"짧은 본문끼리도 짝을 짓는다 ({짝바닥}군데)"
    # ★ 다만 **짧아도 제목 밑동까지 같으면 진짜 사본이다.** 바닥값만 두면
    #   「8월 회의록」 셋(본문 20자·제목 같음)을 놓친다(시험 쪽이 갈랐다).
    밑동봄 = 본문3.count("chr(31) + 밑동 if 짧다")
    assert not 소스있다 or 밑동봄 >= 2, f"짧은 것에서 제목 밑동을 안 본다 ({밑동봄}군데)"
    # ★ 같은 폴더를 두 번 흡수해도 다시 안 쌓인다 — 오너 기록 388장(12.2%)의 원인이었다
    이미봄 = 본문3.count("ingest.들일것(뿌리, 이미)")
    assert not 소스있다 or 이미봄 >= 2, f"흡수가 이미 든 글을 안 본다 ({이미봄}군데)"

    # ★★ **막이는 쓰는 것을 막지 보는 것을 막지 않는다.**
    #   처음에는 세는 것까지 막아서, 「먼저 세어만 봐라」를 시켜 놓고 **셀 수가
    #   없었다.** 보는 것이 막히면 정할 근거가 없어지고 **남는 길은 「그래도
    #   쓴다」뿐**이라, 안전장치가 오히려 위험한 쪽으로 몬다(시험 쪽이 잡았다).
    for 있어야, 몇번, 까닭 in (
            ('사람것 = _사람이손댄것(뿌리)', 2, "사람 손질을 안 본다"),
            ('if 사람것 and "--손댄것도쓴다" not in sys.argv:', 2,
             "막이가 쓰는 자리에 없다 — 세는 것까지 막으면 안 된다"),
            ('★ 사람이 손댄 항목', 2, "미리보기가 사람 손질을 안 알려 준다")):
        assert not 소스있다 or 본문3.count(있어야) >= 몇번, f"{까닭} ({본문3.count(있어야)}군데)"
    # ★ 옛 판이 들인 항목(지은이 칸이 없다)을 사람 손질로 오해하면 안 된다 —
    #   시험 PC 에서 552개가 그렇게 잡혀 세는 것까지 막혔다.
    옛것가르기 = 본문3.count(chr(105) + chr(102) + ' "출처:" in 머리 and')
    # (검사문은 chr() 로 쪼개 적어 제 몫을 안 센다 — 그래서 1군데면 충분하다)
    assert not 소스있다 or 옛것가르기 >= 1, f"출처만 있는 옛 흡수분을 안 가른다 ({옛것가르기}군데)"

    # ★ **켠 스위치는 제 몫을 머리글에 찍는다.** 안 찍으면 「먹었는지」를 값이
    #   달라진 것으로만 알게 되고, 값이 같게 나오는 판에서는 「안 먹은 것」과
    #   「달라진 게 없는 것」이 안 갈린다(시험 쪽 요청).
    for 있어야, 몇번, 까닭 in (
            ('제목 벡터를 빼고 쟀다', 2, "--제목벡터빼고 가 머리글에 안 찍힌다"),
            ('정답을 여럿 적은 물음', 2, "정답 여럿이 머리글에 안 찍힌다")):
        assert not 소스있다 or 본문3.count(있어야) >= 몇번, f"{까닭} ({본문3.count(있어야)}군데)"

    # ★★ **모르는 스위치는 조용히 지나가면 안 된다.**
    #   시험하는 쪽이 아직 그 스위치가 없는 판에 `--제목벡터빼고` 를 주고 쟀더니
    #   **그냥 잰 값과 똑같은 숫자**가 나왔다. 그대로 읽으면 「빼도 안 좋아진다」가
    #   되는데 **정반대의 거짓말**이고, 참한 고침을 죽일 뻔했다.
    #   **값이 똑같으면 「달라진 게 없다」가 아니라 「안 먹은 것 아닌가」다.**
    assert _모르는스위치(["--찾기점수", "--없는것"]) == ["--없는것"]
    assert _모르는스위치(["--찾기점수", "--빼고", "점검보고"]) == [], "값을 스위치로 봤다"
    assert _모르는스위치(["--찾기점수", "--제목벡터빼고"]) == []
    assert main(["--없는것"]) == 2, "모르는 스위치인데 그냥 돌았다"
    # 명령줄로 물었으면 명령줄로 답한다 — 창을 띄우면 답이 아니다
    assert main(["--도움말"]) == 0

    # ★ 정답을 여럿 받는다 — 하나만 받으면 **정답이 둘인 물음이 무조건 실패로 적힌다.**
    #   실사용에서 「아래 띠 말이 어색하던 것」의 1등이 「어색한 문장 고치기」였는데
    #   시험하는 쪽이 **사람 눈에도 그럴듯하다**고 했다. 그런 물음을 실패로 세면
    #   **고칠 것이 없는데 있다고 하는 숫자**가 된다.
    본문2 = _소스글()
    assert not 본문2 or '정답칸.split(";")' in 본문2, "정답을 여럿 못 받는다"
    assert not 본문2 or "min(자리) if 자리 else 0" in 본문2, "여럿 중 제일 위를 안 센다"

    # (이 글자들은 이 파일에서 `--doctor` 자리에만 있다 — 진단 묶음 쪽은 report.py 다)
    본문 = _소스글()
    for 있어야 in ('report["판 적합률"]', '그중 흐린 선'):
        assert not 본문 or 있어야 in 본문, f"--doctor 에 「{있어야}」가 없다"

    print("eb self-check 통과")


def 말하기(said: str) -> None:
    """콘솔이 있으면 찍고, 없으면 조용히 넘어간다.

    **창 프로그램(`--noconsole`)에서는 `sys.stdout` 이 `None` 이다.** `print` 는
    그때 조용히 넘어가지만 `sys.stdout.flush()` 는 터진다 — 그러면 PyInstaller 가
    오류창을 띄우고, 그 창은 다른 창 뒤에 가려져 보이지도 않는데 **아무도 안 눌러서
    프로세스가 영영 안 나간다.** 낯선 PC 에서 「일은 1초에 끝나는데 서 있다」로
    나흘 걸려 잡힌 자리다. 콘솔에 쓰는 일은 전부 이 문으로만 지난다.
    """
    if sys.stdout is None:
        return
    # ★ **못 찍는 글자는 닮은 글자로 바꿔 찍는다.** 그냥 막기만 하면
    # cp949 콘솔에서 줄마다 `—` 같은 기호가 섞여 읽기가 나빴다.
    마름 = getattr(sys.stdout, "encoding", None) or "utf-8"
    if 마름.lower() not in ("utf-8", "utf8"):
        for 이것, 저것 in (("—", "-"), ("–", "-"), ("…", "..."),
                          ("→", "->"), ("↔", "<->"), (chr(0x26A0), "!")):
            if 이것 in said:
                said = said.replace(이것, 저것)
    try:
        try:
            print(said)
        except UnicodeEncodeError:
            # ★ **못 찍는 글자 하나로 한 마디를 통째로 버리지 않는다.**
            # 앞의 막이가 안 먹는 자리가 있어 여기서 한 번 더 받는다.
            마름 = getattr(sys.stdout, "encoding", None) or "utf-8"
            print(said.encode(마름, "backslashreplace").decode(마름, "replace"))
        sys.stdout.flush()
    except (AttributeError, OSError, ValueError) as e:
        # ★ **말이 안 나갔으면 왜 안 나갔는지라도 남긴다.** 조용히 삼키면
        # 시험하는 쪽 눈에는 「아무 말도 안 한다」로만 보이고 원인을 못 찾는다.
        try:
            report.trail(f"콘솔에 못 찍음: {type(e).__name__}: {e}")
        except Exception:
            pass


if __name__ == "__main__":
    # **한 번 쓰고 끝나는 스위치가 터지면 조용히 죽으면 안 된다 — 그리고 안 죽어도
    # 안 된다.** 창 프로그램에서 안 잡힌 예외가 나면 PyInstaller 가 오류창을 띄우는데,
    # 그 창은 다른 창 뒤에 가려져 보이지도 않고 아무도 안 눌러서 **프로세스가 영영
    # 안 나간다.** 사람 눈에는 「말없이 멈춰 있다」로 보인다.
    # 그래서 스위치가 도는 동안만 이 그물을 건다 — 자국에 남기고 곧바로 나간다.
    # (화면이 뜬 뒤에는 걷는다. 거기서는 죽지 않고 살아 있는 것이 옳다.)
    def _스위치가_죽으면(kind, err, tb):
        report.log_crash(err)
        report.trail(f"스위치에서 죽음: {kind.__name__}: {err}")
        말하기(f"{kind.__name__}: {err}")
        os._exit(1)

    sys.excepthook = _스위치가_죽으면

    if "--진단모음" in sys.argv or "--report" in sys.argv:
        # 사람이 폴더를 뒤질 필요 없이 **파일 하나**를 보내면 된다.
        made = report.bundle()
        말하기(f"진단 묶음을 만들었다:{chr(10)}  {made}{chr(10)}"
              f"이 파일 하나만 보내면 된다. 기록 내용·토큰·사용자 이름은 안 들어 있다.")
        raise SystemExit(0)

    if "--그물시험" in sys.argv or "--net-test" in sys.argv:
        # **그물이 도는지 원격에서 재 볼 길.** 스위치가 터졌을 때 자국에 남기고
        # 곧바로 나가는지는, 터뜨려 보지 않으면 확인할 방법이 없다 —
        # 낯선 PC 가 「그물이 정말 도는지는 확인 못 했다」고 남겼다.
        # 앞서 로그 폭증 방어도 같은 이유로 스위치를 뒀다.
        raise RuntimeError("그물이 도는지 보려고 일부러 터뜨린 것이다")

    if "--색인다시" in sys.argv or "--reindex" in sys.argv:
        # **색인은 언제나 다시 만들 수 있다.** 기록(.md)이 원본이고 색인은 그것을 훑어
        # 만든 것뿐이라, 어긋났다 싶으면 통째로 버리고 다시 만드는 것이 제일 확실하다.
        # 켤 때 저절로 고치기도 하지만, 사람이 손으로 시킬 길도 있어야 한다.
        import time as clock

        from notes import Notes

        t0 = clock.perf_counter()
        n = Notes(paths.notes_dir(), str(paths.index_path()), index_now=False)
        n.conn.execute("DELETE FROM vectors")
        n.conn.execute("UPDATE notes SET vec_mtime = 0")
        # ★ **「다시 만든다」면 통째로 다시 만들어야 한다.** `reindex()` 는 원래
        # **바뀐 파일만** 읽는다(그게 켤 때는 옳다). 그런데 이 스위치를 부르는 까닭은
        # 대개 **규칙이 바뀌었기 때문**이다 — 파일은 그대로인데 읽는 법이 달라진 것이다.
        # 그때 「바뀐 파일만」 보면 아무것도 안 바뀌어서 **0.3초에 끝나고 옛 값이
        # 그대로 남는다.** 실제로 「흡수한 글의 `[[ ]]` 는 안 센다」를 고쳤는데
        # 옛 링크 여섯이 그대로 남아 「적은 것 4」가 안 내려갔다.
        #
        # 그래서 **파일에서 나온 것은 통째로 비우고 다시 쌓는다.** 기록(.md)이 원본이라
        # 잃을 것이 없다. 20년치라도 이 길이 있어야 규칙 하나 고칠 때마다 통째로
        # 다시 흡수하지 않는다.
        for 표 in ("notes", "links", "tags", "aliases"):
            n.conn.execute(f"DELETE FROM {표}")
        n.conn.execute("DELETE FROM search")
        n.conn.commit()
        n.reindex()
        said = (f"색인을 통째로 다시 만들었다 ({clock.perf_counter() - t0:.1f}초){chr(10)}"
                f"  항목 {n.conn.execute('SELECT count(*) FROM notes').fetchone()[0]}개"
                f" · 본문이 빈 항목 {n.blank_count()}개{chr(10)}"
                f"  뜻 벡터는 뒤에서 다시 만든다 — 켜 두면 채워진다"
                f" (지금 만들 거리 {n.vec_left()}개){chr(10)}"
                f"  기록(.md)은 안 건드렸다.")
        (paths.data_dir() / "vc-색인다시.txt").write_text(said, encoding="utf-8")
        n.conn.close()
        말하기(said)
        # **일을 마쳤으면 반드시 나간다.** 설치본에서 이 스위치만 할 일을 다 하고도
        # 안 죽었다(CPU 0.3초, 실 1개로 서 있었다). 소스로는 재현이 안 돼 원인을 못
        # 짚었는데, 한 번 쓰고 끝나는 스위치라 남은 것을 기다릴 이유가 없다.
        # 파일도 DB 도 이미 닫았으니 잃을 것이 없다.
        os._exit(0)

    if "--판올리기" in sys.argv:
        # ★★ **옛 판 항목을 지금 판으로 올린다. 다시 붓지 않고.**
        #
        # 다시 붓기는 **색인을 새로 만드는 수단이지 노트를 고치는 수단이 아니다** —
        # 사람이 손댄 것을 지우기 때문이다. 그래서 노트를 고쳐야 하면 이 길로 온다.
        #
        # 0판 → 1판이 할 일 셋(붓기 전 사본 3142장에서 실측):
        #   스키마 칸이 없다      3142장 → `스키마: 1` 을 박는다
        #   앞머리가 두 겹이다     122장  → 본문 맨 앞 `---` 블록을 앞머리로 올린다
        #   제목에 `--` 가 있다    34장   → 꾸밈이 하이픈으로 뭉갠 것. 이름을 바꾼다
        #
        # ★ 이름 바꾸기는 **여러 파일**을 건드린다(역링크·이력 폴더). `notes.rename` 이
        #   그걸 한 덩어리로 하고 **하다 만 것을 쪽지로 남긴다.**
        import re as _re

        from notes import Note, Notes, 적는판

        _앞머리꼴 = _re.compile(r"\A---\n.*?\n---\n", _re.S)

        뿌리 = paths.notes_dir()
        사람것 = _사람이손댄것(뿌리)      # 세는 것은 늘 된다. 막이는 쓰기 앞에만 선다
        쓸까 = "--쓴다" in sys.argv or "--write" in sys.argv
        n = Notes(뿌리, str(paths.index_path()), index_now=False)

        올릴것, 이름바꿀것 = [], []
        모두 = 0
        for 길 in n.notes_files():
            try:
                글 = 길.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            모두 += 1
            머리 = 글.split(chr(10) + "---", 1)[0]
            할일 = []
            if f"스키마: {적는판}" not in 머리:
                할일.append("판")
            # ★ **가로줄을 두 겹으로 세지 않는다.** 처음엔 줄바꿈+`---` 이 두 번
            # 나오면 두 겹으로 쳤는데, **본문에 흔한 가로줄**이 그대로 걸렸다 —
            # 3142장에서 122장이 그 꼴이었고 **진짜 두 겹은 0장**이었다.
            # 두 겹은 「앞머리를 뗀 나머지가 **또 `열쇠: 값` 꼴로 시작**하는 것」이다.
            뗀뒤 = _앞머리꼴.sub("", 글, count=1)
            if 뗀뒤 != 글 and _re.match(r"\A---\n[^\n]*:", 뗀뒤):
                할일.append("앞머리")
            깨끗 = _re.sub(r"-{2,}", "", 길.stem).strip()
            if 깨끗 != 길.stem and 깨끗:
                할일.append("제목")
                이름바꿀것.append((길.stem, 깨끗))
            if 할일:
                올릴것.append((길, 할일))

        셈 = {"판": 0, "앞머리": 0, "제목": 0}
        for _, 할일 in 올릴것:
            for t in 할일:
                셈[t] += 1
        줄 = [f"판 올리기 — 항목 {모두}장 · 지금 판 {적는판}",
              f"  올릴 것 {len(올릴것)}장",
              f"    스키마 칸 없음 {셈['판']} · 앞머리 두 겹 {셈['앞머리']}"
              f" · 제목에 -- {셈['제목']}"]
        if 사람것:
            줄.append(f"  ★ 사람이 손댄 항목 {len(사람것)}개 — 이대로는 안 쓴다"
                      f" (예: {', '.join(사람것[:3])})")

        if not 쓸까:
            줄 += ["", "**아무것도 안 고쳤다.** 셀 것만 세어 봤다.",
                   "  이대로 올리려면 뒤에 --쓴다 를 붙여라.", "",
                   "이름이 바뀔 것 스무 개 미리보기:", "-" * 72]
            for 옛, 새 in 이름바꿀것[:20]:
                줄.append(f"  {옛[:44]}")
                줄.append(f"    → {새[:44]}")
        else:
            if 사람것 and "--손댄것도쓴다" not in sys.argv:
                말하기(chr(10).join(줄) + chr(10) * 2
                       + f"★ 사람이 손댄 기록이 {len(사람것)}개 있어 **안 고쳤다.**"
                       + chr(10) + "  세는 것은 늘 된다 — 위 숫자를 보고 정하면 된다."
                       + chr(10) + "  그래도 올리려면 --손댄것도쓴다 를 붙여라.")
                os._exit(1)
            # ★★ **이름부터 바꾸고, 그 다음에 남은 것을 모두 박는다.**
            # 처음에는 반대로 했다 — 이름 바꿀 것은 건너뛰고 나중에 바꿨는데,
            # **이름 바꾸기가 실패한 항목은 두 고리 사이로 빠져** 이름도 안 바뀌고
            # 스키마도 안 박혔다(3142장 중 1장이 그랬다). 순서를 뒤집으면
            # 실패해도 **두 번째 고리가 반드시 줍는다.**
            바꾼이름 = 0
            못바꾼 = []
            for 옛, 새 in 이름바꿀것:
                # 역링크·이력 폴더까지 같이 옮긴다. 하다 말면 쪽지가 남는다.
                if n.rename(옛, 새):
                    바꾼이름 += 1
                else:
                    못바꾼.append(옛)
            고친것 = 0
            for 길 in list(n.notes_files()):
                try:
                    머리 = 길.read_text(encoding="utf-8", errors="replace").split(
                        chr(10) + "---", 1)[0]
                except OSError:
                    continue
                if f"스키마: {적는판}" in 머리:
                    continue
                쪽 = n.read_at(str(길))
                if 쪽 is None:
                    continue
                # `write` 가 앞머리를 끌어올리고 스키마를 박는다. 지난 판도 남긴다.
                n.write(쪽, str(길))
                고친것 += 1
            n.reindex()
            남 = sum(1 for 길 in n.notes_files()
                     if f"스키마: {적는판}" not in
                     길.read_text(encoding="utf-8", errors="replace").split(
                         chr(10) + "---", 1)[0])
            줄 += ["", f"**{고친것}장 고치고 이름 {바꾼이름}개 바꿨다.**"
                       " 지난 판(`.이력/`)에 남겼다 — 되돌릴 수 있다.",
                   f"  아직 옛 판: {남}장"]
            if 못바꾼:
                줄.append(f"  ★ 이름을 못 바꾼 것 {len(못바꾼)}개"
                          f" (새 이름이 이미 있는 것들이다): {', '.join(못바꾼[:3])}")

        n.conn.close()
        (paths.data_dir() / "vc-판올리기.txt").write_text(chr(10).join(줄), encoding="utf-8")
        말하기(chr(10).join(줄[:12]) + chr(10)
               + f"  적었다: {paths.data_dir() / 'vc-판올리기.txt'}")
        os._exit(0)

    if "--휴지통" in sys.argv:
        # ★★ **버린 것은 여기 있다. 그리고 여기만 안 찾는다.**
        # 찾기·색인·그물은 이 자리를 아예 안 본다 — 「찾으라고 하기 전까지
        # 안 찾는다」(오너 결정 2026-09-09). 그러니 부를 길이 하나는 있어야 한다.
        자리 = paths.휴지통자리()
        것들 = sorted(자리.glob("*.md")) if 자리.is_dir() else []
        뒤에 = sys.argv[sys.argv.index("--휴지통") + 1:]
        찾을말 = next((a for a in 뒤에 if not a.startswith("-")), "")
        줄 = [f"휴지통: {자리}", f"  담긴 것 {len(것들)}개"]
        보인 = 0
        for f in 것들:
            try:
                글 = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if 찾을말 and 찾을말 not in 글:
                continue
            보인 += 1
            if 보인 > 40:
                continue
            몸 = 글.split(chr(10) + "---" + chr(10), 1)[-1].strip()
            첫 = next((t.strip() for t in 몸.splitlines() if t.strip()), "")
            줄.append(f"  {f.stem}")
            줄.append(f"      {첫[:88]}")
        if 찾을말:
            줄.insert(2, f"  「{찾을말}」이 든 것 {보인}개")
        if 보인 > 40:
            줄.append(f"  … 앞 40개만 보였다 (모두 {보인}개)")
        줄 += ["", "  되살리려면 그 파일을 글 폴더로 옮겨라 — 파일이 곧 항목이다.",
               f"  글 폴더: {paths.notes_dir()}"]
        (paths.data_dir() / "vc-휴지통.txt").write_text(chr(10).join(줄), encoding="utf-8")
        말하기(chr(10).join(줄[:12]) + chr(10)
               + f"  적었다: {paths.data_dir() / 'vc-휴지통.txt'}")
        os._exit(0)

    if "--사본치우기" in sys.argv:
        # ★★ **본문이 똑같은 항목을 하나만 남긴다.**
        #
        # 같은 글이 두 나무에서 흡수되면 사본이 생긴다 — 볼트에 한 벌, 프로젝트
        # 폴더 안 옛 기록에 한 벌. 실측으로 3183장 중 **388장(12.2%)** 이 그랬다.
        # 그물에서 「사본끼리 잇는 선」이 나오는 것도 여기서 온다.
        #
        # ★ **지우지 않고 `.이력/` 으로 치운다.** 지우면 되돌릴 수가 없다 —
        # `delete()` 는 파일을 그냥 없앤다. 치워 두면 파일이 남아 되살릴 수 있다.
        #
        # ★ **미리보기가 기본이다.** `--쓴다` 를 붙여야 실제로 움직인다.
        import hashlib
        import re as _re
        from collections import defaultdict

        import ingest
        from notes import Notes

        뿌리 = paths.notes_dir()
        # ★★ **막이는 쓰는 것을 막지, 보는 것을 막지 않는다.**
        # 처음에는 세는 것까지 막았다 — 「먼저 세어만 봐라」를 시켜 놓고
        # **셀 수가 없었다.** 보는 것이 막히면 **정할 근거가 없어지고 남는 길은
        # 「그래도 쓴다」뿐**이라, 안전장치가 오히려 **위험한 쪽으로 몬다.**
        # 그래서 세는 것은 늘 되고, **쓰기 직전에만** 막는다.
        사람것 = _사람이손댄것(뿌리)

        앞머리 = _re.compile(r"\A---\n.*?\n---\n?", _re.S)
        n = Notes(뿌리, str(paths.index_path()), index_now=False)
        몸별 = defaultdict(list)
        모두 = 0
        for 길 in n.notes_files():
            try:
                글 = 길.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            모두 += 1
            몸 = 앞머리.sub("", 글).strip()
            # ★★ **빈 글은 아예 뺀다.** 비어 있는 두 글은 **같은 내용을 가진 게 아니라
            # 내용이 없는 것**이다 — 「본문이 똑같다」가 성립하지 않는 자리다.
            # 바닥값을 넣으면서 이 줄을 지웠더니 **제목 밑동 예외가 바닥값을 뚫고**
            # 빈 글끼리 묶였다(시험 쪽이 잡았다). 특히 창에서 「새 항목」으로 만들어
            # 두고 **아직 안 쓴 글**이 사본으로 치워질 뻔했다.
            # (물건은 이미 이걸 따로 센다 — `--doctor` 의 「본문이 빈 항목」)
            if not 몸:
                continue
            # ★★ **너무 짧으면 짝을 안 짓는다.**
            #
            # 본문만 보고 짝을 지었더니 **두 글자짜리 본문 셋**이 한 뭉치가 되어,
            # 제목이 서로 다른 딴 글이 「치울 것」에 들어갔다(시험 쪽이 잡았다):
            #   「활동두번째」·「줄이 겹친다」·「띄우기시험」 — 본문이 다 두 글자
            #
            # **13071자가 같은 것과 두 글자가 같은 것을 한 잣대로 다루면 안 된다.**
            # 긴 글이 글자까지 같으면 사본이 맞지만, 짧은 글이 같은 것은 그냥
            # **짧아서** 같은 것이다. 흡수의 「너무 짧다」와 같은 바닥값을 쓴다.
            # 짧은 것은 **제목까지 같을 때만** 짝을 짓는다. 시험 쪽이 갈랐다:
            #   본문 같음 · 제목 다름  → 사본 아님 (그냥 짧아서 같다)
            #   본문 같음 · 제목도 같음 → **진짜 사본**  ← 바닥값만 두면 이걸 놓친다
            # 「8월 회의록」 셋이 본문 20자로 같고 제목도 같은데 안 잡혔다.
            짧다 = len(" ".join(몸.split())) < ingest.짧은조각
            # 제목은 **밑동**으로 본다. 겹칠 때 붙는 꼬리(` 2`·` (출처)`)를 뗀다 —
            # 「8월 회의록」·「8월 회의록 2」·「8월 회의록 3」은 같은 글의 사본이다.
            밑동 = _re.sub(r"\s*\([^)]*\)\s*$", "", 길.stem)
            밑동 = _re.sub(r"\s+\d+$", "", 밑동).strip()
            지문 = hashlib.sha256(
                (" ".join(몸.split()) + (chr(31) + 밑동 if 짧다 else "")
                 ).encode("utf-8")).hexdigest()
            몸별[지문].append(길)
            continue


        치울것, 지킨것, 건너뛴것 = [], [], []
        for 같은것 in 몸별.values():
            if len(같은것) < 2:
                continue
            # **짧은 제목을 남긴다.** 긴 쪽은 겹쳐서 출처가 덧붙은 것이다
            # (`0단계 실제 결과 (eb)` ← `0단계 실제 결과`). 같으면 먼저 만든 것.
            차례 = sorted(같은것, key=lambda q: (len(q.stem), q.stem))
            남길, 뺄것 = 차례[0], 차례[1:]
            for 길 in 뺄것:
                # ★ **가리키는 것이 있으면 안 치운다.** 치우면 그 이음이 허공을 가리킨다.
                걸린 = n.conn.execute(
                    "SELECT count(*) FROM links WHERE dst = ?", (길.stem,)).fetchone()[0]
                if 걸린:
                    건너뛴것.append((길.stem, 걸린))
                    continue
                치울것.append((길, 남길.stem))
            지킨것.append(남길.stem)

        줄 = [f"사본 치우기 — 항목 {모두}장",
              f"  본문이 똑같은 뭉치 {len(지킨것)}개 · 치울 것 {len(치울것)}장",
              f"  가리키는 것이 있어 그냥 둔 것 {len(건너뛴것)}장",
              f"  (본문 {ingest.짧은조각}자 미만은 **제목 밑동까지 같을 때만** 짝을 짓는다)"]
        if 사람것:
            줄.append(f"  ★ 사람이 손댄 항목 {len(사람것)}개 — 이대로는 안 쓴다"
                      + f" (예: {', '.join(사람것[:3])})")
        for 이름, 몇 in 건너뛴것[:5]:
            줄.append(f"      {몇}개가 가리킨다: {이름[:52]}")

        if "--쓴다" not in sys.argv and "--write" not in sys.argv:
            줄 += ["", "**아무것도 안 치웠다.** 셀 것만 세어 봤다.",
                   "  이대로 치우려면 뒤에 --쓴다 를 붙여라.", "",
                   "치울 것 스무 개 미리보기:", "-" * 72]
            for 길, 남는 in 치울것[:20]:
                줄.append(f"  치움: {길.stem[:46]}")
                줄.append(f"    남길 것: {남는[:46]}")
        else:
            # 여기서부터가 **쓰는 자리**다. 막이는 여기 선다.
            if 사람것 and "--손댄것도쓴다" not in sys.argv:
                말하기(chr(10).join(줄) + chr(10) * 2
                       + f"★ 사람이 손댄 기록이 {len(사람것)}개 있어 **안 썼다.**"
                       + chr(10) + "  세는 것은 늘 된다 — 위 숫자를 보고 정하면 된다."
                       + chr(10) + "  그래도 치우려면 --손댄것도쓴다 를 붙여라.")
                os._exit(1)
            움직인 = 0
            for 길, _ in 치울것:
                try:
                    # **치우기 전에 지난 판으로 남긴다.** 그래야 되살릴 수 있다.
                    n.keep_history(길, 길.read_text(encoding="utf-8"), always=True)
                except (OSError, ValueError):
                    pass
                if n.delete(길.stem):
                    움직인 += 1
            n.reindex()
            줄 += ["", f"**{움직인}장 치웠다.** 지난 판(`.이력/`)에 남겨 뒀다 — 되살릴 수 있다.",
                   f"  남은 항목: {n.conn.execute('SELECT count(*) FROM notes').fetchone()[0]}장"]

        n.conn.close()
        (paths.data_dir() / "vc-사본치움.txt").write_text(chr(10).join(줄), encoding="utf-8")
        말하기(chr(10).join(줄[:14]) + chr(10)
               + f"  적었다: {paths.data_dir() / 'vc-사본치움.txt'}")
        os._exit(0)

    if "--찾기점수" in sys.argv or "--score" in sys.argv:
        # **판마다 못 재면 「그대로일 것이다」로 넘어간다.** 실제로 열일곱 판 동안 찾기
        # 등수를 한 번도 안 쟀다 — 그 사이 벡터 쓰는 자리를 여러 번 건드렸는데도.
        # 다섯 물음을 손으로 치고 화면을 읽는 데 5~10분이 드니 안 하게 된 것이다.
        # 물음과 정답을 적은 파일 하나면 스무 물음도 한 번에 잰다.
        import time as clock

        from brain import onnx_embedder
        from notes import Notes

        # **`--빼고` 뒤의 값은 위치 인자가 아니다.** 안 걸러 내면 그것이 물음 파일로
        # 잡혀 「물음 파일이 없다: guidelines」로 죽는다.
        준것, 건너뛸 = [], False
        for a in sys.argv[1:]:
            if 건너뛸:
                건너뛸 = False
                continue
            if a in ("--빼고", "--without"):
                건너뛸 = True
            elif not a.startswith("-"):
                준것.append(a)
        물음표 = Path(준것[0]) if 준것 else (paths.data_dir() / "찾기물음.txt")
        if not 물음표.exists():
            말하기(f"물음 파일이 없다: {물음표}{chr(10)}"
                   f"  한 줄에 하나씩 「물음 | 정답 제목」 꼴로 적어 두면 된다.")
            os._exit(1)

        n = Notes(paths.notes_dir(), str(paths.index_path()), index_now=False)
        n.use_embedder(onnx_embedder(paths.meaning_dir()))
        # ★ `--제목벡터빼고` 로 **제목 벡터를 빼고** 같은 물음을 다시 잰다.
        # 뜻 검색은 「카드 벡터」와 「제목 벡터」 중 가까운 쪽을 쓰는데, 그 최댓값이
        # 답을 덮는 자리가 나왔다(엉뚱한 글의 제목 벡터가 정답의 본문 벡터를 이겼다).
        # 기본은 안 바꾼다 — 지금 방식은 실측으로 정한 것이라 **같은 잣대로 다시
        # 재기 전에는 못 바꾼다.** 그 재기를 할 수 있게 길만 낸다.
        if "--제목벡터빼고" in sys.argv:
            n.제목벡터끄기 = True

        # ★ **어디서 흡수해 온 것을 빼고 재는 길.** 흡수 뒤 점수가 떨어졌을 때
        # 「흡수한 글이 원래 글을 밀어낸 것」인지 「원래부터 그랬는지」를 가르려면
        # 흡수분만 빼고 다시 재면 된다. 항목을 옮겼다 되돌리는 것보다 **안전하다** —
        # 되돌리다 잃는 것이 없다. 앞머리 `출처:` 에 이 글이 든 항목을 뺀다.
        뺄것 = ""
        for i, a in enumerate(sys.argv):
            if a in ("--빼고", "--without") and i + 1 < len(sys.argv):
                뺄것 = sys.argv[i + 1]
        뺀수 = 0
        if 뺄것:
            # `출처` 는 앞머리에만 있고 DB 에는 없다 — 파일을 읽어 본다.
            # 한 번 쓰고 끝나는 스위치라 이 값은 치러도 된다.
            뺀제목 = set()
            for r in n.conn.execute("SELECT title FROM notes"):
                쪽 = n.read(r["title"])
                if 쪽 is not None and 뺄것 in str(
                        (getattr(쪽, "extra", None) or {}).get("출처", "")):
                    뺀제목.add(r["title"])
            뺀수 = len(뺀제목)

        줄 = ["물음 | 정답 | 등수 | 1등", "-" * 72]
        등수들 = []
        t0 = clock.perf_counter()
        for 한줄 in 물음표.read_text(encoding="utf-8").splitlines():
            한줄 = 한줄.strip()
            if not 한줄 or 한줄.startswith("#") or "|" not in 한줄:
                continue
            물음, _, 정답칸 = (조각.strip() for 조각 in 한줄.partition("|"))
            # ★ **정답이 여럿일 수 있다.** `정답1; 정답2` 로 적는다.
            #
            # 하나만 받으면 **정답이 둘인 물음은 무조건 실패로만 적힌다** —
            # 실사용에서 「아래 띠 말이 어색하던 것」의 1등이 「어색한 문장 고치기」로
            # 나왔는데, 시험하는 쪽이 **사람 눈에도 그럴듯하다**고 했다. 그런 물음을
            # 실패로 세면 **숫자가 거짓말을 한다** — 고칠 것이 없는데 있다고 한다.
            # 정답을 여럿 적을 수 있으면 「물음이 무른 것」과 「물건이 못 찾는 것」이 갈린다.
            정답들 = [t.strip() for t in 정답칸.split(";") if t.strip()]
            정답 = 정답들[0] if 정답들 else 정답칸
            if 뺄것:
                # ★ **순위를 매긴 뒤에 빼면 안 된다.** 처음에 그렇게 만들었더니
                # 상위 여덟 칸이 통째로 뺄 것이면 **보여 줄 게 하나도 안 남아**
                # 「(없음)」이 됐다 — 실제로 다섯 물음이 그랬다. 그러면 「밀려났다」와
                # 「아예 못 잰다」가 안 갈리고, 빼기 전 값과도 견줄 수가 없다.
                # **넉넉히 뽑아 놓고 빼고 나서 위에서 여덟을 센다.**
                찾음 = [r["title"] for r in n.search(물음, k=200)
                        if r["title"] not in 뺀제목][:8]
            else:
                찾음 = [r["title"] for r in n.search(물음)]
            # 여럿이면 **제일 위에 온 것**으로 센다. 하나만 맞아도 맞은 것이다.
            자리 = [찾음.index(t) + 1 for t in 정답들 if t in 찾음]
            등수 = min(자리) if 자리 else 0                      # 0 = 목록 밖
            맞은것 = next((t for t in 정답들 if t in 찾음), 정답)
            등수들.append(등수)
            보일정답 = 맞은것 if 등수 else " 또는 ".join(정답들)
            줄.append(f"{물음} | {보일정답} | {등수 or '밖'} | {찾음[0] if 찾음 else '(없음)'}")
        센것 = len(등수들)
        일등 = sum(1 for r in 등수들 if r == 1)
        셋안 = sum(1 for r in 등수들 if 1 <= r <= 3)
        밖 = sum(1 for r in 등수들 if r == 0)
        뺌 = f" · 「{뺄것}」에서 온 {뺀수}개는 빼고 쟀다" if 뺄것 else ""
        # ★★ **켠 스위치는 제 몫을 머리글에 찍는다.**
        # 안 찍으면 **먹었는지를 값이 달라진 것으로만 알게 된다** — 값이 같게 나오는
        # 판에서는 「안 먹은 것」과 「달라진 게 없는 것」이 안 갈린다. 시험하는 쪽이
        # 없는 스위치를 주고 재서 **정반대 결론이 나올 뻔한** 자리다.
        if n.제목벡터끄기:
            뺌 += " · **제목 벡터를 빼고 쟀다**(본문 벡터만)"
        if 여럿 := sum(1 for l in 물음표.read_text(encoding="utf-8").splitlines()
                       if ";" in l.partition("|")[2]):
            뺌 += f" · 정답을 여럿 적은 물음 {여럿}개"
        said = (f"물음 {센것}개 · 1등 {일등} · 3등 안 {셋안} · 목록 밖 {밖}"
                f" · {clock.perf_counter() - t0:.1f}초{뺌}{chr(10)}{chr(10)}"
                + chr(10).join(줄))
        (paths.data_dir() / "vc-찾기점수.txt").write_text(said, encoding="utf-8")
        n.conn.close()
        말하기(said.split(chr(10))[0] + chr(10)
               + f"  적었다: {paths.data_dir() / 'vc-찾기점수.txt'}")
        os._exit(0)

    if "--흡수" in sys.argv or "--ingest" in sys.argv:
        # **이 물건은 사람이 적는 것에서 AI가 적는 것으로 방향이 바뀌었다.**
        # 사람은 하루 두세 개를 적지만 AI는 이미 있는 자료를 통째로 들인다.
        # 그래서 여기서 제일 조심할 것은 **말없이 쌓지 않는 것**이다 —
        # 수천 개를 부어 놓고 나면 어느 것이 어디서 왔는지 되짚을 길이 없다.
        # `--쓴다`를 안 주면 **세어만 보고 아무것도 안 쓴다.**
        import time as clock

        import gate
        import ingest
        from notes import Note, Notes

        준것 = [a for a in sys.argv[1:] if not a.startswith("-")]
        if not 준것:
            말하기("어느 폴더를 들일지 알려 줘:  --흡수 " + chr(34) + "C:\고른\폴더" + chr(34))
            os._exit(1)
        # **빈칸 든 경로를 따옴표 없이 붙여넣는 일이 흔하다.** 그러면 여기 토막으로
        # 나뉘어 들어와 앞머리만 잡힌다(「D:\옵시디언\Second Brain」 → 「D:\옵시디언\Second」).
        # 붙여 본 것이 진짜 폴더면 그게 사람이 말한 자리다.
        뿌리 = Path(준것[0])
        이어붙임 = Path(" ".join(준것))
        if not 뿌리.is_dir() and 이어붙임.is_dir():
            뿌리 = 이어붙임
        if not 뿌리.is_dir():
            말하기(f"그런 폴더가 없다: {뿌리}{chr(10)}"
                   f"  빈칸이 든 경로면 따옴표로 감싸라.")
            os._exit(1)

        t0 = clock.perf_counter()
        # ★★ **이미 든 글은 다시 안 들인다.** 이걸 안 넘기면 같은 폴더를 두 번
        # 흡수할 때 통째로 다시 쌓인다 — 오너 기록 388장(12.2%)이 그렇게 생겼다.
        # `--사본치우기` 는 그 증상을 치우는 것이고, 원인은 여기다.
        이미 = set()
        try:
            from notes import Notes as _N

            _n = _N(paths.notes_dir(), str(paths.index_path()), index_now=False)
            for (몸,) in _n.conn.execute("SELECT body FROM notes"):
                굳힌 = " ".join((몸 or "").split())
                if 굳힌:
                    이미.add(ingest.hashlib.blake2b(
                        굳힌.encode("utf-8"), digest_size=16).hexdigest())
            _n.conn.close()
        except Exception:
            이미 = set()      # 색인을 못 읽어도 흡수는 돌아간다(겹침만 못 본다)
        # ★★ **휴지통에 있는 것도 「이미 본 것」이다.** 안 그러면 버린 조각을
        # 부을 때마다 문지기에게 다시 물어본다 — 자리마다 몇 십 초씩 든다.
        이미 |= _휴지통지문()
        조각들, s = ingest.들일것(뿌리, 이미)
        줄 = [f"흡수: {뿌리}", "", f"싼 문지기 — {s}"]
        말하기(chr(10).join(줄))

        # 비싼 문지기. 모델이 없으면 **거기서 멈춘다** — 문지기 없이 쌓으면
        # 과정 소음이 그대로 항목이 된다(기록 폴더는 그런 조각이 대부분이었다).
        골라낸 = []
        try:
            from engine import LocalEngine
            # **구운 뒤에는 `__file__` 이 `_internal` 안을 가리킨다.** 거기서 두 칸
            # 올라가면 엉뚱한 자리다 — `paths` 가 이미 언 것과 안 언 것을 갈라 준다.
            eng = LocalEngine(model_dir=str(paths.gguf_dir()))
            있는 = [m for m in eng.available() if "vl" not in m.lower()]
            if not 있는:
                # ★★ **넣으라고 말할 자리를 정확히 말한다.** 예전엔 `gguf_dir()` 을
                # 그대로 찍었는데, 모델이 없을 때 그 값은 **`_internal\models`** —
                # 프로그램 속이라 사람이 넣을 자리가 아니고 다음 판을 덮으면 지워진다.
                # 실제로 시험하는 쪽이 그 자리를 받아 멈췄다. **exe 옆을 말한다.**
                넣을자리 = (Path(sys.executable).parent / "models"
                          if paths.frozen() else paths.gguf_dir())
                raise RuntimeError(
                    f"글 모델이 없다. {넣을자리} 에 .gguf 를 넣어라 "
                    "(폴더가 없으면 만들어라 · 받는 자리는 지시서에)")
            이름 = 있는[0]

            def 말시키기(글: str) -> str:
                # 문지기는 늘 같은 답을 내야 한다. 갈리면 왜 들어왔는지 못 되짚는다.
                return eng.chat([{"role": "user", "content": 글}], model=이름,
                                temperature=0.0, max_tokens=400)

            def 알림(한것, 다, gs):
                말하기(f"  …{한것}/{다}  {gs}")

            골라낸, gs, 막힌 = gate.거르기(조각들, 말시키기, 알림)
            줄 += ["", f"비싼 문지기({이름}) — {gs}"]
            # ★ **죽은 문지기로 쌓지 않는다.** 모델이 통째로 안 돌면 셈은
            # 「다 통과」로 보인다 — 실제로 1058개가 1초 만에 전부 통과했다.
            # 그대로 쓰면 과정 소음이 그대로 항목이 되고 되돌릴 길이 없다.
            if gs.죽었나:
                raise RuntimeError(
                    f"절반 넘게 못 알아들었다({gs.몫 * 100:.0f}%). "
                    f"문지기가 아니라 죽어 있던 것이다. 탈: {gs.탈 or '(없음)'}")
        except Exception as e:
            줄 += ["", f"★ 비싼 문지기를 못 돌렸다: {type(e).__name__}: {e}",
                   "  문지기 없이 쌓으면 과정 소음이 그대로 항목이 된다. 안 쓴다."]
            (paths.data_dir() / "vc-흡수.txt").write_text(chr(10).join(줄),
                                                          encoding="utf-8")
            # ★ **센 것을 오류 옆에 다시 놓는다.** 멈춘 재도 「내 파일을 몇 장 봤나」는
            # 알아야 한다 — 막이는 쓰는 것을 막아야지 보는 것을 막으면 안 된다.
            말하기(chr(10).join(줄[-2:]) + chr(10) + f"  센 것: {s}")
            os._exit(1)

        걸린 = clock.perf_counter() - t0
        줄 += ["", f"{걸린:.0f}초 · 조각당 {걸린 / max(1, s.본것):.2f}초"]

        # ★★ **사람이 손댄 기록이 있으면 안 붓는다.**
        #
        # 지금은 기록이 전부 흡수분이라 다시 붓는 것이 공짜다 — 지울 사람 손질이
        # 없다. 그런데 **오너가 옵시디언에서 한 글자라도 고치는 순간 그 성질이
        # 사라진다.** 그때도 이 길이 열려 있으면 재수집이 **사람 손질을 지우는
        # 도구**가 된다. 되돌릴 수 없고, 지워졌다는 것조차 안 보인다.
        #
        # 그래서 규칙을 말이 아니라 **여기서 막는다** — 「다시 붓기는 색인을 새로
        # 만드는 수단이지 노트를 고치는 수단이 아니다」. 노트를 고쳐야 하면
        # 이행 스크립트로 한다(순서 있고, 여러 번 돌려도 같고, 배치마다 이력 남김).
        if "--쓴다" in sys.argv or "--write" in sys.argv:
            사람것 = _사람이손댄것(paths.notes_dir())
            if 사람것 and "--그래도쓴다" not in sys.argv:
                말하기(chr(10).join([
                    f"★ 사람이 손댄 기록이 {len(사람것)}개 있다. 다시 붓지 않는다.",
                    "",
                    "  재수집은 항목을 새로 만든다 — 사람이 고친 것은 **지워진다.**",
                    "  다시 붓기는 색인을 새로 만드는 수단이지 노트를 고치는 수단이 아니다.",
                    "  노트를 고쳐야 하면 이행 스크립트로 해라(되돌릴 자리를 남기면서).",
                    "",
                    "  손댄 것 몇 개:",
                    *[f"    {이름}" for 이름 in 사람것[:5]],
                    "",
                    "  그래도 지우고 부으려면 --그래도쓴다 를 붙여라.",
                ]))
                os._exit(1)

        if "--쓴다" not in sys.argv and "--write" not in sys.argv:
            줄 += ["", "**아무것도 안 썼다.** 들일 것만 세어 봤다.",
                   "  이대로 넣으려면 뒤에 --쓴다 를 붙여라.", "",
                   "들어올 것 스무 개 미리보기:", "-" * 72]
            # ★ **미리보기가 실제로 쓰일 제목과 같아야 한다.** 짧은 제목에 출처를
            # 붙이는 일을 쓰는 길에만 넣었더니, `--쓴다` 없이 본 사람이
            # 「출처가 안 붙는다」고 보고했다 — 붙는데 **미리보기가 안 보여 준 것**이다.
            # 미리보기가 딴것을 보여 주면 그걸로 판정할 수가 없다.
            본제목: set[str] = set()
            for c, 판 in 골라낸[:20]:
                보일 = gate.겹치지않게(판.제목, Path(c.출처).stem, 본제목)
                본제목.add(보일)
                줄.append(f"[{판.갈래}] {보일}  ←  {c.출처}:{c.줄}")
                줄.append(f"    {판.몸.splitlines()[0][:90] if 판.몸 else ''}")
            # ★ **막힌 것도 보여 준다.** 남긴 것만 찍으면 「이건 남겼어야 했다」를
            # 볼 길이 없다 — 문지기를 고치려면 그게 있어야 한다. 시험하는 쪽이
            # 「막힌 것을 볼 길이 없다」로 짚어 준 자리다.
            if 막힌:
                줄 += ["", f"막힌 것 {min(len(막힌), gate.막힌보기)}개 미리보기 (버린 것 {gs.버린것}개 중):",
                       "-" * 72]
                for c in 막힌[:gate.막힌보기]:
                    첫 = next((줄자.strip() for 줄자 in c.몸.splitlines()
                               if 줄자.strip()), "")
                    줄.append(f"  {c.출처}:{c.줄}")
                    줄.append(f"      {첫[:88]}")
        else:
            n = Notes(paths.notes_dir(), str(paths.index_path()), index_now=False)
            # ★ **서로 다른 조각에 같은 제목을 붙이면 조용히 덮어쓴다.**
            # 「Context」 「Summary」 같은 소제목은 문서마다 있다 — 첫 시험에서
            # 31개를 썼는데 파일은 29개였다(둘이 이력으로만 남았다). 7045 조각이면
            # 수십 번 난다. `write` 가 같은 제목을 「고치는 것」으로 보는 것은 옳고,
            # **겹치는 제목을 만들어 보내는 이쪽이 잘못**이다.
            #
            # 겹치면 어느 문서에서 왔는지를 붙인다 — 번호보다 이쪽이 찾는 데 쓸모 있다.
            있던제목 = {r["title"] for r in
                        n.conn.execute("SELECT title FROM notes")}
            앞수 = n.conn.execute("SELECT count(*) FROM notes").fetchone()[0]
            쓴것 = 0
            for c, 판 in 골라낸:
                # **어디서 왔는지를 항목에 박아 둔다.** AI가 쓴 것이라 사람이
                # 「이거 진짜야?」를 물을 때 원본으로 갈 길이 없으면 못 믿는다.
                제목 = gate.겹치지않게(판.제목, Path(c.출처).stem, 있던제목)
                있던제목.add(제목)
                note = Note(title=제목, body=판.몸, kind=판.갈래,
                            extra={"출처": f"{뿌리 / c.출처}", "줄": c.줄,
                                   "들인이유": 판.왜,
                                   "지은이": "문지기" if not 판.못알아들음 else "그대로"})
                try:
                    n.write(note)
                    쓴것 += 1
                except Exception as e:      # 한 항목 때문에 7천 개가 안 멈춘다
                    줄.append(f"  못 쓴 것: {제목} — {type(e).__name__}: {e}")
            # **센 것과 실제로 는 것이 같은지 확인한다.** 첫 시험에서 31개를 썼다고
            # 적어 놓고 파일은 29개였다 — 세는 쪽만 보면 잃은 것을 영영 모른다.
            판수 = n.conn.execute("SELECT count(*) FROM notes").fetchone()[0]
            n.conn.close()
            잃은 = gate.잃은수(쓴것, 앞수, 판수)
            # ★★ **버린 것은 지우지 않고 휴지통에 모은다** (오너 결정 2026-09-09).
            # 기록 폴더 **밖**이라 찾기·색인·그물 어디에도 안 들어간다 —
            # 「찾으라고 하기 전까지 안 찾는다」. 그리고 여기 있는 것은 다시 부어도
            # **문지기에게 또 안 물어본다** — 예전엔 같은 폴더를 열 번 부으면
            # 버린 조각을 열 번 물어봤다(시험 쪽이 잰 그 재심사다).
            버린수 = _휴지통에담기(막힌, 뿌리)
            if 버린수:
                줄.append(f"  버린 것 {버린수}개는 휴지통에 뒀다: {paths.휴지통자리()}")
            줄 += ["", f"**{쓴것}개 썼다.** 원본 파일은 하나도 안 건드렸다.",
                   f"  기록에 든 항목: {앞수} → {판수}개 (는 것 {판수 - 앞수})"]
            if 잃은:
                줄.append(f"  ★ 쓴 것보다 는 것이 적다 — {잃은}개가 겹쳐 덮였다.")

        (paths.data_dir() / "vc-흡수.txt").write_text(chr(10).join(줄), encoding="utf-8")
        말하기(chr(10).join(줄[-6:]) + chr(10)
               + f"  적었다: {paths.data_dir() / 'vc-흡수.txt'}")
        os._exit(0)

    if "--이음선" in sys.argv or "--links" in sys.argv:
        # **짐작한 이음선은 파일에도 DB 에도 안 쓰인다.** 그래서 화면에서 카드를 하나씩
        # 열지 않으면 셀 수가 없다 — 낯선 PC 가 「72 중 몇이 찍어낸 무리끼리인가」를
        # 물었는데 셀 길이 없었다. 통째로 뽑아 준다.
        from notes import Notes

        n = Notes(paths.notes_dir(), str(paths.index_path()), index_now=False)
        모두 = [r["title"] for r in n.conn.execute("SELECT title FROM notes ORDER BY title")]
        맞짝 = n.kin(모두)
        길 = n.kin(모두, 맞짝만=False)
        짝 = sorted({tuple(sorted((t, v[0]))) for t, v in 맞짝.items() if v})
        빈길 = [t for t, v in 길.items() if not v]
        줄 = [f"항목 {len(모두)}개 · 맞짝 이음선 {len(짝)}개 · 카드에 길이 없는 것 {len(빈길)}개",
              "", "== 맞짝(그래프 선) =="]
        줄 += [f"  {a}  ↔  {b}" for a, b in 짝]
        줄 += ["", "== 카드 줄(내가 꼽은 1등) =="]
        줄 += [f"  {t}  →  {v[0] if v else '(없음)'}" for t, v in sorted(길.items())]
        said = chr(10).join(줄)
        (paths.data_dir() / "vc-이음선.txt").write_text(said, encoding="utf-8")
        n.conn.close()
        말하기(줄[0] + chr(10) + f"  적었다: {paths.data_dir() / 'vc-이음선.txt'}")
        os._exit(0)

    if "--재보기" in sys.argv or "--bench" in sys.argv:
        # **프로그램이 스스로 잰다.** 사람이 「3초 기다렸더니 있었다」로는 30개와
        # 100개를 못 가른다. 낯선 PC 가 그 한계를 짚어 줘서 넣었다.
        import statistics
        import time as clock

        from brain import onnx_embedder
        from notes import Notes

        n = Notes(paths.notes_dir(), str(paths.index_path()), index_now=False)
        수 = n.conn.execute("SELECT count(*) FROM notes").fetchone()[0]
        말 = ["말이 안 통한 것", "이름 바꿔서 생긴 문제", "사진", "회의", "기록"]
        n.use_embedder(onnx_embedder(paths.meaning_dir()))
        n.search("몸풀기")                      # 첫 번을 빼야 캐시가 안 섞인다
        잰다 = []
        for _ in range(5):
            for q in 말:
                t0 = clock.perf_counter()
                n.search(q)
                잰다.append((clock.perf_counter() - t0) * 1000)
        빈것 = n.blank_count()
        said = (f"항목 {수}개에서 검색 {len(잰다)}번{chr(10)}"
                f"  가운뎃값 {statistics.median(잰다):.0f} ms{chr(10)}"
                f"  제일 빠른 것 {min(잰다):.0f} ms · 제일 느린 것 {max(잰다):.0f} ms{chr(10)}"
                f"  뜻 벡터 {n.conn.execute('SELECT count(*) FROM vectors').fetchone()[0]}개"
                f" · 아직 못 만든 것 {n.vec_left()}개 · 본문이 빈 항목 {빈것}개")
        (paths.data_dir() / "vc-재보기.txt").write_text(said, encoding="utf-8")
        말하기(said)
        raise SystemExit(0)

    if "--예외시험" in sys.argv or "--log-test" in sys.argv:
        # **일부러 예외를 500번 낸다.** 같은 예외가 쏟아져도 로그가 안 부푸는지
        # 낯선 PC 에서 직접 재 보라고 둔 스위치다 — 5차 시험에서 예외가 한 건도
        # 안 나서 그 방어가 실제로 도는지 못 봤다.
        death = paths.data_dir() / report.DEATH
        before = death.stat().st_size if death.exists() else 0
        for _ in range(500):
            try:
                raise RuntimeError("일부러 낸 시험용 오류")
            except RuntimeError as err:
                report.log_crash(err)
        after = death.stat().st_size if death.exists() else 0
        said = (f"같은 예외 500번을 냈다.{chr(10)}"
                f"  죽음 기록 {before} -> {after} 바이트 (늘어난 것 {after - before})"
                f"{chr(10)}  막지 않았다면 수십 KB 가 됐어야 한다.{chr(10)}"
                f"  파일: {death}")
        (paths.data_dir() / "vc-예외시험.txt").write_text(said, encoding="utf-8")
        말하기(said)
        raise SystemExit(0)

    if "--진단" in sys.argv or "--doctor" in sys.argv:
        # 설치본이 무엇을 어디서 찾는지 **직접 물어본다.** 콘솔이 없어 안 보이므로
        # 파일로 남긴다. 뭔가 안 될 때 이것부터 본다.
        import json

        from brain import onnx_embedder, pin_runtime

        m = paths.models_dir()
        report = {
            "설치본인가": paths.frozen(),
            "딸린 것 자리": str(paths.app_dir()),
            "모델 자리": str(m),
            "모델 있나": (m / "model.onnx").exists(),
            "낱말표 있나": (m / "tokenizer.json").exists(),
            "기록 자리": str(paths.data_dir()),
            "런타임 붙듦": pin_runtime(),
        }
        # 사람이 이 값으로 「왜 벡터가 모자라지」를 스스로 가른다. 없어서 못 갈랐다.
        try:
            from notes import Notes

            n = Notes(paths.notes_dir(), str(paths.index_path()), index_now=False)
            셈 = lambda q: n.conn.execute(q).fetchone()[0]
            report["항목 수"] = 셈("SELECT count(*) FROM notes")
            # ★ **판 적합률은 여기에도 있어야 한다.** 창이 안 뜨는 판에서는
            # `--doctor` 만 돌아가는데, **그때 이 값이 제일 필요하다.**
            # 시험하는 쪽이 「--doctor 에는 없고 --report 에만 있다」로 짚었다.
            import notes as _n

            옛것, 모두 = [], 0
            for 파일 in n.notes_files():
                try:
                    머리 = 파일.read_text(encoding="utf-8", errors="replace").split(
                        chr(10) + "---", 1)[0]
                except OSError:
                    continue
                모두 += 1
                if f"스키마: {_n.적는판}" not in 머리:
                    옛것.append(파일.stem)
            맞은 = 모두 - len(옛것)
            report["판 적합률"] = (f"{맞은}/{모두} ({맞은 / max(1, 모두) * 100:.1f}%)가 "
                                  f"{_n.적는판}판")
            if 옛것:
                report["아직 옛 판"] = f"{len(옛것)}개"
                report["아직 옛 판 (이름 몇 개)"] = 옛것[:8]
            report["연결 수"] = 셈("SELECT count(*) FROM links")
            # 듣는 자리를 적는다 — 창을 못 띄우는 판에서도 이건 알아야 한다.
            report["듣는 자리"] = (
                f"{HOST}:{PORT}"
                + (" ← 같은 공유기의 다른 기기에서도 닿는다 (--no-server 로 끈다)"
                   if HOST == "0.0.0.0" else ""))
            report["  그중 흐린 선"] = 셈("SELECT count(*) FROM links WHERE 흐림 = 1")
            report["뜻 벡터 수"] = 셈("SELECT count(*) FROM vectors")
            report["아직 못 만든 벡터"] = n.vec_left()
            report["본문이 빈 항목"] = n.blank_count()
            # **어느 것이 비었다고 세는지 이름을 보여 준다.** 숫자만으로는
            # 「카운터가 틀렸나, 본문이 정말 DB 에 없나」를 못 가른다 —
            # 낯선 PC 에서 그 둘을 가르지 못해 멈췄다.
            report["빈 것으로 센 항목"] = [r[0] for r in n.conn.execute(
                "SELECT title FROM notes WHERE trim(body, ?) = '' LIMIT 8", (n.BLANK,))]
            report["본문 길이 (빈 것으로 센 것)"] = [
                r[0] for r in n.conn.execute(
                    "SELECT length(body) FROM notes WHERE trim(body, ?) = '' LIMIT 8",
                    (n.BLANK,))]
            n.conn.close()
        except Exception as err:
            report["색인 읽기 실패"] = f"{type(err).__name__}: {err}"
        # 왜 안 되는지까지 적는다. "안 됨"만 알면 고칠 수가 없다.
        try:
            import onnxruntime

            report["런타임 판"] = onnxruntime.__version__
        except BaseException as err:
            report["런타임 오류"] = f"{type(err).__name__}: {err}"
        try:
            report["임베더 됨"] = onnx_embedder(m) is not None
        except BaseException as err:
            report["임베더 오류"] = f"{type(err).__name__}: {err}"
        out = paths.data_dir() / "vc-진단.json"
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        말하기(json.dumps(report, ensure_ascii=False, indent=2))
        raise SystemExit(0)

    # 여기부터는 오래 도는 길이다. 그물을 걷는다 — 화면이 뜬 뒤의 예외는 죽는 것이
    # 아니라 남기고 사는 것이 옳고, 그 몫은 `report.catch_slot_deaths()` 가 맡는다.
    sys.excepthook = sys.__excepthook__

    if "--check" in sys.argv:
        _self_check()
    else:
        try:
            raise SystemExit(main())
        except SystemExit:
            raise
        except BaseException as err:
            _log_crash(err)
            report.log_crash(err)
            raise
