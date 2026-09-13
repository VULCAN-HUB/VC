# -*- coding: utf-8 -*-
"""대조군이 기준선과 안 맞는 까닭을 가른다 — 사본 폴더를 **그대로** 재 본다.

`실험-토막벡터.py` 의 대조군은 사본의 글을 **평평한 폴더에 다시 써서** 만들었다
(앞머리 없이 몸만). 그 대조군이 1등 10 · 목록 밖 4 로 나왔는데 기준선은 1등 2 ·
목록 밖 14 다. 맞힌 여섯은 기준선과 똑같고 그 위에 여덟을 더 맞혔다 — 우연이 아니라
**조건이 하나 다르다.**

여기서는 사본 폴더를 손대지 않고 그대로 잰다. 색인 DB 만 작업 폴더에 새로 만든다.
- 값이 기준선(2/6/14)에 가까우면 → **파일을 다시 쓴 것**이 원인이다(앞머리·폴더 구조).
- 값이 대조군(10/15/4)에 가까우면 → **내 채점이나 벡터 세대**가 원인이다.
"""
import sys
import time
from pathlib import Path

뿌리 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(뿌리 / "pc"))

from brain import onnx_embedder          # noqa: E402
from notes import EMBED_TOKENS, Notes    # noqa: E402

사본 = 뿌리 / "시험기록" / "잣대-사본-20260912" / "data" / "notes"
작업 = 뿌리 / "시험기록" / "실험-토막-작업"
물음표 = 뿌리 / "시험기록" / "잣대-물음-20260912.txt"
모델 = 뿌리 / "models"                    # e5-small 384 — 구운 판과 같은 모델


def 물음읽기():
    for 한줄 in 물음표.read_text(encoding="utf-8").splitlines():
        한줄 = 한줄.strip()
        if not 한줄 or 한줄.startswith("#") or "|" not in 한줄:
            continue
        물음, _, 정답칸 = (조각.strip() for 조각 in 한줄.partition("|"))
        yield 물음, [t.strip() for t in 정답칸.split(";") if t.strip()]


def 한판(토큰: int) -> str:
    색인 = 작업 / f"원본그대로-{토큰}.db"
    for 꼬리 in ("", "-wal", "-shm"):
        Path(str(색인) + 꼬리).unlink(missing_ok=True)
    n = Notes(사본, str(색인), index_now=False)
    n.reindex()
    n.use_embedder(onnx_embedder(모델, max_tokens=토큰))
    t = time.perf_counter()
    while n.embed_some(64):
        pass
    잰벡터 = time.perf_counter() - t
    등수들, 줄 = [], []
    for 물음, 정답들 in 물음읽기():
        찾음 = [r["title"] for r in n.search(물음)]
        자리 = [찾음.index(a) + 1 for a in 정답들 if a in 찾음]
        등수 = min(자리) if 자리 else 0
        등수들.append(등수)
        줄.append(f"{물음} | {등수 or '밖'} | {찾음[0] if 찾음 else '(없음)'}")
    항목 = n.conn.execute("SELECT count(*) FROM notes").fetchone()[0]
    폭 = n.conn.execute("SELECT length(vec) FROM vectors LIMIT 1").fetchone()
    n.conn.close()
    머리 = (f"[원본 그대로 · max_tokens {토큰}] 1등 {sum(1 for r in 등수들 if r == 1)}"
            f" · 3등 안 {sum(1 for r in 등수들 if 1 <= r <= 3)}"
            f" · 목록 밖 {sum(1 for r in 등수들 if r == 0)}"
            f" · 항목 {항목}개 · 벡터 {폭[0] // 2 if 폭 else 0}칸 · 만드는 데 {잰벡터:.0f}초")
    print("  " + 머리, flush=True)
    return 머리 + "\n" + "\n".join(줄)


def main() -> int:
    작업.mkdir(parents=True, exist_ok=True)
    # 128 은 `--찾기점수` 가 쓰는 값(onnx_embedder 기본), 192 는 화면이 쓰는 값.
    # 둘이 다르면 **같은 창고인데 만드는 자리에 따라 벡터가 갈린다** — 그것부터 본다.
    적을것 = [한판(128), 한판(EMBED_TOKENS)]
    (작업 / "결과-원본그대로.md").write_text("\n\n".join(적을것), encoding="utf-8")
    print(f"\n적었다: {작업 / '결과-원본그대로.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
