import { beforeEach, describe, expect, it } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderToStaticMarkup } from 'react-dom/server';
import { ReplayView } from '../src/components/v2-views';
import {
  clearReplaySelection,
  loadReplaySelection,
  saveReplaySelection,
} from '../src/lib/replay-state';

function renderReplay() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <ReplayView queue={[]} />
    </QueryClientProvider>,
  );
}

describe('replay comparison persistence', () => {
  beforeEach(() => {
    clearReplaySelection();
  });

  it('starts empty and round-trips across simulated navigation', () => {
    expect(loadReplaySelection()).toEqual({ a: '', b: '' });
    saveReplaySelection({ a: 'run_aaa111', b: 'run_bbb222' });
    // A fresh load (as after navigation away and back) restores the pair.
    expect(loadReplaySelection()).toEqual({ a: 'run_aaa111', b: 'run_bbb222' });
  });

  it('clearing one side keeps the other side stored', () => {
    saveReplaySelection({ a: 'run_aaa111', b: 'run_bbb222' });
    saveReplaySelection({ a: '', b: 'run_bbb222' });
    expect(loadReplaySelection()).toEqual({ a: '', b: 'run_bbb222' });
  });

  it('replay view restores the stored comparison after remount', () => {
    saveReplaySelection({ a: 'run_aaa111', b: 'run_bbb222' });
    const first = renderReplay();
    expect(first).toContain('value="run_aaa111"');
    expect(first).toContain('value="run_bbb222"');
    // Remounting (navigating away and back) shows the same comparison.
    const second = renderReplay();
    expect(second).toContain('value="run_aaa111"');
    expect(second).toContain('value="run_bbb222"');
  });

  it('replay view starts blank with no stored comparison', () => {
    const html = renderReplay();
    expect(html).toContain('aria-label="Replay"');
    expect(html).not.toContain('value="run_');
  });
});
