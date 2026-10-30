# Contributor Attribution: Review Draft

Status: review draft only. Not independently assessed. Do not treat as final submission or as a published authorship claim.

Scope: this file is the sole owned artifact for this task. It covers `docs/contributor-attribution.md` only. No change to `README` or any other file is made or claimed here.

Method: prepared from public tracked Git history only. No private journals, orchestration state, credentials, private environment files, personal photos, external private documents, or old-machine state were used. Commit author and committer identity fields were inspected only to avoid misattribution and are not reproduced here. This draft does not publish personal names, emails, or private identifiers.

## Event window

Per the organizer official event page at https://events.cerebralvalley.ai/e/meta-ai-developer-hackathon, the hackathon begins Oct 26, 2026 and submissions are due Nov 4 at 9 PM ET. This corrects the prior draft statement that the event window was unknown.

## What repository history establishes

Tracked history observed in this worktree:

- Head commit: `b199d093efd04adc32dbeee29057a30dbd772b49` with subject `Enforce specificity lint through review and export gates`.
- Early tracked history includes `37a358a75302e457b908d775dc51b18f09230f13` dated `2026-10-27` with subject about LaunchCrew v1 idea-to-launch work, followed by `0c9855548453883f3c758ae52f71c0ac5b4616fe` and `e4355702633b22cc9308abff24853244b2c03db7` on the same date.
- Total tracked commits on current branch at time of review: `325`.
- Observed date range of commit metadata: `2026-10-27` through `2026-10-30`.
- Tracked top level areas include `backend/`, `web/`, `tests/`, `docs/`, `launchcrew/`, `scripts/`, `deploy/`, `containers/`, `evaluation/`, `agent_presets/`, `agents/`, `runs/`, `facts/`, and `db/`.
- Representative recent tracked changes, by hash subject and path:
  - `b199d093efd04adc32dbeee29057a30dbd772b49`: `launchcrew/checker_policies.py`, `launchcrew/human_review.py`, `launchcrew/run.py`, `tests/test_specificity_lint.py`.
  - `8afbf55a2b24c25ddf8eee2ebc7d126a5f0d1407`: `.github/workflows/verify.yml`, `scripts/verify-container-path.py`, `tests/test_container_migration.py`.
  - `32bf240b7fe2a79fc680ca4c628a5f63dbb36efc`: records patch-equivalent branches integrated on main.
  - `14a17f75589057cdf0256bd3eaf4f364386b6051` and `ca6a24d6356aff80aeab82f27b6c3ebdb608a346`: `launchcrew/facts.py`, `tests/test_checker_eval_quality.py`.
  - `901fa0248ac495909bc8ba368e8caf879b828f2d`, `90d50550fda5d172e6722b23843c555816ece237`, `dac04c9ad0012edbd7ff056e0f391170b9bf5edf`, `517be4bef85bc13be158fea40663abb17d1a5183`: `evaluation/README.md`, `evaluation/runner.py`, `evaluation/test_metrics.py`.
  - Drive intake sequence `9738f074d201e2b21d7538d13cc7daa02054c12e`, `93870f9c63d8d0c0885235e8fe6a3fd40897bc09`, `cdfa2299b7a250858a592b9b87f71bc7fa270c47`, `994790e3750e9f6e3786e741aeb3d52510fd56e2`, `00713fe90e7a605b5972685012ea2530b6cae74e`, `9b9f6c0d319f58a104585194494bf3b140871174`: `backend/drive_intake.py`, `backend/tests/test_drive_intake_api.py`, `backend/tests/test_drive_request_shape.py`, `docs/drive-intake-decision.md`, `web/src/components/drive-intake-form.tsx`, `web/src/lib/drive-intake.ts`, `web/tests/drive-intake.test.tsx`.

What this supports: the repository contains sustained tracked work across backend, web, tests, evaluation, and docs during the recorded date range of `2026-10-27` through `2026-10-30`. Those commit timestamps fall within the organizer window of Oct 26, 2026 through Nov 4 at 9 PM ET. Timestamp placement within the window does not prove actual creation date or provenance. It does not by itself prove when ideas originated, which work was newly created during the event, or who performed each item. Git metadata alone cannot prove provenance for pre-existing external assets or for exact tool authorship.

## What cannot be established from this source

- Whether any specific file or feature is wholly new work during the event, pre-existing work, or rework of a pre-existing external asset. Git history shows tracked change order, not asset provenance.
- Exact tool authorship for any commit. Commit metadata records committer fields, but those fields are not reliable evidence of which tool, agent, or person authored the substantive change. This draft therefore makes no per-commit authorship assignment and does not infer authorship from committer strings.
- Completeness of contributions. Untracked work, uncommitted work, work outside this repository, and work in private systems are out of scope for this history-only draft.
- Deployment or submission state. This draft makes no claim of a live deployment and no claim of final submission.

## Current authorship policy note

Current policy assigns product authorship to the personal Muse Code CLI while Codex orchestrates and verifies. That policy statement describes the current operating arrangement. It is not applied retroactively in this draft to specific historical commits, because the tracked history reviewed here does not itself record that division of labor per commit.

## Unresolved items

1. Event window is now cited from the organizer page above. Provenance remains unresolved: commit timestamps within that window do not prove that the corresponding work was newly created during the event rather than imported, adapted, or continued from prior or external work.
2. Pre-existing external assets are not inventoried here. Any asset reused from outside the tracked history needs explicit listing before novelty can be assessed.
3. Per-item tool and human contribution shares are unresolved. This requires independent evidence beyond Git metadata. No names, personal identifiers, or authorship assignments are invented here.
4. Submission and deployment claims remain out of scope until independently assessed by the coordinator. This draft makes no live deployment claim and no final submission claim.

## Independent review steps

1. Confirm head hash and counts with: `git rev-parse HEAD`, `git rev-list --count HEAD`, and `git log --format='%H %ad %s' --date=short -30`.
2. Spot check cited paths with: `git log --name-status --oneline -10` and `git ls-files docs/`.
3. Confirm no personal identifiers were added by inspecting this file only.
4. Coordinator to assess external asset list, contribution shares, and whether any stronger authorship statement is warranted against the cited organizer window. Until then, keep this file marked as a review draft.
