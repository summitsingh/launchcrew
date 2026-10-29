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
