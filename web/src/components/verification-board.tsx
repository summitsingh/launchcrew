'use client';
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { api, unwrap } from '@/lib/api';
import type { components } from '@/lib/schema';

export type Delivery = components['schemas']['DeliveryOut'];
type Attempt = Record<string, string | number | null | undefined>;

export const DELIVERY_STATES = ['not_posted', 'posted', 'verified', 'failed'] as const;

export function DeliveryStateBadge({ state }: { state: string }) {
  return <span className="badge" data-delivery-state={state} title={state}>{state}</span>;
}

export function DeliveryAttemptsList({ attempts }: { attempts: Delivery['attempts'] }) {
  const rows = ((attempts ?? []) as Attempt[]);
  const ordered = [...rows].sort(
    (a, b) => Number(a.attempt_number ?? 0) - Number(b.attempt_number ?? 0));
  return <ol data-testid="delivery-attempts-list" aria-label="Delivery attempts">
    {ordered.length === 0 && <li className="hint">No attempts yet.</li>}
    {ordered.map(attempt => <li key={String(attempt.attempt_number ?? attempt.timestamp)}>
      <span>Attempt {String(attempt.attempt_number ?? '')}</span>
      {' '}<span>{String(attempt.timestamp ?? '')}</span>
      {' '}<span>{String(attempt.state ?? '')}</span>
      {attempt.match_kind ? <span> ({String(attempt.match_kind)})</span> : null}
      {attempt.reason ? <span>: {String(attempt.reason)}</span> : null}
    </li>)}
  </ol>;
}

function OutcomeForm({ delivery }: { delivery: Delivery }) {
  const client = useQueryClient();
  const [postedDate, setPostedDate] = useState('');
  const [likes, setLikes] = useState('0');
  const [comments, setComments] = useState('0');
  const [clicks, setClicks] = useState('0');
  const [sales, setSales] = useState('0');
  const [note, setNote] = useState('');
  const [notice, setNotice] = useState('');
  const log = useMutation({
    mutationFn: () => unwrap(api.POST('/api/calendar/slots/{slot_id}/deliveries/{channel}/outcomes', {
      params: { path: { slot_id: delivery.slot_id, channel: delivery.channel } },
      body: {
        posted_date: postedDate, likes: Number(likes), comments: Number(comments),
        clicks: Number(clicks), sales: Number(sales), note,
      },
    })),
    onSuccess: () => { setNotice('Outcome logged.'); client.invalidateQueries({ queryKey: ['verification-board'] }); },
    onError: (error: Error) => setNotice(error.message),
  });
  return <form data-testid={`log-outcome-${delivery.slot_id}-${delivery.channel}`} aria-label="Log outcome"
    onSubmit={e => { e.preventDefault(); log.mutate(); }}>
    <p><strong>Log outcome</strong> <span className="hint">(verified rows only)</span></p>
    <p><label htmlFor={`outcome-date-${delivery.id}`}>Posted date</label>
      <input id={`outcome-date-${delivery.id}`} type="date" value={postedDate} onChange={e => setPostedDate(e.target.value)} /></p>
    <p><label htmlFor={`outcome-likes-${delivery.id}`}>Likes</label>
      <input id={`outcome-likes-${delivery.id}`} inputMode="numeric" value={likes} onChange={e => setLikes(e.target.value)} /></p>
    <p><label htmlFor={`outcome-comments-${delivery.id}`}>Comments</label>
      <input id={`outcome-comments-${delivery.id}`} inputMode="numeric" value={comments} onChange={e => setComments(e.target.value)} /></p>
    <p><label htmlFor={`outcome-clicks-${delivery.id}`}>Clicks</label>
      <input id={`outcome-clicks-${delivery.id}`} inputMode="numeric" value={clicks} onChange={e => setClicks(e.target.value)} /></p>
    <p><label htmlFor={`outcome-sales-${delivery.id}`}>Sales</label>
      <input id={`outcome-sales-${delivery.id}`} inputMode="numeric" value={sales} onChange={e => setSales(e.target.value)} /></p>
    <p><label htmlFor={`outcome-note-${delivery.id}`}>Note</label>
      <input id={`outcome-note-${delivery.id}`} value={note} maxLength={500} onChange={e => setNote(e.target.value)} /></p>
    <div className="queue-actions">
      <Button type="submit" disabled={log.isPending}>{log.isPending ? 'Logging...' : 'Log outcome'}</Button>
    </div>
    {notice && <p role="status">{notice}</p>}
  </form>;
}

export function DeliveryRow({ delivery }: { delivery: Delivery }) {
  const client = useQueryClient();
  const [liveUrl, setLiveUrl] = useState(delivery.live_url ?? '');
  const [liveText, setLiveText] = useState('');
  const [notice, setNotice] = useState('');
  const refresh = () => {
    client.invalidateQueries({ queryKey: ['verification-board'] });
    client.invalidateQueries({ queryKey: ['calendar-slots'] });
  };
  const markPosted = useMutation({
    mutationFn: (verifyNow: boolean) => unwrap(api.POST('/api/calendar/slots/{slot_id}/deliveries/{channel}/mark-posted', {
      params: { path: { slot_id: delivery.slot_id, channel: delivery.channel } },
      body: { live_url: liveUrl, ...(liveText.trim() ? { live_text: liveText } : {}), verify_now: verifyNow },
    })),
    onSuccess: () => { setNotice('Marked posted.'); refresh(); },
    onError: (error: Error) => setNotice(error.message),
  });
  const verifyNow = useMutation({
    mutationFn: () => unwrap(api.POST('/api/calendar/slots/{slot_id}/deliveries/{channel}/verify', {
      params: { path: { slot_id: delivery.slot_id, channel: delivery.channel } },
      body: { ...(liveUrl.trim() ? { live_url: liveUrl.trim() } : {}), ...(liveText.trim() ? { live_text: liveText } : {}) },
    })),
    onSuccess: () => { setNotice('Verification ran.'); refresh(); },
    onError: (error: Error) => setNotice(error.message),
  });
  const attempts = (delivery.attempts ?? []) as Attempt[];
  return <article className="panel queue-card" data-delivery-row={`${delivery.slot_id}:${delivery.channel}`}>
    <p><strong>{delivery.channel}</strong> <DeliveryStateBadge state={delivery.delivery_state} />
      {delivery.match_kind ? <span className="hint"> match: {delivery.match_kind}</span> : null}</p>
    {delivery.differing_field ? <p role="alert">Mismatch on field: {delivery.differing_field}
      {delivery.failure_reason ? ` (${delivery.failure_reason})` : ''}</p> : null}
    {delivery.failure_reason && !delivery.differing_field ? <p role="alert">{delivery.failure_reason}</p> : null}
    <p className="hint">{delivery.live_url ? `Live URL: ${delivery.live_url}` : 'No live URL yet.'}</p>
    <p><label htmlFor={`delivery-url-${delivery.id}`}>Live URL</label>
      <input id={`delivery-url-${delivery.id}`} value={liveUrl} placeholder="https://..."
        onChange={e => setLiveUrl(e.target.value)} /></p>
    <p><label htmlFor={`delivery-text-${delivery.id}`}>Live text (optional)</label>
      <textarea id={`delivery-text-${delivery.id}`} value={liveText}
        onChange={e => setLiveText(e.target.value)} /></p>
    <div className="queue-actions">
      <Button variant="outline" data-testid={`mark-posted-${delivery.slot_id}-${delivery.channel}`}
        onClick={() => markPosted.mutate(false)} disabled={markPosted.isPending || !liveUrl.trim()}>
        {markPosted.isPending ? 'Marking...' : 'Mark posted'}</Button>
      <Button data-testid={`verify-${delivery.slot_id}-${delivery.channel}`}
        onClick={() => verifyNow.mutate()} disabled={verifyNow.isPending}>
        {verifyNow.isPending ? 'Verifying...' : 'Verify'}</Button>
      <Button variant="outline" data-testid={`mark-posted-verify-${delivery.slot_id}-${delivery.channel}`}
        onClick={() => markPosted.mutate(true)} disabled={markPosted.isPending || !liveUrl.trim()}>
        Mark posted and verify</Button>
    </div>
    <DeliveryAttemptsList attempts={attempts} />
    {delivery.delivery_state === 'verified' ? <OutcomeForm delivery={delivery} /> : null}
    {notice && <p role="status">{notice}</p>}
  </article>;
}

export function VerificationBoard({ slotId, rows }: { slotId?: string; rows?: Delivery[] }) {
  const board = useQuery({
    queryKey: ['verification-board', slotId ?? 'all'],
    queryFn: () => unwrap(api.GET('/api/calendar/verification-board',
      slotId ? { params: { query: { slot_id: slotId } } } : undefined)),
    enabled: rows === undefined,
  });
  const deliveries = (rows ?? board.data ?? []) as Delivery[];
  return <section className="panel" data-testid="verification-board" aria-label="Cross-post verification board">
    <h2>Cross-post verification board</h2>
    <p className="hint">One row per channel per slot. Paste the live URL, mark posted, then verify against the approved text. Mismatches stay visible; every attempt stays on the record.</p>
    {rows === undefined && board.isPending && <p>Loading deliveries...</p>}
    {rows === undefined && board.error && <p role="alert">{board.error.message}</p>}
    {(rows !== undefined || board.data) && deliveries.length === 0 && <p className="hint">No deliveries yet. Select channels on a slot to start.</p>}
    {deliveries.map(delivery => <DeliveryRow key={`${delivery.slot_id}:${delivery.channel}`} delivery={delivery} />)}
  </section>;
}
