# -*- coding: utf-8 -*-
"""밖에서 파일을 험하게 만져도 견디나. 옵시디언·동기화 도구가 하는 일들."""
import os, shutil, sys
from pathlib import Path
뿌리 = Path(r"D:\프로젝트\비공개\1_EB")
일터 = 뿌리 / "시험기록" / "험한-작업"
if 일터.exists(): shutil.rmtree(일터)
(일터 / "data" / "notes").mkdir(parents=True)
os.environ["VC_DATA"] = str(일터)
sys.path.insert(0, str(뿌리 / "pc"))
from notes import Note, Notes
n = Notes(일터 / "data" / "notes", str(일터 / "색인.db"), index_now=False)
뿌 = 일터 / "data" / "notes"

def 재(무엇, 함수):
    try:
        값 = 함수()
        print(f"  {무엇:34s} 견딘다 ({값})")
    except Exception as e:
        print(f"  {무엇:34s} ★터진다 {type(e).__name__}: {str(e)[:50]}")

n.write(Note(title="멀쩡한 글", body="그냥 글이다."))
n.reindex()

# 1) 앞머리가 깨진 파일
(뿌 / "깨진 앞머리.md").write_text("---\n이건: [닫히지 않은\n---\n몸.\n", encoding="utf-8")
재("앞머리가 깨진 파일", lambda: n.reindex())

# 2) 빈 파일
(뿌 / "빈 파일.md").write_text("", encoding="utf-8")
재("빈 파일", lambda: n.reindex())

# 3) 앞머리만 있고 몸이 없는 파일
(뿌 / "몸 없음.md").write_text("---\nkind: \"note\"\n---\n", encoding="utf-8")
재("몸만 없는 파일", lambda: n.reindex())

# 4) 아주 깊은 폴더
깊 = 뿌 / "a" / "b" / "c" / "d" / "e" / "f"
깊.mkdir(parents=True)
(깊 / "깊은 글.md").write_text("깊이 있다.\n", encoding="utf-8")
재("아주 깊은 폴더", lambda: n.reindex())

# 5) 이름이 같은 글이 두 폴더에
(뿌 / "x").mkdir(); (뿌 / "y").mkdir()
(뿌 / "x" / "쌍둥이.md").write_text("첫째.\n", encoding="utf-8")
(뿌 / "y" / "쌍둥이.md").write_text("둘째.\n", encoding="utf-8")
재("같은 이름이 두 폴더에", lambda: (n.reindex(), len(n.search("쌍둥이", 5)))[1])

# 6) 글자가 깨진 파일 (cp949 로 쓴 것)
(뿌 / "깨진 글자.md").write_bytes("한글이 깨진다.\n".encode("cp949"))
재("cp949 로 쓴 파일", lambda: n.reindex())

# 7) 폴더가 .md 이름을 가진 경우
(뿌 / "폴더인데.md").mkdir()
재("폴더가 .md 이름", lambda: n.reindex())

print(f"\n  끝: 항목 {n.conn.execute('SELECT count(*) FROM notes').fetchone()[0]}개")
n.conn.close()
