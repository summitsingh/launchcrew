import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { capabilityCopy, dataModeCopy, dataModeLabel, dataModeNote } from '../src/components/model-status';
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
      data_basis: 'v2', request_provider: 'none',
    },
    ...overrides,
  } as Receipt;
}

describe('model status footer copy', () => {
  it('fails closed to unknown while loading', () => {
    expect(capabilityCopy(undefined, true, false)).toContain('unknown');
    expect(capabilityCopy(undefined, true, false)).toContain('Loading configuration');
  });

  it('reports Configuration unavailable on error with priority over loading', () => {
    expect(capabilityCopy(undefined, false, true)).toContain('unknown');
    expect(capabilityCopy(undefined, false, true)).toContain('Configuration unavailable');
    expect(capabilityCopy(undefined, false, true)).not.toContain('Loading configuration');
    expect(capabilityCopy(undefined, true, true)).toContain('Configuration unavailable');
    expect(capabilityCopy(undefined, true, true)).not.toContain('Loading configuration');
  });

  it('reports keyless truthfully', () => {
    const html = capabilityCopy({ spark_configured: false, wonder_configured: false, sam_configured: false } as never, false, false);
    expect(html).toContain('not configured');
    expect(html).toContain('Local drafts');
  });

  it('reports configuration present without claiming never tested', () => {
    const html = capabilityCopy({ spark_configured: true, wonder_configured: false, sam_configured: false } as never, false, false);
    expect(html).toContain('Configuration present');
    expect(html).toContain('does not verify');
    expect(html).toContain('Actual calls are in receipts');
    expect(html).toContain('No live call');
    expect(html).not.toContain('not yet tested');
  });
});

describe('stored run usage data mode', () => {
  it('keeps missing metadata unknown for historical receipts', () => {
    expect(dataModeCopy(null)).toBe('unknown');
    expect(dataModeCopy(undefined)).toBe('unknown');
    expect(dataModeCopy({} as never)).toBe('unknown');
    expect(dataModeLabel(null)).toBe('Unknown');
  });

  it('treats legacy standard_no_train without current basis as unverified unknown', () => {
    const legacy = {
      data_mode: 'standard_no_train',
      data_mode_note: 'Stated intent for user data, not a verified API setting.',
    } as never;
    expect(dataModeCopy(legacy)).toBe('unknown');
    expect(dataModeLabel(legacy)).toBe('Unknown');
    expect(dataModeNote(legacy)).toContain('Historical record');
  });

  it('treats standard_no_train with unknown provider as unknown', () => {
    const spoofed = {
      data_mode: 'standard_no_train', data_mode_note: 'note',
      data_basis: 'v2', request_provider: 'unknown',
    } as never;
    expect(dataModeCopy(spoofed)).toBe('unknown');
    expect(dataModeLabel(spoofed)).toBe('Unknown');
  });

  it('labels current not_sent as nothing attempted with current basis', () => {
    expect(dataModeCopy(receipt().model_usage as never)).toBe('not_sent');
    expect(dataModeLabel(receipt().model_usage as never)).toBe('Nothing attempted');
  });

  it('labels current standard, contributor, mixed, and unknown readably with notes', () => {
    const standard = {
      data_mode: 'standard_no_train', data_mode_note: 'Standard request variant note.',
      data_basis: 'v2', request_provider: 'meta',
    } as never;
    expect(dataModeCopy(standard)).toBe('standard_no_train');
    expect(dataModeLabel(standard)).toBe('Standard request variant');
    const contributor = {
      data_mode: 'contributor', data_mode_note: 'Contributor note.',
      data_basis: 'v2', request_provider: 'meta',
    } as never;
    expect(dataModeLabel(contributor)).toContain('Contributor');
    const mixed = {
      data_mode: 'mixed', data_mode_note: 'Mixed note.',
      data_basis: 'v2', request_provider: 'meta',
    } as never;
    expect(dataModeLabel(mixed)).toBe('Mixed variants');
  });

  it('renders stored not_sent and standard modes truthfully on the receipt', () => {
    expect(renderToStaticMarkup(<ScoutFactsSection receipt={receipt()} />)).toContain('Nothing attempted');
    expect(renderToStaticMarkup(<ScoutFactsSection receipt={receipt()} />)).toContain('(not_sent)');
    const standard = receipt({ model_usage: { ...(receipt().model_usage as object), data_mode: 'standard_no_train', data_mode_note: 'Standard request variant note.', data_basis: 'v2', request_provider: 'meta' } });
    const standardHtml = renderToStaticMarkup(<ScoutFactsSection receipt={standard} />);
    expect(standardHtml).toContain('Standard request variant');
    expect(standardHtml).not.toContain('Data: standard_no_train.');
    const legacy = receipt({ model_usage: undefined });
    delete (legacy as Record<string, unknown>).model_usage;
    expect(renderToStaticMarkup(<ScoutFactsSection receipt={legacy} />)).toContain('Data: Unknown (unknown).');
  });

  it('renders legacy hardcoded standard field as unverified unknown', () => {
    const legacyStandard = receipt({
      model_usage: {
        spark_calls: 1, spark_mode: 'spark', mode: 'spark',
        model_used: 'muse-spark-1.3', models_used: ['muse-spark-1.3'], error_types: [], wonder_used: false,
        wonder_attempts: 0, token_counts: {}, tokens_known: false,
        data_mode: 'standard_no_train', data_mode_note: 'Stated intent for user data, not a verified API setting.',
      },
    });
    const html = renderToStaticMarkup(<ScoutFactsSection receipt={legacyStandard} />);
    expect(html).toContain('Unknown');
    expect(html).toContain('Historical record');
    expect(html).not.toContain('Standard request variant');
  });

  it('renders unknown contributor data without a training guarantee', () => {
    const usage = receipt({
      model_usage: {
        spark_calls: 1, spark_mode: 'deterministic_fallback', mode: 'TimeoutError',
        model_used: 'unknown', models_used: [], error_types: ['TimeoutError'], wonder_used: false,
        wonder_attempts: 0, token_counts: {}, tokens_known: false,
        data_mode: 'unknown', data_mode_note: 'Unknown request variant or endpoint on this run.',
        data_basis: 'v2', request_provider: 'unknown',
      },
    });
    const html = renderToStaticMarkup(<ScoutFactsSection receipt={usage} />);
    expect(html).toContain('Unknown');
    expect(html).toContain('Stored usage: TimeoutError, 1 Spark calls, model unknown.');
  });
});
