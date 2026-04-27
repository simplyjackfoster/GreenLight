#!/usr/bin/env python3
"""Train traffic light state classifiers on 64x64 crops.

Models:
- MobileNetV3-Small (torchvision, ImageNet pretrained)
- EfficientNet-Lite0 (timm, ImageNet pretrained)

Dataset layout expected:
<root>/train/<class_name>/*.jpg
<root>/val/<class_name>/*.jpg
where class_name in {red, green, yellow, off}
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from tqdm import tqdm

try:
    import torch
    import torch.nn as nn
    import torch.optim as optim
    from torch.utils.data import DataLoader, WeightedRandomSampler
    from torchvision import datasets, models, transforms
except ModuleNotFoundError:
    torch = None  # type: ignore[assignment]
    nn = Any  # type: ignore[assignment]
    optim = Any  # type: ignore[assignment]
    DataLoader = Any  # type: ignore[assignment]
    WeightedRandomSampler = Any  # type: ignore[assignment]
    datasets = None  # type: ignore[assignment]
    models = None  # type: ignore[assignment]
    transforms = None  # type: ignore[assignment]

MIN_PYTHON = (3, 10)

# Defaults (named constants, no magic numbers)
DEFAULT_DATA_ROOT = Path("export/datasets/crops/traffic_state")
DEFAULT_OUTPUT_ROOT = Path("export/models/checkpoints")
DEFAULT_MODEL_LIST = "mobilenet_v3_small,efficientnet_lite0"

DEFAULT_EPOCHS = 40
DEFAULT_FREEZE_EPOCHS = 5
DEFAULT_BATCH_SIZE = 64
DEFAULT_NUM_WORKERS = 4
DEFAULT_LEARNING_RATE = 1e-3
DEFAULT_WEIGHT_DECAY = 1e-4
DEFAULT_LABEL_SMOOTHING = 0.1
DEFAULT_EARLY_STOPPING_PATIENCE = 5
DEFAULT_IMAGE_SIZE = 64
DEFAULT_SEED = 20260426

# Augmentation knobs (training only)
AUG_BRIGHTNESS = 0.4
AUG_CONTRAST = 0.3
AUG_HUE = 0.08
AUG_BLUR_KERNEL = 3
AUG_BLUR_SIGMA_MIN = 0.1
AUG_BLUR_SIGMA_MAX = 2.0
AUG_HORIZONTAL_FLIP_P = 0.5
AUG_ROTATION_DEGREES = 10
AUG_BLUR_P = 0.35
AUG_CUTOUT_P = 0.4
AUG_CUTOUT_SCALE_MIN = 0.02
AUG_CUTOUT_SCALE_MAX = 0.2
AUG_CUTOUT_RATIO_MIN = 0.3
AUG_CUTOUT_RATIO_MAX = 3.0

IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)

CLASS_NAMES_EXPECTED = ("red", "green", "yellow", "off")

logger = logging.getLogger("train")


@dataclass
class EpochLog:
    epoch: int
    train_loss: float
    val_loss: float
    val_accuracy: float
    learning_rate: float
    phase: str


@dataclass
class ModelSummary:
    model_name: str
    best_val_accuracy: float
    best_epoch: int
    checkpoint_path: str
    confusion_matrix: list[list[int]]
    precision: dict[str, float]
    recall: dict[str, float]
    f1: dict[str, float]
    macro_f1: float


def ensure_python_version() -> None:
    if sys.version_info < MIN_PYTHON:
        raise SystemExit(f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ is required")


def ensure_ml_dependencies() -> None:
    if torch is not None and datasets is not None and models is not None and transforms is not None:
        return
    raise SystemExit(
        "Missing training dependencies. Install with: pip install torch torchvision "
        "timm tqdm numpy"
    )


def seed_everything(seed: int) -> None:
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    np.random.seed(seed)


def resolve_device(device_flag: str) -> torch.device:
    if device_flag == "auto":
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return torch.device("mps")
        if torch.cuda.is_available():
            return torch.device("cuda")
        return torch.device("cpu")

    device = torch.device(device_flag)
    if device.type == "mps" and not (hasattr(torch.backends, "mps") and torch.backends.mps.is_available()):
        raise SystemExit("Requested --device mps but MPS is not available")
    if device.type == "cuda" and not torch.cuda.is_available():
        raise SystemExit("Requested --device cuda but CUDA is not available")
    return device


def build_transforms(image_size: int) -> tuple[transforms.Compose, transforms.Compose]:
    train_tfms = transforms.Compose(
        [
            transforms.Resize((image_size, image_size)),
            transforms.ColorJitter(brightness=AUG_BRIGHTNESS, contrast=AUG_CONTRAST, hue=AUG_HUE),
            transforms.RandomApply(
                [transforms.GaussianBlur(kernel_size=AUG_BLUR_KERNEL, sigma=(AUG_BLUR_SIGMA_MIN, AUG_BLUR_SIGMA_MAX))],
                p=AUG_BLUR_P,
            ),
            transforms.RandomHorizontalFlip(p=AUG_HORIZONTAL_FLIP_P),
            transforms.RandomRotation(degrees=AUG_ROTATION_DEGREES),
            transforms.ToTensor(),
            transforms.RandomErasing(
                p=AUG_CUTOUT_P,
                scale=(AUG_CUTOUT_SCALE_MIN, AUG_CUTOUT_SCALE_MAX),
                ratio=(AUG_CUTOUT_RATIO_MIN, AUG_CUTOUT_RATIO_MAX),
                value="random",
            ),
            transforms.Normalize(mean=IMAGENET_MEAN, std=IMAGENET_STD),
        ]
    )

    val_tfms = transforms.Compose(
        [
            transforms.Resize((image_size, image_size)),
            transforms.ToTensor(),
            transforms.Normalize(mean=IMAGENET_MEAN, std=IMAGENET_STD),
        ]
    )
    return train_tfms, val_tfms


def compute_sample_weights(targets: list[int], num_classes: int) -> tuple[list[float], dict[int, float]]:
    counts = np.zeros(num_classes, dtype=np.int64)
    for t in targets:
        counts[t] += 1

    class_weights: dict[int, float] = {}
    for idx in range(num_classes):
        class_weights[idx] = 1.0 / float(counts[idx]) if counts[idx] > 0 else 0.0

    sample_weights = [class_weights[t] for t in targets]
    return sample_weights, class_weights


def build_dataloaders(args: argparse.Namespace) -> tuple[DataLoader, DataLoader, dict[int, str], dict[int, float]]:
    train_dir = args.data_root / "train"
    val_dir = args.data_root / "val"
    if not train_dir.exists() or not val_dir.exists():
        raise SystemExit(f"Expected train/val directories under {args.data_root}")

    train_tfms, val_tfms = build_transforms(args.image_size)

    train_ds = datasets.ImageFolder(str(train_dir), transform=train_tfms)
    val_ds = datasets.ImageFolder(str(val_dir), transform=val_tfms)

    if len(train_ds) == 0 or len(val_ds) == 0:
        raise SystemExit("Train or val split is empty. Run dataset_pipeline.py first.")

    idx_to_class = {idx: name for name, idx in train_ds.class_to_idx.items()}
    class_set = set(idx_to_class.values())
    expected_set = set(CLASS_NAMES_EXPECTED)
    if class_set != expected_set:
        logger.warning(
            "Class folder mismatch. expected=%s got=%s",
            sorted(expected_set),
            sorted(class_set),
        )

    sample_weights, class_weights = compute_sample_weights(train_ds.targets, num_classes=len(train_ds.classes))
    sampler = WeightedRandomSampler(weights=sample_weights, num_samples=len(sample_weights), replacement=True)

    train_loader = DataLoader(
        train_ds,
        batch_size=args.batch_size,
        sampler=sampler,
        num_workers=args.num_workers,
        pin_memory=(args.device != "mps"),
    )
    val_loader = DataLoader(
        val_ds,
        batch_size=args.batch_size,
        shuffle=False,
        num_workers=args.num_workers,
        pin_memory=(args.device != "mps"),
    )

    return train_loader, val_loader, idx_to_class, class_weights


def build_model(model_name: str, num_classes: int, use_pretrained: bool) -> nn.Module:
    if model_name == "mobilenet_v3_small":
        weights = models.MobileNet_V3_Small_Weights.DEFAULT if use_pretrained else None
        model = models.mobilenet_v3_small(weights=weights)
        in_features = model.classifier[-1].in_features
        model.classifier[-1] = nn.Linear(in_features, num_classes)
        return model

    if model_name == "efficientnet_lite0":
        try:
            import timm  # type: ignore
        except ModuleNotFoundError as exc:
            raise SystemExit(
                "efficientnet_lite0 requires timm. Install with: pip install timm"
            ) from exc
        model = timm.create_model("efficientnet_lite0", pretrained=use_pretrained, num_classes=num_classes)
        return model

    raise ValueError(f"Unsupported model: {model_name}")


def set_trainable_phase(model: nn.Module, model_name: str, frozen_backbone: bool) -> None:
    # Start with full freeze/unfreeze toggle
    for param in model.parameters():
        param.requires_grad = not frozen_backbone

    # Keep classification head trainable in frozen phase.
    if model_name == "mobilenet_v3_small":
        for param in model.classifier.parameters():
            param.requires_grad = True
        return

    if model_name == "efficientnet_lite0":
        if hasattr(model, "classifier"):
            for param in model.classifier.parameters():
                param.requires_grad = True
        elif hasattr(model, "get_classifier"):
            classifier_name = model.get_classifier().__class__.__name__
            logger.warning("Using timm classifier accessor: %s", classifier_name)
            for name, param in model.named_parameters():
                if "classifier" in name:
                    param.requires_grad = True
        return


def train_one_epoch(
    model: nn.Module,
    loader: DataLoader,
    criterion: nn.Module,
    optimizer: optim.Optimizer,
    device: torch.device,
    show_progress: bool,
) -> float:
    model.train()
    running_loss = 0.0
    seen = 0

    iterator = tqdm(loader, desc="Train", leave=False, disable=not show_progress)
    for images, labels in iterator:
        images = images.to(device)
        labels = labels.to(device)

        optimizer.zero_grad(set_to_none=True)
        logits = model(images)
        loss = criterion(logits, labels)
        loss.backward()
        optimizer.step()

        batch = images.size(0)
        seen += batch
        running_loss += loss.item() * batch

    return running_loss / max(1, seen)


def evaluate(
    model: nn.Module,
    loader: DataLoader,
    criterion: nn.Module,
    device: torch.device,
    num_classes: int,
    show_progress: bool,
) -> tuple[float, float, np.ndarray]:
    model.eval()
    running_loss = 0.0
    seen = 0
    correct = 0
    confusion = np.zeros((num_classes, num_classes), dtype=np.int64)

    iterator = tqdm(loader, desc="Val", leave=False, disable=not show_progress)
    with torch.no_grad():
        for images, labels in iterator:
            images = images.to(device)
            labels = labels.to(device)

            logits = model(images)
            loss = criterion(logits, labels)
            preds = torch.argmax(logits, dim=1)

            batch = images.size(0)
            seen += batch
            running_loss += loss.item() * batch
            correct += (preds == labels).sum().item()

            y_true = labels.detach().cpu().numpy()
            y_pred = preds.detach().cpu().numpy()
            for t, p in zip(y_true.tolist(), y_pred.tolist()):
                confusion[t, p] += 1

    avg_loss = running_loss / max(1, seen)
    accuracy = correct / max(1, seen)
    return avg_loss, accuracy, confusion


def precision_recall_f1(confusion: np.ndarray, idx_to_class: dict[int, str]) -> tuple[dict[str, float], dict[str, float], dict[str, float], float]:
    precision: dict[str, float] = {}
    recall: dict[str, float] = {}
    f1: dict[str, float] = {}

    class_f1: list[float] = []
    num_classes = confusion.shape[0]
    for idx in range(num_classes):
        cls_name = idx_to_class[idx]
        tp = float(confusion[idx, idx])
        fp = float(confusion[:, idx].sum() - tp)
        fn = float(confusion[idx, :].sum() - tp)

        p = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        r = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f = 2 * p * r / (p + r) if (p + r) > 0 else 0.0

        precision[cls_name] = p
        recall[cls_name] = r
        f1[cls_name] = f
        class_f1.append(f)

    macro_f1 = float(np.mean(class_f1)) if class_f1 else 0.0
    return precision, recall, f1, macro_f1


def format_confusion_matrix(confusion: np.ndarray, idx_to_class: dict[int, str]) -> str:
    labels = [idx_to_class[i] for i in range(len(idx_to_class))]
    rows = ["pred\\true," + ",".join(labels)]
    for i, name in enumerate(labels):
        row_vals = ",".join(str(int(v)) for v in confusion[i])
        rows.append(f"{name},{row_vals}")
    return "\n".join(rows)


def save_checkpoint(path: Path, model: nn.Module, epoch: int, val_accuracy: float, model_name: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "model_name": model_name,
            "epoch": epoch,
            "val_accuracy": val_accuracy,
            "state_dict": model.state_dict(),
        },
        str(path),
    )


def train_single_model(
    model_name: str,
    args: argparse.Namespace,
    train_loader: DataLoader,
    val_loader: DataLoader,
    idx_to_class: dict[int, str],
) -> tuple[ModelSummary, list[EpochLog], dict[int, float]]:
    num_classes = len(idx_to_class)
    model = build_model(model_name, num_classes=num_classes, use_pretrained=not args.no_pretrained)
    device = resolve_device(args.device)
    model = model.to(device)

    # Freeze backbone first N epochs.
    set_trainable_phase(model, model_name, frozen_backbone=True)

    criterion = nn.CrossEntropyLoss(label_smoothing=args.label_smoothing)
    optimizer = optim.AdamW(model.parameters(), lr=args.learning_rate, weight_decay=args.weight_decay)
    scheduler = optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=max(1, args.epochs), eta_min=args.learning_rate * 0.01)

    checkpoint_path = args.output_root / f"best_{model_name}.pt"
    history: list[EpochLog] = []

    best_acc = -math.inf
    best_epoch = -1
    best_confusion = np.zeros((num_classes, num_classes), dtype=np.int64)
    no_improve = 0

    logger.warning("\n=== Training model: %s ===", model_name)
    logger.warning("Device: %s", device)

    for epoch in range(1, args.epochs + 1):
        if epoch == args.freeze_epochs + 1:
            set_trainable_phase(model, model_name, frozen_backbone=False)
            logger.warning("Epoch %d: backbone unfrozen", epoch)

        train_loss = train_one_epoch(
            model=model,
            loader=train_loader,
            criterion=criterion,
            optimizer=optimizer,
            device=device,
            show_progress=not args.no_progress,
        )

        val_loss, val_acc, confusion = evaluate(
            model=model,
            loader=val_loader,
            criterion=criterion,
            device=device,
            num_classes=num_classes,
            show_progress=not args.no_progress,
        )

        scheduler.step()

        phase = "frozen" if epoch <= args.freeze_epochs else "full"
        log_row = EpochLog(
            epoch=epoch,
            train_loss=train_loss,
            val_loss=val_loss,
            val_accuracy=val_acc,
            learning_rate=optimizer.param_groups[0]["lr"],
            phase=phase,
        )
        history.append(log_row)

        logger.warning(
            "epoch=%d phase=%s train_loss=%.5f val_loss=%.5f val_acc=%.4f lr=%.7f",
            epoch,
            phase,
            train_loss,
            val_loss,
            val_acc,
            optimizer.param_groups[0]["lr"],
        )

        if val_acc > best_acc:
            best_acc = val_acc
            best_epoch = epoch
            best_confusion = confusion.copy()
            save_checkpoint(checkpoint_path, model, epoch, val_acc, model_name)
            no_improve = 0
        else:
            no_improve += 1

        if no_improve >= args.early_stopping_patience:
            logger.warning(
                "Early stopping on %s at epoch %d (patience=%d)",
                model_name,
                epoch,
                args.early_stopping_patience,
            )
            break

    precision, recall, f1, macro_f1 = precision_recall_f1(best_confusion, idx_to_class)

    summary = ModelSummary(
        model_name=model_name,
        best_val_accuracy=float(best_acc),
        best_epoch=best_epoch,
        checkpoint_path=str(checkpoint_path),
        confusion_matrix=best_confusion.tolist(),
        precision=precision,
        recall=recall,
        f1=f1,
        macro_f1=macro_f1,
    )

    logger.warning("\nFinal report for %s", model_name)
    logger.warning("best_val_accuracy=%.4f at epoch=%d", summary.best_val_accuracy, summary.best_epoch)
    for cls_name in (idx_to_class[i] for i in range(len(idx_to_class))):
        logger.warning(
            "%s precision=%.4f recall=%.4f f1=%.4f",
            cls_name,
            summary.precision[cls_name],
            summary.recall[cls_name],
            summary.f1[cls_name],
        )
    logger.warning("macro_f1=%.4f", summary.macro_f1)
    logger.warning("Confusion matrix (rows=pred, cols=true):\n%s", format_confusion_matrix(best_confusion, idx_to_class))

    return summary, history, {}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train traffic light state classifiers")
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--models", default=DEFAULT_MODEL_LIST, help="Comma-separated list. Options: mobilenet_v3_small,efficientnet_lite0")

    parser.add_argument("--epochs", type=int, default=DEFAULT_EPOCHS)
    parser.add_argument("--freeze-epochs", type=int, default=DEFAULT_FREEZE_EPOCHS)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--num-workers", type=int, default=DEFAULT_NUM_WORKERS)
    parser.add_argument("--learning-rate", type=float, default=DEFAULT_LEARNING_RATE)
    parser.add_argument("--weight-decay", type=float, default=DEFAULT_WEIGHT_DECAY)
    parser.add_argument("--label-smoothing", type=float, default=DEFAULT_LABEL_SMOOTHING)
    parser.add_argument("--early-stopping-patience", type=int, default=DEFAULT_EARLY_STOPPING_PATIENCE)
    parser.add_argument("--image-size", type=int, default=DEFAULT_IMAGE_SIZE)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)

    parser.add_argument("--device", default="auto", choices=["auto", "cpu", "mps", "cuda"])
    parser.add_argument("--no-pretrained", action="store_true", help="Disable ImageNet pretrained weights")
    parser.add_argument("--no-progress", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    if args.epochs <= 0:
        raise ValueError("--epochs must be > 0")
    if args.freeze_epochs < 0:
        raise ValueError("--freeze-epochs must be >= 0")
    if args.batch_size <= 0:
        raise ValueError("--batch-size must be > 0")
    if args.learning_rate <= 0:
        raise ValueError("--learning-rate must be > 0")
    if args.early_stopping_patience <= 0:
        raise ValueError("--early-stopping-patience must be > 0")
    if args.image_size <= 0:
        raise ValueError("--image-size must be > 0")


def save_training_artifacts(
    output_root: Path,
    summaries: list[ModelSummary],
    history_by_model: dict[str, list[EpochLog]],
    args: argparse.Namespace,
) -> None:
    output_root.mkdir(parents=True, exist_ok=True)

    # Per-model epoch logs
    for model_name, rows in history_by_model.items():
        csv_path = output_root / f"history_{model_name}.csv"
        with csv_path.open("w", encoding="utf-8") as handle:
            handle.write("epoch,phase,train_loss,val_loss,val_accuracy,learning_rate\n")
            for r in rows:
                handle.write(
                    f"{r.epoch},{r.phase},{r.train_loss:.8f},{r.val_loss:.8f},{r.val_accuracy:.8f},{r.learning_rate:.10f}\n"
                )

    report = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "args": {
            "data_root": str(args.data_root),
            "output_root": str(args.output_root),
            "models": args.models,
            "epochs": args.epochs,
            "freeze_epochs": args.freeze_epochs,
            "batch_size": args.batch_size,
            "num_workers": args.num_workers,
            "learning_rate": args.learning_rate,
            "weight_decay": args.weight_decay,
            "label_smoothing": args.label_smoothing,
            "early_stopping_patience": args.early_stopping_patience,
            "image_size": args.image_size,
            "seed": args.seed,
            "device": args.device,
            "no_pretrained": args.no_pretrained,
        },
        "summaries": [asdict(s) for s in summaries],
    }
    with (output_root / "training_report.json").open("w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)


def main() -> None:
    ensure_python_version()
    args = parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s:%(name)s:%(message)s",
    )

    ensure_ml_dependencies()
    validate_args(args)
    seed_everything(args.seed)

    model_names = [m.strip() for m in args.models.split(",") if m.strip()]
    if not model_names:
        raise SystemExit("No models requested. Use --models")

    train_loader, val_loader, idx_to_class, class_weights = build_dataloaders(args)

    logger.warning("Train class weights (for WeightedRandomSampler):")
    for idx in range(len(idx_to_class)):
        logger.warning("  %s: %.8f", idx_to_class[idx], class_weights.get(idx, 0.0))

    summaries: list[ModelSummary] = []
    history_by_model: dict[str, list[EpochLog]] = {}

    for model_name in model_names:
        summary, history, _ = train_single_model(
            model_name=model_name,
            args=args,
            train_loader=train_loader,
            val_loader=val_loader,
            idx_to_class=idx_to_class,
        )
        summaries.append(summary)
        history_by_model[model_name] = history

    save_training_artifacts(args.output_root, summaries, history_by_model, args)

    winner = max(summaries, key=lambda s: s.best_val_accuracy)
    logger.warning("\n=== Winner ===")
    logger.warning("%s (best_val_accuracy=%.4f, checkpoint=%s)", winner.model_name, winner.best_val_accuracy, winner.checkpoint_path)


if __name__ == "__main__":
    main()
