"""Central allowlisted model metadata. Pure, no network, no secrets."""
from urllib.parse import urlsplit

STANDARD_SPARK_MODELS = frozenset({'muse-spark-1.3', 'muse-spark-1.2', 'muse-spark-1.1'})
CONTRIBUTOR_SPARK_MODELS = frozenset({'muse-spark-1.3-contributor', 'muse-spark-1.2-contributor'})
STANDARD_WONDER_MODELS = frozenset({'muse-wonder-1.0'})

DATA_BASIS_V2 = 'v2'

NOT_SENT_NOTE = 'No model request was attempted on this run, so nothing was sent.'
STANDARD_NOTE = ('Standard request variant only on this run to the documented Meta endpoint. '
                 'Current Standard documentation describes this variant as not used for training. '
                 'This describes the request variant, not an independent certification of provider privacy behavior. '
                 'Applies to actual requests on this run, not to current configuration.')
CONTRIBUTOR_NOTE = ('Contributor request variant on this run. '
                    'Content sent to a Contributor variant may be used as training data; '
                    'sending it gives permission to train. No Standard no-train claim applies.')
MIXED_NOTE = ('Mixed Standard and Contributor requests on this run to the documented Meta endpoint. '
              'Contributor content may be used as training data; sending it gives permission to train. '
              'No single no-train claim applies.')
UNKNOWN_NOTE = ('Unknown request variant or endpoint on this run. '
                'No training guarantee is claimed; treat content as if it may be used for training.')


def request_provider_from_base_url(raw):
    """Allowlisted request provider. Returns 'meta' or 'unknown'. Never echoes input."""
    if raw is None:
        return 'meta'
    if not isinstance(raw, str):
        return 'unknown'
    text = raw.strip()
    if not text:
        return 'meta'
    try:
        parts = urlsplit(text)
    except Exception:
        return 'unknown'
    try:
        scheme = (parts.scheme or '').lower()
        host = (parts.hostname or '').lower()
        if scheme != 'https':
            return 'unknown'
        if host != 'api.meta.ai':
            return 'unknown'
        if parts.username or parts.password:
            return 'unknown'
        port = parts.port
        if port is not None and port != 443:
            return 'unknown'
        return 'meta'
    except Exception:
        return 'unknown'


def variant_for_attempt(kind, attempted_model):
    if not isinstance(attempted_model, str):
        return 'unknown'
    if kind == 'wonder':
        return 'standard' if attempted_model in STANDARD_WONDER_MODELS else 'unknown'
    if attempted_model in STANDARD_SPARK_MODELS or attempted_model in STANDARD_WONDER_MODELS:
        return 'standard'
    if attempted_model in CONTRIBUTOR_SPARK_MODELS:
        return 'contributor'
    return 'unknown'


def data_mode_for_attempts(pairs):
    """Pairs are (variant, provider). Missing or non-meta provider fails closed to unknown."""
    if not pairs:
        return ('not_sent', NOT_SENT_NOTE, 'none')
    providers = [p if isinstance(p, str) else 'unknown' for _, p in pairs]
    variants = [v for v, _ in pairs]
    aggregate = 'meta' if providers and all(p == 'meta' for p in providers) else 'unknown'
    if aggregate != 'meta':
        return ('unknown', UNKNOWN_NOTE, aggregate)
    unique = set(variants)
    if unique == {'standard'}:
        return ('standard_no_train', STANDARD_NOTE, aggregate)
    if unique == {'contributor'}:
        return ('contributor', CONTRIBUTOR_NOTE, aggregate)
    if unique == {'standard', 'contributor'}:
        return ('mixed', MIXED_NOTE, aggregate)
    return ('unknown', UNKNOWN_NOTE, aggregate)


def sanitize_model_name(name):
    if isinstance(name, str) and (name in STANDARD_SPARK_MODELS
                                  or name in CONTRIBUTOR_SPARK_MODELS
                                  or name in STANDARD_WONDER_MODELS):
        return name
    return 'unknown'
