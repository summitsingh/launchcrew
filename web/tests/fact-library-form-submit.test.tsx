import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { renderToStaticMarkup } from 'react-dom/server';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { FactLibrarySection } from '../src/components/fact-library';
import { emptyOwnerFacts } from '../src/lib/product-facts';

// The Campaign and Run forms embed FactLibrarySection inside an enclosing
// <form>. A <button> without an explicit type defaults to submit, so every
// library action must carry type="button" to never submit that outer form.
const LIBRARY_BUTTON_IDS = [
  'fact-product-create',
  'fact-variant-load',
  'fact-variant-confirm',
  'fact-variant-save',
] as const;

function shell() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <form onSubmit={() => {}}>
        <FactLibrarySection
          state={emptyOwnerFacts()}
          selection={null}
          onSelectionChange={() => {}}
          onLoad={() => {}}
          notify={() => {}}
          fail={() => {}}
        />
      </form>
    </QueryClientProvider>,
  );
}

function buttonTag(html: string, testId: string): string {
  const match = html.match(new RegExp(`<button[^>]*data-testid="${testId}"[^>]*>`));
  expect(match, `button ${testId} renders inside the enclosing form`).not.toBeNull();
  return match![0];
}

describe('facts library buttons inside forms', () => {
  it('renders Save product as type button so clicking never submits the enclosing form', () => {
    const html = shell();
    expect(html).toContain('<form');
    const tag = buttonTag(html, 'fact-product-create');
    expect(tag).toContain('type="button"');
  });

  it('renders Save current facts as type button inside the enclosing form', () => {
    const tag = buttonTag(shell(), 'fact-variant-save');
    expect(tag).toContain('type="button"');
  });

  it('declares every library action button with an explicit button type in source', () => {
    const source = readFileSync('src/components/fact-library.tsx', 'utf8');
    for (const testId of LIBRARY_BUTTON_IDS) {
      const at = source.indexOf(`data-testid="${testId}"`);
      expect(at, `button ${testId} exists`).toBeGreaterThan(-1);
      // The Button opening tag starts before the testid and ends after it.
      const openStart = source.lastIndexOf('<Button', at);
      const openEnd = source.indexOf('>', at);
      expect(openStart).toBeGreaterThan(-1);
      expect(openEnd).toBeGreaterThan(at);
      const openTag = source.slice(openStart, openEnd);
      expect(openTag, `button ${testId} is explicitly typed`).toContain('type="button"');
    }
  });
});
