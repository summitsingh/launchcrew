import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { renderToStaticMarkup } from 'react-dom/server';
import {
  RunRef,
  RunProgressList,
  ChannelVariantsBundleView,
  describeStageProgress,
  displayRunStatus,
  humanPolicyLabel,
  humanStatusLabel,
  isLiveRun,
  isTerminalReceipt,
  shortId,
} from '../src/components/v2-views';
import type { components } from '../src/lib/schema';

type Receipt = components['schemas']['Receipt'];

function receipt(overrides: Partial<Receipt> = {}): Receipt {
  return { run_id: 'run_demo_m14', status: 'completed', approval_state: 'pending_approval', ...overrides } as unknown as Receipt;
}

const viewsSource = readFileSync('src/components/v2-views.tsx', 'utf8');
const deskSource = readFileSync('src/app/page.tsx', 'utf8');

describe('M14 status lag fix', () => {
  it('shows the final verdict for a completed receipt, never running', () => {
    expect(displayRunStatus(receipt())).toBe('completed');
    expect(displayRunStatus(receipt({ approval_state: 'approved_for_export' }))).toBe('approved');
    expect(displayRunStatus(receipt({ status: 'failed' }))).toBe('failed');
    expect(isTerminalReceipt(receipt())).toBe(true);
    expect(isLiveRun(receipt())).toBe(false);
  });

  it('treats an approved or revised receipt as terminal even with a stale running flag', () => {
    const stale = receipt({ status: 'running', approval_state: 'approved_for_export' });
    expect(isTerminalReceipt(stale)).toBe(true);
    expect(displayRunStatus(stale)).toBe('approved');
    expect(isLiveRun(stale)).toBe(false);
  });

  it('keeps a genuinely in-flight run on the progress path', () => {
    const live = receipt({ status: 'running', approval_state: 'pending_approval' });
    expect(isTerminalReceipt(live)).toBe(false);
    expect(displayRunStatus(live)).toBe('running');
    expect(isLiveRun(live)).toBe(true);
  });

  it('renders the finished progress list with no running lag and no unconfirmed alert', () => {
    const html = renderToStaticMarkup(
      <RunProgressList stages={describeStageProgress([])} workerLive={false} running={false} />,
    );
    expect(html).toContain('Pack finished.');
    expect(html).not.toContain('Pack in progress.');
    expect(html).not.toContain('unconfirmed');
    expect(html).not.toContain('running');
  });

  it('drives the desk review view from terminal evidence, not the stale status flag', () => {
    expect(deskSource).toContain('isLiveRun(run.data)');
    expect(deskSource).toContain('displayRunStatus(run.data)');
    expect(deskSource).toContain('isTerminalReceipt(r)');
    expect(deskSource).not.toContain("run.data.status === 'running'");
    expect(deskSource).not.toContain("r.status === 'completed'");
    expect(viewsSource).toContain('const running = isLiveRun(receipt)');
  });
});

describe('M14 error banners clear on navigation', () => {
  it('clears the active error on every view change', () => {
    expect(deskSource).toContain("const showView = (target: View) => { setView(target); setError(''); }");
    expect(deskSource).toContain('onClick={() => showView(item)}');
    expect(deskSource).not.toMatch(/onClick=\{\(\) => setView\(/);
  });

  it('resets variant action errors when the run or revision changes', () => {
    expect(viewsSource).toContain('}, [runId, revision]);');
  });

  it('hides stale variant text beside the pack-changed lock notice', () => {
    expect(viewsSource).toContain('stale variant text is hidden until it lands');
    const locked = renderToStaticMarkup(
      <ChannelVariantsBundleView
        bundle={{
          revision: 1,
          binding_version: 'approval-binding/v1',
          binding_digest: 'd'.repeat(64),
          confirmed_claims_count: 1,
          x: {
            channel: 'x',
            variant_kind: 'presentation_candidate',
            text: 'Vegan leather wallet.',
            content_valid: true,
            exportable: false,
            independently_exportable: false,
            requires_checker_binding: true,
            status: 'candidate_pending_checker',
            char_count: 21,
            kept_sentences: 1,
            total_sentences: 1,
            omitted_sentences: 0,
          },
        } as unknown as components['schemas']['ChannelVariantsOut']}
        copied={null}
        locked
        onApprove={() => {}}
        onCopy={() => {}}
      />,
    );
    expect(locked).toContain('Locked while the pack changed');
  });
});

describe('M14 human-readable labels', () => {
  it('maps raw policy codes to human labels', () => {
    expect(humanPolicyLabel('veto_scope')).toBe('Scope and claims guard');
    expect(humanPolicyLabel('price_claims')).toBe('Price claims verification');
    expect(humanPolicyLabel('cliches')).toBe('Cliche scrubber');
    expect(humanPolicyLabel('spec_to_benefit')).toBe('Cliche scrubber');
    expect(humanPolicyLabel('ad_policy')).toBe('Platform ad policy lint');
    expect(humanPolicyLabel('landing_parity')).toBe('Landing page parity check');
    expect(humanPolicyLabel('photo_lint')).toBe('Visual aspect ratio check');
  });

  it('maps raw status tokens to human labels', () => {
    expect(humanStatusLabel('candidate_pending_checker')).toBe('Pending Checker verification');
    expect(humanStatusLabel('pending_approval')).toBe('Pending approval');
    expect(humanStatusLabel('approved_for_export')).toBe('Approved for export');
    expect(humanStatusLabel('completed')).toBe('Completed');
    expect(humanStatusLabel(null)).toBe('Unknown status');
  });

  it('shows the human variant status with the raw token inspectable', () => {
    const html = renderToStaticMarkup(
      <ChannelVariantsBundleView
        bundle={{
          revision: 0,
          binding_version: 'approval-binding/v1',
          binding_digest: 'd'.repeat(64),
          confirmed_claims_count: 1,
          x: {
            channel: 'x',
            variant_kind: 'presentation_candidate',
            text: 'Vegan leather wallet.',
            content_valid: true,
            exportable: false,
            independently_exportable: false,
            requires_checker_binding: true,
            status: 'candidate_pending_checker',
            char_count: 21,
            kept_sentences: 1,
            total_sentences: 1,
            omitted_sentences: 0,
          },
        } as unknown as components['schemas']['ChannelVariantsOut']}
        copied={null}
        locked={false}
        onApprove={() => {}}
        onCopy={() => {}}
      />,
    );
    expect(html).toContain('Pending Checker verification');
    expect(html).toContain('title="candidate_pending_checker"');
  });
});

describe('M14 shortened ID display', () => {
  it('shortens long IDs while keeping the full ID on hover, data, and copy', () => {
    expect(shortId('run-1234abcd5678efgh')).toBe('run-1234...');
    expect(shortId('run_demo')).toBe('run_demo');
    const html = renderToStaticMarkup(<RunRef id="run-1234abcd5678efgh" />);
    expect(html).toContain('run-1234...');
    expect(html).not.toContain('>run-1234abcd5678efgh<');
    expect(html).toContain('title="run-1234abcd5678efgh"');
    expect(html).toContain('data-full-id="run-1234abcd5678efgh"');
    expect(html).toContain('Copy ID');
  });

  it('keeps the full ID in the receipt JSON export path', () => {
    expect(viewsSource).toContain('`- Run: ${receipt.run_id}`');
  });
});

describe('M14 copy hygiene', () => {
  it('has zero em dashes in edited surfaces', () => {
    for (const source of [viewsSource, deskSource]) {
      expect(source).not.toContain('\u2014');
    }
  });

  it('has zero Company OS references in edited surfaces', () => {
    for (const source of [viewsSource, deskSource]) {
      expect(source).not.toContain('Company OS');
    }
  });
});
