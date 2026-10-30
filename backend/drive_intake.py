"""Google Drive selected-file read-only intake via server authorization code.

Scope: optional named-test-user demo path for reading one app-authorized
Drive file via official Picker, returning bounded UNCONFIRMED parsed lines
for the existing owner fact confirmation flow. This module never replaces
Google identity sign-in (openid profile email only in backend/auth.py) and
never replaces pasted-text import.

Flow: signed-in Google owners start a separate user-initiated Drive
authorization-code flow that reuses the EXISTING Google identity OAuth
client and secret (GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET). Ordinary
sign-in scopes stay narrow. Drive consent requests only identity plus
drive.file necessary to validate subject and drive Picker, online with no
refresh token and no offline grant. The Drive callback URI is an exact HTTPS
LaunchCrew origin plus /api/drive-import/callback and must be registered as
an extra authorized redirect URI in the Google console. Picker still needs
a transient browser access token per official web-picker guidance; Drive API
accepts Authorization Bearer header. No tokeninfo introspection is used.

Binding: Drive state is bound to the current opaque signed-in session and
actor. The authorize step preserves the actor session without rotation and
without demo replacement. The callback rejects state, actor, session, code,
audience, issuer, expiry, subject, or granted scope mismatches before any
file read. OpenID nonce is validated by Authlib authorize_access_token from
saved state during ID token parsing; source does no separate nonce
comparison. Authlib validated ID token and userinfo are used, plus explicit
exact audience and subject checks. Arbitrary client-supplied tokeninfo is
never authoritative. Granted scope accepts only openid, email or canonical
userinfo email form, profile or canonical userinfo profile form, plus exact
drive file scope; unrelated, broad, duplicate, or ambiguous alias pairs fail
closed.

Grant: the short-lived access token is returned to the same signed-in
browser ONLY to drive official Picker, over a no-store same-origin
session-bound one-time POST claim. No token appears in URL, query,
fragment, log, cookie, persistent DB, localStorage, sessionStorage, or
public receipts. Browser holds the token in memory only. The backend keeps
a tightly bounded ephemeral in-memory grant (plaintext only until first
claim, then a nonreversible digest bound to actor, session, and expiry)
and consumes it on one selected-file POST. A per-process lock atomically
claims and consumes the grant before provider work and never spans
provider I/O. Grants live in process memory only. A restart or a rolling
update that routes authorize and claim to different tasks fails closed
with consent required and needs reauthorization via Connect Drive and
choose file again. No sticky routing is claimed. The selected-file POST
proves its token is the exact server-issued token for this client and
current actor and session; subject-only userinfo or a browser-supplied
token from another client is insufficient. Mismatched, expired, or
replayed grants are refused before Drive API calls.

Binding: every endpoint requires a Google LaunchCrew actor via backend.auth.
Demo placeholder and non-Google actors fail closed even when Drive config
exists, so status reports unavailable, config and suggestions require sign-in.
Workspace is derived server-side with store.workspace_for_actor. The API
accepts no workspace ID and no URLs, so anonymous and foreign workspace
use fails closed. Import is stateless apart from the ephemeral in-memory
grant: no database writes for file content, no Memory writes, no queue
writes, no model calls, no Meta calls.

Bounds: explicit max bytes and max requests, enforced before allocation.
Content-Length is checked before reading. Downloads stream with a hard
cap. Text over the parser bound is refused as oversize. Only Docs export
to text/plain and text/plain download are supported. Docs export uses
documented mimeType query only; files.get uses documented fields, alt,
and shared-drive params only. Optional resource key travels in
X-Goog-Drive-Resource-Keys header only, never URL. Redirects are never
followed. Hosts are pinned to Google endpoints. Deceptive MIME, non-text,
and overlong selections are refused.

Provenance: success returns status unconfirmed, source drive_file, and
product_fact_source drive_file, with a sanitized file title, MIME label,
generic selection context, and bounded unconfirmed parsed text lines for
owner UI. No provider file ID, resource key, token, bytes, or full private
file body are logged, persisted, or returned in public receipts. Live Drive
proof has not been run; status live_verified stays false. Browser holds a
transient Picker token in memory only during selection. Fake OAuth in tests
bypasses Authlib nonce validation; live consent must prove mismatch fails
closed. Rolling update overlap and canonical scope return stay live gates.
"""
import hashlib
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Literal

from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field

from backend import auth, store

DRIVE_SCOPE = 'https://www.googleapis.com/auth/drive.file'
DRIVE_OAUTH_SCOPE = 'openid profile email https://www.googleapis.com/auth/drive.file'
DRIVE_EMAIL_CANONICAL = 'https://www.googleapis.com/auth/userinfo.email'
DRIVE_PROFILE_CANONICAL = 'https://www.googleapis.com/auth/userinfo.profile'
DRIVE_ALLOWED_SCOPES = frozenset({'openid', 'profile', 'email', DRIVE_SCOPE, DRIVE_EMAIL_CANONICAL, DRIVE_PROFILE_CANONICAL})
DRIVE_ISSUERS = ('https://accounts.google.com', 'accounts.google.com')
DRIVE_CALLBACK_PATH = '/api/drive-import/callback'
DRIVE_API_HOST = 'www.googleapis.com'
DRIVE_API_BASE = 'https://www.googleapis.com/drive/v3'

DRIVE_MAX_BYTES = 200000
DRIVE_MAX_TEXT_CHARS = 10000
DRIVE_MAX_REQUESTS_PER_IMPORT = 3
DRIVE_MAX_FILE_ID_CHARS = 256
DRIVE_MAX_RESOURCE_KEY_CHARS = 256
DRIVE_MAX_TITLE_CHARS = 200
DRIVE_MAX_TOKEN_CHARS = 4096
DRIVE_GRANT_TTL_SECONDS = 600
DRIVE_PENDING_TTL_SECONDS = 600
DRIVE_MAX_GRANTS = 512

DOC_MIME = 'application/vnd.google-apps.document'
TEXT_MIME = 'text/plain'
SUPPORTED_MIME_TYPES: tuple[str, ...] = (DOC_MIME, TEXT_MIME)
EXPORT_MIME_FOR_DOC = 'text/plain'
DRIVE_RESOURCE_KEYS_HEADER = 'X-Goog-Drive-Resource-Keys'

DRIVE_PARSER_VERSION = 'drive-import/v1'
SELECTION_CONTEXT = 'Drive file selection'

_FILE_ID_RE = re.compile(r'^[A-Za-z0-9_-]{1,256}$')
_RESOURCE_KEY_RE = re.compile(r'^[A-Za-z0-9_-]{1,256}$')
_RESOURCE_KEYS_HEADER_RE = re.compile(r'^[A-Za-z0-9_-]{1,256}/[A-Za-z0-9_-]{1,256}$')

router = APIRouter(prefix='/api/drive-import')

_GRANTS: dict[tuple[str, str], dict] = {}
_GRANTS_LOCK = threading.Lock()


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class DriveStatusOut(Strict):
    available: bool
    configured: bool
    live_verified: bool = False
    max_bytes: int
    max_requests: int
    reason: str
    scope: str
    supported_mime_types: list[str]


class DrivePublicConfigOut(Strict):
    api_key: str
    app_id: str
    max_bytes: int
    scope: str
    supported_mime_types: list[str]


class DriveImportIn(Strict):
    drive_token: str = Field(min_length=1, max_length=4096)
    file_id: str = Field(min_length=1, max_length=256)
    resource_key: str | None = None


class DrivePickerTokenOut(Strict):
    access_token: str
    expires_in: int
    token_type: Literal['Bearer'] = 'Bearer'


class DriveSuggestionItem(Strict):
    text: str
    source: Literal['drive_file'] = 'drive_file'
    product_fact_source: Literal['drive_file'] = 'drive_file'
    status: Literal['unconfirmed'] = 'unconfirmed'
    confirmed: Literal[False] = False
    index: int


class DriveImportOut(Strict):
    dropped_duplicates: int
    dropped_empty: int
    dropped_overlong: int
    file_title: str
    mime_type: str
    parser_version: str
    product_fact_source: Literal['drive_file'] = 'drive_file'
    selection_context: str
    source: Literal['drive_file'] = 'drive_file'
    status: Literal['unconfirmed'] = 'unconfirmed'
    suggestions: list[DriveSuggestionItem]
    truncated: bool


def drive_configured() -> bool:
    return bool(
        os.getenv('GOOGLE_DRIVE_API_KEY', '').strip()
        and os.getenv('GOOGLE_DRIVE_APP_ID', '').strip()
        and os.getenv('GOOGLE_CLIENT_ID', '').strip()
        and os.getenv('GOOGLE_CLIENT_SECRET', '').strip()
    )


def drive_callback_uri() -> str:
    base = os.environ.get('PUBLIC_BASE_URL', '').rstrip('/')
    return base + DRIVE_CALLBACK_PATH


def drive_oauth_client():
    client_id = os.getenv('GOOGLE_CLIENT_ID', '').strip()
    client_secret = os.getenv('GOOGLE_CLIENT_SECRET', '').strip()
    if not client_id or not client_secret:
        raise HTTPException(503, 'Drive intake unavailable')
    oauth = OAuth()
    return oauth.register(
        'google-drive',
        client_id=client_id,
        client_secret=client_secret,
        server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
        client_kwargs={'scope': DRIVE_OAUTH_SCOPE},
    )


def _google_sub(actor: object) -> str | None:
    if not isinstance(actor, str):
        return None
    if not actor.startswith('google:'):
        return None
    sub = actor[len('google:'):]
    if not sub or not sub.strip():
        return None
    for char in sub:
        if char.isspace() or ord(char) < 33 or ord(char) > 126:
            return None
    return sub


def require_google_sub(actor: object) -> str:
    sub = _google_sub(actor)
    if sub is not None:
        return sub
    if actor is None or actor == '' or actor == 'demo_placeholder':
        raise HTTPException(401, 'Sign in required')
    raise HTTPException(403, 'Drive consent required')


def drive_public_config_dict() -> dict:
    api_key = os.getenv('GOOGLE_DRIVE_API_KEY', '').strip()
    app_id = os.getenv('GOOGLE_DRIVE_APP_ID', '').strip()
    if not api_key or not app_id or not auth.google_configured():
        raise HTTPException(503, 'Drive intake unavailable')
    return {
        'api_key': api_key,
        'app_id': app_id,
        'max_bytes': DRIVE_MAX_BYTES,
        'scope': DRIVE_SCOPE,
        'supported_mime_types': list(SUPPORTED_MIME_TYPES),
    }


def drive_status_dict() -> dict:
    configured = drive_configured()
    return {
        'available': configured,
        'configured': configured,
        'live_verified': False,
        'max_bytes': DRIVE_MAX_BYTES,
        'max_requests': DRIVE_MAX_REQUESTS_PER_IMPORT,
        'reason': 'ok' if configured else 'drive_not_configured',
        'scope': DRIVE_SCOPE,
        'supported_mime_types': list(SUPPORTED_MIME_TYPES),
    }


def validate_file_id(value: object) -> str:
    if not isinstance(value, str):
        raise HTTPException(422, 'Invalid Drive selection')
    if len(value) < 1 or len(value) > DRIVE_MAX_FILE_ID_CHARS:
        raise HTTPException(422, 'Invalid Drive selection')
    if not _FILE_ID_RE.match(value):
        raise HTTPException(422, 'Invalid Drive selection')
    return value


def validate_resource_key(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise HTTPException(422, 'Invalid Drive selection')
    if len(value) < 1 or len(value) > DRIVE_MAX_RESOURCE_KEY_CHARS:
        raise HTTPException(422, 'Invalid Drive selection')
    if not _RESOURCE_KEY_RE.match(value):
        raise HTTPException(422, 'Invalid Drive selection')
    return value


def validate_token(value: object) -> str:
    if not isinstance(value, str):
        raise HTTPException(403, 'Drive consent required')
    if len(value) < 1 or len(value) > DRIVE_MAX_TOKEN_CHARS:
        raise HTTPException(403, 'Drive consent required')
    for char in value:
        if char.isspace() or ord(char) < 33 or ord(char) > 126:
            raise HTTPException(403, 'Drive consent required')
    return value


def normalize_mime(value: object) -> str:
    if not isinstance(value, str):
        raise HTTPException(422, 'Unsupported Drive file type')
    cleaned = value.strip().lower()
    if cleaned not in SUPPORTED_MIME_TYPES:
        raise HTTPException(422, 'Unsupported Drive file type')
    return cleaned


def sanitize_title(value: object) -> str:
    if not isinstance(value, str):
        return 'Drive file'
    cleaned = ''.join(char if char == ' ' or (ord(char) >= 33 and ord(char) != 127) else ' ' for char in value)
    collapsed = ' '.join(cleaned.split())
    if not collapsed:
        return 'Drive file'
    if len(collapsed) > DRIVE_MAX_TITLE_CHARS:
        collapsed = collapsed[:DRIVE_MAX_TITLE_CHARS].rstrip()
    return collapsed or 'Drive file'


def check_no_url(value: object) -> None:
    if isinstance(value, str) and ('://' in value or value.startswith('http') or '/' in value or '?' in value or '#' in value):
        raise HTTPException(422, 'Invalid Drive selection')


def resource_keys_header_value(file_id: str, resource_key: str | None) -> str | None:
    if not resource_key:
        return None
    validated_id = validate_file_id(file_id)
    validated_key = validate_resource_key(resource_key)
    if validated_key is None:
        return None
    return validated_id + '/' + validated_key


def build_metadata_url(file_id: str, resource_key: str | None = None) -> str:
    # Documented files.get query only. Resource key is sent via
    # X-Goog-Drive-Resource-Keys header, never URL.
    _ = resource_key
    query = {'fields': 'id,name,mimeType,size,trashed', 'supportsAllDrives': 'true'}
    return DRIVE_API_BASE + '/files/' + urllib.parse.quote(file_id, safe='') + '?' + urllib.parse.urlencode(query)


def build_content_url(file_id: str, resource_key: str | None, mime: str) -> str:
    # Documented query only. Docs export uses mimeType only. Plain-text
    # files.get uses alt plus shared-drive params only. Resource key is
    # sent via X-Goog-Drive-Resource-Keys header, never URL.
    _ = resource_key
    base = DRIVE_API_BASE + '/files/' + urllib.parse.quote(file_id, safe='')
    if mime == DOC_MIME:
        query = {'mimeType': EXPORT_MIME_FOR_DOC}
        return base + '/export?' + urllib.parse.urlencode(query)
    query = {'alt': 'media', 'supportsAllDrives': 'true'}
    return base + '?' + urllib.parse.urlencode(query)


def check_drive_url(url: str) -> None:
    try:
        parsed = urllib.parse.urlsplit(url)
    except Exception:
        raise HTTPException(502, 'Drive provider error') from None
    if parsed.scheme != 'https' or parsed.hostname != DRIVE_API_HOST:
        raise HTTPException(502, 'Drive provider error')
    if parsed.username or parsed.password or parsed.fragment:
        raise HTTPException(502, 'Drive provider error')
    if not parsed.path.startswith('/drive/v3/files/'):
        raise HTTPException(502, 'Drive provider error')
    lowered = (parsed.query or '').lower()
    if 'access_token' in lowered or 'resourcekey' in lowered or 'resource_key' in lowered:
        raise HTTPException(502, 'Drive provider error')


def check_content_length(headers, max_bytes: int) -> None:
    raw = None
    try:
        raw = headers.get('Content-Length')
    except Exception:
        raw = None
    if raw is None:
        return
    try:
        size = int(str(raw).strip())
    except Exception:
        raise HTTPException(502, 'Drive provider error') from None
    if size < 0 or size > max_bytes:
        raise HTTPException(413, 'Drive file too large')


def response_mime(headers) -> str:
    try:
        raw = headers.get('Content-Type', '')
    except Exception:
        raw = ''
    if not isinstance(raw, str):
        return ''
    return raw.split(';', 1)[0].strip().lower()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise HTTPException(502, 'Drive provider error')


def _http_get(url: str, token: str, max_bytes: int, resource_keys: str | None = None):
    try:
        early = urllib.parse.urlsplit(url)
    except Exception:
        raise HTTPException(502, 'Drive provider error') from None
    lowered = (early.query or '').lower()
    if 'access_token' in lowered or 'resourcekey' in lowered or 'resource_key' in lowered:
        raise HTTPException(502, 'Drive provider error')
    check_drive_url(url)
    if resource_keys is not None and not _RESOURCE_KEYS_HEADER_RE.match(resource_keys):
        raise HTTPException(502, 'Drive provider error')
    opener = urllib.request.build_opener(_NoRedirect)
    request = urllib.request.Request(url, method='GET')
    request.add_header('Authorization', 'Bearer ' + token)
    if resource_keys is not None:
        request.add_header(DRIVE_RESOURCE_KEYS_HEADER, resource_keys)
    try:
        response = opener.open(request, timeout=15)
    except HTTPException:
        raise
    except urllib.error.HTTPError as error:
        code = getattr(error, 'code', 0)
        if code in (301, 302, 303, 307, 308):
            raise HTTPException(502, 'Drive provider error') from None
        if code in (401, 403, 404):
            raise HTTPException(403, 'Drive file unavailable or not selected') from None
        if code == 413:
            raise HTTPException(413, 'Drive file too large') from None
        raise HTTPException(502, 'Drive provider error') from None
    except Exception:
        raise HTTPException(502, 'Drive provider error') from None
    with response:
        status = getattr(response, 'status', 200)
        if status in (301, 302, 303, 307, 308):
            raise HTTPException(502, 'Drive provider error')
        if status in (401, 403, 404):
            raise HTTPException(403, 'Drive file unavailable or not selected')
        headers = response.headers
        check_content_length(headers, max_bytes)
        data = response.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise HTTPException(413, 'Drive file too large')
        return bytes(data), headers, status


class DriveProvider:
    def metadata(self, file_id: str, resource_key: str | None, token: str) -> dict:
        import json

        url = build_metadata_url(file_id, resource_key)
        header = resource_keys_header_value(file_id, resource_key)
        data, _, _ = _http_get(url, token, 10000, resource_keys=header)
        try:
            payload = json.loads(data.decode('utf-8'))
        except Exception:
            raise HTTPException(502, 'Drive provider error') from None
        if not isinstance(payload, dict):
            raise HTTPException(502, 'Drive provider error')
        return payload

    def content(self, file_id: str, resource_key: str | None, token: str, mime: str):
        url = build_content_url(file_id, resource_key, mime)
        header = resource_keys_header_value(file_id, resource_key)
        return _http_get(url, token, DRIVE_MAX_BYTES, resource_keys=header)


def get_provider() -> DriveProvider:
    return DriveProvider()


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _session_parts(request: Request) -> tuple[str | None, str | None]:
    raw = request.cookies.get(auth.COOKIE)
    if not raw:
        return None, None
    return raw, auth.session_key(raw)


def _prune_grants_locked(now: float | None = None) -> None:
    at = now if now is not None else time.time()
    expired = [key for key, grant in _GRANTS.items() if grant.get('expiry_ts', 0) <= at]
    for key in expired:
        _GRANTS.pop(key, None)


def _prune_grants() -> None:
    with _GRANTS_LOCK:
        _prune_grants_locked()


def check_drive_id_binding(userinfo: object, expected_client_id: str, expected_sub: str) -> None:
    if not isinstance(userinfo, dict):
        raise HTTPException(403, 'Drive consent required')
    aud = userinfo.get('aud')
    if isinstance(aud, list):
        if len(aud) != 1 or aud[0] != expected_client_id:
            raise HTTPException(403, 'Drive consent required')
    elif not isinstance(aud, str) or aud != expected_client_id:
        raise HTTPException(403, 'Drive consent required')
    iss = userinfo.get('iss')
    if not isinstance(iss, str) or iss not in DRIVE_ISSUERS:
        raise HTTPException(403, 'Drive consent required')
    exp_raw = userinfo.get('exp')
    try:
        exp = int(exp_raw) if isinstance(exp_raw, bool) is False else -1
    except Exception:
        raise HTTPException(403, 'Drive consent required') from None
    if exp <= int(time.time()):
        raise HTTPException(403, 'Drive consent required')
    sub = userinfo.get('sub')
    if not isinstance(sub, str) or not sub or sub != expected_sub:
        raise HTTPException(403, 'Drive consent required')


def check_drive_granted_scope(token: object) -> None:
    if not isinstance(token, dict):
        raise HTTPException(403, 'Drive consent required')
    scope_raw = token.get('scope', '')
    if not isinstance(scope_raw, str):
        raise HTTPException(403, 'Drive consent required')
    parts = scope_raw.split()
    if not parts:
        raise HTTPException(403, 'Drive consent required')
    if len(parts) != len(set(parts)):
        raise HTTPException(403, 'Drive consent required')
    scopes = set(parts)
    if DRIVE_SCOPE not in scopes:
        raise HTTPException(403, 'Drive consent required')
    if not scopes.issubset(DRIVE_ALLOWED_SCOPES):
        raise HTTPException(403, 'Drive consent required')
    if 'email' in scopes and DRIVE_EMAIL_CANONICAL in scopes:
        raise HTTPException(403, 'Drive consent required')
    if 'profile' in scopes and DRIVE_PROFILE_CANONICAL in scopes:
        raise HTTPException(403, 'Drive consent required')


def check_no_refresh_token(token: object) -> None:
    if isinstance(token, dict) and token.get('refresh_token'):
        raise HTTPException(403, 'Drive consent required')


def _drive_state_keys(session: dict) -> list[str]:
    return [key for key in session.keys() if key.startswith('_state_google-drive_')]


def decode_text(data: bytes) -> str:
    try:
        text = data.decode('utf-8')
    except Exception:
        raise HTTPException(422, 'Unsupported Drive file type') from None
    if '\x00' in text:
        raise HTTPException(422, 'Unsupported Drive file type')
    if len(text) > DRIVE_MAX_TEXT_CHARS:
        raise HTTPException(413, 'Drive file too large')
    return text


def _verify_and_consume_grant(actor: str, session_hash: str, presented_token: str) -> None:
    with _GRANTS_LOCK:
        _prune_grants_locked()
        grant = _GRANTS.get((actor, session_hash))
        if grant is None:
            raise HTTPException(403, 'Drive consent required')
        if grant.get('consumed'):
            _GRANTS.pop((actor, session_hash), None)
            raise HTTPException(403, 'Drive consent required')
        if not grant.get('delivered'):
            raise HTTPException(403, 'Drive consent required')
        if grant.get('expiry_ts', 0) <= time.time():
            _GRANTS.pop((actor, session_hash), None)
            raise HTTPException(403, 'Drive consent required')
        if grant.get('digest') != token_digest(presented_token):
            raise HTTPException(403, 'Drive consent required')
        _GRANTS.pop((actor, session_hash), None)


def _store_grant(actor: str, session_hash: str, access_token: str, ttl: int) -> None:
    with _GRANTS_LOCK:
        _prune_grants_locked()
        if len(_GRANTS) >= DRIVE_MAX_GRANTS:
            raise HTTPException(503, 'Drive intake unavailable')
        _GRANTS[(actor, session_hash)] = {
            'digest': token_digest(access_token),
            'plaintext': access_token,
            'expiry_ts': time.time() + ttl,
            'delivered': False,
            'consumed': False,
        }


def _claim_picker_token(actor: str, session_hash: str) -> tuple[str, int]:
    with _GRANTS_LOCK:
        _prune_grants_locked()
        grant = _GRANTS.get((actor, session_hash))
        if grant is None or grant.get('consumed') or grant.get('delivered'):
            raise HTTPException(403, 'Drive consent required')
        if grant.get('expiry_ts', 0) <= time.time():
            _GRANTS.pop((actor, session_hash), None)
            raise HTTPException(403, 'Drive consent required')
        plaintext = grant.get('plaintext')
        if not isinstance(plaintext, str) or not plaintext:
            _GRANTS.pop((actor, session_hash), None)
            raise HTTPException(403, 'Drive consent required')
        remaining = int(grant['expiry_ts'] - time.time())
        if remaining <= 0:
            _GRANTS.pop((actor, session_hash), None)
            raise HTTPException(403, 'Drive consent required')
        grant['delivered'] = True
        grant['plaintext'] = None
        return plaintext, remaining


def import_drive_selection(
    file_id: str,
    resource_key: str | None,
    token: str,
    provider: DriveProvider,
    actor: str,
    session_hash: str,
) -> dict:
    validated_id = validate_file_id(file_id)
    check_no_url(validated_id)
    validated_key = validate_resource_key(resource_key)
    if validated_key:
        check_no_url(validated_key)
    validated_token = validate_token(token)
    require_google_sub(actor)
    if not session_hash:
        raise HTTPException(401, 'Sign in required')
    _verify_and_consume_grant(actor, session_hash, validated_token)
    requests = 0

    def counted():
        nonlocal requests
        requests += 1
        if requests > DRIVE_MAX_REQUESTS_PER_IMPORT:
            raise HTTPException(502, 'Drive provider error')

    counted()
    meta = provider.metadata(validated_id, validated_key, validated_token)
    if not isinstance(meta, dict):
        raise HTTPException(502, 'Drive provider error')
    if meta.get('trashed') is True:
        raise HTTPException(403, 'Drive file unavailable or not selected')
    returned_id = meta.get('id')
    if returned_id is not None and returned_id != validated_id:
        raise HTTPException(403, 'Drive file unavailable or not selected')
    mime = normalize_mime(meta.get('mimeType', ''))
    title = sanitize_title(meta.get('name', ''))
    size_raw = meta.get('size')
    if size_raw is not None:
        try:
            size = int(str(size_raw).strip())
        except Exception:
            raise HTTPException(502, 'Drive provider error') from None
        if size < 0 or size > DRIVE_MAX_BYTES:
            raise HTTPException(413, 'Drive file too large')

    counted()
    result = provider.content(validated_id, validated_key, validated_token, mime)
    if not isinstance(result, tuple) or len(result) != 3:
        raise HTTPException(502, 'Drive provider error')
    data, headers, _ = result
    if not isinstance(data, (bytes, bytearray)):
        raise HTTPException(502, 'Drive provider error')
    if len(data) > DRIVE_MAX_BYTES:
        raise HTTPException(413, 'Drive file too large')
    seen = response_mime(headers)
    if seen != TEXT_MIME:
        raise HTTPException(422, 'Unsupported Drive file type')
    text = decode_text(bytes(data))

    from launchcrew.import_suggestions import parse_import_text

    try:
        parsed = parse_import_text(text, 'drive_file')
    except (TypeError, ValueError):
        raise HTTPException(422, 'Unsupported Drive file type') from None
    suggestions = [
        {
            'text': item['text'],
            'source': 'drive_file',
            'product_fact_source': 'drive_file',
            'status': 'unconfirmed',
            'confirmed': False,
            'index': item['index'],
        }
        for item in parsed['suggestions']
    ]
    return {
        'status': 'unconfirmed',
        'source': 'drive_file',
        'product_fact_source': 'drive_file',
        'file_title': title,
        'mime_type': mime,
        'selection_context': SELECTION_CONTEXT,
        'suggestions': suggestions,
        'truncated': parsed['truncated'],
        'dropped_duplicates': parsed['dropped_duplicates'],
        'dropped_overlong': parsed['dropped_overlong'],
        'dropped_empty': parsed['dropped_empty'],
        'parser_version': DRIVE_PARSER_VERSION,
    }


@router.get('/status', response_model=DriveStatusOut)
def drive_status(actor: str = Depends(auth.actor)):
    store.workspace_for_actor(actor)
    if not drive_configured():
        return drive_status_dict()
    if _google_sub(actor) is None:
        return {
            'available': False,
            'configured': True,
            'live_verified': False,
            'max_bytes': DRIVE_MAX_BYTES,
            'max_requests': DRIVE_MAX_REQUESTS_PER_IMPORT,
            'reason': 'auth_required',
            'scope': DRIVE_SCOPE,
            'supported_mime_types': list(SUPPORTED_MIME_TYPES),
        }
    return drive_status_dict()


@router.get('/config', response_model=DrivePublicConfigOut)
def drive_config(actor: str = Depends(auth.actor)):
    store.workspace_for_actor(actor)
    if not drive_configured():
        raise HTTPException(503, 'Drive intake unavailable')
    require_google_sub(actor)
    return drive_public_config_dict()


@router.get('/authorize')
async def drive_authorize(request: Request, actor: str = Depends(auth.actor)):
    auth.validate_config()
    store.workspace_for_actor(actor)
    if not drive_configured():
        raise HTTPException(503, 'Drive intake unavailable')
    require_google_sub(actor)
    raw, session_hash = _session_parts(request)
    if not raw or not session_hash:
        raise HTTPException(401, 'Sign in required')
    data = auth.load_session(request)
    if not data or data.get('actor') != actor:
        raise HTTPException(401, 'Sign in required')
    client = drive_oauth_client()
    request.scope['session'] = dict(data)
    callback_uri = drive_callback_uri()
    response = await client.authorize_redirect(
        request,
        callback_uri,
        access_type='online',
        include_granted_scopes='false',
    )
    state_keys = _drive_state_keys(request.session)
    if not state_keys:
        raise HTTPException(502, 'Drive provider error')
    state = state_keys[-1].split('_state_google-drive_', 1)[1]
    binding = {
        'actor': actor,
        'session_hash': session_hash,
        'state': state,
        'expiry_ts': time.time() + DRIVE_PENDING_TTL_SECONDS,
        'redirect_uri': callback_uri,
    }
    request.session['drive_oauth_binding'] = binding
    auth.update_session_data_in_place(raw, dict(request.session))
    return response


@router.get('/callback')
async def drive_callback(request: Request, actor: str = Depends(auth.actor)):
    auth.validate_config()
    store.workspace_for_actor(actor)
    if not drive_configured():
        raise HTTPException(503, 'Drive intake unavailable')
    require_google_sub(actor)
    expected_sub = require_google_sub(actor)
    raw, session_hash = _session_parts(request)
    if not raw or not session_hash:
        raise HTTPException(401, 'Sign in required')
    data = auth.load_session(request)
    if not data or data.get('actor') != actor:
        raise HTTPException(401, 'Sign in required')
    binding = data.get('drive_oauth_binding')
    if not isinstance(binding, dict):
        raise HTTPException(403, 'Drive consent required')
    query_state = request.query_params.get('state', '')
    query_code = request.query_params.get('code', '')
    if request.query_params.get('error'):
        raise HTTPException(403, 'Drive consent required')
    if not query_state or not query_code:
        raise HTTPException(403, 'Drive consent required')
    if binding.get('state') != query_state:
        raise HTTPException(403, 'Drive consent required')
    if binding.get('actor') != actor or binding.get('session_hash') != session_hash:
        raise HTTPException(403, 'Drive consent required')
    try:
        expiry = float(binding.get('expiry_ts', 0))
    except Exception:
        raise HTTPException(403, 'Drive consent required') from None
    if expiry <= time.time():
        raise HTTPException(403, 'Drive consent required')
    if binding.get('redirect_uri') != drive_callback_uri():
        raise HTTPException(403, 'Drive consent required')
    client = drive_oauth_client()
    request.scope['session'] = dict(data)
    try:
        token = await client.authorize_access_token(request)
    except Exception:
        raise HTTPException(403, 'Drive consent required') from None
    if not isinstance(token, dict):
        raise HTTPException(403, 'Drive consent required')
    access_token = token.get('access_token')
    if not isinstance(access_token, str) or not access_token:
        raise HTTPException(403, 'Drive consent required')
    validate_token(access_token)
    check_no_refresh_token(token)
    check_drive_granted_scope(token)
    expected_client = os.getenv('GOOGLE_CLIENT_ID', '').strip()
    if not expected_client:
        raise HTTPException(503, 'Drive intake unavailable')
    check_drive_id_binding(token.get('userinfo', {}), expected_client, expected_sub)
    try:
        expires_in = int(str(token.get('expires_in', '0')).strip())
    except Exception:
        raise HTTPException(403, 'Drive consent required') from None
    if expires_in <= 0:
        raise HTTPException(403, 'Drive consent required')
    ttl = min(expires_in, DRIVE_GRANT_TTL_SECONDS)
    _store_grant(actor, session_hash, access_token, ttl)
    cleaned = dict(data)
    for key in _drive_state_keys(cleaned):
        cleaned.pop(key, None)
    cleaned.pop('drive_oauth_binding', None)
    auth.update_session_data_in_place(raw, cleaned)
    return RedirectResponse('/?drive=authorized', status_code=303)


@router.post('/picker-token', response_model=DrivePickerTokenOut)
def drive_picker_token(request: Request, actor: str = Depends(auth.actor)):
    store.workspace_for_actor(actor)
    if not drive_configured():
        raise HTTPException(503, 'Drive intake unavailable')
    require_google_sub(actor)
    _, session_hash = _session_parts(request)
    if not session_hash:
        raise HTTPException(401, 'Sign in required')
    plaintext, remaining = _claim_picker_token(actor, session_hash)
    return {'access_token': plaintext, 'expires_in': remaining, 'token_type': 'Bearer'}


@router.post('/suggestions', response_model=DriveImportOut)
def drive_suggestions(body: DriveImportIn, request: Request, actor: str = Depends(auth.actor), provider: DriveProvider = Depends(get_provider)):
    store.workspace_for_actor(actor)
    if not drive_configured():
        raise HTTPException(503, 'Drive intake unavailable')
    require_google_sub(actor)
    _, session_hash = _session_parts(request)
    if not session_hash:
        raise HTTPException(401, 'Sign in required')
    return import_drive_selection(body.file_id, body.resource_key, provider=provider, token=body.drive_token, actor=actor, session_hash=session_hash)
