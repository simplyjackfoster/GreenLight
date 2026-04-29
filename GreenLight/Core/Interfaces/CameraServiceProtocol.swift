@preconcurrency import AVFoundation
@preconcurrency import CoreVideo
import Foundation

struct CameraFrame: @unchecked Sendable {
    let pixelBuffer: CVPixelBuffer
}

protocol CameraServiceProtocol: Sendable {
    var previewSession: AVCaptureSession { get }
    var frames: AsyncStream<CameraFrame> { get async }
    func start() async
    func stop() async
}
