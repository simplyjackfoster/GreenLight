#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from adaptive_state_manager import (
    AdaptiveStateManager,
    BufferConfig,
    LightColor,
    LightingCondition,
    StateManagerConfig,
    StateUpdateInput,
    TrafficState,
)


def make_input(
    color: LightColor | None,
    speed_mph: float = 0.0,
    lighting: LightingCondition = LightingCondition.DAY,
    reliability: float = 0.95,
    pre_chime: bool = False,
) -> StateUpdateInput:
    return StateUpdateInput(
        observed_color=color,
        reliability_score=reliability,
        lighting=lighting,
        speed_mph=speed_mph,
        pre_chime_confirmed=pre_chime,
    )


class TestTentativeGreenTimeout(unittest.TestCase):
    def _advance_to_tentative(self, mgr: AdaptiveStateManager) -> None:
        mgr.update(make_input(LightColor.RED))
        mgr.update(make_input(LightColor.GREEN))
        self.assertEqual(mgr.state, TrafficState.TENTATIVE_GREEN)

    def test_tentative_green_times_out_and_resets(self):
        config = StateManagerConfig(
            tentative_green_timeout_frames=3,
            speed_adaptive_buffer=False,
            adaptive_buffer=BufferConfig(day=1, dusk=1, night=1),
        )
        mgr = AdaptiveStateManager(config)
        self._advance_to_tentative(mgr)

        for _ in range(3):
            mgr.update(make_input(LightColor.GREEN, pre_chime=False))

        self.assertNotEqual(mgr.state, TrafficState.TENTATIVE_GREEN)

    def test_tentative_green_does_not_timeout_before_limit(self):
        config = StateManagerConfig(
            tentative_green_timeout_frames=5,
            speed_adaptive_buffer=False,
            adaptive_buffer=BufferConfig(day=1, dusk=1, night=1),
        )
        mgr = AdaptiveStateManager(config)
        self._advance_to_tentative(mgr)

        for _ in range(4):
            mgr.update(make_input(LightColor.GREEN, pre_chime=False))

        self.assertEqual(mgr.state, TrafficState.TENTATIVE_GREEN)


class TestSpeedAdaptiveBuffer(unittest.TestCase):
    def test_buffer_larger_at_high_speed(self):
        config = StateManagerConfig(speed_adaptive_buffer=True)
        mgr = AdaptiveStateManager(config)
        mgr._set_buffer_size(LightingCondition.DAY, speed_mph=50.0)
        high_speed_size = mgr.buffer_size

        mgr._set_buffer_size(LightingCondition.DAY, speed_mph=0.0)
        stationary_size = mgr.buffer_size

        self.assertGreaterEqual(high_speed_size, stationary_size)

    def test_buffer_capped_at_night_maximum(self):
        config = StateManagerConfig(speed_adaptive_buffer=True)
        mgr = AdaptiveStateManager(config)
        mgr._set_buffer_size(LightingCondition.NIGHT, speed_mph=100.0)
        self.assertLessEqual(mgr.buffer_size, config.adaptive_buffer.night)


if __name__ == "__main__":
    unittest.main()
