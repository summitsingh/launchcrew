"""Cross-post verification board domain logic (standard library only).

One delivery row per calendar slot per channel tracks a delivery state
(not_posted, posted, verified, failed), the owner-marked live URL, the
match kind of the last verification (exact, trimmed_by_rule, mismatch),
the differing field on mismatch, a plain-language failure reason, and
an ordered audit trail of timestamped attempts.

Verification compares live post content against the approved channel
variant text: exact match, capability-trimmed rule match (whole
sentences dropped on a full sentence boundary per the channel
capability, for example the X character limit), or mismatch. Mismatch
is a visible failure state, never a silent pass. Every state change
appends a new timestamped attempt entry; earlier attempts are never
overwritten.
"""

import html as html_mod
import ipaddress
import re
import socket
from datetime import datetime, timezone
from urllib.parse import urlparse

DELIVERY_STATES = ('not_posted', 'posted', 'verified', 'failed')
MATCH_KINDS = ('exact', 'trimmed_by_rule', 'mismatch')

MODULE_VERSION = 'verification-board/v1'

_URL_SCHEMES = ('http', 'https')
_MAX_FETCH_BYTES = 512 * 1024
_EXCERPT_CHARS = 280


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def normalize_channel(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('channel must be a nonempty string')
    return value.strip().lower()


def normalize_live_url(value):
    """Validate an owner-supplied live URL syntactically.

    Requires a nonempty http(s) URL with a host. Host safety (SSRF
    guard) is enforced separately at fetch time by
    :func:`assert_fetchable_host`, so marking a slot posted with a URL
    never performs DNS or network I/O on its own.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError('live_url must be a nonempty string')
    cleaned = value.strip()
    if len(cleaned) > 2000:
        raise ValueError('live_url must be 2000 characters or fewer')
    for char in cleaned:
        code = ord(char)
        if code < 32 or code == 127:
            raise ValueError('live_url contains unsafe control characters')
    parsed = urlparse(cleaned)
    if parsed.scheme not in _URL_SCHEMES or not parsed.hostname:
        raise ValueError('live_url must be an http(s) URL with a host')
    return cleaned


def normalize_optional_text(value, field_name, max_length=20000):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(field_name + ' must be a string')
    if len(value) > max_length:
        raise ValueError(field_name + ' must be %d characters or fewer' % max_length)
    for char in value:
        code = ord(char)
        if code in (0, 8, 11, 12) or code == 127:
            raise ValueError(field_name + ' contains unsafe control characters')
    return value


def assert_fetchable_host(hostname):
    """SSRF guard: refuse local, private, and unresolvable hosts before fetch."""
    lowered = hostname.strip().lower().rstrip('.')
    if lowered in ('localhost',):
        raise ValueError('live_url host is not allowed')
    try:
        infos = socket.getaddrinfo(hostname, None)
    except (socket.gaierror, UnicodeError, ValueError):
        raise ValueError('live_url host could not be resolved')
    for info in infos:
        address = info[4][0] if info[4] else ''
        try:
            parsed_ip = ipaddress.ip_address(address)
        except ValueError:
            continue
        if (parsed_ip.is_private or parsed_ip.is_loopback
                or parsed_ip.is_link_local or parsed_ip.is_multicast
                or parsed_ip.is_reserved or parsed_ip.is_unspecified):
            raise ValueError('live_url host is not allowed')


def blank_attempts():
    return []


def excerpt(text, limit=_EXCERPT_CHARS):
    if not isinstance(text, str):
        return ''
    cleaned = ' '.join(text.split())
    if len(cleaned) > limit:
        return cleaned[:limit]
    return cleaned


def build_attempt(state, live_url=None, match_kind=None, differing_field=None,
                  reason=None, live_text_excerpt='', timestamp=None,
                  attempt_number=None):
    if state not in DELIVERY_STATES:
        raise ValueError('attempt state must be one of ' + ', '.join(DELIVERY_STATES))
    if match_kind is not None and match_kind not in MATCH_KINDS:
        raise ValueError('match_kind must be one of ' + ', '.join(MATCH_KINDS))
    return {
        'attempt_number': attempt_number,
        'timestamp': timestamp or utc_now_iso(),
        'state': state,
        'live_url': live_url,
        'match_kind': match_kind,
        'differing_field': differing_field,
        'reason': reason,
        'live_text_excerpt': live_text_excerpt or '',
    }


def append_attempt(attempts, entry):
    """Append one attempt to the ordered trail, numbering it chronologically."""
    trail = list(attempts) if isinstance(attempts, list) else []
    numbered = dict(entry)
    numbered['attempt_number'] = len(trail) + 1
    if not numbered.get('timestamp'):
        numbered['timestamp'] = utc_now_iso()
    trail.append(numbered)
    return trail


def blank_delivery(slot_id, channel):
    return {
        'slot_id': slot_id,
        'channel': channel,
        'delivery_state': 'not_posted',
        'live_url': None,
        'match_kind': None,
        'differing_field': None,
        'failure_reason': None,
        'attempts': [],
    }


def approved_text_for_channel(bundle_entry):
    if not isinstance(bundle_entry, dict):
        return '', ''
    text = bundle_entry.get('text')
    subject = bundle_entry.get('subject')
    if not isinstance(text, str):
        text = ''
    if not isinstance(subject, str):
        subject = ''
    return text, subject


def trimmed_rule_text(channel, approved_text):
    """Capability-trimmed rule version of the approved text, or None."""
    from .channel_variants import apply_channel_capability
    if not isinstance(approved_text, str):
        return None
    result = apply_channel_capability(channel, approved_text)
    if result.get('blocked'):
        return None
    if result.get('trimmed'):
        return result.get('text')
    return None


def compare_live_post_to_variant(approved_text, live_text,
                                 approved_subject=None, live_subject=None,
                                 channel=None):
    """Compare live post content against the approved variant text.

    Returns a dict with delivery_state, match_kind, differing_field,
    and failure_reason. Exact text (and subject when the approved
    variant carries one) match yields verified/exact. A match against
    the capability-trimmed rule version yields verified/trimmed_by_rule.
    Any other difference yields failed/mismatch naming the differing
    field (subject when the subject differed, else text). Mismatch is
    always a visible failure, never a silent pass.
    """
    approved = approved_text if isinstance(approved_text, str) else ''
    live = live_text if isinstance(live_text, str) else ''
    approved_sub = approved_subject if isinstance(approved_subject, str) else ''
    live_sub = live_subject if isinstance(live_subject, str) else ''
    if approved_sub.strip():
        if live_sub != approved_sub:
            return {
                'delivery_state': 'failed',
                'match_kind': 'mismatch',
                'differing_field': 'subject',
                'failure_reason': 'Live post mismatch on field: subject',
            }
    else:
        approved_sub = ''
        live_sub = ''
    if live == approved:
        return {
            'delivery_state': 'verified',
            'match_kind': 'exact',
            'differing_field': None,
            'failure_reason': None,
        }
    if isinstance(channel, str) and channel.strip():
        trimmed = trimmed_rule_text(channel.strip().lower(), approved)
        if trimmed is not None and live == trimmed:
            return {
                'delivery_state': 'verified',
                'match_kind': 'trimmed_by_rule',
                'differing_field': None,
                'failure_reason': None,
            }
    return {
        'delivery_state': 'failed',
        'match_kind': 'mismatch',
        'differing_field': 'text',
        'failure_reason': 'Live post mismatch on field: text',
    }


_META_RE = re.compile(
    r'<meta\s[^>]*?(?:property|name)\s*=\s*["\']([^"\']+)["\'][^>]*?content\s*=\s*["\']([^"\']*)["\'][^>]*?>'
    r'|<meta\s[^>]*?content\s*=\s*["\']([^"\']*)["\'][^>]*?(?:property|name)\s*=\s*["\']([^"\']+)["\'][^>]*?>',
    re.I | re.S)
_TITLE_RE = re.compile(r'<title[^>]*>(.*?)</title>', re.I | re.S)
_BODY_RE = re.compile(r'<body[^>]*>(.*?)</body>', re.I | re.S)
_TAG_RE = re.compile(r'<script.*?</script>|<style.*?</style>|<[^>]+>', re.I | re.S)


def extract_live_text(html_text):
    """Extract candidate live text from fetched HTML (deterministic)."""
    if not isinstance(html_text, str):
        return '', ''
    candidates = {}
    for match in _META_RE.finditer(html_text):
        name = (match.group(1) or match.group(4) or '').strip().lower()
        content = html_mod.unescape(match.group(2) or match.group(3) or '').strip()
        if name and content and name not in candidates:
            candidates[name] = content
    for key in ('og:description', 'description', 'twitter:description'):
        if candidates.get(key):
            return candidates[key], 'meta:' + key
    title_match = _TITLE_RE.search(html_text)
    title = html_mod.unescape(title_match.group(1)).strip() if title_match else ''
    title = ' '.join(title.split())
    body_match = _BODY_RE.search(html_text)
    body_html = body_match.group(1) if body_match else html_text
    body = html_mod.unescape(_TAG_RE.sub(' ', body_html))
    body = ' '.join(body.split())
    if body:
        return body[:20000], 'body'
    if title:
        return title[:20000], 'title'
    return '', ''


def fetch_live_html(live_url, timeout_seconds=10):
    """Fetch a live URL with an SSRF guard; returns (html, fetched_url)."""
    import urllib.request
    cleaned = normalize_live_url(live_url)
    assert_fetchable_host(urlparse(cleaned).hostname or '')
    request = urllib.request.Request(
        cleaned, headers={'User-Agent': 'LaunchCrew verification check (owner-marked URL)'})
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
        content_type = ''
        try:
            content_type = response.headers.get('Content-Type', '')
        except Exception:
            content_type = ''
        if content_type and 'html' not in content_type.lower() and 'text' not in content_type.lower():
            raise ValueError('live_url did not return readable text content')
        raw = response.read(_MAX_FETCH_BYTES + 1)
    if len(raw) > _MAX_FETCH_BYTES:
        raise ValueError('live_url response was too large to verify')
    charset = 'utf-8'
    match = re.search(r'charset=([^\s;]+)', content_type or '', re.I)
    if match:
        charset = match.group(1).strip(' "\'')
    try:
        return raw.decode(charset or 'utf-8', errors='replace'), cleaned
    except (LookupError, ValueError):
        return raw.decode('utf-8', errors='replace'), cleaned


def resolve_live_content(live_url=None, live_text=None, live_subject=None,
                         fetcher=None):
    """Resolve live content from explicit text or by fetching the URL.

    Explicit live_text (or live_subject) wins so API callers and unit
    tests can verify deterministically; otherwise the live URL is
    fetched and its text/meta description/body text is extracted.
    Returns (live_text, live_subject, fetched_url_or_None).
    """
    subject = live_subject if isinstance(live_subject, str) else ''
    if isinstance(live_text, str):
        return live_text, subject, None
    if not isinstance(live_url, str) or not live_url.strip():
        raise ValueError('Provide live_text or a live_url to verify')
    fetch = fetcher or fetch_live_html
    html_text, _ = fetch(live_url.strip())
    text, _ = extract_live_text(html_text)
    return text, subject, live_url.strip()
