# GreenLight CarPlay Integration — Plan B

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a CarPlay screen to GreenLight that shows the current light state, speed, and lets the driver mute the chime or change sensitivity without touching the phone.

**Architecture:** A `CPTemplateApplicationScene` runs alongside the existing `UIWindowScene`. Both scenes share `DetectionState.shared` (built in Plan A). `CarPlaySceneDelegate` observes `DetectionState` via Combine and pushes updates to a `CPInformationTemplate`. Pure display-string logic lives in `CarPlayTemplateBuilder` (stateless struct, fully unit-testable without CarPlay hardware). The phone always runs inference — CarPlay is display-only.

**Tech Stack:** Swift 5.9+, iOS 16+, CarPlay framework, Combine, XCTest

**Prerequisite:** Plan A complete. Apple "Driving Task" entitlement approved and provisioning profile updated.

> **Entitlement request:** Submit at [developer.apple.com/contact/request/carplay](https://developer.apple.com/contact/request/carplay) — select "Driving Task App". Typical approval: 1–5 business days. You can develop and test in the Xcode CarPlay simulator **without** the entitlement. You need it only for physical vehicle head units and App Store submission.

---

## File Map

**New files:**
- `GreenLight/GreenLight.entitlements` — CarPlay driving task entitlement
- `GreenLight/CarPlay/CarPlayTemplateBuilder.swift` — pure functions: items, button titles, sensitivity cycling
- `GreenLight/CarPlay/CarPlaySceneDelegate.swift` — `CPTemplateApplicationSceneDelegate`, owns the `CPInformationTemplate`, observes `DetectionState`
- `GreenLightTests/CarPlayTemplateBuilderTests.swift` — unit tests for all pure logic

**Modified files:**
- `GreenLight/Info.plist` — add `CPTemplateApplicationSceneSessionRoleApplication` scene config entry
- `GreenLight/AppDelegate.swift` — route CarPlay scene sessions to `CarPlaySceneDelegate`

> **Every new `.swift` file** must be added to the `GreenLight` target in Xcode. Test files go in `GreenLightTests`.

---

## Task 1: Entitlements file + Xcode project wiring

**Files:**
- Create: `GreenLight/GreenLight.entitlements`

CarPlay requires the `com.apple.developer.carplay-driving-task` entitlement. Create the file now so it's wired up before any CarPlay code runs.

- [ ] **Step 1: Create GreenLight.entitlements**

Create `GreenLight/GreenLight.entitlements`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>com.apple.developer.carplay-driving-task</key>
    <true/>
</dict>
</plist>
```

- [ ] **Step 2: Set the entitlements file in Xcode**

1. Select the `GreenLight` project in the navigator
2. Select the `GreenLight` target
3. Go to **Build Settings** → search for "Code Signing Entitlements"
4. Set the value to `GreenLight/GreenLight.entitlements`

- [ ] **Step 3: Verify build still succeeds**

Product → Build (⌘B). Should compile cleanly. The entitlement has no runtime effect until CarPlay code is added.

- [ ] **Step 4: Commit**

```bash
git add GreenLight/GreenLight.entitlements
git commit -m "chore: add CarPlay driving task entitlement file"
```

---

## Task 2: Info.plist CarPlay scene configuration

**Files:**
- Modify: `GreenLight/Info.plist`

Registers the CarPlay scene with UIKit so the system knows which delegate class to instantiate when a CarPlay head unit connects.

- [ ] **Step 1: Add CarPlay scene to UIApplicationSceneManifest**

Open `GreenLight/Info.plist`. Locate the existing `UISceneConfigurations` dictionary (added in Plan A, Task 10). It currently looks like:

```xml
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
```

Add the CarPlay entry so it becomes:

```xml
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
    <key>CPTemplateApplicationSceneSessionRoleApplication</key>
    <array>
        <dict>
            <key>UISceneConfigurationName</key>
            <string>CarPlay Configuration</string>
            <key>UISceneDelegateClassName</key>
            <string>$(PRODUCT_MODULE_NAME).CarPlaySceneDelegate</string>
        </dict>
    </array>
</dict>
```

- [ ] **Step 2: Build and verify**

Product → Build (⌘B). No errors expected — the delegate class `CarPlaySceneDelegate` doesn't need to exist yet for the plist to be valid.

- [ ] **Step 3: Commit**

```bash
git add GreenLight/Info.plist
git commit -m "feat: register CarPlay scene configuration in Info.plist"
```

---

## Task 3: CarPlayTemplateBuilder — pure display logic (TDD)

**Files:**
- Create: `GreenLight/CarPlay/CarPlayTemplateBuilder.swift`
- Create: `GreenLightTests/CarPlayTemplateBuilderTests.swift`

All string formatting and state→display mapping lives here. These are pure functions with no CarPlay framework dependency, so they are fully unit-testable without a CarPlay session or device.

- [ ] **Step 1: Write the failing tests**

Create `GreenLightTests/CarPlayTemplateBuilderTests.swift` and add to the `GreenLightTests` target:

```swift
import XCTest
@testable import GreenLight

final class CarPlayTemplateBuilderTests: XCTestCase {

    // MARK: - Status strings

    func testStatusStringRed() {
        XCTAssertEqual(CarPlayTemplateBuilder.statusString(for: .red), "Red light ahead")
    }

    func testStatusStringGreen() {
        XCTAssertEqual(CarPlayTemplateBuilder.statusString(for: .green), "Green — go!")
    }

    func testStatusStringYellow() {
        XCTAssertEqual(CarPlayTemplateBuilder.statusString(for: .yellow), "Yellow light")
    }

    func testStatusStringUnknown() {
        XCTAssertEqual(CarPlayTemplateBuilder.statusString(for: .unknown), "Watching...")
    }

    func testStatusStringNone() {
        XCTAssertEqual(CarPlayTemplateBuilder.statusString(for: .none), "Watching...")
    }

    // MARK: - Items

    func testMakeItemsReturnsTwoItems() {
        let items = CarPlayTemplateBuilder.makeItems(
            lightColor: .red,
            speed: 0,
            speedUnit: "MPH"
        )
        XCTAssertEqual(items.count, 2)
    }

    func testMakeItemsStatusTitle() {
        let items = CarPlayTemplateBuilder.makeItems(lightColor: .green, speed: 0, speedUnit: "MPH")
        XCTAssertEqual(items[0].title, "Status")
        XCTAssertEqual(items[0].detail, "Green — go!")
    }

    func testMakeItemsSpeedRoundsDown() {
        let items = CarPlayTemplateBuilder.makeItems(lightColor: .unknown, speed: 32.9, speedUnit: "MPH")
        XCTAssertEqual(items[1].title, "Speed")
        XCTAssertEqual(items[1].detail, "32 MPH")
    }

    func testMakeItemsSpeedWithMetricUnit() {
        let items = CarPlayTemplateBuilder.makeItems(lightColor: .unknown, speed: 50.0, speedUnit: "km/h")
        XCTAssertEqual(items[1].detail, "50 km/h")
    }

    func testMakeItemsSpeedZero() {
        let items = CarPlayTemplateBuilder.makeItems(lightColor: .unknown, speed: 0.0, speedUnit: "MPH")
        XCTAssertEqual(items[1].detail, "0 MPH")
    }

    // MARK: - Button titles

    func testMuteButtonTitleWhenChimeEnabled() {
        XCTAssertEqual(CarPlayTemplateBuilder.muteButtonTitle(isChimeEnabled: true), "Mute Chime")
    }

    func testMuteButtonTitleWhenChimeMuted() {
        XCTAssertEqual(CarPlayTemplateBuilder.muteButtonTitle(isChimeEnabled: false), "Unmute Chime")
    }

    func testSensitivityButtonTitleLow() {
        XCTAssertEqual(
            CarPlayTemplateBuilder.sensitivityButtonTitle(for: .low),
            "Sensitivity: Low"
        )
    }

    func testSensitivityButtonTitleMedium() {
        XCTAssertEqual(
            CarPlayTemplateBuilder.sensitivityButtonTitle(for: .medium),
            "Sensitivity: Medium"
        )
    }

    func testSensitivityButtonTitleHigh() {
        XCTAssertEqual(
            CarPlayTemplateBuilder.sensitivityButtonTitle(for: .high),
            "Sensitivity: High"
        )
    }

    // MARK: - Sensitivity cycling

    func testNextSensitivityLowToMedium() {
        XCTAssertEqual(CarPlayTemplateBuilder.nextSensitivity(after: .low), .medium)
    }

    func testNextSensitivityMediumToHigh() {
        XCTAssertEqual(CarPlayTemplateBuilder.nextSensitivity(after: .medium), .high)
    }

    func testNextSensitivityHighWrapsToLow() {
        XCTAssertEqual(CarPlayTemplateBuilder.nextSensitivity(after: .high), .low)
    }
}
```

- [ ] **Step 2: Run tests to verify they fail**

Product → Test (⌘U). `CarPlayTemplateBuilderTests` should fail with a compile error — `CarPlayTemplateBuilder` does not exist yet.

- [ ] **Step 3: Implement CarPlayTemplateBuilder**

Create `GreenLight/CarPlay/CarPlayTemplateBuilder.swift` and add to the `GreenLight` target:

```swift
import CarPlay

struct CarPlayTemplateBuilder {

    // MARK: - Status string

    static func statusString(for color: DetectedLightColor) -> String {
        switch color {
        case .red:            return "Red light ahead"
        case .green:          return "Green — go!"
        case .yellow:         return "Yellow light"
        case .unknown, .none: return "Watching..."
        }
    }

    // MARK: - CPInformationItems

    static func makeItems(
        lightColor: DetectedLightColor,
        speed: Double,
        speedUnit: String
    ) -> [CPInformationItem] {
        [
            CPInformationItem(title: "Status", detail: statusString(for: lightColor)),
            CPInformationItem(title: "Speed",  detail: "\(Int(speed)) \(speedUnit)"),
        ]
    }

    // MARK: - Button titles

    static func muteButtonTitle(isChimeEnabled: Bool) -> String {
        isChimeEnabled ? "Mute Chime" : "Unmute Chime"
    }

    static func sensitivityButtonTitle(for sensitivity: ConfidenceSensitivity) -> String {
        "Sensitivity: \(sensitivity.rawValue)"
    }

    // MARK: - Sensitivity cycling

    static func nextSensitivity(after current: ConfidenceSensitivity) -> ConfidenceSensitivity {
        let all = ConfidenceSensitivity.allCases
        guard let idx = all.firstIndex(of: current) else { return .medium }
        return all[(idx + 1) % all.count]
    }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Product → Test (⌘U). All `CarPlayTemplateBuilderTests` should pass.

- [ ] **Step 5: Commit**

```bash
git add GreenLight/CarPlay/CarPlayTemplateBuilder.swift \
        GreenLightTests/CarPlayTemplateBuilderTests.swift
git commit -m "feat: add CarPlayTemplateBuilder with full test coverage"
```

---

## Task 4: CarPlaySceneDelegate

**Files:**
- Create: `GreenLight/CarPlay/CarPlaySceneDelegate.swift`

Owns the `CPInterfaceController` and `CPInformationTemplate`. Observes `DetectionState.shared` via Combine and refreshes the template on every state change. Uses `.debounce` to avoid 15fps template hammering.

- [ ] **Step 1: Create CarPlaySceneDelegate.swift**

Create `GreenLight/CarPlay/CarPlaySceneDelegate.swift` and add to the `GreenLight` target:

```swift
import CarPlay
import Combine

final class CarPlaySceneDelegate: UIResponder, CPTemplateApplicationSceneDelegate {

    private var interfaceController: CPInterfaceController?
    private var infoTemplate: CPInformationTemplate?
    private var cancellables = Set<AnyCancellable>()

    // MARK: - CPTemplateApplicationSceneDelegate

    func templateApplicationScene(
        _ templateApplicationScene: CPTemplateApplicationScene,
        didConnect interfaceController: CPInterfaceController
    ) {
        self.interfaceController = interfaceController
        let template = buildTemplate()
        infoTemplate = template
        interfaceController.setRootTemplate(template, animated: false, completion: nil)
        subscribeToStateChanges()
    }

    func templateApplicationScene(
        _ templateApplicationScene: CPTemplateApplicationScene,
        didDisconnectInterfaceController interfaceController: CPInterfaceController
    ) {
        cancellables.removeAll()
        self.interfaceController = nil
        infoTemplate = nil
    }

    // MARK: - Template construction

    private func buildTemplate() -> CPInformationTemplate {
        CPInformationTemplate(
            title: "GreenLight",
            layout: .leading,
            items: makeItems(),
            actions: makeActions()
        )
    }

    private func makeItems() -> [CPInformationItem] {
        let state = DetectionState.shared
        return CarPlayTemplateBuilder.makeItems(
            lightColor: state.lightColor,
            speed: state.speed,
            speedUnit: state.speedUnit
        )
    }

    private func makeActions() -> [CPTextButton] {
        let state = DetectionState.shared

        let muteButton = CPTextButton(
            title: CarPlayTemplateBuilder.muteButtonTitle(isChimeEnabled: state.isChimeEnabled),
            textStyle: state.isChimeEnabled ? .normal : .cancel
        ) { [weak self] _ in
            Task { @MainActor in
                DetectionState.shared.isChimeEnabled.toggle()
                self?.refreshTemplate()
            }
        }

        let sensitivityButton = CPTextButton(
            title: CarPlayTemplateBuilder.sensitivityButtonTitle(for: state.sensitivity),
            textStyle: .normal
        ) { [weak self] _ in
            Task { @MainActor in
                DetectionState.shared.sensitivity = CarPlayTemplateBuilder.nextSensitivity(
                    after: DetectionState.shared.sensitivity
                )
                self?.refreshTemplate()
            }
        }

        return [muteButton, sensitivityButton]
    }

    // MARK: - Live updates

    private func subscribeToStateChanges() {
        DetectionState.shared.objectWillChange
            .receive(on: DispatchQueue.main)
            // Debounce: DetectionState fires at inference rate (15fps). 
            // CarPlay templates don't need sub-second refresh.
            .debounce(for: .milliseconds(200), scheduler: DispatchQueue.main)
            .sink { [weak self] _ in
                self?.refreshTemplate()
            }
            .store(in: &cancellables)
    }

    @MainActor
    private func refreshTemplate() {
        guard let template = infoTemplate else { return }
        template.updateItems(makeItems())
        template.updateActions(makeActions())
    }
}
```

- [ ] **Step 2: Build and verify**

Product → Build (⌘B). Should compile cleanly.

- [ ] **Step 3: Commit**

```bash
git add GreenLight/CarPlay/CarPlaySceneDelegate.swift
git commit -m "feat: add CarPlaySceneDelegate with live DetectionState observation"
```

---

## Task 5: AppDelegate — route CarPlay sessions

**Files:**
- Modify: `GreenLight/AppDelegate.swift`

The `application(_:configurationForConnecting:options:)` method currently returns the default phone configuration for all sessions. It needs to return the CarPlay configuration when the session role is `carTemplateApplication`.

- [ ] **Step 1: Update AppDelegate.swift**

Replace the `configurationForConnecting` method in `GreenLight/AppDelegate.swift`:

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

    // MARK: - Scene routing

    func application(
        _ application: UIApplication,
        configurationForConnecting connectingSceneSession: UISceneSession,
        options: UIScene.ConnectionOptions
    ) -> UISceneConfiguration {
        switch connectingSceneSession.role {
        case UISceneSession.Role.carTemplateApplication:
            return UISceneConfiguration(
                name: "CarPlay Configuration",
                sessionRole: connectingSceneSession.role
            )
        default:
            return UISceneConfiguration(
                name: "Default Configuration",
                sessionRole: connectingSceneSession.role
            )
        }
    }

    // MARK: - Audio session

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

- [ ] **Step 2: Build and verify**

Product → Build (⌘B). No errors expected.

- [ ] **Step 3: Commit**

```bash
git add GreenLight/AppDelegate.swift
git commit -m "feat: route CarPlay scene sessions to CarPlaySceneDelegate"
```

---

## Task 6: Test in the CarPlay Simulator

No code changes. Verification only.

> You do **not** need the Apple entitlement to test in the Xcode simulator. The CarPlay simulator works in development builds.

- [ ] **Step 1: Open the CarPlay simulator window**

1. Build and run the app in the **iPhone simulator** (⌘R)
2. In the menu bar: **I/O → External Displays → CarPlay**

A second simulator window opens showing the CarPlay screen.

- [ ] **Step 2: Verify initial state**

The CarPlay screen should show:
```
GreenLight

Status    Watching...
Speed     0 MPH

[Mute Chime]    [Sensitivity: Medium]
```

- [ ] **Step 3: Verify mute toggle**

Tap "Mute Chime" on the CarPlay screen. The button title should change to "Unmute Chime". Open the Settings screen on the phone simulator — "Enable chime" toggle should be OFF (state is shared).

Tap "Unmute Chime" — toggle should go back to ON.

- [ ] **Step 4: Verify sensitivity cycling**

Tap "Sensitivity: Medium" → title changes to "Sensitivity: High"
Tap again → "Sensitivity: Low"
Tap again → "Sensitivity: Medium" (wraps around)

Open Settings on the phone — the sensitivity picker should reflect the current CarPlay selection.

- [ ] **Step 5: Verify speed updates**

Speed display is "0 MPH" in the simulator (no GPS). On a real device with GPS, the speed should update in real time as the vehicle moves. Note this for device testing.

- [ ] **Step 6: Commit verification note**

```bash
git commit --allow-empty -m "test: CarPlay simulator verified — state sharing, mute toggle, sensitivity cycling"
```

---

## Self-Review

**Spec coverage check:**

| Requirement | Task |
|---|---|
| `CPTemplateApplicationScene` setup | Task 2 (Info.plist) + Task 4 (SceneDelegate) |
| CarPlay UI: status display | Task 3 (makeItems) + Task 4 (template) |
| CarPlay UI: speed display | Task 3 (makeItems) + Task 4 (template) |
| CarPlay UI: mute toggle | Task 3 (muteButtonTitle) + Task 4 (CPTextButton) |
| CarPlay UI: sensitivity setting | Task 3 (sensitivityButtonTitle, nextSensitivity) + Task 4 |
| State sharing phone ↔ CarPlay | Task 4 (DetectionState.shared) |
| Entitlement (`carplay-driving-task`) | Task 1 |
| Info.plist scene manifest | Task 2 |
| AppDelegate scene routing | Task 5 |
| Simulator testing instructions | Task 6 |
| Unit tests for display logic | Task 3 (CarPlayTemplateBuilderTests) |
| Live updates from inference pipeline | Task 4 (subscribeToStateChanges + debounce) |

**No placeholders found.** All code blocks complete. Type names (`DetectedLightColor`, `DetectionState`, `ConfidenceSensitivity`) match Plan A definitions exactly.

**One user action required:** Request the Apple Driving Task entitlement before submitting to the App Store. Development and simulator testing work without it.
