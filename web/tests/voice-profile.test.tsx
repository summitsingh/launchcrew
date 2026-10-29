import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { renderToStaticMarkup } from 'react-dom/server';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { DiffResult, MemoryView, VoiceBlock } from '../src/components/v2-views';
import { memoryEditPayload } from '../src/lib/v2';
import type { components } from '../src/lib/schema';

type Receipt = components['schemas']['Receipt'];
type Diff = components['schemas']['RunDiff'];
type MemoryItem = components['schemas']['MemoryItemOut'];

function voiceReceipt(overrides: Record<string, unknown> = {}): Receipt {
  return {
    run_id: 'run_voice_demo',
    idea: 'Synthetic garden brief',
    status: 'completed',
    approval_state: 'pending_approval',
    revision: 0,
    approvals: [],
    summary: {},
    audit: {},
    voice_profile: {
      id: 'mem_voice_demo',
      title: 'Synthetic voice',
      version: 'voice/v1:syntheticdemo12',
      digest: 'a'.repeat(64),
      example_count: 3,
      banned_term_count: 1,
      banned_terms: ['harbor'],
      notice: 'style references only: examples are synthetic style references, never factual evidence or authority; they never bypass Checker and never become confirmed facts.',
    },
    voice_stale: false,
    ...overrides,
  } as unknown as Receipt;
}

function voiceDiff(overrides: Record<string, unknown> = {}): Diff {
  return {
    run_a_id: 'run_a',
    run_b_id: 'run_b',
    same_idea: true,
    idea: 'Synthetic garden brief',
    draft_v1_post_changed: false,
    draft_v1_email_changed: false,
    draft_v2_post_changed: false,
    draft_v2_email_changed: false,
    draft_v1_post_a: 'Post A',
    draft_v1_post_b: 'Post A',
    draft_v2_post_a: 'Post A',
    draft_v2_post_b: 'Post A',
    draft_v2_email_a: 'Email A',
    draft_v2_email_b: 'Email A',
    checker_v1_blocked_count_a: 0,
    checker_v1_blocked_count_b: 0,
    checker_v2_blocked_count_a: 0,
    checker_v2_blocked_count_b: 0,
    blocked_claims_only_in_a: [],
    blocked_claims_only_in_b: [],
    approval_state_a: 'pending_approval',
    approval_state_b: 'pending_approval',
    approval_state_changed: false,
    status_a: 'completed',
    status_b: 'completed',
    receipt_keys_only_in_a: [],
    receipt_keys_only_in_b: [],
    checker_profile_a: 'standard',
    checker_profile_b: 'standard',
    checker_profile_changed: false,
    memory_ids_a: [],
    memory_ids_b: [],
    stage_bindings_changed: false,
    voice_id_a: 'mem_voice_demo',
    voice_id_b: 'mem_voice_demo',
    voice_title_a: 'Synthetic voice',
    voice_title_b: 'Synthetic voice',
    voice_version_a: 'voice/v1:syntheticdemo12',
    voice_version_b: 'voice/v1:syntheticdemo12',
    voice_changed: false,
    ...overrides,
  };
}

describe('voice memory controls', () => {
  it('offers the voice kind with synthetic-only and actor workspace guidance', () => {
    const client = new QueryClient();
    client.setQueryData(['memory'], []);
    const html = renderToStaticMarkup(
      <QueryClientProvider client={client}><MemoryView /></QueryClientProvider>,
    );
    expect(html).toContain('voice_profile');
    expect(html).toContain('synthetic style examples');
    expect(html).toContain('style references only');
    expect(html).toContain('never become confirmed facts');
    expect(html).toContain('Samples stay in your actor workspace');
    expect(html).toContain('invalidates dependent approvals until a new revision check passes');
  });

  it('documents the voice JSON shape in source for explicit entry', () => {
    const source = readFileSync('src/components/v2-views.tsx', 'utf8');
    expect(source).toContain('voice_profile');
    expect(source).toContain('banned_terms');
    expect(source).toContain('Use synthetic samples only, 3 to 5 pairs');
    expect(source).toContain('Banned terms block drafts, revisions, and channel candidates');
  });

  it('accepts a synthetic voice payload as an editable object', () => {
    const voice = JSON.stringify({
      examples: [
        { input: 'Synthetic draft about garden layout', output: 'Synthetic revision about garden layout' },
        { input: 'Synthetic draft about trail map', output: 'Synthetic revision about trail map' },
        { input: 'Synthetic draft about recipe card', output: 'Synthetic revision about recipe card' },
      ],
      banned_terms: ['harbor'],
    });
    const payload = memoryEditPayload('Synthetic voice', voice);
    expect(payload.title).toBe('Synthetic voice');
    expect(payload.content).toHaveProperty('examples');
    expect(payload.content).toHaveProperty('banned_terms');
  });

  it('renders a cached synthetic voice item without contacting a backend', () => {
    const client = new QueryClient();
    const item: MemoryItem = {
      id: 'mem_voice_demo',
      kind: 'voice_profile',
      title: 'Synthetic voice',
      content: { examples: [], banned_terms: ['harbor'] },
      source_run_id: null,
      created_at: '2026-10-29T00:00:00Z',
      updated_at: '2026-10-29T00:00:00Z',
    };
    client.setQueryData(['memory'], [item]);
    const html = renderToStaticMarkup(
      <QueryClientProvider client={client}><MemoryView /></QueryClientProvider>,
    );
    expect(html).toContain('Synthetic voice');
    expect(html).toContain('Kind (read-only): voice_profile');
    expect(html).toContain('harbor');
  });
});

describe('voice receipt block', () => {
  it('shows source, version, counts, notice, and stale state', () => {
    const html = renderToStaticMarkup(<VoiceBlock receipt={voiceReceipt()} />);
    for (const text of ['Voice profile', 'Synthetic voice', 'voice/v1:syntheticdemo12', 'Examples: 3', 'Banned terms: 1', 'style references only']) {
      expect(html).toContain(text);
    }
    expect(html).not.toContain('Stale:');
    const stale = renderToStaticMarkup(<VoiceBlock receipt={voiceReceipt({ voice_stale: true })} />);
    expect(stale).toContain('Stale: edited or deleted since this receipt, new revision check required');
  });

  it('stays empty when no voice was selected', () => {
    expect(renderToStaticMarkup(<VoiceBlock receipt={voiceReceipt({ voice_profile: null })} />)).toBe('');
    expect(renderToStaticMarkup(<VoiceBlock receipt={{} as unknown as Receipt} />)).toBe('');
  });
});

describe('voice replay diff', () => {
  it('shows matching voice sources as unchanged with a style-only note', () => {
    const html = renderToStaticMarkup(<DiffResult diff={voiceDiff()} />);
    expect(html).toContain('Voice source changes');
    expect(html).toContain('Synthetic voice');
    expect(html).toContain('voice/v1:syntheticdemo12');
    expect(html).toContain('Changed: false');
    expect(html).toContain('Style references only');
    expect(html).toContain('Samples never become confirmed facts');
  });

  it('marks a changed voice version explicitly', () => {
    const html = renderToStaticMarkup(
      <DiffResult diff={voiceDiff({ voice_version_b: 'voice/v1:otherdigest34', voice_changed: true })} />,
    );
    expect(html).toContain('voice/v1:otherdigest34');
    expect(html).toContain('Changed: true');
  });

  it('labels missing voice as none without inventing a source', () => {
    const html = renderToStaticMarkup(
      <DiffResult diff={voiceDiff({
        voice_id_a: null, voice_title_a: null, voice_version_a: null,
        voice_id_b: null, voice_title_b: null, voice_version_b: null,
        voice_changed: false,
      })} />,
    );
    expect(html).toContain('none');
    expect(html).toContain('no version');
  });
});
