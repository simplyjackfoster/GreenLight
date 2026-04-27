#!/usr/bin/env python3
"""Primary light selection for multi-light traffic scenes.

This module is intentionally explicit and Swift-portable:
- Tunable constants are grouped in config dataclasses
- No hidden global state
- Score components are exposed for debugging/overlay usage
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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

    @property
    def area(self) -> float:
        return self.width * self.height

    @property
    def center_x(self) -> float:
        return self.x1 + (self.width * 0.5)

    @property
    def center_y(self) -> float:
        return self.y1 + (self.height * 0.5)


@dataclass(frozen=True)
class LightCandidate:
    bbox: BoundingBox
    candidate_id: str | None = None
    state_hint: str | None = None
    lane_type: str = "unknown"  # e.g. straight, left_turn, right_turn, unknown
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SelectionWeights:
    area: float = 0.35
    center_proximity: float = 0.25
    vertical_position: float = 0.15
    stability: float = 0.15
    aspect_ratio_validity: float = 0.10


@dataclass(frozen=True)
class PrimaryLightSelectorConfig:
    frame_width: int
    frame_height: int

    weights: SelectionWeights = field(default_factory=SelectionWeights)

    stability_history_frames: int = 7
    occlusion_hold_frames: int = 3
    switch_hysteresis_margin: float = 0.08

    center_x_target: float = 0.5
    center_x_half_range: float = 0.5

    # Upper-center zone prior
    center_y_target: float = 0.35
    center_y_half_range: float = 0.35

    expected_aspect_ratio_hw: float = 2.0
    aspect_ratio_tolerance: float = 1.0

    track_match_iou_threshold: float = 0.30


@dataclass(frozen=True)
class SelectedLight:
    candidate: LightCandidate
    score: float
    component_scores: dict[str, float]
    carried_over: bool = False


@dataclass
class _TrackState:
    selected: SelectedLight | None = None
    history: list[BoundingBox] = field(default_factory=list)
    missed_frames: int = 0


class PrimaryLightSelector:
    def __init__(self, config: PrimaryLightSelectorConfig) -> None:
        self.config = config
        self._state = _TrackState()

    def reset(self) -> None:
        self._state = _TrackState()

    def update(self, candidates: list[LightCandidate]) -> SelectedLight | None:
        if not candidates:
            return self._handle_occlusion()

        scored = self._score_candidates(candidates)
        best = max(scored, key=lambda item: item[0])
        best_score, best_candidate, best_components = best

        if self._state.selected is not None:
            retained = self._maybe_apply_hysteresis(candidates, scored, best)
            if retained is not None:
                self._commit_selection(retained.candidate, retained.score, retained.component_scores)
                return retained

        self._commit_selection(best_candidate, best_score, best_components)
        return SelectedLight(candidate=best_candidate, score=best_score, component_scores=best_components)

    def _handle_occlusion(self) -> SelectedLight | None:
        if self._state.selected is None:
            return None

        self._state.missed_frames += 1
        if self._state.missed_frames <= self.config.occlusion_hold_frames:
            s = self._state.selected
            assert s is not None
            return SelectedLight(
                candidate=s.candidate,
                score=s.score,
                component_scores=s.component_scores,
                carried_over=True,
            )

        self.reset()
        return None

    def _commit_selection(self, candidate: LightCandidate, score: float, components: dict[str, float]) -> None:
        self._state.selected = SelectedLight(candidate=candidate, score=score, component_scores=components)
        self._state.missed_frames = 0
        self._state.history.append(candidate.bbox)
        if len(self._state.history) > self.config.stability_history_frames:
            self._state.history = self._state.history[-self.config.stability_history_frames :]

    def _score_candidates(self, candidates: list[LightCandidate]) -> list[tuple[float, LightCandidate, dict[str, float]]]:
        max_area = max((c.bbox.area for c in candidates), default=1.0)
        max_area = max(max_area, 1.0)

        scores: list[tuple[float, LightCandidate, dict[str, float]]] = []
        for c in candidates:
            area_score = self._area_score(c.bbox, max_area)
            center_score = self._center_score(c.bbox)
            vertical_score = self._vertical_score(c.bbox)
            stability_score = self._stability_score(c.bbox)
            aspect_score = self._aspect_ratio_score(c.bbox)

            w = self.config.weights
            total = (
                (w.area * area_score)
                + (w.center_proximity * center_score)
                + (w.vertical_position * vertical_score)
                + (w.stability * stability_score)
                + (w.aspect_ratio_validity * aspect_score)
            )

            components = {
                "area": area_score,
                "center_proximity": center_score,
                "vertical_position": vertical_score,
                "stability": stability_score,
                "aspect_ratio_validity": aspect_score,
            }
            scores.append((total, c, components))

        return scores

    def _maybe_apply_hysteresis(
        self,
        candidates: list[LightCandidate],
        scored: list[tuple[float, LightCandidate, dict[str, float]]],
        best: tuple[float, LightCandidate, dict[str, float]],
    ) -> SelectedLight | None:
        selected = self._state.selected
        if selected is None:
            return None

        previous_bbox = selected.candidate.bbox
        current_match: tuple[float, LightCandidate, dict[str, float]] | None = None

        for entry in scored:
            score, candidate, comps = entry
            if iou(previous_bbox, candidate.bbox) >= self.config.track_match_iou_threshold:
                if current_match is None or score > current_match[0]:
                    current_match = (score, candidate, comps)

        if current_match is None:
            return None

        best_score, best_candidate, _ = best
        curr_score, curr_candidate, curr_comps = current_match

        if best_candidate is curr_candidate:
            return None

        if best_score < (curr_score + self.config.switch_hysteresis_margin):
            return SelectedLight(candidate=curr_candidate, score=curr_score, component_scores=curr_comps)

        return None

    def _area_score(self, bbox: BoundingBox, max_area: float) -> float:
        return clip01(bbox.area / max_area)

    def _center_score(self, bbox: BoundingBox) -> float:
        cx_norm = bbox.center_x / float(max(1, self.config.frame_width))
        dist = abs(cx_norm - self.config.center_x_target)
        denom = max(1e-6, self.config.center_x_half_range)
        return clip01(1.0 - (dist / denom))

    def _vertical_score(self, bbox: BoundingBox) -> float:
        cy_norm = bbox.center_y / float(max(1, self.config.frame_height))
        dist = abs(cy_norm - self.config.center_y_target)
        denom = max(1e-6, self.config.center_y_half_range)
        return clip01(1.0 - (dist / denom))

    def _stability_score(self, bbox: BoundingBox) -> float:
        if not self._state.history:
            return 0.5

        scores = [iou(h, bbox) for h in self._state.history]
        return clip01(sum(scores) / float(len(scores)))

    def _aspect_ratio_score(self, bbox: BoundingBox) -> float:
        w = max(1e-6, bbox.width)
        ratio_hw = bbox.height / w

        expected = max(1e-6, self.config.expected_aspect_ratio_hw)
        tolerance = max(1e-6, self.config.aspect_ratio_tolerance)

        diff = abs(ratio_hw - expected)
        return clip01(1.0 - (diff / tolerance))


def clip01(value: float) -> float:
    return max(0.0, min(1.0, value))


def iou(a: BoundingBox, b: BoundingBox) -> float:
    ix1 = max(a.x1, b.x1)
    iy1 = max(a.y1, b.y1)
    ix2 = min(a.x2, b.x2)
    iy2 = min(a.y2, b.y2)

    iw = max(0.0, ix2 - ix1)
    ih = max(0.0, iy2 - iy1)
    inter = iw * ih

    union = a.area + b.area - inter
    if union <= 0.0:
        return 0.0
    return inter / union
