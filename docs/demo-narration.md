# LaunchCrew demo narration, 2m50 target, 3 minute hard limit

Status: SOURCE ONLY. No video has been recorded from this narration. No site,
model, or SAM claim is verified by this file. Verification happens only when
root runs `web/scripts/record-demo.mjs` after terminal checks plus live proof,
then checks duration, sound, frame privacy, and receipt claims. Keep this file
in sync with the `SEGMENTS` array in that script. Every segment id below must
appear here, and the say text must match exactly, so offline audio timing stays
true to the recorded UI. Checks UNRUN here by design.

Rules for every line:

- Fictional demo data only: vegan leather wallet, $49, Austin commuters,
  Instagram. No real product, customer, personal, or credential data.
- New wallet flow is keyless and deterministic. Proven before any mutation by
  health auth disabled_demo, auth status enabled false, and model capabilities
  with no configured text models, then rechecked through capture with each new
  run and campaign receipt showing zero model calls and deterministic fallback.
  Do not claim any new run used models. A separate stored Spark proof, if
  present at runtime, gets its own explicit 8s silent EDL slot apart from the
  wallet flow with its own stored usage numbers.
- Scout facts are demo or source provided, never web research. Risks are demo
  hypotheses for review, never approved facts.
- The unsupported claim seed is shown through the explicit UI checkbox and is
  labelled seeded demo in narration and captions.
- Memory before and after is a prepared comparison from two actual UI runs.
  Both screenshots are actual captures from the same session, labelled on card.
  Save waits the true UI close plus a read only persisted readback, then
  asserts exact blocked claims, final draft differences, and no supersede
  before receipt derived labels are built. Fail honestly on mismatch.
- Campaign week shows seven distinct day packs with per day approval only.
  Each day card is scrolled into the viewport and asserted readable inside the
  actual shot hold. DOM count alone is never proof.
- Human approval and export use the actual download plus the stored timeline.
  Submission stays not attempted. The demo actor is labelled as demo.
- The SAM shot, if included, is a separate private jacket photo test. The photo
  is withheld. The wallet demo has not had a SAM photo check. Checked alone
  never means segmented. Stored in a separate private host DB, not the public
  AWS DB. No photo, picker, canvas, image, provider ID, digest, filename,
  geometry, or crop data appears in the public video.
- Close uses a labelled closing card with the public repo and the recorded
  HTTPS site address on screen in the viewport. No verified word is printed in
  source; the runtime HTTPS health gate is recorded in the manifest and root
  verifies proof.
- Captions carry the same honesty labels as narration. Setup, navigation, and
  run waits between evidence holds are trimmed and logged in edit. Invented
  transports, stage pauses, speedups, reordered evidence, and fake progress are
  not allowed.

Total target: 170 seconds (2m50). Hard limit: 180 seconds. EDL slots are
12, 20, 26, 24, 18, 15, 13, 17, 18, 7, plus optional 8s Spark. The harness
pre-generates narration audio, probes each clip with ffprobe, requires each
clip fits its assigned slot, captures actual source in and out per evidence
hold, then derives video cuts, audio placement with silence padding,
contiguous captions, and manifest from ONE edit decision list and verifies
the final MP4.

## Segment list

### s1-brief, 0:00-0:12, Wallet brief

On screen: Launch brief view, fictional brief text, approved demo facts aside.
Hold starts on the asserted brief in the viewport.

Say:

> LaunchCrew turns one demo idea into a pack you approve before export. Fictional wallet brief: forty nine dollars, Austin commuters, Instagram. Keyless deterministic flow.

Caption: Fictional wallet brief. Keyless deterministic flow.

### s2-guard, 0:12-0:32, Custom PriceGuard checker

On screen: Agent builder, PriceGuard profile, personality, expertise, decision
rule Block price claims, veto scope price_claims, dry run preview showing
Enforced policies: price_claims, held readable in the viewport.

Say:

> This is a custom checker named PriceGuard. Its veto scope is price claims, exact match, a supported policy. Its rule is Block price claims. Free text rules outside the supported list stay advisory only and are never enforced.

Caption: PriceGuard: supported price_claims policy. Other text stays advisory.

### s3-scout, 0:32-0:58, Scout facts and sources

On screen: Run review, Scout facts and sources section, 5 facts with Verified
marks, 3 risks, demo source lines, No external research was run, deterministic
fallback note. Facts and honesty copy scrolled readable in the shot hold.

Say:

> Scout sourced five demo facts with sources, plus three demo risks. These come from the local demo facts file and the demo brand brief. No external research ran, and no live product check is claimed.

Caption: 5 demo facts, 3 demo risks. Demo sources. No external research.

### s4-seed, 0:58-1:22, Seeded block and revision

On screen: Seed checkbox checked and labelled seeded demo, best in Texas shown
blocked with a reason, revised draft without it, PriceGuard removal of the $49
claim, final blocked count 0. Block evidence held readable.

Say:

> With the seeded demo box checked, the unsupported claim best in Texas is blocked with a reason, then left out of the revised draft. PriceGuard also removes the forty nine dollar claim under its price policy. The final check shows zero blocked.

Caption: Seeded demo: unsupported claim blocked and revised out.

### s5-replay, 1:22-1:40, Replay

On screen: Replay view with two actual run IDs from this session, Compare
result, checker binding difference, stage bindings changed true, held readable.

Say:

> Replay compares two actual runs from this session by their stored run IDs. Same brief, different checker binding. The verdict difference comes from the recorded receipts, not from editing.

Caption: Replay of two actual run IDs from this session.

### s6-memory, 1:40-1:55, Memory edit

On screen: Prepared comparison card from two actual UI runs, before screenshot
and after screenshot side by side, PREPARED COMPARISON badge, run prefixes,
receipt derived block labels.

Say:

> This is a prepared comparison from two actual runs made through the UI. After editing the memory rule, the next run blocks a different real claim. Nothing here is typed as a fake result.

Caption: Prepared comparison. Two actual UI runs, before and after edit.

### s7-campaign, 1:55-2:08, Campaign week

On screen: Campaign view, seven distinct Day cards scrolled readable one by one
in the shot hold, per day pending state, individual approve controls, no batch
approval. Ends on Day 7 asserted evidence.

Say:

> Campaign week holds seven distinct day packs. Each day stays pending until you approve it on its own. No batch approval, no auto publish.

Caption: Seven distinct days. Each approved on its own.

### s8-sam, 2:08-2:25, Separate photo result (optional)

On screen: Pixel free evidence card only, SEPARATE PRIVATE TEST badge, jacket
test label, separate private host DB note, method, scope, photo state, nonzero
segmentations, checked time, revision. No photo, no picker, no canvas, no image,
no synthetic test image beside the card.

Include this segment only when root supplies a validated sanitized proof file
at runtime and correlation is actually confirmed. Otherwise skip it and report
pending honestly. Never pretend a private SAM run exists in the public AWS DB.

Say:

> This is the stored result from a separate authorized private jacket photo test. The photo is withheld. This wallet demo has not had a SAM photo check. Checked alone never means segmented.

Caption: Separate private jacket test. Photo withheld. Wallet not SAM checked.

### s9-approve, 2:25-2:43, Human approve and export

On screen: Approval queue, pending approval tap to approved for export, Export
pack actual download, receipt view with Recorded events timeline, demo actor,
Not attempted submission line. Timeline scrolled readable in the hold.

Say:

> Nothing exports without your tap. Approval and export are recorded with the demo actor and time, and the receipt timeline keeps the history. Submission shows not attempted.

Caption: Human approve, export download, stored timeline. Not attempted.

### s10-close, 2:43-2:50, Close

On screen: CLOSING CARD with public repo https://github.com/summitsingh/launchcrew
and the recorded HTTPS site address, both readable in the viewport for the
7s slot. No localhost shown as public.

Say:

> LaunchCrew: one idea, three agents, one pack you approve. Demo only. Repo and site address on screen.

Caption: Demo only. Closing card with repo and site address.

## Voice and captions

- Voice: existing macOS say offline voice, system default unless `--voice`
  names an installed voice from `say -v` output. No voice download is used.
- Each say clip is measured with ffprobe and must fit its EDL slot. If over,
  shorten the `SEGMENTS` say string and this doc together.
- Captions: `launchcrew-demo.srt` is generated from EDL slot times in take
  order, contiguous with no invented gaps. Each block carries its slot, title,
  and honesty label above. Audio is padded with silence to the same slots so
  video, audio, and captions stay aligned.
- If the SAM segment is skipped, its say text and caption are omitted from
  audio and captions, later slots shift earlier, and the manifest records the
  skip as pending honestly. Spark, if present, gets an explicit silent 8s slot
  apart from the wallet flow.
- `edl.json` plus `shot-manifest.json` record source in and out per hold, slot
  starts, trimmed setup and wait spans, and full private run IDs.

End of narration. No recording, upload, publication, or submission is claimed.
