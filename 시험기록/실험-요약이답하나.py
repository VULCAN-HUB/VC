# -*- coding: utf-8 -*-
"""1단의 **한 줄 요약이 물음에 답하나**를 눈으로 본다.

답하면 2단(900~1500자)을 아예 안 불러도 된다 — 한 물음 값이 774자에서 끝난다.
기계로 채점할 수 없어 값을 적지 않는다. **고칠 자리를 찾으려고 보는 것**이다.
"""
import sys
from pathlib import Path

뿌리 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(뿌리 / "pc"))

import notes as N                                   # noqa: E402
from brain import onnx_embedder                     # noqa: E402
from notes import EMBED_TOKENS, Notes               # noqa: E402

일터 = 뿌리 / "시험기록" / "꺼내기-작업"
물음표 = 뿌리 / "시험기록" / "잣대-물음-20260912.txt"
모델 = 뿌리 / "models" / "e5-base"


def main() -> int:
    n = Notes(일터 / "data" / "notes", str(일터 / "색인.db"), index_now=False)
    n.reindex()
    n.use_embedder(onnx_embedder(모델, max_tokens=EMBED_TOKENS))
    while n.embed_some(64):
        pass
    for 한줄 in 물음표.read_text(encoding="utf-8").splitlines():
        if "|" not in 한줄 or 한줄.startswith("#"):
            continue
        물음, _, 정답칸 = (조각.strip() for 조각 in 한줄.partition("|"))
        정답들 = [t.strip() for t in 정답칸.split(";") if t.strip()]
        제목들 = [r["title"] for r in n.search(물음, 5)]
        맞은 = next((a for a in 정답들 if a in 제목들), None)
        print(f"\n■ {물음}")
        if not 맞은:
            print("  (1단 목록 밖)")
            continue
        쪽 = n.read(맞은)
        print(f"  → {맞은}")
        print(f"  요약: {N.요약(쪽.body, 물음=물음)}")
    n.conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
