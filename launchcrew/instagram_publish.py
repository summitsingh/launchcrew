"""Instagram live transport: real Graph API single-image publish path.

Two-step flow against a fixed Graph API version: create a media
container from a public image URL plus caption, then publish the
container. Used only when every live prerequisite holds: the
LAUNCHCREW_INSTAGRAM_LIVE flag is true, the stored brand connection
carries a real owner token, and the execute call supplies a public
https image URL. Otherwise the caller keeps the simulated default
transport, which stays explicitly labeled.

The token travels only in request bodies and is never included in
raised reasons, returned values, or logs. Only single-image posts are
covered; reels and stories need different endpoints and stay out.
"""

from __future__ import annotations

import io
import json
import os
import re
import urllib.request
from typing import Any
from urllib.parse import urlparse

MODULE_VERSION = "instagram-publish/v1"

GRAPH_ORIGIN = "https://graph.facebook.com"
GRAPH_VERSION = "v21.0"

CAPTION_MAX_CHARS = 2200
TOKEN_MAX_CHARS = 4000
USER_ID_RE = re.compile(r"^[0-9]{1,64}$")

LIVE_FLAG = "LAUNCHCREW_INSTAGRAM_LIVE"

NO_LIVE_MESSAGE = (
    "instagram live prerequisites unmet: flag LAUNCHCREW_INSTAGRAM_LIVE "
    "must be true with a real brand token and a public https image URL"
)
CAPTION_MESSAGE = (
    "instagram caption must be a nonempty string of at most %d characters"
    % CAPTION_MAX_CHARS
)
MEDIA_MESSAGE = (
    "instagram needs a public https image URL of at most 2000 characters"
)
USER_MESSAGE = "instagram user id must be digits"
TOKEN_MESSAGE = "instagram token must be a nonempty string"
PROVIDER_MESSAGE = "instagram refused the publish call: %s"


class InstagramTransportError(Exception):
    """Raised when the Graph API refuses or the call cannot complete."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def urlopen(request, timeout=None):
    """Single indirection so tests can patch the HTTP seam."""
    from urllib.request import urlopen as _real_urlopen
    return _real_urlopen(request, timeout=timeout)


def instagram_live_enabled() -> bool:
    """Return True only when the owner explicitly enables live posting."""
    return os.environ.get(LIVE_FLAG, "").strip().lower() == "true"


def normalize_user_id(value: Any) -> str:
    """Return the numeric IG user id or raise InstagramTransportError."""
    if not isinstance(value, str) or not USER_ID_RE.match(value.strip()):
        raise InstagramTransportError(USER_MESSAGE)
    return value.strip()


def normalize_media_url(value: Any) -> str:
    """Return the public https image URL or raise InstagramTransportError."""
    if not isinstance(value, str):
        raise InstagramTransportError(MEDIA_MESSAGE)
    cleaned = value.strip()
    if not cleaned or len(cleaned) > 2000:
        raise InstagramTransportError(MEDIA_MESSAGE)
    try:
        parsed = urlparse(cleaned)
    except ValueError:
        raise InstagramTransportError(MEDIA_MESSAGE) from None
    if parsed.scheme != "https" or not parsed.hostname:
        raise InstagramTransportError(MEDIA_MESSAGE)
    return cleaned


def normalize_caption(value: Any) -> str:
    """Return the caption text or raise InstagramTransportError."""
    if not isinstance(value, str):
        raise InstagramTransportError(CAPTION_MESSAGE)
    cleaned = value.strip()
    if not cleaned or len(cleaned) > CAPTION_MAX_CHARS:
        raise InstagramTransportError(CAPTION_MESSAGE)
    return cleaned


def normalize_token(value: Any) -> str:
    """Return the token or raise InstagramTransportError, never echoing it."""
    if not isinstance(value, str) or not value.strip():
        raise InstagramTransportError(TOKEN_MESSAGE)
    cleaned = value.strip()
    if len(cleaned) > TOKEN_MAX_CHARS:
        raise InstagramTransportError(TOKEN_MESSAGE)
    return cleaned


def _post(path: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        GRAPH_ORIGIN + "/" + GRAPH_VERSION + path,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except Exception as error:
        raise InstagramTransportError(
            PROVIDER_MESSAGE % ("network or HTTP failure: %s" % type(error).__name__))
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise InstagramTransportError(PROVIDER_MESSAGE % "unreadable response")
    if not isinstance(data, dict):
        raise InstagramTransportError(PROVIDER_MESSAGE % "unreadable response")
    error = data.get("error")
    if isinstance(error, dict):
        raise InstagramTransportError(
            PROVIDER_MESSAGE % str(error.get("message") or "unknown provider error")[:300])
    return data


def create_container(ig_user_id: str, media_url: str, caption: str,
                     token: str, timeout: float = 30.0) -> str:
    """Create a media container; return its creation id."""
    user_id = normalize_user_id(ig_user_id)
    url = normalize_media_url(media_url)
    text = normalize_caption(caption)
    key = normalize_token(token)
    data = _post("/%s/media" % user_id,
                 {"image_url": url, "caption": text, "access_token": key},
                 timeout)
    creation_id = data.get("id")
    if not isinstance(creation_id, str) or not creation_id.strip():
        raise InstagramTransportError(PROVIDER_MESSAGE % "missing container id")
    return creation_id.strip()


def publish_container(ig_user_id: str, creation_id: str, token: str,
                      timeout: float = 30.0) -> str:
    """Publish a container; return the media id."""
    user_id = normalize_user_id(ig_user_id)
    if not isinstance(creation_id, str) or not creation_id.strip():
        raise InstagramTransportError("instagram creation id must be a nonempty string")
    key = normalize_token(token)
    data = _post("/%s/media_publish" % user_id,
                 {"creation_id": creation_id.strip(), "access_token": key},
                 timeout)
    media_id = data.get("id")
    if not isinstance(media_id, str) or not media_id.strip():
        raise InstagramTransportError(PROVIDER_MESSAGE % "missing media id")
    return media_id.strip()


def live_prerequisites(ig_user_id: Any, token: Any, media_url: Any,
                       caption: Any) -> list[str]:
    """Return the missing live requirements, empty when ready to call.

    Takes explicit values so the caller supplies the decrypted token
    and the connection's external id; the live flag is checked by the
    caller through instagram_live_enabled.
    """
    missing: list[str] = []
    try:
        normalize_user_id(ig_user_id)
    except InstagramTransportError:
        missing.append("numeric instagram user id is missing")
    try:
        normalize_token(token)
    except InstagramTransportError:
        missing.append("brand connection has no usable token")
    try:
        normalize_media_url(media_url)
    except InstagramTransportError:
        missing.append("public https image URL is missing or invalid")
    try:
        normalize_caption(caption)
    except InstagramTransportError:
        missing.append("caption is missing or over the limit")
    return missing


def instagram_transport(ig_user_id: str, media_url: str, caption: str,
                        token: str, timeout: float = 30.0) -> dict[str, Any]:
    """Publish one image post; return the real media id, never simulated."""
    creation_id = create_container(ig_user_id, media_url, caption, token, timeout)
    media_id = publish_container(ig_user_id, creation_id, token, timeout)
    return {"platform_post_id": media_id, "live_url": None, "simulated": False}
