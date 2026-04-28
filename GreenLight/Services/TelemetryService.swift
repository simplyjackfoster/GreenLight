import Foundation

struct TelemetryEvent: Encodable {
    let timestamp: String
    let filteredLight: String
    let observedLight: String
    let speedStatus: String
    let displayState: String
    let lensSmudged: Bool

    init(result: DetectionResult, speedStatus: SpeedStatus) {
        timestamp = ISO8601DateFormatter().string(from: Date())
        filteredLight = result.lightColor.telemetryLabel
        observedLight = result.observedColor.telemetryLabel
        self.speedStatus = speedStatus.telemetryLabel
        displayState = result.lightColor.telemetryLabel
        lensSmudged = result.lensSmudged
    }
}

actor TelemetryService: TelemetryServiceProtocol {
    private let retentionDays = 7
    private let encoder = JSONEncoder()
    private var currentFileHandle: FileHandle?
    private var currentFileDate = ""

    init() {
        pruneOldFiles()
    }

    nonisolated func log(_ result: DetectionResult, speedStatus: SpeedStatus) {
        Task { await _log(result, speedStatus: speedStatus) }
    }

    private func _log(_ result: DetectionResult, speedStatus: SpeedStatus) {
        let event = TelemetryEvent(result: result, speedStatus: speedStatus)
        guard let data = try? encoder.encode(event),
              let line = String(data: data, encoding: .utf8) else { return }
        appendLine(line)
    }

    private func appendLine(_ line: String) {
        let today = dateString(from: Date())
        if today != currentFileDate {
            currentFileHandle?.closeFile()
            currentFileHandle = openHandle(for: today)
            currentFileDate = today
        }
        guard let handle = currentFileHandle,
              let data = (line + "\n").data(using: .utf8) else { return }
        handle.seekToEndOfFile()
        handle.write(data)
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
                at: dir,
                includingPropertiesForKeys: [.creationDateKey]
              ),
              let cutoff = Calendar.current.date(byAdding: .day, value: -retentionDays, to: Date()) else { return }

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
