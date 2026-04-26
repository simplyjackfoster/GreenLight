#!/usr/bin/env python3

from __future__ import annotations

import argparse
import logging
import shutil
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, List

from tqdm import tqdm

BASE_DIR = Path(__file__).resolve().parents[1]
MIN_PYTHON = (3, 10)
DEFAULT_PROGRESS = True
SPLITS = ("train", "val")
VALID_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}

logger = logging.getLogger(__name__)


def list_split_files(dataset_dir: Path, split: str) -> List[Path]:
    root = dataset_dir / split
    if not root.exists():
        return []
    return [p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in VALID_EXTENSIONS]


def merge_datasets(inputs: List[Path], output: Path, show_progress: bool) -> Counter:
    counts: Counter = Counter()
    output.mkdir(parents=True, exist_ok=True)

    for idx, dataset in enumerate(inputs):
        if not dataset.exists():
            logger.warning("Skipping missing dataset directory: %s", dataset)
            continue

        for split in SPLITS:
            files = list_split_files(dataset, split)
            for src in tqdm(files, desc=f"Merge {dataset.name}/{split}", disable=not show_progress):
                class_name = src.parent.name
                dst_dir = output / split / class_name
                dst_dir.mkdir(parents=True, exist_ok=True)
                dst_name = f"ds{idx}_{dataset.name}_{src.name}"
                dst = dst_dir / dst_name
                try:
                    shutil.copy2(src, dst)
                except OSError as exc:
                    logger.warning("Failed to copy %s -> %s: %s", src, dst, exc)
                    continue
                counts[class_name] += 1

    return counts


def imbalance_ratio(counts: Counter) -> float:
    if not counts:
        return 0.0
    values = [v for v in counts.values() if v > 0]
    if not values:
        return 0.0
    return max(values) / min(values)


def sampler_weights(counts: Counter) -> Dict[str, float]:
    weights: Dict[str, float] = {}
    for cls, n in counts.items():
        if n > 0:
            weights[cls] = 1.0 / float(n)
    return weights


def report(counts: Counter) -> None:
    logger.warning("Combined class distribution:")
    for cls in sorted(counts):
        logger.warning("%s: %s", cls, counts[cls])

    ratio = imbalance_ratio(counts)
    logger.warning("Class imbalance ratio (max/min): %.4f", ratio)

    weights = sampler_weights(counts)
    logger.warning("Recommended WeightedRandomSampler class weights:")
    for cls in sorted(weights):
        logger.warning("%s: %.8f", cls, weights[cls])


if __name__ == "__main__":
    if sys.version_info < MIN_PYTHON:
        raise SystemExit(f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ is required.")

    parser = argparse.ArgumentParser(description="Merge crop datasets and report class imbalance")
    parser.add_argument("--input", nargs="+", required=True, help="Two or more crop dataset directories")
    parser.add_argument("--output", default=str(BASE_DIR / "labels" / "merged"), help="Output merged dataset root")
    parser.add_argument("--annotations", default=str(BASE_DIR / "annotations"), help="Reserved compatibility argument")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    parser.add_argument("--no-progress", action="store_true", help="Disable tqdm progress bars")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s:%(name)s:%(message)s",
    )

    input_dirs = [Path(p) for p in args.input]
    if len(input_dirs) < 2:
        raise ValueError("--input requires at least two dataset directories")

    counts = merge_datasets(
        inputs=input_dirs,
        output=Path(args.output),
        show_progress=DEFAULT_PROGRESS and not args.no_progress,
    )
    report(counts)
