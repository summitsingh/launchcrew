import { describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import {
  ChannelVariantsBundleView,
  LandingPageParitySection,
  SUPPORTED_CHECKER_POLICIES,
} from '../src/components/v2-views';
import type { components } from '../src/lib/schema';

type Bundle = components['schemas']['ChannelVariantsOut'];
type Variant = components['schemas']['ChannelVariantOut'];

function variant(overrides: Record<string, unknown> = {}): Variant {
  return {
    channel: 'x',
    variant_kind: 'presentation_candidate',
    text: 'Vegan leather wallet, $49.',
    subject: '',
    content_valid: true,
    exportable: false,
    independently_exportable: false,
    requires_checker_binding: true,
    status: 'candidate_pending_checker',
    reason: '',
    trim_note: '',
    char_count: 27,
    kept_sentences: 1,
    total_sentences: 1,
    omitted_sentences: 0,
    approval_note: 'Presentation candidate only.',
    ...overrides,
  } as Variant;
}

function sevenChannelBundle(): Bundle {
  return {
    bundle_version: 'checked-launch-matrix/v1',
    receipt_id: 'run_demo',
    revision: 0,
    approval_state: 'approved_for_export',
    binding_version: 'approval-binding/v1',
    binding_digest: 'b'.repeat(64),
    channel_approvals: {},
    facts_mode: 'demo_template',
    facts_label: 'Bundled fictional demo template',
    template_used: true,
    confirmed_claims_count: 5,
    draft_source: 'current post draft',
    all_content_valid: true,
    no_auto_publish: true,
    note: 'Checked export candidates only.',
    provenance: {},
    x: variant({ channel: 'x', ad_policy_passed: true, ad_policy_hits: [] }),
    linkedin: variant({ channel: 'linkedin' }),
    instagram: variant({ channel: 'instagram' }),
    email: variant({ channel: 'email' }),
    facebook: variant({ channel: 'facebook' }),
    tiktok: variant({ channel: 'tiktok' }),
    shopify: variant({ channel: 'shopify' }),
  } as unknown as Bundle;
}

const handlers = () => ({ onApprove: vi.fn(), onCopy: vi.fn() });

describe('Community launch matrix views', () => {
  it('renders all seven channel cards including TikTok and Shopify', () => {
    const html = renderToStaticMarkup(
      <ChannelVariantsBundleView bundle={sevenChannelBundle()} copied={null} locked={false} {...handlers()} />
    );
    for (const label of ['X', 'LinkedIn', 'Instagram', 'Email', 'Facebook', 'TikTok / Reels Script', 'Shopify PDP']) {
      expect(html).toContain(`${label} variant`);
    }
  });

  it('shows the Ad Shield compliant badge when the lint passes', () => {
    const html = renderToStaticMarkup(
      <ChannelVariantsBundleView bundle={sevenChannelBundle()} copied={null} locked={false} {...handlers()} />
    );
    expect(html).toContain('Ad Shield: Compliant');
  });

  it('shows Ad Policy violations with category, match, and reason', () => {
    const base = sevenChannelBundle();
    const flagged = {
      ...base,
      x: variant({
        channel: 'x',
        ad_policy_passed: false,
        ad_policy_hits: [{ category: 'absolute_claim', match: 'guaranteed', reason: 'Absolute promise: guaranteed.' }],
      }),
    } as Bundle;
    const html = renderToStaticMarkup(
      <ChannelVariantsBundleView bundle={flagged} copied={null} locked={false} {...handlers()} />
    );
    expect(html).toContain('Ad Policy: 1 violation');
    expect(html).toContain('absolute_claim');
    expect(html).toContain('guaranteed');
    expect(html).toContain('Absolute promise: guaranteed.');
  });

  it('lists the cliches checker policy with its exact veto and rule', () => {
    const entry = SUPPORTED_CHECKER_POLICIES.find(policy => policy.veto === 'cliches');
    expect(entry).toBeDefined();
    expect(entry?.rule).toBe('Block marketing cliches');
  });

  it('renders the landing page parity form with URL and HTML inputs', () => {
    const html = renderToStaticMarkup(
      <QueryClientProvider client={new QueryClient()}>
        <LandingPageParitySection runId="run_demo" />
      </QueryClientProvider>
    );
    expect(html).toContain('Landing page offer parity');
    expect(html).toContain('landing-url-run_demo');
    expect(html).toContain('landing-html-run_demo');
    expect(html).toContain('Audit landing page');
    expect(html).toContain('Privacy Policy');
  });
});
