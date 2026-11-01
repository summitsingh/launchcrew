"""Provider metrics pull domain logic (standard library only).

Only VERIFIED deliveries (delivery_state == "verified") may pull
provider metrics. Every canonical metric in CANONICAL_METRICS is
reported as either a nonnegative integer or the exact literal string
NOT_REPORTED ("not reported"). Unsupported or omitted metrics are
never coerced to a fake 0.

Each platform declares which metrics it offers via
PLATFORM_REPORTED_METRICS. When no explicit provider payload is
passed, a deterministic adapter returns stable per-channel integers
for supported metrics (no network, no clock dependence beyond the
caller-supplied fetch time).
"""

from datetime import datetime, timezone

CANONICAL_METRICS = ("reach", "likes", "comments", "clicks", "shares")

NOT_REPORTED = "not reported"

REFRESH_MODES = ("manual", "scheduled")

MODULE_VERSION = "analytics-pull/v1"

PLATFORM_REPORTED_METRICS = {
    "instagram": ("reach", "likes", "comments", "shares"),
    "x": ("reach", "likes", "comments", "clicks", "shares"),
    "tiktok": ("reach", "likes", "comments", "shares"),
    "youtube": ("reach", "likes", "comments"),
    "linkedin": ("reach", "likes", "comments", "clicks", "shares"),
    "facebook": ("reach", "likes", "comments", "clicks", "shares"),
}

DEFAULT_SOURCE_LABELS = {
    "instagram": "instagram_graph_api",
    "x": "x_analytics_api",
    "tiktok": "tiktok_research_api",
    "youtube": "youtube_analytics_api",
    "linkedin": "linkedin_analytics_api",
    "facebook": "facebook_graph_api",
}

_MAX_COUNT = 1000000
_MAX_SOURCE_LABEL = 120

_ADAPTER_BASE = {"reach": 800, "likes": 40, "comments": 5, "clicks": 20, "shares": 3}
_ADAPTER_SPAN = {"reach": 900, "likes": 160, "comments": 45, "clicks": 120, "shares": 30}


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def normalize_channel(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("channel must be a nonempty string")
    return value.strip().lower()


def normalize_refresh_mode(value):
    if value not in REFRESH_MODES:
        raise ValueError("refresh_mode must be one of manual, scheduled")
    return value


def normalize_source_label(value, channel):
    if value is None:
        return default_source_label(channel)
    if not isinstance(value, str) or not value.strip():
        raise ValueError("source_label must be a nonempty string")
    cleaned = value.strip()
    if len(cleaned) > _MAX_SOURCE_LABEL:
        raise ValueError("source_label must be 120 characters or fewer")
    for char in cleaned:
        code = ord(char)
        if code < 32 or code == 127:
            raise ValueError("source_label contains unsafe control characters")
    return cleaned


def default_source_label(channel):
    key = normalize_channel(channel)
    return DEFAULT_SOURCE_LABELS.get(key, key + "_analytics_api")


def supported_metrics_for(channel):
    key = normalize_channel(channel)
    if key in PLATFORM_REPORTED_METRICS:
        return tuple(PLATFORM_REPORTED_METRICS[key])
    return CANONICAL_METRICS


def normalize_provider_metrics(value):
    """Validate an explicit provider response payload.

    Accepts None (meaning no override; the adapter supplies values)
    or a dict mapping a subset of canonical metric names to integers
    or None. Unknown metric names, booleans, negative values, floats,
    and other non-integer values fail closed with ValueError. Omitted
    keys and None values both mean "not reported by the provider".
    """
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("provider_metrics must be an object")
    cleaned = {}
    for key, entry in value.items():
        if key not in CANONICAL_METRICS:
            raise ValueError("provider_metrics has unknown metric: " + str(key))
        if entry is None:
            continue
        if type(entry) is not int:
            raise ValueError("provider_metrics[%s] must be an integer or null" % key)
        if entry < 0 or entry > _MAX_COUNT:
            raise ValueError("provider_metrics[%s] must be 0 to 1000000" % key)
        cleaned[key] = entry
    return cleaned


def adapter_metrics(channel):
    """Deterministic per-platform pull used when no override is passed.

    Returns integers for supported metrics only; unsupported metrics
    are absent so the caller records them as NOT_REPORTED.
    """
    key = normalize_channel(channel)
    seed = sum(ord(char) for char in key)
    result = {}
    for index, metric in enumerate(supported_metrics_for(key)):
        span = _ADAPTER_SPAN[metric]
        result[metric] = _ADAPTER_BASE[metric] + ((seed * (index + 7)) % span)
    return result


def build_metrics(channel, provider_metrics=None):
    """Build the honest canonical metrics dict for one channel.

    Every canonical metric maps to either an integer or the exact
    string NOT_REPORTED. A metric keeps its integer only when the
    platform supports it AND the provider response carries an
    integer for it. Anything else (unsupported, omitted, or null)
    is NOT_REPORTED, never 0.
    """
    supplied = normalize_provider_metrics(provider_metrics)
    effective = dict(supplied) if supplied is not None else adapter_metrics(channel)
    supported = set(supported_metrics_for(channel))
    metrics = {}
    for metric in CANONICAL_METRICS:
        value = effective.get(metric)
        if metric in supported and type(value) is int and value >= 0:
            metrics[metric] = value
        else:
            metrics[metric] = NOT_REPORTED
    reported = [metric for metric in CANONICAL_METRICS
                if metrics[metric] != NOT_REPORTED]
    unreported = [metric for metric in CANONICAL_METRICS
                  if metrics[metric] == NOT_REPORTED]
    return {"metrics": metrics, "reported_metrics": reported,
            "unreported_metrics": unreported}


def metric_parts(channel, metrics):
    """Plain-language per-metric parts, e.g. "1240 reach" or "clicks: not reported"."""
    parts = []
    for metric in CANONICAL_METRICS:
        value = (metrics or {}).get(metric, NOT_REPORTED)
        if type(value) is int:
            parts.append("%d %s" % (value, metric))
        else:
            parts.append("%s: %s" % (metric, NOT_REPORTED))
    return parts


def summary_text(channel, metrics):
    """One-line badge summary, e.g. "instagram: 1240 reach, clicks: not reported"."""
    return normalize_channel(channel) + ": " + ", ".join(metric_parts(channel, metrics))


def build_channel_badge(channel, source_label, fetched_at, refresh_mode, metrics):
    return {"channel": normalize_channel(channel),
            "source_label": normalize_source_label(source_label, channel),
            "fetched_at": fetched_at,
            "refresh_mode": normalize_refresh_mode(refresh_mode),
            "metrics": dict(metrics)}


def build_outcome_badge(channel_badges):
    """Calendar outcome badge: per-channel summaries plus one summary line."""
    badges = list(channel_badges or [])
    summaries = [summary_text(entry["channel"], entry.get("metrics") or {})
                 for entry in badges]
    return {"has_outcomes": len(badges) > 0,
            "channel_badges": badges,
            "summary_text": " | ".join(summaries)}


def outcome_note(source_label, fetched_at, channel, metrics):
    """Outcome-log note labeling a provider pull with source and fetch time."""
    return ("Provider pull %s at %s for %s: %s. "
            "Unreported metrics show as not reported, never zero."
            % (source_label, fetched_at, normalize_channel(channel),
               ", ".join(metric_parts(channel, metrics))))
