import { beforeEach, describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { ResumeLastRunBanner } from '../src/components/resume-last-run';
import { clearLastRunId, readLastRunId, writeLastRunId } from '../src/lib/last-run';

describe('resume last run pointer', () => {
  beforeEach(() => {
    clearLastRunId();
  });

  it('starts empty and round-trips across a simulated reload', () => {
    expect(readLastRunId()).toBe('');
    writeLastRunId('run_abc123');
    // A fresh read (as after reload or navigation) sees the same run.
    expect(readLastRunId()).toBe('run_abc123');
  });

  it('forgetting clears the prompt', () => {
    writeLastRunId('run_abc123');
    clearLastRunId();
    expect(readLastRunId()).toBe('');
  });
});

describe('resume last run banner', () => {
  it('points at the latest run id', () => {
    const html = renderToStaticMarkup(
      <ResumeLastRunBanner lastRunId="run_abc123" activeRunId="" onResume={() => {}} />,
    );
    expect(html).toContain('data-testid="resume-last-run"');
    expect(html).toContain('Resume last run');
    expect(html).toContain('run_abc1');
    expect(html).toContain('data-testid="resume-last-run-open"');
  });

  it('stays hidden without a recorded run', () => {
    expect(
      renderToStaticMarkup(<ResumeLastRunBanner lastRunId="" activeRunId="" onResume={() => {}} />),
    ).toBe('');
  });

  it('stays hidden while that run is already open', () => {
    expect(
      renderToStaticMarkup(
        <ResumeLastRunBanner lastRunId="run_abc123" activeRunId="run_abc123" onResume={() => {}} />,
      ),
    ).toBe('');
  });
});
