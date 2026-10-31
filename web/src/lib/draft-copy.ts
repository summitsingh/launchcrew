import { api, unwrap } from './api';
import type { components } from './schema';

export type DraftKind = 'post' | 'email';
export type DraftCopyRecord = components['schemas']['DraftCopyOut'];

export function draftCopyLabel(kind: DraftKind): string {
  return kind === 'post' ? 'Current Instagram draft' : 'Current email draft';
}

/** Copy is offered only for a completed pack with a current export
 *  approval. The server still rechecks the exact text, revision, and
 *  binding at click time; this gate only keeps the buttons honest. */
export function canCopyDraft(receipt: { status?: unknown; approval_state?: unknown } | null | undefined): boolean {
  if (!receipt || typeof receipt !== 'object') return false;
  return receipt.status === 'completed' && receipt.approval_state === 'approved_for_export';
}

export function requestDraftCopy(runId: string, kind: DraftKind, revision: number): Promise<DraftCopyRecord> {
  return unwrap(api.POST('/api/runs/{run_id}/copy', {
    params: { path: { run_id: runId } },
    body: { kind, expected_revision: revision },
  }));
}

export type DraftCopyOutcome = { copied: string } | { refused: string };

/** Copy only the server-authorized exact text. Any refusal, mismatch,
 *  or clipboard failure copies nothing and reports why. */
export async function copyAuthorizedDraft(
  request: () => Promise<DraftCopyRecord>,
  kind: DraftKind,
  revision: number,
  writeText: (text: string) => Promise<boolean>,
): Promise<DraftCopyOutcome> {
  let record: DraftCopyRecord;
  try {
    record = await request();
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return { refused: `Copy refused: ${message} Only human-approved exact text at the current revision can be copied.` };
  }
  const label = draftCopyLabel(kind).toLowerCase();
  if (!record.copy_authorized || !record.text || record.kind !== kind || record.revision !== revision) {
    return { refused: `Copy refused for ${label} (revision ${revision}). The exact text needs a current human approval.` };
  }
  const ok = await writeText(record.text);
  if (!ok) return { refused: `Copy failed for ${label}. Select the draft text manually.` };
  return { copied: `${draftCopyLabel(kind)} copied (revision ${record.revision}).` };
}
