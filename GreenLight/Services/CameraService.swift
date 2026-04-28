import AVFoundation
import CoreMedia
import CoreVideo

actor CameraService: CameraServiceProtocol {

    // nonisolated let so CameraPreview can access it without actor hop
    nonisolated let previewSession: AVCaptureSession = AVCaptureSession()

    let frames: AsyncStream<CVPixelBuffer>
    private let framesContinuation: AsyncStream<CVPixelBuffer>.Continuation
    private let queue = DispatchQueue(label: "com.greenlight.camera", qos: .userInitiated)
    private var bridge: CameraOutputBridge?

    init() {
        var cont: AsyncStream<CVPixelBuffer>.Continuation!
        frames = AsyncStream(bufferingPolicy: .bufferingNewest(1)) { cont = $0 }
        framesContinuation = cont
    }

    func start() async {
        await configure()
        queue.async { [previewSession] in
            guard !previewSession.isRunning else { return }
            previewSession.startRunning()
        }
    }

    func stop() async {
        queue.async { [previewSession] in
            previewSession.stopRunning()
        }
    }

    private func configure() async {
        let discovery = AVCaptureDevice.DiscoverySession(
            deviceTypes: [.builtInWideAngleCamera],
            mediaType: .video,
            position: .back
        )
        guard let device = discovery.devices.first,
              let input = try? AVCaptureDeviceInput(device: device) else { return }

        let output = AVCaptureVideoDataOutput()
        output.alwaysDiscardsLateVideoFrames = true
        output.videoSettings = [
            kCVPixelBufferPixelFormatTypeKey as String: Int(kCVPixelFormatType_420YpCbCr8BiPlanarFullRange)
        ]

        let bridge = CameraOutputBridge(continuation: framesContinuation)
        self.bridge = bridge
        output.setSampleBufferDelegate(bridge, queue: queue)

        previewSession.beginConfiguration()
        previewSession.sessionPreset = .hd1280x720
        if previewSession.canAddInput(input) { previewSession.addInput(input) }
        if previewSession.canAddOutput(output) { previewSession.addOutput(output) }

        do {
            try device.lockForConfiguration()
            device.activeVideoMinFrameDuration = CMTime(value: 1, timescale: 15)
            device.activeVideoMaxFrameDuration = CMTime(value: 1, timescale: 15)
            device.unlockForConfiguration()
        } catch {}

        previewSession.commitConfiguration()
    }
}

private final class CameraOutputBridge: NSObject, AVCaptureVideoDataOutputSampleBufferDelegate, @unchecked Sendable {
    private let continuation: AsyncStream<CVPixelBuffer>.Continuation

    init(continuation: AsyncStream<CVPixelBuffer>.Continuation) {
        self.continuation = continuation
    }

    func captureOutput(
        _ output: AVCaptureOutput,
        didOutput sampleBuffer: CMSampleBuffer,
        from connection: AVCaptureConnection
    ) {
        guard let buffer = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }
        continuation.yield(buffer)
    }
}
