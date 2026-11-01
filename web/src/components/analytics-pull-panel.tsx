'use client';
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { api, unwrap } from '@/lib/api';
import type { components } from '@/lib/schema';

export type AnalyticsPull = components['schemas']['AnalyticsPullOut'];

export type BadgeMetrics = Record<string, number | string | null | undefined>;

export type ChannelBadgeLike = {
  channel?: string;
  source_label?: string;
  fetched_at?: string;
  refresh_mode?: string;
  metrics?: BadgeMetrics;
};

export type OutcomeBadgeLike = {
  has_outcomes?: boolean;
  channel_badges?: ChannelBadgeLike[];
  summary_text?: string;
} | null | undefined;

export const CANONICAL_METRICS = ['reach', 'likes', 'comments', 'clicks', 'shares'] as const;

export const NOT_REPORTED = 'not reported';

/** Display one metric value honestly: integers stay, anything else reads as not reported. */
export function metricDisplay(value: unknown): string {
  return typeof value === 'number' ? String(value) : NOT_REPORTED;
}

/** One-line summary for a channel, e.g. "instagram: 1240 reach, clicks: not reported". */
export function channelSummaryText(channel: string, metrics: BadgeMetrics | null | undefined): string {
  const safe = metrics ?? {};
  const parts = CANONICAL_METRICS.map(metric => {
    const value = safe[metric];
    return typeof value === 'number' ? `${String(value)} ${metric}` : `${metric}: ${NOT_REPORTED}`;
  });
  return `${channel}: ${parts.join(', ')}`;
}

/** Join per-channel summaries for a calendar slot badge. */
export function badgeSummaryText(badges: ChannelBadgeLike[] | null | undefined): string {
  return (badges ?? []).map(entry => channelSummaryText(entry.channel ?? '', entry.metrics)).join(' | ');
}

function normalizeBadges(badge: OutcomeBadgeLike): ChannelBadgeLike[] {
  if (!badge || typeof badge !== 'object') return [];
  return Array.isArray(badge.channel_badges) ? badge.channel_badges : [];
}

export function SlotOutcomeBadge({ badge, slotId }: { badge: OutcomeBadgeLike; slotId: string }) {
  if (!badge || badge.has_outcomes !== true) return null;
  const badges = normalizeBadges(badge);
  const summary = typeof badge.summary_text === 'string' && badge.summary_text
    ? badge.summary_text
    : badgeSummaryText(badges);
  return <div className="queue-card" data-testid={`slot-outcome-badge-${slotId}`} aria-label="Outcome badge">
    <p><strong>Outcomes</strong> <span className="hint">{summary}</span></p>
    {badges.map(entry => <div key={String(entry.channel ?? 'unknown')}>
      <p className="hint">{String(entry.channel ?? '')} · {String(entry.source_label ?? '')} · {String(entry.fetched_at ?? '')} · {String(entry.refresh_mode ?? '')}</p>
      <ul>
        {CANONICAL_METRICS.map(metric => <li key={metric}>{metric}: {metricDisplay(entry.metrics?.[metric])}</li>)}
      </ul>
    </div>)}
  </div>;
}

function pullChannelBadges(pull: AnalyticsPull): ChannelBadgeLike[] {
  const metrics = (pull.metrics ?? {}) as BadgeMetrics;
  return [{
    channel: pull.channel,
    source_label: pull.source_label,
    fetched_at: typeof pull.fetched_at === 'string' ? pull.fetched_at : String(pull.fetched_at ?? ''),
    refresh_mode: pull.refresh_mode,
    metrics,
  }];
}

export function AnalyticsPullPanel({ slotId = '', channel = '', pulls }: { slotId?: string; channel?: string; pulls?: AnalyticsPull[] }) {
  const client = useQueryClient();
  const [slotInput, setSlotInput] = useState(slotId);
  const [channelInput, setChannelInput] = useState(channel);
  const [notice, setNotice] = useState('');
  const pullsQuery = useQuery({
    queryKey: ['analytics-pulls'],
    queryFn: () => unwrap(api.GET('/api/analytics/pulls')),
    enabled: pulls === undefined,
  });
  const rows = ((pulls ?? pullsQuery.data ?? []) as AnalyticsPull[]);
  const refreshQueries = () => {
    client.invalidateQueries({ queryKey: ['analytics-pulls'] });
    client.invalidateQueries({ queryKey: ['calendar-slots'] });
  };
  const manual = useMutation({
    mutationFn: () => unwrap(api.POST('/api/calendar/slots/{slot_id}/deliveries/{channel}/analytics/refresh', {
      params: { path: { slot_id: slotInput.trim(), channel: channelInput.trim() } },
      body: {},
    })),
    onSuccess: () => { setNotice('Manual refresh ran.'); refreshQueries(); },
    onError: (error: Error) => setNotice(error.message),
  });
  const scheduled = useMutation({
    mutationFn: () => unwrap(api.POST('/api/analytics/refresh-scheduled', { body: {} })),
    onSuccess: (data: { refreshed?: unknown[] }) => {
      const count = Array.isArray(data?.refreshed) ? data.refreshed.length : 0;
      setNotice(`Scheduled refresh ran for ${count} verified ${count === 1 ? 'post' : 'posts'}.`);
      refreshQueries();
    },
    onError: (error: Error) => setNotice(error.message),
  });
  const manualTarget = slotInput.trim() && channelInput.trim();
  return <section className="panel" data-testid="analytics-pull-panel" aria-label="Analytics pull">
    <h2>Provider metrics pull</h2>
    <p className="hint">Verified posts only. Reach, likes, comments, clicks, and shares come from the provider
      with source and fetch time; unsupported metrics read as not reported, never zero.</p>
    <p>
      <label htmlFor="analytics-slot-id">Slot id</label>
      <input id="analytics-slot-id" value={slotInput} onChange={e => setSlotInput(e.target.value)} placeholder="slot_..." />
    </p>
    <p>
      <label htmlFor="analytics-channel">Channel</label>
      <input id="analytics-channel" value={channelInput} onChange={e => setChannelInput(e.target.value)} placeholder="instagram" />
    </p>
    <div className="queue-actions">
      <Button data-testid="analytics-manual-refresh-btn"
        onClick={() => manual.mutate()} disabled={manual.isPending || !manualTarget}>
        {manual.isPending ? 'Refreshing...' : 'Manual refresh'}</Button>
      <Button variant="outline" data-testid="analytics-scheduled-refresh-btn"
        onClick={() => scheduled.mutate()} disabled={scheduled.isPending}>
        {scheduled.isPending ? 'Running...' : 'Run scheduled refresh'}</Button>
    </div>
    {pullsQuery.error && pulls === undefined ? <p role="alert">{(pullsQuery.error as Error).message}</p> : null}
    {rows.length === 0
      ? <p className="hint">No provider pulls yet. Refresh a verified post to record metrics.</p>
      : <ul aria-label="Analytics pulls">
        {rows.map(pull => <li key={pull.id} data-pull={`${pull.slot_id}:${pull.channel}`}>
          <p><strong>{pull.channel}</strong> <span className="hint">{pull.source_label} · {String(pull.fetched_at ?? '')} · {pull.refresh_mode}</span></p>
          {pullChannelBadges(pull).map(entry => <ul key={entry.channel}>
            {CANONICAL_METRICS.map(metric => <li key={metric}>{metric}: {metricDisplay(entry.metrics?.[metric])}</li>)}
          </ul>)}
        </li>)}
      </ul>}
    {notice && <p role="status">{notice}</p>}
  </section>;
}
