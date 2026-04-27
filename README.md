# GreenLight

An iPhone + CarPlay app that chimes when your traffic light turns green.

**Disclaimer:** *Do not rely on this app for safety. Keep your eyes on the road at all times. Local laws on mobile device use while driving vary by jurisdiction.*

---

## How it works

GreenLight runs a real-time traffic-light detection and state classification pipeline on-device:

1. Captures camera frames at 720p / 30 FPS via `AVCaptureSession`
2. Detects traffic-light candidates with a YOLO detector (CoreML)
3. Selects the driver-relevant light with `PrimaryLightSelector`
4. Classifies its state (`red` / `green` / `yellow` / `off` / `hard_negative`) with a MobileNetV3 classifier (CoreML)
5. Runs confidence fusion, temporal state machine, and a pre-chime validation burst
6. Chimes only when all gates pass and the vehicle is stopped (< 2 mph)

See `ARCHITECTURE.md` for the full system design.

---

## Requirements

- Xcode 15+
- iPhone with iOS 16+ (physical device required for camera)
- CarPlay-compatible head unit (optional)

---

## Getting started

```bash
git clone https://github.com/simplyjackfoster/GreenLight.git
open GreenLight.xcodeproj
```

Select your iPhone as the run target, configure signing under **Signing & Capabilities**, and build.

---

## ML pipeline

The classifier is trained on crops from LISA, S2TLD, and BSTLD with a data quality loop (hard-negative mining, lighting/scale balancing).

### Export a detector model

```bash
pip install -U ultralytics
yolo export model=yolo26n.pt format=coreml nms=True int8=True
./scripts/install_coreml_model.sh yolo26n.mlpackage yolo26nTraffic
```

Fallback if `yolo26n` export fails:

```bash
yolo export model=yolo11n.pt format=coreml nms=True int8=True
./scripts/install_coreml_model.sh yolo11n.mlpackage yolo11nTraffic
```

The app loads models in priority order: `yolo26nTraffic` → `yolo11nTraffic` → `yolov8nTraffic`.

### Train the state classifier

```bash
python dataset_pipeline.py --lisa-root export/datasets/raw/lisa \
                            --s2tld-root export/datasets/raw/s2tld \
                            --bstld-root export/datasets/raw/bstld
python train.py
python export_coreml.py
```

See `docs/data-pipeline.md` for the full reproducible workflow.

---

## Ship gate

| Metric | Threshold |
|---|---|
| False positives / hour | < 0.5 to ship, > 1.0 unshippable |
| True positive rate (red→green) | > 92% |

---

## License

See `LICENSE`.
