'use client';
import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { api } from '@/lib/api';
import {
  IMPORT_SOURCES,
  IMPORT_TEXT_MAX,
  PENDING_REPLACE_WARNING,
  applyStructuredSuggestionToState,
  importSourceLabel,
  isStructuredConflictError,
  structuredFieldLabel,
  validateImportText,
  StructuredReplaceConflict,
  type ImportSource,
  type ImportSuggestionsOut,
  type StructuredImportOut,
} from '@/lib/import-suggestions';
import { sourceLabel, type OwnerFactsState } from '@/lib/product-facts';

export function ImportSuggestionsList({
  result,
  edited,
  onEdit,
  onAddOne,
  onAddAll,
}: {
  result: ImportSuggestionsOut;
  edited: Record<number, string>;
  onEdit: (index: number, value: string) => void;
  onAddOne: (index: number) => void;
  onAddAll: () => void;
}) {
  if (result.suggestions.length === 0) {
    return <p role="status">No suggestions. Paste listing or bio text above.</p>;
  }
  return (
    <div>
      <p className="hint">
        {result.suggestions.length} suggestion{result.suggestions.length === 1 ? '' : 's'}.
        Status: unconfirmed. Parser: {result.parser_version}.
        {result.truncated ? ' Truncated to the bounded list.' : ''}
        {result.dropped_duplicates > 0 ? ` Dropped duplicates: ${result.dropped_duplicates}.` : ''}
        {result.dropped_overlong > 0 ? ` Dropped overlong: ${result.dropped_overlong}.` : ''}
        {result.dropped_empty > 0 ? ` Skipped empty lines: ${result.dropped_empty}.` : ''}
      </p>
      <ul className="scout-list">
        {result.suggestions.map(item => {
          const current = edited[item.index] ?? item.text;
          return (
            <li key={item.index} className="scout-fact">
              <div className="scout-row">
                <span>Suggestion {item.index + 1}</span>
                <span className="badge pending">Unconfirmed</span>
              </div>
              <label htmlFor={`intake-suggestion-${item.index}`}>Edit suggestion {item.index + 1}</label>
              <input
                id={`intake-suggestion-${item.index}`}
                value={current}
                onChange={e => onEdit(item.index, e.target.value)}
              />
              <p className="hint">
                Source: {importSourceLabel(item.source)} · Product fact source: {sourceLabel(item.product_fact_source)} · Status: unconfirmed · Confirmed: no
              </p>
              <div className="queue-actions">
                <Button type="button" variant="outline" onClick={() => onAddOne(item.index)}>
                  Add as allowed claim
                </Button>
              </div>
            </li>
          );
        })}
      </ul>
      {result.suggestions.length > 1 && (
        <div className="queue-actions">
          <Button type="button" variant="outline" onClick={onAddAll}>
            Add all as allowed claims
          </Button>
        </div>
      )}
    </div>
  );
}

export function StructuredProposalFields({
  result,
  idPrefix,
  onApplyOne,
  onApplyAll,
}: {
  result: {
    field_suggestions: { field: string; text: string; index: number }[];
    parser_version: string;
    truncated: boolean;
    dropped_duplicates: number;
    dropped_overlong: number;
    dropped_empty: number;
  };
  idPrefix: string;
  onApplyOne: (index: number, value: string) => void;
  onApplyAll: (selected: { index: number; value: string }[]) => void;
}) {
  const [edited, setEdited] = useState<Record<number, string>>({});
  const [selected, setSelected] = useState<Record<number, boolean>>({});
  if (result.field_suggestions.length === 0) {
    return <p role="status">No per-field suggestions. Paste listing or bio text above.</p>;
  }
  const toggle = (index: number, checked: boolean) => {
    setSelected(prev => ({ ...prev, [index]: checked }));
  };
  const edit = (index: number, value: string) => {
    setEdited(prev => ({ ...prev, [index]: value }));
  };
  const chosen = result.field_suggestions
    .filter(item => selected[item.index] === true)
    .map(item => ({ index: item.index, value: edited[item.index] ?? item.text }));
  return (
    <div>
      <p className="hint">
        {result.field_suggestions.length} per-field suggestion{result.field_suggestions.length === 1 ? '' : 's'}.
        Status: unconfirmed. Parser: {result.parser_version}.
        {result.truncated ? ' Truncated to the bounded list.' : ''}
        {result.dropped_duplicates > 0 ? ` Dropped duplicates: ${result.dropped_duplicates}.` : ''}
        {result.dropped_overlong > 0 ? ` Dropped overlong: ${result.dropped_overlong}.` : ''}
        {result.dropped_empty > 0 ? ` Skipped empty lines: ${result.dropped_empty}.` : ''}
      </p>
      <ul className="scout-list">
        {result.field_suggestions.map(item => {
          const current = edited[item.index] ?? item.text;
          return (
            <li key={item.index} className="scout-fact">
              <div className="scout-row">
                <span>Suggested {structuredFieldLabel(item.field)} {item.index + 1}</span>
                <span className="badge pending">Unconfirmed</span>
              </div>
              <label htmlFor={`${idPrefix}-field-${item.index}`}>Edit suggested {structuredFieldLabel(item.field).toLowerCase()} {item.index + 1}</label>
              <input
                id={`${idPrefix}-field-${item.index}`}
                value={current}
                onChange={e => edit(item.index, e.target.value)}
              />
              <p className="hint">
                Suggested field: {structuredFieldLabel(item.field)} · Status: unconfirmed · Confirmed: no
              </p>
              <label className="checkbox" htmlFor={`${idPrefix}-select-${item.index}`}>
                <input
                  id={`${idPrefix}-select-${item.index}`}
                  type="checkbox"
                  checked={selected[item.index] === true}
                  onChange={e => toggle(item.index, e.target.checked)}
                />
                Select {structuredFieldLabel(item.field).toLowerCase()} suggestion {item.index + 1} for the fact form
              </label>
              <div className="queue-actions">
                <Button type="button" variant="outline" onClick={() => onApplyOne(item.index, current)}>
                  Apply {structuredFieldLabel(item.field).toLowerCase()} to fact form
                </Button>
              </div>
            </li>
          );
        })}
      </ul>
      {result.field_suggestions.length > 1 && (
        <div className="queue-actions">
          <Button type="button" variant="outline" disabled={chosen.length === 0} onClick={() => onApplyAll(chosen)}>
            Apply selected fields ({chosen.length}) to fact form
          </Button>
        </div>
      )}
      <p className="hint">
        Applied values land unconfirmed in the matching fact field. Confirm each explicitly in the fact form.
      </p>
    </div>
  );
}

export function PendingReplaceBanner({
  warning,
  activeDigest,
  heldDigest,
  heldLabel,
  onReplace,
  onKeep,
}: {
  warning: string;
  activeDigest: string | null | undefined;
  heldDigest: string;
  heldLabel: string;
  onReplace: () => void;
  onKeep: () => void;
}) {
  return (
    <div role="alert" className="message error">
      <p>{warning}</p>
      <p className="hint">
        Pending proposal digest: {activeDigest}. {heldLabel} proposal digest: {heldDigest}.
      </p>
      <div className="queue-actions">
        <Button type="button" variant="outline" onClick={onReplace}>
          Replace pending with held import
        </Button>
        <Button type="button" variant="outline" onClick={onKeep}>
          Keep pending proposal
        </Button>
      </div>
    </div>
  );
}

export function ImportSuggestionsForm({
  onApplyState,
  disabled,
}: {
  onApplyState: (updater: (state: OwnerFactsState) => OwnerFactsState) => void;
  disabled?: boolean;
}) {
  const [text, setText] = useState('');
  const [source, setSource] = useState<ImportSource>('listing');
  const [pending, setPending] = useState<StructuredImportOut | null>(null);
  const [held, setHeld] = useState<StructuredImportOut | null>(null);
  const [warning, setWarning] = useState('');
  const localErrors = validateImportText(text);
  const propose = useMutation({
    mutationFn: async (input: { confirm_replace: boolean }) => {
      const { data, error, response } = await api.POST('/api/import-suggestions/structured', {
        body: {
          text,
          source,
          active_digest: pending?.proposal_digest ?? null,
          confirm_replace: input.confirm_replace,
        },
      });
      if (!response.ok || !data) {
        const conflict = error as unknown;
        if (response.status === 409 && isStructuredConflictError(conflict)) {
          throw new StructuredReplaceConflict(
            conflict.message || PENDING_REPLACE_WARNING,
            conflict.active_digest,
            conflict.proposal_digest,
            conflict.proposal,
          );
        }
        throw new Error(`Request failed (${response.status}). Check the API and try again.`);
      }
      return data;
    },
    onSuccess: data => {
      setPending(data);
      setHeld(null);
      setWarning('');
    },
    onError: (error: unknown) => {
      if (error instanceof StructuredReplaceConflict) {
        setHeld(error.proposal as StructuredImportOut);
        setWarning(error.message);
      }
    },
  });
  const busy = propose.isPending || disabled === true;
  const canPropose = text.trim().length > 0 && localErrors.length === 0 && !busy;
  const otherError = propose.error instanceof Error && !(propose.error instanceof StructuredReplaceConflict)
    ? propose.error.message
    : '';

  const applyOne = (proposal: StructuredImportOut) => (index: number, value: string) => {
    const item = proposal.field_suggestions.find(s => s.index === index);
    if (!item) return;
    onApplyState(prev => applyStructuredSuggestionToState(prev, item, value));
  };
  const applyAll = (proposal: StructuredImportOut) => (selected: { index: number; value: string }[]) => {
    for (const { index, value } of selected) {
      applyOne(proposal)(index, value);
    }
  };

  return (
    <div>
      <h3>Paste a listing or social bio</h3>
      <p className="hint">
        Proposals stay unconfirmed suggestions with provenance. Nothing becomes evidence until you edit
        and explicitly confirm each in the fact form.
      </p>
      <label htmlFor="intake-text">Paste product listing or social bio/caption text</label>
      <textarea
        id="intake-text"
        rows={4}
        maxLength={IMPORT_TEXT_MAX}
        value={text}
        onChange={e => setText(e.target.value)}
      />
      <label htmlFor="intake-source">Source for pasted text</label>
      <select
        id="intake-source"
        value={source}
        onChange={e => setSource(e.target.value as ImportSource)}
      >
        {IMPORT_SOURCES.map(value => (
          <option key={value} value={value}>{importSourceLabel(value)}</option>
        ))}
      </select>
      {localErrors.length > 0 && (
        <div role="alert" className="message error">
          <ul>{localErrors.map((message, i) => <li key={i}>{message}</li>)}</ul>
        </div>
      )}
      {otherError && <p role="alert">{otherError}</p>}
      <div className="queue-actions">
        <Button type="button" variant="outline" disabled={!canPropose} onClick={() => propose.mutate({ confirm_replace: false })}>
          {propose.isPending ? 'Proposing...' : 'Propose suggestions'}
        </Button>
      </div>
      {warning && held && (
        <PendingReplaceBanner
          warning={warning}
          activeDigest={pending?.proposal_digest}
          heldDigest={held.proposal_digest}
          heldLabel="Held"
          onReplace={() => propose.mutate({ confirm_replace: true })}
          onKeep={() => { setHeld(null); setWarning(''); }}
        />
      )}
      {pending && (
        <div>
          <h4>Pending per-field proposal ({importSourceLabel(pending.source)})</h4>
          {pending.replaced && <p className="hint">Pending proposal was replaced by your confirmed replacement.</p>}
          <StructuredProposalFields
            result={pending}
            idPrefix="intake-pending"
            onApplyOne={applyOne(pending)}
            onApplyAll={applyAll(pending)}
          />
        </div>
      )}
      {held && (
        <div>
          <h4>Held new import (did not replace pending)</h4>
          <StructuredProposalFields
            result={held}
            idPrefix="intake-held"
            onApplyOne={applyOne(held)}
            onApplyAll={applyAll(held)}
          />
        </div>
      )}
    </div>
  );
}
