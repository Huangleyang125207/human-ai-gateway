// macOS VisionKit Subject Lift — 用 Apple 的"长按图片把主体扣出来"那个 API
// Build: swift /tmp/cutout_macos.swift <input.jpg> <output.png>
import Vision
import CoreImage
import CoreImage.CIFilterBuiltins
import Foundation
import AppKit

guard CommandLine.arguments.count >= 3 else {
    print("usage: swift cutout_macos.swift <input> <output.png>")
    exit(1)
}
let inPath = CommandLine.arguments[1]
let outPath = CommandLine.arguments[2]
let inURL = URL(fileURLWithPath: inPath)
let outURL = URL(fileURLWithPath: outPath)

guard let image = CIImage(contentsOf: inURL) else {
    print("ERR: cannot read \(inPath)"); exit(1)
}

let t0 = Date()
let request = VNGenerateForegroundInstanceMaskRequest()
let handler = VNImageRequestHandler(ciImage: image)
do {
    try handler.perform([request])
} catch {
    print("ERR: vision request failed: \(error)"); exit(1)
}
guard let obs = request.results?.first else {
    print("ERR: no subject detected"); exit(1)
}

let pixelBuffer: CVPixelBuffer
do {
    pixelBuffer = try obs.generateMaskedImage(
        ofInstances: obs.allInstances,
        from: handler,
        croppedToInstancesExtent: false
    )
} catch {
    print("ERR: generateMaskedImage failed: \(error)"); exit(1)
}

let maskedCI = CIImage(cvPixelBuffer: pixelBuffer)
let ctx = CIContext()
do {
    try ctx.writePNGRepresentation(
        of: maskedCI,
        to: outURL,
        format: .RGBA8,
        colorSpace: CGColorSpaceCreateDeviceRGB()
    )
} catch {
    print("ERR: write PNG failed: \(error)"); exit(1)
}

let dt = Int(Date().timeIntervalSince(t0) * 1000)
print("OK: \(outPath) (\(dt)ms, \(obs.allInstances.count) instances)")
