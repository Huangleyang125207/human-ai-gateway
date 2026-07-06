#!/usr/bin/env bash
# ★ H1:让 gitignore 的 Capacitor 原生 android 工程「可复现」。
# app/android/ 是 `cap add android` 的生成物(gitignore),本地手工改过若干 native 配置。
# 这些改动散在生成工程里 = 换机/CI 不可复现 = 「无 CI」的深层根因。此脚本把它们抽成
# 幂等 patch:CI 里 `cap add android` 后跑一次即还原到本机同款可 build 状态。
# 版本从 mobile/VERSION 盖章,与 mobile-api.js APP_VERSION 单源对齐。
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"          # gateway/mobile/scripts
MOBILE="$(cd "$HERE/.." && pwd)"               # gateway/mobile
ANDROID="$MOBILE/app/android"
VERSION="$(tr -d ' \t\n\r' < "$MOBILE/VERSION")"
VCODE="${1:-2}"                                 # versionCode(单调递增,CI 可传 build number)

[ -d "$ANDROID" ] || { echo "✗ $ANDROID 不存在 —— 先 cd app && npx cap add android" >&2; exit 1; }

# 1. minSdk 24(tasks-vision/MediaPipe 要求;默认模板是 22)
sed -i.bak -E 's/minSdkVersion = [0-9]+/minSdkVersion = 24/' "$ANDROID/variables.gradle"

# 2. app/build.gradle:版本从 VERSION 盖章 + ABI 白名单(裁 armeabi-v7a/x86,留 arm64+x86_64)
APP_GRADLE="$ANDROID/app/build.gradle"
sed -i.bak -E "s/versionCode [0-9]+/versionCode $VCODE/; s/versionName \"[^\"]*\"/versionName \"$VERSION\"/" "$APP_GRADLE"
if ! grep -q "abiFilters" "$APP_GRADLE"; then
  # 在 versionName 行后插 ndk abiFilters(幂等:已有则跳过)
  sed -i.bak2 -E "/versionName \"$VERSION\"/a\\
        ndk { abiFilters 'arm64-v8a', 'x86_64' }" "$APP_GRADLE"
fi

rm -f "$ANDROID/variables.gradle.bak" "$APP_GRADLE".bak "$APP_GRADLE".bak2 2>/dev/null || true
echo "✓ android-setup: minSdk=24 · version=$VERSION($VCODE) · abiFilters=arm64+x86_64"
echo "  (tflite noCompress + tasks-vision dep 在 mobile/plugins/cutout/android/build.gradle,受版本控制,cap sync 自动带入)"
