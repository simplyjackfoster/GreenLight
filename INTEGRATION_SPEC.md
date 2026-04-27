# Integration Spec: iOS + CarPlay Traffic-Light Green Chime

## 1) `.mlpackage` Integration into Xcode
- Place exported classifier package in app repo, e.g. `GreenLight/Models/traffic_light_state_classifier.mlpackage`.
- Add to Xcode target and verify it is copied in build phases.
- Keep YOLO detector and classifier versioned together:
  - Detector: `yolov8n_coco_trafficlight`
  - Classifier: `traffic_light_state_classifier`
- Add model metadata checks at app launch:
  - Expected class labels: `red, green, yellow, off`
  - Expected input shape: `(1, 3, 64, 64)` for MultiArray path

## 2) `AVCaptureSession` Setup
- Recommended capture preset: `AVCaptureSession.Preset.hd1280x720`.
- Recommended FPS: `30` (drop to `24` if thermal pressure rises).
- Camera choice:
  - Default: rear wide camera (`.builtInWideAngleCamera`).
  - Fallback: any rear camera if wide unavailable.
- Video orientation handling:
  - Lock processing orientation to portrait sensor coordinates.
  - Convert Vision output to normalized image coordinates once.
  - Avoid per-stage mixed coordinate systems.

## 3) YOLO -> Classifier Pipe (Vision Framework)
- YOLO stage (frozen): run per frame and filter for traffic-light class only.
- For each candidate bbox:
  - Select primary with `PrimaryLightSelector`.
  - Crop around selected box with 15% padding.
  - Resize to `64x64`.
  - Normalize with ImageNet mean/std if using MultiArray input.
- Vision output notes:
  - YOLO detections via `VNRecognizedObjectObservation.boundingBox` are normalized and origin-bottom-left.
  - Convert once to pixel coordinates for current `CVPixelBuffer` width/height.
- Efficient crop path:
  - Use `vImage`/`CoreImage`/Metal where possible to avoid CPU copies.
  - Reuse pixel buffers and temporary arrays to limit allocations.

## 4) Porting State Logic to Swift
- Mirror Python modules one-to-one as Swift types:
  - `PrimaryLightSelector`
  - `ConfidenceFusionEngine`
  - `PreChimeValidator`
  - `AdaptiveStateManager`
- Keep all tunables centralized in a `struct Tuning`.
- Keep state transitions explicit with `enum` and pure functions where possible.
- Add unit tests in `GreenLightTests` for transition and cooldown edge cases.

## 5) CarPlay Integration
- Scene setup:
  - Add `CPTemplateApplicationScene` in scene manifest.
  - Provide `CPTemplateApplicationSceneDelegate` implementation.
- Recommended template:
  - `CPInformationTemplate` for status-centric display (current state, confidence, chime readiness).
- Shared state between phone + CarPlay:
  - Use a single `ObservableObject` pipeline service.
  - Publish updates through Combine (`CurrentValueSubject` or `@Published`).
- Entitlement:
  - Apply for CarPlay entitlement relevant to driving-assistance-style app behavior through Apple review.
  - Ensure UI purpose and safety constraints are documented in submission notes.

## 6) Background Execution (Screen Locked)
- Important platform constraint:
  - Continuous camera capture + real-time CV is not generally allowed while app is fully backgrounded/locked without approved modes and compliant behavior.
- Practical strategy:
  - Keep app foreground-active while connected to CarPlay UI.
  - Handle interruptions and resume quickly.
  - Fail safe: disable chime path if capture/inference pauses.

## 7) Audio / Chime
- `AVAudioSession` configuration:
  - Category: `.playback`
  - Mode: `.default` or `.voicePrompt` (evaluate per route behavior)
  - Options: include route-friendly options for CarPlay playback continuity
- Muted-phone behavior:
  - Use playback category + active session before chime play.
  - Validate behavior on device + CarPlay head unit (route varies by hardware).
- Recommended chime characteristics:
  - Frequency emphasis around `1.5-2.5kHz`
  - Duration `180-300ms`
  - Fast attack + short fade-out to avoid harsh clicks
- CarPlay speakers:
  - Rely on active audio route from `AVAudioSession.currentRoute`.
  - Gate repeated alerts with cooldown to avoid nuisance.

## Operational Checks Before Ship
- Run evaluation suite on held-out labeled set and verify:
  - False positives per hour `< 0.5` target
  - True positive rate `> 92%`
  - P95 latency acceptable for stoplight departure use case
- Verify behavior separately for:
  - day/night
  - single/multiple visible lights
  - partial occlusions and short LOS loss
