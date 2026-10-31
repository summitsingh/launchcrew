'use client';
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { api, unwrap } from '@/lib/api';
import type { components } from '@/lib/schema';

export type RunOutcome = components['schemas']['OutcomeOut'];
export type OutcomeChannel = RunOutcome['channel'];

export const OUTCOME_CHANNELS = [
  'email',
  'facebook',
  'in_person',
  'instagram',
  'linkedin',
  'other',
  'phone',
  'sms',
  'web',
  'x',
] as const;

export const OUTCOME_MAX_COUNT = 1000000;
export const OUTCOME_MAX_NOTE_LENGTH = 500;
export const OUTCOME_EMPTY = 'No owner-reported outcomes yet for this run.';
export const OUTCOME_SELF_REPORT = 'Owner self-report, not provider-measured';
export const OUTCOME_PROVENANCE_NOTE =
  'Owner-entered only. These rows are self-reported and never provider-measured. No ROI is computed, nothing auto-posts, and nothing is seeded.';

/** Exact YYYY-MM-DD real calendar date, mirroring launchcrew.outcome_log. */
export function isValidOutcomeDate(value: string): boolean {
  if (typeof value !== 'string' || value.length !== 10) return false;
  if (value[4] !== '-' || value[7] !== '-') return false;
  const parts = value.split('-');
  if (parts.length !== 3) return false;
  if (parts[0].length !== 4 || parts[1].length !== 2 || parts[2].length !== 2) return false;
  for (const part of parts) {
    if (!/^[0-9]+$/.test(part)) return false;
    for (const ch of part) {
      if (ch.charCodeAt(0) > 127) return false;
    }
  }
  const year = Number(parts[0]);
  const month = Number(parts[1]);
  const day = Number(parts[2]);
  if (!Number.isInteger(year) || !Number.isInteger(month) || !Number.isInteger(day)) return false;
  const probe = new Date(Date.UTC(year, month - 1, day));
  return (
    probe.getUTCFullYear() === year &&
    probe.getUTCMonth() === month - 1 &&
    probe.getUTCDate() === day
  );
}

/** Type-exact bounded count: integer 0..1000000, booleans rejected. */
export function isValidOutcomeCount(value: unknown): boolean {
  if (typeof value !== 'number') return false;
  if (!Number.isInteger(value)) return false;
  return value >= 0 && value <= OUTCOME_MAX_COUNT;
}

/** Parse a typed number input into a bounded count, or null when invalid. */
export function parseOutcomeCount(raw: string): number | null {
  if (typeof raw !== 'string' || !raw.trim()) return null;
  if (!/^[0-9]+$/.test(raw.trim())) return null;
  const value = Number(raw.trim());
  if (!Number.isSafeInteger(value)) return null;
  if (value < 0 || value > OUTCOME_MAX_COUNT) return null;
  return value;
}

/** Single-line owner note: 1..500 chars, no whitespace-only, no controls. */
export function isValidOutcomeNote(value: string): boolean {
  if (typeof value !== 'string') return false;
  if (!value.trim()) return false;
  if (value.length < 1 || value.length > OUTCOME_MAX_NOTE_LENGTH) return false;
  for (const ch of value) {
    const code = ch.charCodeAt(0);
    if (code < 32 || code === 127) return false;
  }
  return true;
}

export type OutcomeDraft = {
  channel: string;
  posted_date: string;
  likes: string;
  comments: string;
  clicks: string;
  sales: string;
  note: string;
};

/** Human-readable validation errors for a draft, empty when saveable. */
export function validateOutcomeDraft(draft: OutcomeDraft): string[] {
  const errors: string[] = [];
  if (!(OUTCOME_CHANNELS as readonly string[]).includes(draft.channel)) {
    errors.push('Channel must be one of the listed owner channels.');
  }
  if (!isValidOutcomeDate(draft.posted_date)) {
    errors.push('Posted date must be a real calendar date in YYYY-MM-DD format.');
  }
  for (const key of ['likes', 'comments', 'clicks', 'sales'] as const) {
    if (parseOutcomeCount(draft[key]) === null) {
      errors.push(`${key} must be a whole number from 0 to ${OUTCOME_MAX_COUNT}.`);
    }
  }
  if (!isValidOutcomeNote(draft.note)) {
    errors.push(
      `Note must be 1 to ${OUTCOME_MAX_NOTE_LENGTH} characters, single line, with no control characters.`,
    );
  }
  return errors;
}

/** One-line metric summary from persisted values only. */
export function outcomeSummary(outcome: Pick<RunOutcome, 'likes' | 'comments' | 'clicks' | 'sales'>): string {
  return `likes ${outcome.likes} · comments ${outcome.comments} · clicks ${outcome.clicks} · sales ${outcome.sales}`;
}

export function OutcomeList({ outcomes }: { outcomes: RunOutcome[] }) {
  if (outcomes.length === 0) {
    return <p className="hint">{OUTCOME_EMPTY}</p>;
  }
  return (
    <ul className="scout-list">
      {outcomes.map(item => (
        <li key={item.id} className="scout-fact">
          <div className="scout-row">
            <strong>
              {item.channel} · {item.posted_date} · Exported revision {item.export_revision}
            </strong>
            <span className="badge approved">{OUTCOME_SELF_REPORT}</span>
          </div>
          <p className="hint">{outcomeSummary(item)}</p>
          <p className="draft">{item.note}</p>
          <p className="hint">
            Provenance: {item.provenance} · Actor: {item.actor} · Logged: {item.created_at}
          </p>
        </li>
      ))}
    </ul>
  );
}

const EMPTY_DRAFT: OutcomeDraft = {
  channel: 'email',
  posted_date: '',
  likes: '0',
  comments: '0',
  clicks: '0',
  sales: '0',
  note: '',
};

export function OutcomeForm({ runId }: { runId: string }) {
  const client = useQueryClient();
  const [draft, setDraft] = useState<OutcomeDraft>(EMPTY_DRAFT);
  const [reviewing, setReviewing] = useState(false);
  const [notice, setNotice] = useState('');
  const errors = validateOutcomeDraft(draft);
  const saveable = errors.length === 0;
  const save = useMutation({
    mutationFn: () => {
      const body = {
        channel: draft.channel as OutcomeChannel,
        posted_date: draft.posted_date,
        likes: parseOutcomeCount(draft.likes) as number,
        comments: parseOutcomeCount(draft.comments) as number,
        clicks: parseOutcomeCount(draft.clicks) as number,
        sales: parseOutcomeCount(draft.sales) as number,
        note: draft.note,
      };
      return unwrap(api.POST('/api/runs/{run_id}/outcomes', { params: { path: { run_id: runId } }, body }));
    },
    onSuccess: saved => {
      setDraft(EMPTY_DRAFT);
      setReviewing(false);
      setNotice(`Saved owner self-report for exported revision ${saved.export_revision}.`);
      client.invalidateQueries({ queryKey: ['run-outcomes', runId] });
    },
  });

  const set = (key: keyof OutcomeDraft) => (value: string) => {
    setDraft(current => ({ ...current, [key]: value }));
    setNotice('');
    save.reset();
  };

  if (reviewing) {
    return (
      <div>
        <h4>Review before save</h4>
        <p className="hint">
          {draft.channel} · {draft.posted_date} · likes {draft.likes} · comments {draft.comments} · clicks{' '}
          {draft.clicks} · sales {draft.sales}
        </p>
        <p className="draft">{draft.note}</p>
        <p className="hint">{OUTCOME_SELF_REPORT}. Saving stores one immutable row for the current exported revision.</p>
        {save.error && <p role="alert">{(save.error as Error).message}</p>}
        <div className="queue-actions">
          <Button onClick={() => save.mutate()} disabled={save.isPending || !saveable}>
            {save.isPending ? 'Saving...' : 'Confirm and save'}
          </Button>
          <Button variant="outline" onClick={() => { setReviewing(false); save.reset(); }} disabled={save.isPending}>
            Back to edit
          </Button>
        </div>
      </div>
    );
  }

  return (
    <form
      onSubmit={e => {
        e.preventDefault();
        if (!saveable) return;
        save.reset();
        setReviewing(true);
      }}
    >
      <h4>Log an owner self-report</h4>
      <p className="hint">
        Typed and bounded. Review the values before save. New logs need the latest revision approved and
        exported; historical rows keep their exported revision.
      </p>
      <label htmlFor={`outcome-channel-${runId}`}>Channel</label>
      <select
        id={`outcome-channel-${runId}`}
        value={draft.channel}
        onChange={e => set('channel')(e.target.value)}
      >
        {OUTCOME_CHANNELS.map(value => (
          <option key={value} value={value}>
            {value}
          </option>
        ))}
      </select>
      <label htmlFor={`outcome-date-${runId}`}>Posted date (YYYY-MM-DD)</label>
      <input
        id={`outcome-date-${runId}`}
        type="date"
        required
        value={draft.posted_date}
        onChange={e => set('posted_date')(e.target.value)}
      />
      <div className="field-grid">
        {(['likes', 'comments', 'clicks', 'sales'] as const).map(key => (
          <div key={key}>
            <label htmlFor={`outcome-${key}-${runId}`}>{key}</label>
            <input
              id={`outcome-${key}-${runId}`}
              type="number"
              required
              min={0}
              max={OUTCOME_MAX_COUNT}
              step={1}
              inputMode="numeric"
              value={draft[key]}
              onChange={e => set(key)(e.target.value)}
            />
          </div>
        ))}
      </div>
      <label htmlFor={`outcome-note-${runId}`}>Note (single line, up to 500 characters)</label>
      <textarea
        id={`outcome-note-${runId}`}
        required
        rows={2}
        maxLength={OUTCOME_MAX_NOTE_LENGTH}
        value={draft.note}
        onChange={e => set('note')(e.target.value)}
      />
      {errors.length > 0 && (
        <div role="alert" className="message error">
          <ul>
            {errors.map((text, i) => (
              <li key={i}>{text}</li>
            ))}
          </ul>
        </div>
      )}
      {save.error && <p role="alert">{(save.error as Error).message}</p>}
      {notice && <p role="status">{notice}</p>}
      <Button type="submit" disabled={!saveable}>
        Review outcome
      </Button>
    </form>
  );
}

export function RunOutcomesSection({ runId, label }: { runId: string; label: string }) {
  const outcomes = useQuery({
    queryKey: ['run-outcomes', runId],
    queryFn: () => unwrap(api.GET('/api/runs/{run_id}/outcomes', { params: { path: { run_id: runId } } })),
    enabled: !!runId,
  });
  return (
    <section className="panel" aria-label={`Owner-reported outcomes for ${label}`}>
      <p className="eyebrow">OWNER-REPORTED OUTCOMES</p>
      <h2 title={runId}>
        {label}: {runId.length <= 12 ? runId : `${runId.slice(0, 8)}...`}
      </h2>
      <p className="hint">
        <span className="badge approved">{OUTCOME_SELF_REPORT}</span> {OUTCOME_PROVENANCE_NOTE}
      </p>
      {outcomes.isPending && <p>Loading owner self-reports...</p>}
      {outcomes.error && <p role="alert">{(outcomes.error as Error).message}</p>}
      {outcomes.data && <OutcomeList outcomes={outcomes.data as RunOutcome[]} />}
      <OutcomeForm runId={runId} />
    </section>
  );
}
