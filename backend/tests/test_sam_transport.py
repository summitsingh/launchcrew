"""Offline SAM transport header, order, and failure semantics. No provider access."""
import io
import json
from unittest.mock import patch
from urllib.request import Request

import pytest

from backend import sam


def sse(*events):
    return io.BytesIO(b''.join(b'data: ' + json.dumps(e).encode() + b'\n\n' for e in events))


TAG = '<0f>2<|box;x1=1;y1=2;x2=3;y2=4;w=8;h=8|><|mask;x=0;y=0;data=2,2,~demo-payload|>'


def stream():
    return sse({'type': 'response.output_text.delta', 'delta': TAG[:30]},
               {'type': 'response.output_text.delta', 'delta': TAG[30:]},
               {'type': 'response.completed'})


def test_files_uses_json_accept_and_responses_uses_sse(tmp_path, monkeypatch):
    monkeypatch.setenv('META_API_KEY', 'offline-fixture')
    monkeypatch.setattr(sam, 'DEMO_PHOTOS', tmp_path)
    photo = tmp_path / 'wallet.png'
    photo.write_bytes(b'demo photo bytes')
    calls = []

    def transport(request, timeout):
        calls.append(request)
        if request.full_url.endswith('/files'):
            assert request.get_header('Accept') == 'application/json'
            assert request.get_header('Content-type', request.get_header('Content-Type')) is not None
            content_type = request.get_header('Content-type') or request.get_header('Content-Type')
            assert content_type.startswith('multipart/form-data; boundary=')
            assert b'name="purpose"' in request.data and b'user_data' in request.data
            assert b'demo photo bytes' in request.data
            return io.BytesIO(b'{"id":"file-demo"}')
        assert request.full_url.endswith('/responses')
        assert request.get_header('Accept') == 'text/event-stream'
        body = json.loads(request.data)
        assert body['model'] == 'sam-3.1' and body['stream'] is True
        assert body['metadata'] == {'mask_encoding': 'lossless'}
        assert body['input'][0]['content'][1] == {'type': 'input_image', 'file_id': 'file-demo'}
        return stream()

    with patch('backend.sam.urlopen', side_effect=transport):
        result = sam.verify_demo_photo(photo, enabled=True)
    assert result == {'method': 'sam-3.1', 'checked': True}
    assert len(calls) == 2
    assert calls[0].full_url.endswith('/files')
    assert calls[1].full_url.endswith('/responses')


def test_disabled_no_key_or_no_photo_makes_zero_calls(tmp_path, monkeypatch):
    monkeypatch.delenv('META_API_KEY', raising=False)
    monkeypatch.delenv('LAUNCHCREW_SAM_DEMO_PHOTO', raising=False)
    monkeypatch.setattr(sam, 'DEMO_PHOTOS', tmp_path)
    photo = tmp_path / 'wallet.png'
    photo.write_bytes(b'demo')
    with patch('backend.sam.urlopen', side_effect=AssertionError('no calls expected')):
        assert sam.verify_demo_photo(photo, enabled=False) == {'method': 'not_run', 'checked': False}
        assert sam.verify_demo_photo(photo, enabled=True) == {'method': 'not_run', 'checked': False}
        assert sam.verify_demo_photo(None, enabled=True) == {'method': 'not_run', 'checked': False}
        assert sam.verify_configured_demo() == {'method': 'not_run', 'checked': False}


def test_files_failure_blocks_responses_single_attempt_each(tmp_path, monkeypatch):
    monkeypatch.setenv('META_API_KEY', 'offline-fixture')
    monkeypatch.setattr(sam, 'DEMO_PHOTOS', tmp_path)
    photo = tmp_path / 'wallet.png'
    photo.write_bytes(b'demo')
    calls = []

    def failing_files(request, timeout):
        calls.append(request.full_url)
        raise OSError('files unreachable')

    with patch('backend.sam.urlopen', side_effect=failing_files):
        result = sam.verify_demo_photo(photo, enabled=True)
    assert result['method'] == 'sam-3.1'
    assert result['checked'] is False
    assert result['error_type'] == 'OSError'
    assert calls == [c for c in calls if c.endswith('/files')]
    assert len(calls) == 1


def test_redirect_refused_before_resend_at_handler_seam(monkeypatch):
    monkeypatch.setenv('META_API_KEY', 'offline-fixture')
    handler = sam._RefuseRedirect()
    request = Request('https://api.meta.ai/v1/files', data=b'photo body')
    for code in (301, 302, 303, 307, 308):
        with pytest.raises(sam.SamTransportError, match='redirect refused'):
            handler.redirect_request(request, None, code, 'redirect', {}, 'https://other.example/files')
    # The production opener carries the refusing handler, so urllib raises
    # instead of following; no second request is ever constructed or sent.
    assert any(isinstance(item, sam._RefuseRedirect) for item in sam._photo_opener().handlers)


def test_one_upload_then_one_responses_no_retry(tmp_path, monkeypatch):
    monkeypatch.setenv('META_API_KEY', 'offline-fixture')
    monkeypatch.setattr(sam, 'DEMO_PHOTOS', tmp_path)
    photo = tmp_path / 'wallet.png'
    photo.write_bytes(b'demo')
    order = []

    def counting(request, timeout):
        order.append(request.full_url)
        if request.full_url.endswith('/files'):
            return io.BytesIO(b'{"id":"file-demo"}')
        return stream()

    with patch('backend.sam.urlopen', side_effect=counting):
        result = sam.verify_demo_photo(photo, enabled=True)
    assert result['checked'] is True
    assert len(order) == 2
    assert order[0].endswith('/files') and order[1].endswith('/responses')
