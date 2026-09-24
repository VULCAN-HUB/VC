"""윈도우 offscreen 에서 `QMessageBox.show()` 가 죽는 자리 찾기 (한 번 쓰고 지울 것).

계단마다 **먼저 찍고** 실행한다 — 접근 위반은 자국을 안 남기므로
마지막으로 찍힌 번호가 죽인 조각이다.

여기까지 잰 것:
  · 그냥 위젯 show / QDialog show / QDialog open  — 다 산다
  · QMessageBox 만들기 / 단추 붙이기              — 다 산다
  · **QMessageBox.show()**                        — 윈도우에서 죽는다 (맥은 산다)
  · 맥 Qt 5.15.14 · 윈도우 Qt 5.15.2 (PyQt 는 둘 다 5.15.11)

`QMessageBox` 가 `QDialog` 와 다르게 하는 일: 뜰 때 제 크기를 맞추려고
**마우스가 어느 화면에 있는지** 묻는다. offscreen 판에는 마우스가 없다.

    python tools/상자탐침.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import paths

paths.화면없이()
paths.pin_qt_plugins()

from PyQt5.QtCore import PYQT_VERSION_STR, QT_VERSION_STR, QLibraryInfo   # noqa: E402
from PyQt5.QtGui import QCursor, QGuiApplication                          # noqa: E402
from PyQt5.QtWidgets import QApplication, QMessageBox                     # noqa: E402

print("Qt", QT_VERSION_STR, "· PyQt", PYQT_VERSION_STR, flush=True)
print("Qt 어디서", QLibraryInfo.location(QLibraryInfo.LibrariesPath), flush=True)

앱 = QApplication([])
print("으뜸화면", QGuiApplication.primaryScreen(), flush=True)


def 재기(번호: str, 하기) -> None:
    print(f"{번호} 들어간다", flush=True)
    값 = 하기()
    앱.processEvents()
    print(f"{번호} 살았다", "→", 값, flush=True)


def 마우스자리():
    return QCursor.pos()


def 마우스화면():
    return QGuiApplication.screenAt(QCursor.pos())


def 으뜸자리():
    return QGuiApplication.primaryScreen().availableGeometry()


def 상자보이기():
    b = QMessageBox(QMessageBox.NoIcon, "t", "그냥 글", QMessageBox.NoButton)
    b.addButton("닫는다", QMessageBox.RejectRole)
    b.show()
    앱.processEvents()
    b.close()
    return "떴다"


def 상자이전에화면고정():
    """마우스를 먼저 한 번 물어 본 뒤에 띄우면 사는지."""
    QGuiApplication.screenAt(QCursor.pos())
    b = QMessageBox(QMessageBox.NoIcon, "t", "그냥 글", QMessageBox.NoButton)
    b.addButton("닫는다", QMessageBox.RejectRole)
    b.show()
    앱.processEvents()
    b.close()
    return "떴다"


재기("1 마우스 자리", 마우스자리)
재기("2 마우스가 있는 화면", 마우스화면)
재기("3 으뜸화면 크기", 으뜸자리)
재기("4 상자 show", 상자보이기)
재기("5 화면 먼저 묻고 상자 show", 상자이전에화면고정)

print("다 살았다", flush=True)
sys.stdout.flush()
os._exit(0)
