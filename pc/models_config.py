"""쓸 모델을 고르는 곳 (결정 42).

**개발용 PC 사양으로 값을 굳히면 안 된다.** 쓰는 사람마다 하드웨어가 다르고, 더 좋은
모델이 나오면 갈아 끼울 수 있어야 한다. 그래서 모델 이름을 코드에 박지 않고 여기 모은다.

역할은 넷이다:

    chat     글자 모델 (GGUF, `models/`)
    vision   사진 보는 모델 (GGUF + mmproj 짝)
    stt      받아쓰기 (faster-whisper 이름: tiny·base·small·medium·large-v3)
    voice    목소리 (Piper ONNX, `models/piper/`)

각 값이 **비어 있으면 자동**이다: 사양을 재서(`engine.detect_hardware`) 등급에 맞는 것을
고른다. 사용자가 고른 값이 있으면 그게 언제나 이긴다 — 자동 추천이 사용자 선택을 덮으면
"내가 고른 게 왜 안 먹지"가 된다.

    {"models": {"chat": "", "vision": "", "stt": "large-v3", "voice": ""}}

새 모델을 쓰려면 파일을 `models/`에 넣고 이름만 여기 적으면 된다. 코드는 안 바뀐다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import engine

ROLES = ("chat", "vision", "stt", "voice")

# 받아쓰기는 파일이 아니라 이름으로 받는다(faster-whisper가 알아서 받아 온다).
# 큰 것부터 적는다 — 사양이 되면 위에서부터 고른다.
STT_CHOICES = ("large-v3", "medium", "small", "base", "tiny")

# 등급별 받아쓰기 기본값. GPU가 없으면 큰 모델은 몇 초씩 걸려 대화가 안 된다(실측 2.53s).
STT_BY_TIER = {"high": "large-v3", "mid": "medium", "low": "small", "cpu": "base"}


def installed(model_dir: str | Path = "../models") -> dict[str, list[str]]:
    """지금 이 PC에 있는 것들. 화면이 이 목록을 보여주고 사용자가 고른다."""
    root = Path(model_dir)
    ggufs = sorted(p for p in root.glob("*.gguf")) if root.is_dir() else []

    chat, vision = [], []
    for p in ggufs:
        if p.stem.endswith(".mmproj"):
            continue  # 모델이 아니라 비전 모델의 짝이다
        (vision if (p.parent / f"{p.stem}.mmproj.gguf").is_file() else chat).append(p.stem)

    piper = root / "piper"
    voices = sorted(p.stem for p in piper.glob("*.onnx")) if piper.is_dir() else []
    return {"chat": chat, "vision": vision, "stt": list(STT_CHOICES), "voice": voices}


def resolve(cfg: dict[str, Any], model_dir: str | Path = "../models") -> dict[str, Any]:
    """설정 + 이 PC 사양 → 실제로 쓸 모델.

    사용자가 고른 값이 최우선. 비어 있을 때만 사양을 보고 고른다.
    가진 게 없으면 빈 문자열 — 그 기능만 조용히 빠지고 나머지는 돈다.
    """
    hw = engine.detect_hardware()
    have = installed(model_dir)
    chosen = dict(cfg.get("models") or {})

    out: dict[str, Any] = {"hardware": hw, "installed": have, "auto": {}, "using": {}}
    for role in ROLES:
        picked = (chosen.get(role) or "").strip()
        if role == "stt":
            auto = STT_BY_TIER.get(hw["tier"], "base")
        else:
            # 비전은 짝이 있는 것 중 첫 번째, 나머지는 그냥 첫 번째.
            auto = have[role][0] if have[role] else ""
        out["auto"][role] = auto

        if picked and (role == "stt" or picked in have[role]):
            out["using"][role] = picked
        else:
            # 고른 게 사라졌으면(파일을 지웠거나 이름이 바뀜) 자동으로 되돌아간다.
            out["using"][role] = auto
    out["gpu_layers"] = engine.ADVICE[hw["tier"]]["gpu_layers"]
    return out


def choose(cfg: dict[str, Any], role: str, name: str,
           model_dir: str | Path = "../models") -> bool:
    """사용자가 골랐다. 설정 dict를 그 자리에서 고친다(저장은 부르는 쪽이 한다)."""
    if role not in ROLES:
        return False
    name = (name or "").strip()
    have = installed(model_dir)
    # 빈 문자열은 "자동으로 되돌린다"는 뜻이라 늘 받는다.
    if name and role != "stt" and name not in have[role]:
        return False
    if name and role == "stt" and name not in STT_CHOICES:
        return False
    cfg.setdefault("models", {})[role] = name
    return True


def _self_check() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "piper").mkdir()
        for f in ("qwen2.5-1.5b.gguf", "qwen2.5-vl-3b.gguf",
                  "qwen2.5-vl-3b.mmproj.gguf", "llama-8b.gguf"):
            (root / f).write_bytes(b"fake")
        (root / "piper" / "ko_KR-kss-medium.onnx").write_bytes(b"fake")

        have = installed(root)
        # 짝(mmproj)이 있는 것만 비전으로 센다. 짝 자체는 목록에 없다.
        assert have["vision"] == ["qwen2.5-vl-3b"], have["vision"]
        assert have["chat"] == ["llama-8b", "qwen2.5-1.5b"], have["chat"]
        assert "qwen2.5-vl-3b.mmproj" not in have["chat"]
        assert have["voice"] == ["ko_KR-kss-medium"]

        # 설정이 비어 있으면 사양을 보고 자동으로 고른다.
        cfg: dict[str, Any] = {}
        r = resolve(cfg, root)
        assert r["using"]["vision"] == "qwen2.5-vl-3b"
        assert r["using"]["stt"] in STT_CHOICES
        assert r["hardware"]["tier"] in STT_BY_TIER

        # 사용자가 고른 값이 자동을 이긴다 — 안 그러면 "내가 고른 게 왜 안 먹지"가 된다.
        assert choose(cfg, "chat", "llama-8b", root)
        assert resolve(cfg, root)["using"]["chat"] == "llama-8b"
        assert choose(cfg, "stt", "large-v3", root)
        assert resolve(cfg, root)["using"]["stt"] == "large-v3"

        # 없는 것은 못 고른다.
        assert not choose(cfg, "chat", "없는모델", root)
        assert not choose(cfg, "stt", "huge-v9", root)
        assert not choose(cfg, "없는역할", "x", root)

        # 빈 값은 "자동으로 되돌리기"다. 자동은 이름순 첫 번째.
        assert choose(cfg, "chat", "", root)
        assert resolve(cfg, root)["using"]["chat"] == "llama-8b"

        # 고른 모델 파일이 사라지면 조용히 자동으로 돌아간다 — 그것 때문에 안 뜨면 안 된다.
        choose(cfg, "chat", "llama-8b", root)
        (root / "llama-8b.gguf").unlink()
        assert resolve(cfg, root)["using"]["chat"] == "qwen2.5-1.5b"

        # 아무것도 없어도 죽지 않는다. 그 기능만 빠진다.
        empty = Path(tmp) / "빈폴더"
        empty.mkdir()
        bare = resolve({}, empty)
        assert bare["using"]["chat"] == "" and bare["using"]["stt"] in STT_CHOICES

    print("models_config self-check 통과")


if __name__ == "__main__":
    _self_check()
