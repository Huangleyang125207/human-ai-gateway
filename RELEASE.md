# Release Workflow

## 两条路径(别再搞混)

| 路径 | 何时用 | Mac | Win | 用时 |
|---|---|---|---|---|
| **A · CI tag-push(主路径)** | 真发版给用户 | ✓ 自动 notarize + 上 GH Release + 推 COS | ✓ 同步 build 推 yanpai | 30-50min |
| **B · 本机 `release-mac-local.sh --push`** | 急,等不了 CI;或 CI 挂了备用 | ✓ 本机 notarize | ✗ **只发 Mac**,Win 落后 | 8-20min |
| **C · 本机不 --push** | 装到自己机器测一下,不发版 | 仅本机 | — | 8min |

**默认走 A** — 所有真用户(Mac + Win)同步拿到。
B 是 6.2 加的备用快速路径,但代价是 Win 不同步;只在 CI 挂掉或紧急 hotfix 才用,且**用完同一周内必须再走一次 A 让 Win 跟上**。
6.17 的教训:把 B 当默认导致 Win 用户停在 v0.1.34 滞后 5 天没人发现。记忆 anchor — **Mac 发版 ≠ 发版**,Win 同步才算完。

---

## A · CI 主路径(推荐)

### 1. Merge feature branch 进 main

正常迭代时改动在 feature branch(`mobile-mvp` 等),merge 到 `main`:

```bash
git checkout main
git merge feature-branch --ff-only   # 有 conflict 改普通 merge
```

### 2. Bump 版本号(两处)

```bash
# src-tauri/tauri.conf.json     "version": "0.1.X"
# server.py                      APP_VERSION = "0.1.X"
git commit -am "chore: bump 0.1.X"
```

### 3. Push + tag,CI 全自动接管

```bash
git push origin main             # 触发 Win CI(build-win.yml,**.py / **.html / shared/** 改了才跑)
git tag v0.1.X
git push origin v0.1.X           # 触发 Mac CI(build-mac.yml,tag v* 触发)
```

CI 用的 secrets(`APPLE_APP_SPECIFIC_PASSWORD` / `APPLE_CERTIFICATE_BASE64` / `COS_SECRET_*` 等)**一次配好永远复用**,不需要每次配。

CI 完成后:
- Mac 用户:走 Tauri updater 从 COS 拉 → 自动更新
- Win 用户:走 yanpai → 自动更新

### 4. 验

- `gh run list --limit 3` 看两条 workflow 都 success
- yanpai feedback-sink `/recent` 几小时内看到新 client_id 升到新版本

---

## B · 本机 fast-path(紧急/CI 挂)

### 一次性 setup

```bash
# 1. tauri-cli (Rust)
cargo install tauri-cli --version "^2.0" --locked

# 2. notarytool keychain 凭证(本机 --push 时才需;CI 路径不需要)
xcrun notarytool store-credentials gateway-notary \
  --apple-id ryszardgrunnill@mail.com \
  --team-id L2QPVXA6DT
# 提示输 app-specific password
```

### B 路径步骤(同 A 的 1-2,差别在 3)

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
