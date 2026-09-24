"""합치기(Compile) — `raw/` 를 읽어 `wiki/` 쪽을 만든다. 화면은 안 쓴다.

카파시 LLM Wiki 의 둘째 일이다. 사람은 **모으기만** 하고, 원본에서 쓸 것을 건져
서로 이어 주는 일은 여기서 한다.

★★ **손을 갈아 끼울 수 있게 한 문으로 받는다**(오너 2026-09-20: 「로컬이 1차, 큰 정리와
   검토는 클로드가, 추후 더 좋은 모델이 가능해지면 로컬에서」). 이 파일은 **누가 답하는지
   모른다** — `부르기(말들) -> 글` 하나만 받는다. 로컬 `qwen3-8b` 든 바깥 AI 든 같은 얼굴이다.
   `ai_fill.py` 가 이미 그 결이라 그대로 따랐다.

★★ **원본은 안 고친다.** raw 는 진실의 원천이라 손대지 않는다 — 「합쳤다」 표시는
   앱 자리 `vc-합쳤다.json` 에만 둔다(`ai_fill` 과 같은 규칙, 결정 17).

★ **모델이 없으면 조용히 아무것도 안 한다.** 1차가 없다고 창고가 멈추면 안 된다.

1차(로컬)가 하는 것은 **요점 · 갈래 · 태그 · 이어질 이름**까지다. 엔티티·개념 쪽을 지어
서로 잇는 **큰 정리**는 같은 문에 더 좋은 손을 끼워 돌린다 — 이어질 이름은 `[[이름]]` 으로
적어 두므로, 아직 없는 것은 VC 의 「아직 없는 것」 칸에 그대로 뜬다.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Callable

import paths
import wiki
from notes import Note, Notes, parse_links

메모 = "vc-합쳤다.json"
한바퀴 = 3          # 한 번에 몇 장. 많이 잡으면 모델이 오래 돌아 화면이 굳는다

# ★★ **`/no_think` 를 붙인다.** 로컬 `qwen3` 는 추론 모델이라 `<think>` 로 답 길이를
#   통째로 써 버린다 — 실측: 400토큰 안에서 생각만 하다 끝나 **JSON 이 아예 안 나왔다**
#   (21초 쓰고 건너뜀). 끄면 **5초에 JSON 이 나온다.** qwen 이 아닌 손에게는 그냥 글자라
#   해롭지 않다.
_생각끄기 = " /no_think"

프롬프트 = """너는 개인 위키를 정리한다. 아래는 사람이 모아 둔 **원본** 하나다.
읽고 **JSON 하나만** 답해라. 설명도 인사도 하지 마라.

꼴(이 예시를 그대로 베끼지 말고, 원본을 읽고 채워라):

{"요점": "클로드 3.5 소네트가 나왔다. 코딩과 시각 추론이 좋아지고 속도가 두 배다.",
 "갈래": "개념",
 "태그": ["AI", "모델"],
 "이어질것": ["앤트로픽", "코딩 도구"]}

규칙:
- 요점은 세 줄 안쪽. 원본을 안 읽어도 무슨 이야기인지 알게 적는다.
- 갈래는 **다음 중 하나만** 골라 그대로 적는다: 개념 · 결정 · 오류 · 작업 · 규칙 · 설계 · 엔티티
- 태그는 원본에 실제로 나온 낱말 두셋. 없으면 빈 목록.
- 이어질것은 이 글과 묶일 만한 **이름** 두셋(사람·물건·프로젝트·주제). 없으면 빈 목록.
- 모르면 빈 값으로 둬라. **지어내지 마라.**""" + _생각끄기


#  모델이 프롬프트 글자를 그대로 베끼는 일이 있다 — 실측으로 `태그: ["한글 낱말 두셋"]`,
#  `갈래: "기술 | 엔티티"` 가 나왔다.
#  ★ 거르는 것은 **설명문 조각**뿐이다. 예시에 쓴 낱말(`AI`·`모델`)까지 버리면
#    **진짜 쓸 만한 태그를 잃는다** — 그건 예시를 잘못 고른 내 탓이지 모델 탓이 아니다.
#    예시를 **통째로** 베낀 경우만 따로 버린다.
_설명말 = ("낱말", "두셋", "빈 목록", "이 예시", "예시를", "지어내지")
_예시태그 = ["AI", "모델"]
_예시이어질 = ["앤트로픽", "코딩 도구"]


def _지문(글: str) -> str:
    return hashlib.blake2b(" ".join(글.split()).encode("utf-8"), digest_size=16).hexdigest()


def _적어둔것(어디: Path | None = None) -> dict:
    어디 = 어디 or paths.기계자리(메모)
    try:
        난것 = json.loads(어디.read_text(encoding="utf-8"))
        return 난것 if isinstance(난것, dict) else {}
    except (OSError, ValueError):
        return {}


def _적기(값: dict, 어디: Path | None = None) -> None:
    어디 = 어디 or paths.기계자리(메모)
    try:
        어디.parent.mkdir(parents=True, exist_ok=True)
        어디.write_text(json.dumps(값, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass          # 못 적어도 멈출 이유가 없다 — 다음에 다시 합칠 뿐이다


def 원본들(창고: Notes) -> list[str]:
    """`raw/` 층에 있는 글 제목들. 최근 것부터."""
    낸다 = []
    for 줄 in 창고.conn.execute("SELECT title, path FROM notes ORDER BY created DESC"):
        자리 = Path(줄["path"])
        try:
            첫칸 = 자리.relative_to(창고.root).parts[0]
        except ValueError:
            continue
        if 첫칸 == wiki.RAW:
            낸다.append(줄["title"])
    return 낸다


def 이미이어진것(창고: Notes) -> set[str]:
    """**wiki 쪽이 이미 가리키는 원본**들. 그 원본은 누군가 합쳐 놓은 것이다.

    ★★ 제목 규칙(`… 요점`)만 보면 안 된다. **더 좋은 손이 지은 쪽은 제 이름을 갖는다** —
       실제로 그랬다: 큰 정리가 「에이전트와 워크플로를 가르는 기준」을 지어 원본을 가리켰는데,
       1차가 그것을 못 보고 **같은 원본으로 요약을 하나 더 만들었다.** 한 원본에 요약이 둘이 된다.
    """
    낸다 = set()
    for 줄 in 창고.conn.execute("SELECT src, dst FROM links"):
        가리킨 = 창고.read(줄["dst"])
        if 가리킨 is None or 가리킨.kind != wiki.원본갈래:
            continue
        # ★ **제가 지은 요약은 「남」이 아니다.** 원본 제 자신도 아니다.
        #   이 둘을 안 빼면 한 번 합친 원본은 **바뀌어도 영영 다시 안 합친다**.
        if 줄["src"] in (가리킨.title, 요약제목(가리킨.title)):
            continue
        낸다.add(가리킨.title)
    return 낸다


def 아직안한것(창고: Notes, 몇: int = 한바퀴, 어디: Path | None = None) -> list[str]:
    """아직 안 합친 원본. **몸이 그대로면 다시 안 합친다** — 두 번 돌려도 같은 결과다."""
    적힌 = _적어둔것(어디)
    이어진 = 이미이어진것(창고)
    낸다 = []
    for 제목 in 원본들(창고):
        글 = 창고.read(제목)
        if 글 is None:
            continue
        if 적힌.get(제목) == _지문(글.body):
            continue
        if 제목 in 이어진:
            continue          # 더 좋은 손이 이미 합쳤다 — 요약을 둘로 만들지 않는다
        낸다.append(제목)
        if len(낸다) >= 몇:
            break
    return 낸다


def _json풀기(답: str) -> dict | None:
    """모델 답에서 JSON 하나를 꺼낸다. 앞뒤에 말이 붙어 와도 건진다."""
    글 = re.sub(r"(?s)<think>.*?</think>", "", 답 or "").strip()
    글 = re.sub(r"^```(?:json)?|```$", "", 글.strip(), flags=re.M).strip()
    시작 = 글.find("{")
    if 시작 < 0:
        return None
    깊이 = 0
    for i in range(시작, len(글)):
        if 글[i] == "{":
            깊이 += 1
        elif 글[i] == "}":
            깊이 -= 1
            if 깊이 == 0:
                try:
                    난것 = json.loads(글[시작:i + 1])
                except ValueError:
                    return None
                return 난것 if isinstance(난것, dict) else None
    return None


def 한장(부르기: Callable[[list[dict]], str], 글: Note) -> dict:
    """원본 한 장을 묻는다. 못 알아들으면 빈 dict."""
    답 = _json풀기(부르기([
        {"role": "system", "content": 프롬프트},
        {"role": "user", "content": f"제목: {글.title}\n\n{글.body[:3000]}" + _생각끄기},
    ]))
    if not 답:
        return {}
    요점 = str(답.get("요점") or "").strip()
    if not 요점:
        return {}          # 요점이 없으면 쪽을 만들 것이 없다
    갈래 = str(답.get("갈래") or "").strip()
    if not wiki.아는갈래(갈래) or 갈래 == wiki.원본갈래:
        갈래 = "개념"      # 모르는 갈래를 그대로 쓰면 창고에 없는 말이 쌓인다
    def 고르기(키: str, 예시: list[str]) -> list[str]:
        난것 = []
        for x in (답.get(키) or []):
            말 = str(x).strip().lstrip("#").strip()
            # 설명문 조각은 값이 아니다 — 안 버리면 창고가 프롬프트 글자로 덮인다
            if 말 and not any(b in 말 for b in _설명말):
                난것.append(말)
        # 예시를 **통째로** 베꼈으면 버린다(하나만 겹치는 것은 진짜일 수 있다)
        if 난것[:len(예시)] == 예시:
            return []
        return 난것[:3]

    return {"요점": 요점, "갈래": 갈래,
            "태그": 고르기("태그", _예시태그), "이어질것": 고르기("이어질것", _예시이어질)}


def 요약제목(원본제목: str) -> str:
    return f"{원본제목} 요점"


def 요약글(원본제목: str, 난것: dict) -> str:
    """출처요약 쪽의 몸. **원본으로 되돌아가는 링크**를 반드시 단다."""
    줄 = [난것["요점"], "", f"원본: [[{원본제목}]]"]
    이어질 = [x for x in 난것.get("이어질것", []) if x != 원본제목]
    if 이어질:
        줄 += ["", "이어질 것: " + " · ".join(f"[[{x}]]" for x in 이어질)]
    태그 = 난것.get("태그") or []
    if 태그:
        줄 += ["", " ".join(f"#{t.lstrip('#')}" for t in 태그)]
    return chr(10).join(줄) + chr(10)


_원본줄 = re.compile(r"(?m)^\s*원본\s*:\s*(.+)$")


def 원본선언(몸: str) -> set[str]:
    """이 쪽이 「**내 원본은 이것**」이라고 밝힌 것들.

    `요약글()` 이 반드시 다는 `원본: [[…]]` 줄을 읽는다. 사람이 손으로 쓴 쪽도 같은
    줄을 쓰므로 **누가 지었든 같은 표시**다.

    ★ 그냥 원본을 **가리키기만** 하는 것(엮음 글의 「읽은 것」 목록)과 다르다.
      그 둘을 안 가르면 엮음 글 하나가 원본 여섯을 「내가 요약했다」고 주장하게 된다.
    """
    낸다 = set()
    for m in _원본줄.finditer(몸 or ""):
        for 이름, _ in parse_links(m.group(1)):
            낸다.add(이름)
    return 낸다


def 합치기(창고: Notes, 부르기: Callable[[list[dict]], str] | None,
         몇: int = 한바퀴, 어디: Path | None = None,
         적기: Callable[[str], None] | None = None) -> dict:
    """안 합친 원본 몇 장을 읽어 `wiki/` 에 **출처요약** 쪽을 만든다.

    돌려주는 것: `{"만든것": [...], "건너뛴것": [...]}`.
    `적기` 를 주면 한 장마다 한 줄 남긴다(log).
    """
    if 부르기 is None:
        return {"만든것": [], "건너뛴것": [], "왜": "모델이 없다"}
    만든것, 건너뛴것 = [], []
    적힌 = _적어둔것(어디)
    for 제목 in 아직안한것(창고, 몇, 어디):
        글 = 창고.read(제목)
        if 글 is None:
            continue
        try:
            난것 = 한장(부르기, 글)
        except Exception:
            건너뛴것.append(제목)      # 한 장이 터져도 나머지는 합친다
            continue
        # **못 알아들은 것도 적어 둔다** — 안 적으면 같은 원본을 영영 다시 묻는다
        적힌[제목] = _지문(글.body)
        if not 난것:
            건너뛴것.append(제목)
            continue
        쪽제목 = 요약제목(제목)
        창고.write(Note(title=쪽제목, body=요약글(제목, 난것), kind=난것["갈래"],
                       extra={"출처": "VC", "상태": "살아있음"}))
        만든것.append(쪽제목)
        if 적기 is not None:
            적기(f"합치기 · {제목} → {쪽제목} ({난것['갈래']})")
    _적기(적힌, 어디)
    return {"만든것": 만든것, "건너뛴것": 건너뛴것}


def _self_check() -> None:
    import tempfile

    # JSON 풀기 — 모델은 앞뒤에 말을 붙이고 코드울타리를 친다
    assert _json풀기('{"요점": "가"}') == {"요점": "가"}
    assert _json풀기('여기 있습니다:\n```json\n{"요점":"나"}\n```\n끝') == {"요점": "나"}
    assert _json풀기("<think>음</think>{\"요점\":\"다\"}") == {"요점": "다"}
    assert _json풀기("JSON 못 만들겠다") is None
    assert _json풀기('{"깨진": ') is None
    # 안쪽 중괄호가 있어도 한 덩이로 건진다
    assert _json풀기('{"a": {"b": 1}} 뒤에 말')["a"] == {"b": 1}

    with tempfile.TemporaryDirectory() as tmp:
        창고 = Notes(Path(tmp) / "notes")
        표 = Path(tmp) / 메모
        원본 = Note(title="링크 · example.com", body="- https://example.com/a\n기사 몸",
                   kind=wiki.원본갈래)
        창고.write(원본)
        창고.write(Note(title="내가 적은 것", body="이건 원본이 아니다", kind="메모"))

        assert 원본들(창고) == ["링크 · example.com"], 원본들(창고)
        원본몸 = 창고.read("링크 · example.com").body      # 저장된 꼴(끝 줄바꿈이 붙는다)
        assert 아직안한것(창고, 어디=표) == ["링크 · example.com"]

        부른것 = []

        def 가짜(말들):
            부른것.append(말들)
            return ('앞말 {"요점": "예제 사이트 소개", "갈래": "개념", '
                    '"태그": ["시험", "#예제"], "이어질것": ["example", "링크 · example.com"]} 뒷말')

        난것 = 합치기(창고, 가짜, 어디=표)
        assert 난것["만든것"] == ["링크 · example.com 요점"], 난것
        # ★ **생각 끄기가 붙어야 한다.** 로컬 qwen3 는 추론 모델이라 `<think>` 로 답 길이를
        #   다 써 버린다 — 실측: 400토큰 안에서 생각만 하다 끝나 JSON 이 아예 안 나왔다
        #   (21초 쓰고 건너뜀). 붙이면 5초에 나온다. 그래서 **붙었는지 직접 잰다.**
        보낸말 = " ".join(m["content"] for m in 부른것[0])
        assert "/no_think" in 보낸말, "생각 끄기가 안 붙었다 — 로컬 모델이 답을 못 낸다"
        쪽 = 창고.read("링크 · example.com 요점")
        assert 쪽 is not None and 쪽.kind == "개념", 쪽
        # ★ **원본으로 되돌아가는 링크**가 있어야 한다 — 요약만 남으면 근거를 잃는다
        assert "[[링크 · example.com]]" in 쪽.body, 쪽.body
        assert "#시험" in 쪽.body and "##" not in 쪽.body, 쪽.body
        # 자기 자신은 「이어질 것」에서 뺀다
        assert 쪽.body.count("[[링크 · example.com]]") == 1, 쪽.body
        assert "[[example]]" in 쪽.body
        # 요약 쪽은 **wiki 층**에 간다
        자리 = 창고.path_of(쪽.title).relative_to(창고.root).as_posix()
        assert 자리.startswith(wiki.WIKI + "/"), 자리
        # ★ **원본은 안 고친다** — raw 는 진실의 원천이다
        assert 창고.read("링크 · example.com").body == 원본몸, "합치면서 원본을 고쳤다"

        # ★ **제가 지은 요약은 「남이 합친 것」이 아니다.** 이걸 안 빼면 한 번 합친 원본은
        #   바뀌어도 영영 다시 안 합쳐진다(실제로 밟았다).
        assert 이미이어진것(창고) == set(), 이미이어진것(창고)

        # ★★ **두 번 돌려도 같은 결과다.** 안 그러면 돌 때마다 같은 요약이 쌓인다.
        assert 아직안한것(창고, 어디=표) == []
        assert 합치기(창고, 가짜, 어디=표)["만든것"] == []
        assert len(부른것) == 1, f"같은 원본을 다시 물었다: {len(부른것)}"

        # ★★ **누가 이미 합쳤으면 또 안 한다.** 큰 정리가 제 이름으로 쪽을 지어 원본을
        #   가리키면, 1차는 그것을 보고 비켜야 한다 — 안 그러면 한 원본에 요약이 둘이 된다
        #   (실제로 그랬다: 내가 지은 쪽과 로컬이 지은 「… 요점」이 겹쳤다).
        표7 = Path(tmp) / "일곱째.json"
        창고.write(Note(title="딴 이름 요약", body="요점만 적는다.\n\n원본: [[링크 · example.com]]",
                       kind="개념"))
        창고.reindex()
        assert "링크 · example.com" in 이미이어진것(창고)
        assert 아직안한것(창고, 어디=표7) == [], "이미 합쳐진 원본을 또 합치려 한다"
        assert 합치기(창고, 가짜, 어디=표7)["만든것"] == []
        창고.delete("딴 이름 요약")
        창고.reindex()

        # 원본이 바뀌면 **다시 합친다**
        바뀐 = 창고.read("링크 · example.com")
        바뀐.body += "\n- https://example.com/b"
        창고.write(바뀐)
        assert 아직안한것(창고, 어디=표) == ["링크 · example.com"]

        # ★ 모델이 못 알아들어도 **다시 안 묻는다** — 안 적으면 영영 같은 것을 묻는다
        표2 = Path(tmp) / "둘째.json"
        헛소리 = lambda 말들: "무슨 말인지 모르겠다"
        난것2 = 합치기(창고, 헛소리, 어디=표2)
        assert 난것2["만든것"] == [] and 난것2["건너뛴것"] == ["링크 · example.com"], 난것2
        assert 아직안한것(창고, 어디=표2) == [], "못 알아들은 원본을 또 묻는다"

        # 모델이 없으면 조용히 아무것도 안 한다
        표3 = Path(tmp) / "셋째.json"
        assert 합치기(창고, None, 어디=표3)["만든것"] == []
        assert not 표3.exists(), "모델도 없는데 파일을 만들었다"

        # ★ **프롬프트를 베낀 값은 안 받는다**(실측으로 `태그: ["한글 낱말 두셋"]` 이 나왔다).
        표5 = Path(tmp) / "다섯째.json"
        베낌 = lambda 말들: ('{"요점": "가", "갈래": "개념", "태그": ["한글 낱말 두셋", "진짜태그"], '
                          '"이어질것": ["앤트로픽", "코딩 도구"]}')
        합치기(창고, 베낌, 어디=표5)
        벤것 = 창고.read("링크 · example.com 요점")
        assert "한글 낱말" not in 벤것.body, 벤것.body
        assert "진짜태그" in 벤것.body, "베낀 말만 버려야 하는데 진짜 태그까지 버렸다"
        assert "앤트로픽" not in 벤것.body, "예시를 통째로 베낀 것을 받았다"
        # ★ 예시에 쓴 낱말이라도 **하나만 겹치면 진짜일 수 있다** — 버리지 않는다
        표6 = Path(tmp) / "여섯째.json"
        진짜 = lambda 말들: '{"요점": "나", "갈래": "개념", "태그": ["AI", "속도"], "이어질것": []}'
        합치기(창고, 진짜, 어디=표6)
        assert "#AI" in 창고.read("링크 · example.com 요점").body, "쓸 만한 태그를 버렸다"

        # 모르는 갈래를 답해도 **창고에 없는 말이 쌓이지 않는다**
        표4 = Path(tmp) / "넷째.json"
        엉뚱 = lambda 말들: '{"요점": "가", "갈래": "우주선", "태그": [], "이어질것": []}'
        합치기(창고, 엉뚱, 어디=표4)
        assert 창고.read("링크 · example.com 요점").kind == "개념"

        창고.conn.close()

    print("synth self-check 통과")


if __name__ == "__main__":
    import sys

    if "--check" in sys.argv:
        _self_check()
