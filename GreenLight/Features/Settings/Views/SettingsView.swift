import SwiftUI

struct SettingsView: View {
    @Environment(\.dismiss) private var dismiss
    @Bindable var settings: SettingsState

    var body: some View {
        NavigationStack {
            Form {
                Section("Chime") {
                    Toggle("Enable chime", isOn: $settings.isChimeEnabled)
                    Picker("Sensitivity", selection: $settings.sensitivity) {
                        ForEach(ConfidenceSensitivity.allCases) { level in
                            Text(level.rawValue).tag(level)
                        }
                    }
                }
                Section("Display") {
                    Toggle("Show speed", isOn: $settings.showSpeed)
                    Toggle("Metric units", isOn: $settings.useMetricUnits)
                    Toggle("Bounding boxes", isOn: $settings.showBoundingBoxes)
                    Toggle("Labels", isOn: $settings.showLabels)
                }
            }
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") { dismiss() }
                }
            }
        }
    }
}
