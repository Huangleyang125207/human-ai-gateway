#!/bin/bash
# release-mac-local.sh — 本机 build/装/(可选)推 yanpai。
#
# ⚠️  这不是主发版路径!主路径是 CI tag-push(详 RELEASE.md "A · CI 主路径")。
#     本脚本 --push 只发 Mac,Win 用户不同步;6.17 教训就是把 B 当默认导致 Win 落后 5 天。
#     用本脚本 --push 后,**同一周内必须再走 CI 路径让 Win 跟上**。
#
# 用法:
#   bash scripts/release-mac-local.sh              # 只 build + 装 /Applications + 启动测(C 路径)
#   bash scripts/release-mac-local.sh --push       # B 路径:本机 notarize + 推 yanpai(仅 Mac,紧急时用)
#   bash scripts/release-mac-local.sh --skip-build # 直接装当前已 build 的产物(调试用)
#
# 前置 setup (一次性):
#   cargo install tauri-cli --version "^2.0" --locked
#   xcrun notarytool store-credentials gateway-notary \
#     --apple-id ryszardgrunnill@mail.com --team-id L2QPVXA6DT
#
# 链路:
#   1. preflight 检查依赖齐
#   2. bump version 提示(确认 src-tauri/tauri.conf.json + APP_VERSION 已改)
#   3. bash build-sidecar.sh                  PyInstaller freeze (~3min)
#   4. cargo tauri build                      codesign + tar.gz + minisign (~5min)
#   5. --push 时: xcrun notarytool submit + staple                       (~5-15min)
#   6. quit + 替换 /Applications/Gateway.app + 启动
#   7. --push 时: rsync 推 yanpai (Tauri updater 自动分发)

set -e
cd "$(dirname "$0")/.."

GREEN=$'\033[32m'
RED=$'\033[31m'
YELLOW=$'\033[33m'
RESET=$'\033[0m'

PUSH=0
SKIP_BUILD=0
for arg in "$@"; do
  case "$arg" in
    --push) PUSH=1 ;;
    --skip-build) SKIP_BUILD=1 ;;
    -h|--help)
      sed -n '2,10p' "$0" | sed 's/^# //'
      exit 0
      ;;
  esac
done

YANPAI=101.42.108.30
DEPLOY_KEY=$HOME/.ssh/gateway-updates-deploy
MINISIGN_KEY=$HOME/.minisign/gateway-tauri.key
APPLE_ID=ryszardgrunnill@mail.com
APPLE_TEAM_ID=L2QPVXA6DT
NOTARY_PROFILE=gateway-notary

fail() { echo "${RED}✗ $1${RESET}"; exit 1; }
say() { echo "${GREEN}▶${RESET} $1"; }
warn() { echo "${YELLOW}⚠ $1${RESET}"; }

# ── 1. preflight ────────────────────────────────────────────────────
say "preflight"
command -v cargo >/dev/null || fail "cargo (Rust) 不在 PATH"
command -v cargo-tauri >/dev/null 2>&1 || [ -f ~/.cargo/bin/cargo-tauri ] \
  || fail "tauri-cli 未装,跑 'cargo install tauri-cli --version ^2.0 --locked'"
[ -f "$MINISIGN_KEY" ] || fail "minisign key 不在: $MINISIGN_KEY"
[ -d .venv-build ] || fail ".venv-build 不存在 — 跑 'uv venv --python 3.11 .venv-build && uv pip install --python .venv-build -r requirements.txt pyinstaller rembg==2.0.61 rapidocr-onnxruntime'"
# .venv-build 必须 3.10+:server.py 有运行时 X|None 联合语法(CI 用 3.11);3.9 能构建但一跑就崩(2026-06-15 踩过)
_pyver=$(.venv-build/bin/python -c 'import sys;print(f"{sys.version_info[0]}.{sys.version_info[1]}")' 2>/dev/null)
case "$_pyver" in 3.9|3.8|3.7|2.*|"") fail ".venv-build 是 Python $_pyver,需 3.10+(对齐 CI 的 3.11)。重建:'uv venv --python 3.11 .venv-build' 再装依赖";; esac
security find-identity -p codesigning -v 2>/dev/null | grep -q "Developer ID Application: yang chunyan" \
  || fail "Apple Developer ID 证书不在 keychain"
if [ "$PUSH" = "1" ]; then
  [ -f "$DEPLOY_KEY" ] || fail "deploy key 不在: $DEPLOY_KEY"
  xcrun notarytool history --keychain-profile "$NOTARY_PROFILE" >/dev/null 2>&1 \
    || fail "notary profile '$NOTARY_PROFILE' 未存,跑 'xcrun notarytool store-credentials $NOTARY_PROFILE --apple-id $APPLE_ID --team-id $APPLE_TEAM_ID'"
fi
echo "  ✓ 全齐"

# ── 2. version sanity ─────────────────────────────────────────────────
VERSION=$(jq -r .version src-tauri/tauri.conf.json)
APPV=$(grep '^APP_VERSION = ' server.py | sed 's/.*"\(.*\)".*/\1/')
echo "  tauri version: $VERSION"
echo "  APP_VERSION:   $APPV"
[ "$VERSION" = "$APPV" ] || warn "tauri.conf.json($VERSION) ≠ APP_VERSION($APPV) — 两边要 sync"

# ── 3. sidecar freeze ────────────────────────────────────────────────
if [ "$SKIP_BUILD" = "0" ]; then
  say "sidecar freeze (~3min)"
  bash build-sidecar.sh 2>&1 | tail -3
fi

# ── 4. Tauri build (codesign + minisign,notarize 看 --push) ──────────
if [ "$SKIP_BUILD" = "0" ]; then
  say "Tauri build (~5min)"
  export TAURI_SIGNING_PRIVATE_KEY=$(cat "$MINISIGN_KEY")
  export TAURI_SIGNING_PRIVATE_KEY_PASSWORD=""
  if [ "$PUSH" = "1" ]; then
    export APPLE_ID
    export APPLE_PASSWORD="@keychain:$NOTARY_PROFILE"
    export APPLE_TEAM_ID
  fi
  (cd src-tauri && cargo tauri build) 2>&1 | tail -10
fi

# ── 5. 路径 sanity ───────────────────────────────────────────────────
BUNDLE=src-tauri/target/release/bundle/macos
APP=$BUNDLE/Gateway.app
TAR=$BUNDLE/Gateway.app.tar.gz
SIG=$BUNDLE/Gateway.app.tar.gz.sig
DMG=$(ls src-tauri/target/release/bundle/dmg/Gateway_*.dmg 2>/dev/null | head -1)
[ -d "$APP" ] || fail "build 失败,$APP 不存在"
[ -f "$TAR" ] || fail "$TAR 不存在"
[ -f "$SIG" ] || fail "$SIG 不存在"

# ── 6. quit + 替换 /Applications + 启动 ──────────────────────────────
say "替换 /Applications/Gateway.app"
if pgrep -f "/Applications/Gateway.app" >/dev/null; then
  echo "  Gateway 在跑,先强退"
  pkill -9 -f "/Applications/Gateway.app" 2>/dev/null
  sleep 2
fi
rm -rf /Applications/Gateway.app
cp -R "$APP" /Applications/
NEWVER=$(defaults read /Applications/Gateway.app/Contents/Info CFBundleShortVersionString)
echo "  ✓ 装好 v$NEWVER ($(du -sh /Applications/Gateway.app | cut -f1))"

say "启动 — 验证 sidecar 起得来"
open /Applications/Gateway.app
sleep 8
if pgrep -f "gateway-server" >/dev/null; then
  echo "  ✓ sidecar 跑起来了"
else
  fail "sidecar 没起 — 看 Console.app 找 Gateway / gateway-server crash"
fi

# ── 7. (--push 时) 推 yanpai ──────────────────────────────────────────
if [ "$PUSH" = "1" ]; then
  say "生成 latest.json + 推 yanpai"
  TMP=$(mktemp -d -t gateway-release.XXXX)
  trap "rm -rf $TMP" EXIT
  cp "$TAR" "$TMP/Gateway.app.tar.gz"
  cp "$SIG" "$TMP/Gateway.app.tar.gz.sig"
  SHA=$(git rev-parse HEAD 2>/dev/null || echo "local")
  cat > "$TMP/latest.json" <<EOF
{
  "version": "$VERSION",
  "notes": "local release $SHA",
  "pub_date": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "platforms": {
    "darwin-aarch64": {
      "signature": $(jq -Rs . < "$SIG"),
      "url": "http://$YANPAI:18080/updates/Gateway.app.tar.gz"
    }
  }
}
EOF
  rsync -e "ssh -i $DEPLOY_KEY -o IdentitiesOnly=yes -o StrictHostKeyChecking=no" \
        "$TMP/Gateway.app.tar.gz" \
        "$TMP/Gateway.app.tar.gz.sig" \
        "$TMP/latest.json" \
        ubuntu@$YANPAI:./
  say "verify yanpai"
  YANPAI_VER=$(curl -s --max-time 5 "http://$YANPAI:18080/updates/latest.json" | jq -r '.version')
  echo "  yanpai latest.json version: $YANPAI_VER"
  [ "$YANPAI_VER" = "$VERSION" ] || warn "yanpai 版本 ($YANPAI_VER) ≠ build 版本 ($VERSION) — 推送可能没完成"
fi

echo ""
echo "${GREEN}✓ 完成 — Gateway v$NEWVER 已装 + 启动${RESET}"
[ "$PUSH" = "1" ] && echo "${GREEN}  其他用户 5s 内自动 fetch + 升级${RESET}"
exit 0   # 末行 [ test ] && echo 在非 --push 时会让脚本退 1 假失败,显式退 0
