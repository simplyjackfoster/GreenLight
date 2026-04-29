import Foundation

struct UserDefaultsSettingsRepository: SettingsRepository {
    private let userDefaults: UserDefaults

    init(userDefaults: UserDefaults) {
        self.userDefaults = userDefaults
    }

    func load() -> SettingsValues {
        userDefaults.register(defaults: [
            "visualizeDetections": false,
            "showLabels": true,
            "showSpeed": true,
            "iouThreshold": 0.6,
            "chimeEnabled": true,
            "confidenceSensitivity": "Medium",
            "metricUnits": false,
        ])

        return SettingsValues(
            isChimeEnabled: userDefaults.bool(forKey: "chimeEnabled"),
            sensitivity: ConfidenceSensitivity(rawValue: userDefaults.string(forKey: "confidenceSensitivity") ?? "Medium") ?? .medium,
            iouThreshold: userDefaults.double(forKey: "iouThreshold"),
            useMetricUnits: userDefaults.bool(forKey: "metricUnits"),
            showBoundingBoxes: userDefaults.bool(forKey: "visualizeDetections"),
            showLabels: userDefaults.bool(forKey: "showLabels"),
            showSpeed: userDefaults.bool(forKey: "showSpeed")
        )
    }

    func save(_ values: SettingsValues) {
        userDefaults.set(values.isChimeEnabled, forKey: "chimeEnabled")
        userDefaults.set(values.sensitivity.rawValue, forKey: "confidenceSensitivity")
        userDefaults.set(values.iouThreshold, forKey: "iouThreshold")
        userDefaults.set(values.useMetricUnits, forKey: "metricUnits")
        userDefaults.set(values.showBoundingBoxes, forKey: "visualizeDetections")
        userDefaults.set(values.showLabels, forKey: "showLabels")
        userDefaults.set(values.showSpeed, forKey: "showSpeed")
    }
}
