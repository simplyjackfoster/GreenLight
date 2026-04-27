#!/usr/bin/env python3
"""Debug overlay renderer for traffic-light pipeline introspection."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

try:
    import cv2
except ModuleNotFoundError:
    cv2 = None  # type: ignore[assignment]


STATE_COLORS_BGR: dict[str, tuple[int, int, int]] = {
    "red": (0, 0, 255),
    "green": (0, 255, 0),
    "yellow": (0, 255, 255),
    "off": (180, 180, 180),
    "unknown": (255, 255, 255),
}

PANEL_BG_COLOR = (20, 20, 20)
PANEL_TEXT_COLOR = (235, 235, 235)
PRIMARY_BOX_THICKNESS = 3
SECONDARY_BOX_THICKNESS = 1
DOT_RADIUS = 5
DOT_GAP = 15


@dataclass(frozen=True)
class OverlayLight:
    bbox: tuple[int, int, int, int]
    state: str
    classifier_confidence: float
    fusion_score: float
    is_primary: bool = False


@dataclass(frozen=True)
class OverlayStats:
    state_machine_state: str
    frame_buffer_states: list[str] = field(default_factory=list)
    ambient_lighting: str = "unknown"
    ambient_mean: float = 0.0
    ambient_std: float = 0.0
    chime_fire: bool = False
    true_positive_chimes: int = 0
    false_positive_chimes: int = 0


class DebugOverlayRenderer:
    def __init__(self) -> None:
        if cv2 is None:
            raise RuntimeError("OpenCV is required. Install with: pip install opencv-python")

    def render(self, frame_bgr: np.ndarray, lights: list[OverlayLight], stats: OverlayStats) -> np.ndarray:
        canvas = frame_bgr.copy()
        self._draw_lights(canvas, lights)
        self._draw_info_panel(canvas, stats)
        self._draw_buffer_dots(canvas, stats.frame_buffer_states)
        self._draw_chime_indicator(canvas, stats.chime_fire)
        return canvas

    def _draw_lights(self, canvas: np.ndarray, lights: list[OverlayLight]) -> None:
        for light in lights:
            x1, y1, x2, y2 = light.bbox
            color = STATE_COLORS_BGR.get(light.state, STATE_COLORS_BGR["unknown"])
            thickness = PRIMARY_BOX_THICKNESS if light.is_primary else SECONDARY_BOX_THICKNESS
            cv2.rectangle(canvas, (x1, y1), (x2, y2), color, thickness)

            if light.is_primary:
                cv2.rectangle(canvas, (x1 - 2, y1 - 2), (x2 + 2, y2 + 2), (255, 255, 255), 1)

            text = f"{light.state} c={light.classifier_confidence:.2f} f={light.fusion_score:.2f}"
            cv2.putText(canvas, text, (x1, max(15, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)

    def _draw_info_panel(self, canvas: np.ndarray, stats: OverlayStats) -> None:
        panel_w = 420
        panel_h = 125

        cv2.rectangle(canvas, (8, 8), (8 + panel_w, 8 + panel_h), PANEL_BG_COLOR, -1)
        cv2.rectangle(canvas, (8, 8), (8 + panel_w, 8 + panel_h), (90, 90, 90), 1)

        lines = [
            f"State: {stats.state_machine_state}",
            f"Ambient: {stats.ambient_lighting} mean={stats.ambient_mean:.2f} std={stats.ambient_std:.2f}",
            f"TP chimes: {stats.true_positive_chimes}  FP chimes: {stats.false_positive_chimes}",
        ]
        y = 30
        for line in lines:
            cv2.putText(canvas, line, (18, y), cv2.FONT_HERSHEY_SIMPLEX, 0.52, PANEL_TEXT_COLOR, 1, cv2.LINE_AA)
            y += 28

    def _draw_buffer_dots(self, canvas: np.ndarray, buffer_states: list[str]) -> None:
        if not buffer_states:
            return
        start_x = 22
        y = 115
        for i, state in enumerate(buffer_states):
            color = STATE_COLORS_BGR.get(state, STATE_COLORS_BGR["unknown"])
            cx = start_x + (i * DOT_GAP)
            cv2.circle(canvas, (cx, y), DOT_RADIUS, color, -1)
            cv2.circle(canvas, (cx, y), DOT_RADIUS, (30, 30, 30), 1)

    def _draw_chime_indicator(self, canvas: np.ndarray, chime_fire: bool) -> None:
        text = "CHIME" if chime_fire else "NO CHIME"
        color = (0, 255, 0) if chime_fire else (120, 120, 120)
        h, w = canvas.shape[:2]
        cv2.rectangle(canvas, (w - 180, 10), (w - 10, 45), (0, 0, 0), -1)
        cv2.rectangle(canvas, (w - 180, 10), (w - 10, 45), color, 1)
        cv2.putText(canvas, text, (w - 165, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2, cv2.LINE_AA)


def load_overlay_json(path: Path) -> tuple[list[OverlayLight], OverlayStats]:
    data = json.loads(path.read_text(encoding="utf-8"))

    lights = [
        OverlayLight(
            bbox=tuple(item["bbox"]),
            state=item.get("state", "unknown"),
            classifier_confidence=float(item.get("classifier_confidence", 0.0)),
            fusion_score=float(item.get("fusion_score", 0.0)),
            is_primary=bool(item.get("is_primary", False)),
        )
        for item in data.get("lights", [])
    ]

    s = data.get("stats", {})
    stats = OverlayStats(
        state_machine_state=s.get("state_machine_state", "SEARCHING"),
        frame_buffer_states=[str(x) for x in s.get("frame_buffer_states", [])],
        ambient_lighting=s.get("ambient_lighting", "unknown"),
        ambient_mean=float(s.get("ambient_mean", 0.0)),
        ambient_std=float(s.get("ambient_std", 0.0)),
        chime_fire=bool(s.get("chime_fire", False)),
        true_positive_chimes=int(s.get("true_positive_chimes", 0)),
        false_positive_chimes=int(s.get("false_positive_chimes", 0)),
    )

    return lights, stats


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render debug overlay for one frame")
    parser.add_argument("--frame", type=Path, required=True)
    parser.add_argument("--overlay-json", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if cv2 is None:
        raise SystemExit("OpenCV is required. Install with: pip install opencv-python")

    frame = cv2.imread(str(args.frame), cv2.IMREAD_COLOR)
    if frame is None:
        raise SystemExit(f"Failed to read frame: {args.frame}")

    lights, stats = load_overlay_json(args.overlay_json)
    renderer = DebugOverlayRenderer()
    out = renderer.render(frame, lights, stats)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    ok = cv2.imwrite(str(args.out), out)
    if not ok:
        raise SystemExit(f"Failed to write output image: {args.out}")


if __name__ == "__main__":
    main()
