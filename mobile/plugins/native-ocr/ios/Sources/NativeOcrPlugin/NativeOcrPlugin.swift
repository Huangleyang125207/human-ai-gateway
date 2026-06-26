import Foundation
import Capacitor
import Vision
import UIKit

// 端侧 OCR · iOS Vision Framework(VNRecognizeTextRequest)。
// iOS 16+ 中文识别(zh-Hans),iOS 13-15 退英文 + 数字。
// 完全离线 + 不上传图;补剂瓶 "60 粒" / "180 capsules" 等小字场景精度 > 95%。
//
// JS: window.Capacitor.Plugins.NativeOcr.recognize({ image: dataUrlOrB64 })
//   → { text: "按行 join", blocks: [{text, confidence, bbox}], engine: "VNRecognizeText" }
@objc(NativeOcrPlugin)
public class NativeOcrPlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "NativeOcrPlugin"
    public let jsName = "NativeOcr"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "available", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "recognize", returnType: CAPPluginReturnPromise)
    ]

    @objc func available(_ call: CAPPluginCall) {
        // Vision OCR 从 iOS 13 起就在(英文)。中文 iOS 16+。
        if #available(iOS 16.0, *) {
            call.resolve(["available": true, "engine": "VNRecognizeText", "languages": ["zh-Hans", "en-US"]])
        } else if #available(iOS 13.0, *) {
            call.resolve(["available": true, "engine": "VNRecognizeText", "languages": ["en-US"], "reason": "中文需 iOS 16+"])
        } else {
            call.resolve(["available": false, "reason": "需要 iOS 13+"])
        }
    }

    @objc func recognize(_ call: CAPPluginCall) {
        guard #available(iOS 13.0, *) else { call.reject("端侧 OCR 需要 iOS 13+"); return }
        guard var b64 = call.getString("image") else { call.reject("缺 image 参数"); return }
        if b64.hasPrefix("data:"), let comma = b64.range(of: ",") { b64 = String(b64[comma.upperBound...]) }
        guard let data = Data(base64Encoded: b64),
              let uiImage = UIImage(data: data),
              let cgImage = uiImage.cgImage else { call.reject("图片解码失败"); return }

        let langsArg = call.getArray("languages", String.self) ?? ["zh-Hans", "en-US"]

        DispatchQueue.global(qos: .userInitiated).async {
            let request = VNRecognizeTextRequest { (req, err) in
                if let err = err { call.reject("Vision 识别失败: \(err.localizedDescription)"); return }
                guard let observations = req.results as? [VNRecognizedTextObservation] else {
                    call.resolve(["text": "", "blocks": [], "engine": "VNRecognizeText"])
                    return
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
                call.resolve(["text": allText, "blocks": blocks, "engine": "VNRecognizeText"])
            }

            // iOS 16+ 才支持 zh-Hans;低版本传 zh-Hans 会 silently fallback 到英文
            if #available(iOS 16.0, *) {
                request.recognitionLanguages = langsArg
            } else {
                // 过滤 zh-* 留英文 / 数字
                let filtered = langsArg.filter { !$0.lowercased().hasPrefix("zh") }
                request.recognitionLanguages = filtered.isEmpty ? ["en-US"] : filtered
            }
            request.recognitionLevel = .accurate         // 精度模式;.fast 在补剂瓶小字上掉点
            request.usesLanguageCorrection = true

            let handler = VNImageRequestHandler(cgImage: cgImage,
                                                orientation: Self.cgOrientation(uiImage.imageOrientation))
            do { try handler.perform([request]) }
            catch { call.reject("Vision 调用失败: \(error.localizedDescription)") }
        }
    }

    private static func cgOrientation(_ orientation: UIImage.Orientation) -> CGImagePropertyOrientation {
        switch orientation {
        case .up: return .up
        case .down: return .down
        case .left: return .left
        case .right: return .right
        case .upMirrored: return .upMirrored
        case .downMirrored: return .downMirrored
        case .leftMirrored: return .leftMirrored
        case .rightMirrored: return .rightMirrored
        @unknown default: return .up
        }
    }
}
