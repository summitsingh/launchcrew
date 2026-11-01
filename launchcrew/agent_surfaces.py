"""SC6 agent surfaces domain: workspace keys, MCP tools, and skill metadata.

One shared workspace state backs all four surfaces (Web UI, REST API,
hosted MCP server, CLI). A workspace key is a bearer secret bound to one
workspace_id; only its SHA-256 hash is stored. The six MCP tools mirror
the six agent REST operations. The installable skill document teaches
external agents the validate-then-apply pattern and the refusal rules.
"""

from __future__ import annotations

import hashlib
import secrets
from typing import Any

KEY_PREFIX = 'lc_wk_'

DEFAULT_SCOPES = (
    'accounts',
    'capabilities',
    'upload',
    'validate',
    'apply',
    'run_status',
    'mcp',
)

MCP_TOOL_NAMES = (
    'launchcrew_accounts',
    'launchcrew_capabilities',
    'launchcrew_upload',
    'launchcrew_validate',
    'launchcrew_apply',
    'launchcrew_run_status',
)

REFUSAL_RULES = (
    {
        'code': 'invalid_or_revoked_workspace_key',
        'reason': 'The workspace key is missing, unknown, or revoked.',
        'http_status': 401,
    },
    {
        'code': 'pack_not_approved',
        'reason': 'Pack is not approved. Approve the linked run for export first.',
        'http_status': 409,
    },
    {
        'code': 'format_check_failed',
        'reason': 'Format check failed. Fix the named format reason first.',
        'http_status': 409,
    },
    {
        'code': 'unapproved_channel_variants',
        'reason': 'Channel variants are not approved. Approve each selected channel first.',
        'http_status': 409,
    },
    {
        'code': 'not_marked_ready',
        'reason': 'Slot is not marked Ready. Mark it Ready after the gate passes.',
        'http_status': 409,
    },
)

SKILL_NAME = 'launchcrew-socialclaw'
SKILL_VERSION = '1.0.0'

MCP_TOOL_DESCRIPTIONS = {
    'launchcrew_accounts': 'List workspace social connections and platform status (same state as the Web UI).',
    'launchcrew_capabilities': 'List live plus baseline channel capabilities (same state as the Web UI).',
    'launchcrew_upload': 'Upload a media asset into the workspace Media Library.',
    'launchcrew_validate': 'Validate one slot against the validate gate. Refusals name every failing condition.',
    'launchcrew_apply': 'Apply an exported schedule file unchanged (validate-then-apply).',
    'launchcrew_run_status': 'Read run status, approval state, and workspace schedule status.',
}


def generate_raw_key() -> str:
    return KEY_PREFIX + secrets.token_hex(24)


def hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


def key_prefix(raw_key: str) -> str:
    return raw_key[:12]


def new_key_id() -> str:
    return 'wkey_' + secrets.token_hex(8)


def mcp_tools() -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = [
        {'name': 'launchcrew_accounts',
         'description': MCP_TOOL_DESCRIPTIONS['launchcrew_accounts'],
         'input_schema': {'type': 'object', 'properties': {}}},
        {'name': 'launchcrew_capabilities',
         'description': MCP_TOOL_DESCRIPTIONS['launchcrew_capabilities'],
         'input_schema': {'type': 'object', 'properties': {}}},
        {'name': 'launchcrew_upload',
         'description': MCP_TOOL_DESCRIPTIONS['launchcrew_upload'],
         'input_schema': {'type': 'object',
                          'properties': {'filename': {'type': 'string'},
                                         'mime_type': {'type': 'string'},
                                         'width': {'type': 'number'},
                                         'height': {'type': 'number'},
                                         'duration_seconds': {'type': 'number'},
                                         'data_b64': {'type': 'string'}},
                          'required': ['filename']}},
        {'name': 'launchcrew_validate',
         'description': MCP_TOOL_DESCRIPTIONS['launchcrew_validate'],
         'input_schema': {'type': 'object',
                          'properties': {'slot_id': {'type': 'string'}},
                          'required': ['slot_id']}},
        {'name': 'launchcrew_apply',
         'description': MCP_TOOL_DESCRIPTIONS['launchcrew_apply'],
         'input_schema': {'type': 'object',
                          'properties': {'schedule': {'type': 'object'}},
                          'required': ['schedule']}},
        {'name': 'launchcrew_run_status',
         'description': MCP_TOOL_DESCRIPTIONS['launchcrew_run_status'],
         'input_schema': {'type': 'object',
                          'properties': {'run_id': {'type': 'string'}}}},
    ]
    return tools


def skill_tools() -> list[str]:
    return list(MCP_TOOL_NAMES)


def refusal_rules() -> list[dict[str, Any]]:
    return [dict(rule) for rule in REFUSAL_RULES]
