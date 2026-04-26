#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import logging
import random
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

from PIL import Image
from tqdm import tqdm

BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_SAMPLE_PER_CLASS = 10
EXPECTED_SIZE = (64, 64)

logger = logging.getLogger(__name__)


def gather_split_files(root: Path, split: str) -> Dict[str, List[Path]]:
    out: Dict[str, List[Path]] = defaultdict(list)
    split_root = root / split
    if not split_root.exists():
        return out
    for class_dir in split_root.iterdir():
        if not class_dir.is_dir():
            continue
        out[class_dir.name] = sorted([p for p in class_dir.iterdir() if p.is_file()])
    return out


def sha1_file(path: Path) -> str:
    hasher = hashlib.sha1()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(8192)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def check_dataset(root: Path, sample_per_class: int) -> bool:
    train = gather_split_files(root, "train")
    val = gather_split_files(root, "val")

    if not train or not val:
        logger.error("Missing expected train/val folders under %s", root)
        return False

    ok = True

    all_files = [("train", c, p) for c, files in train.items() for p in files] + [("val", c, p) for c, files in val.items() for p in files]
    logger.warning("Found %s files total.", len(all_files))

    # Corruption + size checks
    for split, cls, path in tqdm(all_files, desc="Validate images", disable=not logger.isEnabledFor(logging.INFO)):
        try:
            with Image.open(path) as img:
                img.verify()
            with Image.open(path) as img2:
                if img2.size != EXPECTED_SIZE:
                    ok = False
                    logger.error("Invalid image size for %s: %s", path, img2.size)
        except OSError as exc:
            ok = False
            logger.error("Corrupted image %s: %s", path, exc)

    # Duplicate hashes across train/val
    train_hashes: Dict[str, List[Path]] = defaultdict(list)
    for _, _, path in tqdm([(s, c, p) for s, c, p in all_files if s == "train"], desc="Hash train", disable=not logger.isEnabledFor(logging.INFO)):
        train_hashes[sha1_file(path)].append(path)

    duplicate_count = 0
    for _, _, path in tqdm([(s, c, p) for s, c, p in all_files if s == "val"], desc="Hash val", disable=not logger.isEnabledFor(logging.INFO)):
        h = sha1_file(path)
        if h in train_hashes:
            duplicate_count += 1
            logger.error("Duplicate content across train/val: %s", path)

    if duplicate_count > 0:
        ok = False

    # Sample summary
    logger.warning("Random sample summary:")
    for split_name, split_data in [("train", train), ("val", val)]:
        for cls in sorted(split_data):
            files = split_data[cls]
            n = min(sample_per_class, len(files))
            sampled = random.sample(files, n) if n > 0 else []
            logger.warning("%s/%s: %s files (sampled %s)", split_name, cls, len(files), len(sampled))

    logger.warning("Final status: %s", "GO" if ok else "NO-GO")
    return ok


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Validate crop dataset integrity")
    parser.add_argument("--input", default=str(BASE_DIR / "labels" / "merged"), help="Input merged crop dataset root")
    parser.add_argument("--output", default=str(BASE_DIR / "labels" / "reports"), help="Reserved output argument")
    parser.add_argument("--annotations", default=str(BASE_DIR / "annotations"), help="Reserved compatibility argument")
    parser.add_argument("--sample-per-class", type=int, default=DEFAULT_SAMPLE_PER_CLASS, help="Random samples per class")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s:%(name)s:%(message)s",
    )

    ok = check_dataset(Path(args.input), args.sample_per_class)
    raise SystemExit(0 if ok else 1)
