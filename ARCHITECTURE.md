# Architecture: Green-Light Chime Pipeline

## System Objective
Deliver a high-trust green-light chime with low false-positive rate in real road scenes with multiple visible signals.

## Pipeline Overview
1. Stage 1 detector: frozen YOLOv8n COCO traffic-light localization.
2. Stage 2 classifier: MobileNetV3-Small (primary) / EfficientNet-Lite0 (comparison) for `red/green/yellow/off`.
3. Primary selection: choose the driver-relevant light among multiple candidates.
4. Confidence fusion: combine classifier confidence + geometry + temporal prior + ambient conditions.
5. Pre-chime validator: 6-pass burst confirmation before any chime.
6. Adaptive state manager: transition control, lost handling, speed gate, cooldown.
7. Evaluation + overlay: objective metrics + debuggability.

## Design Decisions
- Two-stage architecture kept by design for speed and modularity.
- Detector remains frozen to reduce maintenance complexity and preserve on-device speed.
- Classifier trained only on public datasets (LISA, S2TLD, BSTLD).
- Label space normalized to 4 classes to simplify state logic and Swift port.
- Reliability is not a single-model output; it is a fused confidence from multiple signals.
- Chime is gated by both state-machine semantics and pre-chime burst validation.

## Components

### 1) Dataset Pipeline (`dataset_pipeline.py`)
Responsibilities:
- Parse LISA CSV, S2TLD XML, BSTLD YAML.
- Normalize labels to `red/green/yellow/off`.
- Crop with 15% padding and resize to 64x64.
- Stratified 85/15 train/val split.
- Export class folders and sampling manifests.

Key tunables:
- `DEFAULT_PADDING_RATIO = 0.15`
- `DEFAULT_SPLIT_RATIO = 0.85`
- `DEFAULT_MIN_BOX_AREA = 16.0`

### 2) Training (`train.py`)
Responsibilities:
- Train `mobilenet_v3_small` and `efficientnet_lite0`.
- Freeze backbone for 5 epochs then unfreeze.
- WeightedRandomSampler for class imbalance.
- AdamW + cosine annealing + label smoothing.
- Early stopping on validation accuracy.

Key tunables:
- `DEFAULT_LEARNING_RATE = 1e-3`
- `DEFAULT_FREEZE_EPOCHS = 5`
- `DEFAULT_EARLY_STOPPING_PATIENCE = 5`
- Augment knobs (`AUG_*`) for brightness/contrast/blur/rotation/cutout

### 3) Core ML Export (`export_coreml.py`)
Responsibilities:
- Auto-select winning checkpoint.
- Export as ML Program with float16 and `compute_units=ALL`.
- Output `classLabel` + `classProbability`.
- Validate parity on 20 val samples against PyTorch.

Key tunables:
- `--input-type multiarray|image`
- `--validation-samples`
- parity gate threshold (current hard gate: top-1 match >= 0.95)

### 4) Primary Selector (`primary_light_selector.py`)
Responsibilities:
- Score candidates by area/center/vertical/stability/aspect ratio.
- Maintain selection through short occlusion.
- Prevent rapid switching via hysteresis.

Weights (default):
- area `0.35`
- center proximity `0.25`
- vertical `0.15`
- stability `0.15`
- aspect ratio `0.10`

Key tunables:
- `track_match_iou_threshold`
- `switch_hysteresis_margin`
- `occlusion_hold_frames`

### 5) Confidence Fusion (`confidence_fusion_engine.py`)
Responsibilities:
- Fuse classifier confidence, bbox size/stability, ambient score, transition prior.
- Apply adaptive day/dusk/night threshold.

Transition priors:
- red -> green: `0.90`
- green -> green: `0.85`
- yellow -> red: `0.80`
- off -> off: `0.55`

Adaptive thresholds:
- day `0.82`
- dusk `0.87`
- night `0.91`

### 6) Pre-Chime Validator (`pre_chime_validator.py`)
Responsibilities:
- Freeze selected bbox.
- Run 6-pass scale burst: `0.9,0.95,1.0,1.05,1.1,1.0(+brightness)`.
- Require `5/6` green confirmations above threshold.
- Enforce total time budget (`150ms`).

Key tunables:
- `required_confirmations = 5`
- `total_time_budget_ms = 150`
- `brightness_delta = 0.08`

### 7) Adaptive State Manager (`adaptive_state_manager.py`)
Responsibilities:
- Manage transition graph and chime gating.
- LOST hold for temporary occlusion.
- Adaptive buffer by lighting condition.
- Speed and cooldown safety gates.

Key tunables:
- `lost_hold_frames = 45`
- `speed_gate_mph = 2.0`
- `cooldown_frames = 150`
- buffer size day/dusk/night = `5/7/10`

### 8) Evaluation (`evaluate.py`)
Responsibilities:
- Compute TP/FP/FN, latency median/P95, FP/hour.
- Breakdowns by day/night and single/multiple lights.
- Trust verdict:
  - `UNSHIPPABLE` if FP/hour > 1.0
  - `TARGET` if FP/hour < 0.5 and TPR > 92%

### 9) Debug Overlay (`debug_overlay.py`)
Responsibilities:
- Draw all candidate boxes + primary highlight.
- Annotate state/confidence/fusion per light.
- Show current state machine state, buffer dots, ambient estimate, chime indicator, running TP/FP counters.

## Data Contracts
- Class labels across all modules are lowercase: `red|green|yellow|off`.
- Frame coordinate system for bboxes is pixel-space `(x1,y1,x2,y2)`.
- Reliability scores are clipped to `[0,1]`.
- Lighting condition enum: `day|dusk|night`.

## Failure Handling Strategy
- Missing datasets/dependencies fail with explicit install/download instructions.
- Empty or malformed inputs fail fast with actionable errors.
- State machine resets after prolonged LOST timeout.
- Chime never fires if speed gate or cooldown gate fails.

## Portability Notes (Python -> Swift)
- Dataclass/enum structures map directly to Swift `struct`/`enum`.
- Deterministic constants are centralized for tuning parity.
- Components expose intermediate scores for debugging and telemetry.

## Recommended Tuning Order in Field Tests
1. Reduce false positives via selector hysteresis + fusion thresholds.
2. Recover missed greens via pre-chime required confirmations and buffer sizes.
3. Rebalance latency vs precision using state-manager buffer and confidence gates.
