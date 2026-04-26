#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import logging
import random
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

from PIL import Image
from tqdm import tqdm

BASE_DIR = Path(__file__).resolve().parents[1]
MIN_PYTHON = (3, 10)
DEFAULT_SAMPLE_PER_CLASS = 10
EXPECTED_SIZE = (64, 64)
DEFAULT_PROGRESS = True
SPLITS = ("train", "val")
VALID_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
HASH_CHUNK_SIZE = 8192
SAMPLE_SEED = 1881

logger = logging.getLogger(__name__)


def gather_split_files(root: Path, split: str) -> Dict[str, List[Path]]:
    out: Dict[str, List[Path]] = defaultdict(list)
    split_root = root / split
    if not split_root.exists():
        return out
    for class_dir in split_root.iterdir():
        if not class_dir.is_dir():
            continue
        out[class_dir.name] = sorted(
            [p for p in class_dir.iterdir() if p.is_file() and p.suffix.lower() in VALID_EXTENSIONS]
        )
    return out


def sha1_file(path: Path) -> str:
    hasher = hashlib.sha1()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(HASH_CHUNK_SIZE)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def check_dataset(root: Path, sample_per_class: int, expected_size: Tuple[int, int], show_progress: bool) -> bool:
    if sample_per_class <= 0:
        raise ValueError(f"--sample-per-class must be positive, got {sample_per_class}")
    if expected_size[0] <= 0 or expected_size[1] <= 0:
        raise ValueError(f"Expected image size must be positive, got {expected_size}")

    train = gather_split_files(root, SPLITS[0])
    val = gather_split_files(root, SPLITS[1])

    if not train or not val:
        logger.error("Missing expected train/val folders under %s", root)
        return False

    ok = True

    all_files = [(SPLITS[0], c, p) for c, files in train.items() for p in files] + [
        (SPLITS[1], c, p) for c, files in val.items() for p in files
    ]
    logger.warning("Found %s files total.", len(all_files))
    if not all_files:
        logger.error("No crop files found under %s", root)
        return False

    # Corruption + size checks
    for split, cls, path in tqdm(all_files, desc="Validate images", disable=not show_progress):
        try:
            with Image.open(path) as img:
                img.verify()
            with Image.open(path) as img2:
                if img2.size != expected_size:
                    ok = False
                    logger.error("Invalid image size for %s: %s", path, img2.size)
        except OSError as exc:
            ok = False
            logger.error("Corrupted image %s: %s", path, exc)

    # Duplicate hashes across train/val
    train_hashes: Dict[str, List[Path]] = defaultdict(list)
    for _, _, path in tqdm(
        [(s, c, p) for s, c, p in all_files if s == SPLITS[0]],
        desc="Hash train",
        disable=not show_progress,
    ):
        train_hashes[sha1_file(path)].append(path)

    duplicate_count = 0
    for _, _, path in tqdm(
        [(s, c, p) for s, c, p in all_files if s == SPLITS[1]],
        desc="Hash val",
        disable=not show_progress,
    ):
        h = sha1_file(path)
        if h in train_hashes:
            duplicate_count += 1
            logger.error("Duplicate content across train/val: %s", path)

    if duplicate_count > 0:
        ok = False

    # Sample summary
    logger.warning("Random sample summary:")
    random.seed(SAMPLE_SEED)
    for split_name, split_data in [(SPLITS[0], train), (SPLITS[1], val)]:
        for cls in sorted(split_data):
            files = split_data[cls]
            n = min(sample_per_class, len(files))
            sampled = random.sample(files, n) if n > 0 else []
            preview = ", ".join(path.name for path in sampled[:3]) if sampled else "none"
            logger.warning(
                "%s/%s: %s files (sampled %s, preview: %s)",
                split_name,
                cls,
                len(files),
                len(sampled),
                preview,
            )

    logger.warning("Final status: %s", "GO" if ok else "NO-GO")
    return ok


if __name__ == "__main__":
    if sys.version_info < MIN_PYTHON:
        raise SystemExit(f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ is required.")

    parser = argparse.ArgumentParser(description="Validate crop dataset integrity")
    parser.add_argument("--input", default=str(BASE_DIR / "labels" / "merged"), help="Input merged crop dataset root")
    parser.add_argument("--output", default=str(BASE_DIR / "labels" / "reports"), help="Reserved output argument")
    parser.add_argument("--annotations", default=str(BASE_DIR / "annotations"), help="Reserved compatibility argument")
    parser.add_argument("--sample-per-class", type=int, default=DEFAULT_SAMPLE_PER_CLASS, help="Random samples per class")
    parser.add_argument("--expected-size", type=int, default=EXPECTED_SIZE[0], help="Expected square crop size")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    parser.add_argument("--no-progress", action="store_true", help="Disable tqdm progress bars")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s:%(name)s:%(message)s",
    )

    try:
        ok = check_dataset(
            root=Path(args.input),
            sample_per_class=args.sample_per_class,
            expected_size=(args.expected_size, args.expected_size),
            show_progress=DEFAULT_PROGRESS and not args.no_progress,
        )
    except ValueError as exc:
        logger.error("%s", exc)
        raise SystemExit(1) from exc
    raise SystemExit(0 if ok else 1)
