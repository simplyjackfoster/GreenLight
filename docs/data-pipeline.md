# Data Pipeline

This document defines the reproducible path from dataset generation to app model integration.

## Prerequisites

- Python 3.10+
- `pip`
- Project root: `GreenLight/`

Install required Python packages:

```bash
make py-deps
```

This creates a local virtual environment at `.venv-dataset/` and installs the required tooling there.

## Stable artifact locations

- Raw inputs: `export/datasets/raw/`
- Generated crops: `export/datasets/crops/`
- Merged datasets: `export/datasets/merged/`
- Training checkpoints: `export/models/checkpoints/`
- CoreML exports: `export/models/coreml/`
- App runtime models: `DriverAssistant/Models/`

## 1) Run compile checks + smoke pipeline

```bash
make py-compile
make dataset-smoke
```

Expected smoke outputs:

- `export/datasets/ci-smoke/crops_a/`
- `export/datasets/ci-smoke/crops_b/`
- `export/datasets/ci-smoke/merged/`
- Pipeline check prints `Final status: GO`

## 2) Generate crop datasets for classifier/object workflows

Example for COCO-style annotations:

```bash
make dataset-crops \
  ANNOTATIONS=export/datasets/raw/annotations \
  INPUT_IMAGES=export/datasets/raw/images \
  DATASET=val_new_images \
  OUTPUT=export/datasets/crops/coco \
  CLASSES="red green yellow off na"
```

Expected output structure:

- `export/datasets/crops/coco/train/<class>/*.jpg`
- `export/datasets/crops/coco/val/<class>/*.jpg`

## 3) Merge datasets and validate

```bash
make dataset-merge \
  DATASET_A=export/datasets/crops/coco \
  DATASET_B=export/datasets/crops/s2tld \
  MERGED=export/datasets/merged/main

make pipeline-check MERGED=export/datasets/merged/main
```

Expected output:

- `export/datasets/merged/main/train/<class>/*.jpg`
- `export/datasets/merged/main/val/<class>/*.jpg`
- Class imbalance + recommended `WeightedRandomSampler` weights printed by merge step
- `Final status: GO` from pipeline check

## 4) Train and export model

Training command depends on your selected trainer (YOLOv5/YOLOv8/custom). Save artifacts under:

- Checkpoints: `export/models/checkpoints/`
- CoreML output: `export/models/coreml/`

## 5) Integrate CoreML output into app

Copy exported model into the app models directory:

```bash
make install-coreml MODEL_PATH=export/models/coreml/yolov8nTraffic.mlpackage MODEL_NAME=yolov8nTraffic
```

Then in Xcode:

1. Open `DriverAssistant.xcodeproj`
2. Confirm model is part of app target and in Copy Bundle Resources
3. If model filename changed, update lookup in:
   - `DriverAssistant/ViewControllers/ViewControllerDetection.swift`

Current lookup expects `yolov5sTraffic.mlmodelc`.
