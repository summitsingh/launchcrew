import { test, expect } from '@playwright/test';
import { existsSync, mkdirSync } from 'node:fs';
import { homedir } from 'node:os';
import { join, resolve } from 'node:path';

// Phase D demo shots: static public pages plus the desk shell, with a
// console-error gate. No sign-in, no writes, no model calls.
const shots = resolve('../.local/demo-shots');
mkdirSync(shots, { recursive: true });

// The pinned Playwright revision's browser was never downloaded on this
// machine; reuse the newer cached headless shell for shots only.
const cachedShell = join(homedir(), 'Library', 'Caches', 'ms-playwright',
  'chromium_headless_shell-1228', 'chrome-headless-shell-mac-arm64', 'chrome-headless-shell');
if (existsSync(cachedShell)) {
  test.use({ launchOptions: { executablePath: cachedShell } });
}

const PAGES = ['/', '/plans', '/demo', '/privacy', '/terms'] as const;

for (const path of PAGES) {
  test(`demo shot ${path} renders without console errors`, async ({ page }) => {
    test.setTimeout(60_000);
    const errors: string[] = [];
    page.on('console', message => {
      if (message.type() === 'error') errors.push(message.text());
    });
    page.on('pageerror', error => {
      errors.push(String(error));
    });
    await page.setViewportSize({ width: 1280, height: 900 });
    const response = await page.goto(path);
    expect(response?.status()).toBe(200);
    const name = path === '/' ? 'home' : path.slice(1);
    await page.screenshot({ path: `${shots}/${name}.png`, fullPage: true });
    expect(errors).toEqual([]);
  });
}
