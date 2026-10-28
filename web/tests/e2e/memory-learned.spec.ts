import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';

// Learned memory end to end through the real desk UI and API, no route
// mocks. A PriceGuard Checker (veto_scope price_claims, decision rule Block
// price claims) blocks the naturally occurring $49 claim in an ordinary run
// with the unsupported-claim demo switched off. That approved run is
// exported, both memory kinds are learned from it, the learned blocked rule
// is selected into a later default-Checker run, edited to another real
// approved claim, and deleted, while the learned example stays style-only.
// A rule for an absent claim records zero blocks and changes no draft.
// Multiline personality and expertise persist, clone, and reach the Maker
// stage snapshot. No publishing: every export also asserts submit_attempted
// is false.
const wallet = 'Vegan leather wallet, $49, for Austin commuters, launch on Instagram';

test('learned memory rules and multiline crew survive the desk', async ({ page, request }) => {
  test.setTimeout(180_000);
  await page.setViewportSize({ width: 1024, height: 1000 });
  const suffix = String(Date.now());
  const agentName = `MemMaker${suffix}`;
  const guardName = `MemPriceGuard${suffix}`;
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

  // PriceGuard Checker: only supported exact-match policy entries are enforced.
  await page.getByRole('button', { name: 'New agent', exact: true }).click();
  await page.getByLabel('Name', { exact: true }).fill(guardName);
  await page.getByRole('button', { name: 'Save agent', exact: true }).click();
  await expect(page.getByRole('status')).toContainText(`Saved agent ${guardName}`);
  await page.getByLabel('Decision rules (one per line)').fill('Block price claims');
  await page.getByLabel('Veto scope (one per line)').fill('price_claims');
  await page.getByRole('button', { name: 'Save agent', exact: true }).click();

  // Policy-triggered run: no unsupported seed, the $49 claim is real.
  await page.getByRole('button', { name: 'Launch brief', exact: false }).click();
  await page.getByLabel('Maker profile', { exact: true }).selectOption(agentName);
  await page.getByLabel('Checker agent', { exact: true }).selectOption(guardName);
  await page.getByLabel('Include the unsupported claim demo').uncheck();
  await page.getByRole('button', { name: 'Create draft', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Unsupported claims stopped.' })).toBeVisible();
  await expect(page.getByText('$49', { exact: true }).first()).toBeVisible();
  await expect(page.getByText('1 blocked in v1').first()).toBeVisible();
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
  const ruleItem = (await (await request.get(`/api/memory/${ruleId}`)).json()) as { content: { blocked_claims: { claim: string }[] } };
  expect(ruleItem.content.blocked_claims.map((entry) => entry.claim)).toEqual(['$49']);

  await page.getByLabel('Run id', { exact: true }).fill(seedId);
  await page.getByLabel('Learned kind', { exact: true }).selectOption('approval_example');
  await page.getByRole('button', { name: 'Learn from run', exact: true }).click();
  await expect(page.getByText('Memory learned from the selected run.')).toBeVisible();
  const learnedExampleCard = page.locator('article[aria-label^="Memory item: approval_example:"]');
  await expect(learnedExampleCard.first()).toBeVisible();
  const exampleId = await learnedExampleCard.first().locator('.run-id').innerText();

  // Learned blocked rule filters the real claim under the default Checker.
  await page.getByRole('button', { name: 'Launch brief', exact: false }).click();
  await page.getByLabel('Memory ids, comma separated, optional').fill(ruleId);
  await page.getByLabel('Maker profile', { exact: true }).selectOption(agentName);
  await page.getByLabel('Checker agent', { exact: true }).selectOption('Checker');
  await page.getByLabel('Include the unsupported claim demo').uncheck();
  await page.getByRole('button', { name: 'Create draft', exact: true }).click();
  await expect(page.getByText('1 blocked in v1').first()).toBeVisible();
  const ruledId = await page.locator('.section-row .run-id').innerText();
  const ruled = (await (await request.get(`/api/runs/${ruledId}`)).json()) as {
    memory_used: { id: string }[]; memory_blocked_rules: { claim: string }[];
    maker_draft_v1: { post: string }; maker_draft_v2: { post: string }; checker_v2: { blocked_count: number };
  };
  expect(ruled.memory_used.map((entry) => entry.id)).toContain(ruleId);
  expect(ruled.memory_blocked_rules[0].claim).toBe('$49');
  expect(ruled.maker_draft_v1.post).toContain('$49');
  expect(ruled.maker_draft_v2.post).not.toContain('$49');
  expect(ruled.checker_v2.blocked_count).toBe(0);

  // Default Checker without the rule: no block, price present.
  const plain = (await (await request.post('/api/runs', {
    data: { idea: wallet, agent_name: agentName, seed_unverified_claim: false },
  })).json()) as { checker_v1: { blocked_count: number }; maker_draft_v2: { post: string } };
  expect(plain.checker_v1.blocked_count).toBe(0);

  // A rule for an absent claim records zero blocks and changes no draft.
  const absent = (await (await request.post('/api/memory', {
    data: { kind: 'blocked_rule', title: `NoHype${suffix}`, content: { claim: 'best in Texas' } },
  })).json()) as { id: string };
  const absentRun = (await (await request.post('/api/runs', {
    data: { idea: wallet, agent_name: agentName, seed_unverified_claim: false, memory_ids: [absent.id] },
  })).json()) as {
    checker_v1: { blocked_count: number }; maker_draft_v1: { post: string };
    maker_draft_v2: { post: string }; memory_blocked_rules: { claim: string }[];
  };
  expect(absentRun.memory_blocked_rules[0].claim).toBe('best in Texas');
  expect(absentRun.checker_v1.blocked_count).toBe(0);
  expect(absentRun.maker_draft_v1.post).not.toContain('best in Texas');
  expect(absentRun.maker_draft_v2.post).not.toContain('best in Texas');

  // Learned example is style context only: keyless drafts match with or without it.
  const withExample = (await (await request.post('/api/runs', {
    data: { idea: wallet, agent_name: agentName, memory_ids: [exampleId] },
  })).json()) as { maker_draft_v2: unknown; memory_examples: { id: string }[] };
  const plainRun = (await (await request.post('/api/runs', {
    data: { idea: wallet, agent_name: agentName },
  })).json()) as { maker_draft_v2: unknown };
  expect(withExample.maker_draft_v2).toEqual(plainRun.maker_draft_v2);
  expect(withExample.memory_examples.map((entry) => entry.id)).toContain(exampleId);

  // Editing the learned rule to another real claim changes the verdict identity.
  await page.getByRole('button', { name: 'Memory', exact: false }).click();
  await learnedRuleCard.first().getByRole('button', { name: 'Edit memory', exact: true }).click();
  await page.getByLabel('Edit content JSON object').fill('{"blocked_claims": [{"claim": "Designed in Texas", "reason": "Edited rule"}]}');
  await page.getByRole('button', { name: 'Save memory', exact: true }).click();
  await page.getByRole('button', { name: 'Launch brief', exact: false }).click();
  await page.getByLabel('Memory ids, comma separated, optional').fill(ruleId);
  await page.getByLabel('Maker profile', { exact: true }).selectOption(agentName);
  await page.getByLabel('Checker agent', { exact: true }).selectOption('Checker');
  await page.getByLabel('Include the unsupported claim demo').uncheck();
  await page.getByRole('button', { name: 'Create draft', exact: true }).click();
  await expect(page.getByText('1 blocked in v1').first()).toBeVisible();
  await expect(page.getByText('Designed in Texas', { exact: true }).first()).toBeVisible();
  const editedId = await page.locator('.section-row .run-id').innerText();
  const edited = (await (await request.get(`/api/runs/${editedId}`)).json()) as {
    checker_v1: { blocked_claims: { claim: string }[] }; maker_draft_v2: { post: string };
  };
  expect(edited.checker_v1.blocked_claims.map((entry) => entry.claim)).toEqual(['Designed in Texas']);
  expect(edited.maker_draft_v2.post).not.toContain('Designed in Texas');
  expect(edited.maker_draft_v2.post).toContain('$49');

  // Deleting the learned rule removes its effect; reuse is refused and the
  // old receipt still carries its snapshot.
  await page.getByRole('button', { name: 'Memory', exact: false }).click();
  page.once('dialog', (dialog) => dialog.accept());
  await learnedRuleCard.first().getByRole('button', { name: 'Delete memory', exact: true }).click();
  await expect(learnedRuleCard).toHaveCount(0);
  const reused = await request.post('/api/runs', { data: { idea: wallet, agent_name: agentName, memory_ids: [ruleId] } });
  expect(reused.status()).toBe(404);
  await page.getByRole('button', { name: 'Launch brief', exact: false }).click();
  await page.getByLabel('Memory ids, comma separated, optional').fill('');
  await page.getByLabel('Maker profile', { exact: true }).selectOption(agentName);
  await page.getByLabel('Checker agent', { exact: true }).selectOption('Checker');
  await page.getByLabel('Include the unsupported claim demo').uncheck();
  await page.getByRole('button', { name: 'Create draft', exact: true }).click();
  await expect(page.getByText('0 blocked in v1').first()).toBeVisible();
  const reread = (await (await request.get(`/api/runs/${ruledId}`)).json()) as {
    memory_blocked_rules: { claim: string }[];
  };
  expect(reread.memory_blocked_rules[0].claim).toBe('$49');
  await expect(page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});
