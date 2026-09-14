#!/usr/bin/env bash
# VC 폰 앱 아이폰판 — 맥에서 돌린다.
#
#   bash build_ios.sh check     # 분석·시험 + 서명 없이 굽기(컴파일 확인)
#   bash build_ios.sh sim       # 시뮬레이터에 띄우기
#   bash build_ios.sh phone     # 케이블로 꽂은 아이폰에 설치(무료 Apple ID 서명 — 먼저 Xcode 에서 팀을 고른다)
#
# 무료 Apple ID 서명은 7일 뒤 만료된다 — 그때 `phone` 을 다시 돌린다.
set -euo pipefail
cd "$(dirname "$0")"
F=flutter

"$F" pub get
case "${1:-check}" in
  check)
    "$F" analyze
    "$F" test
    "$F" build ios --release --no-codesign
    ;;
  sim)
    open -a Simulator
    sleep 8
    "$F" run -d "$(xcrun simctl list devices booted | grep -oE '[0-9A-F-]{36}' | head -1)"
    ;;
  phone)
    "$F" devices
    "$F" run --release -d "$("$F" devices --machine | python3 -c 'import json,sys; print(next(d["id"] for d in json.load(sys.stdin) if d["targetPlatform"]=="ios"))')"
    ;;
  *) echo "check | sim | phone"; exit 1 ;;
esac
