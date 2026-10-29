"""Additional campaign angles beyond the existing seven.

Pure standard library helpers. No model calls, no fetching, no
publishing, no photo behavior.

The existing seven angles live in the campaign week setup. This module
supplies five more named angles, each with a distinct brief template
and one hook template. Factual slots are filled only from
caller-supplied explicitly confirmed facts. Templates never invent
values and never auto-confirm. When required facts are missing or a
filled hook would exceed its limit, rendering returns a
suggestion and needs-owner-confirmation state with no brief or hook.
"""

import copy
import re

MODULE_VERSION = "campaign-angles/v1"
HOOK_MAX_CHARS = 140
BRIEF_MAX_CHARS = 280

EXISTING_ANGLES = (
    "Origin story",
    "Material and craft",
    "Commuter use",
    "Styling",
    "Care and durability",
    "Social proof",
    "Launch offer",
)

ADDITIONAL_ANGLES = (
    "Gift ready",
    "Workday carry",
    "Weekend carry",
    "Repair and reuse",
    "Founder note",
)

ALLOWED_SLOTS = ("product", "material", "price", "design")

SLOT_RE = re.compile(r"\{(\w+)\}")

ANGLE_TEMPLATES = {
    "Gift ready": {
        "brief_template": "Gift pick: {product} at {price}.",
        "hook_template": "Gift idea: {product} at {price}.",
        "required_facts": ["product", "price"],
        "description": "Gift positioning using only confirmed product and price.",
    },
    "Workday carry": {
        "brief_template": "Workday carry: {product}, {design}.",
        "hook_template": "For the workday: {product}, {design}.",
        "required_facts": ["product", "design"],
        "description": "Workday use using only confirmed product and design.",
    },
    "Weekend carry": {
        "brief_template": "Weekend carry in {material}: {product}.",
        "hook_template": "Weekend carry: {product} in {material}.",
        "required_facts": ["product", "material"],
        "description": "Weekend use using only confirmed product and material.",
    },
    "Repair and reuse": {
        "brief_template": "Made to keep: {material}, {design}.",
        "hook_template": "Built to keep: {material}, {design}.",
        "required_facts": ["material", "design"],
        "description": "Keep and reuse using only confirmed material and design.",
    },
    "Founder note": {
        "brief_template": "From the founder: {product}, {design}, {price}.",
        "hook_template": "Founder note: {product}, {price}.",
        "required_facts": ["product", "design", "price"],
        "description": "Founder voice using only confirmed product, design, and price.",
    },
}


def list_existing_angles():
    """Return the existing seven angle names in order."""
    return list(EXISTING_ANGLES)


def list_additional_angles():
    """Return the five additional angle names in order."""
    return list(ADDITIONAL_ANGLES)


def get_angle_detail(angle_name):
    """Return a copy of one angle template detail.

    Raises ValueError for unknown names. The returned dict is a copy;
    editing it never changes the module templates.
    """
    if not isinstance(angle_name, str):
        raise TypeError("angle_name must be a string")
    detail = ANGLE_TEMPLATES.get(angle_name)
    if detail is None:
        raise ValueError("Unknown campaign angle: " + angle_name)
    result = copy.deepcopy(detail)
    result["angle"] = angle_name
    return result


def _cleaned_facts(confirmed_facts):
    """Return (cleaned dict, error). Never mutates the caller input."""
    if not isinstance(confirmed_facts, dict):
        return {}, "Confirmed facts must be a dict of slot to verified string."
    cleaned = {}
    for key, value in confirmed_facts.items():
        if not isinstance(key, str):
            continue
        if not isinstance(value, str):
            continue
        text = value.strip()
        if not text:
            continue
        cleaned[key] = text
    return cleaned, None


def _metadata(angle_name, used_facts, brief_chars, hook_chars):
    return {
        "module": MODULE_VERSION,
        "source": "caller_confirmed_facts",
        "angle": angle_name,
        "limits": {"hook_max_chars": HOOK_MAX_CHARS, "brief_max_chars": BRIEF_MAX_CHARS},
        "used_facts": list(used_facts),
        "brief_chars": brief_chars,
        "hook_chars": hook_chars,
        "note": (
            "Factual slots use only caller confirmed facts. Templates "
            "never invent values and never auto-confirm."
        ),
    }


def _needs_confirmation(angle_name, missing, suggestion, used_facts=()):
    ordered_missing = list(missing)
    return {
        "angle": angle_name,
        "status": "needs_owner_confirmation",
        "state": "suggestion",
        "brief": None,
        "hook": None,
        "missing_facts": ordered_missing,
        "suggestion": suggestion,
        "metadata": _metadata(angle_name, list(used_facts), 0, 0),
    }


def render_angle(angle_name, confirmed_facts):
    """Render one angle brief and hook from confirmed facts only.

    On success returns status ready with brief and hook strings. When
    required facts are missing, when facts have the wrong shape, or
    when a filled hook or brief would exceed its limit, returns status
    needs_owner_confirmation with state suggestion and no brief or
    hook. Never invents a fact value.
    """
    if not isinstance(angle_name, str):
        raise TypeError("angle_name must be a string")
    detail = ANGLE_TEMPLATES.get(angle_name)
    if detail is None:
        raise ValueError("Unknown campaign angle: " + angle_name)
    required = list(detail["required_facts"])
    cleaned, shape_error = _cleaned_facts(confirmed_facts)
    if shape_error is not None:
        return _needs_confirmation(
            angle_name,
            required,
            "Needs owner confirmation for: "
            + ", ".join(required)
            + ". Provide confirmed facts as a dict of slot to verified string. "
            "No brief or hook generated.",
        )
    missing = [slot for slot in required if slot not in cleaned]
    if missing:
        return _needs_confirmation(
            angle_name,
            missing,
            "Needs owner confirmation for: "
            + ", ".join(missing)
            + ". No brief or hook generated.",
            used_facts=[s for s in required if s in cleaned],
        )
    slots_needed = set(SLOT_RE.findall(detail["brief_template"]))
    slots_needed.update(SLOT_RE.findall(detail["hook_template"]))
    unfilled = sorted(s for s in slots_needed if s not in cleaned)
    if unfilled:
        return _needs_confirmation(
            angle_name,
            unfilled,
            "Needs owner confirmation for: "
            + ", ".join(unfilled)
            + ". No brief or hook generated.",
            used_facts=[s for s in required if s in cleaned],
        )
    values = {slot: cleaned[slot] for slot in slots_needed}
    brief = detail["brief_template"].format(**values)
    hook = detail["hook_template"].format(**values)
    if len(hook) > HOOK_MAX_CHARS:
        return _needs_confirmation(
            angle_name,
            [],
            "Hook is %d characters, over the 140 character limit. "
            "Needs owner confirmation with shorter confirmed facts. "
            "No brief or hook generated." % len(hook),
            used_facts=required,
        )
    if len(brief) > BRIEF_MAX_CHARS:
        return _needs_confirmation(
            angle_name,
            [],
            "Brief is %d characters, over the 280 character limit. "
            "Needs owner confirmation with shorter confirmed facts. "
            "No brief or hook generated." % len(brief),
            used_facts=required,
        )
    if SLOT_RE.search(brief) or SLOT_RE.search(hook):
        return _needs_confirmation(
            angle_name,
            [],
            "Unfilled template slot remains. Needs owner confirmation. "
            "No brief or hook generated.",
            used_facts=required,
        )
    return {
        "angle": angle_name,
        "status": "ready",
        "state": "ready",
        "brief": brief,
        "hook": hook,
        "missing_facts": [],
        "suggestion": None,
        "metadata": _metadata(angle_name, required, len(brief), len(hook)),
    }


def render_all_angles(confirmed_facts):
    """Render all five additional angles in deterministic order."""
    cleaned, _ = _cleaned_facts(confirmed_facts)
    angles = {}
    for name in ADDITIONAL_ANGLES:
        angles[name] = render_angle(name, confirmed_facts)
    provenance = {
        "module": MODULE_VERSION,
        "source": "caller_confirmed_facts",
        "existing_angles": list(EXISTING_ANGLES),
        "additional_angles": list(ADDITIONAL_ANGLES),
        "confirmed_keys": sorted(cleaned),
        "limits": {"hook_max_chars": HOOK_MAX_CHARS, "brief_max_chars": BRIEF_MAX_CHARS},
        "note": (
            "Five angles beyond the existing seven. Factual slots use "
            "only caller confirmed facts. Missing facts yield a "
            "suggestion state, never invented text."
        ),
    }
    return {"angles": angles, "provenance": provenance}


def validate_hook(hook_text):
    """Validate one hook: single line, no slots, at most 140 chars."""
    limit = HOOK_MAX_CHARS
    if not isinstance(hook_text, str):
        return {
            "ok": False,
            "char_count": 0,
            "limit": limit,
            "reasons": ["Hook must be a string."],
        }
    reasons = []
    char_count = len(hook_text)
    if not hook_text.strip():
        reasons.append("Empty hook.")
    if char_count > limit:
        reasons.append("Exceeds %d characters (%d chars)." % (limit, char_count))
    if "\n" in hook_text or "\r" in hook_text:
        reasons.append("Hook must be a single line.")
    if SLOT_RE.search(hook_text):
        reasons.append("Hook contains an unfilled slot.")
    return {
        "ok": not reasons,
        "char_count": char_count,
        "limit": limit,
        "reasons": reasons,
    }
