// macOS Vision Framework OCR — 端侧识别简繁中文 + 英文 + 日韩
// 镜像 cutout_subject_lift.swift 的 Stdin/Stdout 约定:
//   build:  swiftc tools/ocr_vision.swift -o tools/ocr_vision
//   call:   ./ocr_vision <input_path>
//   stdout: 识别出的文本(按 line 用 \n 连),识别完打 "---END---" 一行 + ms 信息到 stderr
//   stderr: "OK: <lines> lines, <ms>ms" 或 "ERR: ..."
//   exit:   0 成功(text 可能空 — 图里就是没文字),非 0 失败
import Vision
import CoreImage
import Foundation
import AppKit

guard CommandLine.arguments.count >= 2 else {
    FileHandle.standardError.write("usage: ocr_vision <input>\n".data(using: .utf8)!)
    exit(1)
}
let inPath = CommandLine.arguments[1]
let inURL = URL(fileURLWithPath: inPath)

guard let image = CIImage(contentsOf: inURL) else {
    FileHandle.standardError.write("ERR: cannot read \(inPath)\n".data(using: .utf8)!)
    exit(1)
}

let t0 = Date()
let request = VNRecognizeTextRequest()
request.recognitionLanguages = ["zh-Hans", "zh-Hant", "en-US", "ja-JP", "ko-KR"]
request.recognitionLevel = .accurate
request.usesLanguageCorrection = true
// minimumTextHeight 0 = 不过滤小字;Apple 默认会过滤极小文字,改 0 保留全部
request.minimumTextHeight = 0.0

let handler = VNImageRequestHandler(ciImage: image)
do {
    try handler.perform([request])
} catch {
    FileHandle.standardError.write("ERR: vision request failed: \(error)\n".data(using: .utf8)!)
    exit(1)
}

guard let observations = request.results else {
    // 没文字也算成功 — 空输出 + exit 0
    let dt = Int(Date().timeIntervalSince(t0) * 1000)
    FileHandle.standardError.write("OK: 0 lines, \(dt)ms\n".data(using: .utf8)!)
    exit(0)
}

var lines: [String] = []
for obs in observations {
    // topCandidates(1) 拿最 confident 的那条
    if let top = obs.topCandidates(1).first {
        lines.append(top.string)
    }
}

let joined = lines.joined(separator: "\n")
print(joined)
let dt = Int(Date().timeIntervalSince(t0) * 1000)
FileHandle.standardError.write("OK: \(lines.count) lines, \(dt)ms\n".data(using: .utf8)!)
exit(0)
