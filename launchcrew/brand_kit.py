"""Brand kit fields on the voice profile (isolated, dependency-free).

Brand kit keys accepted alongside voice examples: brand_colors (list
of hex or named colors), fonts (list of font names), logo_reference
(string asset reference), and banned_rules (list of banned
rules/terms). Helpers normalize untrusted input, compute a
deterministic digest, and version the kit so any color, font, logo,
or rule change alters the recorded version on the run receipt.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

BRAND_KIT_VERSION_PREFIX = "brand-kit/v1"
MAX_BRAND_COLORS = 20
MAX_BRAND_FONTS = 20
MAX_BRAND_RULES = 50
MAX_BRAND_ENTRY_CHARS = 120
MAX_LOGO_REF_CHARS = 500


def _clean_entries(raw: Any, what: str, limit: int) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise TypeError("brand kit '%s' must be a list" % what)
    if len(raw) > limit:
        raise ValueError("brand kit '%s' must hold at most %d items" % (what, limit))
    cleaned: list[str] = []
    for index, entry in enumerate(raw):
        if not isinstance(entry, str):
            raise TypeError("brand kit '%s[%d]' must be a string" % (what, index))
        text = " ".join(entry.strip().split())
        if not text:
            raise ValueError("brand kit '%s[%d]' must not be empty" % (what, index))
        if len(text) > MAX_BRAND_ENTRY_CHARS:
            raise ValueError("brand kit '%s[%d]' exceeds %d characters" % (what, index, MAX_BRAND_ENTRY_CHARS))
        cleaned.append(text)
    seen: dict[str, str] = {}
    for entry in cleaned:
        key = entry.casefold()
        if key not in seen:
            seen[key] = entry
    return sorted(seen.values(), key=lambda s: (s.casefold(), s))


def _clean_logo(raw: Any) -> str | None:
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise TypeError("brand kit 'logo_reference' must be a string")
    text = raw.strip()
    if not text:
        return None
    if len(text) > MAX_LOGO_REF_CHARS:
        raise ValueError("brand kit 'logo_reference' exceeds %d characters" % MAX_LOGO_REF_CHARS)
    return text


def normalize_brand_kit(content: Any) -> dict[str, Any]:
    """Normalize brand kit fields from an untrusted voice content mapping."""
    source = content if isinstance(content, dict) else {}
    colors = _clean_entries(source.get("brand_colors", source.get("brandColors")), "brand_colors", MAX_BRAND_COLORS)
    fonts = _clean_entries(source.get("fonts"), "fonts", MAX_BRAND_FONTS)
    banned = _clean_entries(source.get("banned_rules", source.get("bannedRules")), "banned_rules", MAX_BRAND_RULES)
    logo = _clean_logo(source.get("logo_reference", source.get("logoReference")))
    return {"brand_colors": colors, "fonts": fonts, "logo_reference": logo, "banned_rules": banned}


def brand_kit_digest(kit: Any) -> str:
    """Deterministic SHA-256 hex over the normalized brand kit."""
    normalized = normalize_brand_kit(kit if isinstance(kit, dict) else {})
    payload = {"brand_colors": normalized["brand_colors"], "fonts": normalized["fonts"],
               "logo_reference": normalized["logo_reference"], "banned_rules": normalized["banned_rules"]}
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def brand_kit_version(kit: Any) -> str:
    """Versioned brand kit label derived from the kit digest."""
    return "%s:%s" % (BRAND_KIT_VERSION_PREFIX, brand_kit_digest(kit)[:16])


def brand_kit_receipt(content: Any) -> dict[str, Any]:
    """Build the receipt brand_kit record with version and digest."""
    kit = normalize_brand_kit(content if isinstance(content, dict) else {})
    digest = brand_kit_digest(kit)
    return {"version": "%s:%s" % (BRAND_KIT_VERSION_PREFIX, digest[:16]),
            "digest": digest,
            "brand_colors": list(kit["brand_colors"]),
            "fonts": list(kit["fonts"]),
            "logo_reference": kit["logo_reference"],
            "banned_rules": list(kit["banned_rules"])}
