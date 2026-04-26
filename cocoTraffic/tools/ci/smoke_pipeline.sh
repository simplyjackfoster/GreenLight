#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
PYTHON_BIN="${PYTHON:-python3}"
WORK_DIR="${ROOT_DIR}/export/datasets/ci-smoke"
ANN_DIR="${WORK_DIR}/annotations"
IMG_DIR="${WORK_DIR}/images"
CROPS_A="${WORK_DIR}/crops_a"
CROPS_B="${WORK_DIR}/crops_b"
MERGED_DIR="${WORK_DIR}/merged"
export WORK_DIR

rm -rf "${WORK_DIR}"
mkdir -p \
  "${ANN_DIR}" \
  "${IMG_DIR}/val_new_images" \
  "${CROPS_A}" \
  "${CROPS_B}" \
  "${MERGED_DIR}"

"${PYTHON_BIN}" - <<'PY'
import json
import os
from pathlib import Path
from PIL import Image

root = Path(os.environ["WORK_DIR"])
ann = root / "annotations"
img = root / "images" / "val_new_images"

categories = [
    {"supercategory": "person", "id": 1, "name": "person"},
    {"supercategory": "vehicle", "id": 2, "name": "bicycle"},
    {"supercategory": "vehicle", "id": 3, "name": "car"},
    {"supercategory": "vehicle", "id": 4, "name": "motorcycle"},
    {"supercategory": "vehicle", "id": 6, "name": "bus"},
    {"supercategory": "vehicle", "id": 7, "name": "train"},
    {"supercategory": "vehicle", "id": 8, "name": "truck"},
    {"supercategory": "outdoor", "id": 10, "name": "traffic light"},
    {"supercategory": "outdoor", "id": 11, "name": "fire hydrant"},
    {"supercategory": "outdoor", "id": 13, "name": "stop sign"},
    {"supercategory": "animal", "id": 17, "name": "cat"},
    {"supercategory": "animal", "id": 18, "name": "dog"},
    {"supercategory": "outdoor", "id": 92, "name": "traffic_light_red"},
    {"supercategory": "outdoor", "id": 93, "name": "traffic_light_green"},
    {"supercategory": "outdoor", "id": 94, "name": "traffic_light_na"},
]

images = [
    {"id": 1, "file_name": "0000000000000001.jpg", "width": 128, "height": 128},
    {"id": 2, "file_name": "0000000000000002.jpg", "width": 128, "height": 128},
    {"id": 3, "file_name": "0000000000000003.jpg", "width": 128, "height": 128},
]

annotations = [
    {"id": 101, "image_id": 1, "category_id": 92, "bbox": [10, 10, 20, 20], "area": 400, "iscrowd": 0, "segmentation": [[]]},
    {"id": 102, "image_id": 1, "category_id": 93, "bbox": [40, 20, 25, 25], "area": 625, "iscrowd": 0, "segmentation": [[]]},
    {"id": 103, "image_id": 2, "category_id": 94, "bbox": [15, 15, 30, 20], "area": 600, "iscrowd": 0, "segmentation": [[]]},
    {"id": 104, "image_id": 3, "category_id": 10, "bbox": [5, 5, 10, 10], "area": 100, "iscrowd": 0, "segmentation": [[]]},
    {"id": 105, "image_id": 3, "category_id": 3, "bbox": [60, 60, 20, 20], "area": 400, "iscrowd": 0, "segmentation": [[]]},
]

payload = {
    "info": {
        "year": 2026,
        "version": "ci-smoke",
        "description": "GreenLight CI synthetic annotations",
        "contributor": "CI",
        "url": "",
        "date_created": "2026-04-26",
    },
    "licenses": [{"id": i, "name": f"l{i}", "url": ""} for i in range(1, 9)],
    "images": images,
    "annotations": annotations,
    "categories": categories,
}

(ann / "instances_val_new_images.json").write_text(json.dumps(payload), encoding="utf-8")

for image in images:
    Image.new("RGB", (128, 128), (120, 120, 120)).save(img / image["file_name"])
PY

"${PYTHON_BIN}" "${ROOT_DIR}/cocoTraffic/api/make_yolo_labels.py" \
  --annotations "${ANN_DIR}" \
  --input "${IMG_DIR}" \
  --output "${CROPS_A}" \
  --dataset-name "val_new_images" \
  --output-format crops \
  --classes red green \
  --min-box-size 50 \
  --crop-size 64 \
  --padding 0.15 \
  --split 0.85 \
  --verbose

# Build a tiny second dataset to make merge meaningful without external inputs.
mkdir -p "${CROPS_B}/val/yellow"
"${PYTHON_BIN}" - <<'PY'
import os
from pathlib import Path
from PIL import Image

work_dir = Path(os.environ["WORK_DIR"])
dst = work_dir / "crops_b" / "val" / "yellow" / "synthetic_yellow.jpg"
Image.new("RGB", (64, 64), (255, 255, 0)).save(dst)
PY

"${PYTHON_BIN}" "${ROOT_DIR}/cocoTraffic/tools/merge_datasets.py" \
  --input "${CROPS_A}" "${CROPS_B}" \
  --output "${MERGED_DIR}" \
  --verbose

"${PYTHON_BIN}" "${ROOT_DIR}/cocoTraffic/tools/pipeline_check.py" \
  --input "${MERGED_DIR}" \
  --sample-per-class 10 \
  --verbose

echo "Smoke pipeline completed: ${MERGED_DIR}"
