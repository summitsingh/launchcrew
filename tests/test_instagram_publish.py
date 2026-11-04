"""Instagram transport coverage: request shape, sequencing, errors.

Pure stdlib unittest with a patched HTTP seam. No network. The fixture
token is synthetic and revoked by construction.
"""

import io
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

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
    def test_container_then_publish_then_permalink_sequence(self):
        calls = []

        def fake_opener(request, timeout=None):
            calls.append(request)
            if request.full_url.endswith("/media"):
                return _response({"id": "creation_1"})
            if "fields=status_code" in request.full_url:
                return _response({"status_code": "FINISHED"})
            if "fields=permalink" in request.full_url:
                return _response({"id": "media_9",
                                  "permalink": "https://www.instagram.com/p/DbSeq9/"})
            return _response({"id": "media_9"})

        with patch.object(ig, "urlopen", side_effect=fake_opener):
            result = ig.instagram_transport(USER, MEDIA, CAPTION, TOKEN)
        self.assertEqual(len(calls), 4)
        first = calls[0]
        self.assertEqual(first.get_method(), "POST")
        self.assertTrue(first.full_url.startswith(ig.GRAPH_ORIGIN + "/v21.0/123456789/media"))
        body = json.loads(first.data.decode())
        self.assertEqual(body["image_url"], MEDIA)
        self.assertEqual(body["caption"], CAPTION)
        self.assertEqual(body["access_token"], TOKEN)
        second = calls[1]
        self.assertEqual(second.get_method(), "GET")
        self.assertTrue(second.full_url.endswith("/creation_1?fields=status_code"))
        self.assertEqual(second.get_header("Authorization"), "Bearer " + TOKEN)
        self.assertNotIn(TOKEN, second.full_url)
        third = calls[2]
        self.assertTrue(third.full_url.endswith("/media_publish"))
        body = json.loads(third.data.decode())
        self.assertEqual(body["creation_id"], "creation_1")
        fourth = calls[3]
        self.assertEqual(fourth.get_method(), "GET")
        self.assertIn("fields=permalink", fourth.full_url)
        self.assertEqual(fourth.get_header("Authorization"), "Bearer " + TOKEN)
        self.assertNotIn(TOKEN, fourth.full_url)
        self.assertEqual(result, {"platform_post_id": "media_9",
                                  "live_url": "https://www.instagram.com/p/DbSeq9/",
                                  "simulated": False})

    def test_waits_for_container_before_publish(self):
        responses = [{"id": "creation_1"}, {"status_code": "IN_PROGRESS"},
                     {"status_code": "FINISHED"}, {"id": "media_9"},
                     {"permalink": "https://www.instagram.com/p/DbSeq9/"}]
        with patch.object(ig, "urlopen", side_effect=[_response(p) for p in responses]) as opener:
            with patch.object(ig, "_sleep") as sleep:
                result = ig.instagram_transport(USER, MEDIA, CAPTION, TOKEN, timeout=7.5)
        self.assertEqual(result["platform_post_id"], "media_9")
        sleep.assert_called_once_with(3)
        self.assertEqual(
            [call.args[0].full_url for call in opener.call_args_list],
            [ig.GRAPH_ORIGIN + "/" + ig.GRAPH_VERSION + path for path in (
                "/123456789/media", "/creation_1?fields=status_code",
                "/creation_1?fields=status_code", "/123456789/media_publish",
                "/media_9?fields=permalink")])
        self.assertTrue(all(call.kwargs["timeout"] == 7.5
                            for call in opener.call_args_list))

    def test_fatal_container_status_prevents_publish(self):
        for status in ("ERROR", "EXPIRED"):
            with self.subTest(status=status):
                responses = [_response({"id": "creation_1"}),
                             _response({"status_code": status})]
                with patch.object(ig, "urlopen", side_effect=responses) as opener:
                    with patch.object(ig, "_sleep") as sleep:
                        with self.assertRaisesRegex(ig.InstagramTransportError, status):
                            ig.instagram_transport(USER, MEDIA, CAPTION, TOKEN)
                self.assertEqual(opener.call_count, 2)
                self.assertFalse(any(call.args[0].full_url.endswith("/media_publish")
                                     for call in opener.call_args_list))
                sleep.assert_not_called()

    def test_container_readiness_budget_prevents_publish(self):
        responses = [_response({"id": "creation_1"})] + [
            _response({"status_code": "IN_PROGRESS"}) for _ in range(20)]
        with patch.object(ig, "urlopen", side_effect=responses) as opener:
            with patch.object(ig, "_sleep") as sleep:
                with self.assertRaisesRegex(ig.InstagramTransportError,
                                            "media container was not ready in time"):
                    ig.instagram_transport(USER, MEDIA, CAPTION, TOKEN)
        self.assertEqual(opener.call_count, 21)
        self.assertTrue(all(call.args[0].full_url.endswith("/creation_1?fields=status_code")
                            for call in opener.call_args_list[1:]))
        self.assertEqual(sleep.call_count, 19)
        self.assertTrue(all(call.args == (3,) for call in sleep.call_args_list))

    def test_unusable_status_keeps_polling(self):
        for payload in ({}, {"status_code": None}, {"status_code": ""},
                        {"status_code": []}, {"status_code": "UNKNOWN"}):
            with self.subTest(payload=payload):
                responses = [{"id": "creation_1"}, payload,
                             {"status_code": "FINISHED"}, {"id": "media_9"}, {}]
                with patch.object(ig, "urlopen", side_effect=[_response(p) for p in responses]):
                    with patch.object(ig, "_sleep") as sleep:
                        result = ig.instagram_transport(USER, MEDIA, CAPTION, TOKEN)
                self.assertEqual(result["platform_post_id"], "media_9")
                sleep.assert_called_once_with(3)

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

    def test_http_error_surfaces_provider_message(self):
        message = "The app is not authorized to publish for this account"
        error = HTTPError(ig.GRAPH_ORIGIN, 403, "Forbidden", {},
                          io.BytesIO(json.dumps({"error": {"message": message}}).encode()))
        with patch.object(ig, "urlopen", side_effect=error):
            with self.assertRaises(ig.InstagramTransportError) as raised:
                ig.instagram_transport(USER, MEDIA, CAPTION, TOKEN)
        self.assertEqual(raised.exception.reason, ig.PROVIDER_MESSAGE % message)
        self.assertNotIn(TOKEN, raised.exception.reason)

    def test_http_error_truncates_provider_message(self):
        message = "Provider refusal " + "x" * 400
        error = HTTPError(ig.GRAPH_ORIGIN, 400, "Bad Request", {},
                          io.BytesIO(json.dumps({"error": {"message": message}}).encode()))
        with patch.object(ig, "urlopen", side_effect=error):
            with self.assertRaises(ig.InstagramTransportError) as raised:
                ig.instagram_transport(USER, MEDIA, CAPTION, TOKEN)
        self.assertEqual(raised.exception.reason, ig.PROVIDER_MESSAGE % message[:300])

    def test_http_error_without_provider_message_includes_status(self):
        bodies = [b"not json", b"\xff", b"[]", b"{}", b'{"error": {}}',
                  b'{"error": {"message": ""}}',
                  b'{"error": {"message": 123}}', TOKEN.encode()]
        for body in bodies:
            with self.subTest(body_type=type(body).__name__):
                error = HTTPError(ig.GRAPH_ORIGIN, 403, "Forbidden", {}, io.BytesIO(body))
                with patch.object(ig, "urlopen", side_effect=error):
                    with self.assertRaises(ig.InstagramTransportError) as raised:
                        ig.instagram_transport(USER, MEDIA, CAPTION, TOKEN)
                self.assertEqual(raised.exception.reason, ig.PROVIDER_MESSAGE % "HTTP 403")
                self.assertNotIn(TOKEN, raised.exception.reason)

    def test_url_error_keeps_network_failure_mapping(self):
        with patch.object(ig, "urlopen", side_effect=URLError("unreachable")):
            with self.assertRaises(ig.InstagramTransportError) as raised:
                ig.instagram_transport(USER, MEDIA, CAPTION, TOKEN)
        self.assertEqual(raised.exception.reason,
                         ig.PROVIDER_MESSAGE % "network or HTTP failure: URLError")

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


class LiveFlagTemplateTests(unittest.TestCase):
    """The live flag must survive stack rollouts via the template.

    LAUNCHCREW_INSTAGRAM_LIVE lived only in manually registered task
    definition revisions, so every CloudFormation rollout reconciled it
    away and live publishing silently reverted to simulated. It belongs
    in the ApiTaskDefinition container environment next to the other
    plain (non-secret) launch flags.
    """

    def test_live_flag_in_api_environment(self):
        from pathlib import Path
        text = (Path(__file__).resolve().parents[1]
                / "deploy" / "aws" / "fargate.yaml").read_text(encoding="utf-8")
        api_start = text.index("ApiTaskDefinition:")
        api_block = text[api_start:text.index("WebTaskDefinition:")]
        container_start = api_block.index("- Name: api")
        container_block = api_block[container_start:]
        env_start = container_block.index("Environment:")
        secrets_start = container_block.index("Secrets:")
        env_block = container_block[env_start:secrets_start]
        self.assertIn(
            "{ Name: LAUNCHCREW_INSTAGRAM_LIVE, Value: 'true' }",
            env_block,
        )


class PrerequisitesTests(unittest.TestCase):
    def test_all_missing_listed(self):
        missing = ig.live_prerequisites("handle", "", None, "")
        self.assertEqual(len(missing), 4)

    def test_ready_when_complete(self):
        self.assertEqual(ig.live_prerequisites(USER, TOKEN, MEDIA, CAPTION), [])


if __name__ == "__main__":
    unittest.main()
