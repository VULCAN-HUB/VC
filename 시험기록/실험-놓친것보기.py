# -*- coding: utf-8 -*-
"""1단이 못 찾은 물음이 **어디까지 밀려 있나**를 본다.

목적: 13/20 의 나머지 7이 ① 뜻으로 아예 안 잡히는 것인지 ② k=5 에 잘려서 빠진
것인지 갈린다. ①이면 찾는 방법을 바꿔야 하고, ②면 순서(고르기)를 고치면 된다.
값만 보고 다음 손질을 고르려고 만든 것이라 판에는 안 들어간다.
"""
import sys
from pathlib import Path

뿌리 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(뿌리 / "pc"))
sys.path.insert(0, str(뿌리 / "시험기록"))

import notes as N                                   # noqa: E402
from brain import onnx_embedder                     # noqa: E402
from notes import EMBED_TOKENS, Notes               # noqa: E402

일터 = 뿌리 / "시험기록" / "꺼내기-작업"
물음표 = 뿌리 / "시험기록" / "잣대-물음-20260912.txt"
모델 = 뿌리 / "models"


def 물음읽기():
    for 한줄 in 물음표.read_text(encoding="utf-8").splitlines():
        한줄 = 한줄.strip()
        if not 한줄 or 한줄.startswith("#") or "|" not in 한줄:
            continue
        물음, _, 정답칸 = (조각.strip() for 조각 in 한줄.partition("|"))
        yield 물음, [t.strip() for t in 정답칸.split(";") if t.strip()]


def 자리(제목들, 정답들):
    난것 = [제목들.index(a) + 1 for a in 정답들 if a in 제목들]
    return min(난것) if 난것 else 0


def main() -> int:
    n = Notes(일터 / "data" / "notes", str(일터 / "색인.db"), index_now=False)
    n.reindex()
    n.use_embedder(onnx_embedder(모델, max_tokens=EMBED_TOKENS))
    while n.embed_some(64):
        pass
    print(f"항목 {n.conn.execute('SELECT count(*) FROM notes').fetchone()[0]} · 못 만든 벡터 {n.vec_left()}")
    print(f"{'물음':30} {'1단':>4} {'뜻200':>6} {'낱말수':>5}  정답")
    for 물음, 정답들 in 물음읽기():
        결과 = n.search(물음, 5)
        일단 = 자리([r["title"] for r in 결과], 정답들)
        낱말수 = n.낱말로찾은수
        뜻 = 자리([t for t, _ in n.semantic(물음, k=200)], 정답들)
        print(f"{물음[:30]:30} {일단 or '밖':>4} {뜻 or '밖':>6} {낱말수:>5}  {정답들[0][:34]}")
    n.conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
