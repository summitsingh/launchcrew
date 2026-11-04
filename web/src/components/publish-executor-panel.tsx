'use client';
import { Badge as WorkspaceBadge } from '@/components/ui/badge';
import { Card } from '@/components/ui/card';

import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { api, unwrap } from '@/lib/api';
import type { components } from '@/lib/schema';

export type PublishExecution = components['schemas']['PublishExecutionOut'];
export type PublishDueSlot = components['schemas']['PublishDueSlotOut'];
type Attempt = Record<string, string | number | boolean | null | undefined>;

export function SimulatedChip() {
  return <WorkspaceBadge appearance="workspace" asChild ><span className="badge" data-testid="simulated-chip"
    title="Posted by the simulated transport; no platform was contacted">SIMULATED</span></WorkspaceBadge>;
}

export const EXECUTION_STATUSES = [
  'pending',
  'posted',
  'failed',
  'skipped_needs_approval',
  'paused_by_kill_switch',
] as const;

export function ExecutionStatusBadge({ status }: { status: string }) {
  return <WorkspaceBadge appearance="workspace" asChild ><span className="badge" data-execution-status={status} title={status}>{status}</span></WorkspaceBadge>;
}

export function plainExecutionExplanation(execution: PublishExecution): string {
  const raw = typeof execution.last_error === 'string' ? execution.last_error.toLowerCase() : '';
  if (execution.status === 'skipped_needs_approval') return 'Not posted: this slot still needs approval before anything can publish.';
  if (execution.status === 'paused_by_kill_switch') return 'Not posted: execution is paused by the owner kill switch.';
  if (raw.includes('photo') || raw.includes('media') || raw.includes('image')) return 'Delivery failed on the photo step. Reconnect the brand account or check the slot image, then retry.';
  if (raw.includes('revoked') || raw.includes('token') || raw.includes('connect') || raw.includes('disconnect') || raw.includes('reconnect')) return 'Delivery failed: the brand account connection needs attention. Reconnect the brand account, then retry.';
  if (raw.includes('ready') || raw.includes('approval')) return 'Delivery failed: the slot was not Ready with an approved pack. Approve the pack first, then retry.';
  return 'Delivery failed on publication. Check the safe details below, then retry.';
}

export function ExecutionAttemptsList({ attempts }: { attempts: PublishExecution['attempts'] }) {
  const rows = ((attempts ?? []) as Attempt[]);
  const ordered = [...rows].sort(
    (a, b) => Number(a.attempt_number ?? 0) - Number(b.attempt_number ?? 0));
  return <ol data-testid="publish-attempts-list" aria-label="Publish attempts">
    {ordered.length === 0 && <li className="hint">No attempts yet.</li>}
    {ordered.map(attempt => <li key={String(attempt.attempt_number ?? attempt.timestamp)}>
      <span>Attempt {String(attempt.attempt_number ?? '')}</span>
      {' '}<span>{String(attempt.timestamp ?? '')}</span>
      {' '}<span>{String(attempt.outcome ?? '')}</span>
      {attempt.simulated === true ? <span> <SimulatedChip /></span> : null}
      {' '}<span>backoff {String(attempt.backoff_seconds ?? 0)}s</span>
      {attempt.failure_reason ? <span>: {String(attempt.failure_reason)}</span> : null}
    </li>)}
  </ol>;
}

function SafeDetailValue({ value }: { value: unknown }) {
  if (value === null || value === undefined) return <span>not recorded</span>;
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return <span>{String(value)}</span>;
  return <span>not recorded</span>;
}

export function ExecutionRow({ execution }: { execution: PublishExecution }) {
  const client = useQueryClient();
  const [notice, setNotice] = useState('');
  const [showDetails, setShowDetails] = useState(false);
  const retry = useMutation({
    mutationFn: () => unwrap(api.POST('/api/publish/slots/{slot_id}/retry', {
      params: { path: { slot_id: execution.slot_id } }, body: {},
    })),
    onSuccess: () => {
      setNotice('Owner retry ran.');
      client.invalidateQueries({ queryKey: ['publish-status'] });
      client.invalidateQueries({ queryKey: ['calendar-slots'] });
    },
    onError: (error: Error) => setNotice(error.message),
  });
  const attempts = (execution.attempts ?? []) as Attempt[];
  return <Card appearance="workspace" asChild ><article className="panel queue-card"
    data-execution-row={`${execution.slot_id}:${execution.channel}`}>
    <p><strong>{execution.channel}</strong> <ExecutionStatusBadge status={execution.status} />
      {execution.simulated === true ? <span> <SimulatedChip /></span> : null}</p>
    <p className="hint">Slot {execution.slot_id} · key {execution.idempotency_key}</p>
    {(execution.status === 'skipped_needs_approval' || execution.status === 'failed')
      ? <p role="status">{plainExecutionExplanation(execution)} No automatic retry runs; use Owner retry below only if you want one more attempt.</p> : null}
    <div><Button variant="outline" onClick={() => setShowDetails(value => !value)} aria-expanded={showDetails}>{showDetails ? 'Hide details' : 'Show details'}</Button>
      {showDetails && <dl>
        <div><dt>Stored reason</dt><dd>{execution.last_error || 'not recorded'}</dd></div>
        <div><dt>Idempotency key</dt><dd>{execution.idempotency_key || 'not recorded'}</dd></div>
        {(attempts ?? []).map((attempt, i) => {
          const details = (attempt as Record<string, unknown>).details;
          const safe = details && typeof details === 'object' ? (details as Record<string, unknown>) : null;
          return <div key={i}><dt>Attempt {String((attempt as Record<string, unknown>).attempt_number ?? i + 1)} safe detail</dt><dd>
            {safe ? <ul>
              {(['message', 'failed_call', 'status', 'code', 'subcode', 'type'] as const).map(key => <li key={key}>{key}: <SafeDetailValue value={safe[key]} /></li>)}
            </ul> : <span>Legacy record: only the stored reason above is available.</span>}
          </dd></div>;
        })}
      </dl>}</div>
    {showDetails && <>{execution.live_url ? <p className="hint">Live URL: {execution.live_url}</p> : null}
      {execution.platform_post_id
        ? <p className="hint">Platform post: {execution.platform_post_id}</p> : null}
      <ExecutionAttemptsList attempts={attempts} /></>}
    {execution.status === 'failed'
      ? <div className="queue-actions">
        <Button variant="outline"
          data-testid={`publish-retry-${execution.slot_id}-${execution.channel}`}
          onClick={() => retry.mutate()} disabled={retry.isPending}>
          {retry.isPending ? 'Retrying...' : 'Owner retry'}</Button>
      </div> : null}
    {notice && <p role="status">{notice}</p>}
  </article></Card>;
}

export function DueSlotsList({ slots }: { slots: PublishDueSlot[] }) {
  return <ul data-testid="publish-due-slots" aria-label="Due ready slots">
    {slots.length === 0 && <li className="hint">No due Ready slots.</li>}
    {slots.map(slot => <li key={slot.slot_id}>
      {slot.slot_id} · {slot.slot_date} {slot.planned_time} · {(slot.channels ?? []).join(', ')}
    </li>)}
  </ul>;
}

export function PublishExecutorPanel() {
  const client = useQueryClient();
  const [notice, setNotice] = useState('');
  const status = useQuery({
    queryKey: ['publish-status'],
    queryFn: () => unwrap(api.GET('/api/publish/status')),
  });
  const killSwitch = (status.data as { kill_switch?: { paused?: boolean } } | undefined)
    ?.kill_switch ?? { paused: false };
  const paused = killSwitch.paused === true;
  const executions = ((status.data as { executions?: PublishExecution[] } | undefined)
    ?.executions ?? []) as PublishExecution[];
  const dueSlots = ((status.data as { due_slots?: PublishDueSlot[] } | undefined)
    ?.due_slots ?? []) as PublishDueSlot[];
  const refresh = () => { client.invalidateQueries({ queryKey: ['publish-status'] }); };
  const toggleKill = useMutation({
    mutationFn: () => unwrap(api.POST('/api/publish/kill-switch', {
      body: { paused: !paused, reason: paused ? '' : 'owner hold from panel' },
    })),
    onSuccess: () => {
      setNotice(paused ? 'Execution resumed.' : 'Execution paused. Slots and packs untouched.');
      refresh();
    },
    onError: (error: Error) => setNotice(error.message),
  });
  const runDue = useMutation({
    mutationFn: () => unwrap(api.POST('/api/publish/execute-due', { body: {} })),
    onSuccess: data => {
      const done = (data as { executed_slots?: string[] }).executed_slots ?? [];
      setNotice(`Tick ran. Posted ${done.length} due Ready slot${done.length === 1 ? '' : 's'}.`);
      refresh();
      client.invalidateQueries({ queryKey: ['calendar-slots'] });
    },
    onError: (error: Error) => setNotice(error.message),
  });
  return <Card appearance="workspace" asChild ><section className="panel" data-testid="publish-executor-panel"
    aria-label="Autonomous publish executor">
    <h2>Autonomous publish executor</h2>
    <p className="hint">Ready slots post at their scheduled time with no per-post tap.
      Platform success sets state to posted only and hands off to the S5
      verification board for live verification.</p>
    <p role="status" aria-label="Kill switch state">
      {status.isPending ? 'Loading executor status...'
        : paused ? 'Execution paused by owner kill switch.' : 'Execution running.'}
    </p>
    <div className="queue-actions">
      <Button variant="outline" data-testid="publish-kill-switch-btn"
        onClick={() => toggleKill.mutate()} disabled={toggleKill.isPending || status.isPending}>
        {toggleKill.isPending ? 'Updating...' : paused ? 'Resume execution' : 'Pause execution'}
      </Button>
      <Button data-testid="publish-execute-due-btn"
        onClick={() => runDue.mutate()} disabled={runDue.isPending}>
        {runDue.isPending ? 'Running...' : 'Run due Ready slots'}</Button>
    </div>
    {status.error && <p role="alert">{(status.error as Error).message}</p>}
    <DueSlotsList slots={dueSlots} />
    {executions.map(execution => <ExecutionRow key={execution.id} execution={execution} />)}
    {notice && <p role="status">{notice}</p>}
  </section></Card>;
}
