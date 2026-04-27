#!/usr/bin/env python3
"""Export a trained traffic-light state classifier to Core ML.

Primary path uses MultiArray input (1,3,64,64) for exact parity with PyTorch
normalization. Optional image input is supported for CVPixelBuffer pipelines.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image
from tqdm import tqdm

try:
    import torch
    import torch.nn as nn
    from torchvision import datasets, models, transforms
except ModuleNotFoundError:
    torch = None  # type: ignore[assignment]
    nn = Any  # type: ignore[assignment]
    datasets = None  # type: ignore[assignment]
    models = None  # type: ignore[assignment]
    transforms = None  # type: ignore[assignment]

try:
    import coremltools as ct
except ModuleNotFoundError:
    ct = None  # type: ignore[assignment]

MIN_PYTHON = (3, 10)

DEFAULT_CHECKPOINTS_DIR = Path("export/models/checkpoints")
DEFAULT_DATA_ROOT = Path("export/datasets/crops/traffic_state")
DEFAULT_OUTPUT_DIR = Path("export/models/coreml")
DEFAULT_IMAGE_SIZE = 64
DEFAULT_VALIDATION_SAMPLES = 20
DEFAULT_SEED = 20260426

IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)

logger = logging.getLogger("export_coreml")


@dataclass(frozen=True)
class ValidationSummary:
    samples_used: int
    top1_matches: int
    top1_match_rate: float
    mean_abs_prob_diff: float


def ensure_python_version() -> None:
    if sys.version_info < MIN_PYTHON:
        raise SystemExit(f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ is required")


def ensure_dependencies() -> None:
    missing: list[str] = []
    if torch is None or datasets is None or models is None or transforms is None:
        missing.append("torch/torchvision")
    if ct is None:
        missing.append("coremltools")
    if missing:
        raise SystemExit(
            "Missing dependencies: "
            + ", ".join(missing)
            + ". Install with: pip install torch torchvision coremltools pillow tqdm numpy timm"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export winning classifier checkpoint to Core ML (.mlpackage)")
    parser.add_argument("--checkpoints-dir", type=Path, default=DEFAULT_CHECKPOINTS_DIR)
    parser.add_argument("--training-report", type=Path, default=None, help="Path to training_report.json; defaults to <checkpoints-dir>/training_report.json")
    parser.add_argument("--checkpoint", type=Path, default=None, help="Explicit checkpoint path. If omitted, uses winner from training_report.json")
    parser.add_argument("--model-name", default=None, help="Override model name (mobilenet_v3_small or efficientnet_lite0)")

    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT, help="Dataset root containing val/ for parity validation")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--output-name", default="traffic_light_state_classifier", help="Output basename without extension")

    parser.add_argument("--image-size", type=int, default=DEFAULT_IMAGE_SIZE)
    parser.add_argument("--validation-samples", type=int, default=DEFAULT_VALIDATION_SAMPLES)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)

    parser.add_argument("--input-type", choices=["multiarray", "image"], default="multiarray", help="Core ML model input type")
    parser.add_argument("--author", default="GreenLight")
    parser.add_argument("--version", default="1.0.0")
    parser.add_argument("--description", default="Traffic light state classifier: red/green/yellow/off")

    parser.add_argument("--device", choices=["auto", "cpu", "mps", "cuda"], default="auto")
    parser.add_argument(
        "--skip-normalization-check",
        action="store_true",
        help="Skip multiarray vs image-mode normalization divergence check",
    )
    parser.add_argument("--no-progress", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def resolve_device(flag: str) -> torch.device:
    if flag == "auto":
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return torch.device("mps")
        if torch.cuda.is_available():
            return torch.device("cuda")
        return torch.device("cpu")

    device = torch.device(flag)
    if device.type == "mps" and not (hasattr(torch.backends, "mps") and torch.backends.mps.is_available()):
        raise SystemExit("Requested --device mps but MPS is unavailable")
    if device.type == "cuda" and not torch.cuda.is_available():
        raise SystemExit("Requested --device cuda but CUDA is unavailable")
    return device


def build_model(model_name: str, num_classes: int) -> nn.Module:
    if model_name == "mobilenet_v3_small":
        model = models.mobilenet_v3_small(weights=None)
        in_features = model.classifier[-1].in_features
        model.classifier[-1] = nn.Linear(in_features, num_classes)
        return model

    if model_name == "efficientnet_lite0":
        try:
            import timm  # type: ignore
        except ModuleNotFoundError as exc:
            raise SystemExit("efficientnet_lite0 requires timm. Install with: pip install timm") from exc
        model = timm.create_model("efficientnet_lite0", pretrained=False, num_classes=num_classes)
        return model

    raise ValueError(f"Unsupported model: {model_name}")


def find_winner_checkpoint(args: argparse.Namespace) -> tuple[str, Path]:
    if args.checkpoint is not None:
        if not args.checkpoint.exists():
            raise SystemExit(f"Checkpoint not found: {args.checkpoint}")
        if args.model_name is None:
            payload = torch.load(str(args.checkpoint), map_location="cpu")
            inferred = str(payload.get("model_name", "")).strip()
            if not inferred:
                raise SystemExit("--model-name is required when checkpoint lacks model_name metadata")
            return inferred, args.checkpoint
        return args.model_name, args.checkpoint

    training_report = args.training_report or (args.checkpoints_dir / "training_report.json")
    if not training_report.exists():
        raise SystemExit(f"Training report not found: {training_report}")

    with training_report.open("r", encoding="utf-8") as handle:
        report = json.load(handle)

    summaries = report.get("summaries", [])
    if not summaries:
        raise SystemExit(f"No model summaries in {training_report}")

    winner = max(summaries, key=lambda s: float(s.get("best_val_accuracy", -1.0)))
    model_name = str(winner.get("model_name", "")).strip()
    ckpt_path = Path(str(winner.get("checkpoint_path", "")).strip())

    if not model_name:
        raise SystemExit(f"Winner summary missing model_name in {training_report}")

    if not ckpt_path.exists():
        fallback = args.checkpoints_dir / f"best_{model_name}.pt"
        if fallback.exists():
            ckpt_path = fallback
        else:
            raise SystemExit(f"Winner checkpoint missing: {ckpt_path}")

    return model_name, ckpt_path


def build_val_dataset(data_root: Path, image_size: int) -> tuple[Any, dict[int, str], list[str]]:
    val_dir = data_root / "val"
    if not val_dir.exists():
        raise SystemExit(f"Validation split directory not found: {val_dir}")

    tfm = transforms.Compose(
        [
            transforms.Resize((image_size, image_size)),
            transforms.ToTensor(),
            transforms.Normalize(mean=IMAGENET_MEAN, std=IMAGENET_STD),
        ]
    )
    dataset = datasets.ImageFolder(str(val_dir), transform=tfm)
    if len(dataset) == 0:
        raise SystemExit(f"Validation dataset is empty: {val_dir}")

    idx_to_class = {idx: name for name, idx in dataset.class_to_idx.items()}
    class_labels = [idx_to_class[i] for i in range(len(idx_to_class))]
    return dataset, idx_to_class, class_labels


def trace_model(model: nn.Module, image_size: int) -> Any:
    model.eval()
    example = torch.randn(1, 3, image_size, image_size)
    with torch.no_grad():
        traced = torch.jit.trace(model, example)
    return traced


def convert_to_coreml(
    traced_model: Any,
    input_type: str,
    image_size: int,
    class_labels: list[str],
) -> Any:
    classifier_config = ct.ClassifierConfig(class_labels)

    if input_type == "multiarray":
        inputs = [ct.TensorType(name="input", shape=(1, 3, image_size, image_size), dtype=np.float32)]
    else:
        # CVPixelBuffer path. Uses unified scale + channel bias approximation.
        scale = 1.0 / (255.0 * float(np.mean(IMAGENET_STD)))
        bias = [
            -IMAGENET_MEAN[0] / IMAGENET_STD[0],
            -IMAGENET_MEAN[1] / IMAGENET_STD[1],
            -IMAGENET_MEAN[2] / IMAGENET_STD[2],
        ]
        inputs = [
            ct.ImageType(
                name="input",
                shape=(1, 3, image_size, image_size),
                color_layout=ct.colorlayout.RGB,
                scale=scale,
                bias=bias,
            )
        ]

    mlmodel = ct.convert(
        traced_model,
        convert_to="mlprogram",
        inputs=inputs,
        classifier_config=classifier_config,
        compute_precision=ct.precision.FLOAT16,
        compute_units=ct.ComputeUnit.ALL,
    )
    return mlmodel


def preprocess_for_pytorch(path: str, image_size: int) -> torch.Tensor:
    tfm = transforms.Compose(
        [
            transforms.Resize((image_size, image_size)),
            transforms.ToTensor(),
            transforms.Normalize(mean=IMAGENET_MEAN, std=IMAGENET_STD),
        ]
    )
    with Image.open(path) as img:
        rgb = img.convert("RGB")
        tensor = tfm(rgb)
    return tensor


def preprocess_for_coreml(path: str, image_size: int, input_type: str) -> Any:
    with Image.open(path) as img:
        rgb = img.convert("RGB").resize((image_size, image_size))
        if input_type == "image":
            return rgb

        arr = np.asarray(rgb, dtype=np.float32) / 255.0
        arr = arr.transpose(2, 0, 1)
        mean = np.array(IMAGENET_MEAN, dtype=np.float32)[:, None, None]
        std = np.array(IMAGENET_STD, dtype=np.float32)[:, None, None]
        arr = (arr - mean) / std
        arr = np.expand_dims(arr, axis=0)
        return arr


def extract_prob_dict(pred: dict[str, Any], class_labels: list[str]) -> dict[str, float]:
    if "classProbability" in pred and isinstance(pred["classProbability"], dict):
        raw = pred["classProbability"]
        return {label: float(raw.get(label, 0.0)) for label in class_labels}

    # Fallback: find first dict[str, number]
    for value in pred.values():
        if isinstance(value, dict):
            try:
                out = {str(k): float(v) for k, v in value.items()}
                return {label: float(out.get(label, 0.0)) for label in class_labels}
            except Exception:
                continue

    raise RuntimeError("Could not find class probability output in Core ML prediction")


def validate_parity(
    pytorch_model: nn.Module,
    device: torch.device,
    coreml_model: Any,
    dataset: Any,
    class_labels: list[str],
    image_size: int,
    input_type: str,
    samples: int,
    seed: int,
    show_progress: bool,
) -> ValidationSummary:
    rng = np.random.default_rng(seed)
    indices = np.arange(len(dataset))
    rng.shuffle(indices)
    picked = indices[: min(samples, len(indices))]

    pytorch_model.eval()

    top1_matches = 0
    prob_diff_sum = 0.0

    iterator = tqdm(picked.tolist(), desc="Validate parity", disable=not show_progress)
    with torch.no_grad():
        for idx in iterator:
            path, _ = dataset.samples[idx]

            x_t = preprocess_for_pytorch(path, image_size).unsqueeze(0).to(device)
            pt_logits = pytorch_model(x_t)
            pt_probs = torch.softmax(pt_logits, dim=1).cpu().numpy()[0]

            coreml_input = preprocess_for_coreml(path, image_size, input_type)
            pred = coreml_model.predict({"input": coreml_input})
            cm_probs_dict = extract_prob_dict(pred, class_labels)
            cm_probs = np.array([cm_probs_dict[label] for label in class_labels], dtype=np.float64)

            pt_top = int(np.argmax(pt_probs))
            cm_top = int(np.argmax(cm_probs))
            if pt_top == cm_top:
                top1_matches += 1

            prob_diff_sum += float(np.mean(np.abs(pt_probs.astype(np.float64) - cm_probs)))

    used = len(picked)
    return ValidationSummary(
        samples_used=used,
        top1_matches=top1_matches,
        top1_match_rate=(top1_matches / used) if used > 0 else 0.0,
        mean_abs_prob_diff=(prob_diff_sum / used) if used > 0 else 0.0,
    )


def check_normalization_divergence(
    traced_model: Any,
    primary_model: Any,
    dataset: Any,
    class_labels: list[str],
    image_size: int,
    input_type: str,
    max_samples: int = 50,
    divergence_threshold: float = 0.01,
    seed: int = DEFAULT_SEED,
) -> float:
    """Compare top-1 confidence between multiarray and image-mode Core ML paths."""
    if input_type not in {"multiarray", "image"}:
        return 0.0

    other_input_type = "image" if input_type == "multiarray" else "multiarray"
    secondary_model = convert_to_coreml(traced_model, other_input_type, image_size, class_labels)

    rng = np.random.default_rng(seed)
    indices = np.arange(len(dataset))
    rng.shuffle(indices)
    picked = indices[: min(max_samples, len(indices))]

    divergences: list[float] = []
    for idx in picked:
        path, _ = dataset.samples[int(idx)]
        try:
            primary_input = preprocess_for_coreml(path, image_size, input_type)
            secondary_input = preprocess_for_coreml(path, image_size, other_input_type)
            primary_pred = primary_model.predict({"input": primary_input})
            secondary_pred = secondary_model.predict({"input": secondary_input})
            primary_probs = extract_prob_dict(primary_pred, class_labels)
            secondary_probs = extract_prob_dict(secondary_pred, class_labels)
        except Exception:
            continue

        top1_primary = max(primary_probs.values()) if primary_probs else 0.0
        top1_secondary = max(secondary_probs.values()) if secondary_probs else 0.0
        divergences.append(abs(top1_primary - top1_secondary))

    if not divergences:
        logger.warning("Normalization divergence check: no samples compared")
        return 0.0

    mean_div = float(np.mean(divergences))
    if mean_div > divergence_threshold:
        logger.warning(
            "Normalization divergence %.4f exceeds threshold %.4f; image-mode normalization may differ",
            mean_div,
            divergence_threshold,
        )
    else:
        logger.warning("Normalization divergence %.4f within threshold %.4f", mean_div, divergence_threshold)
    return mean_div


def file_size_mb(path: Path) -> float:
    if path.is_file():
        size = path.stat().st_size
    else:
        size = sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
    return size / (1024.0 * 1024.0)


def main() -> None:
    ensure_python_version()
    args = parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s:%(name)s:%(message)s",
    )

    ensure_dependencies()

    model_name, checkpoint_path = find_winner_checkpoint(args)
    logger.warning("Selected model=%s checkpoint=%s", model_name, checkpoint_path)
    device = resolve_device(args.device)
    logger.warning("PyTorch validation device: %s", device)

    val_dataset, idx_to_class, class_labels = build_val_dataset(args.data_root, args.image_size)

    model = build_model(model_name, num_classes=len(class_labels))
    payload = torch.load(str(checkpoint_path), map_location="cpu")
    state_dict = payload.get("state_dict")
    if state_dict is None:
        raise SystemExit(f"Checkpoint missing state_dict: {checkpoint_path}")
    model.load_state_dict(state_dict, strict=True)
    model = model.to(device)
    model.eval()

    traced = trace_model(model, args.image_size)
    mlmodel = convert_to_coreml(traced, args.input_type, args.image_size, class_labels)

    mlmodel.author = args.author
    mlmodel.version = args.version
    mlmodel.short_description = args.description
    mlmodel.input_description["input"] = (
        "Traffic light crop input tensor. Shape (1,3,64,64) normalized with ImageNet mean/std"
        if args.input_type == "multiarray"
        else "Traffic light crop image (RGB, 64x64)"
    )

    mlmodel.output_description["classLabel"] = "Predicted traffic light class label"
    mlmodel.output_description["classProbability"] = "Per-class probabilities"

    summary = validate_parity(
        pytorch_model=model,
        device=device,
        coreml_model=mlmodel,
        dataset=val_dataset,
        class_labels=class_labels,
        image_size=args.image_size,
        input_type=args.input_type,
        samples=args.validation_samples,
        seed=args.seed,
        show_progress=not args.no_progress,
    )

    logger.warning(
        "Validation: samples=%d top1_matches=%d top1_match_rate=%.4f mean_abs_prob_diff=%.6f",
        summary.samples_used,
        summary.top1_matches,
        summary.top1_match_rate,
        summary.mean_abs_prob_diff,
    )

    if summary.samples_used > 0 and summary.top1_match_rate < 0.95:
        raise SystemExit(
            f"Core ML parity check failed: top1_match_rate={summary.top1_match_rate:.4f} < 0.95"
        )

    if not args.skip_normalization_check:
        mean_divergence = check_normalization_divergence(
            traced_model=traced,
            primary_model=mlmodel,
            dataset=val_dataset,
            class_labels=class_labels,
            image_size=args.image_size,
            input_type=args.input_type,
            seed=args.seed,
        )
        logger.warning("Mean normalization divergence (multiarray vs image-mode): %.4f", mean_divergence)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    output_path = args.output_dir / f"{args.output_name}.mlpackage"
    mlmodel.save(str(output_path))

    size_mb = file_size_mb(output_path)
    logger.warning("Export complete: %s", output_path)
    logger.warning("Final model file size: %.2f MB", size_mb)


if __name__ == "__main__":
    main()
