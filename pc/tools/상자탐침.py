"""단축키 상자가 윈도우 offscreen 에서 죽는 자리 찾기 (한 번 쓰고 지울 것).

접근 위반은 파이썬 자국을 안 남기고 프로세스를 죽인다. 그래서 **한 계단마다
먼저 찍고** 실행한다 — 마지막으로 찍힌 번호가 죽인 조각이다.

1차에서 「민글·부모없음」이 죽었다. 표도 글꼴도 아니고 상자를 **여는 것** 자체다.
그래서 더 잘게 나눈다: 창을 보이는 것 / `show()` 와 `open()` / 상자와 그냥 대화창.

    python tools/상자탐침.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import paths
import theme

paths.화면없이()
paths.pin_qt_plugins()

from PyQt5.QtCore import QT_VERSION_STR, Qt                              # noqa: E402
from PyQt5.QtCore import PYQT_VERSION_STR                                # noqa: E402
from PyQt5.QtWidgets import (QApplication, QDialog, QMessageBox,         # noqa: E402
                             QPushButton, QWidget)

print("Qt", QT_VERSION_STR, "· PyQt", PYQT_VERSION_STR, flush=True)
print("화면판", os.environ.get("QT_QPA_PLATFORM"), "· 글꼴자리", os.environ.get("QT_QPA_FONTDIR"), flush=True)

앱 = QApplication([])
print("화면들", [(s.name(), s.size().width(), s.size().height()) for s in 앱.screens()], flush=True)
print("MONO", theme.MONO, flush=True)


def 재기(번호: str, 하기) -> None:
    print(f"{번호} 들어간다", flush=True)
    하기()
    앱.processEvents()
    print(f"{번호} 살았다", flush=True)


def 위젯보이기():
    w = QWidget()
    w.show()
    앱.processEvents()
    w.close()


def 대화창보이기():
    d = QDialog()
    d.show()
    앱.processEvents()
    d.close()


def 대화창열기():
    d = QDialog()
    d.open()
    앱.processEvents()
    d.close()


def 상자만들기():
    QMessageBox(QMessageBox.NoIcon, "t", "그냥 글", QMessageBox.NoButton)


def 상자단추():
    b = QMessageBox(QMessageBox.NoIcon, "t", "그냥 글", QMessageBox.NoButton)
    b.addButton("닫는다", QMessageBox.RejectRole)


def 상자보이기():
    b = QMessageBox(QMessageBox.NoIcon, "t", "그냥 글", QMessageBox.NoButton)
    b.addButton("닫는다", QMessageBox.RejectRole)
    b.show()
    앱.processEvents()
    b.close()


def 상자열기():
    b = QMessageBox(QMessageBox.NoIcon, "t", "그냥 글", QMessageBox.NoButton)
    b.addButton("닫는다", QMessageBox.RejectRole)
    b.open()
    앱.processEvents()
    b.close()


def 상자기본단추():
    b = QMessageBox(QMessageBox.NoIcon, "t", "그냥 글", QMessageBox.Ok)
    b.open()
    앱.processEvents()
    b.close()


재기("1 그냥위젯 show", 위젯보이기)
재기("2 대화창 show", 대화창보이기)
재기("3 대화창 open", 대화창열기)
재기("4 상자 만들기만", 상자만들기)
재기("5 상자 단추까지", 상자단추)
재기("6 상자 show", 상자보이기)
재기("7 상자 open", 상자열기)
재기("8 상자 기본단추 open", 상자기본단추)

print("다 살았다", flush=True)
sys.stdout.flush()
os._exit(0)
