import AVFoundation
import CoreVideo
import Foundation

protocol CameraServiceProtocol: Sendable {
    var previewSession: AVCaptureSession { get }
    var frames: AsyncStream<CVPixelBuffer> { get }
    func start() async
    func stop() async
}

protocol DetectionEngineProtocol: Sendable {
    var results: AsyncStream<DetectionResult> { get }
    func attach(camera: any CameraServiceProtocol) async
}

protocol LocationServiceProtocol: Sendable {
    var readings: AsyncStream<SpeedReading> { get }
    func start() async
}

protocol AudioServiceProtocol: Sendable {
    var isMuted: Bool { get async }
    func setMuted(_ muted: Bool) async
    func play()
}

protocol TelemetryServiceProtocol: Sendable {
    func log(_ result: DetectionResult, speedStatus: SpeedStatus)
}
