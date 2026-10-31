'use client';

/** Home-page prompt to resume the most recent run after reload or navigation. */
export function ResumeLastRunBanner({
  lastRunId,
  activeRunId,
  onResume,
}: {
  lastRunId: string;
  activeRunId: string;
  onResume: (runId: string) => void;
}) {
  if (!lastRunId || lastRunId === activeRunId) return null;
  const short = lastRunId.slice(0, 8);
  return (
    <section className="panel" data-testid="resume-last-run" aria-label="Resume last run">
      <p className="eyebrow">CONTINUE WHERE YOU LEFT OFF</p>
      <h2>Resume last run</h2>
      <p className="hint">
        Your most recent pack ({short}) is still here after reload or navigation. Nothing was
        published or verified by keeping this pointer.
      </p>
      <div className="queue-actions">
        <button
          type="button"
          className="button"
          data-testid="resume-last-run-open"
          onClick={() => onResume(lastRunId)}
        >
          Open last run {short}
        </button>
      </div>
    </section>
  );
}
