import { describe, it, expect } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { FactLibrarySection, MissingFactsPrompt } from '../src/components/fact-library';
import { ConfirmedFactsBlock } from '../src/components/v2-views';
import {
  buildProductFactsInput,
  emptyOwnerFacts,
  missingCoreFacts,
  ownerFactsFromInput,
} from '../src/lib/product-facts';
import type { components } from '../src/lib/schema';

type Receipt = components['schemas']['Receipt'];

function confirmedState() {
  const state = emptyOwnerFacts();
  state.material = { value: 'Full-grain leather', confirmed: true, source: 'owner' };
  state.contents = { value: 'Six card slots', confirmed: true, source: 'owner' };
  state.size = { value: 'Bifold compact', confirmed: true, source: 'owner' };
  state.price = { value: '$129', confirmed: true, source: 'owner' };
  return state;
}

describe('missing core facts', () => {
  it('reports no missing facts when all four core fields are confirmed', () => {
    expect(missingCoreFacts(confirmedState())).toEqual([]);
  });

  it('names each unconfirmed core field in core order', () => {
    const state = emptyOwnerFacts();
    state.material = { value: 'Full-grain leather', confirmed: true, source: 'owner' };
    expect(missingCoreFacts(state)).toEqual(['contents', 'size', 'price']);
  });

  it('treats unconfirmed text as missing and empty form as fully missing', () => {
    const state = emptyOwnerFacts();
    state.price = { value: '$129', confirmed: false, source: 'owner' };
    expect(missingCoreFacts(state)).toEqual(['material', 'contents', 'size', 'price']);
  });

  it('treats confirmed-but-empty values as missing', () => {
    const state = confirmedState();
    state.size = { value: '   ', confirmed: true, source: 'owner' };
    expect(missingCoreFacts(state)).toEqual(['size']);
  });
});

describe('library variant conversion', () => {
  it('round-trips stored variant input without confirming anything new', () => {
    const stored = buildProductFactsInput(confirmedState());
    const loaded = ownerFactsFromInput(stored);
    expect(loaded.material).toEqual({ value: 'Full-grain leather', confirmed: true, source: 'owner' });
    expect(loaded.price).toEqual({ value: '$129', confirmed: true, source: 'owner' });
    expect(buildProductFactsInput(loaded)).toEqual(stored);
    expect(missingCoreFacts(loaded)).toEqual([]);
  });

  it('falls back to owner source for unknown provenance and keeps suggestions unconfirmed', () => {
    const loaded = ownerFactsFromInput({
      material: { value: 'Canvas', confirmed: false, source: 'blog' },
      allowed_claims: [{ value: 'Sturdy', confirmed: false, source: 'memory' }],
    } as unknown as Parameters<typeof ownerFactsFromInput>[0]);
    expect(loaded.material).toEqual({ value: 'Canvas', confirmed: false, source: 'owner' });
    expect(loaded.allowed_claims).toEqual([{ value: 'Sturdy', confirmed: false, source: 'memory' }]);
    expect(missingCoreFacts(loaded)).toEqual(['material', 'contents', 'size', 'price']);
  });
});

describe('missing-fact prompt', () => {
  it('prompts with the missing facts and an explicit waiver checkbox', () => {
    const html = renderToStaticMarkup(
      <MissingFactsPrompt missing={['contents', 'size', 'price']} waived={false} onWaive={() => {}} />,
    );
    expect(html).toContain('data-testid="missing-facts-prompt"');
    expect(html).toContain('contents, size, price');
    expect(html).toContain('data-testid="waive-missing-core"');
    expect(html).not.toContain('checked');
  });

  it('reflects a recorded waiver and renders nothing when complete', () => {
    const waived = renderToStaticMarkup(
      <MissingFactsPrompt missing={['price']} waived onWaive={() => {}} />,
    );
    expect(waived).toContain('checked');
    expect(renderToStaticMarkup(<MissingFactsPrompt missing={[]} waived={false} onWaive={() => {}} />)).toBe('');
  });
});

describe('facts library section', () => {
  function shell() {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return renderToStaticMarkup(
      <QueryClientProvider client={queryClient}>
        <FactLibrarySection
          state={emptyOwnerFacts()}
          selection={null}
          onSelectionChange={() => {}}
          onLoad={() => {}}
          notify={() => {}}
          fail={() => {}}
        />
      </QueryClientProvider>,
    );
  }

  it('offers product selection and save-current-facts controls', () => {
    const html = shell();
    expect(html).toContain('data-testid="fact-library"');
    expect(html).toContain('data-testid="fact-product-select"');
    expect(html).toContain('data-testid="fact-product-name"');
    expect(html).toContain('data-testid="fact-product-create"');
    expect(html).toContain('data-testid="fact-variant-name"');
    expect(html).toContain('data-testid="fact-variant-save"');
  });
});

describe('receipt waiver and library provenance', () => {
  function receiptWith(productFacts: Record<string, unknown>, extra: Record<string, unknown> = {}) {
    return {
      run_id: 'run_demo',
      status: 'completed',
      approval_state: 'pending_approval',
      approvals: [],
      revision: 0,
      summary: {},
      audit: {},
      product_facts: productFacts,
      ...extra,
    } as unknown as Receipt;
  }

  it('shows missing facts with a recorded owner waiver', () => {
    const html = renderToStaticMarkup(
      <ConfirmedFactsBlock
        receipt={receiptWith({
          mode: 'owner_input',
          template_used: false,
          fields: [],
          confirmed_claims: ['Full-grain leather'],
          allowlist: ['Full-grain leather'],
          suggested: [],
          founder_note: null,
          draft_variant: null,
          labels: {},
          missing_core_facts: ['contents', 'size', 'price'],
          missing_core_waived: true,
        })}
      />,
    );
    expect(html).toContain('data-testid="receipt-fact-waiver"');
    expect(html).toContain('contents, size, price');
    expect(html).toContain('Owner waiver recorded: yes');
  });

  it('shows the library snapshot behind a bound run', () => {
    const html = renderToStaticMarkup(
      <ConfirmedFactsBlock
        receipt={receiptWith(
          {
            mode: 'owner_input',
            template_used: false,
            fields: [],
            confirmed_claims: ['Full-grain leather'],
            allowlist: ['Full-grain leather'],
            suggested: [],
            founder_note: null,
            draft_variant: null,
            labels: {},
            missing_core_facts: [],
            missing_core_waived: false,
          },
          { fact_library: { product_name: 'Trail Wallet', variant_name: 'Standard' } },
        )}
      />,
    );
    expect(html).toContain('data-testid="receipt-fact-library"');
    expect(html).toContain('Trail Wallet / Standard');
  });
});
