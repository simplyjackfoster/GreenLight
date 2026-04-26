# ========================================================================= #
# Generates labels in YOLO format or cropped traffic-light classifier data. #
# File is tailored to the COCO Traffic Plus dataset.                        #
# ========================================================================= #

from __future__ import annotations

import argparse
import csv
import json
import logging
import random
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from PIL import Image
from tqdm import tqdm

# FIXED: derive paths from script location instead of hardcoded ../ paths
BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_MIN_BOX_SIZE = 400.0
DEFAULT_PADDING = 0.15
DEFAULT_CROP_SIZE = 64
DEFAULT_SPLIT = 0.85
SPLIT_SEED = 1881

logger = logging.getLogger(__name__)

# category_id remap for legacy YOLO export compatibility
COCO_TO_YOLO = {
    "1": "0",
    "2": "1",
    "3": "2",
    "4": "3",
    "6": "4",
    "7": "5",
    "8": "6",
    "11": "7",
    "13": "8",
    "17": "9",
    "18": "10",
    "92": "11",
    "93": "12",
    "94": "13",
}

CANONICAL_CLASS_ALIASES = {
    "red": "red",
    "traffic_light_red": "red",
    "green": "green",
    "traffic_light_green": "green",
    "yellow": "yellow",
    "traffic_light_yellow": "yellow",
    "na": "na",
    "traffic_light_na": "na",
    "off": "off",
    "traffic_light_off": "off",
    "traffic light": "traffic_light",
    "traffic_light": "traffic_light",
}


def validate_or_warn(condition: bool, message: str, strict: bool = False) -> None:
    # FIXED: replace fragile assert crashes with warning + optional strict mode
    if condition:
        return
    if strict:
        raise ValueError(message)
    logger.warning(message)


class Dataset:
    def __init__(self, path: str, filename: str, strict: bool = False) -> None:
        self.filename = filename
        with open(Path(path) / f"{filename}.json", "r", encoding="utf-8") as f:
            anns = json.load(f)

        self.img_ids_to_ann_ids: Dict[Any, List[Any]] = defaultdict(list)
        self.ann_id_to_anns: Dict[Any, Dict[str, Any]] = {}
        self.img_ids_to_imgs: Dict[Any, Dict[str, Any]] = {}
        self.category_id_to_name: Dict[str, str] = {
            str(cat["id"]): str(cat["name"]).strip().lower() for cat in anns["categories"]
        }

        self.img_ids: List[Any] = []
        for image in anns["images"]:
            self.img_ids.append(image["id"])
            self.img_ids_to_imgs[image["id"]] = image

        for ann in anns["annotations"]:
            img_id = ann["image_id"]
            ann_id = ann["id"]
            self.img_ids_to_ann_ids[img_id].append(ann_id)
            self.ann_id_to_anns[ann_id] = ann

        validate_or_warn(
            len(self.img_ids_to_ann_ids) <= len(self.img_ids),
            f"Unexpected annotation index shape in {filename}.",
            strict,
        )
        logger.info("Loaded %s annotations from %s images!", len(self.ann_id_to_anns), len(self.img_ids))

    def get_annotations(self, img_id: Any) -> List[Dict[str, Any]]:
        ann_ids = self.img_ids_to_ann_ids.get(img_id, [])
        return [self.ann_id_to_anns[ann_id] for ann_id in ann_ids]

    def get_image_ids(self) -> List[Any]:
        return self.img_ids

    def get_image(self, img_id: Any) -> Dict[str, Any]:
        return self.img_ids_to_imgs[img_id]

    def category_name(self, category_id: Any) -> str:
        return self.category_id_to_name.get(str(category_id), "")


def normalize_class_name(raw: str) -> str:
    key = raw.strip().lower()
    return CANONICAL_CLASS_ALIASES.get(key, key)


def parse_requested_classes(classes: Optional[Sequence[str]]) -> Optional[Set[str]]:
    if not classes:
        return None
    return {normalize_class_name(c) for c in classes}


def box_coco_to_yolo(bbox_coco: Sequence[float], img: Dict[str, Any]) -> List[float]:
    return [
        (bbox_coco[0] + 0.5 * bbox_coco[2]) / img["width"],
        (bbox_coco[1] + 0.5 * bbox_coco[3]) / img["height"],
        bbox_coco[2] / img["width"],
        bbox_coco[3] / img["height"],
    ]


def bbox_area(bbox: Sequence[float]) -> float:
    return float(bbox[2]) * float(bbox[3])


def filter_annotation(
    ann: Dict[str, Any],
    data: Dataset,
    requested_classes: Optional[Set[str]],
    min_box_size: float,
) -> Tuple[bool, str]:
    if bbox_area(ann["bbox"]) < min_box_size:
        return False, ""

    class_name = normalize_class_name(data.category_name(ann["category_id"]))
    if requested_classes is not None and class_name not in requested_classes:
        return False, class_name
    return True, class_name


def resolve_image_path(images_dir: Path, dataset_name: str, image_meta: Dict[str, Any], img_id: Any) -> Optional[Path]:
    file_name = image_meta.get("file_name")
    candidates: List[Path] = []
    if file_name:
        candidates.append(images_dir / dataset_name / str(file_name))
        candidates.append(images_dir / str(file_name))
    candidates.append(images_dir / dataset_name / f"{str(img_id)}.jpg")
    candidates.append(images_dir / f"{str(img_id)}.jpg")
    candidates.append(images_dir / dataset_name / f"{str(img_id)}.jpg".zfill(16))
    candidates.append(images_dir / f"{str(img_id)}.jpg".zfill(16))

    for path in candidates:
        if path.exists():
            return path
    return None


def clamp(value: int, low: int, high: int) -> int:
    return max(low, min(value, high))


def crop_bbox(image: Image.Image, bbox: Sequence[float], padding: float, crop_size: int) -> Image.Image:
    x, y, w, h = bbox
    pad_w = int(round(w * padding))
    pad_h = int(round(h * padding))
    x1 = clamp(int(round(x)) - pad_w, 0, image.width)
    y1 = clamp(int(round(y)) - pad_h, 0, image.height)
    x2 = clamp(int(round(x + w)) + pad_w, 0, image.width)
    y2 = clamp(int(round(y + h)) + pad_h, 0, image.height)
    if x2 <= x1:
        x2 = clamp(x1 + 1, 1, image.width)
    if y2 <= y1:
        y2 = clamp(y1 + 1, 1, image.height)
    return image.crop((x1, y1, x2, y2)).resize((crop_size, crop_size), Image.BILINEAR)


def image_split(img_ids: Sequence[Any], split: float) -> Dict[Any, str]:
    ids = list(img_ids)
    random.seed(SPLIT_SEED)
    random.shuffle(ids)
    cut = int(len(ids) * split)
    return {img_id: ("train" if idx < cut else "val") for idx, img_id in enumerate(ids)}


def export_yolo(
    data: Dataset,
    img_ids: Sequence[Any],
    labels_dir: Path,
    requested_classes: Optional[Set[str]],
    min_box_size: float,
    strict: bool,
) -> Dict[str, int]:
    class_counts: Dict[str, int] = defaultdict(int)
    skipped_images = 0

    for img_id in tqdm(img_ids, desc="Export YOLO labels", disable=not logger.isEnabledFor(logging.INFO)):
        filename = f"{str(img_id)}.txt" if "--" in str(img_id) else f"{str(img_id)}.txt".zfill(16)
        anns = data.get_annotations(img_id)
        if len(anns) == 0:
            # FIXED: do not abort whole export when one image has no annotations
            skipped_images += 1
            continue

        img = data.get_image(img_id)
        rows: List[Tuple[str, float, float, float, float]] = []
        for ann in anns:
            keep_ann, class_name = filter_annotation(ann, data, requested_classes, min_box_size)
            if not keep_ann:
                continue
            if str(ann["category_id"]) == "10":
                continue
            yolo_class = COCO_TO_YOLO.get(str(ann["category_id"]))
            if yolo_class is None:
                continue
            bbox_yolo = box_coco_to_yolo(ann["bbox"], img)
            rows.append((yolo_class, bbox_yolo[0], bbox_yolo[1], bbox_yolo[2], bbox_yolo[3]))
            class_counts[class_name] += 1

        validate_or_warn(all(len(row) == 5 for row in rows), f"Label/vector mismatch for image_id {img_id}.", strict)
        out_dir = labels_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        with open(out_dir / filename, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f, delimiter=" ")
            for row in rows:
                writer.writerow(row)

    logger.info("Skipped %s images without annotations.", skipped_images)
    return class_counts


def export_crops(
    data: Dataset,
    img_ids: Sequence[Any],
    images_dir: Path,
    dataset_name: str,
    output_dir: Path,
    requested_classes: Optional[Set[str]],
    min_box_size: float,
    padding: float,
    crop_size: int,
    split: float,
) -> Dict[str, int]:
    split_map = image_split(img_ids, split)
    class_counts: Dict[str, int] = defaultdict(int)
    missing_images = 0

    for img_id in tqdm(img_ids, desc="Export crops", disable=not logger.isEnabledFor(logging.INFO)):
        anns = data.get_annotations(img_id)
        if not anns:
            continue
        image_meta = data.get_image(img_id)
        img_path = resolve_image_path(images_dir, dataset_name, image_meta, img_id)
        if img_path is None:
            missing_images += 1
            logger.warning("Missing image for image_id %s", img_id)
            continue

        with Image.open(img_path) as image:
            image = image.convert("RGB")
            for idx, ann in enumerate(anns):
                keep_ann, class_name = filter_annotation(ann, data, requested_classes, min_box_size)
                if not keep_ann:
                    continue
                split_name = split_map[img_id]
                crop = crop_bbox(image, ann["bbox"], padding=padding, crop_size=crop_size)
                class_dir = output_dir / split_name / class_name
                class_dir.mkdir(parents=True, exist_ok=True)
                crop_name = f"{img_id}_{ann.get('id', idx)}.jpg"
                crop.save(class_dir / crop_name)
                class_counts[class_name] += 1

    if missing_images:
        logger.warning("Skipped %s images because source files were missing.", missing_images)
    return class_counts


def log_distribution(class_counts: Dict[str, int]) -> None:
    logger.warning("Class distribution report:")
    if not class_counts:
        logger.warning("(empty)")
        return
    for class_name in sorted(class_counts):
        logger.warning("%s: %s", class_name, class_counts[class_name])


def run(
    annotations_dir: Path,
    images_dir: Path,
    dataset_name: str,
    output_dir: Path,
    classes: Optional[Sequence[str]],
    min_box_size: float,
    output_format: str,
    padding: float,
    crop_size: int,
    split: float,
    strict: bool,
) -> None:
    filename = f"instances_{dataset_name}"
    data = Dataset(str(annotations_dir), filename, strict=strict)
    img_ids = data.get_image_ids()
    requested_classes = parse_requested_classes(classes)

    if output_format == "yolo":
        class_counts = export_yolo(
            data=data,
            img_ids=img_ids,
            labels_dir=output_dir / dataset_name,
            requested_classes=requested_classes,
            min_box_size=min_box_size,
            strict=strict,
        )
    else:
        class_counts = export_crops(
            data=data,
            img_ids=img_ids,
            images_dir=images_dir,
            dataset_name=dataset_name,
            output_dir=output_dir,
            requested_classes=requested_classes,
            min_box_size=min_box_size,
            padding=padding,
            crop_size=crop_size,
            split=split,
        )

    log_distribution(class_counts)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(BASE_DIR / "images"), help="Input images directory")
    parser.add_argument("--output", default=str(BASE_DIR / "labels"), help="Output directory")
    parser.add_argument("--annotations", default=str(BASE_DIR / "annotations"), help="COCO annotations directory")
    parser.add_argument("--dataset-name", default="val_new_images", help="Dataset suffix used in instances_<dataset>.json")
    parser.add_argument("--classes", nargs="+", default=None, help="Class names to export (e.g. --classes red green)")
    parser.add_argument("--min-box-size", type=float, default=DEFAULT_MIN_BOX_SIZE, help="Minimum bbox area in pixels^2")
    parser.add_argument("--output-format", choices=["yolo", "crops"], default="yolo", help="Output format")
    parser.add_argument("--padding", type=float, default=DEFAULT_PADDING, help="Crop padding as a fraction")
    parser.add_argument("--crop-size", type=int, default=DEFAULT_CROP_SIZE, help="Square output crop dimension")
    parser.add_argument("--split", type=float, default=DEFAULT_SPLIT, help="Train split ratio for crop export")
    parser.add_argument("--strict", action="store_true", help="Fail on validation mismatches instead of warning")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s:%(name)s:%(message)s",
    )

    run(
        annotations_dir=Path(args.annotations),
        images_dir=Path(args.input),
        dataset_name=args.dataset_name,
        output_dir=Path(args.output),
        classes=args.classes,
        min_box_size=args.min_box_size,
        output_format=args.output_format,
        padding=args.padding,
        crop_size=args.crop_size,
        split=args.split,
        strict=args.strict,
    )
