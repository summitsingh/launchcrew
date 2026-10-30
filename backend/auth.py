"""Opt-in Authlib OAuth with opaque cookies and server-side Postgres sessions.

Google-only priority: source wiring exposes only configured providers and
requires Google configuration when enabled. Facebook code remains present but
unpublished and inactive unless its credentials are explicitly configured.
Only identity scopes. Provider tokens are never persisted or returned to clients.
Live provider sign-in has not been verified. Status live_verified stays false
until actual provider proof.
"""
import hashlib
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import text
from backend import store

router = APIRouter(prefix='/api/auth')
COOKIE = 'launchcrew_session'
SESSION_HOURS = 8


def enabled():
    return os.getenv('AUTH_ENABLED', 'false').lower() == 'true'


def google_configured():
    return bool(os.getenv('GOOGLE_CLIENT_ID') and os.getenv('GOOGLE_CLIENT_SECRET'))


def facebook_configured():
    return bool(os.getenv('FACEBOOK_CLIENT_ID') and os.getenv('FACEBOOK_CLIENT_SECRET'))


def configured_providers():
    providers = []
    if google_configured():
        providers.append('google')
    if facebook_configured():
        providers.append('facebook')
    return providers


def validate_config():
    if not enabled():
        return
    base = os.environ.get('PUBLIC_BASE_URL', '')
    parsed = urlsplit(base)
    if parsed.scheme != 'https' or not parsed.netloc or parsed.path not in ('', '/') or parsed.query or parsed.fragment:
        raise RuntimeError('Auth requires PUBLIC_BASE_URL with HTTPS')
    if not google_configured():
        raise RuntimeError('Auth requires Google provider configuration')


def oauth_client(provider):
    if provider not in ('google', 'facebook') or not enabled():
        raise HTTPException(404, 'Provider unavailable')
    key = provider.upper()
    if not os.getenv(key + '_CLIENT_ID') or not os.getenv(key + '_CLIENT_SECRET'):
        raise HTTPException(404, 'Provider unavailable')
    oauth = OAuth()
    config = dict(client_id=os.environ[key + '_CLIENT_ID'], client_secret=os.environ[key + '_CLIENT_SECRET'])
    if provider == 'google':
        config.update(server_metadata_url='https://accounts.google.com/.well-known/openid-configuration', client_kwargs={'scope': 'openid profile email'})
    else:
        config.update(authorize_url='https://www.facebook.com/v24.0/dialog/oauth', access_token_url='https://graph.facebook.com/v24.0/oauth/access_token', api_base_url='https://graph.facebook.com/v24.0/', client_kwargs={'scope': 'public_profile email'})
    return oauth.register(provider, **config)


def session_key(raw):
    return hashlib.sha256(raw.encode()).hexdigest()


def load_session(request):
    raw = request.cookies.get(COOKIE)
    if not raw:
        return None
    with store.connect() as db:
        row = db.execute(text('SELECT data FROM auth_sessions WHERE id=:id AND expires_at>now()'), {'id': session_key(raw)}).fetchone()
    return row[0] if row else None


def save_session(data, response, old=None):
    raw = secrets.token_urlsafe(32)
    with store.connect() as db:
        if old:
            db.execute(text('DELETE FROM auth_sessions WHERE id=:id'), {'id': session_key(old)})
        db.execute(text('INSERT INTO auth_sessions(id,data,expires_at) VALUES (:id,CAST(:data AS jsonb),:expiry)'), {'id': session_key(raw), 'data': json.dumps(data), 'expiry': datetime.now(timezone.utc) + timedelta(hours=SESSION_HOURS)})
    response.set_cookie(COOKIE, raw, secure=True, httponly=True, samesite='lax', max_age=SESSION_HOURS * 3600, path='/api')


def update_session_data_in_place(raw, data):
    if not raw:
        return
    with store.connect() as db:
        db.execute(text('UPDATE auth_sessions SET data=CAST(:data AS jsonb) WHERE id=:id'), {'id': session_key(raw), 'data': json.dumps(data)})


def actor(request: Request):
    if not enabled():
        return 'demo_placeholder'
    data = load_session(request)
    if not data or not data.get('actor'):
        raise HTTPException(401, 'Sign in required')
    return data['actor']


@router.get('/status')
def status(request: Request) -> dict[str, str | bool | list[str]]:
    data = load_session(request) if enabled() else None
    return {'enabled': enabled(), 'user': data.get('actor', '') if data else '', 'live_verified': False, 'providers': configured_providers() if enabled() else []}


@router.get('/{provider}/login')
async def login(provider: str, request: Request):
    validate_config()
    client = oauth_client(provider)
    # Authlib uses request.session for state and nonce. Persist that dictionary
    # server-side and rotate its opaque cookie after authentication.
    request.scope['session'] = {}
    response = await client.authorize_redirect(request, os.environ['PUBLIC_BASE_URL'].rstrip('/') + '/api/auth/' + provider + '/callback')
    save_session(request.session, response, request.cookies.get(COOKIE))
    return response


@router.get('/{provider}/callback')
async def callback(provider: str, request: Request):
    validate_config()
    client = oauth_client(provider)
    data = load_session(request)
    if not data:
        raise HTTPException(400, 'OAuth state expired')
    request.scope['session'] = data
    try:
        token = await client.authorize_access_token(request)
        if provider == 'google':
            user = token.get('userinfo', {})
            subject = user.get('sub')
        else:
            result = await client.get('me', params={'fields': 'id,name,email'}, token=token)
            subject = result.json().get('id')
        if not subject:
            raise ValueError('Missing identity')
    except Exception:
        # No provider errors or tokens in responses, logs, receipts, or sessions.
        raise HTTPException(400, 'Identity verification failed') from None
    response = RedirectResponse('/', status_code=303)
    save_session({'actor': provider + ':' + str(subject)}, response, request.cookies.get(COOKIE))
    return response


@router.post('/logout')
def logout(request: Request, response: Response) -> dict[str, bool]:
    raw = request.cookies.get(COOKIE)
    if raw:
        with store.connect() as db:
            db.execute(text('DELETE FROM auth_sessions WHERE id=:id'), {'id': session_key(raw)})
    # Expire the client cookie as well as deleting the server session row.
    # Logout stays idempotent for a missing or already invalid cookie.
    response.delete_cookie(COOKIE, path='/api')
    return {'signed_out': True}
