import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';

// Human review editing through the real desk UI and API, no route mocks.
// A clean run is revised from Run review with allowed facts, which resets
// approval; an unsupported edit is rejected unsaved with per-claim reasons;
// correction, reapproval, and export use the latest human text. A failed run
// is produced through a real unsupported brand_fact memory (actual core
// failure, not a SQL seed) and the desk shows explicit failed status with
// no edit, approve, or export controls.
const wallet = 'Vegan leather wallet, $49, for Austin commuters, launch on Instagram';

test('human revision editing and failed run review', async ({ page, request }) => {
  test.setTimeout(180_000);
  await page.setViewportSize({ width: 1024, height: 1000 });
  const suffix = String(Date.now());
  await page.goto('/');
  await expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);

  // Clean run without the unsupported-claim demo.
  await page.getByLabel('Maker profile', { exact: true }).selectOption('Maker');
  await page.getByLabel('Include the unsupported claim demo').uncheck();
  await page.getByRole('button', { name: 'Create draft', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Ready for your review.' })).toBeVisible();
  const runId = await page.locator('.section-row .run-id').innerText();
  expect(runId.startsWith('run_')).toBe(true);

  // Valid human revision from Run review.
  const validPost = 'Vegan leather wallet. Designed in Texas.';
  const validEmail = 'For Austin commuters. $49.';
  await page.getByLabel('Post text').fill(validPost);
  await page.getByLabel('Email text').fill(validEmail);
  await expect(page.getByText('Unsaved changes. Save runs the deterministic recheck.')).toBeVisible();
  await page.getByRole('button', { name: 'Save human revision', exact: true }).click();
  await expect(page.getByText(/Saved revision 1\. This pack needs fresh approval before export\./)).toBeVisible();
  await expect(page.getByText(/Current revision: 1 \(human revision\)/)).toBeVisible();

  // Unsupported edit is rejected unsaved with per-claim reasons.
  await page.getByLabel('Post text').fill('best in Texas. Vegan leather wallet.');
  await page.getByRole('button', { name: 'Save human revision', exact: true }).click();
  await expect(page.getByText(/Needs revision:/).first()).toBeVisible();
  await expect(page.getByText(/best in Texas/).first()).toBeVisible();
  const reread = (await (await request.get(`/api/runs/${runId}`)).json()) as { revision: number; human_draft: { post: string } };
  expect(reread.revision).toBe(1);
  expect(reread.human_draft.post).toBe(validPost);

  // Correct, approve the latest revision, and export the actual human text.
  await page.getByLabel('Post text').fill(validPost);
  await expect(page.getByRole('button', { name: 'Save human revision', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: 'Approval queue', exact: false }).click();
  const card = page.locator(`[data-run-id="${runId}"]`);
  await expect(card.getByText(/Revision 1 \(human\)/)).toBeVisible();
  await expect(card.getByText(/pending fresh approval/i)).toBeVisible();
  await card.getByRole('button', { name: 'Approve for export', exact: true }).click();
  await expect(card.getByText('Approved for export', { exact: true })).toBeVisible();
  const downloadEvent = page.waitForEvent('download');
  await card.getByRole('button', { name: 'Export pack', exact: true }).click();
  const download = await downloadEvent;
  const target = `/tmp/human-review-${suffix}.json`;
  await download.saveAs(target);
  const exported = JSON.parse(readFileSync(target, 'utf8')) as {
    run_id: string; approval_state: string; exported_revision: number;
    exported_draft: { post: string; email: string }; maker_draft_v2: { post: string };
  };
  expect(exported.run_id).toBe(runId);
  expect(exported.approval_state).toBe('approved_for_export');
  expect(exported.exported_revision).toBe(1);
  expect(exported.exported_draft.post).toBe(validPost);
  expect(exported.exported_draft.email).toBe(validEmail);
  expect(exported.maker_draft_v2.post).not.toBe(validPost);

  // Failed run through a real unsupported brand_fact memory.
  const memory = (await (await request.post('/api/memory', {
    data: { kind: 'brand_fact', title: `Bad${suffix}`, content: { claim: 'best in Texas' } },
  })).json()) as { id: string };
  const failed = (await (await request.post('/api/runs', {
    data: { idea: wallet, agent_name: 'Maker', memory_ids: [memory.id] },
  })).json()) as { run_id: string; status: string };
  expect(failed.status).toBe('failed');
  await page.getByRole('button', { name: 'Approval queue', exact: false }).click();
  const failedCard = page.locator(`[data-run-id="${failed.run_id}"]`);
  await expect(failedCard.getByText('Pipeline stopped safely')).toBeVisible();
  await expect(failedCard.getByRole('button', { name: 'Approve for export', exact: true })).toHaveCount(0);
  await expect(failedCard.getByRole('button', { name: 'Export pack', exact: true })).toHaveCount(0);
  await failedCard.getByRole('button', { name: 'Review draft', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Pipeline stopped safely.' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Check did not complete.' })).toBeVisible();
  await expect(page.getByLabel('Post text')).toBeDisabled();
  await expect(page.getByLabel('Email text')).toBeDisabled();
  await expect(page.getByText('No approval or export is offered on failed runs.')).toBeVisible();
  await expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});
