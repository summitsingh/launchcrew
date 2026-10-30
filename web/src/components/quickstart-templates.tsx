'use client';
import { emptyOwnerFacts, type OwnerFactsState, type OwnerFactState } from '@/lib/product-facts';

// Slice 5 foundation: fictional quick-start intake templates.
//
// INTEGRATION (wiring not done here, parent owns it):
// 1. Render <QuickstartTemplates onApply={...} /> above the existing
//    ProductFactsForm without editing shared files.
// 2. In onApply, merge the returned OwnerFactsState into the parent form
//    state as UNCONFIRMED values only. Never set confirmed=true here.
// 3. The owner must still review each example, replace it with the owner
//    fact (or explicitly attest it), and check each confirmation box in
//    ProductFactsForm. This panel does NOT enforce that per-field review
//    itself: ProductFactsForm lets an unchanged example be confirmed, so
//    the parent must send the prefill provenance to the backend, have the
//    backend persist it server-side, render a separate per-field review
//    control for prefilled fields, and block submit while
//    findUnreviewedTemplateFields returns any flag. Then validate with
//    validateOwnerFacts and submit with buildProductFactsInput. The
//    backend must revalidate with assert_template_review_complete against
//    its server-retained provenance copy: frontend state is never the
//    enforcement boundary.
// 4. This component never submits, never confirms, never verifies, and
//    never publishes. It is not a live feature until the parent wires it.
// 5. facts/quickstart_*.json is authoritative. QUICKSTART_TEMPLATES below
//    duplicates those values for offline rendering; the parity test in
//    tests/test_quickstart_templates.py fails when they drift.

export type QuickstartTemplateId = 'quickstart_food' | 'quickstart_mobile_app' | 'quickstart_local_service';

type QuickstartFact = { value: string };

export type QuickstartTemplate = {
  id: QuickstartTemplateId;
  title: string;
  kind: 'food' | 'mobile_app' | 'local_service';
  description: string;
  material: QuickstartFact;
  contents: QuickstartFact;
  size: QuickstartFact;
  price: QuickstartFact;
  allowed_claims: QuickstartFact[];
  founder_note: QuickstartFact;
};

function fact(value: string): OwnerFactState {
  return { value, confirmed: false, source: 'demo_template' };
}

export const QUICKSTART_TEMPLATES: readonly QuickstartTemplate[] = [
  {
    id: 'quickstart_food',
    title: 'Fictional food product starter',
    kind: 'food',
    description: 'Example starter for an invented oat snack bar. No real brand is named.',
    material: { value: 'Oats, honey, and sunflower seeds' },
    contents: { value: 'Twelve baked oat bars per box' },
    size: { value: 'Box of 12 bars, 40 g each' },
    price: { value: '$18 per box' },
    allowed_claims: [
      { value: 'Baked in small batches in the Harborlight kitchen' },
      { value: 'Recyclable cardboard box' },
    ],
    founder_note: { value: 'I started Harborlight snacks for weekend trail walks.' },
  },
  {
    id: 'quickstart_mobile_app',
    title: 'Fictional mobile app starter',
    kind: 'mobile_app',
    description: 'Example starter for an invented daily habit tracker app. No real app is named.',
    material: { value: 'Fernway habit tracker app for daily routines' },
    contents: { value: 'Daily check-ins, streaks, and gentle reminders' },
    size: { value: 'Phone app that works offline' },
    price: { value: '$4 per month after a free week' },
    allowed_claims: [
      { value: 'Streak view for daily check-ins' },
      { value: 'Reminder tones stay off by default' },
    ],
    founder_note: { value: 'I built Fernway to keep my own evening routine steady.' },
  },
  {
    id: 'quickstart_local_service',
    title: 'Fictional local service starter',
    kind: 'local_service',
    description: 'Example starter for an invented curbside bike tune-up stand. No real business is named.',
    material: { value: 'Curbside bike tune-up at the Maple Street stand' },
    contents: { value: 'Brake check, gear tune, and tire top-up' },
    size: { value: 'Thirty minute curbside appointment' },
    price: { value: '$35 per tune-up visit' },
    allowed_claims: [
      { value: 'Same-day slots on Saturdays at Maple Street' },
      { value: 'Basic parts carried on the stand cart' },
    ],
    founder_note: { value: 'I opened the Maple Street stand to fix neighbor bikes faster.' },
  },
] as const;

export function getQuickstartTemplate(id: QuickstartTemplateId): QuickstartTemplate {
  const found = QUICKSTART_TEMPLATES.find(t => t.id === id);
  if (!found) throw new Error(`Unknown quick-start template: ${id}`);
  return found;
}

/** Convert one template to a full unconfirmed OwnerFactsState. Always confirmed:false. */
export function quickstartToOwnerFacts(template: QuickstartTemplate): OwnerFactsState {
  const state = emptyOwnerFacts();
  state.material = fact(template.material.value);
  state.contents = fact(template.contents.value);
  state.size = fact(template.size.value);
  state.price = fact(template.price.value);
  state.allowed_claims = template.allowed_claims.map(c => fact(c.value));
  state.founder_note = fact(template.founder_note.value);
  return state;
}

/** Convert one template to unconfirmed allowed-claim facts for onAdd-style parents. */
export function quickstartToAllowedClaims(template: QuickstartTemplate): OwnerFactState[] {
  return template.allowed_claims.map(c => fact(c.value));
}

export type QuickstartFieldKey = string;

export type QuickstartFieldProvenance = {
  templateId: QuickstartTemplateId;
  exampleValue: string;
  ownerAttested: boolean;
};

export type QuickstartProvenance = Record<QuickstartFieldKey, QuickstartFieldProvenance>;

export type QuickstartPrefill = {
  templateId: QuickstartTemplateId;
  state: OwnerFactsState;
  provenance: QuickstartProvenance;
};

function entryForKey(state: OwnerFactsState, key: QuickstartFieldKey): OwnerFactState | null {
  const claimMatch = key.match(/^allowed_claims\[(\d+)\]$/);
  if (claimMatch) {
    const index = Number(claimMatch[1]);
    return state.allowed_claims[index] ?? null;
  }
  const entry = (state as unknown as Record<string, OwnerFactState | OwnerFactState[]>)[key];
  return entry && !Array.isArray(entry) ? (entry as OwnerFactState) : null;
}

/**
 * Build the selection envelope for one template: unconfirmed form state
 * plus per-field provenance. The parent must send the provenance to the
 * backend, which persists it server-side and revalidates on submit. This
 * client record is a convenience copy only and never an enforcement
 * boundary.
 */
export function buildQuickstartPrefill(template: QuickstartTemplate): QuickstartPrefill {
  const state = quickstartToOwnerFacts(template);
  const provenance: QuickstartProvenance = {};
  for (const name of ['material', 'contents', 'size', 'price', 'founder_note'] as const) {
    provenance[name] = { templateId: template.id, exampleValue: template[name].value, ownerAttested: false };
  }
  template.allowed_claims.forEach((claim, index) => {
    provenance[`allowed_claims[${index}]`] = { templateId: template.id, exampleValue: claim.value, ownerAttested: false };
  });
  return { templateId: template.id, state, provenance };
}

/** Mark one prefilled field explicitly reviewed. Persist the result server-side. */
export function attestPrefillField(provenance: QuickstartProvenance, key: QuickstartFieldKey): QuickstartProvenance {
  if (!provenance[key]) throw new Error(`Unknown prefilled field: ${key}`);
  return { ...provenance, [key]: { ...provenance[key], ownerAttested: true } };
}

function normalizeQuickstartValue(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^\p{L}\p{N}\s]/gu, '')
    .replace(/\s+/g, ' ')
    .trim();
}

function quickstartTokens(text: string): string[] {
  return (text.toLowerCase().match(/[a-z0-9]+/g) ?? []);
}

function tokenEditDistance(a: string[], b: string[]): number {
  if (a.join(' ') === b.join(' ')) return 0;
  if (a.length === 0) return b.length;
  if (b.length === 0) return a.length;
  let prev = b.map((_, j) => j + 1);
  prev.unshift(0);
  for (let i = 1; i <= a.length; i++) {
    const cur = [i];
    for (let j = 1; j <= b.length; j++) {
      cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] !== b[j - 1] ? 1 : 0));
    }
    prev = cur;
  }
  return prev[b.length];
}

/**
 * True when a submitted value is the example verbatim or trivially edited
 * (case, punctuation, whitespace, pluralization, or a one-or-two-token
 * tweak). An edit never proves review on its own.
 */
export function isStillQuickstartExample(value: string, example: string): boolean {
  if (normalizeQuickstartValue(value) === normalizeQuickstartValue(example)) return true;
  const a = quickstartTokens(value);
  const b = quickstartTokens(example);
  if (a.length === 0 || b.length === 0) return true;
  return tokenEditDistance(a, b) <= 2;
}

export type QuickstartReviewFlag = { field: string; reason: string; value: string };

/**
 * Check confirmed template-derived fields against provenance. Only fields
 * present in provenance are examined: ordinary facts submitted without a
 * template are NEVER flagged, even on coincidental text matches. Reasons:
 * unchanged_example, trivially_modified, provenance_not_updated. A field
 * passes when substantively replaced with a genuine source, or explicitly
 * attested with a genuine source. Client-side convenience only; the
 * backend must revalidate against server-retained provenance.
 */
export function findUnreviewedTemplateFields(
  state: OwnerFactsState,
  provenance: QuickstartProvenance,
): QuickstartReviewFlag[] {
  const flagged: QuickstartReviewFlag[] = [];
  for (const [key, record] of Object.entries(provenance)) {
    const entry = entryForKey(state, key);
    if (!entry || entry.confirmed !== true || !entry.value.trim()) continue;
    if (entry.source === 'demo_template') {
      flagged.push({ field: key, reason: 'provenance_not_updated', value: entry.value });
    } else if (isStillQuickstartExample(entry.value, record.exampleValue)) {
      if (record.ownerAttested) continue;
      const reason =
        normalizeQuickstartValue(entry.value) === normalizeQuickstartValue(record.exampleValue)
          ? 'unchanged_example'
          : 'trivially_modified';
      flagged.push({ field: key, reason, value: entry.value });
    }
  }
  return flagged;
}

/** True while any template-derived confirmation still needs owner review. */
export function hasUnreviewedTemplateFields(state: OwnerFactsState, provenance: QuickstartProvenance): boolean {
  return findUnreviewedTemplateFields(state, provenance).length > 0;
}

function suggestionCount(template: QuickstartTemplate): number {
  return 4 + template.allowed_claims.length + 1;
}

export function QuickstartTemplates({
  onApply,
  disabled,
}: {
  onApply: (state: OwnerFactsState, templateId: QuickstartTemplateId) => void;
  disabled?: boolean;
}) {
  return (
    <div>
      <h3>Quick-start templates</h3>
      <p className="hint">
        Fictional examples only. Choosing a template fills the intake form with unconfirmed
        suggestions marked Demo template. Nothing is confirmed, verified, or published here.
        Review each example, replace it with your own fact, and confirm each checkbox yourself
        in the fact form. This panel does not enforce that review; unchanged examples must be
        rejected before submit.
      </p>
      <ul className="scout-list">
        {QUICKSTART_TEMPLATES.map(template => (
          <li key={template.id} className="scout-fact">
            <div className="scout-row">
              <span>{template.title}</span>
              <span className="badge pending">Fictional, unconfirmed</span>
            </div>
            <p className="hint">
              {template.description} Includes {suggestionCount(template)} suggestions. Source: Demo
              template. Confirmed: no.
            </p>
            <div className="queue-actions">
              <button
                type="button"
                className="button outline"
                disabled={disabled === true}
                onClick={() => onApply(quickstartToOwnerFacts(template), template.id)}
              >
                Use {template.title}
              </button>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
