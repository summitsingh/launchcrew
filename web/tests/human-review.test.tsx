import { describe, it, expect } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { currentDraftOf, currentCheckOf, revisionStatusOf, FailedRunNotice, ReceiptTimeline, HumanRevisionEditor } from '../src/components/v2-views';
import type { components } from '../src/lib/schema';

type Receipt = components['schemas']['Receipt'];

function receipt(overrides: Record<string, unknown> = {}): Receipt {
  return {
    run_id: 'run_demo',
    status: 'completed',
    idea: 'Demo',
    checker_profile: 'standard',
    memory_used: [],
    approval_state: 'pending_approval',
    approvals: [],
    revision: 0,
    revision_history: [],
    summary: { submit_attempted: false },
    audit: { event_log: [{ step: 'checker_v2', agent: 'Checker', profile: 'Checker', action: 'Rechecked', timestamp: '2026-01-01T00:00:00Z' }] },
    maker_draft_v2: { post: 'Maker post', email: 'Maker email', claims: [] },
    checker_v2: { blocked_count: 0, verified_count: 1, blocked_claims: [], revision_instructions: [] },
    ...overrides,
  } as Receipt;
}

describe('human revision helpers', () => {
  it('prefers the saved human draft and check over Maker output', () => {
    const revised = receipt({
      revision: 1,
      human_draft: { post: 'Human post', email: 'Human email', claims: [], revision: 1 },
      human_check: { blocked_count: 0, verified_count: 2, blocked_claims: [], revision_instructions: [] },
    });
    expect(currentDraftOf(revised)).toMatchObject({ post: 'Human post', revision: 1, human: true });
    expect(currentCheckOf(revised)?.blocked_count).toBe(0);
    expect(revisionStatusOf(revised)).toBe('pending fresh approval');
  });

  it('keeps Maker content for unrevised packs', () => {
    const plain = receipt();
    expect(currentDraftOf(plain).post).toBe('Maker post');
    expect(revisionStatusOf(plain)).toBe('pending approval');
  });

  it('marks failed runs explicitly', () => {
    const failed = receipt({ status: 'failed', maker_draft_v2: undefined, checker_v2: undefined });
    expect(revisionStatusOf(failed)).toBe('failed');
    const html = renderToStaticMarkup(<FailedRunNotice receipt={failed} />);
    expect(html).toContain('Pipeline stopped safely.');
  });

  it('renders the recorded timeline without inventing timestamps', () => {
    const html = renderToStaticMarkup(<ReceiptTimeline receipt={receipt()} />);
    expect(html).toContain('checker_v2');
    expect(html).toContain('2026-01-01T00:00:00Z');
    expect(html).toContain('No times are invented');
  });

  it('disables the editor on failed runs', () => {
    const failed = receipt({ status: 'failed' });
    const html = renderToStaticMarkup(
      <QueryClientProvider client={new QueryClient()}>
        <HumanRevisionEditor receipt={failed} />
      </QueryClientProvider>,
    );
    expect(html).toContain('disabled=""');
    expect(html).toContain('Rechecking compares your edited text');
  });
});
