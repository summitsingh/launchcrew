import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { renderToStaticMarkup } from 'react-dom/server';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { CampaignView, DiffResult } from '../src/components/v2-views';
import type { components } from '../src/lib/schema';

function campaignHtml() {
  const profiles: components['schemas']['Profile'][] = [
    { name: 'Scout', role: 'Analyst', department: 'Growth', personality: 'Cautious', expertise: 'Facts', decision_rules: ['Use facts'], veto_scope: [], tools_allowed: ['facts_file'], spend_limit: 0, approval_level: 'approve_each', examples: [] },
    { name: 'Maker', role: 'Writer', department: 'Growth', personality: 'Warm', expertise: 'Brand', decision_rules: ['Use facts'], veto_scope: [], tools_allowed: ['facts_file'], spend_limit: 0, approval_level: 'approve_each', examples: [] },
    { name: 'Checker', role: 'Auditor', department: 'Growth', personality: 'Strict', expertise: 'Rules', decision_rules: ['Block any claim not found in facts file'], veto_scope: ['unverified_claims'], tools_allowed: ['facts_file'], spend_limit: 0, approval_level: 'approve_each', examples: [] },
  ];
  return renderToStaticMarkup(<QueryClientProvider client={new QueryClient()}><CampaignView profiles={profiles} /></QueryClientProvider>);
}

describe('per-stage role selections', () => {
  it('offers explicit Scout, Maker, and Checker bindings on the brief form', () => {
    const source = readFileSync('src/app/page.tsx', 'utf8');
    for (const id of ['id="run-scout"', 'id="run-agent"', 'id="run-checker-agent"', 'id="run-checker"']) {
      expect(source).toContain(id);
    }
    for (const label of ['Scout agent', 'Maker agent', 'Checker agent', 'Checker profile']) {
      expect(source).toContain(label);
    }
    expect(source).toContain('scout_name');
    expect(source).toContain('maker_name');
    expect(source).toContain('checker_name');
    expect(source).toContain('agent_name');
  });

  it('documents the supported Checker policy subset and advisory-only handling', () => {
    const source = readFileSync('src/app/page.tsx', 'utf8') + readFileSync('src/components/v2-views.tsx', 'utf8');
    for (const text of ['superlatives', 'price_claims', 'Block superlatives', 'Block price claims', 'advisory only', '/api/checker-policies', 'cannot be relaxed']) {
      expect(source).toContain(text);
    }
  });

  it('renders campaign stage selectors without a live backend', () => {
    const html = campaignHtml();
    for (const label of ['Scout agent', 'Maker agent', 'Checker agent', 'Checker profile', 'Create week', 'Nothing publishes automatically.']) {
      expect(html).toContain(label);
    }
    expect(html).toContain('id="campaign-scout"');
    expect(html).toContain('id="campaign-maker"');
    expect(html).toContain('id="campaign-checker-agent"');
    expect(html).toContain('id="campaign-checker"');
  });

  it('shows stage binding differences in replay', () => {
    const diff: components['schemas']['RunDiff'] = {
      run_a_id: 'run_a', run_b_id: 'run_b', same_idea: true, idea: 'Demo wallet',
      draft_v1_post_changed: false, draft_v1_email_changed: false, draft_v2_post_changed: false, draft_v2_email_changed: false,
      draft_v1_post_a: 'A', draft_v1_post_b: 'A', draft_v2_post_a: 'A', draft_v2_post_b: 'A',
      draft_v2_email_a: 'A', draft_v2_email_b: 'A',
      checker_v1_blocked_count_a: 0, checker_v1_blocked_count_b: 1,
      checker_v2_blocked_count_a: 0, checker_v2_blocked_count_b: 0,
      checker_profile_a: 'standard', checker_profile_b: 'standard', checker_profile_changed: false,
      scout_name_a: 'Scout', scout_name_b: 'EagleScout',
      maker_name_a: 'Maker', maker_name_b: 'Maker',
      checker_name_a: 'Checker', checker_name_b: 'PriceGuard',
      stage_bindings_changed: true,
      memory_ids_a: [], memory_ids_b: [],
      voice_changed: false,
      blocked_claims_only_in_a: [], blocked_claims_only_in_b: [{ claim: '$49', reason: "Blocked by Checker policy 'price_claims': price value" }],
      approval_state_a: 'pending_approval', approval_state_b: 'pending_approval', approval_state_changed: false,
      status_a: 'completed', status_b: 'completed',
      receipt_keys_only_in_a: [], receipt_keys_only_in_b: [],
    };
    const html = renderToStaticMarkup(<DiffResult diff={diff} />);
    for (const text of ['Scout: Scout / EagleScout', 'Maker: Maker / Maker', 'Checker: Checker / PriceGuard', 'Stage bindings changed: true']) {
      expect(html).toContain(text);
    }
  });

  it('shows enforced versus advisory-only preview state in the agent builder', () => {
    const source = readFileSync('src/app/page.tsx', 'utf8');
    for (const text of ['Enforced policies:', 'Advisory-only entries:', '<SupportedPoliciesHint']) {
      expect(source).toContain(text);
    }
  });
});
