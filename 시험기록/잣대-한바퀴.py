# -*- coding: utf-8 -*-
"""구운 판 한 바퀴 — AI 가 실무에서 하는 일 전부."""
import json, urllib.error, urllib.parse, urllib.request
from pathlib import Path
기록 = Path(r"D:\프로젝트\_빌드파일\VC-실무\기록")
토큰 = json.loads((기록 / "eb_config.json").read_text(encoding="utf-8"))["pair_token"]
쓴 = [0]
def 부르기(길, 몸=None, 어떻게="GET"):
    데 = json.dumps(몸, ensure_ascii=False).encode() if 몸 is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:8765{길}", data=데, method=어떻게,
                                 headers={"Authorization": f"Bearer {토큰}",
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            글, 코드 = r.read().decode(), r.status
    except urllib.error.HTTPError as e:
        글, 코드 = e.read().decode(), e.code
    쓴[0] += len(글) + (len(데) if 데 else 0)
    return 코드, (json.loads(글) if 글 else {})
def Q(s): return urllib.parse.quote(s)

st, hello = 부르기("/eb/v1/hello")
print(f"1) 인사 {st} · {len(json.dumps(hello, ensure_ascii=False))}자 · 갈래 "
      f"{json.dumps(hello.get('store',{}).get('kinds'), ensure_ascii=False)}")
물음 = [l.strip().partition("|") for l in Path(
    r"D:\프로젝트\비공개\1_EB\시험기록\잣대-물음-20260912.txt").read_text(encoding="utf-8").splitlines()
    if l.strip() and not l.startswith("#") and "|" in l]
찾음 = 글자 = 0
for q, _, a in 물음:
    q = q.strip(); 정답들 = [t.strip() for t in a.split(";") if t.strip()]
    앞 = 쓴[0]; st, f = 부르기("/eb/v1/memory/search?q=" + Q(q)); 글자 += 쓴[0] - 앞
    if any(x in [r["title"] for r in f["results"]] for x in 정답들): 찾음 += 1
print(f"2) 찾기 20물음 · 1단 평균 {글자 // len(물음)}자 · 찾음 {찾음}/20")
앞 = 쓴[0]; st, b = 부르기("/eb/v1/memory/search?brief=1&k=60&q=" + Q("kind:결정"))
print(f"3) 목록 훑기 brief=1 k=60 · {st} · {len(b['results'])}장 · {쓴[0]-앞}자")
앞 = 쓴[0]; st, b2 = 부르기("/eb/v1/memory/search?k=60&q=" + Q("kind:결정"))
print(f"   같은 것 brief 없이 · {쓴[0]-앞}자")
긴 = next((r["title"] for r in b2["results"] if r.get("chars", 0) > 1000), None)
if 긴:
    앞 = 쓴[0]; st, t1 = 부르기("/eb/v1/memory/note?title=" + Q(긴))
    통 = 쓴[0] - 앞
    앞 = 쓴[0]; st, t2 = 부르기("/eb/v1/memory/note?title=" + Q(긴) + "&q=" + Q("모델 엔진 결정"))
    print(f"4) 긴 글 「{긴[:20]}」 통째 {통}자 · q= 둘레 {쓴[0]-앞}자 · 잘랐나 {t2.get('cut')}")
import time as _t
표 = f"잠수함 시험 {int(_t.time())}"
앞 = 쓴[0]; st, w = 부르기("/eb/v1/memory", {"title": "실무 확인 글",
    "text": f"{표} — 안개 속 등대가 선박을 인도한다."}, "POST")
# 쓴 그 문장으로 묻는다 — **벡터가 반영됐나**만 잰다(뜻 거리 실력은 위 20물음이 잰다)
st, f = 부르기("/eb/v1/memory/search?q=" + Q(표))
찾 = [r["title"] for r in f["results"]]
print(f"5) 쓰고 바로 뜻으로 찾기 · {'찾음' if '실무 확인 글' in 찾 else '★못 찾음'} · {쓴[0]-앞}자")
print(f"\n★ 전체 {쓴[0]}자")# ★ **잰 뒤에는 치운다.** 판마다 「실무 확인 글」이 오너 기록에 남아 자란다.

# ★ 잰 뒤에는 치운다 — 판마다 「실무 확인 글」이 오너 기록에 남아 자란다.
부르기("/eb/v1/memory/delete", {"title": "실무 확인 글"}, "POST")

print(f"\n★ 전체 {쓴[0]}자")
