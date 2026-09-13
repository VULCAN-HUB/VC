# -*- coding: utf-8 -*-
"""두 모델이 무엇을 갈라 찾나 — 합치면 몇 개인가."""
import sys
from pathlib import Path
뿌리 = Path(r"D:\프로젝트\비공개\1_EB"); sys.path.insert(0, str(뿌리 / "pc"))
from brain import onnx_embedder
from notes import EMBED_TOKENS, Notes
일터 = 뿌리 / "시험기록" / "꺼내기-작업"
물음들 = []
for l in (뿌리 / "시험기록" / "잣대-물음-20260912.txt").read_text(encoding="utf-8").splitlines():
    l = l.strip()
    if l and not l.startswith("#") and "|" in l:
        q, _, a = (x.strip() for x in l.partition("|"))
        물음들.append((q, [t.strip() for t in a.split(";") if t.strip()]))
찾은것 = {}
for 이름, 색인, 모델 in (("작은", "색인.db", "models"), ("큰", "큰모델.db", "models/e5-base")):
    n = Notes(일터 / "data" / "notes", str(일터 / 색인), index_now=False)
    n.use_embedder(onnx_embedder(뿌리 / 모델, max_tokens=EMBED_TOKENS))
    찾은것[이름] = {q for q, 정답들 in 물음들
                   if any(a in [r["title"] for r in n.search(q, 5)] for a in 정답들)}
    n.conn.close()
작, 큰 = 찾은것["작은"], 찾은것["큰"]
print(f"  작은 모델 {len(작)}/20 · 큰 모델 {len(큰)}/20 · 합치면 {len(작 | 큰)}/20")
print(f"  둘 다 찾음 {len(작 & 큰)}개")
print(f"  작은 것만 찾음 {len(작 - 큰)}개:")
for q in sorted(작 - 큰): print(f"    - {q[:40]}")
print(f"  큰 것만 찾음 {len(큰 - 작)}개:")
for q in sorted(큰 - 작): print(f"    + {q[:40]}")
