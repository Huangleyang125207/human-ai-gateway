import Foundation
import Capacitor
import CoreMotion

// 步数 · iOS CoreMotion CMPedometer。
// 权限 =「运动与健身」(NSMotionUsageDescription);首次真实查询即弹系统授权框,
// CoreMotion 没有独立的 request API — request() 就是做一次当日查询然后回读状态。
// stats() = 当日累计 + 最近 N 小时整点分桶(CMPedometer 支持任意区间查询,数值精确)。
//
// JS: window.Capacitor.Plugins.Steps.probe() / .request() / .today() / .stats({hours})
@objc(StepsPlugin)
public class StepsPlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "StepsPlugin"
    public let jsName = "Steps"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "probe", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "request", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "today", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "stats", returnType: CAPPluginReturnPromise)
    ]

    private let pedometer = CMPedometer()

    private func stateString() -> String {
        guard CMPedometer.isStepCountingAvailable() else { return "unavailable" }
        switch CMPedometer.authorizationStatus() {
        case .authorized: return "granted"
        case .denied, .restricted: return "denied"
        case .notDetermined: return "undetermined"
        @unknown default: return "undetermined"
        }
    }

    @objc func probe(_ call: CAPPluginCall) {
        call.resolve(["state": stateString()])
    }

    @objc func request(_ call: CAPPluginCall) {
        guard CMPedometer.isStepCountingAvailable() else {
            call.resolve(["state": "unavailable"]); return
        }
        let start = Calendar.current.startOfDay(for: Date())
        pedometer.queryPedometerData(from: start, to: Date()) { [weak self] _, _ in
            DispatchQueue.main.async {
                call.resolve(["state": self?.stateString() ?? "undetermined"])
            }
        }
    }

    @objc func today(_ call: CAPPluginCall) {
        guard CMPedometer.isStepCountingAvailable() else {
            call.reject("unavailable"); return
        }
        let start = Calendar.current.startOfDay(for: Date())
        pedometer.queryPedometerData(from: start, to: Date()) { data, error in
            DispatchQueue.main.async {
                if let d = data {
                    call.resolve([
                        "steps": d.numberOfSteps.intValue,
                        "since": ISO8601DateFormatter().string(from: start),
                        "source": "coremotion",
                        "approximate": false
                    ])
                } else {
                    call.reject(error?.localizedDescription ?? "no-data")
                }
            }
        }
    }

    // 当日累计 + 最近 N 小时整点分桶(旧→新;末桶是"本小时整点→现在")
    @objc func stats(_ call: CAPPluginCall) {
        guard CMPedometer.isStepCountingAvailable() else {
            call.reject("unavailable"); return
        }
        let hoursWanted = min(max(call.getInt("hours") ?? 6, 1), 12)
        let now = Date()
        let cal = Calendar.current
        let startOfDay = cal.startOfDay(for: now)

        // 分桶:从当前整点往回退 hoursWanted 个
        var buckets: [(Date, Date)] = []
        var bucketEnd = now
        var bucketStart = cal.dateInterval(of: .hour, for: now)?.start ?? now.addingTimeInterval(-3600)
        for _ in 0..<hoursWanted {
            buckets.append((bucketStart, bucketEnd))
            bucketEnd = bucketStart
            bucketStart = bucketStart.addingTimeInterval(-3600)
        }

        let group = DispatchGroup()
        var perBucket = [Int: Int]()
        var todaySteps = -1
        group.enter()
        pedometer.queryPedometerData(from: startOfDay, to: now) { d, _ in
            todaySteps = d?.numberOfSteps.intValue ?? -1
            group.leave()
        }
        for (i, b) in buckets.enumerated() {
            group.enter()
            pedometer.queryPedometerData(from: b.0, to: b.1) { d, _ in
                perBucket[i] = d?.numberOfSteps.intValue ?? -1
                group.leave()
            }
        }
        group.notify(queue: .main) {
            let fmt = DateFormatter()
            fmt.dateFormat = "HH:mm"
            var recent: [[String: Any]] = []
            for (i, b) in buckets.enumerated().reversed() {  // 旧 → 新
                recent.append(["from": fmt.string(from: b.0), "to": fmt.string(from: b.1), "steps": perBucket[i] ?? -1])
            }
            call.resolve([
                "today": todaySteps,
                "since": ISO8601DateFormatter().string(from: startOfDay),
                "source": "coremotion",
                "approximate": false,
                "recent": recent
            ])
        }
    }
}
