"""Per-draft voice provenance note from generation metadata.

Pure and isolated: no database, no network, no file, no environment access.
The note describes which voice samples were present as style context and
which voice snapshot version was active. Metadata only: sample identifiers
and titles are recorded, sample body text is never accepted, stored, or
echoed here.

Style boundary:
voice samples are style context only. They are never fact sources, never
factual evidence or authority, and confer no factual authority on a draft.
An empty sample list means no voice style context was present. A missing
or blank snapshot version is reported as unknown, never invented.
"""

from __future__ import annotations

from typing import Any

UNKNOWN_VERSION = "unknown"

VOICE_STYLE_NOTICE = (
    "Voice samples are style context only and never fact sources; "
    "they are never factual evidence or authority and confer no factual authority."
)


def _safe_label(value: Any) -> str | None:
    """Return a stripped non-empty string label, else None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text if text else None


def normalize_samples(samples: Any) -> list[dict[str, str | None]]:
    """Normalize untrusted sample metadata to id/title pairs.

    Only ``id`` and ``title`` are read. Every other key (body text,
    content, examples, claims) is ignored so sample wording can never
    leak into provenance. Entries that are not dicts, or dicts with
    neither a usable ``id`` nor ``title``, are skipped. Input is never
    mutated.

    Returns:
        A new list of ``{"id": str | None, "title": str | None}`` dicts
        in input order.
    """
    if samples is None:
        return []
    if not isinstance(samples, (list, tuple)):
        return []
    normalized: list[dict[str, str | None]] = []
    for entry in samples:
        if not isinstance(entry, dict):
            continue
        sample_id = _safe_label(entry.get("id"))
        title = _safe_label(entry.get("title"))
        if sample_id is None and title is None:
            continue
        normalized.append({"id": sample_id, "title": title})
    return normalized


def normalize_version(version: Any) -> str:
    """Normalize an untrusted snapshot version label.

    Returns the stripped version string, or ``"unknown"`` when the
    version is missing, blank, or not a string. Never invents a version.
    """
    label = _safe_label(version)
    return label if label is not None else UNKNOWN_VERSION


def _render_note(entries: list[dict[str, str | None]], version: str) -> str:
    if entries:
        parts: list[str] = []
        for entry in entries:
            sample_id = entry.get("id")
            title = entry.get("title")
            if sample_id and title:
                parts.append("'%s' [%s]" % (title, sample_id))
            elif sample_id:
                parts.append("[%s]" % sample_id)
            else:
                parts.append("'%s'" % title)
        count = len(entries)
        noun = "sample" if count == 1 else "samples"
        return (
            "Voice provenance: %d voice %s present as style context only "
            "(%s). Snapshot version: %s. %s"
            % (count, noun, "; ".join(parts), version, VOICE_STYLE_NOTICE)
        )
    return (
        "Voice provenance: no voice samples were present as style context. "
        "Snapshot version: %s. %s" % (version, VOICE_STYLE_NOTICE)
    )


def build_voice_provenance(samples: Any = None, snapshot_version: Any = None) -> dict[str, Any]:
    """Build an honest per-draft voice provenance record.

    Args:
        samples: Untrusted iterable of mappings carrying ``id`` and/or
            ``title`` for each voice sample present as style context.
            Body text under any other key is ignored.
        snapshot_version: Untrusted voice snapshot version label. Missing
            or blank values become ``"unknown"``.

    Returns:
        A new dict with ``sample_count`` (int), ``samples`` (list of
        ``{"id", "title"}`` in input order), ``snapshot_version`` (str),
        ``has_voice`` (bool, True only when at least one sample is
        present), ``notice`` (style-only boundary text), and ``note``
        (human-readable per-draft provenance sentence).
    """
    entries = normalize_samples(samples)
    version = normalize_version(snapshot_version)
    return {
        "sample_count": len(entries),
        "samples": entries,
        "snapshot_version": version,
        "has_voice": bool(entries),
        "notice": VOICE_STYLE_NOTICE,
        "note": _render_note(entries, version),
    }


def format_voice_provenance_note(samples: Any = None, snapshot_version: Any = None) -> str:
    """Return the per-draft provenance sentence for the given metadata."""
    return str(build_voice_provenance(samples, snapshot_version)["note"])
