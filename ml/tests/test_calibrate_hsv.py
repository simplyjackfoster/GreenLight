import sys
import unittest
import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from calibrate_hsv import compute_hsv_percentiles, format_swift_ranges


class TestCalibrateHSV(unittest.TestCase):
    def _make_bgr_patch(self, h_deg: float, s: float, v: float) -> np.ndarray:
        import cv2

        h_cv = int(h_deg / 2)
        s_cv = int(s * 255)
        v_cv = int(v * 255)
        hsv = np.full((10, 10, 3), [h_cv, s_cv, v_cv], dtype=np.uint8)
        return cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)

    def test_pure_red_lands_in_red_range(self):
        red_patch = self._make_bgr_patch(0, 0.9, 0.9)
        result = compute_hsv_percentiles({"red": [red_patch]})
        self.assertIn("red", result)
        self.assertLessEqual(result["red"]["h_p05"], 5)

    def test_pure_green_lands_in_green_range(self):
        green_patch = self._make_bgr_patch(120, 0.8, 0.8)
        result = compute_hsv_percentiles({"green": [green_patch]})
        self.assertIn("green", result)
        p05 = result["green"]["h_p05"]
        p95 = result["green"]["h_p95"]
        self.assertGreaterEqual(p95, p05)

    def test_format_swift_ranges_produces_valid_output(self):
        stats = {
            "red": {"h_p05": 355.0, "h_p95": 10.0, "s_p05": 0.5, "s_p95": 0.95, "v_p05": 0.3, "v_p95": 0.95, "sample_count": 100},
            "green": {"h_p05": 90.0, "h_p95": 150.0, "s_p05": 0.4, "s_p95": 0.9, "v_p05": 0.3, "v_p95": 0.9, "sample_count": 100},
        }
        output = format_swift_ranges(stats)
        self.assertIn("red", output.lower())
        self.assertIn("green", output.lower())
        self.assertIn("isRed", output)
        self.assertIn("isGreen", output)


if __name__ == "__main__":
    unittest.main()
