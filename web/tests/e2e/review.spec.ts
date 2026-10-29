import { test, expect, type Page } from '@playwright/test';
import { writeFileSync, readFileSync, mkdirSync } from 'node:fs';
import { resolve } from 'node:path';
const local = resolve('../.local');
mkdirSync(local, { recursive: true });
async function noOverflow(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
}
async function showAdvanced(page: Page) {
  const toggle = page.getByRole('button', { name: 'Advanced', exact: true });
  if ((await toggle.getAttribute('aria-expanded')) === 'false') await toggle.click();
}
for (const width of [375, 768, 1024, 1440]) {
  test.describe(`${width}px`, () => {
    const suffix = `${width}_${Date.now()}`;
    const agentName = `Wallet${suffix}`;
    test.beforeEach(async ({ page }) => { await page.setViewportSize({ width, height: 1000 }); await page.goto('/'); });
    test('agent builder', async ({ page }) => {
      await noOverflow(page);
      await page.screenshot({ path: `${local}/idea-${width}.png`, fullPage: true });
      await showAdvanced(page);
      await page.getByRole('button', { name: 'Agent builder', exact: false }).click();
      await page.getByRole('button', { name: 'New agent', exact: true }).click();
      await page.getByLabel('Name', { exact: true }).fill(agentName);
      await page.getByRole('button', { name: 'Save agent', exact: true }).click();
      await expect(page.getByRole('status')).toContainText(`Saved agent ${agentName}`);
      await page.getByLabel('Personality', { exact: true }).fill('Grounded demo editor');
      await page.getByRole('button', { name: 'Save agent', exact: true }).click();
      await expect(page.getByRole('button', { name: 'Save agent', exact: true })).toBeEnabled();
      await page.getByRole('button', { name: 'Dry-run preview', exact: true }).click();
      await expect(page.getByText('No writes · No model calls', { exact: true })).toBeVisible();
      await page.getByLabel('Clone with a new name').fill(agentName + 'Copy');
      await page.getByRole('button', { name: 'Clone agent', exact: true }).click();
      await expect(page.getByRole('status').first()).toContainText(`Cloned agent ${agentName}Copy`);
      await noOverflow(page);
      await page.screenshot({ path: `${local}/builder-${width}.png`, fullPage: true });
      writeFileSync(`${local}/agent-${width}.json`, JSON.stringify({ agentName }));
    });
    test('approval queue and wallet demo', async ({ page }) => {
      const { agentName: savedAgent } = JSON.parse(readFileSync(`${local}/agent-${width}.json`, 'utf8'));
      await page.getByLabel('Maker agent', { exact: true }).selectOption(savedAgent);
      await page.getByLabel('Include the unsupported claim demo').check();
      await page.getByRole('button', { name: 'Create draft', exact: true }).click();
      await expect(page.getByRole('heading', { name: 'Unsupported claims stopped.' })).toBeVisible();
      const firstCheck = page.locator('section.panel', { has: page.getByRole('heading', { name: 'Unsupported claims stopped.', exact: true }) });
      await expect(firstCheck.locator('.blocked').getByText('best in Texas', { exact: true })).toBeVisible();
      await expect(page.getByText('The revised draft uses only approved facts. Final blocked count: 0.')).toBeVisible();
      await noOverflow(page);
      await page.screenshot({ path: `${local}/run-${width}.png`, fullPage: true });
      const id = await page.locator('.section-row .run-id').innerText();
      await page.getByRole('button', { name: 'Go to approval queue', exact: true }).click();
      const card = page.locator(`[data-run-id="${id}"]`);
      await expect(card.getByText('Pending approval', { exact: true })).toBeVisible();
      await expect(card.getByRole('button', { name: 'Export pack', exact: true })).toHaveCount(0);
      await noOverflow(page);
      await page.screenshot({ path: `${local}/queue-${width}.png`, fullPage: true });
      await card.getByRole('button', { name: 'Approve for export', exact: true }).click();
      await expect(card.getByText('Approved for export', { exact: true })).toBeVisible();
      const downloadEvent = page.waitForEvent('download');
      await card.getByRole('button', { name: 'Export pack', exact: true }).click();
      const download = await downloadEvent;
      const target = `${local}/export-${width}.json`;
      await download.saveAs(target);
      const receipt = JSON.parse(readFileSync(target, 'utf8'));
      expect(receipt.run_id).toBe(id);
      expect(receipt.approval_state).toBe('approved_for_export');
      expect(receipt.approvals[0].approved_by).toBe('demo_placeholder');
      expect(receipt.summary.submit_attempted).toBe(false);
      writeFileSync(`${local}/demo-${width}.json`, JSON.stringify({ width, run_id: id, agent: savedAgent, before: 'pending_approval', after: receipt.approval_state, approval_by: receipt.approvals[0].approved_by, checker_v1_blocked: receipt.checker_v1.blocked_count, checker_v2_blocked: receipt.checker_v2.blocked_count, export: 'downloaded_json' }, null, 2));
    });
    test('receipt view', async ({ page }) => {
      const { run_id } = JSON.parse(readFileSync(`${local}/demo-${width}.json`, 'utf8'));
      await page.getByRole('navigation', { name: 'Workspace' }).getByRole('button', { name: 'Approval queue' }).click();
      await page.locator(`[data-run-id="${run_id}"]`).getByRole('button', { name: 'View receipt', exact: true }).click();
      await expect(page.getByRole('heading', { name: 'Receipt', exact: true })).toBeVisible();
      await expect(page.getByText('demo_placeholder', { exact: true })).toBeVisible();
      await page.getByText('Inspect complete receipt JSON', { exact: true }).click();
      await expect(page.locator('pre')).toContainText(run_id);
      await noOverflow(page);
      await page.screenshot({ path: `${local}/receipt-${width}.png`, fullPage: true });
    });
  });
}
