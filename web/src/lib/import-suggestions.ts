import type { components } from './schema';
import { PRODUCT_FACT_SOURCES, type OwnerFactState, type ProductFactSource } from './product-facts';

export type ImportSuggestionsIn = components['schemas']['ImportSuggestionsIn'];
export type ImportSuggestionsOut = components['schemas']['ImportSuggestionsOut'];
export type ImportSuggestionItem = components['schemas']['ImportSuggestionItem'];
export type ImportSource = ImportSuggestionsIn['source'];

export const IMPORT_SOURCES: readonly ImportSource[] = [
  'listing',
  'instagram_bio',
  'instagram_caption',
] as const;

export const IMPORT_TEXT_MAX = 10000;

export const IMPORT_SOURCE_LABELS: Record<ImportSource, string> = {
  listing: 'Listing',
  instagram_bio: 'Instagram bio',
  instagram_caption: 'Instagram caption',
};

export function importSourceLabel(source: string): string {
  return (IMPORT_SOURCE_LABELS as Record<string, string>)[source] ?? source;
}

/** Map an import source to the precise product-facts provenance label.
 * Listing stays listing; pasted social text maps to pasted_text, the
 * contract label for owner-pasted text. Unknown values fail closed to
 * pasted_text and never become owner confirmed input.
 */
export function mapImportSourceToProductFactSource(source: string): ProductFactSource {
  if (source === 'listing') return 'listing';
  if (source === 'instagram_bio' || source === 'instagram_caption') return 'pasted_text';
  return 'pasted_text';
}

function coerceProductFactSource(value: unknown, fallbackImportSource: string): ProductFactSource {
  if (typeof value === 'string' && (PRODUCT_FACT_SOURCES as readonly string[]).includes(value)) {
    return value as ProductFactSource;
  }
  return mapImportSourceToProductFactSource(fallbackImportSource);
}

/** Convert one intake suggestion to an unconfirmed owner fact.
 * Always returns confirmed false with a valid product-facts source.
 * Edited text wins over the parsed text; both stay plain text for the
 * fact form to trim and validate. Never truncates silently.
 */
export function toOwnerFactFromSuggestion(
  suggestion: Pick<ImportSuggestionItem, 'text' | 'source' | 'product_fact_source'>,
  editedText?: string,
): OwnerFactState {
  const raw = typeof editedText === 'string' ? editedText : suggestion.text;
  return {
    value: raw,
    confirmed: false,
    source: coerceProductFactSource(suggestion.product_fact_source, suggestion.source),
  };
}

export function toOwnerFactsFromSuggestions(
  suggestions: Pick<ImportSuggestionItem, 'text' | 'source' | 'product_fact_source' | 'index'>[],
  edited: Record<number, string> = {},
): OwnerFactState[] {
  return suggestions.map(item =>
    toOwnerFactFromSuggestion(item, edited[item.index]),
  );
}

/** Mirror backend intake bounds for early UI feedback.
 * The server still validates with the bounded parser; this never
 * authorizes anything.
 */
export function validateImportText(text: string): string[] {
  const errors: string[] = [];
  if (text.length > IMPORT_TEXT_MAX) {
    errors.push(`Pasted text exceeds ${IMPORT_TEXT_MAX} characters.`);
  }
  if (/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]/.test(text)) {
    errors.push('Pasted text contains disallowed control characters.');
  }
  return errors;
}
