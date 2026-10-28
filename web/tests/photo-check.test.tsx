import { describe, it, expect, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import {
  PhotoCheckPanel,
  cropFitsFrame,
  cropWithinFrame,
  isOwnAdmissionPoll,
  isStaleReply,
  photoBlocksApproval,
  photoStatusCopy,
  readStoredPhoto,
  revokePreviewUrl,
  validateSelection,
  type PhotoPanelProps,
  type StoredPhoto,
} from '../src/components/photo-check';
import { photoRevisionSuffix, queueTextSource, textSourceOf } from '../src/lib/v2';
import type { components } from '../src/lib/schema';

type Receipt = components['schemas']['Receipt'];

function panel(overrides: Partial<PhotoPanelProps> = {}): string {
  const props: PhotoPanelProps = {
    runId: 'run_demo',
    revision: 0,
    failed: false,
    stored: null,
    transport: null,
    selectionName: null,
    selectionMeta: null,
    previewUrl: null,
    hasPayload: false,
    pending: false,
    removePending: false,
    notice: null,
    error: null,
    preview: null,
    naturalW: null,
    naturalH: null,
    cropDrawn: false,
    cropHint: null,
    ...overrides,
  };
  return renderToStaticMarkup(<PhotoCheckPanel {...props} />);
}

const notRun: StoredPhoto = {
  state: 'requested_unchecked',
  label: null,
  reason: 'not_run: SAM not configured, photo unchecked',
  revision: 1,
  actor: 'demo_placeholder',
  checkedAt: '2026-01-01T00:00:00Z',
};

const detected: StoredPhoto = {
  state: 'checked',
  label: 'detected',
  reason: 'clear_single',
  revision: 1,
  actor: 'demo_placeholder',
  checkedAt: '2026-01-01T00:00:00Z',
};

describe('photo check review copy', () => {
  it('photo_keyless_blocks_approve_export', () => {
    const html = panel({ stored: notRun, revision: 1 });
    expect(html).toContain('SAM not configured, photo unchecked');
    expect(html).toContain('Approval and export are refused');
    expect(html).toContain('not_run: SAM not configured, photo unchecked');
    expect(html).not.toContain('photo-crop-canvas');
    expect(photoBlocksApproval(notRun, 1)).toContain('not_run');
    // A stale revision still blocks even for a detected summary.
    expect(photoBlocksApproval(detected, 2)).not.toBe(null);
    expect(photoBlocksApproval(detected, 1)).toBe(null);
    expect(photoBlocksApproval(null, 0)).toBe(null);
  });

  it('photo_remove_requires_reapprove', () => {
    const html = panel({ stored: detected, revision: 1 });
    expect(html).toContain('Remove photo');
    expect(html).toContain('Fresh human approval is still required before export');
    expect(html).toContain('Photo gate is satisfied on this revision');
  });

  it('photo_single_detected_offers_crop_only_existing_pixels', () => {
    const preview = { frame_w: 32, frame_h: 16, crop: { x1: 4, y1: 4, x2: 20, y2: 12 }, label: 'detected' as const };
    expect(cropFitsFrame(32, 16, preview)).toBe(true);
    expect(cropWithinFrame(preview)).toBe(true);
    const html = panel({ stored: detected, revision: 1, preview, naturalW: 32, naturalH: 16, cropDrawn: true });
    expect(html).toContain('photo-crop-canvas');
    expect(html).toContain('Download crop');
    expect(html).toContain('only subsets existing pixels');
    expect(html).toContain('cut-off pixels cannot be recovered');
  });

  it('shows no fake persisted preview after reload', () => {
    const html = panel({ stored: detected, revision: 1 });
    expect(html).not.toContain('<img');
    expect(html).toContain('Stored at revision 1');
  });

  it('selected unchecked photo is never implied approved or exported', () => {
    const html = panel({ selectionName: 'wallet.png', selectionMeta: 'PNG, 12.0 KiB', previewUrl: 'blob:local', hasPayload: true });
    expect(html).toContain('Unchecked');
    expect(html).toContain('not approved and not exportable until an explicit check passes');
    expect(html).toContain('Selected photo preview (local only, not yet checked)');
    expect(html).toContain('No photo attached');
  });

  it('disables duplicate checks while a check is pending', () => {
    const html = panel({ selectionName: 'wallet.png', hasPayload: true, pending: true });
    expect(html).toContain('Checking photo...');
    expect(html).toContain('disabled');
    expect(html).toContain('Duplicate checks are disabled until it settles');
  });

  it('reports unknown, not_detected, and clipping honestly with no override', () => {
    for (const label of ['not_detected', 'possible_clipping', 'unknown'] as const) {
      const stored: StoredPhoto = { ...detected, label, reason: label === 'unknown' ? 'needs_review' : 'gate' };
      const html = panel({ stored, revision: 1 });
      expect(html).toContain('There is no override');
      expect(photoBlocksApproval(stored, 1)).not.toBe(null);
    }
    expect(photoStatusCopy({ ...detected, label: 'possible_clipping', reason: 'edge_or_size_gate' }, 1)).toContain('possible clipping');
  });

  it('keeps text-model usage frozen and photo attempts separate', () => {
    const html = panel({
      stored: detected,
      revision: 1,
      transport: { attempts: 1, uploads: 1, segmentations: 1, lastHandling: 'segmented', note: 'Photo bytes were sent for this check.' },
    });
    expect(html).toContain('Text-model usage above covers text models only');
    expect(html).toContain('Photo attempts: 1 attempt(s), 1 upload(s), 1 segmentation(s)');
    expect(html).toContain('Handling: segmented');
  });
});

describe('photo check guards', () => {
  it('drops late async replies from an old run or an older request', () => {
    expect(isStaleReply('run_a', 'run_b', 1, 1)).toBe(true);
    expect(isStaleReply('run_a', 'run_a', 1, 2)).toBe(true);
    expect(isStaleReply('run_a', 'run_a', 2, 2)).toBe(false);
  });

  it('recognizes only the exact own admission, never a superseding revision', () => {
    const admitted: StoredPhoto = {
      state: 'check_requested',
      label: null,
      reason: 'check_requested: segmentation in flight',
      revision: 1,
      actor: 'demo_placeholder',
      checkedAt: '',
    };
    const expected = { sentRevision: 0, expectedRevision: 1 };
    // The polled N+1 with check_requested at exactly N+1 is our own operation.
    expect(isOwnAdmissionPoll(expected, 1, admitted)).toBe(true);
    // No tracked admission means every revision change invalidates.
    expect(isOwnAdmissionPoll(null, 1, admitted)).toBe(false);
    // A later text edit that leaves the stale check_requested summary behind
    // still invalidates: the polled revision moved past the admission.
    expect(isOwnAdmissionPoll(expected, 2, admitted)).toBe(false);
    expect(isOwnAdmissionPoll(expected, 2, { ...admitted, revision: 1 })).toBe(false);
    // A final verdict, a removal, or a missing summary is never the admission.
    expect(isOwnAdmissionPoll(expected, 1, { ...admitted, state: 'checked' })).toBe(false);
    expect(isOwnAdmissionPoll(expected, 1, { ...admitted, state: 'no_photo' })).toBe(false);
    expect(isOwnAdmissionPoll(expected, 1, null)).toBe(false);
    // Revision alone never suffices: a mismatched stored revision is stale.
    expect(isOwnAdmissionPoll(expected, 1, { ...admitted, revision: 0 })).toBe(false);
  });

  it('revokes object URLs on replace and unmount, and ignores empty input', () => {
    const revoke = vi.fn();
    (globalThis as unknown as { URL: { revokeObjectURL: () => void } }).URL = { revokeObjectURL: revoke };
    revokePreviewUrl('blob:old');
    expect(revoke).toHaveBeenCalledWith('blob:old');
    revoke.mockClear();
    revokePreviewUrl(null);
    expect(revoke).not.toHaveBeenCalled();
  });

  it('rejects non-image, oversize, and over-pixel selections before any send', () => {
    expect(validateSelection({ type: 'image/gif', size: 100 }, null)).toContain('Only static PNG or JPEG');
    expect(validateSelection({ type: 'image/png', size: 1024 * 1024 + 1 }, null)).toContain('1 MiB');
    expect(validateSelection({ type: 'image/jpeg', size: 100 }, { width: 4000, height: 3000 })).toContain('8 megapixels');
    expect(validateSelection({ type: 'image/png', size: 100 }, { width: 32, height: 16 })).toBe(null);
  });

  it('refuses to draw a crop when dims miss the approved oriented frame', () => {
    const preview = { frame_w: 32, frame_h: 16, crop: { x1: 4, y1: 4, x2: 20, y2: 12 }, label: 'detected' as const };
    // Browser-decoded dims with EXIF applied must equal the oriented frame exactly; swapped is a miss.
    expect(cropFitsFrame(16, 32, preview)).toBe(false);
    expect(cropFitsFrame(32, 16, preview)).toBe(true);
    expect(cropWithinFrame({ ...preview, crop: { x1: 0, y1: 0, x2: 32, y2: 12 } })).toBe(false);
    expect(cropWithinFrame({ ...preview, crop: null })).toBe(false);
    // The canvas mounts with the crop offer so the draw effect has a target,
    // but it stays hidden and the download stays disabled until a real draw.
    const html = panel({ stored: detected, revision: 1, preview, naturalW: 16, naturalH: 32, cropDrawn: false, cropHint: 'Crop unavailable: the loaded image is 16 by 32 but the approved oriented frame is 32 by 16. No crop was drawn and no pixels were invented.' });
    expect(html).toContain('photo-crop-canvas');
    expect(html).toContain('display:none');
    expect(html).toContain('disabled');
    expect(html).toContain('No crop was drawn and no pixels were invented');
  });

  it('mounts the crop canvas with the offer, hidden until a real draw completes', () => {
    const preview = { frame_w: 32, frame_h: 16, crop: { x1: 4, y1: 4, x2: 20, y2: 12 }, label: 'detected' as const };
    const hidden = panel({ stored: detected, revision: 1, preview, naturalW: 32, naturalH: 16, cropDrawn: false });
    expect(hidden).toContain('photo-crop-canvas');
    expect(hidden).toContain('display:none');
    expect(hidden).toContain('Preparing the crop preview. Download unlocks after the preview draws.');
    const drawn = panel({ stored: detected, revision: 1, preview, naturalW: 32, naturalH: 16, cropDrawn: true });
    expect(drawn).toContain('photo-crop-canvas');
    expect(drawn).not.toContain('display:none');
    expect(drawn).toContain('Download crop');
  });

  it('treats a present but malformed photo state as blocking unknown, never no_photo', () => {
    const malformed = readStoredPhoto({ photo_status: { bogus: true } } as unknown as Receipt);
    expect(malformed?.state).toBe('unknown');
    expect(photoBlocksApproval(malformed, 0)).not.toBe(null);
    const missingState = readStoredPhoto({ photo_status: {} } as unknown as Receipt);
    expect(missingState?.state).toBe('unknown');
    const nonObject = readStoredPhoto({ photo_status: 'checked' } as unknown as Receipt);
    expect(nonObject?.state).toBe('unknown');
    const html = panel({ stored: malformed, revision: 0 });
    expect(html).toContain('unknown');
    expect(html).toContain('Approval and export are refused');
  });

  it('marks a stale detected check superseded, never passed on the current revision', () => {
    const copy = photoStatusCopy({ ...detected, revision: 1 }, 2);
    expect(copy).toContain('superseded');
    expect(copy).not.toContain('passed on this revision');
    expect(photoBlocksApproval({ ...detected, revision: 1 }, 2)).not.toBe(null);
    expect(photoBlocksApproval({ ...detected, revision: 1 }, 1)).toBe(null);
  });

  it('rejects errored zero or invalid decoded dims before any send', () => {
    expect(validateSelection({ type: 'image/png', size: 100 }, { width: 0, height: 32 })).toContain('invalid');
    expect(validateSelection({ type: 'image/png', size: 100 }, { width: -4, height: 32 })).toContain('invalid');
    expect(validateSelection({ type: 'image/png', size: 100 }, { width: Number.NaN, height: 32 })).toContain('invalid');
    expect(validateSelection({ type: 'image/png', size: 100 }, { width: 32, height: 16 })).toBe(null);
  });
});

describe('photo revision copy', () => {
  it('labels queue cards Revision N (human) while detail copy keeps human revision', () => {
    expect(queueTextSource({ human_draft: null })).toBe('Maker');
    expect(queueTextSource({})).toBe('Maker');
    expect(queueTextSource({ human_draft: { post: 'H', email: 'E' } })).toBe('human');
    expect(textSourceOf({ human_draft: { post: 'H', email: 'E' } })).toBe('human revision');
  });

  it('keeps Maker and human text sources distinct and never fabricates human_draft', () => {
    expect(textSourceOf({ human_draft: null })).toBe('Maker');
    expect(textSourceOf({})).toBe('Maker');
    expect(textSourceOf({ human_draft: { post: 'H', email: 'E' } })).toBe('human revision');
    // A photo-only bump on a Maker base stays Maker-sourced.
    expect(textSourceOf({ human_draft: null })).toBe('Maker');
    expect(photoRevisionSuffix({ photo_status: null })).toBe('');
    expect(photoRevisionSuffix({ photo_status: { state: 'no_photo' } })).toBe('');
    expect(photoRevisionSuffix({ photo_status: { state: 'requested_unchecked' } })).toBe(' · photo requested_unchecked');
  });
});
