import Foundation

actor LocationService: LocationServiceProtocol {

    let readings: AsyncStream<SpeedReading>
    private let readingsContinuation: AsyncStream<SpeedReading>.Continuation

    init() {
        var cont: AsyncStream<SpeedReading>.Continuation!
        readings = AsyncStream(bufferingPolicy: .bufferingNewest(1)) { cont = $0 }
        readingsContinuation = cont
    }

    func start() async {
        // TODO: implement CLLocationManager
    }
}
