"""Optional Scout synthesis only. Absence or failure never blocks Spark fallback."""
import os
from .spark import _call


def wonder_synthesize_for_scout(text, fallback_callable, scout_profile=None, *, admission=None):
    model = os.environ.get('META_WONDER_MODEL', '').strip()
    if not model:
        return None
    system = 'Scout synthesis only. Use supplied demo facts; mark other claims unverified.'
    if isinstance(scout_profile, dict):
        try:
            extra = '\n'.join([str(scout_profile.get('name', '')), str(scout_profile.get('role', '')),
                               str(scout_profile.get('personality', '')),
                               *[str(item) for item in scout_profile.get('decision_rules', [])],
                               str(scout_profile.get('expertise', ''))])
            system = system + '\nScout profile:\n' + extra
        except Exception:
            system = 'Scout synthesis only. Use supplied demo facts; mark other claims unverified.'
    result = _call(system, text, {'facts_used': ['approved claim'], 'risks': ['demo risk']}, model,
                 admission=admission)
    # The caller owns fallback_callable invocation so attempts can be audited once.
    return result
