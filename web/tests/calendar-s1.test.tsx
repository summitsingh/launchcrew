import { describe, it, expect } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AddSlotFromRun, CalendarView, PlaceCampaignOnCalendar, buildMonthGrid, buildWeekDays, groupSlotsByDate } from '../src/components/calendar-view';
import type { components } from '../src/lib/schema';

type Slot = components['schemas']['CalendarSlotOut'];

function slot(partial: Partial<Slot> & { id: string; slot_date: string }): Slot {
  return { slot_type: 'feed_post', pillar: 'product', format: 'feed_post', status: 'drafted', run_id: null, campaign_id: null, campaign_day: null, ...partial };
}

function provider(children: React.ReactNode) {
  return renderToStaticMarkup(<QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>);
}

describe('calendar week and month views', () => {
  it('builds a 7-day week from the anchor date', () => {
    expect(buildWeekDays('2026-11-02')).toEqual([
      '2026-11-02', '2026-11-03', '2026-11-04', '2026-11-05',
      '2026-11-06', '2026-11-07', '2026-11-08',
    ]);
  });
  it('builds week-aligned month grids covering 28- and 30-day months', () => {
    expect(buildMonthGrid(2026, 2)).toHaveLength(28);
    expect(buildMonthGrid(2026, 11)).toHaveLength(35);
    expect(buildMonthGrid(2026, 1)).toHaveLength(35);
    for (const [year, month, days] of [[2026, 2, 28], [2026, 11, 30], [2026, 1, 31]] as const) {
      const cells = buildMonthGrid(year, month).filter((entry): entry is string => entry !== null);
      expect(cells).toHaveLength(days);
      expect(cells[0]).toBe(`${year}-${String(month).padStart(2, '0')}-01`);
    }
  });
  it('renders week and month toggle controls', () => {
    const html = provider(<CalendarView />);
    for (const label of ['Content Calendar', 'Week view', 'Month view', 'Anchor date', 'Add a slot from a run']) expect(html).toContain(label);
  });
  it('shows visible empty slot gaps for unfilled feed, story, and reel slots', () => {
    const html = provider(<CalendarView />);
    for (const slotType of ['feed_post', 'story', 'reel']) expect(html).toContain(`Empty ${slotType} slot`);
  });
  it('groups slots by date so each day shows its own pillar, format, link, and status', () => {
    const slots: Slot[] = [
      slot({ id: 'slot_a', slot_date: '2026-11-02', slot_type: 'feed_post', pillar: 'product', status: 'approved', run_id: 'run_1', campaign_id: 'camp_1', campaign_day: 1 }),
      slot({ id: 'slot_b', slot_date: '2026-11-02', slot_type: 'story', pillar: 'founder-story', format: 'story', status: 'checked', run_id: 'run_2' }),
    ];
    const grouped = groupSlotsByDate(slots);
    expect(grouped.get('2026-11-02')).toHaveLength(2);
    expect(grouped.get('2026-11-03')).toBeUndefined();
  });
  it('places a 7-day campaign in one click and adds a slot from a run', () => {
    const placeHtml = provider(<PlaceCampaignOnCalendar campaignId="camp_demo" />);
    expect(placeHtml).toContain('Place on calendar');
    expect(placeHtml).toContain('Start date');
    const addHtml = provider(<AddSlotFromRun />);
    for (const label of ['Add a slot from a run', 'feed_post', 'story', 'reel', 'Run id']) expect(addHtml).toContain(label);
  });
});
