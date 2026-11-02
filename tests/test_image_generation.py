"""Image generation domain coverage: providers, characters, prompts.

Pure stdlib unittest with synthetic fixtures only. No DB, no network.
"""

import unittest

from launchcrew import image_generation as img


class ProviderTests(unittest.TestCase):
    def test_providers(self):
        self.assertEqual(img.PROVIDERS, ("openai", "xai", "gemini"))
        self.assertEqual(img.normalize_provider("gemini"), "gemini")
        for bad in ("midjourney", "", None, 5, ["openai"]):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    img.normalize_provider(bad)


class CharacterTests(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(img.normalize_character_name("  Maya  "), "Maya")
        self.assertEqual(img.normalize_appearance("Tall  runner "), "Tall runner")

    def test_invalid(self):
        for bad in ("", "   ", None, 7, "x" * 121):
            with self.subTest(bad=repr(bad)[:20]):
                with self.assertRaises(ValueError):
                    img.normalize_character_name(bad)
        for bad in ("", "   ", None, 7, "x" * 2001):
            with self.subTest(bad=repr(bad)[:20]):
                with self.assertRaises(ValueError):
                    img.normalize_appearance(bad)
        with self.assertRaises(ValueError):
            img.normalize_scene("")


class PromptTests(unittest.TestCase):
    def test_binds_all_parts(self):
        prompt = img.build_shoot_prompt("Athletic woman, short hair",
                                        "Rooftop at golden hour",
                                        "Cotton tee, $49")
        self.assertIn("Athletic woman", prompt)
        self.assertIn("Rooftop", prompt)
        self.assertIn("Cotton tee", prompt)
        self.assertIn("no text overlays", prompt)
        self.assertLessEqual(len(prompt), img.PROMPT_MAX_CHARS)

    def test_empty_context_ok(self):
        prompt = img.build_shoot_prompt("Athletic woman", "Studio backdrop", "")
        self.assertIn("Studio backdrop", prompt)
        self.assertNotIn("Product context", prompt)


if __name__ == "__main__":
    unittest.main()
