"""Channel presentation candidates, plus checked receipt-bound bundles.

The base builders below are pure standard library helpers. No model
calls, no fetching, no publishing, no photo behavior.

Base builder inputs are caller supplied: draft text, confirmed fact
strings, and audience or angle context. Outputs are presentation
candidates only, never independently exportable. Every candidate
requires downstream current approved Checker/receipt binding before
any export. No Checker approval or receipt is claimed by the base
builders and no approval ID is invented.

Every draft sentence in every candidate is copied verbatim from the
draft. No sentence is reworded, shortened, or split. Trimming for X
and Facebook drops whole trailing sentences only, on a full sentence
boundary, with an explicit trim note. Audience suggestions and
campaign angles are recorded as unverified context in metadata and
are never rendered as product facts.

Slice 4 product integration: checked_channel_variants(receipt)
derives the five candidates from the current approved post draft
and the receipt-bound confirmed claims. It refuses unless the
receipt is currently exportable, meaning human approval for export
on the latest revision with a clean final check and a matching
current approval binding. Audience and campaign angle inputs are
never used there, so no angle is claimed. Every rendered candidate
is re-verified with verify_exact_variant_text; failures downgrade
to needs-revision with no text. Results stay presentation
candidates with no auto-publish; copying the exact text happens
only through authorize_channel_copy at the current revision, which
rechecks the gate, the revision, and the exact rendered text, and
returns the authorized record. The API copy route revalidates this
server-side on a fresh owner-scoped receipt read at click time.
"""

import copy
import re

from .ad_policy_lint import lint_ad_policy

MODULE_VERSION = "channel-variants/v1"
X_MAX_CHARS = 280
FACEBOOK_MAX_CHARS = 2000
TIKTOK_MAX_CHARS = 2200
SHOPIFY_MAX_CHARS = 2000
CHANNELS = ("x", "linkedin", "instagram", "email", "facebook")
LAUNCH_MATRIX_CHANNELS = ("x", "linkedin", "instagram", "email", "facebook", "tiktok", "shopify")

LINKEDIN_HEADER = "Update:"
INSTAGRAM_CLOSER = "More soon."
EMAIL_SUBJECT = "Quick update"
EMAIL_GREETING = "Hello,"
EMAIL_CLOSER = "Thanks,"
TIKTOK_HEADER = "[Visual: 3-second hook]"
TIKTOK_CLOSER = "[Audio: Original voice / CTA: Tap link in bio]"

SOURCE_LABEL = "caller_supplied_draft"
SOURCE_NOTE = (
    "Caller-supplied draft; does not imply current Checker approval "
    "or receipt binding."
)
CONTEXT_NOTE = "Suggestion only. Not a verified product fact."

VARIANT_KIND = "presentation_candidate"
BUNDLE_KIND = "presentation_candidates"
STATUS_CANDIDATE = "candidate_pending_checker"
STATUS_NEEDS_REVISION = "needs_revision"
APPROVAL_NOTE = (
    "Presentation candidate only; not independently exportable. No "
    "Checker approval or receipt binding claimed. Requires downstream "
    "current approved Checker/receipt binding before any export."
)

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
        "source_note": SOURCE_NOTE,
        "variant_kind": VARIANT_KIND,
        "channel": channel,
        "limits": {
            "x_max_chars": X_MAX_CHARS,
            "facebook_max_chars": FACEBOOK_MAX_CHARS,
            "tiktok_max_chars": TIKTOK_MAX_CHARS,
            "shopify_max_chars": SHOPIFY_MAX_CHARS,
        },
        "confirmed_facts_count": confirmed_count,
        "audience_context": _context_entry(audience),
        "angle_context": _context_entry(campaign_angle),
        "context_note": (
            "Audience and angle inputs are suggestions. They are never "
            "treated as confirmed product facts and are never rendered "
            "into variant text."
        ),
        "independently_exportable": False,
        "exportable": False,
        "requires_checker_binding": True,
        "checker_approval": None,
        "receipt_id": None,
        "approval_note": APPROVAL_NOTE,
    }


def _ad_policy_fields(text, subject=None):
    """Deterministic ad policy lint for one rendered variant.

    Lints the rendered variant text, plus the subject for email
    variants. Returns (passed, hits) where passed is True when
    lint finds no hits and hits is the sorted list of hit dicts.
    Never raises on content; lint failures yield no hits.
    """
    combined = text if isinstance(text, str) else ""
    if isinstance(subject, str) and subject.strip():
        combined = (combined + " " + subject).strip() if combined else subject
    try:
        hits = lint_ad_policy(combined)
    except Exception:
        hits = []
    if not isinstance(hits, list):
        hits = []
    hits = [dict(hit) for hit in hits if isinstance(hit, dict)]
    return len(hits) == 0, hits


def _needs_revision(channel, confirmed_count, audience, campaign_angle, reason):
    metadata = _base_metadata(channel, confirmed_count, audience, campaign_angle)
    passed, hits = _ad_policy_fields(
        "", EMAIL_SUBJECT if channel == "email" else None
    )
    metadata.update(
        {
            "char_count": 0,
            "kept_sentences": 0,
            "total_sentences": 0,
            "omitted_sentences": 0,
            "content_valid": False,
            "exportable": False,
            "independently_exportable": False,
            "status": STATUS_NEEDS_REVISION,
            "ad_policy_passed": passed,
            "ad_policy_hits": [dict(hit) for hit in hits],
        }
    )
    variant = {
        "channel": channel,
        "variant_kind": VARIANT_KIND,
        "text": "",
        "content_valid": False,
        "exportable": False,
        "independently_exportable": False,
        "requires_checker_binding": True,
        "checker_approval": None,
        "receipt_id": None,
        "approval_note": APPROVAL_NOTE,
        "status": STATUS_NEEDS_REVISION,
        "reason": reason,
        "trim_note": None,
        "ad_policy_passed": passed,
        "ad_policy_hits": hits,
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


def _candidate_success(channel, text, kept_count, total, omitted, char_count,
                       variant_tokens, unconfirmed, confirmed_count,
                       audience, campaign_angle, trim_note, extra=None):
    subject = None
    if isinstance(extra, dict) and isinstance(extra.get("subject"), str):
        subject = extra["subject"]
    passed, hits = _ad_policy_fields(text, subject)
    metadata = _base_metadata(channel, confirmed_count, audience, campaign_angle)
    metadata.update(
        {
            "char_count": char_count,
            "kept_sentences": kept_count,
            "total_sentences": total,
            "omitted_sentences": omitted,
            "measured_claims": list(variant_tokens),
            "unconfirmed_measured_claims": list(unconfirmed),
            "content_valid": True,
            "exportable": False,
            "independently_exportable": False,
            "status": STATUS_CANDIDATE,
            "ad_policy_passed": passed,
            "ad_policy_hits": [dict(hit) for hit in hits],
        }
    )
    variant = {
        "channel": channel,
        "variant_kind": VARIANT_KIND,
        "text": text,
        "content_valid": True,
        "exportable": False,
        "independently_exportable": False,
        "requires_checker_binding": True,
        "checker_approval": None,
        "receipt_id": None,
        "approval_note": APPROVAL_NOTE,
        "status": STATUS_CANDIDATE,
        "reason": None,
        "trim_note": trim_note,
        "ad_policy_passed": passed,
        "ad_policy_hits": hits,
        "metadata": metadata,
    }
    if extra:
        variant.update(extra)
    return variant


def build_x_variant(draft_text, confirmed_facts, audience=None, campaign_angle=None):
    """Build the X presentation candidate, at most 280 characters.

    Keeps leading whole sentences that fit. Drops whole trailing
    sentences with a trim note when needed. Refuses with a
    non-exportable needs-revision result when the first sentence alone
    exceeds the limit, when no sentence exists, when a sentence
    boundary is an abbreviation fragment, or when the kept text
    contains price, percent, or size tokens absent from confirmed
    facts. Never emits a shortened fragment and never exports
    unconfirmed measurable claims. Success is a presentation
    candidate requiring downstream current approved Checker/receipt
    binding; never independently exportable.
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
    return _candidate_success(
        "x", text, kept_count, total, omitted, char_count,
        variant_tokens, unconfirmed, len(confirmed),
        audience, campaign_angle, trim_note,
    )


def build_linkedin_variant(draft_text, confirmed_facts, audience=None, campaign_angle=None):
    """Build the LinkedIn presentation candidate with all sentences verbatim.

    Fails closed with a non-exportable needs-revision result when the
    rendered text contains price, percent, or size tokens absent from
    confirmed facts, or when a sentence boundary is ambiguous.
    Success is a presentation candidate requiring downstream current
    approved Checker/receipt binding; never independently exportable.
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
    return _candidate_success(
        "linkedin", text, len(sentences), len(sentences), 0, len(text),
        variant_tokens, unconfirmed, len(confirmed),
        audience, campaign_angle, None,
    )


def build_instagram_variant(draft_text, confirmed_facts, audience=None, campaign_angle=None):
    """Build the Instagram presentation candidate with all sentences verbatim.

    Fails closed with a non-exportable needs-revision result when the
    rendered text contains price, percent, or size tokens absent from
    confirmed facts, or when a sentence boundary is ambiguous.
    Success is a presentation candidate requiring downstream current
    approved Checker/receipt binding; never independently exportable.
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
    return _candidate_success(
        "instagram", text, len(sentences), len(sentences), 0, len(text),
        variant_tokens, unconfirmed, len(confirmed),
        audience, campaign_angle, None,
    )


def build_email_variant(draft_text, confirmed_facts, audience=None, campaign_angle=None):
    """Build the email presentation candidate with a fixed subject and verbatim body.

    Fails closed with a non-exportable needs-revision result when the
    rendered body contains price, percent, or size tokens absent from
    confirmed facts, or when a sentence boundary is ambiguous.
    Success is a presentation candidate requiring downstream current
    approved Checker/receipt binding; never independently exportable.
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
    return _candidate_success(
        "email", body, len(sentences), len(sentences), 0, len(body),
        variant_tokens, unconfirmed, len(confirmed),
        audience, campaign_angle, None,
        extra={"subject": EMAIL_SUBJECT, "body": body},
    )


def build_facebook_variant(draft_text, confirmed_facts, audience=None, campaign_angle=None):
    """Build the Facebook presentation candidate, at most 2000 characters.

    FACEBOOK_MAX_CHARS is an explicit conservative bound, well under
    the platform maximum, chosen so long drafts still trim. Keeps
    leading whole sentences joined with blank lines. Drops whole
    trailing sentences with a trim note when needed. Refuses with a
    non-exportable needs-revision result when the first sentence alone
    exceeds the limit, when no sentence exists, when a sentence
    boundary is an abbreviation fragment, or when the kept text
    contains price, percent, or size tokens absent from confirmed
    facts. Never emits a shortened fragment and never exports
    unconfirmed measurable claims. Success is a presentation
    candidate requiring downstream current approved Checker/receipt
    binding; never independently exportable.
    """
    if not isinstance(draft_text, str):
        raise TypeError("draft_text must be a string")
    confirmed = _confirmed_list(confirmed_facts)
    sentences = split_sentences(draft_text)
    if not sentences:
        return _needs_revision(
            "facebook",
            len(confirmed),
            audience,
            campaign_angle,
            "No sentences found in draft text. Needs revision.",
        )
    first_len = len(sentences[0])
    if first_len > FACEBOOK_MAX_CHARS:
        return _needs_revision(
            "facebook",
            len(confirmed),
            audience,
            campaign_angle,
            "Non-exportable: first sentence is %d characters, over the "
            "%d character Facebook limit. Needs revision with a shorter "
            "opening sentence. No fragment was exported."
            % (first_len, FACEBOOK_MAX_CHARS),
        )
    fragment = _abbreviation_fragment(sentences)
    if fragment is not None:
        return _needs_revision_with_claims(
            "facebook",
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
        candidate = sentence if not kept else "\n\n".join(kept + [sentence])
        if len(candidate) <= FACEBOOK_MAX_CHARS:
            kept.append(sentence)
        else:
            break
    text = "\n\n".join(kept)
    char_count = len(text)
    total = len(sentences)
    kept_count = len(kept)
    omitted = total - kept_count
    if kept and _looks_like_abbreviation_fragment(kept[-1]):
        return _needs_revision_with_claims(
            "facebook",
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
            "facebook",
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
            "Trimmed to %d of %d sentences (%d/%d chars) on a full "
            "sentence boundary; %d trailing sentence(s) omitted; no "
            "sentence shortened."
            % (kept_count, total, char_count, FACEBOOK_MAX_CHARS, omitted)
        )
    else:
        trim_note = None
    return _candidate_success(
        "facebook", text, kept_count, total, omitted, char_count,
        variant_tokens, unconfirmed, len(confirmed),
        audience, campaign_angle, trim_note,
    )


def build_tiktok_variant(draft_text, confirmed_facts, audience=None, campaign_angle=None):
    """Build the TikTok/Reels script presentation candidate.

    Fixed non-factual script framing wraps verbatim draft sentences:
    TIKTOK_HEADER on the first line, one verbatim sentence per line
    in the body, and TIKTOK_CLOSER on the last line. Keeps all whole
    sentences with no rewording. Refuses with a non-exportable
    needs-revision result when no sentence exists, when a sentence
    boundary is an abbreviation fragment, when the framed script
    exceeds TIKTOK_MAX_CHARS, or when the rendered text contains
    price, percent, or size tokens absent from confirmed facts.
    Success is a presentation candidate requiring downstream current
    approved Checker/receipt binding; never independently exportable.
    """
    if not isinstance(draft_text, str):
        raise TypeError("draft_text must be a string")
    confirmed = _confirmed_list(confirmed_facts)
    sentences = split_sentences(draft_text)
    if not sentences:
        return _needs_revision(
            "tiktok",
            len(confirmed),
            audience,
            campaign_angle,
            "No sentences found in draft text. Needs revision.",
        )
    fragment = _abbreviation_fragment(sentences)
    if fragment is not None:
        return _needs_revision_with_claims(
            "tiktok",
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
    text = TIKTOK_HEADER + "\n" + "\n".join(sentences) + "\n" + TIKTOK_CLOSER
    if len(text) > TIKTOK_MAX_CHARS:
        return _needs_revision_with_claims(
            "tiktok",
            len(confirmed),
            audience,
            campaign_angle,
            "Non-exportable: framed script is %d characters, over the "
            "%d character TikTok limit. Needs revision with fewer or "
            "shorter sentences. No fragment was exported."
            % (len(text), TIKTOK_MAX_CHARS),
            [],
            [],
            len(sentences),
        )
    variant_tokens, unconfirmed = _split_measured(text, confirmed)
    if unconfirmed:
        return _needs_revision_with_claims(
            "tiktok",
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
    return _candidate_success(
        "tiktok", text, len(sentences), len(sentences), 0, len(text),
        variant_tokens, unconfirmed, len(confirmed),
        audience, campaign_angle, None,
    )


def build_shopify_variant(draft_text, confirmed_facts, audience=None, campaign_angle=None):
    """Build the Shopify PDP bullet presentation candidate.

    Formats each verbatim draft sentence as one scannable bullet
    ("- " + sentence), one bullet per line. Confirmed facts gate
    measured claims and are never rendered. Keeps all whole
    sentences with no rewording. Refuses with a non-exportable
    needs-revision result when no sentence exists, when a sentence
    boundary is an abbreviation fragment, when the bullet list
    exceeds SHOPIFY_MAX_CHARS, or when the rendered text contains
    price, percent, or size tokens absent from confirmed facts.
    Success is a presentation candidate requiring downstream current
    approved Checker/receipt binding; never independently exportable.
    """
    if not isinstance(draft_text, str):
        raise TypeError("draft_text must be a string")
    confirmed = _confirmed_list(confirmed_facts)
    sentences = split_sentences(draft_text)
    if not sentences:
        return _needs_revision(
            "shopify",
            len(confirmed),
            audience,
            campaign_angle,
            "No sentences found in draft text. Needs revision.",
        )
    fragment = _abbreviation_fragment(sentences)
    if fragment is not None:
        return _needs_revision_with_claims(
            "shopify",
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
    text = "\n".join("- " + sentence for sentence in sentences)
    if len(text) > SHOPIFY_MAX_CHARS:
        return _needs_revision_with_claims(
            "shopify",
            len(confirmed),
            audience,
            campaign_angle,
            "Non-exportable: bullet list is %d characters, over the "
            "%d character Shopify limit. Needs revision with fewer or "
            "shorter sentences. No fragment was exported."
            % (len(text), SHOPIFY_MAX_CHARS),
            [],
            [],
            len(sentences),
        )
    variant_tokens, unconfirmed = _split_measured(text, confirmed)
    if unconfirmed:
        return _needs_revision_with_claims(
            "shopify",
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
    return _candidate_success(
        "shopify", text, len(sentences), len(sentences), 0, len(text),
        variant_tokens, unconfirmed, len(confirmed),
        audience, campaign_angle, None,
    )


def _voice_block_for_candidate(text, voice_snapshot, voice_ref):
    if not isinstance(voice_snapshot, dict):
        return None
    terms = voice_snapshot.get('banned_terms')
    if not isinstance(terms, list) or not terms:
        return None
    if not isinstance(text, str) or not text.strip():
        return None
    try:
        from .voice_profile import voice_single_block_for_text
        return voice_single_block_for_text(voice_snapshot, text, voice_ref)
    except (TypeError, ValueError):
        return None


def _apply_voice_to_variant(variant, voice_snapshot, voice_ref, confirmed_count, audience, campaign_angle):
    if not isinstance(variant, dict) or variant.get('status') != STATUS_CANDIDATE:
        return variant
    texts = []
    main = variant.get('text')
    if isinstance(main, str) and main.strip():
        texts.append(main)
    subject = variant.get('subject')
    if isinstance(subject, str) and subject.strip():
        texts.append(subject)
    for text in texts:
        hit = _voice_block_for_candidate(text, voice_snapshot, voice_ref)
        if hit is not None:
            reason = (hit['reason'] + '. Needs revision without the banned term. '
                      'No text exported.')
            total = len(split_sentences(main)) if isinstance(main, str) else 0
            blocked = _needs_revision(variant.get('channel', 'x'), confirmed_count,
                                      audience, campaign_angle, reason)
            blocked['metadata']['total_sentences'] = total
            blocked['metadata']['omitted_sentences'] = total
            blocked['metadata']['voice_blocked'] = True
            blocked['metadata']['voice_reason'] = hit['reason']
            if variant.get('channel') == 'email':
                blocked['subject'] = EMAIL_SUBJECT
                blocked['body'] = ''
            return blocked
    variant = copy.deepcopy(variant)
    variant.setdefault('metadata', {})['voice_blocked'] = False
    return variant


def build_channel_variants(draft_text, confirmed_facts, audience=None, campaign_angle=None, voice_snapshot=None, voice_ref=None):
    """Build all five presentation candidates plus provenance.

    Candidate text comes only from verbatim draft sentences plus fixed
    non-factual framing. Audience and campaign angle inputs are kept in
    metadata as suggestions and never rendered as facts. Every
    candidate requires downstream current approved Checker/receipt
    binding; none is independently exportable. When a voice snapshot is
    supplied, candidates containing banned terms refuse with a concrete
    voice reason and needs-revision status.
    """
    confirmed_copy = _confirmed_list(confirmed_facts)
    variants = {
        "x": build_x_variant(draft_text, confirmed_copy, audience, campaign_angle),
        "linkedin": build_linkedin_variant(draft_text, confirmed_copy, audience, campaign_angle),
        "instagram": build_instagram_variant(draft_text, confirmed_copy, audience, campaign_angle),
        "email": build_email_variant(draft_text, confirmed_copy, audience, campaign_angle),
        "facebook": build_facebook_variant(draft_text, confirmed_copy, audience, campaign_angle),
    }
    if isinstance(voice_snapshot, dict) and isinstance(voice_snapshot.get('banned_terms'), list) and voice_snapshot.get('banned_terms'):
        for channel in list(variants.keys()):
            variants[channel] = _apply_voice_to_variant(
                variants[channel], voice_snapshot, voice_ref,
                len(confirmed_copy), audience, campaign_angle)
    voice_info = None
    if isinstance(voice_snapshot, dict) and isinstance(voice_snapshot.get('banned_terms'), list) and voice_snapshot.get('banned_terms'):
        ref = voice_ref if isinstance(voice_ref, dict) else {}
        voice_info = {'title': ref.get('title'), 'version': ref.get('version'),
                      'banned_term_count': len(voice_snapshot.get('banned_terms', []))}
    provenance = {
        "module": MODULE_VERSION,
        "source": SOURCE_LABEL,
        "source_note": SOURCE_NOTE,
        "bundle_kind": BUNDLE_KIND,
        "variant_kind": VARIANT_KIND,
        "channels": list(CHANNELS),
        "confirmed_facts_count": len(confirmed_copy),
        "audience_context": _context_entry(audience),
        "angle_context": _context_entry(campaign_angle),
        "limits": {
            "x_max_chars": X_MAX_CHARS,
            "facebook_max_chars": FACEBOOK_MAX_CHARS,
            "tiktok_max_chars": TIKTOK_MAX_CHARS,
            "shopify_max_chars": SHOPIFY_MAX_CHARS,
        },
        "independently_exportable": False,
        "exportable": False,
        "requires_checker_binding": True,
        "checker_approval": None,
        "receipt_id": None,
        "approval_note": APPROVAL_NOTE,
        "voice": voice_info,
        "note": (
            "Presentation candidates only; not independently exportable. "
            "No new factual assertions. Audience and angle are "
            "suggestions, not verified facts. Price, material, contents, "
            "and size wording is copied verbatim or the candidate "
            "refuses. No Checker approval or receipt binding claimed. "
            "Requires downstream current approved Checker/receipt "
            "binding before any export."
        ),
    }
    return {
        "x": variants["x"],
        "linkedin": variants["linkedin"],
        "instagram": variants["instagram"],
        "email": variants["email"],
        "facebook": variants["facebook"],
        "provenance": provenance,
    }


def build_launch_matrix(draft_text, confirmed_facts, audience=None, campaign_angle=None, voice_snapshot=None, voice_ref=None):
    """Build all seven launch matrix presentation candidates plus provenance.

    Covers LAUNCH_MATRIX_CHANNELS (x, linkedin, instagram, email,
    facebook, tiktok, shopify). Candidate text comes only from
    verbatim draft sentences plus fixed non-factual framing. Audience
    and campaign angle inputs are kept in metadata as suggestions
    and never rendered as facts. Every candidate requires
    downstream current approved Checker/receipt binding; none is
    independently exportable. When a voice snapshot is supplied,
    candidates containing banned terms refuse with a concrete voice
    reason and needs-revision status.
    """
    confirmed_copy = _confirmed_list(confirmed_facts)
    builders = {
        "x": build_x_variant,
        "linkedin": build_linkedin_variant,
        "instagram": build_instagram_variant,
        "email": build_email_variant,
        "facebook": build_facebook_variant,
        "tiktok": build_tiktok_variant,
        "shopify": build_shopify_variant,
    }
    variants = {
        channel: builders[channel](draft_text, confirmed_copy, audience, campaign_angle)
        for channel in LAUNCH_MATRIX_CHANNELS
    }
    if isinstance(voice_snapshot, dict) and isinstance(voice_snapshot.get('banned_terms'), list) and voice_snapshot.get('banned_terms'):
        for channel in list(variants.keys()):
            variants[channel] = _apply_voice_to_variant(
                variants[channel], voice_snapshot, voice_ref,
                len(confirmed_copy), audience, campaign_angle)
    voice_info = None
    if isinstance(voice_snapshot, dict) and isinstance(voice_snapshot.get('banned_terms'), list) and voice_snapshot.get('banned_terms'):
        ref = voice_ref if isinstance(voice_ref, dict) else {}
        voice_info = {'title': ref.get('title'), 'version': ref.get('version'),
                      'banned_term_count': len(voice_snapshot.get('banned_terms', []))}
    provenance = {
        "module": MODULE_VERSION,
        "source": SOURCE_LABEL,
        "source_note": SOURCE_NOTE,
        "bundle_kind": BUNDLE_KIND,
        "variant_kind": VARIANT_KIND,
        "matrix": True,
        "channels": list(LAUNCH_MATRIX_CHANNELS),
        "matrix_channels": list(LAUNCH_MATRIX_CHANNELS),
        "confirmed_facts_count": len(confirmed_copy),
        "audience_context": _context_entry(audience),
        "angle_context": _context_entry(campaign_angle),
        "limits": {
            "x_max_chars": X_MAX_CHARS,
            "facebook_max_chars": FACEBOOK_MAX_CHARS,
            "tiktok_max_chars": TIKTOK_MAX_CHARS,
            "shopify_max_chars": SHOPIFY_MAX_CHARS,
        },
        "independently_exportable": False,
        "exportable": False,
        "requires_checker_binding": True,
        "checker_approval": None,
        "receipt_id": None,
        "approval_note": APPROVAL_NOTE,
        "voice": voice_info,
        "note": (
            "Launch matrix presentation candidates only; not "
            "independently exportable. Covers all seven launch "
            "channels in one call. No new factual assertions. "
            "Audience and angle are suggestions, not verified "
            "facts. Price, material, contents, and size wording is "
            "copied verbatim or the candidate refuses. No Checker "
            "approval or receipt binding claimed. Requires "
            "downstream current approved Checker/receipt binding "
            "before any export."
        ),
    }
    result = {channel: variants[channel] for channel in LAUNCH_MATRIX_CHANNELS}
    result["provenance"] = provenance
    return result


CHECKED_BUNDLE_VERSION = "checked-channel-variants/v1"
CHECKED_LAUNCH_MATRIX_VERSION = "checked-launch-matrix/v1"
CHECKED_DRAFT_SOURCE = "current post draft"
CHECKED_NO_PUBLISH_NOTE = (
    "Checked export candidates only. No auto-publish, no auto-post, "
    "no auto-send, no scheduling, and no campaign angles. Copy for "
    "offline use only after this human approval, through the copy "
    "action that rechecks the exact text against the current "
    "revision, facts, and binding. Every candidate derives verbatim "
    "from the current approved post draft and the confirmed claims "
    "bound to that approval."
)
COPY_NOTE = (
    "Copy authorized for offline use only at the stated revision "
    "and approval binding, for the stated human-approved exact "
    "text. No auto-publish, no auto-post, no auto-send. The exact "
    "text below passed deterministic checks against the current "
    "approved draft and confirmed claims, and a human approved "
    "that exact text at the stated revision."
)
VARIANT_APPROVAL_VERSION = "channel-variant-approval/v1"


def _checked_confirmed_claims(receipt):
    """Confirmed claim strings bound on this receipt, in stored order."""
    product = receipt.get('product_facts') if isinstance(receipt, dict) else None
    if not isinstance(product, dict):
        raise ValueError(
            'Checked channel variants require product facts on the receipt')
    raw = product.get('confirmed_claims')
    if not isinstance(raw, list) or not raw:
        raise ValueError(
            'Checked channel variants require a nonempty confirmed-claims list')
    cleaned = []
    for entry in raw:
        if not isinstance(entry, str) or not entry.strip():
            raise ValueError('Confirmed claims must be nonempty strings')
        cleaned.append(entry)
    return cleaned


def _checked_voice(receipt):
    """Voice snapshot and ref from the receipt, or (None, None)."""
    raw = receipt.get('voice_profile') if isinstance(receipt, dict) else None
    if not isinstance(raw, dict):
        return None, None
    terms = raw.get('banned_terms')
    if not isinstance(terms, list) or not terms:
        return None, None
    cleaned = [term for term in terms if isinstance(term, str) and term.strip()]
    if not cleaned:
        return None, None
    snapshot = {'banned_terms': cleaned}
    ref = {'id': raw.get('id'), 'title': raw.get('title'),
           'version': raw.get('version')}
    return snapshot, ref


def _checked_variant_entry(variant):
    """API-ready variant dict with sentence counts promoted to top level."""
    metadata = variant.get('metadata') if isinstance(variant, dict) else None
    if not isinstance(metadata, dict):
        metadata = {}

    def _count(key):
        value = metadata.get(key)
        return value if isinstance(value, int) and value >= 0 else 0

    text = variant.get('text')
    subject = variant.get('subject')
    reason = variant.get('reason')
    trim_note = variant.get('trim_note')
    approval_note = variant.get('approval_note')
    passed = variant.get('ad_policy_passed')
    hits = variant.get('ad_policy_hits')
    if not isinstance(passed, bool) or not isinstance(hits, list):
        passed = metadata.get('ad_policy_passed')
        hits = metadata.get('ad_policy_hits')
    if not isinstance(passed, bool) or not isinstance(hits, list):
        passed, hits = _ad_policy_fields(
            text if isinstance(text, str) else '',
            subject if isinstance(subject, str) else None,
        )
    hits = [dict(hit) for hit in hits if isinstance(hit, dict)]
    passed = passed if isinstance(passed, bool) else len(hits) == 0
    return {
        'channel': variant.get('channel', ''),
        'variant_kind': variant.get('variant_kind', VARIANT_KIND),
        'text': text if isinstance(text, str) else '',
        'subject': subject if isinstance(subject, str) else '',
        'content_valid': bool(variant.get('content_valid')),
        'exportable': False,
        'independently_exportable': False,
        'requires_checker_binding': True,
        'status': variant.get('status', ''),
        'reason': reason if isinstance(reason, str) else '',
        'trim_note': trim_note if isinstance(trim_note, str) else '',
        'char_count': _count('char_count'),
        'kept_sentences': _count('kept_sentences'),
        'total_sentences': _count('total_sentences'),
        'omitted_sentences': _count('omitted_sentences'),
        'approval_note': approval_note if isinstance(approval_note, str) else APPROVAL_NOTE,
        'ad_policy_passed': passed,
        'ad_policy_hits': hits,
    }


def _require_checked_gate(receipt):
    """Shared exportable gate for variant reads and copy actions.

    Requires a completed receipt with human approval for export on
    the latest revision, a clean final check, and a matching current
    approval binding. Raises ValueError with a fail-closed reason
    otherwise. Messages stay stable for API status mapping.
    """
    from .human_review import binding_status, exportable
    if not isinstance(receipt, dict):
        raise ValueError('Receipt unavailable for checked channel variants')
    if receipt.get('status') == 'running':
        raise ValueError(
            'Run is still running; checked variants unlock with the final receipt')
    if receipt.get('status') == 'failed':
        raise ValueError('Failed runs have no checked channel variants')
    if receipt.get('approval_state') != 'approved_for_export':
        raise ValueError(
            'Checked channel variants require human approval of the latest '
            'revision; nothing is published automatically')
    if not exportable(receipt):
        bound, reason = binding_status(receipt)
        if not bound:
            raise ValueError('Checked channel variants refused: ' + reason)
        raise ValueError(
            'Checked channel variants require approval of the latest '
            'revision and a clean final check')


def _strip_framing(channel, text):
    """Remove fixed non-factual framing, or return None when malformed."""
    if channel == 'linkedin':
        prefix = LINKEDIN_HEADER + '\n\n'
        if not text.startswith(prefix):
            return None
        return text[len(prefix):]
    if channel == 'instagram':
        suffix = '\n\n' + INSTAGRAM_CLOSER
        if not text.endswith(suffix):
            return None
        return text[:-len(suffix)]
    if channel == 'email':
        prefix = EMAIL_GREETING + '\n\n'
        suffix = '\n\n' + EMAIL_CLOSER
        if not (text.startswith(prefix) and text.endswith(suffix)):
            return None
        return text[len(prefix):-len(suffix)]
    if channel == 'tiktok':
        prefix = TIKTOK_HEADER + '\n'
        suffix = '\n' + TIKTOK_CLOSER
        if not (text.startswith(prefix) and text.endswith(suffix)):
            return None
        return text[len(prefix):-len(suffix)]
    if channel == 'shopify':
        return text
    return text


def verify_exact_variant_text(channel, rendered_text, rendered_subject,
                              draft_post, confirmed_facts,
                              voice_snapshot=None, voice_ref=None):
    """Verify the exact rendered variant text, not just its draft.

    Checks the full rendered string including fixed framing: verbatim
    sentence equality against the approved post draft, exact
    measured-claim support from confirmed facts, channel character
    limits, and the receipt voice profile on the exact rendered text.
    No audience or campaign angle input is used. No new literal bans
    are introduced; voice matching stays the receipt's own
    context-aware profile. Returns (True, '') or (False, reason).
    """
    if channel not in LAUNCH_MATRIX_CHANNELS:
        return False, 'Unknown channel.'
    if not isinstance(rendered_text, str) or not rendered_text.strip():
        return False, 'No variant text to verify.'
    if not isinstance(draft_post, str) or not draft_post.strip():
        return False, 'Approved post draft unavailable.'
    try:
        confirmed = _confirmed_list(confirmed_facts)
    except (TypeError, ValueError):
        return False, 'Confirmed facts unavailable.'
    if channel == 'email':
        if rendered_subject != EMAIL_SUBJECT:
            return False, 'Email subject is not the fixed subject.'
    elif isinstance(rendered_subject, str) and rendered_subject != '':
        return False, 'Unexpected subject on a non-email variant.'
    core = _strip_framing(channel, rendered_text)
    if core is None:
        return False, 'Variant framing is not the fixed framing.'
    try:
        draft_sentences = split_sentences(draft_post)
    except TypeError:
        return False, 'Approved post draft unavailable.'
    if channel in ('x', 'facebook'):
        limit = X_MAX_CHARS if channel == 'x' else FACEBOOK_MAX_CHARS
        check = (validate_x_variant(rendered_text, confirmed, draft_post)
                 if channel == 'x'
                 else validate_facebook_variant(rendered_text, confirmed, draft_post))
        if not check.get('ok'):
            return False, 'Variant text is not the exact leading draft prefix within limits.'
        if len(rendered_text) > limit:
            return False, 'Variant text exceeds the channel limit.'
    elif channel == 'tiktok':
        if len(rendered_text) > TIKTOK_MAX_CHARS:
            return False, 'Variant text exceeds the channel limit.'
        try:
            core_sentences = split_sentences(core)
        except TypeError:
            return False, 'Variant text has no verifiable sentences.'
        if core_sentences != draft_sentences:
            return False, ('Variant sentences are not the exact approved '
                           'draft sentences in order.')
    elif channel == 'shopify':
        if len(rendered_text) > SHOPIFY_MAX_CHARS:
            return False, 'Variant text exceeds the channel limit.'
        lines = [line for line in core.splitlines() if line.strip()]
        core_sentences = []
        for line in lines:
            if not line.startswith('- '):
                return False, 'Variant framing is not the fixed framing.'
            core_sentences.append(line[2:])
        if core_sentences != draft_sentences:
            return False, ('Variant sentences are not the exact approved '
                           'draft sentences in order.')
    else:
        try:
            core_sentences = split_sentences(core)
        except TypeError:
            return False, 'Variant text has no verifiable sentences.'
        if core_sentences != draft_sentences:
            return False, ('Variant sentences are not the exact approved '
                           'draft sentences in order.')
    confirmed_tokens = _confirmed_token_set(confirmed)
    variant_tokens = _measured_tokens(rendered_text)
    if channel == 'email' and isinstance(rendered_subject, str):
        variant_tokens = variant_tokens + _measured_tokens(rendered_subject)
    unconfirmed = sorted({t for t in variant_tokens if t not in confirmed_tokens})
    if unconfirmed:
        return False, ('Measured claims not in confirmed facts: '
                       + ', '.join(unconfirmed) + '.')
    if isinstance(voice_snapshot, dict):
        terms = voice_snapshot.get('banned_terms')
        if isinstance(terms, list) and terms:
            try:
                from .voice_profile import voice_single_block_for_text
                hit = voice_single_block_for_text(
                    voice_snapshot, rendered_text, voice_ref)
                if hit is not None:
                    return False, hit.get('reason') or 'Blocked by voice profile.'
                if channel == 'email' and isinstance(rendered_subject, str):
                    subject_hit = voice_single_block_for_text(
                        voice_snapshot, rendered_subject, voice_ref)
                    if subject_hit is not None:
                        return False, (subject_hit.get('reason')
                                       or 'Blocked by voice profile.')
            except (TypeError, ValueError):
                return False, 'Voice profile cannot be applied.'
    return True, ''


def _entry_approval_current(channel, entry, record, current, pack_digest):
    """Pure currentness check of one stored variant approval.

    Compares the stored record against the freshly derived entry,
    revision, and pack binding digest. Never raises; fails closed
    with a reason.
    """
    if not isinstance(record, dict):
        return None, False, ('No human approval of this exact channel '
                             'text at the current revision.')
    if not isinstance(entry, dict):
        return record, False, 'Variant entry unavailable.'
    if record.get('revision') != current:
        return record, False, ('Variant approval is stale; the pack '
                               'changed since approval.')
    if record.get('pack_binding_digest') != pack_digest:
        return record, False, ('Variant approval is stale; facts, copy, '
                               'policy, voice, photo, or check changed '
                               'since approval.')
    if not entry.get('content_valid') or not entry.get('text'):
        return record, False, ('Variant approval is stale; the exact text '
                               'no longer verifies.')
    if entry.get('text') != record.get('text') or entry.get('subject') != record.get('subject'):
        return record, False, ('Variant approval is stale; the exact text '
                               'differs from the approved text.')
    try:
        expected = variant_approval_digest(
            channel, entry['text'], entry['subject'],
            current, pack_digest)
    except ValueError:
        return record, False, 'Variant approval cannot be recomputed.'
    if record.get('variant_digest') != expected:
        return record, False, ('Variant approval digest mismatch; '
                               'reapprove this exact text.')
    if record.get('approval_version') != VARIANT_APPROVAL_VERSION:
        return record, False, ('Variant approval version mismatch; '
                               'reapprove this exact text.')
    return record, True, ''


def channel_approval_status(receipt, channel):
    """Check the stored human approval of one exact channel text.

    Returns (record_or_None, current_bool, reason). Current only when
    a stored approval names this channel with the current revision,
    the current pack binding digest, and a variant digest that matches
    the freshly derived exact text and subject. Anything else fails
    closed with a reason naming stale approval or mismatch. Never
    raises on content; malformed receipts fail closed as not current.
    """
    if channel not in CHANNELS:
        return None, False, 'Unknown channel.'
    if not isinstance(receipt, dict):
        return None, False, 'Receipt unavailable.'
    try:
        from .human_review import approval_binding, current_revision
        current = current_revision(receipt)
        binding = approval_binding(receipt)
    except Exception:
        return None, False, ('Pack approval binding unavailable; '
                             'reapprove the pack first.')
    try:
        bundle = _build_checked_bundle(receipt)
    except ValueError as error:
        record = _stored_variant_approvals(receipt).get(channel)
        return record if isinstance(record, dict) else None, False, (
            str(error) or 'Variant approval check failed.')
    except Exception:
        return None, False, 'Variant approval check failed.'
    record = _stored_variant_approvals(receipt).get(channel)
    return _entry_approval_current(channel, bundle[channel], record,
                                   current, binding['digest'])


def _build_checked_bundle(receipt):
    """Build the checked bundle and per-channel entries; no approval echo."""
    from .human_review import (approval_binding, current_draft,
                               current_revision)
    _require_checked_gate(receipt)
    confirmed = _checked_confirmed_claims(receipt)
    draft = current_draft(receipt)
    post = draft.get('post')
    if not isinstance(post, str) or not post.strip():
        raise ValueError(
            'Checked channel variants require a nonempty approved post draft')
    voice_snapshot, voice_ref = _checked_voice(receipt)
    bundle = build_channel_variants(post, confirmed,
                                    voice_snapshot=voice_snapshot,
                                    voice_ref=voice_ref)
    product = receipt.get('product_facts')
    if not isinstance(product, dict):
        raise ValueError(
            'Checked channel variants require product facts on the receipt')
    binding = approval_binding(receipt)
    mode = product.get('mode')
    label = product.get('template_label')
    entries = {}
    for channel in CHANNELS:
        entry = _checked_variant_entry(bundle[channel])
        if entry['content_valid']:
            ok, reason = verify_exact_variant_text(
                channel, entry['text'], entry['subject'], post,
                confirmed, voice_snapshot, voice_ref)
            if not ok:
                entry = dict(entry)
                entry['content_valid'] = False
                entry['status'] = STATUS_NEEDS_REVISION
                entry['text'] = ''
                entry['reason'] = ('Copy refused: exact rendered text failed '
                                   're-verification: ' + reason)
                entry['trim_note'] = ''
                entry['char_count'] = 0
                entry['kept_sentences'] = 0
        entries[channel] = entry
    result = {
        'bundle_version': CHECKED_BUNDLE_VERSION,
        'receipt_id': receipt.get('run_id', ''),
        'revision': current_revision(receipt),
        'approval_state': receipt.get('approval_state', ''),
        'binding_version': binding['version'],
        'binding_digest': binding['digest'],
        'facts_mode': mode if isinstance(mode, str) else '',
        'facts_label': label if isinstance(label, str) else '',
        'template_used': bool(product.get('template_used')),
        'confirmed_claims_count': len(confirmed),
        'draft_source': CHECKED_DRAFT_SOURCE,
        'all_content_valid': all(entry['content_valid']
                                 for entry in entries.values()),
        'no_auto_publish': True,
        'note': CHECKED_NO_PUBLISH_NOTE,
    }
    result.update(entries)
    result['provenance'] = bundle['provenance']
    result['channel_approvals'] = {}
    return result


def checked_channel_variants(receipt):
    """Build checked channel export candidates for an approved receipt.

    Derives all five candidates verbatim from the current approved
    post draft and the receipt-bound confirmed claims. Refuses with
    ValueError unless the receipt is currently exportable: human
    approval for export on the latest revision, a clean final check,
    and a matching current approval binding. No audience or campaign
    angle input is used, so no angle is claimed. Voice banned terms
    from the receipt still veto with needs-revision status. Every
    rendered candidate is independently re-verified with
    verify_exact_variant_text; a verification failure downgrades that
    channel to needs-revision with no text. Every candidate stays non
    independently exportable with no auto-publish; copying the exact
    text additionally requires a current human approval of that exact
    text (see approve_channel_variant and authorize_channel_copy).
    The returned bundle echoes the binding digest and revision it was
    checked against, plus a per-channel approval summary.
    """
    from .human_review import approval_binding, current_revision
    result = _build_checked_bundle(receipt)
    binding = approval_binding(receipt)
    current = current_revision(receipt)
    approvals_echo = {}
    for channel in CHANNELS:
        record = _stored_variant_approvals(receipt).get(channel)
        if not isinstance(record, dict):
            continue
        _, current_ok, _ = _entry_approval_current(
            channel, result[channel], record, current, binding['digest'])
        approvals_echo[channel] = {
            'approved_by': record.get('approved_by'),
            'revision': record.get('revision'),
            'current': bool(current_ok),
        }
    result['channel_approvals'] = approvals_echo
    return result


def checked_launch_matrix(receipt):
    """Build checked launch matrix candidates for an approved receipt.

    Same gate as :func:`checked_channel_variants`: refuses with
    ValueError unless the receipt is currently exportable, meaning
    human approval for export on the latest revision with a clean
    final check and a matching current approval binding. Derives all
    seven presentation candidates (x, linkedin, instagram, email,
    facebook, tiktok, shopify) verbatim from the current approved
    post draft and the receipt-bound confirmed claims via
    :func:`build_launch_matrix`. No audience or campaign angle input
    is used, so no angle is claimed. Every rendered candidate is
    independently re-verified with :func:`verify_exact_variant_text`;
    a verification failure downgrades that channel to needs-revision
    with no text. Every candidate stays non independently exportable
    with no auto-publish. The returned bundle echoes the binding
    digest and revision it was checked against.
    """
    from .human_review import (approval_binding, current_draft,
                               current_revision)
    _require_checked_gate(receipt)
    confirmed = _checked_confirmed_claims(receipt)
    draft = current_draft(receipt)
    post = draft.get('post')
    if not isinstance(post, str) or not post.strip():
        raise ValueError(
            'Checked launch matrix requires a nonempty approved post draft')
    voice_snapshot, voice_ref = _checked_voice(receipt)
    matrix = build_launch_matrix(post, confirmed,
                                 voice_snapshot=voice_snapshot,
                                 voice_ref=voice_ref)
    product = receipt.get('product_facts')
    if not isinstance(product, dict):
        raise ValueError(
            'Checked launch matrix requires product facts on the receipt')
    binding = approval_binding(receipt)
    mode = product.get('mode')
    label = product.get('template_label')
    entries = {}
    for channel in LAUNCH_MATRIX_CHANNELS:
        entry = _checked_variant_entry(matrix[channel])
        if entry['content_valid']:
            ok, reason = verify_exact_variant_text(
                channel, entry['text'], entry['subject'], post,
                confirmed, voice_snapshot, voice_ref)
            if not ok:
                entry = dict(entry)
                entry['content_valid'] = False
                entry['status'] = STATUS_NEEDS_REVISION
                entry['text'] = ''
                entry['reason'] = ('Copy refused: exact rendered text failed '
                                   're-verification: ' + reason)
                entry['trim_note'] = ''
                entry['char_count'] = 0
                entry['kept_sentences'] = 0
        entries[channel] = entry
    result = {
        'bundle_version': CHECKED_LAUNCH_MATRIX_VERSION,
        'receipt_id': receipt.get('run_id', ''),
        'revision': current_revision(receipt),
        'approval_state': receipt.get('approval_state', ''),
        'binding_version': binding['version'],
        'binding_digest': binding['digest'],
        'facts_mode': mode if isinstance(mode, str) else '',
        'facts_label': label if isinstance(label, str) else '',
        'template_used': bool(product.get('template_used')),
        'confirmed_claims_count': len(confirmed),
        'draft_source': CHECKED_DRAFT_SOURCE,
        'all_content_valid': all(entry['content_valid']
                                 for entry in entries.values()),
        'no_auto_publish': True,
        'note': CHECKED_NO_PUBLISH_NOTE,
    }
    result.update(entries)
    result['provenance'] = matrix['provenance']
    result['channel_approvals'] = {}
    return result


def authorize_channel_copy(receipt, channel, expected_revision=None):
    """Authorize copying the exact text of one channel variant.

    Re-reads the gate at action time: the receipt must be currently
    exportable with a matching current approval binding, and
    expected_revision must match the current revision (a concurrent
    revision change refuses with a stale error). Requires a current
    human approval of this exact channel text and subject at the
    current revision and pack binding digest. Rebuilds the bundle
    from the current approved draft and confirmed claims, then
    re-verifies the exact rendered text of the requested channel with
    verify_exact_variant_text, including equality with the approved
    text. Fails closed with ValueError on any mismatch; the returned
    record carries the exact text plus the revision, approver, and
    binding digest it was authorized against. The candidate itself
    stays non independently exportable: only this record authorizes
    the copy.
    """
    from .human_review import approval_binding, current_revision
    if channel not in CHANNELS:
        raise ValueError('Unknown channel.')
    if not isinstance(receipt, dict):
        raise ValueError('Receipt unavailable for checked channel variants')
    current = current_revision(receipt)
    if expected_revision is None:
        if current > 0:
            raise ValueError(
                'Copy is stale; expected_revision is required for edited revisions')
    else:
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int):
            raise ValueError('expected_revision must be an integer')
        if expected_revision != current:
            raise ValueError('Copy is stale; the draft changed')
    _require_checked_gate(receipt)
    approval, current_ok, status_reason = channel_approval_status(receipt, channel)
    if not current_ok:
        raise ValueError('Copy requires human approval of this exact channel text '
                         'at the current revision'
                         + (': ' + status_reason if status_reason else ''))
    bundle = checked_channel_variants(receipt)
    entry = bundle[channel]
    if not entry['content_valid'] or not entry['text']:
        reason = entry.get('reason') or 'needs revision'
        raise ValueError('Copy refused: ' + reason)
    if entry['text'] != approval.get('text') or entry['subject'] != approval.get('subject'):
        raise ValueError('Copy refused: exact text differs from the approved text.')
    post = bundle_post_text(receipt)
    confirmed = _checked_confirmed_claims(receipt)
    voice_snapshot, voice_ref = _checked_voice(receipt)
    ok, reason = verify_exact_variant_text(
        channel, entry['text'], entry['subject'], post,
        confirmed, voice_snapshot, voice_ref)
    if not ok:
        raise ValueError('Copy refused: ' + reason)
    binding = approval_binding(receipt)
    return {
        'channel': channel,
        'text': entry['text'],
        'subject': entry['subject'],
        'revision': current,
        'receipt_id': receipt.get('run_id', ''),
        'binding_version': binding['version'],
        'binding_digest': binding['digest'],
        'approved_by': approval.get('approved_by'),
        'copy_authorized': True,
        'note': COPY_NOTE,
    }


def bundle_post_text(receipt):
    """Current approved post draft text, or '' when unavailable."""
    try:
        from .human_review import current_draft
        draft = current_draft(receipt)
    except Exception:
        return ''
    post = draft.get('post') if isinstance(draft, dict) else None
    return post if isinstance(post, str) else ''


def variant_approval_digest(channel, text, subject, revision, pack_digest):
    """Deterministic digest binding the exact approved variant text.

    Covers the channel, the exact rendered text and subject, the
    receipt revision, and the current pack approval binding digest
    (which itself covers revision, owner-confirmed facts, policy,
    voice, photo, and check). Raises ValueError on malformed inputs;
    callers fail closed.
    """
    import hashlib
    import json as json_mod
    if channel not in CHANNELS:
        raise ValueError('Unknown channel.')
    if not isinstance(text, str) or not text:
        raise ValueError('Variant text unavailable for approval binding.')
    if not isinstance(subject, str):
        raise ValueError('Variant subject unavailable for approval binding.')
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise ValueError('Revision unavailable for approval binding.')
    if not isinstance(pack_digest, str) or len(pack_digest) != 64:
        raise ValueError('Pack binding digest unavailable for approval binding.')
    payload = {'version': VARIANT_APPROVAL_VERSION, 'channel': channel,
               'text': text, 'subject': subject, 'revision': revision,
               'pack_binding_digest': pack_digest}
    raw = json_mod.dumps(payload, sort_keys=True, separators=(',', ':'),
                         ensure_ascii=False).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()


def _stored_variant_approvals(receipt):
    raw = receipt.get('channel_approvals') if isinstance(receipt, dict) else None
    return raw if isinstance(raw, dict) else {}


def approve_channel_variant(receipt, channel, actor, expected_revision=None):
    """Human-approve the exact text of one channel variant.

    The approver reviews the exact rendered candidate (as served by
    the bundle read), then this records a variant approval bound to
    that exact text and subject, the current revision, and the current
    pack approval binding digest (which covers revision, confirmed
    facts, policy, voice, photo, and check). Requires the exportable
    pack gate first, then revision currency: a concurrent revision
    change refuses stale. Unsupported or unverified exact text cannot
    be approved. Returns a revised receipt copy with the approval and
    an audit event; approval, revision, and export state otherwise
    unchanged. Raises ValueError on any failure.
    """
    from .human_review import approval_binding, current_revision
    from .receipts import timestamp
    if channel not in CHANNELS:
        raise ValueError('Unknown channel.')
    if not isinstance(receipt, dict):
        raise ValueError('Receipt unavailable for channel approval.')
    if not isinstance(actor, str) or not actor.strip():
        raise ValueError('Channel approval requires a signed-in approver.')
    current = current_revision(receipt)
    if expected_revision is None:
        if current > 0:
            raise ValueError(
                'Channel approval is stale; expected_revision is required for edited revisions')
    else:
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int):
            raise ValueError('expected_revision must be an integer')
        if expected_revision != current:
            raise ValueError('Channel approval is stale; the draft changed')
    _require_checked_gate(receipt)
    bundle = checked_channel_variants(receipt)
    entry = bundle[channel]
    if not entry['content_valid'] or not entry['text']:
        raise ValueError('Channel variant needs revision before it can be approved: '
                         + (entry.get('reason') or 'no verified text'))
    post = bundle_post_text(receipt)
    confirmed = _checked_confirmed_claims(receipt)
    voice_snapshot, voice_ref = _checked_voice(receipt)
    ok, reason = verify_exact_variant_text(
        channel, entry['text'], entry['subject'], post,
        confirmed, voice_snapshot, voice_ref)
    if not ok:
        raise ValueError('Channel variant needs revision before it can be approved: ' + reason)
    binding = approval_binding(receipt)
    digest = variant_approval_digest(
        channel, entry['text'], entry['subject'], current, binding['digest'])
    revised = copy.deepcopy(receipt)
    approvals = dict(_stored_variant_approvals(revised))
    now = timestamp()
    approvals[channel] = {
        'channel': channel,
        'text': entry['text'],
        'subject': entry['subject'],
        'revision': current,
        'pack_binding_version': binding['version'],
        'pack_binding_digest': binding['digest'],
        'variant_digest': digest,
        'approval_version': VARIANT_APPROVAL_VERSION,
        'approved_by': actor,
        'approved_at': now,
    }
    revised['channel_approvals'] = approvals
    events = list((revised.get('audit') or {}).get('event_log') or [])
    events.append({'step': 'channel_variant_approval', 'agent': 'human',
                   'profile': actor or 'human',
                   'action': ('Approved exact %s text at revision %d for offline copy; '
                              'no publish, post, or send occurred'
                              % (channel, current)),
                   'timestamp': now, 'revision': current,
                   'channel': channel, 'approved_by': actor})
    revised.setdefault('audit', {})['event_log'] = events
    return revised


def _validate_leading_prefix_candidate(candidate_text, confirmed_facts,
                                       draft_text, limit, label):
    """Shared content-validity check for X and Facebook candidates.

    Requires the candidate sentences to equal the exact leading
    prefix of split_sentences(draft_text), in order. The only
    sanctioned shortening is trailing whole-sentence trim. Skipping
    first or middle source sentences fails. Reports pure content
    validity only; never product-level export authority.
    """
    base_invalid = {
        "content_valid": False,
        "ok": False,
        "exportable": False,
        "independently_exportable": False,
        "requires_checker_binding": True,
        "checker_approval": None,
        "receipt_id": None,
        "approval_note": APPROVAL_NOTE,
        "limit": limit,
    }
    if not isinstance(candidate_text, str) or not isinstance(draft_text, str):
        result = dict(base_invalid)
        result.update(
            {
                "char_count": 0,
                "reasons": ["Invalid input types."],
                "checks": {"limit_ok": False, "nonempty_ok": False},
            }
        )
        return result
    try:
        confirmed = _confirmed_list(confirmed_facts)
    except (TypeError, ValueError):
        result = dict(base_invalid)
        result.update(
            {
                "char_count": len(candidate_text),
                "reasons": ["Invalid confirmed facts."],
                "checks": {
                    "limit_ok": len(candidate_text) <= limit,
                    "nonempty_ok": bool(candidate_text.strip()),
                },
            }
        )
        return result
    reasons = []
    char_count = len(candidate_text)
    limit_ok = char_count <= limit
    if not limit_ok:
        reasons.append("Exceeds %d characters (%d chars)." % (limit, char_count))
    nonempty_ok = bool(candidate_text.strip())
    if not nonempty_ok:
        reasons.append("Empty %s text." % label)
        result = dict(base_invalid)
        result.update(
            {
                "char_count": char_count,
                "reasons": reasons,
                "checks": {"limit_ok": limit_ok, "nonempty_ok": False},
            }
        )
        return result
    try:
        candidate_sentences = split_sentences(candidate_text)
    except TypeError:
        candidate_sentences = []
    try:
        draft_sentences = split_sentences(draft_text)
    except TypeError:
        draft_sentences = []
    verbatim_ok = True
    if not candidate_sentences:
        verbatim_ok = False
        reasons.append("No complete sentence found in %s text." % label)
    elif not draft_sentences:
        verbatim_ok = False
        preview = candidate_sentences[0][:40]
        reasons.append("Sentence not verbatim in draft: %s" % preview)
    elif len(candidate_sentences) > len(draft_sentences):
        verbatim_ok = False
        reasons.append(
            "Candidate has more sentences than draft; must equal the "
            "exact leading prefix verbatim."
        )
    elif candidate_sentences != draft_sentences[: len(candidate_sentences)]:
        verbatim_ok = False
        for idx, cand in enumerate(candidate_sentences):
            expected = draft_sentences[idx]
            if cand != expected:
                preview = cand[:40]
                if cand in draft_sentences:
                    reasons.append(
                        "Sentence skips earlier draft sentence(s); "
                        "candidate must equal the exact leading prefix "
                        "verbatim in order: %s" % preview
                    )
                else:
                    reasons.append(
                        "Sentence not verbatim in draft: %s" % preview
                    )
                break
    confirmed_tokens = set()
    for fact in confirmed:
        confirmed_tokens.update(_measured_tokens(fact))
    variant_tokens = _measured_tokens(candidate_text)
    measured_ok = True
    for token in variant_tokens:
        if token not in confirmed_tokens:
            measured_ok = False
            reasons.append("Measured claim not in confirmed facts: %s" % token)
    ok = limit_ok and nonempty_ok and verbatim_ok and measured_ok
    return {
        "ok": ok,
        "content_valid": ok,
        "exportable": False,
        "independently_exportable": False,
        "requires_checker_binding": True,
        "checker_approval": None,
        "receipt_id": None,
        "approval_note": APPROVAL_NOTE,
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


def validate_x_variant(x_text, confirmed_facts, draft_text):
    """Deterministically validate an X candidate for content validity.

    Checks the 280 character limit, exact leading-prefix sentence
    relationship to the draft, and exact measured-claim relationship
    to confirmed facts. The candidate sentences must equal the exact
    leading prefix of split_sentences(draft_text), in order. The only
    sanctioned shortening is trailing whole-sentence trim. Skipping
    first or middle source sentences, reordering, and partial or cut
    sentences fail. Reports pure content validity only (ok and
    content_valid); never product-level export authority. Export
    fields are always False and require downstream current approved
    Checker/receipt binding. Never raises on content; type errors
    fail closed.
    """
    return _validate_leading_prefix_candidate(
        x_text, confirmed_facts, draft_text, X_MAX_CHARS, "X"
    )


def validate_facebook_variant(facebook_text, confirmed_facts, draft_text):
    """Deterministically validate a Facebook candidate for content validity.

    Checks the conservative Facebook character bound, exact
    leading-prefix sentence relationship to the draft, and exact
    measured-claim relationship to confirmed facts. Whole-sentence
    leading-prefix behavior mirrors the X validator. Reports pure
    content validity only; never product-level export authority.
    Never raises on content; type errors fail closed.
    """
    return _validate_leading_prefix_candidate(
        facebook_text, confirmed_facts, draft_text, FACEBOOK_MAX_CHARS, "Facebook"
    )
