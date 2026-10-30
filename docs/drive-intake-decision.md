# Drive selected-file intake decision, source-only

Status: source wiring only. Live Drive proof has NOT been run, is NOT claimed, and is NOT done in this task. `live_verified` stays false. Pasted-text import and Google identity sign-in stay unchanged as the default paths.

## Complete scope

This connector adds an optional Google Picker intake for one user-selected file, without replacing existing flows:

- Google Picker user selection with `https://www.googleapis.com/auth/drive.file` scope. Google documents this scope as per-file selected access, but the scope technically permits edits. Product code only calls read-only Drive file metadata, get, export, and download APIs. It never calls create, update, delete, or permissions APIs.
- Separate incremental Drive consent via GIS, requested only in the Drive intake UI. Ordinary sign-in stays `openid profile email` only in `backend/auth.py`. No sign-in scope is broadened.
- Only the Picker-selected file ID and resource key may be read. The API accepts no URLs and no workspace ID. Workspace is derived server-side from the LaunchCrew actor. Anonymous use fails closed, and foreign workspace use fails closed.
- Supported demo set: Google Docs export to plain text (`application/vnd.google-apps.document` exported as `text/plain`) and plain text download (`text/plain`). All other types fail closed, including photos, PDFs, HTML, video, and binary. No photos in Picker views or server handling.
- Explicit bounds, enforced before allocation: max 200000 bytes per file, max 10000 text chars for parsing, max 3 provider requests per import (tokeninfo, metadata, content), max 20 suggestions, max 500 chars per suggestion via the shared parser. Content-Length is checked before reading. Downloads stream with a hard cap.
- Closed refusals: arbitrary URLs, redirect following, wrong host, missing scope, expired token, nonselected file, trashed file, ID mismatch, unsupported MIME, oversize content, non-text bytes, and deceptive Content-Type.
- No logging or persistence of provider access token, raw capability URL or key, file bytes, or personal contents. Success returns a sanitized file title, MIME label, and generic selection context for owner UI only. No provider file ID, resource key, token, or bytes appear in responses, receipts, or logs.
- Bounded candidate facts as UNCONFIRMED with `drive_file` provenance. Never auto-confirm, never auto-add to Memory, never auto-publish, and never present provider text as verified marketing facts. The existing owner fact confirmation flow is reused. Public receipts stay free of provider identifiers.
- Public app stays keyless for this connector: no Meta calls, no model calls, no database writes. Product works without Drive configuration, with a clear optional unavailable state. Pasted-text import still works.

## Nov 3 Central planning assumption

Nov 3 is a Central planning target, not a proof date. Nov 4 is the deadline. A practical named-test-user demo path is implemented now in source, but development with named test users does not imply production readiness, review approval, or live authorization. Schedule risk remains until external consent, test user setup, and any required review are complete. Do not present planning alignment as live Drive proof.

## Practical named-test-user demo path now

This path uses synthetic test identities only, for example `synthetic-test-user-01` and `synthetic-test-user-02` in mocked tests. No personal names, emails, accounts, or asset filenames are used.

1. Operator configures the three public Drive inputs in server environment only (see Configuration). No value goes in source, commits, logs, or docs.
2. Owner signs in with existing Google identity sign-in when enabled, or uses demo placeholder mode when disabled. Drive intake binds to that actor and workspace.
3. Owner opens owner-input mode, sees Drive status, and chooses Choose Drive file. The UI loads official GIS and Picker libraries, requests a short lived GIS token for `drive.file` scope only, and shows a Picker filtered to Google Docs and plain text.
4. Owner selects one file in Picker. The UI holds the selection ephemerally and posts only file ID, optional resource key, and GIS token to `POST /api/drive-import/suggestions`.
5. Backend validates scope and expiry, reads metadata, enforces MIME and size bounds, downloads or exports bounded text with no redirects, parses with the shared unconfirmed parser, and returns unconfirmed suggestions with Drive file provenance and sanitized title context.
6. Owner edits suggestions and explicitly adds chosen lines as unconfirmed allowed claims, then explicitly confirms each in the existing fact form. Only confirmed values with `drive_file` source can become evidence in a later run. Unconfirmed values stay suggestions.

## External Google consent and review gate, honestly

This source change is not a silent feature cut, and it is not live proof. The following external gates remain outside this task:

- The Google Cloud OAuth client currently carries identity scopes only. Drive API enablement, Picker enablement, and incremental `drive.file` consent setup may be needed in the Cloud console. This task makes no external account change and requests no approval.
- External Testing may limit use to named test users, and consent may expire. A test user count alone proves nothing about live intake from this source. Do not present it as production access or verified intake.
- Public production authorization may require Google review for the Drive scope. Review status is unknown here. Production use stays blocked until review, consent, and deployment checks are explicitly approved.
- No live Drive call is made in source work or tests. All provider responses in tests are fake. Provider API calls stay disabled in tests.

## Configuration inputs, exact names without values

Public Drive inputs live only in server process environment. They are never in source or commits. The backend serves only the public subset to the signed-in frontend via `GET /api/drive-import/config`. No secret is served.

- `GOOGLE_DRIVE_CLIENT_ID`: public OAuth client ID used by GIS for incremental `drive.file` consent. Served to frontend. No secret value here.
- `GOOGLE_DRIVE_API_KEY`: public browser API key used by Picker. Served to frontend. No secret value here.
- `GOOGLE_DRIVE_APP_ID`: Cloud project number used by Picker. Served to frontend. No secret value here.
- `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`: existing identity sign-in credentials with `openid profile email` only. Unchanged. Never broadened for Drive. Never served to frontend.

When any Drive public input is missing, `GET /api/drive-import/status` reports `available` false with reason `drive_not_configured`, `GET /api/drive-import/config` returns 503, and `POST /api/drive-import/suggestions` returns 503. Pasted-text import still works.

## Bounded workflow and failure states

- `GET /api/drive-import/status`: actor bound status with `available`, `configured`, `live_verified` false, `scope`, `supported_mime_types`, `max_bytes`, `max_requests`, and `reason`.
- `GET /api/drive-import/config`: actor bound public Picker config only. 503 when unconfigured. 401 when LaunchCrew sign-in is required.
- `POST /api/drive-import/suggestions`: body carries `file_id`, optional `resource_key`, and `drive_token`. Stateless, no database writes. Response carries `status` unconfirmed, `source` drive_file, `product_fact_source` drive_file, `file_title`, `mime_type`, `selection_context` Drive file selection, bounded `suggestions` with `confirmed` false, drop counts, and `parser_version` drive-import/v1.
- Failure codes use generic details with no IDs, tokens, bytes, or titles: 401 for LaunchCrew sign-in required, 403 for Drive consent required or file unavailable or not selected, 413 for too large, 422 for unsupported type or invalid selection, 502 for provider error, 503 for unavailable. The UI maps these to actionable hints and always offers pasted-text import.

## Files

- `backend/drive_intake.py`: feature scoped connector, validation, read-only provider, and API routes. No Meta calls, no sign-in change, no outcome or migration change.
- `backend/app.py`: additive router include plus `drive_file` in product fact source type only.
- `launchcrew/import_suggestions.py`: additive `drive_file` source in shared unconfirmed parser.
- `launchcrew/facts.py`: additive `drive_file` provenance label.
- `web/src/lib/drive-intake.ts`: Drive scope, MIME, bounds, validation, and unconfirmed mapping helpers.
- `web/src/components/drive-intake-form.tsx`: official GIS plus Picker intake with script loading, selection context, suggestions list, and failure states.
- `web/src/app/page.tsx`: mount Drive intake beside pasted-text import in owner-input mode.
- `web/src/lib/product-facts.ts`: additive `drive_file` label.
- `backend/openapi.json` and `web/src/lib/schema.d.ts`: regenerated contracts for Drive routes and `drive_file` provenance.
- `backend/tests/test_drive_intake_api.py`: fake provider API tests for two-user denial, token discard, selected ID binding, MIME and size and redirect refusal, and no auto-confirm.
- `web/tests/drive-intake.test.tsx`: fake intake UI tests for bounds, validation, mapping, title context without IDs, escaping, and no auto-confirm.
- `docs/drive-intake-decision.md`: this public generic decision record.

No new migration is added. Intake stays ephemeral until the owner explicitly confirms in the existing fact form, so no head promotion is required.

## Remaining external and live proof

Do not run live proof until explicit operator approval is recorded and deployment HTTPS is verified. Live proof is not in this task.

- Confirm Drive API and Picker are enabled for the Cloud project, incremental `drive.file` consent is configured, and named test users are allowlisted, without recording personal identifiers.
- Confirm `GET /api/drive-import/status` reports configured true with `live_verified` false before selection, and `GET /api/drive-import/config` returns public config only.
- With a named test user, complete GIS consent for `drive.file` only, select one Google Doc in Picker, confirm export to text and unconfirmed suggestions with Drive file provenance, then select one plain text file and confirm download path.
- Confirm second-actor isolation with two test subjects, consent expiry handling, re-pick after 403, oversize refusal, unsupported type refusal, and no provider identifiers in receipts or logs.
- Confirm rollback: unset Drive public inputs to return to optional unavailable state, and confirm pasted-text import still works.
- Confirm production review status separately before any public authorization claim.

What is NOT done: live Drive calls, live consent, production review, deployed status, CI execution, demo video, submission, and any external account change. This record is source-only plus fake provider tests. Do not claim tests pass, live Drive intake, production access, or deployed status from this source change.
