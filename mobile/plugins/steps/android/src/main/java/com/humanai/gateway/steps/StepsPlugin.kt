package com.humanai.gateway.steps

import android.Manifest
import android.content.Context
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.os.Build
import android.os.Handler
import android.os.Looper
import com.getcapacitor.JSArray
import com.getcapacitor.JSObject
import com.getcapacitor.PermissionState
import com.getcapacitor.Plugin
import com.getcapacitor.PluginCall
import com.getcapacitor.PluginMethod
import com.getcapacitor.annotation.CapacitorPlugin
import com.getcapacitor.annotation.Permission
import com.getcapacitor.annotation.PermissionCallback
import org.json.JSONArray
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * 步数 · Android TYPE_STEP_COUNTER 传感器(值 = 开机以来累计)。
 * 走传感器而非 Health Connect:国行 ROM 无 Google 服务也可用。
 *
 * 局限:传感器只有"当前累计",没有历史查询。因此:
 *   - "今日步数"用 SharedPreferences 记每日基线近似(首日/重启后 approximate=true)
 *   - "分时步数"(stats.recent)靠使用时打点:每次读数存 (ts, cumulative) 采样,
 *     相邻采样差值 = 该区间步数。app 不开就没有打点 → 分段可能稀疏,诚实返回。
 */
@CapacitorPlugin(
    name = "Steps",
    permissions = [Permission(alias = "activity", strings = [Manifest.permission.ACTIVITY_RECOGNITION])]
)
class StepsPlugin : Plugin() {

    private fun sensorManager(): SensorManager =
        context.getSystemService(Context.SENSOR_SERVICE) as SensorManager

    private fun sensorAvailable(): Boolean =
        sensorManager().getDefaultSensor(Sensor.TYPE_STEP_COUNTER) != null

    private fun stateString(): String {
        if (!sensorAvailable()) return "unavailable"
        if (Build.VERSION.SDK_INT < 29) return "granted"  // Q 之前无该运行时权限
        return when (getPermissionState("activity")) {
            PermissionState.GRANTED -> "granted"
            PermissionState.DENIED -> "denied"
            else -> "undetermined"
        }
    }

    @PluginMethod
    fun probe(call: PluginCall) {
        val r = JSObject(); r.put("state", stateString()); call.resolve(r)
    }

    @PluginMethod
    fun request(call: PluginCall) {
        if (!sensorAvailable() || Build.VERSION.SDK_INT < 29 || stateString() == "granted") {
            probe(call); return
        }
        requestPermissionForAlias("activity", call, "permDone")
    }

    @PermissionCallback
    private fun permDone(call: PluginCall) { probe(call) }

    // ── 一次性读当前累计值(3 秒超时) ──────────────────────
    private fun readCounter(call: PluginCall, onValue: (Long) -> Unit) {
        val sm = sensorManager()
        val sensor = sm.getDefaultSensor(Sensor.TYPE_STEP_COUNTER)
            ?: run { call.reject("unavailable"); return }
        call.setKeepAlive(true)
        var done = false
        val listener = object : SensorEventListener {
            override fun onSensorChanged(e: SensorEvent) {
                if (done) return; done = true
                sm.unregisterListener(this)
                onValue(e.values[0].toLong())
            }
            override fun onAccuracyChanged(s: Sensor?, a: Int) {}
        }
        sm.registerListener(listener, sensor, SensorManager.SENSOR_DELAY_FASTEST)
        Handler(Looper.getMainLooper()).postDelayed({
            if (!done) {
                done = true
                sm.unregisterListener(listener)
                call.reject("no-reading — 传感器 3 秒无读数(可能设备无计步硬件)")
            }
        }, 3000)
    }

    // ── 今日基线(近似) ────────────────────────────────────
    private fun todayFromBaseline(cumulative: Long): Pair<Long, Boolean> {
        val prefs = context.getSharedPreferences("gw_steps", Context.MODE_PRIVATE)
        val todayKey = SimpleDateFormat("yyyy-MM-dd", Locale.US).format(Date())
        var base = prefs.getLong("base", -1L)
        val baseDate = prefs.getString("date", "") ?: ""
        var approximate = false
        if (baseDate != todayKey || base < 0) {   // 新的一天 / 首次:从此刻起算
            base = cumulative; approximate = true
            prefs.edit().putString("date", todayKey).putLong("base", base).apply()
        } else if (cumulative < base) {           // 重启:累计回落,基线清零
            base = 0; approximate = true
            prefs.edit().putLong("base", 0).apply()
        }
        return Pair(cumulative - base, approximate)
    }

    @PluginMethod
    fun today(call: PluginCall) {
        val st = stateString()
        if (st != "granted") { call.reject("not-granted:$st"); return }
        readCounter(call) { cum ->
            val (steps, approx) = todayFromBaseline(cum)
            val r = JSObject()
            r.put("steps", steps)
            r.put("since", SimpleDateFormat("yyyy-MM-dd", Locale.US).format(Date()))
            r.put("source", "sensor")
            r.put("approximate", approx)
            call.resolve(r)
        }
    }

    // ── 当日统计 + 采样分段(最近 N 小时) ──────────────────
    @PluginMethod
    fun stats(call: PluginCall) {
        val st = stateString()
        if (st != "granted") { call.reject("not-granted:$st"); return }
        val hours = (call.getInt("hours") ?: 6).coerceIn(1, 12)
        readCounter(call) { cum ->
            val (steps, approx) = todayFromBaseline(cum)
            val recent = sampleAndSegments(cum, hours)
            val r = JSObject()
            r.put("today", steps)
            r.put("since", SimpleDateFormat("yyyy-MM-dd", Locale.US).format(Date()))
            r.put("source", "sensor")
            r.put("approximate", approx)
            r.put("recent", recent)
            call.resolve(r)
        }
    }

    // 打点 + 生成分段:samples 存 [[tsMs, cumulative], ...],保留 26h;
    // 相邻采样差 = 区间步数;累计回落(重启)的区间丢弃。
    private fun sampleAndSegments(cumulative: Long, hours: Int): JSArray {
        val prefs = context.getSharedPreferences("gw_steps", Context.MODE_PRIVATE)
        val nowMs = System.currentTimeMillis()
        val arr = try { JSONArray(prefs.getString("samples", "[]")) } catch (e: Exception) { JSONArray() }
        // 追加当前点(距上个采样 >60s 才记,防抖)
        val kept = JSONArray()
        var lastTs = 0L
        for (i in 0 until arr.length()) {
            val s = arr.optJSONArray(i) ?: continue
            val ts = s.optLong(0)
            if (nowMs - ts <= 26 * 3600_000L) { kept.put(s); lastTs = ts }
        }
        if (nowMs - lastTs > 60_000L) {
            kept.put(JSONArray().put(nowMs).put(cumulative))
        }
        prefs.edit().putString("samples", kept.toString()).apply()

        // 窗口内相邻采样 → 分段
        val fmt = SimpleDateFormat("HH:mm", Locale.US)
        val windowStart = nowMs - hours * 3600_000L
        val out = JSArray()
        var prevTs = -1L; var prevCum = -1L
        for (i in 0 until kept.length()) {
            val s = kept.optJSONArray(i) ?: continue
            val ts = s.optLong(0); val c = s.optLong(1)
            if (ts < windowStart) { prevTs = ts; prevCum = c; continue }
            if (prevTs > 0 && prevCum >= 0 && c >= prevCum) {
                val seg = JSObject()
                seg.put("from", fmt.format(Date(if (prevTs < windowStart) windowStart else prevTs)))
                seg.put("to", fmt.format(Date(ts)))
                seg.put("steps", c - prevCum)
                out.put(seg)
            }
            prevTs = ts; prevCum = c
        }
        return out
    }
}
