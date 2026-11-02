"""Dropbox import connector: provider-gated skeleton, closed by default.

Cloud storage is the second import lane next to Google Drive: the
owner connects a Dropbox app once, then picks files into runs without
manual downloads. This slice is the code-only gate shape: config
detection, status reporting, and authorize plus callback routes that
refuse closed until the owner configures the app. No provider HTTP
exists in this module, so every path runs green keyless with zero
network. Live file reads stay gated on the owner creating the Dropbox
app and granting the token.

All helpers are pure stdlib with no network, model, file, or
environment access beyond reading the three setup names. Reasons are
plain human-readable strings naming the rule that failed.
"""

from __future__ import annotations

import os
from typing import Any

MODULE_VERSION = "dropbox-import/v1"

CALLBACK_PATH = "/api/dropbox-import/callback"

SETUP_NAMES = ("DROPBOX_CLIENT_ID", "DROPBOX_CLIENT_SECRET", "PUBLIC_BASE_URL")

NOT_CONFIGURED_MESSAGE = (
    "dropbox intake unavailable: Dropbox app not configured; "
    "set DROPBOX_CLIENT_ID and DROPBOX_CLIENT_SECRET plus PUBLIC_BASE_URL, "
    "then register the callback URI"
)


def dropbox_configured() -> bool:
    """Return True only when the Dropbox app values are present."""
    return bool(
        os.getenv("DROPBOX_CLIENT_ID", "").strip()
        and os.getenv("DROPBOX_CLIENT_SECRET", "").strip()
    )


def callback_uri() -> str:
    """Return the exact OAuth callback URI for app registration."""
    base = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
    return base + CALLBACK_PATH


def status_dict() -> dict[str, Any]:
    """Return the public connector status without leaking values."""
    configured = dropbox_configured()
    return {"available": configured,
            "configured": configured,
            "live_verified": False,
            "reason": "ok" if configured else "dropbox_not_configured",
            "callback_path": CALLBACK_PATH,
            "setup_names": list(SETUP_NAMES)}


def missing_setup_names() -> list[str]:
    """Return the setup names that are absent or blank, names only."""
    return [name for name in SETUP_NAMES
            if not os.getenv(name, "").strip()]
