# Agent working notes

## Test policy (owner directive, Nov 2026)

Do not run the slow suites on every slice. They block development
velocity and run at the end instead.

- Skip `python -m unittest discover -s tests` per slice. It takes
  about 25 minutes. Run it only at major milestones and before any
  final done claim.
- Skip any other suite that takes more than a few minutes per slice
  for the same reason.
- Per-slice gate instead: the affected pytest files, the related pure
  unit tests, `pnpm --dir web test`, `pnpm --dir web typecheck`,
  `pnpm --dir web build`, and `python3 scripts/check-repo-text.py`.
- Full local suite (pytest, unittest, vitest, typecheck, build, text
  scan) still gates release claims. Nothing here weakens a test, the
  Checker, or the approval binding.
