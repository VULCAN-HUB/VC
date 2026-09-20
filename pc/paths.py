"""무엇이 어디 있는지 한 곳에서 정한다.

소스로 돌릴 때와 설치본으로 돌릴 때 자리가 다르다. 그걸 부르는 쪽마다 따로 따지면
**한 군데를 놓쳤을 때 조용히 꺼진다** — 실제로 설치본에서 모델을 못 찾아 뜻 검색이
꺼진 채로 돌았고, 아무 표시도 안 났다.

두 가지가 갈린다:

**모델**은 프로그램에 딸린 것이다. 설치본에서는 exe 옆(`_internal/models`), 소스에서는
저장소 옆(`../models`).

**기록**은 사람 것이다. 설치 폴더 안에 두면 안 된다 — Program Files는 못 쓰고, 다시
깔면 20년치가 같이 지워진다. `문서\\VC` 에 둔다. 눈에 보이고, 백업에 딸려 가고,
**옵시디언으로 그 폴더를 그대로 열 수 있다**(이 프로그램이 옵시디언 대용이므로 중요하다).
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

APP_NAME = "VC"

# ★ **판 번호는 여기 한 자리에만 적는다.** 그동안 exe 속성에는 `0.1.0.0` 이
# 박혀 있었고 진짜 판(v0.1.54)은 공유 폴더 파일 이름과 내 머릿속에만 있었다.
# 되돌릴 판을 고르려면 **쓰는 사람이 exe 만 보고 알 수 있어야 한다.**
# 굽는 스크립트가 이 값을 읽어 `version.txt` 를 만들고, 진단에도 같이 적는다.
VERSION = "0.5.19"


def _qt_runtime_first() -> bool:
    """PyQt5 가 제 낡은 C++ 런타임을 이미 올려놨는가.

    한 프로세스에 같은 이름의 DLL 은 하나만 올라간다. **Qt 것이 먼저 올라가면
    onnxruntime 은 그것을 물고 죽는다** — 되돌릴 방법이 없다.

    올라온 것을 직접 묻는 대신, **Qt 가 이미 불러와졌는지**로 판단한다. 훨씬 간단하고
    확실하다: `sys.modules` 에 PyQt5 가 있고 그 폴더에 낡은 런타임이 들어 있으면 그렇다.
    """
    mod = sys.modules.get("PyQt5")
    if mod is None or not getattr(mod, "__file__", None):
        return False
    return (Path(mod.__file__).parent / "Qt5" / "bin" / "msvcp140.dll").exists()


def pin_runtime() -> bool:
    """시스템 C++ 런타임을 미리 붙든다. **이 파일을 불러올 때 저절로 돈다.** 5ms다.

    PyQt5 는 불러올 때 제 `Qt5\bin` 을 DLL 찾는 자리 **앞에** 끼워 넣는다. 거기 든
    msvcp140/vcruntime140 은 2019년 판이라, 뒤에 올라오는 onnxruntime 이 그걸 물면
    불러오다 죽는다 — 오류가 아니라 **프로세스가 통째로 죽는 일도 있었다**.

    윈도우는 같은 이름의 DLL 을 한 프로세스에 두 번 안 올린다. 그래서 시스템 것을
    먼저 붙들어 두면 나중에 누가 무엇을 찾든 이미 올라온 새것을 쓴다.

    **Qt 가 먼저 올라온 뒤에는 되돌릴 수 없다** — 절대 경로로 불러도 이미 올라온
    사본이 돌아온다. 그때는 False 를 돌려준다. 부르는 쪽은 그러면 onnxruntime 을
    **아예 안 올린다** — 뜻 검색이 꺼지는 것이 프로그램이 죽는 것보다 낫다.
    """
    global _PINNED
    if _PINNED:
        return True     # 이미 제때 붙들었다. Qt 가 나중에 올라와도 상관없다
    if os.name != "nt":
        _PINNED = True
        return True     # 윈도우 밖에서는 이 얽힘이 없다

    # **늦었으면 아무것도 안 건드린다.** Qt 것이 이미 올라온 뒤에 시스템 것을 또
    # 올리면 한 프로세스에 C++ 런타임이 두 벌이 되어 그것만으로 죽는다.
    if _qt_runtime_first():
        return False

    import ctypes

    root = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")
    for name in ("vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll", "concrt140.dll"):
        try:
            ctypes.WinDLL(os.path.join(root, name))
        except OSError:
            pass        # 윈도우 판에 따라 없는 것도 있다
    _PINNED = True
    return True


# 이 파일을 불러오는 순간 한 번 붙든다. 성공하면 기억해 둔다 — 뒤에 Qt 가 올라와도
# 이미 새 런타임이 프로세스에 있으므로 괜찮다.
_PINNED = False
_PINNED = pin_runtime()


def qt_plugins_dir() -> Path | None:
    """PyQt5 가 들고 온 플러그인 폴더(`PyQt5/Qt5/plugins`). 없으면 None.

    **PyQt5 를 여기서 불러오지 않는다.** `pin_runtime()` 이 「Qt 가 먼저 올라왔는가」로
    판단하므로, 이 파일을 불러오는 것만으로 Qt 가 올라오면 윈도우의 런타임 붙들기가
    통째로 망가진다. 이미 올라와 있을 때만 그 자리를 알려 준다.
    """
    mod = sys.modules.get("PyQt5")
    if mod is None or not getattr(mod, "__file__", None):
        return None
    곳 = Path(mod.__file__).parent / "Qt5" / "plugins"
    return 곳 if 곳.is_dir() else None


_QT_PINNED = False


def pin_qt_plugins() -> bool:
    """Qt 플러그인 자리를 **파이썬 글자 그대로** 박는다. 창을 만들기 전에 부른다.

    ★★ **경로에 한글이 있으면 Qt 가 제 플러그인 자리를 스스로 못 찾는다.**
    맥에서 `~/프로젝트/VC` 로 풀고 돌리자 창 띄우는 모듈 일곱이 통째로 죽었다:

        PluginsPath: /Users/…/????/VC/pc/…/PyQt5/Qt5/plugins
        qt.qpa.plugin: Could not find the Qt platform plugin "cocoa" in ""

    Qt 가 제 설치 자리를 **8비트 글자로 되돌리면서** 한글을 `?` 로 버린다. 그런 폴더는
    없으니 `cocoa` 도 `offscreen` 도 못 찾고, 자체점검까지 다 터진다. `LANG` 을 UTF-8 로
    줘도 안 고쳐진다 — 되돌리는 자리가 로캘보다 앞이다.

    `addLibraryPath()` 에는 **파이썬 글자를 그대로** 넘길 수 있어 8비트를 거치지 않는다.
    그래서 한글 자리가 살아서 들어간다. 환경 변수(`QT_QPA_PLATFORM_PLUGIN_PATH`)로는
    같은 병을 다시 밟는다 — 그쪽도 8비트로 읽힌다.

    여러 번 불러도 된다. 참을 주면 자리를 박았거나 이미 박혀 있다는 뜻이다.
    """
    global _QT_PINNED
    if _QT_PINNED:
        return True
    # ★ **PyQt5 를 여기서 직접 올린다.** 「이미 올라와 있으면」으로 두었더니, 부르는
    #   자리가 `import PyQt5` 보다 한 줄 앞이면 **아무 말 없이 아무것도 안 했다** —
    #   그리고 창은 그대로 안 떴다. 부르는 쪽은 어차피 곧 Qt 를 쓴다.
    #   (`pin_runtime()` 은 이 파일을 불러오는 순간 이미 끝났으므로 늦지 않는다.)
    import PyQt5        # noqa: F401
    from PyQt5.QtCore import QCoreApplication

    곳 = qt_plugins_dir()
    if 곳 is None:
        return False        # 구운 판은 PyInstaller 가 제 길로 넣는다

    자리 = str(곳)
    if 자리 not in QCoreApplication.libraryPaths():
        QCoreApplication.addLibraryPath(자리)
    _QT_PINNED = 자리 in QCoreApplication.libraryPaths()
    return _QT_PINNED


def frozen() -> bool:
    """설치본으로 도는 중인가."""
    return getattr(sys, "frozen", False)


def app_dir() -> Path:
    """딸려 온 것들이 있는 자리."""
    if frozen():
        # PyInstaller 는 함께 넣은 자료를 여기에 푼다(폴더 통째면 `_internal`).
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent


def models_dir() -> Path:
    """모델이 있는 자리. 없어도 된다 — 부르는 쪽이 알아서 꺼진다."""
    if env := os.environ.get("VC_MODELS"):
        return Path(env)
    return app_dir() / "models" if frozen() else app_dir().parent / "models"


def gguf_dir() -> Path:
    """**사람이 손으로 넣는 큰 모델**이 있는 자리.

    딸려 오는 것들(뜻 벡터·목소리)과 갈라 둔 이유가 있다. 1GB짜리 GGUF 는 판마다
    다시 받게 할 수 없어 zip 에 안 담고 사람이 넣는데, 그 자리가 `models_dir()`
    이면 두 가지가 어긋난다:

    - 설치본에서 거기는 `_internal/models` — **프로그램 속**이라 넣으라고 할 데가
      아니고, 다음 판을 덮어씌우면 지워진다.
    - 그렇다고 `models_dir()` 을 exe 옆으로 옮기면 **딸려 온 뜻 벡터 모델이
      안 보이게 된다.** 실제로 한 번 그렇게 고쳤다가 되돌렸다.

    그래서 여기는 **exe 옆 `models`**(`fetched_dir()`) 를 쓴다. 딸려 온 뜻·목소리 모델은
    `models_config.installed` · `meaning_dir` 가 두 자리를 다 보므로 안 사라진다.
    같은 판에서 전에 프로그램 속에 받아 둔 gguf 만 있으면 그리로 내려간다.
    """
    곁 = fetched_dir()
    if frozen() and not (곁.is_dir() and any(곁.glob("*.gguf"))) and any(models_dir().glob("*.gguf")):
        return models_dir()
    return 곁


def fetched_dir() -> Path:
    """**내려받은 모델**이 들어가는 자리 — 새 판을 덮어 풀어도 남아야 한다.

    ★★ 전엔 받은 것이 `_internal/models`(프로그램 속)에 들어가 **판을 올리면 지워졌다** —
    v0.5.18 을 실무 폴더에 풀자 받아 둔 e5-base(296MB)가 사라지고 뜻 벡터가 작은 모델 폭으로
    통째로 다시 만들어졌다(찾음 12 → 4/20). 설치본은 exe 옆 `models`, 소스로 돌 때는 `models_dir()`.
    """
    if env := os.environ.get("VC_MODELS"):
        return Path(env)
    if not frozen():
        return models_dir()
    if sys.platform == "darwin":
        # ★ 맥에서 「exe 옆」은 `VC.app/Contents/MacOS` — **앱 속**이라 앱을 바꾸면 같이 지워진다.
        return Path.home() / "Library" / "Application Support" / APP_NAME / "models"
    return Path(sys.executable).parent / "models"


# 뜻 검색에 쓸 모델을 고르는 차례. **받은 것이 딸린 것보다 먼저다.**
# 앞엣것부터 보고 `model.onnx`·`tokenizer.json`이 둘 다 있으면 그걸 쓴다.
MEANING_ORDER = ("e5-base", "")


def meaning_dir(고른것: str = "") -> Path:
    """뜻 검색 모델이 있는 자리. **사람이 고른 것이 먼저**, 없으면 받은 큰 것, 그다음 딸려 온 것.

    딸려 온 것을 덮어쓰지 않고 **곁에 둔다** — 받은 것이 시원찮으면 폴더 하나만
    지우면 되돌아간다.

    ★★ `고른것` 은 화면 「뜻 검색」 칸에서 고른 이름이다. 예전에는 그 칸이 아예 없어
    **받아 두고도 되돌릴 길이 없었다**(열린 문제 15). 「딸려 온 것」 을 고르면 뿌리를 쓴다.
    """
    root = models_dir()
    차례 = list(MEANING_ORDER)
    # ★★ **이름을 안 넘기면 설정에 적힌 고른 것을 쓴다.** 전엔 서버만 고른 것을 읽고 창(`Indexer`)·
    #   `--doctor` 는 기본(큰 것)을 썼다. 사람이 「딸려 온 것」을 고르면 **창(768)과 서버(384)가 같은
    #   색인에서 서로의 벡터를 계속 지웠고**(폭이 다르면 통째로 버린다), `--doctor` 의 뜻 왕복도
    #   실무 벡터를 지울 수 있었다. 부르는 쪽마다 맡기지 않고 여기 한 자리에서 읽는다.
    if not 고른것:
        try:
            고른것 = str((load_config().get("models") or {}).get("meaning") or "")
        except Exception:
            고른것 = ""
    if 고른것:
        # 「딸려 온 것 (e5-small)」 처럼 꾸민 이름이면 뿌리를 가리킨다.
        차례.insert(0, "" if 고른것.startswith("딸려 온 것") else 고른것)
    for name in 차례:
        # 받은 것(이름 폴더)은 받은 자리 먼저 — 같은 판에서 전에 프로그램 속에 받은 것도 본다. 딸려 온 것은 뿌리.
        for here in ([fetched_dir() / name, root / name] if name else [root]):
            if (here / "model.onnx").is_file() and (here / "tokenizer.json").is_file():
                return here
    return root


def documents_dir() -> Path:
    """윈도우가 말하는 **진짜** 문서 폴더.

    `~/Documents` 를 글자 그대로 붙이면 안 된다. 한글 윈도우의 문서 폴더는
    `C:/Users/<이름>/문서` 다. 그런데 `~/Documents` 도 만들면 만들어지기 때문에,
    글자로 붙이면 **탐색기 「문서」에는 없는 딴 폴더**가 조용히 생기고 기록이 거기
    쌓인다. 실제로 낯선 PC 에서 그렇게 됐다. 윈도우한테 직접 물어본다.
    """
    if os.name == "nt":
        try:
            import ctypes.wintypes

            buf = ctypes.create_unicode_buffer(260)
            # CSIDL_PERSONAL=5, SHGFP_TYPE_CURRENT=0. 옮겨 놨으면 옮긴 자리를 준다.
            if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0 and buf.value:
                return Path(buf.value)
        except (OSError, AttributeError, ImportError):
            pass          # 못 물어보면 아래 글자 붙이기로 내려간다
    return Path(os.path.expanduser("~")) / "Documents"


_검사자리: Path | None = None
_가둘까 = True          # 검사 안에서 「쪽지가 이기는지」를 잴 때만 잠시 끈다


def 검사중인가() -> bool:
    """이 프로세스가 **자체점검**으로 돌고 있나.

    ★★ 자체점검이 **진짜 자리를 건드리면 안 된다.** 실제로 그랬다(2026-09-21):
       `server` 검사가 진짜 `eb_config.json` 을 읽고 쓰는데, 그 사이 떠 있던 VC 가
       반쯤 쓰인 파일을 읽고 **「설정이 깨졌다」며 새로 만들었다**(자국에 남았다:
       「폰은 다시 짝지어야 한다」). `eb.db` 도 같은 식으로 「깨져서 옆에 치웠다」.
       검사 한 번에 **쓰던 사람의 VC 가 망가진다** — 그것도 조용히.

    ★ 전에는 안 났다. 소스로 돌 때 자리가 `Path.cwd()` 라 검사가 소스 폴더에 떨어졌기
      때문이다. `기록자리.txt` 로 창고를 못 박으면서 **검사도 진짜 자리를 쓰게 됐다.**

    `paths` 는 모든 모듈이 들여오므로 **여기 한 자리**에서 가둔다.
    """
    return _가둘까 and "--check" in sys.argv[1:]


def _가둔자리() -> Path:
    """검사가 쓸 임시 자리. 프로세스마다 하나, 끝나면 지운다."""
    global _검사자리
    if _검사자리 is None:
        import atexit
        import shutil
        import tempfile

        _검사자리 = Path(tempfile.mkdtemp(prefix="vc-검사-"))
        atexit.register(lambda: shutil.rmtree(_검사자리, ignore_errors=True))
    return _검사자리


def data_dir() -> Path:
    """기록·색인·설정이 사는 자리. 없으면 만든다.

    소스로 돌릴 때는 **지금 자리 그대로** 둔다. 개발하다 갑자기 문서 폴더에
    기록이 생기면 놀란다.
    """
    if env := os.environ.get("VC_DATA"):
        here = Path(env)
    elif 검사중인가():
        here = _가둔자리() / "기록"      # 검사는 진짜 창고를 안 건드린다
    elif (적힌 := _적어둔자리()) is not None:
        here = 적힌
    elif frozen():
        here = documents_dir() / APP_NAME
        # 예전 판이 만들어 둔 자리에 기록이 있으면 **그걸 계속 쓴다.**
        # 자리를 옮기면 쓰던 사람 눈에는 기록이 통째로 사라진 것이 된다.
        old = Path(os.path.expanduser("~")) / "Documents" / APP_NAME
        if old != here and (old / "data" / "notes").is_dir():
            here = old
    else:
        here = Path.cwd()
    here.mkdir(parents=True, exist_ok=True)
    return here


def _앱자리기본() -> Path:
    """구운 판이 **기계 파일**을 두는 운영체제 자리. 맥 Application Support · 윈도우 LOCALAPPDATA."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA")
        return (Path(base) if base else Path.home() / "AppData" / "Local") / APP_NAME
    base = os.environ.get("XDG_STATE_HOME")
    return (Path(base) if base else Path.home() / ".local" / "state") / APP_NAME


def state_dir() -> Path:
    """**기계 파일**(db · 설정 열쇠 · 로그 · 보고서 · 결과물 · 테마)이 사는 자리. 없으면 만든다.

    ★★ 기록 자리는 **사람이 여는 폴더**다(옵시디언·파일 앱) — 오너 결정(2026-09-15): 메모만 둔다.
    전에는 db·열쇠·로그 20여 가지가 글과 섞였고, 맥 문서 폴더는 iCloud 로 동기화돼
    **열쇠와 db 가 올라가고** 「저장 공간 최적화」가 db 를 내리면 색인이 깨질 수 있었다.

    차례: `VC_STATE` → `VC_DATA` 를 줬으면 **기록 자리를 따른다**(시험이 진짜 자리를 못 건드리게) →
    구운 판이거나 `기록자리.txt` 를 쓰면 운영체제 앱 자리 → 소스로 돌면 기록 자리(개발 흐름 그대로).
    """
    if env := os.environ.get("VC_STATE"):
        here = Path(env)
    elif 검사중인가() and not os.environ.get("VC_DATA"):
        here = _가둔자리() / "기계"      # 설정·db·열쇠도 진짜 것을 안 건드린다
    elif os.environ.get("VC_DATA"):
        here = data_dir()
    elif frozen() or _적어둔자리() is not None:
        here = _앱자리기본()
    else:
        here = data_dir()
    here.mkdir(parents=True, exist_ok=True)
    return here


def 기계자리(이름: str) -> Path:
    """기계 파일 하나의 자리. **앱 자리에 없고 옛 기록 자리에만 있으면 옛 자리를 준다.**

    옮기기가 확인에 실패해 원본을 남겼을 때도 VC 가 그대로 돌게 하는 되돌림이다 —
    아무것도 안 사라지고, 다음에 켤 때 다시 옮겨 본다.
    """
    새 = state_dir() / 이름
    옛 = data_dir() / 이름
    if 새 != 옛 and not 새.exists() and 옛.exists():
        return 옛
    return 새


# 옛 기록 자리에서 앱 자리로 옮길 기계 파일. **글(`data/notes`) · 첨부 · 휴지통은 여기 없다** — 사람 것이다.
기계파일들 = (
    "notes_index.db", "eb.db", "eb_config.json", "theme.json", "mic.json",
    "vc-기록.log", "vc-죽음.log", "vc-오류.txt", "vc-메모리.json", "vc-화면상태.json", "vc-자전.json",
    "vc-진단.json", "vc-스스로짐작.txt", "vc-색인다시.txt", "vc-판올리기.txt", "vc-휴지통.txt",
    "vc-사본치움.txt", "vc-찾기점수.txt", "vc-흡수.txt", "vc-이음선.txt", "vc-재보기.txt",
    "vc-예외시험.txt", "찾기물음.txt",
    "data/talk.jsonl", "data/recordings", "data/artifacts",
)


def _옮긴것확인(옛: Path, 새: Path, 옛크기: tuple[int, int]) -> bool:
    """사본이 원본만큼 멀쩡한가. db 는 열어서 검사, json 은 읽어 보고, 나머지는 크기를 댄다."""
    import json as _j

    if 새.is_dir():
        파일 = [f for f in 새.rglob("*") if f.is_file()]
        return (len(파일), sum(f.stat().st_size for f in 파일)) == 옛크기
    if 새.stat().st_size != 옛크기[1]:
        return False
    if 새.suffix == ".db":
        con = _sq.connect(f"file:{새}?mode=ro", uri=True)
        try:
            return con.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        finally:
            con.close()
    if 새.suffix == ".json":
        _j.loads(새.read_text(encoding="utf-8"))
    return True


def 기계파일옮기기() -> dict:
    """옛 기록 자리의 기계 파일을 앱 자리로 **복사 → 확인 → 원본 지움**(오너 결정 2026-09-15). 켤 때 한 번.

    ★ **혼자 켜기 잠금을 잡은 뒤, db 를 열기 전에** 부른다 — 열린 db 를 옮기면 반쪽이 된다.
    확인에 실패하면 반쪽 사본을 치우고 **원본은 그대로 둔다** — `기계자리()` 가 옛 자리를 계속 준다.
    앱 자리에 이미 있는 것은 건드리지 않는다(두 번 불러도 같다).
    """
    import shutil

    새곳, 옛곳 = state_dir(), data_dir()
    결과: dict = {"옮김": [], "남김": [], "이미": []}
    if 새곳.resolve() == 옛곳.resolve():
        return 결과
    for 이름 in 기계파일들:
        옛, 새 = 옛곳 / 이름, 새곳 / 이름
        if not 옛.exists():
            continue
        if 새.exists():
            결과["이미"].append(이름)
            continue
        딸림 = [옛.with_name(옛.name + 끝) for 끝 in ("-wal", "-shm")] if 이름.endswith(".db") else []
        딸림 = [f for f in 딸림 if f.exists()]
        try:
            새.parent.mkdir(parents=True, exist_ok=True)
            if 옛.is_dir():
                파일 = [f for f in 옛.rglob("*") if f.is_file()]
                옛크기 = (len(파일), sum(f.stat().st_size for f in 파일))
                shutil.copytree(옛, 새)
            else:
                옛크기 = (1, 옛.stat().st_size)
                for f in 딸림:
                    shutil.copy2(f, 새.with_name(f.name))
                shutil.copy2(옛, 새)
            if not _옮긴것확인(옛, 새, 옛크기):
                raise ValueError("사본이 원본과 다르다")
        except (OSError, ValueError, _sq.Error) as e:
            if 새.is_dir():
                shutil.rmtree(새, ignore_errors=True)
            else:
                for f in [새, *[새.with_name(d.name) for d in 딸림]]:
                    f.unlink(missing_ok=True)
            결과["남김"].append(f"{이름}: {type(e).__name__}")
            continue
        if 옛.is_dir():
            shutil.rmtree(옛, ignore_errors=True)
        else:
            for f in [옛, *딸림]:
                f.unlink(missing_ok=True)
        결과["옮김"].append(이름)
    return 결과


SPOT = "기록자리.txt"


def _적어둔자리() -> Path | None:
    """딸린 것 옆의 `기록자리.txt` 에 적힌 자리. 없으면 `None`.

    **기록이 어디 살지는 사람마다 다르다.** 이 PC 는 작업물을 D 하드에만 두는데
    설치본 기본값은 문서 폴더(C)다. 환경 변수는 바탕화면 아이콘으로 켜면 안 붙고,
    코드에 `D:` 를 박으면 딴 PC 와 맥에서 깨진다. 그래서 **파일 한 장으로 가리킨다.**

    설정에 못 넣는 이유: 설정 자체가 이 자리 안에 산다 — 먼저 자리를 알아야 한다.

    ★★ **사람은 `VC.exe` 옆에 놓는다.** 설치본은 PyInstaller 폴더 꼴이라
    `app_dir()` 이 `_internal` 을 가리키는데, **그 안에 설정 파일을 넣는 사람은 없다.**
    실제로 시험하는 쪽이 exe 옆에 놓았다가 **조용히 기본 자리로 돌아가** 막혔다.
    그래서 **exe 옆을 먼저 보고**, 없으면 딸린 것 옆을 본다.
    """
    global _쪽지문제
    _쪽지문제 = ""
    찾을자리 = []
    if frozen():
        찾을자리.append(Path(sys.executable).parent / SPOT)   # 사람이 놓는 자리
    찾을자리.append(app_dir() / SPOT)                        # 딸린 것 옆(_internal)
    try:
        적힌 = ""
        for 쪽지 in 찾을자리:
            if 쪽지.is_file():
                적힌 = 쪽지.read_text(encoding="utf-8-sig").strip()
                break
    except OSError:
        return None
    # 첫 줄만 본다. 아래에 왜 그리 했는지 적어 둘 수 있게.
    적힌 = 적힌.splitlines()[0].strip() if 적힌 else ""
    if not 적힌 or 적힌.startswith("#"):
        return None
    자리 = Path(적힌).expanduser()
    # ★ **못 쓰는 자리면 조용히 따르지 않는다.** 외장이 빠졌거나 오타면 그 자리에
    # 새 빈 기록이 생기고, 쓰는 사람 눈에는 **기록이 통째로 사라진 것**이 된다.
    # ★ 만들 수 있는 것과 쓸 수 있는 것은 다르다. 폴더는 멀쩡히 있는데 못 쓰는
    #   자리가 있다 — 끊긴 공유 폴더, 읽기 전용 외장. **이 PC 에서는 그 경우를
    #   못 만들어서 검사로 못 재고 있다**(못 만드는 자리는 mkdir 이 먼저 막는다).
    try:
        자리.mkdir(parents=True, exist_ok=True)
        (자리 / ".써지나").write_text("", encoding="utf-8")
        (자리 / ".써지나").unlink()
    except OSError as 막힘:
        # ★★ **따르지 않았으면 그렇다고 말해야 한다.** 조용히 기본 자리로 떨어지면 빈 기록으로
        #   켜져, 사람 눈엔 기록이 통째로 사라진 것이 된다 — 피하려던 바로 그 일이다.
        _쪽지문제 = (f"기록자리.txt 가 가리키는 {자리} 에 쓸 수 없어 기본 자리로 켰다 "
                    f"({type(막힘).__name__}) — 외장이 빠졌거나 경로가 틀렸다")
        return None
    return 자리


_쪽지문제 = ""


def 적어둔자리문제() -> str:
    """`기록자리.txt` 가 있는데 못 쓰는 자리를 가리켜 따르지 않았으면 그 까닭. 아니면 빈 글."""
    if not os.environ.get("VC_DATA"):
        _적어둔자리()
    return _쪽지문제


_LOCK = None            # 붙들고 있어야 잠금이 유지된다. 놓으면 풀린다


def only_one(data: Path | None = None) -> bool:
    """이 기록 자리를 쓰는 VC 가 나 하나면 `True`.

    **둘이 같은 기록을 만지면 서로 덮어쓴다.** 낯선 PC 실사용에서 작업표시줄에서
    못 찾고 다시 켜다가 두 벌이 경고 없이 떴다 — 사람이 흔히 저지르는 일이다.

    기록 자리마다 따로 잠근다. 시험용 자리와 진짜 자리를 같이 켜는 것은 막지 않는다.
    """
    global _LOCK
    if _LOCK is not None:
        return True
    if data is None and state_dir() != data_dir():
        # 잠금 파일도 기계 파일이라 앱 자리에 둔다. **기록 자리마다 따로 잠그는 뜻**은 이름에 자리 지문을 넣어 지킨다.
        import hashlib
        지문 = hashlib.sha1(str(data_dir().resolve()).encode("utf-8")).hexdigest()[:10]
        where = state_dir() / f"vc-혼자-{지문}.lock"
    else:
        where = (data or data_dir()) / "vc-혼자.lock"
    if os.name != "nt":
        # ★ 맥·리눅스는 **열린 파일도 지워진다** — 아래 윈도우 방식이면 둘째가 앞엣것의 잠금을 지우고 같이 떴다.
        #   flock 은 여는 것마다 따로라 같은 프로세스 안에서도 둘째를 막는다(자체점검과 같은 뜻).
        import fcntl

        try:
            f = where.open("a+", encoding="utf-8")
        except OSError:
            return True        # 못 잠그면 막지는 않는다. 안 켜지는 것이 더 나쁘다
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            f.close()
            return False
        f.truncate(0)
        f.write(str(os.getpid()))
        f.flush()
        _LOCK = f
        return True
    try:
        # 이미 열려 있으면 윈도우가 못 지운다 — 그것으로 남이 쓰는지 안다.
        if where.exists():
            try:
                where.unlink()
            except OSError:
                return False
        _LOCK = where.open("w", encoding="utf-8")
        _LOCK.write(str(os.getpid()))
        _LOCK.flush()
    except OSError:
        _LOCK = None
        return True        # 못 잠그면 막지는 않는다. 안 켜지는 것이 더 나쁘다
    return True


def notes_dir() -> Path:
    return data_dir() / "data" / "notes"


def index_path() -> Path:
    return 기계자리("notes_index.db")


def store_path() -> Path:
    return 기계자리("eb.db")


def 휴지통자리() -> Path:
    """**문지기가 버린 조각이 가는 자리.** 지우지 않고 여기 모은다.

    기록 폴더 **밖**이다 — 색인·찾기·그물 어디에도 안 들어간다.
    「찾으라고 하기 전까지 안 찾는다」가 규칙이다(오너 결정 2026-09-09).
    안 비운다. 되살릴 수 있어야 버리는 일이 무섭지 않다.
    """
    return data_dir() / "휴지통"


def config_path() -> Path:
    return 기계자리("eb_config.json")


def load_config() -> dict:
    """설정을 읽는다. 없거나 깨졌으면 빈 사전 — **설정 한 줄 때문에 프로그램이 죽지 않는다.**"""
    import json as _j

    try:
        값 = _j.loads(config_path().read_text(encoding="utf-8"))
        return 값 if isinstance(값, dict) else {}
    except (OSError, ValueError):
        return {}


def save_config(값: dict) -> bool:
    """설정을 쓴다. 못 써도 터지지 않는다(돌아가는 데 꼭 필요한 것이 아니다)."""
    import json as _j

    try:
        config_path().parent.mkdir(parents=True, exist_ok=True)
        config_path().write_text(_j.dumps(값, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except (OSError, TypeError, ValueError):
        return False


import sqlite3 as _sq
import threading as _th


class _다읽은:
    """커서를 잠금 안에서 다 읽어 둔 것. 잠금 밖에서 한 줄씩 당기면 딴 실과 또 엉킨다."""

    def __init__(self, cur) -> None:
        self._줄 = cur.fetchall() if cur.description else []
        self.rowcount, self.lastrowid = cur.rowcount, cur.lastrowid

    def fetchone(self):
        return self._줄.pop(0) if self._줄 else None

    def fetchall(self):
        줄, self._줄 = self._줄, []
        return 줄

    def __iter__(self):
        return iter(self.fetchall())


class 잠근연결(_sq.Connection):
    """여러 실이 같이 쓰는 sqlite 연결. `sqlite3.connect(..., factory=잠근연결)`.

    ★★ 서버는 `ThreadingHTTPServer` 라 요청마다 실이 따로인데 `Notes`·`Store` 연결은 하나다.
    잠그기 전에는 이름 바꾸기의 다시 훑기와 덧붙이기가 겹쳐 `IntegrityError: not an error` 로 터졌다.
    """
    # ponytail: 결과를 통째로 읽어 둔다 — 큰 SELECT 는 메모리를 더 먹는다. 문제 되면 그 자리만 fetchmany

    def __init__(self, *a, **k) -> None:
        super().__init__(*a, **k)
        self._잠금 = _th.RLock()

    def execute(self, *a):
        with self._잠금:
            return _다읽은(super().execute(*a))

    def executemany(self, *a):
        with self._잠금:
            return _다읽은(super().executemany(*a))

    def executescript(self, *a):
        with self._잠금:
            return super().executescript(*a)

    def commit(self) -> None:
        with self._잠금:
            super().commit()


def _self_check() -> None:
    global _가둘까      # 「쪽지가 이기는지」를 재는 구간에서만 가둠을 잠시 푼다
    import tempfile

    # 잠근연결: 딴 실이 잠금을 쥐면 execute 가 기다린다. 겹쳐 터지는 것은 우연이라 재현 대신 기다림을 본다.
    import time as _t

    _c = _sq.connect(":memory:", check_same_thread=False, factory=잠근연결)
    _c.execute("CREATE TABLE t (x)")
    for _i in range(3):
        _c.execute("INSERT INTO t VALUES (?)", (_i,))
    _c.commit()
    _끝: list = []
    with _c._잠금:
        _실 = _th.Thread(target=lambda: _끝.append(_c.execute("SELECT count(*) FROM t").fetchone()[0]))
        _실.start()
        _t.sleep(0.3)
        assert not _끝, "잠근연결이 안 잠근다 — 서버 실들이 한 연결을 겹쳐 쓴다"
    _실.join()
    assert _끝 == [3], _끝
    assert _c.execute("UPDATE t SET x = 0").rowcount == 3
    assert [r[0] for r in _c.execute("SELECT x FROM t")] == [0, 0, 0]
    _c.close()

    assert app_dir().exists()
    # 소스로 돌 때는 지금 자리다 — 개발 중에 문서 폴더가 더럽혀지면 안 된다.
    # ★ 단 `기록자리.txt` 가 있으면 **그것이 이긴다**(2026-09-20). 켜는 폴더마다 창고가
    #   갈리는 것을 막으려고 쪽지로 못 박았다 — 아래 「어디서 켜도 같은 창고」 검사 참조.
    assert not frozen()
    if _적어둔자리() is None and not 검사중인가():
        assert data_dir() == Path.cwd(), data_dir()
    assert models_dir() == app_dir().parent / "models", models_dir()
    # 뜻 검색 모델은 **받은 것이 먼저**다. 둘 다 없으면 모델 자리 그대로 돌려준다.
    assert meaning_dir() in (models_dir(), models_dir() / "e5-base"), meaning_dir()

    # ★ **큰 모델 자리를 딸려 온 것 자리와 갈라 둔다.** 한 번 `models_dir()` 을
    # 통째로 exe 옆으로 옮겼다가 **딸려 온 뜻 벡터 모델이 안 보이게** 됐다.
    # 소스로 돌 때는 둘이 같은 자리다 — 갈라지는 것은 구운 뒤뿐이다.
    assert gguf_dir() == models_dir(), gguf_dir()

    # 언 것처럼 꾸며 갈라지는지 본다. exe 옆에 `.gguf` 가 있으면 그쪽,
    # 없으면 딸려 온 자리. **없는데 exe 옆을 고르면 딸려 온 것이 통째로 사라진다.**
    with tempfile.TemporaryDirectory() as tmp:
        곁 = Path(tmp) / "models"
        곁.mkdir()
        # 구운 것과 같은 모양으로 꾸민다 — 딸려 온 것은 `_internal` 에 풀린다.
        (Path(tmp) / "_internal" / "models").mkdir(parents=True)
        옛프로즌, 옛실행, 첫판 = globals()["frozen"], sys.executable, sys.platform
        globals()["frozen"] = lambda: True
        sys.executable = str(Path(tmp) / "VC.exe")
        sys._MEIPASS = str(Path(tmp) / "_internal")
        # ★ **「exe 옆」을 재는 동안은 윈도우인 척한다.** 맥에서 돌리면 `fetched_dir()`
        #   이 맥 분기(`Application Support`)로 빠져 이 아래가 통째로 터진다 —
        #   검사가 윈도우에서만 맞는 모양이었다. 맥 분기는 바로 밑에서 따로 잰다.
        sys.platform = "win32"
        try:
            속 = Path(tmp) / "_internal" / "models"
            assert fetched_dir() == 곁, fetched_dir()
            assert gguf_dir() == 곁, "받을 자리가 프로그램 속이다 — 판을 올리면 지워진다"
            (속 / "옛.gguf").write_bytes(b"x")
            assert gguf_dir() == 속, "같은 판에서 프로그램 속에 받아 둔 gguf 를 못 찾는다"
            (곁 / "아무.gguf").write_bytes(b"x")
            assert gguf_dir() == 곁, gguf_dir()
            # 뜻 모델: 받은 큰 것은 exe 옆에서, 딸려 온 작은 것은 프로그램 속 뿌리에서 찾는다
            for 곳 in (속, 곁 / "e5-base"):
                곳.mkdir(exist_ok=True)
                (곳 / "model.onnx").write_bytes(b"x")
                (곳 / "tokenizer.json").write_bytes(b"x")
            assert meaning_dir("e5-base") == 곁 / "e5-base", f"exe 옆에 받은 큰 모델을 못 찾는다: {meaning_dir('e5-base')}"
            assert meaning_dir("딸려 온 것 (e5-small)") == 속, "딸려 온 것을 못 찾는다"
            sys.platform = "darwin"
            assert "Application Support" in str(fetched_dir()) and "VC.exe" not in str(fetched_dir()), \
                f"맥은 받은 모델이 앱 속(VC.app/Contents/MacOS)에 들어간다: {fetched_dir()}"
        finally:
            globals()["frozen"], sys.executable = 옛프로즌, 옛실행
            sys.platform = 첫판
            del sys._MEIPASS

    # **문서 폴더는 윈도우한테 물어야 한다.** 한글 윈도우면 `문서`, 옮겨 놨으면 옮긴 자리.
    # `~/Documents` 를 글자로 붙이면 탐색기에 없는 딴 폴더가 조용히 생긴다.
    docs = documents_dir()
    assert docs.is_absolute(), docs
    if os.name == "nt":
        import ctypes

        buf = ctypes.create_unicode_buffer(260)
        ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf)
        assert str(docs) == buf.value, (docs, buf.value)

    # **같은 기록 자리를 둘이 만지면 안 된다.** 서로 덮어쓴다.
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["VC_DATA"] = tmp
        try:
            global _LOCK
            keep, _LOCK = _LOCK, None
            assert only_one(), "처음 켠 것이 막혔다"
            mine, _LOCK = _LOCK, None
            assert not only_one(), "둘째가 안 막혔다"
            mine.close()
            assert only_one(), "앞엣것이 닫혔는데도 막힌다"
            _LOCK.close()
            _LOCK = keep
        finally:
            del os.environ["VC_DATA"]

    # 환경 변수로 어디든 옮길 수 있어야 한다. 검사도 이 길로 딴 데를 쓴다.
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["VC_DATA"] = tmp
        os.environ["VC_MODELS"] = tmp
        try:
            assert data_dir() == Path(tmp)
            assert models_dir() == Path(tmp)
            assert meaning_dir() == Path(tmp), "아무것도 없으면 모델 자리 그대로"
            big = Path(tmp) / "e5-base"
            big.mkdir()
            (big / "model.onnx").write_bytes(b"x")
            assert meaning_dir() == Path(tmp), "낱말표가 없으면 아직 못 쓴다"
            (big / "tokenizer.json").write_bytes(b"x")
            assert meaning_dir() == big, "받은 것이 있으면 그게 먼저다"
            # ★★ **사람이 고른 것이 먼저다.** 예전에는 고르는 칸이 아예 없어
            #   받아 두고도 되돌릴 길이 없었다(열린 문제 15).
            #   딸려 온 것도 있어야 「그쪽으로 되돌리기」를 잴 수 있다.
            (Path(tmp) / "model.onnx").write_bytes(b"x")
            (Path(tmp) / "tokenizer.json").write_bytes(b"x")
            # ★★ **이름을 안 넘겨도 설정에 적힌 고른 것을 따른다** — 창·서버·진단이 같은 모델을 써야
            #   서로의 벡터를 안 지운다.
            (Path(tmp) / "eb_config.json").write_text(
                '{"models": {"meaning": "딸려 온 것 (e5-small)"}}', encoding="utf-8")
            assert meaning_dir() == Path(tmp), f"설정에서 고른 모델을 안 따른다: {meaning_dir()}"
            (Path(tmp) / "eb_config.json").unlink()
            assert meaning_dir() == big, "고른 것이 없으면 받은 큰 것이 먼저다"
            assert meaning_dir() == big, "받은 것이 있으면 여전히 그게 먼저다"
            assert meaning_dir("딸려 온 것 (e5-small)") == Path(tmp),                 "「딸려 온 것」 을 골랐는데 큰 것을 쓴다"
            assert meaning_dir("e5-base") == big, "고른 것을 안 쓴다"
            assert meaning_dir("없는것") == big, "없는 것을 고르면 있는 것으로 내려가야 한다"
            assert notes_dir() == Path(tmp) / "data" / "notes"
            assert index_path() == Path(tmp) / "notes_index.db"
            assert config_path().name == "eb_config.json"
        finally:
            del os.environ["VC_DATA"], os.environ["VC_MODELS"]

    # 검사 중에는 **가둔 자리**로 돌아온다(진짜 창고를 안 건드린다)
    assert data_dir() == (_가둔자리() / "기록" if 검사중인가()
                          else (_적어둔자리() or Path.cwd())), "환경 변수를 지웠는데 안 돌아왔다"
    # C++ 런타임 붙들기. **순서가 전부다** — Qt 가 먼저 올라오면 되돌릴 수 없고,
    # 그때 onnxruntime 을 올리면 프로세스가 통째로 죽는다.
    if os.name == "nt":
        assert "PyQt5" not in sys.modules or pin_runtime() is False
        # 이 검사는 Qt 없이 도는 자리라 붙들기가 되어야 한다.
        assert pin_runtime() is True, "제 순서인데 못 붙들었다"
        assert _qt_runtime_first() is False

    # 쪽지로 기록 자리 옮기기. **못 쓰는 자리는 안 따라간다** — 따라가면
    # 빈 기록이 새로 생겨서 쓰는 사람 눈엔 기록이 사라진 것이 된다.
    import tempfile

    with tempfile.TemporaryDirectory() as 잠깐:
        잠깐 = Path(잠깐)
        쪽지 = app_dir() / SPOT
        원래 = 쪽지.read_text(encoding="utf-8") if 쪽지.is_file() else None
        환경 = os.environ.pop("VC_DATA", None)
        _가둘까 = False      # 이 구간은 **쪽지가 이기는지**를 재는 자리다
        적기 = lambda 글: 쪽지.write_text(글, encoding="utf-8")
        try:
            # 첫 줄이 자리, 그 아래는 사람이 왜 그리 했는지 적는 자리다
            적기(str(잠깐 / "기록") + chr(10) + "# 여기 둔 까닭을 적어 둔다" + chr(10))
            assert data_dir() == 잠깐 / "기록", data_dir()
            assert 적어둔자리문제() == "", "잘 따른 쪽지인데 문제가 있다고 한다"
            # 못 쓰는 자리를 가리키면 무시하고 원래 자리로 돌아간다.
            # ★ 파일 **밑**을 가리킨다. 처음엔 없는 드라이브(Z:)를 썼는데
            # 이 PC 에 Z: 가 실제로 있어서 **시험이 구별을 못 했다.**
            막힌길 = 잠깐 / "이건파일이다"
            막힌길.write_text("", encoding="utf-8")
            못쓸 = str(막힌길 / "VC")
            적기(못쓸)
            assert data_dir() != Path(못쓸), "못 쓰는 자리를 따라갔다"
            # ★★ 따르지 않았으면 **그렇다고 말해야 한다** — 조용히 빈 기록으로 켜지면 기록이 사라진 것 같다.
            assert 못쓸 in 적어둔자리문제(), f"못 쓰는 자리를 안 따른 까닭을 안 말한다: {적어둔자리문제()!r}"
            # 주석만 있거나 비면 안 적은 것으로 친다.
            # ★ 안 거르면 **`# 아직 안 정했다` 라는 이름의 폴더가 생긴다** —
            #   처음엔 `Path("#")` 과 비교해서 이걸 못 잡았다.
            군소리 = "# 아직 안 정했다"
            적기(군소리 + chr(10))
            assert data_dir() != Path(군소리).absolute(), data_dir()
            assert not (Path.cwd() / 군소리).exists(), "군소리 이름으로 폴더가 생겼다"
            적기("")
            assert data_dir() == Path.cwd() or frozen(), data_dir()
            # ★★ **설치본에서는 사람이 `VC.exe` 옆에 놓는다.** `app_dir()` 은
            # `_internal` 을 가리켜서 exe 옆에 놓은 쪽지가 **조용히 무시됐다** —
            # 시험하는 쪽이 그대로 겪었다(「기본 자리로 돌아갔다」). exe 옆을 먼저 본다.
            # 여기서만 얼린 척한다. 진짜로 얼릴 수는 없으니 두 값을 바꿔 끼운다.
            적기("")                                   # 딸린 것 옆 쪽지는 비워 둔다
            가짜exe = 잠깐 / "설치본" / "VC.exe"
            가짜exe.parent.mkdir(parents=True, exist_ok=True)
            가짜exe.write_text("", encoding="utf-8")
            # BOM 이 붙어 저장돼도 읽혀야 한다 — 메모장이 기본으로 붙인다
            (가짜exe.parent / SPOT).write_text(
                "﻿" + str(잠깐 / "옆에둔곳"), encoding="utf-8")
            # ★ `_MEIPASS` 까지 가짜로 놓는다. 안 놓으면 `app_dir()` 이 exe 옆을
            #   그대로 돌려줘 **고침을 빼도 검사가 통과한다** — 실제로 그랬다.
            #   설치본은 `_internal` 이 따로 있으니 그 꼴을 만들어 놓고 재야 한다.
            속팡 = 가짜exe.parent / "_internal"
            속팡.mkdir(exist_ok=True)
            참exe, 참얼림 = sys.executable, globals()["frozen"]
            sys.executable = str(가짜exe)
            globals()["frozen"] = lambda: True
            sys._MEIPASS = str(속팡)
            try:
                assert _적어둔자리() == 잠깐 / "옆에둔곳", _적어둔자리()
            finally:
                sys.executable, globals()["frozen"] = 참exe, 참얼림
                del sys._MEIPASS

            # 환경 변수가 쪽지를 이긴다 — 시험할 때 쪽지를 안 건드려도 되게
            os.environ["VC_DATA"] = str(잠깐 / "환경")
            적기(str(잠깐 / "기록"))
            assert data_dir() == 잠깐 / "환경", data_dir()
        finally:
            _가둘까 = True
            os.environ.pop("VC_DATA", None)
            if 환경 is not None:
                os.environ["VC_DATA"] = 환경
            if 원래 is None:
                쪽지.unlink(missing_ok=True)
            else:
                쪽지.write_text(원래, encoding="utf-8")

    # 판은 굽는 스크립트가 숫자 셋으로 쪼개 쓴다. 모양이 틀리면 거기서 깨진다.
    assert re.fullmatch(r"\d+\.\d+\.\d+", VERSION), VERSION

    # ★★ **판 태그가 이미 있으면 그 판은 나간 것이다 — 올려야 한다.**
    #   실제로 `v0.1.99` 태그를 `VERSION = 0.1.98` 인 커밋에 달았다. 커밋 메시지의
    #   따옴표가 셸을 깨면서 판 올리는 `sed` 도 같이 안 먹었는데 그걸 못 봤다 —
    #   구운 판이 `--doctor` 에 「v0.1.98」 을 찍어서야 알았다.
    #   **사람이 눈으로 볼 일이 아니다.** 여기서 막는다.
    #   (소스가 아니면 `git` 이 없다 — 그때는 건너뛴다.)
    try:
        import subprocess

        있는태그 = subprocess.run(
            ["git", "-C", str(Path(__file__).resolve().parent.parent), "tag", "--list",
             f"v{VERSION}"], capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        있는태그 = ""
    assert not 있는태그, (
        f"v{VERSION} 태그가 이미 있다 — 이 판은 나갔다. paths.VERSION 을 올려라")

    # ★ **Qt 플러그인 자리 박기** — 경로에 한글이 있으면 Qt 가 제 자리를 못 찾는다.
    #   `pin_qt_plugins()` 를 되돌리면 여기서 터져야 한다.
    assert qt_plugins_dir() is None, "PyQt5 가 벌써 올라왔다 — 런타임 붙들기가 늦는다"
    import PyQt5                                          # noqa: F401  (여기서 처음 올린다)
    from PyQt5.QtCore import QCoreApplication, QLibraryInfo

    곳 = qt_plugins_dir()
    assert 곳 is not None and (곳 / "platforms").is_dir(), f"Qt 플러그인 폴더가 없다: {곳}"
    assert pin_qt_plugins() and pin_qt_plugins(), "Qt 플러그인 자리를 못 박는다(두 번 불러도 돼야 한다)"
    assert str(곳) in QCoreApplication.libraryPaths(), QCoreApplication.libraryPaths()
    # Qt 가 스스로 말하는 자리는 **한글이 깨져 있을 수 있다** — 그래서 박는 것이다.
    # 깨지지 않는 자리(영문 경로)에서는 둘이 같다. 어느 쪽이든 박은 자리는 살아 있어야 한다.
    스스로 = QLibraryInfo.location(QLibraryInfo.PluginsPath)
    assert "?" not in str(곳), f"우리가 박는 자리부터 깨졌다: {곳}"
    if "?" in 스스로:
        print(f"  (Qt 가 스스로 말하는 자리는 깨져 있다: {스스로} — 박아서 넘겼다)")

    # ★★ **기계 파일은 앱 자리로, 옛 창고는 복사 → 확인 → 원본 지움**(오너 결정 2026-09-15).
    #   소스로 돌 때는 기록 자리 그대로 · VC_DATA 를 주면 따라간다(시험 격리) · 확인 못 한 것은 원본을 남기고 옛 자리를 계속 쓴다.
    # ★ `기록자리.txt` 를 쓰면 기계 파일은 **앱 자리**로 간다 — 오너 결정(2026-09-15):
    #   기록 폴더는 사람이 여는 곳이라 메모만 둔다(문서 폴더는 iCloud 로 올라갈 수 있고,
    #   그러면 열쇠·db 가 따라 올라간다). 쪽지가 없을 때만 기록 자리와 같아야 한다.
    if 검사중인가():
        pass          # 가둔 자리 안에서 기록·기계가 갈려 있다(바로 위에서 쟀다)
    elif _적어둔자리() is None:
        assert state_dir() == data_dir(), "소스로 돌 때 기계 파일 자리가 기록 자리를 떠났다 — 개발 흐름이 바뀐다"
    else:
        assert state_dir() == _앱자리기본(), state_dir()
    옛판 = sys.platform
    옛환경 = {k: os.environ.get(k) for k in ("VC_DATA", "VC_STATE", "LOCALAPPDATA")}
    try:
        with tempfile.TemporaryDirectory() as tmp:
            기록, 앱 = Path(tmp) / "기록", Path(tmp) / "앱"
            기록.mkdir()
            os.environ["VC_DATA"] = str(기록)
            os.environ.pop("VC_STATE", None)
            assert state_dir() == data_dir() == 기록, "VC_DATA 를 주면 기계 파일도 따라가야 시험이 진짜 자리를 안 건드린다"
            sys.platform = "darwin"
            assert _앱자리기본() == Path.home() / "Library" / "Application Support" / APP_NAME, _앱자리기본()
            sys.platform = "win32"
            os.environ["LOCALAPPDATA"] = str(Path(tmp) / "로컬")
            assert _앱자리기본() == Path(tmp) / "로컬" / APP_NAME, _앱자리기본()
            sys.platform = 옛판

            os.environ["VC_STATE"] = str(앱)
            (기록 / "eb_config.json").write_text('{"pair_token": "t"}', encoding="utf-8")
            _c2 = _sq.connect(str(기록 / "eb.db"))
            _c2.execute("CREATE TABLE a (x)")
            _c2.execute("INSERT INTO a VALUES (1)")
            _c2.commit()
            _c2.close()
            (기록 / "notes_index.db").write_bytes(b"not a database at all " * 60)   # 깨진 db
            (기록 / "data" / "artifacts").mkdir(parents=True)
            (기록 / "data" / "artifacts" / "a.txt").write_text("결과", encoding="utf-8")
            (기록 / "data" / "notes").mkdir(parents=True)
            (기록 / "data" / "notes" / "글.md").write_text("글", encoding="utf-8")

            결과 = 기계파일옮기기()
            assert "eb.db" in 결과["옮김"] and not (기록 / "eb.db").exists() and (앱 / "eb.db").exists(), 결과
            assert store_path() == 앱 / "eb.db" and config_path() == 앱 / "eb_config.json", (store_path(), config_path())
            assert "data/artifacts" in 결과["옮김"] and (앱 / "data" / "artifacts" / "a.txt").exists(), 결과
            assert any(x.startswith("notes_index.db") for x in 결과["남김"]), f"확인 못 한 db 를 옮겼다고 한다: {결과}"
            assert (기록 / "notes_index.db").exists() and not (앱 / "notes_index.db").exists(), \
                "확인 못 한 사본을 남기거나 원본을 지웠다"
            assert index_path() == 기록 / "notes_index.db", "옮기지 못한 파일은 옛 자리를 계속 써야 한다"
            assert (기록 / "data" / "notes" / "글.md").exists(), "글을 건드렸다 — 글은 기계 파일이 아니다"
            다시 = 기계파일옮기기()
            assert not 다시["옮김"] and "eb.db" not in 다시["남김"], f"두 번 부르면 달라진다: {다시}"
    finally:
        sys.platform = 옛판
        for k, v in 옛환경.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    # ★★ **어디서 켜도 같은 창고를 봐야 한다**(2026-09-20). 소스로 돌 때는 `Path.cwd()`
    #   를 창고로 삼는데, 그래서 **켜는 폴더에 따라 창고가 갈렸다** — 볼트 119장이
    #   `VC/pc/data/notes` 에 들어갔는데 `VC/` 에서 켠 VC 는 3장짜리 창고를 보고 있었다.
    #   「기록이 사라졌다」로 보이는 종류라, `기록자리.txt` 로 못 박고 **그것이 이기는지**를 잰다.
    import os as _os8
    import tempfile as _임시8

    with _임시8.TemporaryDirectory() as _잠깐8:
        옛데이터 = _os8.environ.pop("VC_DATA", None)
        옛cwd = _os8.getcwd()
        쪽지 = app_dir() / SPOT
        옛쪽지 = 쪽지.read_text(encoding="utf-8") if 쪽지.exists() else None
        try:
            _가둘까 = False      # 이 구간만 — **쪽지가 이기는지**를 재야 한다
            둘것 = Path(_잠깐8) / "정한자리"
            쪽지.write_text(str(둘것), encoding="utf-8")
            본것 = []
            for 어디 in (_잠깐8, str(app_dir()), str(app_dir().parent)):
                _os8.chdir(어디)
                본것.append(str(data_dir()))
            assert len(set(본것)) == 1, f"켜는 자리마다 창고가 다르다: {본것}"
            assert 본것[0] == str(둘것), (본것[0], 둘것)
        finally:
            _가둘까 = True
            _os8.chdir(옛cwd)
            if 옛쪽지 is None:
                쪽지.unlink(missing_ok=True)
            else:
                쪽지.write_text(옛쪽지, encoding="utf-8")
            if 옛데이터 is not None:
                _os8.environ["VC_DATA"] = 옛데이터

    # ★★ **검사는 진짜 자리를 안 건드린다**(2026-09-21에 실제로 망가뜨리고 알았다).
    #   `server` 검사가 진짜 `eb_config.json` 을 읽고 쓰는 사이, 떠 있던 VC 가 반쯤 쓰인
    #   파일을 보고 **「설정이 깨졌다」며 새로 만들었다** — 자국에 「폰은 다시 짝지어야
    #   한다」가 남았다. `eb.db` 도 「깨져서 옆에 치웠다」. **검사 한 번에 쓰던 사람의
    #   VC 가 조용히 망가진다.** `--check` 로 도는 동안은 통째로 임시 자리에 가둔다.
    assert 검사중인가(), "이 검사는 `--check` 로 도는데 그렇게 안 보인다"
    진짜창고 = _적어둔자리()
    if 진짜창고 is not None:
        assert data_dir() != 진짜창고, "검사가 진짜 창고를 쓴다 — 쓰던 사람 기록이 위험하다"
        assert _가둔자리() in data_dir().parents or data_dir() == _가둔자리(), data_dir()
    assert _가둔자리() in state_dir().parents or state_dir() == _가둔자리(), state_dir()
    assert config_path().parent == state_dir(), config_path()
    # 같은 프로세스 안에서는 **늘 같은 자리**다 — 매번 새로 만들면 검사끼리 못 이어진다
    assert _가둔자리() == _가둔자리()

    print("paths self-check 통과")


if __name__ == "__main__":
    _self_check()
