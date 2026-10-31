// Session-backed Replay comparison selection.
//
// The two compared run ids are kept in window.sessionStorage so the
// comparison survives navigation within the session (including reload)
// without ever appearing in shared state. In non-browser contexts
// (tests, SSR) an in-memory fallback keeps the same read/write contract.

const KEY_A = 'launchcrew.replayA';
const KEY_B = 'launchcrew.replayB';
const KEY_DIFF = 'launchcrew.replayDiff';

let memoryA = '';
let memoryB = '';
let memoryDiff = '';

function browserStorage(): Storage | null {
  try {
    if (typeof window !== 'undefined' && window.sessionStorage) return window.sessionStorage;
  } catch {
    return null;
  }
  return null;
}

function readKey(key: string, fallback: string): string {
  const store = browserStorage();
  if (store) {
    try {
      return store.getItem(key) ?? '';
    } catch {
      return fallback;
    }
  }
  return fallback;
}

function writeKey(key: string, value: string, setMemory: (next: string) => void): void {
  setMemory(value);
  const store = browserStorage();
  if (store) {
    try {
      if (value) store.setItem(key, value);
      else store.removeItem(key);
    } catch {
      /* storage unavailable; the in-memory copy still applies */
    }
  }
}

export type ReplaySelection = { a: string; b: string };

/** Last successful Replay comparison, stored with the pair it compared. */
export type StoredReplayDiff = { a: string; b: string; diff: unknown };

/** Currently stored Replay comparison, or empty ids when none is stored. */
export function loadReplaySelection(): ReplaySelection {
  return { a: readKey(KEY_A, memoryA), b: readKey(KEY_B, memoryB) };
}

/** Persist the Replay comparison selection. Blank ids clear that side. */
export function saveReplaySelection(selection: ReplaySelection): void {
  writeKey(KEY_A, selection.a, next => {
    memoryA = next;
  });
  writeKey(KEY_B, selection.b, next => {
    memoryB = next;
  });
}

/** Forget the stored Replay comparison. */
export function clearReplaySelection(): void {
  saveReplaySelection({ a: '', b: '' });
  clearReplayDiff();
}

function readDiffRaw(): string {
  const store = browserStorage();
  if (store) {
    try {
      return store.getItem(KEY_DIFF) ?? '';
    } catch {
      return memoryDiff;
    }
  }
  return memoryDiff;
}

function writeDiffRaw(raw: string): void {
  memoryDiff = raw;
  const store = browserStorage();
  if (store) {
    try {
      if (raw) store.setItem(KEY_DIFF, raw);
      else store.removeItem(KEY_DIFF);
    } catch {
      /* storage unavailable; the in-memory copy still applies */
    }
  }
}

/** Last stored Replay diff result with the pair it compared, or null. */
export function loadReplayDiff(): StoredReplayDiff | null {
  const raw = readDiffRaw();
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as Partial<StoredReplayDiff>;
    if (
      typeof parsed.a !== 'string' ||
      typeof parsed.b !== 'string' ||
      !parsed.a ||
      !parsed.b ||
      parsed.diff === null ||
      typeof parsed.diff !== 'object'
    ) {
      return null;
    }
    return { a: parsed.a, b: parsed.b, diff: parsed.diff };
  } catch {
    return null;
  }
}

/** Persist a successful Replay diff result keyed to the compared pair. */
export function saveReplayDiff(selection: ReplaySelection, diff: unknown): void {
  if (!selection.a || !selection.b || diff === null || typeof diff !== 'object') return;
  writeDiffRaw(JSON.stringify({ a: selection.a, b: selection.b, diff }));
}

/** Forget the stored Replay diff result. */
export function clearReplayDiff(): void {
  writeDiffRaw('');
}
