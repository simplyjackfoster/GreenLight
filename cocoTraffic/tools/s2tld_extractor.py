#!/usr/bin/env python3

from __future__ import annotations

import argparse
import logging
import random
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

from PIL import Image
from tqdm import tqdm

BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_MIN_BOX_SIZE = 400.0
DEFAULT_PADDING = 0.15
DEFAULT_CROP_SIZE = 64
DEFAULT_SPLIT = 0.85
SPLIT_SEED = 1881

CLASS_MAP = {
    "red": "red",
    "yellow": "yellow",
    "green": "green",
    "off": "off",
    "wait_on": "yellow",
}

logger = logging.getLogger(__name__)


def bbox_area(box: Tuple[int, int, int, int]) -> float:
    return float(max(0, box[2] - box[0]) * max(0, box[3] - box[1]))


def clamp(v: int, low: int, high: int) -> int:
    return max(low, min(high, v))


def crop_bbox(image: Image.Image, box: Tuple[int, int, int, int], padding: float, crop_size: int) -> Image.Image:
    x1, y1, x2, y2 = box
    w = x2 - x1
    h = y2 - y1
    pad_w = int(round(w * padding))
    pad_h = int(round(h * padding))

    cx1 = clamp(x1 - pad_w, 0, image.width)
    cy1 = clamp(y1 - pad_h, 0, image.height)
    cx2 = clamp(x2 + pad_w, 0, image.width)
    cy2 = clamp(y2 + pad_h, 0, image.height)

    if cx2 <= cx1:
        cx2 = clamp(cx1 + 1, 1, image.width)
    if cy2 <= cy1:
        cy2 = clamp(cy1 + 1, 1, image.height)

    return image.crop((cx1, cy1, cx2, cy2)).resize((crop_size, crop_size), Image.BILINEAR)


def parse_xml(xml_path: Path) -> Tuple[str, List[Tuple[str, Tuple[int, int, int, int]]]]:
    tree = ET.parse(xml_path)
    root = tree.getroot()

    filename = root.findtext("filename")
    if not filename:
        filename = xml_path.with_suffix(".jpg").name

    objects: List[Tuple[str, Tuple[int, int, int, int]]] = []
    for obj in root.findall("object"):
        name = (obj.findtext("name") or "").strip().lower()
        mapped = CLASS_MAP.get(name)
        if mapped is None:
            continue
        bnd = obj.find("bndbox")
        if bnd is None:
            continue
        try:
            xmin = int(float(bnd.findtext("xmin", "0")))
            ymin = int(float(bnd.findtext("ymin", "0")))
            xmax = int(float(bnd.findtext("xmax", "0")))
            ymax = int(float(bnd.findtext("ymax", "0")))
        except ValueError:
            continue
        objects.append((mapped, (xmin, ymin, xmax, ymax)))

    return filename, objects


def split_assignments(image_names: Sequence[str], split: float) -> Dict[str, str]:
    items = list(image_names)
    random.seed(SPLIT_SEED)
    random.shuffle(items)
    cutoff = int(len(items) * split)
    return {name: ("train" if i < cutoff else "val") for i, name in enumerate(items)}


def run(
    input_dir: Path,
    output_dir: Path,
    min_box_size: float,
    padding: float,
    crop_size: int,
    split: float,
) -> Counter:
    xml_files = sorted(input_dir.glob("*.xml"))
    if not xml_files:
        logger.error("No XML files found in %s", input_dir)
        return Counter()

    by_image: Dict[str, List[Tuple[str, Tuple[int, int, int, int]]]] = defaultdict(list)
    for xml_path in tqdm(xml_files, desc="Parse S2TLD XML", disable=not logger.isEnabledFor(logging.INFO)):
        try:
            filename, objects = parse_xml(xml_path)
        except ET.ParseError as exc:
            logger.warning("Skipping malformed XML %s: %s", xml_path, exc)
            continue
        by_image[filename].extend(objects)

    assignments = split_assignments(list(by_image.keys()), split)
    counts: Counter = Counter()

    for filename in tqdm(sorted(by_image.keys()), desc="Export S2TLD crops", disable=not logger.isEnabledFor(logging.INFO)):
        image_path = input_dir / filename
        if not image_path.exists():
            logger.warning("Missing image file for XML entry: %s", image_path)
            continue

        try:
            with Image.open(image_path) as image:
                image = image.convert("RGB")
                for idx, (class_name, box) in enumerate(by_image[filename]):
                    if bbox_area(box) < min_box_size:
                        continue
                    split_name = assignments[filename]
                    out_dir = output_dir / split_name / class_name
                    out_dir.mkdir(parents=True, exist_ok=True)
                    crop = crop_bbox(image, box, padding, crop_size)
                    crop_name = f"{Path(filename).stem}_{idx}.jpg"
                    crop.save(out_dir / crop_name)
                    counts[class_name] += 1
        except OSError as exc:
            logger.warning("Skipping unreadable image %s: %s", image_path, exc)

    return counts


def log_distribution(counts: Counter) -> None:
    logger.warning("Class distribution report:")
    if not counts:
        logger.warning("(empty)")
        return
    for class_name in sorted(counts):
        logger.warning("%s: %s", class_name, counts[class_name])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract S2TLD crops into train/val/class folders")
    parser.add_argument("--input", default=str(BASE_DIR / "tools" / "s2tld"), help="Input directory containing XML and image files")
    parser.add_argument("--output", default=str(BASE_DIR / "labels" / "s2tld"), help="Output root directory")
    parser.add_argument("--annotations", default=str(BASE_DIR / "annotations"), help="Reserved compatibility argument")
    parser.add_argument("--min-box-size", type=float, default=DEFAULT_MIN_BOX_SIZE, help="Minimum bbox area in pixels^2")
    parser.add_argument("--padding", type=float, default=DEFAULT_PADDING, help="Crop padding ratio")
    parser.add_argument("--crop-size", type=int, default=DEFAULT_CROP_SIZE, help="Crop output size")
    parser.add_argument("--split", type=float, default=DEFAULT_SPLIT, help="Train split ratio")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s:%(name)s:%(message)s",
    )

    counts = run(
        input_dir=Path(args.input),
        output_dir=Path(args.output),
        min_box_size=args.min_box_size,
        padding=args.padding,
        crop_size=args.crop_size,
        split=args.split,
    )
    log_distribution(counts)
