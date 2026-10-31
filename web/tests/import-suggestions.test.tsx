import { describe, it, expect } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ImportSuggestionsForm, ImportSuggestionsList, PendingReplaceBanner, StructuredProposalFields } from '../src/components/import-suggestions-form';
import {
  IMPORT_SOURCES,
  IMPORT_TEXT_MAX,
  PENDING_REPLACE_WARNING,
  STRUCTURED_FIELDS,
  STRUCTURED_PARSER_VERSION,
  applyConfirmedStructuredSuggestions,
  applyStructuredSuggestionToState,
  importSourceLabel,
  isStructuredConflictError,
  mapImportSourceToProductFactSource,
  structuredFieldLabel,
  toOwnerFactFromSuggestion,
  toOwnerFactsFromSuggestions,
  validateImportText,
  StructuredReplaceConflict,
  type ImportSuggestionsOut,
  type StructuredImportOut,
} from '../src/lib/import-suggestions';
import {
  buildProductFactsInput,
  emptyOwnerFacts,
  validateOwnerFacts,
} from '../src/lib/product-facts';

function structuredResult(): StructuredImportOut {
  return {
    status: 'unconfirmed',
    source: 'listing',
    product_fact_source: 'listing',
    field_suggestions: [
      { field: 'material', text: 'Full-grain leather tote', source: 'listing', product_fact_source: 'listing', status: 'unconfirmed', confirmed: false, index: 0 },
      { field: 'contents', text: 'Holds six card slots', source: 'listing', product_fact_source: 'listing', status: 'unconfirmed', confirmed: false, index: 1 },
      { field: 'size', text: 'Compact bifold', source: 'listing', product_fact_source: 'listing', status: 'unconfirmed', confirmed: false, index: 2 },
      { field: 'price', text: '$49', source: 'listing', product_fact_source: 'listing', status: 'unconfirmed', confirmed: false, index: 3 },
      { field: 'allowed_claim', text: 'Handmade for Austin commuters', source: 'listing', product_fact_source: 'listing', status: 'unconfirmed', confirmed: false, index: 4 },
      { field: 'founder_note', text: 'I stitch every seam.', source: 'instagram_caption', product_fact_source: 'pasted_text', status: 'unconfirmed', confirmed: false, index: 5 },
    ],
    proposal_digest: 'a'.repeat(64),
    replaced: false,
    truncated: false,
    dropped_duplicates: 0,
    dropped_overlong: 0,
    dropped_empty: 0,
    parser_version: STRUCTURED_PARSER_VERSION,
  } as StructuredImportOut;
}

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
        <ImportSuggestionsForm onApplyState={() => {}} />
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

describe('structured per-field suggestions', () => {
  it('labels every structured field', () => {
    expect([...STRUCTURED_FIELDS]).toEqual([
      'material',
      'contents',
      'size',
      'price',
      'allowed_claim',
      'founder_note',
    ]);
    expect(STRUCTURED_PARSER_VERSION).toBe('import-structured/v1');
    expect(structuredFieldLabel('material')).toBe('Material');
    expect(structuredFieldLabel('contents')).toBe('Contents');
    expect(structuredFieldLabel('size')).toBe('Size');
    expect(structuredFieldLabel('price')).toBe('Price');
    expect(structuredFieldLabel('allowed_claim')).toBe('Allowed claim');
    expect(structuredFieldLabel('founder_note')).toBe('Founder note');
    expect(structuredFieldLabel('unknown-field')).toBe('unknown-field');
  });

  it('routes each suggestion to its matching fact slot, always unconfirmed', () => {
    const state = emptyOwnerFacts();
    const result = structuredResult();
    const material = applyStructuredSuggestionToState(state, result.field_suggestions[0], 'Full-grain leather tote');
    expect(material.material).toEqual({ value: 'Full-grain leather tote', confirmed: false, source: 'listing' });
    expect(material.allowed_claims).toEqual([]);
    const contents = applyStructuredSuggestionToState(state, result.field_suggestions[1], 'Holds six card slots');
    expect(contents.contents.value).toBe('Holds six card slots');
    expect(contents.contents.confirmed).toBe(false);
    const size = applyStructuredSuggestionToState(state, result.field_suggestions[2], 'Compact bifold');
    expect(size.size.value).toBe('Compact bifold');
    const price = applyStructuredSuggestionToState(state, result.field_suggestions[3], '$49');
    expect(price.price).toEqual({ value: '$49', confirmed: false, source: 'listing' });
    const claim = applyStructuredSuggestionToState(state, result.field_suggestions[4], 'Handmade for Austin commuters');
    expect(claim.allowed_claims).toEqual([
      { value: 'Handmade for Austin commuters', confirmed: false, source: 'listing' },
    ]);
    const note = applyStructuredSuggestionToState(state, result.field_suggestions[5], 'I stitch every seam.');
    expect(note.founder_note).toEqual({ value: 'I stitch every seam.', confirmed: false, source: 'pasted_text' });
    expect(validateOwnerFacts(material)).toEqual([]);
  });

  it('applies only field-by-field confirmed suggestions', () => {
    const result = structuredResult();
    const next = applyConfirmedStructuredSuggestions(
      emptyOwnerFacts(),
      result.field_suggestions,
      { 0: 'Edited leather' },
      { 0: true, 3: true },
    );
    expect(next.material.value).toBe('Edited leather');
    expect(next.material.confirmed).toBe(false);
    expect(next.price.value).toBe('$49');
    expect(next.contents.value).toBe('');
    expect(next.size.value).toBe('');
    expect(next.allowed_claims).toEqual([]);
    expect(next.founder_note.value).toBe('');
  });

  it('detects pending-replace conflicts without inventing payloads', () => {
    const proposal = structuredResult();
    const conflict = {
      message: PENDING_REPLACE_WARNING,
      active_digest: 'b'.repeat(64),
      proposal_digest: proposal.proposal_digest,
      proposal,
    };
    expect(isStructuredConflictError(conflict)).toBe(true);
    expect(isStructuredConflictError({ message: 'nope' })).toBe(false);
    expect(isStructuredConflictError(null)).toBe(false);
    const error = new StructuredReplaceConflict(
      conflict.message,
      conflict.active_digest,
      conflict.proposal_digest,
      conflict.proposal,
    );
    expect(error).toBeInstanceOf(Error);
    expect(error.message).toContain('did not replace it');
    expect(error.proposal).toBe(proposal);
    expect(PENDING_REPLACE_WARNING).toContain('did not replace it');
    expect(PENDING_REPLACE_WARNING).toContain('Keep the pending proposal');
  });
});

describe('structured per-field UI flow', () => {
  it('renders one confirmable row per field with unconfirmed status', () => {
    const html = renderToStaticMarkup(
      <StructuredProposalFields result={structuredResult()} idPrefix="test-intake" onApplyOne={() => {}} onApplyAll={() => {}} />,
    );
    for (const text of [
      '6 per-field suggestions',
      'Status: unconfirmed',
      'Parser: import-structured/v1',
      'Suggested Material 1',
      'Suggested Contents 2',
      'Suggested Size 3',
      'Suggested Price 4',
      'Suggested Allowed claim 5',
      'Suggested Founder note 6',
      'Edit suggested material 1',
      'Edit suggested price 4',
      'Full-grain leather tote',
      'Holds six card slots',
      '$49',
      'Suggested field: Material',
      'Suggested field: Price',
      'Confirmed: no',
      'Select material suggestion 1 for the fact form',
      'Select price suggestion 4 for the fact form',
      'Apply material to fact form',
      'Apply price to fact form',
      'Apply selected fields (0) to fact form',
      'Applied values land unconfirmed',
      'Confirm each explicitly in the fact form',
    ]) {
      expect(html).toContain(text);
    }
    expect(html).not.toContain('Verified');
    expect(html).toContain('Unconfirmed');
  });

  it('shows the pending-replace warning with keep and replace actions', () => {
    const html = renderToStaticMarkup(
      <PendingReplaceBanner
        warning={PENDING_REPLACE_WARNING}
        activeDigest={'b'.repeat(64)}
        heldDigest={'a'.repeat(64)}
        heldLabel="Held"
        onReplace={() => {}}
        onKeep={() => {}}
      />,
    );
    for (const text of [
      'did not replace it',
      'Keep the pending proposal',
      `Pending proposal digest: ${'b'.repeat(64)}`,
      `Held proposal digest: ${'a'.repeat(64)}`,
      'Replace pending with held import',
      'Keep pending proposal',
    ]) {
      expect(html).toContain(text);
    }
    expect(html).not.toContain('Verified');
  });

  it('escapes structured markup as plain text', () => {
    const hostile = structuredResult();
    hostile.field_suggestions = [
      { field: 'allowed_claim', text: '<script>alert(1)</script>', source: 'listing', product_fact_source: 'listing', status: 'unconfirmed', confirmed: false, index: 0 },
    ];
    const html = renderToStaticMarkup(
      <StructuredProposalFields result={hostile} idPrefix="test-hostile" onApplyOne={() => {}} onApplyAll={() => {}} />,
    );
    expect(html).toContain('&lt;script&gt;alert(1)&lt;/script&gt;');
    expect(html).not.toContain('<script>alert(1)</script>');
  });

  it('flows from structured intake through fact form to per-field confirmation', () => {
    const result = structuredResult();
    const applied = applyConfirmedStructuredSuggestions(
      emptyOwnerFacts(),
      result.field_suggestions,
      {},
      { 0: true, 3: true, 5: true },
    );
    expect(validateOwnerFacts(applied)).toEqual([]);
    const out = buildProductFactsInput(applied);
    expect(out.material).toEqual({ value: 'Full-grain leather tote', confirmed: false, source: 'listing' });
    expect(out.price).toEqual({ value: '$49', confirmed: false, source: 'listing' });
    expect(out.founder_note?.value).toBe('I stitch every seam.');
    const confirmedState = {
      ...applied,
      material: { ...applied.material, confirmed: true },
      price: { ...applied.price, confirmed: true },
      founder_note: { ...applied.founder_note, confirmed: true },
    };
    expect(validateOwnerFacts(confirmedState)).toEqual([]);
    const confirmedOut = buildProductFactsInput(confirmedState);
    expect(confirmedOut.material?.confirmed).toBe(true);
    expect(confirmedOut.price?.confirmed).toBe(true);
  });
});
