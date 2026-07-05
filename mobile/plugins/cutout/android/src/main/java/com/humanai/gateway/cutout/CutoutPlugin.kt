package com.humanai.gateway.cutout

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.util.Base64
import android.util.Log
import com.getcapacitor.JSObject
import com.getcapacitor.Plugin
import com.getcapacitor.PluginCall
import com.getcapacitor.PluginMethod
import com.getcapacitor.annotation.CapacitorPlugin
import com.google.mediapipe.framework.image.BitmapImageBuilder
import com.google.mediapipe.framework.image.ByteBufferExtractor
import com.google.mediapipe.framework.image.MPImage
import com.google.mediapipe.tasks.components.containers.NormalizedKeypoint
import com.google.mediapipe.tasks.core.BaseOptions
import com.google.mediapipe.tasks.vision.imagesegmenter.ImageSegmenterResult
import com.google.mediapipe.tasks.vision.interactivesegmenter.InteractiveSegmenter
import com.google.mediapipe.tasks.vision.interactivesegmenter.InteractiveSegmenter.RegionOfInterest
import java.io.ByteArrayOutputStream
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference

/**
 * 端侧抠主体 · Android MediaPipe Interactive Segmenter(magic_touch.tflite,vendored assets)。
 * 选型:国产 ROM 无 Google Play services → ML Kit Subject Segmentation 不可用;
 * MediaPipe tasks-vision 自包含 AAR + bundled 模型,全 AOSP 系 ROM 离线可用。
 * 契约与 iOS Vision 版一致:cutout({image: dataURL[, x, y]}) → {png: dataURL|null};
 * 分割失败/空掩码返 {png: null},JS 调用方原图兜底(mobile-api.js 抠图接线)。
 * 掩码语义(官方 sample OverlayView):category mask byte 0 = 选中物体,非 0 = 背景。
 */
@CapacitorPlugin(name = "Cutout")
class CutoutPlugin : Plugin() {

    @PluginMethod
    fun cutout(call: PluginCall) {
        val dataUrl = call.getString("image")
        if (dataUrl == null || !dataUrl.startsWith("data:")) {
            call.reject("缺 image dataURL")
            return
        }
        // 提示点:默认图像中心偏上(拍物体照片主体习惯性居中)
        val normX = (call.getDouble("x") ?: 0.5).toFloat()
        val normY = (call.getDouble("y") ?: 0.5).toFloat()
        try {
            val b64 = dataUrl.substringAfter("base64,", "")
            val bytes = Base64.decode(b64, Base64.DEFAULT)
            var bmp = BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
                ?: run { call.resolve(nullPng()); return }
            // 超大图先缩(内存 + 推理耗时);聊天上传已 1600px 内,此处兜底
            val maxSide = 1600
            if (bmp.width > maxSide || bmp.height > maxSide) {
                val s = maxSide.toFloat() / maxOf(bmp.width, bmp.height)
                bmp = Bitmap.createScaledBitmap(bmp, (bmp.width * s).toInt(), (bmp.height * s).toInt(), true)
            }
            val mask = segment(bmp, normX, normY)
            if (mask == null) { call.resolve(nullPng()); return }
            val cut = applyMask(bmp, mask) ?: run { call.resolve(nullPng()); return }
            val out = ByteArrayOutputStream()
            cut.compress(Bitmap.CompressFormat.PNG, 100, out)
            val png = "data:image/png;base64," + Base64.encodeToString(out.toByteArray(), Base64.NO_WRAP)
            val ret = JSObject()
            ret.put("png", png)
            call.resolve(ret)
        } catch (e: Exception) {
            Log.e(TAG, "cutout failed: ${e.message}")
            call.resolve(nullPng())
        }
    }

    private fun nullPng(): JSObject {
        val ret = JSObject()
        ret.put("png", null)
        return ret
    }

    /** 跑 magic_touch 分割,返回 category mask(byte 0 = 物体);失败/超时返 null */
    private fun segment(bmp: Bitmap, normX: Float, normY: Float): ByteArray? {
        val resultRef = AtomicReference<ByteArray?>(null)
        val latch = CountDownLatch(1)
        var segmenter: InteractiveSegmenter? = null
        try {
            val options = InteractiveSegmenter.InteractiveSegmenterOptions.builder()
                .setBaseOptions(BaseOptions.builder().setModelAssetPath(MODEL_ASSET).build())
                .setOutputCategoryMask(true)
                .setOutputConfidenceMasks(false)
                .setResultListener { result: ImageSegmenterResult, _: MPImage ->
                    try {
                        val buf = ByteBufferExtractor.extract(result.categoryMask().get())
                        val arr = ByteArray(buf.capacity())
                        buf.rewind(); buf.get(arr)
                        resultRef.set(arr)
                    } catch (e: Exception) {
                        Log.e(TAG, "mask extract failed: ${e.message}")
                    }
                    latch.countDown()
                }
                .setErrorListener { e -> Log.e(TAG, "segmenter error: ${e.message}"); latch.countDown() }
                .build()
            segmenter = InteractiveSegmenter.createFromOptions(context, options)
            // 官方 sample 用像素坐标(normX * width)构造 keypoint
            val roi = RegionOfInterest.create(NormalizedKeypoint.create(normX * bmp.width, normY * bmp.height))
            segmenter.segmentWithResultListener(BitmapImageBuilder(bmp).build(), roi)
            latch.await(20, TimeUnit.SECONDS)
        } catch (e: Exception) {
            Log.e(TAG, "segment failed: ${e.message}")
        } finally {
            try { segmenter?.close() } catch (e: Exception) {}
        }
        return resultRef.get()
    }

    /** 掩码套 alpha + 裁到主体 bbox(留 pad);掩码空/太小(误触发)返 null 走原图兜底 */
    private fun applyMask(bmp: Bitmap, mask: ByteArray): Bitmap? {
        val w = bmp.width; val h = bmp.height
        if (mask.size < w * h) return null
        var minX = w; var minY = h; var maxX = -1; var maxY = -1
        val pixels = IntArray(w * h)
        bmp.getPixels(pixels, 0, w, 0, 0, w, h)
        var kept = 0
        for (y in 0 until h) {
            val row = y * w
            for (x in 0 until w) {
                val i = row + x
                if (mask[i].toInt() == 0) {  // 0 = 物体
                    kept++
                    if (x < minX) minX = x; if (x > maxX) maxX = x
                    if (y < minY) minY = y; if (y > maxY) maxY = y
                } else {
                    pixels[i] = 0  // 背景全透明
                }
            }
        }
        // 掩码占比 < 1% = 分割没抓到东西,别产出一张几乎全透明的"贴纸"
        if (kept < w * h / 100) return null
        val pad = 6
        minX = maxOf(0, minX - pad); minY = maxOf(0, minY - pad)
        maxX = minOf(w - 1, maxX + pad); maxY = minOf(h - 1, maxY + pad)
        val cut = Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888)
        cut.setPixels(pixels, 0, w, 0, 0, w, h)
        return Bitmap.createBitmap(cut, minX, minY, maxX - minX + 1, maxY - minY + 1)
    }

    companion object {
        private const val TAG = "CutoutPlugin"
        private const val MODEL_ASSET = "magic_touch.tflite"
    }
}
