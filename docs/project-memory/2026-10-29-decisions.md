# Project memory: current decisions and boundaries

Date: 2026-10-29
Scope: LaunchCrew public record only. Decisions, not completion claims.

## Scope and authorship

- Full six-slice audit and proposal scope stays intact. No slice is dropped to simplify a feature.
- All product coding, tests, and docs are authored by Muse. Codex only orchestrates, verifies, and handles Git and cloud steps.
- Work lands on isolated feature branches. Merges to main are independently reviewed.

## Cloud and model boundary

- Only LaunchCrew-owned resources are in scope, within the approved account. Unrelated shared or production resources must not be modified.
- See docs/aws-approval-pack.md for the current public approval pack and LaunchCrew-only boundary.
- Public model paths stay keyless until a verified global spend guard exists.
- Private bounded model or photo proofs do not imply public photo or video permission.

## Auth, recording, and schedule

- Clerk or open-source OAuth fallback is approved for development use only. Production needs exact provider app ownership, redirect, and security validation, plus Central planning. The Nov 3 Central planning target carries schedule risk; development credentials do not imply production readiness.
- Recording follows feature proof. Final publication and submission stay separately reviewed.
- Nov 3 is a planning target. Nov 4 is the deadline.
