"""Instagram transport coverage: request shape, sequencing, errors.

Pure stdlib unittest with a patched HTTP seam. No network. The fixture
token is synthetic and revoked by construction.
"""

import io
import json
import unittest
from unittest.mock import patch

from launchcrew import instagram_publish as ig

TOKEN = "fixture-token-not-real"
USER = "123456789"
MEDIA = "https://example.invalid/shot.jpg"
CAPTION = "New drop, link in bio."


def _response(payload):
    stream = io.BytesIO(json.dumps(payload).encode())
    stream.__enter__ = lambda self: self  # type: ignore[attr-defined]
    stream.__exit__ = lambda self, *args: False  # type: ignore[attr-defined]
    return stream


class NormalizeTests(unittest.TestCase):
    def test_contract(self):
        self.assertEqual(ig.MODULE_VERSION, "instagram-publish/v1")
        self.assertEqual(ig.GRAPH_ORIGIN, "https://graph.facebook.com")

    def test_valid_values(self):
        self.assertEqual(ig.normalize_user_id(" 123 "), "123")
        self.assertEqual(ig.normalize_media_url(MEDIA), MEDIA)
        self.assertEqual(ig.normalize_caption(" hi "), "hi")
        self.assertEqual(ig.normalize_token(" abc "), "abc")

    def test_invalid_values_raise_without_echo(self):
        cases = [(ig.normalize_user_id, "abc"), (ig.normalize_user_id, ""),
                 (ig.normalize_media_url, "http://example.invalid/x.jpg"),
                 (ig.normalize_media_url, "not a url"),
                 (ig.normalize_caption, ""), (ig.normalize_caption, "x" * 2201),
                 (ig.normalize_token, ""), (ig.normalize_token, "  ")]
        for func, bad in cases:
            with self.subTest(func=func.__name__, bad=str(bad)[:20]):
                with self.assertRaises(ig.InstagramTransportError):
                    func(bad)

    def test_disabled_by_default(self):
        import os
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(ig.LIVE_FLAG, None)
            self.assertFalse(ig.instagram_live_enabled())
        with patch.dict(os.environ, {ig.LIVE_FLAG: "true"}):
            self.assertTrue(ig.instagram_live_enabled())


class RequestShapeTests(unittest.TestCase):
    def test_container_then_publish_sequence(self):
        calls = []

        def fake_opener(request, timeout=None):
            calls.append(request)
            if request.full_url.endswith("/media"):
                return _response({"id": "creation_1"})
            return _response({"id": "media_9"})

        with patch.object(ig, "urlopen", side_effect=fake_opener):
            result = ig.instagram_transport(USER, MEDIA, CAPTION, TOKEN)
        self.assertEqual(len(calls), 2)
        first = calls[0]
        self.assertEqual(first.get_method(), "POST")
        self.assertTrue(first.full_url.startswith(ig.GRAPH_ORIGIN + "/v21.0/123456789/media"))
        body = json.loads(first.data.decode())
        self.assertEqual(body["image_url"], MEDIA)
        self.assertEqual(body["caption"], CAPTION)
        self.assertEqual(body["access_token"], TOKEN)
        second = calls[1]
        self.assertTrue(second.full_url.endswith("/media_publish"))
        body = json.loads(second.data.decode())
        self.assertEqual(body["creation_id"], "creation_1")
        self.assertEqual(result, {"platform_post_id": "media_9",
                                  "live_url": None, "simulated": False})

    def test_token_never_leaks_into_errors(self):
        def bad_token_opener(request, timeout=None):
            return _response({"error": {"message": "Invalid OAuth access token",
                                        "type": "OAuthException", "code": 190}})

        with patch.object(ig, "urlopen", side_effect=bad_token_opener):
            with self.assertRaises(ig.InstagramTransportError) as raised:
                ig.instagram_transport(USER, MEDIA, CAPTION, TOKEN)
        self.assertIn("Invalid OAuth", str(raised.exception))
        self.assertNotIn(TOKEN, str(raised.exception))

    def test_network_failure_maps_cleanly(self):
        with patch.object(ig, "urlopen", side_effect=TimeoutError("slow")):
            with self.assertRaises(ig.InstagramTransportError) as raised:
                ig.instagram_transport(USER, MEDIA, CAPTION, TOKEN)
        self.assertNotIn(TOKEN, str(raised.exception))

    def test_garbage_response_refuses(self):
        with patch.object(ig, "urlopen", return_value=io.BytesIO(b"not json")):
            with self.assertRaises(ig.InstagramTransportError):
                ig.instagram_transport(USER, MEDIA, CAPTION, TOKEN)

    def test_missing_ids_refuse(self):
        with patch.object(ig, "urlopen", return_value=_response({"id": " "})):
            with self.assertRaises(ig.InstagramTransportError):
                ig.instagram_transport(USER, MEDIA, CAPTION, TOKEN)

    def test_validation_happens_before_http(self):
        with patch.object(ig, "urlopen",
                          side_effect=AssertionError("zero HTTP expected")):
            with self.assertRaises(ig.InstagramTransportError):
                ig.instagram_transport("not-numeric", MEDIA, CAPTION, TOKEN)
            with self.assertRaises(ig.InstagramTransportError):
                ig.instagram_transport(USER, "http://example.invalid/x.jpg",
                                       CAPTION, TOKEN)
            with self.assertRaises(ig.InstagramTransportError):
                ig.instagram_transport(USER, MEDIA, "x" * 2201, TOKEN)


class PrerequisitesTests(unittest.TestCase):
    def test_all_missing_listed(self):
        missing = ig.live_prerequisites("handle", "", None, "")
        self.assertEqual(len(missing), 4)

    def test_ready_when_complete(self):
        self.assertEqual(ig.live_prerequisites(USER, TOKEN, MEDIA, CAPTION), [])


if __name__ == "__main__":
    unittest.main()
