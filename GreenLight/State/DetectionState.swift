import Combine
import CoreLocation
import Foundation

@MainActor
final class DetectionState: NSObject, ObservableObject {

    static let shared = DetectionState()

    @Published var lightColor: DetectedLightColor = .unknown
    @Published var showGreenTransitionCue: Bool = false

    @Published var speed: Double = 0.0
    @Published var speedUnit: String = "MPH"

    private(set) var speedMph: Double = 0.0
    var isStationary: Bool { speedMph < Constants.Detection.stationarySpeedThresholdMPH }

    @Published var isChimeEnabled: Bool = UserDefaults.standard.bool(forKey: "chimeEnabled") {
        didSet { UserDefaults.standard.set(isChimeEnabled, forKey: "chimeEnabled") }
    }

    @Published var sensitivity: ConfidenceSensitivity = {
        let raw = UserDefaults.standard.string(forKey: "confidenceSensitivity") ?? ""
        return ConfidenceSensitivity(rawValue: raw) ?? .medium
    }() {
        didSet { UserDefaults.standard.set(sensitivity.rawValue, forKey: "confidenceSensitivity") }
    }

    @Published var useMetricUnits: Bool = UserDefaults.standard.bool(forKey: "metricUnits") {
        didSet { UserDefaults.standard.set(useMetricUnits, forKey: "metricUnits") }
    }

    private let locationManager = CLLocationManager()

    private override init() {
        super.init()
        locationManager.delegate = self
        locationManager.desiredAccuracy = kCLLocationAccuracyBest
        locationManager.requestWhenInUseAuthorization()
        locationManager.startUpdatingLocation()
    }

    // FIXED: expose explicit visual cue for red->green transition so users get on-screen feedback with/without audio.
    func triggerGreenTransitionCue() {
        showGreenTransitionCue = true
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.25) { [weak self] in
            self?.showGreenTransitionCue = false
        }
    }
}

extension DetectionState: CLLocationManagerDelegate {
    nonisolated func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        guard let location = locations.last else { return }
        let rawMetersPerSecond = max(0, location.speed)

        Task { @MainActor in
            self.speedMph = rawMetersPerSecond * 2.237
            if self.useMetricUnits {
                self.speed = rawMetersPerSecond * 3.6
                self.speedUnit = "km/h"
            } else {
                self.speed = self.speedMph
                self.speedUnit = "MPH"
            }
        }
    }
}
