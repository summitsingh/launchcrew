import createClient from 'openapi-fetch';
import type { paths } from './schema';
export const api = createClient<paths>();
export async function unwrap<T>(request: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
  const result = await request;
  if (result.error || !result.response.ok || result.data === undefined) throw new Error(`Request failed (${result.response.status}). Check the API and try again.`);
  return result.data;
}
