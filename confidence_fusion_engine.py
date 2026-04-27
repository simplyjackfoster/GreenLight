#!/usr/bin/env python3
"""Confidence fusion engine for traffic-light state reliability.

Combines classifier confidence, box geometry/tracking quality, ambient lighting,
and transition prior into a single reliability score.
"""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import numpy as np

try:
    import cv2
except ModuleNotFoundError:
    cv2 = None  # type: ignore[assignment]


class LightState(str, Enum):
    RED = "red"
    GREEN = "green"
    YELLOW = "yellow"
    OFF = "off"


class LightingCondition(str, Enum):
    DAY = "day"
    DUSK = "dusk"
    NIGHT = "night"


@dataclass(frozen=True)
class FusionWeights:
    classifier_softmax: float = 0.40
    bbox_size: float = 0.20
    bbox_stability: float = 0.20
    ambient_lighting: float = 0.10
    transition_prior: float = 0.10


@dataclass(frozen=True)
class TransitionPriorMatrix:
    values: dict[str, dict[str, float]] = field(
        default_factory=lambda: {
            "red": {"red": 0.05, "green": 0.90, "yellow": 0.05, "off": 0.00},
            "green": {"red": 0.05, "green": 0.85, "yellow": 0.10, "off": 0.00},
            "yellow": {"red": 0.80, "green": 0.00, "yellow": 0.10, "off": 0.10},
            "off": {"red": 0.30, "green": 0.10, "yellow": 0.05, "off": 0.55},
        }
    )


@dataclass(frozen=True)
class AdaptiveThresholds:
    day: float = 0.82
    dusk: float = 0.87
    night: float = 0.91


@dataclass(frozen=True)
class AmbientLightingConfig:
    # Mean luminance ranges are normalized [0,1]
    day_mean_min: float = 0.55
    night_mean_max: float = 0.28

    # Normalized scene-contrast heuristics
    low_contrast_max: float = 0.12
    high_contrast_min: float = 0.20


@dataclass(frozen=True)
class FusionConfig:
    weights: FusionWeights = field(default_factory=FusionWeights)
    priors: TransitionPriorMatrix = field(default_factory=TransitionPriorMatrix)
    thresholds: AdaptiveThresholds = field(default_factory=AdaptiveThresholds)
    ambient: AmbientLightingConfig = field(default_factory=AmbientLightingConfig)


@dataclass(frozen=True)
class AmbientStats:
    brightness_mean: float
    brightness_std: float
    lighting_condition: LightingCondition
    ambient_score: float


@dataclass(frozen=True)
class FusionInput:
    predicted_state: LightState
    previous_state: LightState
    classifier_confidence: float
    bbox_size_score: float
    bbox_stability_score: float
    ambient_stats: AmbientStats


@dataclass(frozen=True)
class FusionResult:
    predicted_state: LightState
    reliability_score: float
    adaptive_threshold: float
    is_reliable: bool
    components: dict[str, float]


def clip01(v: float) -> float:
    return max(0.0, min(1.0, v))


def soft_sign(x: float) -> float:
    return x / (1.0 + abs(x))


class ConfidenceFusionEngine:
    def __init__(self, config: FusionConfig | None = None) -> None:
        self.config = config or FusionConfig()

    def estimate_ambient(self, frame_bgr: np.ndarray) -> AmbientStats:
        if cv2 is None:
            raise RuntimeError("OpenCV is required. Install with: pip install opencv-python")
        if frame_bgr.size == 0:
            raise ValueError("Empty frame input")

        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        mean = float(np.mean(gray) / 255.0)
        std = float(np.std(gray) / 255.0)

        lighting = self._infer_lighting_condition(mean, std)
        ambient_score = self._ambient_reliability_score(mean, std)

        return AmbientStats(
            brightness_mean=mean,
            brightness_std=std,
            lighting_condition=lighting,
            ambient_score=ambient_score,
        )

    def fuse(self, item: FusionInput) -> FusionResult:
        prior = self._transition_prior(item.previous_state, item.predicted_state)

        w = self.config.weights
        components = {
            "classifier_softmax": clip01(item.classifier_confidence),
            "bbox_size": clip01(item.bbox_size_score),
            "bbox_stability": clip01(item.bbox_stability_score),
            "ambient_lighting": clip01(item.ambient_stats.ambient_score),
            "transition_prior": clip01(prior),
        }

        weighted = (
            (w.classifier_softmax * components["classifier_softmax"])
            + (w.bbox_size * components["bbox_size"])
            + (w.bbox_stability * components["bbox_stability"])
            + (w.ambient_lighting * components["ambient_lighting"])
            + (w.transition_prior * components["transition_prior"])
        )

        threshold = self._adaptive_threshold(item.ambient_stats.lighting_condition)
        reliability = clip01(weighted)

        return FusionResult(
            predicted_state=item.predicted_state,
            reliability_score=reliability,
            adaptive_threshold=threshold,
            is_reliable=(reliability >= threshold),
            components=components,
        )

    def _transition_prior(self, previous_state: LightState, predicted_state: LightState) -> float:
        table = self.config.priors.values
        return float(table.get(previous_state.value, {}).get(predicted_state.value, 0.0))

    def _adaptive_threshold(self, lighting: LightingCondition) -> float:
        t = self.config.thresholds
        if lighting == LightingCondition.DAY:
            return t.day
        if lighting == LightingCondition.DUSK:
            return t.dusk
        return t.night

    def _infer_lighting_condition(self, mean: float, std: float) -> LightingCondition:
        cfg = self.config.ambient
        if mean >= cfg.day_mean_min:
            return LightingCondition.DAY
        if mean <= cfg.night_mean_max:
            return LightingCondition.NIGHT

        # Middle range is dusk by default.
        return LightingCondition.DUSK

    def _ambient_reliability_score(self, mean: float, std: float) -> float:
        # Reward adequate brightness and moderate contrast.
        # Brightness term centered around daytime-dusk boundary.
        mean_term = clip01(0.5 + (0.9 * soft_sign((mean - 0.40) * 3.0)))

        cfg = self.config.ambient
        if std <= cfg.low_contrast_max:
            contrast_term = clip01(std / max(1e-6, cfg.low_contrast_max))
        elif std >= cfg.high_contrast_min:
            contrast_term = 1.0
        else:
            span = cfg.high_contrast_min - cfg.low_contrast_max
            contrast_term = clip01((std - cfg.low_contrast_max) / max(1e-6, span))

        return clip01((0.6 * mean_term) + (0.4 * contrast_term))


def parse_state(value: str) -> LightState:
    try:
        return LightState(value.lower())
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid state: {value}") from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fuse multi-signal confidence for traffic-light state transitions")
    parser.add_argument("--predicted-state", type=parse_state, default=LightState.GREEN)
    parser.add_argument("--previous-state", type=parse_state, default=LightState.RED)
    parser.add_argument("--classifier-confidence", type=float, default=0.92)
    parser.add_argument("--bbox-size-score", type=float, default=0.80)
    parser.add_argument("--bbox-stability-score", type=float, default=0.85)

    parser.add_argument("--frame", type=Path, default=None, help="Optional frame path for ambient estimation")
    parser.add_argument("--ambient-mean", type=float, default=0.45, help="Fallback normalized mean [0,1]")
    parser.add_argument("--ambient-std", type=float, default=0.16, help="Fallback normalized std [0,1]")

    parser.add_argument("--out-json", type=Path, default=None)
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s:%(name)s:%(message)s",
    )

    engine = ConfidenceFusionEngine()

    if args.frame is not None:
        if cv2 is None:
            raise SystemExit("OpenCV is required when using --frame. Install with: pip install opencv-python")
        frame = cv2.imread(str(args.frame), cv2.IMREAD_COLOR)
        if frame is None:
            raise SystemExit(f"Failed to read frame: {args.frame}")
        ambient = engine.estimate_ambient(frame)
    else:
        lighting = engine._infer_lighting_condition(args.ambient_mean, args.ambient_std)
        ambient_score = engine._ambient_reliability_score(args.ambient_mean, args.ambient_std)
        ambient = AmbientStats(
            brightness_mean=clip01(args.ambient_mean),
            brightness_std=clip01(args.ambient_std),
            lighting_condition=lighting,
            ambient_score=ambient_score,
        )

    result = engine.fuse(
        FusionInput(
            predicted_state=args.predicted_state,
            previous_state=args.previous_state,
            classifier_confidence=args.classifier_confidence,
            bbox_size_score=args.bbox_size_score,
            bbox_stability_score=args.bbox_stability_score,
            ambient_stats=ambient,
        )
    )

    payload = {
        "ambient": {
            "brightness_mean": ambient.brightness_mean,
            "brightness_std": ambient.brightness_std,
            "lighting_condition": ambient.lighting_condition.value,
            "ambient_score": ambient.ambient_score,
        },
        "fusion": {
            "predicted_state": result.predicted_state.value,
            "reliability_score": result.reliability_score,
            "adaptive_threshold": result.adaptive_threshold,
            "is_reliable": result.is_reliable,
            "components": result.components,
        },
        "config": asdict(engine.config),
    }

    serialized = json.dumps(payload, indent=2)
    if args.out_json is not None:
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(serialized + "\n", encoding="utf-8")
    print(serialized)


if __name__ == "__main__":
    main()
