import XCTest
@testable import DriverAssistant

final class LightStateManagerTests: XCTestCase {

    private func confirmRed(mgr: LightStateManager, count: Int = 3, now: Date = Date()) {
        for _ in 0..<count {
            _ = mgr.update(detectedLight: .red, isStationary: true, now: now)
        }
    }

    func testSingleRedFrameDoesNotConfirm() {
        let mgr = LightStateManager()
        let t = Date()
        _ = mgr.update(detectedLight: .red, isStationary: true, now: t)
        XCTAssertFalse(mgr.update(detectedLight: .green, isStationary: true, now: t))
    }

    func testTwoRedFramesDoNotConfirm() {
        let mgr = LightStateManager(redConfirmCount: 3)
        let t = Date()
        _ = mgr.update(detectedLight: .red, isStationary: true, now: t)
        _ = mgr.update(detectedLight: .red, isStationary: true, now: t)
        XCTAssertFalse(mgr.update(detectedLight: .green, isStationary: true, now: t))
        XCTAssertFalse(mgr.update(detectedLight: .green, isStationary: true, now: t))
    }

    func testRedInterruptedByNoneResetsCount() {
        let mgr = LightStateManager(redConfirmCount: 3)
        let t = Date()
        _ = mgr.update(detectedLight: .red, isStationary: true, now: t)
        _ = mgr.update(detectedLight: .red, isStationary: true, now: t)
        _ = mgr.update(detectedLight: .none, isStationary: true, now: t)
        _ = mgr.update(detectedLight: .red, isStationary: true, now: t)
        _ = mgr.update(detectedLight: .red, isStationary: true, now: t)
        XCTAssertFalse(mgr.update(detectedLight: .green, isStationary: true, now: t))
        XCTAssertFalse(mgr.update(detectedLight: .green, isStationary: true, now: t))
    }

    func testFullSequenceTriggerChime() {
        let mgr = LightStateManager(redConfirmCount: 3, greenConfirmCount: 2)
        let t = Date()
        confirmRed(mgr: mgr, count: 3, now: t)
        XCTAssertFalse(mgr.update(detectedLight: .green, isStationary: true, now: t))
        XCTAssertTrue(mgr.update(detectedLight: .green, isStationary: true, now: t))
    }

    func testChimeFiresExactlyOnce() {
        let mgr = LightStateManager(redConfirmCount: 3, greenConfirmCount: 2, cooldownDuration: 20)
        let t = Date()
        confirmRed(mgr: mgr, count: 3, now: t)
        _ = mgr.update(detectedLight: .green, isStationary: true, now: t)
        let fired = mgr.update(detectedLight: .green, isStationary: true, now: t)
        XCTAssertTrue(fired)
        XCTAssertFalse(mgr.update(detectedLight: .green, isStationary: true, now: t))
        XCTAssertFalse(mgr.update(detectedLight: .green, isStationary: true, now: t))
    }

    func testNoChimeWhenMovingAtGreenTransition() {
        let mgr = LightStateManager(redConfirmCount: 3, greenConfirmCount: 2)
        let t = Date()
        confirmRed(mgr: mgr, count: 3, now: t)
        XCTAssertFalse(mgr.update(detectedLight: .green, isStationary: false, now: t))
        XCTAssertFalse(mgr.update(detectedLight: .green, isStationary: false, now: t))
    }

    func testChimeFiresIfStationaryDuringRedAndGreen() {
        let mgr = LightStateManager(redConfirmCount: 3, greenConfirmCount: 2)
        let t = Date()
        confirmRed(mgr: mgr, count: 3, now: t)
        _ = mgr.update(detectedLight: .green, isStationary: true, now: t)
        XCTAssertTrue(mgr.update(detectedLight: .green, isStationary: true, now: t))
    }

    func testCooldownBlocksImmediateReTrigger() {
        let mgr = LightStateManager(redConfirmCount: 3, greenConfirmCount: 2, cooldownDuration: 20)
        let t0 = Date()
        confirmRed(mgr: mgr, count: 3, now: t0)
        _ = mgr.update(detectedLight: .green, isStationary: true, now: t0)
        _ = mgr.update(detectedLight: .green, isStationary: true, now: t0)

        let t1 = t0.addingTimeInterval(5)
        confirmRed(mgr: mgr, count: 3, now: t1)
        _ = mgr.update(detectedLight: .green, isStationary: true, now: t1)
        XCTAssertFalse(mgr.update(detectedLight: .green, isStationary: true, now: t1))
    }

    func testCooldownExpiryAllowsReTrigger() {
        let mgr = LightStateManager(redConfirmCount: 3, greenConfirmCount: 2, cooldownDuration: 20)
        let t0 = Date()
        confirmRed(mgr: mgr, count: 3, now: t0)
        _ = mgr.update(detectedLight: .green, isStationary: true, now: t0)
        _ = mgr.update(detectedLight: .green, isStationary: true, now: t0)

        let t1 = t0.addingTimeInterval(21)
        confirmRed(mgr: mgr, count: 3, now: t1)
        _ = mgr.update(detectedLight: .green, isStationary: true, now: t1)
        XCTAssertTrue(mgr.update(detectedLight: .green, isStationary: true, now: t1))
    }

    func testFallbackUsesObservedLightWhenFilteredMissing() {
        let fallback = LightTransitionFallbackState(cooldownDuration: 20, redMemoryDuration: 8)
        let t = Date()
        XCTAssertFalse(fallback.update(
            filteredLight: .none,
            observedLight: .red,
            isStationary: true,
            now: t
        ))
        XCTAssertTrue(fallback.update(
            filteredLight: .none,
            observedLight: .green,
            isStationary: true,
            now: t.addingTimeInterval(1)
        ))
    }

    func testFallbackRedMemoryExpires() {
        let fallback = LightTransitionFallbackState(cooldownDuration: 20, redMemoryDuration: 3)
        let t = Date()
        _ = fallback.update(filteredLight: .none, observedLight: .red, isStationary: true, now: t)
        XCTAssertFalse(fallback.update(
            filteredLight: .none,
            observedLight: .green,
            isStationary: true,
            now: t.addingTimeInterval(4)
        ))
    }

    func testFallbackRespectsCooldownBetweenTransitions() {
        let fallback = LightTransitionFallbackState(cooldownDuration: 20, redMemoryDuration: 8)
        let t0 = Date()
        _ = fallback.update(filteredLight: .none, observedLight: .red, isStationary: true, now: t0)
        XCTAssertTrue(fallback.update(
            filteredLight: .none,
            observedLight: .green,
            isStationary: true,
            now: t0.addingTimeInterval(1)
        ))

        let t1 = t0.addingTimeInterval(5)
        _ = fallback.update(filteredLight: .none, observedLight: .red, isStationary: true, now: t1)
        XCTAssertFalse(fallback.update(
            filteredLight: .none,
            observedLight: .green,
            isStationary: true,
            now: t1.addingTimeInterval(1)
        ))
    }

    func testFallbackPrefersFilteredLightOverObservedLight() {
        let fallback = LightTransitionFallbackState(cooldownDuration: 20, redMemoryDuration: 8)
        let t = Date()
        _ = fallback.update(filteredLight: .red, observedLight: .none, isStationary: true, now: t)
        XCTAssertTrue(fallback.update(
            filteredLight: .green,
            observedLight: .red,
            isStationary: true,
            now: t.addingTimeInterval(1)
        ))
    }
}
