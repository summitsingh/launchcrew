# Voice edit measurement protocol (bounded)

This protocol compares human edit effort with and without a voice
profile. It is bounded, synthetic-only, and truthful. No results are
claimed here. All result cells are explicitly unmeasured until
controlled runs are recorded.

No owner-approved past posts exist in this repo and none are claimed.
Public Summit Leather site and social presence informed tone direction
only, not confirmed product facts and not post ownership. No source
excerpts, photos, or private identifiers are used.

## Scope bounds

- Same idea text for both arms.
- Same confirmed product facts and allowlist for both arms.
- Same Scout, Maker, and Checker bindings for both arms.
- Same Checker profile and policies for both arms.
- Same reviewer, same revision UI, same export gate.
- One synthetic voice profile for the with-voice arm only.
- At most 5 paired runs per comparison batch.
- Stop on any Checker failure, stale voice flag, or binding mismatch.

Out of scope: model quality claims, brand lift, conversion, posting,
publishing, delivery, durability, shipping, or catalog truth.

## Arms

- Arm A (without voice): `memory_ids` carries no `voice_profile`.
- Arm B (with voice): `memory_ids` carries exactly one synthetic
  `voice_profile` with 3 to 5 synthetic examples and an explicit
  banned term list.

Both arms use the same factual allowlist path. Voice samples never
become facts. Banned terms only add Checker blocks with concrete
reasons.

## Steps

1. Confirm product facts once and reuse the same snapshot for both arms.
2. Run Arm A without voice. Record run id, receipt voice null, v1 and
   v2 blocked counts, and v2 post and email text.
3. Run Arm B with the synthetic voice. Record run id, receipt voice
   id, title, version, digest, counts, v1 and v2 blocked counts, and
   v2 post and email text.
4. Revise each arm once in the human revision editor. Save only text
   that passes recheck. Record revision number and final check.
5. Approve each arm individually after its own clean check. Export is
   optional and uses the same server export artifact path.
6. Measure edits from v2 Maker text to saved human text for each arm
   using the metrics below.

## Metrics

Measure text edits only. Do not infer quality or preference.

- Post edit distance: character-level distance from v2 post to human post.
- Email edit distance: character-level distance from v2 email to human email.
- Sentences changed: count of v2 sentences absent from human text.
- Banned term hits: count of voice blocks in v1 and in revision recheck.
- Revision saves: count of successful human saves per arm.
- Reviewer notes: free text about phrasing only, no factual claims.

## Results table (unmeasured placeholders)

| Batch | Arm A run | Arm B run | Post distance | Email distance | Sentences changed | Voice blocks | Saves |
|-------|-----------|-----------|---------------|----------------|-------------------|--------------|-------|
| 1     | Unmeasured | Unmeasured | Unmeasured | Unmeasured | Unmeasured | Unmeasured | Unmeasured |
| 2     | Unmeasured | Unmeasured | Unmeasured | Unmeasured | Unmeasured | Unmeasured | Unmeasured |
| 3     | Unmeasured | Unmeasured | Unmeasured | Unmeasured | Unmeasured | Unmeasured | Unmeasured |
| 4     | Unmeasured | Unmeasured | Unmeasured | Unmeasured | Unmeasured | Unmeasured | Unmeasured |
| 5     | Unmeasured | Unmeasured | Unmeasured | Unmeasured | Unmeasured | Unmeasured | Unmeasured |

Summary cells below stay unmeasured until a full batch is recorded.

- Median post distance without voice: Unmeasured
- Median post distance with voice: Unmeasured
- Median email distance without voice: Unmeasured
- Median email distance with voice: Unmeasured
- Median sentences changed without voice: Unmeasured
- Median sentences changed with voice: Unmeasured
- Total voice blocks in Arm B v1: Unmeasured
- Total voice blocks in Arm B revisions: Unmeasured

## Recording rules

- Record run ids, voice id, title, version, and digest for every Arm B run.
- Record `voice_changed` in Replay when comparing paired runs.
- Record stale flags. A stale run is not exportable and needs a new
  human revision check before approval.
- Keep voice samples synthetic. Never paste real posts, names,
  handles, photos, or identifiers into Memory or notes.
- Do not claim owner approval, past performance, or post ownership
  from this protocol.

## Acceptance for a measured batch

- Both arms completed with clean final checks.
- Approval bindings verified for the approved revisions.
- Receipt JSON preserved for each run.
- Voice receipt fields present on Arm B and null on Arm A.
- No cross-arm fact changes and no binding mismatches.

Until those artifacts exist, this file correctly reports Unmeasured.
