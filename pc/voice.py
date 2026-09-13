"""귀와 입 — 말로 부르고 말로 답한다.

키보드로 치는 이비는 이비가 아니다. 글래스에는 키보드가 없다.

    귀   마이크 → 말이 끝날 때까지 모음 → 받아쓰기(Whisper)
    입   글자 → 소리 (윈도우 SAPI / 맥 say)

**모델도 목소리도 새로 안 받는다.** 받아쓰기는 faster-whisper, 목소리는 OS에 이미
들어 있는 것을 쓴다(윈도우 한국어 Heami). 설치할 게 없으면 사용자가 설치를 안 한다.

지키는 것 넷:

    말하는 중엔 안 듣는다      자기 목소리를 다시 받아쓰면 혼자 대화가 이어진다
    호출어만으로는 실행 안 함   짧은 호출어는 오인식이 잦다 — 부르기만 하면 기다린다
    조용해질 때까지 모은다      고정 길이로 자르면 말이 중간에서 끊긴다
    마이크 없으면 키보드로      장치 문제로 이비가 통째로 죽으면 안 된다
"""

from __future__ import annotations

import paths
import difflib
import json
import platform
import re
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable

from engine import _add_cuda_dlls

SAMPLE_RATE = 16000  # Whisper가 쓰는 값. 다른 값이면 어차피 여기로 맞춰야 한다
SILENCE_SEC = 0.5  # 이만큼 조용하면 말이 끝난 것으로 본다. 이 값이 체감 반응속도다
MAX_UTTERANCE_SEC = 15  # 한 번에 이보다 길게 안 받는다
START_LEVEL = 0.012  # 이 크기를 넘으면 말이 시작된 것으로 본다(0~1)

# 마이크마다 감도가 다르다. 기본값은 어디선가 반드시 틀린다 — 재서 저장한 값이 있으면
# 그걸 쓴다(`mic_tune.py --apply`가 만든다).
MIC_TUNING = paths.data_dir() / "mic.json"

# 답한 직후 이만큼은 호출어 없이 받는다. 사람은 한 번 부르고 여러 마디 이어 말한다 —
# 매번 호출어를 요구하면 대화가 아니라 명령 입력이 된다.
FOLLOWUP_SEC = 12


def _load_tuning() -> None:
    global START_LEVEL, SILENCE_SEC
    try:
        saved = json.loads(MIC_TUNING.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    START_LEVEL = float(saved.get("start_level", START_LEVEL))
    SILENCE_SEC = float(saved.get("silence_sec", SILENCE_SEC))

# 부르는 이름은 **둘 다** 받는다. 하나는 제품 이름(VC), 하나는 만든 곳(VULCAN).
WAKE = "브이씨"                     # 화면·안내에 쓰는 이름
WAKE_WORDS = ("브이씨", "불칸")      # 받아쓰기에 미리 알려 줄 이름들

# 받아쓰기가 흔들리는 꼴들. **짐작이 아니라 실제로 돌려준 것**을 적는다
# (2026-08-27 입→귀 왕복 측정).
#
# 중요한 발견: "브이씨"는 한글로 안 돌아온다 — `VC`·`VCR`·`PC` 처럼 로마자로 온다.
# 한글 꼴만 적어 뒀으면 한 번도 안 걸렸을 것이다.
#
# "불칸"은 두 음절이지만 ㅂ·ㅋ가 섞여 파열음이 두 번 나서 잡음 속에서도 윤곽이
# 남는다. 앞선 호출어 "이비"는 모음이 이어져 "입이"·"이기"로 잘 흘렀다.
WAKE_FORMS = (
    # 불칸 계열
    "불칸", "불 칸", "VULCAN", "벌컨", "불칸아", "불칸이", "불카라",
    "불칵", "불캉", "불간", "풀칸", "물칸", "발칸", "불칼",
    # "브이씨"를 아는 낱말로 일러 주면 받아쓰기가 "불칸"까지 그쪽으로 끌어당긴다.
    # 이름을 둘 두는 값이다 — 관찰된 꼴을 그대로 태운다.
    "브이카", "브이카는", "불카는",
    # 브이씨 계열 — 로마자로 온다
    "브이씨", "브이 씨", "브이씨야", "브이씨의", "VC", "VCR", "V씨", "비씨", "뷔씨",
)

# **이것만 말했을 때에만** 호출로 친다. `PC`는 너무 흔해서 꼴에 넣으면
# "PC 켜줘"·"PC 느려" 같은 말이 전부 호출로 먹힌다. 그런데 "브이씨"라고만 부르면
# 받아쓰기가 실제로 `PC`를 돌려준다 — 그래서 통째로 그것뿐일 때만 태운다.
WAKE_ALONE = ("PC", "피씨", "피시", "비시")

# 호출어처럼 들리지만 아닌 말. 이게 없으면 뉴스만 틀어도 VC가 깨어난다.
#
# **"불 켜"·"불 꺼"를 호출어 꼴에 넣으면 안 된다.** 실제 지시어라서, 넣는 순간
# 불을 켜라는 말이 전부 호출로 먹힌다 — 그래서 받침이 ㄴ인 꼴만 태운다.
NOT_WAKE = ("발칸반도", "발칸포", "불칸반도", "브이로그", "비씨카드",
            "PC방", "피시방", "피씨방", "VCR테이프")


_load_tuning()


def heard_wake(text: str) -> tuple[bool, str]:
    """호출어가 들렸는지, 그리고 뒤에 붙은 지시가 뭔지.

    호출어만 부르고 끝난 경우와 지시까지 말한 경우를 구분해야 한다 — 전자는 대기,
    후자는 실행이다.
    """
    clean = text.strip()
    if not clean:
        return False, ""
    # **말머리만 본다.** 어디에 있든 막으면 "브이씨 브이로그 만들어줘" 같은
    # 멀쩡한 부름까지 죽는다. 호출어 판정도 어차피 말머리에서만 한다.
    tight = clean.replace(" ", "")
    if any(tight.upper().startswith(bad.upper()) for bad in NOT_WAKE):
        return False, ""  # 발칸반도 얘기는 VC를 부른 게 아니다

    # 통째로 그것뿐일 때만 호출인 꼴(흔한 낱말이라 뒤에 말이 붙으면 안 태운다).
    bare = tight.rstrip(",.!?~")
    if any(bare.upper() == form.upper() for form in WAKE_ALONE):
        return True, ""

    # 긴 것부터 본다. "불칸"을 먼저 맞히면 "불칸아 불 꺼"에서 "아 불 꺼"가 지시가 되고,
    # "VC"를 먼저 맞히면 "VCR 불 꺼"에서 "R 불 꺼"가 지시가 된다.
    forms = sorted(WAKE_FORMS, key=len, reverse=True)
    woke, rest = False, clean
    # **말머리에 부름이 겹치면 다 뗀다.** 받아쓰기가 앞 소리를 흘려 넣어
    # "브이씨, 불칸 오늘 일정"처럼 두 번 붙는 일이 실제로 있었다 — 하나만 떼면
    # 남은 호출어가 지시의 첫 낱말이 되어 버린다.
    for _ in range(3):
        for form in forms:
            m = re.match(rf"^\s*{re.escape(form)}\s*[,.!?~]*\s*", rest, re.IGNORECASE)
            if m:
                woke, rest = True, rest[m.end():].strip()
                break
        else:
            break
    return (True, rest) if woke else (False, "")


class Talk:
    """대화가 이어지는 동안을 기억한다.

    한 번 부르고 여러 마디 이어 말하는 게 사람의 방식이다. 답한 직후 잠깐은 호출어
    없이 받고, 그 시간이 지나면 다시 불러야 한다 — 계속 열어 두면 옆 사람 말이나
    영상 소리에 반응한다.
    """

    def __init__(self, window_sec: float = FOLLOWUP_SEC) -> None:
        self.window_sec = window_sec
        self.open_until = 0.0

    @property
    def listening(self) -> bool:
        return time.monotonic() < self.open_until

    def opened(self) -> None:
        """이비가 답했다. 이어 말할 시간을 연다."""
        self.open_until = time.monotonic() + self.window_sec

    def closed(self) -> None:
        self.open_until = 0.0

    # 이어 말하기로 받을 수 있는 길이. 이보다 길면 사람이 이비에게 하는 말이 아니라
    # 옆에서 나는 소리다 — 실측에서 영상 소리가 통째로 들어왔다.
    MAX_FOLLOWUP_WORDS = 6

    def take(self, heard: str) -> tuple[bool, str]:
        """이 말을 받을지 정한다.

        호출어가 있으면 언제나 받는다. 없으면 **열려 있고 짧을 때만** 받는다 —
        열어 두는 동안 TV·영상 소리가 그대로 지시가 되면 안 된다.
        """
        woke, order = heard_wake(heard)
        if woke:
            return True, order

        clean = heard.strip()
        if self.listening and clean and len(clean.split()) <= self.MAX_FOLLOWUP_WORDS:
            return True, clean
        return False, ""


# ★ 작업 폴더 기준(`../models/piper`)이면 구운 판에서 못 찾아 윈도 기본 목소리로 조용히 내려앉는다.
PIPER_DIR = paths.models_dir() / "piper"
SPEECH_SPEED = 0.92  # 1보다 작으면 빠르게. 너무 빠르면 알아듣기 힘들다


class Mouth:
    """말한다. 신경망 목소리가 있으면 그걸 쓰고, 없으면 OS 목소리로 떨어진다.

    OS 목소리(윈도우 SAPI)는 어디서나 되지만 기계 소리가 난다. Piper 모델을
    `models/piper/`에 두면 훨씬 사람 같고 **더 빠르다**(실시간의 7배로 합성).
    """

    # 입은 하나다 — 스피커가 하나니까. 화면과 마이크 실이 각자 Mouth를 만들어도
    # "지금 말하는 중"은 같이 봐야 한다. 안 그러면 한쪽이 말할 때 다른 쪽이 받아쓴다.
    speaking = threading.Event()
    # 스피커도 하나다. 두 군데서 동시에 말하면 소리가 겹쳐 둘 다 못 알아듣는다.
    _mouth_lock = threading.Lock()
    _piper: Any = None  # 모델은 한 번만 올린다(결정 27 상주 제어와 같은 이유)

    def __init__(self, lang: str = "ko", piper_dir: str | Path = PIPER_DIR,
                 model_name: str = "") -> None:
        self.lang = lang
        self.piper_dir = Path(piper_dir)
        self.model_name = model_name  # 비우면 폴더의 첫 번째(결정 42)
        self._voice = None if self._load_piper() else self._make_voice()

    def _load_piper(self) -> bool:
        if Mouth._piper is not None:
            return True
        models = sorted(self.piper_dir.glob("*.onnx")) if self.piper_dir.is_dir() else []
        if self.model_name:
            # 고른 게 사라졌으면 조용히 첫 번째로 되돌아간다 — 그것 때문에 벙어리가 되면 안 된다.
            models = [m for m in models if m.stem == self.model_name] or models
        if not models:
            return False
        try:
            from piper import PiperVoice

            Mouth._piper = PiperVoice.load(str(models[0]))
            return True
        except Exception:
            return False  # 모델이 깨졌어도 말은 해야 한다 — OS 목소리로 내려간다

    def _make_voice(self) -> Any:
        if platform.system() != "Windows":
            return None  # 맥·리눅스는 `say`/`spd-say`로 떨어진다
        try:
            import win32com.client

            voice = win32com.client.Dispatch("SAPI.SpVoice")
            for v in voice.GetVoices():
                if self.lang in v.GetAttribute("Language").lower() or "ko" in v.GetDescription().lower():
                    voice.Voice = v
                    break
                # 언어 속성이 코드로 오는 경우가 있어 설명으로도 본다
                if "korean" in v.GetDescription().lower() or "heami" in v.GetDescription().lower():
                    voice.Voice = v
                    break
            return voice
        except Exception:
            return None

    @property
    def available(self) -> bool:
        return (Mouth._piper is not None or self._voice is not None
                or platform.system() == "Darwin")

    @property
    def kind(self) -> str:
        if Mouth._piper is not None:
            return "piper"
        return "sapi" if self._voice is not None else "os"

    def say(self, text: str) -> None:
        """말한다. 말하는 동안 귀는 닫힌다 — 자기 목소리를 받아쓰면 안 된다."""
        if not text.strip():
            return
        # 앞말이 끝날 때까지 기다린다. 겹쳐 내보내면 둘 다 못 알아듣는다.
        with Mouth._mouth_lock:
            self.speaking.set()
            try:
                if Mouth._piper is not None:
                    self._say_piper(text)
                elif self._voice is not None:
                    self._voice.Speak(text)
                elif platform.system() == "Darwin":
                    subprocess.run(["say", text], check=False)
            finally:
                self.speaking.clear()

    def _say_piper(self, text: str) -> None:
        import numpy as np
        import sounddevice as sd

        from piper import SynthesisConfig

        chunks = Mouth._piper.synthesize(
            text, SynthesisConfig(length_scale=SPEECH_SPEED))
        audio = np.concatenate([
            np.frombuffer(c.audio_int16_bytes, dtype=np.int16) for c in chunks])
        rate = Mouth._piper.config.sample_rate
        sd.play(audio, rate)
        sd.wait()  # 끝날 때까지 붙잡는다 — 안 그러면 귀가 자기 목소리를 듣는다

    def to_wav(self, text: str, path: str | Path) -> Path | None:
        """말을 파일로 뽑는다. 마이크 없이 귀를 검사할 때 쓴다."""
        if Mouth._piper is not None:
            import wave

            with wave.open(str(path), "wb") as w:
                Mouth._piper.synthesize_wav(text, w)
            return Path(path)
        if self._voice is None:
            return None
        import win32com.client

        stream = win32com.client.Dispatch("SAPI.SpFileStream")
        stream.Open(str(path), 3)  # 3 = 새로 만들어 쓰기
        old = self._voice.AudioOutputStream
        try:
            self._voice.AudioOutputStream = stream
            self._voice.Speak(text)
        finally:
            self._voice.AudioOutputStream = old
            stream.Close()
        return Path(path)


TARGET_RMS = 0.06  # 받아쓰기가 편하게 듣는 크기

# Whisper는 유튜브 자막으로 학습돼서 **소리가 거의 없는 구간을 주면 상투구를 지어낸다**
# ("시청해 주셔서 감사합니다"). 주변에 아무 소리가 없어도 나온다 — 실측에서 나왔다.
# 지어낸 말은 점수가 유독 나쁘다: 멀쩡한 말 -0.38~-0.90, 지어낸 말 -1.46.
MAX_VOCAB = 5  # 받아쓰기에 일러줄 낱말 수 상한. 넘기면 오염이 이득을 넘는다
MIN_LOGPROB = -1.10
MAX_NO_SPEECH = 0.60

# 점수를 빠져나오는 것들. 학습 데이터에 워낙 많아 확신 있게 지어낸다.
JUNK = ("시청해 주셔", "구독과 좋아요", "구독 부탁", "감사합니다 다음 영상",
        "오늘도 시청", "영상 봐주셔서")


# 실제 기록에서 되풀이된 오인식. 소리가 비슷해 모델이 늘 같은 데서 미끄러진다 —
# 모델을 바꾸는 것보다 여기 한 줄 적는 게 싸다. 새로 관찰되면 계속 늘린다.
MISHEARD = {
    "최대치": ("채넷치", "채널치", "채넷찌", "체제지", "최세찌", "채소집", "최새치"),
    "줄여": ("죽여", "주려", "쭐여", "줄어"),
    "볼륨": ("울렴", "울림", "룰륨", "위리엠", "릴리엠", "불륨"),
    "음소거": ("음소가", "옴소가", "음소기"),
}


def fix_misheard(text: str) -> str:
    """되풀이되는 오인식을 제자리로 돌린다. 뜻이 바뀌는 낱말만 손댄다."""
    for right, wrongs in MISHEARD.items():
        for wrong in wrongs:
            if wrong in text:
                text = text.replace(wrong, right)
    return text


def _clean(segments: Any) -> str:
    """지어낸 말을 걸러낸다. 조용할 때 이비가 혼자 반응하는 걸 여기서 막는다."""
    kept = []
    for s in segments:
        text = s.text.strip()
        if not text:
            continue
        if getattr(s, "no_speech_prob", 0.0) > MAX_NO_SPEECH:
            continue
        if getattr(s, "avg_logprob", 0.0) < MIN_LOGPROB:
            continue
        if any(j in text for j in JUNK):
            continue
        kept.append(text)
    return fix_misheard(" ".join(kept).strip())


def _normalize(audio: Any) -> Any:
    """소리를 적당한 크기로 키운다.

    마이크 감도가 낮으면 받아쓰기가 눈에 띄게 흔들린다 — 같은 말도 작게 녹음되면
    엉뚱하게 받아쓴다. 파일 경로가 오면 손대지 않는다.
    """
    try:
        import numpy as np
    except ImportError:
        return audio
    if not isinstance(audio, np.ndarray) or audio.size == 0:
        return audio

    audio = audio.astype(np.float32)
    rms = float(np.sqrt(np.mean(audio ** 2)))
    if rms < 1e-6:
        return audio

    # 실측: 이 PC 마이크는 최대치 0.03 수준으로 들어온다(정상은 0.3~0.7). 20배로는
    # 모자라서 "볼륨"이 "울렴"으로 흘렸다. 다만 키울수록 잡음도 같이 커지므로,
    # **가장 큰 소리가 꽉 차는 선**까지만 키운다 — 그 위로는 잘리기만 한다.
    peak = float(np.abs(audio).max())
    gain = min(TARGET_RMS / rms, (0.85 / peak) if peak > 1e-6 else 1.0, 60.0)
    return np.clip(audio * gain, -1.0, 1.0).astype(np.float32)


class Ears:
    """마이크에서 말 한 덩어리를 떼어내 글자로 바꾼다.

    받아쓰기 모델은 한 번 올리고 계속 쓴다 — 엔진과 같은 이유다(결정 27 상주 제어).
    """

    def __init__(self, model_size: str = "", device: str = "") -> None:
        self.model_size = model_size
        self.device = device
        self._model: Any = None
        self.spoke_at = 0.0  # 말이 끝난 순간. 체감 지연을 여기서 잰다
        self.last_audio: Any = None  # 방금 들은 원본. 기록에 남겨 되돌려 본다
        self.last_peak = 0.0
        self.clipped = False

    def _load(self) -> Any:
        """GPU가 되면 큰 모델을 쓴다. 안 되면 작은 모델로 내려간다.

        base는 빠르지만 호출어를 흘려 놓친다. small은 정확한데
        CPU에서 2.5초라 대화가 안 된다. **GPU면 둘 다 된다** — 그래서 장치를 먼저 보고
        모델 크기를 정한다.
        """
        if self._model is not None:
            return self._model
        from faster_whisper import WhisperModel

        # 사용자가 고른 크기가 있으면 GPU·CPU 어느 쪽이든 그걸 쓴다(결정 42).
        # 없으면 사양을 보고 고른다 — 되면 정확한 쪽, 안 되면 빠른 쪽.
        wanted = [(self.device, self.model_size)] if self.device else (
            [("cuda", self.model_size), ("cpu", self.model_size)] if self.model_size
            else [("cuda", "small"), ("cpu", "base")]
        )
        errors = []
        for device, size in wanted:
            try:
                if device == "cuda":
                    _add_cuda_dlls()
                self._model = WhisperModel(size, device=device, compute_type="int8")
                self.device, self.model_size = device, size
                return self._model
            except Exception as e:
                errors.append(f"{device}/{size}: {e}")
        raise RuntimeError("받아쓰기 모델을 못 올렸다 — " + " / ".join(errors))

    def transcribe(self, audio: Any, vocabulary: list[str] | None = None) -> str:
        """소리 → 글자. 파일 경로도 되고 numpy 배열(16kHz mono float32)도 된다.

        **아는 낱말을 미리 일러준다.** 호출어는 짧아서 그냥 두면 엉뚱하게 들린다
        (결정 11 파생 논점). 모듈 이름도 같이 넣으면 지시어 인식이 같이 좋아진다.
        """
        audio = _normalize(audio)
        # 어휘는 조금만 준다. 실측: 5개면 오인식이 8/10 → 9/10으로 줄지만, 22개를 주면
        # **조용할 때 지어낸 말까지 확신해서** 없는 지시를 만들어낸다("위험, 음소거").
        # 힌트는 도움이자 오염원이다.
        words = [*WAKE_WORDS, *(vocabulary or [])[:MAX_VOCAB]]
        segments, info = self._load().transcribe(
            str(audio) if isinstance(audio, (str, Path)) else audio,
            language="ko",
            # 앞뒤 침묵은 마이크에서 이미 잘라 왔다. VAD를 또 돌리면 모델을 하나 더
            # 올려 시간만 먹는다.
            vad_filter=False,
            # 지시는 한 문장이라 여러 후보를 견줄 값어치가 없다. 빔 5 → 1이 체감을 가른다.
            beam_size=1,
            # 앞 문장을 물고 가면 엉뚱한 말이 이어져 나온다. 지시는 매번 독립이다.
            condition_on_previous_text=False,
            initial_prompt=", ".join(dict.fromkeys(words)),
        )
        return _clean(segments)

    # --- 마이크 -----------------------------------------------------------

    def listen(self, mouth: Mouth | None = None,
               on_level: Callable[[float], None] | None = None,
               vocabulary: list[str] | None = None) -> str:
        """말이 시작될 때까지 기다렸다가, 조용해지면 잘라서 받아쓴다.

        고정 길이로 자르면 문장이 중간에서 끊긴다. 사람은 문장 길이를 안 맞춰 준다.
        """
        import numpy as np
        import sounddevice as sd

        chunk = int(SAMPLE_RATE * 0.05)
        frames: list[Any] = []
        started = False
        quiet_for = 0.0
        began = time.monotonic()
        # 지금 이 방의 소음을 재서 문턱을 거기에 맞춘다. 고정값은 마이크 볼륨을 한 번
        # 만지면 바로 틀어진다 — 실측에서 값을 올리자 소음이 문턱을 넘어 "말이 끝났다"를
        # 못 알아채고 한 마디를 10초씩 녹음했다.
        floor: list[float] = []
        gate = START_LEVEL

        with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                            blocksize=chunk) as stream:
            while True:
                block, _ = stream.read(chunk)
                if mouth is not None and mouth.speaking.is_set():
                    frames.clear()  # 이비가 말하는 동안 들어온 소리는 버린다
                    started = False
                    continue

                level = float(np.sqrt(np.mean(block ** 2)))
                if on_level is not None:
                    on_level(level)

                if not started:
                    # 말이 시작되기 전 소리는 전부 소음이다. 그걸로 문턱을 잡는다.
                    floor.append(level)
                    del floor[:-40]  # 최근 2초만 본다
                    if len(floor) >= 10:
                        quiet = sorted(floor)[len(floor) // 2]  # 중앙값 — 튀는 값에 안 흔들린다
                        gate = max(START_LEVEL, quiet * 3.0)

                if level >= gate:
                    started = True
                    quiet_for = 0.0
                elif started:
                    quiet_for += 0.05

                if started:
                    frames.append(block.copy())
                    if quiet_for >= SILENCE_SEC:
                        break
                    if time.monotonic() - began > MAX_UTTERANCE_SEC:
                        break
                elif time.monotonic() - began > MAX_UTTERANCE_SEC * 2:
                    return ""  # 아무도 말을 안 했다

        if not frames:
            return ""
        # 말이 끝난 순간을 남긴다. 여기서부터 답이 나올 때까지가 사용자가 느끼는 지연이다
        # — 말을 시작할 때까지 기다린 시간을 같이 재면 6초처럼 보여 엉뚱한 데를 고치게 된다.
        self.spoke_at = time.monotonic()
        self.last_audio = np.concatenate(frames).flatten()
        # 잘렸는지 남긴다. 소리가 너무 크면 일그러져서 아무리 좋은 모델도 못 알아듣는다.
        self.last_peak = float(np.abs(self.last_audio).max())
        self.clipped = self.last_peak >= 0.99
        return self.transcribe(self.last_audio, vocabulary)


def _self_check() -> None:
    # 목소리 모델 자리는 작업 폴더를 따르면 안 된다 — 구운 판에서 못 찾아 기본 목소리로 내려앉는다
    assert PIPER_DIR.is_absolute(), f"목소리 모델 자리가 작업 폴더 기준이다: {PIPER_DIR}"
    # --- 호출어 판정: 마이크 없이 검사할 수 있는 부분 ---
    # 이름 둘 다 받는다.
    assert heard_wake("불칸 볼륨 올려") == (True, "볼륨 올려")
    assert heard_wake("불칸, 이거 뭐야") == (True, "이거 뭐야")
    assert heard_wake("불 칸 볼륨 올려")[0] is True  # 받아쓰기가 띄어 쓴 경우
    assert heard_wake("불칸아 불 꺼") == (True, "불 꺼")
    assert heard_wake("불칸") == (True, "")  # 부르기만 함 → 대기
    assert heard_wake("브이씨 이거 뭐야") == (True, "이거 뭐야")
    assert heard_wake("브이씨") == (True, "")
    assert heard_wake("") == (False, "")

    # **로마자로 받아쓰인다** — 실제 왕복 측정에서 나온 꼴들(2026-08-27).
    # 한글 꼴만 적어 뒀으면 "브이씨"는 한 번도 안 걸렸다.
    assert heard_wake("VC 볼륨 올려줘") == (True, "볼륨 올려줘")
    assert heard_wake("vc 도와줘") == (True, "도와줘")       # 대소문자 안 가린다
    assert heard_wake("VCR 오늘 일정 알려줘") == (True, "오늘 일정 알려줘")
    # 긴 꼴을 먼저 맞혀야 한다. "VC"부터 맞히면 "R 오늘…"이 지시가 된다.
    assert heard_wake("VCR 불 꺼")[1] == "불 꺼"

    # `PC`는 **그것만 말했을 때**에만 호출이다. 흔한 낱말이라 뒤에 말이 붙으면 안 된다.
    assert heard_wake("PC") == (True, "")
    assert heard_wake("피씨") == (True, "")
    for common in ("PC 켜줘", "PC 느려", "피씨방 가자"):
        assert heard_wake(common)[0] is False, common

    # 호출어처럼 들리지만 아닌 말 — 이게 없으면 뉴스만 틀어도 깨어난다.
    for wrong in ("발칸반도 어디야", "발칸포 사거리", "브이로그 보여줘", "비씨카드 결제"):
        assert heard_wake(wrong)[0] is False, wrong

    # 말머리만 본다. 어디에 있든 막으면 멀쩡한 부름까지 죽는다.
    assert heard_wake("브이씨 브이로그 만들어줘") == (True, "브이로그 만들어줘")

    # 부름이 겹쳐 들어오는 일이 실제로 있다 — 받아쓰기가 앞 소리를 흘려 넣는다.
    # 하나만 떼면 남은 호출어가 지시의 첫 낱말이 된다.
    assert heard_wake("브이씨, 불칸 오늘 일정 알려줘") == (True, "오늘 일정 알려줘")
    assert heard_wake("불칸 브이씨 볼륨 올려") == (True, "볼륨 올려")

    # 불을 켜라는 말이 호출로 먹히면 안 된다 — 호출어와 소리가 가장 가까운 지시어다.
    for order in ("불 켜", "불 꺼", "불 켜줘", "거실 불 꺼"):
        assert heard_wake(order)[0] is False, order

    # 소리가 작으면 키워서 넣는다 — 조용한 마이크에서 받아쓰기가 흔들린다.
    try:
        import numpy as np

        quiet = (np.sin(np.linspace(0, 300, 8000)) * 0.002).astype(np.float32)
        loud = _normalize(quiet)
        assert float(np.sqrt(np.mean(loud ** 2))) > float(np.sqrt(np.mean(quiet ** 2))) * 5
        assert abs(loud).max() <= 1.0, "키우다가 잘렸다"
        assert _normalize(np.zeros(10, dtype=np.float32)).max() == 0  # 무음은 그대로
    except ImportError:
        pass

    # 답한 직후엔 호출어 없이 이어 말할 수 있다 — 매번 부르게 하면 대화가 아니다.
    talk = Talk(window_sec=0.3)
    assert talk.take("최대치까지 올려") == (False, ""), "안 열렸는데 받았다"
    assert talk.take("불칸 볼륨 올려") == (True, "볼륨 올려")
    talk.opened()
    assert talk.take("최대치까지 올려") == (True, "최대치까지 올려"), "이어 말하기가 안 된다"
    # 열려 있어도 긴 말은 안 받는다 — 실측에서 영상 소리가 통째로 들어왔다.
    long_talk = "여러분 안녕하세요 오늘은 영상으로 다시 만나요 시청해 주셔서 감사합니다"
    assert talk.take(long_talk) == (False, ""), "영상 소리를 지시로 받았다"
    assert talk.take("불칸 소리 줄여") == (True, "소리 줄여")  # 열려 있어도 호출어는 벗긴다
    time.sleep(0.35)
    assert talk.take("최대치까지 올려") == (False, ""), "시간이 지나도 계속 열려 있다"
    talk.opened(); talk.closed()
    assert talk.take("아무 말") == (False, ""), "닫았는데 열려 있다"

    # 되풀이되는 오인식은 표로 돌린다 — 실제 기록에서 뽑았다.
    assert fix_misheard("볼륨 채넷치까지 올려") == "볼륨 최대치까지 올려"
    assert fix_misheard("울렴 죽여줘") == "볼륨 줄여줘"
    assert fix_misheard("옴소가") == "음소거"
    assert fix_misheard("볼륨 최대치까지 올려") == "볼륨 최대치까지 올려"  # 멀쩡한 건 그대로

    # 문턱은 그때그때 소음에 맞춰야 한다. 마이크 볼륨을 한 번 만지면 고정값은 틀어진다.
    def gate_for(noise_levels, base=0.012):
        floor = sorted(noise_levels)[len(noise_levels) // 2]
        return max(base, floor * 3.0)

    assert gate_for([0.001] * 20) == 0.012, "조용한 방에서는 기본값을 쓴다"
    assert abs(gate_for([0.02] * 20) - 0.06) < 1e-9, "시끄러우면 문턱을 올린다"
    # 튀는 소리 하나에 흔들리지 않는다 — 중앙값이라서.
    assert gate_for([0.001] * 19 + [0.9]) == 0.012

    mouth = Mouth()
    print(f"입 준비됨: {mouth.available} ({mouth.kind})")
    if not mouth.available:
        print("voice self-check 통과 (목소리 없음 — 호출어 판정만 확인)")
        return

    # --- 입 → 귀 왕복: 마이크 없이 전 경로를 확인한다 ---
    #
    # 같은 소리를 네 번씩 넣어 재봤다(2026-08-27, 로컬 받아쓰기):
    #   브이씨 4/4  ·  불칸 2/4 → 관찰된 꼴을 태운 뒤 3/4
    #
    # 그래서 **브이씨만 막는다.** 불칸은 재서 보여만 준다 — 4번에 1번 흘리는 것으로
    # 검사를 막으면, 우리 코드가 멀쩡한 날에도 빌드가 빨갛게 된다. 흘리는 사실을
    # 숨기는 게 아니라 화면에 찍어 둔다.
    #
    # 낱말이 그대로 살아 오기도 요구하지 않는다. 같은 문장이 "일정"→"일참"→"일전"으로
    # 흔들려서, 그걸로 막으면 우리 코드가 아니라 모델의 그날 컨디션을 검사하게 된다.
    with tempfile.TemporaryDirectory() as tmp:
        ears = Ears()
        for name, must in (("브이씨", True), ("불칸", False)):
            wav = Path(tmp) / f"{name}.wav"
            said = f"{name} 오늘 일정 알려줘"
            if mouth.to_wav(said, wav) is None or not wav.exists():
                print("voice self-check 통과 (파일 출력 불가 — 호출어 판정만 확인)")
                return
            assert wav.stat().st_size > 1000, "소리가 안 담겼다"

            t = time.time()
            heard = ears.transcribe(wav)
            took = time.time() - t
            woke, order = heard_wake(heard)
            like = difflib.SequenceMatcher(
                None, "오늘 일정 알려줘", order.strip(" .!?~")).ratio()
            print(f"  {said!r} → {heard!r}  ({took:.1f}s)")
            print(f"    깨움={woke}  지시={order!r}  닮음={like:.2f}")

            assert heard, "받아쓰기가 빈 문자열이다"
            if must:
                assert woke, f"'{name}'을 불렀는데 못 알아들었다: {heard}"
                assert order, f"호출어만 떼고 나니 지시가 없다: {heard}"
            elif not woke:
                print(f"    (참고: '{name}'이 이번엔 흘렀다 — 측정치 3/4)")

    print("voice self-check 통과")


if __name__ == "__main__":
    _self_check()
