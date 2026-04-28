# GreenLight Architecture Redesign

**Goal:** Rebuild GreenLight to professional iOS 26 standards — feature-first MVVM, actor-based services, full SwiftUI, Liquid Glass design language, and correct Swift 6.2 concurrency throughout.

---

## iOS 26 / Swift 6.2 Features Used

| Feature | Where |
|---|---|
| `glassEffect()` | All HUD panels, banners, pills, settings sheet — primary design material |
| `@Animatable` macro | `TrafficLightIndicator` Shape — animates between light states |
| Swift 6.2 main actor by default | All `@Observable` ViewModels, `AppEnvironment` |
| `@concurrent` | `DetectionEngine.runInference()` — keeps Vision/CoreML off main actor |
| Intuitive `nonisolated async` | Service actors — async functions run in caller's context |
| `WebView(url:)` | Settings "How detection works" — replaces `UIViewRepresentable` wrapper |
| `LensSmudgeDetectionRequest` | `DetectionEngine` — surfaces HUD warning when lens is dirty |

---

## Folder Structure

Feature-first organisation. No `ViewControllers/`, `Models/`, `Views/` type-buckets.

```
GreenLight/
├── App/
│   ├── GreenLightApp.swift          # @main, builds AppEnvironment, NavigationStack root
│   └── AppEnvironment.swift         # DI container — constructs and holds all services
│
├── Features/
│   ├── Camera/
│   │   ├── CameraView.swift         # Full-bleed camera + floating glass HUD
│   │   └── CameraViewModel.swift    # @Observable, @MainActor
│   ├── Settings/
│   │   └── SettingsView.swift       # .sheet() presentation, no separate VM
│   └── Onboarding/
│       └── OnboardingView.swift     # First-launch permissions + safety disclaimer
│
├── Services/
│   ├── CameraService.swift          # actor — owns AVCaptureSession
│   ├── DetectionEngine.swift        # actor — owns Vision + CoreML + LensSmudge
│   ├── LocationService.swift        # actor — owns CLLocationManager
│   ├── AudioService.swift           # actor — owns AVAudioSession + AVAudioPlayer
│   └── TelemetryService.swift       # actor — owns JSONL file handles
│
├── Domain/
│   ├── Types.swift                  # DetectedLightColor, SpeedStatus, DisplayLightState
│   ├── DetectionResult.swift        # Output type from DetectionEngine
│   ├── LightStateManager.swift      # Pure state machine, no I/O
│   └── LightTransitionFallbackState.swift
│
└── UI/
    ├── CameraPreview.swift          # UIViewRepresentable — only UIKit in the app
    ├── TrafficLightIndicator.swift  # @Animatable Shape
    ├── GlassCard.swift              # Reusable glassEffect() container view
    └── Theme.swift                  # Colours, typography, spacing constants
```

**Three enforced rules:**
1. Features only talk to Services through protocols — never to concrete actor types
2. Domain has zero imports of UIKit, SwiftUI, AVFoundation, or Vision
3. Services never import SwiftUI — they communicate via `AsyncStream`

---

## Service Layer

Every service is a Swift actor behind a `Sendable` protocol. Real implementations are used in production; mock implementations are used in tests and SwiftUI previews.

### Protocols

```swift
protocol CameraServiceProtocol: Sendable {
    var frames: AsyncStream<CVPixelBuffer> { get }
    func start() async
    func stop() async
}

protocol DetectionEngineProtocol: Sendable {
    var results: AsyncStream<DetectionResult> { get }
}

protocol LocationServiceProtocol: Sendable {
    var readings: AsyncStream<SpeedReading> { get }
}

protocol AudioServiceProtocol: Sendable {
    var isMuted: Bool { get set }
    func play()
}

protocol TelemetryServiceProtocol: Sendable {
    func log(_ result: DetectionResult, speedStatus: SpeedStatus)
}
```

### Service responsibilities

**`CameraService`**
- Owns `AVCaptureSession` at `.hd1280x720`
- Locks frame rate to 15 FPS via `activeVideoMinFrameDuration`
- Publishes raw `CVPixelBuffer` frames via `AsyncStream`
- Calls `session.startRunning()` off the main thread

**`DetectionEngine`**
- Consumes frames from `CameraService`
- Resolves ML model URL from bundle (yolo26nTraffic → yolo11nTraffic → yolov8nTraffic fallback chain)
- Runs `VNCoreMLRequest` marked `@concurrent` — never blocks main actor
- Runs `VNDetectLensSmudgeRequest` on the same handler pass
- Applies `GeometryFilter` and `ColorHeuristic` / `TrafficLightStateClassifier` for label resolution
- Publishes `DetectionResult` via `AsyncStream`

**`LocationService`**
- Wraps `CLLocationManager` callbacks into `AsyncStream<SpeedReading>` via `AsyncStream.Continuation`
- Sets `gpsActive = false` on permission denial or error
- Published `SpeedReading` includes raw m/s, computed MPH, and `SpeedStatus`

**`AudioService`**
- Configures `AVAudioSession` with `.playback` category and `.default` mode on init
- Loads chime from bundle once; calls `prepareToPlay()`
- `play()` is fire-and-forget; respects `isMuted`

**`TelemetryService`**
- Writes per-frame `TelemetryEvent` as JSONL to `Documents/telemetry/YYYY-MM-DD.jsonl`
- Rolls to a new file at midnight
- Prunes files older than 7 days on init

### Dependency injection

`AppEnvironment` is constructed once at app startup and injected into the SwiftUI tree via `.environment()`. No singletons anywhere else.

```swift
@MainActor
final class AppEnvironment {
    let camera: any CameraServiceProtocol
    let detection: any DetectionEngineProtocol
    let location: any LocationServiceProtocol
    let audio: any AudioServiceProtocol
    let telemetry: any TelemetryServiceProtocol
    let settings: SettingsStore          // shared across VM + services

    static let live = AppEnvironment(
        camera: CameraService(),
        detection: DetectionEngine(),
        location: LocationService(),
        audio: AudioService(),
        telemetry: TelemetryService(),
        settings: SettingsStore()
    )

    static let preview = AppEnvironment(
        camera: MockCameraService(),
        detection: MockDetectionEngine(),
        location: MockLocationService(),
        audio: MockAudioService(),
        telemetry: MockTelemetryService(),
        settings: SettingsStore()
    )
}
```

`SettingsStore` is a lightweight `@Observable` class (not an actor — all reads/writes happen on the main actor):

```swift
@Observable
@MainActor
final class SettingsStore {
    var isChimeEnabled: Bool       // persisted via @AppStorage internally
    var sensitivity: ConfidenceSensitivity
    var iouThreshold: Double
    var useMetricUnits: Bool
    var showBoundingBoxes: Bool
    var showLabels: Bool
    var showSpeed: Bool
}
```

---

## ViewModel & State Flow

### `CameraViewModel`

Single `@Observable @MainActor` class. Injected with services from `AppEnvironment`. Drives everything `CameraView` renders.

```swift
@Observable
@MainActor
final class CameraViewModel {
    // Published state
    var lightState: DisplayLightState = .unknown
    var speed: Double = 0
    var speedUnit: String = "MPH"
    var speedStatus: SpeedStatus = .unknown
    var showGreenAlert: Bool = false
    var showLensSmudgeWarning: Bool = false
    var boundingBoxes: [BoundingBox] = []

    // Services — injected, never constructed here
    private let detection: any DetectionEngineProtocol
    private let location: any LocationServiceProtocol
    private let audio: any AudioServiceProtocol
    private let telemetry: any TelemetryServiceProtocol

    // Settings — injected from AppEnvironment
    private let settings: SettingsStore

    // Pure domain logic — synchronous, fully unit-testable
    private let stateManager = LightStateManager()
    private let fallback = LightTransitionFallbackState()
}
```

### Data flow

```
CameraService ──frames──▶ DetectionEngine (@concurrent inference)
                                  │
                          DetectionResult (AsyncStream)
                                  │
                          CameraViewModel (consumes on MainActor)
                                  │
                          LightStateManager (pure, synchronous)
                                  │
                          ┌───────▼────────┐
                          │  CameraView    │
                          │  (@Bindable VM)│
                          └────────────────┘

LocationService ──SpeedReading──▶ CameraViewModel
```

### Subscription pattern

```swift
func start() async {
    await withTaskGroup(of: Void.self) { group in
        group.addTask { await self.consumeDetection() }
        group.addTask { await self.consumeLocation() }
    }
}

private func consumeDetection() async {
    for await result in detection.results {
        let chime = stateManager.update(
            detectedLight: result.lightColor,
            speedStatus: speedStatus
        )
        let fallbackChime = stateManager.isTrackingRedOrTransitioning &&
            fallback.update(
                filteredLight: result.lightColor,
                observedLight: result.observedColor,
                speedStatus: speedStatus
            )
        lightState = stateManager.displayState
        boundingBoxes = result.boundingBoxes
        showLensSmudgeWarning = result.lensSmudged
        if chime || fallbackChime {
            audio.play()
            triggerGreenAlert()
        }
        telemetry.log(result, speedStatus: speedStatus)
    }
}

private func consumeLocation() async {
    for await reading in location.readings {
        speedStatus = reading.speedStatus
        speed = reading.displaySpeed(metric: settings.useMetricUnits)
        speedUnit = settings.useMetricUnits ? "km/h" : "MPH"
    }
}
```

### Settings state

`SettingsView` reads `@AppStorage` directly for display toggles. A lightweight `@Observable SettingsStore` (owned by `AppEnvironment`) holds values that need to propagate into detection (sensitivity, chime enabled, IoU threshold). No view model needed.

---

## App Design

### Main Camera Screen (`CameraView`)

Full-bleed `CameraPreview` fills the entire screen. All UI floats on top as `glassEffect()` panels. No navigation bar, no status bar chrome.

**Layout:**

```
┌─────────────────────────────────┐
│  [⚠ Lens smudge detected    ]   │  ← amber glass banner, top, slides in/out
│  [🟢 Green light detected   ]   │  ← green glass banner (same slot, alert wins)
│                                 │
│                      ┌────────┐ │
│                      │  34    │ │  ← speed glass pill, top right
│                      │  MPH   │ │
│                      └────────┘ │
│                                 │
│         (camera feed)           │
│                                 │
│   ┌─────────────────────────┐   │
│   │   ●  ●  ●   Red Light   │   │  ← glass card, bottom
│   └─────────────────────────┘   │     TrafficLightIndicator (@Animatable Shape)
│                                 │
│  [⚙]                            │  ← glass gear pill, bottom left, always visible
└─────────────────────────────────┘
```

**`TrafficLightIndicator` shape:**
Custom `@Animatable` Shape with three circle positions in a vertical housing. `activeIndex` (Double 0–2) animates between light states — glow and scale transition smoothly. `glowIntensity` pulses when a state is confirmed.

```swift
@Animatable
struct TrafficLightIndicator: Shape {
    var activeIndex: Double      // 0 = red, 1 = yellow, 2 = green
    var glowIntensity: Double    // 0–1, pulses on confirmed state

    func path(in rect: CGRect) -> Path { ... }
}
```

**Banners:** Green alert and lens smudge warning share the top slot. Green alert takes priority. Both use `glassEffect()` with a tinted overlay (green / amber). Slide in from top edge, auto-dismiss.

**Gear button:** Permanent glass pill, bottom left. Always visible. Tapping presents the settings sheet. No hidden tap-anywhere gesture.

**Bounding boxes:** Debug overlay rendered as a SwiftUI `Canvas` on top of `CameraPreview`. Controlled by `showBoundingBoxes` in settings. Off by default in production builds (`#if DEBUG` default true, release default false).

### Settings Sheet (`SettingsView`)

`.sheet()` presentation — slides up over camera. Dismissed by swipe down or a Done button.

Sections:
- **Chime** — enable toggle, sensitivity segmented picker (Low / Medium / High)
- **Display** — show speed toggle, metric units toggle, bounding boxes toggle, labels toggle
- **Detection** — IoU threshold slider (advanced, collapsible)
- **About** — `WebView(url: Constants.urlObjectDetection)`, on-device privacy note

### Onboarding (`OnboardingView`)

Shown as `.fullScreenCover` on first launch (keyed to `@AppStorage("hasOnboarded")`). Three step cards with glass panels, a blurred background, and a Next/Done button.

1. **Camera** — requests `AVCaptureDevice` permission. If denied, shows Settings deep-link.
2. **Location** — requests `whenInUse` location permission. Explains speed-gate purpose.
3. **Safety disclaimer** — "GreenLight is a driving aid, not a substitute for your attention. Always watch the road." — must tap "I understand" to proceed.

---

## What Gets Deleted

| Current file | Fate |
|---|---|
| `ViewController.swift` | Deleted — `CameraPreview` UIViewRepresentable replaces it |
| `ViewControllerDetection.swift` | Deleted — logic moves to `DetectionEngine` + `CameraViewModel` |
| `DetectionState.swift` | Deleted — replaced by `CameraViewModel` + `SettingsStore` |
| `WebViewContainer.swift` | Deleted — replaced by native `WebView(url:)` |
| `AppDelegate.swift` | Deleted — `@main` SwiftUI App struct handles lifecycle |
| `SceneDelegate.swift` | Deleted — same |
| `Main.storyboard` / `LaunchScreen.storyboard` | Deleted — SwiftUI App lifecycle needs neither |

`LightStateManager`, `LightTransitionFallbackState`, `GeometryFilter`, `ColorHeuristic`, `TrafficLightStateClassifier`, `ChimeController` logic, and `TelemetryLogger` all survive — they move into `Domain/` or are absorbed into their respective service.

---

## Info.plist Fixes (Required Before Submission)

- `CFBundleDisplayName` → `"GreenLight"` (currently `"DriverAssistant"`)
- `NSCameraUsageDescription` → `"GreenLight uses your camera to detect traffic light states and alert you when the light turns green."`
- `NSLocationWhenInUseUsageDescription` → `"Your speed is used to avoid false alerts when you're stationary. Location never leaves your device."`
- `UIMainStoryboardFile` → remove (SwiftUI lifecycle)
- `UILaunchStoryboardName` → replace with `UILaunchScreen` dict for SwiftUI launch screen

---

## Testing Strategy

- **Domain** (`LightStateManager`, `LightTransitionFallbackState`, `GeometryFilter`) — pure XCTest, zero mocking needed
- **ViewModels** — inject mock services via protocol; test state transitions synchronously using `AsyncStream` with known sequences
- **Services** — integration tests on device; unit tests use mock `AVCaptureSession` / `CLLocationManager` subclasses
- **UI** — SwiftUI previews use `AppEnvironment.preview` with `MockDetectionEngine` emitting scripted sequences
