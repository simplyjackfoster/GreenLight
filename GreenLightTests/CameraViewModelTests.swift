import AVFoundation
import CoreVideo
import XCTest
@testable import GreenLight

@MainActor
final class CameraViewModelTests: XCTestCase {

    func testStartBeginsServicesAndAppliesMuteSetting() async {
        let camera = FakeCameraService()
        let detection = FakeDetectionEngine()
        let location = FakeLocationService()
        let audio = FakeAudioService()
        let telemetry = FakeTelemetryService()
        let settings = SettingsState(values: SettingsValues(
            isChimeEnabled: false,
            sensitivity: .medium,
            iouThreshold: 0.6,
            useMetricUnits: false,
            showBoundingBoxes: false,
            showLabels: true,
            showSpeed: true
        ))

        let container = AppDependencyContainer(
            camera: camera,
            detection: detection,
            location: location,
            audio: audio,
            telemetry: telemetry,
            settings: settings
        )
        let viewModel = CameraViewModel(dependencies: container)

        viewModel.start()
        try? await Task.sleep(for: .milliseconds(80))

        XCTAssertGreaterThan(camera.startCallCount, 0)
        XCTAssertGreaterThan(location.startCallCount, 0)
        let muted = await audio.isMuted
        XCTAssertTrue(muted)
    }

    func testStreamsUpdateDisplayedStateAndTelemetry() async {
        let camera = FakeCameraService()
        let detection = FakeDetectionEngine()
        let location = FakeLocationService()
        let audio = FakeAudioService()
        let telemetry = FakeTelemetryService()
        let settings = SettingsState(values: SettingsValues(
            isChimeEnabled: true,
            sensitivity: .medium,
            iouThreshold: 0.6,
            useMetricUnits: false,
            showBoundingBoxes: false,
            showLabels: true,
            showSpeed: true
        ))

        let container = AppDependencyContainer(
            camera: camera,
            detection: detection,
            location: location,
            audio: audio,
            telemetry: telemetry,
            settings: settings
        )
        let viewModel = CameraViewModel(dependencies: container)

        viewModel.start()
        try? await Task.sleep(for: .milliseconds(40))

        location.push(SpeedReading(metersPerSecond: 5.36, mph: 12.0, speedStatus: .knownMoving))
        detection.push(DetectionResult(
            lightColor: .red,
            observedColor: .red,
            boundingBoxes: [BoundingBox(rect: .init(x: 0, y: 0, width: 0.2, height: 0.2), label: "traffic_light_red", confidence: 0.93)]
        ))

        try? await Task.sleep(for: .milliseconds(120))

        XCTAssertEqual(viewModel.lightState, .red)
        XCTAssertEqual(viewModel.boundingBoxes.count, 1)
        XCTAssertEqual(viewModel.speedUnit, "MPH")
        XCTAssertEqual(viewModel.speedStatus, .knownMoving)
        XCTAssertEqual(telemetry.logCount, 1)
        XCTAssertEqual(audio.playCallCount, 0)
    }
}

final class FakeCameraService: CameraServiceProtocol, @unchecked Sendable {
    let previewSession = AVCaptureSession()
    let frames: AsyncStream<CVPixelBuffer>
    private let framesContinuation: AsyncStream<CVPixelBuffer>.Continuation
    private(set) var startCallCount = 0

    init() {
        var cont: AsyncStream<CVPixelBuffer>.Continuation!
        frames = AsyncStream { cont = $0 }
        framesContinuation = cont
    }

    func start() async {
        startCallCount += 1
    }

    func stop() async {}
}

final class FakeDetectionEngine: DetectionEngineProtocol, @unchecked Sendable {
    let results: AsyncStream<DetectionResult>
    private let continuation: AsyncStream<DetectionResult>.Continuation

    init() {
        var cont: AsyncStream<DetectionResult>.Continuation!
        results = AsyncStream { cont = $0 }
        continuation = cont
    }

    func attach(camera: any CameraServiceProtocol) async {}

    func push(_ result: DetectionResult) {
        continuation.yield(result)
    }
}

final class FakeLocationService: LocationServiceProtocol, @unchecked Sendable {
    let readings: AsyncStream<SpeedReading>
    private let continuation: AsyncStream<SpeedReading>.Continuation
    private(set) var startCallCount = 0

    init() {
        var cont: AsyncStream<SpeedReading>.Continuation!
        readings = AsyncStream { cont = $0 }
        continuation = cont
    }

    func start() async {
        startCallCount += 1
    }

    func push(_ reading: SpeedReading) {
        continuation.yield(reading)
    }
}

final class FakeAudioService: AudioServiceProtocol, @unchecked Sendable {
    private(set) var muted = false
    private(set) var playCallCount = 0

    var isMuted: Bool {
        get async {
            muted
        }
    }

    func setMuted(_ muted: Bool) async {
        self.muted = muted
    }

    func play() {
        playCallCount += 1
    }
}

final class FakeTelemetryService: TelemetryServiceProtocol, @unchecked Sendable {
    private(set) var logCount = 0

    func log(_ result: DetectionResult, speedStatus: SpeedStatus) {
        logCount += 1
    }
}
