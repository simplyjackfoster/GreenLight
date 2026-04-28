import Foundation
import Observation

@Observable
@MainActor
final class SettingsStore {
    var isChimeEnabled: Bool {
        didSet { UserDefaults.standard.set(isChimeEnabled, forKey: "chimeEnabled") }
    }
    var sensitivity: ConfidenceSensitivity {
        didSet { UserDefaults.standard.set(sensitivity.rawValue, forKey: "confidenceSensitivity") }
    }
    var iouThreshold: Double {
        didSet { UserDefaults.standard.set(iouThreshold, forKey: "iouThreshold") }
    }
    var useMetricUnits: Bool {
        didSet { UserDefaults.standard.set(useMetricUnits, forKey: "metricUnits") }
    }
    var showBoundingBoxes: Bool {
        didSet { UserDefaults.standard.set(showBoundingBoxes, forKey: "visualizeDetections") }
    }
    var showLabels: Bool {
        didSet { UserDefaults.standard.set(showLabels, forKey: "showLabels") }
    }
    var showSpeed: Bool {
        didSet { UserDefaults.standard.set(showSpeed, forKey: "showSpeed") }
    }

    init() {
        let d = UserDefaults.standard
        d.register(defaults: [
            "visualizeDetections": false,
            "showLabels": true,
            "showSpeed": true,
            "iouThreshold": 0.6,
            "chimeEnabled": true,
            "confidenceSensitivity": "Medium",
            "metricUnits": false,
        ])
        isChimeEnabled = d.bool(forKey: "chimeEnabled")
        sensitivity = ConfidenceSensitivity(rawValue: d.string(forKey: "confidenceSensitivity") ?? "Medium") ?? .medium
        iouThreshold = d.double(forKey: "iouThreshold")
        useMetricUnits = d.bool(forKey: "metricUnits")
        showBoundingBoxes = d.bool(forKey: "visualizeDetections")
        showLabels = d.bool(forKey: "showLabels")
        showSpeed = d.bool(forKey: "showSpeed")
    }
}
