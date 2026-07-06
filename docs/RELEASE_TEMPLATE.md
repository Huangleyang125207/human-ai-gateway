# Release Template — 桌面 OSS 跨平台分发

> 参考样本:[OpenHuman v0.54](https://github.com/tinyhumansai/openhuman)
> (Tauri 框架,GPLv3,21K stars,2026-02 起活跃发版)
> 它的发版矩阵就是这个模板的标准答案 — 行业惯例,不是特殊设计。
> 落进 gateway 时把 Tauri 相关字段换成 PyInstaller 对应物。

---

## 一、四平台 × 签名 + 自动更新矩阵

| 平台 | arch | 安装格式 | 签名机构 | 签名成本/年(USD) | 自动更新 |
|------|------|----------|----------|------------------|----------|
| **macOS** | arm64 + x86_64 | `.dmg` + `.app.tar.gz`(updater 用) | Apple Developer ID | $99 | Tauri updater / Sparkle |
| **Windows** | x86_64 | `.msi`(WiX,IT 用)+ `-setup.exe`(NSIS,普通用户) | DigiCert OV/EV | $200-600 | Tauri updater / WinSparkle |
| **Linux** | x86_64 + arm64 | `.AppImage` + `.deb` | **无签**(行业惯例) | $0 | AppImage updater(zsync)/ apt 仓库 |
| **Mobile** | — | — | — | — | **不做**(独立产品,App Store / Play Store 评审独立) |

**关键:** 行业惯例就 4 平台 × 上面这些格式。**别贪心**(不发 .rpm / .snap / .flatpak / .pkg,长尾用户能自己 build);**别漏**(漏 x86_64 mac = Intel 用户全没了,漏 .msi = 企业 IT 装不了)。

OpenHuman v0.54 的实际产物清单 = 上表 row 1-3 全 ship + 配套 .sig 更新签名:

```
OpenHuman_0.54.0_aarch64.dmg                          168 MB
OpenHuman_0.54.0_aarch64-apple-darwin.app.tar.gz      168 MB  ← updater
OpenHuman_0.54.0_x64.dmg                              179 MB
OpenHuman_0.54.0_x86_64-apple-darwin.app.tar.gz       179 MB  ← updater
OpenHuman_0.54.0_x64_en-US.msi                        WiX
OpenHuman_0.54.0_x64-setup.exe                        NSIS
OpenHuman_0.54.0_amd64.AppImage                       Linux
OpenHuman_0.54.0_amd64.deb                            Linux
*.sig                                                 minisign updater 签
latest.json                                           updater manifest
openhuman-core-*-linux-gnu.tar.gz                     standalone CLI sidecar
```

---

## 二、各平台 setup 清单(从零到 release)

### macOS — 3-5 天工作量

```
□  注册 Apple Developer Program(个人 / 公司都行),$99/年
□  Apple Developer 后台创建 "Developer ID Application" 证书 → 下载 .cer
□  Keychain Access 里导出 .p12(含私钥)备份
□  本地 codesign --deep --force --options=runtime --sign "Developer ID Application: NAME (TEAMID)" Foo.app
□  xcrun notarytool submit Foo.dmg --apple-id ... --password app-specific-pw --team-id ... --wait
□  xcrun stapler staple Foo.dmg
□  GitHub Actions 自动化:.p12 base64 编码 → Secrets,workflow 跑 codesign + notarytool
□  分 arm64 + x86_64 两个 dmg(universal2 可选,但 Rust/Python 多 dep 时打包麻烦)
```

**Secrets 命名(参 OpenHuman):**
- `APPLE_CERTIFICATE_BASE64`
- `APPLE_CERTIFICATE_PASSWORD`
- `APPLE_SIGNING_IDENTITY`(完整字串:`Developer ID Application: NAME (TEAMID)`)
- `APPLE_ID`
- `APPLE_APP_SPECIFIC_PASSWORD`(Apple ID 后台生成,不是登录密码)
- `APPLE_TEAM_ID`

### Windows — 5-7 天工作量(签名比 Mac 复杂)

```
□  买 DigiCert 代码签名证书 — OV($200-400) 或 EV($400-700)
   · OV:便宜,但 SmartScreen 要"积累信誉"几周才不告警(累计下载量门槛)
   · EV:贵,但 SmartScreen **即刻信任**,新软件首发推荐
□  证书发货:USB 硬件 token(EV) 或软证书(OV)
□  本地用 signtool.exe(Windows SDK)签名 .exe / .msi
□  GitHub Actions 自动化:DigiCert 现在推 KeyLocker 云签名(secrets 配 SM_API_KEY + smctl)
□  打两种格式:.msi(WiX,IT 部署)+ .exe(NSIS 或 Inno Setup,GUI 安装)
□  Windows Defender 偶尔仍会误报新签名软件 — 提交 VirusTotal + Microsoft Defender 误报申诉
```

**典型 Secrets:**
- `WINDOWS_CERTIFICATE_BASE64` + `WINDOWS_CERTIFICATE_PASSWORD`(本地证书路径)
- 或 `SM_HOST` + `SM_API_KEY` + `SM_CLIENT_CERT_*`(DigiCert KeyLocker 云签)

### Linux — 2-3 天

```
□  无需签名(社区惯例;Linux 用户自己负责)
□  打 .AppImage(linuxdeploy 工具链)
□  打 .deb(dpkg-deb 或 fpm)
□  GitHub Release 直接上传,用户 wget / curl 拉
□  可选:维护一个 PPA(Ubuntu)或 Copr(Fedora),但维护成本高,跳
□  可选:推到 Flathub(Flatpak)— 评审 1-2 周,通过后用户 flatpak install
```

**关键:** AppImage 单文件双击就跑,**对发版方最省事**。.deb 是给 Debian/Ubuntu 用户的"正经"安装。两个都发覆盖 90% 用户。

### Mobile — 不做

桌面 OSS app **几乎都不做 mobile**。原因:

- iOS App Store 评审严 + 每年 $99 + 复杂的隐私清单 + 沙盒限制
- Android Play Store $25 一次性,但同样要写隐私政策 + 内容评级 + 通过自动扫描
- 移动端的产品形态跟桌面差很多(交互 / 离线 / 数据迁移),**几乎要重做一遍 UX**
- 业内做了 mobile 的桌面应用(Obsidian / Notion / Linear)都是把它当**独立产品线**,有独立团队

gateway 现阶段:**明确不做**。远期想做的话当独立产品线启动,不在桌面 OSS 模板内。

---

## 三、自动更新

| 框架 | mac | win | linux | 备注 |
|------|-----|-----|-------|------|
| Tauri (Rust) | builtin updater + minisign | builtin | AppImage 内嵌 zsync | OpenHuman 用这套 |
| Electron | electron-updater(基于 Squirrel.Mac / Squirrel.Windows) | 同左 | AppImage + zsync | Obsidian / VSCode 用 |
| Python (PyInstaller) | **没有官方方案** | 同左 | 同左 | gateway 当前 |

**对 gateway:** 短期不做自动更新。改用 in-app "检查新版本" 按钮 → 打开 GitHub Release 页让用户手动下载新 .dmg。等版本节奏稳定到周更级别再上 Sparkle(mac)+ WinSparkle(win),那时候投入产出比才划算。

---

## 四、CI 标准做法(GitHub Actions)

OpenHuman 的 `.github/workflows/build-desktop.yml` 模式可以照搬:

```yaml
# release.yml(顶层触发,tag push 时跑)
on:
  push:
    tags: [v*]
jobs:
  build-mac-arm64:    { uses: ./.github/workflows/build-mac.yml,     with: { arch: arm64  } }
  build-mac-x86:      { uses: ./.github/workflows/build-mac.yml,     with: { arch: x86_64 } }
  build-win:          { uses: ./.github/workflows/build-windows.yml                         }
  build-linux:        { uses: ./.github/workflows/build-linux.yml                           }
  publish-release:    { needs: [build-mac-arm64, build-mac-x86, build-win, build-linux]
                       uses: ./.github/workflows/publish.yml                                }
```

`secrets: inherit` 一次过给所有子 workflow 用。Secrets 在 fork 里**不会带过去**(GitHub 平台保证),所以 PR contributor 跑不动 release(只能跑测试)— 这是设计,不是 bug。

---

## 五、成本汇总(每年)

| 项 | 成本 |
|------|------|
| Apple Developer Program | $99 |
| Windows DigiCert OV(便宜路线) | ~$200 |
| Windows DigiCert EV(推荐) | ~$500 |
| GitHub Actions(public repo 免费) | $0 |
| Linux 分发 | $0 |
| **首年合计(OV)** | **~$300** |
| **首年合计(EV)** | **~$600** |

OpenHuman / Ollama / LM Studio / Bruno 这类 OSS 桌面项目都是这个量级。

---

## 六、给 gateway 的落地优先级

按"用户痛感 × 成本"排:

| 优先级 | 动作 | 预算 | 工作量 | 解决 |
|--------|------|------|--------|------|
| **P0** | 迁移测试(干净 mac 装一遍) | $0 | 半天 | 验单 API onboarding 假设成立 |
| **P1** | Apple Developer + macOS notarize | $99/年 | 2-3 天 | mac 用户 0 警告装机 |
| **P2** | GitHub Actions 自动 release(arm64 + x86_64 双 dmg) | $0 | 1-2 天 | 每次发版自动化 |
| **P3** | Windows DigiCert + .msi/.exe 双格式 | $200-500/年 | 5-7 天 | 进 Win 市场 |
| **P4** | Linux .AppImage + .deb | $0 | 2-3 天 | 极客用户群 |
| **P5** | 自动更新(Sparkle / WinSparkle) | $0 | 5+ 天 | 频繁发版才值 |
| **不做** | Mobile / .rpm / .snap / .flatpak | — | — | 长尾,投入不划算 |

P0-P2 是接下来 2-4 周的事。P3 看是否真有 Windows 早期用户需求(可先发未签名版让 willing-tester 装,等市场信号再投钱)。
