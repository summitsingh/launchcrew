import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';

// Learned memory end to end through the real desk UI and API, no route
// mocks. A seeded run is approved and exported, both memory kinds are
// learned from it, the learned blocked rule is selected into a later run,
// edited away, and deleted, while the learned example stays style-only.
// Multiline personality and expertise persist, clone, and reach the Maker
// stage snapshot. No publishing: every export also asserts submit_attempted
// is false.
const wallet = 'Vegan leather wallet, $49, for Austin commuters, launch on Instagram';

test('learned memory rules and multiline crew survive the desk', async ({ page, request }) => {
  test.setTimeout(180_000);
  await page.setViewportSize({ width: 1024, height: 1000 });
  const suffix = String(Date.now());
  const agentName = `MemMaker${suffix}`;
  await page.goto('/');
  await expect(page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);

  // Multiline personality and expertise through accessible textarea controls.
  await page.getByRole('button', { name: 'Agent builder', exact: false }).click();
  await page.getByRole('button', { name: 'New agent', exact: true }).click();
  await page.getByLabel('Name', { exact: true }).fill(agentName);
  await page.getByRole('button', { name: 'Save agent', exact: true }).click();
  await expect(page.getByRole('status')).toContainText(`Saved agent ${agentName}`);
  await expect(page.getByLabel('Personality', { exact: true }).evaluate((node) => node.tagName)).toBe('TEXTAREA');
  await expect(page.getByLabel('Expertise', { exact: true }).evaluate((node) => node.tagName)).toBe('TEXTAREA');
  await page.getByLabel('Personality', { exact: true }).fill('Grounded editor\nSecond line of judgment');
  await page.getByLabel('Expertise', { exact: true }).fill('Austin commuter voice\nPlain words only');
  await page.getByRole('button', { name: 'Save agent', exact: true }).click();
  await page.getByLabel('Clone with a new name').fill(`${agentName}Copy`);
  await page.getByRole('button', { name: 'Clone agent', exact: true }).click();
  await expect(page.getByRole('status').first()).toContainText(`Cloned agent ${agentName}Copy`);
  await expect(page.getByLabel('Personality', { exact: true })).toHaveValue('Grounded editor\nSecond line of judgment');
  await expect(page.getByLabel('Expertise', { exact: true })).toHaveValue('Austin commuter voice\nPlain words only');

  // Seeded run: blocked in v1, revised clean, gated export, approve, export.
  await page.getByRole('button', { name: 'Launch brief', exact: false }).click();
  await page.getByLabel('Maker profile', { exact: true }).selectOption(agentName);
  await page.getByRole('button', { name: 'Create draft', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Unsupported claims stopped.' })).toBeVisible();
  await expect(page.getByText('best in Texas', { exact: true })).toBeVisible();
  const seedId = await page.locator('.section-row .run-id').innerText();
  const seedReceipt = (await (await request.get(`/api/runs/${seedId}`)).json()) as {
    stage_agents: { maker: { personality: string; expertise: string } };
    approval_state: string; summary: { submit_attempted: boolean };
  };
  expect(seedReceipt.stage_agents.maker.personality).toContain('Second line of judgment');
  expect(seedReceipt.stage_agents.maker.expertise).toContain('Plain words only');
  const refused = await request.post(`/api/runs/${seedId}/export`, { data: {} });
  expect(refused.status()).toBe(422);
  await page.getByRole('button', { name: 'Go to approval queue', exact: true }).click();
  const seedCard = page.locator(`[data-run-id="${seedId}"]`);
  await seedCard.getByRole('button', { name: 'Approve for export', exact: true }).click();
  await expect(seedCard.getByText('Approved for export', { exact: true })).toBeVisible();
  const downloadEvent = page.waitForEvent('download');
  await seedCard.getByRole('button', { name: 'Export pack', exact: true }).click();
  const download = await downloadEvent;
  const target = `/tmp/learned-seed-${suffix}.json`;
  await download.saveAs(target);
  const exported = JSON.parse(readFileSync(target, 'utf8')) as { approval_state: string; summary: { submit_attempted: boolean } };
  expect(exported.approval_state).toBe('approved_for_export');
  expect(exported.summary.submit_attempted).toBe(false);

  // Learn both kinds from the approved run through the desk UI.
  await page.getByRole('button', { name: 'Memory', exact: false }).click();
  await page.getByLabel('Run id', { exact: true }).fill(seedId);
  await page.getByLabel('Learned kind', { exact: true }).selectOption('blocked_rule');
  await page.getByRole('button', { name: 'Learn from run', exact: true }).click();
  await expect(page.getByText('Memory learned from the selected run.')).toBeVisible();
  const learnedRuleCard = page.locator('article[aria-label^="Memory item: blocked_rule:"]');
  await expect(learnedRuleCard.first()).toBeVisible();
  const ruleId = await learnedRuleCard.first().locator('.run-id').innerText();
  const ruleItem = (await (await request.get(`/api/memory/${ruleId}`)).json()) as { content: { blocked_claims: unknown } };
  expect(Array.isArray((ruleItem.content as { blocked_claims: unknown }).blocked_claims)).toBe(true);

  await page.getByLabel('Run id', { exact: true }).fill(seedId);
  await page.getByLabel('Learned kind', { exact: true }).selectOption('approval_example');
  await page.getByRole('button', { name: 'Learn from run', exact: true }).click();
  await expect(page.getByText('Memory learned from the selected run.')).toBeVisible();
  const learnedExampleCard = page.locator('article[aria-label^="Memory item: approval_example:"]');
  await expect(learnedExampleCard.first()).toBeVisible();
  const exampleId = await learnedExampleCard.first().locator('.run-id').innerText();

  // Learned blocked rule persists into a later run and shows provenance.
  await page.getByRole('button', { name: 'Launch brief', exact: false }).click();
  await page.getByLabel('Memory ids, comma separated, optional').fill(ruleId);
  await page.getByLabel('Maker profile', { exact: true }).selectOption(agentName);
  await page.getByLabel('Include the unsupported claim demo').uncheck();
  await page.getByRole('button', { name: 'Create draft', exact: true }).click();
  await expect(page.getByText('1 blocked in v1').first()).toBeVisible();
  const ruledId = await page.locator('.section-row .run-id').innerText();
  const ruled = (await (await request.get(`/api/runs/${ruledId}`)).json()) as {
    memory_used: { id: string }[]; memory_blocked_rules: { claim: string }[];
    maker_draft_v2: { post: string }; checker_v2: { blocked_count: number };
  };
  expect(ruled.memory_used.map((entry) => entry.id)).toContain(ruleId);
  expect(ruled.memory_blocked_rules[0].claim).toBe('best in Texas');
  expect(ruled.maker_draft_v2.post).not.toContain('best in Texas');
  expect(ruled.checker_v2.blocked_count).toBe(0);

  // Learned example is style context only: keyless drafts match with or without it.
  const withExample = (await (await request.post('/api/runs', {
    data: { idea: wallet, agent_name: agentName, memory_ids: [exampleId] },
  })).json()) as { maker_draft_v2: unknown; memory_examples: { id: string }[] };
  const plainRun = (await (await request.post('/api/runs', {
    data: { idea: wallet, agent_name: agentName },
  })).json()) as { maker_draft_v2: unknown };
  expect(withExample.maker_draft_v2).toEqual(plainRun.maker_draft_v2);
  expect(withExample.memory_examples.map((entry) => entry.id)).toContain(exampleId);

  // Editing the learned rule to a malformed value removes its effect.
  await page.getByRole('button', { name: 'Memory', exact: false }).click();
  await learnedRuleCard.first().getByRole('button', { name: 'Edit memory', exact: true }).click();
  await page.getByLabel('Edit content JSON object').fill('{"blocked_claims": [{"nope": 1}]}');
  await page.getByRole('button', { name: 'Save memory', exact: true }).click();
  await page.getByRole('button', { name: 'Launch brief', exact: false }).click();
  await page.getByLabel('Memory ids, comma separated, optional').fill(ruleId);
  await page.getByLabel('Maker profile', { exact: true }).selectOption(agentName);
  await page.getByLabel('Include the unsupported claim demo').uncheck();
  await page.getByRole('button', { name: 'Create draft', exact: true }).click();
  await expect(page.getByText('0 blocked in v1').first()).toBeVisible();

  // Deleting the learned rule removes it; reuse is refused and the old
  // receipt still carries its snapshot.
  await page.getByRole('button', { name: 'Memory', exact: false }).click();
  page.once('dialog', (dialog) => dialog.accept());
  await learnedRuleCard.first().getByRole('button', { name: 'Delete memory', exact: true }).click();
  await expect(learnedRuleCard).toHaveCount(0);
  const reused = await request.post('/api/runs', { data: { idea: wallet, agent_name: agentName, memory_ids: [ruleId] } });
  expect(reused.status()).toBe(404);
  const reread = (await (await request.get(`/api/runs/${ruledId}`)).json()) as {
    memory_blocked_rules: { claim: string }[];
  };
  expect(reread.memory_blocked_rules[0].claim).toBe('best in Texas');
  await expect(page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});
