import Foundation

struct TelemetryEvent: Encodable {
    let timestamp: String
    let filteredLight: String
    let observedLight: String
    let speedStatus: String
    let stateMachineChime: Bool
    let fallbackChime: Bool
    let displayState: String

    init(
        filteredLight: DetectedLightColor,
        observedLight: DetectedLightColor,
        speedStatus: SpeedStatus,
        stateMachineChime: Bool,
        fallbackChime: Bool,
        displayState: DetectedLightColor
    ) {
        self.timestamp = ISO8601DateFormatter().string(from: Date())
        self.filteredLight = filteredLight.telemetryLabel
        self.observedLight = observedLight.telemetryLabel
        self.speedStatus = speedStatus.telemetryLabel
        self.stateMachineChime = stateMachineChime
        self.fallbackChime = fallbackChime
        self.displayState = displayState.telemetryLabel
    }
}

final class TelemetryLogger {
    static let shared = TelemetryLogger()

    private let queue = DispatchQueue(label: "TelemetryLogger", qos: .utility)
    private let retentionDays = 7
    private let encoder = JSONEncoder()

    private var currentFileHandle: FileHandle?
    private var currentFileDate: String = ""

    private init() {
        queue.async { self.pruneOldFiles() }
    }

    func log(_ event: TelemetryEvent) {
        queue.async { [self] in
            guard let data = try? encoder.encode(event),
                  let line = String(data: data, encoding: .utf8) else { return }
            appendLine(line)
        }
    }

    private func appendLine(_ line: String) {
        let today = dateString(from: Date())
        if today != currentFileDate {
            currentFileHandle?.closeFile()
            currentFileHandle = openHandle(for: today)
            currentFileDate = today
        }
        guard let handle = currentFileHandle else { return }
        handle.seekToEndOfFile()
        handle.write((line + "\n").data(using: .utf8)!)
    }

    private func openHandle(for dateString: String) -> FileHandle? {
        guard let dir = telemetryDirectory() else { return nil }
        let url = dir.appendingPathComponent("\(dateString).jsonl")
        if !FileManager.default.fileExists(atPath: url.path) {
            FileManager.default.createFile(atPath: url.path, contents: nil)
        }
        return try? FileHandle(forWritingTo: url)
    }

    private func pruneOldFiles() {
        guard let dir = telemetryDirectory(),
              let files = try? FileManager.default.contentsOfDirectory(
                  at: dir, includingPropertiesForKeys: [.creationDateKey]) else { return }
        guard let cutoff = Calendar.current.date(byAdding: .day, value: -retentionDays, to: Date()) else {
            return
        }
        for file in files {
            guard let created = try? file.resourceValues(forKeys: [.creationDateKey]).creationDate,
                  created < cutoff else { continue }
            try? FileManager.default.removeItem(at: file)
        }
    }

    private func telemetryDirectory() -> URL? {
        guard let docs = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first else {
            return nil
        }
        let dir = docs.appendingPathComponent("telemetry")
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir
    }

    private func dateString(from date: Date) -> String {
        let fmt = DateFormatter()
        fmt.dateFormat = "yyyy-MM-dd"
        return fmt.string(from: date)
    }
}

private extension DetectedLightColor {
    var telemetryLabel: String {
        switch self {
        case .red: return "red"
        case .green: return "green"
        case .yellow: return "yellow"
        case .unknown: return "unknown"
        case .none: return "none"
        }
    }
}

private extension SpeedStatus {
    var telemetryLabel: String {
        switch self {
        case .knownStationary: return "stationary"
        case .knownMoving: return "moving"
        case .unknown: return "unknown"
        }
    }
}
