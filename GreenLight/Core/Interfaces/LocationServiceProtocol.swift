import Foundation

protocol LocationServiceProtocol: Sendable {
    var readings: AsyncStream<SpeedReading> { get }
    func start() async
}
