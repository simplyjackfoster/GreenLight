import Foundation

protocol DetectionEngineProtocol: Sendable {
    var results: AsyncStream<DetectionResult> { get }
    func attach(camera: any CameraServiceProtocol) async
}
