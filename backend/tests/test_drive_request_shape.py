"""Drive provider request-shape tests with fake opener.

Source-only tests that inspect the actual urllib Request URL and headers.
No provider network calls, no real credentials, no live Drive proof. All
IDs, keys, tokens, and bodies are synthetic.
"""
import urllib.error
import urllib.parse
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from backend import drive_intake

FILE_ID = 'demo-file-01'
DOC_ID = 'demo-doc-02'
RESOURCE_KEY = 'synthetic-resource-key-01'
TOKEN = 'synthetic-drive-token-shape-01'


class FakeHeaders(dict):
    def get(self, key, default=None):
        return super().get(key, default)


class FakeResponse:
    def __init__(self, data, headers=None, status=200):
        self._data = bytes(data)
        self.headers = headers if headers is not None else FakeHeaders({})
        self.status = status

    def read(self, size=-1):
        if size is None or size < 0:
            return self._data
        return self._data[:size]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeOpener:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.requests = []

    def open(self, request, timeout=None):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return self.response


def _query_keys(url):
    parsed = urllib.parse.urlsplit(url)
    assert parsed.scheme == 'https'
    assert parsed.hostname == drive_intake.DRIVE_API_HOST
    assert parsed.path.startswith('/drive/v3/files/')
    return dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))


def _auth_header(request):
    return request.get_header('Authorization')


def _resource_header(request):
    return request.get_header(drive_intake.DRIVE_RESOURCE_KEYS_HEADER)


def test_metadata_url_uses_documented_query_only():
    for key in (None, RESOURCE_KEY):
        url = drive_intake.build_metadata_url(FILE_ID, key)
        query = _query_keys(url)
        assert set(query) == {'fields', 'supportsAllDrives'}
        assert query['fields'] == 'id,name,mimeType,size,trashed'
        assert query['supportsAllDrives'] == 'true'
        assert 'resourcekey' not in url.lower()
        assert 'resource_key' not in url.lower()
        assert TOKEN not in url
        assert RESOURCE_KEY not in url
    assert drive_intake.resource_keys_header_value(FILE_ID, None) is None
    assert drive_intake.resource_keys_header_value(FILE_ID, RESOURCE_KEY) == FILE_ID + '/' + RESOURCE_KEY


def test_plain_text_media_url_uses_documented_query_only():
    for key in (None, RESOURCE_KEY):
        url = drive_intake.build_content_url(FILE_ID, key, drive_intake.TEXT_MIME)
        query = _query_keys(url)
        assert set(query) == {'alt', 'supportsAllDrives'}
        assert query['alt'] == 'media'
        assert query['supportsAllDrives'] == 'true'
        assert 'mimetype' not in url.lower()
        assert 'resourcekey' not in url.lower()
        assert TOKEN not in url
        assert RESOURCE_KEY not in url


def test_docs_export_url_uses_mimetype_only():
    for key in (None, RESOURCE_KEY):
        url = drive_intake.build_content_url(DOC_ID, key, drive_intake.DOC_MIME)
        parsed = urllib.parse.urlsplit(url)
        assert parsed.path.endswith('/export')
        query = _query_keys(url)
        assert set(query) == {'mimeType'}
        assert query['mimeType'] == 'text/plain'
        assert 'supportsalldrives' not in url.lower()
        assert 'resourcekey' not in url.lower()
        assert TOKEN not in url
        assert RESOURCE_KEY not in url


@pytest.mark.parametrize('key', [None, RESOURCE_KEY])
def test_provider_metadata_request_shape_via_opener(key):
    payload = b'{"id":"demo-file-01","name":"Shape file","mimeType":"text/plain"}'
    headers = FakeHeaders({'Content-Type': 'application/json; charset=utf-8'})
    opener = FakeOpener(response=FakeResponse(payload, headers, 200))
    with patch.object(drive_intake.urllib.request, 'build_opener', return_value=opener):
        body = drive_intake.DriveProvider().metadata(FILE_ID, key, TOKEN)
    assert body['id'] == FILE_ID
    assert len(opener.requests) == 1
    request = opener.requests[0]
    query = _query_keys(request.full_url)
    assert set(query) == {'fields', 'supportsAllDrives'}
    assert TOKEN not in request.full_url
    assert RESOURCE_KEY not in request.full_url
    assert _auth_header(request) == 'Bearer ' + TOKEN
    expected = None if key is None else FILE_ID + '/' + RESOURCE_KEY
    assert _resource_header(request) == expected


@pytest.mark.parametrize('key', [None, RESOURCE_KEY])
def test_provider_plain_text_media_request_shape_via_opener(key):
    data = b'Shape line one\nShape line two'
    headers = FakeHeaders({'Content-Type': 'text/plain; charset=utf-8', 'Content-Length': str(len(data))})
    opener = FakeOpener(response=FakeResponse(data, headers, 200))
    with patch.object(drive_intake.urllib.request, 'build_opener', return_value=opener):
        out, seen, status = drive_intake.DriveProvider().content(FILE_ID, key, TOKEN, drive_intake.TEXT_MIME)
    assert bytes(out) == data
    assert status == 200
    assert len(opener.requests) == 1
    request = opener.requests[0]
    query = _query_keys(request.full_url)
    assert set(query) == {'alt', 'supportsAllDrives'}
    assert TOKEN not in request.full_url
    assert RESOURCE_KEY not in request.full_url
    assert _auth_header(request) == 'Bearer ' + TOKEN
    expected = None if key is None else FILE_ID + '/' + RESOURCE_KEY
    assert _resource_header(request) == expected


@pytest.mark.parametrize('key', [None, RESOURCE_KEY])
def test_provider_docs_export_request_shape_via_opener(key):
    data = b'Exported shape text'
    headers = FakeHeaders({'Content-Type': 'text/plain', 'Content-Length': str(len(data))})
    opener = FakeOpener(response=FakeResponse(data, headers, 200))
    with patch.object(drive_intake.urllib.request, 'build_opener', return_value=opener):
        out, _, _ = drive_intake.DriveProvider().content(DOC_ID, key, TOKEN, drive_intake.DOC_MIME)
    assert bytes(out) == data
    assert len(opener.requests) == 1
    request = opener.requests[0]
    parsed = urllib.parse.urlsplit(request.full_url)
    assert parsed.path.endswith('/export')
    query = _query_keys(request.full_url)
    assert set(query) == {'mimeType'}
    assert TOKEN not in request.full_url
    assert RESOURCE_KEY not in request.full_url
    assert _auth_header(request) == 'Bearer ' + TOKEN
    expected = None if key is None else DOC_ID + '/' + RESOURCE_KEY
    assert _resource_header(request) == expected


def test_resource_key_header_rejects_injection_and_url_leak():
    for bad in ('bad\nkey', 'bad\rkey', 'bad:key', 'bad/key', 'bad key', 'x' * 257, 'bad!'):
        with pytest.raises(HTTPException):
            drive_intake.resource_keys_header_value(FILE_ID, bad)
    for bad in ('bad\nid', 'bad:id', 'bad/id with space'):
        with pytest.raises(HTTPException):
            drive_intake.resource_keys_header_value(bad, RESOURCE_KEY)
    with pytest.raises(HTTPException) as invalid:
        drive_intake._http_get(
            drive_intake.build_metadata_url(FILE_ID, None),
            TOKEN,
            10000,
            resource_keys='bad\nheader',
        )
    assert invalid.value.status_code == 502
    for url in (
        'https://www.googleapis.com/drive/v3/files/demo-file-01?fields=id&resourceKey=abc',
        'https://www.googleapis.com/drive/v3/files/demo-file-01?alt=media&resource_key=abc',
        'https://www.googleapis.com/drive/v3/files/demo-file-01/export?mimeType=text%2Fplain&resourceKey=abc',
        'https://www.googleapis.com/drive/v3/files/demo-file-01?alt=media&access_token=abc',
    ):
        with pytest.raises(HTTPException) as leaked:
            drive_intake.check_drive_url(url)
        assert leaked.value.status_code == 502


def test_redirect_and_host_refused_via_opener():
    with pytest.raises(HTTPException) as direct:
        drive_intake._NoRedirect().redirect_request(None, None, 302, 'Found', {}, 'https://evil.invalid/')
    assert direct.value.status_code == 502
    moved = FakeOpener(response=FakeResponse(b'moved', FakeHeaders({}), 302))
    with patch.object(drive_intake.urllib.request, 'build_opener', return_value=moved):
        with pytest.raises(HTTPException) as status:
            drive_intake._http_get(drive_intake.build_metadata_url(FILE_ID, None), TOKEN, 10000)
    assert status.value.status_code == 502
    assert len(moved.requests) == 1
    assert TOKEN not in moved.requests[0].full_url
    http_error = urllib.error.HTTPError(
        drive_intake.build_metadata_url(FILE_ID, None), 301, 'Moved', {}, None
    )
    redirect_error = FakeOpener(error=http_error)
    with patch.object(drive_intake.urllib.request, 'build_opener', return_value=redirect_error):
        with pytest.raises(HTTPException) as moved_error:
            drive_intake._http_get(drive_intake.build_metadata_url(FILE_ID, None), TOKEN, 10000)
    assert moved_error.value.status_code == 502
    for bad_url in (
        'http://www.googleapis.com/drive/v3/files/demo-file-01?alt=media',
        'https://evil.invalid/drive/v3/files/demo-file-01?alt=media',
    ):
        with pytest.raises(HTTPException) as host:
            drive_intake.check_drive_url(bad_url)
        assert host.value.status_code == 502
