import Foundation

protocol TelemetryServiceProtocol: Sendable {
    func log(_ result: DetectionResult, speedStatus: SpeedStatus)
}
