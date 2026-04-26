import XCTest
@testable import DriverAssistant

final class GeometryFilterTests: XCTestCase {

    private let validBox = CGRect(x: 0.35, y: 0.50, width: 0.20, height: 0.25)

    func testValidBoxPasses() {
        XCTAssertTrue(GeometryFilter.passes(normalizedBox: validBox))
    }

    func testTooSmallFails() {
        let tiny = CGRect(x: 0.45, y: 0.60, width: 0.01, height: 0.01)
        XCTAssertFalse(GeometryFilter.passes(normalizedBox: tiny))
    }

    func testTooLowInFrameFails() {
        let low = CGRect(x: 0.35, y: 0.05, width: 0.20, height: 0.20)
        XCTAssertFalse(GeometryFilter.passes(normalizedBox: low))
    }

    func testTooFarLeftFails() {
        let left = CGRect(x: 0.0, y: 0.55, width: 0.10, height: 0.20)
        XCTAssertFalse(GeometryFilter.passes(normalizedBox: left))
    }

    func testTooFarRightFails() {
        let right = CGRect(x: 0.90, y: 0.55, width: 0.10, height: 0.20)
        XCTAssertFalse(GeometryFilter.passes(normalizedBox: right))
    }

    func testExactlyOnAreaThresholdPasses() {
        let onThreshold = CGRect(x: 0.40, y: 0.55, width: 0.10, height: 0.05)
        XCTAssertTrue(GeometryFilter.passes(normalizedBox: onThreshold))
    }

    func testCustomThresholdsAreRespected() {
        let low = CGRect(x: 0.35, y: 0.05, width: 0.20, height: 0.20)
        XCTAssertTrue(GeometryFilter.passes(
            normalizedBox: low,
            minimumAreaFraction: 0.005,
            topFraction: 0.99,
            centerFraction: 0.99
        ))
    }
}
