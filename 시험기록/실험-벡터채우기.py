# -*- coding: utf-8 -*-
"""사본 DB 의 낡은 벡터를 채운다 — 구운 판이 「못 만든 벡터 0」에서 재게 하려고.

구운 v0.1.92 는 못 만든 벡터를 세기만 하고 안 채운다(오늘 소스에서 고쳤다).
그래서 같은 사본을 재도 **낡은 벡터 14개를 낡은 채로** 쟀다. 그 14개가 하필
잣대의 정답 글들이라 점수가 통째로 낮게 나왔다.

굽지 않고 가르려고, 여기서 채워 놓고 구운 exe 를 다시 돌린다.
모델은 exe 옆에 딸린 것과 같은 파일이다(해시 대조함).
"""
import sys
import time
from pathlib import Path

뿌리 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(뿌리 / "pc"))

from brain import onnx_embedder          # noqa: E402
from notes import EMBED_TOKENS, Notes    # noqa: E402

사본 = 뿌리 / "시험기록" / "잣대-사본-20260912"
n = Notes(사본 / "data" / "notes", str(사본 / "notes_index.db"), index_now=False)
n.reindex()
n.use_embedder(onnx_embedder(뿌리 / "models", max_tokens=EMBED_TOKENS))
print("채우기 전 못 만든 벡터", n.vec_left(), flush=True)
t = time.perf_counter()
while n.embed_some(64):
    pass
print(f"채운 뒤 {n.vec_left()}개 · {time.perf_counter() - t:.0f}초")
n.conn.close()
