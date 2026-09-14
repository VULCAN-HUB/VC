#!/usr/bin/env bash
# VC 맥 설치본 굽기 — VC.app 을 만들어 zip 으로 묶는다. (build.ps1 의 맥판)
#
#   cd pc && bash build_mac.sh            # 처음이면 .venv-mac 을 만들고 필요한 것을 깐다
#
# ★ 서명은 임시(ad-hoc)다. 처음 열 때 「확인되지 않은 개발자」가 뜨면
#   Finder 에서 VC.app 을 오른쪽 클릭 → 열기. (없애려면 유료 개발자 계정 공증이 필요하다)
# ★ 모델 폴더(../models 의 model.onnx · tokenizer.json · piper)가 있어야 뜻 검색·목소리가 담긴다.
set -euo pipefail
cd "$(dirname "$0")"
시작=$(date +%s)

if [ ! -d .venv-mac ]; then
  python3 -m venv .venv-mac
  .venv-mac/bin/pip install --upgrade pip
  # llama-cpp-python 은 맥에서 소스로 굽는다(Metal) — Xcode 명령줄 도구·cmake 가 필요하다
  CMAKE_ARGS="-DGGML_METAL=on" .venv-mac/bin/pip install -r requirements-mac.txt
fi
PY=.venv-mac/bin/python

echo "== 자체점검"
"$PY" eb.py --모두검사

echo "== 아이콘"
QT_QPA_PLATFORM=offscreen "$PY" - <<'EOF'
import sys
sys.path.insert(0, ".")
from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QImage, QPainter, QColor
app = QApplication([])
import logo, theme
theme.use("vulcan")
m = logo.VulcanMark(1024)
img = QImage(1024, 1024, QImage.Format_ARGB32)
img.fill(QColor("#0a0a0b"))
p = QPainter(img)
p.setRenderHint(QPainter.Antialiasing)
m._draw_mark(p, 512, 512, 512 * 0.62 / m._RATIO, 0.55, theme.T.ACCENT)
p.end()
img.save("vc_mac.png")
print("vc_mac.png")
EOF

echo "== 굽는 중"
판=$("$PY" -c "import paths; print(paths.VERSION)")
"$PY" -m PyInstaller VC.spec --noconfirm --clean
codesign --force --deep --sign - dist/VC.app
mkdir -p ../../_빌드파일
묶음="../../_빌드파일/VC-mac-v$판.zip"
rm -f "$묶음"
ditto -c -k --keepParent dist/VC.app "$묶음"     # zip 은 심볼릭 링크를 깨뜨린다 — ditto 로 묶는다
shasum -a 256 "$묶음"
echo "== 끝. $묶음 · $(( ($(date +%s) - 시작) / 60 ))분"
