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
    private(set) var gpsActive: Bool = false

    var speedStatus: SpeedStatus {
        guard gpsActive else { return .unknown }
        return speedMph < Constants.Detection.stationarySpeedThresholdMPH ? .knownStationary : .knownMoving
    }

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

    func triggerGreenTransitionCue() {
        showGreenTransitionCue = true
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.25) { [weak self] in
            self?.showGreenTransitionCue = false
        }
    }
}

extension DetectionState: CLLocationManagerDelegate {
    nonisolated func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        guard let location = locations.last, location.speed >= 0 else { return }
        let rawMetersPerSecond = location.speed

        Task { @MainActor in
            self.gpsActive = true
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

    nonisolated func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        Task { @MainActor in
            self.gpsActive = false
        }
    }

    nonisolated func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        let status = manager.authorizationStatus
        Task { @MainActor in
            if status == .denied || status == .restricted {
                self.gpsActive = false
            }
        }
    }
}
