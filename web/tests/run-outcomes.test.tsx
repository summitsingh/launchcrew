import { describe, it, expect } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import {
  OUTCOME_EMPTY,
  OUTCOME_MAX_COUNT,
  OUTCOME_SELF_REPORT,
  OutcomeForm,
  OutcomeList,
  RunOutcomesSection,
  isValidOutcomeCount,
  isValidOutcomeDate,
  isValidOutcomeNote,
  outcomeSummary,
  parseOutcomeCount,
  validateOutcomeDraft,
  type RunOutcome,
} from '../src/components/run-outcomes';

function outcome(overrides: Partial<RunOutcome> = {}): RunOutcome {
  return {
    id: 'out_demo1',
    run_id: 'run_demo1',
    export_revision: 0,
    channel: 'x',
    posted_date: '2026-06-01',
    likes: 10,
    comments: 2,
    clicks: 5,
    sales: 1,
    note: 'owner note for the day',
    provenance: 'self_reported',
    actor: 'google:synthetic-owner',
    created_at: '2026-06-02T00:00:00Z',
    ...overrides,
  } as RunOutcome;
}

const FORBIDDEN = ['provider-measured results', 'ROI:', 'ROI =', 'auto-posted to', 'live measurement shows'];

describe('owner outcome validation', () => {
  it('accepts exact real dates and rejects malformed or unreal ones', () => {
    expect(isValidOutcomeDate('2026-06-01')).toBe(true);
    expect(isValidOutcomeDate('2024-02-29')).toBe(true);
    for (const bad of ['', '2026-1-1', '2026/06/01', '2026-13-01', '2026-00-10', '2026-06-32', '2026-02-30', '2026-02-29', 'not-a-date', '2026-06-01T00:00:00', ' 2026-06-01']) {
      expect(isValidOutcomeDate(bad)).toBe(false);
    }
  });

  it('keeps counts type-exact, bounded, and nonnegative', () => {
    expect(isValidOutcomeCount(0)).toBe(true);
    expect(isValidOutcomeCount(OUTCOME_MAX_COUNT)).toBe(true);
    for (const bad of [-1, OUTCOME_MAX_COUNT + 1, 1.5, Number.NaN, '5', null, undefined, true, false, [1]]) {
      expect(isValidOutcomeCount(bad)).toBe(false);
    }
    expect(parseOutcomeCount('0')).toBe(0);
    expect(parseOutcomeCount(String(OUTCOME_MAX_COUNT))).toBe(OUTCOME_MAX_COUNT);
    expect(parseOutcomeCount('5 ')).toBe(5);
    for (const bad of ['', '  ', '-1', '1.5', 'abc', String(OUTCOME_MAX_COUNT + 1)]) {
      expect(parseOutcomeCount(bad)).toBe(null);
    }
  });

  it('keeps notes single line, bounded, and non-blank', () => {
    expect(isValidOutcomeNote('owner note')).toBe(true);
    expect(isValidOutcomeNote('n'.repeat(500))).toBe(true);
    for (const bad of ['', '   ', 'n'.repeat(501), 'line1\nline2', 'tab\there', 'nul\0here']) {
      expect(isValidOutcomeNote(bad)).toBe(false);
    }
  });

  it('reports every invalid draft field for review', () => {
    const good = { channel: 'email', posted_date: '2026-06-01', likes: '1', comments: '2', clicks: '3', sales: '4', note: 'owner note' };
    expect(validateOutcomeDraft(good)).toEqual([]);
    const bad = { channel: 'social', posted_date: '2026-02-30', likes: '-1', comments: '1.5', clicks: '', sales: '9999999', note: '  ' };
    const errors = validateOutcomeDraft(bad);
    expect(errors.length).toBeGreaterThanOrEqual(6);
    expect(errors.join(' ')).toContain('Channel');
    expect(errors.join(' ')).toContain('Posted date');
    expect(errors.join(' ')).toContain('likes');
  });

  it('summarizes only persisted metric values', () => {
    expect(outcomeSummary(outcome({ likes: 1, comments: 2, clicks: 3, sales: 4 }))).toBe(
      'likes 1 · comments 2 · clicks 3 · sales 4',
    );
  });
});

describe('owner outcomes replay display', () => {
  it('shows an explicit self-report label, revision, and persisted values', () => {
    const html = renderToStaticMarkup(<OutcomeList outcomes={[outcome(), outcome({ id: 'out_demo2', export_revision: 1, note: 'second owner note' })]} />);
    expect(html).toContain(OUTCOME_SELF_REPORT);
    expect(html).toContain('not provider-measured');
    expect(html).toContain('Exported revision 0');
    expect(html).toContain('Exported revision 1');
    expect(html).toContain('likes 10');
    expect(html).toContain('owner note for the day');
    expect(html).toContain('second owner note');
    expect(html).toContain('self_reported');
    expect(html).toContain('google:synthetic-owner');
    for (const token of FORBIDDEN) expect(html).not.toContain(token);
  });

  it('shows a clear empty state with no seeded rows', () => {
    const html = renderToStaticMarkup(<OutcomeList outcomes={[]} />);
    expect(html).toContain(OUTCOME_EMPTY);
    expect(html).not.toContain('out_demo1');
    for (const token of FORBIDDEN) expect(html).not.toContain(token);
  });

  it('keeps entry fields typed and bounded with review before save', () => {
    const html = renderToStaticMarkup(
      <QueryClientProvider client={new QueryClient()}>
        <OutcomeForm runId="run_demo1" />
      </QueryClientProvider>,
    );
    expect(html).toContain('Log an owner self-report');
    expect(html).toContain('<select');
    expect(html).toContain('type="date"');
    expect(html).toContain('type="number"');
    expect(html).toContain('min="0"');
    expect(html).toContain(`max="${OUTCOME_MAX_COUNT}"`);
    expect(html).toContain('step="1"');
    expect(html).toContain('<textarea');
    expect(html).toContain('Review outcome');
    expect(html).not.toContain('Confirm and save');
    for (const token of FORBIDDEN) expect(html).not.toContain(token);
  });

  it('mounts the replay section next to the matching run with provenance copy', () => {
    const html = renderToStaticMarkup(
      <QueryClientProvider client={new QueryClient()}>
        <RunOutcomesSection runId="run_demo1" label="Run A owner outcomes" />
      </QueryClientProvider>,
    );
    expect(html).toContain('Run A owner outcomes');
    expect(html).toContain('run_demo1');
    expect(html).toContain(OUTCOME_SELF_REPORT);
    expect(html).toContain('Owner-entered only');
    expect(html).toContain('never provider-measured');
    expect(html).toContain('No ROI is computed');
    expect(html).toContain('nothing auto-posts');
    expect(html).toContain('nothing is seeded');
    for (const token of FORBIDDEN) expect(html).not.toContain(token);
  });
});
