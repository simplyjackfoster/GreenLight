import AVFoundation
import UIKit

@main
class AppDelegate: UIResponder, UIApplicationDelegate {

    func application(
        _ application: UIApplication,
        didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?
    ) -> Bool {
        registerUserDefaults()
        configureAudioSession()
        return true
    }

    func application(
        _ application: UIApplication,
        configurationForConnecting connectingSceneSession: UISceneSession,
        options: UIScene.ConnectionOptions
    ) -> UISceneConfiguration {
        UISceneConfiguration(name: "Default Configuration", sessionRole: connectingSceneSession.role)
    }

    private func configureAudioSession() {
        do {
            // FIXED: ambient mode is suppressed by hardware silent switch; use playback for audible safety chime.
            try AVAudioSession.sharedInstance().setCategory(
                .playback,
                mode: .default,
                options: [.duckOthers]
            )
            try AVAudioSession.sharedInstance().setActive(true)
        } catch {
            print("[AppDelegate] Audio session configuration failed: \(error)")
        }
    }

    // FIXED: ensure first-launch defaults don't evaluate to false when read with UserDefaults.bool(forKey:)
    private func registerUserDefaults() {
        UserDefaults.standard.register(defaults: [
            "visualizeDetections": true,
            "showLabels": true,
            "showSpeed": true,
            "iouThreshold": 0.6,
            "chimeEnabled": true,
            "confidenceSensitivity": "Medium",
            "metricUnits": false,
        ])
    }
}
