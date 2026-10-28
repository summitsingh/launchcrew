import { defineConfig } from '@playwright/test';
export default defineConfig({ testDir: './tests/e2e', fullyParallel: false, workers: 1, retries: 0, reporter: [['list'], ['json', { outputFile: '../.local/playwright-results.json' }]], use: { baseURL: process.env.WEB_URL || 'http://127.0.0.1:3000', headless: true, browserName: 'chromium', trace: 'retain-on-failure' }, outputDir: 'test-results' });
