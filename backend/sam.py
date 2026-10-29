"""SAM Files plus Responses transport. Geometry stays in memory, never in receipts.

Files uploads request a one hour expiry via expires_after anchor created_at
plus 3600 seconds, sent before the final file part. The product path
(upload_and_segment) validates integer created_at and expires_at with an
exact 3600 difference plus a valid file id before any segmentation call.
Missing or invalid upload metadata ends terminal with budget spent, no retry,
and no third DELETE cleanup call. Published SAM price seen as 0.0025 per
image; a Files upload or storage fee free statement was not found, so no
all free claim is made. Limited operations plus one hour expiry are proof
assumptions, not a verified hard provider cap. Root verifies current primary
price and operation bound before any live call.
"""
import json
import os
from pathlib import Path
import re
from time import monotonic
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import uuid4

SAM_FILE_EXPIRY_SECONDS = 3600
SAM_FILE_EXPIRY_ANCHOR = 'created_at'


class SamTransportError(RuntimeError):
    """A bounded SAM Files-to-Responses sequence did not complete.

    ``uploads``/``segmentations`` count the provider calls actually made
    before the failure, so finalization can report honest accounting.
    """

    def __init__(self, message, *, uploads=0, segmentations=0):
        super().__init__(message)
        self.uploads = uploads
        self.segmentations = segmentations


class _RefuseRedirect(HTTPRedirectHandler):
    """Refuse any redirect before the request body could be resent.

    urllib invokes ``redirect_request`` instead of following; raising here
    guarantees the second request is never constructed or sent.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise SamTransportError('redirect refused; body not resent')


def _photo_opener():
    return build_opener(_RefuseRedirect)


def urlopen(request, timeout=None):
    """Module urlopen seam: production traffic refuses redirects pre-follow.

    Tests keep patching ``backend.sam.urlopen``; unpatched calls go through
    an opener whose redirect handler raises before any resend.
    """
    return _photo_opener().open(request, timeout=timeout)


def _files_body(boundary, filename, mime, raw_bytes):
    """Multipart Files body with one hour expiry parts before the file part.

    Part order is fixed: purpose, expires_after anchor, expires_after
    seconds, then file. Callers keep original exact bytes unchanged.
    """
    head = (f'--{boundary}\r\nContent-Disposition: form-data; name="purpose"\r\n\r\nuser_data\r\n'
            f'--{boundary}\r\nContent-Disposition: form-data; name="expires_after[anchor]"\r\n\r\n'
            f'{SAM_FILE_EXPIRY_ANCHOR}\r\n'
            f'--{boundary}\r\nContent-Disposition: form-data; name="expires_after[seconds]"\r\n\r\n'
            f'{SAM_FILE_EXPIRY_SECONDS}\r\n'
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f'Content-Type: {mime}\r\n\r\n').encode()
    return head + raw_bytes + f'\r\n--{boundary}--\r\n'.encode()


def _validate_files_upload(payload, progress):
    """Strict product validation for a Files upload response.

    Requires a non-empty string id plus integer (not bool) created_at and
    expires_at with an exact 3600 difference. Returns the file id.
    Raises SamTransportError on any missing or invalid field. No DELETE
    cleanup is attempted; the caller treats this as terminal with budget
    already spent.
    """
    try:
        file_id = payload.get('id') if isinstance(payload, dict) else None
        created = payload.get('created_at') if isinstance(payload, dict) else None
        expires = payload.get('expires_at') if isinstance(payload, dict) else None
    except Exception:
        raise SamTransportError('Invalid files upload response', **progress)
    if not isinstance(file_id, str) or not file_id:
        raise SamTransportError('Missing file id', **progress)
    if type(created) is not int or type(expires) is not int:
        raise SamTransportError('Invalid files expiry metadata', **progress)
    if expires - created != SAM_FILE_EXPIRY_SECONDS:
        raise SamTransportError('Invalid files expiry window', **progress)
    return file_id


DEMO_PHOTOS = Path(__file__).resolve().parents[1] / 'facts' / 'demo_photos'
# Concept prompts return paired boxes and lossless masks, documented by Meta.
RECORD = re.compile(
    r'(\d+)<\|box;x1=(\d+);y1=(\d+);x2=(\d+);y2=(\d+);w=(\d+);h=(\d+)'
    r'(?:;c=[\d.]+)?\|><\|mask;x=(-?\d+);y=(-?\d+)(?:;c=[\d.]+)?;data=(\d+),(\d+),~([^|]+)\|>')


def parse_sse(lines):
    """Consume SSE events, including split deltas and multi-line data fields."""
    deltas, data = [], []
    completed = False

    def consume():
        nonlocal completed
        if not data:
            return
        payload = '\n'.join(data)
        data.clear()
        if payload == '[DONE]':
            return
        event = json.loads(payload)
        kind = event.get('type')
        if kind in ('error', 'response.failed', 'response.incomplete'):
            raise RuntimeError('SAM stream failed')
        if kind == 'response.output_text.delta':
            deltas.append(event['delta'])
        if kind == 'response.completed':
            if event.get('response', {}).get('status', 'completed') != 'completed':
                raise RuntimeError('SAM incomplete')
            completed = True

    for raw_line in lines:
        line = raw_line.decode('utf-8').rstrip('\r\n')
        if not line:
            consume()
        elif line.startswith('data:'):
            data.append(line[5:].lstrip(' '))
    consume()
    if not completed:
        raise ValueError('SAM stream did not complete')
    text = ''.join(deltas)
    records = []
    for line in text.splitlines():
        frame = re.match(r'<(\d+)f>', line)
        if not frame:
            raise ValueError('Invalid SAM frame')
        line_frame = int(frame[1])
        remaining = line[frame.end():]
        while remaining:
            match = RECORD.match(remaining)
            if not match:
                raise ValueError('Invalid lossless SAM record')
            values = match.groups()
            records.append({'frame': line_frame, 'object_id': int(values[0]),
                            'box': tuple(map(int, values[1:7])),
                            'mask': {'x': int(values[7]), 'y': int(values[8]),
                                     'height': int(values[9]), 'width': int(values[10]),
                                     'encoding': 'lossless', 'payload': values[11]}})
            remaining = remaining[match.end():]
            if remaining:
                if not remaining.startswith(','):
                    raise ValueError('Invalid SAM separator')
                remaining = remaining[1:]
                repeated = re.match(r'<(\d+)f>', remaining)
                if repeated:
                    if int(repeated[1]) != line_frame:
                        raise ValueError('Invalid SAM frame')
                    remaining = remaining[repeated.end():]
    return records


def verify_demo_photo(photo=None, *, enabled=False):
    """Only a server-selected photo beneath facts/demo_photos can be uploaded."""
    result = {'method': 'not_run', 'checked': False}
    key = os.environ.get('META_API_KEY', '').strip()
    if not enabled or not key or photo is None:
        return result
    result['method'] = 'sam-3.1'
    try:
        path = Path(photo).resolve()
        if (not path.is_relative_to(DEMO_PHOTOS.resolve()) or path.suffix.lower() not in ('.png', '.jpg', '.jpeg')
                or not path.is_file()):
            raise ValueError('Demo photo required')
        deadline = monotonic() + 30

        def send(endpoint, body, content_type, accept):
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise TimeoutError()
            return urlopen(Request(os.environ.get('META_API_BASE_URL', 'https://api.meta.ai/v1').rstrip('/') + endpoint,
                                   data=body, headers={'Authorization': 'Bearer ' + key,
                                                       'Content-Type': content_type, 'Accept': accept}),
                           timeout=remaining)

        boundary = 'launchcrew' + uuid4().hex
        mime = 'image/png' if path.suffix.lower() == '.png' else 'image/jpeg'
        body = _files_body(boundary, 'demo' + path.suffix.lower(), mime, path.read_bytes())
        with send('/files', body, 'multipart/form-data; boundary=' + boundary, 'application/json') as response:
            file_id = json.load(response)['id']
        if not isinstance(file_id, str) or not file_id:
            raise ValueError('Missing file id')
        payload = {'model': 'sam-3.1', 'input': [{'type': 'message', 'role': 'user', 'content': [
            {'type': 'input_text', 'text': 'jacket'}, {'type': 'input_image', 'file_id': file_id}]}],
            'stream': True, 'metadata': {'mask_encoding': 'lossless'}}
        with send('/responses', json.dumps(payload).encode(), 'application/json', 'text/event-stream') as response:
            def bounded_lines():
                for line in response:
                    if monotonic() >= deadline:
                        raise TimeoutError()
                    yield line
            parse_sse(bounded_lines())
        # Checked means segmentation completed, including zero matches. No approval verdict.
        result['checked'] = True
    except Exception as error:
        result['error_type'] = type(error).__name__
    return result


def verify_configured_demo():
    name = os.environ.get('LAUNCHCREW_SAM_DEMO_PHOTO', '')
    return verify_demo_photo(DEMO_PHOTOS / name if name else None, enabled=bool(name))


def photo_sam_operable():
    """Operator feature flag plus key presence. Never proof of credits."""
    key = os.environ.get('META_API_KEY', '').strip()
    enabled = os.environ.get('LAUNCHCREW_PHOTO_SAM_ENABLED', '').strip().lower() == 'true'
    return bool(key and enabled)


def upload_and_segment(raw_bytes, mime, concept='product', timeout_s=30.0):
    """One Files upload plus one Responses segmentation, no retries.

    The Responses call happens only after a valid upload id plus integer
    created_at and expires_at with an exact 3600 difference, all held in
    memory. A redirect that would resend the body is refused instead.
    Raises SamTransportError on any failure. Returns parsed records.
    No DELETE cleanup is attempted after a failed upload validation.
    """
    key = os.environ.get('META_API_KEY', '').strip()
    if not key:
        raise SamTransportError('SAM not configured')
    if mime not in ('image/png', 'image/jpeg'):
        raise SamTransportError('Unsupported image mime')
    deadline = monotonic() + timeout_s
    progress = {'uploads': 0, 'segmentations': 0}

    def send(endpoint, body, content_type, accept):
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise SamTransportError('SAM sequence timed out', **progress)
        request = Request(os.environ.get('META_API_BASE_URL', 'https://api.meta.ai/v1').rstrip('/') + endpoint,
                          data=body, headers={'Authorization': 'Bearer ' + key,
                                              'Content-Type': content_type, 'Accept': accept})
        progress['uploads' if endpoint == '/files' else 'segmentations'] += 1
        try:
            return urlopen(request, timeout=remaining)
        except SamTransportError as error:
            error.uploads = max(error.uploads, progress['uploads'])
            error.segmentations = max(error.segmentations, progress['segmentations'])
            raise
        except Exception as error:
            raise SamTransportError(type(error).__name__ + ': transport failed', **progress)

    try:
        boundary = 'launchcrew' + uuid4().hex
        suffix = '.png' if mime == 'image/png' else '.jpg'
        body = _files_body(boundary, 'photo' + suffix, mime, raw_bytes)
        with send('/files', body, 'multipart/form-data; boundary=' + boundary, 'application/json') as response:
            payload = json.load(response)
        file_id = _validate_files_upload(payload, progress)
        payload = {'model': 'sam-3.1', 'input': [{'type': 'message', 'role': 'user', 'content': [
            {'type': 'input_text', 'text': concept}, {'type': 'input_image', 'file_id': file_id}]}],
            'stream': True, 'metadata': {'mask_encoding': 'lossless'}}
        with send('/responses', json.dumps(payload).encode(), 'application/json', 'text/event-stream') as response:
            def bounded_lines():
                for line in response:
                    if monotonic() >= deadline:
                        raise SamTransportError('SAM sequence timed out', **progress)
                    yield line
            return parse_sse(bounded_lines())
    except SamTransportError:
        raise
    except Exception as error:
        raise SamTransportError(type(error).__name__ + ': segmentation failed', **progress)
