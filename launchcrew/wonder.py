"""Optional Scout synthesis only. Absence or failure never blocks Spark fallback."""
import os
from .spark import _call


def wonder_synthesize_for_scout(text, fallback_callable):
    model = os.environ.get('META_WONDER_MODEL', '').strip()
    if not model:
        return None
    result = _call('Scout synthesis only. Use supplied demo facts; mark other claims unverified.',
                   text, {'facts_used': ['approved claim'], 'risks': ['demo risk']}, model)
    # The caller owns fallback_callable invocation so attempts can be audited once.
    return result if result['mode'] == 'spark' else None
