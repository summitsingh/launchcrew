"""LaunchCrew agent CLI: drive the four-surface flow from a terminal.

The CLI reads and writes the exact same workspace state as the Web UI,
the REST API, and the hosted MCP server. Authentication uses a workspace
key (``--workspace-key`` or ``LAUNCHCREW_WORKSPACE_KEY``) sent as
``X-Workspace-Key`` (``Authorization: Bearer`` also works). The base URL
comes from ``--api-url`` or ``LAUNCHCREW_API_URL``.

The headline flow is validate-then-apply: export the validated schedule
JSON from the Web UI (``GET /api/calendar/schedule-export``), validate
it, then apply it unchanged::

    launchcrew validate schedule-export.json
    launchcrew apply schedule-export.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

DEFAULT_API_URL = 'http://127.0.0.1:8000'


def _workspace_key(explicit: str | None) -> str | None:
    if explicit:
        return explicit
    return os.environ.get('LAUNCHCREW_WORKSPACE_KEY')


def _api_url(explicit: str | None) -> str:
    if explicit:
        return explicit.rstrip('/')
    return os.environ.get('LAUNCHCREW_API_URL', DEFAULT_API_URL).rstrip('/')


def _headers(workspace_key: str | None) -> dict[str, str]:
    if workspace_key:
        return {'X-Workspace-Key': workspace_key}
    return {}


def _post(client: Any, api_url: str, path: str, payload: dict[str, Any],
          workspace_key: str | None) -> Any:
    headers = _headers(workspace_key)
    if client is not None:
        return client.post(path, json=payload, headers=headers or None)
    import httpx
    with httpx.Client(base_url=api_url, timeout=60) as http:
        return http.post(path, json=payload, headers=headers)


def _get(client: Any, api_url: str, path: str, workspace_key: str | None) -> Any:
    headers = _headers(workspace_key)
    if client is not None:
        return client.get(path, headers=headers or None)
    import httpx
    with httpx.Client(base_url=api_url, timeout=60) as http:
        return http.get(path, headers=headers)


def _read_schedule_file(path: str) -> dict[str, Any]:
    document = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(document, dict):
        raise ValueError('schedule file must hold a JSON object')
    return document


def _emit(response: Any) -> Any:
    try:
        body = response.json()
    except Exception:
        body = {'status_code': response.status_code, 'text': response.text}
    if response.status_code >= 400:
        detail = body.get('detail') if isinstance(body, dict) else None
        print(json.dumps(body, indent=2, sort_keys=True))
        raise SystemExit('Request failed with status %d%s' % (
            response.status_code,
            (': ' + json.dumps(detail, sort_keys=True)) if detail else ''))
    print(json.dumps(body, indent=2, sort_keys=True))
    return body


def apply_schedule_file(path: str, api_url: str = DEFAULT_API_URL,
                        workspace_key: str | None = None, client: Any = None) -> dict[str, Any]:
    """Apply an exported schedule file unchanged. Returns the parsed result."""
    document = _read_schedule_file(path)
    return _emit(_post(client, api_url, '/api/agent/apply', document, workspace_key))


def validate_schedule(path_or_slot: str, api_url: str = DEFAULT_API_URL,
                      workspace_key: str | None = None, client: Any = None,
                      from_file: bool = False) -> dict[str, Any]:
    """Validate one slot id or one exported schedule file against the gate."""
    if from_file:
        payload: dict[str, Any] = {'schedule': _read_schedule_file(path_or_slot)}
    else:
        payload = {'slot_id': path_or_slot}
    return _emit(_post(client, api_url, '/api/agent/validate', payload, workspace_key))


def upload_asset(payload: dict[str, Any], api_url: str = DEFAULT_API_URL,
                 workspace_key: str | None = None, client: Any = None) -> dict[str, Any]:
    return _emit(_post(client, api_url, '/api/agent/upload', payload, workspace_key))


def show_run_status(run_id: str | None, api_url: str = DEFAULT_API_URL,
                    workspace_key: str | None = None, client: Any = None) -> dict[str, Any]:
    path = '/api/agent/runs/%s/status' % run_id if run_id else '/api/agent/status'
    return _emit(_get(client, api_url, path, workspace_key))


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument('--api-url', default=None,
                        help='Backend base URL (default LAUNCHCREW_API_URL or http://127.0.0.1:8000).')
    common.add_argument('--workspace-key', default=None,
                        help='Workspace key (default LAUNCHCREW_WORKSPACE_KEY).')
    parser = argparse.ArgumentParser(prog='launchcrew',
                                     description='LaunchCrew agent CLI over the shared workspace state.',
                                     parents=[common])
    sub = parser.add_subparsers(dest='command', required=True)

    apply_cmd = sub.add_parser('apply', aliases=['apply-schedule'], parents=[common],
                               help='Apply an exported schedule file unchanged.')
    apply_cmd.add_argument('schedule_json_path', help='Path to schedule-export/v1 JSON.')

    validate_cmd = sub.add_parser('validate', parents=[common],
                                  help='Validate one slot or schedule file.')
    validate_cmd.add_argument('target', help='Slot id, or schedule file with --schedule-file.')
    validate_cmd.add_argument('--schedule-file', action='store_true',
                              help='Treat target as an exported schedule file.')

    sub.add_parser('accounts', parents=[common], help='List workspace social connections.')
    sub.add_parser('capabilities', parents=[common],
                   help='List live plus baseline channel capabilities.')

    upload_cmd = sub.add_parser('upload', parents=[common],
                                help='Upload a media asset to the Media Library.')
    upload_cmd.add_argument('--filename', required=True)
    upload_cmd.add_argument('--mime-type', default=None)
    upload_cmd.add_argument('--width', type=int, default=None)
    upload_cmd.add_argument('--height', type=int, default=None)
    upload_cmd.add_argument('--duration-seconds', type=float, default=None)
    upload_cmd.add_argument('--data-b64', default=None)

    status_cmd = sub.add_parser('run-status', parents=[common],
                                help='Show run or workspace status.')
    status_cmd.add_argument('--run-id', default=None)
    return parser


def main(argv: list[str] | None = None, client: Any = None) -> dict[str, Any]:
    args = build_parser().parse_args(argv)
    api_url = _api_url(args.api_url)
    workspace_key = _workspace_key(args.workspace_key)
    if args.command in ('apply', 'apply-schedule'):
        return apply_schedule_file(args.schedule_json_path, api_url, workspace_key, client)
    if args.command == 'validate':
        return validate_schedule(args.target, api_url, workspace_key, client,
                                 from_file=bool(args.schedule_file))
    if args.command == 'accounts':
        response = _get(client, api_url, '/api/agent/accounts', workspace_key)
        return _emit(response)
    if args.command == 'capabilities':
        response = _get(client, api_url, '/api/agent/capabilities', workspace_key)
        return _emit(response)
    if args.command == 'upload':
        payload = {'filename': args.filename}
        if args.mime_type is not None:
            payload['mime_type'] = args.mime_type
        if args.width is not None:
            payload['width'] = args.width
        if args.height is not None:
            payload['height'] = args.height
        if args.duration_seconds is not None:
            payload['duration_seconds'] = args.duration_seconds
        if args.data_b64 is not None:
            payload['data_b64'] = args.data_b64
        return upload_asset(payload, api_url, workspace_key, client)
    if args.command == 'run-status':
        return show_run_status(args.run_id, api_url, workspace_key, client)
    raise SystemExit('Unknown command: %s' % args.command)


if __name__ == '__main__':
    main()
