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

import os
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
        if '지은이: "문지기"' in 머리 or '지은이: "그대로"' in 머리:
            continue
        남.append(f.stem)
    return 남


def main() -> None:
    argv = sys.argv[1:] if argv is None else argv
    want_ui = "--no-ui" not in argv
    want_server = "--no-server" not in argv

    cfg = srv.load_config()
    if want_server and not server_alive():
        start_server(cfg)
        print(f"VC 서버 {HOST}:{PORT} (프로토콜 {srv.PROTOCOL_VERSION})")
        print(f"페어링 토큰: {cfg['pair_token']}")
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
    win.show()
    report.trail("창 떴다")
    code = app.exec_()
    report.trail(f"끔 ({code})")
    report.stop_watching()
    return code


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
    try:
        print(said)
        sys.stdout.flush()
    except (AttributeError, OSError, ValueError):
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
            물음, _, 정답 = (조각.strip() for 조각 in 한줄.partition("|"))
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
            등수 = 찾음.index(정답) + 1 if 정답 in 찾음 else 0   # 0 = 목록 밖
            등수들.append(등수)
            줄.append(f"{물음} | {정답} | {등수 or '밖'} | {찾음[0] if 찾음 else '(없음)'}")
        센것 = len(등수들)
        일등 = sum(1 for r in 등수들 if r == 1)
        셋안 = sum(1 for r in 등수들 if 1 <= r <= 3)
        밖 = sum(1 for r in 등수들 if r == 0)
        뺌 = f" · 「{뺄것}」에서 온 {뺀수}개는 빼고 쟀다" if 뺄것 else ""
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
        조각들, s = ingest.들일것(뿌리)
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
                raise RuntimeError(
                    f"글 모델이 없다. {paths.gguf_dir()} 에 .gguf 를 넣어라 "
                    "(내려받는 자리는 지시서에)")
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
            말하기(chr(10).join(줄[-2:]))
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
                줄 += ["", f"막힌 것 {len(막힌)}개 미리보기 (버린 것 {gs.버린것}개 중):",
                       "-" * 72]
                for c in 막힌:
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
