import { describe, it, expect } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { CampaignDayCard, CampaignView, DiffResult, ReplayView } from '../src/components/v2-views';
import { canApproveDay, canExportDay } from '../src/lib/v2';
import type { components } from '../src/lib/schema';

const day: components['schemas']['CampaignDay'] = { day: 1, run_id: 'run_demo', approval_state: 'pending_approval', status: 'completed', checker_v2_blocked_count: 0, idea: 'Demo wallet', angle: 'Origin story', brief: 'Designed in Texas for Austin commuters', draft_v2_post: 'Vegan leather wallet, designed in Texas.', revision: 0 };
const noop = () => {};
function card(value: typeof day, busy = false) { return renderToStaticMarkup(<CampaignDayCard day={value} busy={busy} approve={noop} download={noop} />); }

describe('v2 review controls', () => {
  it('allows only a pending clean successful day to be approved', () => {
    expect(canApproveDay(day)).toBe(true);
    expect(card(day)).toContain('Approve for export');
    expect(card(day)).not.toContain('Export pack');
    for (const unsafe of [{ ...day, checker_v2_blocked_count: 1 }, { ...day, checker_v2_blocked_count: null }, { ...day, status: 'failed' }, { ...day, status: 'running' }, { ...day, status: 'unknown' }]) {
      expect(canApproveDay(unsafe)).toBe(false);
      expect(card(unsafe)).not.toContain('Approve for export');
    }
    expect(card(day, true)).toContain('disabled=""');
  });
  it('shows export only after individual approval', () => {
    const approved = { ...day, approval_state: 'approved_for_export' as const };
    expect(canExportDay(day)).toBe(false);
    expect(canExportDay(approved)).toBe(true);
    expect(card(approved)).toContain('Export pack');
    expect(card(approved)).not.toContain('Approve for export');
    for (const bad of [{ ...approved, status: 'failed' }, { ...approved, status: 'running' }, { ...approved, status: 'unknown' }]) {
      expect(canExportDay(bad)).toBe(false);
      expect(card(bad)).not.toContain('Export pack');
    }
  });
  it('renders both review views without a live backend', () => {
    const html = renderToStaticMarkup(<QueryClientProvider client={new QueryClient()}><ReplayView queue={[]} /><CampaignView profiles={[]} /></QueryClientProvider>);
    for (const label of ['Replay', 'Run A id', 'Run B id', 'Compare', 'Pick from queue', 'Campaign Week', 'Create week', 'Nothing publishes automatically.']) expect(html).toContain(label);
  });
  it('offers all twelve campaign angles and binds owner facts on the week form', () => {
    const html = renderToStaticMarkup(<QueryClientProvider client={new QueryClient()}><CampaignView profiles={[]} /></QueryClientProvider>);
    for (const angle of ['Origin story', 'Material and craft', 'Commuter use', 'Styling', 'Care and durability', 'Social proof', 'Launch offer', 'Build in public milestone', 'Customer problem story', 'Before and after', 'Objection answer', 'Founder lesson']) {
      expect(html).toContain(angle);
    }
    for (const label of ['Campaign angles (choose exactly 7, one per day in order)', 'Product facts mode', 'Owner-input mode', 'Bundled fictional demo-template mode']) {
      expect(html).toContain(label);
    }
  });
  it('renders draft, verdict, approval and receipt changes with a mismatch note', () => {
    const diff: components['schemas']['RunDiff'] = {
      run_a_id: 'run_a', run_b_id: 'run_b', same_idea: false, idea: 'Demo wallet',
      draft_v1_post_changed: true, draft_v1_email_changed: false, draft_v2_post_changed: true, draft_v2_email_changed: false,
      draft_v1_post_a: 'First A', draft_v1_post_b: 'First B', draft_v2_post_a: 'Final A', draft_v2_post_b: 'Final B', draft_v2_email_a: 'Email A', draft_v2_email_b: 'Email B',
      checker_v1_blocked_count_a: 1, checker_v1_blocked_count_b: 0, checker_v2_blocked_count_a: 0, checker_v2_blocked_count_b: 0,
      blocked_claims_only_in_a: [{ claim: 'best in Texas', reason: 'Unsupported' }], blocked_claims_only_in_b: [],
      approval_state_a: 'pending_approval', approval_state_b: 'approved_for_export', approval_state_changed: true, status_a: 'completed', status_b: 'completed', receipt_keys_only_in_a: ['demo_extra'], receipt_keys_only_in_b: [], checker_profile_a: 'standard', checker_profile_b: 'strict', checker_profile_changed: true, memory_ids_a: [], memory_ids_b: [], stage_bindings_changed: false, voice_changed: false
    };
    const html = renderToStaticMarkup(<DiffResult diff={diff} />);
    for (const text of ['different ideas', 'Draft changes', 'First A', 'Final B', 'Email A', 'Checker verdict changes', 'Checker profile changes', 'standard', 'strict', 'best in Texas', 'Approval state changes', 'approved_for_export', 'Receipt key diff', 'demo_extra']) expect(html).toContain(text);
    expect(card(day)).toContain('Origin story');
    expect(card(day)).toContain('Designed in Texas for Austin commuters');
    expect(renderToStaticMarkup(<DiffResult diff={{ ...diff, same_idea: true }} />)).not.toContain('different ideas');
  });
});
