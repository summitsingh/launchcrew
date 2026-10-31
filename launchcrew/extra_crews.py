"""Isolated foundation for Slice 6 extra crews (stdlib only).

Covers four prebuilt helper profiles on the existing agent spine:

* Support: FAQ and reply drafts checked against confirmed facts.
* Designer: crop and layout suggestions in words only, grounded in
  explicitly supplied validated original-image geometry data from the
  existing photo contracts. No pixel generation, processing, or viewing.
* Analyst: owner outcome summaries over the actual multi-metric
  outcome shape (posted_date plus likes, comments, clicks, sales)
  with intact self-report provenance.
* Research: sourced fact gathering as unconfirmed suggestions, with
  owner-supplied references kept distinct from verified sources.

Scope guarantees:

* Pure stdlib, deterministic, no I/O, no network, no database, no
  model calls, no photo transport, no filesystem access.
* Profiles validate through ``launchcrew.agents.validate`` with zero
  spend, ``approve_each``, one distinct enforced Checker policy each
  (Support blocks price claims, Designer blocks superlatives, Analyst
  blocks marketing cliches, Research bans the custom phrase moonshot),
  and tools limited to the existing ``ALLOWED_TOOLS`` set.
* Nothing here confirms facts, approves drafts, writes to any memory
  or approval store, or crosses the owner and workspace boundary.
  Every output requires owner confirmation and Checker approval
  through a separate explicit step that is not implemented here.
* Confirmed and unconfirmed states stay distinct. Support drafts cite
  ``facts.check_claim`` verdicts. Research suggestions stay
  unconfirmed even when they match a confirmed sentence, and no
  lookup is ever implied or performed. Analyst summaries restate
  only validated self-reported outcome records and never invent
  measures, totals, trends, or comparisons. Designer suggestions
  describe words only, derive only from supplied geometry data, and
  never claim pixels were viewed.
* No hard-coded demo file paths appear in live profile guidance.
  The source of truth is workspace-confirmed facts plus owner
  provided material.

Integration needs (not implemented here, reported honestly):

* Owner confirmation UI for each draft or suggestion.
* Checker approval binding before any export or use.
* Workspace isolation wiring: Analyst callers must pass the expected
  workspace when entries carry workspace tags; mismatches fail
  closed here, but server-side enforcement lives in the backend.
* Designer callers must supply validated geometry from the existing
  photo contracts (``launchcrew.photo_policy`` verdicts plus the
  sanitized ``backend.photo_review`` status). A bare filename or
  label never establishes an owner original.
* No backend, API, schema, store, or UI changes in this module.
"""

import copy
import datetime

EXTRA_CREW_VERSION = "extra-crews/v2"
STATUS_DRAFT = "draft"
STATUS_UNCONFIRMED = "unconfirmed"
PROVENANCE_SELF_REPORTED = "self_reported"
ENTERED_BY_OWNER = "owner_entered"

EXTRA_CREW_NAMES = ("support", "designer", "analyst", "research")

ACTOR_PLACEHOLDER = "demo_placeholder"
MAX_NOTE_LENGTH = 500
MAX_METRIC = 1000000

_SUPPORT_PROFILE = {
    "name": "Support",
    "role": "Intended FAQ Reply Drafter",
    "department": "Support",
    "personality": (
        "Cautious and fact grounded. Intended to draft FAQ replies only "
        "from workspace-confirmed facts and owner provided notes. Would cite "
        "its source for each claim and mark anything unverified. Would require "
        "owner confirmation and Checker approval before any draft is used, "
        "and would not approve its own drafts or bypass review."
    ),
    "expertise": (
        "Intended coverage of FAQ reply drafting from workspace-confirmed "
        "facts and owner provided notes. No network lookup. No invented "
        "answers. Source is limited to cited workspace-confirmed fact "
        "entries, confirmation is limited to owner review, and approval is "
        "limited to Checker review for each draft. Checker veto remains "
        "authoritative."
    ),
    "decision_rules": [
        "Use only workspace-confirmed facts and owner provided notes as source, and cite the source for each claim",
        "Mark any claim without a source as unverified and leave it for owner confirmation",
        "Prepare drafts for owner confirmation and Checker approval, and do not approve drafts or bypass review",
        "If sources conflict or are missing, ask for owner input instead of guessing",
        "Block price claims",
    ],
    "veto_scope": ["price_claims"],
    "tools_allowed": ["facts_file", "spark_strict_json", "receipt_log", "claim_check"],
    "spend_limit": 0,
    "approval_level": "approve_each",
    "examples": [],
}

_DESIGNER_PROFILE = {
    "name": "Designer",
    "role": "Intended Photo Layout Suggestion Helper",
    "department": "Design",
    "personality": (
        "Careful and non altering. Intended to suggest crops and layouts in "
        "words only, grounded in explicitly supplied validated geometry from "
        "the existing photo contracts for owner provided originals. Would "
        "not generate, view, alter, or process pixels. Would describe "
        "suggestions in words for owner confirmation, and would require "
        "Checker approval before any suggestion is used. Would not approve "
        "its own suggestions or bypass review."
    ),
    "expertise": (
        "Intended coverage of crop and layout suggestions described in words, "
        "based only on validated geometry for owner provided originals plus "
        "owner brand notes. No generated, viewed, or altered pixels. No image "
        "processing. Source is limited to supplied photo contract geometry, "
        "confirmation is limited to owner review, and approval is limited to "
        "Checker review for each suggestion. Checker veto remains "
        "authoritative."
    ),
    "decision_rules": [
        "Suggest crops and layouts in words only, grounded in explicitly supplied validated photo geometry for owner provided originals",
        "Do not generate, view, alter, or process pixels, and do not claim to edit image files or to have inspected pixels",
        "Prepare suggestions for owner confirmation and Checker approval, and do not approve suggestions or bypass review",
        "If validated geometry, the original photo, or the brand note is missing, ask for owner input instead of guessing",
        "Block superlatives",
    ],
    "veto_scope": ["superlatives"],
    "tools_allowed": ["facts_file", "spark_strict_json", "receipt_log"],
    "spend_limit": 0,
    "approval_level": "approve_each",
    "examples": [],
}

_ANALYST_PROFILE = {
    "name": "Analyst",
    "role": "Intended Outcome Summary Helper",
    "department": "Analytics",
    "personality": (
        "Careful and literal. Intended to summarize only validated owner "
        "entered multi-metric outcome records in plain words. Would not "
        "invent metrics, trends, or comparisons. Would cite the owner entered "
        "source for each summary point and keep self-report provenance "
        "visible. Would require owner confirmation and Checker approval before "
        "any summary is used, and would not approve its own summaries or "
        "bypass review."
    ),
    "expertise": (
        "Intended coverage of summaries of validated owner entered outcome "
        "records carrying posted date plus likes, comments, clicks, sales, "
        "and note, with no invented metrics. No network lookup. No computed "
        "totals, trends, or comparisons beyond restating supplied records. "
        "Source is limited to validated owner entered records, confirmation "
        "is limited to owner review, and approval is limited to Checker "
        "review for each summary. Checker veto remains authoritative."
    ),
    "decision_rules": [
        "Summarize only validated owner entered outcome records, and cite the owner entry for each point",
        "Do not invent metrics, totals, trends, targets, or comparisons",
        "Prepare summaries for owner confirmation and Checker approval, and do not approve summaries or bypass review",
        "If owner entries are missing, unclear, invalid, or from another workspace, fail closed and ask for owner input instead of guessing",
        "Block marketing cliches",
    ],
    "veto_scope": ["cliches"],
    "tools_allowed": ["facts_file", "spark_strict_json", "receipt_log"],
    "spend_limit": 0,
    "approval_level": "approve_each",
    "examples": [],
}

_RESEARCH_PROFILE = {
    "name": "Research",
    "role": "Intended Sourced Fact Suggestion Helper",
    "department": "Research",
    "personality": (
        "Cautious and source first. Intended to suggest facts only as "
        "unconfirmed suggestions with a stated owner-supplied reference. "
        "Would keep owner-supplied references distinct from verified sources "
        "and mark anything without a source as unverified. Would never imply "
        "a lookup was performed. Would require owner confirmation for every "
        "suggestion and Checker approval before any suggestion is used. Would "
        "not approve its own suggestions or bypass review."
    ),
    "expertise": (
        "Intended coverage of sourced fact suggestions from owner provided "
        "material against workspace-confirmed facts. No network lookup. No "
        "unsourced claims stated as true. Owner-supplied references are kept "
        "distinct from verified sources, confirmation is limited to owner "
        "review, and approval is limited to Checker review for each "
        "suggestion. Checker veto remains authoritative."
    ),
    "decision_rules": [
        "Use workspace-confirmed facts and owner provided material as source, keep owner-supplied references distinct from verified sources, and cite the reference for every suggested fact",
        "Mark any suggestion without a source as unverified, keep every suggestion unconfirmed, and never imply a lookup was performed",
        "Prepare suggestions for owner confirmation and Checker approval, and do not approve suggestions or bypass review",
        "If a source is missing or unclear, ask for owner input instead of guessing",
        "Ban phrase moonshot",
    ],
    "veto_scope": ["banned:moonshot"],
    "tools_allowed": ["facts_file", "spark_strict_json", "receipt_log", "claim_check"],
    "spend_limit": 0,
    "approval_level": "approve_each",
    "examples": [],
}

_PROFILES = {
    "support": _SUPPORT_PROFILE,
    "designer": _DESIGNER_PROFILE,
    "analyst": _ANALYST_PROFILE,
    "research": _RESEARCH_PROFILE,
}

__all__ = [
    "EXTRA_CREW_VERSION",
    "EXTRA_CREW_NAMES",
    "STATUS_DRAFT",
    "STATUS_UNCONFIRMED",
    "PROVENANCE_SELF_REPORTED",
    "ENTERED_BY_OWNER",
    "get_extra_crew_profile",
    "list_extra_crew_profiles",
    "draft_support_reply",
    "suggest_designer_layout",
    "summarize_outcomes",
    "suggest_research_facts",
]


def _check_name(name):
    if not isinstance(name, str):
        raise TypeError("crew name must be a string")
    key = name.strip().lower()
    if key not in _PROFILES:
        raise ValueError("unknown extra crew: %r" % (name,))
    return key


def get_extra_crew_profile(name):
    """Return a deep copy of one prebuilt extra crew profile.

    The copy validates through ``launchcrew.agents.validate`` and is
    safe for callers to render or attach to a draft. Profiles never
    approve their own output.
    """
    from . import agents

    key = _check_name(name)
    profile = copy.deepcopy(_PROFILES[key])
    agents.validate(profile)
    return profile


def list_extra_crew_profiles():
    """Return deep copies of all four prebuilt extra crew profiles."""
    return [get_extra_crew_profile(name) for name in EXTRA_CREW_NAMES]


def _check_claims_list(claims):
    if not isinstance(claims, list):
        raise TypeError("claims must be a list of strings")
    for item in claims:
        if not isinstance(item, str):
            raise TypeError("each claim must be a string")
    return list(claims)


def _check_facts(facts):
    if not isinstance(facts, dict):
        raise TypeError("facts must be a dict with approved_claims")
    approved = facts.get("approved_claims")
    if not isinstance(approved, list) or not approved:
        raise ValueError("facts require a nonempty approved_claims list")
    sources = facts.get("sources")
    if sources is not None:
        if not isinstance(sources, list) or not all(isinstance(s, str) for s in sources):
            raise ValueError("facts sources must be a list of strings when present")
    return facts


def draft_support_reply(question, claims, facts):
    """Draft an FAQ reply checked against confirmed facts.

    Args:
        question: Owner supplied FAQ question as a string.
        claims: Candidate reply sentences as a list of strings.
        facts: Facts dict with ``approved_claims`` (same shape used
            by ``launchcrew.facts.check_claim``).

    Returns a draft dict with per claim verdict, evidence, source,
    ``status`` ``"draft"``, ``approved`` False,
    ``requires_owner_confirmation`` True, and
    ``requires_checker_approval`` True. Unmatched claims stay
    unverified and ask for owner input. Never approves the draft.
    """
    from .facts import check_claim

    if not isinstance(question, str):
        raise TypeError("question must be a string")
    if not question.strip():
        raise ValueError("question must not be empty")
    _check_facts(facts)
    items = _check_claims_list(claims)
    checked = []
    for text in items:
        result = check_claim(text, facts)
        checked.append(
            {
                "claim": text,
                "verified": bool(result.get("verified")),
                "verdict": result.get("verdict"),
                "evidence": result.get("evidence"),
                "reason": result.get("reason"),
                "source": "facts_file" if result.get("verified") else "unverified",
                "status": STATUS_DRAFT,
            }
        )
    needs_owner_input = not items or any(not item["verified"] for item in checked)
    return {
        "crew": "support",
        "question": question,
        "claims": checked,
        "status": STATUS_DRAFT,
        "approved": False,
        "requires_owner_confirmation": True,
        "requires_checker_approval": True,
        "needs_owner_input": needs_owner_input,
        "profile_version": EXTRA_CREW_VERSION,
    }


def _designer_needs_input(photo_label, request_note, reason, verdict=None):
    return {
        "crew": "designer",
        "photo_label": photo_label,
        "request_note": request_note,
        "suggestion_text": "",
        "words_only": True,
        "original_only": True,
        "geometry_grounded": False,
        "verdict": verdict,
        "crop": None,
        "inspected_pixels": False,
        "generated_pixels": False,
        "processed_pixels": False,
        "source": "owner_provided_original",
        "status": STATUS_DRAFT,
        "approved": False,
        "requires_owner_confirmation": True,
        "requires_checker_approval": True,
        "needs_owner_input": True,
        "needs_owner_input_reason": reason,
        "profile_version": EXTRA_CREW_VERSION,
    }


def suggest_designer_layout(photo, request_note, brand_note=""):
    """Suggest a crop or layout in words from validated photo geometry.

    Args:
        photo: Dict with explicitly supplied validated original-image
            data from the existing photo contracts: ``frame`` as two
            positive ints ``(width, height)``, ``records`` as the SAM
            record list used by
            ``launchcrew.photo_policy.classify_photo_geometry``, and an
            optional ``photo_ref`` string label plus an optional
            ``status`` sanitized summary dict. A bare label never
            establishes an owner original or image geometry.
        request_note: Owner supplied layout request as a string.
        brand_note: Optional owner brand note as a string.

    Returns a words-only suggestion dict. Geometry is validated with
    the existing photo policy; anything other than a current
    ``detected`` verdict yields ``needs_owner_input`` True with no
    suggestion text. The suggestion never contains pixels, never
    claims files were edited, and never claims pixels were viewed:
    it states it derives from supplied geometry data. Never approves
    the suggestion.
    """
    from .photo_policy import classify_photo_geometry, suggest_crop

    if not isinstance(photo, dict):
        raise TypeError("photo must be a dict with frame and records")
    if not isinstance(request_note, str):
        raise TypeError("request_note must be a string")
    if not isinstance(brand_note, str):
        raise TypeError("brand_note must be a string")
    if isinstance(request_note, bytes) or isinstance(brand_note, bytes):
        raise TypeError("pixel bytes are not accepted")
    for key in ("frame", "records"):
        if key not in photo:
            raise TypeError("photo dict must include %r" % key)
    photo_ref = photo.get("photo_ref", "")
    if not isinstance(photo_ref, str):
        raise TypeError("photo_ref must be a string when present")
    if len(photo_ref) > 500 or len(request_note) > 2000 or len(brand_note) > 2000:
        raise ValueError("photo_ref, request_note, or brand_note is overlong")
    label = photo_ref.strip()
    if not request_note.strip():
        return _designer_needs_input(
            label, request_note, "request note is missing", verdict=None
        )
    frame = photo.get("frame")
    records = photo.get("records")
    if not isinstance(records, list) or not records:
        return _designer_needs_input(
            label, request_note.strip(), "validated geometry records are missing", verdict=None
        )
    verdict = classify_photo_geometry(records, frame)
    if not isinstance(verdict, dict) or verdict.get("label") != "detected":
        detail = (verdict or {}).get("label", "unknown") if isinstance(verdict, dict) else "unknown"
        return _designer_needs_input(
            label,
            request_note.strip(),
            "validated geometry is insufficient: verdict is %s" % detail,
            verdict=verdict if isinstance(verdict, dict) else None,
        )
    try:
        box = records[0].get("box") if isinstance(records[0], dict) else None
        crop = suggest_crop(box, frame)
    except (ValueError, TypeError, KeyError, AttributeError):
        return _designer_needs_input(
            label, request_note.strip(), "validated crop geometry is missing", verdict=verdict
        )
    words = (
        "For the owner provided original%s, the supplied geometry reports "
        "a detected subject in a %s by %s frame with reason %r. "
        "Consider a words-only crop holding existing pixels from "
        "(%d, %d) to (%d, %d) to frame the subject for %r."
        % (
            (" %r" % label) if label else "",
            str(frame[0]),
            str(frame[1]),
            verdict.get("reason", ""),
            crop["x1"],
            crop["y1"],
            crop["x2"],
            crop["y2"],
            request_note.strip(),
        )
    )
    if brand_note.strip():
        words += " Keep the owner brand note in mind: %r." % brand_note.strip()
    words += (
        " This derives from supplied geometry data only; no pixels were "
        "viewed, generated, or altered. Confirm the original and the brand "
        "note, then seek Checker approval before use."
    )
    return {
        "crew": "designer",
        "photo_label": label,
        "request_note": request_note.strip(),
        "brand_note": brand_note.strip(),
        "suggestion_text": words,
        "words_only": True,
        "original_only": True,
        "geometry_grounded": True,
        "verdict": verdict,
        "crop": dict(crop),
        "inspected_pixels": False,
        "generated_pixels": False,
        "processed_pixels": False,
        "source": "owner_provided_original",
        "status": STATUS_DRAFT,
        "approved": False,
        "requires_owner_confirmation": True,
        "requires_checker_approval": True,
        "needs_owner_input": False,
        "needs_owner_input_reason": "",
        "profile_version": EXTRA_CREW_VERSION,
    }


def _validate_posted_date(value):
    if not isinstance(value, str):
        return "posted_date must be a string in YYYY-MM-DD format"
    if len(value) != 10 or value[4] != "-" or value[7] != "-":
        return "posted_date must be in YYYY-MM-DD format"
    parts = value.split("-")
    if (
        len(parts) != 3
        or len(parts[0]) != 4
        or len(parts[1]) != 2
        or len(parts[2]) != 2
        or not all(part.isascii() and part.isdigit() for part in parts)
    ):
        return "posted_date must be in YYYY-MM-DD format"
    try:
        datetime.date(int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError:
        return "posted_date is not a real calendar date"
    return None


def _validate_metric(value):
    if type(value) is not int:
        return "metric must be an integer"
    if value < 0 or value > MAX_METRIC:
        return "metric must be between 0 and 1000000"
    return None


def _validate_note_text(note):
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


def _check_outcome_record(entry, workspace_id, run_id):
    from .outcome_log import KNOWN_CHANNELS

    if not isinstance(entry, dict):
        raise TypeError("each outcome entry must be a dict")
    if "count" in entry or "date" in entry:
        raise ValueError(
            "legacy single-count entries are not summarized here; "
            "supply posted_date plus likes, comments, clicks, and sales"
        )
    missing = [
        key
        for key in (
            "channel",
            "posted_date",
            "likes",
            "comments",
            "clicks",
            "sales",
            "note",
            "provenance",
        )
        if key not in entry
    ]
    if missing:
        raise ValueError("outcome entry is missing: %s" % ", ".join(sorted(missing)))
    channel = entry.get("channel")
    if not isinstance(channel, str) or channel not in KNOWN_CHANNELS:
        raise ValueError("outcome entry has an unknown channel")
    date_error = _validate_posted_date(entry.get("posted_date"))
    if date_error is not None:
        raise ValueError("outcome entry has an invalid posted_date: " + date_error)
    for key in ("likes", "comments", "clicks", "sales"):
        metric_error = _validate_metric(entry.get(key))
        if metric_error is not None:
            raise ValueError("outcome entry has an invalid %s: %s" % (key, metric_error))
    note_error = _validate_note_text(entry.get("note"))
    if note_error is not None:
        raise ValueError("outcome entry has an invalid note: " + note_error)
    if entry.get("provenance") != PROVENANCE_SELF_REPORTED:
        raise ValueError("outcome entry must carry self_reported provenance")
    if "entered_by" in entry and entry.get("entered_by") != ENTERED_BY_OWNER:
        raise ValueError("outcome entry must carry owner_entered source")
    actor = entry.get("actor")
    if actor is not None:
        if not isinstance(actor, str) or not actor.strip():
            raise ValueError("outcome entry has an invalid actor")
        if actor.strip() == ACTOR_PLACEHOLDER:
            raise ValueError("outcome entry must come from a signed-in actor")
    tagged_workspace = entry.get("workspace_id")
    if tagged_workspace is not None:
        if not isinstance(tagged_workspace, str) or not tagged_workspace:
            raise ValueError("outcome entry has an invalid workspace tag")
        if not isinstance(workspace_id, str) or not workspace_id:
            raise ValueError(
                "workspace-tagged outcome entries require an expected workspace"
            )
        if tagged_workspace != workspace_id:
            raise ValueError("outcome entry belongs to another workspace")
    elif workspace_id is not None and not isinstance(workspace_id, str):
        raise TypeError("workspace_id must be a string when given")
    tagged_run = entry.get("run_id")
    if tagged_run is not None and run_id is not None and tagged_run != run_id:
        raise ValueError("outcome entry belongs to another run")
    if run_id is not None and not isinstance(run_id, str):
        raise TypeError("run_id must be a string when given")
    return entry


def summarize_outcomes(entries, workspace_id=None, run_id=None):
    """Summarize validated multi-metric owner outcome records.

    Args:
        entries: List of owner outcome record dicts shaped like the
            existing outcome API rows: ``channel``, ``posted_date``,
            ``likes``, ``comments``, ``clicks``, ``sales``, ``note``,
            and ``provenance`` ``"self_reported"``. Optional
            ``workspace_id``, ``run_id``, ``actor``, and
            ``entered_by`` tags are checked when present.
        workspace_id: Expected workspace for entries that carry a
            ``workspace_id`` tag. Tagged entries from another
            workspace fail closed.
        run_id: Expected run for entries that carry a ``run_id`` tag.

    Returns a summary dict that restates each record verbatim with a
    per point citation. No totals, averages, trends, targets, or
    comparisons are computed, and no measure is invented. Empty input
    yields ``needs_owner_input`` True. Never approves the summary.
    """
    if not isinstance(entries, list):
        raise TypeError("entries must be a list")
    if workspace_id is not None and not isinstance(workspace_id, str):
        raise TypeError("workspace_id must be a string when given")
    if run_id is not None and not isinstance(run_id, str):
        raise TypeError("run_id must be a string when given")
    points = []
    for index, entry in enumerate(entries):
        checked = _check_outcome_record(entry, workspace_id, run_id)
        points.append(
            {
                "point": "On %s, channel %s: likes %d, comments %d, clicks %d, sales %d. Note: %s"
                % (
                    checked["posted_date"],
                    checked["channel"],
                    checked["likes"],
                    checked["comments"],
                    checked["clicks"],
                    checked["sales"],
                    checked["note"],
                ),
                "citation": "owner entry %d" % index,
                "provenance": PROVENANCE_SELF_REPORTED,
                "entered_by": checked.get("entered_by", ENTERED_BY_OWNER),
                "status": STATUS_DRAFT,
            }
        )
    return {
        "crew": "analyst",
        "points": points,
        "entry_count": len(points),
        "invented_metrics": False,
        "computed_totals": False,
        "source": "owner_entered_outcomes",
        "status": STATUS_DRAFT,
        "approved": False,
        "requires_owner_confirmation": True,
        "requires_checker_approval": True,
        "needs_owner_input": not points,
        "profile_version": EXTRA_CREW_VERSION,
    }


def suggest_research_facts(candidates, facts):
    """Gather sourced candidates as unconfirmed suggestions.

    Args:
        candidates: List of strings or dicts with ``text`` and optional
            ``source``. Plain strings are treated as having no source
            and stay unverified. A source string is recorded verbatim
            as an owner-supplied reference; when it matches a
            workspace-confirmed ``facts`` source it is marked
            accordingly for advisory purposes only.
        facts: Facts dict with ``approved_claims`` used only for
            advisory match notes. Matching never confirms a candidate.

    Returns a result dict with ``status`` ``"unconfirmed"`` on the
    result and on every suggestion. Each suggestion carries
    ``source_kind``: ``"workspace_verified_reference"`` when the
    owner-supplied reference matches a workspace-confirmed source,
    ``"owner_supplied_reference"`` when a reference was supplied but
    matches nothing confirmed, and ``"unsourced"`` otherwise. Every
    suggestion requires owner confirmation and Checker approval. No
    network lookup is performed or implied.
    """
    from .facts import check_claim

    if not isinstance(candidates, list):
        raise TypeError("candidates must be a list")
    _check_facts(facts)
    confirmed_sources = facts.get("sources") or []
    suggestions = []
    for index, raw in enumerate(candidates):
        if isinstance(raw, str):
            text, source = raw, ""
        elif isinstance(raw, dict):
            text = raw.get("text")
            source = raw.get("source", "")
            if not isinstance(text, str):
                raise TypeError("candidate text must be a string")
            if not isinstance(source, str):
                raise TypeError("candidate source must be a string")
        else:
            raise TypeError("each candidate must be a string or dict")
        if len(text) > 500:
            raise ValueError("candidate text is overlong")
        if len(source) > 500:
            raise ValueError("candidate source is overlong")
        advisory = check_claim(text, facts) if text.strip() else None
        matched = bool(advisory and advisory.get("verified"))
        stripped_source = source.strip()
        if not stripped_source:
            source_kind = "unsourced"
            recorded_source = "unsourced"
        elif stripped_source in confirmed_sources:
            source_kind = "workspace_verified_reference"
            recorded_source = stripped_source
        else:
            source_kind = "owner_supplied_reference"
            recorded_source = stripped_source
        suggestions.append(
            {
                "text": text,
                "source": recorded_source,
                "source_kind": source_kind,
                "status": STATUS_UNCONFIRMED,
                "verified": False,
                "confirmed": False,
                "matched_confirmed_fact": matched,
                "note": (
                    "Owner-supplied reference matches a workspace-confirmed "
                    "source for advisory purposes only; still unconfirmed, no "
                    "lookup was performed, and owner confirmation plus "
                    "Checker approval are required."
                    if matched or source_kind == "workspace_verified_reference"
                    else "Unverified owner-supplied reference; no lookup was "
                    "performed; leave for owner confirmation."
                ),
                "index": index,
            }
        )
    return {
        "crew": "research",
        "status": STATUS_UNCONFIRMED,
        "suggestions": suggestions,
        "approved": False,
        "requires_owner_confirmation": True,
        "requires_checker_approval": True,
        "needs_owner_input": not suggestions,
        "profile_version": EXTRA_CREW_VERSION,
    }


# Backward-compatible alias
list_extra_crews_profiles = list_extra_crew_profiles
