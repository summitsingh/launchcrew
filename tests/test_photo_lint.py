"""Photo lint coverage: headers, ratios, resolution, audit.

New-file-only coverage for launchcrew/photo_lint.py. Stdlib
unittest with synthetic minimal PNG and JPEG byte sequences.
"""

import os
import struct
import tempfile
import unittest

from launchcrew.photo_lint import (
    PHOTO_LINT_VERSION,
    TARGET_RATIOS,
    audit_photo,
    get_image_dimensions,
    lint_photo_aspect_ratio,
    lint_photo_resolution,
)


def make_png(width, height):
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    out = bytearray(b"\x89PNG\r\n\x1a\n")
    out += struct.pack(">I", 13) + b"IHDR" + ihdr + struct.pack(">I", 0)
    out += struct.pack(">I", 0) + b"IEND" + struct.pack(">I", 0)
    return bytes(out)


def make_jpeg(width, height, progressive=False):
    sof = 0xC2 if progressive else 0xC0
    frame = bytes([0x08]) + struct.pack(">H", height) + struct.pack(">H", width)
    frame += bytes([0x03, 0x01, 0x11, 0x00, 0x02, 0x11, 0x01, 0x03, 0x11, 0x01])
    seg_len = len(frame) + 2
    out = bytearray([0xFF, 0xD8])
    out += bytes([0xFF, sof]) + struct.pack(">H", seg_len) + frame
    out += bytes([0xFF, 0xD9])
    return bytes(out)


class VersionTests(unittest.TestCase):
    def test_version(self):
        self.assertEqual(PHOTO_LINT_VERSION, "photo-lint/v1")

    def test_targets(self):
        self.assertEqual(TARGET_RATIOS["feed_square"]["label"], "1:1")
        self.assertAlmostEqual(TARGET_RATIOS["feed_square"]["ratio"], 1.0)
        self.assertEqual(TARGET_RATIOS["instagram_ad_portrait"]["label"], "4:5")
        self.assertAlmostEqual(
            TARGET_RATIOS["instagram_ad_portrait"]["ratio"], 0.80)
        self.assertEqual(TARGET_RATIOS["reels_story_vertical"]["label"], "9:16")
        self.assertAlmostEqual(
            TARGET_RATIOS["reels_story_vertical"]["ratio"], 0.5625)
        self.assertEqual(TARGET_RATIOS["landscape"]["label"], "16:9")
        self.assertAlmostEqual(
            TARGET_RATIOS["landscape"]["ratio"], 16.0 / 9.0, places=3)


class GetDimensionsTests(unittest.TestCase):
    def test_png_sizes(self):
        for width, height in (
            (1080, 1080), (1080, 1350), (1080, 1920), (500, 500)):
            with self.subTest(width=width, height=height):
                self.assertEqual(
                    get_image_dimensions(make_png(width, height)),
                    (width, height))

    def test_jpeg_baseline_sizes(self):
        for width, height in (
            (1080, 1080), (1080, 1350), (1080, 1920), (500, 500)):
            with self.subTest(width=width, height=height):
                self.assertEqual(
                    get_image_dimensions(make_jpeg(width, height)),
                    (width, height))

    def test_jpeg_progressive_sizes(self):
        self.assertEqual(
            get_image_dimensions(make_jpeg(1080, 1350, progressive=True)),
            (1080, 1350))

    def test_bytearray_and_memoryview(self):
        raw = make_png(1080, 1080)
        self.assertEqual(get_image_dimensions(bytearray(raw)), (1080, 1080))
        self.assertEqual(get_image_dimensions(memoryview(raw)), (1080, 1080))

    def test_file_path(self):
        raw = make_jpeg(1080, 1080)
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            tmp.write(raw)
            path = tmp.name
        try:
            self.assertEqual(get_image_dimensions(path), (1080, 1080))
        finally:
            os.unlink(path)

    def test_invalid_bytes_raise(self):
        for bad in (b"", b"hello", bytes(100), make_png(0, 10)[:8] + bytes(40)):
            with self.subTest(bad=bad[:12]):
                with self.assertRaises(ValueError):
                    get_image_dimensions(bad)

    def test_invalid_type_raises(self):
        for bad in (None, 123, {"w": 1}):
            with self.subTest(bad=bad):
                with self.assertRaises(TypeError):
                    get_image_dimensions(bad)


class AspectRatioTests(unittest.TestCase):
    def test_feed_square_compliant(self):
        result = lint_photo_aspect_ratio(1080, 1080, "feed_square")
        self.assertTrue(result["compliant"])
        self.assertAlmostEqual(result["aspect_ratio"], 1.0)
        self.assertEqual(result["target_ratio"], "1:1")
        self.assertIsNone(result["warning"])

    def test_instagram_portrait_compliant(self):
        result = lint_photo_aspect_ratio(1080, 1350, "instagram_ad_portrait")
        self.assertTrue(result["compliant"])
        self.assertAlmostEqual(result["aspect_ratio"], 0.80)
        self.assertEqual(result["target_ratio"], "4:5")
        self.assertIsNone(result["warning"])

    def test_reels_vertical_compliant(self):
        result = lint_photo_aspect_ratio(1080, 1920, "reels_story_vertical")
        self.assertTrue(result["compliant"])
        self.assertAlmostEqual(result["aspect_ratio"], 0.5625)
        self.assertEqual(result["target_ratio"], "9:16")
        self.assertIsNone(result["warning"])

    def test_landscape_compliant(self):
        result = lint_photo_aspect_ratio(1920, 1080, "landscape")
        self.assertTrue(result["compliant"])
        self.assertEqual(result["target_ratio"], "16:9")
        self.assertIsNone(result["warning"])

    def test_widescreen_fails_square(self):
        result = lint_photo_aspect_ratio(1920, 1080, "feed_square")
        self.assertFalse(result["compliant"])
        self.assertIsNotNone(result["warning"])
        self.assertIn("feed_square", result["warning"])

    def test_square_fails_portrait(self):
        result = lint_photo_aspect_ratio(1080, 1080, "instagram_ad_portrait")
        self.assertFalse(result["compliant"])
        self.assertIsNotNone(result["warning"])

    def test_square_fails_reels(self):
        result = lint_photo_aspect_ratio(1080, 1080, "reels_story_vertical")
        self.assertFalse(result["compliant"])
        self.assertIsNotNone(result["warning"])

    def test_portrait_fails_reels(self):
        result = lint_photo_aspect_ratio(1080, 1350, "reels_story_vertical")
        self.assertFalse(result["compliant"])
        self.assertIsNotNone(result["warning"])

    def test_small_square_ratio_still_compliant(self):
        result = lint_photo_aspect_ratio(500, 500, "feed_square")
        self.assertTrue(result["compliant"])
        self.assertIsNone(result["warning"])

    def test_tolerance_boundary(self):
        result = lint_photo_aspect_ratio(1000, 1000, "feed_square")
        self.assertTrue(result["compliant"])
        result = lint_photo_aspect_ratio(1030, 1000, "feed_square")
        self.assertFalse(result["compliant"])

    def test_unknown_channel_raises(self):
        with self.assertRaises(ValueError):
            lint_photo_aspect_ratio(1080, 1080, "nope")

    def test_bad_dimensions_raise(self):
        for width, height in ((0, 10), (10, 0), (-5, 10), ("a", 10)):
            with self.subTest(width=width, height=height):
                with self.assertRaises(ValueError):
                    lint_photo_aspect_ratio(width, height, "feed_square")


class ResolutionTests(unittest.TestCase):
    def test_retina_sizes_pass(self):
        for width, height in ((1080, 1080), (1080, 1350), (1080, 1920)):
            with self.subTest(width=width, height=height):
                result = lint_photo_resolution(width, height)
                self.assertTrue(result["compliant"])
                self.assertEqual(result["width"], width)
                self.assertEqual(result["height"], height)
                self.assertIsNone(result["warning"])

    def test_low_res_warns(self):
        result = lint_photo_resolution(500, 500)
        self.assertFalse(result["compliant"])
        self.assertEqual(result["width"], 500)
        self.assertEqual(result["height"], 500)
        self.assertIsNotNone(result["warning"])
        self.assertIn("500x500", result["warning"])

    def test_one_axis_short_warns(self):
        self.assertFalse(lint_photo_resolution(1080, 500)["compliant"])
        self.assertFalse(lint_photo_resolution(500, 1080)["compliant"])

    def test_custom_minima(self):
        self.assertTrue(
            lint_photo_resolution(500, 500, min_width=500, min_height=500)[
                "compliant"])
        self.assertFalse(
            lint_photo_resolution(500, 500, min_width=600, min_height=500)[
                "compliant"])

    def test_bad_inputs_raise(self):
        with self.assertRaises(ValueError):
            lint_photo_resolution(0, 1080)
        with self.assertRaises(ValueError):
            lint_photo_resolution(1080, 1080, min_width=0, min_height=1080)


class AuditTests(unittest.TestCase):
    def test_audit_square_png(self):
        summary = audit_photo(make_png(1080, 1080), ["feed_square"])
        self.assertEqual(summary["version"], "photo-lint/v1")
        self.assertEqual(summary["width"], 1080)
        self.assertEqual(summary["height"], 1080)
        self.assertAlmostEqual(summary["aspect_ratio"], 1.0)
        self.assertTrue(summary["compliant"])
        self.assertEqual(summary["warnings"], [])
        self.assertTrue(summary["channels"]["feed_square"]["compliant"])
        self.assertTrue(summary["resolution"]["compliant"])

    def test_audit_portrait_jpeg(self):
        summary = audit_photo(
            make_jpeg(1080, 1350),
            ["feed_square", "instagram_ad_portrait", "reels_story_vertical"])
        self.assertTrue(summary["channels"]["instagram_ad_portrait"][
            "compliant"])
        self.assertFalse(summary["channels"]["feed_square"]["compliant"])
        self.assertFalse(summary["channels"]["reels_story_vertical"][
            "compliant"])
        self.assertTrue(summary["resolution"]["compliant"])
        self.assertFalse(summary["compliant"])
        self.assertTrue(summary["warnings"])

    def test_audit_low_res_reports_both(self):
        summary = audit_photo(make_png(500, 500), ["feed_square"])
        self.assertTrue(summary["channels"]["feed_square"]["compliant"])
        self.assertFalse(summary["resolution"]["compliant"])
        self.assertFalse(summary["compliant"])
        self.assertEqual(len(summary["warnings"]), 1)

    def test_audit_low_res_wrong_ratio_reports_two(self):
        summary = audit_photo(
            make_png(500, 500), ["instagram_ad_portrait"])
        self.assertFalse(summary["compliant"])
        self.assertEqual(len(summary["warnings"]), 2)

    def test_audit_reels_jpeg(self):
        summary = audit_photo(
            make_jpeg(1080, 1920), ["reels_story_vertical"])
        self.assertTrue(summary["compliant"])
        self.assertEqual(summary["warnings"], [])

    def test_audit_accepts_path(self):
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp.write(make_png(1080, 1080))
            path = tmp.name
        try:
            summary = audit_photo(path, ["feed_square"])
        finally:
            os.unlink(path)
        self.assertTrue(summary["compliant"])

    def test_audit_bad_channels_raise(self):
        with self.assertRaises(ValueError):
            audit_photo(make_png(1080, 1080), [])
        with self.assertRaises(ValueError):
            audit_photo(make_png(1080, 1080), ["unknown_channel"])


if __name__ == "__main__":
    unittest.main()
