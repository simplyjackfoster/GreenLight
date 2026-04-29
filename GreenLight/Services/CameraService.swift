@preconcurrency import AVFoundation
import CoreMedia
@preconcurrency import CoreVideo

actor CameraService: CameraServiceProtocol {

    // nonisolated let so CameraPreview can access it without actor hop
    nonisolated let previewSession: AVCaptureSession = AVCaptureSession()

    let frames: AsyncStream<CameraFrame>
    private let framesContinuation: AsyncStream<CameraFrame>.Continuation
    private let queue = DispatchQueue(label: "com.greenlight.camera", qos: .userInitiated)
    private var bridge: CameraOutputBridge?

    init() {
        var cont: AsyncStream<CameraFrame>.Continuation!
        frames = AsyncStream(bufferingPolicy: .bufferingNewest(1)) { cont = $0 }
        framesContinuation = cont
    }

    func start() async {
        await configure()
        queue.async { [weak self] in
            guard let self else { return }
            guard !self.previewSession.isRunning else { return }
            self.previewSession.startRunning()
        }
    }

    func stop() async {
        queue.async { [weak self] in
            guard let self else { return }
            self.previewSession.stopRunning()
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
            device.activeVideoMinFrameDuration = CMTime(value: 1, timescale: 30)
            device.activeVideoMaxFrameDuration = CMTime(value: 1, timescale: 30)
            device.unlockForConfiguration()
        } catch {}

        previewSession.commitConfiguration()
    }
}

private final class CameraOutputBridge: NSObject, AVCaptureVideoDataOutputSampleBufferDelegate, @unchecked Sendable {
    private let continuation: AsyncStream<CameraFrame>.Continuation

    init(continuation: AsyncStream<CameraFrame>.Continuation) {
        self.continuation = continuation
    }

    func captureOutput(
        _ output: AVCaptureOutput,
        didOutput sampleBuffer: CMSampleBuffer,
        from connection: AVCaptureConnection
    ) {
        guard let buffer = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }
        continuation.yield(CameraFrame(pixelBuffer: buffer))
    }
}
