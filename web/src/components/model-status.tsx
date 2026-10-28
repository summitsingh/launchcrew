'use client';
import { useQuery } from '@tanstack/react-query';
import { api, unwrap } from '@/lib/api';
import type { components } from '@/lib/schema';

type Capabilities = components['schemas']['ModelCapabilities'];
type Usage = components['schemas']['ModelUsage'];

export function capabilityCopy(status: Capabilities | undefined, isPending: boolean, isError: boolean): string {
  if (isPending || status === undefined) return 'Model status unknown. Loading configuration.';
  if (isError) return 'Model status unknown. Configuration unavailable.';
  if (!status.spark_configured && !status.wonder_configured && !status.sam_configured) {
    return 'Local drafts. Model calls not configured.';
  }
  return 'Configured, not yet tested. Key presence does not prove API works, credits, or authorization. No live call made from this page.';
}

export function dataModeCopy(usage: Usage | null | undefined): string {
  const mode = (usage as unknown as { data_mode?: unknown } | null)?.data_mode;
  if (typeof mode !== 'string' || !mode) return 'unknown';
  return mode;
}

export function ModelStatusFooter() {
  const query = useQuery({ queryKey: ['model-capabilities'], queryFn: () => unwrap(api.GET('/api/model-capabilities')) });
  return <span className="tiny">{capabilityCopy(query.data, query.isPending, query.isError)}</span>;
}
