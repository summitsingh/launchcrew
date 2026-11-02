"""Image provider adapters: OpenAI, xAI Grok, Google Gemini Imagen.

One injectable HTTP seam serves all three providers; each adapter
builds its documented request shape and parses its documented
response into base64 image bytes. Keys travel in request headers or
query strings only and are never included in raised reasons, returned
values, or logs. Every failure maps to ImageProviderError naming the
provider and the provider message.

Documented shapes:
* OpenAI: POST https://api.openai.com/v1/images/generations with
  Bearer key and {model gpt-image-1, prompt, size, n}; the response
  carries data[].b64_json always, never a URL.
* xAI: POST https://api.x.ai/v1/images/generations with Bearer key
  and {model grok-2-image, prompt, n, response_format b64_json};
  the response carries data[].b64_json when requested.
* Gemini: POST https://generativelanguage.googleapis.com/v1beta
  /models/{model}:predict with the key as ?key= and {instances:
  [{prompt}], parameters: {sampleCount, aspectRatio,
  personGeneration allow_adult}}; the response carries
  predictions[].bytesBase64Encoded.
"""

from __future__ import annotations

import base64
import binascii
import json
import urllib.request
from typing import Any

MODULE_VERSION = "image-adapters/v1"

OPENAI_ORIGIN = "https://api.openai.com"
OPENAI_MODEL = "gpt-image-1"
OPENAI_SIZES = {"4:5": "1024x1536", "1:1": "1024x1024",
                "9:16": "1024x1536", "16:9": "1536x1024"}

XAI_ORIGIN = "https://api.x.ai"
XAI_MODEL = "grok-2-image"

GEMINI_ORIGIN = "https://generativelanguage.googleapis.com"
GEMINI_MODEL = "imagen-4.0-generate-001"
GEMINI_ASPECTS = {"4:5": "3:4", "1:1": "1:1",
                  "9:16": "9:16", "16:9": "16:9"}

COUNT_MIN = 1
COUNT_MAX = 2

PROVIDER_MODELS = {"openai": OPENAI_MODEL, "xai": XAI_MODEL,
                   "gemini": GEMINI_MODEL}

KEY_NAMES = {"openai": "OPENAI_API_KEY", "xai": "XAI_API_KEY",
             "gemini": "GEMINI_API_KEY"}

PROVIDER_MESSAGE = "%s image generation failed: %s"


class ImageProviderError(Exception):
    """Raised when a provider refuses or the call cannot complete."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def urlopen(request, timeout=None):
    """Single indirection so tests can patch the HTTP seam."""
    from urllib.request import urlopen as _real_urlopen
    return _real_urlopen(request, timeout=timeout)


def _fail(provider: str, detail: str) -> ImageProviderError:
    return ImageProviderError(PROVIDER_MESSAGE % (provider, detail))


def _post(url: str, headers: dict[str, str], payload: dict[str, Any],
          provider: str, timeout: float = 120.0) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers=headers,
                                     method="POST")
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except Exception as error:
        raise _fail(provider, "network or HTTP failure: %s"
                    % type(error).__name__) from None
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise _fail(provider, "unreadable response") from None
    if not isinstance(data, dict):
        raise _fail(provider, "unreadable response") from None
    error = data.get("error")
    if isinstance(error, dict):
        raise _fail(provider, str(error.get("message")
                                  or "unknown provider error")[:300])
    if isinstance(error, str) and error.strip():
        raise _fail(provider, error.strip()[:300])
    return data


def _clean_b64(value: Any, provider: str, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _fail(provider, "response missing image bytes at %s" % where)
    cleaned = "".join(value.split())
    try:
        decoded = base64.b64decode(cleaned, validate=False)
    except (binascii.Error, ValueError):
        raise _fail(provider, "response image bytes are not valid base64") from None
    if not decoded:
        raise _fail(provider, "response image bytes are empty") from None
    return cleaned


def openai_request(prompt: str, size: str, count: int,
                   key: str) -> tuple[str, dict[str, str], dict[str, Any]]:
    """Build the OpenAI images request; pure, no network."""
    validate_key(key, "openai")
    if size not in OPENAI_SIZES.values():
        raise _fail("openai", "unsupported size %s" % size)
    validate_count(count)
    headers = {"Content-Type": "application/json",
               "Authorization": "Bearer " + key}
    payload = {"model": OPENAI_MODEL, "prompt": prompt, "size": size,
               "n": count}
    return OPENAI_ORIGIN + "/v1/images/generations", headers, payload


def openai_images(raw: Any) -> list[str]:
    """Parse OpenAI b64 images; refuse URL-only responses."""
    if not isinstance(raw, dict) or not isinstance(raw.get("data"), list):
        raise _fail("openai", "unreadable response")
    images = []
    for entry in raw["data"]:
        if not isinstance(entry, dict) or "b64_json" not in entry:
            raise _fail("openai", "response has no inline image bytes")
        images.append(_clean_b64(entry["b64_json"], "openai", "data[].b64_json"))
    if not images:
        raise _fail("openai", "response contains no images")
    return images


def xai_request(prompt: str, count: int, key: str) -> tuple[str, dict[str, str], dict[str, Any]]:
    """Build the xAI images request; pure, no network."""
    validate_key(key, "xai")
    validate_count(count)
    headers = {"Content-Type": "application/json",
               "Authorization": "Bearer " + key}
    payload = {"model": XAI_MODEL, "prompt": prompt, "n": count,
               "response_format": "b64_json"}
    return XAI_ORIGIN + "/v1/images/generations", headers, payload


def xai_images(raw: Any) -> list[str]:
    """Parse xAI b64 images; refuse URL-only responses."""
    if not isinstance(raw, dict) or not isinstance(raw.get("data"), list):
        raise _fail("xai", "unreadable response")
    images = []
    for entry in raw["data"]:
        if not isinstance(entry, dict) or "b64_json" not in entry:
            raise _fail("xai", "response has no inline image bytes")
        images.append(_clean_b64(entry["b64_json"], "xai", "data[].b64_json"))
    if not images:
        raise _fail("xai", "response contains no images")
    return images


def gemini_request(prompt: str, aspect: str, count: int,
                   key: str) -> tuple[str, dict[str, str], dict[str, Any]]:
    """Build the Gemini Imagen predict request; pure, no network."""
    validate_key(key, "gemini")
    if aspect not in GEMINI_ASPECTS:
        raise _fail("gemini", "unsupported aspect %s" % aspect)
    validate_count(count)
    headers = {"Content-Type": "application/json",
               "x-goog-api-key": key}
    payload = {"instances": [{"prompt": prompt}],
               "parameters": {"sampleCount": count,
                              "aspectRatio": GEMINI_ASPECTS[aspect],
                              "personGeneration": "allow_adult"}}
    url = ("%s/v1beta/models/%s:predict?key=%s"
           % (GEMINI_ORIGIN, GEMINI_MODEL, key))
    return url, headers, payload


def gemini_images(raw: Any) -> list[str]:
    """Parse Gemini prediction bytes."""
    if not isinstance(raw, dict) or not isinstance(raw.get("predictions"), list):
        raise _fail("gemini", "unreadable response")
    images = []
    for entry in raw["predictions"]:
        if not isinstance(entry, dict) or "bytesBase64Encoded" not in entry:
            raise _fail("gemini", "response has no inline image bytes")
        images.append(_clean_b64(entry["bytesBase64Encoded"], "gemini",
                                 "predictions[].bytesBase64Encoded"))
    if not images:
        raise _fail("gemini", "response contains no images")
    return images


def validate_key(key: Any, provider: str) -> str:
    """Return the key or raise without echoing any value."""
    if not isinstance(key, str) or not key.strip():
        raise _fail(provider, "provider key is not configured")
    if len(key.strip()) > 4000:
        raise _fail(provider, "provider key is not configured")
    return key.strip()


def validate_count(count: Any) -> int:
    """Return the image count within the cost bound or raise."""
    if isinstance(count, bool) or not isinstance(count, int):
        raise ImageProviderError("image count must be an integer from 1 to 2")
    if not COUNT_MIN <= count <= COUNT_MAX:
        raise ImageProviderError("image count must be an integer from 1 to 2")
    return count


def generate(provider: str, prompt: str, aspect: str, count: int,
             key: str, timeout: float = 120.0) -> list[str]:
    """Generate images with one provider; return base64 PNG bytes list."""
    if provider == "openai":
        size = OPENAI_SIZES.get(aspect)
        if size is None:
            raise _fail("openai", "unsupported aspect %s" % aspect)
        url, headers, payload = openai_request(prompt, size, count, key)
        return openai_images(_post(url, headers, payload, "openai", timeout))
    if provider == "xai":
        url, headers, payload = xai_request(prompt, count, key)
        return xai_images(_post(url, headers, payload, "xai", timeout))
    if provider == "gemini":
        url, headers, payload = gemini_request(prompt, aspect, count, key)
        return gemini_images(_post(url, headers, payload, "gemini", timeout))
    raise ImageProviderError("image provider must be one of openai, xai, gemini")
