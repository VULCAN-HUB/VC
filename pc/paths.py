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
VERSION = "0.1.67"


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

    그래서 여기만 **exe 옆 `models` 를 먼저 보고**, 없으면 딸려 온 자리로 내려간다.
    """
    if env := os.environ.get("VC_MODELS"):
        return Path(env)
    if frozen():
        곁 = Path(sys.executable).parent / "models"
        if any(곁.glob("*.gguf")) if 곁.is_dir() else False:
            return 곁
    return models_dir()


# 뜻 검색에 쓸 모델을 고르는 차례. **받은 것이 딸린 것보다 먼저다.**
# 앞엣것부터 보고 `model.onnx`·`tokenizer.json`이 둘 다 있으면 그걸 쓴다.
MEANING_ORDER = ("e5-base", "")


def meaning_dir() -> Path:
    """뜻 검색 모델이 있는 자리. 받은 큰 것이 있으면 그것, 없으면 딸려 온 것.

    딸려 온 것을 덮어쓰지 않고 **곁에 둔다** — 받은 것이 시원찮으면 폴더 하나만
    지우면 되돌아간다.
    """
    root = models_dir()
    for name in MEANING_ORDER:
        here = root / name if name else root
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


def data_dir() -> Path:
    """기록·색인·설정이 사는 자리. 없으면 만든다.

    소스로 돌릴 때는 **지금 자리 그대로** 둔다. 개발하다 갑자기 문서 폴더에
    기록이 생기면 놀란다.
    """
    if env := os.environ.get("VC_DATA"):
        here = Path(env)
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


SPOT = "기록자리.txt"


def _적어둔자리() -> Path | None:
    """딸린 것 옆의 `기록자리.txt` 에 적힌 자리. 없으면 `None`.

    **기록이 어디 살지는 사람마다 다르다.** 이 PC 는 작업물을 D 하드에만 두는데
    설치본 기본값은 문서 폴더(C)다. 환경 변수는 바탕화면 아이콘으로 켜면 안 붙고,
    코드에 `D:` 를 박으면 딴 PC 와 맥에서 깨진다. 그래서 **파일 한 장으로 가리킨다.**

    설정에 못 넣는 이유: 설정 자체가 이 자리 안에 산다 — 먼저 자리를 알아야 한다.
    """
    try:
        쪽지 = app_dir() / SPOT
        적힌 = 쪽지.read_text(encoding="utf-8").strip() if 쪽지.is_file() else ""
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
    except OSError:
        return None
    return 자리


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
    where = (data or data_dir()) / "vc-혼자.lock"
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
    return data_dir() / "notes_index.db"


def store_path() -> Path:
    return data_dir() / "eb.db"


def config_path() -> Path:
    return data_dir() / "eb_config.json"


def _self_check() -> None:
    import tempfile

    assert app_dir().exists()
    # 소스로 돌 때는 지금 자리다 — 개발 중에 문서 폴더가 더럽혀지면 안 된다.
    assert not frozen()
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
        옛프로즌, 옛실행 = globals()["frozen"], sys.executable
        globals()["frozen"] = lambda: True
        sys.executable = str(Path(tmp) / "VC.exe")
        sys._MEIPASS = str(Path(tmp) / "_internal")
        try:
            assert gguf_dir() != 곁, "빈 폴더인데 exe 옆을 골랐다"
            (곁 / "아무.gguf").write_bytes(b"x")
            assert gguf_dir() == 곁, gguf_dir()
        finally:
            globals()["frozen"], sys.executable = 옛프로즌, 옛실행
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
            assert notes_dir() == Path(tmp) / "data" / "notes"
            assert index_path() == Path(tmp) / "notes_index.db"
            assert config_path().name == "eb_config.json"
        finally:
            del os.environ["VC_DATA"], os.environ["VC_MODELS"]

    assert data_dir() == Path.cwd(), "환경 변수를 지웠는데 안 돌아왔다"
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
        적기 = lambda 글: 쪽지.write_text(글, encoding="utf-8")
        try:
            # 첫 줄이 자리, 그 아래는 사람이 왜 그리 했는지 적는 자리다
            적기(str(잠깐 / "기록") + chr(10) + "# 여기 둔 까닭을 적어 둔다" + chr(10))
            assert data_dir() == 잠깐 / "기록", data_dir()
            # 못 쓰는 자리를 가리키면 무시하고 원래 자리로 돌아간다.
            # ★ 파일 **밑**을 가리킨다. 처음엔 없는 드라이브(Z:)를 썼는데
            # 이 PC 에 Z: 가 실제로 있어서 **시험이 구별을 못 했다.**
            막힌길 = 잠깐 / "이건파일이다"
            막힌길.write_text("", encoding="utf-8")
            못쓸 = str(막힌길 / "VC")
            적기(못쓸)
            assert data_dir() != Path(못쓸), "못 쓰는 자리를 따라갔다"
            # 주석만 있거나 비면 안 적은 것으로 친다.
            # ★ 안 거르면 **`# 아직 안 정했다` 라는 이름의 폴더가 생긴다** —
            #   처음엔 `Path("#")` 과 비교해서 이걸 못 잡았다.
            군소리 = "# 아직 안 정했다"
            적기(군소리 + chr(10))
            assert data_dir() != Path(군소리).absolute(), data_dir()
            assert not (Path.cwd() / 군소리).exists(), "군소리 이름으로 폴더가 생겼다"
            적기("")
            assert data_dir() == Path.cwd() or frozen(), data_dir()
            # 환경 변수가 쪽지를 이긴다 — 시험할 때 쪽지를 안 건드려도 되게
            os.environ["VC_DATA"] = str(잠깐 / "환경")
            적기(str(잠깐 / "기록"))
            assert data_dir() == 잠깐 / "환경", data_dir()
        finally:
            os.environ.pop("VC_DATA", None)
            if 환경 is not None:
                os.environ["VC_DATA"] = 환경
            if 원래 is None:
                쪽지.unlink(missing_ok=True)
            else:
                쪽지.write_text(원래, encoding="utf-8")

    # 판은 굽는 스크립트가 숫자 셋으로 쪼개 쓴다. 모양이 틀리면 거기서 깨진다.
    assert re.fullmatch(r"\d+\.\d+\.\d+", VERSION), VERSION

    print("paths self-check 통과")


if __name__ == "__main__":
    _self_check()
