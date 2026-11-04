"""Autonomous Ready-slot publish executor domain logic (standard library only).

Execution runs only on calendar slots in Ready state, at the slot
scheduled time, with no per-post tap. There is no path from unapproved
content to a publish call: the executor re-checks the approval binding
at execution time, and any mismatch or later edit means the slot is no
longer Ready, so the executor skips it and marks it needs-approval.

Per channel, publishing goes through the official platform API with the
approved variant and the slot media, under a deterministic idempotency
key per (slot, channel, binding digest) so a retry can never duplicate
a post. Failures retry automatically at most twice with backoff, then
the slot channel moves to failed with a plain-language reason and any
further retry is the owner explicit action. Platform success alone
records posted and hands off to S5 verification; it never marks a slot
verified. The owner kill switch pauses all execution without touching
calendar slots or packs.
"""

import hashlib
import os
from datetime import datetime, timezone

EXECUTION_STATUSES = ('pending', 'posted', 'failed', 'skipped_needs_approval',
                      'paused_by_kill_switch')

MAX_AUTO_RETRIES = 2
BACKOFF_SECONDS = [2, 5]

MODULE_VERSION = 'publish-executor/v1'

REVOKED_TOKEN_REASON = ('Publish failed: the brand account token was revoked or expired. '
                        'Reconnect the brand account, then retry.')
NOT_CONNECTED_REASON = ('Publish failed: no connected brand account for this channel. '
                        'Connect the brand account, then retry.')
DISCONNECTED_REASON = ('Publish failed: the brand account is disconnected. '
                       'Reconnect the brand account, then retry.')
SIMULATED_FAILURE_REASON = ('Publish failed: simulated provider error (revoked_token). '
                            'Reconnect the brand account, then retry.')

_REVOKED_TEST_TOKEN = 'revoked_test_token'


class PublishTransportError(ValueError):
    """A publish attempt failed with a plain-language owner-facing reason."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason
        self.simulated = False


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def normalize_channel(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('channel must be a nonempty string')
    return value.strip().lower()


def idempotency_key(slot_id, channel, binding_digest):
    """Deterministic key per (slot, channel, binding digest).

    A retry under the same key can never duplicate a post: when an
    execution with this key already succeeded, later calls return the
    existing result without re-posting. Any binding change alters the
    digest, so edited content never reuses a prior key.
    """
    if not isinstance(slot_id, str) or not slot_id:
        raise ValueError('slot_id must be a nonempty string')
    channel_key = normalize_channel(channel)
    digest = binding_digest if isinstance(binding_digest, str) and binding_digest else 'unbound'
    raw = (slot_id + ':' + channel_key + ':' + digest).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()


def backoff_before_attempt(attempt_number):
    """Seconds recorded as waited before the given 1-based attempt.

    The initial attempt waits 0 seconds; each automatic retry records
    the configured backoff delay. Recording only: the request-scoped
    executor never sleeps.
    """
    if not isinstance(attempt_number, int) or attempt_number < 1:
        raise ValueError('attempt_number must be a positive integer')
    if attempt_number == 1:
        return 0
    index = attempt_number - 2
    if index < len(BACKOFF_SECONDS):
        return BACKOFF_SECONDS[index]
    return BACKOFF_SECONDS[-1]


def attempts_exhausted(attempt_count, max_auto_retries=MAX_AUTO_RETRIES):
    """True once 1 initial attempt plus the allowed auto retries ran."""
    return int(attempt_count or 0) >= 1 + int(max_auto_retries)


def build_attempt(attempt_number, channel, key, outcome, platform_post_id=None,
                  live_url=None, failure_reason=None, timestamp=None):
    """One executor attempt record for the JSONB attempts trail."""
    return {
        'attempt_number': int(attempt_number),
        'timestamp': timestamp or utc_now_iso(),
        'channel': normalize_channel(channel),
        'idempotency_key': key,
        'backoff_seconds': backoff_before_attempt(int(attempt_number)),
        'outcome': outcome,
        'platform_post_id': platform_post_id,
        'live_url': live_url,
        'failure_reason': failure_reason,
    }


def append_attempt(attempts, entry):
    """Append one attempt to the ordered trail, numbering chronologically."""
    trail = list(attempts) if isinstance(attempts, list) else []
    numbered = dict(entry)
    numbered['attempt_number'] = len(trail) + 1
    numbered['backoff_seconds'] = backoff_before_attempt(numbered['attempt_number'])
    if not numbered.get('timestamp'):
        numbered['timestamp'] = utc_now_iso()
    trail.append(numbered)
    return trail


def blank_execution(slot_id, channel, key, max_auto_retries=MAX_AUTO_RETRIES):
    return {
        'slot_id': slot_id,
        'channel': normalize_channel(channel),
        'idempotency_key': key,
        'status': 'pending',
        'platform_post_id': None,
        'live_url': None,
        'attempt_count': 0,
        'max_auto_retries': int(max_auto_retries),
        'attempts': [],
        'last_error': None,
    }


def simulate_failure_requested(value):
    """Test and drill hook: only the exact revoked_token drill fails."""
    return isinstance(value, str) and value.strip() == 'revoked_token'


def default_transport(channel, variant_text, subject, connection, key,
                      simulate_failure=None):
    """Simulated publish for one channel. No platform is contacted.

    Uses the stored brand connection (encrypted server-side token,
    never echoed) and the approved variant text. Returns a dict with a
    deterministic platform_post_id, a placeholder live_url under
    example.com, and simulated True. Raises PublishTransportError with
    a plain-language reason on any failure, including revoked test
    tokens and disconnected accounts, so the executor can record
    bounded retries without duplicating posts. A live platform
    transport replaces this function per channel; see
    launchcrew.instagram_publish for the Instagram path.
    """
    channel_key = normalize_channel(channel)
    forced = simulate_failure_requested(simulate_failure) or simulate_failure_requested(
        os.environ.get('LAUNCHCREW_PUBLISH_SIMULATE_FAILURE'))
    if forced:
        raise PublishTransportError(SIMULATED_FAILURE_REASON)
    if not isinstance(connection, dict) or connection.get('status') != 'connected':
        if isinstance(connection, dict) and connection.get('status') == 'disconnected':
            raise PublishTransportError(DISCONNECTED_REASON)
        raise PublishTransportError(NOT_CONNECTED_REASON)
    if not connection.get('encrypted_token'):
        raise PublishTransportError(DISCONNECTED_REASON)
    try:
        from .social_connections import decrypt_token
        plaintext = decrypt_token(connection['encrypted_token'])
    except Exception:
        raise PublishTransportError(REVOKED_TOKEN_REASON)
    if not plaintext or plaintext.strip() == _REVOKED_TEST_TOKEN:
        raise PublishTransportError(REVOKED_TOKEN_REASON)
    seed = (key + ':' + channel_key + ':' + (variant_text or '')).encode('utf-8')
    digest = hashlib.sha256(seed).hexdigest()
    return {
        'platform_post_id': 'post_' + digest[:16],
        'live_url': 'https://' + channel_key + '.example.com/posts/' + digest[:12],
        'simulated': True,
    }
