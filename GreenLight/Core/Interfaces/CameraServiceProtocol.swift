import AVFoundation
import CoreVideo
import Foundation

protocol CameraServiceProtocol: Sendable {
    var previewSession: AVCaptureSession { get }
    var frames: AsyncStream<CVPixelBuffer> { get }
    func start() async
    func stop() async
}
