"""Google Drive selected-file read-only intake, optional connector.

Scope: a practical named-test-user demo path for reading one app-authorized
Drive file via Picker plus GIS, returning bounded UNCONFIRMED parsed lines
for the existing owner fact confirmation flow. This module never replaces
Google identity sign-in (openid profile email only in backend/auth.py) and
never replaces pasted-text import.

Read-only guarantee: product code only performs HTTP GET against
Drive file metadata, get, export, and download endpoints. It never calls
create, update, delete, or permissions APIs. Picker filters to Docs and
plain text. No photos.

Consent and owner binding: separate incremental drive.file scope via GIS,
requested only in the Drive intake UI. Ordinary sign-in scopes stay narrow.
The backend validates the GIS token for drive.file scope and expiry, plus
exact audience/client against GOOGLE_DRIVE_CLIENT_ID and exact user identity
against the authenticated LaunchCrew actor google:<sub>, via tokeninfo.
Missing, ambiguous, or mismatched audience or identity fails closed. The
server then reads only the stated file ID and resource key. A file ID alone
does not prove a fresh Picker selection server-side; drive.file scope only
permits app-authorized files the user opened for this app. The latest UI
selection display stays local browser behavior only. Provider tokens travel
only in POST bodies and Authorization Bearer headers, never in URLs, logs,
persistence, or responses.

Binding: every endpoint requires a Google LaunchCrew actor via backend.auth.
Demo placeholder and non-Google actors fail closed even when Drive config
exists, so status reports unavailable, config and suggestions require sign-in.
Workspace is derived server-side with store.workspace_for_actor. The API
accepts no workspace ID and no URLs, so anonymous and foreign workspace
use fails closed. Import is stateless: no database writes, no Memory
writes, no queue writes, no model calls, no Meta calls.

Bounds: explicit max bytes and max requests, enforced before allocation.
Content-Length is checked before reading. Downloads stream with a hard
cap. Text over the parser bound is refused as oversize. Only Docs export
to text/plain and text/plain download are supported. Redirects are never
followed. Hosts are pinned to Google endpoints. Deceptive MIME, non-text,
and overlong selections are refused.

Provenance: success returns status unconfirmed, source drive_file, and
product_fact_source drive_file, with a sanitized file title, MIME label,
generic selection context, and bounded unconfirmed parsed text lines for
owner UI. No provider file ID, resource key, token, bytes, or full private
file body are logged, persisted, or returned in public receipts. Live Drive
proof has not been run; status live_verified stays false.
"""
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from backend import auth, store

DRIVE_SCOPE = 'https://www.googleapis.com/auth/drive.file'
DRIVE_TOKENINFO_URL = 'https://oauth2.googleapis.com/tokeninfo'
DRIVE_TOKENINFO_HOST = 'oauth2.googleapis.com'
DRIVE_API_HOST = 'www.googleapis.com'
DRIVE_API_BASE = 'https://www.googleapis.com/drive/v3'

DRIVE_MAX_BYTES = 200000
DRIVE_MAX_TEXT_CHARS = 10000
DRIVE_MAX_REQUESTS_PER_IMPORT = 3
DRIVE_MAX_FILE_ID_CHARS = 256
DRIVE_MAX_RESOURCE_KEY_CHARS = 256
DRIVE_MAX_TITLE_CHARS = 200
DRIVE_MAX_TOKEN_CHARS = 4096

DOC_MIME = 'application/vnd.google-apps.document'
TEXT_MIME = 'text/plain'
SUPPORTED_MIME_TYPES: tuple[str, ...] = (DOC_MIME, TEXT_MIME)
EXPORT_MIME_FOR_DOC = 'text/plain'

DRIVE_PARSER_VERSION = 'drive-import/v1'
SELECTION_CONTEXT = 'Drive file selection'

_FILE_ID_RE = re.compile(r'^[A-Za-z0-9_-]{1,256}$')
_RESOURCE_KEY_RE = re.compile(r'^[A-Za-z0-9_-]{1,256}$')

router = APIRouter(prefix='/api/drive-import')


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
    client_id: str
    max_bytes: int
    scope: str
    supported_mime_types: list[str]


class DriveImportIn(Strict):
    drive_token: str = Field(min_length=1, max_length=4096)
    file_id: str = Field(min_length=1, max_length=256)
    resource_key: str | None = None


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
        os.getenv('GOOGLE_DRIVE_CLIENT_ID', '').strip()
        and os.getenv('GOOGLE_DRIVE_API_KEY', '').strip()
        and os.getenv('GOOGLE_DRIVE_APP_ID', '').strip()
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
    client_id = os.getenv('GOOGLE_DRIVE_CLIENT_ID', '').strip()
    api_key = os.getenv('GOOGLE_DRIVE_API_KEY', '').strip()
    app_id = os.getenv('GOOGLE_DRIVE_APP_ID', '').strip()
    if not client_id or not api_key or not app_id:
        raise HTTPException(503, 'Drive intake unavailable')
    return {
        'api_key': api_key,
        'app_id': app_id,
        'client_id': client_id,
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


def build_metadata_url(file_id: str, resource_key: str | None) -> str:
    query = {'fields': 'id,name,mimeType,size,trashed', 'supportsAllDrives': 'true'}
    if resource_key:
        query['resourceKey'] = resource_key
    return DRIVE_API_BASE + '/files/' + urllib.parse.quote(file_id, safe='') + '?' + urllib.parse.urlencode(query)


def build_content_url(file_id: str, resource_key: str | None, mime: str) -> str:
    base = DRIVE_API_BASE + '/files/' + urllib.parse.quote(file_id, safe='')
    if mime == DOC_MIME:
        query = {'mimeType': EXPORT_MIME_FOR_DOC, 'supportsAllDrives': 'true'}
        if resource_key:
            query['resourceKey'] = resource_key
        return base + '/export?' + urllib.parse.urlencode(query)
    query = {'alt': 'media', 'supportsAllDrives': 'true'}
    if resource_key:
        query['resourceKey'] = resource_key
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
    if 'access_token' in (parsed.query or '').lower():
        raise HTTPException(502, 'Drive provider error')


def check_tokeninfo_url(url: str) -> None:
    try:
        parsed = urllib.parse.urlsplit(url)
    except Exception:
        raise HTTPException(502, 'Drive provider error') from None
    if parsed.scheme != 'https' or parsed.hostname != DRIVE_TOKENINFO_HOST:
        raise HTTPException(502, 'Drive provider error')
    if parsed.username or parsed.password or parsed.fragment:
        raise HTTPException(502, 'Drive provider error')
    if parsed.path != '/tokeninfo':
        raise HTTPException(502, 'Drive provider error')
    if parsed.query:
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


def _http_get(url: str, token: str, max_bytes: int):
    try:
        early = urllib.parse.urlsplit(url)
    except Exception:
        raise HTTPException(502, 'Drive provider error') from None
    if 'access_token' in (early.query or '').lower():
        raise HTTPException(502, 'Drive provider error')
    check_drive_url(url) if url.startswith(DRIVE_API_BASE) else check_tokeninfo_url(url)
    opener = urllib.request.build_opener(_NoRedirect)
    request = urllib.request.Request(url, method='GET')
    if url.startswith(DRIVE_API_BASE) or url.startswith(DRIVE_TOKENINFO_URL):
        request.add_header('Authorization', 'Bearer ' + token)
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
    def tokeninfo(self, token: str) -> dict:
        url = DRIVE_TOKENINFO_URL
        check_tokeninfo_url(url)
        data, _, _ = _http_get(url, token, 10000)
        import json

        try:
            payload = json.loads(data.decode('utf-8'))
        except Exception:
            raise HTTPException(502, 'Drive provider error') from None
        if not isinstance(payload, dict):
            raise HTTPException(502, 'Drive provider error')
        return payload

    def metadata(self, file_id: str, resource_key: str | None, token: str) -> dict:
        import json

        url = build_metadata_url(file_id, resource_key)
        data, _, _ = _http_get(url, token, 10000)
        try:
            payload = json.loads(data.decode('utf-8'))
        except Exception:
            raise HTTPException(502, 'Drive provider error') from None
        if not isinstance(payload, dict):
            raise HTTPException(502, 'Drive provider error')
        return payload

    def content(self, file_id: str, resource_key: str | None, token: str, mime: str):
        url = build_content_url(file_id, resource_key, mime)
        return _http_get(url, token, DRIVE_MAX_BYTES)


def get_provider() -> DriveProvider:
    return DriveProvider()


def check_token_scope(payload: dict) -> None:
    scope_raw = payload.get('scope', '')
    if not isinstance(scope_raw, str):
        raise HTTPException(403, 'Drive consent required')
    scopes = set(scope_raw.split())
    if DRIVE_SCOPE not in scopes:
        raise HTTPException(403, 'Drive consent required')
    expires_raw = payload.get('expires_in', '')
    try:
        expires = int(str(expires_raw).strip())
    except Exception:
        raise HTTPException(403, 'Drive consent required') from None
    if expires <= 0:
        raise HTTPException(403, 'Drive consent required')


def check_token_binding(payload: dict, actor: str) -> None:
    expected_client = os.getenv('GOOGLE_DRIVE_CLIENT_ID', '').strip()
    if not expected_client:
        raise HTTPException(503, 'Drive intake unavailable')
    expected_sub = require_google_sub(actor)
    audiences: list[str] = []
    for key in ('aud', 'audience', 'issued_to'):
        value = payload.get(key)
        if value is None:
            continue
        if not isinstance(value, str) or not value.strip():
            raise HTTPException(403, 'Drive consent required')
        audiences.append(value.strip())
    if not audiences:
        raise HTTPException(403, 'Drive consent required')
    if len(set(audiences)) != 1 or audiences[0] != expected_client:
        raise HTTPException(403, 'Drive consent required')
    identities: list[str] = []
    for key in ('sub', 'user_id'):
        value = payload.get(key)
        if value is None:
            continue
        if not isinstance(value, str) or not value.strip():
            raise HTTPException(403, 'Drive consent required')
        identities.append(value.strip())
    if not identities:
        raise HTTPException(403, 'Drive consent required')
    if len(set(identities)) != 1 or identities[0] != expected_sub:
        raise HTTPException(403, 'Drive consent required')


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


def import_drive_selection(file_id: str, resource_key: str | None, token: str, provider: DriveProvider, actor: str) -> dict:
    validated_id = validate_file_id(file_id)
    check_no_url(validated_id)
    validated_key = validate_resource_key(resource_key)
    if validated_key:
        check_no_url(validated_key)
    validated_token = validate_token(token)
    require_google_sub(actor)
    requests = 0

    def counted():
        nonlocal requests
        requests += 1
        if requests > DRIVE_MAX_REQUESTS_PER_IMPORT:
            raise HTTPException(502, 'Drive provider error')

    counted()
    scope_payload = provider.tokeninfo(validated_token)
    check_token_scope(scope_payload)
    check_token_binding(scope_payload, actor)

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


@router.post('/suggestions', response_model=DriveImportOut)
def drive_suggestions(body: DriveImportIn, actor: str = Depends(auth.actor), provider: DriveProvider = Depends(get_provider)):
    store.workspace_for_actor(actor)
    if not drive_configured():
        raise HTTPException(503, 'Drive intake unavailable')
    require_google_sub(actor)
    return import_drive_selection(body.file_id, body.resource_key, provider=provider, token=body.drive_token, actor=actor)
