"""찾은 것이 많을 때 **더 좁히는 길**을 찾아 준다 (오너 2026-09-19).

★★ **되는데 안 알려 주면 없는 것과 같다.** `kind:` · `tag:` · `year:` · `path:` 로 좁힐 수 있는데,
   「관련 37개야」라는 말만 보고 사람이 스스로 그 문법을 떠올릴 길이 없었다.
   그래서 **찾은 것들 자체를 세어** 「이렇게 더 좁힐 수 있어」를 만든다.

고르는 규칙 — **진짜로 갈라지는 것만** 권한다:
  · 전부에 붙어 있는 값은 안 권한다(37개 중 37개가 `일` 이면 좁혀도 그대로다)
  · 하나뿐인 값도 안 권한다(37 → 1 은 좁히기가 아니라 고르기다)
  · 반쯤 가르는 것을 가장 좋게 본다 — 한 번 눌러 가장 많이 줄어든다
"""

from __future__ import annotations

import re

TAG = re.compile(r"(?:^|\s)#([^\s#,.]{1,24})")


def _년월(path: str) -> tuple[str, str]:
    """`2026/09/글.md` → ("2026", "2026/09"). 폴더를 안 쓰면 빈 글."""
    조각 = [c for c in str(path).replace("\\", "/").split("/") if c]
    if len(조각) >= 2 and len(조각[0]) == 4 and 조각[0].isdigit():
        return 조각[0], f"{조각[0]}/{조각[1]}"
    return "", ""


def 세기(행들: list[dict]) -> dict[str, dict[str, int]]:
    """찾은 것들에서 갈래·태그·해·폴더를 센다."""
    표: dict[str, dict[str, int]] = {"kind": {}, "tag": {}, "year": {}, "path": {}}

    def 더하기(칸: str, 값: str) -> None:
        if 값:
            표[칸][값] = 표[칸].get(값, 0) + 1

    for r in 행들:
        더하기("kind", str(r.get("kind") or "").strip())
        해, 달 = _년월(r.get("path") or "")
        더하기("year", 해)
        더하기("path", 달)
        for t in set(TAG.findall(str(r.get("body") or ""))):
            더하기("tag", t)
    return 표


def 제안(행들: list[dict], 최대: int = 3, 적어도: int = 5) -> list[str]:
    """`["kind:결정(12)", "tag:고기(7)"]`. 좁힐 만한 게 없으면 빈 목록.

    [적어도] 개보다 적게 찾았으면 아무것도 안 권한다 — 몇 개 안 되면 그냥 보는 게 빠르다.
    """
    전체 = len(행들)
    if 전체 < 적어도:
        return []
    나온것 = []
    for 칸, 값들 in 세기(행들).items():
        for 값, 수 in 값들.items():
            if 수 < 2 or 수 >= 전체:      # 하나뿐이거나 전부면 좁히기가 아니다
                continue
            # 반쯤 가르는 것이 가장 좋다 — 0.5 에서 멀수록 값이 떨어진다
            점수 = 1.0 - abs(수 / 전체 - 0.5) * 2
            나온것.append((점수, 수, f"{칸}:{값}({수})"))
    # 점수 → 개수 → 글자순(같은 점수면 늘 같은 차례여야 시험이 흔들리지 않는다)
    나온것.sort(key=lambda x: (-x[0], -x[1], x[2]))
    # 같은 칸이 셋을 다 먹지 않게 — 갈래만 셋 권하면 좁히는 길이 하나로 보인다
    골라: list[str] = []
    쓴칸: dict[str, int] = {}
    for _, _, 말 in 나온것:
        칸 = 말.split(":", 1)[0]
        if 쓴칸.get(칸, 0) >= 2:
            continue
        쓴칸[칸] = 쓴칸.get(칸, 0) + 1
        골라.append(말)
        if len(골라) >= 최대:
            break
    return 골라


def 한줄(행들: list[dict], 최대: int = 3) -> str:
    """사람에게 보일 한 줄. 권할 게 없으면 빈 글."""
    got = 제안(행들, 최대)
    return f"더 좁히려면 — {' · '.join(got)}" if got else ""


def _self_check() -> None:
    def 행(제목, kind="", body="", path=""):
        return {"title": 제목, "kind": kind, "body": body, "path": path}

    # 몇 개 안 되면 안 권한다 — 그냥 보는 게 빠르다
    assert 제안([행(f"{i}", kind="일") for i in range(4)]) == []

    # 전부 같은 갈래면 그 갈래는 안 권한다(좁혀도 그대로)
    같음 = [행(f"{i}", kind="일", path="2026/09/x.md") for i in range(10)]
    assert all(not s.startswith("kind:일") for s in 제안(같음)), 제안(같음)

    # 반쯤 가르는 것을 먼저 권한다
    섞임 = ([행(f"a{i}", kind="결정", body="#고기") for i in range(5)]
           + [행(f"b{i}", kind="일") for i in range(5)])
    got = 제안(섞임)
    assert got and got[0] in ("kind:결정(5)", "kind:일(5)", "tag:고기(5)"), got
    assert any(s.startswith("tag:고기") for s in got), got

    # 하나뿐인 값은 안 권한다 — 좁히기가 아니라 고르기다
    하나 = [행(f"{i}", kind="일") for i in range(9)] + [행("외톨이", kind="규칙")]
    assert all(not s.startswith("kind:규칙") for s in 제안(하나)), 제안(하나)

    # 해·달은 경로에서 읽는다
    해들 = ([행(f"a{i}", kind="일", path="2026/09/x.md") for i in range(5)]
          + [행(f"b{i}", kind="일", path="2025/03/x.md") for i in range(5)])
    got = 제안(해들)
    assert any(s.startswith("year:") for s in got) or any(s.startswith("path:") for s in got), got

    # 한 칸이 다 먹지 않는다 — 갈래만 셋이면 좁히는 길이 하나로 보인다
    여러갈래 = []
    for 갈래, 수 in (("일", 4), ("결정", 3), ("규칙", 3), ("메모", 2)):
        여러갈래 += [행(f"{갈래}{i}", kind=갈래, body="#공통") for i in range(수)]
    got = 제안(여러갈래, 최대=3)
    assert sum(1 for s in got if s.startswith("kind:")) <= 2, got

    assert 한줄([행(f"{i}", kind="일") for i in range(3)]) == ""
    assert 한줄(섞임).startswith("더 좁히려면 — ")
    print("facets self-check 통과")


if __name__ == "__main__":
    import sys

    if "--check" in sys.argv:
        _self_check()
