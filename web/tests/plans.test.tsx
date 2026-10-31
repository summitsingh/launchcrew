import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { readFileSync } from 'node:fs';
import PlansPage from '../src/app/plans/page';
import { WaitlistForm } from '../src/components/waitlist-form';
import { ABOUT_MISSION, CHECKER_UNMETERED_NOTE, PLANS, demoVideoUrl, isValidWaitlistEmail, submitWaitlist } from '../src/lib/plans';

describe('plans catalog', () => {
  it('defines Free, Pro, and Team tiers with positioned audiences', () => {
    expect(PLANS.map(p => p.tier)).toEqual(['free', 'pro', 'team']);
    expect(PLANS.map(p => p.name)).toEqual(['Free', 'Pro', 'Team']);
    const byTier = Object.fromEntries(PLANS.map(p => [p.tier, p]));
    expect(byTier.free.audience).toMatch(/solo founder/i);
    expect(byTier.pro.audience).toMatch(/growing brand/i);
    expect(byTier.team.audience).toMatch(/multi-seat|collaboration/i);
    for (const plan of PLANS) {
      expect(plan.features.length).toBeGreaterThan(0);
      expect(plan.price.trim().length).toBeGreaterThan(0);
    }
  });

  it('keeps the checking path unmetered with no credit meter language', () => {
    expect(CHECKER_UNMETERED_NOTE).toMatch(/unmetered/i);
    expect(CHECKER_UNMETERED_NOTE).not.toMatch(/credit/i);
    const catalog = JSON.stringify(PLANS);
    expect(catalog).not.toMatch(/credit/i);
    expect(catalog).toMatch(/unmetered/i);
  });

  it('renders all three tiers plus the unmetered checker note', () => {
    const html = renderToStaticMarkup(<PlansPage />);
    for (const name of ['Free', 'Pro', 'Team']) {
      expect(html).toContain(name);
    }
    expect(html).toContain('Checker safety verification stays unmetered');
    expect(html).not.toMatch(/credit/i);
  });

  it('renders the about section with the launch copilot mission', () => {
    const html = renderToStaticMarkup(<PlansPage />);
    expect(html).toContain('About LaunchCrew');
    expect(html).toContain('deterministic');
    expect(html).toContain('fact-grounded');
    expect(ABOUT_MISSION).toMatch(/e-commerce|founders/i);
    expect(ABOUT_MISSION).toMatch(/hallucination/i);
    expect(ABOUT_MISSION).toMatch(/policy compliance/i);
  });
});

describe('demo video slot', () => {
  it('shows an honest placeholder when no video URL is configured', () => {
    delete process.env.NEXT_PUBLIC_DEMO_VIDEO_URL;
    expect(demoVideoUrl()).toBe('');
    const html = renderToStaticMarkup(<PlansPage />);
    expect(html).toContain('demo video link will appear here');
    expect(html).not.toContain('demo-link');
  });

  it('shows the video link only when a URL is configured', () => {
    process.env.NEXT_PUBLIC_DEMO_VIDEO_URL = 'https://example.com/demo';
    try {
      expect(demoVideoUrl()).toBe('https://example.com/demo');
      const html = renderToStaticMarkup(<PlansPage />);
      expect(html).toContain('demo-link');
      expect(html).toContain('https://example.com/demo');
    } finally {
      delete process.env.NEXT_PUBLIC_DEMO_VIDEO_URL;
    }
  });
});

describe('waitlist form', () => {
  it('renders email input, tier selection, and submit button', () => {
    const html = renderToStaticMarkup(<WaitlistForm />);
    expect(html).toContain('waitlist-email');
    expect(html).toContain('waitlist-tier');
    expect(html).toContain('Join the waitlist');
    for (const name of ['Free', 'Pro', 'Team']) {
      expect(html).toContain(name);
    }
  });

  it('validates email addresses', () => {
    expect(isValidWaitlistEmail('founder@example.com')).toBe(true);
    expect(isValidWaitlistEmail(' Founder@Example.com ')).toBe(true);
    for (const bad of ['', 'not-an-email', 'a@b', 'a @b.com', 'a@b@c.com']) {
      expect(isValidWaitlistEmail(bad)).toBe(false);
    }
  });

  it('submits valid signups and rejects invalid email without posting', async () => {
    let posted: unknown = null;
    const ok = await submitWaitlist(
      { email: ' founder@example.com ', interest: '', tier: 'pro' },
      async (url, body) => {
        posted = { url, body };
        return { status: 201, body: { email: 'founder@example.com' } };
      },
    );
    expect(ok).toEqual({ ok: true, duplicate: false, message: 'You are on the waitlist.' });
    expect(posted).toEqual({ url: '/api/waitlist', body: { email: 'founder@example.com', interest: 'general', tier: 'pro' } });

    let calls = 0;
    const invalid = await submitWaitlist(
      { email: 'not-an-email', interest: '', tier: 'free' },
      async () => {
        calls += 1;
        return { status: 201, body: {} };
      },
    );
    expect(invalid.ok).toBe(false);
    expect(invalid.message).toMatch(/valid email/i);
    expect(calls).toBe(0);
  });

  it('reports duplicates and failures honestly', async () => {
    const dup = await submitWaitlist(
      { email: 'repeat@example.com', interest: '', tier: 'team' },
      async () => ({ status: 200, body: { duplicate: true } }),
    );
    expect(dup).toEqual({ ok: true, duplicate: true, message: 'This email is already on the waitlist.' });

    const failed = await submitWaitlist(
      { email: 'new@example.com', interest: '', tier: 'free' },
      async () => ({ status: 500, body: { detail: 'boom' } }),
    );
    expect(failed.ok).toBe(false);

    const offline = await submitWaitlist(
      { email: 'new@example.com', interest: '', tier: 'free' },
      async () => {
        throw new Error('network down');
      },
    );
    expect(offline).toEqual({ ok: false, duplicate: false, message: 'Signup failed. Try again.' });
  });
});

describe('footer navigation', () => {
  it('links the plans page from the plans footer and the review desk', () => {
    const plansHtml = renderToStaticMarkup(<PlansPage />);
    expect(plansHtml).toContain('href="/plans"');
    expect(plansHtml).toContain('href="/"');
    const deskSource = readFileSync('src/app/page.tsx', 'utf8');
    expect(deskSource).toContain('href="/plans"');
  });
});
