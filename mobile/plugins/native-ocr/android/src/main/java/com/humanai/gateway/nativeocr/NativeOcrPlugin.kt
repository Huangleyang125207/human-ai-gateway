package com.humanai.gateway.nativeocr

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.util.Base64
import com.getcapacitor.JSObject
import com.getcapacitor.JSArray
import com.getcapacitor.Plugin
import com.getcapacitor.PluginCall
import com.getcapacitor.PluginMethod
import com.getcapacitor.annotation.CapacitorPlugin
import com.google.android.gms.tasks.Tasks
import com.google.mlkit.vision.common.InputImage
import com.google.mlkit.vision.text.TextRecognition
import com.google.mlkit.vision.text.chinese.ChineseTextRecognizerOptions
import com.google.mlkit.vision.text.latin.TextRecognizerOptions

/**
 * 端侧 OCR · Android Google ML Kit text recognition v2(中文模型 zh-Hans + Latin 后备)。
 *
 * 完全离线 + Play Services 自动管模型(首次启动 ~10MB 下载,之后冷启动 < 100ms)。
 * 国行 ROM / 鸿蒙无 GMS 时 available() 返 false,JS 端 fall back 到云端百炼 vision OCR
 * (mobile-api.js /api/vision/classify with extra_question="OCR 出文字")。
 *
 * TODO Phase C:无 GMS 时换 PaddleOCR Android demo(github.com/PaddlePaddle/PaddleOCR/
 * tree/main/deploy/android_demo)— 自带 pp-OCRv4 mobile 模型 ~10MB,纯离线。
 */
@CapacitorPlugin(name = "NativeOcr")
class NativeOcrPlugin : Plugin() {

    @PluginMethod
    fun available(call: PluginCall) {
        try {
            // 触发 ML Kit recognizer 实例化判可用(无 GMS 时构造时就 throw)
            TextRecognition.getClient(ChineseTextRecognizerOptions.Builder().build())
            val r = JSObject()
            r.put("available", true)
            r.put("engine", "MLKitTextRecognition")
            val langs = JSArray(); langs.put("zh-Hans"); langs.put("en-US")
            r.put("languages", langs)
            call.resolve(r)
        } catch (e: Exception) {
            val r = JSObject()
            r.put("available", false)
            r.put("reason", "MLKit 不可用(可能无 GMS):${e.message}")
            call.resolve(r)
        }
    }

    @PluginMethod
    fun recognize(call: PluginCall) {
        var b64 = call.getString("image") ?: run { call.reject("缺 image 参数"); return }
        if (b64.startsWith("data:")) {
            val comma = b64.indexOf(',')
            if (comma >= 0) b64 = b64.substring(comma + 1)
        }
        val bytes: ByteArray = try {
            Base64.decode(b64, Base64.DEFAULT)
        } catch (e: IllegalArgumentException) { call.reject("base64 解码失败: ${e.message}"); return }
        val bitmap: Bitmap = BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
            ?: run { call.reject("图片解码失败"); return }

        val langs = call.getArray("languages")?.let {
            (0 until it.length()).map { i -> it.getString(i) }
        } ?: listOf("zh-Hans", "en-US")
        val useChinese = langs.any { it.lowercase().startsWith("zh") }

        // ChineseTextRecognizerOptions 已含 Latin 字符 + 数字识别,所以中文优先用它;
        // 否则用 Latin v2 引擎(更轻,无中文模型下载)
        val recognizer = if (useChinese) {
            TextRecognition.getClient(ChineseTextRecognizerOptions.Builder().build())
        } else {
            TextRecognition.getClient(TextRecognizerOptions.DEFAULT_OPTIONS)
        }

        val image = InputImage.fromBitmap(bitmap, 0)
        recognizer.process(image)
            .addOnSuccessListener { result ->
                val r = JSObject()
                r.put("text", result.text)  // 按行 join 全部识别文字
                val blocksArr = JSArray()
                for (block in result.textBlocks) {
                    for (line in block.lines) {
                        val lineObj = JSObject()
                        lineObj.put("text", line.text)
                        line.confidence?.let { lineObj.put("confidence", it) }
                        line.boundingBox?.let { box ->
                            val bbox = JSObject()
                            bbox.put("x", box.left); bbox.put("y", box.top)
                            bbox.put("w", box.width()); bbox.put("h", box.height())
                            lineObj.put("bbox", bbox)
                        }
                        blocksArr.put(lineObj)
                    }
                }
                r.put("blocks", blocksArr)
                r.put("engine", "MLKitTextRecognition")
                call.resolve(r)
            }
            .addOnFailureListener { e ->
                call.reject("MLKit 识别失败: ${e.message}")
            }
    }
}
