"""Content calendar domain logic: slot types, pillars, status derivation.

Slot types are feed_post, story, and reel. Status ranks advance
drafted < checked < approved < exported, with verified as a terminal
owner-held state that automatic sync never demotes. Pillars accept the
five built-in values plus any owner-added non-empty label.
"""
from datetime import date as date_cls

SLOT_TYPES = ('feed_post', 'story', 'reel')
SLOT_STATUSES = ('drafted', 'checked', 'approved', 'exported', 'verified')
BUILTIN_PILLARS = ('product', 'lifestyle', 'styling', 'social_proof', 'offer')

_STATUS_RANK = {'drafted': 0, 'checked': 1, 'approved': 2, 'exported': 3, 'verified': 4}

CAMPAIGN_SLOT_TYPES = ('feed_post', 'story', 'reel', 'feed_post', 'story', 'reel', 'feed_post')
CAMPAIGN_PILLARS = ('product', 'lifestyle', 'styling', 'social_proof', 'offer', 'product', 'lifestyle')


def status_rank(status):
    return _STATUS_RANK.get(status, 0)


def normalize_pillar(value):
    if not isinstance(value, str):
        raise ValueError('pillar must be a string')
    cleaned = ' '.join(value.strip().split())
    if not cleaned or len(cleaned) > 80:
        raise ValueError('pillar must be 1 to 80 characters')
    for char in cleaned:
        code = ord(char)
        if code < 32 or code == 127:
            raise ValueError('pillar contains unsafe control characters')
    return cleaned


def normalize_slot_type(value):
    if value not in SLOT_TYPES:
        raise ValueError('slot_type must be one of feed_post, story, reel')
    return value


def parse_slot_date(value):
    if not isinstance(value, str) or len(value) != 10:
        raise ValueError('slot_date must be in YYYY-MM-DD format')
    try:
        year, month, day = int(value[0:4]), int(value[5:7]), int(value[8:10])
        if value[4] != '-' or value[7] != '-':
            raise ValueError('bad separator')
        return date_cls(year, month, day)
    except (ValueError, TypeError):
        raise ValueError('slot_date must be a real calendar date in YYYY-MM-DD format')


def status_for_receipt(receipt):
    """Derive a slot status from a run receipt without mutating it."""
    if not isinstance(receipt, dict):
        return 'drafted'
    if receipt.get('exported_draft') or receipt.get('export_history'):
        return 'exported'
    if receipt.get('approval_state') == 'approved_for_export':
        return 'approved'
    if receipt.get('status') == 'completed':
        check = receipt.get('checker_v2') or {}
        blocked = check.get('blocked_count') if isinstance(check, dict) else None
        if blocked == 0:
            return 'checked'
    return 'drafted'


def should_advance(stored, computed):
    """Automatic sync only advances; verified is terminal and never demoted."""
    if stored == 'verified':
        return False
    if stored not in _STATUS_RANK or computed not in _STATUS_RANK:
        return False
    return _STATUS_RANK[computed] > _STATUS_RANK[stored]


def slot_type_for_day(day):
    if not isinstance(day, int) or day < 1 or day > 7:
        raise ValueError('campaign day must be 1 to 7')
    return CAMPAIGN_SLOT_TYPES[day - 1]


def pillar_for_day(day):
    if not isinstance(day, int) or day < 1 or day > 7:
        raise ValueError('campaign day must be 1 to 7')
    return CAMPAIGN_PILLARS[day - 1]
