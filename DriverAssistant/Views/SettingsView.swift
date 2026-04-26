import SwiftUI

struct SettingsView: View {

    @ObservedObject private var state = DetectionState.shared

    @AppStorage("visualizeDetections") private var visualizeDetections = true
    @AppStorage("showLabels") private var showLabels = true
    @AppStorage("showSpeed") private var showSpeed = true
    @AppStorage("iouThreshold") private var iouThreshold: Double = 0.6

    var body: some View {
        Form {
            Section(header: Text("Green Light Chime")) {
                Toggle("Enable chime", isOn: $state.isChimeEnabled)
                Picker("Sensitivity", selection: $state.sensitivity) {
                    ForEach(ConfidenceSensitivity.allCases) { level in
                        Text(level.rawValue).tag(level)
                    }
                }
                .pickerStyle(.segmented)
            }

            Section(header: Text("Display")) {
                Toggle("Show speed", isOn: $showSpeed)
                Toggle("Use metric units", isOn: $state.useMetricUnits)
                Toggle("Show bounding boxes", isOn: $visualizeDetections)
                Toggle("Show labels", isOn: $showLabels)
            }

            Section(header: Text("Detector (Advanced)")) {
                VStack(alignment: .leading) {
                    Text("IoU threshold: \(iouThreshold, specifier: "%.2f")")
                        .font(.caption)
                        .foregroundColor(.secondary)
                    Slider(value: $iouThreshold, in: 0...1)
                }
            }

            Section(header: Text("About")) {
                NavigationLink("How detection works") {
                    WebView()
                }
                Text("All processing is on-device. No data leaves your phone.")
                    .font(.caption)
                    .foregroundColor(.secondary)
            }
        }
        .navigationTitle("Settings")
    }
}
