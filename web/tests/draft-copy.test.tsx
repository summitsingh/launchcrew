import { describe, expect, it, vi } from 'vitest';
import {
  canCopyDraft,
  copyAuthorizedDraft,
  draftCopyLabel,
  type DraftCopyRecord,
} from '../src/lib/draft-copy';

function record(overrides: Partial<DraftCopyRecord> = {}): DraftCopyRecord {
  return {
    approved_by: 'demo_placeholder',
    kind: 'post',
    text: 'Server authorized post text.',
    revision: 0,
    receipt_id: 'run_demo',
    binding_version: 'approval-binding/v1',
    binding_digest: 'a'.repeat(64),
    copy_authorized: true,
    note: 'Copy authorized for offline use only.',
    ...overrides,
  };
}

describe('server-authorized draft copy', () => {
  it('copies only the server-authorized exact text on an approved pack', async () => {
    const writeText = vi.fn(async () => true);
    // The client display text differs; only the server record may be copied.
    const outcome = await copyAuthorizedDraft(
      async () => record({ text: 'Server authorized post text.' }),
      'post',
      0,
      writeText,
    );
    expect(writeText).toHaveBeenCalledTimes(1);
    expect(writeText).toHaveBeenCalledWith('Server authorized post text.');
    expect(outcome).toEqual({ copied: 'Current Instagram draft copied (revision 0).' });
  });

  it('copies the email kind with its own label', async () => {
    const writeText = vi.fn(async () => true);
    const outcome = await copyAuthorizedDraft(
      async () => record({ kind: 'email', text: 'Server authorized email text.', revision: 1 }),
      'email',
      1,
      writeText,
    );
    expect(writeText).toHaveBeenCalledWith('Server authorized email text.');
    expect(outcome).toEqual({ copied: 'Current email draft copied (revision 1).' });
  });

  it('refuses a pending pack without touching the clipboard', async () => {
    const writeText = vi.fn(async () => true);
    const outcome = await copyAuthorizedDraft(
      async () => {
        throw new Error('Request failed (422): Copy requires human approval of the latest revision for export');
      },
      'post',
      0,
      writeText,
    );
    expect(writeText).not.toHaveBeenCalled();
    expect(outcome).toHaveProperty('refused');
    expect((outcome as { refused: string }).refused).toContain('Copy refused');
  });

  it('refuses a stale revision without touching the clipboard', async () => {
    const writeText = vi.fn(async () => true);
    const outcome = await copyAuthorizedDraft(
      async () => {
        throw new Error('Request failed (409): Copy is stale; the draft changed');
      },
      'post',
      0,
      writeText,
    );
    expect(writeText).not.toHaveBeenCalled();
    expect((outcome as { refused: string }).refused).toContain('Copy refused');
  });

  it('refuses an unauthorized or mismatched record without copying', async () => {
    const writeText = vi.fn(async () => true);
    for (const bad of [
      record({ copy_authorized: false }),
      record({ text: '' }),
      record({ kind: 'email' }),
      record({ revision: 1 }),
    ]) {
      writeText.mockClear();
      const outcome = await copyAuthorizedDraft(async () => bad, 'post', 0, writeText);
      expect(writeText, JSON.stringify(bad)).not.toHaveBeenCalled();
      expect((outcome as { refused: string }).refused).toContain('Copy refused');
    }
  });

  it('reports a clipboard failure without claiming a copy', async () => {
    const writeText = vi.fn(async () => false);
    const outcome = await copyAuthorizedDraft(async () => record(), 'post', 0, writeText);
    expect(writeText).toHaveBeenCalledTimes(1);
    expect((outcome as { refused: string }).refused).toContain('Copy failed');
  });

  it('gates the copy buttons on a current export approval', () => {
    expect(canCopyDraft({ status: 'completed', approval_state: 'pending_approval' })).toBe(false);
    expect(canCopyDraft({ status: 'completed', approval_state: 'approved_for_export' })).toBe(true);
    expect(canCopyDraft({ status: 'failed', approval_state: 'approved_for_export' })).toBe(false);
    expect(canCopyDraft({ status: 'running', approval_state: 'pending_approval' })).toBe(false);
  });

  it('refuses missing or invalid receipts without throwing', () => {
    expect(canCopyDraft(null)).toBe(false);
    expect(canCopyDraft(undefined)).toBe(false);
    expect(canCopyDraft({} as { status?: unknown; approval_state?: unknown })).toBe(false);
  });

  it('labels each draft kind for the approval notice', () => {
    expect(draftCopyLabel('post')).toBe('Current Instagram draft');
    expect(draftCopyLabel('email')).toBe('Current email draft');
  });
});
