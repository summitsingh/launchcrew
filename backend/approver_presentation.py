"""Central neutral approver presentation for public receipt surfaces.

Internal storage keeps raw actor keys (for example provider subjects and the
shared demo placeholder) in receipts, the approvals table, and the audit
table. Public surfaces must never render those identifiers. This module maps
them to one neutral label by schema field, with actor pattern recognition
only for generic actor/profile slots where agent names must be preserved.
"""

import copy

PUBLIC_APPROVER_LABEL = "Public demo reviewer"

# Schema fields that always hold a human approver identity when non empty.
_APPROVER_FIELDS = frozenset({"approved_by", "revised_by", "exported_by", "last_exported_by"})

# Generic slots that may hold either an agent name or an actor key.
_ACTOR_LIKE_FIELDS = frozenset({"actor", "profile"})

_PROVIDER_PREFIXES = ("google:", "facebook:", "demo:", "auth:")


def is_actor_identifier(value):
    """True for values that look like an auth actor key, not a display name."""
    if not isinstance(value, str):
        return False
    text = value.strip()
    if not text:
        return False
    lowered = text.lower()
    if lowered in {"demo_placeholder", "keyless", "pending"}:
        return True
    if text.startswith(_PROVIDER_PREFIXES):
        return True
    if "@" in text:
        return True
    if text.isdigit() and len(text) >= 5:
        return True
    if ":" in text and " " not in text and len(text) >= 8:
        return True
    return False


def presentation_approver(value):
    """Neutral label for schema approver fields. Empty values stay empty."""
    if isinstance(value, str) and value.strip():
        return PUBLIC_APPROVER_LABEL
    return value


def presentation_actor(value):
    """Neutral label for generic actor slots, preserving agent names."""
    if is_actor_identifier(value):
        return PUBLIC_APPROVER_LABEL
    return value


def _sanitize_node(node):
    if isinstance(node, dict):
        cleaned = {}
        for key, value in node.items():
            if key in _APPROVER_FIELDS:
                cleaned[key] = presentation_approver(value) if isinstance(value, str) else value
            elif key in _ACTOR_LIKE_FIELDS and isinstance(value, str):
                cleaned[key] = presentation_actor(value)
            else:
                cleaned[key] = _sanitize_node(value)
        return cleaned
    if isinstance(node, list):
        return [_sanitize_node(entry) for entry in node]
    return node


def sanitize_receipt_for_presentation(receipt):
    """Return a presentation copy with approver identities neutralized.

    The input dict is never mutated, so callers can persist the raw receipt
    first and sanitize only the served copy.
    """
    if not isinstance(receipt, dict):
        return receipt
    return _sanitize_node(copy.deepcopy(receipt))


def sanitize_bundle_for_presentation(bundle):
    """Neutralize channel approval identities in a channel bundle copy."""
    if not isinstance(bundle, dict):
        return bundle
    return _sanitize_node(copy.deepcopy(bundle))


def sanitize_copy_record_for_presentation(record):
    """Neutralize the approver slot in a server authorized copy record."""
    if not isinstance(record, dict):
        return record
    cleaned = copy.deepcopy(record)
    if isinstance(cleaned.get("approved_by"), str) and cleaned["approved_by"].strip():
        cleaned["approved_by"] = PUBLIC_APPROVER_LABEL
    return cleaned
