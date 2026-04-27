import unittest

from primary_light_selector import (
    BoundingBox,
    LightCandidate,
    PrimaryLightSelector,
    PrimaryLightSelectorConfig,
)


def c(box: tuple[float, float, float, float], cid: str) -> LightCandidate:
    return LightCandidate(candidate_id=cid, bbox=BoundingBox(*box))


class PrimaryLightSelectorTests(unittest.TestCase):
    def setUp(self) -> None:
        cfg = PrimaryLightSelectorConfig(frame_width=1000, frame_height=600)
        self.selector = PrimaryLightSelector(cfg)

    def test_single_light_in_frame(self) -> None:
        only = c((460, 140, 520, 300), "only")
        selected = self.selector.update([only])

        self.assertIsNotNone(selected)
        assert selected is not None
        self.assertEqual(selected.candidate.candidate_id, "only")

    def test_two_lights_side_by_side_prefers_larger_centered(self) -> None:
        left_small = c((120, 170, 160, 250), "left_small")
        center_large = c((450, 120, 560, 330), "center_large")

        selected = self.selector.update([left_small, center_large])

        self.assertIsNotNone(selected)
        assert selected is not None
        self.assertEqual(selected.candidate.candidate_id, "center_large")

    def test_primary_plus_distant_intersection_ignores_distant(self) -> None:
        primary = c((455, 145, 545, 320), "primary")
        distant = c((865, 60, 885, 95), "distant")

        selected = self.selector.update([primary, distant])

        self.assertIsNotNone(selected)
        assert selected is not None
        self.assertEqual(selected.candidate.candidate_id, "primary")

    def test_primary_occluded_for_three_frames_maintains_selection(self) -> None:
        primary = c((460, 140, 550, 330), "primary")
        distractor = c((830, 100, 860, 150), "distractor")

        first = self.selector.update([primary, distractor])
        self.assertIsNotNone(first)
        assert first is not None
        self.assertEqual(first.candidate.candidate_id, "primary")

        occl_1 = self.selector.update([])
        occl_2 = self.selector.update([])
        occl_3 = self.selector.update([])
        lost = self.selector.update([])

        self.assertIsNotNone(occl_1)
        self.assertIsNotNone(occl_2)
        self.assertIsNotNone(occl_3)
        self.assertTrue(occl_1.carried_over)
        self.assertTrue(occl_2.carried_over)
        self.assertTrue(occl_3.carried_over)

        assert occl_1 is not None
        assert occl_2 is not None
        assert occl_3 is not None
        self.assertEqual(occl_1.candidate.candidate_id, "primary")
        self.assertEqual(occl_2.candidate.candidate_id, "primary")
        self.assertEqual(occl_3.candidate.candidate_id, "primary")

        self.assertIsNone(lost)

    def test_left_turn_arrow_vs_straight_prefers_straight(self) -> None:
        # Simulated arrow head: wider aspect ratio (low h/w score)
        left_arrow = c((390, 175, 490, 235), "left_arrow")

        # Straight signal cluster: taller aspect ratio close to expected h/w
        straight = c((510, 130, 570, 290), "straight")

        selected = self.selector.update([left_arrow, straight])

        self.assertIsNotNone(selected)
        assert selected is not None
        self.assertEqual(selected.candidate.candidate_id, "straight")


if __name__ == "__main__":
    unittest.main()
