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
낱말꼴 = re.compile(r"[가-힣A-Za-z0-9][가-힣A-Za-z0-9]{1,}")
# 어디에나 나오는 말은 좁히는 데 쓸모가 없다
흔한말 = {"그리고", "하지만", "그래서", "오늘", "어제", "내일", "이것", "저것", "때문", "하는",
        "한다", "했다", "있다", "없다", "된다", "같다", "https", "http", "www", "com",
        "메모", "기록", "정리", "확인", "the", "and", "for", "you", "with", "this"}


def _년월(path: str) -> tuple[str, str]:
    """`2026/09/글.md` → ("2026", "2026/09"). 폴더를 안 쓰면 빈 글."""
    조각 = [c for c in str(path).replace("\\", "/").split("/") if c]
    if len(조각) >= 2 and len(조각[0]) == 4 and 조각[0].isdigit():
        return 조각[0], f"{조각[0]}/{조각[1]}"
    return "", ""


# 좁히기로 쓸모가 없는 앞머리. 날짜는 `year:`·`path:` 가 이미 하고, `들인곳` 은
# 어느 폴더에서 왔는지라 글 고르는 데 안 쓴다.
안셀앞머리 = frozenset({"date", "날짜", "created", "들인곳", "id", "지은이"})


def 세기(행들: list[dict], 앞머리: dict | None = None) -> dict[str, dict[str, int]]:
    """찾은 것들에서 갈래·태그·해·폴더를 세고, **앞머리 값**도 같이 센다.

    ★ 앞머리(`status: active`)는 창고가 남의 볼트에서 받아 온 것이라 이름이 저마다 다르다.
      부르는 쪽이 `{제목: {이름: 값}}` 을 넘겨 준다 — 이 모듈은 창고를 모른다.
    """
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
        for 이름, 값 in (앞머리 or {}).get(str(r.get("title") or ""), {}).items():
            if 이름 in 안셀앞머리:
                continue
            값 = str(값).split("#")[0].strip()
            # 값이 길면 좁히기가 안 된다 — 한 글에만 있는 긴 글귀는 권할 말이 못 된다
            if 값 and len(값) <= 24:
                표.setdefault(이름, {})
                표[이름][값] = 표[이름].get(값, 0) + 1
    return 표


def 낱말제안(행들: list[dict], 물은말: str = "", 최대: int = 3) -> list[str]:
    """찾은 것들을 **반쯤 가르는 낱말**들. 쉼표로 덧붙여 좁히라고 권할 말이다(오너 2026-09-20).

    ★ 쉼표로 좁히는 것은 **이미 되고 있었다**(`고기, 먹음` → 둘 다 든 글). 그런데 화면이
      아무 말도 안 해 아무도 몰랐다 — 되는데 안 알려 주면 없는 것과 같다.
    """
    전체 = len(행들)
    이미 = {w.lower() for w in 낱말꼴.findall(물은말 or "")}
    셈: dict[str, int] = {}
    for r in 행들:
        글 = f"{r.get('title') or ''} {r.get('body') or ''}"[:600]
        for w in {x.lower() for x in 낱말꼴.findall(글)}:
            if w in 흔한말 or w in 이미 or len(w) < 2:
                continue
            셈[w] = 셈.get(w, 0) + 1
    골라 = []
    for w, n in 셈.items():
        if n < 2 or n >= 전체:            # 하나뿐이거나 전부면 좁히기가 아니다
            continue
        골라.append((1.0 - abs(n / 전체 - 0.5) * 2, n, w))
    골라.sort(key=lambda x: (-x[0], -x[1], x[2]))
    return [w for _, _, w in 골라[:최대]]


def 제안(행들: list[dict], 최대: int = 3, 적어도: int = 5, 앞머리: dict | None = None) -> list[str]:
    """`["kind:결정(12)", "tag:고기(7)"]`. 좁힐 만한 게 없으면 빈 목록.

    [적어도] 개보다 적게 찾았으면 아무것도 안 권한다 — 몇 개 안 되면 그냥 보는 게 빠르다.
    """
    전체 = len(행들)
    if 전체 < 적어도:
        return []
    나온것 = []
    for 칸, 값들 in 세기(행들, 앞머리).items():
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


def 한줄(행들: list[dict], 최대: int = 3, 물은말: str = "", 앞머리: dict | None = None) -> str:
    """사람에게 보일 한 줄. 권할 게 없으면 빈 글.

    **낱말을 먼저** 권한다 — 쉼표로 덧붙이는 것이 `kind:` 문법보다 손에 익다(오너 2026-09-20).
    """
    말 = []
    # ★ 세 개만 돼도 권한다 — 좁히기는 **이어질 때** 쓸모가 있다. 7개에서 한 번 권하고
    #   4개에서 입을 닫으면 「고기, 먹음, 배달」로 가는 길이 중간에 끊긴다(오너 2026-09-20).
    낱말 = 낱말제안(행들, 물은말) if len(행들) >= 3 else []
    if 낱말 and 물은말.strip():
        첫 = 낱말[0]
        고른 = " · ".join(낱말)
        말.append(f"쉼표로 더 좁혀 — 「{물은말.strip()}, {첫}」 (쓸 만한 말: {고른})")
    got = 제안(행들, 최대, 앞머리=앞머리)
    if got:
        말.append(f"갈래·태그로는 — {' · '.join(got)}")
    return " / ".join(말)


def _self_check() -> None:
    def 행(제목, kind="", body="", path=""):
        return {"title": 제목, "kind": kind, "body": body, "path": path}

    # 갈래·태그 권유는 몇 개 안 되면 안 한다 — 그냥 보는 게 빠르다
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
    assert 한줄(섞임).startswith("갈래·태그로는 — "), 한줄(섞임)

    # ★ 쉼표로 좁히는 길을 **말로 알려 준다**(오너 2026-09-20). 이미 되던 것인데 아무도 몰랐다.
    고기들 = ([행(f"a{i}", body="고기 먹음 배달") for i in range(4)]
            + [행(f"b{i}", body="고기 구움 숯불") for i in range(4)])
    낱말 = 낱말제안(고기들, "고기")
    assert 낱말 and "고기" not in 낱말, 낱말          # 이미 친 말은 다시 안 권한다
    # ★ **이미 친 말이 일부 글에만 있어도 다시 권하면 안 된다** — 「고기, 고기」는 좁히기가 아니다.
    #   (뜻 검색이 낱말 없는 글까지 담아 오므로 이 꼴이 실제로 나온다.)
    섞여든것 = ([행(f"x{i}", body="고기 먹음") for i in range(4)]
             + [행(f"y{i}", body="먹음 배달") for i in range(4)])
    assert "고기" not in 낱말제안(섞여든것, "고기"), 낱말제안(섞여든것, "고기")
    assert set(낱말) & {"먹음", "배달", "구움", "숯불"}, 낱말
    줄 = 한줄(고기들, 물은말="고기")
    assert 줄.startswith("쉼표로 더 좁혀 — 「고기, "), 줄
    # 전부에 든 말은 안 권한다 — 좁혀도 그대로다
    같은말 = [행(f"c{i}", body="회의 노트") for i in range(6)]
    assert "회의" not in 낱말제안(같은말, ""), 낱말제안(같은말, "")
    # 물은 말이 없으면(빈 창고 앞머리) 쉼표 권유를 안 한다 — 붙일 말이 없다
    assert not 한줄(고기들, 물은말="").startswith("쉼표로"), 한줄(고기들, 물은말="")
    # ★ **이어질 때** 쓸모가 있다 — 셋만 남아도 다음 낱말을 권한다(중간에 끊기면 안 된다)
    셋 = [행("a", body="고기 먹음 배달"), 행("b", body="고기 먹음 회식"), 행("c", body="고기 구움")]
    assert 한줄(셋, 물은말="고기").startswith("쉼표로 더 좁혀"), 한줄(셋, 물은말="고기")
    # 둘 이하면 안 권한다 — 그냥 보면 된다
    assert not 한줄(셋[:2], 물은말="고기").startswith("쉼표로")
    # ★★ **앞머리도 좁히는 길로 권한다**(오너 2026-09-20). 되는데 안 알려 주면
    #   없는 것과 같다 — 쉼표 좁히기도 되고 있었는데 아무도 몰랐던 것과 같은 자리다.
    행들2 = [{"title": f"글{i}", "body": "몸", "kind": "note", "path": "2026/09/x.md"}
           for i in range(8)]
    # ★ 날짜·들인곳을 **반쯤 가르게** 둔다 — 그러지 않으면 「하나뿐/전부」 규칙에
    #   저절로 걸러져, 빼는 규칙이 없어도 검사가 통과해 버린다(그래서 한 번 놓쳤다).
    앞 = {f"글{i}": {"status": "active" if i < 3 else "draft",
                   "date": "2026-09-01" if i < 4 else "2026-09-02",
                   "들인곳": "볼트가" if i < 4 else "볼트나"} for i in range(8)}
    권 = 제안(행들2, 최대=4, 앞머리=앞)
    assert any(말.startswith("status:active(3)") for 말 in 권), 권
    assert not any(말.startswith("date:") for 말 in 권), f"날짜를 권한다: {권}"
    assert not any(말.startswith("들인곳") for 말 in 권), f"들인곳을 권한다: {권}"
    # 앞머리를 안 넘기면 예전과 똑같이 돈다 — 창고를 모르는 자리에서도 쓴다
    assert not any("status" in 말 for 말 in 제안(행들2, 최대=4)), "안 넘겼는데 앞머리가 나온다"
    # 값이 길면 권하지 않는다(한 글에만 있는 긴 글귀는 좁히는 말이 못 된다)
    긴앞 = {f"글{i}": {"note": "아주 길고 긴 설명이 여기에 계속 이어진다 정말로" if i < 4
                            else "또 다른 아주 길고 긴 설명이 여기에 이어진다"} for i in range(8)}
    assert not any(말.startswith("note:") for 말 in 제안(행들2, 최대=4, 앞머리=긴앞)), "긴 값을 권한다"
    # ★ **사람이 보는 한 줄까지 와야 한다.** 제안만 되고 화면 문구에 안 실리면 없는 길이다.
    줄 = 한줄(행들2, 최대=4, 물은말="글", 앞머리=앞)
    assert "status:active" in 줄, f"앞머리가 사람이 보는 줄에 안 온다: {줄}"

    print("facets self-check 통과")


if __name__ == "__main__":
    import sys

    if "--check" in sys.argv:
        _self_check()
