# -*- coding: utf-8 -*-
"""토막 벡터가 「목록 밖 14」를 줄이는가 — 본체를 안 건드리고 밖에서 재 본다.

지금 VC 는 글 한 편에 벡터 한 장이고, 그 벡터는 본문 **앞 200자**(CARD_CHARS)로만
만든다. 잣대 20물음의 정답 글은 348~1597자로 **전부 200자를 넘는다** — 본문 대부분이
벡터에 안 들어간다. 카드를 400/800자로 늘리는 길은 이미 재서 졌다(뜻이 뭉개진다,
곁실험 3). 아직 안 잰 것은 **글을 토막내 토막마다 벡터를 만들고 가장 가까운 토막으로
치는 길**이다 — 제목 벡터를 max 로 쓰는 것과 같은 구조다.

스키마(`vectors.path PRIMARY KEY`)를 고치기 전에 사본에서 먼저 잰다. 쪼개는 것은
파일 쪽에서 하므로 VC 코드는 한 줄도 안 바꾼다.

★ 견주는 규칙(기준선 문서): **같은 판·같은 벡터 세대끼리 견준다.** 그래서 대조군도
여기서 다시 만들어 잰다 — 문서에 적힌 2/6/14 와 직접 견주지 않는다.
★ 모델은 e5-small(384). 기준선이 구운 판으로 쟀고 구운 판이 그 모델이다.
  이 PC 소스의 기본값은 e5-base(768)이라 그대로 두면 못 견준다.
"""
import shutil
import sys
import time
from pathlib import Path

뿌리 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(뿌리 / "pc"))

from brain import onnx_embedder          # noqa: E402
from notes import (HISTORY_DIR, TEMPLATE_DIR, Note, Notes,  # noqa: E402
                   headings, safe_title, section)

사본 = 뿌리 / "시험기록" / "잣대-사본-20260912" / "data" / "notes"
작업 = 뿌리 / "시험기록" / "실험-토막-작업"
물음표 = 뿌리 / "시험기록" / "잣대-물음-20260912.txt"
모델 = 뿌리 / "models"                    # e5-small 384
쪼갤길이 = 200                             # CARD_CHARS 와 같다


def 잰다(무엇: str):
    t = time.perf_counter()
    print(f"  {무엇} …", end="", flush=True)
    return t


def 끝(t):
    print(f" {time.perf_counter() - t:.0f}초")


def 조각들(제목: str, 몸: str) -> list[tuple[str, str]]:
    """한 편을 토막으로. 소제목이 있으면 소제목마다, 없으면 길이로 자른다.

    소제목 앞의 머리글도 한 토막이다 — 거기 요지가 적힌 글이 많다.
    """
    if len(몸) <= 쪼갤길이:
        return [(제목, 몸)]
    머리들 = [h for _, h in headings(몸)]
    out = []
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
            if not 토막.strip():
                continue
            # 소제목 글자도 토막에 넣는다 — 그 말이 뜻의 절반이다
            out.append((f"{제목} ∙ {h}", f"{h}\n{토막}"))
    if not out:
        for i in range(0, len(몸), 쪼갤길이):
            out.append((f"{제목} ∙ {i // 쪼갤길이 + 1}", 몸[i:i + 쪼갤길이]))
    return out


def 창고만들기(곳: Path, 쪼갠다: bool) -> int:
    """사본의 항목을 평평한 .md 로 다시 쓴다. 앞머리는 안 쓴다 — 두 창고의 조건을 같게."""
    if 곳.exists():
        shutil.rmtree(곳)
    곳.mkdir(parents=True)
    본이름 = {}
    센다 = 0
    for path in sorted(사본.rglob("*.md")):
        if HISTORY_DIR in path.parts or TEMPLATE_DIR in path.parts:
            continue                       # 지난 판은 항목이 아니다
        쪽 = Note.loads(path.stem, path.read_text(encoding="utf-8", errors="replace"))
        몸 = 쪽.body
        조각 = 조각들(쪽.title, 몸) if 쪼갠다 else [(쪽.title, 몸)]
        for 이름, 글 in 조각:
            안전 = safe_title(이름)
            n = 본이름.get(안전, 0) + 1
            본이름[안전] = n
            # `safe_title` 은 확장자를 안 붙인다. 겹치면 번호를 뒤에 단다 —
            # 제목은 파일명이라 겹치면 뒤엣것이 앞엣것을 덮어 항목이 조용히 준다.
            파일 = 곳 / (f"{안전}.md" if n == 1 else f"{안전} ({n}).md")
            파일.write_text(글, encoding="utf-8")
            센다 += 1
    return 센다


def 물음읽기() -> list[tuple[str, list[str]]]:
    out = []
    for 한줄 in 물음표.read_text(encoding="utf-8").splitlines():
        한줄 = 한줄.strip()
        if not 한줄 or 한줄.startswith("#") or "|" not in 한줄:
            continue
        물음, _, 정답칸 = (조각.strip() for 조각 in 한줄.partition("|"))
        out.append((물음, [t.strip() for t in 정답칸.split(";") if t.strip()]))
    return out


def 채점(곳: Path, 색인: Path, 이름표: str, 제목벡터끄기: bool = False) -> str:
    n = Notes(곳, str(색인), index_now=False)
    n.제목벡터끄기 = 제목벡터끄기
    t = 잰다(f"{이름표} 색인")
    n.reindex()
    끝(t)
    n.use_embedder(onnx_embedder(모델))    # 384. 기본 max_tokens 128 = eb.py 와 같다
    t = 잰다(f"{이름표} 벡터 {n.vec_left()}장")
    while n.embed_some(64):
        pass
    끝(t)
    항목 = n.conn.execute("SELECT count(*) FROM notes").fetchone()[0]
    등수들, 줄 = [], []
    t0 = time.perf_counter()
    for 물음, 정답들 in 물음읽기():
        찾음 = [r["title"] for r in n.search(물음)]
        # ★ 쪼갠 창고에서는 정답 제목이 「원제목 ∙ 소제목」이 된다.
        #   원제목으로 **시작하면** 맞은 것으로 센다 — 안 쪼갠 쪽도 같은 규칙이라 공정하다.
        자리 = [i + 1 for i, t2 in enumerate(찾음)
                if any(t2 == a or t2.startswith(a + " ∙") for a in 정답들)]
        등수 = min(자리) if 자리 else 0
        등수들.append(등수)
        줄.append(f"{물음} | {등수 or '밖'} | {찾음[0] if 찾음 else '(없음)'}")
    머리 = (f"[{이름표}] 물음 {len(등수들)}개 · 1등 {sum(1 for r in 등수들 if r == 1)}"
            f" · 3등 안 {sum(1 for r in 등수들 if 1 <= r <= 3)}"
            f" · 목록 밖 {sum(1 for r in 등수들 if r == 0)}"
            f" · {time.perf_counter() - t0:.1f}초 · 항목 {항목}개"
            f" · 못 만든 벡터 {n.vec_left()}개"
            + (" · 제목 벡터 뺌" if 제목벡터끄기 else ""))
    n.conn.close()
    print("  " + 머리)
    return 머리 + "\n" + "\n".join(줄)


def main() -> int:
    작업.mkdir(parents=True, exist_ok=True)
    적을것 = []
    for 이름표, 쪼갠다 in (("대조군 통짜", False), ("실험군 토막", True)):
        곳 = 작업 / ("통짜" if not 쪼갠다 else "토막")
        t = 잰다(f"{이름표} 창고")
        센다 = 창고만들기(곳, 쪼갠다)
        끝(t)
        print(f"  파일 {센다}장")
        색인 = 작업 / f"{곳.name}.db"
        색인.unlink(missing_ok=True)
        적을것.append(채점(곳, 색인, 이름표))
    (작업 / "결과.md").write_text("\n\n".join(적을것), encoding="utf-8")
    print(f"\n적었다: {작업 / '결과.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
