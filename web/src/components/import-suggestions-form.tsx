'use client';
import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { api, unwrap } from '@/lib/api';
import {
  IMPORT_SOURCES,
  IMPORT_TEXT_MAX,
  importSourceLabel,
  toOwnerFactFromSuggestion,
  toOwnerFactsFromSuggestions,
  validateImportText,
  type ImportSource,
  type ImportSuggestionItem,
  type ImportSuggestionsOut,
} from '@/lib/import-suggestions';
import { sourceLabel, type OwnerFactState } from '@/lib/product-facts';

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

export function ImportSuggestionsForm({
  onAdd,
  disabled,
}: {
  onAdd: (facts: OwnerFactState[]) => void;
  disabled?: boolean;
}) {
  const [text, setText] = useState('');
  const [source, setSource] = useState<ImportSource>('listing');
  const [result, setResult] = useState<ImportSuggestionsOut | null>(null);
  const [edited, setEdited] = useState<Record<number, string>>({});
  const localErrors = validateImportText(text);
  const propose = useMutation({
    mutationFn: () => unwrap(api.POST('/api/import-suggestions', { body: { text, source } })),
    onSuccess: data => {
      setResult(data);
      setEdited({});
    },
  });
  const busy = propose.isPending || disabled === true;
  const canPropose = text.trim().length > 0 && localErrors.length === 0 && !busy;

  const handleEdit = (index: number, value: string) => {
    setEdited(prev => ({ ...prev, [index]: value }));
  };
  const handleAddOne = (index: number) => {
    if (!result) return;
    const item = result.suggestions.find(s => s.index === index) as ImportSuggestionItem | undefined;
    if (!item) return;
    onAdd([toOwnerFactFromSuggestion(item, edited[index] ?? item.text)]);
  };
  const handleAddAll = () => {
    if (!result) return;
    onAdd(toOwnerFactsFromSuggestions(result.suggestions, edited));
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
      {propose.error && <p role="alert">{propose.error.message}</p>}
      <div className="queue-actions">
        <Button type="button" variant="outline" disabled={!canPropose} onClick={() => propose.mutate()}>
          {propose.isPending ? 'Proposing...' : 'Propose suggestions'}
        </Button>
      </div>
      {result && (
        <ImportSuggestionsList
          result={result}
          edited={edited}
          onEdit={handleEdit}
          onAddOne={handleAddOne}
          onAddAll={handleAddAll}
        />
      )}
    </div>
  );
}
