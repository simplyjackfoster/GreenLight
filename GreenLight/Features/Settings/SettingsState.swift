import Foundation
import Observation

@Observable
@MainActor
final class SettingsState {
    var isChimeEnabled: Bool { didSet { persist() } }
    var sensitivity: ConfidenceSensitivity { didSet { persist() } }
    var iouThreshold: Double { didSet { persist() } }
    var useMetricUnits: Bool { didSet { persist() } }
    var showBoundingBoxes: Bool { didSet { persist() } }
    var showLabels: Bool { didSet { persist() } }
    var showSpeed: Bool { didSet { persist() } }

    private let onChange: @Sendable (SettingsValues) -> Void

    init(values: SettingsValues, onChange: @escaping @Sendable (SettingsValues) -> Void = { _ in }) {
        isChimeEnabled = values.isChimeEnabled
        sensitivity = values.sensitivity
        iouThreshold = values.iouThreshold
        useMetricUnits = values.useMetricUnits
        showBoundingBoxes = values.showBoundingBoxes
        showLabels = values.showLabels
        showSpeed = values.showSpeed
        self.onChange = onChange
    }

    private func persist() {
        onChange(currentValues())
    }

    private func currentValues() -> SettingsValues {
        SettingsValues(
            isChimeEnabled: isChimeEnabled,
            sensitivity: sensitivity,
            iouThreshold: iouThreshold,
            useMetricUnits: useMetricUnits,
            showBoundingBoxes: showBoundingBoxes,
            showLabels: showLabels,
            showSpeed: showSpeed
        )
    }
}
