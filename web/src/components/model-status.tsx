'use client';
import { useQuery } from '@tanstack/react-query';
import { api, unwrap } from '@/lib/api';
import type { components } from '@/lib/schema';

type Capabilities = components['schemas']['ModelCapabilities'];
type Usage = components['schemas']['ModelUsage'];

export function capabilityCopy(status: Capabilities | undefined, isPending: boolean, isError: boolean): string {
  if (isError) return 'Model status unknown. Configuration unavailable.';
  if (isPending || status === undefined) return 'Model status unknown. Loading configuration.';
  if (!status.spark_configured && !status.wonder_configured && !status.sam_configured) {
    return 'Local drafts. Model calls not configured.';
  }
  return 'Configuration present. This readonly check does not verify availability or credits. Actual calls are in receipts. No live call made from this page.';
}

export const DATA_BASIS_V2 = 'v2';

type UsageLike = {
  data_mode?: unknown;
  data_basis?: unknown;
  request_provider?: unknown;
  data_mode_note?: unknown;
};

function rawMode(usage: Usage | null | undefined): string {
  const mode = (usage as unknown as UsageLike | null)?.data_mode;
  if (typeof mode !== 'string' || !mode) return 'unknown';
  return mode;
}

function isCurrentBasis(usage: Usage | null | undefined): boolean {
  return (usage as unknown as UsageLike | null)?.data_basis === DATA_BASIS_V2;
}

function providerOf(usage: Usage | null | undefined): string {
  const provider = (usage as unknown as UsageLike | null)?.request_provider;
  return typeof provider === 'string' ? provider : 'unknown';
}

export function dataModeCopy(usage: Usage | null | undefined): string {
  const mode = rawMode(usage);
  if (!usage || mode === 'unknown') return 'unknown';
  if (!isCurrentBasis(usage)) return 'unknown';
  if (mode === 'standard_no_train' && providerOf(usage) !== 'meta') return 'unknown';
  return mode;
}

export function dataModeLabel(usage: Usage | null | undefined): string {
  const mode = dataModeCopy(usage);
  if (mode === 'not_sent' && isCurrentBasis(usage)) return 'Nothing attempted';
  if (mode === 'standard_no_train') return 'Standard request variant';
  if (mode === 'contributor') return 'Contributor (may train)';
  if (mode === 'mixed') return 'Mixed variants';
  return 'Unknown';
}

export function dataModeNote(usage: Usage | null | undefined): string {
  if (!usage) return 'No stored usage on this receipt.';
  if (!isCurrentBasis(usage)) return 'Historical record without current basis. Unverified, so treat as unknown.';
  const note = (usage as unknown as UsageLike | null)?.data_mode_note;
  if (typeof note === 'string' && note.trim()) return note;
  return 'No note stored.';
}

export function ModelStatusFooter() {
  const query = useQuery({ queryKey: ['model-capabilities'], queryFn: () => unwrap(api.GET('/api/model-capabilities')) });
  return <span className="tiny">{capabilityCopy(query.data, query.isPending, query.isError)}</span>;
}
