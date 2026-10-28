"""Task 1 red tests: photo geometry policy v1.

Synthetic hand-authored fixtures only. No provider output, no photos.
"""
import unittest

from launchcrew.photo_policy import (
    PHOTO_POLICY_VERSION,
    classify_photo_geometry,
    suggest_crop,
)


def _rec(box, mask=None, frame=0, object_id=1):
    if mask is None:
        x1, y1, x2, y2, w, h = box
        mask = {
            "x": 0,
            "y": 0,
            "height": y2 - y1 + 1,
            "width": x2 - x1 + 1,
            "encoding": "lossless",
            "payload": "AA==",
        }
    return {"frame": frame, "object_id": object_id, "box": box, "mask": mask}


class PhotoPolicyTests(unittest.TestCase):
    def test_policy_version(self):
        self.assertEqual(PHOTO_POLICY_VERSION, "photo-geometry/v1")

    def test_single_clear_box_is_detected(self):
        rec = _rec((100, 100, 300, 400, 1600, 1200))
        verdict = classify_photo_geometry([rec], (1600, 1200))
        self.assertEqual(verdict["label"], "detected")
        self.assertEqual(verdict["policy_version"], "photo-geometry/v1")

    def test_valid_cropped_mask_dims_pass(self):
        # Box 100,100,300,400 has inclusive extent 201x301; the cropped
        # mask raster is 301 rows x 201 cols at origin (0,0).
        rec = {
            "frame": 0,
            "object_id": 1,
            "box": (100, 100, 300, 400, 1600, 1200),
            "mask": {
                "x": 0,
                "y": 0,
                "height": 301,
                "width": 201,
                "encoding": "lossless",
                "payload": "AA==",
            },
        }
        self.assertEqual(
            classify_photo_geometry([rec], (1600, 1200))["label"], "detected"
        )

    def test_mask_origin_must_be_zero(self):
        rec = {
            "frame": 0,
            "object_id": 1,
            "box": (100, 100, 300, 400, 1600, 1200),
            "mask": {
                "x": 100,
                "y": 100,
                "height": 301,
                "width": 201,
                "encoding": "lossless",
                "payload": "AA==",
            },
        }
        verdict = classify_photo_geometry([rec], (1600, 1200))
        self.assertEqual(verdict["label"], "unknown")
        self.assertEqual(verdict["reason"], "fix_photo")

    def test_mask_dims_must_be_positive_and_bounded(self):
        base_box = (100, 100, 300, 400, 1600, 1200)
        for bad_mask in (
            {"x": 0, "y": 0, "height": 0, "width": 201,
             "encoding": "lossless", "payload": "AA=="},
            {"x": 0, "y": 0, "height": 301, "width": 0,
             "encoding": "lossless", "payload": "AA=="},
            {"x": 0, "y": 0, "height": 1201, "width": 201,
             "encoding": "lossless", "payload": "AA=="},
            {"x": 0, "y": 0, "height": 301, "width": 1601,
             "encoding": "lossless", "payload": "AA=="},
        ):
            rec = {"frame": 0, "object_id": 1, "box": base_box, "mask": bad_mask}
            verdict = classify_photo_geometry([rec], (1600, 1200))
            self.assertEqual(verdict["label"], "unknown", bad_mask)
            self.assertEqual(verdict["reason"], "fix_photo")

    def test_mask_equality_with_frame_never_required(self):
        # A small cropped mask well under frame size is valid: the box
        # below clears the size gate while the mask is only 50x50.
        rec = _rec((100, 100, 300, 400, 1600, 1200))
        rec["mask"]["height"] = 50
        rec["mask"]["width"] = 50
        self.assertEqual(
            classify_photo_geometry([rec], (1600, 1200))["label"], "detected"
        )

    def test_payload_is_opaque_and_never_decoded(self):
        rec = _rec((100, 100, 300, 400, 1600, 1200))
        rec["mask"]["payload"] = "not-base64!!!"
        verdict = classify_photo_geometry([rec], (1600, 1200))
        self.assertEqual(verdict["label"], "detected")
        self.assertNotIn("payload", verdict)

    def test_zero_records_is_not_detected_without_frame_dims(self):
        verdict = classify_photo_geometry([], None)
        self.assertEqual(verdict["label"], "not_detected")
        self.assertEqual(verdict["reason"], "no_match")

    def test_edge_touch_is_possible_clipping(self):
        rec = _rec((0, 10, 200, 400, 1600, 1200))
        self.assertEqual(
            classify_photo_geometry([rec], (1600, 1200))["label"],
            "possible_clipping",
        )

    def test_two_px_edge_gate_boundary(self):
        # Distance 2 to the edge still clips; distance 3 clears.
        touching = _rec((3, 50, 200, 400, 1600, 1200))
        touching["box"] = (2, 50, 200, 400, 1600, 1200)
        touching["mask"] = {
            "x": 0, "y": 0, "height": 351, "width": 199,
            "encoding": "lossless", "payload": "AA==",
        }
        self.assertEqual(
            classify_photo_geometry([touching], (1600, 1200))["label"],
            "possible_clipping",
        )
        clear = _rec((3, 50, 200, 400, 1600, 1200))
        self.assertEqual(
            classify_photo_geometry([clear], (1600, 1200))["label"], "detected"
        )

    def test_small_area_clips(self):
        # Frame 100x100 area 10000; 2% is 200. Area 100 clips.
        rec = _rec((40, 40, 49, 49, 100, 100))
        self.assertEqual(
            classify_photo_geometry([rec], (100, 100))["label"],
            "possible_clipping",
        )

    def test_large_area_clips(self):
        # Frame 100x100; box covering 100x99 = 9900 > 98% clips.
        rec = _rec((0, 0, 99, 98, 100, 100))
        self.assertEqual(
            classify_photo_geometry([rec], (100, 100))["label"],
            "possible_clipping",
        )

    def test_inclusive_area_off_by_one(self):
        # Box (0,0,1,1) covers 2x2 = 4 px, not 1 px. On a 10x10 frame
        # (area 100) that is 4%, so it clears the 2% gate.
        rec = _rec((4, 4, 5, 5, 10, 10))
        verdict = classify_photo_geometry([rec], (10, 10))
        self.assertEqual(verdict["label"], "detected")

    def test_bad_coordinates_fail_closed(self):
        cases = [
            (300, 100, 100, 400, 1600, 1200),  # x2 < x1
            (100, 400, 300, 100, 1600, 1200),  # y2 < y1
            (5, 5, 2000, 400, 1600, 1200),  # x2 beyond frame
            (-1, 5, 100, 400, 1600, 1200),  # x1 negative
            (100, 100, 300, 1200, 1600, 1200),  # y2 beyond frame
        ]
        for box in cases:
            rec = _rec(box)
            verdict = classify_photo_geometry([rec], (1600, 1200))
            self.assertEqual(verdict["label"], "unknown", box)
            self.assertEqual(verdict["reason"], "fix_photo")

    def test_bad_frames_fail_closed(self):
        rec = _rec((100, 100, 300, 400, 1600, 1200))
        # Non-zero record frame.
        bad_frame = _rec((100, 100, 300, 400, 1600, 1200), frame=1)
        self.assertEqual(
            classify_photo_geometry([bad_frame], (1600, 1200))["label"],
            "unknown",
        )
        # Record dims disagree with the passed frame.
        self.assertEqual(
            classify_photo_geometry([rec], (800, 600))["label"], "unknown"
        )
        # Records disagree with each other.
        other = _rec((200, 200, 300, 300, 800, 600), object_id=2)
        verdict = classify_photo_geometry([rec, other], (1600, 1200))
        self.assertEqual(verdict["label"], "unknown")
        self.assertEqual(verdict["reason"], "fix_photo")
        # Records present but frame missing or non-positive.
        for bad in (None, (0, 1200), (1600, 0), (-1, 5)):
            verdict = classify_photo_geometry([rec], bad)
            self.assertEqual(verdict["label"], "unknown", bad)
            self.assertEqual(verdict["reason"], "fix_photo")
        # Non-positive record dims.
        flat = _rec((100, 100, 300, 400, 0, 1200))
        self.assertEqual(
            classify_photo_geometry([flat], (1600, 1200))["label"], "unknown"
        )

    def test_multi_match_is_unknown_needs_review(self):
        r1 = _rec((10, 10, 100, 100, 1600, 1200), object_id=1)
        r2 = _rec((200, 200, 300, 300, 1600, 1200), object_id=2)
        verdict = classify_photo_geometry([r1, r2], (1600, 1200))
        self.assertEqual(verdict["label"], "unknown")
        self.assertEqual(verdict["reason"], "needs_review")

    def test_crop_pads_box_basis_and_clamps(self):
        crop = suggest_crop((100, 100, 300, 400, 1600, 1200), (1600, 1200))
        self.assertEqual(crop, {"x1": 84, "y1": 76, "x2": 316, "y2": 424})

    def test_crop_clamps_at_frame_edge(self):
        crop = suggest_crop((0, 0, 100, 100, 1600, 1200), (1600, 1200))
        self.assertEqual(crop["x1"], 0)
        self.assertEqual(crop["y1"], 0)
        self.assertGreater(crop["x2"], 100)
        self.assertGreater(crop["y2"], 100)
        self.assertLessEqual(crop["x2"], 1599)
        self.assertLessEqual(crop["y2"], 1199)

    def test_no_crop_offered_for_non_detected(self):
        # Non-detected verdicts carry no crop: the verdict dict has no
        # crop key and multi/empty/invalid inputs never yield detected.
        empty = classify_photo_geometry([], None)
        self.assertEqual(empty["label"], "not_detected")
        self.assertNotIn("crop", empty)
        r1 = _rec((10, 10, 100, 100, 1600, 1200), object_id=1)
        r2 = _rec((200, 200, 300, 300, 1600, 1200), object_id=2)
        multi = classify_photo_geometry([r1, r2], (1600, 1200))
        self.assertNotEqual(multi["label"], "detected")
        self.assertNotIn("crop", multi)
        edge = classify_photo_geometry(
            [_rec((0, 10, 200, 400, 1600, 1200))], (1600, 1200)
        )
        self.assertNotEqual(edge["label"], "detected")
        self.assertNotIn("crop", edge)


if __name__ == "__main__":
    unittest.main()
