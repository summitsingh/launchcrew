'use client';
import { useQuery } from '@tanstack/react-query';
import { api, unwrap } from '@/lib/api';

export const CONNECTIONS_LOCKED = 'Connection management is locked in public demo mode.';

export function useConnectionManagementLocked(): boolean {
  const health = useQuery({ queryKey: ['workspace-health'], queryFn: () => unwrap(api.GET('/api/health')) });
  // Keep token and connection controls closed until the deployment mode is known.
  return !health.isSuccess || health.data.auth === 'disabled_demo';
}
