import Foundation

enum DetectedLightColor: Equatable, Hashable {
    case red
    case green
    case yellow
    case unknown
    case none
}

enum ConfidenceSensitivity: String, CaseIterable, Identifiable {
    case low = "Low"
    case medium = "Medium"
    case high = "High"

    var id: String { rawValue }

    var confidenceThreshold: Double {
        switch self {
        case .low:
            return 0.55
        case .medium:
            return 0.70
        case .high:
            return 0.80
        }
    }
}

enum SpeedStatus: Equatable {
    case knownStationary
    case knownMoving
    case unknown
}
