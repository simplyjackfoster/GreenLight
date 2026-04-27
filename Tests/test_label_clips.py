import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).parent.parent))
from label_clips import build_frame_csv, interpolate_annotations


class TestLabelClips(unittest.TestCase):
    def test_interpolate_fills_frames_between_keyframes(self):
        keyframes = {0: "red", 5: "green"}
        result = interpolate_annotations(keyframes, total_frames=8)
        self.assertEqual(result[0], "red")
        self.assertEqual(result[1], "red")
        self.assertEqual(result[4], "red")
        self.assertEqual(result[5], "green")
        self.assertEqual(result[7], "green")

    def test_build_frame_csv_columns(self):
        annotations = {i: "red" for i in range(3)}
        rows = build_frame_csv(
            annotations=annotations,
            lighting="day",
            visible_lights=1,
            fps=30.0,
        )
        self.assertEqual(len(rows), 3)
        self.assertIn("frame_index", rows[0])
        self.assertIn("gt_state", rows[0])
        self.assertIn("pred_state", rows[0])
        self.assertIn("chime", rows[0])
        self.assertIn("lighting", rows[0])
        self.assertIn("visible_lights", rows[0])
        self.assertEqual(rows[0]["gt_state"], "red")
        self.assertEqual(rows[0]["pred_state"], "none")
        self.assertEqual(rows[0]["chime"], "0")

    def test_interpolate_empty_keyframes_raises(self):
        with self.assertRaises(ValueError):
            interpolate_annotations({}, total_frames=10)


if __name__ == "__main__":
    unittest.main()
