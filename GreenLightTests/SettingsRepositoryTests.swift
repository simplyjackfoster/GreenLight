import XCTest
@testable import GreenLight

final class SettingsRepositoryTests: XCTestCase {

    func testLoadReturnsRegisteredDefaults() {
        let defaults = UserDefaults(suiteName: "SettingsRepositoryTests.defaults")!
        defaults.removePersistentDomain(forName: "SettingsRepositoryTests.defaults")
        let repository = UserDefaultsSettingsRepository(userDefaults: defaults)

        let values = repository.load()

        XCTAssertEqual(values.isChimeEnabled, true)
        XCTAssertEqual(values.sensitivity, .medium)
        XCTAssertEqual(values.iouThreshold, 0.6)
        XCTAssertEqual(values.useMetricUnits, false)
        XCTAssertEqual(values.showBoundingBoxes, false)
        XCTAssertEqual(values.showLabels, true)
        XCTAssertEqual(values.showSpeed, true)
    }

    func testSavePersistsValues() {
        let defaults = UserDefaults(suiteName: "SettingsRepositoryTests.persist")!
        defaults.removePersistentDomain(forName: "SettingsRepositoryTests.persist")
        let repository = UserDefaultsSettingsRepository(userDefaults: defaults)
        let input = SettingsValues(
            isChimeEnabled: false,
            sensitivity: .high,
            iouThreshold: 0.72,
            useMetricUnits: true,
            showBoundingBoxes: true,
            showLabels: false,
            showSpeed: false
        )

        repository.save(input)
        let output = repository.load()

        XCTAssertEqual(output.isChimeEnabled, false)
        XCTAssertEqual(output.sensitivity, .high)
        XCTAssertEqual(output.iouThreshold, 0.72)
        XCTAssertEqual(output.useMetricUnits, true)
        XCTAssertEqual(output.showBoundingBoxes, true)
        XCTAssertEqual(output.showLabels, false)
        XCTAssertEqual(output.showSpeed, false)
    }
}
