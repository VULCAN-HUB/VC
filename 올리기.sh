#!/bin/sh
# 깃허브에 **비공개**로 올린다. 한 번만 하면 된다.
#
# ★ 로그인은 사람이 해야 한다 — 열쇠를 남이 대신 넣는 일은 하지 않는다.
set -e
cd "$(dirname "$0")"

if ! gh auth status >/dev/null 2>&1; then
  echo "== 먼저 로그인한다 (브라우저가 열린다)"
  gh auth login
fi

echo "== 비공개 저장소를 만들고 올린다"
gh repo create VC --private --source=. --remote=origin --push

echo
echo "끝. 윈도우 PC 에서는 이렇게 받는다:"
echo "  gh repo clone <계정>/VC"
echo "  cd VC\\pc"
echo "  .\\build.ps1"
