import Foundation

struct SettingsValues: Sendable {
    var isChimeEnabled: Bool
    var sensitivity: ConfidenceSensitivity
    var iouThreshold: Double
    var useMetricUnits: Bool
    var showBoundingBoxes: Bool
    var showLabels: Bool
    var showSpeed: Bool
}

protocol SettingsRepository {
    func load() -> SettingsValues
    func save(_ values: SettingsValues)
}
