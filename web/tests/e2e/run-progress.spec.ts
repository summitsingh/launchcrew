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
  await page.getByLabel('Maker profile', { exact: true }).selectOption('Maker');
  await page.getByRole('button', { name: 'Create draft', exact: true }).click();

  // The pending view opens immediately, before the pipeline finishes.
  const progress = page.locator('section[aria-label="Run progress"]');
  await expect(progress.getByRole('heading', { name: 'Pack in progress.' })).toBeVisible();
  await expect(progress).toContainText('Nothing here is predicted');
  await page.screenshot({ path: `${local}/01-pending.png`, fullPage: true });

  // The final review unlocks only with the completed receipt.
  await expect(page.getByRole('heading', { name: 'Unsupported claims stopped.' })).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText('The revised draft uses only approved facts. Final blocked count: 0.')).toBeVisible();
  const runId = await page.locator('.section-row .run-id').innerText();
  await page.screenshot({ path: `${local}/02-review.png`, fullPage: true });

  // The stored steps agree with the final receipt: order, profiles, evidence.
  const steps = await request.get(`/api/runs/${runId}/steps`);
  expect(steps.status()).toBe(200);
  const body = await steps.json();
  expect(body.run_id).toBe(runId);
  expect(body.steps.map((row: { stage: string; state: string }) => `${row.stage}:${row.state}`)).toEqual([
    'accepted:completed',
    'deterministic_checks:completed',
    'scout:completed',
    'maker_draft_v1:completed',
    'checker_v1:completed',
    'maker_draft_v2:completed',
    'checker_v2:completed',
    'receipt:completed',
  ]);
  const observed = body.steps.map((row: { observed_at: string }) => row.observed_at);
  expect(new Set(observed).size).toBe(observed.length);
  const receipt = await request.get(`/api/runs/${runId}/receipt`);
  expect((await receipt.json()).status).toBe('completed');
  expect(body.steps.at(-1).evidence.stored).toBe(true);

  // Approval still needs a fresh human decision on the completed pack.
  await page.getByRole('button', { name: 'Go to approval queue', exact: true }).click();
  const card = page.locator(`[data-run-id="${runId}"]`);
  await expect(card.getByText('Pending approval', { exact: true })).toBeVisible();
  await card.getByRole('button', { name: 'Approve for export', exact: true }).click();
  await expect(card.getByText('Approved for export', { exact: true })).toBeVisible();
});
