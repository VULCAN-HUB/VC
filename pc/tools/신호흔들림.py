"""딴 실에서 쏜 신호를 주 실이 받다 죽는지 두들겨 본다 (한 번 쓰고 지울 것).

윈도우 CI 에서 `ui` 자체점검이 가끔 접근 위반으로 죽는다. 자국은 늘 같다 —
주 실이 `processEvents()` 로 신호를 꺼내는 순간이고, **신호를 쏜 실은 이미
자국에 없다**(쏘고 곧 끝났다). 그 짐작이 맞는지 여기서 두들겨 본다.

맥에서는 300번을 돌려도 안 죽었다.

    python tools/신호흔들림.py [몇번]
"""
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import paths

paths.화면없이()
paths.pin_qt_plugins()

from PyQt5.QtCore import QObject, pyqtSignal          # noqa: E402
from PyQt5.QtWidgets import QApplication              # noqa: E402

앱 = QApplication([])


class 집(QObject):
    # `query_done` 과 같은 꼴이다 — 글 둘 · 목록 하나 · 참거짓 하나
    done = pyqtSignal(str, str, list, bool)


받은 = []
집하나 = 집()
집하나.done.connect(lambda a, b, c, d: 받은.append(a))

몇 = int(sys.argv[1]) if len(sys.argv) > 1 else 300
for i in range(몇):
    def 일(n=i):
        집하나.done.emit(f"물음{n}", "답", ["회의록"], False)
    threading.Thread(target=일, daemon=True).start()   # 쏘고 곧 끝나는 실
    앱.processEvents()
    time.sleep(0.002)

끝 = time.monotonic() + 10
while len(받은) < 몇 and time.monotonic() < 끝:
    앱.processEvents()
    time.sleep(0.005)

print(f"{len(받은)}/{몇} 받았다", flush=True)
sys.stdout.flush()
os._exit(0)
