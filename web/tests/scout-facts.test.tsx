import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { ScoutFactsSection } from '../src/components/v2-views';
import type { components } from '../src/lib/schema';

type Receipt = components['schemas']['Receipt'];

const SOURCES = ['demo_facts.json', 'demo brand brief'];
const DEFAULT_CLAIMS = [
  '100% vegan PU leather',
  'Designed in Texas',
  '$49',
  'Vegan leather wallet',
  'For Austin commuters',
];
const DEFAULT_RISKS = [
  'Risk 1: Unsupported product claims require revision.',
  'Risk 2: Channel suitability is unverified by this facts file.',
  'Risk 3: Price and availability need human review before export.',
];

function receipt(overrides: Record<string, unknown> = {}): Receipt {
  return {
    run_id: 'run_demo',
    status: 'completed',
    idea: 'Vegan leather wallet, $49, for Austin commuters, launch on Instagram',
    checker_profile: 'standard',
    memory_used: [],
    approval_state: 'pending_approval',
    approvals: [],
    revision: 0,
    revision_history: [],
    export_history: [],
    summary: { submit_attempted: false },
    audit: {},
    stage_bindings: { scout: 'Scout', maker: 'Maker', checker: 'Checker' },
    scout: {
      facts_used: DEFAULT_CLAIMS.map((claim) => ({ claim, verified: true, evidence: claim, sources: SOURCES })),
      risks: [...DEFAULT_RISKS],
      sources: SOURCES,
      model_mode: 'deterministic_fallback',
      model_note: 'No model synthesis.',
    },
    model_usage: {
      spark_calls: 0, spark_mode: 'deterministic_fallback', mode: 'deterministic_fallback',
      model_used: 'none', models_used: [], error_types: [], wonder_used: false,
      wonder_attempts: 0, token_counts: {}, tokens_known: false,
      data_mode: 'not_sent', data_mode_note: 'No model request was attempted on this run, so nothing was sent.',
      data_basis: 'v2', request_provider: 'none',
    },
    ...overrides,
  } as Receipt;
}

function countClass(html: string, cls: string) {
  return html.split(`class="scout-${cls}"`).length - 1;
}

describe('Scout facts and risks section', () => {
  it('renders the five default sourced facts with labels, evidence, and verified status', () => {
    const html = renderToStaticMarkup(<ScoutFactsSection receipt={receipt()} />);
    expect(html).toContain('Scout facts and sources');
    for (const claim of DEFAULT_CLAIMS) {
      expect(html).toContain(claim);
    }
    expect(countClass(html, 'fact')).toBe(5);
    expect(html.match(/Verified/g)?.length).toBeGreaterThanOrEqual(5);
    expect(html).toContain('demo_facts.json');
    expect(html).toContain('demo brand brief');
    expect(html).toContain('Evidence:');
  });

  it('renders the three default demo risks as unverified hypotheses, not external research', () => {
    const html = renderToStaticMarkup(<ScoutFactsSection receipt={receipt()} />);
    expect(countClass(html, 'risk')).toBe(3);
    for (const risk of DEFAULT_RISKS) {
      expect(html).toContain(risk);
    }
    expect(html).toContain('Demo risk, unverified');
    expect(html).toContain('No external research was run');
  });

  it('preserves the selected custom Scout identity', () => {
    const html = renderToStaticMarkup(
      <ScoutFactsSection receipt={receipt({ stage_bindings: { scout: 'EagleScout', maker: 'Maker', checker: 'Checker' } })} />,
    );
    expect(html).toContain('EagleScout');
  });

  it('marks unverified model facts and model risks as hypotheses without inventing sources', () => {
    const html = renderToStaticMarkup(
      <ScoutFactsSection receipt={receipt({
        scout: {
          facts_used: [{ claim: 'Model guess', verified: false, evidence: 'Model guess', sources: [] }],
          risks: ['Unverified model risk: a guess'],
          sources: SOURCES,
          model_mode: 'spark',
          model_note: 'Optional Scout synthesis received.',
        },
      })} />,
    );
    expect(html).toContain('Unverified');
    expect(html).toContain('No stored source: unverified model hypothesis, not external research.');
    expect(html).toContain('Unverified model hypothesis');
    expect(html).not.toContain('Verified');
  });

  it('shows deterministic fallback truthfully when no model synthesis ran', () => {
    const html = renderToStaticMarkup(<ScoutFactsSection receipt={receipt()} />);
    expect(html).toContain('deterministic fallback');
    expect(html).toContain('No model synthesis.');
    expect(html).toContain('0 Spark calls');
  });

  it('renders a legacy receipt without Scout data instead of inventing facts', () => {
    const legacy = receipt({ scout: undefined, model_usage: undefined, stage_bindings: undefined });
    delete (legacy as Record<string, unknown>).scout;
    const html = renderToStaticMarkup(<ScoutFactsSection receipt={legacy} />);
    expect(html).toContain('Sourced facts unavailable for this receipt.');
    for (const claim of DEFAULT_CLAIMS) {
      expect(html).not.toContain(claim);
    }
    expect(countClass(html, 'fact')).toBe(0);
    expect(countClass(html, 'risk')).toBe(0);
  });
});
