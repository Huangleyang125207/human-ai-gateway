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
# ★复审 R7:versionCode 加 10000 底座 —— CI 传 run number(首跑=1),不加底座会低于本地基线(2),
#   测试者本地装过再装 CI 首跑包被 INSTALL_FAILED_VERSION_DOWNGRADE 拒。底座保证任何产物 code>本地。
VCODE=$(( 10000 + ${1:-0} ))

[ -d "$ANDROID" ] || { echo "✗ $ANDROID 不存在 —— 先 cd app && npx cap add android" >&2; exit 1; }

# ★复审 R6:set -euo pipefail 下 sed 对 0 次替换仍返 0(静默 no-op)。每处关键 patch 后断言命中,
#   未来 Capacitor 模板字段改名时立即失败,不把默认值(minSdk22 等)悄悄放进 build。
assert_has() { grep -qE "$2" "$1" || { echo "✗ patch 未命中: $2  in  $1(模板可能漂移)" >&2; exit 1; }; }

# 1. minSdk 24(tasks-vision/MediaPipe 要求;默认模板是 22)
sed -i.bak -E 's/minSdkVersion = [0-9]+/minSdkVersion = 24/' "$ANDROID/variables.gradle"
assert_has "$ANDROID/variables.gradle" 'minSdkVersion = 24'

# 2. app/build.gradle:版本从 VERSION 盖章 + ABI 白名单(裁 armeabi-v7a/x86,留 arm64+x86_64)
APP_GRADLE="$ANDROID/app/build.gradle"
sed -i.bak -E "s/versionCode [0-9]+/versionCode $VCODE/; s/versionName \"[^\"]*\"/versionName \"$VERSION\"/" "$APP_GRADLE"
assert_has "$APP_GRADLE" "versionCode $VCODE"
assert_has "$APP_GRADLE" "versionName \"$VERSION\""
if ! grep -q "abiFilters" "$APP_GRADLE"; then
  # 在 versionCode 行后插 ndk abiFilters(锚 versionCode 避免 versionName 里的点号在正则里通配 · 复审 N5)
  sed -i.bak2 -E "/versionCode $VCODE/a\\
        ndk { abiFilters 'arm64-v8a', 'x86_64' }" "$APP_GRADLE"
fi
assert_has "$APP_GRADLE" "abiFilters"

rm -f "$ANDROID/variables.gradle.bak" "$APP_GRADLE".bak "$APP_GRADLE".bak2 2>/dev/null || true
echo "✓ android-setup: minSdk=24 · version=$VERSION($VCODE) · abiFilters=arm64+x86_64"
echo "  (tflite noCompress + tasks-vision dep 在 mobile/plugins/cutout/android/build.gradle,受版本控制,cap sync 自动带入)"
