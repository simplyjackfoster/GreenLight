import Foundation
import CoreLocation

actor LocationService: LocationServiceProtocol {

    let readings: AsyncStream<SpeedReading>
    private let readingsContinuation: AsyncStream<SpeedReading>.Continuation
    private let manager: CLLocationManager
    private let bridge: LocationBridge

    init() {
        var cont: AsyncStream<SpeedReading>.Continuation!
        readings = AsyncStream(bufferingPolicy: .bufferingNewest(1)) { cont = $0 }
        readingsContinuation = cont
        manager = CLLocationManager()
        bridge = LocationBridge(continuation: cont)
        manager.delegate = bridge
        manager.desiredAccuracy = kCLLocationAccuracyBest
    }

    func start() async {
        manager.requestWhenInUseAuthorization()
        manager.startUpdatingLocation()
    }
}

private final class LocationBridge: NSObject, CLLocationManagerDelegate, @unchecked Sendable {
    private let continuation: AsyncStream<SpeedReading>.Continuation

    init(continuation: AsyncStream<SpeedReading>.Continuation) {
        self.continuation = continuation
    }

    func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        guard let location = locations.last, location.speed >= 0 else { return }
        let mps = location.speed
        let mph = mps * 2.237
        let speedStatus: SpeedStatus = mph < Constants.Detection.stationarySpeedThresholdMPH ? .knownStationary : .knownMoving
        continuation.yield(SpeedReading(metersPerSecond: mps, mph: mph, speedStatus: speedStatus))
    }

    func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        continuation.yield(SpeedReading(metersPerSecond: 0, mph: 0, speedStatus: .unknown))
    }

    func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        let status = manager.authorizationStatus
        if status == .denied || status == .restricted {
            continuation.yield(SpeedReading(metersPerSecond: 0, mph: 0, speedStatus: .unknown))
        }
    }
}
