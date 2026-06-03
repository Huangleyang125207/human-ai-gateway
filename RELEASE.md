# Release Workflow

每次 bump 版本统一走这条 — 别再手动 build / 装 / 推。

## 一次性 setup(每台开发 Mac 一次)

```bash
# 1. tauri-cli (Rust)
cargo install tauri-cli --version "^2.0" --locked

# 2. notarytool keychain 凭证(--push 时才需)
xcrun notarytool store-credentials gateway-notary \
  --apple-id ryszardgrunnill@mail.com \
  --team-id L2QPVXA6DT
# 提示输 app-specific password
```

## 标准发版流程

### 1. Bump 版本号(两处同时改)

```bash
# src-tauri/tauri.conf.json     "version": "0.1.X"
# server.py                      APP_VERSION = "0.1.X"
```

两边必须一致 — `release-mac-local.sh` 会 sanity-check 提醒。

### 2. 本机 build + 装 + 测

```bash
bash scripts/release-mac-local.sh
```

这步:
- preflight check 依赖齐
- sidecar PyInstaller freeze
- Tauri build(codesign,不 notarize)
- 替换 /Applications/Gateway.app
- 启动 + 等 sidecar 起来

测什么:
- 新功能跑得通
- consent / 数据 tab / curator 不挂
- chat 流畅

### 3. 满意了再推 yanpai 给所有用户

```bash
bash scripts/release-mac-local.sh --push
```

`--push` 额外做:
- 走 notarize(Apple 服务器 5-15min)
- staple ticket
- 生成 `latest.json`(含 minisign 签名)
- rsync 推 yanpai `/opt/feedback-sink/data/updates/`
- verify yanpai endpoint 返新版本

用户端 5s 后台 fetch 自动升级。

### 4. git commit + push

```bash
git add -A
git commit -m "release: 0.1.X"
git push origin main
```

(public repo + GitHub Actions Mac runner 现在转本地了不烧钱,push 只触发 Win build。)

## 调试用

```bash
bash scripts/release-mac-local.sh --skip-build   # 跳 build 直接装现有产物
```

build 已经 ok 但启动后 sidecar crash → 直接 replace + 重跑,不重 build。

## 常见踩坑

- **sidecar 启动失败 "different Team IDs"** → 检查 `src-tauri/entitlements.plist` 是否含 `disable-library-validation`。PyInstaller 嵌的 Python3.framework 是 python.org 签的,跟你的 Developer ID 不同。
- **Gatekeeper 弹"无法验证开发者"** → 没 notarize。`xattr -dr com.apple.quarantine /Applications/Gateway.app` 强解除一次,或者用 `--push` 路径走 notarize。
- **rsync 推 yanpai 卡死** → 家宽上行慢,150MB 等 10-30min 正常。**不要**因为慢就 ctrl-c,会留 partial,下次重传更乱。
- **tauri.conf.json version 改了但 sidecar APP_VERSION 没改** → 心跳上报和实际版本不一致。脚本会 warn 但不阻断,自己注意。

## 文件清单

- `scripts/release-mac-local.sh` — 工作流主体
- `src-tauri/tauri.conf.json` — version + signing identity + entitlements 引用
- `src-tauri/entitlements.plist` — hardenedRuntime 跨 Team ID 兼容
- `~/.minisign/gateway-tauri.key` — Tauri updater 签名(私钥)
- `~/.ssh/gateway-updates-deploy` — yanpai 推送(rrsync sandbox)
