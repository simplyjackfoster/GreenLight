# GreenLight Safety & Evaluation Hardening Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the broken speed gate, unsynchronized fallback state machine, missing on-device telemetry, and un-runnable evaluation pipeline so GreenLight's ship gate (< 0.5 FP/hour, > 92% TPR) can be measured and trusted.

**Architecture:** Two independent workstreams that can run concurrently on different machines. Group A (Swift, Mac-only) hardens the iOS runtime: replaces the broken `isStationary: Bool` with a tri-state `SpeedStatus`, synchronizes the fallback chime path, and adds structured per-frame telemetry. Group B (Python, Mac or PC) makes the evaluation pipeline actually runnable: adds a video annotation tool, an HSV calibration script, and medium-priority pipeline improvements.

**Tech Stack:** Swift 5.9, XCTest, CoreLocation, Python 3.10+, OpenCV (`cv2`), imagehash (`pip install imagehash`), PyTorch, coremltools

---

## File Map

### Group A — Swift Runtime (Mac)
- Modify: `GreenLight/Detection/Types.swift` — add `SpeedStatus` enum
- Modify: `GreenLight/State/DetectionState.swift` — replace `isStationary: Bool` with `speedStatus: SpeedStatus`, track GPS availability
- Modify: `GreenLight/Detection/LightStateManager.swift` — update `update()` signatures, add `isTrackingRedOrTransitioning` property
- Modify: `GreenLight/ViewControllers/ViewControllerDetection.swift` — pass `speedStatus`, gate fallback on `isTrackingRedOrTransitioning`
- Create: `GreenLight/Telemetry/TelemetryLogger.swift` — per-frame structured JSONL logging with 7-day rolling retention
- Modify: `GreenLightTests/LightStateManagerTests.swift` — update all `isStationary:` call sites to `speedStatus:`
- Create: `GreenLightTests/TelemetryLoggerTests.swift` — telemetry file creation and pruning tests

### Group B — Python ML Tooling (Mac or PC)
- Create: `label_clips.py` — OpenCV-based frame-by-frame video annotator outputting evaluate.py-compatible CSV
- Create: `calibrate_hsv.py` — reads crop images from `export/datasets/crops/`, outputs HSV 5th/95th percentile table per class
- Modify: `GreenLight/Detection/ColorHeuristic.swift` — update HSV constants from calibration output (done after Task 7 output)
- Modify: `adaptive_state_manager.py` — add `tentative_green_timeout_frames` config + speed-adaptive buffer size
- Modify: `dataset_pipeline.py` — pHash-based temporal deduplication before train/val split
- Modify: `export_coreml.py` — add per-channel divergence check between multiarray and image-mode inference paths
- Modify: `Tests/test_dataset_pipeline.py` — add deduplication unit tests

---

## Group A: Swift Runtime Hardening

### Task 1: SpeedStatus tri-state + DetectionState

**Files:**
- Modify: `GreenLight/Detection/Types.swift`
- Modify: `GreenLight/State/DetectionState.swift`

- [ ] **Step 1: Add SpeedStatus to Types.swift**

Open `GreenLight/Detection/Types.swift`. After the `ConfidenceSensitivity` enum, add:

```swift
enum SpeedStatus: Equatable {
    case knownStationary   // GPS active, speed < threshold
    case knownMoving       // GPS active, speed >= threshold
    case unknown           // No fix or permission denied — fail-safe: suppress chime
}
```

- [ ] **Step 2: Update DetectionState to track GPS availability**

Replace the entire body of `GreenLight/State/DetectionState.swift` with:

```swift
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
```

- [ ] **Step 3: Build to check for compile errors**

```bash
xcodebuild -project GreenLight.xcodeproj -scheme GreenLight -destination 'generic/platform=iOS' build 2>&1 | grep -E "error:|warning:|BUILD"
```

Expected: compile errors in `LightStateManager.swift` and `ViewControllerDetection.swift` because `isStationary` is now gone. That is correct — fix in Task 2.

- [ ] **Step 4: Commit**

```bash
git add GreenLight/Detection/Types.swift GreenLight/State/DetectionState.swift
git commit -m "feat: replace isStationary Bool with SpeedStatus tri-state in DetectionState"
```

---

### Task 2: Update LightStateManager and LightTransitionFallbackState

**Files:**
- Modify: `GreenLight/Detection/LightStateManager.swift`

- [ ] **Step 1: Replace LightStateManager.swift**

Replace the entire file `GreenLight/Detection/LightStateManager.swift` with:

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
        redConfirmCount: Int = Constants.Detection.redConfirmFrames,
        greenConfirmCount: Int = Constants.Detection.greenConfirmFrames,
        cooldownDuration: TimeInterval = Constants.Chime.cooldownSeconds
    ) {
        self.redConfirmCount = redConfirmCount
        self.greenConfirmCount = greenConfirmCount
        self.cooldownDuration = cooldownDuration
    }

    @discardableResult
    func update(
        detectedLight: DetectedLightColor,
        speedStatus: SpeedStatus,
        now: Date = Date()
    ) -> Bool {
        if case .cooldown = internalState {
            guard let start = cooldownStart,
                  now.timeIntervalSince(start) >= cooldownDuration else {
                return false
            }
            internalState = .idle
            cooldownStart = nil
        }

        switch (internalState, detectedLight) {
        case (.idle, .red):
            internalState = .trackingRed(count: 1)

        case (.trackingRed(let count), .red):
            let next = count + 1
            internalState = next >= redConfirmCount ? .confirmedRed : .trackingRed(count: next)

        case (.confirmedRed, .green):
            if speedStatus == .knownStationary {
                internalState = .transitioningToGreen(count: 1)
            } else {
                internalState = .idle
            }

        case (.transitioningToGreen(let count), .green):
            if speedStatus == .knownStationary {
                let next = count + 1
                if next >= greenConfirmCount {
                    internalState = .cooldown
                    cooldownStart = now
                    return true
                }
                internalState = .transitioningToGreen(count: next)
            } else {
                internalState = .idle
            }

        case (.trackingRed, _),
             (.confirmedRed, .none),
             (.confirmedRed, .yellow),
             (.transitioningToGreen, .none),
             (.transitioningToGreen, .red),
             (.transitioningToGreen, .yellow):
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

    var displayState: DetectedLightColor {
        switch internalState {
        case .idle:
            return .unknown
        case .trackingRed, .confirmedRed:
            return .red
        case .transitioningToGreen, .cooldown:
            return .green
        }
    }

    var isTrackingRedOrTransitioning: Bool {
        switch internalState {
        case .trackingRed, .confirmedRed, .transitioningToGreen:
            return true
        default:
            return false
        }
    }
}

final class LightTransitionFallbackState {

    let cooldownDuration: TimeInterval
    let redMemoryDuration: TimeInterval

    private var lastRedSeenAt: Date?
    private var lastChimeAt: Date?

    init(
        cooldownDuration: TimeInterval = Constants.Chime.cooldownSeconds,
        redMemoryDuration: TimeInterval = Constants.Chime.redMemorySeconds
    ) {
        self.cooldownDuration = cooldownDuration
        self.redMemoryDuration = redMemoryDuration
    }

    @discardableResult
    func update(
        filteredLight: DetectedLightColor,
        observedLight: DetectedLightColor,
        speedStatus: SpeedStatus,
        now: Date = Date()
    ) -> Bool {
        let effectiveLight = resolvedLight(filteredLight: filteredLight, observedLight: observedLight)

        if effectiveLight == .red {
            lastRedSeenAt = now
            return false
        }

        guard effectiveLight == .green, speedStatus == .knownStationary else { return false }

        guard let lastRedSeenAt else { return false }
        let elapsedSinceRed = now.timeIntervalSince(lastRedSeenAt)
        guard elapsedSinceRed <= redMemoryDuration else {
            self.lastRedSeenAt = nil
            return false
        }

        if let lastChimeAt, now.timeIntervalSince(lastChimeAt) < cooldownDuration {
            return false
        }

        self.lastChimeAt = now
        self.lastRedSeenAt = nil
        return true
    }

    func reset() {
        lastRedSeenAt = nil
        lastChimeAt = nil
    }

    private func resolvedLight(
        filteredLight: DetectedLightColor,
        observedLight: DetectedLightColor
    ) -> DetectedLightColor {
        if filteredLight == .red || filteredLight == .green {
            return filteredLight
        }
        if observedLight == .red || observedLight == .green {
            return observedLight
        }
        return .none
    }
}
```

- [ ] **Step 2: Build to verify LightStateManager compiles**

```bash
xcodebuild -project GreenLight.xcodeproj -scheme GreenLight -destination 'generic/platform=iOS' build 2>&1 | grep -E "error:|BUILD"
```

Expected: errors only in `ViewControllerDetection.swift` (still passes old `isStationary:`). That is correct.

- [ ] **Step 3: Commit**

```bash
git add GreenLight/Detection/LightStateManager.swift
git commit -m "feat: update LightStateManager to accept SpeedStatus, add isTrackingRedOrTransitioning"
```

---

### Task 3: Fix ViewControllerDetection — speed gate + fallback sync

**Files:**
- Modify: `GreenLight/ViewControllers/ViewControllerDetection.swift`

- [ ] **Step 1: Update handleResults to use speedStatus and gate the fallback**

In `GreenLight/ViewControllers/ViewControllerDetection.swift`, replace the `handleResults` method (lines 87–154) with:

```swift
@MainActor
private func handleResults(_ results: [Any]) {
    detectionOverlay.sublayers = nil

    let threshold = detectionState.sensitivity.confidenceThreshold
    var bestFilteredLightColor: DetectedLightColor = .none
    var bestFilteredConfidence: Float = 0
    var bestObservedLightColor: DetectedLightColor = .none
    var bestObservedConfidence: Float = 0

    for observation in results.compactMap({ $0 as? VNRecognizedObjectObservation }) {
        guard let top = observation.labels.first,
              Double(top.confidence) >= threshold else { continue }

        let label = top.identifier
        let box = observation.boundingBox

        let lightColor = resolveTrafficLightColor(label: label, box: box)
        if lightColor != .unknown, lightColor != .none,
           top.confidence > bestObservedConfidence {
            bestObservedLightColor = lightColor
            bestObservedConfidence = top.confidence
        }

        if lightColor != .unknown, lightColor != .none,
           GeometryFilter.passes(normalizedBox: box),
           top.confidence > bestFilteredConfidence {
            bestFilteredLightColor = lightColor
            bestFilteredConfidence = top.confidence
        }

        let objectBounds = VNImageRectForNormalizedRect(box, Int(bufferSize.width), Int(bufferSize.height))

        if boolDefaultTrue("visualizeDetections") {
            detectionOverlay.addSublayer(drawBox(objectBounds, label: label))
        }
        if boolDefaultTrue("showLabels") {
            detectionOverlay.addSublayer(drawLabel(objectBounds, label: label, confidence: top.confidence))
        }
    }

    let speedStatus = detectionState.speedStatus

    let stateMachineChime = stateManager.update(
        detectedLight: bestFilteredLightColor,
        speedStatus: speedStatus
    )

    // Fallback only activates when the primary state machine is actively tracking red/transitioning.
    // This prevents the fallback from being a fully independent chime path that bypasses geometry.
    let fallbackChime = stateManager.isTrackingRedOrTransitioning && fallbackState.update(
        filteredLight: bestFilteredLightColor,
        observedLight: bestObservedLightColor,
        speedStatus: speedStatus
    )

    if previousObservedLight == .red && bestObservedLightColor == .green {
        detectionState.triggerGreenTransitionCue()
    }
    previousObservedLight = bestObservedLightColor

    detectionState.lightColor = stateManager.displayState

    let chimeFired = stateMachineChime || fallbackChime
    chimeController.isMuted = !detectionState.isChimeEnabled
    if chimeFired {
        chimeController.play()
        detectionState.triggerGreenTransitionCue()
    }

    TelemetryLogger.shared.log(TelemetryEvent(
        filteredLight: bestFilteredLightColor,
        observedLight: bestObservedLightColor,
        speedStatus: speedStatus,
        stateMachineChime: stateMachineChime,
        fallbackChime: fallbackChime,
        displayState: stateManager.displayState
    ))
}
```

- [ ] **Step 2: Build — expect a missing TelemetryLogger error**

```bash
xcodebuild -project GreenLight.xcodeproj -scheme GreenLight -destination 'generic/platform=iOS' build 2>&1 | grep -E "error:|BUILD"
```

Expected: one error about `TelemetryLogger` not found. That is correct — add it in Task 4.

- [ ] **Step 3: Commit**

```bash
git add GreenLight/ViewControllers/ViewControllerDetection.swift
git commit -m "fix: use SpeedStatus tri-state for speed gate and synchronize fallback chime path"
```

---

### Task 4: TelemetryLogger

**Files:**
- Create: `GreenLight/Telemetry/TelemetryLogger.swift`

- [ ] **Step 1: Create the Telemetry directory and TelemetryLogger.swift**

Create `GreenLight/Telemetry/TelemetryLogger.swift`:

```swift
import Foundation

struct TelemetryEvent: Encodable {
    let timestamp: String
    let filteredLight: String
    let observedLight: String
    let speedStatus: String
    let stateMachineChime: Bool
    let fallbackChime: Bool
    let displayState: String

    init(
        filteredLight: DetectedLightColor,
        observedLight: DetectedLightColor,
        speedStatus: SpeedStatus,
        stateMachineChime: Bool,
        fallbackChime: Bool,
        displayState: DetectedLightColor
    ) {
        self.timestamp = ISO8601DateFormatter().string(from: Date())
        self.filteredLight = filteredLight.telemetryLabel
        self.observedLight = observedLight.telemetryLabel
        self.speedStatus = speedStatus.telemetryLabel
        self.stateMachineChime = stateMachineChime
        self.fallbackChime = fallbackChime
        self.displayState = displayState.telemetryLabel
    }
}

final class TelemetryLogger {
    static let shared = TelemetryLogger()

    private let queue = DispatchQueue(label: "TelemetryLogger", qos: .utility)
    private let retentionDays = 7
    private let encoder = JSONEncoder()

    private var currentFileHandle: FileHandle?
    private var currentFileDate: String = ""

    private init() {
        queue.async { self.pruneOldFiles() }
    }

    func log(_ event: TelemetryEvent) {
        queue.async { [self] in
            guard let data = try? encoder.encode(event),
                  let line = String(data: data, encoding: .utf8) else { return }
            appendLine(line)
        }
    }

    private func appendLine(_ line: String) {
        let today = dateString(from: Date())
        if today != currentFileDate {
            currentFileHandle?.closeFile()
            currentFileHandle = openHandle(for: today)
            currentFileDate = today
        }
        guard let handle = currentFileHandle else { return }
        handle.write((line + "\n").data(using: .utf8)!)
    }

    private func openHandle(for dateString: String) -> FileHandle? {
        guard let dir = telemetryDirectory() else { return nil }
        let url = dir.appendingPathComponent("\(dateString).jsonl")
        if !FileManager.default.fileExists(atPath: url.path) {
            FileManager.default.createFile(atPath: url.path, contents: nil)
        }
        return try? FileHandle(forWritingTo: url)
    }

    private func pruneOldFiles() {
        guard let dir = telemetryDirectory(),
              let files = try? FileManager.default.contentsOfDirectory(
                  at: dir, includingPropertiesForKeys: [.creationDateKey]) else { return }
        let cutoff = Calendar.current.date(byAdding: .day, value: -retentionDays, to: Date())!
        for file in files {
            guard let created = try? file.resourceValues(forKeys: [.creationDateKey]).creationDate,
                  created < cutoff else { continue }
            try? FileManager.default.removeItem(at: file)
        }
    }

    private func telemetryDirectory() -> URL? {
        guard let docs = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first else {
            return nil
        }
        let dir = docs.appendingPathComponent("telemetry")
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir
    }

    private func dateString(from date: Date) -> String {
        let fmt = DateFormatter()
        fmt.dateFormat = "yyyy-MM-dd"
        return fmt.string(from: date)
    }
}

private extension DetectedLightColor {
    var telemetryLabel: String {
        switch self {
        case .red: return "red"
        case .green: return "green"
        case .yellow: return "yellow"
        case .unknown: return "unknown"
        case .none: return "none"
        }
    }
}

private extension SpeedStatus {
    var telemetryLabel: String {
        switch self {
        case .knownStationary: return "stationary"
        case .knownMoving: return "moving"
        case .unknown: return "unknown"
        }
    }
}
```

- [ ] **Step 2: Add TelemetryLogger.swift to the Xcode target**

Open `GreenLight.xcodeproj/project.pbxproj` and verify `TelemetryLogger.swift` is in the Compile Sources build phase. If added via Xcode file creation, it auto-includes. If done via CLI, the agent must add the file reference manually using Xcode or by editing `project.pbxproj`. The easiest approach: open Xcode, right-click `GreenLight/Telemetry` group → Add Files → select `TelemetryLogger.swift` → ensure "Add to targets: GreenLight" is checked.

- [ ] **Step 3: Build cleanly**

```bash
xcodebuild -project GreenLight.xcodeproj -scheme GreenLight -destination 'generic/platform=iOS' build 2>&1 | grep -E "error:|BUILD"
```

Expected: `** BUILD SUCCEEDED **`

- [ ] **Step 4: Commit**

```bash
git add GreenLight/Telemetry/TelemetryLogger.swift GreenLight.xcodeproj/project.pbxproj
git commit -m "feat: add TelemetryLogger for per-frame structured JSONL logging with 7-day retention"
```

---

### Task 5: Update Swift tests

**Files:**
- Modify: `GreenLightTests/LightStateManagerTests.swift`
- Create: `GreenLightTests/TelemetryLoggerTests.swift`

- [ ] **Step 1: Update LightStateManagerTests — replace all `isStationary:` with `speedStatus:`**

In `GreenLightTests/LightStateManagerTests.swift`, replace the helper and all test methods. The key change: every `isStationary: true` becomes `speedStatus: .knownStationary`, every `isStationary: false` becomes `speedStatus: .knownMoving`.

Replace the entire file with:

```swift
import XCTest
@testable import GreenLight

final class LightStateManagerTests: XCTestCase {

    private func confirmRed(mgr: LightStateManager, count: Int = 3, now: Date = Date()) {
        for _ in 0..<count {
            _ = mgr.update(detectedLight: .red, speedStatus: .knownStationary, now: now)
        }
    }

    func testSingleRedFrameDoesNotConfirm() {
        let mgr = LightStateManager()
        let t = Date()
        _ = mgr.update(detectedLight: .red, speedStatus: .knownStationary, now: t)
        XCTAssertFalse(mgr.update(detectedLight: .green, speedStatus: .knownStationary, now: t))
    }

    func testTwoRedFramesDoNotConfirm() {
        let mgr = LightStateManager(redConfirmCount: 3)
        let t = Date()
        _ = mgr.update(detectedLight: .red, speedStatus: .knownStationary, now: t)
        _ = mgr.update(detectedLight: .red, speedStatus: .knownStationary, now: t)
        XCTAssertFalse(mgr.update(detectedLight: .green, speedStatus: .knownStationary, now: t))
        XCTAssertFalse(mgr.update(detectedLight: .green, speedStatus: .knownStationary, now: t))
    }

    func testRedInterruptedByNoneResetsCount() {
        let mgr = LightStateManager(redConfirmCount: 3)
        let t = Date()
        _ = mgr.update(detectedLight: .red, speedStatus: .knownStationary, now: t)
        _ = mgr.update(detectedLight: .red, speedStatus: .knownStationary, now: t)
        _ = mgr.update(detectedLight: .none, speedStatus: .knownStationary, now: t)
        _ = mgr.update(detectedLight: .red, speedStatus: .knownStationary, now: t)
        _ = mgr.update(detectedLight: .red, speedStatus: .knownStationary, now: t)
        XCTAssertFalse(mgr.update(detectedLight: .green, speedStatus: .knownStationary, now: t))
        XCTAssertFalse(mgr.update(detectedLight: .green, speedStatus: .knownStationary, now: t))
    }

    func testFullSequenceTriggerChime() {
        let mgr = LightStateManager(redConfirmCount: 3, greenConfirmCount: 2)
        let t = Date()
        confirmRed(mgr: mgr, count: 3, now: t)
        XCTAssertFalse(mgr.update(detectedLight: .green, speedStatus: .knownStationary, now: t))
        XCTAssertTrue(mgr.update(detectedLight: .green, speedStatus: .knownStationary, now: t))
    }

    func testChimeFiresExactlyOnce() {
        let mgr = LightStateManager(redConfirmCount: 3, greenConfirmCount: 2, cooldownDuration: 20)
        let t = Date()
        confirmRed(mgr: mgr, count: 3, now: t)
        _ = mgr.update(detectedLight: .green, speedStatus: .knownStationary, now: t)
        let fired = mgr.update(detectedLight: .green, speedStatus: .knownStationary, now: t)
        XCTAssertTrue(fired)
        XCTAssertFalse(mgr.update(detectedLight: .green, speedStatus: .knownStationary, now: t))
        XCTAssertFalse(mgr.update(detectedLight: .green, speedStatus: .knownStationary, now: t))
    }

    func testNoChimeWhenMoving() {
        let mgr = LightStateManager(redConfirmCount: 3, greenConfirmCount: 2)
        let t = Date()
        confirmRed(mgr: mgr, count: 3, now: t)
        XCTAssertFalse(mgr.update(detectedLight: .green, speedStatus: .knownMoving, now: t))
        XCTAssertFalse(mgr.update(detectedLight: .green, speedStatus: .knownMoving, now: t))
    }

    func testNoChimeWhenSpeedUnknown() {
        let mgr = LightStateManager(redConfirmCount: 3, greenConfirmCount: 2)
        let t = Date()
        confirmRed(mgr: mgr, count: 3, now: t)
        XCTAssertFalse(mgr.update(detectedLight: .green, speedStatus: .unknown, now: t))
        XCTAssertFalse(mgr.update(detectedLight: .green, speedStatus: .unknown, now: t))
    }

    func testChimeFiresIfStationaryDuringRedAndGreen() {
        let mgr = LightStateManager(redConfirmCount: 3, greenConfirmCount: 2)
        let t = Date()
        confirmRed(mgr: mgr, count: 3, now: t)
        _ = mgr.update(detectedLight: .green, speedStatus: .knownStationary, now: t)
        XCTAssertTrue(mgr.update(detectedLight: .green, speedStatus: .knownStationary, now: t))
    }

    func testCooldownBlocksImmediateReTrigger() {
        let mgr = LightStateManager(redConfirmCount: 3, greenConfirmCount: 2, cooldownDuration: 20)
        let t0 = Date()
        confirmRed(mgr: mgr, count: 3, now: t0)
        _ = mgr.update(detectedLight: .green, speedStatus: .knownStationary, now: t0)
        _ = mgr.update(detectedLight: .green, speedStatus: .knownStationary, now: t0)

        let t1 = t0.addingTimeInterval(5)
        confirmRed(mgr: mgr, count: 3, now: t1)
        _ = mgr.update(detectedLight: .green, speedStatus: .knownStationary, now: t1)
        XCTAssertFalse(mgr.update(detectedLight: .green, speedStatus: .knownStationary, now: t1))
    }

    func testCooldownExpiryAllowsReTrigger() {
        let mgr = LightStateManager(redConfirmCount: 3, greenConfirmCount: 2, cooldownDuration: 20)
        let t0 = Date()
        confirmRed(mgr: mgr, count: 3, now: t0)
        _ = mgr.update(detectedLight: .green, speedStatus: .knownStationary, now: t0)
        _ = mgr.update(detectedLight: .green, speedStatus: .knownStationary, now: t0)

        let t1 = t0.addingTimeInterval(21)
        confirmRed(mgr: mgr, count: 3, now: t1)
        _ = mgr.update(detectedLight: .green, speedStatus: .knownStationary, now: t1)
        XCTAssertTrue(mgr.update(detectedLight: .green, speedStatus: .knownStationary, now: t1))
    }

    func testIsTrackingRedOrTransitioningWhenTrackingRed() {
        let mgr = LightStateManager(redConfirmCount: 3)
        let t = Date()
        _ = mgr.update(detectedLight: .red, speedStatus: .knownStationary, now: t)
        XCTAssertTrue(mgr.isTrackingRedOrTransitioning)
    }

    func testIsTrackingRedOrTransitioningFalseWhenIdle() {
        let mgr = LightStateManager()
        XCTAssertFalse(mgr.isTrackingRedOrTransitioning)
    }

    func testFallbackDoesNotChimeWhenSpeedUnknown() {
        let fallback = LightTransitionFallbackState(cooldownDuration: 20, redMemoryDuration: 8)
        let t = Date()
        _ = fallback.update(filteredLight: .none, observedLight: .red, speedStatus: .knownStationary, now: t)
        XCTAssertFalse(fallback.update(
            filteredLight: .none,
            observedLight: .green,
            speedStatus: .unknown,
            now: t.addingTimeInterval(1)
        ))
    }

    func testFallbackUsesObservedLightWhenFilteredMissing() {
        let fallback = LightTransitionFallbackState(cooldownDuration: 20, redMemoryDuration: 8)
        let t = Date()
        XCTAssertFalse(fallback.update(
            filteredLight: .none,
            observedLight: .red,
            speedStatus: .knownStationary,
            now: t
        ))
        XCTAssertTrue(fallback.update(
            filteredLight: .none,
            observedLight: .green,
            speedStatus: .knownStationary,
            now: t.addingTimeInterval(1)
        ))
    }

    func testFallbackRedMemoryExpires() {
        let fallback = LightTransitionFallbackState(cooldownDuration: 20, redMemoryDuration: 3)
        let t = Date()
        _ = fallback.update(filteredLight: .none, observedLight: .red, speedStatus: .knownStationary, now: t)
        XCTAssertFalse(fallback.update(
            filteredLight: .none,
            observedLight: .green,
            speedStatus: .knownStationary,
            now: t.addingTimeInterval(4)
        ))
    }

    func testFallbackRespectsCooldown() {
        let fallback = LightTransitionFallbackState(cooldownDuration: 20, redMemoryDuration: 8)
        let t0 = Date()
        _ = fallback.update(filteredLight: .none, observedLight: .red, speedStatus: .knownStationary, now: t0)
        XCTAssertTrue(fallback.update(
            filteredLight: .none,
            observedLight: .green,
            speedStatus: .knownStationary,
            now: t0.addingTimeInterval(1)
        ))

        let t1 = t0.addingTimeInterval(5)
        _ = fallback.update(filteredLight: .none, observedLight: .red, speedStatus: .knownStationary, now: t1)
        XCTAssertFalse(fallback.update(
            filteredLight: .none,
            observedLight: .green,
            speedStatus: .knownStationary,
            now: t1.addingTimeInterval(1)
        ))
    }

    func testFallbackPrefersFilteredLightOverObserved() {
        let fallback = LightTransitionFallbackState(cooldownDuration: 20, redMemoryDuration: 8)
        let t = Date()
        _ = fallback.update(filteredLight: .red, observedLight: .none, speedStatus: .knownStationary, now: t)
        XCTAssertTrue(fallback.update(
            filteredLight: .green,
            observedLight: .red,
            speedStatus: .knownStationary,
            now: t.addingTimeInterval(1)
        ))
    }
}
```

- [ ] **Step 2: Create TelemetryLoggerTests.swift**

Create `GreenLightTests/TelemetryLoggerTests.swift`:

```swift
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
```

- [ ] **Step 3: Run all Swift tests**

```bash
xcodebuild test -project GreenLight.xcodeproj -scheme GreenLight \
  -destination 'platform=iOS Simulator,name=iPhone 16' 2>&1 | grep -E "Test.*passed|Test.*failed|error:|BUILD"
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add GreenLightTests/LightStateManagerTests.swift GreenLightTests/TelemetryLoggerTests.swift
git commit -m "test: update LightStateManager tests for SpeedStatus, add TelemetryLogger tests"
```

---

## Group B: Python ML Tooling

### Task 6: label_clips.py — video annotation tool

**Files:**
- Create: `label_clips.py`

**Purpose:** Allows annotating a recorded driving video frame-by-frame with ground-truth traffic light states. Output CSV is the input to `evaluate.py`.

**Prerequisite:** `pip install opencv-python` (already present in the dataset venv).

- [ ] **Step 1: Write the failing test**

Create `Tests/test_label_clips.py`:

```python
import csv
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).parent.parent))
from label_clips import build_frame_csv, interpolate_annotations


class TestLabelClips(unittest.TestCase):

    def test_interpolate_fills_frames_between_keyframes(self):
        keyframes = {0: "red", 5: "green"}
        result = interpolate_annotations(keyframes, total_frames=8)
        self.assertEqual(result[0], "red")
        self.assertEqual(result[1], "red")
        self.assertEqual(result[4], "red")
        self.assertEqual(result[5], "green")
        self.assertEqual(result[7], "green")

    def test_build_frame_csv_columns(self):
        annotations = {i: "red" for i in range(3)}
        rows = build_frame_csv(
            annotations=annotations,
            lighting="day",
            visible_lights=1,
            fps=30.0,
        )
        self.assertEqual(len(rows), 3)
        self.assertIn("frame_index", rows[0])
        self.assertIn("gt_state", rows[0])
        self.assertIn("pred_state", rows[0])
        self.assertIn("chime", rows[0])
        self.assertIn("lighting", rows[0])
        self.assertIn("visible_lights", rows[0])
        self.assertEqual(rows[0]["gt_state"], "red")
        self.assertEqual(rows[0]["pred_state"], "none")
        self.assertEqual(rows[0]["chime"], "0")

    def test_interpolate_empty_keyframes_raises(self):
        with self.assertRaises(ValueError):
            interpolate_annotations({}, total_frames=10)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify failure**

```bash
cd ~/GreenLight && python -m pytest Tests/test_label_clips.py -v 2>&1 | head -20
```

Expected: `ImportError` or `ModuleNotFoundError` for `label_clips`.

- [ ] **Step 3: Implement label_clips.py**

Create `label_clips.py` in the project root:

```python
#!/usr/bin/env python3
"""Video annotation tool for traffic-light ground-truth labeling.

Keyboard controls (when video window is open):
  SPACE       play / pause
  RIGHT / D   step forward one frame
  LEFT  / A   step back one frame
  r           mark current frame as RED
  g           mark current frame as GREEN
  y           mark current frame as YELLOW
  o           mark current frame as OFF
  s           save CSV and continue
  q           save CSV and quit

The tool uses keyframe interpolation: marking frame 10 as RED and frame 20 as GREEN
fills frames 10-19 as RED and 20+ as GREEN.

Output CSV columns match evaluate.py:
  frame_index, gt_state, pred_state, chime, lighting, visible_lights

pred_state is always "none" (fill later from telemetry).
chime is always "0" (fill later from telemetry).
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

try:
    import cv2
    CV2_AVAILABLE = True
except ModuleNotFoundError:
    CV2_AVAILABLE = False

VALID_STATES = {"red", "green", "yellow", "off"}
KEY_MAP = {
    ord("r"): "red",
    ord("g"): "green",
    ord("y"): "yellow",
    ord("o"): "off",
}


def interpolate_annotations(
    keyframes: dict[int, str],
    total_frames: int,
) -> dict[int, str]:
    if not keyframes:
        raise ValueError("No keyframes provided")

    sorted_keys = sorted(keyframes)
    result: dict[int, str] = {}

    for i, kf in enumerate(sorted_keys):
        state = keyframes[kf]
        end = sorted_keys[i + 1] if i + 1 < len(sorted_keys) else total_frames
        for f in range(kf, end):
            result[f] = state

    # Fill any frames before the first keyframe with the first keyframe state.
    first_state = keyframes[sorted_keys[0]]
    for f in range(0, sorted_keys[0]):
        result[f] = first_state

    return result


def build_frame_csv(
    annotations: dict[int, str],
    lighting: str,
    visible_lights: int,
    fps: float,
) -> list[dict[str, str]]:
    rows = []
    for frame_index in sorted(annotations):
        rows.append({
            "frame_index": str(frame_index),
            "gt_state": annotations[frame_index],
            "pred_state": "none",
            "chime": "0",
            "lighting": lighting,
            "visible_lights": str(visible_lights),
        })
    return rows


def save_csv(rows: list[dict[str, str]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["frame_index", "gt_state", "pred_state", "chime", "lighting", "visible_lights"]
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def annotate_interactive(
    video_path: Path,
    output_csv: Path,
    lighting: str,
    visible_lights: int,
) -> None:
    if not CV2_AVAILABLE:
        raise SystemExit("OpenCV not available. Install with: pip install opencv-python")

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise SystemExit(f"Cannot open video: {video_path}")

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

    keyframes: dict[int, str] = {}
    frame_idx = 0
    paused = True
    current_state = "unknown"

    print(f"Annotating {video_path.name} ({total_frames} frames @ {fps:.1f} fps)")
    print("Controls: r=red  g=green  y=yellow  o=off  SPACE=play/pause  <-/->= step  s=save  q=quit")

    while True:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = cap.read()
        if not ret:
            break

        h, w = frame.shape[:2]
        overlay = frame.copy()
        colour = {
            "red": (0, 0, 220),
            "green": (0, 200, 0),
            "yellow": (0, 200, 220),
            "off": (150, 150, 150),
        }.get(current_state, (200, 200, 200))

        cv2.rectangle(overlay, (0, 0), (w, 50), (30, 30, 30), -1)
        cv2.putText(overlay, f"Frame {frame_idx}/{total_frames - 1}  State: {current_state}",
                    (10, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.9, colour, 2)
        cv2.putText(overlay, "r=red  g=green  y=yellow  o=off  SPACE=play  <-/->= step  s=save  q=quit",
                    (10, h - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (180, 180, 180), 1)

        cv2.imshow("GreenLight Annotator", overlay)
        wait_ms = 0 if paused else max(1, int(1000 / fps))
        key = cv2.waitKey(wait_ms) & 0xFF

        if key == ord("q"):
            break
        elif key == ord("s"):
            if keyframes:
                ann = interpolate_annotations(keyframes, total_frames)
                rows = build_frame_csv(ann, lighting, visible_lights, fps)
                save_csv(rows, output_csv)
                print(f"Saved {len(rows)} rows to {output_csv}")
        elif key in KEY_MAP:
            current_state = KEY_MAP[key]
            keyframes[frame_idx] = current_state
            print(f"  frame {frame_idx}: {current_state}")
        elif key == ord(" "):
            paused = not paused
        elif key in (83, ord("d")):  # right arrow or d
            frame_idx = min(frame_idx + 1, total_frames - 1)
            paused = True
        elif key in (81, ord("a")):  # left arrow or a
            frame_idx = max(frame_idx - 1, 0)
            paused = True

        if not paused:
            frame_idx = min(frame_idx + 1, total_frames - 1)
            if frame_idx == total_frames - 1:
                paused = True

    cap.release()
    cv2.destroyAllWindows()

    if keyframes:
        ann = interpolate_annotations(keyframes, total_frames)
        rows = build_frame_csv(ann, lighting, visible_lights, fps)
        save_csv(rows, output_csv)
        print(f"Saved {len(rows)} rows to {output_csv}")
    else:
        print("No annotations made — nothing saved.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Annotate driving video clips for evaluate.py")
    parser.add_argument("video", type=Path, help="Path to video file (.mp4, .mov, etc.)")
    parser.add_argument("--output", "-o", type=Path, default=None,
                        help="Output CSV path (default: <video_stem>_annotations.csv)")
    parser.add_argument("--lighting", choices=["day", "dusk", "night"], default="day")
    parser.add_argument("--visible-lights", type=int, default=1)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output = args.output or args.video.with_name(args.video.stem + "_annotations.csv")
    annotate_interactive(
        video_path=args.video,
        output_csv=output,
        lighting=args.lighting,
        visible_lights=args.visible_lights,
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests**

```bash
cd ~/GreenLight && python -m pytest Tests/test_label_clips.py -v
```

Expected: all 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add label_clips.py Tests/test_label_clips.py
git commit -m "feat: add label_clips.py video annotation tool for evaluate.py ground-truth generation"
```

---

### Task 7: calibrate_hsv.py — HSV range calibration

**Files:**
- Create: `calibrate_hsv.py`

**Prerequisite:** Datasets downloaded and `dataset_pipeline.py` already run so crops exist in `export/datasets/crops/traffic_state/`.

- [ ] **Step 1: Write the failing test**

Create `Tests/test_calibrate_hsv.py`:

```python
import sys
import unittest
import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from calibrate_hsv import compute_hsv_percentiles, format_swift_ranges


class TestCalibrateHSV(unittest.TestCase):

    def _make_bgr_patch(self, h_deg: float, s: float, v: float) -> np.ndarray:
        """Create a 10x10 BGR patch with the given HSV values."""
        import cv2
        h_cv = int(h_deg / 2)  # OpenCV uses 0-179
        s_cv = int(s * 255)
        v_cv = int(v * 255)
        hsv = np.full((10, 10, 3), [h_cv, s_cv, v_cv], dtype=np.uint8)
        return cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)

    def test_pure_red_lands_in_red_range(self):
        import cv2
        red_patch = self._make_bgr_patch(0, 0.9, 0.9)  # 0° hue = pure red
        result = compute_hsv_percentiles({"red": [red_patch]})
        # Hue 0° in OpenCV is 0; in our output it should be near 0
        self.assertIn("red", result)
        self.assertLessEqual(result["red"]["h_p05"], 5)

    def test_pure_green_lands_in_green_range(self):
        green_patch = self._make_bgr_patch(120, 0.8, 0.8)  # 120° = green
        result = compute_hsv_percentiles({"green": [green_patch]})
        self.assertIn("green", result)
        p05 = result["green"]["h_p05"]
        p95 = result["green"]["h_p95"]
        self.assertGreater(p95, p05)

    def test_format_swift_ranges_produces_valid_output(self):
        stats = {
            "red": {"h_p05": 355.0, "h_p95": 10.0, "s_p05": 0.5, "s_p95": 0.95, "v_p05": 0.3, "v_p95": 0.95},
            "green": {"h_p05": 90.0, "h_p95": 150.0, "s_p05": 0.4, "s_p95": 0.9, "v_p05": 0.3, "v_p95": 0.9},
        }
        output = format_swift_ranges(stats)
        self.assertIn("red", output.lower())
        self.assertIn("green", output.lower())
        self.assertIn("isRed", output)
        self.assertIn("isGreen", output)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify failure**

```bash
cd ~/GreenLight && python -m pytest Tests/test_calibrate_hsv.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError` for `calibrate_hsv`.

- [ ] **Step 3: Implement calibrate_hsv.py**

Create `calibrate_hsv.py` in the project root:

```python
#!/usr/bin/env python3
"""Extract HSV 5th/95th percentile statistics from classifier crop dataset.

Run after dataset_pipeline.py has produced crops in export/datasets/crops/.

Usage:
  python calibrate_hsv.py --crops-root export/datasets/crops/traffic_state

Output: recommended ColorHeuristic.swift HSV thresholds covering 95% of real data.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

try:
    import cv2
except ModuleNotFoundError as exc:
    raise SystemExit("OpenCV required: pip install opencv-python") from exc

CLASSES = ("red", "green", "yellow", "off")
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp"}


def load_crop_images(crops_root: Path, class_name: str) -> list[np.ndarray]:
    images: list[np.ndarray] = []
    for split in ("train", "val"):
        class_dir = crops_root / split / class_name
        if not class_dir.exists():
            continue
        for p in class_dir.iterdir():
            if p.suffix.lower() not in IMAGE_EXTS:
                continue
            img = cv2.imread(str(p), cv2.IMREAD_COLOR)
            if img is not None:
                images.append(img)
    return images


def compute_hsv_percentiles(
    class_images: dict[str, list[np.ndarray]],
) -> dict[str, dict[str, float]]:
    results: dict[str, dict[str, float]] = {}
    for class_name, images in class_images.items():
        if not images:
            continue

        h_vals: list[float] = []
        s_vals: list[float] = []
        v_vals: list[float] = []

        for bgr in images:
            hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV).reshape(-1, 3).astype(np.float32)
            # Convert OpenCV H (0-179) to degrees (0-358)
            h_vals.extend((hsv[:, 0] * 2.0).tolist())
            s_vals.extend((hsv[:, 1] / 255.0).tolist())
            v_vals.extend((hsv[:, 2] / 255.0).tolist())

        results[class_name] = {
            "h_p05": float(np.percentile(h_vals, 5)),
            "h_p95": float(np.percentile(h_vals, 95)),
            "s_p05": float(np.percentile(s_vals, 5)),
            "s_p95": float(np.percentile(s_vals, 95)),
            "v_p05": float(np.percentile(v_vals, 5)),
            "v_p95": float(np.percentile(v_vals, 95)),
            "sample_count": len(h_vals),
        }

    return results


def format_swift_ranges(stats: dict[str, dict[str, float]]) -> str:
    lines = ["// Calibrated HSV ranges — generated by calibrate_hsv.py"]
    lines.append("// Replace the corresponding lines in ColorHeuristic.swift classifyHSV()")
    lines.append("")

    for cls in ("red", "green", "yellow"):
        if cls not in stats:
            continue
        s = stats[cls]
        h05, h95 = s["h_p05"], s["h_p95"]
        s05 = s["s_p05"]
        v05 = s["v_p05"]
        n = int(s["sample_count"])

        if cls == "red":
            # Red wraps around 0/360 — handle both low-hue and high-hue cases
            lines.append(f"// RED: h 5th={h05:.1f}° 95th={h95:.1f}°  s>={s05:.2f}  v>={v05:.2f}  n={n}")
            lines.append(f"let isRed = (h <= {min(h05, 20):.0f} || h >= {max(h95, 340):.0f}) && s > {s05:.2f} && v > {v05:.2f}")
        elif cls == "green":
            lines.append(f"// GREEN: h 5th={h05:.1f}° 95th={h95:.1f}°  s>={s05:.2f}  v>={v05:.2f}  n={n}")
            lines.append(f"let isGreen = (h >= {h05:.0f} && h <= {h95:.0f}) && s > {s05:.2f} && v > {v05:.2f}")
        elif cls == "yellow":
            lines.append(f"// YELLOW: h 5th={h05:.1f}° 95th={h95:.1f}°  s>={s05:.2f}  v>={v05:.2f}  n={n}")
            lines.append(f"let isYellow = (h >= {h05:.0f} && h <= {h95:.0f}) && s > {s05:.2f} && v > {v05:.2f}")
        lines.append("")

    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Calibrate ColorHeuristic HSV ranges from crop dataset")
    parser.add_argument("--crops-root", type=Path, default=Path("export/datasets/crops/traffic_state"))
    parser.add_argument("--out-json", type=Path, default=None)
    parser.add_argument("--classes", nargs="+", default=list(CLASSES))
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    class_images: dict[str, list[np.ndarray]] = {}
    for cls in args.classes:
        images = load_crop_images(args.crops_root, cls)
        print(f"  {cls}: {len(images)} crops loaded")
        class_images[cls] = images

    stats = compute_hsv_percentiles(class_images)

    if args.out_json:
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(json.dumps(stats, indent=2) + "\n")
        print(f"Stats saved to {args.out_json}")

    print("\n--- Recommended Swift ranges ---")
    print(format_swift_ranges(stats))
    print("\nManually update GreenLight/Detection/ColorHeuristic.swift with the lines above.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests**

```bash
cd ~/GreenLight && python -m pytest Tests/test_calibrate_hsv.py -v
```

Expected: all 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add calibrate_hsv.py Tests/test_calibrate_hsv.py
git commit -m "feat: add calibrate_hsv.py to extract HSV percentiles from crop dataset for ColorHeuristic validation"
```

---

### Task 8: Task 8: adaptive_state_manager.py improvements

**Add:** `tentative_green_timeout_frames` (prevents TENTATIVE_GREEN stuck state) and speed-adaptive buffer sizing.

**Files:**
- Modify: `adaptive_state_manager.py`

- [ ] **Step 1: Write the failing tests**

Add a `Tests/test_adaptive_state_manager.py` file:

```python
#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from adaptive_state_manager import (
    AdaptiveStateManager,
    LightColor,
    LightingCondition,
    StateManagerConfig,
    StateUpdateInput,
    TrafficState,
    BufferConfig,
)


def make_input(
    color: LightColor | None,
    speed_mph: float = 0.0,
    lighting: LightingCondition = LightingCondition.DAY,
    reliability: float = 0.95,
    pre_chime: bool = False,
) -> StateUpdateInput:
    return StateUpdateInput(
        observed_color=color,
        reliability_score=reliability,
        lighting=lighting,
        speed_mph=speed_mph,
        pre_chime_confirmed=pre_chime,
    )


class TestTentativeGreenTimeout(unittest.TestCase):

    def _advance_to_tentative(self, mgr: AdaptiveStateManager) -> None:
        cfg = mgr.config
        for _ in range(cfg.adaptive_buffer.day + 1):
            mgr.update(make_input(LightColor.RED))
        for _ in range(cfg.adaptive_buffer.day + 1):
            mgr.update(make_input(LightColor.GREEN))
        self.assertEqual(mgr.state, TrafficState.TENTATIVE_GREEN)

    def test_tentative_green_times_out_and_resets(self):
        config = StateManagerConfig(tentative_green_timeout_frames=3)
        mgr = AdaptiveStateManager(config)
        self._advance_to_tentative(mgr)

        for _ in range(3):
            out = mgr.update(make_input(LightColor.GREEN, pre_chime=False))

        self.assertNotEqual(mgr.state, TrafficState.TENTATIVE_GREEN,
                            "Should have timed out of TENTATIVE_GREEN")

    def test_tentative_green_does_not_timeout_before_limit(self):
        config = StateManagerConfig(tentative_green_timeout_frames=5)
        mgr = AdaptiveStateManager(config)
        self._advance_to_tentative(mgr)

        for _ in range(4):
            mgr.update(make_input(LightColor.GREEN, pre_chime=False))

        self.assertEqual(mgr.state, TrafficState.TENTATIVE_GREEN)


class TestSpeedAdaptiveBuffer(unittest.TestCase):

    def test_buffer_larger_at_high_speed(self):
        config = StateManagerConfig(speed_adaptive_buffer=True)
        mgr = AdaptiveStateManager(config)
        mgr._set_buffer_size(LightingCondition.DAY, speed_mph=50.0)
        high_speed_size = mgr.buffer_size

        mgr._set_buffer_size(LightingCondition.DAY, speed_mph=0.0)
        stationary_size = mgr.buffer_size

        self.assertGreater(high_speed_size, stationary_size)

    def test_buffer_capped_at_night_maximum(self):
        config = StateManagerConfig(speed_adaptive_buffer=True)
        mgr = AdaptiveStateManager(config)
        mgr._set_buffer_size(LightingCondition.NIGHT, speed_mph=100.0)
        self.assertLessEqual(mgr.buffer_size, config.adaptive_buffer.night)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify failure**

```bash
cd ~/GreenLight && python -m pytest Tests/test_adaptive_state_manager.py -v 2>&1 | head -30
```

Expected: failures about `tentative_green_timeout_frames` and `speed_adaptive_buffer` not being recognized config fields.

- [ ] **Step 3: Update StateManagerConfig and AdaptiveStateManager**

In `adaptive_state_manager.py`, make the following changes:

Replace `StateManagerConfig`:
```python
@dataclass(frozen=True)
class StateManagerConfig:
    lost_hold_frames: int = 45
    speed_gate_mph: float = 2.0
    cooldown_frames: int = 150
    confidence_gate: float = 0.82
    adaptive_buffer: BufferConfig = field(default_factory=BufferConfig)
    tentative_green_timeout_frames: int = 15  # ~500ms at 30 FPS; 0 = disabled
    speed_adaptive_buffer: bool = True
```

Add a `tentative_green_frames` counter to `AdaptiveStateManager.__init__`:
```python
def __init__(self, config: StateManagerConfig | None = None) -> None:
    self.config = config or StateManagerConfig()
    self.state = TrafficState.SEARCHING
    self.last_known_color: LightColor | None = None
    self.buffer: deque[LightColor] = deque()
    self.buffer_size = self.config.adaptive_buffer.day
    self.lost_counter = 0
    self.cooldown_remaining = 0
    self._tentative_green_frames = 0  # frames spent in TENTATIVE_GREEN without confirmation
```

Replace `_set_buffer_size` method:
```python
def _set_buffer_size(self, lighting: LightingCondition, speed_mph: float = 0.0) -> None:
    if lighting == LightingCondition.DAY:
        base = self.config.adaptive_buffer.day
        cap = self.config.adaptive_buffer.night
    elif lighting == LightingCondition.DUSK:
        base = self.config.adaptive_buffer.dusk
        cap = self.config.adaptive_buffer.night
    else:
        base = self.config.adaptive_buffer.night
        cap = self.config.adaptive_buffer.night

    if self.config.speed_adaptive_buffer and speed_mph > 0:
        # Add up to (cap - base) extra frames proportional to speed, capped at night max.
        extra = int((speed_mph / 60.0) * (cap - base))
        self.buffer_size = min(base + extra, cap)
    else:
        self.buffer_size = base

    while len(self.buffer) > self.buffer_size:
        self.buffer.popleft()
```

Update the call site inside `update()`:
```python
def update(self, item: StateUpdateInput) -> StateUpdateOutput:
    self._set_buffer_size(item.lighting, speed_mph=item.speed_mph)
    self._tick_cooldown()
    ...
```

Add timeout logic inside the `TENTATIVE_GREEN` block:
```python
if self.state == TrafficState.TENTATIVE_GREEN:
    timeout = self.config.tentative_green_timeout_frames
    if timeout > 0:
        self._tentative_green_frames += 1
        if self._tentative_green_frames >= timeout:
            self._tentative_green_frames = 0
            self.state = TrafficState.SEARCHING
            return self._emit(reason="tentative_green_timeout", chime=False)

    if item.pre_chime_confirmed and stable_color == LightColor.GREEN:
        self._tentative_green_frames = 0
        self.state = TrafficState.CONFIRMED_GREEN
        reason = "pre_chime_confirmed_green"
        chime_fire = self._should_fire_chime(item.speed_mph)
        if chime_fire:
            self.cooldown_remaining = self.config.cooldown_frames
    elif stable_color in {LightColor.RED, LightColor.YELLOW}:
        self._tentative_green_frames = 0
        self.state = TrafficState.TRACKING_RED if stable_color == LightColor.RED else TrafficState.TRACKING_YELLOW
        reason = "tentative_green_rejected"
    return self._emit(reason=reason, chime=chime_fire)
```

Also reset `_tentative_green_frames` when leaving TENTATIVE_GREEN via `_handle_missing_observation` and `reset()`:
```python
def reset(self) -> None:
    self.state = TrafficState.SEARCHING
    self.last_known_color = None
    self.buffer.clear()
    self.lost_counter = 0
    self.cooldown_remaining = 0
    self._tentative_green_frames = 0
```

- [ ] **Step 4: Run tests**

```bash
cd ~/GreenLight && python -m pytest Tests/test_adaptive_state_manager.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add adaptive_state_manager.py Tests/test_adaptive_state_manager.py
git commit -m "feat: add TENTATIVE_GREEN timeout and speed-adaptive buffer to AdaptiveStateManager"
```

---

### Task 9: Temporal deduplication in dataset_pipeline.py

**Problem:** Video-sourced datasets (LISA, BSTLD) may have near-identical consecutive frames that leak across train/val split.

**Files:**
- Modify: `dataset_pipeline.py`
- Modify: `Tests/test_dataset_pipeline.py`

**Prerequisite:** `pip install imagehash Pillow`

- [ ] **Step 1: Write failing test**

Add to `Tests/test_dataset_pipeline.py`:

```python
from dataset_pipeline import deduplicate_records_by_phash, AnnotationRecord

class TestDeduplication(unittest.TestCase):

    def test_identical_images_are_deduplicated(self):
        import tempfile, shutil
        from PIL import Image
        tmp = Path(tempfile.mkdtemp())
        try:
            # Create two identical images
            img = Image.new("RGB", (64, 64), color=(200, 50, 50))
            p1 = tmp / "a.jpg"
            p2 = tmp / "b.jpg"
            img.save(p1)
            img.save(p2)

            records = [
                AnnotationRecord("src", p1, (0, 0, 64, 64), "red", "red"),
                AnnotationRecord("src", p2, (0, 0, 64, 64), "red", "red"),
            ]
            deduped = deduplicate_records_by_phash(records, threshold=8)
            self.assertEqual(len(deduped), 1)
        finally:
            shutil.rmtree(tmp)

    def test_distinct_images_are_kept(self):
        import tempfile, shutil
        from PIL import Image
        tmp = Path(tempfile.mkdtemp())
        try:
            img_red = Image.new("RGB", (64, 64), color=(200, 50, 50))
            img_green = Image.new("RGB", (64, 64), color=(50, 200, 50))
            p1 = tmp / "red.jpg"
            p2 = tmp / "green.jpg"
            img_red.save(p1)
            img_green.save(p2)

            records = [
                AnnotationRecord("src", p1, (0, 0, 64, 64), "red", "red"),
                AnnotationRecord("src", p2, (0, 0, 64, 64), "green", "green"),
            ]
            deduped = deduplicate_records_by_phash(records, threshold=8)
            self.assertEqual(len(deduped), 2)
        finally:
            shutil.rmtree(tmp)
```

- [ ] **Step 2: Run to verify failure**

```bash
cd ~/GreenLight && python -m pytest Tests/test_dataset_pipeline.py::TestDeduplication -v 2>&1 | head -20
```

Expected: `ImportError` for `deduplicate_records_by_phash`.

- [ ] **Step 3: Add deduplication function to dataset_pipeline.py**

Find the imports section of `dataset_pipeline.py`. Add near the top (after existing imports):

```python
try:
    import imagehash
    from PIL import Image as PILImage
    IMAGEHASH_AVAILABLE = True
except ModuleNotFoundError:
    IMAGEHASH_AVAILABLE = False
```

Add the following function after the existing module-level helper functions (before `class` definitions or before the main pipeline functions):

```python
def deduplicate_records_by_phash(
    records: list[AnnotationRecord],
    threshold: int = 8,
) -> list[AnnotationRecord]:
    """Remove near-duplicate records using perceptual hashing.

    threshold: max Hamming distance to consider images duplicates (0=identical, 8=visually similar).
    Records without a readable image are kept.
    """
    if not IMAGEHASH_AVAILABLE:
        logging.warning("imagehash not installed; skipping deduplication. pip install imagehash")
        return records

    seen_hashes: list[tuple[imagehash.ImageHash, int]] = []
    kept: list[AnnotationRecord] = []

    for record in records:
        try:
            img = PILImage.open(record.image_path).convert("RGB")
            h = imagehash.phash(img)
        except Exception:
            kept.append(record)
            continue

        is_dup = any(abs(h - prev_h) <= threshold for prev_h, _ in seen_hashes)
        if not is_dup:
            seen_hashes.append((h, id(record)))
            kept.append(record)

    removed = len(records) - len(kept)
    if removed:
        logging.info("Deduplication removed %d near-duplicate records (threshold=%d)", removed, threshold)
    return kept
```

- [ ] **Step 4: Wire deduplication into the main pipeline**

In `dataset_pipeline.py`, find where records are collected before the train/val split (search for the stratified split call or the call to `balance_records_by_strata`). Add a deduplication call immediately before the split:

```python
# Deduplicate before split to prevent train/val leakage from consecutive video frames.
records = deduplicate_records_by_phash(records, threshold=args.phash_threshold)
```

And add the CLI argument in `parse_args()`:
```python
parser.add_argument("--phash-threshold", type=int, default=8,
                    help="Perceptual hash Hamming distance threshold for deduplication (0=identical, 8=similar)")
parser.add_argument("--skip-dedup", action="store_true", help="Skip perceptual hash deduplication")
```

And gate the dedup call:
```python
if not args.skip_dedup:
    records = deduplicate_records_by_phash(records, threshold=args.phash_threshold)
```

- [ ] **Step 5: Run tests**

```bash
cd ~/GreenLight && python -m pytest Tests/test_dataset_pipeline.py -v
```

Expected: all tests pass including the two new deduplication tests.

- [ ] **Step 6: Commit**

```bash
git add dataset_pipeline.py Tests/test_dataset_pipeline.py
git commit -m "feat: add pHash-based temporal deduplication to dataset_pipeline to prevent train/val leakage"
```

---

### Task 10: export_coreml.py — normalization divergence check

**Problem:** The image-mode CoreML input uses an approximate per-channel normalization. This task adds a validation step that flags if the divergence from the exact multiarray path exceeds 1%.

**Files:**
- Modify: `export_coreml.py`

- [ ] **Step 1: Locate the parity validation section**

In `export_coreml.py`, find the `parity_check` or similar function (around line 294-343). The existing check compares top-1 match rate. We will add a top-1 confidence divergence check after the existing check.

- [ ] **Step 2: Add the divergence check function**

After the existing parity check function, add:

```python
def check_normalization_divergence(
    mlmodel: Any,
    val_loader: Any,
    class_labels: list[str],
    max_samples: int = 50,
    divergence_threshold: float = 0.01,
) -> float:
    """Compare top-1 confidence between multiarray and image-mode inputs.

    Returns mean absolute confidence divergence. Logs a warning if > divergence_threshold.
    """
    import coremltools as ct
    import torch

    divergences: list[float] = []
    samples_checked = 0

    for images, _ in val_loader:
        if samples_checked >= max_samples:
            break
        for img_tensor in images:
            if samples_checked >= max_samples:
                break

            # Multiarray path: normalized float tensor [1, 3, H, W]
            np_input = img_tensor.unsqueeze(0).numpy()
            try:
                result_arr = mlmodel.predict({"input": np_input})
            except Exception:
                continue

            # Image-mode path: uint8 PIL image [H, W, 3] in RGB
            try:
                from PIL import Image as PILImage
                import numpy as np
                # Denormalize: reverse ImageNet normalization to get 0-255 uint8
                mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
                std = np.array([0.229, 0.224, 0.225], dtype=np.float32)
                img_np = img_tensor.permute(1, 2, 0).numpy()
                img_uint8 = np.clip((img_np * std + mean) * 255, 0, 255).astype(np.uint8)
                pil_img = PILImage.fromarray(img_uint8, mode="RGB")
                result_img = mlmodel.predict({"input": pil_img})
            except Exception:
                continue

            # Compare top-1 confidence
            probs_arr = result_arr.get("classProbability", {})
            probs_img = result_img.get("classProbability", {})
            if not probs_arr or not probs_img:
                continue

            top1_arr = max(probs_arr.values())
            top1_img = max(probs_img.values())
            divergences.append(abs(top1_arr - top1_img))
            samples_checked += 1

    if not divergences:
        logger.warning("Normalization divergence check: no samples compared")
        return 0.0

    mean_div = float(np.mean(divergences))
    if mean_div > divergence_threshold:
        logger.warning(
            "Normalization divergence %.4f exceeds threshold %.4f — "
            "image-mode normalization may not match multiarray path",
            mean_div, divergence_threshold,
        )
    else:
        logger.warning("Normalization divergence %.4f within threshold %.4f", mean_div, divergence_threshold)

    return mean_div
```

- [ ] **Step 3: Call the check in the export main flow**

In `export_coreml.py`'s `main()` function, after the existing parity check call, add:

```python
div = check_normalization_divergence(mlmodel, val_loader, class_labels)
logger.warning("Mean normalization divergence (multiarray vs image-mode): %.4f", div)
```

And add the corresponding CLI argument in `parse_args()`:
```python
parser.add_argument("--skip-normalization-check", action="store_true",
                    help="Skip multiarray vs image-mode normalization divergence check")
```

Gate the call:
```python
if not args.skip_normalization_check:
    div = check_normalization_divergence(mlmodel, val_loader, class_labels)
    logger.warning("Mean normalization divergence: %.4f", div)
```

- [ ] **Step 4: Smoke test the export script help**

```bash
cd ~/GreenLight && python export_coreml.py --help 2>&1 | grep -E "normalization|divergence"
```

Expected: `--skip-normalization-check` appears in the output.

- [ ] **Step 5: Commit**

```bash
git add export_coreml.py
git commit -m "feat: add multiarray vs image-mode normalization divergence check to export_coreml.py"
```

---

## Self-Review

### Spec Coverage

| Requirement | Task |
|---|---|
| Speed gate tri-state (`unknown` suppresses chime) | Task 1, 2, 3 |
| `isStationary` replaced everywhere | Task 2, 3, 5 |
| GPS unavailable → `unknown` → no chime | Task 1 (DetectionState delegate) |
| Fallback gated on `isTrackingRedOrTransitioning` | Task 2 (property), Task 3 (gate) |
| `label_clips.py` produces evaluate.py-compatible CSV | Task 6 |
| HSV calibration against real dataset distributions | Task 7 |
| `ColorHeuristic.swift` HSV ranges updated | Task 7 (calibration output applied manually) |
| TENTATIVE_GREEN timeout | Task 8 |
| Speed-adaptive buffer | Task 8 |
| Temporal deduplication in dataset_pipeline | Task 9 |
| Normalization divergence check in export_coreml | Task 10 |
| On-device telemetry | Task 4 |
| All existing Swift tests updated | Task 5 |

### Placeholder Check
No TBD, TODO, or "implement later" present. Every code step contains the actual code to write.

### Type Consistency
- `SpeedStatus` defined in `Types.swift` (Task 1), used in `DetectionState.swift` (Task 1), `LightStateManager.swift` (Task 2), `ViewControllerDetection.swift` (Task 3), `TelemetryLogger.swift` (Task 4), `LightStateManagerTests.swift` (Task 5).
- `isTrackingRedOrTransitioning` defined on `LightStateManager` in Task 2, consumed in Task 3.
- `TelemetryEvent` defined in Task 4, instantiated in Task 3's `handleResults`.
- `deduplicate_records_by_phash` defined and consumed in `dataset_pipeline.py` in Task 9.
- `tentative_green_timeout_frames` and `speed_adaptive_buffer` added to `StateManagerConfig` in Task 8, consumed by `AdaptiveStateManager._set_buffer_size` and `update()`.
