"""Media creative pack coverage: pure validation and parsing only.

No DB, no network, no provider. Stdlib unittest with synthetic
fixtures only.
"""

import unittest

from launchcrew import media_creative as mc


def _frame(caption="Soft cotton tee", shot="Flat lay on oak table"):
    return caption + mc.SEPARATOR + shot


def _scene(hook="Hook line", shot="Owner pour over", voice="Voice line"):
    return hook + mc.SEPARATOR + shot + mc.SEPARATOR + voice


class NormalizeTests(unittest.TestCase):
    def test_version_and_formats(self):
        self.assertEqual(mc.MODULE_VERSION, "media-creative/v1")
        self.assertEqual(mc.FORMATS, ("carousel", "short_video"))

    def test_format_ok(self):
        self.assertEqual(mc.normalize_format("carousel"), "carousel")
        self.assertEqual(mc.normalize_format("  short_video  "), "short_video")

    def test_format_bad(self):
        for bad in ("video", "", None, 5, ["carousel"]):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    mc.normalize_format(bad)

    def test_facts_ok(self):
        self.assertEqual(mc.normalize_facts("  facts here  "), "facts here")

    def test_facts_bad(self):
        for bad in ("", "   ", None, 42, "x" * (mc.FACTS_MAX_CHARS + 1)):
            with self.subTest(bad=repr(bad)[:20]):
                with self.assertRaises(ValueError):
                    mc.normalize_facts(bad)


class PromptTests(unittest.TestCase):
    def test_schema_hints(self):
        self.assertEqual(set(mc.schema_hint_for("carousel")), {"frames"})
        self.assertEqual(set(mc.schema_hint_for("short_video")), {"scenes"})

    def test_prompts_deterministic_and_bound(self):
        first = (mc.system_prompt_for("carousel"),
                 mc.user_prompt_for("carousel", "Cotton tee, $49."))
        second = (mc.system_prompt_for("carousel"),
                  mc.user_prompt_for("carousel", "Cotton tee, $49."))
        self.assertEqual(first, second)
        self.assertIn("Cotton tee", second[1])
        self.assertIn("carousel", second[1])


class ParseCarouselTests(unittest.TestCase):
    def test_valid_pack(self):
        raw = {"frames": [_frame("Caption %d" % i) for i in range(5)]}
        pack = mc.parse_pack(raw, "carousel")
        self.assertEqual(pack["module_version"], "media-creative/v1")
        self.assertEqual(pack["provenance"], "model_draft_unverified")
        self.assertEqual(len(pack["frames"]), 5)
        self.assertTrue(all(item["source"] == "model_draft"
                            for item in pack["frames"]))
        self.assertEqual(len(pack["captions"]), 5)
        self.assertEqual(len(pack["shot_prompts"]), 5)
        self.assertIn("Caption 0", pack["voiceover_script"])

    def test_count_bounds(self):
        with self.assertRaises(ValueError):
            mc.parse_pack({"frames": [_frame() for _ in range(4)]}, "carousel")
        with self.assertRaises(ValueError):
            mc.parse_pack({"frames": [_frame() for _ in range(11)]}, "carousel")
        pack = mc.parse_pack({"frames": [_frame() for _ in range(10)]},
                             "carousel")
        self.assertEqual(len(pack["frames"]), 10)

    def test_shape_refusals(self):
        with self.assertRaises(ValueError):
            mc.parse_pack({"frames": ["only caption, no separator"]}, "carousel")
        with self.assertRaises(ValueError):
            mc.parse_pack({"frames": [_frame() + mc.SEPARATOR + "extra"]},
                          "carousel")
        with self.assertRaises(ValueError):
            mc.parse_pack({"frames": [_frame("", "shot")]}, "carousel")
        with self.assertRaises(ValueError):
            mc.parse_pack({"frames": [_frame("c" * 141)]}, "carousel")
        with self.assertRaises(ValueError):
            mc.parse_pack({"frames": [_frame("ok", "s" * 201)]}, "carousel")
        with self.assertRaises(ValueError):
            mc.parse_pack({"frames": [_frame() for _ in range(5)],
                           "scenes": []}, "carousel")
        with self.assertRaises(ValueError):
            mc.parse_pack({"frames": "not a list"}, "carousel")
        with self.assertRaises(ValueError):
            mc.parse_pack(["frames"], "carousel")


class ParseShortVideoTests(unittest.TestCase):
    def test_valid_pack(self):
        raw = {"scenes": [_scene("Hook %d" % i, "Shot %d" % i, "Line %d" % i)
                          for i in range(3)]}
        pack = mc.parse_pack(raw, "short_video")
        self.assertEqual(len(pack["scenes"]), 3)
        self.assertEqual(pack["captions"], ["Hook 0", "Hook 1", "Hook 2"])
        self.assertEqual(pack["shot_prompts"],
                         ["Shot 0", "Shot 1", "Shot 2"])
        self.assertIn("Line 1", pack["voiceover_script"])

    def test_exact_count(self):
        with self.assertRaises(ValueError):
            mc.parse_pack({"scenes": [_scene(), _scene()]}, "short_video")
        with self.assertRaises(ValueError):
            mc.parse_pack({"scenes": [_scene() for _ in range(4)]},
                          "short_video")

    def test_part_refusals(self):
        with self.assertRaises(ValueError):
            mc.parse_pack({"scenes": [_scene("h", "s", "")]}, "short_video")
        with self.assertRaises(ValueError):
            mc.parse_pack({"scenes": [_scene("h" * 141)]}, "short_video")
        with self.assertRaises(ValueError):
            mc.parse_pack({"scenes": [42, _scene(), _scene()]}, "short_video")


class SummaryTests(unittest.TestCase):
    def test_helpers_on_validated_pack(self):
        pack = mc.parse_pack(
            {"scenes": [_scene("H%d" % i, "S%d" % i, "V%d" % i)
                        for i in range(3)]},
            "short_video")
        self.assertEqual(mc.captions_for(pack), ["H0", "H1", "H2"])
        self.assertEqual(mc.shot_prompts_for(pack), ["S0", "S1", "S2"])
        self.assertEqual(mc.voiceover_script_for(pack), "V0\nV1\nV2")


if __name__ == "__main__":
    unittest.main()
