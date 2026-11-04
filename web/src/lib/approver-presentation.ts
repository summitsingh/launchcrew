// Central neutral approver presentation for public Review and Classic surfaces.
// Internal receipt data keeps raw actor keys. Public UI renders only this label.
export const PUBLIC_APPROVER_LABEL = 'Public demo reviewer';

const PROVIDER_PREFIXES = ['google:', 'facebook:', 'demo:', 'auth:'];

export function isActorIdentifier(value: unknown): boolean {
  if (typeof value !== 'string') return false;
  const text = value.trim();
  if (!text) return false;
  const lowered = text.toLowerCase();
  if (lowered === 'demo_placeholder' || lowered === 'keyless' || lowered === 'pending') return true;
  if (PROVIDER_PREFIXES.some(prefix => text.startsWith(prefix))) return true;
  if (text.includes('@')) return true;
  if (/^\d{5,}$/.test(text)) return true;
  if (text.includes(':') && !text.includes(' ') && text.length >= 8) return true;
  return false;
}

// Schema approver slots always map non empty values to the neutral label.
export function presentationApprover(value: unknown): string {
  if (typeof value === 'string' && value.trim()) return PUBLIC_APPROVER_LABEL;
  return typeof value === 'string' ? value : '';
}

// Generic actor slots map only actor like values, preserving agent names.
export function presentationActor(value: unknown): string {
  if (typeof value === 'string' && isActorIdentifier(value)) return PUBLIC_APPROVER_LABEL;
  return typeof value === 'string' ? value : '';
}

const APPROVER_KEYS = new Set(['approved_by', 'revised_by', 'exported_by', 'last_exported_by']);
const ACTOR_KEYS = new Set(['actor', 'profile']);

function sanitizeNode(node: unknown): unknown {
  if (Array.isArray(node)) return node.map(sanitizeNode);
  if (node && typeof node === 'object') {
    const out: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(node as Record<string, unknown>)) {
      if (APPROVER_KEYS.has(key) && typeof value === 'string') {
        out[key] = value.trim() ? PUBLIC_APPROVER_LABEL : value;
      } else if (ACTOR_KEYS.has(key) && typeof value === 'string') {
        out[key] = isActorIdentifier(value) ? PUBLIC_APPROVER_LABEL : value;
      } else {
        out[key] = sanitizeNode(value);
      }
    }
    return out;
  }
  return node;
}

// Presentation copy for served JSON, downloads, and copy actions.
// Never mutates the input. Deterministic checks and bindings are preserved.
export function sanitizeReceiptForPresentation<T>(receipt: T): T {
  if (!receipt || typeof receipt !== 'object') return receipt;
  return sanitizeNode(structuredClone(receipt)) as T;
}
