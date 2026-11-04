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

const PLAIN_STATUS_GUIDANCE: Record<number, string> = {
  400: 'That request was not valid. Check the highlighted fields and try again.',
  401: 'Authorization is unavailable. Reload and retry.',
  403: 'That action is not allowed from here. Reload and retry from the current revision.',
  404: 'That item was not found. Reload the list and pick the current item.',
  409: 'That changed while you worked. Reload the latest revision and retry.',
  422: 'That needs a fix before it can be saved. Read the reason below, correct the text, and retry.',
  429: 'Too many tries. Wait a moment and retry once.',
};

export function errorMessage(error: unknown, status: number): string {
  const guidance = PLAIN_STATUS_GUIDANCE[status] || 'Something went wrong. Reload and try again.';
  if (error && typeof error === 'object') {
    const detail = (error as { detail?: unknown }).detail;
    const text = detailText(detail);
    if (text) return `${guidance} Detail: ${text}`;
  }
  return guidance;
}

export async function unwrap<T>(request: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
  const result = await request;
  if (result.error || !result.response.ok || result.data === undefined) {
    throw new Error(errorMessage(result.error, result.response.status));
  }
  return result.data;
}
