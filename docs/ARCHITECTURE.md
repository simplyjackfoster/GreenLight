# Architecture: Green-Light Chime System

## Goal
Build a best-in-class iPhone + CarPlay traffic-light state change detector that reliably chimes on the driver's light turning green while keeping false positives extremely low.

Primary product metrics:
- False positives per hour (key trust metric)
- True positive rate on red->green transitions
- Chime latency (frames/time from true transition to chime)

Ship gate:
- UNSHIPPABLE if false positives per hour > 1.0
- TARGET if false positives per hour < 0.5 and true positive rate > 92%

## Architecture Summary
End-to-end system is split into two layers:
- Model layer: detector + state classifier
- Decision layer: primary selection + fusion + validation + state machine

This separation is intentional:
- Model layer improves visual recognition.
- Decision layer protects user trust with temporal logic and safety gating.

## Runtime Pipeline (On Device)
1. Capture frame (`AVCaptureSession`, 720p, ~30 FPS target).
2. Run traffic-light detector to get candidate boxes.
3. Run `PrimaryLightSelector` to choose driver-relevant signal.
4. Crop selected box and run state classifier (`red/green/yellow/off`).
5. Compute reliability in `ConfidenceFusionEngine`.
6. Update `AdaptiveStateManager`.
7. On tentative green, run `PreChimeValidator` burst.
8. Fire chime only if all gates pass.
9. Render optional `debug_overlay` for development diagnostics.

## Model Layer

### Detector Strategy
Current baseline:
- Frozen YOLOv8n COCO traffic-light localization.

Recommended "my own model" path:
- Train custom detector on unified public traffic-light datasets.
- Train high-accuracy teacher model first (YOLO26 medium tier recommended).
- Distill or downsize to edge-efficient student for iPhone runtime.

YOLO family guidance (Ultralytics, April 2026):
- Newest family: YOLO26.
- Highest accuracy tier: `yolo26x.pt` (best offline benchmark accuracy, highest runtime cost).
- Best edge tradeoff for this app: `yolo26s.pt` (recommended production candidate).
- Fastest/lightest: `yolo26n.pt` (latency-first fallback).

Detector model plan for this project:
1. Train `yolo26m` as teacher (maximize recall/precision quality).
2. Train `yolo26s` as production candidate.
3. Optionally train `yolo26n` as low-latency fallback.
4. Choose production model by full-system metrics:
   - false positives per hour
   - true positive rate
   - end-to-end chime latency
   (not by mAP alone).

Detector training objective:
- Maximize small-object recall with strict false-positive control.

Detector output contract:
- Input: full camera frame.
- Output: list of `bbox + confidence + class` where class is either:
  - single-class `traffic_light`, or
  - multi-class traffic-light variants.

Decision:
- Prefer single-class detector plus dedicated state classifier for robust modularity.

### State Classifier Strategy
Implemented:
- MobileNetV3-Small (primary)
- EfficientNet-Lite0 (comparison)

Upgrade path (explicit comparison matrix):
- Compare `MobileNetV3-Small` vs `MobileNetV3-Large` vs `EfficientNet-Lite1`.
- Run each at `64x64` and `96x96` crop resolutions.
- Promote classifier by trust metrics first (FP/hour, TPR, latency), accuracy second.

Training setup:
- ImageNet pretrained initialization
- 64x64 RGB traffic-light crops
- Label space: `red`, `green`, `yellow`, `off`
- Weighted sampling for class imbalance
- Freeze backbone first epochs, then full fine-tune

Export:
- Core ML `.mlpackage`
- Float16 precision
- `compute_units=ALL`
- Outputs: `classLabel` + `classProbability`

## Data Architecture

### Data Sources (Public Only)
- LISA Traffic Light Dataset (CSV annotations)
- S2TLD (XML annotations, includes `wait_on`)
- BSTLD (YAML annotations, strong small/distant examples)

### Data Normalization
Unified class mapping:
- `wait_on` -> `yellow`
- Directional labels (`RedLeft`, `GreenStraight`, etc.) -> base color
- `flashing_red` -> dropped from training set entirely; treated as `off` at runtime (flashing red is too ambiguous and rare to model reliably, and incorrect classification would risk a false chime)

Unified sample format:
- Record = image path + bbox + normalized class + source dataset metadata

### Dataset Build Steps
1. Parse source annotations.
2. Validate/resolve image paths.
3. Crop bbox with 15% padding.
4. Resize to 64x64.
5. Stratified split (85/15 train/val).
6. Emit class distribution + recommended sampler weights.
7. Save manifests for reproducibility.

### Data Quality Loop
- Hard-negative mining from public data:
  - tail lights, reflections, LED signs, lens flare.
- Balance by lighting condition:
  - day / dusk / night.
- Balance by light scale:
  - near / medium / distant.

## Decision Layer

### Primary Light Selection
`PrimaryLightSelector` score:
- Area: 0.35
- Horizontal center proximity: 0.25
- Vertical prior (upper-center): 0.15
- Temporal stability (IoU history): 0.15
- Aspect-ratio validity: 0.10

Stability behavior:
- History window: 7 frames
- Occlusion hold: 3 frames
- Switch hysteresis to prevent wrong-light hopping

### Confidence Fusion
`ConfidenceFusionEngine` combines:
- Classifier softmax confidence
- Box size score
- Box stability score
- Ambient lighting score
- Transition prior probability

Transition prior matrix:
- from red: to green 0.90
- from green: to green 0.85
- from yellow: to red 0.80
- from off: to off 0.55

Adaptive reliability thresholds:
- day: 0.82
- dusk: 0.87
- night: 0.91

### Pre-Chime Validation Burst
`PreChimeValidator` safeguards final alert:
- Freeze selected bbox
- 6 passes at scales: 0.90, 0.95, 1.00, 1.05, 1.10, 1.00(+brightness)
- Require 5/6 green confirmations above threshold
- Time budget < 150 ms

### Adaptive State Machine
States:
- `SEARCHING`
- `TRACKING_RED`
- `TENTATIVE_GREEN`
- `CONFIRMED_GREEN`
- `TRACKING_GREEN`
- `TRACKING_YELLOW`
- `LOST`

Key gating logic:
- LOST hold up to 45 frames
- Speed gate: must be < 2 mph to chime
- Cooldown: 150 frames after any chime
- Adaptive smoothing window:
  - day 5
  - dusk 7
  - night 10

Speed gate source:
- Primary: `CLLocationManager` GPS-derived speed (requires `whenInUse` location permission).
- Fallback: if location permission is denied or GPS fix is unavailable, speed is treated as `unknown`.
- Unknown speed behavior: chime is suppressed (fail-safe). The app must not chime when it cannot confirm the vehicle is stopped.
- Implementation note: request `whenInUse` permission at onboarding; display a persistent "Speed unavailable — chime disabled" warning in the UI if permission is absent.

Zero-detection handling:
- If 5 or more consecutive frames return zero candidate boxes, the active track is considered lost and the state transitions to `LOST`.
- A single empty frame does not break tracking; the selector occlusion hold (3 frames) absorbs momentary gaps.

LOST state recovery:
- During the 45-frame LOST hold: if a detection reappears with IoU ≥ 0.40 against the last known bbox, re-enter `TRACKING_RED` (never directly to `TENTATIVE_GREEN`).
- Re-entry requires N=3 consecutive frames of classifier agreement on the recovered state before any green transition is allowed.
- After 45 frames without recovery: transition to `SEARCHING`, resetting all temporal state.
- Guard against mid-LOST red approach: if recovery detects green immediately after LOST, the 3-frame agreement requirement prevents a false chime from a missed red phase.

## Evaluation Architecture

`evaluate.py` computes:
- True positive chimes
- False positive chimes
- False negatives (missed red->green)
- Median and P95 latency
- False positives per hour
- Breakdowns:
  - day/night
  - single/multiple visible lights

This evaluator is the final arbiter for model/pipeline promotion.

### Evaluation Input Format

`evaluate.py` operates on labeled clip manifests, not live video.

Manifest format (JSON):
```json
[
  {
    "clip": "path/to/clip.mp4",
    "fps": 30,
    "lighting": "day|dusk|night",
    "ground_truth_chimes": [
      { "frame_start": 120, "frame_end": 135, "label": "red_to_green" }
    ]
  }
]
```

Three supported evaluation modes:
1. **Offline labeled clips** — recorded drive footage with annotated ground-truth chime events (primary mode).
2. **Synthetic sequences** — programmatically generated frame sequences with known state transitions (used for unit-level regression on edge cases: flicker, occlusion, LOST recovery).
3. **Drive replay** (Phase C) — full trip recordings replayed through the live pipeline at real time, logged and post-scored.

Tolerance window: a chime is counted as a true positive if it fires within ±15 frames of a ground-truth event. Chimes outside any ground-truth window are false positives.

## Debug and Observability

`debug_overlay.py` visualizes:
- All detections with state colors
- Primary selected light highlight
- Per-light classifier confidence + fusion score
- State machine current state
- Frame buffer dots
- Ambient estimate
- CHIME / NO CHIME indicator
- Running TP/FP counters

Operational telemetry (required):
- Per-frame selected bbox and score components
- Reliability score and active threshold
- State transitions with reason codes
- Chime events and suppression reasons
- Speed gate status per chime decision (value, source, or `unknown`)

## Deployment Architecture

Build artifacts:
- Detector Core ML package
- Classifier Core ML package
- Tunable constants bundle (versioned)

Runtime compatibility checks:
- Input/output names and shapes
- Class label ordering
- Model metadata version

Versioning rule:
- Detector version + classifier version + logic version must be pinned together in release metadata.

## "Own Model" Upgrade Plan

### Phase A: Strong Baseline
- Keep existing detector.
- Optimize classifier + decision layer until trust gate passes.

### Phase B: Custom Detector
- Build unified detection dataset from public sources.
- Train teacher detector (`yolo26m`).
- Train production candidate (`yolo26s`) for edge deployment.
- Optionally train `yolo26n` fallback profile.
- A/B compare against baseline on full chime evaluator.

Implementation scripts for this phase:
- `build_detection_dataset.py`: unified detector labels from public sets.
- `train_detector.py`: teacher + student training workflow.
- `eval_detector.py`: small-object/day-night-focused detector evaluation.

Acceptance criteria in detector bake-off:
- Candidate must reduce false positives per hour at equal or better TPR.
- Candidate must stay within real-time on-device latency budget.
- If detector mAP improves but FP/hour worsens, reject candidate.

### Phase C: Production Hardening
- Add regression suite across day/night/multi-light edge cases.
- Add calibration set for threshold tuning.
- Freeze release candidate and run extended drive replay evaluation.

## Tunable Parameters (Most Important)

### Highest impact on false positives
1. Fusion adaptive thresholds (day/dusk/night)
2. Selector hysteresis + track IoU threshold
3. Pre-chime required confirmations

### Highest impact on false negatives
1. Detector recall on small/distant lights
2. State-machine buffer sizes (especially night)
3. Pre-chime burst acceptance strictness

## Failure Modes and Mitigations
- Wrong light selected at intersections:
  - Mitigate with stronger selector priors + hysteresis + stability history.
- Night-time glare/reflection false greens:
  - Mitigate with ambient-aware thresholds + hard negatives + pre-chime burst.
- Brief occlusions by trucks/buses:
  - Mitigate with LOST hold and temporal memory.
- Chime spam:
  - Mitigate with cooldown + speed gate.

## File Map

### Python (ML pipeline)
- Dataset: `dataset_pipeline.py`
- Training: `train.py`
- Export: `export_coreml.py`
- Primary selection: `primary_light_selector.py`
- Fusion: `confidence_fusion_engine.py`
- Pre-chime: `pre_chime_validator.py`
- State machine: `adaptive_state_manager.py`
- Evaluation: `evaluate.py`
- Overlay: `debug_overlay.py`

### iOS (Swift runtime)
- Camera capture: `CaptureSession.swift`
- Detector inference: `TrafficLightDetector.swift`
- Primary light selector: `PrimaryLightSelector.swift`
- State classifier: `StateClassifier.swift`
- Confidence fusion: `ConfidenceFusionEngine.swift`
- Pre-chime validator: `PreChimeValidator.swift`
- State machine: `AdaptiveStateManager.swift`
- Speed gate: `SpeedGate.swift` (wraps `CLLocationManager`)
- Chime output: `ChimeController.swift`
- CarPlay integration: `CarPlaySceneDelegate.swift`
- Debug overlay: `DebugOverlayView.swift`

See `INTEGRATION_SPEC.md` for full iOS integration contract, input/output shapes, and CoreML model loading details.
