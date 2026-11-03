import { describe, expect, it } from 'vitest';
import { AUTH_STATUS_RETRY_COUNT, authStatusQueryOptions } from '../src/lib/auth-retry-policy';

describe('desk auth status query policy', () => {
  it('keeps a bounded retry budget so one transient failure cannot freeze polling', () => {
    expect(AUTH_STATUS_RETRY_COUNT).toBeGreaterThan(0);
    const queryFn = () => Promise.resolve('ok');
    expect(authStatusQueryOptions(queryFn)).toEqual({ queryKey: ['auth'], queryFn, retry: AUTH_STATUS_RETRY_COUNT });
  });
});
