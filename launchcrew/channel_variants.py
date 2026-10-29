"""Channel presentation variants for later integration.

Pure standard library helpers. No model calls, no fetching, no
publishing, no photo behavior.

Inputs are caller supplied: checked draft text, confirmed fact strings,
and audience or angle context. Outputs are presentation variants only.
Every draft sentence in every variant is copied verbatim from the
checked draft. No sentence is reworded, shortened, or split. Trimming
for X drops whole trailing sentences only, on a full sentence boundary,
with an explicit trim note. Audience suggestions and campaign angles
are recorded as unverified context in metadata and are never rendered
as product facts.
"""

import copy
import re

MODULE_VERSION = "channel-variants/v1"
X_MAX_CHARS = 280
CHANNELS = ("x", "linkedin", "instagram", "email")

LINKEDIN_HEADER = "Update:"
INSTAGRAM_CLOSER = "More soon."
EMAIL_SUBJECT = "Quick update"
EMAIL_GREETING = "Hello,"
EMAIL_CLOSER = "Thanks,"

SOURCE_LABEL = "caller_checked_draft"
CONTEXT_NOTE = "Suggestion only. Not a verified product fact."

PRICE_RE = re.compile(r"[$\u00a3\u20ac]\s*\d+(?:[,.]\d+)*")
PERCENT_RE = re.compile(r"\d+(?:\.\d+)?%")
SIZE_RE = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:mm|cm|m|km|in|inch|inches|ft|feet|oz|ml|l|g|kg|lb|pcs|pack)\b",
    re.I,
)

ABBREVIATIONS = frozenset(
    {
        "mr",
        "mrs",
        "ms",
        "dr",
        "prof",
        "sr",
        "jr",
        "st",
        "vs",
        "dept",
        "inc",
        "ltd",
        "co",
        "corp",
        "ave",
        "blvd",
        "rd",
        "ft",
        "fig",
        "no",
        "nos",
        "approx",
        "appt",
        "apt",
        "etc",
    }
)


def _is_abbreviation_period(chunk, idx):
    """True when chunk[idx] is a period that does not end a sentence."""
    if chunk[idx] != ".":
        return False
    if idx >= 3:
        tail = chunk[idx - 3 : idx + 1].lower()
        if tail in ("e.g.", "i.e."):
            return True
    k = idx - 1
    while k >= 0 and chunk[k].isalpha():
        k -= 1
    token = chunk[k + 1 : idx]
    if not token:
        return False
    if token.lower() in ABBREVIATIONS:
        return True
    if len(token) == 1 and token.isupper():
        return True
    return False


def _looks_like_abbreviation_fragment(sentence):
    """True for single-token fragments such as 'Dr.' that must not export."""
    s = sentence.strip()
    if " " in s or not s.endswith("."):
        return False
    core = s[:-1].strip().strip(".!?")
    if not core or not core.isalpha():
        return False
    if core.lower() in ABBREVIATIONS:
        return True
    return len(core) == 1 and core.isupper()


def split_sentences(text):
    """Split text into sentences without breaking decimals or abbreviations.

    A period between two digits (as in $49.99 or 3.5) is never a
    boundary. A period ending a known abbreviation (as in Dr. Lee) or
    a single capital initial is never a boundary either. Otherwise a
    run of . ! ? followed by whitespace or the end of the paragraph
    ends a sentence. Newlines also split paragraphs. Terminators are
    preserved on each sentence.
    """
    if not isinstance(text, str):
        raise TypeError("draft_text must be a string")
    sentences = []
    for paragraph in re.split(r"\n+", text):
        chunk = paragraph.strip()
        if not chunk:
            continue
        buf = ""
        i = 0
        n = len(chunk)
        while i < n:
            ch = chunk[i]
            buf += ch
            if ch in ".!?":
                if ch == "." and i > 0 and i + 1 < n:
                    if chunk[i - 1].isdigit() and chunk[i + 1].isdigit():
                        i += 1
                        continue
                j = i + 1
                while j < n and chunk[j] in ".!?":
                    if chunk[j] == "." and j > 0 and j + 1 < n:
                        if chunk[j - 1].isdigit() and chunk[j + 1].isdigit():
                            break
                    buf += chunk[j]
                    j += 1
                if j >= n or chunk[j].isspace():
                    if j - 1 >= i and chunk[j - 1] == ".":
                        if _is_abbreviation_period(chunk, j - 1):
                            i = j
                            continue
                    done = buf.strip()
                    if done:
                        sentences.append(done)
                    buf = ""
                    i = j
                    while i < n and chunk[i].isspace():
                        i += 1
                    continue
            i += 1
        rest = buf.strip()
        if rest:
            sentences.append(rest)
    return sentences


def _confirmed_list(confirmed_facts):
    """Normalize caller confirmed facts to a new list of strings."""
    if isinstance(confirmed_facts, dict):
        items = [confirmed_facts[k] for k in sorted(confirmed_facts)]
    elif isinstance(confirmed_facts, (list, tuple)):
        items = list(confirmed_facts)
    else:
        raise TypeError("confirmed_facts must be a list, tuple, or dict")
    cleaned = []
    for entry in items:
        if not isinstance(entry, str) or not entry.strip():
            raise ValueError("confirmed facts must be nonempty strings")
        cleaned.append(entry)
    return cleaned


def _measured_tokens(text):
    """Price, percent, and size tokens in exact source spelling."""
    if not isinstance(text, str):
        return []
    found = []
    found.extend(PRICE_RE.findall(text))
    found.extend(PERCENT_RE.findall(text))
    found.extend(SIZE_RE.findall(text))
    return found


def _context_entry(value):
    """Copy audience or angle context with an unverified note."""
    if value is None:
        return None
    if isinstance(value, str):
        if not value.strip():
            return None
        return {"value": value, "note": CONTEXT_NOTE}
    if isinstance(value, dict):
        return {"value": copy.deepcopy(value), "note": CONTEXT_NOTE}
    raise TypeError("context must be a string, dict, or None")


def _base_metadata(channel, confirmed_count, audience, campaign_angle):
    return {
        "module": MODULE_VERSION,
        "source": SOURCE_LABEL,
        "channel": channel,
        "limits": {"x_max_chars": X_MAX_CHARS},
        "confirmed_facts_count": confirmed_count,
        "audience_context": _context_entry(audience),
        "angle_context": _context_entry(campaign_angle),
        "context_note": (
            "Audience and angle inputs are suggestions. They are never "
            "treated as confirmed product facts and are never rendered "
            "into variant text."
        ),
    }


def _needs_revision(channel, confirmed_count, audience, campaign_angle, reason):
    metadata = _base_metadata(channel, confirmed_count, audience, campaign_angle)
    metadata.update(
        {
            "char_count": 0,
            "kept_sentences": 0,
            "total_sentences": 0,
            "omitted_sentences": 0,
            "exportable": False,
            "status": "needs_revision",
        }
    )
    variant = {
        "channel": channel,
        "text": "",
        "exportable": False,
        "status": "needs_revision",
        "reason": reason,
        "trim_note": None,
        "metadata": metadata,
    }
    if channel == "email":
        variant["subject"] = EMAIL_SUBJECT
        variant["body"] = ""
    return variant


def _confirmed_token_set(confirmed):
    tokens = set()
    for fact in confirmed:
        tokens.update(_measured_tokens(fact))
    return tokens


def _split_measured(text, confirmed):
    confirmed_tokens = _confirmed_token_set(confirmed)
    variant_tokens = _measured_tokens(text)
    unconfirmed = sorted({t for t in variant_tokens if t not in confirmed_tokens})
    return variant_tokens, unconfirmed


def _needs_revision_with_claims(
    channel, confirmed_count, audience, campaign_angle, reason, measured, unconfirmed, total
):
    variant = _needs_revision(channel, confirmed_count, audience, campaign_angle, reason)
    variant["metadata"]["total_sentences"] = total
    variant["metadata"]["omitted_sentences"] = total
    variant["metadata"]["measured_claims"] = list(measured)
    variant["metadata"]["unconfirmed_measured_claims"] = list(unconfirmed)
    return variant


def _abbreviation_fragment(sentences):
    for sentence in sentences:
        if _looks_like_abbreviation_fragment(sentence):
            return sentence
    return None


def build_x_variant(draft_text, confirmed_facts, audience=None, campaign_angle=None):
    """Build the X variant, at most 280 characters.

    Keeps leading whole sentences that fit. Drops whole trailing
    sentences with a trim note when needed. Refuses with a
    non-exportable needs-revision result when the first sentence alone
    exceeds the limit, when no sentence exists, when a sentence
    boundary is an abbreviation fragment, or when the kept text
    contains price, percent, or size tokens absent from confirmed
    facts. Never emits a shortened fragment and never exports
    unconfirmed measurable claims.
    """
    if not isinstance(draft_text, str):
        raise TypeError("draft_text must be a string")
    confirmed = _confirmed_list(confirmed_facts)
    sentences = split_sentences(draft_text)
    if not sentences:
        return _needs_revision(
            "x",
            len(confirmed),
            audience,
            campaign_angle,
            "No sentences found in draft text. Needs revision.",
        )
    first_len = len(sentences[0])
    if first_len > X_MAX_CHARS:
        return _needs_revision(
            "x",
            len(confirmed),
            audience,
            campaign_angle,
            "Non-exportable: first sentence is %d characters, over the "
            "280 character X limit. Needs revision with a shorter "
            "opening sentence. No fragment was exported." % first_len,
        )
    fragment = _abbreviation_fragment(sentences)
    if fragment is not None:
        return _needs_revision_with_claims(
            "x",
            len(confirmed),
            audience,
            campaign_angle,
            "Non-exportable: sentence boundary ambiguity near '%s'. "
            "Needs revision with an expanded abbreviation or rewritten "
            "draft. No fragment was exported." % fragment,
            [],
            [],
            len(sentences),
        )
    kept = []
    for sentence in sentences:
        candidate = sentence if not kept else " ".join(kept + [sentence])
        if len(candidate) <= X_MAX_CHARS:
            kept.append(sentence)
        else:
            break
    text = " ".join(kept)
    char_count = len(text)
    total = len(sentences)
    kept_count = len(kept)
    omitted = total - kept_count
    if kept and _looks_like_abbreviation_fragment(kept[-1]):
        return _needs_revision_with_claims(
            "x",
            len(confirmed),
            audience,
            campaign_angle,
            "Non-exportable: trimmed text would end with abbreviation "
            "fragment '%s'. Needs revision. No fragment was exported."
            % kept[-1],
            [],
            [],
            total,
        )
    variant_tokens, unconfirmed = _split_measured(text, confirmed)
    if unconfirmed:
        return _needs_revision_with_claims(
            "x",
            len(confirmed),
            audience,
            campaign_angle,
            "Non-exportable: measured claims not in confirmed facts: "
            + ", ".join(unconfirmed)
            + ". Needs revision with exact confirmed facts. "
            "No text exported.",
            variant_tokens,
            unconfirmed,
            total,
        )
    if omitted > 0:
        trim_note = (
            "Trimmed to %d of %d sentences (%d/280 chars) on a full "
            "sentence boundary; %d trailing sentence(s) omitted; no "
            "sentence shortened." % (kept_count, total, char_count, omitted)
        )
    else:
        trim_note = None
    metadata = _base_metadata("x", len(confirmed), audience, campaign_angle)
    metadata.update(
        {
            "char_count": char_count,
            "kept_sentences": kept_count,
            "total_sentences": total,
            "omitted_sentences": omitted,
            "measured_claims": list(variant_tokens),
            "unconfirmed_measured_claims": unconfirmed,
            "exportable": True,
            "status": "ready",
        }
    )
    return {
        "channel": "x",
        "text": text,
        "exportable": True,
        "status": "ready",
        "reason": None,
        "trim_note": trim_note,
        "metadata": metadata,
    }


def build_linkedin_variant(draft_text, confirmed_facts, audience=None, campaign_angle=None):
    """Build the LinkedIn variant with all sentences verbatim.

    Fails closed with a non-exportable needs-revision result when the
    rendered text contains price, percent, or size tokens absent from
    confirmed facts, or when a sentence boundary is ambiguous.
    """
    if not isinstance(draft_text, str):
        raise TypeError("draft_text must be a string")
    confirmed = _confirmed_list(confirmed_facts)
    sentences = split_sentences(draft_text)
    if not sentences:
        return _needs_revision(
            "linkedin",
            len(confirmed),
            audience,
            campaign_angle,
            "No sentences found in draft text. Needs revision.",
        )
    fragment = _abbreviation_fragment(sentences)
    if fragment is not None:
        return _needs_revision_with_claims(
            "linkedin",
            len(confirmed),
            audience,
            campaign_angle,
            "Non-exportable: sentence boundary ambiguity near '%s'. "
            "Needs revision with an expanded abbreviation or rewritten "
            "draft. No fragment was exported." % fragment,
            [],
            [],
            len(sentences),
        )
    text = LINKEDIN_HEADER + "\n\n" + "\n\n".join(sentences)
    variant_tokens, unconfirmed = _split_measured(text, confirmed)
    if unconfirmed:
        return _needs_revision_with_claims(
            "linkedin",
            len(confirmed),
            audience,
            campaign_angle,
            "Non-exportable: measured claims not in confirmed facts: "
            + ", ".join(unconfirmed)
            + ". Needs revision with exact confirmed facts. "
            "No text exported.",
            variant_tokens,
            unconfirmed,
            len(sentences),
        )
    metadata = _base_metadata("linkedin", len(confirmed), audience, campaign_angle)
    metadata.update(
        {
            "char_count": len(text),
            "kept_sentences": len(sentences),
            "total_sentences": len(sentences),
            "omitted_sentences": 0,
            "measured_claims": list(variant_tokens),
            "unconfirmed_measured_claims": unconfirmed,
            "exportable": True,
            "status": "ready",
        }
    )
    return {
        "channel": "linkedin",
        "text": text,
        "exportable": True,
        "status": "ready",
        "reason": None,
        "trim_note": None,
        "metadata": metadata,
    }


def build_instagram_variant(draft_text, confirmed_facts, audience=None, campaign_angle=None):
    """Build the Instagram variant with all sentences verbatim.

    Fails closed with a non-exportable needs-revision result when the
    rendered text contains price, percent, or size tokens absent from
    confirmed facts, or when a sentence boundary is ambiguous.
    """
    if not isinstance(draft_text, str):
        raise TypeError("draft_text must be a string")
    confirmed = _confirmed_list(confirmed_facts)
    sentences = split_sentences(draft_text)
    if not sentences:
        return _needs_revision(
            "instagram",
            len(confirmed),
            audience,
            campaign_angle,
            "No sentences found in draft text. Needs revision.",
        )
    fragment = _abbreviation_fragment(sentences)
    if fragment is not None:
        return _needs_revision_with_claims(
            "instagram",
            len(confirmed),
            audience,
            campaign_angle,
            "Non-exportable: sentence boundary ambiguity near '%s'. "
            "Needs revision with an expanded abbreviation or rewritten "
            "draft. No fragment was exported." % fragment,
            [],
            [],
            len(sentences),
        )
    text = "\n\n".join(sentences) + "\n\n" + INSTAGRAM_CLOSER
    variant_tokens, unconfirmed = _split_measured(text, confirmed)
    if unconfirmed:
        return _needs_revision_with_claims(
            "instagram",
            len(confirmed),
            audience,
            campaign_angle,
            "Non-exportable: measured claims not in confirmed facts: "
            + ", ".join(unconfirmed)
            + ". Needs revision with exact confirmed facts. "
            "No text exported.",
            variant_tokens,
            unconfirmed,
            len(sentences),
        )
    metadata = _base_metadata("instagram", len(confirmed), audience, campaign_angle)
    metadata.update(
        {
            "char_count": len(text),
            "kept_sentences": len(sentences),
            "total_sentences": len(sentences),
            "omitted_sentences": 0,
            "measured_claims": list(variant_tokens),
            "unconfirmed_measured_claims": unconfirmed,
            "exportable": True,
            "status": "ready",
        }
    )
    return {
        "channel": "instagram",
        "text": text,
        "exportable": True,
        "status": "ready",
        "reason": None,
        "trim_note": None,
        "metadata": metadata,
    }


def build_email_variant(draft_text, confirmed_facts, audience=None, campaign_angle=None):
    """Build the email variant with a fixed subject and verbatim body.

    Fails closed with a non-exportable needs-revision result when the
    rendered body contains price, percent, or size tokens absent from
    confirmed facts, or when a sentence boundary is ambiguous.
    """
    if not isinstance(draft_text, str):
        raise TypeError("draft_text must be a string")
    confirmed = _confirmed_list(confirmed_facts)
    sentences = split_sentences(draft_text)
    if not sentences:
        return _needs_revision(
            "email",
            len(confirmed),
            audience,
            campaign_angle,
            "No sentences found in draft text. Needs revision.",
        )
    fragment = _abbreviation_fragment(sentences)
    if fragment is not None:
        return _needs_revision_with_claims(
            "email",
            len(confirmed),
            audience,
            campaign_angle,
            "Non-exportable: sentence boundary ambiguity near '%s'. "
            "Needs revision with an expanded abbreviation or rewritten "
            "draft. No fragment was exported." % fragment,
            [],
            [],
            len(sentences),
        )
    body = EMAIL_GREETING + "\n\n" + " ".join(sentences) + "\n\n" + EMAIL_CLOSER
    variant_tokens, unconfirmed = _split_measured(body, confirmed)
    if unconfirmed:
        return _needs_revision_with_claims(
            "email",
            len(confirmed),
            audience,
            campaign_angle,
            "Non-exportable: measured claims not in confirmed facts: "
            + ", ".join(unconfirmed)
            + ". Needs revision with exact confirmed facts. "
            "No text exported.",
            variant_tokens,
            unconfirmed,
            len(sentences),
        )
    metadata = _base_metadata("email", len(confirmed), audience, campaign_angle)
    metadata.update(
        {
            "char_count": len(body),
            "kept_sentences": len(sentences),
            "total_sentences": len(sentences),
            "omitted_sentences": 0,
            "measured_claims": list(variant_tokens),
            "unconfirmed_measured_claims": unconfirmed,
            "exportable": True,
            "status": "ready",
        }
    )
    return {
        "channel": "email",
        "subject": EMAIL_SUBJECT,
        "body": body,
        "text": body,
        "exportable": True,
        "status": "ready",
        "reason": None,
        "trim_note": None,
        "metadata": metadata,
    }


def build_channel_variants(draft_text, confirmed_facts, audience=None, campaign_angle=None):
    """Build all four presentation variants plus provenance.

    Variant text comes only from verbatim draft sentences plus fixed
    non-factual framing. Audience and campaign angle inputs are kept in
    metadata as suggestions and never rendered as facts.
    """
    confirmed_copy = _confirmed_list(confirmed_facts)
    variants = {
        "x": build_x_variant(draft_text, confirmed_copy, audience, campaign_angle),
        "linkedin": build_linkedin_variant(draft_text, confirmed_copy, audience, campaign_angle),
        "instagram": build_instagram_variant(draft_text, confirmed_copy, audience, campaign_angle),
        "email": build_email_variant(draft_text, confirmed_copy, audience, campaign_angle),
    }
    provenance = {
        "module": MODULE_VERSION,
        "source": SOURCE_LABEL,
        "channels": list(CHANNELS),
        "confirmed_facts_count": len(confirmed_copy),
        "audience_context": _context_entry(audience),
        "angle_context": _context_entry(campaign_angle),
        "limits": {"x_max_chars": X_MAX_CHARS},
        "note": (
            "Presentation only. No new factual assertions. Audience and "
            "angle are suggestions, not verified facts. Price, material, "
            "contents, and size wording is copied verbatim or the "
            "variant refuses."
        ),
    }
    return {
        "x": variants["x"],
        "linkedin": variants["linkedin"],
        "instagram": variants["instagram"],
        "email": variants["email"],
        "provenance": provenance,
    }


def validate_x_variant(x_text, confirmed_facts, draft_text):
    """Deterministically validate an X variant candidate.

    Checks the 280 character limit, verbatim sentence relationship to
    the draft, and exact measured-claim relationship to confirmed
    facts. Returns a dict with ok, exportable, char_count, limit, and
    reasons. Never raises on content; type errors fail closed.
    """
    limit = X_MAX_CHARS
    if not isinstance(x_text, str) or not isinstance(draft_text, str):
        return {
            "ok": False,
            "exportable": False,
            "char_count": 0,
            "limit": limit,
            "reasons": ["Invalid input types."],
            "checks": {"limit_ok": False, "nonempty_ok": False},
        }
    try:
        confirmed = _confirmed_list(confirmed_facts)
    except (TypeError, ValueError):
        return {
            "ok": False,
            "exportable": False,
            "char_count": len(x_text),
            "limit": limit,
            "reasons": ["Invalid confirmed facts."],
            "checks": {"limit_ok": len(x_text) <= limit, "nonempty_ok": bool(x_text.strip())},
        }
    reasons = []
    char_count = len(x_text)
    limit_ok = char_count <= limit
    if not limit_ok:
        reasons.append("Exceeds %d characters (%d chars)." % (limit, char_count))
    nonempty_ok = bool(x_text.strip())
    if not nonempty_ok:
        reasons.append("Empty X text.")
        return {
            "ok": False,
            "exportable": False,
            "char_count": char_count,
            "limit": limit,
            "reasons": reasons,
            "checks": {"limit_ok": limit_ok, "nonempty_ok": False},
        }
    try:
        x_sentences = split_sentences(x_text)
    except TypeError:
        x_sentences = []
    verbatim_ok = True
    for sentence in x_sentences:
        if sentence not in draft_text:
            verbatim_ok = False
            preview = sentence[:40]
            reasons.append("Sentence not verbatim in draft: %s" % preview)
    if not x_sentences:
        verbatim_ok = False
        reasons.append("No complete sentence found in X text.")
    confirmed_tokens = set()
    for fact in confirmed:
        confirmed_tokens.update(_measured_tokens(fact))
    variant_tokens = _measured_tokens(x_text)
    measured_ok = True
    for token in variant_tokens:
        if token not in confirmed_tokens:
            measured_ok = False
            reasons.append("Measured claim not in confirmed facts: %s" % token)
    ok = limit_ok and nonempty_ok and verbatim_ok and measured_ok
    return {
        "ok": ok,
        "exportable": ok,
        "char_count": char_count,
        "limit": limit,
        "reasons": reasons,
        "checks": {
            "limit_ok": limit_ok,
            "nonempty_ok": nonempty_ok,
            "verbatim_ok": verbatim_ok,
            "measured_ok": measured_ok,
        },
    }
