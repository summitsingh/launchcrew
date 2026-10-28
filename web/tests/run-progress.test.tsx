import { describe, it, expect } from 'vitest';
import { QueryClient } from '@tanstack/react-query';
import { renderToStaticMarkup } from 'react-dom/server';
import {
  RunProgressList,
  describeStageProgress,
  stageEvidenceCopy,
} from '../src/components/v2-views';
import {
  applyAcknowledgedReceipt,
  shouldApplyReceipt,
} from '../src/components/photo-check';
import type { components } from '../src/lib/schema';

type Receipt = components['schemas']['Receipt'];

function receiptAt(revision: number): Receipt {
  return { run_id: 'run_demo', revision } as unknown as Receipt;
}

describe('incremental run progress', () => {
  it('orders stages by pipeline and never invents rows', () => {
    const stages = describeStageProgress([
      { stage: 'scout', state: 'completed', observed_at: '2026-10-28T00:00:01Z', profile: 'Scout', evidence: { facts_used: 5, risks: 3, model_mode: 'deterministic_fallback' } },
      { stage: 'accepted', state: 'completed', observed_at: '2026-10-28T00:00:00Z', profile: 'LaunchCrew', evidence: { idea_chars: 62 } },
      { stage: 'unknown_future', state: 'completed', observed_at: '2026-10-28T00:00:02Z', profile: 'X', evidence: {} },
    ]);
    expect(stages.map(stage => stage.stage)).toEqual([
      'accepted', 'deterministic_checks', 'scout', 'maker_draft_v1',
      'checker_v1', 'maker_draft_v2', 'checker_v2', 'receipt',
    ]);
    expect(stages[0]).toMatchObject({ label: 'Accepted', state: 'completed', profile: 'LaunchCrew' });
    expect(stages[1].state).toBe('pending');
    expect(stages[2]).toMatchObject({ label: 'Scout facts', state: 'completed' });
  });

  it('draws evidence copy only from stored step evidence', () => {
    expect(stageEvidenceCopy('scout', { facts_used: 5, risks: 3, model_mode: 'deterministic_fallback' }))
      .toBe('5 facts sourced · 3 risks · synthesis deterministic_fallback');
    expect(stageEvidenceCopy('checker_v1', { blocked_count: 1, verified_count: 4 }))
      .toBe('blocked 1 · verified 4');
    expect(stageEvidenceCopy('receipt', { blocked_count: 0, stored: true }))
      .toBe('receipt stored · final blocked 0');
    expect(stageEvidenceCopy('receipt', {})).toBe('receipt prepared');
  });

  it('marks pending, in progress, and unconfirmed honestly', () => {
    const live = renderToStaticMarkup(
      <RunProgressList stages={describeStageProgress([
        { stage: 'accepted', state: 'completed', observed_at: '2026-10-28T00:00:00Z', profile: 'LaunchCrew', evidence: {} },
        { stage: 'scout', state: 'started', observed_at: '2026-10-28T00:00:01Z', profile: 'Scout', evidence: {} },
      ])} workerLive={true} running={true} />,
    );
    expect(live).toContain('Pack in progress.');
    expect(live).toContain('in progress');
    expect(live).toContain('not yet reached');
    expect(live).toContain('Nothing here is predicted');
    expect(live).not.toContain('worker not observed');
    const lost = renderToStaticMarkup(
      <RunProgressList stages={describeStageProgress([
        { stage: 'accepted', state: 'completed', observed_at: '2026-10-28T00:00:00Z', profile: 'LaunchCrew', evidence: {} },
      ])} workerLive={false} running={true} />,
    );
    expect(lost).toContain('worker not observed');
    expect(lost).toContain('unconfirmed');
  });

  it('never lets an older in-flight GET overwrite an acknowledged mutation receipt', async () => {
    expect(shouldApplyReceipt(null, 1)).toBe(true);
    expect(shouldApplyReceipt(2, 2)).toBe(true);
    expect(shouldApplyReceipt(2, 1)).toBe(false);
    expect(shouldApplyReceipt(2, 3)).toBe(true);
    const client = new QueryClient();
    // Deferred older GET arrives after the mutation was acknowledged: dropped.
    await applyAcknowledgedReceipt(client, 'run_demo', receiptAt(2));
    expect((client.getQueryData(['run', 'run_demo']) as Receipt).revision).toBe(2);
    await applyAcknowledgedReceipt(client, 'run_demo', receiptAt(1));
    expect((client.getQueryData(['run', 'run_demo']) as Receipt).revision).toBe(2);
    // Final mutation receipt at the newer revision still applies.
    await applyAcknowledgedReceipt(client, 'run_demo', receiptAt(3));
    expect((client.getQueryData(['run', 'run_demo']) as Receipt).revision).toBe(3);
  });
});
