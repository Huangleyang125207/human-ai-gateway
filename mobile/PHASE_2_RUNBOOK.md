# Phase 2 真机调试 runbook

> 你这边 Phase 0/1 已 ✅(Apple Developer + Xcode 装好);Phase 2 启动时按这文档跑。
> 估时:首次 1-2 天(主要在 Pod conflict / 权限弹框 / signing 来回);二次跑 < 30 分钟。

---

## 0. 启动前 5 分钟检查

```bash
# Mac 端
xcode-select --print-path        # 应返 /Applications/Xcode.app/Contents/Developer
which pod                        # 应返 cocoapods 路径(没装就 sudo gem install cocoapods)
node --version                   # 应 ≥ 18

# 在项目目录
cd ~/human-ai-dev/gateway/mobile/app
ls capacitor.config.json         # 已配 Camera + Filesystem + Preferences plugin
ls ios/App/App/Info.plist        # 已加 5 个权限文案 + ATS 白名单 + UIBackgroundModes
ls ios/App/App/PrivacyInfo.xcprivacy   # 已写 2025 强制隐私清单
```

---

## 1. 装新依赖 + sync iOS 配置模板 + 同步 Pod

**关键**:`mobile/app/ios/` 在 .gitignore 里(Capacitor 生成物策略)。核心
配置文件(Info.plist + PrivacyInfo.xcprivacy)放在 `mobile/app/ios-template/`,
Phase 2 启动时**第一步**复制覆盖到真 iOS 目录:

```bash
cd ~/human-ai-dev/gateway/mobile/app

# 全新机器:ios/ 不存在时,先 cap add ios 让 Capacitor 生成骨架
test -d ios || npx cap add ios

# 关键:把模板复制到真 iOS 目录(覆盖 Capacitor 默认生成的空 Info.plist)
cp -R ios-template/App/App/* ios/App/App/

# 装 @capacitor/camera ^6(vision/OCR 需要)
npm i @capacitor/camera@^6

# 同步 plugin 到 iOS Pod
npx cap sync ios
```

**改 ios-template/ 后**:重跑 `cp -R ios-template/App/App/* ios/App/App/` +
`npx cap sync ios` — 一行别忘。

**预期看到**:
- `Capacitor` / `CapacitorCamera` / `CapacitorPreferences` / `CapacitorFilesystem` / `CapacitorHttp` 5 个 Pod
- `Pods/Pods.xcodeproj` 重新生成

**踩坑**:
- 报 `unable to find compatible version` → npm cache clean + 删 `package-lock.json` + `rm -rf node_modules/` + 重 `npm i`
- 报 `Pod 'CapacitorCordova' not found` → `cd ios/App && pod install --repo-update`
- 报 capacitor 6 跟自写 `capacitor-cutout` plugin 冲突 → 看 `mobile/plugins/capacitor-cutout/package.json` 改 peerDep 到 `^6.0.0`

---

## 2. Xcode 打开 + 配 Team ID

```bash
npx cap open ios
```

Xcode 自动弹出。**手动改 3 处**:

1. **左侧 App → Signing & Capabilities tab**:
   - Team:选你 Apple Developer 账号(Phase 0 注册的那个,不是 Personal Team)
   - Bundle Identifier:`com.humanai.gateway`(已在 capacitor.config.json 写好)
   - "Automatically manage signing" 勾上

2. **加 Capabilities**(同 tab 内 "+"):
   - **Background Modes** → 勾 "Background fetch"(③ C lazy 纸条 + ⑤ E 后台上报需要)

3. **Build Settings → iOS Deployment Target**:
   - 设 **iOS 15.0**(覆盖 iPhone 6s+ 所有现役设备,Capacitor 6 最低要求)

---

## 3. 真机连接 + 信任证书

1. iPhone 数据线接 Mac
2. iPhone 上:**设置 → 隐私与安全性 → 开发者模式 → 开** (iOS 16+)
3. Xcode 顶栏选你的 iPhone(不是 Simulator)
4. 点 **Run ▶**(Cmd+R)

第一次会失败,iPhone 上:**设置 → 通用 → VPN 与设备管理 → Apple Development: <your-email> → 信任**

回 Xcode 再 Cmd+R → app 装上 iPhone。

---

## 4. 跑通 5 件功能(每件 < 5 分钟)

| 测试 | 步骤 | 预期 |
|---|---|---|
| **首装权限弹框** | 第一次拍图 | 弹"用于在日记里拍照贴图..."文案 |
| **chat 贴图 + AI 描述** | chat → + 按钮 → 选张图 → 输入"这是啥?" → 发送 | AI 回应里含图的描述(vision_classify 真调阿里云) |
| **openCard 贴图 + 落 md** | 主屏 + → 写一段 → 点"+ 贴张图" → 选图 → 保存 | 日记 entry 内嵌图渲染出来(rewriteAttachmentImgs 真跑) |
| **③ C lazy 纸条** | app 关掉 → 重开 | 当天 21:30 块自动出现 AI 留的纸条(若过了 21:30) |
| **web_search** | 跟 AI 说"搜下今天上证收盘" | thread chip 亮"搜 \"...\"" + 真返结果 |

---

## 5. 已知会撞 + fix 路径

### 5.1 iCloud Backup 撑满 5GB

**症状**:用户在 iPhone 设置看到 Gateway 占了 1-3GB iCloud,投诉。

**fix**:在 Swift 层给 `Library/NoCloud/attachments/` 目录写 `NSURLIsExcludedFromBackupKey`。

文件:`mobile/app/ios/App/App/AppDelegate.swift` 加:

```swift
import Capacitor

extension AppDelegate {
    func excludeAttachmentsFromBackup() {
        if let docsUrl = FileManager.default.urls(for: .libraryDirectory, in: .userDomainMask).first {
            let attachmentsUrl = docsUrl.appendingPathComponent("NoCloud/attachments", isDirectory: true)
            try? FileManager.default.createDirectory(at: attachmentsUrl, withIntermediateDirectories: true)
            var resourceValues = URLResourceValues()
            resourceValues.isExcludedFromBackup = true
            var mutableUrl = attachmentsUrl
            try? mutableUrl.setResourceValues(resourceValues)
        }
    }
}
```

在 `application(_:didFinishLaunchingWithOptions:)` 末尾调 `excludeAttachmentsFromBackup()`。

### 5.2 Simulator 没相机

`Camera plugin source=CAMERA` 在 Simulator 直接 throw `kCameraNotAvailable`。

**fix**(已在 mobile.js 写):

```javascript
// pickAndUploadImage 内
if (window.navigator.userAgent.includes("Simulator")) {
  source = "PHOTOS";  // 自动回落
}
```

### 5.3 HEIC iPhone 默认格式

capacitor.config.json 已经写了 `format: "jpeg"` 强转。验证:Camera plugin 拍出来 dataURL prefix 应该是 `data:image/jpeg;base64,...`,**不能是 image/heic**。

### 5.4 Limited Photo Library Access(iOS 17+)

用户首次弹权限选"仅选定的照片"后,**下次 Camera plugin 行为不同**:不再弹相册全屏,而是弹"管理选定的照片"。这是 iOS 系统行为,我们不拦,但 onboarding 文案要解释一下 ("选'允许访问所有照片'体验更顺")。

---

## 6. TestFlight 上传(Phase 3)

通过 Phase 2 / 5 件功能全跑通后:

```bash
# Xcode → Product → Archive(Cmd+Shift+B 先 build for testing 验证)
# Archive 完弹 Organizer → Distribute App → App Store Connect → Upload

# 等 10-30 分钟 Apple 处理上传(邮件通知)
# 然后 App Store Connect 添加内测用户(@xxx 的邮箱,或公开 link)
```

---

## 7. 不要做的事(critic 标的)

- ❌ 不能 `NSAllowsArbitraryLoads=true` 裸开 ATS(审核必拒)— 已用 NSExceptionDomains 白名单方式
- ❌ 不能用 default Camera v6 的 `readWrite` 全量相册权限(审核标"不必要")— Info.plist 文案具体到"只在 app 内访问您主动选中的单张照片"
- ❌ 不能让 LLM 看 dataURL 原文(50KB+ token 爆炸)— 已用 logical url + 后端 fetch
- ❌ Camera plugin 不能默认 `saveToGallery: true`(写相册要单独权限)— config 写 false

---

## 8. 真机调试一次性 / 二次跑差别

| 项 | 首次 | 二次 |
|---|---|---|
| Pod install | 5-15 分钟 | < 1 分钟(增量) |
| Xcode build | 5-10 分钟 | 30 秒(增量) |
| 上 iPhone | 30 秒 + 信任证书 1 分钟 | 5 秒 |
| 跑通 5 件功能 | 30-60 分钟(找各种 bug) | 5 分钟 |
| **总** | **1-2 小时 + 偶发 0.5-1 天 bug** | **< 30 分钟** |
