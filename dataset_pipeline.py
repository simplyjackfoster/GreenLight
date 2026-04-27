#!/usr/bin/env python3
"""Build a unified traffic-light state crop dataset from public sources.

Supported sources:
- LISA Traffic Light Dataset (CSV annotations)
- S2TLD (Pascal VOC XML annotations)
- Bosch Small Traffic Lights Dataset / BSTLD (YAML annotations)

Outputs train/val class folders with 64x64 crops and reports class imbalance
recommendations for WeightedRandomSampler.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import random
import shutil
import sys
import textwrap
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml
from tqdm import tqdm

try:
    import cv2
except ModuleNotFoundError:
    cv2 = None  # type: ignore[assignment]

MIN_PYTHON = (3, 10)

DEFAULT_SPLIT_RATIO = 0.85
DEFAULT_PADDING_RATIO = 0.15
DEFAULT_CROP_SIZE = 64
DEFAULT_MIN_BOX_AREA = 16.0
DEFAULT_SEED = 20260426
DEFAULT_JPEG_QUALITY = 95

TARGET_CLASSES = ("red", "green", "yellow", "off")
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp", ".webp")
LISA_BOX_FILENAME = "frameAnnotationsBOX.csv"

SPLIT_TRAIN = "train"
SPLIT_VAL = "val"

logger = logging.getLogger("dataset_pipeline")


@dataclass(frozen=True)
class AnnotationRecord:
    dataset: str
    image_path: Path
    bbox_xyxy: tuple[float, float, float, float]
    label: str
    raw_label: str


def ensure_python_version() -> None:
    if sys.version_info < MIN_PYTHON:
        raise SystemExit(f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ is required")


def clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def bbox_area(x1: float, y1: float, x2: float, y2: float) -> float:
    return max(0.0, x2 - x1) * max(0.0, y2 - y1)


def normalize_lisa_label(raw_label: str) -> str | None:
    label = raw_label.strip().lower().replace("-", " ").replace("_", " ")

    if "off" in label or "dark" in label or "black" in label:
        return "off"

    red_tokens = ("stop", "red")
    green_tokens = ("go", "green")
    yellow_tokens = ("warning", "yellow", "amber")

    if any(token in label for token in red_tokens):
        return "red"
    if any(token in label for token in green_tokens):
        return "green"
    if any(token in label for token in yellow_tokens):
        return "yellow"
    return None


def normalize_s2tld_label(raw_label: str) -> str | None:
    key = raw_label.strip().lower()
    mapping = {
        "red": "red",
        "green": "green",
        "yellow": "yellow",
        "off": "off",
        "wait_on": "yellow",
    }
    return mapping.get(key)


def normalize_bstld_label(raw_label: str) -> str | None:
    key = raw_label.strip().lower()
    if key == "off":
        return "off"
    if key.startswith("green"):
        return "green"
    if key.startswith("red"):
        return "red"
    if key.startswith("yellow"):
        return "yellow"
    return None


def build_image_index(root: Path) -> dict[str, list[Path]]:
    index: dict[str, list[Path]] = defaultdict(list)
    for ext in IMAGE_EXTENSIONS:
        for path in root.rglob(f"*{ext}"):
            index[path.name].append(path)
    return index


def resolve_image_path(
    root: Path,
    image_index: dict[str, list[Path]],
    rel_paths: Iterable[str],
) -> Path | None:
    candidates: list[Path] = []
    for rel_path in rel_paths:
        clean = rel_path.strip()
        if not clean:
            continue
        clean_path = Path(clean)
        candidates.append(root / clean_path)
        candidates.append(root / clean.lstrip("./"))
        candidates.append(root / clean_path.name)

    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate

    # Fall back to filename-based index resolution.
    names = [Path(r).name for r in rel_paths if r.strip()]
    for name in names:
        matches = image_index.get(name, [])
        if matches:
            return sorted(matches)[0]
    return None


def parse_lisa(
    lisa_root: Path,
    min_box_area: float,
    strict: bool,
    show_progress: bool,
) -> list[AnnotationRecord]:
    image_index = build_image_index(lisa_root)

    csv_paths = sorted(lisa_root.rglob(LISA_BOX_FILENAME))
    if not csv_paths:
        msg = f"No {LISA_BOX_FILENAME} files found under {lisa_root}"
        if strict:
            raise FileNotFoundError(msg)
        logger.warning(msg)
        return []

    records: list[AnnotationRecord] = []
    skipped_unmapped = 0
    skipped_missing_image = 0

    for csv_path in tqdm(csv_paths, desc="Parse LISA CSV", disable=not show_progress):
        with csv_path.open("r", encoding="utf-8") as handle:
            reader = csv.DictReader(handle, delimiter=";")
            for row in reader:
                raw_label = (row.get("Annotation tag") or "").strip()
                label = normalize_lisa_label(raw_label)
                if label is None:
                    skipped_unmapped += 1
                    continue

                filename = row.get("Filename", "")
                origin_file = row.get("Origin file", "")
                image_path = resolve_image_path(lisa_root, image_index, [filename, origin_file])
                if image_path is None:
                    skipped_missing_image += 1
                    continue

                try:
                    x1 = float(row["Upper left corner X"])
                    y1 = float(row["Upper left corner Y"])
                    x2 = float(row["Lower right corner X"])
                    y2 = float(row["Lower right corner Y"])
                except (KeyError, ValueError):
                    continue

                if x2 < x1:
                    x1, x2 = x2, x1
                if y2 < y1:
                    y1, y2 = y2, y1
                if bbox_area(x1, y1, x2, y2) < min_box_area:
                    continue

                records.append(
                    AnnotationRecord(
                        dataset="lisa",
                        image_path=image_path,
                        bbox_xyxy=(x1, y1, x2, y2),
                        label=label,
                        raw_label=raw_label,
                    )
                )

    logger.warning(
        "LISA parsed: %d records, skipped unmapped labels=%d, missing images=%d",
        len(records),
        skipped_unmapped,
        skipped_missing_image,
    )
    return records


def parse_s2tld(
    s2tld_root: Path,
    min_box_area: float,
    strict: bool,
    show_progress: bool,
) -> list[AnnotationRecord]:
    image_index = build_image_index(s2tld_root)
    xml_paths = sorted(s2tld_root.rglob("*.xml"))
    if not xml_paths:
        msg = f"No XML annotations found under {s2tld_root}"
        if strict:
            raise FileNotFoundError(msg)
        logger.warning(msg)
        return []

    records: list[AnnotationRecord] = []
    skipped_unmapped = 0
    skipped_missing_image = 0

    for xml_path in tqdm(xml_paths, desc="Parse S2TLD XML", disable=not show_progress):
        try:
            tree = ET.parse(xml_path)
        except ET.ParseError as exc:
            if strict:
                raise
            logger.warning("Skipping malformed XML %s: %s", xml_path, exc)
            continue

        root = tree.getroot()
        filename = (root.findtext("filename") or f"{xml_path.stem}.jpg").strip()

        image_path = resolve_image_path(
            s2tld_root,
            image_index,
            [filename, str(xml_path.parent / filename)],
        )
        if image_path is None:
            skipped_missing_image += 1
            continue

        for obj in root.findall("object"):
            raw_label = (obj.findtext("name") or "").strip()
            label = normalize_s2tld_label(raw_label)
            if label is None:
                skipped_unmapped += 1
                continue

            bnd = obj.find("bndbox")
            if bnd is None:
                continue

            try:
                x1 = float(bnd.findtext("xmin", "0"))
                y1 = float(bnd.findtext("ymin", "0"))
                x2 = float(bnd.findtext("xmax", "0"))
                y2 = float(bnd.findtext("ymax", "0"))
            except ValueError:
                continue

            if x2 < x1:
                x1, x2 = x2, x1
            if y2 < y1:
                y1, y2 = y2, y1
            if bbox_area(x1, y1, x2, y2) < min_box_area:
                continue

            records.append(
                AnnotationRecord(
                    dataset="s2tld",
                    image_path=image_path,
                    bbox_xyxy=(x1, y1, x2, y2),
                    label=label,
                    raw_label=raw_label,
                )
            )

    logger.warning(
        "S2TLD parsed: %d records, skipped unmapped labels=%d, missing images=%d",
        len(records),
        skipped_unmapped,
        skipped_missing_image,
    )
    return records


def parse_bstld(
    bstld_root: Path,
    yaml_files: list[Path],
    min_box_area: float,
    strict: bool,
    show_progress: bool,
) -> list[AnnotationRecord]:
    image_index = build_image_index(bstld_root)
    records: list[AnnotationRecord] = []
    skipped_unmapped = 0
    skipped_missing_image = 0

    for yaml_path in tqdm(yaml_files, desc="Parse BSTLD YAML", disable=not show_progress):
        if not yaml_path.exists():
            if strict:
                raise FileNotFoundError(f"Missing BSTLD annotation file: {yaml_path}")
            logger.warning("Skipping missing BSTLD YAML: %s", yaml_path)
            continue

        with yaml_path.open("r", encoding="utf-8") as handle:
            data: Any = yaml.safe_load(handle)

        if not isinstance(data, list):
            if strict:
                raise ValueError(f"Invalid BSTLD YAML format: {yaml_path}")
            logger.warning("Skipping invalid BSTLD YAML (not list): %s", yaml_path)
            continue

        for image_entry in data:
            if not isinstance(image_entry, dict):
                continue

            rel_path = str(image_entry.get("path", "")).strip()
            image_path = resolve_image_path(bstld_root, image_index, [rel_path])
            if image_path is None:
                skipped_missing_image += 1
                continue

            boxes = image_entry.get("boxes", [])
            if not isinstance(boxes, list):
                continue

            for box in boxes:
                if not isinstance(box, dict):
                    continue

                raw_label = str(box.get("label", "")).strip()
                label = normalize_bstld_label(raw_label)
                if label is None:
                    skipped_unmapped += 1
                    continue

                try:
                    x1 = float(box["x_min"])
                    y1 = float(box["y_min"])
                    x2 = float(box["x_max"])
                    y2 = float(box["y_max"])
                except (KeyError, ValueError):
                    continue

                if x2 < x1:
                    x1, x2 = x2, x1
                if y2 < y1:
                    y1, y2 = y2, y1
                if bbox_area(x1, y1, x2, y2) < min_box_area:
                    continue

                records.append(
                    AnnotationRecord(
                        dataset="bstld",
                        image_path=image_path,
                        bbox_xyxy=(x1, y1, x2, y2),
                        label=label,
                        raw_label=raw_label,
                    )
                )

    logger.warning(
        "BSTLD parsed: %d records, skipped unmapped labels=%d, missing images=%d",
        len(records),
        skipped_unmapped,
        skipped_missing_image,
    )
    return records


def split_stratified(
    records: list[AnnotationRecord],
    split_ratio: float,
    seed: int,
) -> tuple[list[AnnotationRecord], list[AnnotationRecord]]:
    by_class: dict[str, list[AnnotationRecord]] = defaultdict(list)
    for rec in records:
        by_class[rec.label].append(rec)

    rng = random.Random(seed)
    train_records: list[AnnotationRecord] = []
    val_records: list[AnnotationRecord] = []

    for class_name in TARGET_CLASSES:
        items = by_class.get(class_name, [])
        if not items:
            continue
        rng.shuffle(items)

        if len(items) == 1:
            train_count = 1
        else:
            provisional = int(len(items) * split_ratio)
            train_count = max(1, min(len(items) - 1, provisional))

        train_records.extend(items[:train_count])
        val_records.extend(items[train_count:])

    rng.shuffle(train_records)
    rng.shuffle(val_records)
    return train_records, val_records


def crop_with_padding(
    image: Any,
    bbox_xyxy: tuple[float, float, float, float],
    padding_ratio: float,
    crop_size: int,
) -> Any:
    if cv2 is None:
        raise RuntimeError("OpenCV is required. Install with: pip install opencv-python")
    x1, y1, x2, y2 = bbox_xyxy
    h, w = image.shape[:2]

    bw = max(1.0, x2 - x1)
    bh = max(1.0, y2 - y1)
    pad_x = bw * padding_ratio
    pad_y = bh * padding_ratio

    cx1 = clamp(int(round(x1 - pad_x)), 0, w - 1)
    cy1 = clamp(int(round(y1 - pad_y)), 0, h - 1)
    cx2 = clamp(int(round(x2 + pad_x)), 1, w)
    cy2 = clamp(int(round(y2 + pad_y)), 1, h)

    if cx2 <= cx1:
        cx2 = clamp(cx1 + 1, 1, w)
    if cy2 <= cy1:
        cy2 = clamp(cy1 + 1, 1, h)

    crop = image[cy1:cy2, cx1:cx2]
    return cv2.resize(crop, (crop_size, crop_size), interpolation=cv2.INTER_LINEAR)


def export_crops(
    records: list[AnnotationRecord],
    split_name: str,
    output_root: Path,
    padding_ratio: float,
    crop_size: int,
    show_progress: bool,
) -> Counter:
    if cv2 is None:
        raise RuntimeError("OpenCV is required. Install with: pip install opencv-python")
    counts: Counter = Counter()

    for index, rec in enumerate(tqdm(records, desc=f"Export {split_name}", disable=not show_progress)):
        image = cv2.imread(str(rec.image_path), cv2.IMREAD_COLOR)
        if image is None:
            logger.warning("Unreadable image: %s", rec.image_path)
            continue

        crop = crop_with_padding(image, rec.bbox_xyxy, padding_ratio, crop_size)

        out_dir = output_root / split_name / rec.label
        out_dir.mkdir(parents=True, exist_ok=True)

        base = rec.image_path.stem
        out_name = f"{rec.dataset}_{base}_{index:07d}.jpg"
        out_path = out_dir / out_name

        ok = cv2.imwrite(str(out_path), crop, [int(cv2.IMWRITE_JPEG_QUALITY), DEFAULT_JPEG_QUALITY])
        if not ok:
            logger.warning("Failed to write crop: %s", out_path)
            continue

        counts[rec.label] += 1

    return counts


def dataset_distribution(records: list[AnnotationRecord]) -> dict[str, Counter]:
    report: dict[str, Counter] = defaultdict(Counter)
    for rec in records:
        report[rec.dataset][rec.label] += 1
    return report


def compute_class_weights(train_counts: Counter) -> dict[str, float]:
    return {cls: (1.0 / float(train_counts[cls])) for cls in TARGET_CLASSES if train_counts[cls] > 0}


def print_distribution(
    all_records: list[AnnotationRecord],
    train_counts: Counter,
    val_counts: Counter,
    class_weights: dict[str, float],
) -> None:
    logger.warning("\n=== Class Distribution Report ===")
    total_counts = Counter(rec.label for rec in all_records)

    logger.warning("Overall:")
    for cls in TARGET_CLASSES:
        logger.warning("  %s: %d", cls, total_counts[cls])

    by_dataset = dataset_distribution(all_records)
    logger.warning("By dataset:")
    for dataset_name in sorted(by_dataset):
        line = ", ".join(f"{cls}={by_dataset[dataset_name][cls]}" for cls in TARGET_CLASSES)
        logger.warning("  %s: %s", dataset_name, line)

    logger.warning("Train split:")
    for cls in TARGET_CLASSES:
        logger.warning("  %s: %d", cls, train_counts[cls])

    logger.warning("Val split:")
    for cls in TARGET_CLASSES:
        logger.warning("  %s: %d", cls, val_counts[cls])

    logger.warning("Recommended WeightedRandomSampler class weights (1/freq):")
    for cls in TARGET_CLASSES:
        logger.warning("  %s: %.8f", cls, class_weights.get(cls, 0.0))


def write_manifests(
    output_root: Path,
    train_records: list[AnnotationRecord],
    val_records: list[AnnotationRecord],
    class_weights: dict[str, float],
    args: argparse.Namespace,
) -> None:
    manifests_dir = output_root / "manifests"
    manifests_dir.mkdir(parents=True, exist_ok=True)

    for name, records in ((SPLIT_TRAIN, train_records), (SPLIT_VAL, val_records)):
        path = manifests_dir / f"{name}_records.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["dataset", "image_path", "x1", "y1", "x2", "y2", "label", "raw_label"])
            for rec in records:
                x1, y1, x2, y2 = rec.bbox_xyxy
                writer.writerow([rec.dataset, str(rec.image_path), x1, y1, x2, y2, rec.label, rec.raw_label])

    meta = {
        "target_classes": list(TARGET_CLASSES),
        "class_weights": class_weights,
        "split_ratio": args.split_ratio,
        "padding_ratio": args.padding,
        "crop_size": args.crop_size,
        "min_box_area": args.min_box_area,
        "seed": args.seed,
        "augmentations_note": (
            "Augmentations are intentionally excluded from preprocessing and should be "
            "applied in train.py: brightness/contrast/hue jitter, blur, rotation, "
            "flip, cutout, ImageNet normalization."
        ),
    }
    with (manifests_dir / "sampling_weights.json").open("w", encoding="utf-8") as handle:
        json.dump(meta, handle, indent=2)


def ensure_dataset_available(name: str, root: Path, instructions: str, non_interactive: bool) -> None:
    if root.exists():
        return

    logger.warning("\n%s dataset folder is missing: %s", name, root)
    logger.warning(instructions)

    if non_interactive:
        raise SystemExit(f"Missing required dataset: {name} ({root})")

    input("\nPress Enter after downloading and extracting this dataset, or Ctrl+C to abort... ")

    if not root.exists():
        raise SystemExit(f"Dataset still missing after pause: {name} ({root})")


def manual_download_instructions(name: str) -> str:
    if name == "lisa":
        return textwrap.dedent(
            """
            Manual download required for LISA Traffic Light Dataset.
            1) Open: https://www.kaggle.com/datasets/mbornoe/lisa-traffic-light-dataset
            2) Download and extract to the path passed as --lisa-root.
            3) Ensure CSV files like frameAnnotationsBOX.csv and image frame folders are present.
            """
        ).strip()

    if name == "s2tld":
        return textwrap.dedent(
            """
            Manual download required for S2TLD.
            1) Open: https://github.com/Thinklab-SJTU/S2TLD
            2) Download from linked mirrors (Hugging Face / OneDrive / Baidu) and extract to --s2tld-root.
            3) Ensure XML annotations and image files are both present.
            """
        ).strip()

    if name == "bstld":
        return textwrap.dedent(
            """
            Manual download required for BSTLD images (labels are public YAML files).
            1) Open: https://github.com/bosch-ros-pkg/bstld/tree/master/label_files
            2) Follow the label_files/README.md image archive links and license terms.
            3) Extract RGB image folders and YAML label files under --bstld-root.
            """
        ).strip()

    return "Manual download instructions unavailable."


def parse_bstld_yaml_args(bstld_root: Path, names_csv: str) -> list[Path]:
    files: list[Path] = []
    for raw_name in names_csv.split(","):
        name = raw_name.strip()
        if not name:
            continue
        files.append(bstld_root / name)
    return files


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create 64x64 red/green/yellow/off crops from LISA + S2TLD + BSTLD"
    )
    parser.add_argument("--lisa-root", type=Path, default=Path("export/datasets/raw/lisa"))
    parser.add_argument("--s2tld-root", type=Path, default=Path("export/datasets/raw/s2tld"))
    parser.add_argument("--bstld-root", type=Path, default=Path("export/datasets/raw/bstld"))
    parser.add_argument("--bstld-yaml-files", default="train.yaml,test.yaml,additional_train.yaml")
    parser.add_argument("--output-root", type=Path, default=Path("export/datasets/crops/traffic_state"))

    parser.add_argument("--split-ratio", type=float, default=DEFAULT_SPLIT_RATIO)
    parser.add_argument("--padding", type=float, default=DEFAULT_PADDING_RATIO)
    parser.add_argument("--crop-size", type=int, default=DEFAULT_CROP_SIZE)
    parser.add_argument("--min-box-area", type=float, default=DEFAULT_MIN_BOX_AREA)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)

    parser.add_argument("--clean-output", action="store_true", help="Delete existing output root before export")
    parser.add_argument("--strict", action="store_true", help="Fail fast on malformed/missing expected files")
    parser.add_argument("--non-interactive", action="store_true", help="Do not pause for manual dataset download")
    parser.add_argument("--no-progress", action="store_true", help="Disable tqdm progress bars")
    parser.add_argument("--verbose", action="store_true")

    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    if not (0.0 < args.split_ratio < 1.0):
        raise ValueError("--split-ratio must be between 0 and 1")
    if args.padding < 0.0:
        raise ValueError("--padding must be >= 0")
    if args.crop_size <= 0:
        raise ValueError("--crop-size must be > 0")
    if args.min_box_area < 0.0:
        raise ValueError("--min-box-area must be >= 0")


def main() -> None:
    ensure_python_version()
    args = parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s:%(name)s:%(message)s",
    )

    validate_args(args)
    show_progress = not args.no_progress

    ensure_dataset_available("lisa", args.lisa_root, manual_download_instructions("lisa"), args.non_interactive)
    ensure_dataset_available("s2tld", args.s2tld_root, manual_download_instructions("s2tld"), args.non_interactive)
    ensure_dataset_available("bstld", args.bstld_root, manual_download_instructions("bstld"), args.non_interactive)

    bstld_yaml_files = parse_bstld_yaml_args(args.bstld_root, args.bstld_yaml_files)

    all_records: list[AnnotationRecord] = []
    all_records.extend(parse_lisa(args.lisa_root, args.min_box_area, args.strict, show_progress))
    all_records.extend(parse_s2tld(args.s2tld_root, args.min_box_area, args.strict, show_progress))
    all_records.extend(parse_bstld(args.bstld_root, bstld_yaml_files, args.min_box_area, args.strict, show_progress))

    if not all_records:
        raise SystemExit("No valid annotations found across datasets.")

    train_records, val_records = split_stratified(all_records, args.split_ratio, args.seed)

    if args.clean_output and args.output_root.exists():
        shutil.rmtree(args.output_root)
    args.output_root.mkdir(parents=True, exist_ok=True)

    train_counts = export_crops(
        train_records,
        SPLIT_TRAIN,
        args.output_root,
        args.padding,
        args.crop_size,
        show_progress,
    )
    val_counts = export_crops(
        val_records,
        SPLIT_VAL,
        args.output_root,
        args.padding,
        args.crop_size,
        show_progress,
    )

    class_weights = compute_class_weights(train_counts)
    print_distribution(all_records, train_counts, val_counts, class_weights)
    write_manifests(args.output_root, train_records, val_records, class_weights, args)

    logger.warning("\nDone. Output directory: %s", args.output_root)
    logger.warning("Manifest files: %s", args.output_root / "manifests")


if __name__ == "__main__":
    main()
