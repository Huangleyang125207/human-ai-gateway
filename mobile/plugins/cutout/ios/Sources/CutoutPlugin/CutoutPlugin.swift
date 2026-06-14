import Foundation
import Capacitor
import Vision
import UIKit
import CoreImage

// 端侧抠主体 · iOS 17+ Vision 前景实例 mask(与相册「拷贝主体」同引擎)。
// JS: window.Capacitor.Plugins.Cutout.cutout({ image: dataUrlOrB64 }) → { png: dataUrl }
@objc(CutoutPlugin)
public class CutoutPlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "CutoutPlugin"
    public let jsName = "Cutout"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "available", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "cutout", returnType: CAPPluginReturnPromise)
    ]

    @objc func available(_ call: CAPPluginCall) {
        if #available(iOS 17.0, *) { call.resolve(["available": true]) }
        else { call.resolve(["available": false, "reason": "需要 iOS 17+"]) }
    }

    @objc func cutout(_ call: CAPPluginCall) {
        guard #available(iOS 17.0, *) else { call.reject("on-device cutout 需要 iOS 17+"); return }
        guard var b64 = call.getString("image") else { call.reject("缺 image 参数"); return }
        if b64.hasPrefix("data:"), let comma = b64.range(of: ",") { b64 = String(b64[comma.upperBound...]) }
        guard let data = Data(base64Encoded: b64),
              let uiImage = UIImage(data: data),
              let cgImage = uiImage.cgImage else { call.reject("图片解码失败"); return }

        DispatchQueue.global(qos: .userInitiated).async {
            let request = VNGenerateForegroundInstanceMaskRequest()
            let handler = VNImageRequestHandler(cgImage: cgImage,
                                                orientation: Self.cgOrientation(uiImage.imageOrientation))
            do {
                try handler.perform([request])
                guard let result = request.results?.first else { call.reject("没找到主体"); return }
                let buffer = try result.generateMaskedImage(ofInstances: result.allInstances,
                                                             from: handler,
                                                             croppedToInstancesExtent: true)
                let ci = CIImage(cvPixelBuffer: buffer)
                let ctx = CIContext()
                guard let out = ctx.createCGImage(ci, from: ci.extent),
                      let png = UIImage(cgImage: out).pngData() else { call.reject("合成失败"); return }
                call.resolve(["png": "data:image/png;base64," + png.base64EncodedString()])
            } catch {
                call.reject("Vision 抠图失败: \(error.localizedDescription)")
            }
        }
    }

    static func cgOrientation(_ o: UIImage.Orientation) -> CGImagePropertyOrientation {
        switch o {
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
