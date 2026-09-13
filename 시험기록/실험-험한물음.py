# -*- coding: utf-8 -*-
"""서버에 **험한 물음**을 던져 본다. 값이 아니라 **안 터지나·조용히 이상해지지 않나**를 본다."""
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

기록 = Path(__file__).resolve().parent.parent / "시험기록"
설정 = Path(r"D:\프로젝트\_빌드파일\VC-실무\기록\eb_config.json")
토큰 = json.loads(설정.read_text(encoding="utf-8"))["pair_token"]


def 부른다(길: str):
    req = urllib.request.Request("http://127.0.0.1:8765" + 길,
                                 headers={"Authorization": "Bearer " + 토큰})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")
    except Exception as e:
        return "X", f"{type(e).__name__}: {e}"


def 써보기():
    """쓰는 쪽 험한 입력. 터지나 · 조용히 이상해지나."""
    import urllib.request as U
    def 쓴다(몸):
        req = U.Request("http://127.0.0.1:8765/eb/v1/memory",
                        data=json.dumps(몸).encode("utf-8"), method="POST",
                        headers={"Authorization": "Bearer " + 토큰,
                                 "Content-Type": "application/json"})
        try:
            with U.urlopen(req, timeout=120) as r:
                return r.status, r.read().decode("utf-8")[:120]
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8")[:120]
        except Exception as e:
            return "X", f"{type(e).__name__}: {e}"

    것들 = [
        ("제목 없음", {"text": "몸만 있다"}),
        ("몸 없음", {"title": "몸 없는 글"}),
        ("제목이 숫자", {"title": 12345, "text": "숫자 제목"}),
        ("제목에 경로", {"title": "../../밖으로", "text": "나가나"}),
        ("제목에 널", {"title": "널\x00글자", "text": "널"}),
        ("아주 긴 제목", {"title": "길" * 500, "text": "짧다"}),
        ("본문이 리스트", {"title": "리스트 몸", "text": ["가", "나"]}),
        ("빈 제목", {"title": "   ", "text": "공백 제목"}),
    ]
    for 이름, 몸 in 것들:
        상태, 답 = 쓴다(몸)
        print(f"{str(상태):>3}  {이름:14} | {답[:90]}")
    # ★ 잰 뒤에는 치운다 — 이 시험은 실무 창고에 대고 돈다. 들어간 제목만 지운다.
    import urllib.request as U2
    for _, 몸 in 것들:
        제목 = 몸.get("title")
        if isinstance(제목, str) and 제목.strip():
            req = U2.Request("http://127.0.0.1:8765/eb/v1/memory/delete",
                             data=json.dumps({"title": 제목}).encode("utf-8"), method="POST",
                             headers={"Authorization": "Bearer " + 토큰, "Content-Type": "application/json"})
            try:
                U2.urlopen(req, timeout=30).read()
            except Exception:
                pass


def main() -> int:
    ㅈ = urllib.parse.quote
    for 길 in ["/eb/v1/memory/search?q=" + ㅈ("회의") + "&k=99999",
              "/eb/v1/memory/search?q=a&k=-1",
              "/eb/v1/memory/search?q=a&k=abc",
              "/eb/v1/memory/search?q=",
              "/eb/v1/memory/note?title=",
              "/eb/v1/memory/search?q=" + ㅈ("kind:"),
              "/eb/v1/memory/search?q=" + ㅈ('"안 닫은 따옴표'),
              "/eb/v1/memory/search?q=" + ㅈ("-kind:일 -kind:규칙 -kind:결정"),
              "/eb/v1/memory/search?q=" + ㅈ("가" * 3000),
              "/eb/v1/memory/note?title=" + ㅈ("없는 글") + "&heading=" + ㅈ("^없는칸"),
              ]:
        상태, 몸 = 부른다(길)
        보임 = 몸[:90].replace(chr(10), " ")
        print(f"{str(상태):>3} {len(몸):>6}자  {urllib.parse.unquote(길)[:52]:52} | {보임}")
    print()
    써보기()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


