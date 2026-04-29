# GreenLight

GreenLight is an iOS app that uses on-device computer vision to detect traffic-light color changes and play a short chime when a red-to-green transition is confirmed while the vehicle is stationary.

**Safety disclaimer:** Do not rely on this app for safe driving decisions. Keep your eyes on the road and obey local laws.

## What It Does

- Captures live camera frames from the rear camera.
- Runs a Core ML detector (YOLO model candidates bundled in the app).
- Infers light state (`red`, `green`, `yellow`, `unknown`) using detector labels plus a fallback classifier/heuristic path.
- Applies temporal state logic and speed gating to reduce false alerts.
- Plays a local chime and shows a temporary "Green light detected" banner when conditions are met.
- Shows current speed (optional) and provides in-app settings for chime and display preferences.

## Current Feature Set (Verified)

- SwiftUI camera preview screen with settings sheet.
- On-device inference only (no backend service in this repo).
- Location-based speed status (`knownStationary`, `knownMoving`, `unknown`) for chime gating.
- Local telemetry JSONL logging in app documents storage.
- Settings persistence via `UserDefaults` through a repository.
- Unit tests for core state logic and selected app-layer behavior.
- Python tooling for dataset processing, training, and Core ML export (separate from app runtime).

## Tech Stack

### iOS app
- Swift + SwiftUI (`@Observable`, async/await)
- AVFoundation (camera + audio)
- Vision + Core ML (detection/classification)
- CoreLocation (speed gating)
- Xcode project: `GreenLight.xcodeproj`

### Python tooling
- Python scripts under `ml/` and `cocoTraffic/`
- Makefile targets for dataset pipeline smoke checks and utilities
- Dependencies used across scripts/tests include: `torch`, `torchvision`, `timm`, `coremltools`, `opencv-python`, `pillow`, `pandas`, `tqdm`, `pyyaml`, `imagehash`, `numpy`

## Requirements

### App
- macOS with Xcode (tested with modern Xcode toolchains)
- iOS deployment target: **17.0**
- Physical iPhone required for live camera/location behavior

### Python tooling (optional)
- Python 3.10+
- `pip`

## Setup

### 1) Clone

```bash
git clone https://github.com/simplyjackfoster/GreenLight.git
cd GreenLight
```

### 2) Open in Xcode

```bash
open GreenLight.xcodeproj
```

### 3) Configure signing

In Xcode, set your Team and bundle signing under the `GreenLight` target.

## Run Locally

### Run the app (Xcode)

1. Select `GreenLight` scheme.
2. Select an iPhone target device.
3. Build and run.
4. Grant camera and location permissions when prompted.

## Build

### CLI build (app target)

```bash
xcodebuild \
  -project GreenLight.xcodeproj \
  -scheme GreenLight \
  -destination 'generic/platform=iOS' \
  build CODE_SIGNING_ALLOWED=NO
```

## Test

### Swift unit tests

Compile tests for simulator:

```bash
xcodebuild \
  -project GreenLight.xcodeproj \
  -scheme GreenLight \
  -destination 'platform=iOS Simulator,name=iPhone 16' \
  build-for-testing CODE_SIGNING_ALLOWED=NO
```

Run tests:

```bash
xcodebuild \
  -project GreenLight.xcodeproj \
  -scheme GreenLight \
  -destination 'platform=iOS Simulator,name=iPhone 16' \
  test CODE_SIGNING_ALLOWED=NO
```

### Python tests (ML/data tooling)

From repo root:

```bash
python -m unittest discover -s ml/tests -p 'test_*.py'
```

Note: some ML scripts require additional dependencies and/or dataset files not included in this repository.

## Python / Data Pipeline Commands

Install lightweight dataset pipeline deps via Makefile:

```bash
make py-deps
```

Run compile/smoke checks:

```bash
make py-compile
make dataset-smoke
```

Install a Core ML model artifact into app models folder:

```bash
./scripts/install_coreml_model.sh <path-to-model.mlpackage> <model_name>
```

## Configuration and Environment

- No required `.env` file was found for app runtime.
- App settings are persisted in `UserDefaults` (chime enabled, sensitivity, display options, units).
- App permissions are declared in [`GreenLight/Info.plist`](GreenLight/Info.plist):
  - Camera (`NSCameraUsageDescription`)
  - Location when in use (`NSLocationWhenInUseUsageDescription`)

## Project Structure

```text
GreenLight/
  App/                    # App entry point
  Core/                   # DI container and protocol interfaces
  Data/                   # Settings persistence repository
  Domain/                 # State logic, types, heuristics, classifier wrapper
  Features/               # SwiftUI views/view models by feature
  Services/               # AVFoundation/Vision/Location/Telemetry services
  Models/                 # Bundled Core ML model artifacts
  Resources/              # Chime sound
GreenLightTests/          # Swift unit tests
ml/                       # Python ML/data scripts + tests
cocoTraffic/              # Dataset utilities and smoke pipeline scripts
scripts/                  # Helper shell scripts (e.g., model install)
```

## Known Limitations / Gaps

- CarPlay is referenced in docs, but no active CarPlay scene/delegate implementation is present in current app code.
- UI toggles for "Bounding boxes" and "Labels" are persisted but no on-screen overlay rendering is currently wired in `CameraView`.
- Detector selection/behavior depends on bundled model assets and label mappings; model quality and label schema mismatches can affect detection.
- CI workflow is now `.github/workflows/ios-ci.yml` and uses `xcodebuild` for project-accurate build/test checks.
- Several planning/spec docs under `docs/` describe broader target architecture beyond what is currently implemented.

## License

See [LICENSE](LICENSE).
