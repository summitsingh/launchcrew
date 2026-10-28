"""Optional demo-only SAM transport. Geometry stays in memory, never in receipts."""
import json
import os
from pathlib import Path
import re
from time import monotonic
from urllib.request import Request, urlopen
from uuid import uuid4

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
        remaining = line[frame.end():]
        while remaining:
            match = RECORD.match(remaining)
            if not match:
                raise ValueError('Invalid lossless SAM record')
            values = match.groups()
            records.append({'frame': int(frame[1]), 'object_id': int(values[0]),
                            'box': tuple(map(int, values[1:7])),
                            'mask': {'x': int(values[7]), 'y': int(values[8]),
                                     'height': int(values[9]), 'width': int(values[10]),
                                     'encoding': 'lossless', 'payload': values[11]}})
            remaining = remaining[match.end():]
            if remaining:
                if not remaining.startswith(','):
                    raise ValueError('Invalid SAM separator')
                remaining = remaining[1:]
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

        def send(endpoint, body, content_type):
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise TimeoutError()
            return urlopen(Request(os.environ.get('META_API_BASE_URL', 'https://api.meta.ai/v1').rstrip('/') + endpoint,
                                   data=body, headers={'Authorization': 'Bearer ' + key,
                                                       'Content-Type': content_type, 'Accept': 'text/event-stream'}),
                           timeout=remaining)

        boundary = 'launchcrew' + uuid4().hex
        mime = 'image/png' if path.suffix.lower() == '.png' else 'image/jpeg'
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="purpose"\r\n\r\nuser_data\r\n'
                f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="demo{path.suffix.lower()}"\r\n'
                f'Content-Type: {mime}\r\n\r\n').encode() + path.read_bytes() + f'\r\n--{boundary}--\r\n'.encode()
        with send('/files', body, 'multipart/form-data; boundary=' + boundary) as response:
            file_id = json.load(response)['id']
        if not isinstance(file_id, str) or not file_id:
            raise ValueError('Missing file id')
        payload = {'model': 'sam-3.1', 'input': [{'type': 'message', 'role': 'user', 'content': [
            {'type': 'input_text', 'text': 'jacket'}, {'type': 'input_image', 'file_id': file_id}]}],
            'stream': True, 'metadata': {'mask_encoding': 'lossless'}}
        with send('/responses', json.dumps(payload).encode(), 'application/json') as response:
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
