import type { components } from './schema';

type Day = components['schemas']['CampaignDay'];
export function memoryEditPayload(title: string, contentJson: string): Pick<components['schemas']['MemoryItemEdit'], 'title' | 'content'> {
  if (title.length < 1 || title.length > 200) throw new Error('Title must be between 1 and 200 characters.');
  let content: unknown;
  try { content = JSON.parse(contentJson); }
  catch { throw new Error('Content must be valid JSON.'); }
  if (content === null || Array.isArray(content) || typeof content !== 'object') throw new Error('Content must be a JSON object.');
  return { title, content: content as Record<string, unknown> };
}

export function canApproveDay(day: Day) {
  return day.status === 'completed' && day.approval_state === 'pending_approval' && day.checker_v2_blocked_count === 0;
}
export function canExportDay(day: Day) {
  return day.status === 'completed' && day.approval_state === 'approved_for_export';
}

/** Text-source truth for revision copy: Maker unless a saved human draft exists. Photo-only bumps never fabricate a human revision. */
export function textSourceOf(receipt: { human_draft?: { post?: unknown; email?: unknown } | null }): 'Maker' | 'human revision' {
  const human = receipt.human_draft;
  if (human && typeof human.post === 'string' && typeof human.email === 'string') return 'human revision';
  return 'Maker';
}

/** Short text-source label for approval queue cards: Maker unless a saved human draft exists. */
export function queueTextSource(receipt: { human_draft?: { post?: unknown; email?: unknown } | null }): 'Maker' | 'human' {
  return textSourceOf(receipt) === 'human revision' ? 'human' : 'Maker';
}

/** Additive photo suffix for revision copy; empty on the no-photo legacy path. */
export function photoRevisionSuffix(receipt: { photo_status?: { state?: unknown } | null }): string {
  const state = receipt.photo_status?.state;
  if (typeof state !== 'string' || state === 'no_photo') return '';
  return ` · photo ${state}`;
}
