import { test, expect } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import { writeFileSync, readFileSync, mkdirSync } from 'node:fs';
import { resolve } from 'node:path';

// Integration acceptance, rendered in Chromium through the Next.js desk on
// isolated ports (web 3021, API 8021, AUTH_ENABLED=false, no model calls).
// Blocked and failed guard states are seeded the same way the backend
// acceptance tests seed them: a direct receipt update in the disposable
// database, then the browser must render the guard. Nothing is published:
// every export assertion also checks submit_attempted is false.
const local = resolve('../.local/integration-acceptance');
mkdirSync(local, { recursive: true });
const suffix = String(Date.now());
const agentName = `Integration${suffix}`;
const wallet = 'Vegan leather wallet, $49, for Austin commuters, launch on Instagram';
const dbUrl = process.env.DATABASE_URL || '';

function seedReceipt(runId: string, path: string, value: string) {
  if (!dbUrl) throw new Error('DATABASE_URL is required for guard seeding');
  const sql = `UPDATE runs SET receipt = jsonb_set(receipt, '{${path}}', '${value}'::jsonb) WHERE id = '${runId}'`;
  execFileSync('psql', [dbUrl, '-v', 'ON_ERROR_STOP=1', '-c', sql], { stdio: 'pipe' });
}

test('integration acceptance V1 plus V2', async ({ page, request }) => {
  test.setTimeout(180_000);
  await page.setViewportSize({ width: 1024, height: 1000 });
  await page.goto('/');
  await page.screenshot({ path: `${local}/01-idea.png`, fullPage: true });

  // V1: create, edit, clone an agent.
  await page.getByRole('button', { name: 'Agent builder', exact: false }).click();
  await page.getByRole('button', { name: 'New agent', exact: true }).click();
  await page.getByLabel('Name', { exact: true }).fill(agentName);
  await page.getByRole('button', { name: 'Save agent', exact: true }).click();
  await expect(page.getByRole('status')).toContainText(`Saved agent ${agentName}`);
  await page.getByLabel('Personality', { exact: true }).fill('Grounded demo editor');
  await page.getByRole('button', { name: 'Save agent', exact: true }).click();
  await page.getByRole('button', { name: 'Dry-run preview', exact: true }).click();
  await expect(page.getByText('No writes · No model calls', { exact: true })).toBeVisible();
  await page.getByLabel('Clone with a new name').fill(`${agentName}Copy`);
  await page.getByRole('button', { name: 'Clone agent', exact: true }).click();
  await expect(page.getByRole('status').first()).toContainText(`Cloned agent ${agentName}Copy`);
  await page.screenshot({ path: `${local}/02-agent.png`, fullPage: true });

  // V1: seeded unsupported claim blocked, then revised; approve and export.
  await page.getByRole('button', { name: 'Launch brief', exact: false }).click();
  await page.getByLabel('Maker profile', { exact: true }).selectOption(agentName);
  await page.getByRole('button', { name: 'Create draft', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Unsupported claims stopped.' })).toBeVisible();
  await expect(page.getByText('best in Texas', { exact: true })).toBeVisible();
  await expect(page.getByText('The revised draft uses only approved facts. Final blocked count: 0.')).toBeVisible();
  const v1Scout = page.locator('section[aria-label="Scout facts and sources"]');
  await expect(v1Scout.locator('.scout-fact')).toHaveCount(5);
  await expect(v1Scout.locator('.scout-risk')).toHaveCount(3);
  await expect(v1Scout.getByText('Verified', { exact: true })).toHaveCount(5);
  await expect(v1Scout).toContainText('No external research was run');
  const v1RunId = await page.locator('.section-row .run-id').innerText();
  await page.screenshot({ path: `${local}/03-run.png`, fullPage: true });
  await page.getByRole('button', { name: 'Go to approval queue', exact: true }).click();
  const v1Card = page.locator(`[data-run-id="${v1RunId}"]`);
  await expect(v1Card.getByText('Pending approval', { exact: true })).toBeVisible();
  await expect(v1Card.getByRole('button', { name: 'Export pack', exact: true })).toHaveCount(0);
  const refused = await request.post(`/api/runs/${v1RunId}/export`, { data: {} });
  expect(refused.status()).toBe(422);
  await v1Card.getByRole('button', { name: 'Approve for export', exact: true }).click();
  await expect(v1Card.getByText('Approved for export', { exact: true })).toBeVisible();
  const v1DownloadEvent = page.waitForEvent('download');
  await v1Card.getByRole('button', { name: 'Export pack', exact: true }).click();
  const v1Download = await v1DownloadEvent;
  const v1Target = `${local}/v1-export.json`;
  await v1Download.saveAs(v1Target);
  const v1Receipt = JSON.parse(readFileSync(v1Target, 'utf8'));
  expect(v1Receipt.run_id).toBe(v1RunId);
  expect(v1Receipt.approval_state).toBe('approved_for_export');
  expect(v1Receipt.approvals[0].approved_by).toBe('demo_placeholder');
  expect(v1Receipt.summary.submit_attempted).toBe(false);
  expect(v1Receipt.scout.facts_used).toHaveLength(5);
  expect(v1Receipt.scout.risks).toHaveLength(3);
  await page.screenshot({ path: `${local}/04-queue.png`, fullPage: true });

  // V1 receipt view shows the same state, no attempted publication.
  await v1Card.getByRole('button', { name: 'View receipt', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Receipt', exact: true })).toBeVisible();
  await expect(page.getByText('Not attempted', { exact: true })).toBeVisible();

  // V2 Memory: create a brand fact, run with it, edit it, run again.
  await page.getByRole('button', { name: 'Memory', exact: false }).click();
  await page.getByLabel('Title', { exact: true }).fill(`Handmade${suffix}`);
  await page.getByLabel('Content JSON object', { exact: true }).fill('{"claim": "Handmade vegan wallet for commuters"}');
  await page.getByRole('button', { name: 'Create memory', exact: true }).click();
  await expect(page.getByText('Memory item created.')).toBeVisible();
  const handmadeCard = page.locator(`article[aria-label="Memory item: Handmade${suffix}"]`);
  const handmadeId = await handmadeCard.locator('.run-id').innerText();
  await page.getByRole('button', { name: 'Launch brief', exact: false }).click();
  await page.getByLabel('Memory ids, comma separated, optional').fill(handmadeId);
  await page.getByLabel('Maker profile', { exact: true }).selectOption(agentName);
  await page.getByRole('button', { name: 'Create draft', exact: true }).click();
  await expect(page.getByText('Handmade vegan wallet for commuters').first()).toBeVisible();
  await page.getByRole('button', { name: 'Memory', exact: false }).click();
  await handmadeCard.getByRole('button', { name: 'Edit memory', exact: true }).click();
  await page.getByLabel('Edit content JSON object').fill('{"claim": "Handmade vegan wallet, designed in Texas"}');
  await page.getByRole('button', { name: 'Save memory', exact: true }).click();
  await page.getByRole('button', { name: 'Launch brief', exact: false }).click();
  await page.getByLabel('Memory ids, comma separated, optional').fill(handmadeId);
  await page.getByLabel('Maker profile', { exact: true }).selectOption(agentName);
  await page.getByRole('button', { name: 'Create draft', exact: true }).click();
  await expect(page.getByText('Handmade vegan wallet, designed in Texas').first()).toBeVisible();
  await expect(page.getByText('Handmade vegan wallet for commuters')).toHaveCount(0);
  await page.screenshot({ path: `${local}/05-memory-edit.png`, fullPage: true });

  // V2 Memory delete: a blocked rule filters the real $49 claim,
  // then after delete it does not.
  await page.getByRole('button', { name: 'Memory', exact: false }).click();
  await page.getByLabel('Title', { exact: true }).fill(`NoSuperlative${suffix}`);
  await page.getByLabel('Content JSON object', { exact: true }).fill('{"claim": "$49"}');
  await page.getByLabel('Kind', { exact: true }).selectOption('blocked_rule');
  await page.getByRole('button', { name: 'Create memory', exact: true }).click();
  await expect(page.getByText('Memory item created.')).toBeVisible();
  const blockedCard = page.locator(`article[aria-label="Memory item: NoSuperlative${suffix}"]`);
  const blockedId = await blockedCard.locator('.run-id').innerText();
  await page.getByRole('button', { name: 'Launch brief', exact: false }).click();
  await page.getByLabel('Memory ids, comma separated, optional').fill(blockedId);
  await page.getByLabel('Maker profile', { exact: true }).selectOption(agentName);
  await page.getByLabel('Include the unsupported claim demo').uncheck();
  await page.getByRole('button', { name: 'Create draft', exact: true }).click();
  await expect(page.getByText('1 blocked in v1').first()).toBeVisible();
  await page.getByRole('button', { name: 'Memory', exact: false }).click();
  page.once('dialog', (dialog) => dialog.accept());
  await blockedCard.getByRole('button', { name: 'Delete memory', exact: true }).click();
  await expect(blockedCard).toHaveCount(0);
  const deletedRun = await request.post('/api/runs', { data: { idea: wallet, agent_name: agentName, memory_ids: [blockedId] } });
  expect(deletedRun.status()).toBe(404);
  await page.getByRole('button', { name: 'Launch brief', exact: false }).click();
  await page.getByLabel('Memory ids, comma separated, optional').fill('');
  await page.getByLabel('Maker profile', { exact: true }).selectOption(agentName);
  await page.getByRole('button', { name: 'Create draft', exact: true }).click();
  await expect(page.getByText('0 blocked in v1').first()).toBeVisible();

  // V2 Replay: standard versus strict Checker on the same idea.
  await page.getByRole('button', { name: 'Memory', exact: false }).click();
  await page.getByLabel('Title', { exact: true }).fill(`Hype${suffix}`);
  await page.getByLabel('Content JSON object', { exact: true }).fill('{"claim": "Amazing vegan wallet for commuters"}');
  await page.getByRole('button', { name: 'Create memory', exact: true }).click();
  await expect(page.getByText('Memory item created.')).toBeVisible();
  const hypeCard = page.locator(`article[aria-label="Memory item: Hype${suffix}"]`);
  const hypeId = await hypeCard.locator('.run-id').innerText();
  const replayIds: string[] = [];
  for (const profile of ['standard', 'strict']) {
    await page.getByRole('button', { name: 'Launch brief', exact: false }).click();
    await page.getByLabel('Checker profile').selectOption(profile);
    await page.getByLabel('Memory ids, comma separated, optional').fill(hypeId);
    await page.getByLabel('Maker profile', { exact: true }).selectOption(agentName);
    await page.getByRole('button', { name: 'Create draft', exact: true }).click();
    replayIds.push(await page.locator('.section-row .run-id').innerText());
  }
  await page.getByRole('button', { name: 'Replay', exact: false }).click();
  await page.getByLabel('Run A id').fill(replayIds[0]);
  await page.getByLabel('Run B id').fill(replayIds[1]);
  await page.getByRole('button', { name: 'Compare', exact: true }).click();
  await expect(page.getByText('Checker profile: standard / strict')).toBeVisible();
  await expect(page.getByText('First blocked count: 0 / 1')).toBeVisible();
  await page.screenshot({ path: `${local}/06-replay.png`, fullPage: true });

  // V2 Campaign Week: seven distinct day cards, per-day gates.
  await page.getByRole('button', { name: 'Campaign', exact: false }).click();
  await page.getByLabel('Maker profile', { exact: true }).selectOption(agentName);
  await page.getByRole('button', { name: 'Create week', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Day 1: Origin story' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Day 7: Launch offer' })).toBeVisible();
  const dayHeadings = await page.locator('article h3').allInnerTexts();
  const angles = dayHeadings.filter((h) => h.startsWith('Day '));
  expect(angles).toHaveLength(7);
  expect(new Set(angles).size).toBe(7);
  const briefs: string[] = [];
  for (let day = 1; day <= 7; day++) {
    const card = page.locator('article', { has: page.getByRole('heading', { name: `Day ${day}:` }) });
    briefs.push(await card.locator('h3 + p').innerText());
  }
  expect(briefs).toHaveLength(7);
  expect(briefs.every((brief) => brief.trim().length > 0)).toBe(true);
  expect(new Set(briefs).size).toBe(7);
  const weekId = await page.locator('section p.run-id').first().innerText();
  const week = await request.get(`/api/campaigns/${weekId}`);
  const weekJson = await week.json();
  const apiBriefs = weekJson.days.map((d: { brief: string }) => d.brief);
  expect(new Set(apiBriefs).size).toBe(7);
  expect(briefs).toEqual(apiBriefs);
  const day2Run = weekJson.days[1].run_id;
  const day1Run = weekJson.days[0].run_id;
  // SEEDED blocked day: direct receipt update in the disposable database,
  // then the browser must render the guard. Not a natural UI blocked path.
  seedReceipt(day2Run, 'checker_v2,blocked_count', '1');
  await page.reload();
  await page.getByRole('button', { name: 'Campaign', exact: false }).click();
  await page.getByLabel('Open a campaign').selectOption(weekId);
  await expect(page.getByRole('heading', { name: 'Day 1: Origin story' })).toBeVisible();
  const day2Card = page.locator('article', { has: page.getByRole('heading', { name: 'Day 2:' }) });
  await expect(day2Card.getByRole('button', { name: 'Approve for export', exact: true })).toHaveCount(0);
  await expect(day2Card.getByRole('button', { name: 'Export pack', exact: true })).toHaveCount(0);
  const day1Card = page.locator('article', { has: page.getByRole('heading', { name: 'Day 1:' }) });
  await expect(day1Card.getByRole('button', { name: 'Export pack', exact: true })).toHaveCount(0);
  const day1RunRefused = await request.post(`/api/runs/${day1Run}/export`, { data: {} });
  expect(day1RunRefused.status()).toBe(422);
  const day1CampaignRefused = await request.post(`/api/campaigns/${weekId}/days/1/export`, { data: {} });
  expect(day1CampaignRefused.status()).toBe(422);
  await expect(day1Card.getByText('pending_approval')).toBeVisible();
  await day1Card.getByRole('button', { name: 'Approve for export', exact: true }).click();
  await expect(day1Card.getByText('approved_for_export')).toBeVisible();
  const day1DownloadEvent = page.waitForEvent('download');
  await day1Card.getByRole('button', { name: 'Export pack', exact: true }).click();
  const day1Download = await day1DownloadEvent;
  const day1Target = `${local}/campaign-day1-export.json`;
  await day1Download.saveAs(day1Target);
  const day1Receipt = JSON.parse(readFileSync(day1Target, 'utf8'));
  expect(day1Receipt.run_id).toBe(day1Run);
  expect(day1Receipt.approval_state).toBe('approved_for_export');
  expect(day1Receipt.summary.submit_attempted).toBe(false);
  const day3Card = page.locator('article', { has: page.getByRole('heading', { name: 'Day 3:' }) });
  await day3Card.getByRole('button', { name: 'Approve for export', exact: true }).click();
  await expect(day3Card.getByText('approved_for_export')).toBeVisible();
  const day4Card = page.locator('article', { has: page.getByRole('heading', { name: 'Day 4:' }) });
  await expect(day4Card.getByText('pending_approval')).toBeVisible();
  await page.screenshot({ path: `${local}/07-campaign.png`, fullPage: true });

  // Failed run guard in the queue: Approve is disabled, export is refused.
  // SEEDED failed run: direct receipt update in the disposable database,
  // then the browser must render the guard. Not a natural UI failure path.
  const failedRun = await request.post('/api/runs', { data: { idea: wallet, agent_name: agentName, seed_unverified_claim: false } });
  const failedJson = await failedRun.json();
  seedReceipt(failedJson.run_id, 'status', '"failed"');
  await page.getByRole('button', { name: 'Approval queue', exact: false }).click();
  const failedCard = page.locator(`[data-run-id="${failedJson.run_id}"]`);
  await expect(failedCard.getByRole('button', { name: 'Approve for export', exact: true })).toBeDisabled();
  const failedExport = await request.post(`/api/runs/${failedJson.run_id}/export`, { data: {} });
  expect(failedExport.status()).toBe(422);
  const failedApprove = await request.post(`/api/runs/${failedJson.run_id}/approve`, { data: {} });
  expect(failedApprove.status()).toBe(422);
  await page.screenshot({ path: `${local}/08-failed-guard.png`, fullPage: true });

  writeFileSync(`${local}/summary.json`, JSON.stringify({ agentName, v1RunId, replayIds, weekId, day1Run, day2Run, failedRunId: failedJson.run_id, v1Receipt, day1Receipt }, null, 2));
});
