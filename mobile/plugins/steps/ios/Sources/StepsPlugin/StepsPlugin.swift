import Foundation
import Capacitor
import CoreMotion

// 步数 · iOS CoreMotion CMPedometer。
// 权限 =「运动与健身」(NSMotionUsageDescription);首次真实查询即弹系统授权框,
// CoreMotion 没有独立的 request API — request() 就是做一次当日查询然后回读状态。
// today() 按自然日 0 点起查,数值精确(不需要基线近似)。
//
// JS: window.Capacitor.Plugins.Steps.probe() / .request() / .today()
@objc(StepsPlugin)
public class StepsPlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "StepsPlugin"
    public let jsName = "Steps"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "probe", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "request", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "today", returnType: CAPPluginReturnPromise)
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
}
