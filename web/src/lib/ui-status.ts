import type { components } from '@/lib/schema';

export type StatusTone = 'neutral' | 'success' | 'warning' | 'danger';
export type StatusIcon = 'draft' | 'checking' | 'review' | 'approved' | 'scheduled' | 'published' | 'verified' | 'failed' | 'blocked' | 'info';
export type StatusDefinition = Readonly<{ label: string; tone: StatusTone; icon: StatusIcon; description: string }>;

// Presentation only. These labels never grant approval or publishing permission.
export const launchStatuses = {
  draft: { label: 'Draft', tone: 'neutral', icon: 'draft', description: 'Your draft has not been checked yet.' },
  checking: { label: 'Checking', tone: 'neutral', icon: 'checking', description: 'Your crew is drafting and checking the facts.' },
  needs_review: { label: 'Needs review', tone: 'warning', icon: 'review', description: 'Open the draft to review its checks.' },
  approved: { label: 'Approved', tone: 'neutral', icon: 'approved', description: 'You approved this exact version.' },
  scheduled: { label: 'Scheduled', tone: 'neutral', icon: 'scheduled', description: 'This launch has a scheduled time.' },
  published: { label: 'Published', tone: 'success', icon: 'published', description: 'Publishing succeeded. Check the receipt for the result.' },
  verified: { label: 'Verified', tone: 'success', icon: 'verified', description: 'The published content matches the approved version.' },
  failed: { label: 'Failed', tone: 'danger', icon: 'failed', description: 'This launch stopped. Open its receipt for the next step.' },
} as const satisfies Record<string, StatusDefinition>;

export const claimStatuses = {
  backed: { label: 'Backed by a fact', tone: 'success', icon: 'verified', description: 'This claim matches a confirmed fact.' },
  needs_fix: { label: 'Needs a fix', tone: 'warning', icon: 'review', description: 'Edit this claim or confirm a matching fact, then recheck.' },
  blocked: { label: 'Blocked', tone: 'danger', icon: 'blocked', description: 'The Checker blocked this claim. Review the matching fact and reason.' },
} as const satisfies Record<string, StatusDefinition>;

const note = (label: string, description: string, tone: StatusTone = 'neutral'): StatusDefinition => ({ label, description, tone, icon: tone === 'warning' ? 'review' : tone === 'danger' ? 'blocked' : 'info' });

export const codeStatuses: Readonly<Record<string, StatusDefinition>> = {
  ...launchStatuses,
  ...claimStatuses,
  drafted: launchStatuses.draft,
  pending: launchStatuses.checking,
  queued: launchStatuses.checking,
  started: launchStatuses.checking,
  running: launchStatuses.checking,
  in_progress: launchStatuses.checking,
  checking: launchStatuses.checking,
  completed: launchStatuses.needs_review,
  checked: launchStatuses.needs_review,
  pending_approval: launchStatuses.needs_review,
  needs_revision: claimStatuses.needs_fix,
  approved_for_export: launchStatuses.approved,
  exported: note('Exported', 'The approved version was exported. This does not confirm publishing.'),
  supported: claimStatuses.backed,
  confirmed: claimStatuses.backed,
  pass: claimStatuses.backed,
  passed: claimStatuses.backed,
  unsupported: claimStatuses.blocked,
  unconfirmed: claimStatuses.needs_fix,
  unverified: note('Not verified yet', 'A matching published version has not been verified yet.', 'warning'),
  mismatch: note('Mismatch', 'The published content differs from the approved version. Open its receipt for details.', 'danger'),
  ready: note('Ready', 'This slot passed the Ready gate and publishes automatically at its scheduled time.'),
  not_ready: note('Not ready', 'Resolve each failing Ready check before scheduling publishing.', 'warning'),
  pack_not_approved: note('Draft needs approval', 'Review and approve the exact draft before making this slot Ready.', 'warning'),
  format_check_failed: note('Format needs a fix', 'Fix the format issue named in the checks, then recheck.', 'warning'),
  unapproved_channel_variants: note('Channel versions need approval', 'Review and approve every selected channel version.', 'warning'),
  not_marked_ready: note('Slot needs Ready approval', 'Resolve the Ready checks, then mark the slot Ready.', 'warning'),
  invalid_or_revoked_workspace_key: note('Workspace key needs replacing', 'Ask the workspace owner for a valid key.', 'warning'),
  deterministic_fallback: note('Muse Spark was not used for this draft', 'Open the receipt to see why a deterministic draft was used.', 'warning'),
  deterministic: note('Deterministic', 'This step used fixed rules rather than a live model call.'),
  live: note('Live model call', 'A live model call is recorded in the receipt.'),
  live_verified: note('Live call verified', 'Recorded model evidence confirms a live call.'),
  enabled_unverified: note('Sign-in verification pending', 'Sign-in is enabled, but its live verification is not recorded.'),
  enabled_verified: note('Sign-in verified', 'Live sign-in verification is recorded.'),
  disabled_demo: note('Public demo', 'Visitors use the shared demo workspace without signing in.'),
  demo_template: note('Example facts', 'These fictional facts are examples. Confirm your own facts before generating.'),
  owner_input: note('Your confirmed facts', 'Only facts you explicitly confirmed can support claims.'),
  explicit_claim: note('Confirmed claim', 'You explicitly supplied this claim as a confirmed fact.'),
  connected: note('Connected', 'The API reports a connected account.'),
  disconnected: note('Not connected', 'Connect an account in Settings when connection management is available.'),
  simulated: note('Simulated', 'No platform was contacted.'),
  skipped: note('Skipped', 'This step did not run. Open the receipt for its recorded reason.'),
  cancelled: note('Cancelled', 'This operation was cancelled.'),
  approval_cleared: note('Approval cleared', 'The draft changed. Recheck it before approving again.', 'warning'),
};

export function statusForCode(code: string | null | undefined): StatusDefinition {
  // Unknown codes stay neutral rather than implying success or exposing jargon.
  return code && Object.hasOwn(codeStatuses, code)
    ? codeStatuses[code]
    : note('Status unavailable', 'Open the receipt for the recorded details.');
}

type LaunchEvidence = Pick<components['schemas']['Receipt'], 'status' | 'approval_state' | 'revision' | 'approved_revision'>;

// Schedule and publish evidence must come from their APIs, never inferred here.
export function launchStatus(receipt: LaunchEvidence): StatusDefinition {
  if (receipt.status === 'failed') return launchStatuses.failed;
  if (receipt.approval_state === 'approved_for_export' && receipt.approved_revision === receipt.revision) return launchStatuses.approved;
  if (receipt.status === 'completed') return launchStatuses.needs_review;
  if (['pending', 'queued', 'started', 'running', 'in_progress', 'checking'].includes(receipt.status)) return launchStatuses.checking;
  if (['draft', 'drafted'].includes(receipt.status)) return launchStatuses.draft;
  return statusForCode(null);
}

export function claimStatus({ verified, blocked }: { verified: boolean; blocked: boolean }): StatusDefinition {
  if (blocked) return claimStatuses.blocked;
  return verified ? claimStatuses.backed : claimStatuses.needs_fix;
}
