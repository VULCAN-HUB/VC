"""VC 앱 그림을 PC 표식(logo.VulcanMark · 불칸 테마)으로 굽는다 — 아이콘 · 시작 화면 · 앱 속 표식.

PC 와 같은 얼굴이어야 「같은 VC」로 읽힌다. 그림 파일을 손으로 그리지 않고 PC 가 쓰는 선 그림을
그대로 찍는다(색·획이 바뀌면 이것만 다시 돌린다).

    python app/tools/make_assets.py
"""
import json
import os
import pathlib
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
APP = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP.parent / "pc"))

from PyQt5.QtCore import QPointF, Qt  # noqa: E402
from PyQt5.QtGui import QBrush, QColor, QImage, QPainter, QPainterPath, QRadialGradient  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

qt = QApplication([])
import logo  # noqa: E402
import theme  # noqa: E402

theme.use("vulcan")
BG = QColor("#0a0a0b")
HEAT = 0.55


def render(size: int, *, ring: bool, bg: bool, mark_scale: float = 0.30, round_bg: bool = False) -> QImage:
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(QColor(0, 0, 0, 0))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    c = size / 2
    acc = theme.T.ACCENT
    if bg:
        if round_bg:                                   # 안드로이드 옛 런처는 네모를 그대로 보인다 — 둥글린다
            path = QPainterPath()
            path.addRoundedRect(0, 0, size, size, size * 0.22, size * 0.22)
            p.fillPath(path, BG)
        else:
            p.fillRect(0, 0, size, size, BG)       # iOS 아이콘은 투명을 못 쓴다
        glow = QRadialGradient(QPointF(c, c), c * 0.9)
        glow.setColorAt(0.0, theme.rgba(QColor("#2a0d06"), 255))
        glow.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(glow))
        p.drawEllipse(QPointF(c, c), c * 0.9, c * 0.9)
    mark = logo.VulcanMark(size)
    mark.t = 1.7
    if ring:
        base = c * 0.78                                # 안드로이드 12 시작 아이콘은 가운데 원 밖을 자른다
        mark._draw_haze(p, c, c, base, HEAT, acc)
        mark._draw_embers(p, c, c, base * 0.80, HEAT, acc)
        mark._draw_mark(p, c, c, base * mark_scale, HEAT, acc)
    else:
        mark._draw_mark(p, c, c, c * mark_scale / mark._RATIO, HEAT, acc, solid=size < 40)
    p.end()
    return img


def save(img: QImage, path: pathlib.Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    assert img.save(str(path), "PNG"), path
    print("  ", path.relative_to(APP), img.width())


res = APP / "android/app/src/main/res"
for folder, px in (("mdpi", 48), ("hdpi", 72), ("xhdpi", 96), ("xxhdpi", 144), ("xxxhdpi", 192)):
    save(render(px, ring=False, bg=True, mark_scale=0.52, round_bg=True), res / f"mipmap-{folder}/ic_launcher.png")
save(render(960, ring=True, bg=False), res / "drawable-xxxhdpi/splash_mark.png")   # 240dp

icons = APP / "ios/Runner/Assets.xcassets/AppIcon.appiconset"
for it in json.loads((icons / "Contents.json").read_text(encoding="utf-8"))["images"]:
    px = round(float(it["size"].split("x")[0]) * int(it["scale"].rstrip("x")))
    img = render(px, ring=False, bg=True, mark_scale=0.52).convertToFormat(QImage.Format_RGB32)
    save(img, icons / it["filename"])
launch = APP / "ios/Runner/Assets.xcassets/LaunchImage.imageset"
for name, px in (("LaunchImage.png", 240), ("LaunchImage@2x.png", 480), ("LaunchImage@3x.png", 720)):
    save(render(px, ring=True, bg=False), launch / name)

save(render(720, ring=True, bg=False), APP / "assets/vc_mark.png")
save(render(256, ring=False, bg=False, mark_scale=0.92), APP / "assets/vc_mark_solid.png")
print("끝")
