import { describe, it, expect } from 'vitest';
import { readFileSync, existsSync, statSync } from 'node:fs';

describe('site files (sitemap, favicon, demo facts)', () => {
  it('ships a valid sitemap listing / and /plans', () => {
    const xml = readFileSync('public/sitemap.xml', 'utf8');
    expect(xml).toContain('<urlset');
    expect(xml).toContain('http://www.sitemaps.org/schemas/sitemap/0.9');
    expect(xml).toContain('<loc>https://launchcrew.summitsingh.com/</loc>');
    expect(xml).toContain('<loc>https://launchcrew.summitsingh.com/plans</loc>');
    expect(xml).not.toContain(String.fromCharCode(8212));
  });

  it('links both favicon assets in layout metadata', () => {
    const layout = readFileSync('src/app/layout.tsx', 'utf8');
    expect(layout).toContain('/favicon.ico');
    expect(layout).toContain('/favicon.svg');
    expect(readFileSync('public/favicon.svg', 'utf8')).toContain('<svg');
  });

  it('ships a non-empty favicon.ico', () => {
    expect(existsSync('public/favicon.ico')).toBe(true);
    expect(statSync('public/favicon.ico').size).toBeGreaterThan(0);
  });

  it('publishes demo facts at /facts/demo_facts.json matching the repo facts', () => {
    const published = readFileSync('public/facts/demo_facts.json', 'utf8');
    const source = readFileSync('../facts/demo_facts.json', 'utf8');
    expect(published).toEqual(source);
    const parsed = JSON.parse(published);
    expect(parsed).toHaveProperty('approved_claims');
    expect(Array.isArray(parsed.approved_claims)).toBe(true);
  });
});
