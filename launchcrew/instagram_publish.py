"""Instagram live transport: real Graph API single-image publish path.

Flow against a fixed Graph API version: create a media
container from a public image URL plus caption, wait until ready, publish the
container, then read back the public permalink for verification.
Used only when every live prerequisite holds: the
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
from urllib.error import HTTPError
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


FAILED_CALLS = ('container_create', 'status_poll', 'media_publish',
                'media_permalink', 'caption_readback')

_SAFE_DETAIL_LIMIT = 300


_SAFE_TYPE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")
_LONG_DIGITS_RE = re.compile(r"\b\d{8,}\b")
_URL_VALUE_RE = re.compile(r"https?://\S+")
_BEARER_VALUE_RE = re.compile(r"Bearer\s+\S+", re.IGNORECASE)
_ACCESS_TOKEN_VALUE_RE = re.compile(r"access_token['\"]?\s*[:=]\s*['\"]?([^\s'\",}]+)", re.IGNORECASE)


def _request_secrets(request: urllib.request.Request) -> list[str]:
    """Collect exact secret values from one request without printing them."""
    secrets: list[str] = []
    try:
        header = request.get_header("Authorization") or ""
        if isinstance(header, str) and header.lower().startswith("bearer "):
            token = header[7:].strip()
            if token:
                secrets.append(token)
    except Exception:
        pass
    try:
        raw = request.data
        if isinstance(raw, (bytes, bytearray)) and raw:
            body = bytes(raw).decode("utf-8", "ignore")
            for key in ("access_token", "token"):
                marker = '"%s"' % key
                idx = body.find(marker)
                while idx >= 0:
                    colon = body.find(":", idx + len(marker))
                    if colon < 0:
                        break
                    start = colon + 1
                    while start < len(body) and body[start] in ' "':
                        start += 1
                    end = start
                    while end < len(body) and body[end] not in '" ,}':
                        end += 1
                    candidate = body[start:end].strip()
                    if candidate:
                        secrets.append(candidate)
                    idx = body.find(marker, end)
    except Exception:
        pass
    return [s for s in secrets if isinstance(s, str) and s]


def _scrub_provider_message(value: str, secrets: list[str] | None = None) -> str:
    """Collapse whitespace and redact secrets, URLs, and long account ids."""
    cleaned = ' '.join(value.split())
    if not cleaned:
        return cleaned
    for secret in secrets or []:
        if secret and secret in cleaned:
            cleaned = cleaned.replace(secret, "[redacted]")
    cleaned = _BEARER_VALUE_RE.sub("Bearer [redacted]", cleaned)
    cleaned = _ACCESS_TOKEN_VALUE_RE.sub("access_token=[redacted]", cleaned)
    cleaned = _URL_VALUE_RE.sub("[url]", cleaned)
    cleaned = _LONG_DIGITS_RE.sub("[id]", cleaned)
    return cleaned


def _safe_text(value: Any, limit: int = _SAFE_DETAIL_LIMIT) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = _scrub_provider_message(value)
    if not cleaned:
        return None
    return cleaned[:limit]


def _safe_type(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned or len(cleaned) > 64:
        return None
    if not _SAFE_TYPE_RE.match(cleaned):
        return None
    return cleaned


def _scrub_url_query(url: str | None) -> str | None:
    """Return a URL with every query value removed, never the raw URL."""
    if not isinstance(url, str) or not url:
        return None
    try:
        from urllib.parse import urlsplit, urlunsplit
        parts = urlsplit(url.strip())
        if parts.query:
            return urlunsplit((parts.scheme, parts.netloc, parts.path, '', parts.fragment))
        return url.strip()[:200]
    except ValueError:
        return None


def safe_transport_details(error: BaseException) -> dict[str, Any]:
    """Bounded safe detail dict for a transport error, never with secrets."""
    reason = getattr(error, 'reason', None)
    detail: dict[str, Any] = {
        'message': (_safe_text(reason) if isinstance(reason, str) else 'instagram publish failed') or 'instagram publish failed',
        'failed_call': getattr(error, 'failed_call', None) if getattr(error, 'failed_call', None) in FAILED_CALLS else None,
        'status': getattr(error, 'status', None) if isinstance(getattr(error, 'status', None), int) else None,
        'code': getattr(error, 'code', None) if isinstance(getattr(error, 'code', None), int) else None,
        'subcode': getattr(error, 'subcode', None) if isinstance(getattr(error, 'subcode', None), int) else None,
        'type': _safe_type(getattr(error, 'type', None)),
    }
    return detail


def plain_transport_explanation(error: BaseException) -> str:
    """Plain owner-facing explanation for a failed Instagram call."""
    call = getattr(error, 'failed_call', None)
    where = 'Instagram publish' if call not in FAILED_CALLS else {
        'container_create': 'Instagram container creation',
        'status_poll': 'Instagram media readiness check',
        'media_publish': 'Instagram publish',
        'media_permalink': 'Instagram link readback',
        'caption_readback': 'Instagram caption readback',
    }.get(call, 'Instagram publish')
    reason = getattr(error, 'reason', None)
    short = _safe_text(reason, 200) or 'the provider refused the call'
    return ('%s failed: %s. Check the brand connection and the public image URL, '
            'then retry from the executor panel. Full detail stays under Details.' % (where, short))


class InstagramTransportError(Exception):
    """Raised when the Graph API refuses or the call cannot complete."""

    def __init__(self, reason: str, *, status: int | None = None,
                 code: int | None = None, subcode: int | None = None,
                 type: str | None = None, failed_call: str | None = None):
        super().__init__(reason)
        self.reason = reason
        self.status = status if isinstance(status, int) else None
        self.code = code if isinstance(code, int) else None
        self.subcode = subcode if isinstance(subcode, int) else None
        self.type = type if isinstance(type, str) else None
        self.failed_call = failed_call if failed_call in FAILED_CALLS else None


def urlopen(request, timeout=None):
    """Single indirection so tests can patch the HTTP seam."""
    from urllib.request import urlopen as _real_urlopen
    return _real_urlopen(request, timeout=timeout)


def _sleep(seconds):
    """Single indirection so tests can patch the polling delay."""
    from time import sleep
    sleep(seconds)


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


def _provider_fields(payload: Any) -> tuple[str | None, int | None, int | None, str | None]:
    if not isinstance(payload, dict):
        return None, None, None, None
    message = payload.get("message")
    code = payload.get("code")
    subcode = payload.get("error_subcode")
    etype = payload.get("type")
    return (message if isinstance(message, str) else None,
            code if isinstance(code, int) else None,
            subcode if isinstance(subcode, int) else None,
            etype if isinstance(etype, str) else None)


def _read_json(request: urllib.request.Request, timeout: float,
               failed_call: str | None = None) -> dict[str, Any]:
    call = failed_call if failed_call in FAILED_CALLS else None
    secrets = _request_secrets(request)
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except HTTPError as error:
        message: str | None = None
        code: int | None = None
        subcode: int | None = None
        etype: str | None = None
        try:
            data = json.loads(error.read().decode("utf-8"))
            provider_error = data.get("error") if isinstance(data, dict) else None
            if isinstance(provider_error, dict):
                message, code, subcode, etype = _provider_fields(provider_error)
        except Exception:
            pass
        if not isinstance(message, str) or not message.strip():
            message = "HTTP %d" % error.code
        scrubbed = _scrub_provider_message(message, secrets)[:200]
        raise InstagramTransportError(PROVIDER_MESSAGE % scrubbed,
                                      status=int(error.code), code=code,
                                      subcode=subcode, type=_safe_type(etype),
                                      failed_call=call) from None
    except Exception as error:
        raise InstagramTransportError(
            PROVIDER_MESSAGE % ("network or HTTP failure: %s" % type(error).__name__),
            failed_call=call) from None
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise InstagramTransportError(PROVIDER_MESSAGE % "unreadable response",
                                      failed_call=call) from None
    if not isinstance(data, dict):
        raise InstagramTransportError(PROVIDER_MESSAGE % "unreadable response",
                                      failed_call=call) from None
    error = data.get("error")
    if isinstance(error, dict):
        message, code, subcode, etype = _provider_fields(error)
        text = message or "unknown provider error"
        scrubbed = _scrub_provider_message(str(text), secrets)[:200]
        raise InstagramTransportError(PROVIDER_MESSAGE % scrubbed,
                                      code=code, subcode=subcode, type=_safe_type(etype),
                                      failed_call=call) from None
    return data


def _post(path: str, payload: dict[str, Any], timeout: float,
          failed_call: str | None = None) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        GRAPH_ORIGIN + "/" + GRAPH_VERSION + path,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    return _read_json(request, timeout, failed_call)


def _get(path_query: str, token: str, timeout: float,
         failed_call: str | None = None) -> dict[str, Any]:
    # The token travels in the Authorization header, never in the URL,
    # so request lines in logs or error reports cannot carry it.
    request = urllib.request.Request(
        GRAPH_ORIGIN + "/" + GRAPH_VERSION + path_query,
        headers={"Authorization": "Bearer " + token},
        method="GET",
    )
    return _read_json(request, timeout, failed_call)


def create_container(ig_user_id: str, media_url: str, caption: str,
                     token: str, timeout: float = 30.0) -> str:
    """Create a media container; return its creation id."""
    user_id = normalize_user_id(ig_user_id)
    url = normalize_media_url(media_url)
    text = normalize_caption(caption)
    key = normalize_token(token)
    data = _post("/%s/media" % user_id,
                 {"image_url": url, "caption": text, "access_token": key},
                 timeout, "container_create")
    creation_id = data.get("id")
    if not isinstance(creation_id, str) or not creation_id.strip():
        raise InstagramTransportError(PROVIDER_MESSAGE % "missing container id",
                                      failed_call="container_create")
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
                 timeout, "media_publish")
    media_id = data.get("id")
    if not isinstance(media_id, str) or not media_id.strip():
        raise InstagramTransportError(PROVIDER_MESSAGE % "missing media id",
                                      failed_call="media_publish")
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


def media_permalink(media_id: str, token: str,
                    timeout: float = 30.0) -> str | None:
    """Return the public permalink for a published media id, or None.

    Returns None instead of raising when the provider answers without a
    usable permalink. Provider refusals still raise, and the caller
    decides whether a missing link fails the post.
    """
    cleaned = media_id.strip() if isinstance(media_id, str) else ""
    if not cleaned:
        return None
    key = normalize_token(token)
    data = _get("/%s?fields=permalink" % cleaned, key, timeout, "media_permalink")
    link = data.get("permalink")
    if not isinstance(link, str) or not link.strip():
        return None
    try:
        parsed = urlparse(link.strip())
    except ValueError:
        return None
    if parsed.scheme != "https" or not parsed.hostname:
        return None
    return link.strip()


def instagram_transport(ig_user_id: str, media_url: str, caption: str,
                        token: str, timeout: float = 30.0) -> dict[str, Any]:
    """Publish one image post; return the real media id, never simulated.

    The public permalink is read back after publishing so the execution
    and delivery records carry a live URL for verification. A permalink
    read failure never fails the post itself: the media is already
    published, and recording a failure would risk a duplicate on retry.
    """
    creation_id = create_container(ig_user_id, media_url, caption, token, timeout)
    key = normalize_token(token)
    for poll in range(20):
        data = _get("/%s?fields=status_code" % creation_id, key, timeout, "status_poll")
        status = data.get("status_code")
        if status == "FINISHED":
            break
        if status in ("ERROR", "EXPIRED"):
            raise InstagramTransportError(
                "instagram media container status: %s" % status,
                failed_call="status_poll")
        if poll < 19:
            _sleep(3)
    else:
        raise InstagramTransportError(
            "instagram media container was not ready in time",
            failed_call="status_poll")
    media_id = publish_container(ig_user_id, creation_id, token, timeout)
    try:
        live_url = media_permalink(media_id, token, timeout)
    except InstagramTransportError:
        live_url = None
    return {"platform_post_id": media_id, "live_url": live_url, "simulated": False}


def fetch_media_caption(media_id: str, token: str,
                        timeout: float = 30.0) -> dict[str, str | None]:
    """Read back caption and permalink for a published media id.

    Uses the fixed Graph origin and version with fields=caption,permalink.
    The token travels in the Authorization header only. Returns a dict
    with caption and permalink (either may be None when the provider
    omits them). Provider refusals raise InstagramTransportError with
    failed_call caption_readback and bounded safe fields only.
    """
    cleaned = media_id.strip() if isinstance(media_id, str) else ""
    if not cleaned or not USER_ID_RE.match(cleaned):
        raise InstagramTransportError("instagram media id must be digits",
                                      failed_call="caption_readback")
    key = normalize_token(token)
    data = _get("/%s?fields=caption,permalink" % cleaned, key, timeout,
                "caption_readback")
    caption = data.get("caption")
    link = data.get("permalink")
    out_caption: str | None = None
    if isinstance(caption, str) and caption.strip():
        out_caption = caption.strip()
    if out_caption is not None and len(out_caption) > CAPTION_MAX_CHARS:
        raise InstagramTransportError("instagram caption readback is over the limit",
                                      failed_call="caption_readback")
    out_link = None
    if isinstance(link, str) and link.strip():
        try:
            parsed = urlparse(link.strip())
        except ValueError:
            parsed = None
        host = (parsed.hostname or "").lower() if parsed is not None else ""
        if (parsed is not None and parsed.scheme == "https"
                and host in ("instagram.com", "www.instagram.com")):
            out_link = link.strip()
        else:
            raise InstagramTransportError("instagram permalink host is not allowed",
                                          failed_call="caption_readback")
    return {"caption": out_caption, "permalink": out_link}
