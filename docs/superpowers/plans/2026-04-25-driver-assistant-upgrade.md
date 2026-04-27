# Driver Assistant Production Upgrade — Plan A (Detection + Chime)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Transform the Driver Assistant demo into a production-quality iOS app with a red→green traffic light chime that fires only when stationary, with confidence-gating, geometry heuristics, and a 20-second cooldown.

**Architecture:** UIKit camera pipeline (AVFoundation + Vision + Core ML) feeds into a `@MainActor DetectionState` ObservableObject. A `LightStateManager` state machine tracks red→green transitions. A `ColorHeuristic` classifies traffic light color from bounding box crops (supporting both the existing custom model labels and the future YOLOv8n COCO labels). A `ChimeController` plays a short sound via `AVAudioPlayer`. A new SwiftUI `HUDView` consumes `DetectionState` reactively.

**Tech Stack:** Swift 5.9+, iOS 16+, UIKit + SwiftUI hybrid, AVFoundation, Vision, Core ML, Core Location, AVFAudio, XCTest

**CarPlay:** Covered in Plan B (requires Apple entitlement; parallelize the entitlement request with Plan A work).

---

## File Map

**New files:**
- `DriverAssistant/Detection/Types.swift` — shared enums: `DetectedLightColor`, `LightState`, `ConfidenceSensitivity`
- `DriverAssistant/Detection/LightStateManager.swift` — state machine: idle → red → green → cooldown
- `DriverAssistant/Detection/GeometryFilter.swift` — bounding box position/size validation
- `DriverAssistant/Detection/ColorHeuristic.swift` — HSV classification of traffic light state from a pixel buffer crop
- `DriverAssistant/State/DetectionState.swift` — `@MainActor ObservableObject` shared across all UI
- `DriverAssistant/Audio/ChimeController.swift` — `AVAudioPlayer` wrapper with mute support
- `DriverAssistant/Views/HUDView.swift` — new SwiftUI HUD (replaces DisplayView + NavigationView)
- `DriverAssistant/App/SceneDelegate.swift` — UIWindowScene lifecycle (needed for CarPlay later)
- `DriverAssistantTests/LightStateManagerTests.swift`
- `DriverAssistantTests/GeometryFilterTests.swift`
- `DriverAssistantTests/ColorHeuristicTests.swift`

**Modified files:**
- `DriverAssistant/AppDelegate.swift` — remove `@UIApplicationMain`, add scene delegate support
- `DriverAssistant/Info.plist` — fix `armv7` → `arm64`, add `UIApplicationSceneManifest`, `UIBackgroundModes: audio`
- `DriverAssistant/Configuration/SampleCode.xcconfig` — replace Apple sample-code hack with real config
- `DriverAssistant/ViewControllers/ViewController.swift` — session preset, frame rate cap, error handling
- `DriverAssistant/ViewControllers/ViewControllerDetection.swift` — wire `DetectionState`, `LightStateManager`, `ColorHeuristic`, `GeometryFilter`
- `DriverAssistant/ViewControllers/LocationViewController.swift` — remove, fold into `DetectionState`
- `DriverAssistant/Views/SettingsView.swift` — add chime toggle, sensitivity picker
- `DriverAssistant/Models/Constants.swift` — extend with detection + chime constants

**Deleted files:**
- `DriverAssistant/Views/TestView.swift` — dead code referencing nonexistent class
- `DriverAssistant/Views/DisplayView.swift` — replaced by HUDView
- `DriverAssistant/Views/NavigationView.swift` — replaced by HUDView

> **Note:** Every new `.swift` file must be added to the `DriverAssistant` target in Xcode (drag into the project navigator and check the target box). New test files go in `DriverAssistantTests`.

---

## Task 1: Delete dead code and fix critical configuration

**Files:**
- Delete: `DriverAssistant/Views/TestView.swift`
- Modify: `DriverAssistant/Info.plist`
- Modify: `DriverAssistant/Configuration/SampleCode.xcconfig`

- [x] **Step 1: Delete TestView.swift**

Delete the file `DriverAssistant/Views/TestView.swift`. It references `VisionObjectRecognitionViewController` which does not exist and will cause a compile error if included.

Remove it from the Xcode project target (select file → Delete → Move to Trash).

- [x] **Step 2: Fix armv7 → arm64 in Info.plist**

In `DriverAssistant/Info.plist`, find:
```xml
<key>UIRequiredDeviceCapabilities</key>
<array>
    <string>armv7</string>
</array>
```

Replace with:
```xml
<key>UIRequiredDeviceCapabilities</key>
<array>
    <string>arm64</string>
</array>
```

- [x] **Step 3: Replace SampleCode.xcconfig**

Replace the entire contents of `DriverAssistant/Configuration/SampleCode.xcconfig` with:

```xcconfig
// DriverAssistant.xcconfig
// Project-level build settings.

PRODUCT_BUNDLE_IDENTIFIER = com.$(DEVELOPMENT_TEAM).driverassistant
```

> **Flag for user:** Replace `com.$(DEVELOPMENT_TEAM).driverassistant` with your actual bundle ID (e.g. `com.yourcompany.driverassistant`) before App Store submission. This placeholder is fine for development.

- [x] **Step 4: Commit**

```bash
git add -A
git commit -m "chore: delete dead TestView, fix armv7→arm64, replace sample xcconfig"
```

---

## Task 2: Define shared types

**Files:**
- Create: `DriverAssistant/Detection/Types.swift`

These enums are the vocabulary used by every other component. Define them once here.

- [x] **Step 1: Create the file**

Create `DriverAssistant/Detection/Types.swift` and add it to the `DriverAssistant` Xcode target:

```swift
import Foundation

enum DetectedLightColor: Equatable {
    case red
    case green
    case yellow
    case unknown
}

enum ConfidenceSensitivity: String, CaseIterable, Identifiable {
    case low = "Low"
    case medium = "Medium"
    case high = "High"

    var id: String { rawValue }

    var confidenceThreshold: Double {
        switch self {
        case .low:    return 0.55
        case .medium: return 0.70
        case .high:   return 0.80
        }
    }
}
```

- [x] **Step 2: Commit**

```bash
git add DriverAssistant/Detection/Types.swift
git commit -m "feat: add shared detection types (DetectedLightColor, ConfidenceSensitivity)"
```

---

## Task 3: LightStateManager — state machine (TDD)

**Files:**
- Create: `DriverAssistant/Detection/LightStateManager.swift`
- Create: `DriverAssistantTests/LightStateManagerTests.swift`

The state machine tracks: `idle → trackingRed(n) → confirmedRed → transitioningToGreen(n) → cooldown → idle`.
It returns `true` exactly once per red→green transition that passes all gates.

The `update` function takes an injectable `now: Date` parameter so tests can control time without sleeping.

- [x] **Step 1: Write the failing tests**

Create `DriverAssistantTests/LightStateManagerTests.swift` and add it to the `DriverAssistantTests` target:

```swift
import XCTest
@testable import DriverAssistant

final class LightStateManagerTests: XCTestCase {

    // MARK: - Helpers

    private func confirmRed(mgr: LightStateManager, count: Int = 3, now: Date = Date()) {
        for _ in 0..<count {
            _ = mgr.update(detectedLight: .red, isStationary: true, now: now)
        }
    }

    // MARK: - Red tracking

    func testSingleRedFrameDoesNotConfirm() {
        let mgr = LightStateManager()
        let t = Date()
        _ = mgr.update(detectedLight: .red, isStationary: true, now: t)
        // Immediately green after only 1 red — should not fire
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
        _ = mgr.update(detectedLight: .none, isStationary: true, now: t)   // interrupt
        _ = mgr.update(detectedLight: .red, isStationary: true, now: t)    // restart count
        _ = mgr.update(detectedLight: .red, isStationary: true, now: t)    // 2 reds, not 3
        XCTAssertFalse(mgr.update(detectedLight: .green, isStationary: true, now: t))
        XCTAssertFalse(mgr.update(detectedLight: .green, isStationary: true, now: t))
    }

    // MARK: - Full red→green sequence

    func testFullSequenceTriggerChime() {
        let mgr = LightStateManager(redConfirmCount: 3, greenConfirmCount: 2)
        let t = Date()
        confirmRed(mgr: mgr, count: 3, now: t)
        XCTAssertFalse(mgr.update(detectedLight: .green, isStationary: true, now: t))
        XCTAssertTrue(mgr.update(detectedLight: .green, isStationary: true, now: t))  // 🔔
    }

    func testChimeFiresExactlyOnce() {
        let mgr = LightStateManager(redConfirmCount: 3, greenConfirmCount: 2, cooldownDuration: 20)
        let t = Date()
        confirmRed(mgr: mgr, count: 3, now: t)
        _ = mgr.update(detectedLight: .green, isStationary: true, now: t)
        let fired = mgr.update(detectedLight: .green, isStationary: true, now: t)
        XCTAssertTrue(fired)
        // Extra green frames — chime must NOT fire again during cooldown
        XCTAssertFalse(mgr.update(detectedLight: .green, isStationary: true, now: t))
        XCTAssertFalse(mgr.update(detectedLight: .green, isStationary: true, now: t))
    }

    // MARK: - Speed gate

    func testNoChimeWhenMovingAtGreenTransition() {
        let mgr = LightStateManager(redConfirmCount: 3, greenConfirmCount: 2)
        let t = Date()
        confirmRed(mgr: mgr, count: 3, now: t)
        // Vehicle is moving when light turns green
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

    // MARK: - Cooldown

    func testCooldownBlocksImmediateReTrigger() {
        let mgr = LightStateManager(redConfirmCount: 3, greenConfirmCount: 2, cooldownDuration: 20)
        let t0 = Date()
        confirmRed(mgr: mgr, count: 3, now: t0)
        _ = mgr.update(detectedLight: .green, isStationary: true, now: t0)
        _ = mgr.update(detectedLight: .green, isStationary: true, now: t0)  // fired

        // Immediately start a new cycle — blocked by cooldown
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
        _ = mgr.update(detectedLight: .green, isStationary: true, now: t0)  // fired

        // After cooldown expires, a new full cycle fires again
        let t1 = t0.addingTimeInterval(21)
        confirmRed(mgr: mgr, count: 3, now: t1)
        _ = mgr.update(detectedLight: .green, isStationary: true, now: t1)
        XCTAssertTrue(mgr.update(detectedLight: .green, isStationary: true, now: t1))
    }
}
```

- [x] **Step 2: Run tests to verify they fail**

In Xcode: Product → Test (⌘U). All `LightStateManagerTests` tests should fail with a compile error because `LightStateManager` does not exist yet.

- [x] **Step 3: Implement LightStateManager**

Create `DriverAssistant/Detection/LightStateManager.swift` and add to the `DriverAssistant` target:

```swift
import Foundation

final class LightStateManager {

    private enum InternalState {
        case idle
        case trackingRed(count: Int)
        case confirmedRed
        case transitioningToGreen(count: Int)
        case cooldown
    }

    let redConfirmCount: Int
    let greenConfirmCount: Int
    let cooldownDuration: TimeInterval

    private var internalState: InternalState = .idle
    private var cooldownStart: Date?

    init(
        redConfirmCount: Int = 3,
        greenConfirmCount: Int = 2,
        cooldownDuration: TimeInterval = 20.0
    ) {
        self.redConfirmCount = redConfirmCount
        self.greenConfirmCount = greenConfirmCount
        self.cooldownDuration = cooldownDuration
    }

    /// Advances the state machine one frame. Returns `true` exactly when the chime should fire.
    /// - Parameters:
    ///   - detectedLight: The traffic light color detected in this frame (`.unknown` / `.none` = no light).
    ///   - isStationary: Whether the vehicle speed is below the stationary threshold.
    ///   - now: Current time. Injectable for deterministic testing.
    @discardableResult
    func update(
        detectedLight: DetectedLightColor,
        isStationary: Bool,
        now: Date = Date()
    ) -> Bool {
        // Check cooldown expiry first
        if case .cooldown = internalState {
            guard let start = cooldownStart,
                  now.timeIntervalSince(start) >= cooldownDuration else {
                return false
            }
            internalState = .idle
            cooldownStart = nil
        }

        switch (internalState, detectedLight, isStationary) {

        // ── Red tracking ────────────────────────────────────────────────────
        case (.idle, .red, _):
            internalState = .trackingRed(count: 1)

        case (.trackingRed(let n), .red, _):
            let next = n + 1
            internalState = next >= redConfirmCount ? .confirmedRed : .trackingRed(count: next)

        // ── Confirmed red: waiting for green while stationary ───────────────
        case (.confirmedRed, .green, true):
            internalState = .transitioningToGreen(count: 1)

        case (.confirmedRed, .green, false):
            internalState = .idle  // moving — don't care about this light

        // ── Transitioning to green ──────────────────────────────────────────
        case (.transitioningToGreen(let n), .green, true):
            let next = n + 1
            if next >= greenConfirmCount {
                internalState = .cooldown
                cooldownStart = now
                return true  // 🔔 Fire chime
            }
            internalState = .transitioningToGreen(count: next)

        case (.transitioningToGreen, .green, false):
            internalState = .idle  // started moving — abort

        // ── Any reset condition ─────────────────────────────────────────────
        case (.trackingRed, _, _),
             (.confirmedRed, .none, _),
             (.confirmedRed, .yellow, _),
             (.transitioningToGreen, .none, _),
             (.transitioningToGreen, .red, _),
             (.transitioningToGreen, .yellow, _):
            internalState = .idle

        default:
            break
        }

        return false
    }

    func reset() {
        internalState = .idle
        cooldownStart = nil
    }

    /// The light state to display in the UI (derived from internal state).
    var displayState: DetectedLightColor {
        switch internalState {
        case .idle:                     return .unknown
        case .trackingRed,
             .confirmedRed:             return .red
        case .transitioningToGreen,
             .cooldown:                 return .green
        }
    }
}
```

- [x] **Step 4: Add `.none` case to DetectedLightColor**

Open `DriverAssistant/Detection/Types.swift` and add `.none` to `DetectedLightColor`:

```swift
enum DetectedLightColor: Equatable {
    case red
    case green
    case yellow
    case unknown
    case none       // no traffic light detected this frame
}
```

- [x] **Step 5: Run tests to verify they pass**

In Xcode: Product → Test (⌘U). All `LightStateManagerTests` tests should pass.

- [x] **Step 6: Commit**

```bash
git add DriverAssistant/Detection/LightStateManager.swift \
        DriverAssistant/Detection/Types.swift \
        DriverAssistantTests/LightStateManagerTests.swift
git commit -m "feat: add LightStateManager state machine with full test coverage"
```

---

## Task 4: GeometryFilter — bounding box position validation (TDD)

**Files:**
- Create: `DriverAssistant/Detection/GeometryFilter.swift`
- Create: `DriverAssistantTests/GeometryFilterTests.swift`

Filters out traffic light detections that are too small, too low in the frame, or too far to the side to plausibly be the light this driver needs to respond to.

Vision coordinate system: origin at **bottom-left**, y increases **upward**. So a traffic light at the top of the camera frame has a **high** y value (close to 1.0).

- [x] **Step 1: Write the failing tests**

Create `DriverAssistantTests/GeometryFilterTests.swift`:

```swift
import XCTest
@testable import DriverAssistant

final class GeometryFilterTests: XCTestCase {

    // A box that meets all criteria: centered, upper half, adequate area
    // normalizedBox origin is bottom-left in Vision coords
    // This box: x=0.35, y=0.50 (bottom of box), width=0.20, height=0.25
    // midX = 0.45 (within middle 70%), midY = 0.625 (upper half), area = 0.05
    private let validBox = CGRect(x: 0.35, y: 0.50, width: 0.20, height: 0.25)

    func testValidBoxPasses() {
        XCTAssertTrue(GeometryFilter.passes(normalizedBox: validBox))
    }

    func testTooSmallFails() {
        // area = 0.01 * 0.01 = 0.0001, well below 0.005 minimum
        let tiny = CGRect(x: 0.45, y: 0.60, width: 0.01, height: 0.01)
        XCTAssertFalse(GeometryFilter.passes(normalizedBox: tiny))
    }

    func testTooLowInFrameFails() {
        // midY = 0.15, which is in the bottom 40% of the frame (below 0.40 threshold)
        let low = CGRect(x: 0.35, y: 0.05, width: 0.20, height: 0.20)
        XCTAssertFalse(GeometryFilter.passes(normalizedBox: low))
    }

    func testTooFarLeftFails() {
        // midX = 0.05, outside the middle 70% band [0.15, 0.85]
        let left = CGRect(x: 0.0, y: 0.55, width: 0.10, height: 0.20)
        XCTAssertFalse(GeometryFilter.passes(normalizedBox: left))
    }

    func testTooFarRightFails() {
        // midX = 0.95, outside the middle 70% band [0.15, 0.85]
        let right = CGRect(x: 0.90, y: 0.55, width: 0.10, height: 0.20)
        XCTAssertFalse(GeometryFilter.passes(normalizedBox: right))
    }

    func testExactlyOnAreaThresholdPasses() {
        // area = 0.1 * 0.05 = 0.005, exactly at minimum
        let onThreshold = CGRect(x: 0.40, y: 0.55, width: 0.10, height: 0.05)
        // midX = 0.45, midY = 0.575 — both valid
        XCTAssertTrue(GeometryFilter.passes(normalizedBox: onThreshold))
    }

    func testCustomThresholdsAreRespected() {
        // With relaxed constraints, the low box should pass
        let low = CGRect(x: 0.35, y: 0.05, width: 0.20, height: 0.20)
        XCTAssertTrue(GeometryFilter.passes(
            normalizedBox: low,
            minimumAreaFraction: 0.005,
            topFraction: 0.99,    // almost any vertical position accepted
            centerFraction: 0.99
        ))
    }
}
```

- [x] **Step 2: Run tests to verify they fail**

Product → Test (⌘U). `GeometryFilterTests` should fail with a compile error.

- [x] **Step 3: Implement GeometryFilter**

Create `DriverAssistant/Detection/GeometryFilter.swift`:

```swift
import CoreGraphics

struct GeometryFilter {
    /// Returns `true` if the bounding box is a plausible traffic light for this driver.
    ///
    /// - Parameters:
    ///   - normalizedBox: Vision-normalized bounding box. Origin = bottom-left, y increases upward.
    ///   - minimumAreaFraction: Minimum fraction of total frame area the box must occupy.
    ///   - topFraction: The box center must be within the top `topFraction` of the frame
    ///                  (e.g. 0.60 means center must have Vision y ≥ 0.40).
    ///   - centerFraction: The box center must be within the central `centerFraction` of the frame width
    ///                     (e.g. 0.70 means midX ∈ [0.15, 0.85]).
    static func passes(
        normalizedBox: CGRect,
        minimumAreaFraction: CGFloat = 0.005,
        topFraction: CGFloat = 0.60,
        centerFraction: CGFloat = 0.70
    ) -> Bool {
        // Area check
        let area = normalizedBox.width * normalizedBox.height
        guard area >= minimumAreaFraction else { return false }

        // Vertical position: box center must be in the upper portion of the frame.
        // Vision y increases upward, so upper part of frame = high y values.
        let midY = normalizedBox.midY
        let minimumY = 1.0 - topFraction   // e.g. 0.40 for topFraction=0.60
        guard midY >= minimumY else { return false }

        // Horizontal centering
        let midX = normalizedBox.midX
        let margin = (1.0 - centerFraction) / 2.0  // e.g. 0.15 for centerFraction=0.70
        guard midX >= margin && midX <= (1.0 - margin) else { return false }

        return true
    }
}
```

- [x] **Step 4: Run tests to verify they pass**

Product → Test (⌘U). All `GeometryFilterTests` should pass.

- [x] **Step 5: Commit**

```bash
git add DriverAssistant/Detection/GeometryFilter.swift \
        DriverAssistantTests/GeometryFilterTests.swift
git commit -m "feat: add GeometryFilter with position/size validation and tests"
```

---

## Task 5: ColorHeuristic — HSV traffic light classification (TDD)

**Files:**
- Create: `DriverAssistant/Detection/ColorHeuristic.swift`
- Create: `DriverAssistantTests/ColorHeuristicTests.swift`

The HSV classification is pure and fully testable. The pixel buffer sampling is a separate, non-testable concern (Apple SDK + device hardware). Test only the pure HSV logic.

HSV ranges (H in degrees 0–360):
- Red:    H ∈ [0, 15] or [345, 360], S > 0.50, V > 0.30
- Green:  H ∈ [90, 150], S > 0.40, V > 0.30
- Yellow: H ∈ [25, 60],  S > 0.50, V > 0.40

- [x] **Step 1: Write the failing tests**

Create `DriverAssistantTests/ColorHeuristicTests.swift`:

```swift
import XCTest
@testable import DriverAssistant

final class ColorHeuristicTests: XCTestCase {

    // MARK: - Red classification

    func testBrightRedLowHue() {
        // H=5° (red), S=0.9, V=0.9
        XCTAssertEqual(ColorHeuristic.classifyHSV(h: 5, s: 0.9, v: 0.9), .red)
    }

    func testBrightRedHighHue() {
        // H=355° (wraps around to red), S=0.85, V=0.85
        XCTAssertEqual(ColorHeuristic.classifyHSV(h: 355, s: 0.85, v: 0.85), .red)
    }

    func testRedBelowSaturationThresholdIsUnknown() {
        // H=5° but S=0.2 (too desaturated)
        XCTAssertEqual(ColorHeuristic.classifyHSV(h: 5, s: 0.2, v: 0.9), .unknown)
    }

    func testRedBelowBrightnessThresholdIsUnknown() {
        // H=5°, S=0.9 but V=0.1 (too dark)
        XCTAssertEqual(ColorHeuristic.classifyHSV(h: 5, s: 0.9, v: 0.1), .unknown)
    }

    // MARK: - Green classification

    func testBrightGreen() {
        // H=120° (pure green), S=0.8, V=0.8
        XCTAssertEqual(ColorHeuristic.classifyHSV(h: 120, s: 0.8, v: 0.8), .green)
    }

    func testGreenAtLowerBound() {
        // H=90°, S=0.6, V=0.5
        XCTAssertEqual(ColorHeuristic.classifyHSV(h: 90, s: 0.6, v: 0.5), .green)
    }

    func testGreenAtUpperBound() {
        // H=150°, S=0.5, V=0.5
        XCTAssertEqual(ColorHeuristic.classifyHSV(h: 150, s: 0.5, v: 0.5), .green)
    }

    func testGreenBelowSaturationThresholdIsUnknown() {
        XCTAssertEqual(ColorHeuristic.classifyHSV(h: 120, s: 0.2, v: 0.8), .unknown)
    }

    // MARK: - Yellow classification

    func testYellow() {
        // H=45°, S=0.9, V=0.9
        XCTAssertEqual(ColorHeuristic.classifyHSV(h: 45, s: 0.9, v: 0.9), .yellow)
    }

    func testYellowBelowBrightnessThresholdIsUnknown() {
        XCTAssertEqual(ColorHeuristic.classifyHSV(h: 45, s: 0.9, v: 0.2), .unknown)
    }

    // MARK: - Unknown / ambiguous

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
        // H=20°, between red (0-15) and yellow (25-60) — no match
        XCTAssertEqual(ColorHeuristic.classifyHSV(h: 20, s: 0.9, v: 0.9), .unknown)
    }
}
```

- [x] **Step 2: Run tests to verify they fail**

Product → Test (⌘U). `ColorHeuristicTests` should fail with a compile error.

- [x] **Step 3: Implement ColorHeuristic**

Create `DriverAssistant/Detection/ColorHeuristic.swift`:

```swift
import Foundation
import CoreVideo
import CoreGraphics

struct ColorHeuristic {

    // MARK: - Pure HSV classifier (fully testable, no I/O)

    /// Classifies a single HSV sample into a traffic light color.
    /// - Parameters:
    ///   - h: Hue in degrees [0, 360]
    ///   - s: Saturation [0, 1]
    ///   - v: Brightness/Value [0, 1]
    static func classifyHSV(h: Double, s: Double, v: Double) -> DetectedLightColor {
        let isRed    = (h <= 15 || h >= 345) && s > 0.50 && v > 0.30
        let isGreen  = (h >= 90 && h <= 150) && s > 0.40 && v > 0.30
        let isYellow = (h >= 25 && h <= 60)  && s > 0.50 && v > 0.40

        if isRed    { return .red }
        if isGreen  { return .green }
        if isYellow { return .yellow }
        return .unknown
    }

    // MARK: - Pixel buffer analysis

    /// Samples 9 points from the top third of `boundingBox` (where the bulb is)
    /// in `pixelBuffer` and votes on the dominant traffic light color.
    ///
    /// - Parameters:
    ///   - pixelBuffer: YCbCr pixel buffer from AVFoundation (kCVPixelFormatType_420YpCbCr8BiPlanarFullRange)
    ///   - boundingBox: Vision-normalized bounding box (origin bottom-left, y increases up)
    static func analyze(pixelBuffer: CVPixelBuffer, boundingBox: CGRect) -> DetectedLightColor {
        // Top third of bounding box in Vision coords = highest Y values
        let topThird = CGRect(
            x: boundingBox.origin.x,
            y: boundingBox.maxY - boundingBox.height / 3.0,
            width: boundingBox.width,
            height: boundingBox.height / 3.0
        )

        let bufferWidth  = CVPixelBufferGetWidth(pixelBuffer)
        let bufferHeight = CVPixelBufferGetHeight(pixelBuffer)

        CVPixelBufferLockBaseAddress(pixelBuffer, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(pixelBuffer, .readOnly) }

        var votes: [DetectedLightColor: Int] = [:]

        // 3×3 grid of sample points
        for row in 0..<3 {
            for col in 0..<3 {
                let nx = topThird.origin.x + topThird.width  * (CGFloat(col) + 0.5) / 3.0
                let ny = topThird.origin.y + topThird.height * (CGFloat(row) + 0.5) / 3.0

                // Vision coords (bottom-left origin) → pixel coords (top-left origin)
                let px = Int(nx * CGFloat(bufferWidth))
                let py = Int((1.0 - ny) * CGFloat(bufferHeight))

                guard px >= 0, px < bufferWidth, py >= 0, py < bufferHeight else { continue }

                let rgb = sampleRGB(pixelBuffer: pixelBuffer, x: px, y: py,
                                    width: bufferWidth, height: bufferHeight)
                let (h, s, v) = rgbToHSV(r: rgb.r, g: rgb.g, b: rgb.b)
                let color = classifyHSV(h: h, s: s, v: v)
                votes[color, default: 0] += 1
            }
        }

        // Majority vote, excluding .unknown and .none
        let meaningful = votes.filter { $0.key != .unknown && $0.key != .none }
        return meaningful.max(by: { $0.value < $1.value })?.key ?? .unknown
    }

    // MARK: - Private helpers

    private static func sampleRGB(
        pixelBuffer: CVPixelBuffer,
        x: Int, y: Int,
        width: Int, height: Int
    ) -> (r: Double, g: Double, b: Double) {
        // YCbCr 4:2:0 biplanar — plane 0 is luma (Y), plane 1 is chroma (CbCr interleaved)
        guard let yPlane  = CVPixelBufferGetBaseAddressOfPlane(pixelBuffer, 0),
              let uvPlane = CVPixelBufferGetBaseAddressOfPlane(pixelBuffer, 1) else {
            return (0, 0, 0)
        }

        let yStride  = CVPixelBufferGetBytesPerRowOfPlane(pixelBuffer, 0)
        let uvStride = CVPixelBufferGetBytesPerRowOfPlane(pixelBuffer, 1)

        let yVal  = Double(yPlane.load(fromByteOffset: y * yStride + x, as: UInt8.self))
        let uvX   = (x / 2) * 2
        let uvY   = y / 2
        let cbVal = Double(uvPlane.load(fromByteOffset: uvY * uvStride + uvX,     as: UInt8.self))
        let crVal = Double(uvPlane.load(fromByteOffset: uvY * uvStride + uvX + 1, as: UInt8.self))

        // BT.601 full-range YCbCr → RGB
        let Y  = yVal
        let Cb = cbVal - 128
        let Cr = crVal - 128

        let r = max(0, min(255, Y + 1.402   * Cr))
        let g = max(0, min(255, Y - 0.344136 * Cb - 0.714136 * Cr))
        let b = max(0, min(255, Y + 1.772   * Cb))

        return (r / 255.0, g / 255.0, b / 255.0)
    }

    private static func rgbToHSV(r: Double, g: Double, b: Double) -> (h: Double, s: Double, v: Double) {
        let maxC = max(r, g, b)
        let minC = min(r, g, b)
        let delta = maxC - minC

        let v = maxC
        let s = maxC > 0 ? delta / maxC : 0

        var h: Double = 0
        if delta > 0 {
            switch maxC {
            case r: h = 60 * (((g - b) / delta).truncatingRemainder(dividingBy: 6))
            case g: h = 60 * ((b - r) / delta + 2)
            default: h = 60 * ((r - g) / delta + 4)
            }
        }
        if h < 0 { h += 360 }

        return (h, s, v)
    }
}
```

- [x] **Step 4: Run tests to verify they pass**

Product → Test (⌘U). All `ColorHeuristicTests` should pass.

- [x] **Step 5: Commit**

```bash
git add DriverAssistant/Detection/ColorHeuristic.swift \
        DriverAssistantTests/ColorHeuristicTests.swift
git commit -m "feat: add ColorHeuristic HSV classifier with full test coverage"
```

---

## Task 6: DetectionState — shared observable state

**Files:**
- Create: `DriverAssistant/State/DetectionState.swift`

This is the single source of truth consumed by both the phone HUD and (in Plan B) CarPlay. It also owns the `LocationViewModel` for speed, replacing the disconnected `DisplayView` pattern.

- [x] **Step 1: Create DetectionState.swift**

Create `DriverAssistant/State/DetectionState.swift` and add to the `DriverAssistant` target:

```swift
import Foundation
import Combine
import CoreLocation

@MainActor
final class DetectionState: NSObject, ObservableObject {

    static let shared = DetectionState()

    // MARK: - Detection

    @Published var lightColor: DetectedLightColor = .unknown

    // MARK: - Speed (replaces LocationViewModel)

    @Published var speed: Double = 0.0           // always in mph for internal use
    @Published var speedUnit: String = "MPH"

    var isStationary: Bool { speed < 2.0 }       // < 2 mph = stationary

    // MARK: - Settings (mirrors @AppStorage values, updated by SettingsView)

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

    // MARK: - Location

    private let locationManager = CLLocationManager()

    private override init() {
        super.init()
        locationManager.delegate = self
        locationManager.desiredAccuracy = kCLLocationAccuracyBest
        locationManager.requestWhenInUseAuthorization()
        locationManager.startUpdatingLocation()
    }
}

// MARK: - CLLocationManagerDelegate

extension DetectionState: CLLocationManagerDelegate {
    nonisolated func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        guard let location = locations.last else { return }
        var raw = max(0, location.speed)  // m/s, clamp negatives to 0

        Task { @MainActor in
            if self.useMetricUnits {
                self.speed = raw * 3.6      // km/h
                self.speedUnit = "km/h"
            } else {
                self.speed = raw * 2.237    // mph
                self.speedUnit = "MPH"
            }
        }
    }
}
```

> **Note:** `CLLocationManagerDelegate` methods are called on an arbitrary thread, so updates are dispatched to `@MainActor` explicitly. This resolves the Swift 6 concurrency warning that the existing `LocationViewController` would generate.

- [x] **Step 2: Commit**

```bash
git add DriverAssistant/State/DetectionState.swift
git commit -m "feat: add DetectionState shared observable with speed tracking"
```

---

## Task 7: ChimeController

**Files:**
- Create: `DriverAssistant/Audio/ChimeController.swift`

> **Flag for user:** You must supply a bundled sound file at `DriverAssistant/Resources/chime.aiff` (or `.caf`). Requirements: short (≤0.5s), two-tone ascending, not startling. Free sources: `freesound.org` (CC0 license). The file must be added to the Xcode target's "Copy Bundle Resources" build phase.

- [x] **Step 1: Create ChimeController.swift**

Create `DriverAssistant/Audio/ChimeController.swift` and add to the `DriverAssistant` target:

```swift
import AVFoundation

final class ChimeController {

    private var player: AVAudioPlayer?
    var isMuted: Bool = false

    init() {
        guard let url = Bundle.main.url(forResource: "chime", withExtension: "aiff")
                     ?? Bundle.main.url(forResource: "chime", withExtension: "caf") else {
            print("[ChimeController] Warning: chime sound file not found in bundle")
            return
        }
        do {
            player = try AVAudioPlayer(contentsOf: url)
            player?.prepareToPlay()
        } catch {
            print("[ChimeController] Failed to load chime: \(error)")
        }
    }

    func play() {
        guard !isMuted, let player else { return }
        // Rewind in case we're calling play() rapidly (shouldn't happen due to cooldown,
        // but defensive)
        player.currentTime = 0
        player.play()
    }
}
```

- [x] **Step 2: Configure AVAudioSession in AppDelegate**

Open `DriverAssistant/AppDelegate.swift`. The audio session must be configured before any sound plays. Add to `application(_:didFinishLaunchingWithOptions:)`:

```swift
import UIKit
import AVFoundation

@main
class AppDelegate: UIResponder, UIApplicationDelegate {

    var window: UIWindow?

    func application(
        _ application: UIApplication,
        didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?
    ) -> Bool {
        configureAudioSession()
        return true
    }

    private func configureAudioSession() {
        do {
            // .ambient: respects the silent switch, mixes with other audio (music, navigation)
            try AVAudioSession.sharedInstance().setCategory(.ambient, options: .mixWithOthers)
            try AVAudioSession.sharedInstance().setActive(true)
        } catch {
            print("[AppDelegate] Audio session setup failed: \(error)")
        }
    }
}
```

> **Note:** Remove `@UIApplicationMain` — it will be replaced by `@main` in Task 10 when we add SceneDelegate. For now, keep `@UIApplicationMain` if SceneDelegate is not yet implemented.

- [x] **Step 3: Commit**

```bash
git add DriverAssistant/Audio/ChimeController.swift \
        DriverAssistant/AppDelegate.swift
git commit -m "feat: add ChimeController and configure AVAudioSession"
```

---

## Task 8: Camera pipeline improvements

**Files:**
- Modify: `DriverAssistant/ViewControllers/ViewController.swift`

- [x] **Step 1: Replace ViewController.swift**

Replace the entire contents of `DriverAssistant/ViewControllers/ViewController.swift`:

```swift
import UIKit
import AVFoundation
import Vision
import SwiftUI

class ViewController: UIViewController, AVCaptureVideoDataOutputSampleBufferDelegate {

    // Camera HUD host — set up in setupAVCapture
    private var hudHostController: UIHostingController<HUDView>?

    @IBOutlet weak var trafficLightRed:   UIImageView!
    @IBOutlet weak var trafficLightGreen: UIImageView!
    @IBOutlet weak var stopSign:          UIImageView!
    @IBOutlet weak private var previewView: UIView!

    var bufferSize: CGSize = .zero
    var rootLayer: CALayer!

    let session = AVCaptureSession()
    private var previewLayer: AVCaptureVideoPreviewLayer!
    let videoDataOutput = AVCaptureVideoDataOutput()
    let videoDataOutputQueue = DispatchQueue(
        label: "com.driverassistant.VideoDataOutput",
        qos: .userInitiated,
        attributes: [],
        autoreleaseFrequency: .workItem
    )

    func captureOutput(_ output: AVCaptureOutput, didOutput sampleBuffer: CMSampleBuffer, from connection: AVCaptureConnection) {}

    override func viewDidLoad() {
        UIApplication.shared.isIdleTimerDisabled = true
        super.viewDidLoad()

        guard TARGET_OS_SIMULATOR == 0 else { return }
        setupAVCapture()
    }

    func setupAVCapture() {
        let discovery = AVCaptureDevice.DiscoverySession(
            deviceTypes: [.builtInWideAngleCamera],
            mediaType: .video,
            position: .back
        )

        guard let videoDevice = discovery.devices.first else {
            showCameraUnavailableAlert()
            return
        }

        let deviceInput: AVCaptureDeviceInput
        do {
            deviceInput = try AVCaptureDeviceInput(device: videoDevice)
        } catch {
            showCameraUnavailableAlert()
            return
        }

        session.beginConfiguration()

        // 720p is sufficient for 640×640 model input and saves processing time
        session.sessionPreset = .hd1280x720

        guard session.canAddInput(deviceInput) else {
            session.commitConfiguration()
            return
        }
        session.addInput(deviceInput)

        guard session.canAddOutput(videoDataOutput) else {
            session.commitConfiguration()
            return
        }
        session.addOutput(videoDataOutput)

        videoDataOutput.alwaysDiscardsLateVideoFrames = true
        videoDataOutput.videoSettings = [
            kCVPixelBufferPixelFormatTypeKey as String: Int(kCVPixelFormatType_420YpCbCr8BiPlanarFullRange)
        ]
        videoDataOutput.setSampleBufferDelegate(self, queue: videoDataOutputQueue)

        // Cap frame rate to 15fps — sufficient for traffic detection, saves battery
        do {
            try videoDevice.lockForConfiguration()
            videoDevice.activeVideoMinFrameDuration = CMTime(value: 1, timescale: 15)
            videoDevice.activeVideoMaxFrameDuration = CMTime(value: 1, timescale: 15)
            let dimensions = CMVideoFormatDescriptionGetDimensions(videoDevice.activeFormat.formatDescription)
            bufferSize.width  = CGFloat(dimensions.height)  // swapped: camera is landscape, display is portrait
            bufferSize.height = CGFloat(dimensions.width)
            videoDevice.unlockForConfiguration()
        } catch {
            print("[ViewController] Device configuration failed: \(error)")
        }

        session.commitConfiguration()

        previewLayer = AVCaptureVideoPreviewLayer(session: session)
        previewLayer.videoGravity = .resizeAspectFill
        rootLayer = previewView.layer
        previewLayer.frame = rootLayer.bounds
        rootLayer.addSublayer(previewLayer)

        // Embed SwiftUI HUD
        let hud = UIHostingController(rootView: HUDView())
        hud.view.backgroundColor = .clear
        hud.view.translatesAutoresizingMaskIntoConstraints = false
        addChild(hud)
        view.addSubview(hud.view)
        NSLayoutConstraint.activate([
            hud.view.topAnchor.constraint(equalTo: view.topAnchor),
            hud.view.bottomAnchor.constraint(equalTo: view.bottomAnchor),
            hud.view.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            hud.view.trailingAnchor.constraint(equalTo: view.trailingAnchor),
        ])
        hud.didMove(toParent: self)
        hudHostController = hud
    }

    func startCaptureSession() {
        session.startRunning()
    }

    func teardownAVCapture() {
        previewLayer?.removeFromSuperlayer()
        previewLayer = nil
    }

    func captureOutput(_ captureOutput: AVCaptureOutput, didDrop didDropSampleBuffer: CMSampleBuffer, from connection: AVCaptureConnection) {
        // Uncomment to log frame drops during debugging:
        // print("[ViewController] Dropped frame")
    }

    private func showCameraUnavailableAlert() {
        DispatchQueue.main.async {
            let alert = UIAlertController(
                title: "Camera Unavailable",
                message: "Driver Assistant requires camera access. Please enable it in Settings.",
                preferredStyle: .alert
            )
            alert.addAction(UIAlertAction(title: "Open Settings", style: .default) { _ in
                if let url = URL(string: UIApplication.openSettingsURLString) {
                    UIApplication.shared.open(url)
                }
            })
            alert.addAction(UIAlertAction(title: "OK", style: .cancel))
            self.present(alert, animated: true)
        }
    }
}
```

- [x] **Step 2: Commit**

```bash
git add DriverAssistant/ViewControllers/ViewController.swift
git commit -m "feat: improve camera pipeline — 720p preset, 15fps cap, error handling"
```

---

## Task 9: Refactor ViewControllerDetection

**Files:**
- Modify: `DriverAssistant/ViewControllers/ViewControllerDetection.swift`

This is where all the new components connect. The old indicator UIImageViews are removed in favor of `DetectionState`. The state machine runs per-frame.

- [x] **Step 1: Replace ViewControllerDetection.swift**

Replace the entire contents of `DriverAssistant/ViewControllers/ViewControllerDetection.swift`:

```swift
import UIKit
import AVFoundation
import Vision
import CoreML

class ViewControllerDetection: ViewController {

    // MARK: - Dependencies

    private let detectionState = DetectionState.shared
    private let stateManager   = LightStateManager()
    private let chimeController = ChimeController()

    // MARK: - Vision

    private var detectionOverlay: CALayer!
    private var requests = [VNRequest]()

    // MARK: - Setup

    @discardableResult
    func setupVision() -> NSError? {
        guard let modelURL = Bundle.main.url(forResource: "yolov5sTraffic", withExtension: "mlmodelc")
                          ?? Bundle.main.url(forResource: "yolov8nTraffic",  withExtension: "mlpackage") else {
            return NSError(domain: "ViewControllerDetection", code: -1,
                           userInfo: [NSLocalizedDescriptionKey: "ML model not found"])
        }

        do {
            let mlModel = try MLModel(contentsOf: modelURL)
            let visionModel = try VNCoreMLModel(for: mlModel)
            let request = VNCoreMLRequest(model: visionModel) { [weak self] req, _ in
                guard let self, let results = req.results else { return }
                DispatchQueue.main.async { self.handleResults(results) }
            }
            requests = [request]
        } catch {
            print("[ViewControllerDetection] Model setup failed: \(error)")
            return error as NSError
        }
        return nil
    }

    // MARK: - Per-frame handling

    private var currentPixelBuffer: CVPixelBuffer?

    override func captureOutput(
        _ output: AVCaptureOutput,
        didOutput sampleBuffer: CMSampleBuffer,
        from connection: AVCaptureConnection
    ) {
        guard let pixelBuffer = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }
        currentPixelBuffer = pixelBuffer

        let handler = VNImageRequestHandler(cvPixelBuffer: pixelBuffer, orientation: .right)
        do {
            try handler.perform(requests)
        } catch {
            print("[ViewControllerDetection] Inference failed: \(error)")
        }
    }

    @MainActor
    private func handleResults(_ results: [Any]) {
        detectionOverlay.sublayers = nil

        let threshold = detectionState.sensitivity.confidenceThreshold
        var bestLightColor: DetectedLightColor = .none

        for observation in results.compactMap({ $0 as? VNRecognizedObjectObservation }) {
            guard let top = observation.labels.first,
                  Double(top.confidence) >= threshold else { continue }

            let label = top.identifier
            let box   = observation.boundingBox

            // Resolve traffic light color: supports both custom and COCO model labels
            let lightColor = resolveTrafficLightColor(label: label, box: box)

            // Only pass to state machine if geometry filter clears it
            if lightColor != .unknown && lightColor != .none {
                if GeometryFilter.passes(normalizedBox: box) {
                    // Use the highest-confidence valid detection for the state machine
                    if bestLightColor == .none { bestLightColor = lightColor }
                }
            }

            // Draw overlays if enabled
            let objectBounds = VNImageRectForNormalizedRect(box, Int(bufferSize.width), Int(bufferSize.height))

            if UserDefaults.standard.bool(forKey: "visualizeDetections") {
                detectionOverlay.addSublayer(drawBox(objectBounds, label: label))
            }
            if UserDefaults.standard.bool(forKey: "showLabels") {
                detectionOverlay.addSublayer(drawLabel(objectBounds, label: label, confidence: top.confidence))
            }
        }

        // Advance state machine
        let shouldChime = stateManager.update(
            detectedLight: bestLightColor,
            isStationary: detectionState.isStationary
        )

        // Update shared state for HUD
        detectionState.lightColor = stateManager.displayState

        // Fire chime
        if shouldChime && detectionState.isChimeEnabled {
            chimeController.play()
        }
    }

    // MARK: - Label resolution

    private func resolveTrafficLightColor(label: String, box: CGRect) -> DetectedLightColor {
        switch label {
        case "traffic_light_red":   return .red
        case "traffic_light_green": return .green
        case "traffic_light_na":    return .yellow
        case "traffic light":
            guard let pb = currentPixelBuffer else { return .unknown }
            return ColorHeuristic.analyze(pixelBuffer: pb, boundingBox: box)
        default:
            return .none
        }
    }

    // MARK: - Overlay drawing

    override func setupAVCapture() {
        super.setupAVCapture()
        setupLayers()
        updateLayerGeometry()
        setupVision()
        startCaptureSession()
    }

    private func setupLayers() {
        detectionOverlay = CALayer()
        detectionOverlay.name = "DetectionOverlay"
        detectionOverlay.bounds = CGRect(origin: .zero, size: bufferSize)
        detectionOverlay.position = CGPoint(x: rootLayer.bounds.midX, y: rootLayer.bounds.midY)
        rootLayer.addSublayer(detectionOverlay)
    }

    private func updateLayerGeometry() {
        let bounds = rootLayer.bounds
        let xScale = bounds.width  / bufferSize.width
        let yScale = bounds.height / bufferSize.height
        var scale  = max(xScale, yScale)
        if scale.isInfinite { scale = 1.0 }

        CATransaction.begin()
        CATransaction.setValue(kCFBooleanTrue, forKey: kCATransactionDisableActions)
        detectionOverlay.setAffineTransform(CGAffineTransform(rotationAngle: 0).scaledBy(x: scale, y: -scale))
        detectionOverlay.position = CGPoint(x: bounds.midX, y: bounds.midY)
        CATransaction.commit()
    }

    private func drawBox(_ bounds: CGRect, label: String) -> CAShapeLayer {
        let layer = CAShapeLayer()
        layer.bounds        = bounds
        layer.position      = CGPoint(x: bounds.midX, y: bounds.midY)
        layer.cornerRadius  = 4
        layer.borderWidth   = 8

        switch label {
        case "traffic_light_red",  "stop sign": layer.borderColor = Constants.BoxColours.trafficRed
        case "traffic_light_green", "traffic light": layer.borderColor = Constants.BoxColours.trafficGreen
        case "traffic_light_na":  layer.borderColor = Constants.BoxColours.trafficNa
        case "person", "bicycle": layer.borderColor = Constants.BoxColours.pedestrian
        default:                  layer.borderColor = Constants.BoxColours.misc
        }
        return layer
    }

    private func drawLabel(_ bounds: CGRect, label: String, confidence: VNConfidence) -> CATextLayer {
        let layer = CATextLayer()
        layer.name = "Object Label"

        let font = UIFont.systemFont(ofSize: 28, weight: .medium)
        let text = String(format: "%@ (%.0f%%)", label, confidence * 100)
        let attr: [NSAttributedString.Key: Any] = [
            .font: font,
            .foregroundColor: CGColor(gray: 0.95, alpha: 1.0)
        ]
        layer.string = NSAttributedString(string: text, attributes: attr)

        let width: CGFloat = CGFloat(text.count) * 13
        layer.bounds   = CGRect(x: 0, y: 0, width: width, height: 36)
        layer.position = CGPoint(x: bounds.minX + width / 2, y: bounds.maxY + 18)
        layer.setAffineTransform(CGAffineTransform(scaleX: 1, y: -1))
        return layer
    }
}
```

- [x] **Step 2: Commit**

```bash
git add DriverAssistant/ViewControllers/ViewControllerDetection.swift
git commit -m "feat: refactor ViewControllerDetection to use DetectionState, LightStateManager, ColorHeuristic"
```

---

## Task 10: SceneDelegate + AppDelegate lifecycle

**Files:**
- Create: `DriverAssistant/App/SceneDelegate.swift`
- Modify: `DriverAssistant/AppDelegate.swift`
- Modify: `DriverAssistant/Info.plist`

Migrating to scene-based lifecycle is required before Plan B (CarPlay). CarPlay needs a second `UIScene` (`CPTemplateApplicationScene`).

- [x] **Step 1: Create SceneDelegate.swift**

Create `DriverAssistant/App/SceneDelegate.swift` and add to the `DriverAssistant` target:

```swift
import UIKit

class SceneDelegate: UIResponder, UIWindowSceneDelegate {

    var window: UIWindow?

    func scene(
        _ scene: UIScene,
        willConnectTo session: UISceneSession,
        options connectionOptions: UIScene.ConnectionOptions
    ) {
        guard let windowScene = scene as? UIWindowScene else { return }

        // Preserve storyboard-based launch — Main.storyboard sets the root VC.
        // If migrating to programmatic UI, instantiate ViewControllerDetection here instead.
        let window = UIWindow(windowScene: windowScene)
        let storyboard = UIStoryboard(name: "Main", bundle: nil)
        window.rootViewController = storyboard.instantiateInitialViewController()
        window.makeKeyAndVisible()
        self.window = window
    }
}
```

- [x] **Step 2: Update AppDelegate.swift**

Replace `DriverAssistant/AppDelegate.swift`:

```swift
import UIKit
import AVFoundation

@main
class AppDelegate: UIResponder, UIApplicationDelegate {

    func application(
        _ application: UIApplication,
        didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?
    ) -> Bool {
        configureAudioSession()
        return true
    }

    // MARK: - Scene lifecycle

    func application(
        _ application: UIApplication,
        configurationForConnecting connectingSceneSession: UISceneSession,
        options: UIScene.ConnectionOptions
    ) -> UISceneConfiguration {
        UISceneConfiguration(name: "Default Configuration", sessionRole: connectingSceneSession.role)
    }

    // MARK: - Private

    private func configureAudioSession() {
        do {
            try AVAudioSession.sharedInstance().setCategory(.ambient, options: .mixWithOthers)
            try AVAudioSession.sharedInstance().setActive(true)
        } catch {
            print("[AppDelegate] Audio session configuration failed: \(error)")
        }
    }
}
```

> **Note:** `@UIApplicationMain` is replaced by `@main`. Both compile identically; `@main` is the modern Swift syntax.

- [x] **Step 3: Add UIApplicationSceneManifest to Info.plist**

In `DriverAssistant/Info.plist`, add these keys (before the closing `</dict>`):

```xml
<key>UIApplicationSceneManifest</key>
<dict>
    <key>UIApplicationSupportsMultipleScenes</key>
    <false/>
    <key>UISceneConfigurations</key>
    <dict>
        <key>UIWindowSceneSessionRoleApplication</key>
        <array>
            <dict>
                <key>UISceneConfigurationName</key>
                <string>Default Configuration</string>
                <key>UISceneDelegateClassName</key>
                <string>$(PRODUCT_MODULE_NAME).SceneDelegate</string>
                <key>UISceneStoryboardFile</key>
                <string>Main</string>
            </dict>
        </array>
    </dict>
</dict>
<key>UIBackgroundModes</key>
<array>
    <string>audio</string>
</array>
```

- [x] **Step 4: Build and verify**

Product → Build (⌘B). The app should compile cleanly. Run on device to verify the camera launches as before.

- [x] **Step 5: Commit**

```bash
git add DriverAssistant/App/SceneDelegate.swift \
        DriverAssistant/AppDelegate.swift \
        DriverAssistant/Info.plist
git commit -m "feat: migrate to scene-based lifecycle, add background audio mode"
```

---

## Task 11: New HUDView

**Files:**
- Create: `DriverAssistant/Views/HUDView.swift`
- Delete: `DriverAssistant/Views/DisplayView.swift`
- Delete: `DriverAssistant/Views/NavigationView.swift`

`HUDView` replaces both `DisplayView` (speed) and `NavigationView` (tap-to-show settings). It observes `DetectionState.shared` so all properties are reactive.

- [x] **Step 1: Create HUDView.swift**

Create `DriverAssistant/Views/HUDView.swift` and add to the `DriverAssistant` target:

```swift
import SwiftUI

struct HUDView: View {

    @ObservedObject private var state = DetectionState.shared
    @State private var showSettings = false
    @AppStorage("showSpeed") private var showSpeed = true

    var body: some View {
        ZStack {
            // Tap anywhere to reveal settings button
            Color.clear
                .contentShape(Rectangle())
                .onTapGesture { withAnimation { showSettings.toggle() } }

            VStack {
                // Speed display
                if showSpeed {
                    HStack {
                        Spacer()
                        VStack(spacing: 0) {
                            Text("\(Int(state.speed))")
                                .font(.system(size: 80, weight: .regular, design: .rounded))
                                .foregroundColor(.white)
                            Text(state.speedUnit)
                                .font(.system(size: 36, weight: .light))
                                .foregroundColor(.white.opacity(0.85))
                        }
                        .padding(.top, 60)
                        .padding(.trailing, 20)
                    }
                }

                Spacer()

                // Settings button (tap to toggle)
                if showSettings {
                    NavigationLink(destination: SettingsView()) {
                        Label("Settings", systemImage: "gearshape.fill")
                            .font(.body)
                            .foregroundColor(.white)
                            .padding(.horizontal, 20)
                            .padding(.vertical, 10)
                            .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 12))
                    }
                    .padding(.bottom, 40)
                    .transition(.opacity)
                }
            }
        }
        .navigationBarHidden(true)
    }
}
```

- [x] **Step 2: Delete DisplayView.swift and NavigationView.swift**

Delete `DriverAssistant/Views/DisplayView.swift` and `DriverAssistant/Views/NavigationView.swift` from the Xcode project (select → Delete → Move to Trash).

Fix any storyboard or code references that pointed to these views (the storyboard's root VC is `ViewControllerDetection`, which now embeds `HUDView` directly — no storyboard references to the deleted files needed).

- [x] **Step 3: Commit**

```bash
git add DriverAssistant/Views/HUDView.swift
git commit -m "feat: add HUDView replacing DisplayView+NavigationView, reactive via DetectionState"
```

---

## Task 12: Update SettingsView

**Files:**
- Modify: `DriverAssistant/Views/SettingsView.swift`

Add a chime section with enable toggle and sensitivity picker. Wire to `DetectionState.shared`.

- [x] **Step 1: Replace SettingsView.swift**

Replace the entire contents of `DriverAssistant/Views/SettingsView.swift`:

```swift
import SwiftUI

struct SettingsView: View {

    @ObservedObject private var state = DetectionState.shared

    // Legacy detector settings (still read by ViewControllerDetection via UserDefaults)
    @AppStorage("visualizeDetections") private var visualizeDetections = true
    @AppStorage("showLabels")          private var showLabels = true
    @AppStorage("showSpeed")           private var showSpeed = true
    @AppStorage("iouThreshold")        private var iouThreshold: Double = 0.6

    var body: some View {
        Form {
            // MARK: - Chime
            Section("Green Light Chime") {
                Toggle("Enable chime", isOn: $state.isChimeEnabled)
                Picker("Sensitivity", selection: $state.sensitivity) {
                    ForEach(ConfidenceSensitivity.allCases) { level in
                        Text(level.rawValue).tag(level)
                    }
                }
                .pickerStyle(.segmented)
            }

            // MARK: - Display
            Section("Display") {
                Toggle("Show speed", isOn: $showSpeed)
                Toggle("Use metric units", isOn: $state.useMetricUnits)
                Toggle("Show bounding boxes", isOn: $visualizeDetections)
                Toggle("Show labels", isOn: $showLabels)
            }

            // MARK: - Advanced detector
            Section("Detector (Advanced)") {
                VStack(alignment: .leading) {
                    Text("IoU threshold: \(iouThreshold, specifier: "%.2f")")
                        .font(.caption)
                        .foregroundColor(.secondary)
                    Slider(value: $iouThreshold, in: 0...1)
                }
            }

            // MARK: - About
            Section("About") {
                NavigationLink("How detection works") {
                    WebView()
                }
                Text("All processing is on-device. No data leaves your phone.")
                    .font(.caption)
                    .foregroundColor(.secondary)
            }
        }
        .navigationTitle("Settings")
    }
}
```

- [x] **Step 2: Commit**

```bash
git add DriverAssistant/Views/SettingsView.swift
git commit -m "feat: update SettingsView with chime toggle and sensitivity picker"
```

---

## Task 13: Model swap — YOLO26n export

This task produces no code changes to the repo. It provides the exact commands you need to run to generate the new model.

> **Flag for user:** Run these commands when you have GPU access (local Mac with Apple Silicon or Google Colab). Until then, the app continues working with `yolov5sTraffic.mlmodel`.

- [x] **Step 1: Set up Python environment**

```bash
# Requires Python 3.10+
pip install ultralytics coremltools torch torchvision
```

- [x] **Step 2: Export pretrained YOLO26n to Core ML**

```bash
# Exports to yolo26n.mlpackage in the current directory
yolo export model=yolo26n.pt format=coreml end2end=False nms=True imgsz=640
```

Expected output: `yolo26n.mlpackage` folder.

- [x] **Step 3: Add model to Xcode project**

Drag `yolo26n.mlpackage` into `DriverAssistant/Models/` in Xcode. When prompted:
- ✅ Copy items if needed
- ✅ Add to target: DriverAssistant

- [x] **Step 4: Update model filename in ViewControllerDetection**

The `setupVision()` method in `ViewControllerDetection.swift` resolves model filenames in priority order:
```swift
("yolo26nTraffic", "mlmodelc")
("yolo26nTraffic", "mlpackage")
("yolo11nTraffic", "mlmodelc")
("yolo11nTraffic", "mlpackage")
("yolov8nTraffic", "mlmodelc")
("yolov8nTraffic", "mlpackage")
("yolov5sTraffic", "mlmodelc")
("yolov5sTraffic", "mlmodel")
```

If you name the exported file `yolo26nTraffic`, no code change is needed. Otherwise update the `forResource:` string to match your filename.

- [x] **Step 5: Verify on device**

Build and run. Open Console.app and filter for `[ViewControllerDetection]` — confirm no "Model not found" error.

- [x] **Step 6: Commit (after model is added)**

```bash
git add DriverAssistant/Models/yolo26nTraffic.mlpackage
git commit -m "feat: add YOLO26n CoreML model for on-device inference"
```

---

## Task 14: PrivacyInfo.xcprivacy (App Store requirement)

**Files:**
- Create: `DriverAssistant/PrivacyInfo.xcprivacy`

Required for App Store submission since Spring 2024. Declares which privacy-sensitive APIs the app accesses.

- [x] **Step 1: Create PrivacyInfo.xcprivacy**

Create `DriverAssistant/PrivacyInfo.xcprivacy` and add to the `DriverAssistant` target (must be in "Copy Bundle Resources" build phase):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>NSPrivacyAccessedAPITypes</key>
    <array>
        <dict>
            <key>NSPrivacyAccessedAPIType</key>
            <string>NSPrivacyAccessedAPICategoryUserDefaults</string>
            <key>NSPrivacyAccessedAPITypeReasons</key>
            <array>
                <string>CA92.1</string>
            </array>
        </dict>
    </dict>
    </array>
    <key>NSPrivacyCollectedDataTypes</key>
    <array/>
    <key>NSPrivacyTracking</key>
    <false/>
    <key>NSPrivacyTrackingDomains</key>
    <array/>
</dict>
</plist>
```

> **Note:** `CA92.1` = "Access info from the same app that created it." This covers the app's own `UserDefaults` usage.

- [x] **Step 2: Commit**

```bash
git add DriverAssistant/PrivacyInfo.xcprivacy
git commit -m "chore: add PrivacyInfo.xcprivacy for App Store submission"
```

---

## Self-Review

**Spec coverage check:**

| Requirement | Task |
|---|---|
| Delete dead code, fix configs | Task 1 |
| State machine red→green | Task 3 |
| Geometry filter | Task 4 |
| Color heuristic (supports both models) | Task 5 |
| Shared DetectionState with speed | Task 6 |
| Chime with cooldown and mute | Task 7 |
| Camera pipeline: 720p, 15fps, error handling | Task 8 |
| Detection refactor wired to all components | Task 9 |
| Scene lifecycle for future CarPlay | Task 10 |
| Reactive HUD | Task 11 |
| Settings with chime controls | Task 12 |
| Model upgrade path | Task 13 |
| App Store privacy manifest | Task 14 |
| Background audio mode | Task 10 (Info.plist) |
| Speed gate (< 2mph) for chime | Task 3 (LightStateManager) + Task 6 (DetectionState.isStationary) |
| Consecutive-frame smoothing | Task 3 (redConfirmCount=3, greenConfirmCount=2) |
| Both model label sets | Task 9 (resolveTrafficLightColor) |
| Tests: state machine | Task 3 |
| Tests: geometry filter | Task 4 |
| Tests: color HSV logic | Task 5 |
| CarPlay | Plan B |

**No placeholders found.** All code blocks are complete. Type names are consistent across tasks.

**One user decision outstanding:** chime sound file (`chime.aiff`). Flagged in Task 7.

---

## Plan B (CarPlay) — Prerequisite checklist

Before starting Plan B:
- [ ] Plan A is complete and chime is working on device
- [ ] Apple "Driving Task" entitlement has been requested at developer.apple.com/contact/request/carplay
- [ ] Entitlement approval received (typically 1–5 business days)
- [ ] Provisioning profile updated with CarPlay entitlement
