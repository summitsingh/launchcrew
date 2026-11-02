"""Focal crop coverage: centered equivalence, bias, clamping, digests.

Pure stdlib unittest with synthetic dimensions only. No DB, no network.
"""

import unittest

from launchcrew import media_library as ml


class NormalizeFocalTests(unittest.TestCase):
    def test_valid_points(self):
        self.assertEqual(ml.normalize_focal_point(0.5, 0.5), (0.5, 0.5))
        self.assertEqual(ml.normalize_focal_point(0, 1), (0.0, 1.0))
        self.assertEqual(ml.normalize_focal_point(1, 0), (1.0, 0.0))

    def test_invalid_points_raise(self):
        for bad in ((-0.1, 0.5), (0.5, 1.1), ("left", 0.5), (0.5, None),
                    (True, 0.5), (0.5, False), (None, None)):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    ml.normalize_focal_point(*bad)


class FocalBoxTests(unittest.TestCase):
    def test_center_reproduces_centered_box(self):
        for width, height in ((1600, 900), (900, 1600), (1080, 1080),
                              (1080, 1350), (1920, 1080), (801, 1301)):
            for target in ml.DERIVATIVE_KEYS:
                with self.subTest(width=width, height=height, target=target):
                    self.assertEqual(
                        ml.compute_focal_crop_box(width, height, target),
                        ml.compute_crop_box(width, height, target))
                    self.assertEqual(
                        ml.compute_focal_crop_box(width, height, target, 0.5, 0.5),
                        ml.compute_crop_box(width, height, target))

    def test_bias_slides_offset(self):
        box_left = ml.compute_focal_crop_box(1600, 900, "4:5", 0.0, 0.5)
        box_right = ml.compute_focal_crop_box(1600, 900, "4:5", 1.0, 0.5)
        box_mid = ml.compute_focal_crop_box(1600, 900, "4:5", 0.5, 0.5)
        self.assertEqual(box_left["x"], 0)
        self.assertEqual(box_right["x"], 1600 - box_right["width"])
        self.assertGreater(box_right["x"], box_mid["x"])
        self.assertGreater(box_mid["x"], box_left["x"])
        self.assertEqual(box_left["y"], 0)
        self.assertEqual(box_left["width"], box_right["width"])

    def test_vertical_bias(self):
        box_top = ml.compute_focal_crop_box(900, 1600, "16:9", 0.5, 0.0)
        box_bottom = ml.compute_focal_crop_box(900, 1600, "16:9", 0.5, 1.0)
        self.assertEqual(box_top["y"], 0)
        self.assertEqual(box_bottom["y"], 1600 - box_bottom["height"])
        self.assertGreater(box_bottom["y"], box_top["y"])

    def test_box_stays_in_frame(self):
        for width, height in ((1600, 900), (900, 1600), (1080, 1080), (801, 1301)):
            for target in ml.DERIVATIVE_KEYS:
                for focal in ((0.0, 0.0), (1.0, 1.0), (0.0, 1.0),
                              (1.0, 0.0), (0.25, 0.75)):
                    with self.subTest(width=width, target=target, focal=focal):
                        box = ml.compute_focal_crop_box(
                            width, height, target, *focal)
                        self.assertGreaterEqual(box["x"], 0)
                        self.assertGreaterEqual(box["y"], 0)
                        self.assertLessEqual(box["x"] + box["width"], width)
                        self.assertLessEqual(box["y"] + box["height"], height)

    def test_bad_inputs_raise(self):
        with self.assertRaises(ValueError):
            ml.compute_focal_crop_box(0, 900, "4:5", 0.2, 0.5)
        with self.assertRaises(ValueError):
            ml.compute_focal_crop_box(1600, 900, "nope", 0.2, 0.5)
        with self.assertRaises(ValueError):
            ml.compute_focal_crop_box(1600, 900, "4:5", 2.0, 0.5)


class FocalDigestTests(unittest.TestCase):
    def test_deterministic_and_bound(self):
        first = ml.focal_derivative_digest("abc", "4:5", 0.2, 0.8)
        self.assertEqual(first, ml.focal_derivative_digest("abc", "4:5", 0.2, 0.8))
        self.assertEqual(len(first), 64)
        int(first, 16)

    def test_differs_by_focal_and_key(self):
        base = ml.focal_derivative_digest("abc", "4:5", 0.5, 0.5)
        self.assertNotEqual(base, ml.focal_derivative_digest("abc", "4:5", 0.2, 0.5))
        self.assertNotEqual(base, ml.focal_derivative_digest("abc", "1:1", 0.5, 0.5))
        self.assertNotEqual(base, ml.focal_derivative_digest("abd", "4:5", 0.5, 0.5))


class BuildFocalTests(unittest.TestCase):
    def test_record_shape(self):
        records = ml.build_focal_derivatives("asset1", 1600, 900, "digest9", 0.0, 0.5)
        self.assertEqual(set(records), set(ml.DERIVATIVE_KEYS))
        record = records["4:5"]
        self.assertEqual(record["crop_box"]["x"], 0)
        self.assertEqual(record["focal_point"], {"x": 0.0, "y": 0.5})
        self.assertTrue(record["original_preserved"])
        self.assertEqual(record["derived_from_id"], "asset1")

    def test_single_key_subset(self):
        records = ml.build_focal_derivatives("asset1", 1600, 900, "digest9",
                                             1.0, 0.5, ["9:16"])
        self.assertEqual(set(records), {"9:16"})

    def test_unknown_key_raises(self):
        with self.assertRaises(ValueError):
            ml.build_focal_derivatives("asset1", 1600, 900, "digest9",
                                       0.5, 0.5, ["wide"])


if __name__ == "__main__":
    unittest.main()
