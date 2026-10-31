"""Record owner-confirmed live sign-in proof for Google and Facebook.

Operator-only. Run after a real end-to-end browser sign-in for each
provider against the verified HTTPS deployment. Requires explicit
confirmation flags; refuses mocked or partial proof. Writes one row per
provider into auth_live_verifications, which lets /api/health report
enabled_verified. Until both rows exist, health stays enabled_unverified
(or disabled_demo when auth is off). No credentials, tokens, subjects,
names, or emails are accepted or stored here.
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend import auth  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description='Record live auth proof')
    parser.add_argument('--provider', required=True, choices=('google', 'facebook'))
    parser.add_argument('--owner-confirmed-live-signin', action='store_true')
    parser.add_argument('--note', default='owner-confirmed live sign-in')
    args = parser.parse_args()
    if not args.owner_confirmed_live_signin:
        print('Refused: pass --owner-confirmed-live-signin after a real browser sign-in.')
        return 2
    if os.getenv('AUTH_ENABLED', 'false').lower() != 'true':
        print('Refused: AUTH_ENABLED must be true against the verified deployment.')
        return 2
    try:
        auth.validate_config()
    except RuntimeError as error:
        print('Refused: %s' % error)
        return 2
    auth.record_live_verification(args.provider, args.note)
    verified = auth.live_verified_providers()
    print('Recorded %s. Verified providers: %s.' % (args.provider, ','.join(verified) or 'none'))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
