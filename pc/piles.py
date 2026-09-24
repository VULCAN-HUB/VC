"""비슷한 것끼리 **더미**로 묶기 (오너 2026-09-19).

오너: 「무작위로 작성한 수많은 메모와 간단히 작성한 글들을 모아서 보여주는 무언가가 있으면 좋겠다」
→ 「AI 가 비슷한 것끼리 더미로」로 정했다.

★★ **새 모델을 부르지 않는다.** 창고에는 이미 글마다 **뜻 벡터**가 있다(찾기가 쓰던 것).
   그것으로 묶으면 공짜고 곧바로다 — 수백 장을 8B 에 하나씩 물으면 몇 분이 걸린다.

묶는 법(가까운 것부터 붙이기):
  ① 아직 안 묶인 글 중 **가장 큰 무리를 이룰 글**을 씨앗으로 잡는다
  ② 씨앗과 `문턱` 보다 가까운 것들을 한 더미로 모은다
  ③ 남은 것으로 다시 — 더 못 모으면 남은 것은 「혼자」다
  ※ k-means 가 아니다. **몇 더미가 나올지 미리 못 정한다** — 사람 메모는 덩어리 크기가 제멋대로다.

더미 이름은 **그 더미에만 흔한 낱말**로 짓는다(생성 모델을 안 쓴다 — 느리고 지어낸다).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ★★ **문턱은 창고마다 스스로 고른다.** 처음엔 0.62 같은 고정값을 썼는데, 실제 창고에서
#   **12장이 전부 한 더미**가 됐다 — e5 계열 벡터는 남남끼리도 0.77 부터 시작한다(재 봤다:
#   최소 0.77 · 중앙 0.83 · 최대 0.94). 어떤 모델을 쓰든 값의 폭이 달라지므로 **분포에서** 고른다.
#   아래 백분위 = 「가장 가까운 위 몇 %만 같은 더미로 본다」.
묶는백분위 = 88.0
# 분포가 이상할 때를 대비한 울타리
문턱바닥, 문턱천장 = 0.30, 0.97
문턱 = 0.62      # 표를 손으로 만들어 잴 때만 쓰는 기본값
# 이보다 적으면 더미라고 안 한다. 둘은 우연히 붙기도 한다.
최소 = 2

_낱말 = re.compile(r"[가-힣A-Za-z0-9][가-힣A-Za-z0-9\-]{1,}")
# 어디에나 나오는 말은 이름이 못 된다
_흔한말 = {"그리고", "하지만", "그래서", "오늘", "어제", "내일", "이것", "저것", "때문", "하는",
          "한다", "했다", "있다", "없다", "된다", "같다", "https", "http", "www", "com",
          "메모", "기록", "생각", "정리", "확인", "the", "and", "for", "you", "with"}


@dataclass
class Pile:
    """더미 하나."""

    name: str
    titles: list[str] = field(default_factory=list)

    @property
    def size(self) -> int:
        return len(self.titles)


def _말들(글: str) -> list[str]:
    return [w.lower() for w in _낱말.findall(글 or "") if w.lower() not in _흔한말 and len(w) > 1]


def 이름짓기(제목들: list[str], 글들: dict[str, str], 전체셈: dict[str, int], 전체수: int) -> str:
    """그 더미에만 흔한 낱말 한둘로 이름을 짓는다.

    창고 전체에서도 흔한 말(「제품」 같은)은 이름이 못 된다 — 어느 더미나 그 이름이 된다.
    """
    셈: dict[str, int] = {}
    for t in 제목들:
        for w in set(_말들(t + " " + 글들.get(t, "")[:400])):
            셈[w] = 셈.get(w, 0) + 1
    점수 = []
    for w, n in 셈.items():
        if n < 2 and len(제목들) > 2:
            continue
        흔함 = 전체셈.get(w, 0) / max(전체수, 1)      # 창고 전체에서 얼마나 흔한가
        점수.append((n / len(제목들) - 흔함, n, w))
    점수.sort(key=lambda x: (-x[0], -x[1], x[2]))
    고른 = [w for _, _, w in 점수[:2]]
    return " · ".join(고른) if 고른 else 제목들[0][:20]


def 문턱고르기(가까움, 백분위: float = 묶는백분위) -> float:
    """이 창고에서 「같은 더미」로 볼 문턱. **값 자체가 아니라 분포**를 보고 고른다.

    모델을 바꾸면 가까움의 폭이 통째로 달라진다 — 고정값은 그때마다 틀린다.
    """
    쌍 = [가까움[i][j] for i in range(len(가까움)) for j in range(i + 1, len(가까움))]
    if not 쌍:
        return 문턱
    쌍.sort()
    자리 = min(len(쌍) - 1, max(0, int(round(len(쌍) * 백분위 / 100)) - 1))
    return max(문턱바닥, min(문턱천장, 쌍[자리]))


def 묶기(제목들: list[str], 가까움, 글들: dict[str, str] | None = None,
        문턱값: float = 문턱, 최소수: int = 최소) -> list[Pile]:
    """`가까움[i][j]` 는 i·j 가 얼마나 가까운가(1 이면 같음). 큰 더미부터 돌려준다.

    벡터가 없으면 부르는 쪽이 `가까움` 을 못 만든다 — 그때는 빈 목록이다(화면이 그렇게 말한다).
    """
    글들 = 글들 or {}
    남음 = set(range(len(제목들)))
    # 전체에서 각 낱말이 몇 장에 나오는지 — 흔한 말을 이름에서 빼려고 쓴다
    전체셈: dict[str, int] = {}
    for t in 제목들:
        for w in set(_말들(t + " " + 글들.get(t, "")[:400])):
            전체셈[w] = 전체셈.get(w, 0) + 1

    더미들: list[Pile] = []
    while 남음:
        # 씨앗 = 남은 것 중 **가장 많은 이웃**을 가진 글. 가장 큰 덩어리부터 떼어 낸다.
        씨앗 = max(남음, key=lambda i: (sum(1 for j in 남음 if j != i and 가까움[i][j] >= 문턱값), -i))
        무리 = [i for i in 남음 if i == 씨앗 or 가까움[씨앗][i] >= 문턱값]
        if len(무리) < 최소수:
            break                       # 남은 것은 더 못 모은다 — 「혼자」로 둔다
        남음 -= set(무리)
        # 씨앗과 가까운 순으로 — 더미를 열었을 때 가장 그 더미다운 것이 위에 온다
        무리.sort(key=lambda i: -가까움[씨앗][i])
        titles = [제목들[i] for i in 무리]
        더미들.append(Pile(name=이름짓기(titles, 글들, 전체셈, len(제목들)), titles=titles))
    더미들.sort(key=lambda p: -p.size)
    return 더미들


def 혼자(제목들: list[str], 더미들: list[Pile]) -> list[str]:
    """어느 더미에도 안 든 글들. 「아직 아무것과도 안 닮은 것」이다."""
    묶인 = {t for p in 더미들 for t in p.titles}
    return [t for t in 제목들 if t not in 묶인]


def 창고에서(store, 최대: int = 400, 문턱값: float | None = None) -> tuple[list[Pile], list[str], str]:
    """창고의 뜻 벡터로 묶는다. `(더미들, 혼자, 까닭)` — 못 묶으면 까닭이 찬다."""
    vecs = store._vectors()
    if not vecs:
        return [], [], "아직 뜻 벡터가 없어 — 모델이 올라오면 저절로 만들어져."
    제목들, mat, _tvec = vecs
    try:
        import numpy as np
    except ImportError:
        return [], [], "numpy 가 없어 못 묶어."
    if len(제목들) > 최대:                 # 너무 많으면 최근 것부터 — 셈이 제곱으로 는다
        제목들, mat = 제목들[:최대], mat[:최대]
    if len(제목들) < 최소:
        return [], list(제목들), "묶을 만큼 글이 없어."
    가까움 = (mat @ mat.T).tolist()
    문턱값 = 문턱고르기(가까움) if 문턱값 is None else 문턱값
    글들 = {}
    for t in 제목들:
        쪽 = store.read(t)
        if 쪽:
            글들[t] = 쪽.body
    더미들 = 묶기(제목들, 가까움, 글들, 문턱값)
    return 더미들, 혼자(제목들, 더미들), ""


def _self_check() -> None:
    # 가까움 표를 손으로 만든다 — 벡터·모델 없이 묶는 규칙만 잰다
    제목들 = ["고기 굽기", "삼겹살 먹음", "돼지고기 손질", "정수기 설치", "정수기 필터", "세금 신고"]
    def 가깝나(a, b):
        묶음 = [{0, 1, 2}, {3, 4}]
        if a == b:
            return 1.0
        return 0.9 if any({a, b} <= g for g in 묶음) else 0.1
    가까움 = [[가깝나(i, j) for j in range(len(제목들))] for i in range(len(제목들))]
    글들 = {"고기 굽기": "숯불 고기", "삼겹살 먹음": "고기 배부르다", "돼지고기 손질": "고기 손질",
           "정수기 설치": "정수기 왔다", "정수기 필터": "정수기 필터 갈기", "세금 신고": "세금"}

    더미들 = 묶기(제목들, 가까움, 글들)
    assert len(더미들) == 2, [(p.name, p.titles) for p in 더미들]
    assert 더미들[0].size == 3 and 더미들[1].size == 2, [p.size for p in 더미들]
    assert set(더미들[0].titles) == {"고기 굽기", "삼겹살 먹음", "돼지고기 손질"}, 더미들[0].titles
    # 이름은 **그 더미에만 흔한 낱말**로
    assert "고기" in 더미들[0].name, 더미들[0].name
    assert "정수기" in 더미들[1].name, 더미들[1].name
    # 아무것과도 안 닮은 것은 「혼자」다 — 억지로 어느 더미에 넣지 않는다
    assert 혼자(제목들, 더미들) == ["세금 신고"], 혼자(제목들, 더미들)

    # 문턱을 올리면 아무것도 안 묶인다(다 혼자)
    assert 묶기(제목들, 가까움, 글들, 문턱값=0.95) == []
    # 둘뿐이어도 묶는다 · 최소를 3 으로 올리면 안 묶는다
    assert len(묶기(제목들[3:5], [[1.0, 0.9], [0.9, 1.0]], 글들)) == 1
    assert 묶기(제목들[3:5], [[1.0, 0.9], [0.9, 1.0]], 글들, 최소수=3) == []
    # 큰 더미가 먼저 온다
    assert [p.size for p in 더미들] == sorted([p.size for p in 더미들], reverse=True)
    # 같은 것으로 다시 묶으면 같은 답이다 — 흔들리면 사람이 못 믿는다
    다시 = 묶기(제목들, 가까움, 글들)
    assert [(p.name, p.titles) for p in 다시] == [(p.name, p.titles) for p in 더미들]
    # ★ 문턱은 **분포에서** 고른다 — 값이 높게 몰리는 모델(e5)에서도 갈라져야 한다
    몰린것 = [[1.0 if i == j else (0.92 if abs(i - j) <= 1 else 0.79) for j in range(8)] for i in range(8)]
    고른 = 문턱고르기(몰린것)
    assert 0.79 < 고른 <= 0.92, 고른
    묶임 = 묶기([f"글{i}" for i in range(8)], 몰린것, {}, 문턱값=고른)
    assert 1 < len(묶임) + len(혼자([f"글{i}" for i in range(8)], 묶임)), "다 한 더미가 됐다"
    # 쌍이 없으면 기본값으로 — 터지지 않는다
    assert 문턱고르기([[1.0]]) == 문턱

    print("piles self-check 통과")


if __name__ == "__main__":
    import sys

    if "--check" in sys.argv:
        _self_check()
