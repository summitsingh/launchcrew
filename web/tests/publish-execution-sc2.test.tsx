import { describe, it, expect } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { CalendarView } from '../src/components/calendar-view';
import {
  DueSlotsList,
  ExecutionAttemptsList,
  ExecutionRow,
  ExecutionStatusBadge,
  PublishExecutorPanel,
  type PublishExecution,
} from '../src/components/publish-executor-panel';

function provider(children: React.ReactNode) {
  return renderToStaticMarkup(<QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>);
}

function execution(partial: Partial<PublishExecution> & { id: string; slot_id: string; channel: string }): PublishExecution {
  return {
    idempotency_key: 'key_' + partial.id, status: 'pending', platform_post_id: null,
    live_url: null, simulated: false, attempt_count: 0, max_auto_retries: 2, attempts: [], last_error: null,
    ...partial,
  };
}

const posted = execution({
  id: 'exe_1', slot_id: 'slot_1', channel: 'instagram', status: 'posted',
  platform_post_id: 'post_abc123', live_url: 'https://instagram.example.com/posts/abc',
  attempt_count: 1,
  attempts: [
    {
      attempt_number: 1, timestamp: '2026-11-03T09:00:00+00:00', channel: 'instagram',
      idempotency_key: 'key_exe_1', backoff_seconds: 0, outcome: 'posted',
      platform_post_id: 'post_abc123', live_url: 'https://instagram.example.com/posts/abc',
      failure_reason: null,
    },
  ],
});

const failed = execution({
  id: 'exe_2', slot_id: 'slot_2', channel: 'x', status: 'failed',
  attempt_count: 3, last_error: 'Publish failed: the brand account token was revoked.',
  attempts: [1, 2, 3].map(n => ({
    attempt_number: n, timestamp: `2026-11-03T09:0${n}:00+00:00`, channel: 'x',
    idempotency_key: 'key_exe_2', backoff_seconds: [0, 2, 5][n - 1], outcome: 'failed',
    platform_post_id: null, live_url: null,
    failure_reason: 'Publish failed: the brand account token was revoked.',
  })),
});

const skipped = execution({
  id: 'exe_3', slot_id: 'slot_3', channel: 'tiktok', status: 'skipped_needs_approval',
  last_error: 'Pack changed since approval; the slot needs re-approval.',
});

describe('execution status badges', () => {
  it('renders every executor status', () => {
    for (const state of ['pending', 'posted', 'failed', 'skipped_needs_approval', 'paused_by_kill_switch']) {
      const html = provider(<ExecutionStatusBadge status={state} />);
      expect(html).toContain(`data-execution-status="${state}"`);
      expect(html).toContain(state);
    }
  });
});

describe('execution attempts list', () => {
  it('shows bounded attempts in order with backoff and reason', () => {
    const html = provider(<ExecutionAttemptsList attempts={failed.attempts} />);
    expect(html).toContain('data-testid="publish-attempts-list"');
    expect(html).toContain('Attempt 1');
    expect(html).toContain('Attempt 3');
    expect(html).toContain('backoff 5s');
    expect(html).toContain('the brand account token was revoked');
    expect(html.indexOf('Attempt 1')).toBeLessThan(html.indexOf('Attempt 3'));
  });
});

describe('execution row', () => {
  it('shows the posted result with idempotency key and live URL', () => {
    const html = provider(<ExecutionRow execution={posted} />);
    expect(html).toContain('data-execution-row="slot_1:instagram"');
    expect(html).toContain('data-execution-status="posted"');
    expect(html).toContain('key_exe_1');
    expect(html).toContain('https://instagram.example.com/posts/abc');
    expect(html).toContain('post_abc123');
    expect(html).toContain('data-testid="publish-attempts-list"');
    expect(html).not.toContain('Owner retry');
  });
  it('shows the failed reason with an owner retry button', () => {
    const html = provider(<ExecutionRow execution={failed} />);
    expect(html).toContain('data-execution-status="failed"');
    expect(html).toContain('the brand account token was revoked');
    expect(html).toContain('data-testid="publish-retry-slot_2-x"');
    expect(html).toContain('Owner retry');
  });
  it('names the needs-approval skip reason without a retry button', () => {
    const html = provider(<ExecutionRow execution={skipped} />);
    expect(html).toContain('data-execution-status="skipped_needs_approval"');
    expect(html).toContain('Needs approval');
    expect(html).toContain('Pack changed since approval');
    expect(html).not.toContain('Owner retry');
  });
});

describe('due slots list', () => {
  it('names due ready slots with time and channels', () => {
    const html = provider(<DueSlotsList slots={[
      { slot_id: 'slot_1', slot_date: '2026-11-03', planned_time: '09:00', channels: ['instagram'] },
    ]} />);
    expect(html).toContain('data-testid="publish-due-slots"');
    expect(html).toContain('slot_1');
    expect(html).toContain('09:00');
    expect(html).toContain('instagram');
  });
});

describe('publish executor panel', () => {
  it('renders the kill switch, due action, and posted-only notice', () => {
    const html = provider(<PublishExecutorPanel />);
    expect(html).toContain('data-testid="publish-executor-panel"');
    expect(html).toContain('Autonomous publish executor');
    expect(html).toContain('data-testid="publish-kill-switch-btn"');
    expect(html).toContain('data-testid="publish-execute-due-btn"');
    expect(html).toContain('Run due Ready slots');
    expect(html).toContain('posted only');
    expect(html).toContain('verification board');
    expect(html).toContain('data-testid="publish-due-slots"');
  });
  it('appears on the calendar view', () => {
    const html = provider(<CalendarView />);
    expect(html).toContain('data-testid="publish-executor-panel"');
    expect(html).toContain('data-testid="verification-board"');
  });
});

describe('simulated execution badging', () => {
  it('chips a simulated posted row but not a live one', () => {
    const simulated = execution({
      id: 'exe_sim', slot_id: 'slot_sim', channel: 'instagram', status: 'posted',
      simulated: true, attempt_count: 1,
      attempts: [{ attempt_number: 1, timestamp: '2026-11-04T10:00:00+00:00', channel: 'instagram', idempotency_key: 'key_exe_sim', backoff_seconds: 0, outcome: 'posted', platform_post_id: 'post_sim', live_url: 'https://instagram.example.com/posts/sim', failure_reason: null, simulated: true }],
    });
    const html = provider(<ExecutionRow execution={simulated} />);
    expect(html).toContain('data-testid="simulated-chip"');
    expect(html).toContain('SIMULATED');
    const liveHtml = provider(<ExecutionRow execution={posted} />);
    expect(liveHtml).not.toContain('data-testid="simulated-chip"');
  });
});
