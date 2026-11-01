---
name: launchcrew-socialclaw
description: Run the LaunchCrew social content flow through the REST API, hosted MCP server, or CLI. Use when validating slots, applying exported schedules, checking refusals, or uploading media for LaunchCrew.
---

# LaunchCrew SocialClaw

LaunchCrew plans social content on a shared workspace calendar. One backend
serves four surfaces over the same workspace state: the Web UI, the REST
API, the hosted MCP server, and the `launchcrew` CLI. Work done on one
surface appears on the others because every surface resolves the same
workspace from the workspace key.

## Authentication

Send the workspace key on every REST and MCP call, either as
`Authorization: Bearer <workspace_key>` or as
`X-Workspace-Key: <workspace_key>`. The CLI accepts `--workspace-key`
or the `LAUNCHCREW_WORKSPACE_KEY` environment variable, plus `--api-url`
or `LAUNCHCREW_API_URL` for the backend base URL. A missing, unknown, or
revoked key fails closed with `invalid_or_revoked_workspace_key`. Never
ask for or store the raw key beyond the session that created it.

## Core flow: validate then apply

Follow these steps in order. Each step ends when its stated check passes.

1. **Inspect the workspace.** List accounts with `GET /api/agent/accounts`
   (MCP: `launchcrew_accounts`, CLI: `launchcrew accounts`) and list
   capabilities with `GET /api/agent/capabilities` (MCP:
   `launchcrew_capabilities`, CLI: `launchcrew capabilities`). Done when
   both calls return workspace data.
2. **Export the schedule from the Web UI.** Use
   `GET /api/calendar/schedule-export`. It returns a
   `schedule-export/v1` document with `ready_slots` (Ready slots whose
   gate still passes) and `excluded_slots` (every other slot with its
   failing conditions and reasons). Done when the document validates as
   `schema_version: schedule-export/v1`.
3. **Validate before applying.** Send the slot or the whole export to
   `POST /api/agent/validate` with `{"slot_id": "..."}` or
   `{"schedule": {...}}` (MCP: `launchcrew_validate` with `slot_id`,
   CLI: `launchcrew validate --slot-id <id>` or
   `launchcrew validate export.json --schedule-file`). Done when every
   slot reports `ready_eligible: true`.
4. **Apply the export unchanged.** Send the exact exported JSON to
   `POST /api/agent/apply` (MCP: `launchcrew_apply` with `schedule`,
   CLI: `launchcrew apply schedule-export.json`). The server revalidates
   every `ready_slots` entry against the gate and confirms each passing
   slot as Ready with `applied_via: agent_apply`. Done when the response
   lists the slot in `applied_slot_ids` and the Web UI shows the same
   slot as Ready.
5. **Check run status.** Use `GET /api/agent/runs/{run_id}/status` or
   `GET /api/agent/status` (MCP: `launchcrew_run_status`, CLI:
   `launchcrew run-status [--run-id ...]`). Done when the approval state
   and schedule counts match what the Web UI shows.

## Schedule export schema

The export document uses `schema_version: schedule-export/v1` with
`ready_slots` and `excluded_slots`. Keep the file byte-identical between
export and apply. Each ready slot carries `slot_id`, `slot_date`,
`planned_time`, `slot_type`, `pillar`, `format_key`, `run_id`,
`campaign_id`, `day_number`, `selected_channels`, `channel_variants`,
and `pack_reference` (run id, approval state, revision, binding digest).
The apply endpoint verifies every ready slot against the gate, confirms
each passing slot as Ready with its planned time, slot date, and
selected channels, and returns `applied_slot_ids` plus any
`refused_slots` with reasons.

## Media upload

Upload once with `POST /api/agent/upload`
(`{"filename": "...", "width": 1080, "height": 1350}` plus optional
`mime_type`, `duration_seconds`, `data_b64`) so the asset lands in the
workspace Media Library (MCP: `launchcrew_upload`, CLI:
`launchcrew upload --filename ... --width ... --height ...`). Done when
the response includes the asset id with format facts and derivatives.

## Refusal rules

Every refusal names its reason. Resolve each failing condition, then
validate again. There is no override.

- `invalid_or_revoked_workspace_key` (401): the key is missing,
  unknown, or revoked. Create a fresh key in the Web UI.
- `pack_not_approved` (409): the linked pack is not approved. Approve
  the run for export first.
- `format_check_failed` (409): the format check failed. The
  `format_reason` names the exact block, such as the frame count or
  aspect mismatch. Fix the pack first.
- `unapproved_channel_variants` (409): one or more selected channels
  are not approved. Approve each named channel variant first.
- `not_marked_ready` (409): the slot is not marked Ready. Mark it Ready
  after the gate passes.
- `slot_not_found` (409): the slot id is not in this workspace. Check
  the export and the workspace.

Validate refusals carry `failing_conditions`, human-readable `details`,
per-condition `checks`, `unapproved_channels`, and `format_reason`. The
MCP validate tool reports the same refusal with `is_error: true`.
