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
import com.getcapacitor.JSObject
import com.getcapacitor.PermissionState
import com.getcapacitor.Plugin
import com.getcapacitor.PluginCall
import com.getcapacitor.PluginMethod
import com.getcapacitor.annotation.CapacitorPlugin
import com.getcapacitor.annotation.Permission
import com.getcapacitor.annotation.PermissionCallback
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * 步数 · Android TYPE_STEP_COUNTER 传感器(值 = 开机以来累计)。
 * 走传感器而非 Health Connect:国行 ROM 无 Google 服务也可用。
 *
 * "今日步数"用 SharedPreferences 记每日基线做近似:
 *   - 当天首读:以当前累计值为基线(首日从此刻起算)→ approximate=true
 *   - 重启后累计回落:基线清零 → approximate=true
 *   - 同日后续读数:steps = 累计 - 基线
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

    @PluginMethod
    fun today(call: PluginCall) {
        val st = stateString()
        if (st != "granted") { call.reject("not-granted:$st"); return }
        val sm = sensorManager()
        val sensor = sm.getDefaultSensor(Sensor.TYPE_STEP_COUNTER)
            ?: run { call.reject("unavailable"); return }
        call.setKeepAlive(true)
        var done = false
        val listener = object : SensorEventListener {
            override fun onSensorChanged(e: SensorEvent) {
                if (done) return; done = true
                sm.unregisterListener(this)
                resolveWith(call, e.values[0].toLong())
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

    private fun resolveWith(call: PluginCall, cumulative: Long) {
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
        val r = JSObject()
        r.put("steps", cumulative - base)
        r.put("since", todayKey)
        r.put("source", "sensor")
        r.put("approximate", approximate)
        call.resolve(r)
    }
}
