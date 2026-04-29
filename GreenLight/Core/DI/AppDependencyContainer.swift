import Foundation

@MainActor
final class AppDependencyContainer {
    let camera: any CameraServiceProtocol
    let detection: any DetectionEngineProtocol
    let location: any LocationServiceProtocol
    let audio: any AudioServiceProtocol
    let telemetry: any TelemetryServiceProtocol
    let settings: SettingsState

    init(
        camera: any CameraServiceProtocol,
        detection: any DetectionEngineProtocol,
        location: any LocationServiceProtocol,
        audio: any AudioServiceProtocol,
        telemetry: any TelemetryServiceProtocol,
        settings: SettingsState
    ) {
        self.camera = camera
        self.detection = detection
        self.location = location
        self.audio = audio
        self.telemetry = telemetry
        self.settings = settings
    }

    static let live: AppDependencyContainer = {
        let settingsRepository = UserDefaultsSettingsRepository(userDefaults: .standard)
        let settings = SettingsState(values: settingsRepository.load()) { values in
            settingsRepository.save(values)
        }
        let camera = CameraService()
        let detection = DetectionEngine()
        let location = LocationService()
        let audio = AudioService()
        let telemetry = TelemetryService()
        Task { await detection.attach(camera: camera) }
        return AppDependencyContainer(
            camera: camera,
            detection: detection,
            location: location,
            audio: audio,
            telemetry: telemetry,
            settings: settings
        )
    }()
}
