# -*- coding: utf-8 -*-
"""깨끗한 기준선을 세운다 — 손 안 댄 원본 사본에서, 벡터를 다 채우고 잰다.

지금까지 쓰던 사본(`잣대-사본-20260912`)은 **곁실험 5 가 정답 글 14 장에
「…에 대한 글이다」 한 줄을 붙여 놓은 것**이고, 그 14 장의 **벡터는 붙이기 전 것**이었다.
그 위에서 기준선(1등 2 · 목록 밖 14)과 곁실험 3·4·5·6 과 제목 벡터 결론이 나왔다.
벡터만 채우면 같은 창고가 1등 10 · 목록 밖 4 로 바뀐다(구운 판·소스 둘 다, 2회 재현).

그래서 **원본 창고 값은 아직 아무도 안 쟀다.** 여기서 그것을 잰다.
- 오너 원본은 **읽기만** 한다. 새 사본을 떠서 그 위에서만 잰다.
- 벡터를 다 채우고 잰다. 안 채우면 또 같은 함정에 빠진다.
- 모델은 e5-small(384). 구운 판에 딸린 것과 같은 파일이다(해시 대조함).
"""
import shutil
import sys
import time
from pathlib import Path

뿌리 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(뿌리 / "pc"))

from brain import onnx_embedder          # noqa: E402
from notes import EMBED_TOKENS, Notes    # noqa: E402

원본 = Path(r"D:\옵시디언\VC\data\notes")
새사본 = 뿌리 / "시험기록" / "잣대-사본깨끗-20260912"
물음표 = 뿌리 / "시험기록" / "잣대-물음-20260912.txt"
모델 = 뿌리 / "models"


def 물음읽기():
    for 한줄 in 물음표.read_text(encoding="utf-8").splitlines():
        한줄 = 한줄.strip()
        if not 한줄 or 한줄.startswith("#") or "|" not in 한줄:
            continue
        물음, _, 정답칸 = (조각.strip() for 조각 in 한줄.partition("|"))
        yield 물음, [t.strip() for t in 정답칸.split(";") if t.strip()]


def 채점(n, 이름표: str) -> str:
    등수들, 줄 = [], []
    for 물음, 정답들 in 물음읽기():
        찾음 = [r["title"] for r in n.search(물음)]
        자리 = [찾음.index(a) + 1 for a in 정답들 if a in 찾음]
        등수 = min(자리) if 자리 else 0
        등수들.append(등수)
        줄.append(f"{물음} | {등수 or '밖'} | {찾음[0] if 찾음 else '(없음)'}")
    머리 = (f"[{이름표}] 1등 {sum(1 for r in 등수들 if r == 1)}"
            f" · 3등 안 {sum(1 for r in 등수들 if 1 <= r <= 3)}"
            f" · 목록 밖 {sum(1 for r in 등수들 if r == 0)}"
            f" · 항목 {n.conn.execute('SELECT count(*) FROM notes').fetchone()[0]}개"
            f" · 못 만든 벡터 {n.vec_left()}개")
    print("  " + 머리, flush=True)
    return 머리 + "\n" + "\n".join(줄)


def main() -> int:
    if not 원본.is_dir():
        print(f"원본이 없다: {원본}")
        return 1
    if 새사본.exists():
        shutil.rmtree(새사본)
    t = time.perf_counter()
    # 기록·색인 자리를 사본 안에 두어 원본에 아무것도 안 쓴다.
    shutil.copytree(원본, 새사본 / "data" / "notes")
    print(f"  사본 뜨기 {time.perf_counter() - t:.0f}초", flush=True)

    n = Notes(새사본 / "data" / "notes", str(새사본 / "notes_index.db"), index_now=False)
    t = time.perf_counter()
    n.reindex()
    print(f"  색인 {time.perf_counter() - t:.0f}초 · 항목 "
          f"{n.conn.execute('SELECT count(*) FROM notes').fetchone()[0]}개", flush=True)
    n.use_embedder(onnx_embedder(모델, max_tokens=EMBED_TOKENS))
    t = time.perf_counter()
    while n.embed_some(64):
        pass
    print(f"  벡터 {time.perf_counter() - t:.0f}초 · 못 만든 것 {n.vec_left()}개", flush=True)

    적을것 = [채점(n, "깨끗한 원본 사본")]
    n.제목벡터끄기 = True
    n._vec_cache = None
    적을것.append(채점(n, "깨끗한 원본 사본 · 제목 벡터 뺌"))
    n.conn.close()
    (새사본 / "결과.md").write_text("\n\n".join(적을것), encoding="utf-8")
    print(f"\n적었다: {새사본 / '결과.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
