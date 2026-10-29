import { test, expect } from '@playwright/test';

// Google-only auth UI, rendered through the Next.js desk with mocked auth
// status. No provider network, no real credentials, no live sign-in. All
// subjects are synthetic. Product queries are mocked to empty lists.
const SYN_USER = 'google:synthetic-browser-01';

async function mockEmptyProduct(page) {
  await page.route('**/api/agents', (route) => route.fulfill({ json: [] }));
  await page.route('**/api/queue', (route) => route.fulfill({ json: [] }));
}

test('google-only sign-in link with no facebook link', async ({ page }) => {
  await page.route('**/api/auth/status', (route) =>
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
  await page.route('**/api/auth/status', (route) =>
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
  await page.route('**/api/auth/status', (route) =>
    route.fulfill({
      json: signedIn
        ? { enabled: true, user: SYN_USER, live_verified: false, providers: ['google'] }
        : { enabled: true, user: '', live_verified: false, providers: ['google'] },
    }),
  );
  await mockEmptyProduct(page);
  await page.route('**/api/auth/logout', (route) => {
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
