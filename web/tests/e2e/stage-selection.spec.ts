import { test, expect } from '@playwright/test';
import { writeFileSync, readFileSync, mkdirSync } from 'node:fs';
import { resolve } from 'node:path';

// Custom stage selection, rendered through the Next.js desk on isolated
// ports (web 3021, API 8021, AUTH_ENABLED=false, no model calls).
// Seeded state: none. Every blocked state below is a natural UI path:
// a supported Checker policy (price_claims, exact match) blocks the $49
// price claim, while the default Checker passes the same input.
// Nothing is published: submit_attempted stays false and no export is
// attempted in this spec. Receipt identity is proved through the rendered
// Run review plus the API receipt, not through source-string checks.
const local = resolve('../.local/stage-selection');
mkdirSync(local, { recursive: true });
const suffix = String(Date.now());
const scoutName = `EagleScout${suffix}`;
const checkerName = `PriceGuard${suffix}`;
const wallet = 'Vegan leather wallet, $49, for Austin commuters, launch on Instagram';

async function showAdvanced(page: import('@playwright/test').Page) {
  const toggle = page.getByRole('button', { name: 'Advanced', exact: true });
  if ((await toggle.getAttribute('aria-expanded')) === 'false') await toggle.click();
}

async function createAgent(
  page: import('@playwright/test').Page,
  fields: { name: string; role: string; personality: string; expertise: string; rules: string; veto: string },
) {
  await showAdvanced(page);
  await page.getByRole('button', { name: 'Agent builder', exact: false }).click();
  await page.getByRole('button', { name: 'New agent', exact: true }).click();
  await page.getByLabel('Name', { exact: true }).fill(fields.name);
  await page.getByLabel('Role', { exact: true }).fill(fields.role);
  await page.getByLabel('Personality', { exact: true }).fill(fields.personality);
  await page.getByLabel('Expertise', { exact: true }).fill(fields.expertise);
  await page.getByLabel('decision rules (one per line)').fill(fields.rules);
  await page.getByLabel('veto scope (one per line)').fill(fields.veto);
  await page.getByRole('button', { name: 'Save agent', exact: true }).click();
  await expect(page.getByRole('status')).toContainText(`Saved agent ${fields.name}`);
}

test('custom Scout and Checker selection changes verdict and receipt identity', async ({ page, request }) => {
  test.setTimeout(180_000);
  await page.setViewportSize({ width: 1024, height: 1000 });
  await page.goto('/');
  await page.screenshot({ path: `${local}/01-idea.png`, fullPage: true });

  await createAgent(page, {
    name: scoutName,
    role: 'Skeptical Analyst',
    personality: `Cautious source-first analyst marker S${suffix}`,
    expertise: `Demo market notes marker S${suffix}`,
    rules: 'Use facts file first\nCite a source for every fact',
    veto: '',
  });
  await createAgent(page, {
    name: checkerName,
    role: 'Strict Auditor',
    personality: `Blocks price claims marker C${suffix}`,
    expertise: `Demo approval rules marker C${suffix}`,
    rules: 'Block price claims',
    veto: 'price_claims',
  });
  await page.screenshot({ path: `${local}/02-agents.png`, fullPage: true });

  // Dry-run preview proves the supported policy is enforced, advisory-free.
  // Agent buttons read as letter plus name plus role (for example,
  // C PriceGuard Strict Auditor), so match name with its role, not exact.
  await page.getByRole('button', { name: `${checkerName} Strict Auditor`, exact: false }).first().click();
  await page.getByRole('button', { name: 'Dry-run preview', exact: true }).click();
  await expect(page.getByText('Enforced policies: price_claims')).toBeVisible();
  await page.screenshot({ path: `${local}/03-preview.png`, fullPage: true });

  async function runWithChecker(checker: string) {
    await page.getByRole('button', { name: 'Launch brief', exact: false }).click();
    await page.getByLabel('Scout agent').selectOption(scoutName);
    await page.getByLabel('Maker agent', { exact: true }).selectOption('Maker');
    await page.getByLabel('Checker agent').selectOption(checker);
    await page.getByLabel('Checker profile').selectOption('standard');
    await page.getByLabel('Memory ids, comma separated, optional').fill('');
    const seedBox = page.getByLabel('Include the unsupported claim demo');
    if (await seedBox.isChecked()) await seedBox.uncheck();
    await page.getByLabel('Product, audience, and launch channel').fill(wallet);
    await page.getByRole('button', { name: 'Create draft', exact: true }).click();
    const runId = await page.locator('.section-row .run-id').innerText();
    return runId;
  }

  // Same input, default Checker first: price passes. The Run review
  // check strip reads Approved facts sourced plus Scout name, and blocked
  // count plus Checker name, so assert that rendered text, with the exact
  // blocked count proved through the API receipt below.
  const runDefault = await runWithChecker('Checker');
  await expect(page.getByText(`Approved facts sourced · ${scoutName}`).first()).toBeVisible();
  await expect(page.getByText('0 blocked in v1 · Checker').first()).toBeVisible();
  const defaultReceiptRes = await request.get(`/api/runs/${runDefault}/receipt`);
  expect(defaultReceiptRes.status()).toBe(200);
  const defaultReceipt = await defaultReceiptRes.json();
  expect(defaultReceipt.stage_bindings).toEqual({ scout: scoutName, maker: 'Maker', checker: 'Checker' });
  expect(defaultReceipt.stage_agents.scout.name).toBe(scoutName);
  expect(defaultReceipt.stage_agents.checker.name).toBe('Checker');
  expect(defaultReceipt.checker_v1.blocked_count).toBe(0);
  expect(defaultReceipt.maker_draft_v2.post).toContain('$49');
  expect((defaultReceipt.checker_enforcement.effective_policies as string[])).not.toContain('price_claims');
  expect(defaultReceipt.scout.facts_used).toHaveLength(5);
  expect(defaultReceipt.scout.risks).toHaveLength(3);
  const defaultScout = page.locator('section[aria-label="Scout facts and sources"]');
  const defaultSourcedFacts = defaultScout.locator('h3:has-text("Sourced facts") + ul > li.scout-fact');
  await expect(defaultSourcedFacts).toHaveCount(5);
  await expect(defaultScout.locator('.scout-risk')).toHaveCount(3);
  await page.screenshot({ path: `${local}/04-default.png`, fullPage: true });

  // Same input, custom PriceGuard: price is blocked and revised out.
  const runGuarded = await runWithChecker(checkerName);
  await expect(page.getByText(`Approved facts sourced · ${scoutName}`).first()).toBeVisible();
  await expect(page.getByText(`blocked in v1 · ${checkerName}`).first()).toBeVisible();
  await expect(page.getByText('$49', { exact: false }).first()).toBeVisible();
  const guardedReceiptRes = await request.get(`/api/runs/${runGuarded}/receipt`);
  expect(guardedReceiptRes.status()).toBe(200);
  const guardedReceipt = await guardedReceiptRes.json();
  expect(guardedReceipt.stage_bindings).toEqual({ scout: scoutName, maker: 'Maker', checker: checkerName });
  expect(guardedReceipt.stage_agents.scout.name).toBe(scoutName);
  expect(guardedReceipt.stage_agents.scout.personality).toContain(`S${suffix}`);
  expect(guardedReceipt.stage_agents.checker.name).toBe(checkerName);
  expect(guardedReceipt.stage_agents.checker.veto_scope).toContain('price_claims');
  expect(guardedReceipt.checker_v1.blocked_count).toBeGreaterThan(0);
  const blocked = (guardedReceipt.checker_v1.blocked_claims as { claim: string; reason: string }[]).map((item) => item.claim);
  expect(blocked.join(' ')).toContain('$49');
  const reasons = (guardedReceipt.checker_v1.blocked_claims as { reason: string }[]).map((item) => item.reason).join(' ');
  expect(reasons).toContain('price_claims');
  expect(guardedReceipt.maker_draft_v2.post).not.toContain('$49');
  expect(guardedReceipt.checker_enforcement.effective_policies).toContain('price_claims');
  expect(guardedReceipt.summary.submit_attempted).toBe(false);
  expect(guardedReceipt.scout.facts_used).toHaveLength(5);
  expect(guardedReceipt.scout.risks).toHaveLength(3);
  expect(guardedReceipt.scout.sources).toEqual(['demo_facts.json', 'demo brand brief']);
  const guardedScout = page.locator('section[aria-label="Scout facts and sources"]');
  await expect(guardedScout).toContainText(`Scout stage: ${scoutName}`);
  const guardedSourcedFacts = guardedScout.locator('h3:has-text("Sourced facts") + ul > li.scout-fact');
  await expect(guardedSourcedFacts).toHaveCount(5);
  await expect(guardedScout.locator('.scout-risk')).toHaveCount(3);
  await expect(guardedScout.getByText('Verified', { exact: true })).toHaveCount(5);
  for (const claim of ['100% vegan PU leather', 'Designed in Texas', '$49', 'Vegan leather wallet', 'For Austin commuters']) {
    await expect(guardedSourcedFacts.getByText(claim, { exact: true })).toBeVisible();
  }
  await expect(guardedScout.getByText('Demo risk, unverified').first()).toBeVisible();
  await expect(guardedScout).toContainText('No external research was run');
  await expect(guardedScout).toContainText('deterministic fallback');
  await page.screenshot({ path: `${local}/05-guarded.png`, fullPage: true });

  // Replay proves the stage binding difference, not only the verdict.
  await showAdvanced(page);
  await page.getByRole('button', { name: 'Replay', exact: false }).click();
  await page.getByLabel('Run A id').fill(runDefault);
  await page.getByLabel('Run B id').fill(runGuarded);
  await page.getByRole('button', { name: 'Compare', exact: true }).click();
  await expect(page.getByText(`Scout: ${scoutName} / ${scoutName}`)).toBeVisible();
  await expect(page.getByText(`Checker: Checker / ${checkerName}`)).toBeVisible();
  await expect(page.getByText('Stage bindings changed: true')).toBeVisible();
  await page.screenshot({ path: `${local}/06-replay.png`, fullPage: true });

  writeFileSync(
    `${local}/summary.json`,
    JSON.stringify(
      {
        scoutName,
        checkerName,
        runDefault,
        runGuarded,
        seeded_state: 'none, natural UI path only, supported price_claims policy',
        default_blocked: defaultReceipt.checker_v1.blocked_count,
        guarded_blocked: guardedReceipt.checker_v1.blocked_count,
        submit_attempted: false,
      },
      null,
      2,
    ),
  );
  const summary = JSON.parse(readFileSync(`${local}/summary.json`, 'utf8'));
  expect(summary.seeded_state).toContain('natural UI path only');
});
