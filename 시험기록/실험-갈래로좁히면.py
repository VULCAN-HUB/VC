# -*- coding: utf-8 -*-
"""못 찾은 물음에 **갈래를 붙이면** 몇 등으로 올라오나.

1단이 놓친 것들이 뜻으로는 33~120등에 있다. 창고 2794장 중 `일`이 2373장이니
`kind:결정`(120장)·`kind:규칙`(271장)으로 좁히면 밀어낸 것들이 통째로 빠진다.
좁히기가 값을 내면 고칠 자리는 검색이 아니라 **AI 에게 좁히라고 말해 주는 자리**다.
"""
import sys
from pathlib import Path

뿌리 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(뿌리 / "pc"))

from brain import onnx_embedder                     # noqa: E402
from notes import EMBED_TOKENS, Notes               # noqa: E402

일터 = 뿌리 / "시험기록" / "꺼내기-작업"
물음표 = 뿌리 / "시험기록" / "잣대-물음-20260912.txt"
모델 = 뿌리 / "models" / "e5-base"          # 실무에 깔린 것과 같은 큰 모델


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
    갈래들 = [r[0] for r in n.conn.execute(
        "SELECT kind, count(*) c FROM notes GROUP BY kind ORDER BY c DESC").fetchall()]
    print("갈래", 갈래들)
    print(f"{'물음':28} {'그냥':>4} {'정답 갈래로':>10} {'제일 좋은 갈래':>14}")
    나아진 = 0
    for 물음, 정답들 in 물음읽기():
        그냥 = 자리([r["title"] for r in n.search(물음, 5)], 정답들)
        쪽 = next((n.read(a) for a in 정답들 if n.read(a)), None)
        정답갈래 = (쪽.kind or "note") if 쪽 else "?"
        좁힘 = 자리([r["title"] for r in n.search(f"kind:{정답갈래} {물음}", 5)], 정답들)
        제일 = min([자리([r["title"] for r in n.search(f"kind:{g} {물음}", 5)], 정답들) or 99
                   for g in 갈래들] or [99])
        if not 그냥 and 좁힘:
            나아진 += 1
        print(f"{물음[:28]:28} {그냥 or '밖':>4} {정답갈래:>6}={좁힘 or '밖':<4} {제일 if 제일 < 99 else '밖':>10}")
    print(f"\n갈래를 알면 새로 찾는 물음 {나아진}개")
    n.conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
