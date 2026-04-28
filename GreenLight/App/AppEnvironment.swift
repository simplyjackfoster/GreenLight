import Foundation

@MainActor
final class AppEnvironment {
    let camera: any CameraServiceProtocol
    let detection: any DetectionEngineProtocol
    let location: any LocationServiceProtocol
    let audio: any AudioServiceProtocol
    let telemetry: any TelemetryServiceProtocol
    let settings: SettingsStore

    init(
        camera: any CameraServiceProtocol,
        detection: any DetectionEngineProtocol,
        location: any LocationServiceProtocol,
        audio: any AudioServiceProtocol,
        telemetry: any TelemetryServiceProtocol,
        settings: SettingsStore
    ) {
        self.camera = camera
        self.detection = detection
        self.location = location
        self.audio = audio
        self.telemetry = telemetry
        self.settings = settings
    }

    static let live: AppEnvironment = {
        let settings = SettingsStore()
        let camera = CameraService()
        let detection = DetectionEngine()
        let location = LocationService()
        let audio = AudioService()
        let telemetry = TelemetryService()
        Task { await detection.attach(camera: camera) }
        return AppEnvironment(camera: camera, detection: detection, location: location, audio: audio, telemetry: telemetry, settings: settings)
    }()
}
