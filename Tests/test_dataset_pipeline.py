from __future__ import annotations

from pathlib import Path
import unittest

from dataset_pipeline import (
    AnnotationRecord,
    balance_records_by_strata,
    classify_lighting_from_luminance,
    classify_scale_from_fraction,
    is_hard_negative_candidate,
    run_data_quality_loop,
)


class DataQualityLoopTests(unittest.TestCase):
    def test_luminance_thresholds(self) -> None:
        self.assertEqual(classify_lighting_from_luminance(84.9), "night")
        self.assertEqual(classify_lighting_from_luminance(85.0), "dusk")
        self.assertEqual(classify_lighting_from_luminance(170.0), "dusk")
        self.assertEqual(classify_lighting_from_luminance(170.1), "day")

    def test_scale_thresholds(self) -> None:
        self.assertEqual(classify_scale_from_fraction(0.0099), "distant")
        self.assertEqual(classify_scale_from_fraction(0.01), "medium")
        self.assertEqual(classify_scale_from_fraction(0.05), "medium")
        self.assertEqual(classify_scale_from_fraction(0.0501), "near")

    def test_hard_negative_iou_gate(self) -> None:
        ground_truth = [(10.0, 10.0, 30.0, 30.0)]

        overlapping = (12.0, 12.0, 28.0, 28.0)
        non_overlapping = (60.0, 60.0, 80.0, 80.0)

        self.assertFalse(is_hard_negative_candidate(overlapping, ground_truth))
        self.assertTrue(is_hard_negative_candidate(non_overlapping, ground_truth))

    def test_balance_cap_respected(self) -> None:
        image = Path("/tmp/fake.jpg")
        records: list[AnnotationRecord] = []

        # rarest stratum count = 1 (night, near, green)
        records.append(
            AnnotationRecord("x", image, (0, 0, 10, 10), "green", "green", lighting="night", scale="near")
        )

        # oversized stratum count = 5 (day, medium, red)
        for _ in range(5):
            records.append(
                AnnotationRecord("x", image, (0, 0, 10, 10), "red", "red", lighting="day", scale="medium")
            )

        balanced = balance_records_by_strata(records, seed=123, balance_cap_multiplier=2.0)

        day_medium_red = [
            rec for rec in balanced if rec.lighting == "day" and rec.scale == "medium" and rec.label == "red"
        ]
        night_near_green = [
            rec for rec in balanced if rec.lighting == "night" and rec.scale == "near" and rec.label == "green"
        ]

        self.assertEqual(len(night_near_green), 1)
        self.assertEqual(len(day_medium_red), 2)

    def test_skip_quality_loop_is_passthrough(self) -> None:
        records = [
            AnnotationRecord(
                dataset="lisa",
                image_path=Path("/tmp/a.jpg"),
                bbox_xyxy=(1.0, 1.0, 10.0, 10.0),
                label="red",
                raw_label="stop",
            )
        ]

        out = run_data_quality_loop(
            records,
            seed=42,
            balance_cap_multiplier=2.0,
            hard_neg_ratio=0.2,
            hard_neg_per_image=2,
            skip_quality_loop=True,
        )

        self.assertEqual(out, records)
        self.assertIsNone(out[0].lighting)
        self.assertIsNone(out[0].scale)


if __name__ == "__main__":
    unittest.main()
