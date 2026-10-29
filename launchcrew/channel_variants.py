"""Channel presentation candidates for later integration.

Pure standard library helpers. No model calls, no fetching, no
publishing, no photo behavior.

Inputs are caller supplied: draft text, confirmed fact strings, and
audience or angle context. Outputs are presentation candidates only,
never independently exportable. Every candidate requires downstream
current approved Checker/receipt binding before any export. No
Checker approval or receipt is claimed here and no approval ID is
invented.

Every draft sentence in every candidate is copied verbatim from the
draft. No sentence is reworded, shortened, or split. Trimming for X
and Facebook drops whole trailing sentences only, on a full sentence
boundary, with an explicit trim note. Audience suggestions and
campaign angles are recorded as unverified context in metadata and
are never rendered as product facts.
"""

import copy
import re

MODULE_VERSION = "channel-variants/v1"
X_MAX_CHARS = 280
FACEBOOK_MAX_CHARS = 2000
CHANNELS = ("x", "linkedin", "instagram", "email", "facebook")

LINKEDIN_HEADER = "Update:"
INSTAGRAM_CLOSER = "More soon."
EMAIL_SUBJECT = "Quick update"
EMAIL_GREETING = "Hello,"
EMAIL_CLOSER = "Thanks,"

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


def _needs_revision(channel, confirmed_count, audience, campaign_angle, reason):
    metadata = _base_metadata(channel, confirmed_count, audience, campaign_angle)
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
