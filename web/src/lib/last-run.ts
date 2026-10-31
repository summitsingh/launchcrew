// Last-run pointer for the "Resume last run" home prompt.
//
// The most recent run id is kept in window.localStorage so the prompt
// survives reload and navigation. In non-browser contexts (tests, SSR)
// an in-memory fallback keeps the same read/write contract.

const STORAGE_KEY = 'launchcrew.lastRunId';

let memoryFallback = '';

function browserStorage(): Storage | null {
  try {
    if (typeof window !== 'undefined' && window.localStorage) return window.localStorage;
  } catch {
    return null;
  }
  return null;
}

/** Most recently created or opened run id, or '' when none is recorded. */
export function readLastRunId(): string {
  const store = browserStorage();
  if (store) {
    try {
      return store.getItem(STORAGE_KEY) ?? '';
    } catch {
      return memoryFallback;
    }
  }
  return memoryFallback;
}

/** Record a run as the most recent one. Blank values clear the pointer. */
export function writeLastRunId(runId: string): void {
  memoryFallback = runId;
  const store = browserStorage();
  if (store) {
    try {
      if (runId) store.setItem(STORAGE_KEY, runId);
      else store.removeItem(STORAGE_KEY);
    } catch {
      /* storage unavailable; the in-memory copy still applies */
    }
  }
}

/** Forget the recorded run, for example on sign-out or actor switch. */
export function clearLastRunId(): void {
  writeLastRunId('');
}
