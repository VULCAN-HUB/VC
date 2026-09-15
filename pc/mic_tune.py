"""마이크 문턱값 맞추기 — 네 마이크에서 실제로 재서 저장한다.

    python -X utf8 mic_tune.py            # 재기만 한다
    python -X utf8 mic_tune.py --apply    # 재고 mic.json에 저장한다

기본값(0.012)은 어느 마이크에서든 반드시 틀린다. 감도가 낮으면 말해도 안 잡히고,
높으면 가만있어도 혼자 깨어난다. **재는 게 유일한 답이다.**

두 번 잰다:

    조용할 때   주변 소음 바닥. 이보다는 확실히 위여야 한다
    말할 때     실제 목소리 크기. 이보다는 확실히 아래여야 한다

두 값 사이에 문턱을 놓는다. 사이가 너무 좁으면 마이크를 키우거나 조용한 데로 가야 한다.
"""

from __future__ import annotations

import paths
import json
import statistics
import sys
import time
from pathlib import Path

import voice

QUIET_SEC = 3.0
SPEAK_ROUNDS = 3
TUNING_PATH = paths.기계자리("mic.json")


def _levels(seconds: float, label: str) -> list[float]:
    """소리 크기를 재면서 막대로 보여준다. 눈으로 보여야 마이크가 사는지 안다."""
    import numpy as np
    import sounddevice as sd

    chunk = int(voice.SAMPLE_RATE * 0.05)
    out: list[float] = []
    with sd.InputStream(samplerate=voice.SAMPLE_RATE, channels=1, dtype="float32",
                        blocksize=chunk) as stream:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            block, _ = stream.read(chunk)
            level = float(np.sqrt(np.mean(block ** 2)))
            out.append(level)
            bar = "#" * min(int(level * 400), 44)
            left = end - time.monotonic()
            print(f"\r  {label} {left:3.0f}s  {level:.4f} |{bar:<44}|", end="", flush=True)
    print()
    return out


def measure() -> dict[str, float]:
    import sounddevice as sd

    device = sd.query_devices(sd.default.device[0])
    print(f"마이크: {device['name']}\n")

    print(f"[1/2] {QUIET_SEC:.0f}초간 아무 말도 하지 마. 주변 소음을 잰다.")
    input("      준비되면 엔터: ")
    quiet = _levels(QUIET_SEC, "조용")
    floor = statistics.median(quiet)
    noise_peak = max(quiet)
    print(f"      소음 바닥 {floor:.4f} / 순간 최대 {noise_peak:.4f}\n")

    print(f"[2/2] 'VC 볼륨 줄여줘' 를 {SPEAK_ROUNDS}번 말해. 평소 목소리로.")
    peaks: list[float] = []
    for i in range(SPEAK_ROUNDS):
        input(f"      {i + 1}번째, 엔터 치고 말해: ")
        said = _levels(3.0, "말")
        peaks.append(max(said))
        print(f"      최대 {peaks[-1]:.4f}")
    speech = statistics.median(peaks)
    print()

    # 소음보다 넉넉히 위, 목소리보다 확실히 아래. 둘의 기하평균이 가운데를 잡는다.
    start = (max(noise_peak, 0.0005) * speech) ** 0.5
    start = min(max(start, noise_peak * 1.5), speech * 0.35)
    return {"floor": floor, "noise_peak": noise_peak, "speech": speech,
            "start_level": round(start, 4)}


def main(argv: list[str]) -> int:
    m = measure()
    gap = m["speech"] / max(m["noise_peak"], 1e-6)

    print("=" * 52)
    print(f"  소음 최대   {m['noise_peak']:.4f}")
    print(f"  목소리      {m['speech']:.4f}")
    print(f"  차이        {gap:.1f}배")
    print(f"  추천 문턱   {m['start_level']:.4f}   (지금 {voice.START_LEVEL})")
    print("=" * 52)

    if gap < 3:
        # 소음과 목소리가 붙어 있으면 어떤 문턱을 골라도 둘 중 하나는 틀린다.
        print("\n★ 소음과 목소리 차이가 작다. 문턱을 어디 놔도 오작동한다.")
        print("  마이크를 입 가까이 두거나, 입력 볼륨을 올리거나, 조용한 데서 다시 재.")

    if "--apply" not in argv:
        print("\n저장하려면: python -X utf8 mic_tune.py --apply")
        return 0

    TUNING_PATH.write_text(
        json.dumps({"start_level": m["start_level"], "silence_sec": voice.SILENCE_SEC},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{TUNING_PATH}에 저장했다. VC를 다시 띄우면 적용된다.")
    return 0


def _self_check() -> None:
    import tempfile

    # 저장한 값이 있으면 그걸 쓴다 — 없으면 기본값. 마이크 없이 확인할 수 있는 부분이다.
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "mic.json"
        path.write_text(json.dumps({"start_level": 0.031, "silence_sec": 0.7}),
                        encoding="utf-8")
        old_path, old_start, old_sil = voice.MIC_TUNING, voice.START_LEVEL, voice.SILENCE_SEC
        try:
            voice.MIC_TUNING = path
            voice._load_tuning()
            assert voice.START_LEVEL == 0.031 and voice.SILENCE_SEC == 0.7

            # 깨진 파일은 무시하고 살던 값을 지킨다. 튜닝 파일 하나에 VC가 죽으면 안 된다.
            path.write_text("깨진 내용", encoding="utf-8")
            voice._load_tuning()
            assert voice.START_LEVEL == 0.031

            voice.MIC_TUNING = Path(tmp) / "없는파일.json"
            voice._load_tuning()
            assert voice.START_LEVEL == 0.031
        finally:
            voice.MIC_TUNING, voice.START_LEVEL, voice.SILENCE_SEC = old_path, old_start, old_sil

    print("mic_tune self-check 통과")


if __name__ == "__main__":
    if "--check" in sys.argv:
        _self_check()
    else:
        try:
            raise SystemExit(main(sys.argv[1:]))
        except KeyboardInterrupt:
            print("\n끝")
