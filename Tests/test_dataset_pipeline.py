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


    def test_hard_negative_strata_do_not_poison_positive_cap(self) -> None:
        # A single hard_negative record must not collapse the positive stratum cap.
        image = Path("/tmp/fake.jpg")
        records: list[AnnotationRecord] = []

        # 100 positive records in one stratum
        for _ in range(100):
            records.append(
                AnnotationRecord("x", image, (0, 0, 10, 10), "red", "red", lighting="day", scale="medium")
            )
        # 1 hard_negative record — rarest if it were included in the cap calculation
        records.append(
            AnnotationRecord("x", image, (0, 0, 5, 5), "hard_negative", "mined", lighting="day", scale="medium")
        )

        balanced = balance_records_by_strata(records, seed=0, balance_cap_multiplier=2.0)

        positives = [r for r in balanced if r.label == "red"]
        hard_negs = [r for r in balanced if r.label == "hard_negative"]

        # Cap should be floor(100 * 2.0) = 200 for positives, so all 100 are kept.
        self.assertEqual(len(positives), 100)
        # Hard negatives pass through uncapped.
        self.assertEqual(len(hard_negs), 1)

    def test_balance_cap_below_1_is_rejected(self) -> None:
        import argparse
        from dataset_pipeline import validate_args

        args = argparse.Namespace(
            split_ratio=0.85,
            padding=0.15,
            crop_size=64,
            min_box_area=16.0,
            balance_cap=0.5,
            hard_neg_ratio=0.2,
            hard_neg_per_image=2,
        )
        with self.assertRaises(ValueError, msg="--balance-cap < 1.0 should be rejected"):
            validate_args(args)

    def test_stratum_cap_minimum_is_one(self) -> None:
        # Even with balance_cap_multiplier=1.0 and rarest_count=1, no records are lost.
        image = Path("/tmp/fake.jpg")
        records = [
            AnnotationRecord("x", image, (0, 0, 10, 10), "red", "red", lighting="day", scale="near"),
            AnnotationRecord("x", image, (0, 0, 10, 10), "green", "green", lighting="day", scale="near"),
        ]

        balanced = balance_records_by_strata(records, seed=0, balance_cap_multiplier=1.0)
        self.assertEqual(len(balanced), 2)


if __name__ == "__main__":
    unittest.main()
