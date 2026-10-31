import { describe, it, expect } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { CalendarView, ScheduleDefaultsPanel, ScheduleExportPanel, SlotScheduleCard, gateChecklistRows } from '../src/components/calendar-view';
import type { components } from '../src/lib/schema';

type Slot = components['schemas']['CalendarSlotOut'];

function slot(partial: Partial<Slot> & { id: string; slot_date: string }): Slot {
  return { slot_type: 'feed_post', pillar: 'product', format: 'feed_post', status: 'drafted', run_id: null, campaign_id: null, campaign_day: null, planned_time: '09:00', schedule_state: 'draft', selected_channels: [], approved_channels: [], ...partial };
}

function provider(children: React.ReactNode) {
  return renderToStaticMarkup(<QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>);
}

describe('schedule validate gate rows', () => {
  it('marks every condition failed when no evaluation is available', () => {
    const rows = gateChecklistRows(undefined);
    expect(rows.map(row => row.code)).toEqual(['pack_not_approved', 'format_check_failed', 'unapproved_channel_variants']);
    expect(rows.every(row => row.passed === false)).toBe(true);
  });
  it('passes each condition from the backend checks', () => {
    const rows = gateChecklistRows({ ready_eligible: false, failing_conditions: ['pack_not_approved'], checks: { pack_approved: false, format_passed: true, variants_approved: false } });
    expect(rows.find(row => row.code === 'pack_not_approved')?.passed).toBe(false);
    expect(rows.find(row => row.code === 'format_check_failed')?.passed).toBe(true);
    expect(rows.find(row => row.code === 'unapproved_channel_variants')?.passed).toBe(false);
  });
  it('passes all three conditions for a ready slot', () => {
    const rows = gateChecklistRows({ ready_eligible: true, failing_conditions: [], checks: { pack_approved: true, format_passed: true, variants_approved: true } });
    expect(rows.every(row => row.passed)).toBe(true);
  });
});

describe('schedule defaults panel', () => {
  it('shows daily default time controls for every slot type', () => {
    const html = provider(<ScheduleDefaultsPanel />);
    expect(html).toContain('data-testid="schedule-defaults-panel"');
    for (const slotType of ['feed_post', 'story', 'reel']) {
      expect(html).toContain(`schedule-default-${slotType}`);
      expect(html).toContain(`${slotType} default`);
    }
    expect(html).toContain('Save defaults');
    expect(html).toContain('Planning only');
  });
});

describe('slot schedule card', () => {
  it('shows planned time, channel selection, gate checklist, and mark ready with no override', () => {
    const html = provider(<SlotScheduleCard slot={slot({ id: 'slot_1', slot_date: '2026-11-03', planned_time: '10:15' })} />);
    expect(html).toContain('slot-time-slot_1');
    expect(html).toContain('Planned time');
    for (const channel of ['x', 'linkedin', 'instagram', 'email', 'facebook', 'tiktok', 'shopify']) {
      expect(html).toContain(channel);
      expect(html).toContain(`Approve ${channel}`);
    }
    expect(html).toContain('slot-validate-checklist');
    expect(html).toContain('Validate gate');
    expect(html).toContain('no override');
    expect(html).toContain('data-testid="slot-mark-ready-btn"');
    expect(html).toContain('Mark Ready');
    expect(html).not.toContain('Override');
    expect(html).not.toContain('Force ready');
  });
});

describe('schedule export panel', () => {
  it('shows the export button and JSON preview', () => {
    const html = provider(<ScheduleExportPanel />);
    expect(html).toContain('data-testid="calendar-export-schedule-btn"');
    expect(html).toContain('Export validated schedule JSON');
    expect(html).toContain('data-testid="calendar-schedule-export-json"');
    expect(html).toContain('nothing is submitted anywhere');
  });
  it('appears on the calendar alongside the defaults panel', () => {
    const html = provider(<CalendarView />);
    expect(html).toContain('data-testid="schedule-defaults-panel"');
    expect(html).toContain('data-testid="calendar-export-schedule-btn"');
    expect(html).toContain('data-testid="calendar-schedule-export-json"');
  });
});
