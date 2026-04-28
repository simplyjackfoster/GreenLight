import Foundation
import Observation

@Observable
@MainActor
final class CameraViewModel {
    var lightState: DisplayLightState = .unknown
    var speed: Double = 0
    var speedUnit: String = "MPH"
    var speedStatus: SpeedStatus = .unknown
    var showGreenAlert: Bool = false
    var showLensSmudgeWarning: Bool = false
    var boundingBoxes: [BoundingBox] = []

    private let detection: any DetectionEngineProtocol
    private let location: any LocationServiceProtocol
    private let audio: any AudioServiceProtocol
    private let telemetry: any TelemetryServiceProtocol
    let settings: SettingsStore

    private let stateManager = LightStateManager()
    private let fallback = LightTransitionFallbackState()

    init(environment: AppEnvironment) {
        detection = environment.detection
        location = environment.location
        audio = environment.audio
        telemetry = environment.telemetry
        settings = environment.settings
    }

    func start() {
        Task {
            await withTaskGroup(of: Void.self) { group in
                group.addTask { await self.consumeDetection() }
                group.addTask { await self.consumeLocation() }
            }
        }
    }

    private func consumeDetection() async {
        for await result in detection.results {
            let chime = stateManager.update(detectedLight: result.lightColor, speedStatus: speedStatus)
            let fallbackChime = stateManager.isTrackingRedOrTransitioning && fallback.update(filteredLight: result.lightColor, observedLight: result.observedColor, speedStatus: speedStatus)
            lightState = stateManager.displayState
            boundingBoxes = result.boundingBoxes
            showLensSmudgeWarning = result.lensSmudged
            if chime || fallbackChime {
                audio.play()
                triggerGreenAlert()
            }
            telemetry.log(result, speedStatus: speedStatus)
        }
    }

    private func consumeLocation() async {
        for await reading in location.readings {
            speedStatus = reading.speedStatus
            speed = reading.displaySpeed(metric: settings.useMetricUnits)
            speedUnit = settings.useMetricUnits ? "km/h" : "MPH"
        }
    }

    private func triggerGreenAlert() {
        showGreenAlert = true
        Task {
            try? await Task.sleep(for: .seconds(1.2))
            showGreenAlert = false
        }
    }
}
