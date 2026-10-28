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
  return day.approval_state === 'pending_approval' && day.status !== 'failed' && day.checker_v2_blocked_count === 0;
}
export function canExportDay(day: Day) {
  return day.approval_state === 'approved_for_export';
}
