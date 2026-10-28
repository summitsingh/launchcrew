import { describe, it, expect, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import {
  PhotoCheckPanel,
  cropFitsFrame,
  cropWithinFrame,
  isStaleReply,
  photoBlocksApproval,
  photoStatusCopy,
  revokePreviewUrl,
  validateSelection,
  type PhotoPanelProps,
  type StoredPhoto,
} from '../src/components/photo-check';
import { photoRevisionSuffix, textSourceOf } from '../src/lib/v2';

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
    const html = panel({ stored: detected, revision: 1, preview, naturalW: 16, naturalH: 32, cropDrawn: false, cropHint: 'Crop unavailable: the loaded image is 16 by 32 but the approved oriented frame is 32 by 16. No crop was drawn and no pixels were invented.' });
    expect(html).not.toContain('photo-crop-canvas');
    expect(html).toContain('No crop was drawn and no pixels were invented');
  });
});

describe('photo revision copy', () => {
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
