import CoreGraphics
import Foundation

enum DetectedLightColor: Equatable, Hashable, Sendable {
    case red
    case green
    case yellow
    case unknown
    case none
}

enum DisplayLightState: Equatable, Sendable {
    case red
    case green
    case yellow
    case unknown
}

enum ConfidenceSensitivity: String, CaseIterable, Identifiable, Sendable {
    case low = "Low"
    case medium = "Medium"
    case high = "High"

    var id: String { rawValue }

    var confidenceThreshold: Double {
        switch self {
        case .low: return 0.55
        case .medium: return 0.70
        case .high: return 0.80
        }
    }
}

enum SpeedStatus: Equatable, Sendable {
    case knownStationary
    case knownMoving
    case unknown
}

struct SpeedReading: Sendable {
    var metersPerSecond: Double
    var mph: Double
    var speedStatus: SpeedStatus

    func displaySpeed(metric: Bool) -> Double {
        metric ? metersPerSecond * 3.6 : mph
    }
}

struct BoundingBox: Sendable, Equatable {
    var rect: CGRect
    var label: String
    var confidence: Float
}

extension DetectedLightColor {
    var displayState: DisplayLightState {
        switch self {
        case .red: return .red
        case .green: return .green
        case .yellow: return .yellow
        case .unknown, .none: return .unknown
        }
    }

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

extension SpeedStatus {
    var telemetryLabel: String {
        switch self {
        case .knownStationary: return "stationary"
        case .knownMoving: return "moving"
        case .unknown: return "unknown"
        }
    }
}
