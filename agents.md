# Agent working notes

## Test policy (owner directive, Nov 2026, full stop Nov 3)

All test suites are off until the owner re-enables them. Do not run
pytest, unittest, vitest, typecheck, build, or the text scan on any
slice. Velocity only.

- GitHub CI: the Verify workflow stays disabled. Publish ECR images
  (manual) stays enabled, it is the publish route, not test CI.
  Dependabot and Dependency Graph are not test runners, leave them.
- No suite gates any claim while this stop is in effect. The owner
  accepts the risk of shipping without suite evidence.
- To re-enable: owner says so, then restore the per-slice targeted
  gates plus the full suite at milestones.
- Nothing here edits a test, the Checker, or the approval binding.
