# -*- coding: utf-8 -*-
"""꺼내기 값 잣대 — AI 가 한 물음에 답하려고 **몇 글자를 태우나**.

오너 지시(2026-09-12): 크레딧 소모를 줄이는 것이 성능이다. 그러니 「찾았나」만 재면
모자라다. **찾기까지 태운 글자**를 같이 재야 고침이 이득인지 손해인지 갈린다.

지금 꺼내기는 두 단이다:
  1단  `/eb/v1/memory/search?q=..`      제목·한 줄 요약·소제목 목록·글자 수·이음선
  2단  `/eb/v1/memory/note?title=..`    글 한 편(또는 `&heading=` 로 토막만)

재는 것:
  - 1단 글자   그 물음에 1단이 돌려주는 JSON 전체 글자 수
  - 등수       정답이 1단 목록 몇 번째인가 (0 = 목록 밖)
  - 2단 글자   정답 글을 펼칠 때 드는 글자 수 (통째 / 제일 알맞은 토막)
  - 합계       1단 + 2단. **이것이 한 물음의 값이다**

★ 서버를 안 띄운다. 서버가 쓰는 것과 **같은 함수**를 곧장 불러 같은 꼴로 만든다
  (`server.py` 의 1단 만드는 자리를 그대로 옮겼다). 서버를 띄우면 토큰·포트가 끼어들고
  값이 흔들린다. 꼴이 갈리면 이 파일이 거짓말을 하므로 **server.py 를 고치면 여기도 고친다.**
"""
import json
import shutil
import sys
import time
from pathlib import Path

뿌리 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(뿌리 / "pc"))

import notes as N                                   # noqa: E402
from brain import onnx_embedder                     # noqa: E402
from notes import EMBED_TOKENS, Notes               # noqa: E402

원본 = Path(r"D:\옵시디언\VC\data\notes")
일터 = 뿌리 / "시험기록" / "꺼내기-작업"
물음표 = 뿌리 / "시험기록" / "잣대-물음-20260912.txt"
모델 = 뿌리 / "models"                                # e5-small 384 — 구운 판과 같은 것


def 물음읽기():
    for 한줄 in 물음표.read_text(encoding="utf-8").splitlines():
        한줄 = 한줄.strip()
        if not 한줄 or 한줄.startswith("#") or "|" not in 한줄:
            continue
        물음, _, 정답칸 = (조각.strip() for 조각 in 한줄.partition("|"))
        yield 물음, [t.strip() for t in 정답칸.split(";") if t.strip()]


def 한단(n: Notes, q: str, k: int = 5) -> tuple[list[str], int]:
    """서버의 1단과 **같은 꼴**을 만들고 글자 수를 센다. (제목들, 글자수)"""
    out = []
    for r in n.search(q, k):
        몸 = r["body"]
        한장 = {"title": r["title"], "summary": N.요약(몸, 물음=q), "chars": len(몸)}
        if r["kind"] and r["kind"] != "note":
            한장["kind"] = r["kind"]
        if r["pinned"]:
            한장["pinned"] = True
        if r["created"]:
            한장["created"] = str(r["created"])[:10]
        if 머리 := [h for _, h in N.headings(몸)][:20]:
            한장["headings"] = 머리
        if 이웃 := n.neighbors(r["title"]):
            한장["links"] = 이웃
        out.append(한장)
    글 = json.dumps({"results": out}, ensure_ascii=False)
    return [x["title"] for x in out], len(글)


def 두단(n: Notes, 제목: str, 소제목: str = "") -> int:
    """2단 글자 수. 소제목을 주면 그 토막만."""
    쪽 = n.read(제목)
    if 쪽 is None:
        return 0
    if 소제목:
        토막 = N.section(쪽.body, 소제목)
        본 = {"title": 제목, "heading": 소제목, "text": 토막, "chars": len(토막)}
    else:
        본 = {"title": 제목, "text": 쪽.body, "chars": len(쪽.body),
              "headings": [h for _, h in N.headings(쪽.body)][:20]}
    return len(json.dumps(본, ensure_ascii=False))


def 창고열기() -> Notes:
    if not (일터 / "data" / "notes").is_dir():
        if 일터.exists():
            shutil.rmtree(일터)
        t = time.perf_counter()
        shutil.copytree(원본, 일터 / "data" / "notes")
        print(f"  사본 {time.perf_counter() - t:.0f}초", flush=True)
    n = Notes(일터 / "data" / "notes", str(일터 / "색인.db"), index_now=False)
    t = time.perf_counter()
    n.reindex()
    n.use_embedder(onnx_embedder(모델, max_tokens=EMBED_TOKENS))
    while n.embed_some(64):
        pass
    print(f"  색인·벡터 {time.perf_counter() - t:.0f}초 · 항목 "
          f"{n.conn.execute('SELECT count(*) FROM notes').fetchone()[0]} · "
          f"못 만든 벡터 {n.vec_left()}", flush=True)
    return n


def main() -> int:
    일터.mkdir(parents=True, exist_ok=True)
    n = 창고열기()
    줄 = ["| 물음 | 등수 | 1단 글자 | 2단(통째) | 2단(토막) | 합계(토막 쓸 때) |",
          "|---|---:|---:|---:|---:|---:|"]
    합_1단 = 합_통째 = 합_토막 = 0
    찾음수 = 0
    for 물음, 정답들 in 물음읽기():
        제목들, 한단글자 = 한단(n, 물음)
        자리 = [제목들.index(a) + 1 for a in 정답들 if a in 제목들]
        등수 = min(자리) if 자리 else 0
        합_1단 += 한단글자
        통째 = 토막 = 0
        if 등수:
            찾음수 += 1
            맞은 = next(a for a in 정답들 if a in 제목들)
            통째 = 두단(n, 맞은)
            쪽 = n.read(맞은)
            머리들 = [h for _, h in N.headings(쪽.body)] if 쪽 else []
            # 토막이 있으면 **제일 큰 토막**을 쓴다 — AI 가 어느 토막인지 모르는 채
            # 고르면 최악의 경우 제일 큰 것을 집는다. 낙관하지 않는다.
            토막 = max((두단(n, 맞은, h) for h in 머리들), default=통째)
            합_통째 += 통째
            합_토막 += 토막
        줄.append(f"| {물음[:26]} | {등수 or '밖'} | {한단글자} | {통째 or '-'} "
                  f"| {토막 or '-'} | {한단글자 + 토막 if 등수 else '-'} |")
    머리 = (f"물음 {len(줄) - 2}개 · 1단에 정답이 든 물음 {찾음수}개\n"
            f"1단 글자 합 {합_1단} (물음당 평균 {합_1단 // max(1, len(줄) - 2)})\n"
            f"2단 통째 합 {합_통째} · 2단 토막 합 {합_토막}\n"
            f"**한 물음에 태우는 글자 (찾은 것만, 토막 쓸 때) 평균 "
            f"{(합_1단 * 찾음수 // max(1, len(줄) - 2) + 합_토막) // max(1, 찾음수)}**")
    글 = 머리 + "\n\n" + "\n".join(줄)
    (일터 / "결과.md").write_text(글, encoding="utf-8")
    print(머리)
    print(f"\n적었다: {일터 / '결과.md'}")
    n.conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
