import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { CalendarView } from '../src/components/calendar-view';
import {
  AnalyticsPullPanel,
  SlotOutcomeBadge,
  badgeSummaryText,
  channelSummaryText,
  metricDisplay,
  type AnalyticsPull,
} from '../src/components/analytics-pull-panel';

function provider(children: React.ReactNode) {
  return renderToStaticMarkup(<QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>);
}

function pull(partial: Partial<AnalyticsPull> & { id: string }): AnalyticsPull {
  return {
    slot_id: 'slot_1',
    channel: 'instagram',
    run_id: 'run_1',
    outcome_id: 'out_1',
    source_label: 'instagram_graph_api',
    refresh_mode: 'manual',
    fetched_at: '2026-11-04T09:00:00+00:00',
    metrics: { reach: 1240, likes: 88, comments: 12, clicks: 'not reported', shares: 3 },
    reported_metrics: ['reach', 'likes', 'comments', 'shares'],
    unreported_metrics: ['clicks'],
    ...partial,
  } as AnalyticsPull;
}

describe('metric honesty helpers', () => {
  it('keeps integers and renders anything else as not reported', () => {
    expect(metricDisplay(88)).toBe('88');
    expect(metricDisplay(0)).toBe('0');
    expect(metricDisplay('not reported')).toBe('not reported');
    expect(metricDisplay(null)).toBe('not reported');
    expect(metricDisplay(undefined)).toBe('not reported');
  });
  it('summarizes a channel with not reported markers and never a fake zero', () => {
    const summary = channelSummaryText('instagram', { reach: 1240, likes: 88, clicks: 'not reported' });
    expect(summary).toBe('instagram: 1240 reach, 88 likes, comments: not reported, clicks: not reported, shares: not reported');
    expect(summary).toContain('clicks: not reported');
    expect(summary).not.toMatch(/(^| )0 (reach|likes|comments|clicks|shares)/);
  });
  it('joins channel badges into one slot summary', () => {
    const summary = badgeSummaryText([
      { channel: 'instagram', metrics: { reach: 1240, clicks: 'not reported' } },
      { channel: 'x', metrics: { reach: 400, clicks: 9 } },
    ]);
    expect(summary).toContain('instagram: 1240 reach');
    expect(summary).toContain('clicks: not reported');
    expect(summary).toContain('x: 400 reach');
    expect(summary).toContain(' | ');
  });
});

describe('slot outcome badge', () => {
  it('renders the badge with source, fetch time, and not reported metrics', () => {
    const html = provider(<SlotOutcomeBadge slotId="slot_1" badge={{
      has_outcomes: true,
      channel_badges: [{
        channel: 'instagram',
        source_label: 'instagram_graph_api',
        fetched_at: '2026-11-04T09:00:00+00:00',
        refresh_mode: 'manual',
        metrics: { reach: 1240, likes: 88, comments: 12, clicks: 'not reported', shares: 3 },
      }],
      summary_text: 'instagram: 1240 reach, 88 likes, 12 comments, clicks: not reported, 3 shares',
    }} />);
    expect(html).toContain('data-testid="slot-outcome-badge-slot_1"');
    expect(html).toContain('instagram_graph_api');
    expect(html).toContain('2026-11-04T09:00:00+00:00');
    expect(html).toContain('clicks: not reported');
    expect(html).toContain('1240');
  });
  it('renders nothing without outcomes', () => {
    expect(provider(<SlotOutcomeBadge slotId="slot_9" badge={null} />)).toBe('');
    expect(provider(<SlotOutcomeBadge slotId="slot_9" badge={{ has_outcomes: false, channel_badges: [], summary_text: '' }} />)).toBe('');
  });
});

describe('analytics pull panel', () => {
  it('renders manual and scheduled refresh controls', () => {
    const html = provider(<AnalyticsPullPanel slotId="slot_1" channel="instagram" pulls={[pull({ id: 'apull_1' })]} />);
    expect(html).toContain('data-testid="analytics-pull-panel"');
    expect(html).toContain('data-testid="analytics-manual-refresh-btn"');
    expect(html).toContain('data-testid="analytics-scheduled-refresh-btn"');
    expect(html).toContain('Manual refresh');
    expect(html).toContain('Run scheduled refresh');
  });
  it('inspects per-post pulls with source, fetch time, and not reported markers', () => {
    const html = provider(<AnalyticsPullPanel slotId="slot_1" channel="instagram" pulls={[pull({ id: 'apull_1' })]} />);
    expect(html).toContain('instagram_graph_api');
    expect(html).toContain('2026-11-04T09:00:00+00:00');
    expect(html).toContain('clicks: not reported');
  });
  it('notes the empty state before any pull', () => {
    const html = provider(<AnalyticsPullPanel slotId="slot_1" channel="instagram" pulls={[]} />);
    expect(html).toContain('No provider pulls yet');
  });
});

describe('calendar view integration', () => {
  it('embeds the analytics pull panel', () => {
    const html = provider(<CalendarView />);
    expect(html).toContain('data-testid="analytics-pull-panel"');
  });
});
