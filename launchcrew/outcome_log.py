"""Owner-entered outcome log entry helper (standard library only).

Builds a deterministic, validated in-memory entry from owner-supplied
inputs. There is no clock, no implicit date, no persistence, no
networking, and no provider verification.

Bounds (conservative and documented):
  - channel: exact, case-sensitive member of KNOWN_CHANNELS.
    Per-platform channels use canonical lowercase spellings: "x" for
    X, "linkedin" for LinkedIn, "instagram" for Instagram, and
    "facebook" for Facebook. Generic "social" is not accepted.
  - date: string in YYYY-MM-DD format that is a real calendar date.
  - count: type-exact int (booleans rejected), 0 <= count <= MAX_COUNT.
  - note: non-empty (after stripping whitespace), single line,
    len(note) <= MAX_NOTE_LENGTH, with no control characters
    (code points < 32 or == 127 are rejected).

Provenance on every accepted entry is explicitly owner-entered and
self-reported. Accepted entries never claim measurement, verification,
provider observation, or auto-confirmation.

Failure is closed: any invalid field yields accepted=False, entry=None,
and a structured errors dict keyed by field name.
"""

import datetime

__all__ = [
    "KNOWN_CHANNELS",
    "MAX_COUNT",
    "MIN_COUNT",
    "MAX_NOTE_LENGTH",
    "PROVENANCE",
    "ENTERED_BY",
    "log_outcome",
]

# Finite closed set of owner-reportable channels. Exact match only:
# case-sensitive, no stripping, no coercion, no additions at runtime.
# Per-platform channels use canonical lowercase spellings: "x" (X),
# "linkedin" (LinkedIn), "instagram" (Instagram), "facebook" (Facebook).
# Generic "social" is intentionally absent: it must not substitute for
# a per-platform channel when a per-platform comparison is required.
KNOWN_CHANNELS = frozenset({
    "email",
    "web",
    "sms",
    "phone",
    "in_person",
    "other",
    "x",
    "linkedin",
    "instagram",
    "facebook",
})

MIN_COUNT = 0
MAX_COUNT = 1000000
MAX_NOTE_LENGTH = 500

# Provenance constants for accepted entries. These are the only
# provenance claims this helper ever emits.
PROVENANCE = "self_reported"
ENTERED_BY = "owner_entered"


def _validate_channel(channel):
    if not isinstance(channel, str):
        return "channel must be a string"
    if channel not in KNOWN_CHANNELS:
        return (
            "unknown channel; expected one of: "
            + ", ".join(sorted(KNOWN_CHANNELS))
        )
    return None


def _validate_date(date):
    if not isinstance(date, str):
        return "date must be a string in YYYY-MM-DD format"
    if len(date) != 10 or date[4] != "-" or date[7] != "-":
        return "date must be in YYYY-MM-DD format"
    parts = date.split("-")
    if (
        len(parts) != 3
        or len(parts[0]) != 4
        or len(parts[1]) != 2
        or len(parts[2]) != 2
        or not all(part.isascii() and part.isdigit() for part in parts)
    ):
        return "date must be in YYYY-MM-DD format"
    year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
    try:
        datetime.date(year, month, day)
    except ValueError:
        return "date is not a real calendar date"
    return None


def _validate_count(count):
    # type() check is exact on purpose: bool is a subclass of int and
    # must be rejected, so isinstance() is not used here.
    if type(count) is not int:
        return "count must be an integer"
    if count < MIN_COUNT:
        return "count must be >= 0"
    if count > MAX_COUNT:
        return "count must be <= 1000000"
    return None


def _validate_note(note):
    if not isinstance(note, str):
        return "note must be a string"
    if not note.strip():
        return "note must not be empty"
    if len(note) > MAX_NOTE_LENGTH:
        return "note must be <= 500 characters"
    for char in note:
        code = ord(char)
        if code < 32 or code == 127:
            return "note contains unsafe control characters"
    return None


def log_outcome(channel, date, count, note):
    """Validate owner inputs and build an outcome log entry.

    All four arguments are required; there are no defaults and no
    implicit date. Caller inputs are preserved verbatim: the accepted
    entry stores the exact channel, date, count, and note values, and
    the result echoes the original inputs.

    Returns a dict:
      - accepted=True: {"accepted": True, "entry": {...},
        "errors": {}, "inputs": {...}}
      - accepted=False: {"accepted": False, "entry": None,
        "errors": {field: message}, "inputs": {...}}

    The accepted entry has exactly the keys channel, date, count,
    note, provenance ("self_reported"), and entered_by
    ("owner_entered"). It carries no timestamps, ids, or provider
    claims. The function is deterministic: equal inputs yield equal
    outputs.
    """
    inputs = {"channel": channel, "date": date, "count": count, "note": note}
    errors = {}

    channel_error = _validate_channel(channel)
    if channel_error is not None:
        errors["channel"] = channel_error
    date_error = _validate_date(date)
    if date_error is not None:
        errors["date"] = date_error
    count_error = _validate_count(count)
    if count_error is not None:
        errors["count"] = count_error
    note_error = _validate_note(note)
    if note_error is not None:
        errors["note"] = note_error

    if errors:
        return {"accepted": False, "entry": None, "errors": errors, "inputs": inputs}

    entry = {
        "channel": channel,
        "date": date,
        "count": count,
        "note": note,
        "provenance": PROVENANCE,
        "entered_by": ENTERED_BY,
    }
    return {"accepted": True, "entry": entry, "errors": {}, "inputs": inputs}
