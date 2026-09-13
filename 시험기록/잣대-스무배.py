# -*- coding: utf-8 -*-
"""**20년치 규모**에서 버티나. 오너 창고가 2,800장인데 하루 세 장이면 20년에 2만 장이다.

재는 것: 훑기(색인) · 검색 · 목록 · 파일 수가 늘 때 느려지는 정도.
뜻 벡터는 뺀다 — 2만 장 벡터는 몇 시간짜리라 여기서 잴 것이 아니다(모델 없이 돈다).
"""
import random
import shutil
import sys
import tempfile
import time
from pathlib import Path

뿌리 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(뿌리 / "pc"))

from notes import Note, Notes                        # noqa: E402

낱말 = ("회의 결정 기록 모델 검색 벡터 창고 사람 오너 판 고침 검사 화면 서버 문지기 "
       "태그 링크 이름 제목 본문 값 자리 물음 답 글자 토막 시험 잣대 그물 이력").split()


def 한장(i: int) -> Note:
    random.seed(i)
    줄들 = [" ".join(random.choices(낱말, k=12)) for _ in range(random.randint(3, 20))]
    if i % 7 == 0:
        줄들.append(f"이어진 곳: [[글 {random.randint(0, i or 1)}]]")
    if i % 5 == 0:
        줄들.append(f"#갈래{i % 13}")
    return Note(title=f"글 {i}", body="\n".join(줄들),
                kind=random.choice(["일", "규칙", "결정", "note"]))


def main() -> int:
    몇장 = int(sys.argv[1]) if len(sys.argv) > 1 else 20000
    일터 = Path(tempfile.mkdtemp(prefix="vc스무배"))
    try:
        n = Notes(일터 / "notes", str(일터 / "색인.db"))
        t0 = time.perf_counter()
        for i in range(몇장):
            n.write(한장(i))
        쓰기 = time.perf_counter() - t0
        print(f"{몇장}장 쓰기 {쓰기:.0f}초 ({쓰기 * 1000 / 몇장:.1f}ms/장)")

        n2 = Notes(일터 / "notes", str(일터 / "새색인.db"), index_now=False)
        t0 = time.perf_counter()
        n2.reindex()
        print(f"처음부터 훑기 {time.perf_counter() - t0:.0f}초")

        for 이름, 물음 in (("낱말 하나", "문지기"), ("낱말 둘", "회의 결정"),
                         ("좁히기", "kind:결정 회의"), ("빼기", "-kind:일 회의"),
                         ("제목만", "title:글 1"), ("하나라도", "문지기 OR 잣대"),
                         ("태그", "tag:갈래3")):
            t0 = time.perf_counter()
            낫 = n2.search(물음, 5)
            print(f"  {이름:8} {(time.perf_counter() - t0) * 1000:6.1f}ms · {len(낫)}장")
        t0 = time.perf_counter(); n2.graph()
        print(f"  그물      {(time.perf_counter() - t0) * 1000:6.1f}ms")
        t0 = time.perf_counter(); 외 = n2.외딴것수()
        print(f"  외딴 세기 {(time.perf_counter() - t0) * 1000:6.1f}ms · {외}장")
        쪽 = 일터 / "색인.db"
        print(f"색인 {쪽.stat().st_size // 1024 // 1024}MB · 파일 "
              f"{sum(1 for _ in (일터 / 'notes').rglob('*.md'))}장")
        n.conn.close(); n2.conn.close()
    finally:
        shutil.rmtree(일터, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
