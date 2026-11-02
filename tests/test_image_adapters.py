"""Image adapter coverage: request shapes, parsing, error mapping.

Pure stdlib unittest with a patched HTTP seam. Fixture keys are
synthetic and the seam asserts zero live network.
"""

import base64
import io
import json
import unittest
from unittest.mock import patch

from launchcrew import image_adapters as ad
from launchcrew import image_generation as img

TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8"
    "/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=="
)


def _response(payload):
    return io.BytesIO(json.dumps(payload).encode())


class RequestShapeTests(unittest.TestCase):
    def test_openai_shape(self):
        url, headers, payload = ad.openai_request("A tee", "1024x1024", 1, "sk-fixture")
        self.assertEqual(url, "https://api.openai.com/v1/images/generations")
        self.assertEqual(headers["Authorization"], "Bearer sk-fixture")
        self.assertEqual(payload, {"model": "gpt-image-1", "prompt": "A tee",
                                   "size": "1024x1024", "n": 1})

    def test_xai_shape(self):
        url, headers, payload = ad.xai_request("A tee", 2, "xai-fixture")
        self.assertEqual(url, "https://api.x.ai/v1/images/generations")
        self.assertEqual(headers["Authorization"], "Bearer xai-fixture")
        self.assertEqual(payload, {"model": "grok-2-image", "prompt": "A tee",
                                   "n": 2, "response_format": "b64_json"})

    def test_gemini_shape(self):
        url, headers, payload = ad.gemini_request("A tee", "1:1", 1, "gem-fixture")
        self.assertTrue(url.startswith(
            "https://generativelanguage.googleapis.com/v1beta/models/"))
        self.assertIn(":predict?key=", url)
        self.assertEqual(headers["x-goog-api-key"], "gem-fixture")
        self.assertEqual(payload["instances"], [{"prompt": "A tee"}])
        self.assertEqual(payload["parameters"]["aspectRatio"], "1:1")
        self.assertEqual(payload["parameters"]["sampleCount"], 1)
        self.assertEqual(payload["parameters"]["personGeneration"], "allow_adult")

    def test_rejects_before_http(self):
        for build in (lambda: ad.openai_request("A", "9:99", 1, "k"),
                      lambda: ad.xai_request("A", 3, "k"),
                      lambda: ad.gemini_request("A", "wide", 1, "k"),
                      lambda: ad.openai_request("A", "1024x1024", 1, " ")):
            with self.subTest(build=str(build)):
                with self.assertRaises(ad.ImageProviderError):
                    with patch.object(ad, "urlopen",
                                      side_effect=AssertionError("zero HTTP expected")):
                        build()


class ParseTests(unittest.TestCase):
    def test_openai_b64(self):
        self.assertEqual(ad.openai_images({"data": [{"b64_json": TINY_PNG_B64}]}),
                         [TINY_PNG_B64])

    def test_openai_url_only_refuses(self):
        with self.assertRaises(ad.ImageProviderError):
            ad.openai_images({"data": [{"url": "https://example.invalid/x.png"}]})

    def test_xai_b64(self):
        self.assertEqual(ad.xai_images({"data": [{"b64_json": TINY_PNG_B64}]}),
                         [TINY_PNG_B64])

    def test_gemini_bytes(self):
        raw = {"predictions": [{"bytesBase64Encoded": TINY_PNG_B64}]}
        self.assertEqual(ad.gemini_images(raw), [TINY_PNG_B64])

    def test_garbage_refuses(self):
        for parse in (lambda: ad.openai_images({"data": []}),
                      lambda: ad.xai_images({"nope": 1}),
                      lambda: ad.gemini_images({"predictions": [{}]}),
                      lambda: ad.openai_images({"data": [{"b64_json": "!!!"}]})):
            with self.subTest(parse=str(parse)):
                with self.assertRaises(ad.ImageProviderError):
                    parse()


class GenerateTests(unittest.TestCase):
    def test_openai_end_to_end_shape(self):
        calls = []

        def fake_opener(request, timeout=None):
            calls.append(request)
            return _response({"data": [{"b64_json": TINY_PNG_B64}]})

        with patch.object(ad, "urlopen", side_effect=fake_opener):
            images = ad.generate("openai", "A tee", "1:1", 1, "sk-fixture")
        self.assertEqual(images, [TINY_PNG_B64])
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].get_method(), "POST")

    def test_unknown_provider_refuses(self):
        with self.assertRaises(ad.ImageProviderError):
            ad.generate("midjourney", "A tee", "1:1", 1, "k")

    def test_provider_error_never_leaks_key(self):
        def bad_key_opener(request, timeout=None):
            return _response({"error": {"message": "Incorrect API key provided",
                                        "type": "invalid_request_error"}})

        with patch.object(ad, "urlopen", side_effect=bad_key_opener):
            with self.assertRaises(ad.ImageProviderError) as raised:
                ad.generate("openai", "A tee", "1:1", 1, "sk-live-looking")
        self.assertIn("Incorrect API key", str(raised.exception))
        self.assertNotIn("sk-live-looking", str(raised.exception))

    def test_count_bound(self):
        with self.assertRaises(ad.ImageProviderError):
            ad.validate_count(0)
        with self.assertRaises(ad.ImageProviderError):
            ad.validate_count(3)
        self.assertEqual(ad.validate_count(2), 2)


class PromptPackTests(unittest.TestCase):
    def test_pack_binds_character(self):
        prompt = img.build_shoot_prompt("Athletic woman, short hair",
                                        "Rooftop at golden hour",
                                        "Cotton tee, $49")
        self.assertIn("Athletic woman", prompt)
        self.assertLessEqual(len(prompt), img.PROMPT_MAX_CHARS)


if __name__ == "__main__":
    unittest.main()
