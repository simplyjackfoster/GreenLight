#!/usr/bin/env python3
"""Pre-chime validation burst for robust green confirmation.

Runs a short multi-scale / slight-brightness inference burst before chime fire.
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol

import numpy as np

try:
    import cv2
except ModuleNotFoundError:
    cv2 = None  # type: ignore[assignment]


DEFAULT_VALIDATION_SCALES = (0.90, 0.95, 1.00, 1.05, 1.10, 1.00)
DEFAULT_BRIGHTNESS_BOOST_INDEX = 5
DEFAULT_BRIGHTNESS_DELTA = 0.08
DEFAULT_REQUIRED_CONFIRMATIONS = 5
DEFAULT_TOTAL_TIME_BUDGET_MS = 150.0
DEFAULT_TARGET_STATE = "green"


@dataclass(frozen=True)
class BoundingBox:
    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def width(self) -> float:
        return max(0.0, self.x2 - self.x1)

    @property
    def height(self) -> float:
        return max(0.0, self.y2 - self.y1)


@dataclass(frozen=True)
class PreChimeValidatorConfig:
    scales: tuple[float, ...] = DEFAULT_VALIDATION_SCALES
    brightness_boost_index: int = DEFAULT_BRIGHTNESS_BOOST_INDEX
    brightness_delta: float = DEFAULT_BRIGHTNESS_DELTA
    required_confirmations: int = DEFAULT_REQUIRED_CONFIRMATIONS
    total_time_budget_ms: float = DEFAULT_TOTAL_TIME_BUDGET_MS
    target_state: str = DEFAULT_TARGET_STATE


@dataclass(frozen=True)
class InferenceOutput:
    state: str
    confidence: float


@dataclass(frozen=True)
class BurstPassResult:
    pass_index: int
    scale: float
    brightness_adjusted: bool
    predicted_state: str
    confidence: float
    accepted: bool


@dataclass(frozen=True)
class PreChimeValidationResult:
    confirmed: bool
    confirmations: int
    required_confirmations: int
    elapsed_ms: float
    within_time_budget: bool
    pass_results: list[BurstPassResult]


class InferenceFn(Protocol):
    def __call__(self, crop_rgb: np.ndarray) -> InferenceOutput:
        ...


class PreChimeValidator:
    def __init__(self, config: PreChimeValidatorConfig | None = None) -> None:
        self.config = config or PreChimeValidatorConfig()

    def validate(
        self,
        frame_bgr: np.ndarray,
        frozen_bbox: BoundingBox,
        inference_fn: InferenceFn,
        confidence_threshold: float,
    ) -> PreChimeValidationResult:
        if cv2 is None:
            raise RuntimeError("OpenCV is required. Install with: pip install opencv-python")
        start = time.perf_counter()
        pass_results: list[BurstPassResult] = []
        confirmations = 0

        for pass_index, scale in enumerate(self.config.scales):
            crop = self._scaled_crop(frame_bgr, frozen_bbox, scale)
            crop = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)

            brightness_adjusted = (pass_index == self.config.brightness_boost_index)
            if brightness_adjusted:
                crop = self._adjust_brightness(crop, self.config.brightness_delta)

            output = inference_fn(crop)
            accepted = (
                output.state.lower() == self.config.target_state
                and output.confidence >= confidence_threshold
            )
            if accepted:
                confirmations += 1

            pass_results.append(
                BurstPassResult(
                    pass_index=pass_index,
                    scale=scale,
                    brightness_adjusted=brightness_adjusted,
                    predicted_state=output.state,
                    confidence=output.confidence,
                    accepted=accepted,
                )
            )

            elapsed_ms = (time.perf_counter() - start) * 1000.0
            if elapsed_ms > self.config.total_time_budget_ms:
                break

        elapsed_ms = (time.perf_counter() - start) * 1000.0
        within_budget = elapsed_ms <= self.config.total_time_budget_ms
        confirmed = confirmations >= self.config.required_confirmations

        return PreChimeValidationResult(
            confirmed=confirmed,
            confirmations=confirmations,
            required_confirmations=self.config.required_confirmations,
            elapsed_ms=elapsed_ms,
            within_time_budget=within_budget,
            pass_results=pass_results,
        )

    def _scaled_crop(self, frame_bgr: np.ndarray, bbox: BoundingBox, scale: float) -> np.ndarray:
        h, w = frame_bgr.shape[:2]
        cx = (bbox.x1 + bbox.x2) * 0.5
        cy = (bbox.y1 + bbox.y2) * 0.5

        half_w = max(1.0, bbox.width * 0.5 * scale)
        half_h = max(1.0, bbox.height * 0.5 * scale)

        x1 = int(max(0, min(w - 1, round(cx - half_w))))
        y1 = int(max(0, min(h - 1, round(cy - half_h))))
        x2 = int(max(1, min(w, round(cx + half_w))))
        y2 = int(max(1, min(h, round(cy + half_h))))

        if x2 <= x1:
            x2 = min(w, x1 + 1)
        if y2 <= y1:
            y2 = min(h, y1 + 1)

        return frame_bgr[y1:y2, x1:x2]

    def _adjust_brightness(self, crop_rgb: np.ndarray, delta: float) -> np.ndarray:
        arr = crop_rgb.astype(np.float32) / 255.0
        arr = np.clip(arr + delta, 0.0, 1.0)
        return (arr * 255.0).astype(np.uint8)


class DemoInference:
    def __init__(self, fixed_state: str, fixed_confidence: float) -> None:
        self.fixed_state = fixed_state
        self.fixed_confidence = fixed_confidence

    def __call__(self, crop_rgb: np.ndarray) -> InferenceOutput:
        _ = crop_rgb
        return InferenceOutput(state=self.fixed_state, confidence=self.fixed_confidence)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run pre-chime validation burst")
    parser.add_argument("--frame", type=Path, required=True)
    parser.add_argument("--bbox", required=True, help="x1,y1,x2,y2")
    parser.add_argument("--threshold", type=float, default=0.87)

    parser.add_argument("--demo-state", default="green")
    parser.add_argument("--demo-confidence", type=float, default=0.93)

    parser.add_argument("--out-json", type=Path, default=None)
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def parse_bbox(raw: str) -> BoundingBox:
    parts = [float(x.strip()) for x in raw.split(",")]
    if len(parts) != 4:
        raise ValueError("--bbox must be x1,y1,x2,y2")
    return BoundingBox(x1=parts[0], y1=parts[1], x2=parts[2], y2=parts[3])


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s:%(name)s:%(message)s",
    )

    if cv2 is None:
        raise SystemExit("OpenCV is required. Install with: pip install opencv-python")

    frame = cv2.imread(str(args.frame), cv2.IMREAD_COLOR)
    if frame is None:
        raise SystemExit(f"Failed to read frame: {args.frame}")

    bbox = parse_bbox(args.bbox)

    validator = PreChimeValidator()
    inference = DemoInference(args.demo_state, args.demo_confidence)
    result = validator.validate(frame, bbox, inference, args.threshold)

    payload = asdict(result)
    serialized = json.dumps(payload, indent=2)
    if args.out_json is not None:
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(serialized + "\n", encoding="utf-8")
    print(serialized)


if __name__ == "__main__":
    main()
