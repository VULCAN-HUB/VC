"""무슨 일이 있었는지 남기고, 한 파일로 묶어 보내게 한다.

**딴 PC에서 난 일은 우리가 못 본다.** 쓰는 사람이 "안 켜져요" 한 마디만 할 수 있고,
우리는 화면도 로그도 없다. 그래서 세 가지를 갖춘다:

1. **자국(`vc-기록.log`)** — 켜고 끄고, 어디까지 갔는지. 죽어도 남은 줄까지는 보인다.
2. **죽음(`vc-죽음.log`)** — 파이썬 예외로 **안 잡히는** 죽음까지 잡는다. 실제로
   빈 그래프를 띄우면 프로세스가 통째로 죽었는데 파이썬 쪽엔 아무것도 안 남았다.
   `faulthandler` 는 그 순간의 C 스택을 파일에 쏟아 준다.
3. **묶음(`VC-진단-....zip`)** — 위 둘 + 설정 + 무엇이 어디 있는지. 사람이 폴더를
   뒤질 필요 없이 파일 하나를 보내면 된다.

**개인정보는 안 담는다.** 기록 내용도, 파일 이름도, 사용자 이름도 안 넣는다 —
경로는 집 폴더를 `~` 로 바꿔 적는다.
"""
from __future__ import annotations

import faulthandler
import json
import os
import platform
import sys
import time
import traceback
import zipfile
from pathlib import Path

import paths

# 이 프로세스를 켠 때. 메모리 값 옆에 「켠 지」를 붙이는 데 쓴다.
_시작한때 = time.time()

TRAIL = "vc-기록.log"
DEATH = "vc-죽음.log"
KEEP_BYTES = 512 * 1024   # 자국이 이보다 커지면 앞을 버린다. 20년을 켜 둬도 안 는다

_death_file = None        # faulthandler 가 쓰는 파일. 닫으면 안 되므로 붙들어 둔다


def _hide_home(text: str) -> str:
    """집 폴더를 `~` 로 바꾼다. 사용자 이름이 경로에 들어 있다."""
    home = str(Path.home())
    return text.replace(home, "~").replace(home.replace("\\", "/"), "~")


def trail(what: str) -> None:
    """한 줄 남긴다. **죽어도 여기까지는 갔다**를 알려 주는 자국이다."""
    try:
        path = paths.data_dir() / TRAIL
        if path.exists() and path.stat().st_size > KEEP_BYTES:
            # 앞을 버리고 뒤만 남긴다. 최근 것이 쓸모 있다.
            tail = path.read_bytes()[-KEEP_BYTES // 2:]
            path.write_bytes(("...(앞부분 버림)" + chr(10)).encode() + tail)
        with path.open("a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {_hide_home(what)}\n")
    except OSError:
        pass          # 남기다 실패해도 프로그램이 멈추면 안 된다


def watch_deaths() -> None:
    """파이썬이 못 잡는 죽음까지 파일로 받아 둔다. 켤 때 한 번 부른다.

    접근 위반·스택 넘침 같은 것은 예외로 안 올라온다 — `try/except` 로는 못 잡는다.
    이걸 안 켜 두면 딴 PC 에서 죽었을 때 **남는 게 하나도 없다.**
    """
    global _death_file
    if _death_file is not None:
        return
    try:
        _death_file = (paths.data_dir() / DEATH).open("a", encoding="utf-8")
        # ★ **켤 때는 여기에 아무것도 안 쓴다.** 예전에는 「=== 켬」을 여기 적었는데,
        # 그러면 **켤 때마다 죽음 기록이 자라서 크기로는 죽었는지 알 수가 없다.**
        # 시험하는 쪽이 31바이트씩 느는 것을 보고 「매번 죽는다」로 읽을 뻔했고,
        # 나도 네 시간 시계에서 「죽음기록 그대로」를 예외 없음의 근거로 썼다 —
        # 껐다 켜면 그 근거가 무너진다.
        #
        # 이제 규칙이 하나다: **이 파일이 자랐으면 무언가 죽은 것이다.**
        # 언제 켰는지는 자국(`vc-기록.log`)에 남으므로 잃는 것이 없다.
        trail(f"죽음 지켜보기 켬 ({time.strftime('%Y-%m-%d %H:%M:%S')})")
        faulthandler.enable(file=_death_file, all_threads=True)
    except OSError:
        _death_file = None


def stop_watching() -> None:
    """죽음 지켜보기를 끄고 파일을 놓아준다. 끌 때와 검사에서 쓴다 —
    윈도우는 열린 파일을 못 지운다."""
    global _death_file
    faulthandler.disable()
    if _death_file is not None:
        try:
            _death_file.close()
        except OSError:
            pass
        _death_file = None


def catch_slot_deaths() -> None:
    """**PyQt 슬롯에서 터진 예외를 남긴다.** 켤 때 한 번 부른다.

    PyQt5 는 슬롯 안에서 처리 안 된 파이썬 예외를 만나면 `sys.excepthook` 을 부른 뒤
    `qFatal()` 로 **프로세스를 죽인다**(0xC0000409, Qt5Core.dll). 기본 훅은 stderr 로
    쏟는데 창 프로그램은 stderr 가 없어서 **한 글자도 안 남는다** — 낯선 PC 에서
    검색 한 번에 여섯 번 죽었는데 죽음 기록이 텅 비어 있었다.

    `faulthandler` 로도 안 잡힌다. 이건 접근 위반이 아니라 Qt 가 스스로 부른 abort 다.
    """
    old_hook = sys.excepthook

    def hook(kind, err, tb):
        # 처음 본 예외일 때만 자국에도 적는다. 매 프레임 나는 것을 그대로 적으면
        # 자국이 그 한 줄로만 채워져 **정작 어디까지 갔는지가 안 보인다.**
        if log_crash(err):
            trail(f"슬롯에서 죽음: {kind.__name__}: {err}")
        old_hook(kind, err, tb)

    sys.excepthook = hook


def log_crash(err: BaseException) -> bool:
    """파이썬 예외를 남긴다. **같은 것은 한 번만 적고 세기만 한다.**

    그리는 자리에서 터지면 매 프레임 난다 — 낯선 PC 에서 2분에 같은 traceback 이
    329건 쌓여 로그가 86KB 가 됐다. 진단 묶음은 사람이 보내는 파일이라 이렇게
    부풀면 못 보낸다. **몇 번 났는지가 중요하지 329벌이 필요한 게 아니다.**
    """
    try:
        mark = f"{type(err).__name__}: {err}"
        seen = _seen.get(mark, 0) + 1
        _seen[mark] = seen
        if seen > 1:
            if seen in (2, 10, 100) or seen % 1000 == 0:
                _note(f"=== {_now()} 같은 예외 {seen}번째 — {_hide_home(mark)}" + chr(10))
            return False
        where = "".join(traceback.format_exception(type(err), err, err.__traceback__))
        _note(chr(10) + f"=== {_now()} 예외" + chr(10) + _hide_home(where))
        return True
    except OSError:
        return False


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _note(line: str) -> None:
    """죽음 기록에 한 줄. 너무 커지면 앞을 버린다 — 자국이 무한정 자라면 안 된다."""
    path = paths.data_dir() / DEATH
    if path.exists() and path.stat().st_size > KEEP_BYTES:
        path.write_bytes(("...(앞부분 버림)" + chr(10)).encode()
                         + path.read_bytes()[-KEEP_BYTES // 2:])
    with path.open("a", encoding="utf-8") as f:
        f.write(line)


_seen: dict[str, int] = {}     # 같은 예외를 몇 번 봤나


def facts() -> dict:
    """지금 무엇이 어디 있는지. **기록 내용은 안 담는다.**"""
    models = paths.models_dir()
    out = {
        "때": time.strftime("%Y-%m-%d %H:%M:%S"),
        # ★ **어느 판인지가 맨 위에 있어야 한다.** 이게 없어서 시험하는 쪽이
        # 받은 판을 파일 이름으로만 알았고, 되돌릴 때 짚을 것이 없었다.
        "판": f"v{paths.VERSION}",
        "윈도우": platform.platform(),
        "파이썬": sys.version.split()[0],
        "설치본인가": paths.frozen(),
        "딸린 것 자리": _hide_home(str(paths.app_dir())),
        "기록 자리": _hide_home(str(paths.data_dir())),
        "모델 자리": _hide_home(str(models)),
        "뜻 검색 모델 자리": _hide_home(str(paths.meaning_dir())),
        "모델 있나": (models / "model.onnx").exists(),
        "C++ 런타임 붙듦": paths.pin_runtime(),
    }
    try:
        import notes

        n = notes.Notes(paths.notes_dir(), str(paths.index_path()), index_now=False)
        q = lambda s: n.conn.execute(s).fetchone()[0]
        out["항목 수"] = q("SELECT count(*) FROM notes")
        out["연결 수"] = q("SELECT count(*) FROM links")
        out["뜻 벡터 수"] = q("SELECT count(*) FROM vectors")
        out["아직 못 만든 벡터"] = n.vec_left()
        n.conn.close()
    except Exception as err:
        out["색인 읽기 실패"] = f"{type(err).__name__}: {err}"
    # ★ **메모리는 「켠 지 얼마나 됐나」와 같이 적는다.**
    # 시험하는 쪽이 뜬 직후에 재서 80MB·426MB 를 보고 두 번 「줄었다」로 읽을 뻔했다.
    # 모델이 아직 안 올라온 값이다 — 30초쯤 지나면 494MB 로 자리를 잡는다.
    # **값 옆에 켠 지가 붙어 있으면 그 규칙을 외울 필요가 없다.**
    # 이건 「[자는 중]」·「간격 바람/실제」와 같은 결이다 — **값이 스스로 말하게 한다.**
    try:
        import ctypes
        from ctypes import wintypes

        class _메모(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t),
                        ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t),
                        ("PeakPagefileUsage", ctypes.c_size_t)]

        m = _메모()
        m.cb = ctypes.sizeof(m)
        # **돌려주는 값을 본다.** 안 보면 실패해도 0MB 가 조용히 찍힌다 — 실제로
        # 그랬다. 0 은 「메모리를 안 쓴다」가 아니라 「못 쟀다」인데 구별이 안 된다.
        # ★ **인자 타입을 박아야 한다.** 안 박으면 프로세스 핸들이 int 로 잘려
        # 64비트에서 엉뚱한 값이 되고, 함수는 0(실패)을 돌려준다 —
        # 그런데 우리가 안 보면 **그냥 0MB 가 조용히 찍힌다.**
        커널 = ctypes.windll.kernel32
        커널.GetCurrentProcess.restype = ctypes.c_void_p
        나 = 커널.GetCurrentProcess()
        됨 = 0
        # 윈도 판에 따라 `kernel32` 에도 `psapi` 에도 있다. 둘 다 본다.
        for 어디, 이름 in (("kernel32", "K32GetProcessMemoryInfo"),
                          ("psapi", "GetProcessMemoryInfo")):
            try:
                함수 = getattr(getattr(ctypes.windll, 어디), 이름)
                함수.argtypes = [ctypes.c_void_p, ctypes.POINTER(_메모),
                                wintypes.DWORD]
                함수.restype = wintypes.BOOL
                됨 = 함수(나, ctypes.byref(m), m.cb)
            except (AttributeError, OSError):
                continue
            if 됨:
                break
        if not 됨 or not m.WorkingSetSize:
            raise OSError(f"메모리를 못 쟀다 (돌려준 값 {됨})")
        켠지 = time.time() - _시작한때
        out["메모리"] = (f"{m.WorkingSetSize // 1048576}MB "
                        f"(최고 {m.PeakWorkingSetSize // 1048576}MB · "
                        f"켠 지 {켠지 / 60:.0f}분 {켠지 % 60:.0f}초)")
        if 켠지 < 30:
            out["메모리"] += "  ← **아직 다 안 올라왔다. 30초 뒤에 다시 봐라**"
    except Exception as err:
        out["메모리 실패"] = f"{type(err).__name__}: {err}"

    # ★ **자전이 고르게 도는지.** 시험하는 쪽은 화면을 찍어서 보기 때문에 이걸
    # 구조적으로 못 잰다 — 찍힌 두 장 사이에 무슨 일이 있었는지 안 남는다.
    # 오너가 「중간중간 멈칫한다」고 본 것을 열다섯 판 동안 아무도 못 봤다.
    # 그림 대신 **숫자로** 남기면 사람 눈이 아니어도 갈린다.
    try:
        import graph3d

        # **딴 프로세스가 센 값을 파일에서 읽는다.** 여기(진단 묶음)는
        # 창을 그리는 프로세스가 아니라 별도 프로세스라, 제 셈을 보면
        # 늘 「안 돌았다」다 — 174분을 켜 두고도 그랬다.
        out["자전 고름"] = graph3d.멈칫셈.읽어오기()
    except Exception as err:
        out["자전 고름 실패"] = f"{type(err).__name__}: {err}"
    try:
        import onnxruntime

        out["onnxruntime"] = onnxruntime.__version__
    except Exception as err:
        out["onnxruntime 실패"] = f"{type(err).__name__}: {err}"
    return out


def bundle(out_dir: str | Path = "") -> Path:
    """진단 묶음 하나를 만든다. **이 파일만 보내면 된다.**

    담는 것: 무엇이 어디 있는지 · 자국 · 죽음 기록 · 설정(토큰은 지운다).
    안 담는 것: 기록 내용, 파일 이름, 사용자 이름.
    """
    data = paths.data_dir()
    where = Path(out_dir) if out_dir else data
    where.mkdir(parents=True, exist_ok=True)
    zip_path = where / f"VC-진단-{time.strftime('%Y%m%d-%H%M%S')}.zip"

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("무엇이 어디.json",
                   json.dumps(facts(), ensure_ascii=False, indent=2))
        for name in (TRAIL, DEATH):
            f = data / name
            if f.exists():
                z.writestr(name, _hide_home(f.read_text(encoding="utf-8", errors="replace")))
        cfg = paths.config_path()
        if cfg.exists():
            try:
                got = json.loads(cfg.read_text(encoding="utf-8"))
                # **토큰은 지운다.** 이 파일은 밖으로 나간다.
                for key in list(got):
                    if "token" in key.lower() or "secret" in key.lower():
                        got[key] = "(지움)"
                z.writestr("설정.json", json.dumps(got, ensure_ascii=False, indent=2))
            except (OSError, ValueError):
                pass
    return zip_path


def _self_check() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        os.environ["VC_DATA"] = tmp
        try:
            trail("검사 시작")
            trail("두 번째 줄")
            said = (Path(tmp) / TRAIL).read_text(encoding="utf-8")
            assert "검사 시작" in said and "두 번째 줄" in said

            # ★★ **메모리는 「켠 지」와 같이 적힌다.** 시험하는 쪽이 뜬 직후에 재서
            # 80MB·426MB 를 보고 두 번 「줄었다」로 읽을 뻔했다(모델이 아직 안
            # 올라온 값이다). **값이 스스로 말하면 「30초 뒤에 재라」를 안 외워도 된다.**
            것들 = facts()
            assert 것들["판"].startswith("v0."), 것들["판"]
            메모 = 것들.get("메모리", "")
            assert "MB" in 메모, 것들.get("메모리 실패", 메모)
            # ★ **0MB 는 「안 쓴다」가 아니라 「못 쟀다」다.** 인자 타입을 안 박으면
            # 프로세스 핸들이 잘려 함수가 실패하는데, 안 보면 0MB 가 조용히 찍힌다.
            assert not 메모.startswith("0MB"), 메모
            assert "켠 지" in 메모, 메모
            # 갓 뜬 값에는 「아직 다 안 올라왔다」가 붙는다 — 그래야 안 헷갈린다.
            assert "다시 봐라" in 메모, 메모

            watch_deaths()
            assert faulthandler.is_enabled(), "죽음 지켜보기가 안 켜졌다"
            # ★★ **켜기만 해서는 죽음 기록이 안 자란다.** 규칙은 하나다 —
            # **이 파일이 자랐으면 무언가 죽은 것이다.** 예전에는 켤 때마다
            # 「=== 켬」을 적어서 크기로는 아무것도 알 수 없었고, 시험하는 쪽이
            # 31바이트씩 느는 것을 보고 「매번 죽는다」로 읽을 뻔했다.
            죽음표 = Path(tmp) / DEATH
            assert not 죽음표.exists() or 죽음표.stat().st_size == 0, \
                죽음표.read_text(encoding="utf-8")[:200]
            # 켠 것은 자국에 남는다 — 잃는 것은 없다.
            assert "죽음 지켜보기 켬" in (Path(tmp) / TRAIL).read_text(encoding="utf-8")
            try:
                raise ValueError("일부러 낸 오류")
            except ValueError as err:
                log_crash(err)
            died = (Path(tmp) / DEATH).read_text(encoding="utf-8")
            assert "일부러 낸 오류" in died

            # **같은 예외가 쏟아져도 로그가 안 부푼다.** 그리는 자리에서 터지면
            # 매 프레임 난다 — 낯선 PC 에서 2분에 329건이 쌓여 86KB 가 됐다.
            was = len(died)
            for _ in range(500):
                try:
                    raise ValueError("쏟아지는 오류")
                except ValueError as err:
                    log_crash(err)
            flood = (Path(tmp) / DEATH).read_text(encoding="utf-8")
            assert flood.count("쏟아지는 오류") < 12, flood.count("쏟아지는 오류")
            assert "100번째" in flood, "몇 번 났는지를 안 남겼다"
            assert len(flood) - was < 4000, len(flood) - was

            # **슬롯에서 죽으면 남아야 한다.** 낯선 PC 에서 여섯 번 죽고도 한 줄도
            # 안 남았던 자리다.
            keep = sys.excepthook
            catch_slot_deaths()
            try:
                raise RuntimeError("슬롯에서 난 오류")
            except RuntimeError as err:
                sys.excepthook(type(err), err, err.__traceback__)
            finally:
                sys.excepthook = keep
            died = (Path(tmp) / DEATH).read_text(encoding="utf-8")
            assert "슬롯에서 난 오류" in died, "슬롯 예외가 안 남았다"
            assert "슬롯에서 죽음" in (Path(tmp) / TRAIL).read_text(encoding="utf-8")

            got = facts()
            assert "윈도우" in got and "기록 자리" in got
            # **집 폴더 이름이 새 나가면 안 된다.**
            home = str(Path.home())
            assert home not in json.dumps(got, ensure_ascii=False), "사용자 이름이 샜다"

            # 토큰이 든 설정을 넣어 두고, 묶음에 안 담기는지 본다
            paths.config_path().write_text(
                json.dumps({"pair_token": "비밀값123", "port": 8765}), encoding="utf-8")
            made = bundle()
            assert made.exists() and made.suffix == ".zip"
            with zipfile.ZipFile(made) as z:
                names = set(z.namelist())
                assert {"무엇이 어디.json", TRAIL, DEATH, "설정.json"} <= names, names
                blob = b"".join(z.read(n) for n in names)
            assert "비밀값123".encode() not in blob, "토큰이 묶음에 들어갔다"
            assert home.encode() not in blob, "사용자 이름이 묶음에 들어갔다"
        finally:
            stop_watching()
            del os.environ["VC_DATA"]

    print("report self-check 통과")


if __name__ == "__main__":
    _self_check()
