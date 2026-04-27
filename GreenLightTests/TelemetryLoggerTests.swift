import XCTest
@testable import GreenLight

final class TelemetryLoggerTests: XCTestCase {

    func testTelemetryEventEncodesAllFields() throws {
        let event = TelemetryEvent(
            filteredLight: .red,
            observedLight: .green,
            speedStatus: .knownStationary,
            stateMachineChime: false,
            fallbackChime: true,
            displayState: .red
        )
        let data = try JSONEncoder().encode(event)
        let dict = try JSONSerialization.jsonObject(with: data) as! [String: Any]
        XCTAssertEqual(dict["filteredLight"] as? String, "red")
        XCTAssertEqual(dict["observedLight"] as? String, "green")
        XCTAssertEqual(dict["speedStatus"] as? String, "stationary")
        XCTAssertEqual(dict["stateMachineChime"] as? Bool, false)
        XCTAssertEqual(dict["fallbackChime"] as? Bool, true)
        XCTAssertNotNil(dict["timestamp"])
    }

    func testSpeedStatusUnknownLabel() throws {
        let event = TelemetryEvent(
            filteredLight: .none,
            observedLight: .none,
            speedStatus: .unknown,
            stateMachineChime: false,
            fallbackChime: false,
            displayState: .unknown
        )
        let data = try JSONEncoder().encode(event)
        let dict = try JSONSerialization.jsonObject(with: data) as! [String: Any]
        XCTAssertEqual(dict["speedStatus"] as? String, "unknown")
    }
}
