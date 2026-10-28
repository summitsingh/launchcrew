import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';

// Human revision editing through the real desk UI and API, no route mocks.
// The original Maker pack is approved first through the UI, then the run is
// reopened for review: a valid human revision resets approval, an
// unsupported edit is rejected unsaved with per-claim reasons, and a fresh
// reapproval plus export uses the latest human text with a persisted export
// event and receipt timeline. A failed run is produced through a real
// unsupported brand_fact memory (actual core failure, not a SQL seed) and
// the desk shows explicit failed status with no edit, approve, or export
// controls.
const wallet = 'Vegan leather wallet, $49, for Austin commuters, launch on Instagram';

test('human revision editing and failed run review', async ({ page, request }) => {
  test.setTimeout(180_000);
  await page.setViewportSize({ width: 1024, height: 1000 });
  const suffix = String(Date.now());
  const queueNav = () => page.getByRole('navigation', { name: 'Workspace' }).getByRole('button', { name: 'Approval queue' });
  await page.goto('/');
  await expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);

  // Clean run without the unsupported-claim demo.
  await page.getByLabel('Maker profile', { exact: true }).selectOption('Maker');
  await page.getByLabel('Include the unsupported claim demo').uncheck();
  await page.getByRole('button', { name: 'Create draft', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Ready for your review.' })).toBeVisible();
  const runId = await page.locator('.section-row .run-id').innerText();
  expect(runId.startsWith('run_')).toBe(true);

  // Approve the original Maker pack first through the real queue UI.
  await queueNav().click();
  const makerCard = page.locator(`[data-run-id="${runId}"]`);
  await expect(makerCard.getByText(/Revision 0 \(Maker\)/)).toBeVisible();
  await expect(makerCard.getByText(/pending approval/i)).toBeVisible();
  await makerCard.getByRole('button', { name: 'Approve for export', exact: true }).click();
  await expect(makerCard.getByText('Approved for export', { exact: true })).toBeVisible();

  // Reopen the approved run for review and save a valid human revision.
  await makerCard.getByRole('button', { name: 'Review draft', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Ready for your review.' })).toBeVisible();
  const validPost = 'Vegan leather wallet. Designed in Texas.';
  const validEmail = 'For Austin commuters. $49.';
  await page.getByLabel('Post text').fill(validPost);
  await page.getByLabel('Email text').fill(validEmail);
  await expect(page.getByText('Unsaved changes. Save runs the deterministic recheck.')).toBeVisible();
  await page.getByRole('button', { name: 'Save human revision', exact: true }).click();
  await expect(page.getByText(/Saved revision 1\. This pack needs fresh approval before export\./)).toBeVisible();
  await expect(page.getByText(/Current revision: 1 \(human revision\)/)).toBeVisible();

  // The saved revision resets the earlier Maker approval: the stored run is
  // pending again with no current approvals, and the queue card says so.
  const reset = (await (await request.get(`/api/runs/${runId}`)).json()) as {
    revision: number; approval_state: string; approved_revision: number | null;
    approvals: Array<{ approved_by: string; revision: number }>;
  };
  expect(reset.revision).toBe(1);
  expect(reset.approval_state).toBe('pending_approval');
  expect(reset.approved_revision).toBe(null);
  expect(reset.approvals.length).toBe(0);
  await queueNav().click();
  const card = page.locator(`[data-run-id="${runId}"]`);
  await expect(card.getByText(/Revision 1 \(human\)/)).toBeVisible();
  await expect(card.getByText(/pending fresh approval/i)).toBeVisible();

  // Return to the run, then an unsupported edit is rejected unsaved with
  // per-claim reasons.
  await card.getByRole('button', { name: 'Review draft', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Ready for your review.' })).toBeVisible();
  await page.getByLabel('Post text').fill('best in Texas. Vegan leather wallet.');
  await page.getByRole('button', { name: 'Save human revision', exact: true }).click();
  await expect(page.getByText(/Needs revision:/).first()).toBeVisible();
  await expect(page.getByText(/best in Texas/).first()).toBeVisible();
  const reread = (await (await request.get(`/api/runs/${runId}`)).json()) as {
    revision: number; approval_state: string; human_draft: { post: string };
  };
  expect(reread.revision).toBe(1);
  expect(reread.human_draft.post).toBe(validPost);
  expect(reread.approval_state).toBe('pending_approval');

  // Correct, approve the latest revision, and export the actual human text.
  await page.getByLabel('Post text').fill(validPost);
  await expect(page.getByRole('button', { name: 'Save human revision', exact: true })).toBeDisabled();
  await queueNav().click();
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
    approvals: Array<{ approved_by: string; revision: number; timestamp: string }>;
    export_history: Array<{ revision: number; exported_by: string; timestamp: string }>;
  };
  expect(exported.run_id).toBe(runId);
  expect(exported.approval_state).toBe('approved_for_export');
  expect(exported.exported_revision).toBe(1);
  expect(exported.exported_draft.post).toBe(validPost);
  expect(exported.exported_draft.email).toBe(validEmail);
  expect(exported.maker_draft_v2.post).not.toBe(validPost);
  // The persisted export event records the actual actor, revision, and time.
  expect(exported.approvals.length).toBe(1);
  expect(exported.approvals[0].approved_by).toBe('demo_placeholder');
  expect(exported.approvals[0].revision).toBe(1);
  expect(exported.export_history.length).toBe(1);
  expect(exported.export_history[0].revision).toBe(1);
  expect(exported.export_history[0].exported_by).toBe('demo_placeholder');

  // The receipt UI shows the same persisted export event in its timeline.
  await card.getByRole('button', { name: 'View receipt', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Receipt', exact: true })).toBeVisible();
  await expect(page.getByText('demo_placeholder', { exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Recorded events' })).toBeVisible();
  await expect(page.getByText(/Exported revision 1 by demo_placeholder/)).toBeVisible();
  await expect(page.getByText(/Approval 1: demo_placeholder · revision 1/)).toBeVisible();
  await page.getByText('Inspect complete receipt JSON', { exact: true }).click();
  await expect(page.locator('pre')).toContainText(runId);
  await expect(page.locator('pre')).toContainText('export_history');

  // Failed run through a real unsupported brand_fact memory.
  const memory = (await (await request.post('/api/memory', {
    data: { kind: 'brand_fact', title: `Bad${suffix}`, content: { claim: 'best in Texas' } },
  })).json()) as { id: string };
  const failed = (await (await request.post('/api/runs', {
    data: { idea: wallet, agent_name: 'Maker', memory_ids: [memory.id] },
  })).json()) as { run_id: string; status: string };
  expect(failed.status).toBe('failed');
  await queueNav().click();
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
