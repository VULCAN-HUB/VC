"""마이크 점검 — 안 들릴 때 어디가 막혔는지 본다.

    python -X utf8 mic_check.py

소리 크기를 실시간으로 보여주고, 말이 끝나면 받아쓴 결과를 찍는다.
어느 단계에서 막히는지 눈으로 갈린다:

    막대가 안 움직임        마이크가 안 잡히거나 음소거. 장치 문제
    막대는 움직이나 안 잘림  시작 문턱(START_LEVEL)이 높다
    잘리는데 글자가 빔      받아쓰기 문제(모델·언어)
    글자는 나오나 안 깨어남  호출어 인식 문제
"""

from __future__ import annotations

import sys
import time

import voice


def main() -> int:
    import numpy as np
    import sounddevice as sd

    print("입력 장치:")
    default_in = sd.default.device[0]
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0:
            mark = " <- 기본" if i == default_in else ""
            print(f"  [{i}] {d['name']}{mark}")

    print(f"\n시작 문턱 {voice.START_LEVEL} / 침묵 {voice.SILENCE_SEC}초")
    print("받아쓰기 모델을 올리는 중… (처음 한 번만 오래 걸린다)")
    ears = voice.Ears()
    t = time.time()
    ears._load()
    print(f"준비됨 ({time.time() - t:.1f}s)\n")
    print('말해봐. 예: "VC 볼륨 올려"   (Ctrl+C로 끝)\n')

    peak = 0.0
    while True:
        # 말이 시작될 때까지 막대를 그린다 — 마이크가 살아 있는지 눈으로 보게.
        got = _listen_verbose(ears, sd, np)
        if got is None:
            continue
        heard, level = got
        peak = max(peak, level)
        woke, order = voice.heard_wake(heard)
        print(f"\r  들음: {heard!r}")
        print(f"  최대 크기 {level:.3f} (문턱 {voice.START_LEVEL})")
        print(f"  호출어 {'들림' if woke else '안 들림'} / 지시 {order!r}\n")


def _listen_verbose(ears, sd, np):
    chunk = int(voice.SAMPLE_RATE * 0.05)
    frames, started, quiet, loudest = [], False, 0.0, 0.0
    with sd.InputStream(samplerate=voice.SAMPLE_RATE, channels=1, dtype="float32",
                        blocksize=chunk) as stream:
        while True:
            block, _ = stream.read(chunk)
            level = float(np.sqrt(np.mean(block ** 2)))
            loudest = max(loudest, level)

            bar = "#" * min(int(level * 400), 40)
            flag = "  <말>" if level >= voice.START_LEVEL else ""
            print(f"\r  {level:.4f} |{bar:<40}|{flag}   ", end="", flush=True)

            if level >= voice.START_LEVEL:
                started, quiet = True, 0.0
            elif started:
                quiet += 0.05

            if started:
                frames.append(block.copy())
                if quiet >= voice.SILENCE_SEC:
                    break
                if len(frames) * 0.05 > voice.MAX_UTTERANCE_SEC:
                    break

    if not frames:
        return None
    print("\r  받아쓰는 중…" + " " * 50, end="", flush=True)
    return ears.transcribe(np.concatenate(frames).flatten()), loudest


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n끝")
