'use client';
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { api, unwrap } from '@/lib/api';
import {
  buildProductFactsInput,
  ownerFactsFromInput,
  type OwnerFactsState,
} from '@/lib/product-facts';
import type { components } from '@/lib/schema';

type FactProduct = components['schemas']['FactProductOut'];
type FactVariant = components['schemas']['FactVariantOut'];

export type LibrarySelection = {
  variantId: string;
  productId: string;
  productName: string;
  variantName: string;
  /** Canonical snapshot of the loaded facts for submit-path comparison. */
  snapshot: string;
};

export function MissingFactsPrompt({
  missing,
  waived,
  onWaive,
}: {
  missing: string[];
  waived: boolean;
  onWaive: (next: boolean) => void;
}) {
  if (missing.length === 0) return null;
  return (
    <div role="alert" data-testid="missing-facts-prompt" className="message error">
      <p>
        Missing core facts before drafting: {missing.join(', ')}. Add confirmed values above,
        or record an explicit owner waiver to draft without them.
      </p>
      <label className="checkbox" htmlFor="waive-missing-core">
        <input
          id="waive-missing-core"
          data-testid="waive-missing-core"
          type="checkbox"
          checked={waived}
          onChange={e => onWaive(e.target.checked)}
        />
        Draft without these core facts and record an owner waiver on the receipt
      </label>
    </div>
  );
}

export function FactLibrarySection({
  state,
  selection,
  onSelectionChange,
  onLoad,
  notify,
  fail,
}: {
  state: OwnerFactsState;
  selection: LibrarySelection | null;
  onSelectionChange: (next: LibrarySelection | null) => void;
  onLoad: (next: OwnerFactsState, snapshot: LibrarySelection) => void;
  notify: (text: string) => void;
  fail: (error: Error) => void;
}) {
  const client = useQueryClient();
  const [productId, setProductId] = useState('');
  const [variantId, setVariantId] = useState('');
  const [newProductName, setNewProductName] = useState('');
  const [newVariantName, setNewVariantName] = useState('');

  const products = useQuery({
    queryKey: ['fact-products'],
    queryFn: () => unwrap(api.GET('/api/fact-products')),
  });
  const variants = useQuery({
    queryKey: ['fact-variants', productId],
    queryFn: () => unwrap(api.GET('/api/fact-products/{product_id}/variants', { params: { path: { product_id: productId } } })),
    enabled: !!productId,
  });

  const refresh = () => {
    client.invalidateQueries({ queryKey: ['fact-products'] });
    client.invalidateQueries({ queryKey: ['fact-variants'] });
  };

  const createProduct = useMutation({
    mutationFn: () => unwrap(api.POST('/api/fact-products', { body: { name: newProductName.trim() } })),
    onSuccess: product => {
      setNewProductName('');
      setProductId(product.id);
      refresh();
      notify(`Saved product ${product.name} to the facts library.`);
    },
    onError: fail,
  });

  const saveVariant = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST('/api/fact-products/{product_id}/variants', {
          params: { path: { product_id: productId } },
          body: { name: newVariantName.trim(), product_facts: buildProductFactsInput(state) },
        }),
      ),
    onSuccess: variant => {
      setNewVariantName('');
      setVariantId(variant.id);
      refresh();
      notify(`Saved variant ${variant.name} to the facts library. Confirm it before reuse.`);
    },
    onError: fail,
  });

  const confirmVariant = useMutation({
    mutationFn: (id: string) => unwrap(api.POST('/api/fact-variants/{variant_id}/confirm', { params: { path: { variant_id: id } } })),
    onSuccess: variant => {
      refresh();
      notify(`Confirmed variant ${variant.name}. It can be reused into a new run.`);
    },
    onError: fail,
  });

  const loadVariant = useMutation({
    mutationFn: () => unwrap(api.GET('/api/fact-variants/{variant_id}', { params: { path: { variant_id: variantId } } })),
    onSuccess: variant => {
      const next = ownerFactsFromInput(variant.product_facts as FactVariant['product_facts']);
      const snapshot: LibrarySelection = {
        variantId: variant.id,
        productId: variant.product_id,
        productName: products.data?.find((p: FactProduct) => p.id === variant.product_id)?.name ?? '',
        variantName: variant.name,
        snapshot: JSON.stringify(buildProductFactsInput(next)),
      };
      onLoad(next, snapshot);
      onSelectionChange(snapshot);
      setVariantId(variant.id);
      notify(
        variant.confirmed
          ? `Loaded confirmed variant ${variant.name} into the form.`
          : `Loaded unconfirmed variant ${variant.name} into the form. Confirm each fact before drafting.`,
      );
    },
    onError: fail,
  });

  const selectedVariant = variants.data?.find((v: FactVariant) => v.id === variantId) ?? null;

  return (
    <div data-testid="fact-library" className="panel">
      <p className="eyebrow">FACTS LIBRARY</p>
      <h3>Reuse a saved product</h3>
      <p className="hint">
        Pick a product and variant to load its confirmed facts into the form without retyping.
        A new run binds a snapshot copy, so later library edits never rewrite a stored run.
      </p>
      {products.isPending && <p role="status">Loading saved products...</p>}
      {products.error && <p role="alert">Saved products are unavailable.</p>}
      <label htmlFor="fact-product-select">Saved product</label>
      <select
        id="fact-product-select"
        data-testid="fact-product-select"
        value={productId}
        onChange={e => {
          setProductId(e.target.value);
          setVariantId('');
        }}
      >
        <option value="">Select a product</option>
        {(products.data ?? []).map((p: FactProduct) => (
          <option key={p.id} value={p.id}>
            {p.name} ({p.variant_count} variant{p.variant_count === 1 ? '' : 's'})
          </option>
        ))}
      </select>
      <div className="queue-actions">
        <input
          id="fact-product-name"
          data-testid="fact-product-name"
          value={newProductName}
          onChange={e => setNewProductName(e.target.value)}
          placeholder="New product name"
          maxLength={120}
        />
        <Button
          variant="outline"
          data-testid="fact-product-create"
          disabled={createProduct.isPending || !newProductName.trim()}
          onClick={() => createProduct.mutate()}
        >
          Save product
        </Button>
      </div>
      {productId && (
        <>
          <label htmlFor="fact-variant-select">Saved variant</label>
          <select
            id="fact-variant-select"
            data-testid="fact-variant-select"
            value={variantId}
            onChange={e => setVariantId(e.target.value)}
            disabled={!variants.data}
          >
            <option value="">Select a variant</option>
            {(variants.data ?? []).map((v: FactVariant) => (
              <option key={v.id} value={v.id}>
                {v.name}{v.confirmed ? '' : ' (unconfirmed)'}
              </option>
            ))}
          </select>
          <div className="queue-actions">
            <Button
              variant="outline"
              data-testid="fact-variant-load"
              disabled={loadVariant.isPending || !variantId}
              onClick={() => loadVariant.mutate()}
            >
              Load into form
            </Button>
            {selectedVariant && !selectedVariant.confirmed && (
              <Button
                variant="outline"
                data-testid="fact-variant-confirm"
                disabled={confirmVariant.isPending}
                onClick={() => confirmVariant.mutate(selectedVariant.id)}
              >
                Confirm variant
              </Button>
            )}
            {selectedVariant?.confirmed && (
              <span data-testid="fact-variant-confirmed" className="tag">Confirmed</span>
            )}
          </div>
        </>
      )}
      {selection && (
        <p className="hint" data-testid="fact-library-selection">
          Selected {selection.productName || 'product'} / {selection.variantName}. Untouched loads
          submit by library reference; edits submit inline.
        </p>
      )}
      <h3>Save current facts</h3>
      <p className="hint">Save the current form as a new unconfirmed variant under the selected product.</p>
      <div className="queue-actions">
        <input
          id="fact-variant-name"
          data-testid="fact-variant-name"
          value={newVariantName}
          onChange={e => setNewVariantName(e.target.value)}
          placeholder="New variant name"
          maxLength={120}
        />
        <Button
          variant="outline"
          data-testid="fact-variant-save"
          disabled={saveVariant.isPending || !productId || !newVariantName.trim()}
          onClick={() => saveVariant.mutate()}
        >
          Save current facts
        </Button>
      </div>
    </div>
  );
}
