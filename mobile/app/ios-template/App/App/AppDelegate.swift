import UIKit
import Capacitor

@UIApplicationMain
class AppDelegate: UIResponder, UIApplicationDelegate {

    var window: UIWindow?

    func application(_ application: UIApplication, didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?) -> Bool {
        // critic 标的 trap fix:用户大量贴图会撑爆 iCloud 5GB(@capacitor/filesystem
        // v6 默认走 Library/NoCloud 但不保证子目录继承 skipBackup)
        excludeAttachmentsFromBackup()
        return true
    }

    /// 给 Library/NoCloud/attachments/ 显式打 NSURLIsExcludedFromBackupKey
    /// (Capacitor 6 没暴露这个 API,只能 Swift bridge 直接调 NSURL)
    private func excludeAttachmentsFromBackup() {
        guard let libDir = FileManager.default.urls(for: .libraryDirectory, in: .userDomainMask).first else { return }
        let attachmentsDir = libDir.appendingPathComponent("NoCloud/attachments", isDirectory: true)
        try? FileManager.default.createDirectory(at: attachmentsDir, withIntermediateDirectories: true, attributes: nil)
        var url = attachmentsDir
        var values = URLResourceValues()
        values.isExcludedFromBackup = true
        try? url.setResourceValues(values)
    }

    func applicationWillResignActive(_ application: UIApplication) {}
    func applicationDidEnterBackground(_ application: UIApplication) {}
    func applicationWillEnterForeground(_ application: UIApplication) {}
    func applicationDidBecomeActive(_ application: UIApplication) {}
    func applicationWillTerminate(_ application: UIApplication) {}

    func application(_ app: UIApplication, open url: URL, options: [UIApplication.OpenURLOptionsKey: Any] = [:]) -> Bool {
        return ApplicationDelegateProxy.shared.application(app, open: url, options: options)
    }

    func application(_ application: UIApplication, continue userActivity: NSUserActivity, restorationHandler: @escaping ([UIUserActivityRestoring]?) -> Void) -> Bool {
        return ApplicationDelegateProxy.shared.application(application, continue: userActivity, restorationHandler: restorationHandler)
    }

}
