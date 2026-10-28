import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { capabilityCopy, dataModeCopy } from '../src/components/model-status';
import { ScoutFactsSection } from '../src/components/v2-views';
import type { components } from '../src/lib/schema';

type Receipt = components['schemas']['Receipt'];

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
      facts_used: [{ claim: 'Designed in Texas', verified: true, evidence: 'Designed in Texas', sources: ['demo_facts.json'] }],
      risks: [],
      sources: ['demo_facts.json'],
      model_mode: 'deterministic_fallback',
      model_note: 'No model synthesis.',
    },
    model_usage: {
      spark_calls: 0, spark_mode: 'deterministic_fallback', mode: 'deterministic_fallback',
      model_used: 'none', models_used: [], error_types: [], wonder_used: false,
      wonder_attempts: 0, token_counts: {}, tokens_known: false,
      data_mode: 'not_sent', data_mode_note: 'No model request was attempted on this run, so nothing was sent.',
    },
    ...overrides,
  } as Receipt;
}

describe('model status footer copy', () => {
  it('fails closed to unknown while loading', () => {
    expect(capabilityCopy(undefined, true, false)).toContain('unknown');
    expect(capabilityCopy(undefined, true, false)).toContain('Loading configuration');
  });

  it('fails closed to unknown on error', () => {
    expect(capabilityCopy(undefined, false, true)).toContain('unknown');
  });

  it('reports keyless truthfully', () => {
    const html = capabilityCopy({ spark_configured: false, wonder_configured: false, sam_configured: false } as never, false, false);
    expect(html).toContain('not configured');
    expect(html).toContain('Local drafts');
  });

  it('reports configured but untested without proving the API works', () => {
    const html = capabilityCopy({ spark_configured: true, wonder_configured: false, sam_configured: false } as never, false, false);
    expect(html).toContain('Configured, not yet tested');
    expect(html).toContain('does not prove');
    expect(html).toContain('No live call');
  });
});

describe('stored run usage data mode', () => {
  it('keeps missing metadata unknown for historical receipts', () => {
    expect(dataModeCopy(null)).toBe('unknown');
    expect(dataModeCopy(undefined)).toBe('unknown');
    expect(dataModeCopy({} as never)).toBe('unknown');
  });

  it('renders stored not_sent and standard modes truthfully on the receipt', () => {
    expect(renderToStaticMarkup(<ScoutFactsSection receipt={receipt()} />)).toContain('Data: not_sent.');
    const standard = receipt({ model_usage: { ...(receipt().model_usage as object), data_mode: 'standard_no_train' } });
    expect(renderToStaticMarkup(<ScoutFactsSection receipt={standard} />)).toContain('Data: standard_no_train.');
    const legacy = receipt({ model_usage: undefined });
    delete (legacy as Record<string, unknown>).model_usage;
    expect(renderToStaticMarkup(<ScoutFactsSection receipt={legacy} />)).toContain('Data: unknown.');
  });

  it('renders unknown contributor data without a training guarantee', () => {
    const usage = receipt({
      model_usage: {
        spark_calls: 1, spark_mode: 'deterministic_fallback', mode: 'TimeoutError',
        model_used: 'unknown', models_used: [], error_types: ['TimeoutError'], wonder_used: false,
        wonder_attempts: 0, token_counts: {}, tokens_known: false,
        data_mode: 'unknown', data_mode_note: 'Unknown model variant on this run. No training guarantee is claimed.',
      },
    });
    const html = renderToStaticMarkup(<ScoutFactsSection receipt={usage} />);
    expect(html).toContain('Data: unknown.');
    expect(html).toContain('Stored usage: TimeoutError, 1 Spark calls, model unknown.');
  });
});
