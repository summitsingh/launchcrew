import { expect, test, type Page, type Route } from '@playwright/test';
import { existsSync, mkdirSync } from 'node:fs';
import { homedir } from 'node:os';
import { join, resolve } from 'node:path';

// The pinned Playwright revision's browser was never downloaded on this
// machine; reuse the newer cached headless shell for shots only.
const cachedShell = join(homedir(), 'Library', 'Caches', 'ms-playwright',
  'chromium_headless_shell-1228', 'chrome-headless-shell-mac-arm64', 'chrome-headless-shell');
if (existsSync(cachedShell)) {
  test.use({ launchOptions: { executablePath: cachedShell } });
}

// Judges workspace walk: Launches, New launch, Review, Schedule, Settings.
// All /api traffic is mocked (mocked model transport): no sign-in, no writes
// to a real backend, no model calls. Screenshots land in test-results/demo.
const shots = resolve('./test-results/demo');
mkdirSync(shots, { recursive: true });

const RECEIPT = {
  run_id: 'run_demo1',
  idea: 'Summit Leather Co. launch: 100% vegan PU leather jackets, designed in Texas.',
  status: 'completed',
  approval_state: 'approved_for_export',
  revision: 2,
  approved_revision: 2,
  display: 'approved',
  approvals: [{ action: 'approve', approved_by: 'google:owner', revision: 2, timestamp: '2026-11-04T10:00:00+00:00' }],
  approval_binding: { digest: 'abcdef1234567890abcdef1234567890', version: 'v1' },
  checker_profile: 'standard',
  maker_draft_v2: {
    post: 'New drop: Classic Bomber in 100% vegan PU leather. Cheapest jackets anywhere. Designed in Texas.',
    email: 'The Classic Bomber is here. 100% vegan PU leather, designed in Texas. Shop on Amazon.',
  },
  human_draft: null,
  checker_v1: {
    blocked_count: 1,
    verified_count: 4,
    claim_results: [
      {
        claim: 'Cheapest jackets anywhere',
        verdict: 'unsupported',
        reason: 'superlative without evidence',
        evidence: 'Summit Leather Co. facts list products, not prices',
        source: 'owner',
        blocked: true,
        verified: false,
      },
      {
        claim: 'Designed in Texas',
        verdict: 'supported',
        reason: 'stated on summitleather.co',
        evidence: 'summitleather.co meta description',
        source: 'owner',
        blocked: false,
        verified: true,
      },
    ],
  },
  checker_v2: {
    blocked_count: 0,
    verified_count: 5,
    claim_results: [
      {
        claim: 'Designed in Texas',
        verdict: 'supported',
        reason: 'stated on summitleather.co',
        evidence: 'summitleather.co meta description',
        source: 'owner',
        blocked: false,
        verified: true,
      },
    ],
  },
  human_check: null,
  model_usage: {
    model_used: 'muse-spark-1.3',
    spark_calls: 3,
    mode: 'live',
    latency_ms: 742,
    data_mode: 'evidence',
    data_basis: 'confirmed',
    error_types: [],
  },
  scout: {
    facts_used: [
      { claim: '100% vegan PU leather jackets', source: 'summitleather.co' },
      { claim: 'Designed in Texas', source: 'summitleather.co' },
    ],
  },
  audit: {
    event_log: [
      { action: 'run_accepted', at: '2026-11-04T09:58:00+00:00' },
      { action: 'run_approved', at: '2026-11-04T10:00:00+00:00' },
    ],
  },
  export_history: [],
  brand_kit: {
    version: 'v1',
    digest: 'brandkit1234567890',
    brand_colors: ['#1a1a1a', '#f5f0e8'],
    fonts: ['Inter'],
    banned_rules: ['no superlatives'],
  },
};

const STEPS = {
  run_id: 'run_demo1',
  worker_live: false,
  steps: [
    { seq: 1, stage: 'accepted', state: 'completed', observed_at: '2026-11-04T09:58:00+00:00', profile: 'deterministic', evidence: { idea_chars: 92 } },
    { seq: 2, stage: 'deterministic_checks', state: 'completed', observed_at: '2026-11-04T09:58:01+00:00', profile: 'deterministic', evidence: { facts: 7 } },
    { seq: 3, stage: 'scout', state: 'completed', observed_at: '2026-11-04T09:58:05+00:00', profile: 'muse-spark-1.3', evidence: { facts_used: 7, risks: 1 } },
    { seq: 4, stage: 'maker_draft_v1', state: 'completed', observed_at: '2026-11-04T09:58:20+00:00', profile: 'muse-spark-1.3', evidence: { claims: 6 } },
    { seq: 5, stage: 'checker_v1', state: 'completed', observed_at: '2026-11-04T09:58:25+00:00', profile: 'deterministic', evidence: { blocked_count: 1, verified_count: 4 } },
    { seq: 6, stage: 'maker_draft_v2', state: 'completed', observed_at: '2026-11-04T09:58:35+00:00', profile: 'muse-spark-1.3', evidence: { claims: 5 } },
    { seq: 7, stage: 'checker_v2', state: 'completed', observed_at: '2026-11-04T09:58:40+00:00', profile: 'deterministic', evidence: { blocked_count: 0, verified_count: 5 } },
    { seq: 8, stage: 'receipt', state: 'completed', observed_at: '2026-11-04T09:58:41+00:00', profile: 'deterministic', evidence: { stored: true, blocked_count: 0 } },
  ],
};

const QUEUE = [RECEIPT];

const SLOTS = [
  {
    id: 'slot_demo1',
    slot_date: '2026-11-10',
    slot_type: 'feed_post',
    pillar: 'product',
    format: 'feed_post',
    status: 'scheduled',
    run_id: 'run_demo1',
    selected_channels: ['instagram'],
    approved_channels: ['instagram'],
    schedule_state: 'ready',
  },
];

const DELIVERIES = [
  {
    id: 'del_demo1',
    slot_id: 'slot_demo1',
    channel: 'instagram',
    delivery_state: 'verified',
    live_url: 'https://example.com/posts/summit-bomber',
    match_kind: 'exact',
    differing_field: null,
    failure_reason: null,
    simulated: false,
    attempts: [{ attempt_number: 1, state: 'verified', match_kind: 'exact', source: 'fetched' }],
  },
];

const READY = {
  ready_eligible: true,
  failing_conditions: [],
  checks: { pack_approved: true, format_ok: true, channels_approved: true },
  details: [],
  unapproved_channels: [],
};

async function mockApi(page: Page) {
  await page.route('**/api/**', async (route: Route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    const method = route.request().method();
    const json = (body: unknown, status = 200) =>
      route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
    if (path === '/api/auth/status') return json({ enabled: true, user: null, live_verified: false, providers: ['google'] });
    if (path === '/api/queue') return json(QUEUE);
    if (path === '/api/calendar/slots' && method === 'GET') return json(SLOTS);
    if (path === '/api/runs/async' && method === 'POST') return json({ run_id: 'run_demo1' }, 202);
    if (path === '/api/runs/run_demo1/steps') return json(STEPS);
    if (path === '/api/runs/run_demo1' || path === '/api/runs/run_demo1/receipt') return json(RECEIPT);
    if (path === '/api/agents') return json([{ name: 'Scout' }, { name: 'Maker' }, { name: 'Checker' }]);
    if (path === '/api/formats') return json([{ title: 'Launch post', format_kind: 'launch_post' }]);
    if (path === '/api/trends/presets') return json([]);
    if (path === '/api/quickstart-templates') return json([]);
    if (path === '/api/channel-capabilities')
      return json([{ channel: 'instagram', caption_limit: 2200 }]);
    if (path === '/api/social/connections')
      return json([
        { platform: 'instagram', account_handle: '@summitleather.co', status: 'connected', token_present: true, token_security: 'encrypted' },
        { platform: 'x', status: 'disconnected', token_present: false },
      ]);
    if (path === '/api/calendar/slots/slot_demo1/validate-ready') return json(READY);
    if (path === '/api/calendar/slots/slot_demo1/deliveries') return json(DELIVERIES);
    return json({ detail: 'not mocked' }, 404);
  });
}

async function expectNoErrors(page: Page, errors: string[]) {
  expect(errors, `console errors: ${errors.join(' | ')}`).toEqual([]);
}

async function checkNoOverflow(page: Page, widths: number[]) {
  for (const width of widths) {
    await page.setViewportSize({ width, height: 900 });
    await page.waitForTimeout(300);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow, `horizontal overflow at ${width}px`).toBeLessThanOrEqual(1);
  }
}

test('judges workspace walks five screens without console errors', async ({ page, browserName }) => {
  test.skip(browserName !== 'chromium', 'screenshots target chromium');
  test.setTimeout(120_000);
  const errors: string[] = [];
  page.on('console', message => {
    if (message.type() === 'error') errors.push(message.text());
  });
  page.on('pageerror', error => errors.push(String(error)));
  await mockApi(page);

  // 1. Launches
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/meta-ai-hackathon-demo');
  await expect(page.getByRole('heading', { name: 'Launches' })).toBeVisible();
  await expect(page.getByTestId('demo-launches-table')).toBeVisible();
  await expect(page.getByTestId('demo-launch-run_demo1').getByTestId('demo-status')).toContainText('Approved');
  await page.screenshot({ path: join(shots, 'judges-launches-1440.png') });

  // 2. New launch wizard, three steps
  await page.locator('main').getByRole('link', { name: 'New launch' }).click();
  await expect(page.getByRole('heading', { name: 'New launch' })).toBeVisible();
  await expect(page.getByTestId('demo-idea')).toContainText('Summit Leather Co.');
  await page.getByTestId('demo-step-next').click();
  await expect(page.getByText('Confirm facts')).toBeVisible();
  await page.screenshot({ path: join(shots, 'judges-new-launch-facts-1440.png') });
  await page.getByTestId('demo-step-next').click();
  await expect(page.getByText('Generate', { exact: true })).toBeVisible();

  // 3. Generate with mocked transport, then open review
  await page.getByTestId('demo-generate').click();
  await expect(page.getByTestId('demo-open-review')).toBeVisible({ timeout: 30_000 });
  await page.getByTestId('demo-open-review').click();
  await expect(page.getByRole('heading', { name: 'Review' })).toBeVisible();
  await expect(page.getByTestId('demo-post-draft')).toContainText('Classic Bomber');
  await page.screenshot({ path: join(shots, 'judges-review-draft-1440.png') });

  // Checks tab
  await page.getByRole('tab', { name: 'Checks' }).click();
  await expect(page.getByTestId('demo-checks-list')).toContainText('Blocked');
  await expect(page.getByTestId('demo-checks-list')).toContainText('Backed by a fact');
  await page.screenshot({ path: join(shots, 'judges-review-checks-1440.png') });

  // Receipt tab
  await page.getByRole('tab', { name: 'Receipt' }).click();
  await expect(page.getByTestId('demo-receipt-card')).toContainText('muse-spark-1.3');
  await page.screenshot({ path: join(shots, 'judges-review-receipt-1440.png') });

  // 4. Schedule
  await page.goto('/meta-ai-hackathon-demo/schedule');
  await expect(page.getByRole('heading', { name: 'Schedule' })).toBeVisible();
  await expect(page.getByTestId('demo-slot-slot_demo1')).toBeVisible();
  await page.screenshot({ path: join(shots, 'judges-schedule-1440.png') });

  // 5. Settings
  await page.goto('/meta-ai-hackathon-demo/settings');
  await expect(page.getByRole('heading', { name: 'Settings' })).toBeVisible();
  await expect(page.getByTestId('demo-connection-instagram')).toBeVisible();
  await page.getByTestId('demo-unconnected-toggle').click();
  await page.screenshot({ path: join(shots, 'judges-settings-1440.png') });

  // Narrow viewport pass
  await page.setViewportSize({ width: 375, height: 900 });
  await page.goto('/meta-ai-hackathon-demo');
  await expect(page.getByTestId('demo-launches-table')).toBeVisible();
  await page.screenshot({ path: join(shots, 'judges-launches-375.png') });
  await page.goto('/meta-ai-hackathon-demo/review/run_demo1');
  await expect(page.getByRole('heading', { name: 'Review' })).toBeVisible();
  await page.screenshot({ path: join(shots, 'judges-review-375.png') });

  // Overflow sweep on Launches and Review
  await page.goto('/meta-ai-hackathon-demo');
  await checkNoOverflow(page, [1440, 1024, 768, 375]);
  await page.goto('/meta-ai-hackathon-demo/review/run_demo1');
  await checkNoOverflow(page, [1440, 1024, 768, 375]);

  await expectNoErrors(page, errors);
});
