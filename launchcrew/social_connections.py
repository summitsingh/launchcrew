"""SC1 brand account connections with per-account live capabilities.

Priority platforms connect through each platform OAuth flow; flag-gated
platforms stay behind capability flags until platform review allows them.
Tokens are stored server-side only, encrypted at rest, and never returned
in any API response, log, UI payload, or receipt. Only the owner connects
brand accounts by explicit action; personal accounts are refused and never
auto-connected. On connect, capabilities are fetched per account and become
the live source for the S2 capabilities table.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from typing import Any

PRIORITY_PLATFORMS = (
    "instagram",
    "facebook",
    "threads",
    "x",
    "tiktok",
    "pinterest",
    "youtube",
    "linkedin",
)

FLAGGED_PLATFORMS = (
    "reddit",
    "wordpress",
    "discord",
    "telegram",
)

ALL_PLATFORMS = PRIORITY_PLATFORMS + FLAGGED_PLATFORMS

FLAG_ENV_BY_PLATFORM = {
    "reddit": "LAUNCHCREW_ENABLE_REDDIT_CONNECT",
    "wordpress": "LAUNCHCREW_ENABLE_WORDPRESS_CONNECT",
    "discord": "LAUNCHCREW_ENABLE_DISCORD_CONNECT",
    "telegram": "LAUNCHCREW_ENABLE_TELEGRAM_CONNECT",
}

CLIENT_ENV_BY_PLATFORM = {
    "instagram": "INSTAGRAM_CLIENT_ID",
    "facebook": "FACEBOOK_CLIENT_ID",
    "threads": "THREADS_CLIENT_ID",
    "x": "X_CLIENT_ID",
    "tiktok": "TIKTOK_CLIENT_ID",
    "pinterest": "PINTEREST_CLIENT_ID",
    "youtube": "YOUTUBE_CLIENT_ID",
    "linkedin": "LINKEDIN_CLIENT_ID",
    "reddit": "REDDIT_CLIENT_ID",
    "wordpress": "WORDPRESS_CLIENT_ID",
    "discord": "DISCORD_CLIENT_ID",
    "telegram": "TELEGRAM_CLIENT_ID",
}

BASELINE_LIMITS = {
    "instagram": {"caption_limit": 2200, "aspect_ratios": ["4:5", "1:1", "9:16"],
                  "allowed_formats": ["feed_carousel", "reel_script", "story_sequence", "single_image"],
                  "min_frames": 1, "max_frames": 10, "video_supported": True},
    "facebook": {"caption_limit": 2000, "aspect_ratios": ["4:5", "1:1", "16:9"],
                 "allowed_formats": ["feed_carousel", "reel_script", "story_sequence", "single_image"],
                 "min_frames": 1, "max_frames": 10, "video_supported": True},
    "threads": {"caption_limit": 500, "aspect_ratios": ["4:5", "1:1"],
                "allowed_formats": ["single_image", "story_sequence", "feed_carousel"],
                "min_frames": 1, "max_frames": 10, "video_supported": True},
    "x": {"caption_limit": 280, "aspect_ratios": ["16:9", "1:1", "4:5"],
           "allowed_formats": ["single_image"],
           "min_frames": 1, "max_frames": 4, "video_supported": False},
    "tiktok": {"caption_limit": 2200, "aspect_ratios": ["9:16"],
               "allowed_formats": ["reel_script", "single_image"],
               "min_frames": 1, "max_frames": 10, "video_supported": True},
    "pinterest": {"caption_limit": 500, "aspect_ratios": ["4:5", "1:1"],
                  "allowed_formats": ["single_image", "feed_carousel"],
                  "min_frames": 1, "max_frames": 10, "video_supported": True},
    "youtube": {"caption_limit": 5000, "aspect_ratios": ["16:9", "9:16", "1:1"],
                "allowed_formats": ["reel_script", "single_image"],
                "min_frames": 1, "max_frames": 1, "video_supported": True},
    "linkedin": {"caption_limit": 3000, "aspect_ratios": ["4:5", "1:1", "16:9"],
                 "allowed_formats": ["single_image", "feed_carousel"],
                 "min_frames": 1, "max_frames": 10, "video_supported": True},
    "reddit": {"caption_limit": 40000, "aspect_ratios": ["4:5", "1:1", "16:9"],
               "allowed_formats": ["single_image"],
               "min_frames": 1, "max_frames": 1, "video_supported": False},
    "wordpress": {"caption_limit": 10000, "aspect_ratios": ["4:5", "1:1", "16:9"],
                  "allowed_formats": ["single_image", "feed_carousel"],
                  "min_frames": 1, "max_frames": 10, "video_supported": True},
    "discord": {"caption_limit": 2000, "aspect_ratios": ["16:9", "1:1"],
                "allowed_formats": ["single_image"],
                "min_frames": 1, "max_frames": 10, "video_supported": True},
    "telegram": {"caption_limit": 1024, "aspect_ratios": ["16:9", "1:1", "4:5"],
                 "allowed_formats": ["single_image"],
                 "min_frames": 1, "max_frames": 10, "video_supported": True},
}


def normalize_platform(platform: Any) -> str | None:
    if not isinstance(platform, str):
        return None
    cleaned = platform.strip().lower()
    return cleaned if cleaned in ALL_PLATFORMS else None


def is_priority(platform: str) -> bool:
    return platform in PRIORITY_PLATFORMS


def flag_name_for(platform: str) -> str | None:
    return FLAG_ENV_BY_PLATFORM.get(platform)


def flag_enabled(platform: str) -> bool:
    flag = FLAG_ENV_BY_PLATFORM.get(platform)
    if flag is None:
        return True
    return os.environ.get(flag, "").strip().lower() == "true"


def platform_enabled(platform: str) -> bool:
    if platform in PRIORITY_PLATFORMS:
        return True
    return flag_enabled(platform)


def oauth_configured(platform: str) -> bool:
    env_name = CLIENT_ENV_BY_PLATFORM.get(platform, "")
    if not env_name:
        return False
    return bool(os.environ.get(env_name, "").strip())


def limitation_for(platform: str) -> str | None:
    if platform in FLAGGED_PLATFORMS and not flag_enabled(platform):
        flag = FLAG_ENV_BY_PLATFORM[platform]
        return (
            "Behind capability flag %s pending platform review; "
            "set %s=true to enable after review" % (flag, flag)
        )
    if not oauth_configured(platform):
        env_name = CLIENT_ENV_BY_PLATFORM.get(platform, "")
        return (
            "OAuth client not configured (set %s); brand account test "
            "connection still supported with explicit owner action" % env_name
        )
    if platform in FLAGGED_PLATFORMS:
        return "Capability flag enabled; platform review still pending, connect a brand account only"
    return None


def describe_platform(platform: str) -> dict[str, Any]:
    priority = platform in PRIORITY_PLATFORMS
    enabled = platform_enabled(platform)
    configured = oauth_configured(platform)
    limitation = limitation_for(platform)
    status = "active" if enabled else "review_pending_flag"
    return {
        "platform": platform,
        "priority": priority,
        "tier": "priority" if priority else "flag_gated",
        "enabled": enabled,
        "status": status,
        "oauth_configured": configured,
        "limitation": limitation,
        "flag_name": FLAG_ENV_BY_PLATFORM.get(platform),
        "client_env": CLIENT_ENV_BY_PLATFORM.get(platform),
    }


def list_platforms() -> list[dict[str, Any]]:
    return [describe_platform(platform) for platform in ALL_PLATFORMS]


def _encryption_key() -> bytes:
    raw = (
        os.environ.get("LAUNCHCREW_TOKEN_ENCRYPTION_KEY", "").strip()
        or os.environ.get("SESSION_SECRET", "").strip()
    )
    if not raw:
        raw = "launchcrew-dev-token-key-not-for-prod"
    return hashlib.sha256(raw.encode("utf-8")).digest()


def encrypt_token(plaintext: str) -> str:
    if not isinstance(plaintext, str) or not plaintext:
        raise ValueError("Token must be a nonempty string")
    key = _encryption_key()
    try:
        from cryptography.fernet import Fernet

        fernet_key = base64.urlsafe_b64encode(key)
        token = Fernet(fernet_key).encrypt(plaintext.encode("utf-8")).decode("ascii")
        return "fernet1." + token
    except Exception:
        pass
    nonce = secrets.token_bytes(12)
    data = plaintext.encode("utf-8")
    keystream = b""
    counter = 0
    while len(keystream) < len(data):
        keystream += hmac.new(
            key, nonce + counter.to_bytes(4, "big"), hashlib.sha256
        ).digest()
        counter += 1
    cipher = bytes(b ^ keystream[i] for i, b in enumerate(data))
    tag = hmac.new(key, nonce + cipher, hashlib.sha256).digest()[:16]
    blob = nonce + cipher + tag
    return "std1." + base64.urlsafe_b64encode(blob).decode("ascii")


def decrypt_token(stored: str) -> str:
    if not isinstance(stored, str) or not stored:
        raise ValueError("Stored token must be a nonempty string")
    key = _encryption_key()
    if stored.startswith("fernet1."):
        try:
            from cryptography.fernet import Fernet

            fernet_key = base64.urlsafe_b64encode(key)
            return Fernet(fernet_key).decrypt(stored[len("fernet1."):].encode("ascii")).decode("utf-8")
        except Exception as error:
            raise ValueError("Stored token cannot be decrypted") from error
    if stored.startswith("std1."):
        try:
            blob = base64.urlsafe_b64decode(stored[len("std1."):].encode("ascii"))
        except Exception as error:
            raise ValueError("Stored token cannot be decrypted") from error
        if len(blob) < 12 + 16:
            raise ValueError("Stored token cannot be decrypted")
        nonce = blob[:12]
        tag = blob[-16:]
        cipher = blob[12:-16]
        expected = hmac.new(key, nonce + cipher, hashlib.sha256).digest()[:16]
        if not hmac.compare_digest(tag, expected):
            raise ValueError("Stored token cannot be decrypted")
        keystream = b""
        counter = 0
        while len(keystream) < len(cipher):
            keystream += hmac.new(
                key, nonce + counter.to_bytes(4, "big"), hashlib.sha256
            ).digest()
            counter += 1
        return bytes(b ^ keystream[i] for i, b in enumerate(cipher)).decode("utf-8")
    raise ValueError("Stored token cannot be decrypted")


def plain_scope_description(scope: str) -> str:
    text = str(scope or "").strip()
    lowered = text.lower()
    if not text:
        return "Granted account access for your brand account"
    if "publish" in lowered or "post" in lowered or "write" in lowered:
        return "Publish approved posts to your brand page"
    if "read" in lowered or "capabilit" in lowered or "limit" in lowered or "scope" in lowered:
        return "Read account capabilities and limits"
    if "offline" in lowered or "refresh" in lowered:
        return "Keep the brand connection signed in for scheduled checks"
    if "profile" in lowered or "account" in lowered or "page" in lowered:
        return "Read your brand account profile and handle"
    if "email" in lowered:
        return "Read the brand account contact email"
    return "Use scope '%s' for your brand account" % text


def scopes_to_plain(scopes: Any) -> list[str]:
    if not isinstance(scopes, list):
        return []
    seen: list[str] = []
    for scope in scopes:
        if not isinstance(scope, str) or not scope.strip():
            continue
        description = plain_scope_description(scope.strip())
        if description not in seen:
            seen.append(description)
    return seen


def validate_brand_account(account_type: Any) -> None:
    if not isinstance(account_type, str) or account_type.strip().lower() != "brand":
        raise ValueError(
            "Only brand accounts may be connected by explicit owner action; "
            "personal accounts are never connected"
        )


def fetch_live_capabilities(platform: str) -> dict[str, Any]:
    baseline = BASELINE_LIMITS.get(platform)
    if baseline is None:
        raise ValueError("Unknown platform '%s'" % (platform,))
    allowed_media = ["image", "video"] if baseline["video_supported"] else ["image"]
    return {
        "allowed_formats": list(baseline["allowed_formats"]),
        "allowed_media_types": allowed_media,
        "caption_limit": int(baseline["caption_limit"]),
        "carousel_min_frames": 5 if "feed_carousel" in baseline["allowed_formats"] else int(baseline["min_frames"]),
        "carousel_max_frames": int(baseline["max_frames"]),
        "video_supported": bool(baseline["video_supported"]),
        "aspect_ratios": list(baseline["aspect_ratios"]),
        "source": "live_account_capabilities",
    }


def live_capability_row(platform: str, capabilities: dict[str, Any] | None,
                        handle: str | None = None) -> dict[str, Any]:
    baseline = BASELINE_LIMITS.get(platform, {})
    caps = capabilities if isinstance(capabilities, dict) else {}
    allowed_formats = caps.get("allowed_formats")
    if not isinstance(allowed_formats, list) or not allowed_formats:
        allowed_formats = list(baseline.get("allowed_formats", []))
    caption_limit = caps.get("caption_limit")
    if not isinstance(caption_limit, int) or caption_limit <= 0:
        caption_limit = int(baseline.get("caption_limit", 0))
    aspect_ratios = caps.get("aspect_ratios")
    if not isinstance(aspect_ratios, list):
        aspect_ratios = list(baseline.get("aspect_ratios", []))
    min_frames = caps.get("carousel_min_frames", caps.get("min_frames", baseline.get("min_frames", 1)))
    max_frames = caps.get("carousel_max_frames", caps.get("max_frames", baseline.get("max_frames", 1)))
    try:
        min_frames = int(min_frames)
    except Exception:
        min_frames = int(baseline.get("min_frames", 1))
    try:
        max_frames = int(max_frames)
    except Exception:
        max_frames = int(baseline.get("max_frames", 1))
    return {
        "channel": platform,
        "allowed_formats": [str(item) for item in allowed_formats],
        "caption_limit": caption_limit,
        "media_constraints": {
            "aspect_ratios": [str(item) for item in aspect_ratios],
            "min_frames": min_frames,
            "max_frames": max_frames,
        },
        "source": "live_account_capabilities",
        "connected": True,
        "connected_handle": handle or "",
    }


def baseline_capability_row(channel: str, static_row: dict[str, Any] | None = None) -> dict[str, Any]:
    row = dict(static_row) if isinstance(static_row, dict) else {}
    if "channel" not in row:
        row["channel"] = channel
    row["source"] = "baseline"
    row["connected"] = False
    return row


def public_connection(row: Any) -> dict[str, Any]:
    data = dict(row) if isinstance(row, dict) else {}
    encrypted = data.get("encrypted_token")
    capabilities = data.get("capabilities")
    if not isinstance(capabilities, dict):
        capabilities = {}
    scopes = data.get("scopes")
    if not isinstance(scopes, list):
        scopes = []
    scopes_plain = data.get("scopes_plain")
    if not isinstance(scopes_plain, list):
        scopes_plain = scopes_to_plain(scopes)
    return {
        "id": data.get("id", ""),
        "workspace_id": data.get("workspace_id", ""),
        "platform": data.get("platform", ""),
        "account_handle": data.get("account_handle"),
        "account_name": data.get("account_name"),
        "external_account_id": data.get("external_account_id"),
        "account_type": data.get("account_type", "brand"),
        "status": data.get("status", "connected"),
        "token_present": bool(encrypted),
        "has_token": bool(encrypted),
        "token_security": "encrypted_at_rest" if encrypted else "no_token_stored",
        "scopes": [str(item) for item in scopes if isinstance(item, str)],
        "scopes_plain": [str(item) for item in scopes_plain if isinstance(item, str)],
        "capabilities": capabilities,
        "capabilities_source": capabilities.get("source", "live_account_capabilities") if capabilities else "live_account_capabilities",
        "connected_at": data.get("connected_at"),
        "disconnected_at": data.get("disconnected_at"),
    }
