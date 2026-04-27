#!/usr/bin/env python3
"""Run the traffic-light state classifier pipeline end to end.

This script keeps the repeatable path intentionally narrow:
1. build the four-class crop dataset expected by train.py,
2. train the classifier with a sensible CUDA/CPU default,
3. export the winning checkpoint to Core ML.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


DEFAULT_RAW_LISA = Path("export/datasets/raw/lisa")
DEFAULT_RAW_S2TLD = Path("export/datasets/raw/s2tld")
DEFAULT_RAW_BSTLD = Path("export/datasets/raw/bstld")
DEFAULT_DATA_ROOT = Path("export/datasets/crops/traffic_state")
DEFAULT_CHECKPOINTS = Path("export/models/checkpoints")
DEFAULT_COREML = Path("export/models/coreml")
DEFAULT_TORCH_HOME = Path("export/models/torch_cache")


def run(command: list[str], env: dict[str, str]) -> None:
    print("+ " + " ".join(command), flush=True)
    subprocess.run(command, check=True, env=env)


def detect_device(requested: str) -> str:
    if requested != "auto":
        return requested
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
    except Exception:
        pass
    return "cpu"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build, train, and export the traffic-light state classifier")
    parser.add_argument("--lisa-root", type=Path, default=DEFAULT_RAW_LISA)
    parser.add_argument("--s2tld-root", type=Path, default=DEFAULT_RAW_S2TLD)
    parser.add_argument("--bstld-root", type=Path, default=DEFAULT_RAW_BSTLD)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--checkpoints-dir", type=Path, default=DEFAULT_CHECKPOINTS)
    parser.add_argument("--coreml-dir", type=Path, default=DEFAULT_COREML)
    parser.add_argument("--torch-home", type=Path, default=DEFAULT_TORCH_HOME)

    parser.add_argument("--models", default="mobilenet_v3_small")
    parser.add_argument("--epochs", type=int, default=40)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--num-workers", type=int, default=4)
    parser.add_argument("--device", choices=["auto", "cpu", "mps", "cuda"], default="auto")

    parser.add_argument("--skip-dataset", action="store_true")
    parser.add_argument("--skip-train", action="store_true")
    parser.add_argument("--skip-export", action="store_true")
    parser.add_argument(
        "--skip-parity-check",
        action="store_true",
        default=sys.platform.startswith("win"),
        help="Skip Core ML prediction parity validation. Defaults on for Windows coremltools exports.",
    )
    parser.add_argument("--clean-output", action="store_true", default=True)
    parser.add_argument("--no-clean-output", dest="clean_output", action="store_false")
    parser.add_argument("--no-progress", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    device = detect_device(args.device)

    env = os.environ.copy()
    env["TORCH_HOME"] = str(args.torch_home)

    if not args.skip_dataset:
        dataset_cmd = [
            sys.executable,
            "dataset_pipeline.py",
            "--lisa-root",
            str(args.lisa_root),
            "--s2tld-root",
            str(args.s2tld_root),
            "--bstld-root",
            str(args.bstld_root),
            "--output-root",
            str(args.data_root),
            "--non-interactive",
        ]
        if args.clean_output:
            dataset_cmd.append("--clean-output")
        if args.no_progress:
            dataset_cmd.append("--no-progress")
        run(dataset_cmd, env)

    if not args.skip_train:
        train_cmd = [
            sys.executable,
            "train.py",
            "--data-root",
            str(args.data_root),
            "--output-root",
            str(args.checkpoints_dir),
            "--models",
            args.models,
            "--epochs",
            str(args.epochs),
            "--batch-size",
            str(args.batch_size),
            "--num-workers",
            str(args.num_workers),
            "--device",
            device,
        ]
        if args.no_progress:
            train_cmd.append("--no-progress")
        run(train_cmd, env)

    if not args.skip_export:
        export_cmd = [
            sys.executable,
            "export_coreml.py",
            "--checkpoints-dir",
            str(args.checkpoints_dir),
            "--data-root",
            str(args.data_root),
            "--output-dir",
            str(args.coreml_dir),
            "--device",
            device,
        ]
        if args.no_progress:
            export_cmd.append("--no-progress")
        if args.skip_parity_check:
            export_cmd.append("--skip-parity-check")
        run(export_cmd, env)


if __name__ == "__main__":
    main()
