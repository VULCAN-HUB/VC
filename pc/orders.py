"""사람이 시킨 말을 알아듣는다. **글자만 받고 화면은 모른다.**

여기가 따로 있는 이유: 지금은 타자로 치지만 나중에는 말로 시킨다. 알아듣는 일이
화면이나 마이크에 붙어 있으면 그때 두 벌이 된다. **글자 → 시킨 것** 하나만 여기서
하고, 실제로 하는 일은 부르는 쪽이 한다.

그래서 이 파일은 PyQt5도 모델도 안 쓴다. 검사도 화면 없이 돈다.

**아무 말에나 걸리면 안 된다.** 검색칸이 곧 지시칸이라, "고양이"라고 쳤을 때
지시로 잘못 읽으면 찾는 길이 막힌다. 그래서 **시키는 말끝**(찾아줘·만들어·지워…)이
있을 때만 걸리고, 아니면 `None`을 돌려줘 검색으로 흘려보낸다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# 시키는 말 하나. `what`이 무엇을 하라는 것이고 나머지는 딸린 것이다.
#   찾기 · 열기 · 만들기 · 덧붙이기 · 이름바꾸기 · 지우기 · 되돌리기
#   오늘일지 · 언제 · 태그 · 이어진것 · 곁에 · 닫기
@dataclass
class Order:
    what: str
    target: str = ""
    extra: str = ""
    # 갈라 읽을 자리가 여럿일 때의 나머지 후보들. **부르는 쪽이 진짜 있는 제목을 고른다.**
    # 「학교에 가는 길에 내일 적어줘」에서 「학교」인지 「학교에 가는 길」인지는
    # 항목 목록을 봐야 알 수 있는데, 이 파일은 항목을 모른다.
    alts: tuple = ()


def _clean(text: str) -> str:
    """앞뒤 군더더기를 턴다. 사람은 "그, 회의록 열어줘" 처럼 친다."""
    text = text.strip().strip(".!?~ ")
    for junk in ("좀 ", "그 ", "저 ", "야 ", "VC ", "브이씨 ", "불칸 "):
        if text.startswith(junk):
            text = text[len(junk):].lstrip()
    # 가운데 끼어든 것도 턴다 — 사람은 "사진 보정 순서 **좀** 열어봐" 처럼 친다.
    return _FILLER.sub(" ", text).strip()


# 말끝을 넉넉히 받는다. 하나만 빠져도 사람은 "안 되네" 하고 다시 안 쓴다.
_DO = (r"(?:\s*(?:좀|다|한번|한 번)?\s*"
       r"(?:줘|주라|줄래|봐|보자|봐라|다오|라|자)?"
       r"(?:\s*(?:요|용))?)")

# **「좀」은 어디에나 끼어든다** — "사진 보정 순서 좀 열어봐". 말끝 규칙만으로는 못 잡는다.
_FILLER = re.compile(r"\s+(?:좀|한번|한 번|다시|얼른|빨리)\s+")

RULES: list[tuple[str, re.Pattern]] = [
    # 되돌리기가 먼저다. "지난 판으로 되돌려"에는 「되돌려」와 「지난 판」이 다 들어 있다.
    ("되돌리기", re.compile(rf"^(?:(.+?)\s*)?(?:지난\s*판(?:으로)?|이전\s*판(?:으로)?)?\s*"
                            rf"(?:되돌려|돌려놔|복구해){_DO}$")),
    # 오늘 일지. "오늘 일지", "어제 일기 열어줘"
    ("오늘일지", re.compile(rf"^(오늘|어제|그저께)?\s*(?:일지|일기)"
                            rf"(?:\s*(?:열어|보여|써|쓸래|쓰자){_DO})?$")),
    # 언제 쓴 것. "어제 쓴 것", "이번 주에 적은 글 보여줘"
    # 「어제 쓴 것 보여줘」와 「어제 뭐 썼지」를 다 받는다 — 뒤쪽이 더 자주 나온다.
    ("언제", re.compile(rf"^(오늘|어제|그저께|이번\s*주|지난\s*주|이번\s*달|지난\s*달)"
                        rf"(?:에|엔|자|치)?\s*(?:"
                        rf"(?:뭐|뭔|무슨|무엇)?\s*(?:쓴|적은|만든|고친|썼|적었|만들었)"
                        rf"\s*(?:것|거|글|기록|지|더라|나|었더라|었지)?"
                        rf")(?:\s*(?:있나|있어|없나))?"
                        rf"(?:\s*(?:보여|찾아|알려){_DO})?$")),
    # 태그. "#할일", "태그 할일 보여줘"
    # 「#할일」·「태그 할일」·「할일 태그」 셋 다. 사람은 순서를 안 지킨다.
    ("태그", re.compile(rf"^(?:#|태그\s+)([^\s#]+)"
                        rf"(?:\s*(?:붙은|달린)?\s*(?:것|거|글|기록)?"
                        rf"\s*(?:보여|찾아|알려){_DO})?$")),
    ("태그", re.compile(rf"^([^\s#]+)\s+태그"
                        rf"(?:\s*(?:붙은|달린)?\s*(?:것|거|글|기록)?"
                        rf"\s*(?:보여|찾아|알려){_DO})?$")),
    # 이어진 것. "회의록이랑 이어진 것"
    ("이어진것", re.compile(rf"^(.+?)(?:와|과|랑|이랑|하고)?\s*"
                            rf"(?:이어진|연결된|엮인|붙은)\s*(?:것|거|글|기록)"
                            rf"(?:\s*(?:있나|있어|없나))?"
                            rf"(?:\s*(?:보여|찾아|알려){_DO})?$")),
    # 지우기. **되돌릴 수 없으니 부르는 쪽이 반드시 되묻는다.**
    ("지우기", re.compile(rf"^(.+?)\s*(?:지워|지우자|삭제해|삭제하자|없애|없애자|버려|버리자){_DO}$")),
    # 이름 바꾸기. "회의록 이름 8월 회의록으로 바꿔줘"
    ("이름바꾸기", re.compile(rf"^(.+?)\s*(?:이름|제목)\s*(.+?)(?:으로|로)\s*"
                              rf"(?:바꿔|바꾸자|고쳐|변경해|개명){_DO}$")),
    # 「장보기를 장보기메모로 개명」 — 「이름」이라는 말 없이도 쓴다
    ("이름바꾸기", re.compile(rf"^(.+?)(?:을|를)\s*(.+?)(?:으로|로)\s*"
                              rf"(?:바꿔|바꾸자|개명해|개명){_DO}$")),
    # 덧붙이기. "회의록에 내일 3시 적어줘" — 만들기보다 먼저 본다("추가해"가 겹친다).
    ("덧붙이기", re.compile(rf"^(.+?)(?:에다가|에다|에)\s+(.+?)\s*"
                            rf"(?:적어|써|써둬|덧붙여|추가해|추가|붙여|넣어){_DO}$")),
    # 만들기
    ("만들기", re.compile(rf"^(?:새\s*(?:글|항목|기록)\s*)?(.+?)\s*"
                          rf"(?:만들어|만들자|새로\s*만들어|추가해){_DO}$")),
    # 곁에 띄우기. **열기보다 먼저 본다** — "곁에 띄워"에는 「띄워」가 들어 있다.
    ("곁에", re.compile(rf"^(?:(.+?)\s*)?(?:곁에|나란히|옆에)\s*(?:띄워|보여|열어){_DO}$")),
    # 열기
    ("열기", re.compile(rf"^(.+?)\s*(?:열어|열어봐|열자|보여|보자|띄워|띄우자|꺼내|꺼내자){_DO}$")),
    # 찾기. 제일 아래다 — 위에 안 걸린 것만 검색으로 본다.
    ("찾기", re.compile(rf"^(.+?)\s*(?:찾아|찾아봐|검색해|검색){_DO}$")),
    # 무르기. 「방금 한 것 무르고」 — 잘못 시킨 것을 되돌린다.
    ("무르기", re.compile(rf"^(?:방금\s*(?:것|거|한\s*것|한\s*거)?\s*)?"
                          rf"(?:무르|물러|취소하|취소해|없던\s*걸로\s*하|없던\s*걸로\s*해)"
                          rf"(?:고|자|기|어|여|라)?{_DO}$")),
    # 닫기
    ("닫기", re.compile(rf"^(?:닫아|그만|됐어|치워){_DO}$")),
]


_ADD_TAIL = re.compile(rf"\s*(?:적어|써|써둬|덧붙여|추가해|추가|붙여|넣어){_DO}$")


def _splits(said: str) -> list[tuple[str, str]]:
    """「A에 B 적어줘」를 가를 수 있는 모든 자리. 긴 제목부터 준다.

    제목 안에 「에」가 있으면 어디서 잘라야 할지 글자만으로는 못 정한다.
    **긴 쪽을 먼저 준다** — 「곁에 띄우면 줄이 겹친다」가 「곁」보다 제목일 확률이 높다.
    """
    body = _ADD_TAIL.sub("", said)
    out = []
    for mark in ("에다가", "에다", "에"):
        for at in range(len(body) - 1, -1, -1):
            if not body.startswith(mark, at):
                continue
            head, tail = body[:at].strip(), body[at + len(mark):].strip()
            if head and tail and (head, tail) not in out:
                out.append((head, tail))
    # **「에」가 있는 자리에서만 자르면 놓치는 제목이 있다.** 「학교에 가는 길
    # 물어보기 적어줘」에서 「학교에 가는 길」은 뒤에 「에」가 없어 후보에 아예
    # 안 올랐다(그래서 「학교」로 갔다). 어절 경계도 후보로 넣는다 — 긴 것부터.
    words = body.split()
    for cut in range(len(words) - 1, 0, -1):
        head, tail = " ".join(words[:cut]), " ".join(words[cut:])
        if (head, tail) not in out:
            out.append((head, tail))
    # 긴 제목이 먼저다. 제목 안에 「에」가 든 것이 흔해서 짧은 쪽이 먼저 걸리면
    # 엉뚱한 항목에 붙는다.
    out.sort(key=lambda pair: -len(pair[0]))
    return out


def read_order(text: str) -> Order | None:
    """시킨 말이면 `Order`, 아니면 `None`(= 그냥 찾는 말이다).

    **못 알아들으면 `None`이 맞다.** 억지로 지시로 읽으면 찾으려던 말이 엉뚱한
    동작이 된다 — 그게 못 알아듣는 것보다 나쁘다.
    """
    said = _clean(text)
    if not said:
        return None
    for what, rule in RULES:
        got = rule.match(said)
        if not got:
            continue
        parts = [(g or "").strip() for g in got.groups()]
        target = parts[0] if parts else ""
        extra = parts[1] if len(parts) > 1 else ""
        if what == "덧붙이기":
            # **「에」가 제목 안에도 있다.** 「곁에 띄우면 줄이 겹친다에 … 적어줘」에서
            # 앞에서부터 자르면 제목이 「곁」이 되어 못 찾는다 — 한국어 제목에 아주
            # 흔한 꼴이라(학교에 가는 길 · 집에 오는 길 · 회사에 낼 서류) 그냥
            # 지나갈 수 없다. 자를 수 있는 자리를 **다 모아** 넘기고 고르게 한다.
            return Order(what, target, extra, tuple(_splits(said)))
        if what in ("언제", "태그") or (what == "오늘일지" and not target):
            # 이 셋은 첫 자리가 대상이 아니라 「언제」·「무슨 태그」다.
            pass
        elif not target and what not in ("닫기", "곁에", "되돌리기", "무르기"):
            return None            # 대상 없는 지시는 지시가 아니다
        return Order(what, target, extra)
    return None


def josa(word: str, pair: str) -> str:
    """받침을 보고 조사를 고른다. `josa("회의록", "을/를")` → "회의록을".

    낯선 PC 실사용에서 「'회의록'을 '8월 회의록'로 바꿨어」가 나왔다. 기능에는
    지장이 없지만 **말투가 이 프로그램에서 제일 잘 만든 부분**이라 여기만
    어긋나면 더 눈에 띈다.
    """
    with_bat, without = pair.split("/")
    if not word:
        return word + without
    last = word.strip()[-1]
    if not ("가" <= last <= "힣"):
        return word + without      # 숫자·영문 뒤는 그냥 앞엣것으로 둔다
    has_bat = (ord(last) - 0xAC00) % 28 != 0
    return word + (with_bat if has_bat else without)


def tail(word: str, pair: str) -> str:
    """조사만. `tail("회의록", "을/를")` → "을". 따옴표 밖에 붙일 때 쓴다."""
    return josa(word, pair)[len(word):]


def spoken(order: Order) -> str:
    """무엇을 하려는지 사람 말로. 되묻거나 알릴 때 쓴다."""
    if order.what == "지우기":
        return f"'{josa(order.target, '을/를')}' 지운다. 파일이 사라진다."
    if order.what == "이름바꾸기":
        return (f"'{order.target}'{josa(order.target, '을/를')[len(order.target):]} "
                f"'{order.extra}'{josa(order.extra, '으로/로')[len(order.extra):]} 바꾼다.")
    if order.what == "덧붙이기":
        return f"'{order.target}'에 덧붙인다."
    return order.what


def _self_check() -> None:
    def order(text):
        return read_order(text)

    # --- 시키는 말 ---
    got = order("회의록 열어줘")
    assert got and got.what == "열기" and got.target == "회의록", got

    got = order("좀 그 회의록 보여줘")           # 군더더기가 붙어도 같다
    assert got and got.what == "열기" and got.target == "회의록", got

    got = order("사진 보정 순서 찾아줘")
    assert got and got.what == "찾기" and got.target == "사진 보정 순서", got

    got = order("장보기 만들어")
    assert got and got.what == "만들기" and got.target == "장보기", got

    got = order("새 글 장보기 만들어줘")
    assert got and got.what == "만들기" and got.target == "장보기", got

    got = order("회의록에 내일 세시 적어줘")
    assert got and got.what == "덧붙이기" and got.target == "회의록" \
        and got.extra == "내일 세시", got

    got = order("회의록 이름 8월 회의록으로 바꿔줘")
    assert got and got.what == "이름바꾸기" and got.target == "회의록" \
        and got.extra == "8월 회의록", got

    got = order("장보기 지워줘")
    assert got and got.what == "지우기" and got.target == "장보기", got

    got = order("회의록 되돌려줘")
    assert got and got.what == "되돌리기" and got.target == "회의록", got

    got = order("오늘 일지")
    assert got and got.what == "오늘일지" and got.target == "오늘", got
    assert order("일지 써줘").what == "오늘일지"

    got = order("어제 쓴 것 보여줘")
    assert got and got.what == "언제" and got.target == "어제", got
    got = order("이번 주에 적은 글 보여줘")
    assert got and got.what == "언제" and got.target.replace(" ", "") == "이번주", got

    got = order("#할일 보여줘")
    assert got and got.what == "태그" and got.target == "할일", got
    got = order("태그 업무 보여줘")
    assert got and got.what == "태그" and got.target == "업무", got

    got = order("회의록이랑 이어진 것 보여줘")
    assert got and got.what == "이어진것" and got.target == "회의록", got

    got = order("회의록 곁에 띄워줘")
    assert got and got.what == "곁에" and got.target == "회의록", got
    assert order("닫아").what == "닫기"
    # **방금 한 것 무르기.** 잘못 시켰을 때 되돌릴 길이 없다는 말이 나왔다.
    for said in ("무르고", "물러", "취소해", "방금 것 무르고", "방금 거 취소해",
                 "없던 걸로 해"):
        got = order(said)
        assert got and got.what == "무르기", (said, got)

    # --- 낯선 PC 실사용에서 **안 먹어서 적어 보내 준 다섯** ---
    # 열 개 중 다섯이 여기서 떨어졌다. 규칙 셋이 보였다:
    # 꼬리가 길어질 때 · 낱말 순서가 바뀔 때 · 동의어일 때.
    got = order("사진 보정 순서 좀 열어봐")
    assert got and got.what == "열기" and got.target == "사진 보정 순서", got
    got = order("어제 뭐 썼지")
    assert got and got.what == "언제" and got.target == "어제", got
    got = order("할일 태그 보여줘")            # 「태그 할일」과 순서가 반대
    assert got and got.what == "태그" and got.target == "할일", got
    # **제목 안에 「에」가 있어도 갈라야 한다.** 「학교에 가는 길」 「집에 오는 길」
    # 처럼 한국어 제목에 아주 흔하다. 어디서 자를지는 글자만으로 못 정하니
    # 후보를 다 주고 부르는 쪽이 진짜 있는 제목을 고른다.
    got = order("곁에 띄우면 줄이 겹친다에 새 줄 적어줘")
    assert got and got.what == "덧붙이기", got
    assert ("곁에 띄우면 줄이 겹친다", "새 줄") in got.alts, got.alts
    got = order("학교에 가는 길에 우산 챙기기 적어줘")
    assert ("학교에 가는 길", "우산 챙기기") in got.alts, got.alts
    heads = [h for h, _ in got.alts]
    # 진짜 제목을 고르는 것은 부르는 쪽이다. 여기서는 **긴 것이 먼저 오기만** 하면 된다 —
    # 짧은 쪽이 먼저 걸리면 「학교」처럼 엉뚱한 항목에 붙는다.
    assert heads.index("학교에 가는 길") < heads.index("학교"), heads
    # 「에」가 없는 자리도 후보다 — 「학교에 가는 길 물어보기 적어줘」에서
    # 「학교에 가는 길」이 아예 안 올라왔던 자리다.
    깊은 = order("학교에 가는 길 물어보기 적어줘")
    assert ("학교에 가는 길", "물어보기") in 깊은.alts, 깊은.alts

    got = order("장보기에 우유 추가")
    assert got and got.what == "덧붙이기" and got.target == "장보기"         and got.extra == "우유", got
    got = order("이번 주에 뭔 적었더라")
    assert got and got.what == "언제" and got.target.replace(" ", "") == "이번주", got

    # --- 2일차에 안 먹어서 적어 보내 준 여섯 ---
    # 규칙 둘이 보였다: 청유형 「~자」가 통째로 안 됐고, 조사 하나로 갈렸다
    # (「장보기랑 연결된 거」는 되는데 「장보기하고 이어진 거」는 안 됨).
    got = order("장보기 좀 보자")
    assert got and got.what == "열기" and got.target == "장보기", got
    got = order("새로 하나 만들자")
    assert got and got.what == "만들기", got
    got = order("장보기 지우자")
    assert got and got.what == "지우기" and got.target == "장보기", got
    got = order("오늘자 쓴 거 있어")
    assert got and got.what == "언제" and got.target == "오늘", got
    got = order("장보기를 장보기메모로 개명")
    assert got and got.what == "이름바꾸기" and got.target == "장보기"         and got.extra == "장보기메모", got
    got = order("장보기하고 이어진 거 있나")
    assert got and got.what == "이어진것" and got.target == "장보기", got

    # --- 지시가 **아닌** 말은 흘려보낸다. 여기가 제일 중요하다 ---
    # 검색칸이 곧 지시칸이라, 찾으려던 말이 지시로 읽히면 찾는 길이 막힌다.
    # 낯선 PC 가 실제로 쳐서 **여덟 개 전부 검색으로 갔다**고 확인해 준 것들이다.
    # 말끝을 넓힐 때마다 여기가 안 깨지는지 본다 — 넓히기와 이쪽은 서로 밀어낸다.
    for plain in ("고양이", "사진 보정 순서", "작년에 배포 엎었던 거",
                  "회의록", "무릎 아플 때", "김치찌개 끓이기", "",
                  "지우개", "만들기 어려운 것", "열대야", "찾기 힘든 자료",
                  "추가 요금", "태그 없는 글", "어제 날씨", "일지 쓰는 법",
                  "이름표", "지난주 회의", "보여주기식", "열대 과일",
                  # 「~자」를 받게 넓혔으니 이쪽이 흔들릴 수 있다. 같이 잰다.
                  "만들자고 한 것", "보자기", "지우자마자", "띄우자니 애매한 것",
                  "개명 신청", "있나 없나", "무르익은 것", "취소 수수료"):
        assert read_order(plain) is None, plain

    # **조사는 받침을 본다.** 「'회의록'을 '8월 회의록'로」 처럼 어긋나면
    # 말투가 제일 잘 만든 부분이라 더 눈에 띈다.
    assert josa("회의록", "을/를") == "회의록을"
    assert josa("장보기", "을/를") == "장보기를"
    assert josa("회의록", "으로/로") == "회의록으로"
    assert josa("마트", "으로/로") == "마트로"
    assert josa("VC", "을/를") == "VC를", josa("VC", "을/를")
    assert josa("", "을/를") == "를"
    assert tail("회의록", "을/를") == "을" and tail("마트", "으로/로") == "로"

    print("orders self-check 통과")


if __name__ == "__main__":
    _self_check()
