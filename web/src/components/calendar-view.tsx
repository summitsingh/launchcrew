'use client';
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { api, unwrap } from '@/lib/api';
import { FormatLibraryPanel } from '@/components/format-library';
import { AnalyticsPullPanel, SlotOutcomeBadge } from '@/components/analytics-pull-panel';
import { MediaLibraryPanel } from '@/components/media-library';
import { ViralGeneratorPanel } from '@/components/viral-generator-panel';
import { PublishExecutorPanel } from '@/components/publish-executor-panel';
import { VerificationBoard } from '@/components/verification-board';
import type { components } from '@/lib/schema';

type Slot = components['schemas']['CalendarSlotOut'];
export type CalendarMode = 'week' | 'month';

export const SLOT_TYPES = ['feed_post', 'story', 'reel'] as const;
export const SLOT_STATUSES = ['drafted', 'checked', 'approved', 'exported', 'verified'] as const;
export const SCHEDULE_CHANNELS = ['x', 'linkedin', 'instagram', 'email', 'facebook', 'tiktok', 'shopify'] as const;

export type GateEvaluation = {
  ready_eligible?: boolean;
  failing_conditions?: string[];
  checks?: { pack_approved?: boolean; format_passed?: boolean; variants_approved?: boolean };
  details?: string[];
  unapproved_channels?: string[];
  format_reason?: string | null;
};

/** Validate-gate checklist rows: one row per mandatory condition, no override. */
export function gateChecklistRows(evaluation: GateEvaluation | undefined): { code: string; label: string; passed: boolean }[] {
  const checks = evaluation?.checks ?? {};
  return [
    { code: 'pack_not_approved', label: 'Pack is approved', passed: checks.pack_approved === true },
    { code: 'format_check_failed', label: 'Format check passed', passed: checks.format_passed === true },
    { code: 'unapproved_channel_variants', label: 'Channel variants approved', passed: checks.variants_approved === true },
  ];
}

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
    <SlotOutcomeBadge badge={slot.outcome_badge ?? null} slotId={slot.id} />
    <SlotScheduleCard slot={slot} />
  </article>;
}

export function ScheduleDefaultsPanel() {
  const client = useQueryClient();
  const [times, setTimes] = useState<Record<string, string>>({});
  const [notice, setNotice] = useState('');
  const defaults = useQuery({ queryKey: ['schedule-defaults'], queryFn: () => unwrap(api.GET('/api/calendar/schedule-defaults')) });
  const saved = (defaults.data as { defaults?: Record<string, string> } | undefined)?.defaults ?? {};
  const save = useMutation({
    mutationFn: () => {
      const body: Record<string, string> = {};
      for (const slotType of SLOT_TYPES) body[slotType] = times[slotType] ?? saved[slotType] ?? '';
      return unwrap(api.PUT('/api/calendar/schedule-defaults', { body: { defaults: body } }));
    },
    onSuccess: () => { setNotice('Defaults saved.'); setTimes({}); client.invalidateQueries({ queryKey: ['schedule-defaults'] }); client.invalidateQueries({ queryKey: ['calendar-slots'] }); },
    onError: (error: Error) => setNotice(error.message),
  });
  return <section className="panel" data-testid="schedule-defaults-panel" aria-label="Schedule defaults">
    <h2>Daily default times</h2>
    <p className="hint">Planning only. New slots start at the daily default for their type.</p>
    {SLOT_TYPES.map(slotType => <p key={slotType}>
      <label htmlFor={`schedule-default-${slotType}`}>{slotType} default</label>
      <input id={`schedule-default-${slotType}`} type="time" value={times[slotType] ?? saved[slotType] ?? ''} onChange={e => setTimes(prev => ({ ...prev, [slotType]: e.target.value }))} />
    </p>)}
    <div className="queue-actions">
      <Button onClick={() => save.mutate()} disabled={save.isPending}>{save.isPending ? 'Saving...' : 'Save defaults'}</Button>
    </div>
    {notice && <p role="status">{notice}</p>}
  </section>;
}

export function SlotScheduleCard({ slot }: { slot: Slot }) {
  const client = useQueryClient();
  const [notice, setNotice] = useState('');
  const [plannedTime, setPlannedTime] = useState(slot.planned_time ?? '09:00');
  const [selected, setSelected] = useState<string[]>(slot.selected_channels ?? []);
  const gate = useQuery({
    queryKey: ['slot-gate', slot.id],
    queryFn: () => unwrap(api.GET('/api/calendar/slots/{slot_id}/validate-ready', { params: { path: { slot_id: slot.id } } })),
  });
  const evaluation = gate.data as GateEvaluation | undefined;
  const rows = gateChecklistRows(evaluation);
  const refresh = () => { client.invalidateQueries({ queryKey: ['calendar-slots'] }); client.invalidateQueries({ queryKey: ['slot-gate', slot.id] }); };
  const saveSchedule = useMutation({
    mutationFn: () => unwrap(api.PATCH('/api/calendar/slots/{slot_id}/schedule', { params: { path: { slot_id: slot.id } }, body: { planned_time: plannedTime, selected_channels: selected } })),
    onSuccess: () => { setNotice('Schedule saved.'); refresh(); },
    onError: (error: Error) => setNotice(error.message),
  });
  const approveChannel = useMutation({
    mutationFn: (channel: string) => unwrap(api.POST('/api/calendar/slots/{slot_id}/approve-channels', { params: { path: { slot_id: slot.id } }, body: { channels: [channel] } })),
    onSuccess: () => { setNotice('Channel variant approved.'); refresh(); },
    onError: (error: Error) => setNotice(error.message),
  });
  const markReady = useMutation({
    mutationFn: () => unwrap(api.POST('/api/calendar/slots/{slot_id}/mark-ready', { params: { path: { slot_id: slot.id } } })),
    onSuccess: () => { setNotice('Slot marked Ready.'); refresh(); },
    onError: (error: Error) => setNotice(error.message),
  });
  const toggleChannel = (channel: string) => setSelected(prev => prev.includes(channel) ? prev.filter(entry => entry !== channel) : [...prev, channel]);
  return <div className="queue-card" data-slot-schedule={slot.id}>
    <p className="hint">Planned at {slot.planned_time ?? '09:00'} · {slot.schedule_state ?? 'draft'}</p>
    <p>
      <label htmlFor={`slot-time-${slot.id}`}>Planned time</label>
      <input id={`slot-time-${slot.id}`} type="time" value={plannedTime} onChange={e => setPlannedTime(e.target.value)} />
    </p>
    <fieldset>
      <legend>Channels</legend>
      {SCHEDULE_CHANNELS.map(channel => <p key={channel}>
        <label>
          <input type="checkbox" checked={selected.includes(channel)} onChange={() => toggleChannel(channel)} />
          {channel}
        </label>
        <Button variant="outline" onClick={() => approveChannel.mutate(channel)} disabled={approveChannel.isPending}>Approve {channel}</Button>
      </p>)}
    </fieldset>
    <div className="queue-actions">
      <Button variant="outline" onClick={() => saveSchedule.mutate()} disabled={saveSchedule.isPending}>{saveSchedule.isPending ? 'Saving...' : 'Save schedule'}</Button>
    </div>
    <div data-testid="slot-validate-checklist" aria-label="Validate gate">
      <p><strong>Validate gate</strong> (no override)</p>
      {gate.isPending && <p className="hint">Checking validate gate...</p>}
      {gate.error && <p role="alert">{gate.error.message}</p>}
      {evaluation && <ul>
        {rows.map(row => <li key={row.code}>{row.passed ? 'Pass' : 'Fail'}: {row.label} ({row.code})</li>)}
        {(evaluation.details ?? []).map(detail => <li key={detail}>{detail}</li>)}
      </ul>}
    </div>
    <div className="queue-actions">
      <Button data-testid="slot-mark-ready-btn" data-slot-id={slot.id} onClick={() => markReady.mutate()} disabled={markReady.isPending}>{markReady.isPending ? 'Marking...' : 'Mark Ready'}</Button>
    </div>
    {notice && <p role="status">{notice}</p>}
  </div>;
}

export function ScheduleExportPanel() {
  const [document, setDocument] = useState<{ ready_slots?: unknown[] } | null>(null);
  const [notice, setNotice] = useState('');
  const runExport = useMutation({
    mutationFn: async () => (await unwrap(api.GET('/api/calendar/schedule-export'))) as { ready_slots?: unknown[] },
    onSuccess: (doc: { ready_slots?: unknown[] }) => { setDocument(doc); setNotice(`Exported ${(doc.ready_slots ?? []).length} ready slots. Nothing was published.`); },
    onError: (error: Error) => setNotice(error.message),
  });
  return <section className="panel" aria-label="Schedule export">
    <h2>Validated schedule export</h2>
    <p className="hint">Planning only. The JSON hand-off lists Ready slots; nothing is submitted anywhere.</p>
    <div className="queue-actions">
      <Button data-testid="calendar-export-schedule-btn" onClick={() => runExport.mutate()} disabled={runExport.isPending}>{runExport.isPending ? 'Exporting...' : 'Export validated schedule JSON'}</Button>
    </div>
    {notice && <p role="status">{notice}</p>}
    <pre data-testid="calendar-schedule-export-json">{document ? JSON.stringify(document, null, 2) : 'No export yet.'}</pre>
  </section>;
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
  const formats = useQuery({ queryKey: ['formats'], queryFn: () => unwrap(api.GET('/api/formats')) });
  const capabilities = useQuery({ queryKey: ['channel-capabilities'], queryFn: () => unwrap(api.GET('/api/channel-capabilities')) });
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
    <ScheduleDefaultsPanel />
    <ScheduleExportPanel />
    <AnalyticsPullPanel />
    <MediaLibraryPanel />
    <ViralGeneratorPanel />
    <PublishExecutorPanel />
    <VerificationBoard />
    <AddSlotFromRun />
    <FormatLibraryPanel
      formats={(formats.data ?? []) as { format: string; label: string; rule: string }[]}
      capabilities={(capabilities.data ?? []) as { channel: string; allowed_formats: string[]; caption_limit: number; media_constraints: { aspect_ratios: string[]; min_frames: number; max_frames: number } }[]}
    />
  </section>;
}
