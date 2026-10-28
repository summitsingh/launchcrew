# LaunchCrew demo recording plan, 3 minutes, local UI only until deployment is verified live

Status: PLAN ONLY, refreshed Oct 28, 2026. No video has been recorded. No video claim is made. No recording, upload, submission, deployment, credential, or paid call was made to prepare this plan. Recording is gated on a live SAM pass or a user-approved scope change, plus exact CI 40695455958 reaching terminal, per the current gates below. Exact CI 40695455958 for published main `a6cd81f` is TERMINAL SUCCESS, confirmed from the saved run log `../verification-ci-a6cd81f-success.log` (24 browser passed in 2.3m at line 1130; bootstrap 6th image build tag at lines 1534-1536; container path create, receipt, seeded block, pending export refusal 422, approve, export 200, queue PASS with no model calls at lines 1563-1578; job ends Complete): https://github.com/summitsingh/launchcrew/actions/runs/40695455958. No CI result is claimed for any later docs-only commit before it is pushed and its own run completes. When recording is authorized, record local UI only, unless deployment is verified live at recording time, with WEB 200, API 200, and WEB API 200 at launchcrew.summitsingh.com, with HTTPS verified. The live URL target is NOT live and NOT publicly verified at the time of this plan. The separate approval record, the final video, and the submission all persist as separate gates. Final video version needs user approval before submission.

Target length: 3 minutes, target 2m50s, hard limit 3 minutes, per Participant Guide, demo video showing only work built during the hackathon, Oct 26 to Nov 4, 2026.

Rules for the recording, all must hold:
- New work only, no prior codebase code shown as new work, no ProofPilot work shown as LaunchCrew work.
- Demo data only, no real personal data, no real product, no real customer data, no phone, no address, no email on screen, no key, no prompt, no completion, no secret on screen.
- LaunchCrew scope only: one solo-founder idea in, Scout facts, Maker drafts, Checker verdict, human approval, export receipt. No post, send, pay, submit, publish, auto-apply, screening, ranking, scoring, shortlisting, batch approval, or automatic approval shown as happening or offered. Privacy on screen: demo data only, no real personal data, no key, no prompt, no completion, no secret.
- No em dashes, no hype claim that is not tied to a demo fact, no claim that a feature is live unless the evidence matrix in docs/submission-draft.md says VERIFIED for that feature.
- No auto-post, send, pay, submit, or auto-publish shown as happening, and no attempted publication shown. Approval and export only, with export shown as a file or receipt, not as a published post.
- No deployment URL shown as live until verified live. If recording local UI, label it on screen as Local demo, not live, and do not show a localhost URL as a public demo URL in the final submission copy.
- No v2 feature shown as live unless integrated verification and browser acceptance prove it at recording time. If v2 is not verified at recording time, record v1 only, and update this plan first.

## Timed script, 2m50s target, 7 sections

Section 1, 0:00 to 0:20, 20 seconds, Idea in.
- On screen: LaunchCrew home, local demo label, idea form, blank.
- Narration, plain, no hype: "LaunchCrew turns one idea into a Launch Pack you approve before anything is published."
- Action: type the demo idea, one sentence plus price plus audience, exactly: Vegan leather wallet, $49, for Austin commuters, launch on Instagram. No other idea, no real product name.
- End frame: idea submitted, run starting, no model call shown on screen.

Section 2, 0:20 to 0:50, 30 seconds, Scout, sourced facts.
- On screen: Scout panel, Skeptical Analyst, 5 facts with sources, 3 risks, unverified items marked.
- Narration: "Scout checks first, with sources, and marks what is not verified."
- Action: scroll the 5 facts, pause on one source line, pause on one risk line, pause on one unverified mark. Do not read a full source list aloud, show it visually.
- End frame: Scout facts complete, no unverified fact presented as verified.

Section 3, 0:50 to 1:20, 30 seconds, Maker, drafts tied to facts.
- On screen: Maker panel, Brand Voice Writer, 1 post draft, 1 email draft, each claim tied to a brand fact.
- Narration: "Maker writes in a plain brand voice, with every claim tied to a fact."
- Action: show the post draft, then the email draft, pause on one claim that matches a Scout fact. Do not show a draft with an unverified claim presented as verified.
- End frame: drafts ready for Checker, not published, not sent.

Section 4, 1:20 to 1:50, 30 seconds, User-created Checker, seeded unsupported claim blocked and revised.
- On screen: Checker panel, Strict Auditor, plus a user-created Checker profile, named by the user in the recording, with its own rules shown.
- Narration: "Checker blocks what is not supported, and a user-created Checker can apply its own rules, without overriding safety."
- Action, in order, all on screen:
  1. Show a seeded unsupported claim, for example a claim not found in the facts file, marked blocked by Checker v1, with reason Claim not found in facts file, or equivalent deterministic reason shown in the UI.
  2. Show the same claim excluded from the final draft, with Checker v2 blocked count 0 for the final pack, so the pack can proceed.
  3. Revise the claim to a supported fact, for example a price, audience, or material fact from Scout, and show the revised draft with that supported claim, and no blocked claim remaining.
- End frame: Checker verdict per item, pass, fix, or block, with the blocked item fixed by revision, not by bypassing Checker, and no model suggestion shown as approving or unblocking a claim.

Section 5, 1:50 to 2:10, 20 seconds, Human approval.
- On screen: approval panel, pending_approval state, then approve tap by the human, with approval receipt.
- Narration: "Nothing moves without a human tap. Approval is recorded, with who approved it, or with demo_placeholder only if auth is disabled, labeled as demo."
- Action: show pending_approval, tap approve, show approved_for_export, show approval receipt with run id, Checker verdict, and approval state. If auth is disabled, show demo_placeholder explicitly, do not present it as a signed-in user. If auth is live, show provider subject, not a password, not a token.
- End frame: approved_for_export, submit_attempted false, no publication attempted.

Section 6, 2:10 to 2:35, 25 seconds, Export receipt, and V2, only if verified at recording time.
- On screen: export tap, export HTTP 200, export receipt, with run id, approval state, and draft, and no published post.
- Narration: "Export gives you a pack to use, it does not publish for you."
- Action: tap export, show export receipt, show that no post, send, or pay action followed. If V2 is verified at recording time, show, in this same 25 seconds, one Memory edit effect, or one Replay standard versus strict difference, or one Campaign Week day card, with a label, and cut any other V2 shot. If V2 is not verified, show export receipt only, and do not show Memory, Replay, or Campaign Week as live.
- End frame: export receipt, no attempted publication, no external site opened.

Section 7, 2:35 to 2:50, 15 seconds, Close, what LaunchCrew is, and what it is not.
- On screen: LaunchCrew title, Indie Developer, Build for Your World, public repo URL, local demo label, or live demo URL only if verified live.
- Narration: "LaunchCrew: one idea, three agents, one pack you approve, then export. Nothing posts, sends, or spends without you."
- Action: hold the close frame for 5 seconds, with repo URL readable, and no other claim on screen.
- End frame: close, total time 2m50s, under the 3 minute limit.

## Timing check, before recording

- Rehearse with a timer, in order, sections 1 to 7, with no section overrunning its slot by more than 5 seconds, and total time under 3 minutes, with a 10 second buffer for transitions.
- If a section overruns, cut narration, not evidence: cut the Scout source list reading, cut the Maker draft reading, keep the blocked claim, the revision, the approval tap, and the export receipt, because those are the proof steps.
- If V2 shots overrun section 6, cut V2 to one shot only, or cut V2 entirely, and record v1 only, with this plan updated first.

## Browser acceptance checklist, must pass before recording, not just backend tests

- V1, rendered, on isolated API and web ports, never main ports, disposable database or schema removed after verification: create agent, edit agent, clone agent, each visible in the UI, with the cloned agent shown as a separate agent, not as an edit of the original.
- V1, rendered: unsupported claim blocked, then revised to a supported fact, with Checker v1 blocked count and final draft visible, and no blocked claim in the final draft.
- V1, rendered: export refused before approval, with the refusal state visible, then approve clean pack, then export succeeds, with export receipt visible, and submit_attempted false, and no attempted publication.
- V1, rendered: failed or blocked run cannot be approved or exported, with both refusal states visible, while a clean run can still approve and export.
- V1, rendered: receipt shows correct state, run id, Checker verdict, approval state, and export state, matching the API receipt, with no key, prompt, completion, phone, address, or email on screen.
- V2, rendered, only if integrated verification proves it: Memory edit effect, Memory delete effect, Replay standard versus strict difference, 7 distinct campaign briefs with 7 day cards, per-day pending and blocked approval and export guards, with other days still able to approve and export.
- If any checklist item fails in a rendered run, recording stops, the failure is reported with exact command and output, corrected, and rechecked, and recording does not proceed on backend tests alone.

## Recording setup, local only

- Record local UI only, with a clean browser profile, no bookmarks, no personal tabs, no notifications, no key in the browser, no terminal with a key on screen, no .env file open, no repo file with a secret open.
- Resolution: 1920 by 1080, or the highest stable resolution that keeps UI text readable, with mouse movement slow and deliberate, with each tap visible for at least 2 seconds before the next action.
- Audio: clear narration, no music that obscures narration, no background noise, no personal information spoken.
- File: local file only, not uploaded, not published, not submitted, until Summit approves the final video version in full, with a separate tap, after watching it.
- After recording, check the video frame by frame for: no key, no prompt, no completion, no phone, no address, no email, no secret, no em dash in on-screen text, no live URL claimed as live unless verified, no v2 feature shown as live unless verified, total time under 3 minutes, and all proof steps visible: blocked claim, revision, approval tap, export receipt, no attempted publication.

## Gates, before recording tap

- TODO: live SAM pass, or a user-approved scope change recorded here with the SAM shots cut, with this plan updated first. SAM is held at the time of this plan, so recording stays gated on that decision. Bounded SAM scope already authorized, no reapproval requested. Preflight still required before any paid call: actual balance for the exact approved asset, billed unit, enforceable $1 bound with hard stop after 2 calls. No live SAM calls were made.
- Current test evidence on published main `a6cd81f`: host `5a186a5 --all` TERMINAL exit 0 (271 backend pytest in 7.03s, 234 core in 61.751s, 71 Vitest, 30 contracts plus typecheck plus build, 24 browser in 1.9min), CFN plus test-only 119 PASS in 63.20s with cfn-lint 1.58.0 ZERO diagnostics, PG 55507 binding harness PASS. Exact CI 40695455958 TERMINAL SUCCESS per the saved run log in the status line above. Older `9809b4a` counts (172 backend pytest, 109 core, 63 Vitest, 22 browser) and f70d107 closeout counts stay history.
- Keyless browser acceptance, historical: from candidate f70d107 closeout plus audit: Playwright 1 passed in 9.1s on isolated ports (API 8021, web 3021), all checklist flows rendered across V1 and V2, 8 screenshots plus 2 export receipts plus summary.json, no attempted publication. Audit confirmed no route interception and all 11 artifacts present with matching contents. Current line counts as above.
- TODO: fresh browser pass on the current main line at recording time before the tap to record.
- TODO: user approval to record, separate from all prior taps, with the timed script above approved, and with the decision on whether V2 is included, based on integrated verification at that time.
- TODO: user approval of the final video version, separate from approval to record, before submission.

End of plan. No video has been recorded, no video claim is made, no upload, submission, deployment, credential, or paid call was made to prepare this plan.
