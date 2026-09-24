"""단축키 상자가 윈도우 offscreen 에서 죽는 자리 찾기 (한 번 쓰고 지울 것).

접근 위반은 파이썬 자국을 안 남기고 프로세스를 죽인다. 그래서 **한 계단마다
먼저 찍고** 실행한다 — 마지막으로 찍힌 번호가 죽인 조각이다.

    python tools/상자탐침.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import paths
import theme

paths.화면없이()
paths.pin_qt_plugins()

from PyQt5.QtCore import Qt                                    # noqa: E402
from PyQt5.QtWidgets import QApplication, QMessageBox, QWidget  # noqa: E402

앱 = QApplication([])


def 재기(번호: str, 글: str, 서식: bool, 부모: bool, 단추: bool) -> None:
    print(f"{번호} 들어간다", flush=True)
    어미 = QWidget() if 부모 else None
    if 어미:
        어미.show()
    상자 = QMessageBox(QMessageBox.NoIcon, "단축키", 글, QMessageBox.NoButton, 어미)
    if 서식:
        상자.setTextFormat(Qt.RichText)
    if 단추:
        상자.addButton("닫는다", QMessageBox.RejectRole)
    상자.open()
    앱.processEvents()
    상자.close()
    앱.processEvents()
    print(f"{번호} 살았다", flush=True)


표 = "<table cellspacing='0'><tr><td>Ctrl+O</td><td>연다</td></tr></table>"
꾸민표 = ("<table cellspacing='0'><tr>"
        "<td style='padding:3px 18px 3px 0; color:#7aa2f7; font-family:" + theme.MONO + ";'>Ctrl+O ＼</td>"
        "<td style='padding:3px 0; color:#c0caf5;'>연다</td></tr></table>")

재기("1 민글·부모없음", "그냥 글", False, False, True)
재기("2 표·부모없음", 표, True, False, True)
재기("3 표·부모있음", 표, True, True, True)
재기("4 꾸민표·부모있음", 꾸민표, True, True, True)
재기("5 꾸민표·단추없음", 꾸민표, True, True, False)

# ★ 없는 글꼴 이름만 대면 Qt 가 **별명 목록을 통째로 뒤진다**(`Populating font family
#   aliases`). 윈도우 offscreen 에서 거기가 터지는지 따로 잰다.
없는것 = ("<table cellspacing='0'><tr><td style='font-family:"
       '"Apple SD Gothic Neo", "Menlo", monospace'
       "'>Ctrl+O</td><td>연다</td></tr></table>")
재기("6 없는글꼴만", 없는것, True, True, True)
print("MONO =", theme.MONO, flush=True)

print("다 살았다 — 상자가 아니다", flush=True)
sys.stdout.flush()
os._exit(0)
