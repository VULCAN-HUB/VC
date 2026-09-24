"""로고를 아이콘 파일로 굽는다. 링·불티는 뺀다 — 작은 자리에서 얼룩이 된다."""
import pathlib
import struct
import sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QImage, QPainter, QColor
from PyQt5.QtCore import QBuffer, QByteArray, QIODevice
import paths
paths.pin_qt_plugins()      # 한글 경로에서 Qt 가 제 플러그인을 못 찾는다
app = QApplication([])
import logo, theme
theme.use("vulcan")
mark = logo.VulcanMark(256)
SIZES = [256, 128, 64, 48, 32, 16]
blobs = []
for s in SIZES:
    img = QImage(s, s, QImage.Format_ARGB32)
    img.fill(QColor(0, 0, 0, 0))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    half = s / 2
    # 표식이 가로로 1.383배 넓다. 세로 절반을 그 배율로 나눠야 좌우가 안 잘린다.
    fit = half * 0.92 / mark._RATIO
    mark._draw_mark(p, half, half, fit, 0.55, theme.T.ACCENT, solid=s < 20)
    p.end()
    ba = QByteArray(); buf = QBuffer(ba); buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG"); buf.close()
    blobs.append(bytes(ba))
head = struct.pack("<HHH", 0, 1, len(blobs))
offset = 6 + 16 * len(blobs)
entries = data = b""
for s, b in zip(SIZES, blobs):
    n = s if s < 256 else 0
    entries += struct.pack("<BBBBHHII", n, n, 0, 0, 1, 32, len(b), offset)
    offset += len(b); data += b
out = str(pathlib.Path(__file__).resolve().parent.parent / "vc.ico")
open(out, "wb").write(head + entries + data)
import os
print("saved", out, os.path.getsize(out), "bytes ·", SIZES)
