# =================================================================== #
# Program to pre-annotate images using COCO-trained DETR.             #
#                                                                     #
# Input:                                                              #
# File with paths to each image which should be annotated.            #
#                                                                     #
# Output:                                                             #
# Annotation file in the COCO format                                  #
# Box format: (x, y, w, h), where x,y is the top left corner.         #
                                                                      #
# Note that this does not work well when the image is crowed.         #
# =================================================================== #

import argparse
import csv
import json
import logging
import warnings
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

import torch
import torchvision.transforms as T
from PIL import Image
from tqdm import tqdm

# FIXED: use script-relative defaults + CLI paths instead of hardcoded filenames
BASE_DIR = Path(__file__).resolve().parents[2]
logger = logging.getLogger(__name__)


def read_list_to_annotate(filename: str) -> List[str]:
    """
    Reads the file containing the paths to the images.
    Textfile
    """
    img_paths = []
    with open(filename, "r") as f:
        for line in f:
            img_paths.append(str(line).rstrip('\n'))
    logger.info("Loaded names of %s images.", len(set(img_paths)))
    return img_paths


def box_cxcywh_to_xywh(x: torch.Tensor) -> torch.Tensor:
    # Converts bounding boxes to (x1, y1, w, h) coordinates of top left corner and width and height.

    # (center_x, center_y, h, w)
    x_c, y_c, w, h = x.unbind(1)
    b = [(x_c - 0.5 * w), (y_c - 0.5 * h),
        w, h]
    return torch.stack(b, dim=1)


def rescale_bboxes(out_bbox: torch.Tensor, size: Tuple[int, int]) -> torch.Tensor:
    # Scale the bounding boxes to the image size
    img_w, img_h = size
    b = box_cxcywh_to_xywh(out_bbox)
    #b = out_bbox
    b = b * torch.tensor([img_w, img_h, img_w, img_h], dtype=torch.float32)
    return b


def resolve_device(device_flag: str) -> torch.device:
    # FIXED: selectable device with Apple Silicon MPS / CUDA fallback
    if device_flag != "auto":
        if device_flag == "cuda" and not torch.cuda.is_available():
            warnings.warn("CUDA requested but unavailable. Falling back to CPU.")
            return torch.device("cpu")
        if device_flag == "mps" and not (hasattr(torch.backends, "mps") and torch.backends.mps.is_available()):
            warnings.warn("MPS requested but unavailable. Falling back to CPU.")
            return torch.device("cpu")
        return torch.device(device_flag)

    if torch.cuda.is_available():
        return torch.device("cuda")
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def load_model(device: torch.device, weights: str = "") -> torch.nn.Module:
    # FIXED: prefer local weights if provided, fallback to hub with warning
    if weights:
        if not Path(weights).exists():
            raise FileNotFoundError("Weights file not found: {}".format(weights))
        model = torch.hub.load('facebookresearch/detr', 'detr_resnet50', pretrained=False)
        state = torch.load(weights, map_location=device)
        if isinstance(state, dict) and "model" in state:
            state = state["model"]
        model.load_state_dict(state)
    else:
        warnings.warn("No --weights provided. Falling back to torch.hub model download/cache dependency.")
        model = torch.hub.load('facebookresearch/detr', 'detr_resnet50', pretrained=True)

    model.to(device)
    model.eval()
    return model


def build_transform() -> T.Compose:
    return T.Compose([
        T.Resize(800),
        T.ToTensor(),
        T.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
    ])


def predict_batch(
    model: torch.nn.Module,
    image_paths: Sequence[str],
    transform: T.Compose,
    device: torch.device,
    thresh: float = 0.6,
) -> List[List[float]]:
    # FIXED: batched inference + no_grad for production safety
    images: List[Image.Image] = []
    tensors: List[torch.Tensor] = []
    filenames: List[str] = []

    for img_path in image_paths:
        img = Image.open(img_path).convert("RGB")
        images.append(img)
        filenames.append(Path(img_path).name)
        tensors.append(transform(img))

    batch = torch.stack(tensors).to(device)

    out_rows: List[List[float]] = []
    with torch.no_grad():
        output = model(batch)

    pred_logits = output['pred_logits'].softmax(-1)[:, :, :-1]
    pred_boxes = output['pred_boxes']

    for i in range(len(images)):
        probas = pred_logits[i]
        boxes = rescale_bboxes(pred_boxes[i], images[i].size).detach().cpu()
        labels = probas.max(-1).indices.detach().cpu()
        conf = probas.max(-1).values.detach().cpu()
        keep = conf > thresh

        boxes_np = boxes[keep].numpy()
        labels_np = labels[keep].numpy()
        logger.info("Predicted %s annotations for image %s...", len(labels_np), filenames[i])
        for j in range(len(labels_np)):
            out_rows.append([
                filenames[i],
                int(labels_np[j]),
                float(boxes_np[j][0]),
                float(boxes_np[j][1]),
                float(boxes_np[j][2]),
                float(boxes_np[j][3]),
            ])
    return out_rows


def load_checkpoint(checkpoint_path: str) -> Dict[str, object]:
    if not checkpoint_path or not Path(checkpoint_path).exists():
        return {"processed": [], "annotations": []}
    with open(checkpoint_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("processed", [])
    data.setdefault("annotations", [])
    return data


def save_checkpoint(checkpoint_path: str, processed: Sequence[str], annotations: Sequence[Sequence[float]]) -> None:
    if not checkpoint_path:
        return
    payload = {"processed": list(processed), "annotations": list(annotations)}
    with open(checkpoint_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def auto_annotate(
    img_paths: Sequence[str],
    device: torch.device,
    batch_size: int = 8,
    weights: str = "",
    checkpoint_path: str = "",
    thresh: float = 0.6,
) -> List[List[float]]:
    """
    Auto annotates a list of images using DETR.
    Args:

    """
    model = load_model(device=device, weights=weights)
    transform = build_transform()
    checkpoint = load_checkpoint(checkpoint_path)
    processed = set(checkpoint["processed"])
    annotations: List[List[float]] = list(checkpoint["annotations"])

    pending = [p for p in img_paths if p not in processed]
    logger.info("Resuming with %s already processed and %s pending.", len(processed), len(pending))

    # FIXED: add progress bars for image/batch processing loops
    for i in tqdm(range(0, len(pending), batch_size), desc="Prelabel batches", disable=not logger.isEnabledFor(logging.INFO)):
        batch_paths = pending[i:i+batch_size]
        res = predict_batch(model, batch_paths, transform, device=device, thresh=thresh)
        annotations.extend(res)
        processed.update(batch_paths)
        save_checkpoint(checkpoint_path, sorted(processed), annotations)

    return annotations


def save_annotations(anns: Sequence[Sequence[float]], filename_out: str = 'annotations.csv') -> None:
    with open(filename_out, "w+", newline="", encoding="utf-8") as file:
        write = csv.writer(file)
        write.writerows(anns)

    logger.info("Saved annotations to %s!", filename_out)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(BASE_DIR / "tools" / "preLabeller" / "to_annotate-test.txt"), help="Input txt file containing image paths")
    parser.add_argument("--output", default=str(BASE_DIR / "tools" / "preLabeller" / "annotations.csv"), help="Output CSV file")
    parser.add_argument("--annotations", default=str(BASE_DIR / "annotations"), help="Annotations directory (reserved for compatibility)")
    parser.add_argument("--device", choices=["auto", "cpu", "mps", "cuda"], default="auto")
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--checkpoint", default=str(BASE_DIR / "tools" / "preLabeller" / "prelabel_checkpoint.json"))
    parser.add_argument("--weights", default="", help="Path to local weights file. If omitted, uses torch.hub pretrained model.")
    parser.add_argument("--thresh", type=float, default=0.6)
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    args = parser.parse_args()
    # FIXED: replace bare print with logging and configurable verbosity
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s:%(name)s:%(message)s")

    img_paths = read_list_to_annotate(args.input)
    device = resolve_device(args.device)
    anns = auto_annotate(
        img_paths,
        device=device,
        batch_size=args.batch_size,
        weights=args.weights,
        checkpoint_path=args.checkpoint,
        thresh=args.thresh,
    )
    save_annotations(anns, filename_out=args.output)
