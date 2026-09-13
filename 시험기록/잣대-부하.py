# -*- coding: utf-8 -*-
"""실무 부하 — 검색·쓰기를 되풀이하며 메모리와 응답 시간이 자라나."""
import json, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path
import subprocess
기록 = Path(r"D:\프로젝트\_빌드파일\VC-실무\기록")
토큰 = json.loads((기록 / "eb_config.json").read_text(encoding="utf-8"))["pair_token"]
def 부르기(길, 몸=None, 어떻게="GET"):
    데 = json.dumps(몸, ensure_ascii=False).encode() if 몸 is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:8765{길}", data=데, method=어떻게,
                                 headers={"Authorization": f"Bearer {토큰}",
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode()
def 메모리():
    out = subprocess.run(["powershell", "-NoProfile", "-Command",
                          "(Get-Process VC -ErrorAction SilentlyContinue | "
                          "Measure-Object WorkingSet64 -Sum).Sum"],
                         capture_output=True, text=True).stdout.strip()
    return int(out) // (1024 * 1024) if out.isdigit() else 0
물음 = [l.strip().partition("|")[0].strip() for l in Path(
    r"D:\프로젝트\비공개\1_EB\시험기록\잣대-물음-20260912.txt").read_text(encoding="utf-8").splitlines()
    if l.strip() and not l.startswith("#") and "|" in l]
print(f"처음 메모리 {메모리()}MB")
잰것 = []
for 바퀴 in range(1, 26):
    t = time.perf_counter()
    for q in 물음:
        부르기("/eb/v1/memory/search?q=" + urllib.parse.quote(q))
    부르기("/eb/v1/memory", {"title": f"부하 시험 {바퀴}", "text": f"{바퀴}번째 바퀴에 쓴 글이다."}, "POST")
    걸림 = time.perf_counter() - t
    잰것.append(걸림)
    if 바퀴 % 5 == 0 or 바퀴 == 1:
        print(f"  {바퀴}바퀴 · 21번 부름 {걸림:.2f}초 (한 번 {걸림/21*1000:.0f}ms) · 메모리 {메모리()}MB")
print(f"\n첫 바퀴 {잰것[0]:.2f}초 · 끝 바퀴 {잰것[-1]:.2f}초 · 느려진 비율 {잰것[-1]/잰것[0]:.2f}배")

# ★ 잰 뒤에는 치운다 — 실무 창고 사본에 「부하 시험 1~25」 가 남아 잣대를 흐리고 있었다(2026-09-13 26장 치움).
for 바퀴 in range(1, 26):
    부르기("/eb/v1/memory/delete", {"title": f"부하 시험 {바퀴}"}, "POST")
