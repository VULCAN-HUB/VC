"""윈도우 offscreen 에서 `QMessageBox.show()` 가 죽는 것 — 비켜 갈 길 재기.

여기까지 잰 것:
  · 그냥 위젯 show / QDialog show·open        — 산다
  · QMessageBox 만들기 / 단추 붙이기           — 산다
  · **QMessageBox.show()**                     — 윈도우에서 죽는다 (맥은 산다)
  · 마우스 자리 · 화면 찾기                     — 셋 다 산다 (그 길이 아니다)
  · VC 전용 venv 로 갈아도 그대로. 윈도우용 Qt 는 5.15.2 가 끝이라 올릴 데가 없다.

`QMessageBox` 가 `QDialog` 와 다른 것은 뜰 때 **윈도우에서만 도는 코드**를
지난다는 점이다(시스템 메뉴·소리·접근성). 진짜 창이 없으면 거기서 넘어진다.

그래서 **화면에 붙이지 않고 속만 짜게** 해 본다(`WA_DontShowOnScreen`) —
머리 없이 대화창을 재는 표준 수법이다. 재는 것은 그대로 재고, 창만 안 뜬다.

    python tools/상자탐침.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import paths

paths.화면없이()
paths.pin_qt_plugins()

from PyQt5.QtCore import Qt                                   # noqa: E402
from PyQt5.QtWidgets import QApplication, QMessageBox         # noqa: E402

앱 = QApplication([])


def 재기(번호: str, 하기) -> None:
    print(f"{번호} 들어간다", flush=True)
    값 = 하기()
    앱.processEvents()
    print(f"{번호} 살았다 →", 값, flush=True)


def 상자(붙이지말까: bool, 여는법: str):
    def 하기():
        b = QMessageBox(QMessageBox.NoIcon, "t",
                        "<table cellspacing='0'><tr><td>Ctrl+O</td><td>연다</td></tr></table>",
                        QMessageBox.NoButton)
        b.setTextFormat(Qt.RichText)
        b.addButton("닫는다", QMessageBox.RejectRole)
        if 붙이지말까:
            b.setAttribute(Qt.WA_DontShowOnScreen, True)
        getattr(b, 여는법)()
        앱.processEvents()
        잰것 = (b.isVisible(), b.isModal(), b.sizeHint().width() > 0)
        b.close()
        return f"보이나={잰것[0]} 막나={잰것[1]} 크기잡혔나={잰것[2]}"
    return 하기


재기("1 안붙이고 show", 상자(True, "show"))
재기("2 안붙이고 open", 상자(True, "open"))
재기("3 그냥 show (죽을 자리)", 상자(False, "show"))

print("다 살았다", flush=True)
sys.stdout.flush()
os._exit(0)
