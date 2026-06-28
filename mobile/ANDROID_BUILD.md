# Android 构建 — 明天一起跑测试

> 状态(2026-06-28 夜):Android 平台已 scaffold + 插件就绪 + web 资源已进包。
> **本机缺 Android 工具链 → 还没法 build/跑 APK**。明天装工具链即可构建测试。

---

## 已就绪(今晚做的)

- **平台已生成**:`npx cap add android` 成功 → `mobile/app/android/`(gitignore,跟 `ios/` 一样是生成物,不进版本控制;源在 `m/` + `mobile-api.js` + `plugins/` + `capacitor.config.json`)。
- **插件 Android 解析**(`cap add` 输出确认):
  - `@capacitor/filesystem` — 日记 md / thread.json 落盘 ✅
  - `@capacitor/preferences` — settings / 标签聚合 / scrapbook ✅
  - `capacitor-native-ocr` — **ML Kit 中文 OCR**(离线;无 GMS 国行 ROM 自动 `available()=false` → JS 回落云端百炼 vision OCR)✅
- **cutout 改 iOS-only**(`plugins/cutout/package.json` 去掉 android 声明):iOS 走 Vision Subject Lift;**Android 走云端 `/api/cutout`(rembg/百度)兜底** —— gw-journal.js:267 `if (C && C.cutout)` 存在性检查,缺了优雅降级。端侧 ML Kit Subject Segmentation 是 future(参 native-ocr 的 PaddleOCR TODO)。
- **web 前端同一份**:`m/index.html`(扁平进 www 根)+ `mobile-api.js` shim 已 copy 进 `android/app/src/main/assets/public/`,跟 iOS 完全同源。

## 本机缺什么(明天先装)

这台 Mac 没 **JDK / Android SDK / Gradle / Android Studio**。最快路径二选一:

**A. Android Studio(推荐,一装全有 JDK + SDK + 模拟器)**
```bash
brew install --cask android-studio       # 或官网下载
# 开 Android Studio → SDK Manager → 装 Android 14 (API 34) + Build-Tools 34
```

**B. 纯命令行**
```bash
brew install openjdk@17
# 装 Android command-line tools + sdkmanager;再:
sdkmanager "platform-tools" "platforms;android-34" "build-tools;34.0.0"
yes | sdkmanager --licenses
```
两种都设环境:`export ANDROID_HOME=~/Library/Android/sdk`、`JAVA_HOME` 指 JDK 17。

## 构建 + 装机

```bash
cd ~/human-ai-dev/gateway/mobile
bash build-web.sh                          # 组 www(改了 JS/CSS 后)
cd app && npx cap copy android             # web → android assets
cd android && ./gradlew assembleDebug      # 首次会下 gradle-8.2.1 + ML Kit 依赖,几分钟
# 产物:android/app/build/outputs/apk/debug/app-debug.apk
adb install -r app/build/outputs/apk/debug/app-debug.apk   # 装真机/模拟器
```
或 `npx cap open android` 进 Android Studio 点 ▶ Run(自动起模拟器)。

## 测试重点(对 iOS parity)

- 日记读写 / 打卡 / 八杯水 / 对话工具调用 / **compact 圆环**(刚做的)
- **OCR**:有 GMS → ML Kit 中文离线;无 GMS → 自动回落云端百炼(填了百炼 key)
- **cutout**:Android 走云端(填了百炼 key 才有"眼睛";没填则原图直传)
- **存储**:Filesystem(`Documents/gw/journal/*.md` + `thread.json`)+ Preferences(`CapacitorStorage.*`)
- 触屏:长按编辑态、横滑打卡、抽屉、聚合页 tab —— Android 触摸事件跟 iOS 同走 pointer/touch,理论一致,真机验

## 坑预判

- **Filesystem Directory.Data**:Android 落点跟 iOS 不同(app private storage),路径自处理;seed/inspect 用 `adb shell run-as com.humanai.gateway`。
- **CapacitorHttp**:Android 同样绕 WebView CORS 真打 DeepSeek/百炼,跟 iOS 一致。
- **WKWebView → Android System WebView**:`-webkit-touch-callout` 等 iOS 私有 CSS 在 Android 是 no-op(不报错);长按图片菜单 Android 行为不同,留意 Phase3 贴纸编辑态的长按。
- **minSdk 22**(native-ocr build.gradle)→ Android 5.1+。
