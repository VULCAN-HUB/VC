"""대화 기록 — VC와 주고받은 것을 그대로 남긴다.

학습 로그(`store.py`)는 계측용이라 무엇을 말했는지는 안 남긴다. 이건 사람이 읽고
고치기 위한 기록이다: **뭐라고 들었는지, 뭘로 알아들었는지, 뭐라고 답했는지, 얼마나 걸렸는지.**

    data/talk.jsonl     한 줄에 한 번의 주고받음

안 보고 고치면 찍는 것이다. 음성은 특히 그렇다 — 사용자가 "이상하다"고 할 때
받아쓰기가 틀린 건지, 라우팅이 틀린 건지, 답이 틀린 건지 기록 없이는 못 가른다.

기록은 이 PC에만 남는다(결정 17). 지우려면 파일을 지우면 된다.
"""

from __future__ import annotations

import paths
import json
import threading
import time
from pathlib import Path
from typing import Any

# 대화 기록·녹음 자리. 시험이 바꿔 끼운다 — **비어 있으면 부를 때 앱 자리를 본다.**
# 불러올 때 정하면 옛 창고 옮기기 전 자리에 박혀, 옮긴 뒤에도 기록 폴더에 다시 쌓는다.
LOG_PATH: Path | None = None
MAX_LINES = 5000  # 넘으면 오래된 것부터 버린다. 무한히 쌓이면 여는 것부터 느려진다

# 실제 소리도 남긴다. 받아쓰기가 틀렸을 때 **글자만 봐서는** 마이크가 작아서인지
# 모델이 약해서인지 못 가른다 — 원본을 다시 돌려봐야 안다.
AUDIO_DIR: Path | None = None   # 진단용 녹음이라 기계 파일이다


def _log() -> Path:
    return LOG_PATH or paths.기계자리("data/talk.jsonl")


def _audio() -> Path:
    return AUDIO_DIR or paths.기계자리("data/recordings")
MAX_AUDIO_FILES = 300  # 넘으면 오래된 것부터 지운다. 목소리를 무한정 쌓아두지 않는다

_lock = threading.Lock()


def save_audio(audio: Any, rate: int = 16000) -> str:
    """방금 들은 소리를 WAV로 남기고 파일 이름을 돌려준다.

    **이 PC에만 남는다.** 어디로도 안 보낸다(결정 1·17). 지우려면 폴더를 지우면 된다.
    """
    try:
        import wave

        import numpy as np

        if audio is None or getattr(audio, "size", 0) == 0:
            return ""
        _audio().mkdir(parents=True, exist_ok=True)
        name = f"{time.strftime('%Y%m%d-%H%M%S')}-{int(time.time() * 1000) % 1000:03d}.wav"
        with wave.open(str(_audio() / name), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())
        _trim_audio()
        return name
    except Exception:
        return ""  # 녹음이 안 남는다고 대화가 멈추면 안 된다


def _trim_audio() -> None:
    files = sorted(_audio().glob("*.wav"))
    for old in files[:-MAX_AUDIO_FILES]:
        try:
            old.unlink()
        except OSError:
            pass


def clear_audio() -> int:
    """녹음을 전부 지운다. 목소리는 사용자 것이라 지우는 길이 늘 있어야 한다."""
    gone = 0
    for f in _audio().glob("*.wav"):
        try:
            f.unlink()
            gone += 1
        except OSError:
            pass
    return gone


def record(**fields: Any) -> None:
    """한 번의 주고받음을 남긴다. 실패해도 VC가 멈추면 안 된다."""
    row = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), **fields}
    try:
        _log().parent.mkdir(parents=True, exist_ok=True)
        with _lock, _log().open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        pass  # 기록이 안 남는다고 대화를 못 하면 본말이 뒤집힌다


def read(limit: int = 50) -> list[dict]:
    """최근 것부터. 깨진 줄은 건너뛴다 — 한 줄 깨졌다고 전부 못 읽으면 안 된다."""
    try:
        lines = _log().read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in reversed(lines):
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
        if len(out) >= limit:
            break
    return out


def trim() -> None:
    try:
        lines = _log().read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    if len(lines) > MAX_LINES:
        with _lock:
            _log().write_text("\n".join(lines[-MAX_LINES:]) + "\n", encoding="utf-8")


def show(limit: int = 30) -> str:
    """사람이 읽는 꼴로. 한 줄에 다 안 들어가서 두 줄로 쪼갠다."""
    rows = read(limit)
    if not rows:
        return "기록 없음"

    out = []
    for r in reversed(rows):
        heard = r.get("heard", "")
        order = r.get("order", "")
        mark = "" if r.get("woke", True) else "  [안 깨어남]"
        out.append(f"{r['ts']}  들음 {heard!r}{mark}")
        if order and order != heard:
            out.append(f"{'':19}  지시 {order!r}")
        if r.get("reply"):
            took = r.get("took", {})
            timing = " ".join(f"{k} {v:.2f}s" for k, v in took.items()) if took else ""
            out.append(f"{'':19}  VC {r['reply']!r}  [{r.get('kind', '')}] {timing}")
        if r.get("error"):
            out.append(f"{'':19}  터짐 {r['error']}")
        if r.get("audio"):
            out.append(f"{'':19}  녹음 {r['audio']}")
    return "\n".join(out)


def audit() -> str:
    """녹음들의 소리 크기를 재서 표로 낸다.

    받아쓰기가 틀렸을 때 **원인이 마이크인지 모델인지** 이걸로 갈린다:
    최대치가 낮으면 마이크, 넉넉한데도 틀렸으면 모델이다.
    """
    try:
        import wave

        import numpy as np
    except ImportError:
        return "numpy가 없어 못 잰다"

    rows = {r["audio"]: r for r in read(500) if r.get("audio")}
    files = sorted(_audio().glob("*.wav"))
    if not files:
        return "녹음 없음"

    out = [f"{'파일':<22} {'길이':>5} {'최대':>6} {'평균':>6}  들은 말"]
    for f in files[-30:]:
        try:
            with wave.open(str(f)) as w:
                frames = w.getnframes()
                dur = frames / w.getframerate()
                data = np.frombuffer(w.readframes(frames), dtype=np.int16) / 32768.0
        except Exception as e:
            out.append(f"{f.name:<22} 못 읽음 {e}")
            continue
        peak = float(abs(data).max()) if data.size else 0.0
        rms = float(np.sqrt(np.mean(data ** 2))) if data.size else 0.0
        heard = rows.get(f.name, {}).get("heard", "?")
        flag = "  ← 너무 작다" if peak < 0.05 else ("  ← 잘림" if peak > 0.99 else "")
        out.append(f"{f.name:<22} {dur:4.1f}s {peak:6.3f} {rms:6.3f}  {heard!r}{flag}")
    return "\n".join(out)


def _self_check() -> None:
    import tempfile

    global LOG_PATH, AUDIO_DIR
    # 녹음은 기록 자리 아래다 — 작업 폴더를 따르면 딴 폴더에서 켤 때 엉뚱한 데 쌓이거나 못 만든다
    # ★ 재려는 것은 **「작업 폴더를 따라다니지 않는다」**이다. 녹음은 기계 파일이라
    #   `기록자리.txt` 를 쓰면 앱 자리로 간다(오너 결정 2026-09-15: 기록 폴더엔 메모만).
    #   기록 자리든 앱 자리든 좋지만, cwd 밑이면 켜는 자리마다 녹음이 흩어진다.
    # ★ 양쪽 다 `resolve()` 한다 — 맥의 `/var` 는 `/private/var` 로 가는 이음이라
    #   한쪽만 풀면 같은 자리를 다른 자리로 본다(가둔 검사 자리에서 실제로 터졌다).
    둘자리 = _audio().resolve()
    기록 = paths.data_dir().resolve()
    기계 = paths.state_dir().resolve()
    assert (기록 in 둘자리.parents or 기계 in 둘자리.parents), (
        f"녹음 폴더가 엉뚱한 자리다: {둘자리}")
    assert Path.cwd().resolve() not in 둘자리.parents or 기록 == Path.cwd().resolve(), (
        f"녹음 폴더가 작업 폴더를 따른다: {둘자리}")

    old = LOG_PATH
    try:
        with tempfile.TemporaryDirectory() as tmp:
            LOG_PATH = Path(tmp) / "talk.jsonl"
            assert read() == [] and show() == "기록 없음"

            record(heard="VC 볼륨 올려", woke=True, order="볼륨 올려",
                   reply="볼륨 올렸어", kind="result",
                   took={"받아쓰기": 0.41, "실행": 0.002})
            record(heard="어쩌고", woke=False)

            rows = read()
            assert len(rows) == 2 and rows[0]["heard"] == "어쩌고", rows
            assert rows[1]["reply"] == "볼륨 올렸어"

            text = show()
            assert "볼륨 올렸어" in text and "안 깨어남" in text
            assert "받아쓰기 0.41s" in text

            # 깨진 줄이 있어도 나머지는 읽힌다.
            with _log().open("a", encoding="utf-8") as f:
                f.write("깨진 줄\n")
            assert len(read()) == 2, "깨진 줄 하나에 전부 못 읽는다"

            # --- 녹음 ---
            old_audio = AUDIO_DIR
            try:
                AUDIO_DIR = Path(tmp) / "rec"
                import numpy as np

                tone = (np.sin(np.linspace(0, 400, 16000)) * 0.3).astype(np.float32)
                name = save_audio(tone)
                assert name.endswith(".wav") and (_audio() / name).exists()
                record(heard="VC 볼륨 올려", woke=True, order="볼륨 올려",
                       reply="볼륨 올렸어", kind="result", audio=name)
                assert name in show(), "기록에 녹음 이름이 안 붙었다"

                text = audit()
                assert "1.0s" in text and name in text, text
                assert "VC 볼륨 올려" in text, "어떤 말이었는지 안 붙었다"

                # 오래된 것부터 지운다 — 목소리를 무한정 쌓아두지 않는다.
                global MAX_AUDIO_FILES
                keep, MAX_AUDIO_FILES = MAX_AUDIO_FILES, 2
                try:
                    for _ in range(4):
                        save_audio(tone)
                    assert len(list(_audio().glob("*.wav"))) <= 2
                finally:
                    MAX_AUDIO_FILES = keep

                # 지우는 길이 늘 있어야 한다.
                assert clear_audio() >= 1 and not list(_audio().glob("*.wav"))

                # 소리가 없으면 파일을 안 만든다.
                assert save_audio(np.zeros(0, dtype=np.float32)) == ""
            finally:
                AUDIO_DIR = old_audio

            # 못 쓰는 곳이어도 조용히 넘어간다 — 기록 때문에 대화가 멈추면 안 된다.
            # ★★ 전에는 `Z:/없는드라이브` 였다. 윈도우에서는 없는 드라이브라 못 쓰지만
            #   **맥·리눅스에서는 그냥 상대 경로**다 — 검사가 소스 폴더 안에
            #   `pc/Z:/없는드라이브/talk.jsonl` 을 **진짜로 만들어 놓고** 통과했다.
            #   아무것도 안 재면서 쓰레기만 남긴 것이다. 어느 운영체제에서나 확실히
            #   못 쓰는 자리로 바꾼다 — **파일 밑에는 폴더를 못 만든다.**
            막힌곳 = Path(tmp) / "이건 폴더가 아니라 파일이다"
            막힌곳.write_text("x", encoding="utf-8")
            LOG_PATH = 막힌곳 / "없는폴더" / "talk.jsonl"
            record(heard="아무거나")  # 터지면 안 된다
            assert not _log().exists(), f"못 쓰는 자리인데 썼다: {LOG_PATH}"
    finally:
        LOG_PATH = old

    print("talklog self-check 통과")


if __name__ == "__main__":
    import sys

    args = sys.argv[1:]
    if "--check" in args:
        _self_check()
    elif "--audit" in args:
        print(audit())          # 녹음 소리 크기 표 — 마이크 탓인지 모델 탓인지 가른다
    elif "--clear" in args:
        print(f"녹음 {clear_audio()}개 지웠다")
    else:
        print(show(int(args[0]) if args and args[0].isdigit() else 30))
