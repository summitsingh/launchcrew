/**
 * Shared React Query policy for the review desk.
 *
 * Every run, queue, agent, format, and capability poll is gated on the auth
 * status query, so that query must survive a transient failure. The client
 * default is no retries; the auth status check opts back into a small bounded
 * retry budget so one blip during a deploy or network gap resumes polling
 * instead of freezing the desk on the last receipt until a manual reload.
 */
export const AUTH_STATUS_RETRY_COUNT = 3;

export function authStatusQueryOptions<TQueryFn>(queryFn: TQueryFn): {
  queryKey: ['auth'];
  queryFn: TQueryFn;
  retry: number;
} {
  return { queryKey: ['auth'], queryFn, retry: AUTH_STATUS_RETRY_COUNT };
}
