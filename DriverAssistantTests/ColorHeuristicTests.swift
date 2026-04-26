import XCTest
@testable import DriverAssistant

final class ColorHeuristicTests: XCTestCase {

    func testBrightRedLowHue() {
        XCTAssertEqual(ColorHeuristic.classifyHSV(h: 5, s: 0.9, v: 0.9), .red)
    }

    func testBrightRedHighHue() {
        XCTAssertEqual(ColorHeuristic.classifyHSV(h: 355, s: 0.85, v: 0.85), .red)
    }

    func testRedBelowSaturationThresholdIsUnknown() {
        XCTAssertEqual(ColorHeuristic.classifyHSV(h: 5, s: 0.2, v: 0.9), .unknown)
    }

    func testRedBelowBrightnessThresholdIsUnknown() {
        XCTAssertEqual(ColorHeuristic.classifyHSV(h: 5, s: 0.9, v: 0.1), .unknown)
    }

    func testBrightGreen() {
        XCTAssertEqual(ColorHeuristic.classifyHSV(h: 120, s: 0.8, v: 0.8), .green)
    }

    func testGreenAtLowerBound() {
        XCTAssertEqual(ColorHeuristic.classifyHSV(h: 90, s: 0.6, v: 0.5), .green)
    }

    func testGreenAtUpperBound() {
        XCTAssertEqual(ColorHeuristic.classifyHSV(h: 150, s: 0.5, v: 0.5), .green)
    }

    func testGreenBelowSaturationThresholdIsUnknown() {
        XCTAssertEqual(ColorHeuristic.classifyHSV(h: 120, s: 0.2, v: 0.8), .unknown)
    }

    func testYellow() {
        XCTAssertEqual(ColorHeuristic.classifyHSV(h: 45, s: 0.9, v: 0.9), .yellow)
    }

    func testYellowBelowBrightnessThresholdIsUnknown() {
        XCTAssertEqual(ColorHeuristic.classifyHSV(h: 45, s: 0.9, v: 0.2), .unknown)
    }

    func testBlueIsUnknown() {
        XCTAssertEqual(ColorHeuristic.classifyHSV(h: 220, s: 0.8, v: 0.8), .unknown)
    }

    func testNearBlackIsUnknown() {
        XCTAssertEqual(ColorHeuristic.classifyHSV(h: 0, s: 0, v: 0.05), .unknown)
    }

    func testNearWhiteIsUnknown() {
        XCTAssertEqual(ColorHeuristic.classifyHSV(h: 0, s: 0.01, v: 0.99), .unknown)
    }

    func testHueOnRedGreenBoundaryIsUnknown() {
        XCTAssertEqual(ColorHeuristic.classifyHSV(h: 20, s: 0.9, v: 0.9), .unknown)
    }
}
