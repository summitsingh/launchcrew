import { beforeEach, describe, expect, it } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderToStaticMarkup } from 'react-dom/server';
import { ReplayView } from '../src/components/v2-views';
import {
  clearReplaySelection,
  loadReplayDiff,
  saveReplayDiff,
  saveReplaySelection,
} from '../src/lib/replay-state';

const MARKER = 'Persisted draft post PIN 7x3q';

function storedDiff() {
  return {
    run_a_id: 'run_aaa111',
    run_b_id: 'run_bbb222',
    same_idea: true,
    idea: 'Synthetic persisted comparison',
    draft_v1_post_changed: true,
    draft_v1_email_changed: false,
    draft_v2_post_changed: true,
    draft_v2_email_changed: false,
    draft_v1_post_a: MARKER,
    draft_v1_post_b: 'Other draft',
    draft_v2_post_a: MARKER,
    draft_v2_post_b: 'Other draft',
    draft_v2_email_a: 'Email A',
    draft_v2_email_b: 'Email B',
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
    scout_name_a: 'Scout',
    scout_name_b: 'Scout',
    maker_name_a: 'Maker',
    maker_name_b: 'Maker',
    checker_name_a: 'Checker',
    checker_name_b: 'Checker',
    stage_bindings_changed: false,
    memory_ids_a: [],
    memory_ids_b: [],
  };
}

function renderReplay() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <ReplayView queue={[]} />
    </QueryClientProvider>,
  );
}

describe('replay diff result persistence', () => {
  beforeEach(() => {
    clearReplaySelection();
  });

  it('stores a successful diff keyed to its compared pair', () => {
    const diff = storedDiff();
    saveReplaySelection({ a: 'run_aaa111', b: 'run_bbb222' });
    // Same call the Compare onSuccess handler makes when a comparison succeeds.
    saveReplayDiff({ a: 'run_aaa111', b: 'run_bbb222' }, diff);
    expect(loadReplayDiff()).toEqual({ a: 'run_aaa111', b: 'run_bbb222', diff });
  });

  it('keeps the displayed comparison across unmount and fresh mount without clicking Compare again', () => {
    saveReplaySelection({ a: 'run_aaa111', b: 'run_bbb222' });
    saveReplayDiff({ a: 'run_aaa111', b: 'run_bbb222' }, storedDiff());
    // First mount renders the stored DiffResult immediately.
    const first = renderReplay();
    expect(first).toContain('Draft changes');
    expect(first).toContain(MARKER);
    // Unmounting and mounting a fresh ReplayView (navigating away and back)
    // still displays the DiffResult with no further Compare click.
    const second = renderReplay();
    expect(second).toContain('Draft changes');
    expect(second).toContain(MARKER);
  });

  it('does not render a stale diff for a different pair', () => {
    saveReplaySelection({ a: 'run_aaa111', b: 'run_bbb222' });
    saveReplayDiff({ a: 'run_aaa111', b: 'run_bbb222' }, storedDiff());
    // The user edits the selection away from the compared pair.
    saveReplaySelection({ a: 'run_other1', b: 'run_other2' });
    const html = renderReplay();
    expect(html).not.toContain(MARKER);
  });

  it('clears the stored diff when the selection is cleared', () => {
    saveReplaySelection({ a: 'run_aaa111', b: 'run_bbb222' });
    saveReplayDiff({ a: 'run_aaa111', b: 'run_bbb222' }, storedDiff());
    clearReplaySelection();
    expect(loadReplayDiff()).toBeNull();
    expect(renderReplay()).not.toContain(MARKER);
  });
});
