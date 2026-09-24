#!/usr/bin/env bash
# VC 폰 앱 안드로이드 APK 굽기 (Windows · Git Bash).
#
# ★ Gradle(안드로이드 플러그인)은 **경로에 한글이 있으면 굽기를 거절**하고, Dart 분석기도 한글 경로에서 죽는다.
#   정션(C:\vcapp)은 실제 경로로 풀려 소용없다 — `subst` 가상 드라이브(V:)는 안 풀리므로 그리로 들어가 굽는다.
# ★ sdkmanager(새 Android CLI 감싸개)를 **둘이 동시에 부르면 0xC0000409 로 둘 다 죽는다** — Gradle 이 굽는 중에
#   부족한 패키지를 받으려 부르므로, 굽는 동안 따로 sdkmanager(시스템 이미지 받기 등)를 돌리지 않는다.
# 도구 자리: C:\dev\flutter · C:\dev\android-sdk · C:\dev\jdk-17.* (시스템 PATH 는 안 건드린다)
set -euo pipefail

APPDIR="$(cd "$(dirname "$0")" && pwd -W)"      # 변수 이름은 영문 — bash 는 한글 이름을 변수로 못 읽는다
export JAVA_HOME="$(ls -d /c/dev/jdk-17* | head -1 | sed 's#^/c#C:#')"
export ANDROID_HOME="C:\\dev\\android-sdk"
F=/c/dev/flutter/bin/flutter.bat

cmd //c "subst V: /D" >/dev/null 2>&1 || true
cmd //c "subst V: ${APPDIR//\//\\}"
trap 'cmd //c "subst V: /D" >/dev/null 2>&1 || true' EXIT
cd /v/

"$F" analyze
"$F" test
"$F" build apk --release
ls -la build/app/outputs/flutter-apk/app-release.apk
