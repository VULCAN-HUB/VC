"""메모에 붙은 녹음을 받아쓰고 요약한다 (편의 기능 14번 · 애플 노트 녹음).

폰에서 녹음(.m4a)을 붙여 보내면, 컴퓨터가 뒤에서 받아써 **그 글 끝에** 붙인다:

    ## 받아쓰기 — 녹음 2026-10-01.m4a
    (받아쓴 글)

    ## 녹음 요약
    - …

★ 받아쓰기는 이 컴퓨터 안에서만(faster-whisper). 요약은 대화 모델이 있을 때만.
★ 한 녹음은 **한 번만** — 받아쓴 녹음 이름을 앱 자리 `vc-받아쓰기.json` 에 적는다. 글에 「## 받아쓰기 — 이름」 이 이미 있어도 건너뛴다.
★ 한 바퀴에 몇 개만 — 긴 녹음이 쌓여도 서버가 하루 종일 붙들리지 않게.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Callable

import paths
from notes import Notes, parse_attachments

AUDIO_EXT = {".m4a", ".aac", ".mp3", ".wav"}
MEMO = "vc-받아쓰기.json"
PER_RUN = 3
HEAD = "## 받아쓰기 — "

_model = None


def whisper(path: Path) -> str:
    """녹음 파일 → 글자. 긴 말이라 호출어용 설정(빔 1·VAD 끔)과 다르게 둔다."""
    global _model
    if _model is None:
        from faster_whisper import WhisperModel

        _model = WhisperModel("small", device="cpu", compute_type="int8")
    segments, _ = _model.transcribe(str(path), language="ko", vad_filter=True, beam_size=5)
    return " ".join(s.text.strip() for s in segments).strip()


def _load(where: Path) -> set[str]:
    try:
        got = json.loads(where.read_text(encoding="utf-8"))
        return set(got) if isinstance(got, list) else set()
    except (OSError, ValueError):
        return set()


def run(store: Notes, hear: Callable[[Path], str] | None = whisper,
        summarize: Callable[[str], str] | None = None,
        where: Path | None = None, per_run: int = PER_RUN) -> list[str]:
    """받아쓴 녹음 이름들을 돌려준다."""
    if hear is None:
        return []
    where = where or paths.기계자리(MEMO)
    done = _load(where)
    did: list[str] = []
    rows = store.conn.execute("SELECT title, body FROM notes ORDER BY mtime DESC").fetchall()
    for title, body in rows:
        for name in parse_attachments(body):
            if len(did) >= per_run:
                break
            if Path(name).suffix.lower() not in AUDIO_EXT or name in done or f"{HEAD}{name}" in body:
                continue
            path = store.attachment_path(name)
            if path is None:
                continue
            try:
                text = hear(path)
            except Exception:
                continue            # 못 읽은 녹음은 다음 바퀴에 다시
            done.add(name)
            if not text:
                continue
            add = f"{HEAD}{name}\n\n{text}"
            if summarize is not None and len(text) > 40:   # 아주 짧은 말은 요약할 것이 없다
                try:
                    요약 = re.sub(r"(?s)<think>.*?</think>", "", summarize(text) or "").strip()
                    if 요약:
                        add += f"\n\n## 녹음 요약\n\n{요약}"
                except Exception:
                    pass        # 요약은 덤이다
            store.append(title, add)
            did.append(name)
    if did:
        try:
            where.parent.mkdir(parents=True, exist_ok=True)
            where.write_text(json.dumps(sorted(done), ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
    return did


def _self_check() -> None:
    import tempfile

    from notes import Note

    with tempfile.TemporaryDirectory() as tmp:
        n = Notes(Path(tmp) / "창고")
        name = n.save_attachment(b"fake-m4a", ".m4a", stem="녹음")
        n.write(Note(title="회의 녹음", body=f"촬영 회의\n\n![[{name}]]"))
        n.write(Note(title="사진만", body="![[없는사진.jpg]]"))
        들음: list[Path] = []

        def 귀(p: Path) -> str:
            들음.append(p)
            return "다음 주 화요일 촬영은 오전 열 시로 정했고 정수기 브이씨아이에스 육팔구를 먼저 찍기로 했다. 조명은 두 개 더 빌린다."

        memo = Path(tmp) / MEMO
        did = run(n, 귀, lambda t: "<think>x</think>- 화요일 10시 촬영", memo)
        assert did == [name] and len(들음) == 1, (did, 들음)
        몸 = n.read("회의 녹음").body
        assert f"{HEAD}{name}" in 몸 and "오전 열 시" in 몸 and "## 녹음 요약" in 몸 and "<think>" not in 몸, 몸
        # 한 번만
        assert run(n, 귀, None, memo) == [] and len(들음) == 1, "받아쓴 녹음을 또 받아쓴다"
        # 기록이 사라져도 글에 이미 있으면 건너뛴다
        memo.unlink()
        assert run(n, 귀, None, memo) == [] and len(들음) == 1, "글에 받아쓰기가 있는데 또 한다"
        # 받아쓰기 도구가 없으면 아무것도 안 한다
        assert run(n, None) == []
    print("transcribe self-check 통과")


if __name__ == "__main__":
    if "--check" in sys.argv:
        _self_check()
