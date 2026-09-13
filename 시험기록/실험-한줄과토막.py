# -*- coding: utf-8 -*-
"""깨끗한 창고에서 네 조건을 나란히 잰다 — 한 줄 붙이기와 토막 벡터.

## 왜 다시 재나

곁실험 5 는 목록 밖 14 장의 정답 글에 「…에 대한 글이다」 한 줄을 붙여 놓고,
**그 14 장의 벡터를 다시 안 만든 채** 재고서 「글 쪽을 고쳐도 안 찾는다」고 적었다.
벡터만 채우면 같은 창고가 1등 2 → 10 · 목록 밖 14 → 4 가 된다(구운 판·소스 2회 재현).
깨끗한 원본 사본은 1등 2 · 목록 밖 14 로 기준선과 같다.

→ 목록 밖을 움직인 것은 **붙인 한 줄**이다. 곁실험 5 의 부정은 잘못이고,
   그 위에 선 곁실험 4·6 과 결론 절과 제목 벡터 2→5 도 다시 봐야 한다.

## 한계 — 미리 적는다

한 줄은 **정답 글 14 장에만** 붙어 있다. 창고 2794 장 전체에 붙인 것이 아니므로
이 값은 「정답만 유리하게 고쳤을 때의 위쪽 한계」다. 실제로 쓰려면 흡수할 때
모든 글에 자동으로 붙여야 하고, 그때는 경쟁하는 글도 같이 좋아져 값이 준다.
**이 한계를 모른 채 숫자만 옮겨 적으면 안 된다.**
"""
import shutil
import sys
import time
from pathlib import Path

뿌리 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(뿌리 / "pc"))

from brain import onnx_embedder                                    # noqa: E402
from notes import EMBED_TOKENS, Note, Notes, headings, safe_title, section  # noqa: E402
from notes import HISTORY_DIR, TEMPLATE_DIR                        # noqa: E402

깨끗 = 뿌리 / "시험기록" / "잣대-사본깨끗-20260912" / "data" / "notes"
한줄붙은 = 뿌리 / "시험기록" / "잣대-사본-20260912" / "data" / "notes"
작업 = 뿌리 / "시험기록" / "실험-토막-작업"
물음표 = 뿌리 / "시험기록" / "잣대-물음-20260912.txt"
모델 = 뿌리 / "models"
쪼갤길이 = 200


def 물음읽기():
    for 한줄 in 물음표.read_text(encoding="utf-8").splitlines():
        한줄 = 한줄.strip()
        if not 한줄 or 한줄.startswith("#") or "|" not in 한줄:
            continue
        물음, _, 정답칸 = (조각.strip() for 조각 in 한줄.partition("|"))
        yield 물음, [t.strip() for t in 정답칸.split(";") if t.strip()]


def 조각들(제목: str, 몸: str):
    if len(몸) <= 쪼갤길이:
        return [(제목, 몸)]
    머리들, out = [h for _, h in headings(몸)], []
    if 머리들:
        첫자리 = 몸.find("#")
        머리글 = 몸[:첫자리].strip() if 첫자리 > 0 else ""
        if 머리글:
            out.append((f"{제목} ∙ 머리", 머리글))
        본 = set()
        for h in 머리들:
            if h in 본:
                continue
            본.add(h)
            토막 = section(몸, h)
            if 토막.strip():
                out.append((f"{제목} ∙ {h}", f"{h}\n{토막}"))
    if not out:
        out = [(f"{제목} ∙ {i // 쪼갤길이 + 1}", 몸[i:i + 쪼갤길이])
               for i in range(0, len(몸), 쪼갤길이)]
    return out


def 창고만들기(원본: Path, 곳: Path, 쪼갠다: bool) -> int:
    if 곳.exists():
        shutil.rmtree(곳)
    곳.mkdir(parents=True)
    본이름, 센다 = {}, 0
    for path in sorted(원본.rglob("*.md")):
        if HISTORY_DIR in path.parts or TEMPLATE_DIR in path.parts:
            continue
        쪽 = Note.loads(path.stem, path.read_text(encoding="utf-8", errors="replace"))
        for 이름, 글 in (조각들(쪽.title, 쪽.body) if 쪼갠다 else [(쪽.title, 쪽.body)]):
            안전 = safe_title(이름)
            n = 본이름.get(안전, 0) + 1
            본이름[안전] = n
            (곳 / (f"{안전}.md" if n == 1 else f"{안전} ({n}).md")).write_text(
                글, encoding="utf-8")
            센다 += 1
    return 센다


def 한판(원본: Path, 이름표: str, 쪼갠다: bool) -> str:
    곳 = 작업 / safe_title(이름표)
    t = time.perf_counter()
    센다 = 창고만들기(원본, 곳, 쪼갠다)
    색인 = 작업 / f"{safe_title(이름표)}.db"
    for 꼬리 in ("", "-wal", "-shm"):
        Path(str(색인) + 꼬리).unlink(missing_ok=True)
    n = Notes(곳, str(색인), index_now=False)
    n.reindex()
    n.use_embedder(onnx_embedder(모델, max_tokens=EMBED_TOKENS))
    while n.embed_some(64):
        pass
    등수들, 줄 = [], []
    for 물음, 정답들 in 물음읽기():
        찾음 = [r["title"] for r in n.search(물음)]
        자리 = [i + 1 for i, t2 in enumerate(찾음)
                if any(t2 == a or t2.startswith(a + " ∙") for a in 정답들)]
        등수 = min(자리) if 자리 else 0
        등수들.append(등수)
        줄.append(f"{물음} | {등수 or '밖'} | {찾음[0] if 찾음 else '(없음)'}")
    머리 = (f"[{이름표}] 1등 {sum(1 for r in 등수들 if r == 1)}"
            f" · 3등 안 {sum(1 for r in 등수들 if 1 <= r <= 3)}"
            f" · 목록 밖 {sum(1 for r in 등수들 if r == 0)}"
            f" · 항목 {센다}개 · 못 만든 벡터 {n.vec_left()}개"
            f" · {time.perf_counter() - t:.0f}초")
    n.conn.close()
    print("  " + 머리, flush=True)
    return 머리 + "\n" + "\n".join(줄)


def main() -> int:
    작업.mkdir(parents=True, exist_ok=True)
    적을것 = [
        한판(깨끗, "깨끗 통짜", False),        # 원본 그대로 — 이것이 참 기준선이다
        한판(깨끗, "깨끗 토막", True),         # 토막 벡터만
        한판(한줄붙은, "한줄 통짜", False),     # 정답 14장에 한 줄 붙음
        한판(한줄붙은, "한줄 토막", True),      # 한 줄 + 토막
    ]
    (작업 / "결과-네조건.md").write_text("\n\n".join(적을것), encoding="utf-8")
    print(f"\n적었다: {작업 / '결과-네조건.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
