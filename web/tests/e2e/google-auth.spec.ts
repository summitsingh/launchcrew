import { test, expect } from '@playwright/test';
import type { Page, Route } from '@playwright/test';

// Google-only auth UI, rendered through the Next.js desk with mocked auth
// status. No provider network, no real credentials, no live sign-in. All
// subjects are synthetic. Product queries are mocked to empty lists.
const SYN_USER = 'google:synthetic-browser-01';

async function mockEmptyProduct(page: Page): Promise<void> {
  await page.route('**/api/agents', (route: Route) => route.fulfill({ json: [] }));
  await page.route('**/api/queue', (route: Route) => route.fulfill({ json: [] }));
}

test('google-only sign-in link with no facebook link', async ({ page }) => {
  await page.route('**/api/auth/status', (route: Route) =>
    route.fulfill({ json: { enabled: true, user: '', live_verified: false, providers: ['google'] } }),
  );
  await mockEmptyProduct(page);
  await page.goto('/');
  const signin = page.getByTestId('auth-signin');
  await expect(signin).toBeVisible();
  await expect(signin.getByRole('link', { name: 'Google' })).toHaveAttribute('href', '/api/auth/google/login');
  await expect(page.locator('a[href*="facebook"]')).toHaveCount(0);
  await expect(page.getByText('Auth enabled, unverified')).toBeVisible();
});

test('setup required when google provider is missing', async ({ page }) => {
  await page.route('**/api/auth/status', (route: Route) =>
    route.fulfill({ json: { enabled: true, user: '', live_verified: false, providers: [] } }),
  );
  await mockEmptyProduct(page);
  await page.goto('/');
  await expect(page.getByTestId('auth-setup-required')).toContainText('Google provider setup is required');
  await expect(page.locator('a[href*="/api/auth/google/login"]')).toHaveCount(0);
  await expect(page.locator('a[href*="facebook"]')).toHaveCount(0);
});

test('sign-out clears actor view and returns to sign-in', async ({ page }) => {
  let signedIn = true;
  await page.route('**/api/auth/status', (route: Route) =>
    route.fulfill({
      json: signedIn
        ? { enabled: true, user: SYN_USER, live_verified: false, providers: ['google'] }
        : { enabled: true, user: '', live_verified: false, providers: ['google'] },
    }),
  );
  await mockEmptyProduct(page);
  await page.route('**/api/auth/logout', (route: Route) => {
    signedIn = false;
    return route.fulfill({ json: { signed_out: true } });
  });
  await page.goto('/');
  await expect(page.getByTestId('auth-signed-in')).toContainText(SYN_USER);
  await page.getByTestId('sign-out').click();
  await expect(page.getByTestId('auth-signin')).toBeVisible();
  await expect(page.getByTestId('auth-signed-in')).toHaveCount(0);
  await expect(page.getByText('Signed out.')).toBeVisible();
});

test('two synthetic actors never see each other draft, facts, or cache', async ({ page }) => {
  const ACTOR1 = 'google:synthetic-actor-01';
  const ACTOR2 = 'google:synthetic-actor-02';
  const DRAFT1 = 'Actor1 private brief alpha 01';
  const FACT1 = 'Actor1 private material 01';
  const AGENT1 = 'Maker-Actor1-01';
  const AGENT2 = 'Maker-Actor2-02';
  const DEFAULT_BRIEF = 'Vegan leather wallet, $49, for Austin commuters, launch on Instagram';
  let currentUser = ACTOR1;
  let authDelayMs = 0;
  await page.route('**/api/auth/status', async (route: Route) => {
    if (authDelayMs > 0) {
      await new Promise((resolve) => setTimeout(resolve, authDelayMs));
    }
    await route.fulfill({
      json: { enabled: true, user: currentUser, live_verified: false, providers: ['google'] },
    });
  });
  await page.route('**/api/agents', async (route: Route) => {
    const name = currentUser === ACTOR2 ? AGENT2 : AGENT1;
    await route.fulfill({
      json: [
        {
          name,
          role: 'maker',
          department: 'demo',
          personality: 'p',
          expertise: 'e',
          decision_rules: [],
          veto_scope: [],
          tools_allowed: [],
          examples: [],
        },
      ],
    });
  });
  await page.route('**/api/queue', async (route: Route) => route.fulfill({ json: [] }));
  await page.route('**/api/auth/logout', async (route: Route) => {
    currentUser = ACTOR2;
    authDelayMs = 400;
    await route.fulfill({ json: { signed_out: true } });
  });
  await page.goto('/');
  await expect(page.getByTestId('auth-signed-in')).toContainText(ACTOR1);
  const idea = page.locator('#idea');
  await expect(idea).toBeVisible();
  await idea.fill(DRAFT1);
  await page.locator('input[name="facts-mode"][value="owner"]').check();
  const material = page.locator('#owner-material');
  await expect(material).toBeVisible();
  await material.fill(FACT1);
  await expect(page.locator('#run-agent')).toContainText(AGENT1);
  await page.getByTestId('sign-out').click();
  await expect(idea).toHaveValue(DEFAULT_BRIEF, { timeout: 2000 });
  await expect(page.getByTestId('auth-signed-in')).toContainText(ACTOR2, { timeout: 5000 });
  await expect(idea).toHaveValue(DEFAULT_BRIEF);
  await expect(page.locator('#owner-material')).toHaveCount(0);
  await expect(page.locator('#run-agent')).toContainText(AGENT2);
  await expect(page.locator('#run-agent')).not.toContainText(AGENT1);
  await expect(page.getByText(DRAFT1)).toHaveCount(0);
  await expect(page.getByText(FACT1)).toHaveCount(0);
});

test('logout gates product UI until next actor is known', async ({ page }) => {
  let signedIn = true;
  await page.route('**/api/auth/status', (route: Route) =>
    route.fulfill({
      json: signedIn
        ? { enabled: true, user: SYN_USER, live_verified: false, providers: ['google'] }
        : { enabled: true, user: '', live_verified: false, providers: ['google'] },
    }),
  );
  await mockEmptyProduct(page);
  await page.route('**/api/auth/logout', (route: Route) => {
    signedIn = false;
    return route.fulfill({ json: { signed_out: true } });
  });
  await page.goto('/');
  await expect(page.locator('#idea')).toBeVisible();
  await page.locator('#idea').fill('Private draft before logout 01');
  await page.getByTestId('sign-out').click();
  await expect(page.getByTestId('auth-signin')).toBeVisible();
  await expect(page.locator('#idea')).toHaveCount(0);
  await expect(page.locator('#actor-workspace')).toHaveCount(0);
  await expect(page.getByText('Private draft before logout 01')).toHaveCount(0);
});

test('keyless default shows product UI without sign-in', async ({ page }) => {
  await page.route('**/api/auth/status', (route: Route) =>
    route.fulfill({ json: { enabled: false, user: '', live_verified: false, providers: [] } }),
  );
  await mockEmptyProduct(page);
  await page.goto('/');
  await expect(page.getByText('Demo mode')).toBeVisible();
  await expect(page.locator('#idea')).toBeVisible();
  await expect(page.locator('#actor-workspace')).toBeVisible();
  await expect(page.getByTestId('auth-signin')).toHaveCount(0);
  await expect(page.getByTestId('auth-setup-required')).toHaveCount(0);
});

test('auth status failure shows safe retry with no product queries or draft', async ({ page }) => {
  await page.route('**/api/auth/status', (route: Route) =>
    route.fulfill({ status: 500, json: { detail: 'synthetic status failure' } }),
  );
  let agentsCalls = 0;
  let queueCalls = 0;
  let memoryCalls = 0;
  await page.route('**/api/agents', (route: Route) => {
    agentsCalls += 1;
    return route.fulfill({ json: [] });
  });
  await page.route('**/api/queue', (route: Route) => {
    queueCalls += 1;
    return route.fulfill({ json: [] });
  });
  await page.route('**/api/memory', (route: Route) => {
    memoryCalls += 1;
    return route.fulfill({ json: [] });
  });
  await page.goto('/');
  const authError = page.getByTestId('auth-error');
  await expect(authError).toBeVisible();
  await expect(authError).toContainText('Sign-in check failed');
  await expect(page.getByTestId('auth-retry')).toBeVisible();
  await expect(page.getByText('Auth check failed')).toBeVisible();
  await expect(page.getByText('Demo mode')).toHaveCount(0);
  await expect(page.locator('#idea')).toHaveCount(0);
  await expect(page.locator('#actor-workspace')).toHaveCount(0);
  await expect(page.getByTestId('actor-workspace')).toHaveCount(0);
  await expect(page.getByTestId('auth-signin')).toHaveCount(0);
  await expect(page.getByTestId('auth-signed-in')).toHaveCount(0);
  await expect(page.getByTestId('auth-setup-required')).toHaveCount(0);
  await expect(page.getByTestId('auth-loading')).toHaveCount(0);
  await page.waitForTimeout(500);
  expect(agentsCalls).toBe(0);
  expect(queueCalls).toBe(0);
  expect(memoryCalls).toBe(0);
});

test('auth retry after failure loads keyless workspace without stale state', async ({ page }) => {
  let shouldFail = true;
  await page.route('**/api/auth/status', (route: Route) => {
    if (shouldFail) return route.fulfill({ status: 500, json: { detail: 'synthetic status failure' } });
    return route.fulfill({ json: { enabled: false, user: '', live_verified: false, providers: [] } });
  });
  let agentsCalls = 0;
  await page.route('**/api/agents', (route: Route) => {
    agentsCalls += 1;
    return route.fulfill({ json: [] });
  });
  await page.route('**/api/queue', (route: Route) => route.fulfill({ json: [] }));
  await page.goto('/');
  await expect(page.getByTestId('auth-error')).toBeVisible();
  await expect(page.locator('#idea')).toHaveCount(0);
  expect(agentsCalls).toBe(0);
  shouldFail = false;
  await page.getByTestId('auth-retry').click();
  await expect(page.getByText('Demo mode')).toBeVisible();
  await expect(page.locator('#idea')).toBeVisible();
  await expect(page.getByTestId('actor-workspace')).toBeVisible();
  await expect(page.getByTestId('auth-error')).toHaveCount(0);
  await expect(page.locator('#idea')).toHaveValue('Vegan leather wallet, $49, for Austin commuters, launch on Instagram');
  expect(agentsCalls).toBeGreaterThan(0);
});

test('actor A to B switch never shows A draft facts selection during B rendering', async ({ page }) => {
  const ACTOR1 = 'google:synthetic-frame-actor-01';
  const ACTOR2 = 'google:synthetic-frame-actor-02';
  const DRAFT1 = 'Frame actor1 private brief 01';
  const FACT1 = 'Frame actor1 private material 01';
  const AGENT1 = 'Maker-Frame1-01';
  const AGENT2 = 'Maker-Frame2-02';
  const DEFAULT_BRIEF = 'Vegan leather wallet, $49, for Austin commuters, launch on Instagram';
  let currentUser = ACTOR1;
  let authDelayMs = 0;
  await page.route('**/api/auth/status', async (route: Route) => {
    if (authDelayMs > 0) {
      await new Promise((resolve) => setTimeout(resolve, authDelayMs));
    }
    await route.fulfill({
      json: { enabled: true, user: currentUser, live_verified: false, providers: ['google'] },
    });
  });
  await page.route('**/api/agents', async (route: Route) => {
    const name = currentUser === ACTOR2 ? AGENT2 : AGENT1;
    await route.fulfill({
      json: [
        {
          name,
          role: 'maker',
          department: 'demo',
          personality: 'p',
          expertise: 'e',
          decision_rules: [],
          veto_scope: [],
          tools_allowed: [],
          examples: [],
        },
      ],
    });
  });
  await page.route('**/api/queue', async (route: Route) => route.fulfill({ json: [] }));
  await page.route('**/api/auth/logout', async (route: Route) => {
    currentUser = ACTOR2;
    authDelayMs = 400;
    await route.fulfill({ json: { signed_out: true } });
  });
  await page.goto('/');
  await expect(page.getByTestId('auth-signed-in')).toContainText(ACTOR1);
  const idea = page.locator('#idea');
  await expect(idea).toBeVisible();
  await idea.fill(DRAFT1);
  await page.locator('input[name="facts-mode"][value="owner"]').check();
  const material = page.locator('#owner-material');
  await expect(material).toBeVisible();
  await material.fill(FACT1);
  await expect(page.locator('#run-agent')).toContainText(AGENT1);
  await page.evaluate(() => {
    const store = window as unknown as {
      __actorFrames?: Array<{ idea: string; material: string; agent: string; auth: string; body: string }>;
    };
    store.__actorFrames = [];
    const sample = () => {
      const frames = store.__actorFrames;
      if (!frames || frames.length >= 500) return;
      const ideaEl = document.querySelector('#idea') as HTMLTextAreaElement | null;
      const materialEl = document.querySelector('#owner-material') as HTMLInputElement | null;
      const agentEl = document.querySelector('#run-agent');
      const authEl = document.querySelector('[data-testid="auth-signed-in"]');
      frames.push({
        idea: ideaEl ? ideaEl.value : '',
        material: materialEl ? materialEl.value : '',
        agent: agentEl ? agentEl.textContent || '' : '',
        auth: authEl ? authEl.textContent || '' : '',
        body: document.body ? document.body.innerText.slice(0, 4000) : '',
      });
      requestAnimationFrame(sample);
    };
    requestAnimationFrame(sample);
  });
  await page.getByTestId('sign-out').click();
  await expect(page.getByTestId('auth-signed-in')).toContainText(ACTOR2, { timeout: 5000 });
  await expect(idea).toHaveValue(DEFAULT_BRIEF);
  await expect(page.locator('#run-agent')).toContainText(AGENT2);
  await page.waitForTimeout(500);
  const frames = await page.evaluate(
    () =>
      (window as unknown as {
        __actorFrames?: Array<{ idea: string; material: string; agent: string; auth: string; body: string }>;
      }).__actorFrames || [],
  );
  const bFrames = frames.filter((frame) => frame.auth.includes(ACTOR2));
  expect(bFrames.length).toBeGreaterThan(0);
  for (const frame of bFrames) {
    expect(frame.idea).not.toContain(DRAFT1);
    expect(frame.material).not.toContain(FACT1);
    expect(frame.agent).not.toContain(AGENT1);
    expect(frame.body).not.toContain(DRAFT1);
    expect(frame.body).not.toContain(FACT1);
  }
  await expect(page.getByText(DRAFT1)).toHaveCount(0);
  await expect(page.getByText(FACT1)).toHaveCount(0);
  await expect(page.locator('#owner-material')).toHaveCount(0);
});
