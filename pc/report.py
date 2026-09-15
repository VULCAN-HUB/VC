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


import re  # noqa: E402 — 글 파일 이름 가리기에만 쓴다

_글파일꼴 = re.compile(r"[^\\/\s'\"<>|:*?]+\.md\b")


def _hide_names(text: str) -> str:
    """글 파일 이름(`회의록.md`)을 `(글).md` 로 바꾼다.

    ★ 기록 줄은 예외 문구를 그대로 싣는 곳이 많아 **경로와 함께 글 제목이 딸려 온다**
    (`PermissionError: ... '…\\2026\\09\\회의록.md'`). 줄마다 막으면 새 줄에서 또 샌다 — 묶음 한 자리에서 막는다.
    """
    return _글파일꼴.sub("(글).md", text)


def trail(what: str) -> None:
    """한 줄 남긴다. **죽어도 여기까지는 갔다**를 알려 주는 자국이다."""
    try:
        path = paths.기계자리(TRAIL)
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
        _death_file = (paths.기계자리(DEATH)).open("a", encoding="utf-8")
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
    path = paths.기계자리(DEATH)
    if path.exists() and path.stat().st_size > KEEP_BYTES:
        path.write_bytes(("...(앞부분 버림)" + chr(10)).encode()
                         + path.read_bytes()[-KEEP_BYTES // 2:])
    with path.open("a", encoding="utf-8") as f:
        f.write(line)


_seen: dict[str, int] = {}     # 같은 예외를 몇 번 봤나


_메모파일 = "vc-메모리.json"


def 이프로세스메모리() -> tuple[int, int]:
    """**부르는 프로세스**의 지금·최고 메모리(MB). 못 재면 OSError.

    이건 자기 프로세스를 잰다. 그래서 facts() 는 이걸 직접 안 쓰고, 창이
    메모리찍기() 로 적어 둔 파일을 읽는다 — --report 는 창이 아니기 때문이다.
    """
    if os.name != "nt":
        return _유닉스메모리()
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
    커널 = ctypes.windll.kernel32
    # ★ **인자 타입을 박아야 한다.** 안 박으면 프로세스 핸들이 int 로 잘려
    # 64비트에서 엉뚱한 값이 되고, 함수는 0(실패)을 돌려준다. 그런데 돌려준 값을
    # 안 보면 그냥 0MB 가 조용히 찍힌다 — 실제로 그랬다.
    커널.GetCurrentProcess.restype = ctypes.c_void_p
    나 = 커널.GetCurrentProcess()
    됨 = 0
    # 윈도 판에 따라 kernel32 에도 psapi 에도 있다. 둘 다 본다.
    for 어디, 이름 in (("kernel32", "K32GetProcessMemoryInfo"),
                      ("psapi", "GetProcessMemoryInfo")):
        try:
            함수 = getattr(getattr(ctypes.windll, 어디), 이름)
            함수.argtypes = [ctypes.c_void_p, ctypes.POINTER(_메모), wintypes.DWORD]
            함수.restype = wintypes.BOOL
            됨 = 함수(나, ctypes.byref(m), m.cb)
        except (AttributeError, OSError):
            continue
        if 됨:
            break
    if not 됨 or not m.WorkingSetSize:
        # 0 은 「안 쓴다」가 아니라 「못 쟀다」다. 구별이 안 되니 터뜨린다.
        raise OSError(f"메모리를 못 쟀다 (돌려준 값 {됨})")
    return m.WorkingSetSize // 1048576, m.PeakWorkingSetSize // 1048576


def _유닉스메모리() -> tuple[int, int]:
    """맥·리눅스. 최고는 `getrusage`(맥은 바이트, 리눅스는 KB), 지금은 `ps` 의 RSS(KB).

    ★ 전엔 `ctypes.windll` 을 바로 불러 맥에서는 늘 터졌다 — 창은 삼키고 넘어가 메모리가 한 번도 안 적혔다.
    """
    import resource
    import subprocess
    import sys

    최고 = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    최고 //= 1048576 if sys.platform == "darwin" else 1024
    try:
        지금 = int(subprocess.run(["ps", "-o", "rss=", "-p", str(os.getpid())], capture_output=True,
                                text=True, timeout=5).stdout.strip()) // 1024
    except (OSError, ValueError, subprocess.SubprocessError):
        지금 = 최고
    if not 최고:
        raise OSError("메모리를 못 쟀다")
    return 지금 or 최고, 최고


def 메모리찍기() -> None:
    """창이 제 메모리를 파일에 적는다. 창 안 타이머가 4초마다 부른다.

    **잰 때(벽시계)를 같이 적는다.** 창이 자거나 꺼져 파일이 안 갱신되면
    --report 가 「몇 초째 안 갱신」이라고 말할 수 있어야 한다 — 자전에서
    「[자는 중]」을 붙인 것과 같은 까닭이다. 낡은 값을 신선한 값처럼 보이면 안 된다.
    """
    try:
        지금, 최고 = 이프로세스메모리()
    except OSError:
        return          # 못 재면 안 적는다. facts() 가 「창이 안 적었다」로 읽는다
    try:
        (paths.기계자리(_메모파일)).write_text(
            json.dumps({"잰때": time.time(), "켠지": time.time() - _시작한때,
                        "지금MB": 지금, "최고MB": 최고}), encoding="utf-8")
    except OSError:
        pass            # 못 적어도 창이 멈출 이유는 없다


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
        "앱 자리": _hide_home(str(paths.state_dir())),
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
        # ★ **판번호를 찍기만 하고 볼 길이 없으면 아무 값도 없다.**
        # 판번호를 넣은 까닭이 「무엇이 아직 안 고쳐졌나」를 **물어보기 위해서**인데,
        # 그걸 보여 주는 자리가 없으면 예전처럼 **찾다가 눈에 걸려야** 알게 된다.
        # 파일을 센다 — 색인이 아니라. 색인기는 mtime 을 쓰고 조용히 낡을 수 있다.
        옛것 = []
        모두 = 0
        for 파일 in n.notes_files():
            try:
                머리 = 파일.read_text(encoding="utf-8", errors="replace").split(
                    chr(10) + "---", 1)[0]
            except OSError:
                continue
            모두 += 1
            if f"스키마: {notes.적는판}" not in 머리:
                옛것.append(파일.stem)
        맞은 = 모두 - len(옛것)
        out["판 적합률"] = (f"{맞은}/{모두} ({맞은 / max(1, 모두) * 100:.1f}%)가 "
                           f"{notes.적는판}판")
        if 옛것:
            out["아직 옛 판"] = f"{len(옛것)}개 — 예: " + ", ".join(옛것[:3])
        out["연결 수"] = q("SELECT count(*) FROM links")
        out["  그중 흐린 선"] = q("SELECT count(*) FROM links WHERE 흐림 = 1")
        out["뜻 벡터 수"] = q("SELECT count(*) FROM vectors")
        out["아직 못 만든 벡터"] = n.vec_left()
        n.conn.close()
    except Exception as err:
        out["색인 읽기 실패"] = f"{type(err).__name__}: {err}"
    # ★ 메모리는 **창이 적어 둔 파일**을 읽는다. 여기서 바로 재면 안 된다 —
    # --report 는 창이 아니라 새로 뜬 명령줄 프로세스라, GetCurrentProcess() 로
    # 재면 **자기 자신(갓 뜬 41MB · 0초)** 을 잰다. 시험 쪽 25-1 에서 걸렸다:
    # 45초를 기다려도 41MB · 0초 그대로고 「다시 봐라」가 영영 안 사라졌다.
    # 자전(vc-자전.json)과 같은 길이다 — 창이 적고, 딴 프로세스는 읽는다.
    try:
        글 = json.loads((paths.기계자리(_메모파일)).read_text(encoding="utf-8"))
        몇초전 = time.time() - float(글["잰때"])
        켠지 = float(글["켠지"])          # 창이 파일에 적던 그 순간의 「켠 지」
        값 = (f"{int(글['지금MB'])}MB (최고 {int(글['최고MB'])}MB · "
              f"켠 지 {켠지 / 60:.0f}분 {켠지 % 60:.0f}초)")
        # 4초 타이머가 세 번 넘게 걸렀다 = 창이 자거나 꺼졌다. **그때 값이다.**
        if 몇초전 > 12:
            값 += f"  ← **{몇초전:.0f}초째 안 갱신 — 창이 자거나 꺼졌다. 이건 그때 값**"
        elif 켠지 < 30:
            값 += "  ← **아직 다 안 올라왔다. 30초 뒤에 다시 봐라**"
        out["메모리"] = 값
    except (OSError, KeyError, ValueError, TypeError):   # 파일이 목록·글자로 망가져 있어도 진단은 돈다
        out["메모리"] = "창이 아직 안 적었다 (창이 떠 있어야 잰다)"

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
    try:
        out["죽음 기록"] = _죽음갈라((paths.기계자리(DEATH)).read_text(
            encoding="utf-8", errors="replace"))
    except OSError:
        out["죽음 기록"] = "없음"
    return out


def _죽음갈라(글: str) -> str:
    """죽음 기록을 **갈라** 센다 — 크기로만 보면 죽지 않은 판도 죽은 것으로 읽힌다.

    ★ faulthandler 는 윈도우에서 **나중에 처리될 예외까지** 먼저 적는다. COM 이 안에서
      던지고 받는 `0x8001010d`(RPC_E_CANTCALLOUT_ININPUTSYNCCALL)가 창이 「끔 (0)」으로
      멀쩡히 끝난 판에도 찍혔다(시험 PC 7회) — 그 줄은 죽음이 아니다 [짐작이다: CPython 이
      비오류 코드와 C++ 예외만 거르고 COM 예외는 안 거르는 것으로 안다].
    """
    비치명 = 글.count("code 0x8001010d")
    return (f"비치명 COM 예외 {비치명}줄 · 그 밖의 네이티브 예외 "
            f"{글.count('Windows fatal exception') - 비치명}줄 · 파이썬 traceback {글.count('Traceback')}개")


def bundle(out_dir: str | Path = "") -> Path:
    """진단 묶음 하나를 만든다. **이 파일만 보내면 된다.**

    담는 것: 무엇이 어디 있는지 · 자국 · 죽음 기록 · 설정(토큰은 지운다).
    안 담는 것: 기록 내용, 파일 이름, 사용자 이름.
    """
    data = paths.data_dir()
    where = Path(out_dir) if out_dir else paths.state_dir()
    where.mkdir(parents=True, exist_ok=True)
    zip_path = where / f"VC-진단-{time.strftime('%Y%m%d-%H%M%S')}.zip"

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("무엇이 어디.json",
                   json.dumps(facts(), ensure_ascii=False, indent=2))
        for name in (TRAIL, DEATH):
            f = paths.기계자리(name)
            if f.exists():
                z.writestr(name, _hide_names(_hide_home(f.read_text(encoding="utf-8", errors="replace"))))
        cfg = paths.config_path()
        if cfg.exists():
            try:
                got = json.loads(cfg.read_text(encoding="utf-8"))

                # **비밀은 지운다.** 이 파일은 밖으로 나간다.
                # ★★ 맨 위 칸만 보면 안 된다 — 바깥 AI 키는 `backend.api_key` 처럼 **안쪽**에 있고
                #   (보관소가 없는 OS·옮기기 전에는 평문), 모델 자리는 집 폴더(사용자 이름) 경로다. 둘 다 샜다.
                def 지우기(값):
                    if isinstance(값, dict):
                        return {k: ("(지움)" if any(w in k.lower() for w in ("token", "secret", "key", "password"))
                                    else 지우기(v)) for k, v in 값.items()}
                    if isinstance(값, list):
                        return [지우기(v) for v in 값]
                    return 값
                z.writestr("설정.json", _hide_home(json.dumps(지우기(got), ensure_ascii=False, indent=2)))
            except (OSError, ValueError):
                pass
    return zip_path


def 상태요약(줄수: int = 30) -> dict:
    """「상태·기록」에 보일 것(결정 17 ③ — 폰 ⋮ 메뉴 · 창 접힌 칸).

    자국 끝줄과 죽음 기록 끝줄. **기록 내용·글 파일 이름·집 경로는 가린다** — 묶음과 같은 규칙이다.
    """
    def 끝줄(이름: str) -> list[str]:
        try:
            글 = paths.기계자리(이름).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        return [_hide_names(_hide_home(z)) for z in 글.splitlines() if z.strip()][-줄수:]

    죽음 = 끝줄(DEATH)
    return {"trail": 끝줄(TRAIL), "deaths": len(죽음), "death_tail": 죽음[-5:],
            "uptime_s": int(time.time() - _시작한때)}


def 요약쓰기(기록폴더: str | Path) -> Path | None:
    """설정 「기계 기록 보기」가 「둘 다」일 때, 사람이 읽는 요약 한 장을 `_VC기록/상태.md` 에 적는다.

    ★ 바뀐 게 없으면 안 쓴다 — 30초마다 덮으면 옵시디언·iCloud 가 매번 흔들린다. 그래서 「켠 지」처럼 늘 바뀌는 값은 안 싣는다.
    """
    요 = 상태요약(40)
    줄 = ["# VC 상태", "",
         "> VC 가 적는 기계 기록 요약이다. 고쳐도 다음에 덮인다. 설정 「기계 기록 보기」를 「한 곳」으로 두면 더 안 적는다.", ""]
    if 요["deaths"]:
        줄 += [f"⚠ 죽음 기록 {요['deaths']}줄 — VC 에서 「문제 알리기」로 묶어 보내 줘", ""]
    줄 += ["## 최근 기록 (새것이 위)", ""] + [f"- {z}" for z in reversed(요["trail"])]
    글 = chr(10).join(줄) + chr(10)
    자리 = Path(기록폴더) / "_VC기록" / "상태.md"
    try:
        if 자리.exists() and 자리.read_text(encoding="utf-8") == 글:
            return None
        자리.parent.mkdir(parents=True, exist_ok=True)
        자리.write_text(글, encoding="utf-8")
        return 자리
    except OSError:
        return None         # 기록 폴더가 잠겨도 VC 는 멈추면 안 된다


def _self_check() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        os.environ["VC_DATA"] = tmp
        try:
            trail("검사 시작")
            trail("두 번째 줄")
            said = (Path(tmp) / TRAIL).read_text(encoding="utf-8")
            assert "검사 시작" in said and "두 번째 줄" in said
            # 「상태·기록」 요약은 글 제목·집 경로를 가린다(폰으로 나간다).
            trail(f"열었다 {Path.home()}/문서/회의록.md")
            요약글 = json.dumps(상태요약(), ensure_ascii=False)
            assert "검사 시작" in 요약글, 요약글
            assert "회의록" not in 요약글 and str(Path.home()) not in 요약글, 요약글
            # 「둘 다」의 요약 한 장 — 가린 채로 쓰고, 안 바뀌었으면 다시 안 쓴다.
            쓴 = 요약쓰기(Path(tmp) / "기록")
            assert 쓴 is not None and 쓴.parent.name == "_VC기록", 쓴
            assert "검사 시작" in 쓴.read_text(encoding="utf-8") and "회의록" not in 쓴.read_text(encoding="utf-8")
            assert 요약쓰기(Path(tmp) / "기록") is None, "안 바뀌었는데 또 쓴다 — 옵시디언·iCloud 가 30초마다 흔들린다"

            # ★★ **메모리는 「켠 지」와 같이 적힌다.** 시험하는 쪽이 뜬 직후에 재서
            # 80MB·426MB 를 보고 두 번 「줄었다」로 읽을 뻔했다(모델이 아직 안
            # 올라온 값이다). **값이 스스로 말하면 「30초 뒤에 재라」를 안 외워도 된다.**
            것들 = facts()
            # ★ **판번호를 볼 길**이 있어야 「무엇이 아직 안 고쳐졌나」를 물어볼 수
            #   있다. 안 보여 주면 예전처럼 찾다가 눈에 걸려야 알게 된다.
            assert "판 적합률" in 것들 and "판" in 것들["판 적합률"], 것들.get("판 적합률")
            assert "그중 흐린 선" in str(것들), "흐린 선을 안 센다"
            assert 것들["판"].startswith("v0."), 것들["판"]

            # ── 메모리: 창이 적은 파일을 읽는다 ────────────────────────────
            # ★ 예전엔 facts() 가 자기 프로세스를 쟀다. --report 는 창이 아니라
            #   새 프로세스라 늘 「갓 뜬 41MB · 0초」가 나왔다(시험 25-1).
            #   이제 창이 파일에 적고, 낡으면 그렇게 말한다.
            #
            # 방금 켠 것처럼 만든다 — 그래야 「다시 봐라」 경우를 확실히 본다.
            global _시작한때
            _시작한때 = time.time()
            메모리찍기()
            메모 = facts().get("메모리", "")
            assert "MB" in 메모, 메모
            # 0 은 「안 쓴다」가 아니라 「못 쟀다」다. 인자 타입이 잘리면 이렇게 된다.
            assert not 메모.startswith("0MB"), 메모
            assert "켠 지" in 메모, 메모
            # 방금 적었으니 신선하다 — 「안 갱신」이 붙으면 안 된다.
            assert "안 갱신" not in 메모, 메모
            # 갓 뜬 값이라 「다시 봐라」가 붙어야 한다.
            assert "다시 봐라" in 메모, 메모

            # 낡은 파일 = 창이 자거나 꺼진 것. **낡았다고 말해야 한다.**
            # 이게 없으면 41MB 를 신선한 값으로 읽던 그 병이 그대로 남는다.
            (Path(tmp) / _메모파일).write_text(
                json.dumps({"잰때": time.time() - 60, "켠지": 300.0,
                            "지금MB": 494, "최고MB": 511}), encoding="utf-8")
            낡음 = facts()["메모리"]
            assert "안 갱신" in 낡음 and "494MB" in 낡음, 낡음
            assert "다시 봐라" not in 낡음, 낡음      # 낡은 것에 갓 뜬 딱지 붙이면 안 된다

            # 파일이 없으면(창이 한 번도 안 뜸) 그렇게 말한다 — 0MB 가 아니다.
            (Path(tmp) / _메모파일).unlink()
            없음 = facts()["메모리"]
            assert "안 적었다" in 없음, 없음

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
            # 기록 줄에 예외 문구로 딸려 온 글 파일 이름도 묶음에 안 담긴다
            trail(r"[시험] PermissionError: 'D:\창고\2026\09\남몰래쓴제목.md' 를 못 읽었다")
            paths.config_path().write_text(
                json.dumps({"pair_token": "비밀값123", "port": 8765,
                            # 안쪽 칸의 바깥 AI 키 · 집 폴더가 든 모델 자리도 새면 안 된다
                            "backend": {"kind": "anthropic", "api_key": "sk-안쪽비밀456",
                                        "model_dir": str(Path.home() / "models")}}), encoding="utf-8")
            made = bundle()
            assert made.exists() and made.suffix == ".zip"
            with zipfile.ZipFile(made) as z:
                names = set(z.namelist())
                assert {"무엇이 어디.json", TRAIL, DEATH, "설정.json"} <= names, names
                blob = b"".join(z.read(n) for n in names)
            assert "비밀값123".encode() not in blob, "토큰이 묶음에 들어갔다"
            assert "sk-안쪽비밀456".encode() not in blob, "설정 안쪽의 API 키가 묶음에 들어갔다"
            assert "남몰래쓴제목".encode() not in blob, "기록 줄의 글 파일 이름이 묶음에 들어갔다"
            assert home.encode() not in blob, "사용자 이름이 묶음에 들어갔다"
        finally:
            stop_watching()
            del os.environ["VC_DATA"]

    # 죽음 기록은 갈라 센다 — 비치명 COM 예외를 죽음과 한 셈에 넣지 않는다
    갈라 = _죽음갈라("Windows fatal exception: code 0x8001010d\n\n"
                  "Windows fatal exception: access violation\n"
                  "Traceback (most recent call last):\n")
    assert 갈라 == "비치명 COM 예외 1줄 · 그 밖의 네이티브 예외 1줄 · 파이썬 traceback 1개", 갈라
    print("report self-check 통과")


if __name__ == "__main__":
    _self_check()
