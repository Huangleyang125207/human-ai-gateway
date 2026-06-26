# 端侧 OCR 集成 · iOS + Android 分平台路径

> 起源:parity loop N2 row 标 OUT(`/api/daily-tasks/set-image` mobile 端侧抠图但**无 OCR pill count**,
> 跟桌面 `_ocr_text` + 自动写 `taskmeta.total_pills` 不对齐)。补上端侧 OCR 后 N2 能从 OUT 升 ✅。
>
> 创建:2026-06-26 02:58(parity CONVERGED 之后讨论)· 当前 mobile-api.js commit `962fa8d`

---

## 0 · 一句话

iOS 走 **Vision Framework**(系统自带),Android 走 **Google ML Kit**(Google Play Services 自带),
都不下模型 + 都免费 + 都中文好。**走两条 native plugin 路径,不走纯 JS / wasm**(rapidocr-onnxruntime-web
首次加载 3-5s,Tesseract.js 小字差;native 是冷启动 < 100ms + 比 wasm 准)。

---

## 1 · 共用 JS 入口(mobile-api.js 端,跨平台不变)

新增 endpoint:

```js
"POST /api/cutout": function (req, u, body) {
  var url = body && body.attachment_url;
  var name = body && body.task_name;
  if (!url) return jsonResp({ ok: false, error: "缺 attachment_url" }, 400);
  if (!name) return jsonResp({ ok: false, error: "缺 task_name" }, 400);
  // 拿 attachment dataURL(已在 setting/uploadmeta 或 Filesystem)
  return Store.readAttachment(date, stem).then(function (dataUrl) {
    if (!dataUrl) return jsonResp({ ok: false, error: "attachment 不存在" }, 404);
    // 调 native OCR(下 §2/§3 实装)
    return window.OcrBridge.recognize({ dataUrl: dataUrl }).then(function (r) {
      // r = { text: "全部识别文字\n按行\n返回", blocks: [{text, bbox}] }
      var pillCount = extractPillCount(r.text);  // §4 regex
      // 写 image map + meta
      var p = [Store.setSetting("taskimg/" + name, url)];
      if (pillCount > 0) {
        p.push(Store.getSetting("taskmeta/" + name).then(function (raw) {
          var meta = {}; try { meta = raw ? JSON.parse(raw) : {}; } catch (e) {}
          meta.total_pills = pillCount;
          return Store.setSetting("taskmeta/" + name, JSON.stringify(meta));
        }));
      }
      return Promise.all(p).then(function () {
        return jsonResp({ ok: true, ocr_pill_count: pillCount || null });
      });
    });
  });
},
```

`window.OcrBridge.recognize` 是 Capacitor plugin 暴露,iOS / Android 各自实现 §2/§3。

---

## 2 · iOS 路径 · Vision Framework

### 2.1 选型

- **`VNRecognizeTextRequest`**(Vision Framework,iOS 13+)
- 中文识别 iOS 16+ 默认支持(`recognitionLanguages = ["zh-Hans", "en-US"]`)
- 精度高(尤其小字 + 数字,补剂瓶身的 "60 粒" "180 capsules" 这种场景准)
- 完全离线,不上传图,不耗流量
- 0 依赖(系统自带)

### 2.2 写 Capacitor plugin(Swift)

```bash
# 在 mobile/plugins/ 下建个新 plugin
cd ~/human-ai-dev/gateway/mobile/plugins
npx @capacitor/create-plugin capacitor-vision-ocr \
  --package-id com.humanai.gateway.visionocr \
  --display-name "Vision OCR" \
  --author "humanai"
```

`ios/Plugin/VisionOcrPlugin.swift` 核心(~80 行):

```swift
import Foundation
import Capacitor
import Vision
import UIKit

@objc(VisionOcrPlugin)
public class VisionOcrPlugin: CAPPlugin {
    @objc func recognize(_ call: CAPPluginCall) {
        guard let dataUrl = call.getString("dataUrl") else {
            call.reject("缺 dataUrl"); return
        }
        // 解 data:image/jpeg;base64,xxx
        guard let img = parseDataUrl(dataUrl) else {
            call.reject("dataUrl 解析失败"); return
        }
        guard let cgImage = img.cgImage else { call.reject("cgImage nil"); return }

        let request = VNRecognizeTextRequest { (req, err) in
            if let err = err { call.reject(err.localizedDescription); return }
            guard let observations = req.results as? [VNRecognizedTextObservation] else {
                call.reject("无识别结果"); return
            }
            var allText = ""
            var blocks: [[String: Any]] = []
            for obs in observations {
                guard let cand = obs.topCandidates(1).first else { continue }
                allText += cand.string + "\n"
                blocks.append([
                    "text": cand.string,
                    "confidence": cand.confidence,
                    "bbox": [
                        "x": obs.boundingBox.origin.x,
                        "y": obs.boundingBox.origin.y,
                        "w": obs.boundingBox.size.width,
                        "h": obs.boundingBox.size.height
                    ]
                ])
            }
            call.resolve(["text": allText, "blocks": blocks])
        }
        // iOS 16+ 中文,iOS 13-15 退回英文
        if #available(iOS 16.0, *) {
            request.recognitionLanguages = ["zh-Hans", "en-US"]
        } else {
            request.recognitionLanguages = ["en-US"]
        }
        request.recognitionLevel = .accurate  // 精度模式;.fast 速度优先
        request.usesLanguageCorrection = true

        let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])
        DispatchQueue.global(qos: .userInitiated).async {
            do { try handler.perform([request]) }
            catch { call.reject(error.localizedDescription) }
        }
    }

    private func parseDataUrl(_ url: String) -> UIImage? {
        guard let comma = url.firstIndex(of: ",") else { return nil }
        let base64 = String(url[url.index(after: comma)...])
        guard let data = Data(base64Encoded: base64) else { return nil }
        return UIImage(data: data)
    }
}
```

注册到 Capacitor:`ios/Plugin/VisionOcrPlugin.m`:

```objc
#import <Capacitor/Capacitor.h>
CAP_PLUGIN(VisionOcrPlugin, "VisionOcr",
    CAP_PLUGIN_METHOD(recognize, CAPPluginReturnPromise);
)
```

### 2.3 JS 侧绑定

`mobile/plugins/capacitor-vision-ocr/src/index.ts`:

```ts
import { registerPlugin } from '@capacitor/core';
export interface VisionOcrPlugin {
  recognize(opts: { dataUrl: string }): Promise<{ text: string; blocks: any[] }>;
}
const VisionOcr = registerPlugin<VisionOcrPlugin>('VisionOcr');
export default VisionOcr;
```

mobile-api.js 调用方加 import:`window.OcrBridge = VisionOcr`(在 mobile.js 启动时桥接)。

### 2.4 工程量 + 坑

| 项 | 估时 | 坑 |
|---|---|---|
| plugin 脚手架 + Swift 写完 | 1.5h | `recognitionLanguages = ["zh-Hans"]` 是 iOS 16+;低版本会 throw |
| Capacitor 注册 + sync | 0.5h | `npx cap sync ios` 后 Xcode 重新加载 |
| 真机测一张补剂瓶图 | 0.5h | Vision 在 Simulator 上模型可能没下完整,真机更稳 |

---

## 3 · Android 路径 · Google ML Kit

### 3.1 选型

- **`@capacitor-mlkit/text-recognition`** — 社区维护,封装 Google ML Kit Vision
- 中文模型(`chinese`)Android 端要单独 `npm install @capacitor-mlkit/text-recognition-chinese`
- Android 通过 Google Play Services 下模型(首次启动联网 ~10MB,之后离线)
- 国内设备没 GMS 怎么办?**改用 PaddleOCR Android lite**(自带模型,~10MB,纯离线)

### 3.2 标准路径(有 GMS,海外 / 国内合规设备)

```bash
cd ~/human-ai-dev/gateway/mobile/app
npm install @capacitor-mlkit/text-recognition
npm install @capacitor-mlkit/text-recognition-chinese  # 中文模型
npx cap sync android
```

JS 侧:

```ts
import { TextRecognition } from '@capacitor-mlkit/text-recognition';
import { TextRecognitionLanguage } from '@capacitor-mlkit/text-recognition';

const result = await TextRecognition.recognizeText({
  path: '/path/to/file.jpg',   // 注意:MLKit 要文件路径,不要 dataURL
  language: TextRecognitionLanguage.Chinese,
});
// result = { text: "...", blocks: [{text, lines:[{text, points}]}] }
```

**注意 dataURL → 文件路径**:Capacitor Filesystem 写一份临时:

```js
async function dataUrlToTempFile(dataUrl) {
  const { Filesystem, Directory } = window.Capacitor.Plugins;
  const base64 = dataUrl.split(',')[1];
  const name = 'ocr-tmp-' + Date.now() + '.jpg';
  const result = await Filesystem.writeFile({
    path: name,
    data: base64,
    directory: Directory.Cache,
  });
  return result.uri;  // file:///... 路径
}
```

### 3.3 国产 ROM 无 GMS 的兜底 · PaddleOCR Android

如果走国内市场(华为 / 小米国行 ROM 没 Google Play Services):

- **PaddleOCR Android Demo**(github.com/PaddlePaddle/PaddleOCR/tree/main/deploy/android_demo)
- 自带 pp-OCRv4 mobile 模型(~10MB)
- Java/Kotlin native plugin,自己写 wrapper
- 工程量大(估 3-4h),但完全离线 + 国内可用

或者**端云结合**:无 GMS 时回落调阿里云百炼 vision endpoint(已有 N4 实装的 `_qwen_classify_image`)
+ extra_question="OCR 出文字,只返文字"。慢但兜底通。

### 3.4 工程量 + 坑

| 项 | 估时 | 坑 |
|---|---|---|
| MLKit plugin npm install + sync | 0.5h | Android `minSdkVersion` 要 ≥ 21 |
| dataURL → 临时文件 helper | 0.5h | 用完要 `Filesystem.deleteFile`,不然 Cache 越涨越大 |
| 真机测(华为去看 GMS 兼容) | 1h | 国行 ROM 默认无 GMS → 走 §3.3 兜底 |
| PaddleOCR Android(若做) | +3-4h | 模型放 `assets/`,首次启动 init ~500ms |

---

## 4 · pill_count 抽取(JS,跨平台共用)

```js
function extractPillCount(ocrText) {
  if (!ocrText) return 0;
  // 中文优先:"60 粒" "180片" "120 颗" "30 ct"
  var m = ocrText.match(/(\d+)\s*(粒|片|颗|丸|capsules?|tablets?|softgels?|ct|count)/i);
  if (m) return parseInt(m[1], 10);
  // 备选:"NET 60" "Net Content: 60"
  m = ocrText.match(/(?:net|净含量|装量)[\s:：]*(\d+)/i);
  if (m) return parseInt(m[1], 10);
  // 退一步:找 10-500 之间的孤立数字(单瓶补剂常见范围)
  var nums = ocrText.match(/\b\d+\b/g) || [];
  for (var i = 0; i < nums.length; i++) {
    var n = parseInt(nums[i], 10);
    if (n >= 10 && n <= 500) return n;
  }
  return 0;
}
```

**桌面 `_ocr_text` parity**:桌面 fixture `monkeypatch _ocr_text → "鱼油 60 粒"`,assert `ocr_pill_count == 60`。
我这个 regex 第一条 `(粒|片|...)` 直接 match,对齐桌面 oracle ✓。

---

## 5 · 落地顺序

### Phase A · iOS only(2-3 小时)

1. ⏱ 1.5h:`mobile/plugins/capacitor-vision-ocr/` 写 Swift plugin(§2.2)
2. ⏱ 0.5h:JS 桥接 + mobile-api.js 加 `/api/cutout` endpoint(§1)
3. ⏱ 0.5h:Simulator + 真机各测一张补剂瓶照,看 `ocr_pill_count` 真返
4. ⏱ 0.5h:parity oracle 更新:N2 从 OUT 升 ✅,跑 `test_cutout_*` 桌面 STAY GREEN + JS 端 oracle

### Phase B · Android with GMS(再 +1.5 小时)

5. ⏱ 1h:`@capacitor-mlkit/text-recognition` 安装 + JS 桥接(同上 endpoint 自动 cross-platform)
6. ⏱ 0.5h:真机测

### Phase C · Android no-GMS 兜底(可选 +3-4 小时,等真用户反馈)

7. 看市场:海外 + 国内合规市场 80% 设备有 GMS → Phase B 够用
8. 国行 / 鸿蒙:加 PaddleOCR plugin 或回落阿里云百炼

---

## 6 · 跟桌面 parity 关系

`tests/test_image_routes.py::test_cutout_writes_image_map_and_ocr_pill_count` 桌面契约:

```python
r = client.post("/api/cutout", json={
    "attachment_url": "/attachments/2026-06-25/yuyou.jpg",
    "task_name": "鱼油（Swisse）"
})
assert r.json()["ok"] is True
assert r.json()["ocr_pill_count"] == 60
assert "鱼油（Swisse）" in image_map
assert meta["鱼油（Swisse）"]["total_pills"] == 60
```

完成 Phase A 后 mobile shim 跟这个 oracle 字段级对齐:
- `ok` + `ocr_pill_count` 返字段对齐
- image map = setting `taskimg/<name>` 写
- meta total_pills = setting `taskmeta/<name>` 写

→ `mobile/PARITY_LEDGER.md` N2 从 **OUT** 改 **✅** + 盖当时桌面 sha + JS oracle round-trip pass。

---

## 7 · 不做(显式 SKIP)

- **rapidocr-onnxruntime-web**:wasm 跑 PaddleOCR 模型在浏览器,首次加载 3-5s 用户感觉卡;模型 ~10MB
- **Tesseract.js**:小字 / 中文模糊体效果不行,补剂瓶常见烫金字号准确率 < 60%
- **直接传图给云端 OCR(百度 / 阿里云 / 腾讯)**:已经有 N4 vision/classify 走云端的路径;OCR 走 native 是为
  减少 latency(< 200ms vs 云端 1-3s)+ 隐私(瓶身字不上传)
- **OpenCV.js + 自训模型**:工程量天级,不在 MVP scope

---

## 关联文档

- `mobile/PARITY_LEDGER.md` § 收敛记录(N2 当前 OUT 等本文档落地)
- `mobile/MIGRATION_PARITY_GUIDE.md` § oracle = 桌面契约
- `mobile/PHASE_2_RUNBOOK.md` § Phase 2 真机调试(走完才能真机测 OCR)
- `tests/test_image_routes.py::test_cutout_*`(桌面 oracle 12-13 行,N2 行为契约)
