/** One status vocabulary for the judges workspace (/meta-ai-hackathon-demo).
 *
 * Every raw enum and backend code renders through here so all five screens
 * share the same plain sentence-case labels. Unknown values fall back to a
 * humanized form of the raw token; nothing is invented.
 */

export const RUN_STATUSES = [
  'Draft',
  'Checking',
  'Needs review',
  'Approved',
  'Scheduled',
  'Published',
  'Verified',
] as const;

export type RunStatusLabel = (typeof RUN_STATUSES)[number];

export const CLAIM_STATUSES = ['Backed by a fact', 'Needs a fix', 'Blocked'] as const;

export type ClaimStatusLabel = (typeof CLAIM_STATUSES)[number];

function humanize(token: string): string {
  const words = String(token ?? '')
    .replace(/[_-]+/g, ' ')
    .replace(/([a-z])([A-Z])/g, '$1 $2')
    .trim()
    .toLowerCase();
  if (!words) return 'Unknown';
  return words.charAt(0).toUpperCase() + words.slice(1);
}

const APPROVAL_STATE_LABELS: Record<string, RunStatusLabel> = {
  pending_approval: 'Needs review',
  approved_for_export: 'Approved',
  draft: 'Draft',
};

const RUN_STATE_LABELS: Record<string, RunStatusLabel> = {
  running: 'Checking',
  completed: 'Needs review',
  failed: 'Needs review',
  approved: 'Approved',
};

/** Map a run receipt to the single workspace status. */
export function runStatusLabel(receipt: {
  status?: string | null;
  approval_state?: string | null;
  display?: string | null;
}): RunStatusLabel {
  const approval = (receipt.approval_state ?? '').toString();
  if (APPROVAL_STATE_LABELS[approval]) return APPROVAL_STATE_LABELS[approval];
  const display = (receipt.display ?? '').toString();
  if (RUN_STATE_LABELS[display]) return RUN_STATE_LABELS[display];
  const status = (receipt.status ?? '').toString();
  if (RUN_STATE_LABELS[status]) return RUN_STATE_LABELS[status];
  if (status === 'completed' && approval === 'approved_for_export') return 'Approved';
  return 'Draft';
}

const DELIVERY_STATE_LABELS: Record<string, RunStatusLabel> = {
  not_posted: 'Scheduled',
  posted: 'Published',
  verified: 'Verified',
  failed: 'Needs review',
};

/** Map a delivery or publish execution state to the workspace status. */
export function deliveryStatusLabel(state: string | null | undefined): RunStatusLabel {
  const label = DELIVERY_STATE_LABELS[String(state ?? '')];
  return label ?? 'Draft';
}

/** Map a claim check verdict to the workspace claim status. */
export function claimStatusLabel(entry: {
  verdict?: string | null;
  blocked?: boolean | null;
  verified?: boolean | null;
}): ClaimStatusLabel {
  if (entry.blocked) return 'Blocked';
  const verdict = (entry.verdict ?? '').toString().toLowerCase();
  if (verdict === 'supported' || entry.verified) return 'Backed by a fact';
  if (verdict === 'unsupported' || verdict === 'conflict') return 'Needs a fix';
  return 'Needs a fix';
}

/** Plain labels for backend reason codes shown in the workspace. */
const CODE_LABELS: Record<string, string> = {
  pack_not_approved: 'Pack not approved',
  format_check_failed: 'Format check failed',
  deterministic_fallback: 'Deterministic fallback',
  enabled_unverified: 'Enabled, demo only',
  demo_template: 'Demo template',
  explicit_claim: 'Explicit claim',
  not_posted: 'Not posted',
  posted: 'Posted',
  verified: 'Verified',
  failed: 'Failed',
  skipped_needs_approval: 'Needs approval',
  paused_by_kill_switch: 'Paused',
  already_posted: 'Already posted',
  invalid: 'Invalid',
  valid: 'Valid',
  revision_changed_since_approval: 'Changed since approval',
  approval_binding_mismatch: 'Approval mismatch',
  delivery_not_verified: 'Delivery not verified',
};

/** Map any raw backend enum or code to a plain label. */
export function codeLabel(code: string | null | undefined): string {
  const raw = String(code ?? '');
  if (CODE_LABELS[raw]) return CODE_LABELS[raw];
  return humanize(raw);
}
