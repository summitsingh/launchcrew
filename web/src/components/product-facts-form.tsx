'use client';
import type { OwnerFactsState, OwnerFactState, ProductFactSource } from '@/lib/product-facts';
import { ALLOWED_CLAIMS_MAX, FOUNDER_NOTE_MAX, PRODUCT_FACT_FIELDS, PRODUCT_FACT_SOURCES, PRODUCT_FACT_VALUE_MAX } from '@/lib/product-facts';

function FactRow({
  id,
  label,
  fact,
  onChange,
  max,
  help,
}: {
  id: string;
  label: string;
  fact: OwnerFactState;
  onChange: (next: OwnerFactState) => void;
  max: number;
  help: string;
}) {
  return (
    <div>
      <label htmlFor={id}>{label}</label>
      <input
        id={id}
        value={fact.value}
        maxLength={max}
        onChange={e => onChange({ ...fact, value: e.target.value })}
      />
      <p className="hint">{help} Max {max} characters.</p>
      <label className="checkbox" htmlFor={`${id}-confirmed`}>
        <input
          id={`${id}-confirmed`}
          type="checkbox"
          checked={fact.confirmed}
          onChange={e => onChange({ ...fact, confirmed: e.target.checked })}
        />
        I confirm this fact is correct
      </label>
      <label htmlFor={`${id}-source`}>Source for {label.toLowerCase()}</label>
      <select
        id={`${id}-source`}
        value={fact.source}
        onChange={e => onChange({ ...fact, source: e.target.value as ProductFactSource })}
      >
        {PRODUCT_FACT_SOURCES.map(s => (
          <option key={s} value={s}>{s}</option>
        ))}
      </select>
    </div>
  );
}

export function ProductFactsForm({
  state,
  onChange,
}: {
  state: OwnerFactsState;
  onChange: (next: OwnerFactsState) => void;
}) {
  const setField = (name: (typeof PRODUCT_FACT_FIELDS)[number]) => (next: OwnerFactState) =>
    onChange({ ...state, [name]: next });
  const setClaim = (index: number) => (next: OwnerFactState) => {
    const claims = state.allowed_claims.map((c, i) => (i === index ? next : c));
    onChange({ ...state, allowed_claims: claims });
  };
  const addClaim = () => {
    if (state.allowed_claims.length >= ALLOWED_CLAIMS_MAX) return;
    onChange({ ...state, allowed_claims: [...state.allowed_claims, { value: '', confirmed: false, source: 'owner' as ProductFactSource }] });
  };
  const removeClaim = (index: number) => {
    onChange({ ...state, allowed_claims: state.allowed_claims.filter((_, i) => i !== index) });
  };

  return (
    <div>
      <p className="hint">
        Owner input mode. Only values you explicitly confirm can become evidence. Unconfirmed values stay
        suggestions and are never labeled verified. Nothing is confirmed from the brief text.
      </p>
      {PRODUCT_FACT_FIELDS.map(name => (
        <FactRow
          key={name}
          id={`owner-${name}`}
          label={name[0].toUpperCase() + name.slice(1)}
          fact={state[name]}
          onChange={setField(name)}
          max={PRODUCT_FACT_VALUE_MAX}
          help="Optional owner fact."
        />
      ))}
      <h3>Allowed claims ({state.allowed_claims.length} of {ALLOWED_CLAIMS_MAX})</h3>
      <p className="hint">Up to {ALLOWED_CLAIMS_MAX} short claims. Each needs its own confirmation and source.</p>
      {state.allowed_claims.map((claim, i) => (
        <div key={i}>
          <FactRow
            id={`owner-claim-${i}`}
            label={`Allowed claim ${i + 1}`}
            fact={claim}
            onChange={setClaim(i)}
            max={PRODUCT_FACT_VALUE_MAX}
            help="Optional allowed claim."
          />
          <button type="button" className="button outline" onClick={() => removeClaim(i)}>
            Remove claim {i + 1}
          </button>
        </div>
      ))}
      <div className="queue-actions">
        <button
          type="button"
          className="button outline"
          onClick={addClaim}
          disabled={state.allowed_claims.length >= ALLOWED_CLAIMS_MAX}
        >
          Add allowed claim
        </button>
      </div>
      <div>
        <label htmlFor="owner-founder-note">Founder note, optional</label>
        <textarea
          id="owner-founder-note"
          rows={2}
          maxLength={FOUNDER_NOTE_MAX}
          value={state.founder_note.value}
          onChange={e => onChange({ ...state, founder_note: { ...state.founder_note, value: e.target.value } })}
        />
        <p className="hint">
          One complete sentence ending in punctuation. Owner-supplied unverified color, never an authorized
          factual claim. Max {FOUNDER_NOTE_MAX} characters.
        </p>
        <label className="checkbox" htmlFor="owner-founder-note-confirmed">
          <input
            id="owner-founder-note-confirmed"
            type="checkbox"
            checked={state.founder_note.confirmed}
            onChange={e => onChange({ ...state, founder_note: { ...state.founder_note, confirmed: e.target.checked } })}
          />
          I confirm this note is mine to show as unverified color
        </label>
        <label htmlFor="owner-founder-note-source">Source for founder note</label>
        <select
          id="owner-founder-note-source"
          value={state.founder_note.source}
          onChange={e => onChange({ ...state, founder_note: { ...state.founder_note, source: e.target.value as ProductFactSource } })}
        >
          {PRODUCT_FACT_SOURCES.map(s => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
      </div>
    </div>
  );
}
