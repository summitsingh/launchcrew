'use client';
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { api, unwrap } from '@/lib/api';
import type { components } from '@/lib/schema';

type Slot = components['schemas']['CalendarSlotOut'];
export type CalendarMode = 'week' | 'month';

export const SLOT_TYPES = ['feed_post', 'story', 'reel'] as const;
export const SLOT_STATUSES = ['drafted', 'checked', 'approved', 'exported', 'verified'] as const;

export function toISODate(value: Date): string {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, '0');
  const day = String(value.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

export function parseISODate(value: string): Date {
  const [year, month, day] = value.split('-').map(Number);
  return new Date(year, month - 1, day);
}

export function addDaysISO(value: string, delta: number): string {
  const next = parseISODate(value);
  next.setDate(next.getDate() + delta);
  return toISODate(next);
}

/** Seven consecutive days starting at the anchor date. */
export function buildWeekDays(anchorISO: string): string[] {
  return Array.from({ length: 7 }, (_, i) => addDaysISO(anchorISO, i));
}

/**
 * Month grid for the given year and month (1-12): leading null gaps for
 * weekday alignment followed by every day of the month. The grid holds
 * 28, 30, or 35 cells depending on the month layout.
 */
export function buildMonthGrid(year: number, month: number): (string | null)[] {
  const first = new Date(year, month - 1, 1);
  const daysInMonth = new Date(year, month, 0).getDate();
  const cells: (string | null)[] = [];
  for (let i = 0; i < first.getDay(); i++) cells.push(null);
  for (let day = 1; day <= daysInMonth; day++) cells.push(toISODate(new Date(year, month - 1, day)));
  while (cells.length % 7 !== 0) cells.push(null);
  return cells;
}

export function groupSlotsByDate(slots: Slot[]): Map<string, Slot[]> {
  const grouped = new Map<string, Slot[]>();
  for (const slot of slots) {
    const list = grouped.get(slot.slot_date) ?? [];
    list.push(slot);
    grouped.set(slot.slot_date, list);
  }
  return grouped;
}

export function slotsOfType(slots: Slot[], slotType: string): Slot[] {
  return slots.filter(slot => slot.slot_type === slotType);
}

function StatusBadge({ status }: { status: Slot['status'] }) {
  return <span className="badge" title={status}>{status}</span>;
}

function SlotCard({ slot }: { slot: Slot }) {
  return <article className="panel queue-card" data-slot-id={slot.id}>
    <p><strong>{slot.slot_type}</strong> <StatusBadge status={slot.status} /></p>
    <p className="hint">Pillar: {slot.pillar} · Format: {slot.format}</p>
    <p className="hint">{slot.run_id ? `Run ${slot.run_id}` : 'Unlinked slot'}{slot.campaign_id ? ` · Campaign ${slot.campaign_id} day ${slot.campaign_day ?? ''}`.trimEnd() : ''}</p>
  </article>;
}

function EmptySlotGap({ slotType, slotDate }: { slotType: string; slotDate: string }) {
  return <div className="panel empty" data-empty-slot={`${slotDate}:${slotType}`}><p className="hint">Empty {slotType} slot on {slotDate}. Nothing scheduled.</p></div>;
}

function DayCell({ slotDate, slots }: { slotDate: string; slots: Slot[] }) {
  return <section aria-label={`Calendar day ${slotDate}`}>
    <h3>{slotDate}</h3>
    {SLOT_TYPES.map(slotType => {
      const matches = slotsOfType(slots, slotType);
      if (matches.length === 0) return <EmptySlotGap key={slotType} slotType={slotType} slotDate={slotDate} />;
      return <div key={slotType}>{matches.map(slot => <SlotCard key={slot.id} slot={slot} />)}</div>;
    })}
  </section>;
}

export function PlaceCampaignOnCalendar({ campaignId }: { campaignId: string }) {
  const client = useQueryClient();
  const [startDate, setStartDate] = useState(() => toISODate(new Date()));
  const [notice, setNotice] = useState('');
  const place = useMutation({
    mutationFn: (start: string) => unwrap(api.POST('/api/calendar/campaigns/{campaign_id}/place', { params: { path: { campaign_id: campaignId } }, body: { start_date: start } })),
    onSuccess: slots => { setNotice(`Placed ${slots.length} slots on the calendar.`); client.invalidateQueries({ queryKey: ['calendar-slots'] }); },
    onError: (error: Error) => setNotice(error.message),
  });
  return <div className="queue-actions">
    <label htmlFor={`place-calendar-${campaignId}`}>Start date</label>
    <input id={`place-calendar-${campaignId}`} type="date" value={startDate} onChange={e => setStartDate(e.target.value)} />
    <Button onClick={() => place.mutate(startDate)} disabled={place.isPending || !startDate}>{place.isPending ? 'Placing...' : 'Place on calendar'}</Button>
    {notice && <p role="status">{notice}</p>}
  </div>;
}

export function AddSlotFromRun() {
  const client = useQueryClient();
  const [slotDate, setSlotDate] = useState(() => toISODate(new Date()));
  const [slotType, setSlotType] = useState<string>('feed_post');
  const [pillar, setPillar] = useState('product');
  const [runId, setRunId] = useState('');
  const [notice, setNotice] = useState('');
  const create = useMutation({
    mutationFn: () => unwrap(api.POST('/api/calendar/slots', { body: { slot_date: slotDate, slot_type: slotType as Slot['slot_type'], pillar, format: slotType, ...(runId.trim() ? { run_id: runId.trim() } : {}) } })),
    onSuccess: () => { setNotice('Slot added.'); client.invalidateQueries({ queryKey: ['calendar-slots'] }); },
    onError: (error: Error) => setNotice(error.message),
  });
  return <form className="panel" aria-label="Add calendar slot" onSubmit={e => { e.preventDefault(); create.mutate(); }}>
    <h2>Add a slot from a run</h2>
    <label htmlFor="calendar-slot-date">Date</label>
    <input id="calendar-slot-date" type="date" value={slotDate} onChange={e => setSlotDate(e.target.value)} />
    <label htmlFor="calendar-slot-type">Slot type</label>
    <select id="calendar-slot-type" value={slotType} onChange={e => setSlotType(e.target.value)}>
      {SLOT_TYPES.map(entry => <option key={entry} value={entry}>{entry}</option>)}
    </select>
    <label htmlFor="calendar-slot-pillar">Pillar</label>
    <input id="calendar-slot-pillar" value={pillar} maxLength={80} onChange={e => setPillar(e.target.value)} />
    <label htmlFor="calendar-slot-run">Run id (optional)</label>
    <input id="calendar-slot-run" value={runId} onChange={e => setRunId(e.target.value)} placeholder="run_..." />
    <Button type="submit" disabled={create.isPending}>{create.isPending ? 'Adding...' : 'Add slot'}</Button>
    {notice && <p role="status">{notice}</p>}
  </form>;
}

export function CalendarView() {
  const [mode, setMode] = useState<CalendarMode>('week');
  const [anchor, setAnchor] = useState(() => toISODate(new Date()));
  const days = mode === 'week' ? buildWeekDays(anchor) : buildMonthGrid(parseISODate(anchor).getFullYear(), parseISODate(anchor).getMonth() + 1).filter((entry): entry is string => entry !== null);
  const start = days[0];
  const end = days[days.length - 1];
  const slots = useQuery({ queryKey: ['calendar-slots', start, end], queryFn: () => unwrap(api.GET('/api/calendar/slots', { params: { query: { start_date: start, end_date: end } } })) });
  const grouped = groupSlotsByDate(slots.data ?? []);
  return <section aria-label="Calendar">
    <section className="panel"><h2>Content Calendar</h2><p>Nothing publishes automatically. Empty daily slots stay visible as gaps.</p>
      <div className="queue-actions" role="group" aria-label="Calendar mode">
        <Button variant={mode === 'week' ? undefined : 'outline'} onClick={() => setMode('week')} aria-pressed={mode === 'week'}>Week view</Button>
        <Button variant={mode === 'month' ? undefined : 'outline'} onClick={() => setMode('month')} aria-pressed={mode === 'month'}>Month view</Button>
      </div>
      <label htmlFor="calendar-anchor">Anchor date</label>
      <input id="calendar-anchor" type="date" value={anchor} onChange={e => setAnchor(e.target.value)} />
      <div className="queue-actions">
        <Button variant="outline" onClick={() => setAnchor(addDaysISO(anchor, mode === 'week' ? -7 : -30))}>Previous</Button>
        <Button variant="outline" onClick={() => setAnchor(addDaysISO(anchor, mode === 'week' ? 7 : 30))}>Next</Button>
      </div>
    </section>
    {slots.isPending && <p>Loading slots...</p>}
    {slots.error && <p role="alert">{slots.error.message}</p>}
    {days.map(slotDate => <DayCell key={slotDate} slotDate={slotDate} slots={grouped.get(slotDate) ?? []} />)}
    <AddSlotFromRun />
  </section>;
}
