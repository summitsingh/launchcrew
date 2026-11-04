import { describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import type { components } from '../src/lib/schema';

// Seed Desk's view and active-run state while keeping real review components.
const deskState = vi.hoisted(() => ({ index: 0 }));
vi.mock('react', async importOriginal => {
  const actual = await importOriginal<typeof import('react')>();
  return {
    ...actual,
    useState: (initial: unknown) => {
      const index = deskState.index++;
      return actual.useState(index === 0 ? 'Run' : index === 15 ? 'run_completed_review' : initial);
    },
  };
});

vi.mock('@tanstack/react-query', async importOriginal => {
  const actual = await importOriginal<typeof import('@tanstack/react-query')>();
  return {
    ...actual,
    useQuery: ({ queryKey }: { queryKey: string[] }) => ({
      data: queryKey[0] === 'auth' ? { auth: 'disabled_demo' }
        : queryKey[0] === 'run' ? completedReceipt : [],
      isSuccess: true,
      isPending: false,
      isError: false,
    }),
  };
});

import Page from '../src/app/page';

const completedReceipt = {
  run_id: 'run_completed_review',
  status: 'completed',
  idea: 'Demo',
  checker_profile: 'standard',
  memory_used: [],
  approval_state: 'pending_approval',
  approvals: [],
  revision: 0,
  revision_history: [],
  export_history: [],
  summary: { submit_attempted: false },
  audit: { event_log: [] },
  maker_draft_v2: { post: 'Maker post', email: 'Maker email', claims: [] },
  checker_v1: { blocked_count: 1 },
  checker_v2: { blocked_count: 0, verified_count: 1, blocked_claims: [], revision_instructions: [] },
} as unknown as components['schemas']['Receipt'];

describe('completed Run review', () => {
  it('renders both review Cards and the human revision editor without throwing', () => {
    deskState.index = 0;
    let html = '';
    expect(() => { html = renderToStaticMarkup(<Page />); }).not.toThrow();
    expect(html).toContain('FIRST CHECK');
    expect(html).toContain('REVISED LAUNCH PACK');
    expect(html).toContain('Ready for your review.');
    expect(html).toContain('Maker post');
    expect(html).toContain('Rechecking compares your edited text');
    expect(html).toContain('id="human-post-run_completed_review"');
    expect(html).toContain('id="human-email-run_completed_review"');
  });
});
