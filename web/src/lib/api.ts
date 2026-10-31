import createClient from 'openapi-fetch';
import type { paths } from './schema';
export const api = createClient<paths>();

function detailText(detail: unknown): string {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    const parts = detail.map((item) => {
      if (item && typeof item === 'object') {
        const loc = Array.isArray((item as { loc?: unknown }).loc)
          ? (item as { loc: unknown[] }).loc.map(String).join('.')
          : '';
        const msg = String((item as { msg?: unknown }).msg ?? '');
        return loc ? `${loc}: ${msg}` : msg;
      }
      return String(item);
    }).filter(Boolean);
    if (parts.length) return parts.join('; ');
  }
  if (detail && typeof detail === 'object') {
    const message = (detail as { message?: unknown }).message;
    if (typeof message === 'string' && message) return message;
  }
  return '';
}

export function errorMessage(error: unknown, status: number): string {
  if (error && typeof error === 'object') {
    const detail = (error as { detail?: unknown }).detail;
    const text = detailText(detail);
    if (text) return `Request failed (${status}): ${text}`;
  }
  return `Request failed (${status}). Check the API and try again.`;
}

export async function unwrap<T>(request: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
  const result = await request;
  if (result.error || !result.response.ok || result.data === undefined) {
    throw new Error(errorMessage(result.error, result.response.status));
  }
  return result.data;
}
