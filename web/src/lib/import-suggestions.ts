import type { components } from './schema';
import { PRODUCT_FACT_SOURCES, type OwnerFactsState, type OwnerFactState, type ProductFactSource } from './product-facts';

export type ImportSuggestionsIn = components['schemas']['ImportSuggestionsIn'];
export type ImportSuggestionsOut = components['schemas']['ImportSuggestionsOut'];
export type ImportSuggestionItem = components['schemas']['ImportSuggestionItem'];
export type ImportSource = ImportSuggestionsIn['source'];
export type StructuredImportOut = components['schemas']['StructuredImportOut'];
export type StructuredSuggestionItem = components['schemas']['StructuredSuggestionItem'];
export type StructuredField = StructuredSuggestionItem['field'];
export type StructuredConflictProposal = {
  message: string;
  active_digest: string;
  proposal_digest: string;
  proposal: StructuredImportOut;
};

export const STRUCTURED_FIELDS: readonly StructuredField[] = [
  'material',
  'contents',
  'size',
  'price',
  'allowed_claim',
  'founder_note',
] as const;

export const STRUCTURED_FIELD_LABELS: Record<StructuredField, string> = {
  material: 'Material',
  contents: 'Contents',
  size: 'Size',
  price: 'Price',
  allowed_claim: 'Allowed claim',
  founder_note: 'Founder note',
};

export function structuredFieldLabel(field: string): string {
  return (STRUCTURED_FIELD_LABELS as Record<string, string>)[field] ?? field;
}

export const STRUCTURED_PARSER_VERSION = 'import-structured/v1';

export const PENDING_REPLACE_WARNING =
  'A pending unconfirmed proposal exists. The new import is held and did not replace it. Keep the pending proposal or confirm replacement.';

export type StructuredSuggestionRef = {
  field: string;
  product_fact_source: string;
};

export class StructuredReplaceConflict extends Error {
  activeDigest: string;
  proposalDigest: string;
  proposal: unknown;
  constructor(message: string, activeDigest: string, proposalDigest: string, proposal: unknown) {
    super(message);
    this.name = 'StructuredReplaceConflict';
    this.activeDigest = activeDigest;
    this.proposalDigest = proposalDigest;
    this.proposal = proposal;
  }
}

export function isStructuredConflictError(value: unknown): value is StructuredConflictProposal {
  if (typeof value !== 'object' || value === null) return false;
  const candidate = value as Record<string, unknown>;
  const proposal = candidate.proposal as Record<string, unknown> | undefined;
  return (
    typeof candidate.message === 'string' &&
    typeof candidate.active_digest === 'string' &&
    typeof candidate.proposal_digest === 'string' &&
    typeof proposal === 'object' &&
    proposal !== null &&
    proposal.status === 'unconfirmed' &&
    Array.isArray(proposal.field_suggestions)
  );
}

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

/** Apply one structured field suggestion to a copy of fact form state.
 * The value lands unconfirmed; the owner still confirms it field by field
 * in the fact form. Core fields (material, contents, size, price) fill
 * their matching slot, the founder note fills its slot, and any other
 * suggestion appends to allowed claims.
 */
export function applyStructuredSuggestionToState(
  state: OwnerFactsState,
  suggestion: StructuredSuggestionRef,
  value: string,
): OwnerFactsState {
  const next: OwnerFactsState = {
    ...state,
    allowed_claims: [...state.allowed_claims],
  };
  const fact: OwnerFactState = {
    value,
    confirmed: false,
    source: coerceProductFactSource(suggestion.product_fact_source, suggestion.field),
  };
  switch (suggestion.field) {
    case 'material':
    case 'contents':
    case 'size':
    case 'price':
      next[suggestion.field] = fact;
      break;
    case 'founder_note':
      next.founder_note = fact;
      break;
    default:
      next.allowed_claims = [...next.allowed_claims, fact];
      break;
  }
  return next;
}

/** Apply every confirmed structured suggestion to fact form state.
 * Only indexes present in `confirmed` land in the state; each keeps its
 * edited text. Unconfirmed indexes stay out of the state entirely.
 */
export function applyConfirmedStructuredSuggestions(
  state: OwnerFactsState,
  suggestions: (StructuredSuggestionRef & { index: number; text: string })[],
  edited: Record<number, string>,
  confirmed: Record<number, boolean>,
): OwnerFactsState {
  let next = state;
  for (const item of suggestions) {
    if (confirmed[item.index] !== true) continue;
    next = applyStructuredSuggestionToState(next, item, edited[item.index] ?? item.text);
  }
  return next;
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
