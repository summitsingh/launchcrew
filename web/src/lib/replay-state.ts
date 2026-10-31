// Session-backed Replay comparison selection.
//
// The two compared run ids are kept in window.sessionStorage so the
// comparison survives navigation within the session (including reload)
// without ever appearing in shared state. In non-browser contexts
// (tests, SSR) an in-memory fallback keeps the same read/write contract.

const KEY_A = 'launchcrew.replayA';
const KEY_B = 'launchcrew.replayB';

let memoryA = '';
let memoryB = '';

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
}
