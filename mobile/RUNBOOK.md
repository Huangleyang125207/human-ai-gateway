# 移动端 Capacitor 壳 — 构建运行手册

> 现状:web 层 + 本地 shim + Capacitor 工程**已就绪并验证**(浏览器 phone 视口跑通)。
> 剩下全是**需要原生工具链**的步骤 —— 装好 SDK 后照下面命令走即可出真机包。

## 已完成(不需 SDK,已验)

- `mobile/mobile-api.js` — 本地"假后端",劫持 fetch/EventSource,服务 ~12 个 MVP 端点。
  存储双后端:浏览器 localStorage / 真机 Capacitor Filesystem,自动选。对话直连 DeepSeek。
- `mobile/build-web.sh` — 把现有前端组装进 `app/www/`(只含 webview 要的文件,不带 server.py)。
- `mobile/app/` — Capacitor 工程(`@capacitor/core/cli/ios/android/filesystem/preferences` 已装,CLI 6.2.1)。
- `index.html` 首位加载 shim(守卫:Capacitor/`?mobile=1` 下才拦,桌面零回归)。

## 你要装的工具链(长下载,我装不了)

### iOS
```bash
# 1. Mac App Store 装 Xcode(~15GB)
# 2. 指向完整 Xcode + 接受协议
sudo xcode-select -s /Applications/Xcode.app/Contents/Developer
sudo xcodebuild -license accept
# 3. CocoaPods(你已有 Homebrew)
brew install cocoapods
```

### Android
```bash
# 1. 装 Android Studio(developer.android.com,~1GB),首启向导会下 SDK(~5GB)
# 2. JDK 17(Android Studio 自带 JBR,设给 Gradle 用)
export JAVA_HOME="/Applications/Android Studio.app/Contents/jbr/Contents/Home"
export ANDROID_HOME="$HOME/Library/Android/sdk"
export PATH="$PATH:$ANDROID_HOME/platform-tools"
# (把上面三行写进 ~/.zshrc)
```

## 出包命令(工具链装好后)

```bash
cd mobile/app

# iOS
npx cap add ios                 # 生成 ios/ 工程(跑 pod install)
npm run sync                    # = build:web + cap sync(每次改前端后都跑)
npx cap open ios                # 开 Xcode → 选签名 Team(L2QPVXA6DT)→ 连 iPhone 运行
                                # 内测分发走 TestFlight,或开发签名直接装自己/家人机

# Android
npx cap add android             # 生成 android/ 工程
npm run sync
npx cap open android            # 开 Android Studio → Run 到设备;或 Build > APK 签名后 sideload
```

## 装上手机后的第一步

1. 打开 app → 直接看到今天的日记(首启自动 seed 一份示例日,可删)。
2. 报头 **⚙** → 设置 → 填 **DeepSeek key**(platform.deepseek.com 拿)→ 保存。
   - key 存在设备 Preferences(Keychain/Keystore 级),不外传。
3. 回主页 → 点开对话 → AI 能读今天的日记跟你聊。

## MVP 已知取舍(都是有意为之,见 MOBILE_MVP_PLAN.md)

- **对话非流式**:真机经原生 HTTP 桥绕 CORS,但拿全文后一次性显示(不逐字)。先求能用。
- **数据分叉**:手机这份日记存在 app 私有区,跟你 Mac 的 Obsidian vault **是两份**。
  跨设备同步是 P5(iCloud/git),MVP 不做。
- **字体**:`index.html` 还连 Google Fonts CDN,离线/国内会回落系统字。P3 换成本地 vendor 字体。
- **窄屏**:已无横向溢出,但间距是桌面调的,触控/字号待 P3 收口。
- **砍掉的功能**(返占位):拖图抠图、vision/OCR、web 搜索、插件市场写操作、自动更新、
  AI 工具调用(AI 不直接改 MD)。

## 想先在电脑上看效果(不装 SDK)

```bash
cd <gateway>
python3 -m http.server 8765
# 浏览器开(缩到手机宽):http://localhost:8765/index.html?mobile=1
# 手机同 wifi:http://<Mac 局域网 IP>:8765/index.html?mobile=1 → 也能"添加到主屏"先用着
```
