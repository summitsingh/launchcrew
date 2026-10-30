"""Campaign angle briefs from owner-confirmed facts.

This module is a pure standard-library helper. It takes a small nonempty
list of owner-confirmed fact strings and returns exactly five structured
draft briefs for later human review.

Not wired into any live campaign UI. Core or backend code may import
:func:`generate_campaign_angles` later; this module performs no wiring,
no model call, and no network, database, file, or other external action.

Interface (stable):
    from launchcrew.campaign_angles import generate_campaign_angles

    briefs = generate_campaign_angles([
        "The Blue Harbor demo notebook has 96 pages.",
        "The Blue Harbor demo notebook cover is blue.",
    ])

Each brief is a plain dict with these keys:

    label: short distinct editorial approach name (str).
    editorial_approach: one-line description of the approach (str).
    editorial_instruction: presentational instruction, clearly marked
        as not a fact (str).
    facts_used: exact fact strings quoted in this brief (list of str).
    fact_indexes: positions of facts_used in the input list (list of int).
    brief_text: readable draft containing the approval banner, the
        editorial instruction under its own heading, the exact
        facts under their own heading, and the hook line under its
        own heading (str).
    hook_line: single line under 140 chars. Either a complete
        fact hook (angle prefix plus one whole confirmed fact) or an
        explicit unavailable marker requesting owner input (str).
    hook_fact_index: position of the spotlighted fact in the input (int).
    hook_source_fact: exact spotlighted fact string (str).
    hook_available: True when hook_line is a complete fact hook,
        False when no complete fact fits and hook_line is the
        unavailable marker (bool).
    hook_reason: None when available, else a note asking for a
        shorter confirmed fact (str or None).
    status: always "pending_owner_approval" (str).
    approved: always False (bool).

The five labels are distinct editorial purposes, not reorderings:

    Discovery Hook: open with an editorial hook question answered
        only by the quoted facts.
    Concrete Detail: present the quoted facts with exact wording
        preserved.
    Buyer Question: frame the quoted facts as material for one
        buyer question, without answering beyond them.
    Claim Boundary: state the evidence boundary: only quoted facts
        are asserted, nothing more.
    Concise Recap: recap the quoted facts in a compact draft
        without adding claims.

All five briefs quote the same supplied facts in input order. They
differ in editorial purpose, instruction, questions, and rendered
sections, not in ordering tricks. When only one fact is supplied,
every brief carries an explicit note that the same single fact
supports all five editorial frames, not five independent stories.

Bounds:
    MIN_FACTS = 1, MAX_FACTS = 8, MAX_FACT_CHARS = 500,
    MAX_BRIEF_CHARS = 6000, NUM_ANGLES = 5,
    MAX_HOOK_CHARS = 139 (strictly under 140),
    MIN_DAYS = 1, MAX_DAYS = 7.

Each brief also carries one hook_line: a single line of at most
MAX_HOOK_CHARS chars. A hook is only ever a complete confirmed
fact with an angle specific neutral prefix; this module never
truncates a fact into a hook, because a cut clause can drop a
qualification or negation and reverse meaning. When the mapped
fact does not fit whole, the hook is an explicit unavailable
marker asking for a shorter confirmed fact, and no hook is
pretended. Each campaign day can use one hook line from
generate_campaign_day_hooks, which returns one pending hook per
day under the same complete-or-unavailable rule. Briefs quote the
same shared facts for compatibility, so five angles are five
editorial frames with rotating hook spotlights, not five
independent factual stories; each brief says so honestly, and
fewer facts than angles means reuse is stated.

Rules:
    - Input must be a list or tuple of 1 to MAX_FACTS strings.
    - Each string must be nonblank and at most MAX_FACT_CHARS chars.
    - Exact duplicate strings are rejected.
    - Output keeps each supplied fact string byte-for-byte exact.
    - Output never invents facts and never turns the absence of
      facts into a claim about the product.
    - Editorial instructions and questions live under their own
      headings marked "(not a fact)" and must not be read as
      factual claims. They add no benefit, audience, price,
      origin, guarantee, performance, comparison, inventory, or
      source assertion.
    - Every brief requires individual owner approval. This helper
      never approves anything.
    - Pure function: no input mutation, no randomness, no time,
      no global state, deterministic for the same input order.
"""

NUM_ANGLES = 5
MIN_FACTS = 1
MAX_FACTS = 8
MAX_FACT_CHARS = 500
MAX_BRIEF_CHARS = 6000
MAX_HOOK_CHARS = 139
MIN_DAYS = 1
MAX_DAYS = 7
DEFAULT_DAYS = 7
APPROVAL_STATUS = "pending_owner_approval"

ANGLE_LABELS = (
    "Discovery Hook",
    "Concrete Detail",
    "Buyer Question",
    "Claim Boundary",
    "Concise Recap",
)

ANGLE_HOOK_PREFIXES = (
    "Closer look:",
    "Confirmed note:",
    "Check the record:",
    "Only this is stated:",
    "Short recap:",
)

_APPROVAL_BANNER = (
    "STATUS: PENDING INDIVIDUAL OWNER APPROVAL -- "
    "DRAFT FOR REVIEW, NOT APPROVED."
)

_REVIEW_NOTE = (
    "REVIEW NOTE: This draft re-presents the quoted facts above. "
    "It requires individual owner approval before any use. "
    "No additional facts are asserted here."
)

_HOOK_QUESTION = "What is one confirmed detail worth a closer look?"

_BUYER_QUESTION = "What does the quoted material confirm, in its own words?"

_BOUNDARY_STATEMENT = (
    "Only the quoted facts above are asserted. No additional benefit, audience, "
    "performance, comparison, price, origin, guarantee, inventory, "
    "or source claim beyond those quoted facts is made here."
)

_DETAIL_NOTE = (
    "PRESENTATION NOTE (not a fact): Keep every quoted word exactly "
    "as written; do not paraphrase or explain beyond the quotes."
)

_RECAP_NOTE = (
    "RECAP NOTE (not a fact): This recap repeats the quotes above "
    "with no new wording."
)

__all__ = [
    "NUM_ANGLES",
    "MIN_FACTS",
    "MAX_FACTS",
    "MAX_FACT_CHARS",
    "MAX_BRIEF_CHARS",
    "MAX_HOOK_CHARS",
    "MIN_DAYS",
    "MAX_DAYS",
    "DEFAULT_DAYS",
    "APPROVAL_STATUS",
    "ANGLE_LABELS",
    "ANGLE_HOOK_PREFIXES",
    "generate_campaign_angles",
    "generate_angles",
    "generate_campaign_day_hooks",
    "generate_daily_hooks",
]


def _validate_facts(confirmed_facts):
    """Validate input and return a copied list of facts."""
    if isinstance(confirmed_facts, (str, bytes)):
        raise TypeError("confirmed_facts must be a list or tuple of strings")
    if not isinstance(confirmed_facts, (list, tuple)):
        raise TypeError("confirmed_facts must be a list or tuple of strings")
    facts = list(confirmed_facts)
    if len(facts) < MIN_FACTS:
        raise ValueError("At least one confirmed fact is required")
    if len(facts) > MAX_FACTS:
        raise ValueError("Too many facts: got %d, maximum is %d" % (len(facts), MAX_FACTS))
    for fact in facts:
        if not isinstance(fact, str):
            raise TypeError("Each confirmed fact must be a string")
        if not fact.strip():
            raise ValueError("Confirmed facts must not be blank")
        if len(fact) > MAX_FACT_CHARS:
            raise ValueError(
                "Fact too long: got %d chars, maximum is %d" % (len(fact), MAX_FACT_CHARS)
            )
    if len(set(facts)) != len(facts):
        raise ValueError("Duplicate facts are not allowed")
    return facts


def _numbered_block(facts, heading):
    lines = []
    for i, fact in enumerate(facts, start=1):
        lines.append("%d. %s" % (i, fact))
    return "%s\n%s" % (heading, "\n".join(lines))


def _bullet_block(facts, heading):
    return "%s\n%s" % (heading, "\n".join("- %s" % fact for fact in facts))


def _source_scope_note(total):
    if total == 1:
        return (
            "SOURCE SCOPE (not a fact): Only one owner-confirmed fact "
            "was supplied. All five briefs quote this same single fact "
            "as five editorial frames, not as five independent factual stories."
        )
    return (
        "SOURCE SCOPE (not a fact): All five briefs quote from the same "
        "%d supplied facts as five editorial frames, not as five "
        "independent factual stories." % total
    )


def _collapse_whitespace(text):
    return " ".join(text.split())


_HOOK_UNAVAILABLE_SUFFIX = "hook unavailable: owner input needed."
_HOOK_UNAVAILABLE_REASON = (
    "Mapped fact does not fit whole in a single hook line under "
    "140 chars. No partial hook was made; supply a shorter "
    "owner-confirmed fact for this hook."
)


def _build_hook(prefix, fact):
    """Return (hook_line, available, reason) without ever truncating a fact.

    A hook is prefix plus one whole whitespace-collapsed fact, or an
    explicit unavailable marker. Partial clauses are never hooks.
    """
    if not isinstance(prefix, str) or not prefix.strip():
        raise ValueError("Hook prefix must be a nonempty string")
    collapsed = _collapse_whitespace(fact)
    if not collapsed:
        raise ValueError("Hook fact must be nonempty")
    hook = "%s %s" % (prefix, collapsed)
    if len(hook) < 140 and "\n" not in hook and "\r" not in hook:
        if len(hook) <= MAX_HOOK_CHARS:
            return hook, True, None
    fallback = "%s %s" % (prefix, _HOOK_UNAVAILABLE_SUFFIX)
    if len(fallback) >= 140 or len(fallback) > MAX_HOOK_CHARS:
        raise ValueError("Hook prefix too long")
    return fallback, False, _HOOK_UNAVAILABLE_REASON


def _hook_source_note():
    return (
        "Hook rule (not a fact): a hook is one whole confirmed fact "
        "plus an editorial prefix, never a shortened clause. A cut "
        "clause can drop a qualification, negation, subject, or number "
        "and reverse meaning, so an overlong fact yields an explicit "
        "unavailable marker instead of a hook. The prefix is editorial "
        "framing (not a fact) and adds no benefit, audience, price, "
        "origin, guarantee, performance, comparison, inventory, or "
        "source claim. Every hook needs individual owner approval and "
        "an independent Checker and receipt check before any use; it "
        "is not independently exportable."
    )


def _distinctness_note(total):
    if total == 1:
        return (
            "DISTINCTNESS NOTE (not a fact): Only one owner-confirmed "
            "fact was supplied for five angles, so hooks reuse that "
            "same fact with different editorial framing. These are five "
            "editorial frames, not five independent factual stories. "
            "Supply more confirmed facts for substantively distinct angles."
        )
    if total < NUM_ANGLES:
        return (
            "DISTINCTNESS NOTE (not a fact): Only %d owner-confirmed "
            "facts were supplied for five angles, so some hooks reuse "
            "facts with different editorial framing. Angles differ in "
            "editorial job, not in independent evidence. Supply more "
            "confirmed facts for fully distinct angles." % total
        )
    return (
        "DISTINCTNESS NOTE (not a fact): %d owner-confirmed facts "
        "support five editorial angles. Each hook spotlights one whole "
        "rotating fact; shared quotes remain the common evidence, not "
        "five independent factual stories." % total
    )


def _build_brief(label, approach, instruction, facts, indexes, total, hook_index=0, hook_prefix="Note:"):
    facts_used = [facts[i] for i in indexes]
    if total <= 0:
        raise ValueError("Internal error: no facts for brief")
    hook_fact_index = int(hook_index) % total
    hook_source_fact = facts[hook_fact_index]
    hook_line, hook_available, hook_reason = _build_hook(hook_prefix, hook_source_fact)
    header = "[%s] DRAFT FOR REVIEW -- %s" % (label, _APPROVAL_BANNER)
    instruction_block = "EDITORIAL INSTRUCTION (not a fact): %s" % instruction
    scope_note = _source_scope_note(total)
    distinctness_note = _distinctness_note(total)
    if hook_available:
        hook_block = (
            "CAMPAIGN HOOK LINE (draft, under 140 chars, not a fact on its own):\n%s\n%s"
            % (hook_line, _hook_source_note())
        )
    else:
        hook_block = (
            "CAMPAIGN HOOK LINE (draft, under 140 chars, not a fact on its own):\n%s\n%s\n%s"
            % (hook_line, hook_reason, _hook_source_note())
        )
    if label == "Discovery Hook":
        question_block = (
            "EDITORIAL HOOK QUESTION (not a fact, do not treat as a claim):\n%s"
            % _HOOK_QUESTION
        )
        facts_block = _numbered_block(
            facts_used, "QUOTED FACTS (verbatim, hook support):"
        )
        facts_heading = (
            "OWNER-CONFIRMED FACTS USED (%d of %d supplied, verbatim):\n%s"
            % (len(facts_used), total, facts_block)
        )
        parts = [header, question_block, instruction_block, facts_heading, hook_block, scope_note, _REVIEW_NOTE]
    elif label == "Concrete Detail":
        facts_block = _numbered_block(
            facts_used, "QUOTED FACTS (verbatim, exact wording):"
        )
        facts_heading = (
            "OWNER-CONFIRMED FACTS USED (%d of %d supplied, verbatim):\n%s"
            % (len(facts_used), total, facts_block)
        )
        parts = [header, instruction_block, facts_heading, hook_block, _DETAIL_NOTE, scope_note, _REVIEW_NOTE]
    elif label == "Buyer Question":
        question_block = (
            "EDITORIAL BUYER QUESTION (not a fact, do not treat as a claim):\n%s"
            % _BUYER_QUESTION
        )
        facts_block = _bullet_block(
            facts_used, "QUOTED FACTS (verbatim, answer material only):"
        )
        facts_heading = (
            "OWNER-CONFIRMED FACTS USED (%d of %d supplied, verbatim):\n%s"
            % (len(facts_used), total, facts_block)
        )
        parts = [header, question_block, instruction_block, facts_heading, hook_block, scope_note, _REVIEW_NOTE]
    elif label == "Claim Boundary":
        facts_block = _numbered_block(facts_used, "QUOTED FACTS (verbatim):")
        facts_heading = (
            "OWNER-CONFIRMED FACTS USED (%d of %d supplied, verbatim):\n%s"
            % (len(facts_used), total, facts_block)
        )
        boundary_block = (
            "EVIDENCE / CLAIM BOUNDARY (not a fact, scope note):\n%s"
            % _BOUNDARY_STATEMENT
        )
        parts = [header, instruction_block, facts_heading, hook_block, boundary_block, scope_note, _REVIEW_NOTE]
    else:
        facts_block = _numbered_block(
            facts_used, "QUOTED FACTS (verbatim, recap set):"
        )
        facts_heading = (
            "OWNER-CONFIRMED FACTS USED (%d of %d supplied, verbatim):\n%s"
            % (len(facts_used), total, facts_block)
        )
        parts = [header, instruction_block, facts_heading, hook_block, _RECAP_NOTE, scope_note, _REVIEW_NOTE]
    parts.insert(len(parts) - 1, distinctness_note)
    brief_text = "\n\n".join(parts)
    if len(brief_text) > MAX_BRIEF_CHARS:
        raise ValueError("Generated brief exceeds maximum length")
    return {
        "label": label,
        "editorial_approach": approach,
        "editorial_instruction": instruction,
        "facts_used": list(facts_used),
        "fact_indexes": list(indexes),
        "brief_text": brief_text,
        "hook_line": hook_line,
        "hook_fact_index": hook_fact_index,
        "hook_source_fact": hook_source_fact,
        "hook_available": hook_available,
        "hook_reason": hook_reason,
        "status": APPROVAL_STATUS,
        "approved": False,
    }


def generate_campaign_angles(confirmed_facts):
    """Build exactly five draft campaign angle briefs, each with one hook line.

    Args:
        confirmed_facts: nonempty list or tuple of 1 to MAX_FACTS
            owner-confirmed fact strings. Each must be nonblank,
            at most MAX_FACT_CHARS chars, with no exact duplicates.
            Order is preserved and selections are deterministic.

    Returns:
        A new list of exactly NUM_ANGLES dicts (see module docstring
        for keys). Labels are the five distinct editorial purposes.
        All five briefs quote the same supplied facts in input
        order; differentiation is editorial purpose and framing,
        not reordering. When one fact is supplied, every brief
        carries an explicit note that the same single fact supports
        all five editorial frames, not five independent stories.
        Each brief also carries hook_line (under 140 chars),
        hook_fact_index, hook_source_fact, hook_available, and
        hook_reason. The hook spotlights one rotating fact (angle
        position modulo fact count) with an angle specific neutral
        prefix. A hook is only emitted when the whole fact fits;
        otherwise hook_available is False and hook_line is an explicit
        unavailable marker asking for a shorter confirmed fact, with
        no partial clause presented as a hook. facts_used stays shared
        for compatibility, and each brief honestly states reuse limits
        in a distinctness note. Every brief stays pending owner
        approval and needs an independent Checker and receipt check.

    Raises:
        TypeError: if the input is not a list or tuple of strings.
        ValueError: if count, blank, duplicate, fact-length, or
            output-length bounds are violated.

    Purity:
        No input mutation, no model, network, database, file, or
        external action. Deterministic for the same input.
    """
    facts = _validate_facts(confirmed_facts)
    total = len(facts)
    shared_indexes = list(range(total))
    specs = (
        (
            ANGLE_LABELS[0],
            "Open with an editorial hook question answered only by the quoted facts.",
            "Start from the editorial hook question, then show the quoted "
            "facts as the only supporting material. Do not reword the facts "
            "and do not add surrounding factual sentences.",
            list(shared_indexes),
        ),
        (
            ANGLE_LABELS[1],
            "Present the quoted facts with exact wording preserved.",
            "Show each quoted fact exactly as written, preserving every word. "
            "Do not paraphrase, combine, or add explanatory sentences.",
            list(shared_indexes),
        ),
        (
            ANGLE_LABELS[2],
            "Frame the quoted facts as material for one buyer question, without answering beyond them.",
            "Present the editorial buyer question first, then list the quoted "
            "facts as the only permitted answer material. Do not answer beyond "
            "the quoted wording and do not add recommendations.",
            list(shared_indexes),
        ),
        (
            ANGLE_LABELS[3],
            "State the evidence boundary: only quoted facts are asserted, nothing more.",
            "Quote the facts first, then restate the boundary that no other "
            "benefit, audience, performance, comparison, price, origin, "
            "guarantee, inventory, or source claim is made. Do not add new claims.",
            list(shared_indexes),
        ),
        (
            ANGLE_LABELS[4],
            "Recap the quoted facts in a compact draft without adding claims.",
            "Repeat the quoted facts together as a short recap draft. Do not "
            "shorten their wording and do not add summary claims beyond the quotes.",
            list(shared_indexes),
        ),
    )
    briefs = [
        _build_brief(
            label, approach, instruction, facts, indexes, total,
            hook_index=position, hook_prefix=ANGLE_HOOK_PREFIXES[position],
        )
        for position, (label, approach, instruction, indexes) in enumerate(specs)
    ]
    if len(briefs) != NUM_ANGLES:
        raise ValueError("Internal error: expected exactly five briefs")
    return briefs


def _validate_num_days(num_days):
    if isinstance(num_days, bool):
        raise TypeError("num_days must be an integer")
    if not isinstance(num_days, int):
        raise TypeError("num_days must be an integer")
    if num_days < MIN_DAYS or num_days > MAX_DAYS:
        raise ValueError(
            "num_days must be between %d and %d, got %d"
            % (MIN_DAYS, MAX_DAYS, num_days)
        )
    return num_days


def generate_campaign_day_hooks(confirmed_facts, num_days=DEFAULT_DAYS):
    """Build one pending hook line per campaign day.

    Args:
        confirmed_facts: nonempty list or tuple of 1 to MAX_FACTS
            owner-confirmed fact strings, validated like
            generate_campaign_angles.
        num_days: integer from MIN_DAYS to MAX_DAYS (default 7 for a
            seven day campaign week). Each day maps deterministically
            to facts[(day - 1) % len(facts)].

    Returns:
        A new list of num_days dicts with keys day (1 indexed),
        day_label, hook_line (under 140 chars, single line),
        source_fact (exact input string), fact_index, hook_available
        (bool), hook_reason (str or None), status
        (pending_owner_approval), and approved (False). Available
        hooks use a neutral "Day N draft:" prefix plus one whole
        confirmed fact. When the mapped fact does not fit whole, the
        entry carries hook_available False and an explicit unavailable
        hook_line asking for a shorter confirmed fact; no partial
        clause is presented as a hook. No new claim is added, nothing
        is approved, and every hook needs an independent Checker and
        receipt check.

    Raises:
        TypeError: for bad input types.
        ValueError: for bad counts, blank or duplicate facts,
            overlong facts, bad day counts, or overlong hooks.

    Purity:
        No input mutation, no model, network, database, file, or
        external action. Deterministic for the same input.
    """
    facts = _validate_facts(confirmed_facts)
    days = _validate_num_days(num_days)
    total = len(facts)
    hooks = []
    for day in range(1, days + 1):
        fact_index = (day - 1) % total
        source_fact = facts[fact_index]
        prefix = "Day %d draft:" % day
        hook_line, available, reason = _build_hook(prefix, source_fact)
        hooks.append(
            {
                "day": day,
                "day_label": "Day %d" % day,
                "hook_line": hook_line,
                "source_fact": source_fact,
                "fact_index": fact_index,
                "hook_available": available,
                "hook_reason": reason,
                "status": APPROVAL_STATUS,
                "approved": False,
            }
        )
    return hooks


# Short alias for the same stable helper.
generate_angles = generate_campaign_angles

# Short alias for the per-day hook helper.
generate_daily_hooks = generate_campaign_day_hooks
