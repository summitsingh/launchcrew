import { describe, it, expect } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ImportSuggestionsForm, ImportSuggestionsList } from '../src/components/import-suggestions-form';
import {
  IMPORT_SOURCES,
  IMPORT_TEXT_MAX,
  importSourceLabel,
  mapImportSourceToProductFactSource,
  toOwnerFactFromSuggestion,
  toOwnerFactsFromSuggestions,
  validateImportText,
  type ImportSuggestionsOut,
} from '../src/lib/import-suggestions';
import {
  buildProductFactsInput,
  emptyOwnerFacts,
  validateOwnerFacts,
} from '../src/lib/product-facts';

function intakeResult(): ImportSuggestionsOut {
  return {
    status: 'unconfirmed',
    source: 'listing',
    product_fact_source: 'listing',
    suggestions: [
      { text: 'Canvas tote', source: 'listing', product_fact_source: 'listing', status: 'unconfirmed', confirmed: false, index: 0 },
      { text: 'Large', source: 'listing', product_fact_source: 'listing', status: 'unconfirmed', confirmed: false, index: 1 },
    ],
    truncated: false,
    dropped_duplicates: 0,
    dropped_overlong: 0,
    dropped_empty: 0,
    parser_version: 'import-suggestions/v1',
  } as ImportSuggestionsOut;
}

describe('intake source mapping', () => {
  it('keeps listing as listing and maps social text to pasted_text', () => {
    expect(IMPORT_SOURCES).toEqual(['listing', 'instagram_bio', 'instagram_caption']);
    expect(mapImportSourceToProductFactSource('listing')).toBe('listing');
    expect(mapImportSourceToProductFactSource('instagram_bio')).toBe('pasted_text');
    expect(mapImportSourceToProductFactSource('instagram_caption')).toBe('pasted_text');
    expect(mapImportSourceToProductFactSource('tiktok')).toBe('pasted_text');
    expect(importSourceLabel('listing')).toBe('Listing');
    expect(importSourceLabel('instagram_bio')).toBe('Instagram bio');
    expect(importSourceLabel('instagram_caption')).toBe('Instagram caption');
  });

  it('bounds pasted text and rejects control characters', () => {
    expect(IMPORT_TEXT_MAX).toBe(10000);
    expect(validateImportText('Canvas tote')).toEqual([]);
    expect(validateImportText('x'.repeat(10001)).join(' ')).toContain('10000');
    expect(validateImportText('hello\x00world').join(' ')).toContain('control');
    expect(validateImportText('line one\nline two\ttabbed')).toEqual([]);
  });
});

describe('intake suggestion conversion', () => {
  it('always starts unconfirmed with contract provenance and never truncates', () => {
    const single = toOwnerFactFromSuggestion({
      text: 'Canvas tote',
      source: 'listing',
      product_fact_source: 'listing',
    });
    expect(single).toEqual({ value: 'Canvas tote', confirmed: false, source: 'listing' });
    const edited = toOwnerFactFromSuggestion(
      { text: 'Large', source: 'instagram_bio', product_fact_source: 'pasted_text' },
      '  Extra large tote  ',
    );
    expect(edited).toEqual({ value: '  Extra large tote  ', confirmed: false, source: 'pasted_text' });
    const long = 'y'.repeat(250);
    const kept = toOwnerFactFromSuggestion({ text: long, source: 'listing', product_fact_source: 'listing' });
    expect(kept.value).toBe(long);
    expect(kept.confirmed).toBe(false);
    const coerced = toOwnerFactFromSuggestion({
      text: 'Canvas',
      source: 'instagram_caption',
      product_fact_source: 'blog' as unknown as 'listing',
    });
    expect(coerced).toEqual({ value: 'Canvas', confirmed: false, source: 'pasted_text' });
  });

  it('converts a result list with per-item edits intact', () => {
    const result = intakeResult();
    const facts = toOwnerFactsFromSuggestions(result.suggestions, { 1: 'Extra large' });
    expect(facts).toEqual([
      { value: 'Canvas tote', confirmed: false, source: 'listing' },
      { value: 'Extra large', confirmed: false, source: 'listing' },
    ]);
  });
});

describe('intake UI flow', () => {
  it('renders paste, source, and explicit proposal without verified claims', () => {
    const html = renderToStaticMarkup(
      <QueryClientProvider client={new QueryClient()}>
        <ImportSuggestionsForm onAdd={() => {}} />
      </QueryClientProvider>,
    );
    for (const text of [
      'Paste a listing or social bio',
      'Paste product listing or social bio/caption text',
      'Source for pasted text',
      'Listing',
      'Instagram bio',
      'Instagram caption',
      'Propose suggestions',
      'stay unconfirmed suggestions with provenance',
      'explicitly confirm each',
    ]) {
      expect(html).toContain(text);
    }
    expect(html).not.toContain('Verified');
    expect(html).not.toContain('Approved for export');
  });

  it('shows editable suggestions with provenance and unconfirmed status', () => {
    const html = renderToStaticMarkup(
      <ImportSuggestionsList
        result={intakeResult()}
        edited={{ 1: 'Extra large' }}
        onEdit={() => {}}
        onAddOne={() => {}}
        onAddAll={() => {}}
      />,
    );
    for (const text of [
      '2 suggestions',
      'Status: unconfirmed',
      'Parser: import-suggestions/v1',
      'Suggestion 1',
      'Suggestion 2',
      'Edit suggestion 1',
      'Edit suggestion 2',
      'Canvas tote',
      'Extra large',
      'Source: Listing',
      'Product fact source: Listing',
      'Confirmed: no',
      'Add as allowed claim',
      'Add all as allowed claims',
    ]) {
      expect(html).toContain(text);
    }
    expect(html).not.toContain('Verified');
    expect(html).toContain('Unconfirmed');
  });

  it('escapes pasted markup as plain text', () => {
    const hostile = intakeResult();
    hostile.suggestions = [
      { text: '<script>alert(1)</script>', source: 'listing', product_fact_source: 'listing', status: 'unconfirmed', confirmed: false, index: 0 },
    ];
    const html = renderToStaticMarkup(
      <ImportSuggestionsList result={hostile} edited={{}} onEdit={() => {}} onAddOne={() => {}} onAddAll={() => {}} />,
    );
    expect(html).toContain('&lt;script&gt;alert(1)&lt;/script&gt;');
    expect(html).not.toContain('<script>alert(1)</script>');
  });

  it('flows from intake result through fact form to unconfirmed product facts', () => {
    const result = intakeResult();
    const facts = toOwnerFactsFromSuggestions(result.suggestions, { 1: 'Extra large' });
    const state = emptyOwnerFacts();
    state.material = { value: 'Canvas', confirmed: true, source: 'owner' };
    state.allowed_claims = facts;
    expect(validateOwnerFacts(state)).toEqual([]);
    const out = buildProductFactsInput(state);
    expect(out.material).toEqual({ value: 'Canvas', confirmed: true, source: 'owner' });
    expect(out.allowed_claims).toEqual([
      { value: 'Canvas tote', confirmed: false, source: 'listing' },
      { value: 'Extra large', confirmed: false, source: 'listing' },
    ]);
    const confirmedState = {
      ...state,
      allowed_claims: state.allowed_claims.map(fact => ({ ...fact, confirmed: true })),
    };
    const confirmedOut = buildProductFactsInput(confirmedState);
    expect(confirmedOut.allowed_claims?.every(fact => fact.confirmed)).toBe(true);
  });
});
