import { describe, it, expect } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { CalendarView } from '../src/components/calendar-view';
import {
  DeliveryAttemptsList,
  DeliveryRow,
  DeliveryStateBadge,
  VerificationBoard,
  type Delivery,
} from '../src/components/verification-board';

function provider(children: React.ReactNode) {
  return renderToStaticMarkup(<QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>);
}

function delivery(partial: Partial<Delivery> & { id: string; slot_id: string; channel: string }): Delivery {
  return {
    delivery_state: 'not_posted', live_url: null, match_kind: null,
    differing_field: null, failure_reason: null, attempts: [], ...partial,
  };
}

const verified = delivery({
  id: 'del_1', slot_id: 'slot_1', channel: 'x', delivery_state: 'verified',
  live_url: 'https://example.com/posts/1', match_kind: 'exact',
  attempts: [
    { attempt_number: 1, timestamp: '2026-11-04T10:00:00+00:00', state: 'posted', live_url: 'https://example.com/posts/1', match_kind: null, differing_field: null, reason: null, live_text_excerpt: '' },
    { attempt_number: 2, timestamp: '2026-11-04T10:01:00+00:00', state: 'verified', live_url: 'https://example.com/posts/1', match_kind: 'exact', differing_field: null, reason: null, live_text_excerpt: 'hello' },
  ],
});

const mismatched = delivery({
  id: 'del_2', slot_id: 'slot_1', channel: 'instagram', delivery_state: 'failed',
  live_url: 'https://example.com/posts/2', match_kind: 'mismatch',
  differing_field: 'text', failure_reason: 'Live post mismatch on field: text',
  attempts: [
    { attempt_number: 1, timestamp: '2026-11-04T10:00:00+00:00', state: 'posted', live_url: 'https://example.com/posts/2', match_kind: null, differing_field: null, reason: null, live_text_excerpt: '' },
    { attempt_number: 2, timestamp: '2026-11-04T10:02:00+00:00', state: 'failed', live_url: 'https://example.com/posts/2', match_kind: 'mismatch', differing_field: 'text', reason: 'Live post mismatch on field: text', live_text_excerpt: 'other' },
  ],
});

describe('delivery state badges', () => {
  it('renders every delivery state', () => {
    for (const state of ['not_posted', 'posted', 'verified', 'failed']) {
      const html = provider(<DeliveryStateBadge state={state} />);
      expect(html).toContain(`data-delivery-state="${state}"`);
      expect(html).toContain(state);
    }
  });
});

describe('delivery attempts list', () => {
  it('shows both events in chronological order', () => {
    const html = provider(<DeliveryAttemptsList attempts={mismatched.attempts} />);
    expect(html).toContain('data-testid="delivery-attempts-list"');
    const postedAt = html.indexOf('posted');
    const failedAt = html.indexOf('failed');
    expect(postedAt).toBeGreaterThan(-1);
    expect(failedAt).toBeGreaterThan(postedAt);
    expect(html).toContain('Live post mismatch on field: text');
  });
});

describe('delivery row', () => {
  it('shows the mismatch state with the differing field named', () => {
    const html = provider(<DeliveryRow delivery={mismatched} />);
    expect(html).toContain('data-delivery-state="failed"');
    expect(html).toContain('mismatch');
    expect(html).toContain('Mismatch on field: text');
    expect(html).toContain('Live post mismatch on field: text');
    expect(html).toContain('data-testid="delivery-attempts-list"');
    expect(html).toContain('Live URL');
    expect(html).toContain('Mark posted');
    expect(html).toContain('Verify');
  });
  it('shows the log outcome form only for verified rows', () => {
    const verifiedHtml = provider(<DeliveryRow delivery={verified} />);
    expect(verifiedHtml).toContain('data-delivery-state="verified"');
    expect(verifiedHtml).toContain('match: exact');
    expect(verifiedHtml).toContain('Log outcome');
    expect(verifiedHtml).toContain('Posted date');
    const failedHtml = provider(<DeliveryRow delivery={mismatched} />);
    expect(failedHtml).not.toContain('Log outcome');
  });
});

describe('verification board', () => {
  it('renders one row per channel per slot with board test id', () => {
    const html = provider(<VerificationBoard rows={[verified, mismatched]} />);
    expect(html).toContain('data-testid="verification-board"');
    expect(html).toContain('Cross-post verification board');
    expect(html).toContain('data-delivery-row="slot_1:x"');
    expect(html).toContain('data-delivery-row="slot_1:instagram"');
    expect(html).toContain('data-testid="delivery-attempts-list"');
  });
  it('appears on the calendar view', () => {
    const html = provider(<CalendarView />);
    expect(html).toContain('data-testid="verification-board"');
  });
});
