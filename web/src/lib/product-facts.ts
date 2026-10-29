import type { components } from './schema';

export type ProductFactsInput = components['schemas']['ProductFactsInput'];
export type ProductFactField = components['schemas']['ProductFactField'];
export type FounderNoteField = components['schemas']['FounderNoteField'];
export type ProductFactSource = ProductFactField['source'];

export const PRODUCT_FACT_SOURCES: readonly ProductFactSource[] = [
  'owner',
  'pasted_text',
  'memory',
  'listing',
  'campaign_brief',
  'demo_template',
] as const;

export const PRODUCT_FACT_FIELDS = ['material', 'contents', 'size', 'price'] as const;
export type ProductFactName = (typeof PRODUCT_FACT_FIELDS)[number];

export const PRODUCT_FACT_VALUE_MAX = 200;
export const FOUNDER_NOTE_MAX = 280;
export const ALLOWED_CLAIMS_MAX = 12;

export type OwnerFactState = {
  value: string;
  confirmed: boolean;
  source: ProductFactSource;
};

export type OwnerFactsState = {
  material: OwnerFactState;
  contents: OwnerFactState;
  size: OwnerFactState;
  price: OwnerFactState;
  allowed_claims: OwnerFactState[];
  founder_note: OwnerFactState;
};

export function emptyOwnerFact(): OwnerFactState {
  return { value: '', confirmed: false, source: 'owner' };
}

export function emptyOwnerFacts(): OwnerFactsState {
  return {
    material: emptyOwnerFact(),
    contents: emptyOwnerFact(),
    size: emptyOwnerFact(),
    price: emptyOwnerFact(),
    allowed_claims: [],
    founder_note: emptyOwnerFact(),
  };
}

function normalizeFact(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^\p{L}\p{N}\s]/gu, '')
    .replace(/\s+/g, ' ')
    .trim();
}

/** Mirror backend single-sentence check: one sentence ending in . ! or ?. Prices like $49.99 do not split. */
export function isSingleSentenceOk(text: string): boolean {
  const trimmed = text.trim();
  if (!trimmed) return false;
  if (!/[.!?]$/.test(trimmed)) return false;
  const withoutDecimals = trimmed.replace(/(\d)\.(\d)/g, '$1X$2');
  const parts = withoutDecimals.split(/[.!?]+|\n+/).map(s => s.trim()).filter(Boolean);
  return parts.length === 1;
}

function fieldError(label: string, fact: OwnerFactState, limit: number): string | null {
  if (fact.value.length > limit) return `${label} exceeds ${limit} characters.`;
  if (fact.confirmed && !fact.value.trim()) return `${label} is confirmed but empty.`;
  if (!PRODUCT_FACT_SOURCES.includes(fact.source)) return `${label} source is not supported.`;
  return null;
}

export function validateOwnerFacts(state: OwnerFactsState): string[] {
  const errors: string[] = [];
  for (const name of PRODUCT_FACT_FIELDS) {
    const label = name[0].toUpperCase() + name.slice(1);
    const err = fieldError(label, state[name], PRODUCT_FACT_VALUE_MAX);
    if (err) errors.push(err);
  }
  if (state.allowed_claims.length > ALLOWED_CLAIMS_MAX) {
    errors.push(`Allowed claims exceed the limit of ${ALLOWED_CLAIMS_MAX}.`);
  }
  state.allowed_claims.forEach((fact, i) => {
    const err = fieldError(`Allowed claim ${i + 1}`, fact, PRODUCT_FACT_VALUE_MAX);
    if (err) errors.push(err);
  });
  const note = state.founder_note;
  if (note.value.length > FOUNDER_NOTE_MAX) errors.push(`Founder note exceeds ${FOUNDER_NOTE_MAX} characters.`);
  if (note.confirmed && !note.value.trim()) errors.push('Founder note is confirmed but empty.');
  if (note.value.trim() && !isSingleSentenceOk(note.value)) {
    errors.push('Founder note must be one complete sentence ending in punctuation.');
  }
  if (!PRODUCT_FACT_SOURCES.includes(note.source)) errors.push('Founder note source is not supported.');
  const seen = new Set<string>();
  const confirmedValues: string[] = [];
  for (const name of PRODUCT_FACT_FIELDS) {
    const fact = state[name];
    if (fact.confirmed && fact.value.trim()) confirmedValues.push(fact.value.trim());
  }
  for (const fact of state.allowed_claims) {
    if (fact.confirmed && fact.value.trim()) confirmedValues.push(fact.value.trim());
  }
  for (const value of confirmedValues) {
    const key = normalizeFact(value);
    if (!key || seen.has(key)) {
      errors.push('Duplicate or empty confirmed product fact.');
      break;
    }
    seen.add(key);
  }
  return errors;
}

export function hasAnyOwnerValue(state: OwnerFactsState): boolean {
  for (const name of PRODUCT_FACT_FIELDS) {
    if (state[name].value.trim()) return true;
  }
  if (state.allowed_claims.some(f => f.value.trim())) return true;
  if (state.founder_note.value.trim()) return true;
  return false;
}

function toField(fact: OwnerFactState): ProductFactField {
  return { value: fact.value.trim(), confirmed: fact.confirmed, source: fact.source };
}

/** Build the exact typed product_facts object for owner mode. Empty values are omitted. */
export function buildProductFactsInput(state: OwnerFactsState): ProductFactsInput {
  const out: ProductFactsInput = {};
  for (const name of PRODUCT_FACT_FIELDS) {
    const fact = state[name];
    if (fact.value.trim()) out[name] = toField(fact);
  }
  const claims = state.allowed_claims.filter(f => f.value.trim()).map(toField);
  if (claims.length > 0) out.allowed_claims = claims;
  if (state.founder_note.value.trim()) {
    out.founder_note = {
      value: state.founder_note.value.trim(),
      confirmed: state.founder_note.confirmed,
      source: state.founder_note.source,
    };
  }
  return out;
}

export const SOURCE_LABELS: Record<ProductFactSource, string> = {
  owner: 'Owner',
  pasted_text: 'Pasted text',
  memory: 'Memory',
  listing: 'Listing',
  campaign_brief: 'Campaign brief',
  demo_template: 'Demo template',
};

export function sourceLabel(source: string): string {
  return (SOURCE_LABELS as Record<string, string>)[source] ?? source;
}
