"""Slice 5 foundation: fictional quick-start intake templates.

Each template is a bundled fictional example (food product, mobile app,
local service). Every value ships as an UNCONFIRMED suggestion with
``demo_template`` provenance. Selecting a template never confirms,
verifies, publishes, or authorizes anything: the owner must still
review each example, replace it with the owner fact, and check each
confirmation box in the intake form, which then flows through the
existing ``parse_product_facts`` contract. This module does not enforce
those per-field edits itself; the integration seam must persist the
per-field provenance from :func:`build_prefill` server-side and call
:func:`assert_template_review_complete` with that server copy before
treating any submitted input as evidence, so an unchanged example
(including the first-person founder note) can never silently become a
real fact. Fields submitted without template provenance are ordinary
owner facts and are never blocked, even on coincidental text matches.

Template files reuse the existing facts-file key names
(``approved_claims``, ``sources``) with honestly empty values: no
example claim is approved, and the files deliberately fail the legacy
``load_facts`` evidence gate.

This module performs local file reads only. No network, no credentials,
no publishing. Template files must never carry private identifiers
(emails, phones, street addresses, real brand names).
"""

import copy
import json
import re
from pathlib import Path

from launchcrew.facts import (
    PRODUCT_FACT_SOURCES,
    normalize,
    parse_product_facts,
)

TEMPLATE_IDS = (
    "quickstart_food",
    "quickstart_mobile_app",
    "quickstart_local_service",
)

TEMPLATE_FILES = {
    "quickstart_food": "facts/quickstart_food.json",
    "quickstart_mobile_app": "facts/quickstart_mobile_app.json",
    "quickstart_local_service": "facts/quickstart_local_service.json",
}

TEMPLATE_KINDS = {
    "quickstart_food": "food",
    "quickstart_mobile_app": "mobile_app",
    "quickstart_local_service": "local_service",
}

FICTIONAL_NOTE_KEYWORD = "Fictional example"


def _repo_root_here():
    return Path(__file__).resolve().parents[1]


def list_quickstart_templates():
    """Return stable template metadata without reading file bodies."""
    out = []
    for template_id in TEMPLATE_IDS:
        path = _repo_root_here() / TEMPLATE_FILES[template_id]
        try:
            body = json.loads(path.read_text(encoding="utf-8"))
            title = body.get("title", template_id)
        except (OSError, ValueError):
            title = template_id
        out.append(
            {
                "template_id": template_id,
                "title": title,
                "kind": TEMPLATE_KINDS[template_id],
                "fictional": True,
                "confirmation_required": True,
            }
        )
    return out


def load_quickstart_template(template_id):
    """Load one template file and validate its foundation contract.

    Raises KeyError for unknown ids and ValueError when the file breaks
    the unconfirmed fictional format. Never confirms anything.
    """
    if template_id not in TEMPLATE_FILES:
        raise KeyError("Unknown quick-start template: %r" % (template_id,))
    path = _repo_root_here() / TEMPLATE_FILES[template_id]
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError("Quick-start template unreadable: %s" % template_id) from exc
    except ValueError as exc:
        raise ValueError("Quick-start template is not valid JSON: %s" % template_id) from exc
    if not isinstance(body, dict):
        raise ValueError("Quick-start template must be an object: %s" % template_id)
    if body.get("template_id") != template_id:
        raise ValueError("Quick-start template id mismatch in %s" % template_id)
    if body.get("fictional") is not True:
        raise ValueError("Quick-start template must be labeled fictional: %s" % template_id)
    if body.get("confirmation_required") is not True:
        raise ValueError("Quick-start template must require confirmation: %s" % template_id)
    note = body.get("fictional_note", "")
    if FICTIONAL_NOTE_KEYWORD.lower() not in str(note).lower():
        raise ValueError("Quick-start template needs a fictional-example note: %s" % template_id)
    if "unconfirmed" not in str(note).lower():
        raise ValueError("Quick-start template note must say values are unconfirmed: %s" % template_id)
    # Existing facts-file key names, honestly empty: no example claim is
    # approved, so nothing here can be mistaken for evidence.
    if body.get("approved_claims") != []:
        raise ValueError("Quick-start template must keep approved_claims empty: %s" % template_id)
    sources = body.get("sources")
    if (
        not isinstance(sources, list)
        or not sources
        or not all(isinstance(s, str) for s in sources)
        or "unconfirmed" not in " ".join(sources).lower()
    ):
        raise ValueError("Quick-start template needs unconfirmed source labels: %s" % template_id)
    # Fail closed on the legacy evidence path: the file must never load
    # as approved facts.
    from launchcrew.facts import load_facts

    try:
        load_facts(path)
    except ValueError:
        pass
    else:
        raise ValueError("Quick-start template must not load as approved facts: %s" % template_id)
    suggested = body.get("suggested_facts")
    if not isinstance(suggested, dict):
        raise ValueError("Quick-start template needs a suggested_facts object: %s" % template_id)
    _assert_all_unconfirmed(suggested, template_id)
    # Reuse the owner intake contract as a format gate: the suggested
    # body must parse cleanly and yield zero confirmed claims.
    parsed = parse_product_facts(copy.deepcopy(suggested))
    if parsed["confirmed_claims"]:
        raise ValueError("Quick-start template must not confirm claims: %s" % template_id)
    return copy.deepcopy(body)


def quickstart_suggestions(template_id):
    """Return a deep copy of the suggested product-facts input.

    The copy is safe to hand to ``parse_product_facts`` or to prefill an
    intake form as unconfirmed values. All ``confirmed`` flags are False.
    """
    body = load_quickstart_template(template_id)
    return copy.deepcopy(body["suggested_facts"])


def apply_quickstart_selection(template_id):
    """Selection helper: loading a template is not confirmation.

    Returns the suggested facts unchanged (still unconfirmed). Prefer
    :func:`build_prefill` for new wiring so the per-field provenance
    travels with the selection; the intake seam must still require
    explicit per-field owner review and confirmation, and must call
    :func:`assert_template_review_complete` with server-retained
    provenance on submit: this helper does not enforce edits itself.
    """
    suggested = quickstart_suggestions(template_id)
    _assert_all_unconfirmed(suggested, template_id)
    return suggested


def iter_template_values():
    """Yield every raw example value across all templates (founder note included)."""
    for template_id in TEMPLATE_IDS:
        body = load_quickstart_template(template_id)
        suggested = body["suggested_facts"]
        for name in ("material", "contents", "size", "price", "founder_note"):
            entry = suggested.get(name)
            if isinstance(entry, dict) and entry.get("value"):
                yield entry["value"]
        for item in suggested.get("allowed_claims", []):
            if isinstance(item, dict) and item.get("value"):
                yield item["value"]


def iter_provenance_keys(suggested):
    """Yield stable per-field keys for a suggested-facts object.

    Keys are ``material``, ``contents``, ``size``, ``price``,
    ``founder_note``, and ``allowed_claims[i]``. The same scheme is used
    by the frontend prefill so both sides address the same fields.
    """
    for name in ("material", "contents", "size", "price", "founder_note"):
        entry = suggested.get(name)
        if isinstance(entry, dict) and entry.get("value"):
            yield name
    claims = suggested.get("allowed_claims", [])
    if isinstance(claims, list):
        for index, item in enumerate(claims):
            if isinstance(item, dict) and item.get("value"):
                yield "allowed_claims[%d]" % index


def build_prefill(template_id):
    """Build the selection envelope for one template.

    Returns ``{"template_id", "suggested_facts", "provenance"}`` where the
    facts are all unconfirmed with ``demo_template`` provenance and the
    provenance maps each prefilled field key to ``{"template_id",
    "example_value", "owner_attested": False}``.

    The backend integration MUST persist ``provenance`` server-side
    (session or run state) when the owner picks a template and MUST pass
    that server copy, never a client-supplied copy, to
    :func:`assert_template_review_complete` on submit. Frontend state is
    not an enforcement boundary: a client can drop or forge provenance,
    so only the server-retained record counts.
    """
    body = load_quickstart_template(template_id)
    suggested = copy.deepcopy(body["suggested_facts"])
    provenance = {
        key: {"template_id": template_id, "example_value": _example_for_key(suggested, key),
              "owner_attested": False}
        for key in iter_provenance_keys(suggested)
    }
    return {"template_id": template_id, "suggested_facts": suggested, "provenance": provenance}


def _example_for_key(suggested, key):
    entry = _entry_for_key(suggested, key)
    return entry.get("value", "") if isinstance(entry, dict) else ""


def _entry_for_key(container, key):
    if not isinstance(container, dict):
        return None
    if key.startswith("allowed_claims["):
        try:
            index = int(key[len("allowed_claims["):-1])
        except (ValueError, IndexError):
            return None
        claims = container.get("allowed_claims")
        if isinstance(claims, list) and 0 <= index < len(claims):
            return claims[index]
        return None
    return container.get(key)


def attest_prefill_field(provenance, key):
    """Record explicit per-field owner review of one prefilled example.

    This is a server-side helper: the backend calls it when the owner
    takes the explicit "I reviewed this suggestion" action for a field
    (a control separate from the confirmation checkbox), and persists
    the updated provenance. Returns a copy with ``owner_attested`` True
    for that key. Raises KeyError for unknown keys.
    """
    if not isinstance(provenance, dict) or key not in provenance:
        raise KeyError("Unknown prefilled field: %r" % (key,))
    updated = copy.deepcopy(provenance)
    updated[key] = dict(updated[key])
    updated[key]["owner_attested"] = True
    return updated


_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(text):
    return _TOKEN_RE.findall((text or "").lower())


def _token_edit_distance(a, b):
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _is_still_example(value, example):
    """True when a submitted value is the example, verbatim or trivially edited.

    Normalized equality covers case, punctuation, and whitespace-only
    tweaks. A token edit distance of 2 or less covers pluralization,
    single-word swaps, and other tweaks that do not amount to the owner
    writing their own fact. An edit never proves review on its own.
    """
    if normalize(value) == normalize(example):
        return True
    a, b = _tokens(value), _tokens(example)
    if not a or not b:
        return True
    return _token_edit_distance(a, b) <= 2


def find_unreviewed_template_fields(product_facts_input, provenance):
    """Check confirmed template-derived fields against server provenance.

    Only fields present in ``provenance`` are examined: ordinary facts
    submitted without ever using a template are NEVER flagged, even when
    their text coincides with an example. Each flagged item is
    ``{"field", "reason", "value"}`` with reason one of:

    - ``unchanged_example``: confirmed value still matches the example.
    - ``trivially_modified``: confirmed value differs only trivially.
    - ``provenance_not_updated``: confirmed value keeps ``demo_template``
      provenance instead of a genuine source.

    A template-derived field passes when the owner substantively replaced
    the value with a genuine source, or explicitly attested the field
    (via :func:`attest_prefill_field`) with a genuine source. The
    confirmation checkbox alone never suffices for template fields.
    """
    flagged = []
    if not isinstance(product_facts_input, dict) or not isinstance(provenance, dict):
        return flagged
    for key, record in provenance.items():
        if not isinstance(record, dict):
            continue
        entry = _entry_for_key(product_facts_input, key)
        if not isinstance(entry, dict) or entry.get("confirmed") is not True:
            continue
        value = entry.get("value")
        if not isinstance(value, str) or not value.strip():
            continue
        example = record.get("example_value", "")
        attested = record.get("owner_attested") is True
        if entry.get("source", "owner") == "demo_template":
            flagged.append({"field": key, "reason": "provenance_not_updated", "value": value})
        elif _is_still_example(value, example):
            if attested:
                continue
            reason = ("unchanged_example"
                      if normalize(value) == normalize(example)
                      else "trivially_modified")
            flagged.append({"field": key, "reason": reason, "value": value})
    return flagged


def assert_template_review_complete(product_facts_input, provenance):
    """Fail closed on unreviewed template-derived confirmations.

    Call this on submit with the SERVER-RETAINED provenance, after
    ``parse_product_facts``, before any draft, check, or receipt treats
    the input as evidence. Raises ValueError naming each offending
    field. Pass an empty provenance when no template was used: ordinary
    facts are then never blocked.
    """
    bad = find_unreviewed_template_fields(product_facts_input, provenance)
    if bad:
        raise ValueError(
            "Quick-start review incomplete; review, replace, or attest each listed field: %r"
            % ([item["field"] + ":" + item["reason"] for item in bad],)
        )


def _assert_all_unconfirmed(suggested, template_id):
    for name in ("material", "contents", "size", "price", "founder_note"):
        entry = suggested.get(name)
        if entry is None:
            continue
        if not isinstance(entry, dict):
            raise ValueError("Quick-start %s field %r must be an object" % (template_id, name))
        if entry.get("confirmed") is not False:
            raise ValueError(
                "Quick-start %s field %r must ship unconfirmed" % (template_id, name)
            )
        source = entry.get("source", "demo_template")
        if source not in PRODUCT_FACT_SOURCES:
            raise ValueError(
                "Quick-start %s field %r has an unsupported source" % (template_id, name)
            )
    claims = suggested.get("allowed_claims", [])
    if not isinstance(claims, list) or not claims:
        raise ValueError("Quick-start %s needs a nonempty allowed_claims list" % template_id)
    for index, item in enumerate(claims):
        if not isinstance(item, dict):
            raise ValueError(
                "Quick-start %s claim %d must be an object" % (template_id, index)
            )
        if item.get("confirmed") is not False:
            raise ValueError(
                "Quick-start %s claim %d must ship unconfirmed" % (template_id, index)
            )
        source = item.get("source", "demo_template")
        if source not in PRODUCT_FACT_SOURCES:
            raise ValueError(
                "Quick-start %s claim %d has an unsupported source" % (template_id, index)
            )
