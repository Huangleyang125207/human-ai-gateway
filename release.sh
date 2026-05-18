#!/bin/bash
# release.sh — 一条龙:打包 → smoke test → 通过才把 DMG copy 到 /tmp 可分发
#
# 用法:cd gateway && bash release.sh
#
# 流程:
#   1. bash build-mac-pyinstaller.sh   出 dist-pyinstaller/Gateway.app + .dmg
#   2. bash test-bundle.sh             隔离 fresh state 跑 12 项端点测
#   3. 全过 → cp DMG 到 /tmp/Gateway-Installer-pyinstaller.dmg(可分发)
#   4. 任一步失败 → 不复制,exit 1
#
# 跑完成功:你直接把 /tmp/Gateway-Installer-pyinstaller.dmg 发出去就行。

set -e
cd "$(dirname "$0")"

GREEN=$'\033[32m'
RED=$'\033[31m'
RESET=$'\033[0m'

echo "════════════════════════════════════════════"
echo "  Gateway release: build + test + stage"
echo "════════════════════════════════════════════"
echo

echo "▶ Step 1/3 · build"
if ! bash build-mac-pyinstaller.sh; then
  echo "${RED}✗ build 失败,中止${RESET}"
  exit 1
fi
echo

echo "▶ Step 2/3 · smoke test(隔离 fresh state)"
if ! bash test-bundle.sh; then
  echo
  echo "${RED}✗ smoke test 失败 — 不把 DMG 复制出去(避免发出去坏的)${RESET}"
  exit 1
fi
echo

echo "▶ Step 3/3 · stage 可分发 DMG"
SRC="dist-pyinstaller/Gateway-Installer.dmg"
DST="/tmp/Gateway-Installer-pyinstaller.dmg"
if [ ! -f "$SRC" ]; then
  echo "${RED}✗ 找不到 $SRC${RESET}"
  exit 1
fi
cp "$SRC" "$DST"
SIZE=$(du -h "$DST" | awk '{print $1}')

echo
echo "════════════════════════════════════════════"
echo "  ${GREEN}✓ release 全过 — DMG 已 stage${RESET}"
echo "    路径: $DST  ($SIZE)"
echo "    分发: 把这个 .dmg 发出去即可"
echo "════════════════════════════════════════════"
