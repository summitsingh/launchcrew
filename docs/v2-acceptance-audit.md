# LaunchCrew Item A acceptance audit

Status: follow-up audit, not a completion claim, refreshed Oct 28, 2026 on
main only. This file lives on main. It does not replace README.md or
docs/verification.md. No separate worktree and no separate worker branch
remain in the current status; worktree and branch names below are dated
history only. V2 Memory, Replay, and Campaign Week are integrated on this
main line and covered by the current passes (see docs/verification.md).

## Audit method

Dated history: actual code was read in a v2 worktree at
branch feature/v2-memory-replay-campaign, head 3d878c4:
backend/app.py, backend/adapter.py, backend/tests/test_v2.py,
launchcrew/run.py, launchcrew/facts.py, launchcrew/receipts.py,
web/src/components/v2-views.tsx, web/src/lib/v2.ts, and
backend/migrations/versions/002_v2_memory_campaign.py. That work is now
merged to main; the method below is retained as the record of what was
checked.

## Verdicts before this follow-up

### 1. Memory consumption: ABSENT

Evidence: backend/app.py create_run called adapter.execute with only
run_id, idea, profile, and seed flag. No memory_ids parameter, no read of
memory_items, and backend/adapter.py passed only the static
facts/demo_facts.json to launchcrew/run.py. Memory routes in app.py
(GET, POST, PUT, DELETE, POST /api/memory/from-run) were CRUD plus
explicit learning from an approved run, one way only. No code selected
memory_items for a run, and no run receipt recorded a memory selection.
Editing or deleting a memory item therefore could not change a later
run. The Item A demo proved CRUD and learn-from-run, not consumption.

### 2. Checker profile and Replay difference: ABSENT

Evidence: RunInput in backend/app.py had only idea, agent_name, and
seed_unverified_claim. No checker profile, rule set, or strictness
parameter existed in app.py, adapter.py, or launchcrew/run.py. Checker
verdicts came only from launchcrew/run.py check_pack against the facts
file, plus the seeded unverified claim. Replay in app.py diff_receipts
showed draft changes, blocked counts, blocked claims, approval state,
and receipt keys, but no checker profile field existed to display.
The Item A demo, day 1 vs day 2, showed draft_v2_post_changed false,
Checker v1 blocked 1 vs 1, Checker v2 blocked 0 vs 0, and
approval_state_changed true. That is an approval-state diff, not a
Checker personality diff.

### 3. Campaign Week day-specific briefs: ABSENT

Evidence: backend/app.py create_campaign looped day 1 to 7 and called
adapter.execute with the same idea, profile, and seed flag for every
day, with no day brief, angle, or day-specific claim. CampaignDay had
only day, run_id, approval_state, status, checker_v2_blocked_count,
and idea. Per-day approval and export gates were present and correct:
approve delegates to the single-run approval gate, export delegates to
the single-run export gate, pending export returns 422, and a blocked
final check refuses approval. The day packs were therefore seven
duplicate packs with independent gates, not seven useful day-specific
briefs.

## What this follow-up implemented

All changes described here are on main, deterministic, demo data only,
no live model calls, no credentials, no auto-post, send, pay, submit,
auto-publish, batch approve, batch export, or scheduling auto-publish.

### Memory consumption

- POST /api/runs and POST /api/campaigns accept memory_ids and
  checker_profile. Unknown memory ids return 404 before any pipeline
  run, so a run cannot silently ignore a bad selection.
- Memory selection is read at run time from memory_items, so an edit
  changes the next run and a deletion removes the effect from the next
  run. Selection is recorded in receipt memory_used as id, kind, and
  title, so a run is reproducible from its receipt.
- Documented consumption contract, in backend/adapter.py
  _memory_effects: brand_fact, profile, and approval_example
  content.claim becomes a run allowlist claim for that run only;
  blocked_rule content.claim, and content.blocked_claims list items,
  become run blocked claims; profile content.expertise becomes the
  Maker profile expertise for that run. Items without those fields are
  recorded in memory_used but do not change the draft, by design, and
  are not claimed as consumed.
- Run allowlist claims are added to the facts allowlist for that run
  only, in launchcrew/run.py run_pipeline, with facts file on disk
  untouched. Base v1 runs with no memory_ids behave exactly as before.

### Checker profiles

- checker_profile standard is the previous behavior. Checker profile
  strict adds a deterministic block for superlative or hype words in
  draft claims and draft sentences, in launchcrew/run.py check_pack.
  Strict never verifies an unverified claim, and deterministic claim
  safety is enforced in both profiles: a seeded unverified claim is
  blocked in v1 in both profiles, and the final draft excludes blocked
  and strict-hype claims, so checker_v2 blocked count stays 0 and the
  run can still be approved and exported.
- Receipt records checker_profile, memory_claims, and blocked_claims.
  Replay diff now includes checker_profile_a, checker_profile_b,
  checker_profile_changed, memory_ids_a, and memory_ids_b, and the
  review desk DiffResult shows a Checker profile changes section.
  The review desk Idea form and Campaign form now offer a Checker
  profile selector, and the Idea form accepts comma-separated memory
  ids, so a browser user can create the two profile runs without API
  calls alone.

### Campaign Week day-specific briefs

- backend/app.py CAMPAIGN_BRIEFS defines seven day-specific angles,
  briefs, and brief claims, adapted to the demo idea shape: day 1
  Origin story, day 2 Material and craft, day 3 Commuter use, day 4
  Styling, day 5 Care and durability, day 6 Social proof, day 7 Launch
  offer. Each brief claim is a combination of demo facts only, not a
  new unverified product claim, and is added as a run allowlist claim
  for that day only, so each day draft differs in its brief sentence.
- CampaignDay now includes angle, brief, and draft_v2_post. Receipts
  record campaign_day and campaign_brief. Per-day gates are unchanged:
  approve only when pending and final blocked count is 0, export only
  after approval, pending export returns 422, and a blocked day refuses
  approval and export while another day can still approve and export.
  No batch approve, no batch export, no auto-publish.

## Regression checks

New file backend/tests/test_v2_acceptance.py, deterministic fixtures
only, no live model calls:

- Memory brand fact edit changes the next run.
- Memory blocked rule delete removes the block from the next run, and
  a deleted id returns 404 on run creation.
- Memory selection is recorded in the receipt, and profile expertise
  is recorded for that run.
- Checker strict vs standard on the same idea with the same memory
  claim produces a different v1 verdict and a different v2 draft,
  while a seeded unverified claim is blocked in both profiles.
- Replay shows the checker profile difference, blocked count
  difference, and draft change, not just approval state.
- Campaign Week creates seven days with seven distinct briefs,
  angles, and v2 drafts, per-day receipts with campaign_day and
  campaign_brief, pending export refusal, per-day approval and export,
  other days staying pending, and a blocked day refusing approval and
  export while another day approves.
- Web tests were updated for the new CampaignDay fields and the
  DiffResult checker profile section, where applicable.

## Browser verification plan

Run the UI against isolated services on unique ports, never ports
8001 or 3001, never main Podman state, with a disposable database or
schema removed after verification. Example, to be set at verification
time, not claimed here: API 8011, web 3011, Postgres on a unique local
port, disposable schema, no secrets.

Steps and expected states:

1. Memory edit: in Memory view, create a brand_fact item with a claim,
   create a run with that memory id, confirm the draft contains the
   claim, edit the claim in Memory view, create another run with the
   same memory id, confirm the draft contains the new claim and not
   the old claim. Capture the Memory list, edit form, and run draft.
2. Memory delete: delete a blocked_rule item, create a run without it,
   confirm the previously blocked claim is no longer blocked in v1.
   Capture the delete confirmation and the run Checker panel.
3. Replay personality differences: create a standard run and a strict
   run with the same memory claim, open Replay, pick the two runs,
   confirm the Checker profile changes section shows standard vs
   strict, changed true, blocked count difference, and draft change.
   Capture the Replay comparison.
4. Seven campaign days: create a Campaign Week, confirm seven day
   cards, each with a different angle, brief, and draft, confirm day 1
   approves and exports, other days stay pending, and capture all
   seven day cards.
5. Pending and blocked export refusal: on a pending day, attempt
   export and confirm refusal, approve and export that day, then on a
   blocked day, confirm approval and export both refuse, while another
   day still approves. Capture the refusal states.

If a browser run cannot be done without interfering with main Podman
state or without a full stack, record that as a limitation, provide
the Playwright test plan above and the backend test evidence instead,
and do not claim browser evidence that was not captured.

## Contract and integration notes

- Contract change history: backend/openapi.json
  and web/src/lib/schema.d.ts were regenerated with the repository
  generators after the app.py changes. The generated files on main are
  clean with no diff under the current passes.
- Starlette history: a Starlette repair once generated contracts in
  its separate worktree, from main 4bb295d, while the v2 branch was
  based on 966de60. Both lines touched the same generated files
  from different bases. That conflict is resolved on main; no separate
  worktree remains, and no rebase handling is left open.
- Docs history: Item A once changed README.md and
  docs/verification.md in its commits while a separate docs
  reconciliation worker owned those files in its own worktree, based
  on main 4bb295d. Reconciliation happened on main; no separate worker
  remains.
- V1 preservation: v1 runs with no memory_ids and checker_profile
  standard use the previous pipeline path, except for the
  backward-compatible pipeline parameters and the receipt fields
  memory_used, checker_profile, memory_claims, and blocked_claims,
  which are recorded for every run. No v1 approval, export, or
  deterministic claim safety rule was weakened.

## Limitations

- Browser evidence: see the plan above. Do not treat backend and
  Vitest evidence as browser evidence.
- Playwright smoke for the v2 UI was an open gap in Item A, stack
  down, API 8001 down, web 3001 down. This follow-up does not claim
  that gap is closed unless a Playwright run with isolated ports is
  reported separately, with ports, database, and result files.
- Memory consumption is limited to the documented contract above.
  Arbitrary memory JSON without a claim, blocked claim, or expertise
  field is recorded but does not change a draft, by design.
- Checker strict is a deterministic hype and superlative rule, not a
  model judgment, and it is not a claim that a strict run is better
  for every product. It proves a profile difference, not a quality
  ranking.
- Campaign brief claims are combinations of demo facts only. They
  prove day-specific drafts, not that the briefs are optimal marketing
  copy for a real product.
