# -*- coding: utf-8 -*-
"""실무 창고에서 덮어쓰기 보호를 잰다."""
import json, pathlib, time, urllib.error, urllib.request
기록 = pathlib.Path(r"D:\프로젝트\_빌드파일\VC-실무\기록")
토큰 = json.loads((기록 / "eb_config.json").read_text(encoding="utf-8"))["pair_token"]
def 부르기(길, 몸=None, 어떻게="GET"):
    데 = json.dumps(몸, ensure_ascii=False).encode() if 몸 is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:8765{길}", data=데, method=어떻게,
                                 headers={"Authorization": f"Bearer {토큰}",
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")

표 = f"손질{int(time.time())}"
제목 = f"덮기 시험 {int(time.time())}"
print("1) AI 가 쓴다:", 부르기("/eb/v1/memory", {"title": 제목, "text": "AI 가 처음 쓴 것."}, "POST")[0])
후보 = list((기록 / "data" / "notes").rglob(f"{제목}.md"))
print("2) 사람이 밖에서 고친다:", "파일 찾음" if 후보 else "★파일 못 찾음")
후보[0].write_text(후보[0].read_text(encoding="utf-8").rstrip()
                  + f"\n\n{표} 사람이 손으로 보탠 줄.\n", encoding="utf-8")
st, a = 부르기("/eb/v1/memory", {"title": 제목, "text": "통째로 갈아치운다.", "mode": "replace"}, "POST")
print(f"3) force 없이 덮기 → {st} · {json.dumps(a, ensure_ascii=False)[:100]}")
print(f"   사람 줄 살아 있나: {표 in 후보[0].read_text(encoding='utf-8')}")
st, b = 부르기("/eb/v1/memory", {"title": 제목, "text": "정말 갈아치운다.",
                                "mode": "replace", "force": True}, "POST")
되 = (b or {}).get("undo") or {}
있나 = 되.get("path") and pathlib.Path(되["path"]).is_file()
살았나 = 있나 and 표 in pathlib.Path(되["path"]).read_text(encoding="utf-8")
print(f"4) force 로 덮기 → {st} · undo {'있다' if 있나 else '★없다'} · 지난 판에 사람 줄 {'있다' if 살았나 else '★없다'}")
print(f"   undo: {json.dumps(되, ensure_ascii=False)[:150]}")

# ★ **잰 뒤에는 치운다.** 이 잣대는 실무 창고에 대고 도는데, 판마다 「덮기 시험 …」이
#   한 장씩 쌓였다 — 열두 장이 오너 기록에 섞여 있었다. `memory/delete` 가 생겼으니
#   그것으로 치운다(지우기 전에 한 판 남으므로 되돌릴 수 있다).
st, _ = 부르기("/eb/v1/memory/delete", {"title": 제목}, "POST")
print(f"5) 치우기 → {st} ({제목})")
