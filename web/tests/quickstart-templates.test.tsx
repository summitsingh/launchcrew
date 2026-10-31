import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import {
  QUICKSTART_TEMPLATES,
  QuickstartTemplates,
  attestPrefillField,
  buildQuickstartPrefill,
  findUnreviewedTemplateFields,
  getQuickstartTemplate,
  hasUnreviewedTemplateFields,
  isStillQuickstartExample,
  quickstartToAllowedClaims,
  quickstartToOwnerFacts,
} from '../src/components/quickstart-templates';
import { buildProductFactsInput, validateOwnerFacts } from '../src/lib/product-facts';

describe('quick-start template catalog', () => {
  it('offers wallet, food, mobile app, and local service starters', () => {
    expect(QUICKSTART_TEMPLATES.map(t => t.id)).toEqual([
      'quickstart_wallet',
      'quickstart_food',
      'quickstart_mobile_app',
      'quickstart_local_service',
    ]);
    expect(QUICKSTART_TEMPLATES.map(t => t.kind)).toEqual(['wallet', 'food', 'mobile_app', 'local_service']);
  });

  it('uses invented names with no contact details', () => {
    const text = JSON.stringify(QUICKSTART_TEMPLATES);
    expect(text).not.toMatch(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/i);
    for (const brand of ['Coca', 'Pepsi', 'Nike', 'Samsung']) {
      expect(text).not.toContain(brand);
    }
  });

  it('rejects unknown template ids', () => {
    expect(() => getQuickstartTemplate('quickstart_spaceship' as never)).toThrow('Unknown');
  });
});

describe('quick-start non-confirmation', () => {
  it('converts every value to unconfirmed demo_template facts', () => {
    for (const template of QUICKSTART_TEMPLATES) {
      const state = quickstartToOwnerFacts(template);
      for (const name of ['material', 'contents', 'size', 'price', 'founder_note'] as const) {
        expect(state[name].confirmed).toBe(false);
        expect(state[name].source).toBe('demo_template');
        expect(state[name].value.trim().length).toBeGreaterThan(0);
      }
      expect(state.allowed_claims.length).toBeGreaterThan(0);
      for (const claim of state.allowed_claims) {
        expect(claim.confirmed).toBe(false);
        expect(claim.source).toBe('demo_template');
      }
    }
  });

  it('passes intake validation as suggestions and builds unconfirmed input', () => {
    const state = quickstartToOwnerFacts(getQuickstartTemplate('quickstart_food'));
    expect(validateOwnerFacts(state)).toEqual([]);
    const out = buildProductFactsInput(state);
    expect(out.price).toEqual({ value: '$18 per box', confirmed: false, source: 'demo_template' });
    expect(out.allowed_claims?.every(c => c.confirmed === false)).toBe(true);
  });

  it('requires an explicit confirmation step before any value counts as confirmed', () => {
    const state = quickstartToOwnerFacts(getQuickstartTemplate('quickstart_local_service'));
    const out = buildProductFactsInput(state);
    const confirmedCount = [
      out.material,
      out.contents,
      out.size,
      out.price,
      ...(out.allowed_claims ?? []),
    ].filter(f => f?.confirmed === true).length;
    expect(confirmedCount).toBe(0);
    const confirmed = { ...state, price: { ...state.price, confirmed: true } };
    expect(buildProductFactsInput(confirmed).price?.confirmed).toBe(true);
  });

  it('populates wallet facts as complete unconfirmed demo_template values', () => {
    const state = quickstartToOwnerFacts(getQuickstartTemplate('quickstart_wallet'));
    expect(state.material.value).toBe('Full-grain leather minimalist bifold wallet');
    expect(state.price.value).toBe('$49 for the standard bifold');
    expect(state.founder_note.value).toBe('I designed Cinderfold wallets for my own front pocket carry.');
    const out = buildProductFactsInput(state);
    expect(out.material).toEqual({ value: 'Full-grain leather minimalist bifold wallet', confirmed: false, source: 'demo_template' });
    expect(out.price?.confirmed).toBe(false);
    expect(validateOwnerFacts(state)).toEqual([]);
  });

  it('exposes allowed-claim conversion without confirming', () => {
    const claims = quickstartToAllowedClaims(getQuickstartTemplate('quickstart_mobile_app'));
    expect(claims.length).toBe(2);
    for (const claim of claims) {
      expect(claim).toEqual({ value: expect.any(String), confirmed: false, source: 'demo_template' });
    }
  });

  it('builds an unconfirmed prefill envelope with per-field provenance', () => {
    const prefill = buildQuickstartPrefill(getQuickstartTemplate('quickstart_food'));
    expect(prefill.templateId).toBe('quickstart_food');
    expect(findUnreviewedTemplateFields(prefill.state, prefill.provenance)).toEqual([]);
    expect(hasUnreviewedTemplateFields(prefill.state, prefill.provenance)).toBe(false);
    expect(Object.keys(prefill.provenance)).toContain('price');
    expect(Object.keys(prefill.provenance)).toContain('founder_note');
    expect(Object.keys(prefill.provenance)).toContain('allowed_claims[0]');
    for (const record of Object.values(prefill.provenance)) {
      expect(record.ownerAttested).toBe(false);
      expect(record.exampleValue.trim().length).toBeGreaterThan(0);
    }
  });

  it('never blocks coincident real values when no template was used', () => {
    const prefill = buildQuickstartPrefill(getQuickstartTemplate('quickstart_food'));
    const ordinary = {
      ...prefill.state,
      price: { value: prefill.state.price.value, confirmed: true, source: 'owner' as const },
    };
    expect(findUnreviewedTemplateFields(ordinary, {})).toEqual([]);
    expect(hasUnreviewedTemplateFields(ordinary, {})).toBe(false);
  });

  it('flags confirmed unchanged examples, founder note included', () => {
    const prefill = buildQuickstartPrefill(getQuickstartTemplate('quickstart_food'));
    const priceConfirmed = {
      ...prefill.state,
      price: { ...prefill.state.price, confirmed: true, source: 'owner' as const },
    };
    expect(findUnreviewedTemplateFields(priceConfirmed, prefill.provenance)).toEqual([
      { field: 'price', reason: 'unchanged_example', value: prefill.state.price.value },
    ]);
    expect(hasUnreviewedTemplateFields(priceConfirmed, prefill.provenance)).toBe(true);
    const noteConfirmed = {
      ...prefill.state,
      founder_note: { ...prefill.state.founder_note, confirmed: true, source: 'owner' as const },
    };
    expect(findUnreviewedTemplateFields(noteConfirmed, prefill.provenance)).toEqual([
      { field: 'founder_note', reason: 'unchanged_example', value: prefill.state.founder_note.value },
    ]);
  });

  it('treats trivial edits as still the example, not as review', () => {
    expect(isStillQuickstartExample('Recyclable cardboard box!', 'Recyclable cardboard box')).toBe(true);
    expect(isStillQuickstartExample('recyclable cardboard box', 'Recyclable cardboard box')).toBe(true);
    expect(
      isStillQuickstartExample(
        'Baked in small batches in the Harborlight kitchens',
        'Baked in small batches in the Harborlight kitchen',
      ),
    ).toBe(true);
    expect(
      isStillQuickstartExample('Weekend group workshop in the park pavilion', 'Recyclable cardboard box'),
    ).toBe(false);
    const prefill = buildQuickstartPrefill(getQuickstartTemplate('quickstart_food'));
    const tweaked = {
      ...prefill.state,
      allowed_claims: prefill.state.allowed_claims.map((claim, i) =>
        i === 1 ? { ...claim, value: `${claim.value}!`, confirmed: true, source: 'owner' as const } : claim,
      ),
    };
    expect(findUnreviewedTemplateFields(tweaked, prefill.provenance)).toEqual([
      { field: 'allowed_claims[1]', reason: 'unchanged_example', value: 'Recyclable cardboard box!' },
    ]);
  });

  it('fails closed on bypass attempts', () => {
    const prefill = buildQuickstartPrefill(getQuickstartTemplate('quickstart_local_service'));
    // Source flip without explicit review still flags the unchanged text.
    const flipped = {
      ...prefill.state,
      price: { ...prefill.state.price, confirmed: true, source: 'owner' as const },
    };
    expect(hasUnreviewedTemplateFields(flipped, prefill.provenance)).toBe(true);
    // Genuine replacement that keeps demo_template provenance is rejected:
    // the owner never stated where the fact comes from.
    const staleSource = {
      ...prefill.state,
      price: { value: 'A completely rewritten owner price fact', confirmed: true, source: 'demo_template' as const },
    };
    expect(findUnreviewedTemplateFields(staleSource, prefill.provenance)).toEqual([
      { field: 'price', reason: 'provenance_not_updated', value: 'A completely rewritten owner price fact' },
    ]);
    expect(() => attestPrefillField(prefill.provenance, 'price_eur')).toThrow('Unknown prefilled field');
  });

  it('accepts replaced or attested values with a genuine source', () => {
    const prefill = buildQuickstartPrefill(getQuickstartTemplate('quickstart_local_service'));
    const replaced = {
      ...prefill.state,
      price: { value: 'Weekend group workshop in the park pavilion', confirmed: true, source: 'owner' as const },
    };
    expect(findUnreviewedTemplateFields(replaced, prefill.provenance)).toEqual([]);
    const kept = {
      ...prefill.state,
      price: { ...prefill.state.price, confirmed: true, source: 'owner' as const },
    };
    const attested = attestPrefillField(prefill.provenance, 'price');
    expect(attested.price.ownerAttested).toBe(true);
    expect(prefill.provenance.price.ownerAttested).toBe(false);
    expect(findUnreviewedTemplateFields(kept, attested)).toEqual([]);
    expect(hasUnreviewedTemplateFields(kept, attested)).toBe(false);
  });
});

describe('quick-start templates UI', () => {
  it('labels every template fictional and unconfirmed with no verified claims', () => {
    const html = renderToStaticMarkup(<QuickstartTemplates onApply={() => {}} />);
    expect(html).toContain('Quick-start templates');
    expect(html).toContain('Fictional examples only');
    expect(html).toContain('Nothing is confirmed, verified, or published here');
    expect(html).toContain('does not enforce that review');
    for (const template of QUICKSTART_TEMPLATES) {
      expect(html).toContain(template.title);
      expect(html).toContain(`Use ${template.title}`);
    }
    expect(html.match(/Fictional, unconfirmed/g)?.length).toBe(4);
    expect(html).toContain('Confirmed: no');
    expect(html).not.toContain('Verified');
    expect(html).not.toContain('Approved for export');
  });

  it('disables selection when asked', () => {
    const html = renderToStaticMarkup(<QuickstartTemplates onApply={() => {}} disabled />);
    expect(html).toContain('disabled');
  });
});
