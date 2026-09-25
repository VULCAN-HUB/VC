"""VC가 부리는 부품들(결정 10).

여기 있는 건 경로가 흐르는지 보려고 얹은 껍데기다 — 실제 구현은 각자 붙는다.
첫 진짜 부품은 제품 검색이다(결정 26).

모듈은 선언만 채우면 오케스트레이터가 알아서 부른다. 폰·PC·원격이 같은 목록을 쓴다.
"""

from __future__ import annotations

import paths

import platform
from typing import Any

import product_search
from orchestrator import Instruction, ModuleFailed, ModuleSpec


def build_modules(backend: Any = None, model: str = "") -> list[ModuleSpec]:
    """백엔드를 넘기면 제품 검색이 실제로 돈다. 없으면 단계마다 실패하고 그대로 보고된다."""

    def volume(inst: Instruction) -> str:
        """진짜로 소리를 바꾼다. 윈도우 미디어 키를 그대로 두드린다.

        시스템 볼륨 API(IAudioEndpointVolume)는 COM 래퍼가 필요한데, 미디어 키는
        ctypes 몇 줄이면 되고 사용자가 키보드로 하는 것과 완전히 같은 동작이다.
        """
        # 받아쓰기가 끝음절을 자주 흘린다("음소거" → "음소가"). 앞부분만 본다.
        text = inst.text
        # "끝까지"·"최대치"는 한 번에 끝까지 가라는 말이다. 몇 칸씩 올리면 다시 시켜야 한다.
        # 실제 기록에서 "최고로 키워"가 한 칸씩만 올라갔다. 사람이 쓰는 말을 다 적는다.
        full = any(w in text for w in ("최대", "최고", "끝까지", "맥스", "최소",
                                       "제일", "완전", "풀로"))
        if any(w in text for w in ("음소", "무음", "뮤트", "소리 꺼", "소리 끄", "조용")):
            key, step, word = 0xAD, 1, "음소거했어"
        # 받아쓰기가 "줄여"를 "죽여·주려·쭐여"로 흘린다. 실제 기록에서 나온 것들이다 —
        # 못 알아들으면 반대로 올려버려서 제일 나쁘다.
        elif any(w in text for w in ("줄", "죽여", "주려", "쭐", "낮", "작게", "다운",
                                     "내려", "내리", "최소")):
            key, step, word = 0xAE, 50 if full else 4, "볼륨 줄였어"
        else:
            key, step, word = 0xAF, 50 if full else 4, "볼륨 올렸어"
        if full:
            word = word.replace("볼륨 ", "볼륨 끝까지 ")

        if platform.system() == "Darwin":
            # 맥에는 미디어 키를 두드릴 길이 없다(보내려면 접근성 권한이 있어야 한다).
            # `osascript` 의 `set volume` 은 권한 없이 바로 되고 0~100 을 쓴다.
            # 윈도우 미디어 키 한 번이 2% 라, 같은 체감이 되게 `step` 에 2를 곱한다.
            import subprocess

            간격 = step * 2
            if key == 0xAD:
                문 = "set volume output muted true"
            elif key == 0xAE:
                문 = ("set volume output volume 0" if full else
                      f"set volume output volume (output volume of (get volume settings)) - {간격}")
            else:
                문 = ("set volume output volume 100" if full else
                      f"set volume output volume (output volume of (get volume settings)) + {간격}")
            난것 = subprocess.run(["osascript", "-e", 문], capture_output=True, text=True, **paths.창안띄우기())
            if 난것.returncode != 0:
                raise ModuleFailed("volume", f"소리를 못 바꿨다: {난것.stderr.strip()[:120]}")
            return word

        if platform.system() != "Windows":
            raise ModuleFailed("platform", "이 OS에서는 아직 소리를 못 바꾼다")
        import ctypes

        user32 = ctypes.windll.user32
        for _ in range(step):  # 한 번은 2%라 체감이 없다. 몇 번 눌러 준다
            user32.keybd_event(key, 0, 0, 0)
            user32.keybd_event(key, 0, 2, 0)  # 2 = 키를 뗀다. 안 떼면 눌린 채로 남는다
        return word

    def navigate(inst: Instruction) -> str:
        return "[경로 안내] 배경에서 계속 돈다"

    # 트리거는 넉넉해야 한다. 규칙에서 하나만 걸리면 그대로 실행되지만, 하나도 안 걸리면
    # 1단 모델이 전체 후보를 견주다가 엉뚱한 데로 샌다 — 실제로 "볼륨 줄여줘"가
    # 제품 검색으로 갔다. 사람이 실제로 쓰는 말을 다 적는 게 제일 싸게 막는 방법이다.
    return [
        product_search.build(backend, model),
        ModuleSpec("volume",
                   # 실제 기록에서 "끝까지 올려"가 되묻기로 샜다. 사람은 목적어를 빼고
                   # 말한다 — 동사만으로도 걸리게 둔다.
                   ["볼륨", "소리", "음량", "크게", "작게", "키워", "줄여", "낮춰", "높여",
                    "올려", "내려", "올려줘", "내려줘", "최대치", "최대로", "최소",
                    "조용", "무음", "뮤트", "음소거"],
                   volume),
        ModuleSpec("navigate",
                   ["경로", "안내", "가는 길", "길 찾", "어떻게 가", "데려다"],
                   navigate, persistent=True, can_interrupt=True, render="overlay"),
    ]


if __name__ == "__main__":
    mods = build_modules()
    assert {m.name for m in mods} == {"제품 검색", "volume", "navigate"}
    assert all(m.triggers and callable(m.run) for m in mods)

    # 백엔드가 없어도 목록은 만들어진다 — VC가 뜨는 걸 모델 유무가 막으면 안 된다.
    inst = Instruction(text="이거 뭐야", context={"image": b"\xff\xd8\xff"})
    inst.tier = "pc"
    try:
        next(m for m in mods if m.name == "제품 검색").run(inst)
    except Exception as e:
        assert "모델이 없다" in str(e), e
    else:
        raise AssertionError("백엔드 없이 답했다")

    # 말에 따라 다르게 답해야 한다. 뭘 시켜도 "올렸어"면 거짓말이다.
    vol = next(m for m in mods if m.name == "volume")
    for text, want in [("볼륨 줄여줘", "줄였어"), ("소리 키워", "올렸어"),
                       ("음소거", "음소거"), ("조용히 해줘", "음소거"),
                       ("음소가", "음소거"), ("뮤트해줘", "음소거"),
                       ("볼륨 죽여줘", "줄였어"), ("볼륨 30까지 죽여줘", "줄였어"),
                       ("볼륨 주려", "줄였어"), ("볼륨 최고로 키워", "끝까지 올렸어"),
                       ("풀로 올려", "끝까지 올렸어")]:
        got = vol.run(Instruction(text=text))
        assert want in got, f"{text!r} -> {got!r}"

    print("modules self-check 통과")
