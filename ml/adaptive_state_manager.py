#!/usr/bin/env python3
"""Adaptive traffic-light state manager with chime gating.

State graph:
SEARCHING -> TRACKING_RED -> TENTATIVE_GREEN -> CONFIRMED_GREEN
-> TRACKING_GREEN -> TRACKING_YELLOW -> LOST
"""

from __future__ import annotations

import argparse
import json
from collections import deque
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path


class TrafficState(str, Enum):
    SEARCHING = "SEARCHING"
    TRACKING_RED = "TRACKING_RED"
    TENTATIVE_GREEN = "TENTATIVE_GREEN"
    CONFIRMED_GREEN = "CONFIRMED_GREEN"
    TRACKING_GREEN = "TRACKING_GREEN"
    TRACKING_YELLOW = "TRACKING_YELLOW"
    LOST = "LOST"


class LightColor(str, Enum):
    RED = "red"
    GREEN = "green"
    YELLOW = "yellow"
    OFF = "off"


class LightingCondition(str, Enum):
    DAY = "day"
    DUSK = "dusk"
    NIGHT = "night"


@dataclass(frozen=True)
class BufferConfig:
    day: int = 5
    dusk: int = 7
    night: int = 10


@dataclass(frozen=True)
class StateManagerConfig:
    lost_hold_frames: int = 45
    speed_gate_mph: float = 2.0
    cooldown_frames: int = 150
    confidence_gate: float = 0.82
    adaptive_buffer: BufferConfig = field(default_factory=BufferConfig)
    tentative_green_timeout_frames: int = 15
    speed_adaptive_buffer: bool = True


@dataclass(frozen=True)
class StateUpdateInput:
    observed_color: LightColor | None
    reliability_score: float
    lighting: LightingCondition
    speed_mph: float
    pre_chime_confirmed: bool = False


@dataclass(frozen=True)
class StateUpdateOutput:
    state: TrafficState
    chime_fire: bool
    transition_reason: str
    buffer_snapshot: list[str]
    lost_counter: int
    cooldown_remaining: int


def clip01(v: float) -> float:
    return max(0.0, min(1.0, v))


class AdaptiveStateManager:
    def __init__(self, config: StateManagerConfig | None = None) -> None:
        self.config = config or StateManagerConfig()
        self.state = TrafficState.SEARCHING
        self.last_known_color: LightColor | None = None

        self.buffer: deque[LightColor] = deque()
        self.buffer_size = self.config.adaptive_buffer.day

        self.lost_counter = 0
        self.cooldown_remaining = 0
        self._tentative_green_frames = 0

    def reset(self) -> None:
        self.state = TrafficState.SEARCHING
        self.last_known_color = None
        self.buffer.clear()
        self.lost_counter = 0
        self.cooldown_remaining = 0
        self._tentative_green_frames = 0

    def update(self, item: StateUpdateInput) -> StateUpdateOutput:
        self._set_buffer_size(item.lighting, speed_mph=item.speed_mph)
        self._tick_cooldown()

        if item.observed_color is None or item.reliability_score < self.config.confidence_gate:
            return self._handle_missing_observation()

        self.lost_counter = 0
        self.last_known_color = item.observed_color
        self._push_buffer(item.observed_color)

        stable_color = self._stable_buffer_color()
        reason = "stable_observation"
        chime_fire = False

        if stable_color is None:
            return self._emit(reason="insufficient_buffer", chime=False)

        if self.state == TrafficState.SEARCHING:
            if stable_color == LightColor.RED:
                self.state = TrafficState.TRACKING_RED
                reason = "locked_red"
            elif stable_color == LightColor.GREEN:
                self.state = TrafficState.TRACKING_GREEN
                reason = "locked_green"
            elif stable_color == LightColor.YELLOW:
                self.state = TrafficState.TRACKING_YELLOW
                reason = "locked_yellow"
            return self._emit(reason=reason, chime=False)

        if self.state == TrafficState.TRACKING_RED:
            if stable_color == LightColor.GREEN:
                self.state = TrafficState.TENTATIVE_GREEN
                self._tentative_green_frames = 0
                reason = "red_to_tentative_green"
            elif stable_color == LightColor.YELLOW:
                self.state = TrafficState.TRACKING_YELLOW
                reason = "red_to_yellow"
            return self._emit(reason=reason, chime=False)

        if self.state == TrafficState.TENTATIVE_GREEN:
            timeout = self.config.tentative_green_timeout_frames
            if timeout > 0:
                self._tentative_green_frames += 1
                if self._tentative_green_frames >= timeout:
                    self._tentative_green_frames = 0
                    self.state = TrafficState.SEARCHING
                    return self._emit(reason="tentative_green_timeout", chime=False)

            if item.pre_chime_confirmed and stable_color == LightColor.GREEN:
                self._tentative_green_frames = 0
                self.state = TrafficState.CONFIRMED_GREEN
                reason = "pre_chime_confirmed_green"
                chime_fire = self._should_fire_chime(item.speed_mph)
                if chime_fire:
                    self.cooldown_remaining = self.config.cooldown_frames
            elif stable_color in {LightColor.RED, LightColor.YELLOW}:
                self._tentative_green_frames = 0
                self.state = TrafficState.TRACKING_RED if stable_color == LightColor.RED else TrafficState.TRACKING_YELLOW
                reason = "tentative_green_rejected"
            return self._emit(reason=reason, chime=chime_fire)

        if self.state == TrafficState.CONFIRMED_GREEN:
            self.state = TrafficState.TRACKING_GREEN
            return self._emit(reason="confirmed_to_tracking_green", chime=False)

        if self.state == TrafficState.TRACKING_GREEN:
            if stable_color == LightColor.YELLOW:
                self.state = TrafficState.TRACKING_YELLOW
                reason = "green_to_yellow"
            elif stable_color == LightColor.RED:
                self.state = TrafficState.TRACKING_RED
                reason = "green_to_red"
            return self._emit(reason=reason, chime=False)

        if self.state == TrafficState.TRACKING_YELLOW:
            if stable_color == LightColor.RED:
                self.state = TrafficState.TRACKING_RED
                reason = "yellow_to_red"
            elif stable_color == LightColor.GREEN:
                self.state = TrafficState.TRACKING_GREEN
                reason = "yellow_to_green"
            return self._emit(reason=reason, chime=False)

        if self.state == TrafficState.LOST:
            # Reacquire quickly based on stable color.
            if stable_color == LightColor.RED:
                self.state = TrafficState.TRACKING_RED
                reason = "lost_reacquire_red"
            elif stable_color == LightColor.GREEN:
                self.state = TrafficState.TRACKING_GREEN
                reason = "lost_reacquire_green"
            elif stable_color == LightColor.YELLOW:
                self.state = TrafficState.TRACKING_YELLOW
                reason = "lost_reacquire_yellow"
            return self._emit(reason=reason, chime=False)

        return self._emit(reason=reason, chime=False)

    def _handle_missing_observation(self) -> StateUpdateOutput:
        self._tentative_green_frames = 0
        self.lost_counter += 1
        if self.lost_counter <= self.config.lost_hold_frames:
            self.state = TrafficState.LOST
            return self._emit(reason="occlusion_hold", chime=False)

        self.reset()
        return self._emit(reason="lost_timeout_reset", chime=False)

    def _set_buffer_size(self, lighting: LightingCondition, speed_mph: float = 0.0) -> None:
        if lighting == LightingCondition.DAY:
            base = self.config.adaptive_buffer.day
            cap = self.config.adaptive_buffer.night
        elif lighting == LightingCondition.DUSK:
            base = self.config.adaptive_buffer.dusk
            cap = self.config.adaptive_buffer.night
        else:
            base = self.config.adaptive_buffer.night
            cap = self.config.adaptive_buffer.night

        if self.config.speed_adaptive_buffer and speed_mph > 0:
            extra = int((speed_mph / 60.0) * (cap - base))
            self.buffer_size = min(base + extra, cap)
        else:
            self.buffer_size = base

        while len(self.buffer) > self.buffer_size:
            self.buffer.popleft()

    def _tick_cooldown(self) -> None:
        if self.cooldown_remaining > 0:
            self.cooldown_remaining -= 1

    def _push_buffer(self, color: LightColor) -> None:
        self.buffer.append(color)
        while len(self.buffer) > self.buffer_size:
            self.buffer.popleft()

    def _stable_buffer_color(self) -> LightColor | None:
        if len(self.buffer) < self.buffer_size:
            return None

        counts: dict[LightColor, int] = {}
        for c in self.buffer:
            counts[c] = counts.get(c, 0) + 1

        best_color = max(counts, key=lambda c: counts[c])
        best_ratio = counts[best_color] / float(self.buffer_size)
        return best_color if best_ratio >= 0.6 else None

    def _should_fire_chime(self, speed_mph: float) -> bool:
        if speed_mph >= self.config.speed_gate_mph:
            return False
        if self.cooldown_remaining > 0:
            return False
        return True

    def _emit(self, reason: str, chime: bool) -> StateUpdateOutput:
        return StateUpdateOutput(
            state=self.state,
            chime_fire=chime,
            transition_reason=reason,
            buffer_snapshot=[c.value for c in self.buffer],
            lost_counter=self.lost_counter,
            cooldown_remaining=self.cooldown_remaining,
        )


def parse_color(value: str) -> LightColor:
    return LightColor(value.lower())


def parse_lighting(value: str) -> LightingCondition:
    return LightingCondition(value.lower())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Adaptive state machine demo")
    parser.add_argument("--observed-color", default="red", help="red|green|yellow|off|none")
    parser.add_argument("--reliability", type=float, default=0.90)
    parser.add_argument("--lighting", default="day", help="day|dusk|night")
    parser.add_argument("--speed-mph", type=float, default=0.0)
    parser.add_argument("--pre-chime-confirmed", action="store_true")
    parser.add_argument("--out-json", type=Path, default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manager = AdaptiveStateManager()

    observed: LightColor | None
    if args.observed_color.lower() == "none":
        observed = None
    else:
        observed = parse_color(args.observed_color)

    out = manager.update(
        StateUpdateInput(
            observed_color=observed,
            reliability_score=clip01(args.reliability),
            lighting=parse_lighting(args.lighting),
            speed_mph=max(0.0, args.speed_mph),
            pre_chime_confirmed=args.pre_chime_confirmed,
        )
    )

    payload = asdict(out)
    serialized = json.dumps(payload, indent=2)
    if args.out_json is not None:
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(serialized + "\n", encoding="utf-8")
    print(serialized)


if __name__ == "__main__":
    main()
