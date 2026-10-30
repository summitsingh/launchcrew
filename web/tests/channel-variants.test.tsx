import { describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { ChannelVariantsBundleView } from '../src/components/v2-views';
import type { components } from '../src/lib/schema';

type Bundle = components['schemas']['ChannelVariantsOut'];
type Variant = components['schemas']['ChannelVariantOut'];

function variant(overrides: Partial<Variant> = {}): Variant {
  return {
    channel: 'x',
    variant_kind: 'presentation_candidate',
    text: '',
    subject: '',
    content_valid: false,
    exportable: false,
    independently_exportable: false,
    requires_checker_binding: true,
    status: 'needs_revision',
    reason: 'Needs revision.',
    trim_note: '',
    char_count: 0,
    kept_sentences: 0,
    total_sentences: 0,
    omitted_sentences: 0,
    approval_note: 'Presentation candidate only.',
    ...overrides,
  } as Variant;
}

function bundle(overrides: Partial<Bundle> = {}): Bundle {
  const base = {
    bundle_version: 'checked-channel-variants/v1',
    receipt_id: 'run_demo',
    revision: 0,
    approval_state: 'approved_for_export',
    binding_version: 'approval-binding/v1',
    binding_digest: 'a'.repeat(64),
    channel_approvals: {
      x: { approved_by: 'reviewer', revision: 0, current: true },
    },
    facts_mode: 'demo_template',
    facts_label: 'Bundled fictional demo template',
    template_used: true,
    confirmed_claims_count: 5,
    draft_source: 'current post draft',
    all_content_valid: true,
    no_auto_publish: true,
    note: 'Checked export candidates only.',
    provenance: {},
  };
  return {
    ...base,
    x: variant({ channel: 'x', text: 'Vegan leather wallet.', content_valid: true, status: 'candidate_pending_checker', char_count: 21, kept_sentences: 1, total_sentences: 2, omitted_sentences: 1, trim_note: 'Trimmed on a sentence boundary.' }),
    linkedin: variant({ channel: 'linkedin', text: 'Update:\n\nVegan leather wallet.', content_valid: true, status: 'candidate_pending_checker', char_count: 30, kept_sentences: 1, total_sentences: 1 }),
    instagram: variant({ channel: 'instagram', text: 'Vegan leather wallet.\n\nMore soon.', content_valid: true, status: 'candidate_pending_checker', char_count: 33, kept_sentences: 1, total_sentences: 1 }),
    email: variant({ channel: 'email', text: 'Hello,\n\nVegan leather wallet.\n\nThanks,', subject: 'Quick update', content_valid: true, status: 'candidate_pending_checker', char_count: 40, kept_sentences: 1, total_sentences: 1 }),
    facebook: variant({ channel: 'facebook', content_valid: false, status: 'needs_revision', reason: 'Needs revision with a shorter opening sentence.' }),
    ...overrides,
  } as Bundle;
}

const handlers = () => ({ onApprove: vi.fn(), onCopy: vi.fn() });

describe('Channel variants bundle view', () => {
  it('renders all five channel cards with binding provenance and no publish affordance', () => {
    const html = renderToStaticMarkup(
      <ChannelVariantsBundleView bundle={bundle()} copied={null} locked={false} {...handlers()} />
    );
    for (const label of ['X', 'LinkedIn', 'Instagram', 'Email', 'Facebook']) {
      expect(html).toContain(`${label} variant`);
    }
    expect(html).toContain('a'.repeat(64));
    expect(html).toContain('revision 0');
    expect(html).toContain('Vegan leather wallet.');
    expect(html).toContain('Subject: Quick update');
    expect(html).toContain('Channel approved by reviewer');
    expect(html).toContain('Human-approved exact text');
    expect(html).not.toContain('Publish');
    expect(html).not.toContain('Send');
  });

  it('disables copy without a current human approval and keeps invalid text out', () => {
    const html = renderToStaticMarkup(
      <ChannelVariantsBundleView bundle={bundle()} copied={null} locked={false} {...handlers()} />
    );
    expect(html).toContain('Needs revision');
    expect(html).toContain('Needs revision with a shorter opening sentence.');
    expect(html).toContain('Verified, awaiting your approval');
    const disabledCount = (html.match(/disabled=""/g) ?? []).length;
    // Four verified-but-unapproved cards lock copy; the approved X card locks
    // re-approval; the invalid Facebook card locks both buttons.
    expect(disabledCount).toBe(6);
  });

  it('locks every action while the pack changed', () => {
    const html = renderToStaticMarkup(
      <ChannelVariantsBundleView bundle={bundle()} copied={null} locked onApprove={vi.fn()} onCopy={vi.fn()} />
    );
    expect(html).toContain('Locked while the pack changed');
    const disabledCount = (html.match(/disabled=""/g) ?? []).length;
    expect(disabledCount).toBe(10);
  });

  it('announces a completed copy without exposing publish actions', () => {
    const html = renderToStaticMarkup(
      <ChannelVariantsBundleView bundle={bundle()} copied="x" locked={false} onApprove={vi.fn()} onCopy={vi.fn()} />
    );
    expect(html).toContain('Copied X text for offline use.');
  });
});
