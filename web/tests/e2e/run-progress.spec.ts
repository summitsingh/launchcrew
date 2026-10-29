import { test, expect } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';

// Incremental stage receipts, rendered in Chromium through the Next.js desk
// on isolated ports with the real API and Postgres. No route interception:
// every stage below is a real stored row the pipeline wrote. The run starts
// keyless, so synthesis stays on the deterministic fallback.
const local = resolve('../.local/run-progress');
mkdirSync(local, { recursive: true });
const wallet = 'Vegan leather wallet, $49, for Austin commuters, launch on Instagram';

test('async run shows live stage receipts before the final review', async ({ page, request }) => {
  test.setTimeout(180_000);
  await page.setViewportSize({ width: 1024, height: 1000 });
  await page.goto('/');
  await page.getByRole('button', { name: 'Launch brief', exact: false }).click();
  await page.getByLabel('Maker agent', { exact: true }).selectOption('Maker');
  await page.getByRole('button', { name: 'Create draft', exact: true }).click();

  // A fast real keyless run can complete before Playwright first samples
  // the UI, so one atomic DOM read accepts whichever genuine state is
  // present: the pending view (heading plus its no-prediction
  // disclaimer) or the already-final review. Both paths then prove the
  // same final UI, stored ordered stage history with receipts, and
  // approval gate below; true intermediate persistence stays covered by
  // the controlled backend and stage barrier tests.
  const firstSeen = await page.waitForFunction(
    () => {
      const scope = document.querySelector('section[aria-label="Run progress"]');
      if (
        scope !== null &&
        scope.querySelector('h2')?.textContent === 'Pack in progress.' &&
        (scope.textContent ?? '').includes('Nothing here is predicted')
      ) {
        return 'pending';
      }
      if (
        Array.from(document.querySelectorAll('h2'), (heading) => heading.textContent).includes(
          'Unsupported claims stopped.',
        )
      ) {
        return 'final';
      }
      return null;
    },
    null,
    { polling: 100, timeout: 60_000 },
  );
  if ((await firstSeen.jsonValue()) === 'pending') {
    await page.screenshot({ path: `${local}/01-pending.png`, fullPage: true });
  } else {
    await page.screenshot({ path: `${local}/01-already-final.png`, fullPage: true });
  }

  // The final review unlocks only with the completed receipt.
  await expect(page.getByRole('heading', { name: 'Unsupported claims stopped.' })).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText('The revised draft uses only approved facts. Final blocked count: 0.')).toBeVisible();
  const runId = await page.locator('.section-row .run-id').innerText();
  await page.screenshot({ path: `${local}/02-review.png`, fullPage: true });

  // The stored steps agree with the final receipt: completed order,
  // started history, sequence order, timezone-aware observed times with
  // nondecreasing instants (ties allowed), profiles, and evidence.
  // The module contract stores started and completed rows, so the
  // assertion filters completed rows for the finished order instead of
  // pretending the history is a finished-only list. Millisecond
  // uniqueness is never required: two legitimate quick events may share
  // one millisecond, and Date truncates microseconds to milliseconds, so
  // ties are ordered by seq, never by forcing the clock apart.
  const steps = await request.get(`/api/runs/${runId}/steps`);
  expect(steps.status()).toBe(200);
  const body = await steps.json();
  expect(body.run_id).toBe(runId);
  type Row = { seq: number; stage: string; state: string; observed_at: string; profile: string; evidence: Record<string, unknown> };
  const rows = body.steps as Row[];
  expect(rows.filter(row => row.state === 'completed').map(row => row.stage)).toEqual([
    'accepted',
    'deterministic_checks',
    'scout',
    'maker_draft_v1',
    'checker_v1',
    'maker_draft_v2',
    'checker_v2',
    'receipt',
  ]);
  for (const stage of ['deterministic_checks', 'scout', 'maker_draft_v1', 'checker_v1', 'maker_draft_v2', 'checker_v2', 'receipt']) {
    expect(rows.some(row => row.stage === stage && row.state === 'started')).toBe(true);
  }
  const seqs = rows.map(row => row.seq);
  expect([...seqs].sort((a, b) => a - b)).toEqual(seqs);
  expect(new Set(seqs).size).toBe(seqs.length);
  for (const row of rows) {
    expect(row.observed_at).toBeTruthy();
    expect(row.profile).toBeTruthy();
    // Canonical UTC contract: the API serializes timestamptz as UTC ISO
    // with its zone retained, so every observed time stays comparable.
    expect(row.observed_at).toMatch(/[+-]\d{2}:\d{2}|Z$/);
    expect(Number.isNaN(new Date(row.observed_at).getTime())).toBe(false);
  }
  const instants = rows.map(row => new Date(row.observed_at).getTime());
  for (let i = 1; i < instants.length; i += 1) {
    expect(instants[i]).toBeGreaterThanOrEqual(instants[i - 1]);
  }
  const stored = await request.get(`/api/runs/${runId}/receipt`);
  const receipt = await stored.json();
  expect(receipt.status).toBe('completed');
  const logged = new Map(receipt.audit.event_log.map((entry: { step: string }) => [entry.step, entry]));
  // Full-precision instant comparison: Date keeps milliseconds only,
  // so the shared completion proof compares the canonical second plus
  // the full fractional reading instead of truncating to milliseconds.
  const instantParts = (value: string) => {
    const normalized = value.endsWith('Z') ? value.slice(0, -1) + '+00:00' : value;
    const match = normalized.match(/^(.*)T(\d{2}:\d{2}:\d{2})(?:\.(\d+))?([+-]\d{2}:\d{2})$/);
    if (!match) throw new Error(`Not a timezone-aware instant: ${value}`);
    return { day: match[1], clock: match[2], fraction: (match[3] ?? '').padEnd(6, '0'), zone: match[4] };
  };
  for (const row of rows) {
    if (row.state !== 'completed' || row.stage === 'accepted' || row.stage === 'receipt') continue;
    const entry = logged.get(row.stage) as { timestamp: string; profile: string };
    // One shared clock reading at full precision: the stored step row
    // and the receipt audit entry describe the same observed completion.
    // Date.getTime stays millisecond order only (ties allowed above).
    const want = instantParts(row.observed_at);
    const got = instantParts(entry.timestamp);
    expect(got).toEqual(want);
    expect(new Date(entry.timestamp).getTime()).toBe(new Date(row.observed_at).getTime());
    expect(entry.profile).toBe(row.profile);
  }
  expect(rows.at(-1)?.evidence.stored).toBe(true);

  // Approval still needs a fresh human decision on the completed pack.
  await page.getByRole('button', { name: 'Go to approval queue', exact: true }).click();
  const card = page.locator(`[data-run-id="${runId}"]`);
  await expect(card.getByText('Pending approval', { exact: true })).toBeVisible();
  await card.getByRole('button', { name: 'Approve for export', exact: true }).click();
  await expect(card.getByText('Approved for export', { exact: true })).toBeVisible();
});
