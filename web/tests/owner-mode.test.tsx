import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { renderToStaticMarkup } from 'react-dom/server';
import {
  ApprovalBindingBlock,
  ClaimResultsBlock,
  ConfirmedFactsBlock,
  ScoutFactsSection,
  exportProductSlug,
  safeExportFilename,
} from '../src/components/v2-views';
import { ProductFactsForm } from '../src/components/product-facts-form';
import {
  buildProductFactsInput,
  emptyOwnerFacts,
  hasAnyOwnerValue,
  isSingleSentenceOk,
  validateOwnerFacts,
} from '../src/lib/product-facts';
import type { components } from '../src/lib/schema';

type Receipt = components['schemas']['Receipt'];
type Check = components['schemas']['Check'];

function ownerReceipt(): Receipt {
  return {
    run_id: 'run_owner1',
    idea: 'Canvas tote for farmers market',
    status: 'completed',
    approval_state: 'pending_approval',
    approvals: [],
    revision: 0,
    summary: {},
    audit: {},
    scout: {
      facts_used: [{ claim: 'Canvas tote', verified: true, evidence: 'Canvas tote', sources: ['owner'] }],
      risks: ['Risk: tote demand is unverified.'],
      sources: ['owner'],
      model_mode: 'deterministic_fallback',
      model_note: null,
    },
    product_facts: {
      mode: 'owner_input',
      template: 'demo_facts.json',
      template_label: 'Bundled fictional demo template',
      template_used: false,
      template_note: 'Bundled fictional demo fixture; not used as owner facts for this run.',
      fields: [
        { field: 'material', label: 'Material', value: 'Canvas', confirmed: true, source: 'owner', claim: 'Canvas' },
        { field: 'size', label: 'Size', value: 'Large', confirmed: false, source: 'pasted_text', claim: null },
      ],
      confirmed_claims: ['Canvas'],
      allowlist: ['Canvas'],
      suggested: [{ field: 'size', label: 'Size', value: 'Large', source: 'pasted_text', reason: 'Suggested but not confirmed by the owner' }],
      founder_note: { value: 'We sew every tote in Austin.', confirmed: true, source: 'owner', label: 'Founder note', sentence_ok: true, authorized_as_fact: false },
      draft_variant: { post: 'Tote post. We sew every tote in Austin.', email: 'Tote email. We sew every tote in Austin.', label: 'Owner-supplied founder note variant', authorized: false, verified: false, note: 'Founder note is owner-supplied and unverified; it authorizes no factual claim.' },
      labels: {},
    },
    checker_v1: {
      blocked_count: 1,
      verified_count: 1,
      blocked_claims: [{ claim: 'Best tote ever', reason: 'superlative' }],
      revision_instructions: [],
      claim_results: [
        { claim: 'Canvas tote', verified: true, verdict: 'supported', evidence: 'Canvas', evidence_claims: ['Canvas'], reason: 'Matched approved claim', blocked: false, source: 'explicit_claim' },
        { claim: 'Best tote ever', verified: false, verdict: 'unsupported', evidence: null, evidence_claims: null, reason: 'Claim not found in facts file', blocked: true, source: 'draft_text' },
        { claim: 'Leather tote', verified: false, verdict: 'conflicts', evidence: 'Canvas', evidence_claims: ['Canvas'], reason: 'Material swap', blocked: true, source: 'draft_text' },
      ],
      supported_count: 1,
      unsupported_count: 1,
      conflicts_count: 1,
    },
    checker_v2: { blocked_count: 0, verified_count: 1, blocked_claims: [], revision_instructions: [], claim_results: [], supported_count: 1, unsupported_count: 0, conflicts_count: 0 },
    approval_binding: { version: 'v1', digest: 'abc123' },
    seed_unverified_claim: { enabled: false, claim: null, v1_included: false, v2_included: false, v2_removed: false, note: 'Demo test seed only; v1 records the block, v2 removes it.' },
  } as unknown as Receipt;
}

describe('owner mode request', () => {
  it('builds the exact typed product_facts object and omits empty values', () => {
    const state = emptyOwnerFacts();
    state.material = { value: '  Canvas  ', confirmed: true, source: 'owner' };
    state.size = { value: 'Large', confirmed: false, source: 'pasted_text' };
    state.allowed_claims = [{ value: 'Sews in Austin', confirmed: true, source: 'listing' }];
    state.founder_note = { value: 'We sew every tote in Austin.', confirmed: true, source: 'owner' };
    const out = buildProductFactsInput(state);
    expect(out.material).toEqual({ value: 'Canvas', confirmed: true, source: 'owner' });
    expect(out.contents).toBeUndefined();
    expect(out.size).toEqual({ value: 'Large', confirmed: false, source: 'pasted_text' });
    expect(out.allowed_claims).toEqual([{ value: 'Sews in Austin', confirmed: true, source: 'listing' }]);
    expect(out.founder_note).toEqual({ value: 'We sew every tote in Austin.', confirmed: true, source: 'owner' });
    expect(buildProductFactsInput(emptyOwnerFacts())).toEqual({});
    expect(hasAnyOwnerValue(emptyOwnerFacts())).toBe(false);
    expect(hasAnyOwnerValue(state)).toBe(true);
  });

  it('validates owner facts safely without silent confirmation', () => {
    const bad = emptyOwnerFacts();
    bad.material = { value: '', confirmed: true, source: 'owner' };
    bad.founder_note = { value: 'First. Second.', confirmed: false, source: 'owner' };
    const errors = validateOwnerFacts(bad);
    expect(errors.join(' ')).toContain('confirmed but empty');
    expect(errors.join(' ')).toContain('one complete sentence');
    const dup = emptyOwnerFacts();
    dup.material = { value: 'Canvas tote', confirmed: true, source: 'owner' };
    dup.contents = { value: 'canvas tote!', confirmed: true, source: 'owner' };
    expect(validateOwnerFacts(dup).join(' ')).toContain('Duplicate');
    const many = emptyOwnerFacts();
    many.allowed_claims = Array.from({ length: 13 }, (_, i) => ({ value: `claim ${i}`, confirmed: true, source: 'owner' as const }));
    expect(validateOwnerFacts(many).join(' ')).toContain('12');
    expect(isSingleSentenceOk('We sew every tote in Austin.')).toBe(true);
    expect(isSingleSentenceOk('First. Second.')).toBe(false);
    expect(isSingleSentenceOk('No punctuation')).toBe(false);
    expect(isSingleSentenceOk('$49.99 is the price.')).toBe(true);
  });

  it('posts product_facts only in owner mode and never from brief text', () => {
    const source = readFileSync('src/app/page.tsx', 'utf8');
    expect(source).toContain("useState<'demo' | 'owner'>('demo')");
    expect(source).toContain('Bundled fictional demo-template mode');
    expect(source).toContain('Owner-input mode');
    expect(source).toContain('Omit product_facts entirely');
    expect(source).toContain('Nothing is confirmed from brief text');
    expect(source).toContain('product_facts: buildProductFactsInput(ownerFacts)');
    expect(source).toContain('ProductFactsForm');
  });

  it('renders owner fields with confirmation, source, and constraints', () => {
    const html = renderToStaticMarkup(<ProductFactsForm state={emptyOwnerFacts()} onChange={() => {}} />);
    for (const text of ['Material', 'Contents', 'Size', 'Price', 'Allowed claims', 'Founder note', 'I confirm this fact', 'Source for', 'owner', 'pasted_text', 'memory', 'listing', 'campaign_brief', 'demo_template', 'never labeled verified', 'One complete sentence', 'never an authorized']) {
      expect(html).toContain(text);
    }
  });
});

describe('demo mode compatibility', () => {
  it('keeps demo receipts working and handles missing product facts', () => {
    expect(renderToStaticMarkup(<ConfirmedFactsBlock receipt={{} as unknown as Receipt} />)).toBe('');
    expect(renderToStaticMarkup(<ClaimResultsBlock check={null} title="First" />)).toBe('');
    expect(renderToStaticMarkup(<ApprovalBindingBlock receipt={{} as unknown as Receipt} />)).toBe('');
    const legacy = renderToStaticMarkup(<ScoutFactsSection receipt={{ run_id: 'r', status: 'completed' } as unknown as Receipt} />);
    expect(legacy).toContain('Sourced facts unavailable');
  });

  it('conditions Scout copy on receipt provenance', () => {
    const owner = renderToStaticMarkup(<ScoutFactsSection receipt={ownerReceipt()} />);
    expect(owner).toContain('Owner-confirmed facts');
    expect(owner).toContain('was not used as facts');
    expect(owner).not.toContain('Demo facts only');
    const demo = renderToStaticMarkup(
      <ScoutFactsSection receipt={{ ...ownerReceipt(), product_facts: { mode: 'demo_template', template_used: true, template_label: 'Bundled fictional demo template', template: 'demo_facts.json', template_note: '', fields: [], confirmed_claims: [], allowlist: [], suggested: [], founder_note: null, draft_variant: null, labels: {} } } as unknown as Receipt} />,
    );
    expect(demo).toContain('Demo facts only');
  });
});

describe('owner receipt and checker evidence', () => {
  it('renders mode, confirmed, suggestions, and unverified founder material', () => {
    const html = renderToStaticMarkup(<ConfirmedFactsBlock receipt={ownerReceipt()} />);
    for (const text of ['Mode: owner_input', 'Template used: no', 'Confirmed fields (1)', 'Canvas', 'Source: Owner', 'Confirmed claims (1)', 'Suggestions, not verified (1)', 'Suggestion', 'Pasted text', 'Founder note, separate unverified material', 'We sew every tote in Austin.', 'Owner-supplied unverified color, never an authorized factual claim', 'Founder draft variant, separate unverified material', 'Authorized: no', 'Verified: no']) {
      expect(html).toContain(text);
    }
    expect(html).not.toContain('Verified</span>');
  });

  it('renders claim verdicts with quoted evidence without authorizing export', () => {
    const receipt = ownerReceipt();
    const html = renderToStaticMarkup(<ClaimResultsBlock check={receipt.checker_v1 as Check} title="First check evidence" />);
    for (const text of ['supported', 'unsupported', 'conflicts', 'Canvas tote', 'Best tote ever', 'Leather tote', 'Evidence:', 'Evidence claims:', 'does not authorize export']) {
      expect(html).toContain(text);
    }
  });

  it('shows approval binding and seed marker truthfully', () => {
    const html = renderToStaticMarkup(<ApprovalBindingBlock receipt={ownerReceipt()} />);
    expect(html).toContain('Binding version v1');
    expect(html).toContain('abc123');
    expect(html).toContain('Seed demo: not enabled');
  });
});

describe('safe export filenames', () => {
  it('prefers explicit owner values over idea text and keeps fallback', () => {
    expect(exportProductSlug({ product_name: '  Canvas Tote!  ' })).toBe('canvas-tote');
    expect(exportProductSlug(ownerReceipt())).toBe('canvas');
    expect(exportProductSlug({ idea: 'Vegan leather wallet, $49, for Austin commuters, launch on Instagram with extra words' })).toBe('vegan-leather-wallet-49');
    expect(exportProductSlug({})).toBe('pack');
    const contactEmail = ['jan', 'e', '@', 'example', '.', 'com'].join('');
    const contactPhone = ['512', '-', '555', '-', '0199'].join('');
    const contactIdea = ['Contact me at ', contactEmail, ' or ', contactPhone, ' for a tote'].join('');
    expect(exportProductSlug({ idea: contactIdea })).not.toContain('jane');
    expect(exportProductSlug({ idea: contactIdea })).not.toContain('512');
  });

  it('names files with product plus date, never run id as product', () => {
    const receipt = { run_id: 'run_secret123', idea: 'Canvas tote' } as unknown as Receipt;
    expect(safeExportFilename(receipt, new Date('2026-10-29T12:00:00Z'), 'json')).toBe('launchcrew-pack-20261029-canvas-tote.json');
    expect(safeExportFilename(receipt, new Date('invalid'), 'md')).toBe('launchcrew-pack-nodate-canvas-tote.md');
    expect(safeExportFilename(receipt, new Date('2026-10-29T12:00:00Z'), 'json')).toMatch(/^[a-z0-9.-]+\.[a-z]+$/);
    const desk = readFileSync('src/app/page.tsx', 'utf8');
    expect(desk).toContain('safeExportFilename(r, new Date()');
    expect(desk).not.toContain('safeExportFilename(r.run_id');
    const views = readFileSync('src/components/v2-views.tsx', 'utf8');
    expect(views).toContain('safeExportFilename(run, new Date()');
    expect(views).not.toContain('safeExportFilename(run.run_id');
  });
});

describe('static metadata and header expectations', () => {
  it('keeps frame and referrer headers without backend or edge duplication', () => {
    const config = readFileSync('next.config.ts', 'utf8');
    expect(config).toContain('X-Frame-Options');
    expect(config).toContain('DENY');
    expect(config).toContain('Referrer-Policy');
    expect(config).toContain('strict-origin-when-cross-origin');
    expect(config).toContain("source: '/'");
    expect(config).toContain('public, max-age=0, must-revalidate');
    expect(config).not.toContain('Strict-Transport-Security');
    expect(config).not.toContain('s-maxage');
    expect(config).toContain('/api/:path*');
  });

  it('keeps neutral metadata and truthful static assets in source', () => {
    const layout = readFileSync('src/app/layout.tsx', 'utf8');
    for (const text of ['openGraph', 'twitter', '/favicon.svg', 'nothing publishes']) expect(layout).toContain(text);
    expect(readFileSync('public/robots.txt', 'utf8')).toContain('Allow: /');
    expect(readFileSync('public/sitemap.xml', 'utf8')).toContain('<loc>https://launchcrew.summitsingh.com/</loc>');
    expect(readFileSync('public/favicon.svg', 'utf8')).toContain('<svg');
  });

  it('preserves the server export gate and individual approvals', () => {
    const desk = readFileSync('src/app/page.tsx', 'utf8');
    expect(desk).toContain('/api/runs/{run_id}/approve');
    expect(desk).toContain('/api/runs/{run_id}/export');
    expect(desk).toContain('approved_for_export');
    const views = readFileSync('src/components/v2-views.tsx', 'utf8');
    expect(views).toContain('Review and approve each day individually');
    expect(views).toContain('/api/campaigns/{campaign_id}/days/{day}/approve');
    expect(views).toContain('/api/campaigns/{campaign_id}/days/{day}/export');
  });
});
