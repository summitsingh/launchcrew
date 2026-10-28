'use client';
import { useEffect, useRef, useState, type RefObject } from 'react';
import { Button } from '@/components/ui/button';
import { api } from '@/lib/api';
import type { QueryClient } from '@tanstack/react-query';
import type { components } from '@/lib/schema';

type Receipt = components['schemas']['Receipt'];
type PhotoPreview = components['schemas']['PhotoPreview'];
type CropBox = components['schemas']['PhotoCrop'];

export const MAX_PHOTO_BYTES = 1024 * 1024;
export const MAX_PHOTO_PIXELS = 8_000_000;

export type StoredPhoto = {
  state: string;
  label: string | null;
  reason: string;
  revision: number;
  actor: string;
  checkedAt: string;
};

export type PhotoTransportNote = {
  attempts: number;
  uploads: number;
  segmentations: number;
  lastHandling: string;
  note: string;
};

export function readStoredPhoto(receipt: Receipt): StoredPhoto | null {
  const raw = (receipt as unknown as { photo_status?: unknown }).photo_status;
  if (raw === null || raw === undefined) return null;
  if (typeof raw !== 'object') {
    return { state: 'unknown', label: null, reason: 'unrecognized photo state', revision: 0, actor: '', checkedAt: '' };
  }
  const status = raw as Record<string, unknown>;
  const state = typeof status.state === 'string' && status.state.length > 0 ? status.state : 'unknown';
  return {
    state,
    label: typeof status.label === 'string' ? status.label : null,
    reason: typeof status.reason === 'string' ? status.reason : (state === 'unknown' ? 'unrecognized photo state' : ''),
    revision: typeof status.revision === 'number' ? status.revision : 0,
    actor: typeof status.actor === 'string' ? status.actor : '',
    checkedAt: typeof status.checked_at === 'string' ? status.checked_at : '',
  };
}

export function readPhotoTransport(receipt: Receipt): PhotoTransportNote | null {
  const raw = (receipt as unknown as { photo_transport?: unknown }).photo_transport;
  if (raw === null || raw === undefined || typeof raw !== 'object') return null;
  const transport = raw as Record<string, unknown>;
  const num = (value: unknown) => (typeof value === 'number' && Number.isFinite(value) ? value : 0);
  return {
    attempts: num(transport.attempts),
    uploads: num(transport.uploads),
    segmentations: num(transport.segmentations),
    lastHandling: typeof transport.last_handling === 'string' ? transport.last_handling : 'unknown',
    note: typeof transport.note === 'string' ? transport.note : '',
  };
}

export function photoStatusCopy(stored: StoredPhoto | null, currentRevision: number): string {
  if (!stored || stored.state === 'no_photo') {
    return 'No photo attached. Text-only approval and export rules apply.';
  }
  const stale = stored.revision !== currentRevision;
  const revNote = stale
    ? ` Stored at revision ${stored.revision}; the pack is now at revision ${currentRevision}, so this summary is superseded.`
    : ` Stored at revision ${stored.revision}.`;
  if (stored.state === 'requested_unchecked') {
    return `Photo checked without segmentation: ${stored.reason || 'not_run'}.${revNote} Approval and export stay refused until a detected check plus fresh human approval.`;
  }
  if (stored.state === 'check_requested') {
    return `Photo check in flight: ${stored.reason || 'check_requested'}.${revNote}`;
  }
  if (stored.state === 'unknown') {
    return `Photo state is unknown and blocking: ${stored.reason || 'unrecognized photo state'}.${revNote} Approval and export stay refused. Remove the photo or check a better one.`;
  }
  if (stored.state === 'checked') {
    if (stored.label === 'detected') {
      if (stale) {
        return `Photo check passed an earlier revision and is superseded: one in-frame candidate had passed the size and edge gates, but the pack has since changed so this is not a pass on the current revision.${revNote} Fresh human approval is still required before export, after a fresh check.`;
      }
      return `Photo check passed on this revision: one in-frame candidate passed the size and edge gates. A crop suggestion below only subsets existing pixels; cut-off pixels cannot be recovered.${revNote} Fresh human approval is still required before export.`;
    }
    if (stored.label === 'not_detected') {
      return `Photo check found no candidate: ${stored.reason || 'no_match'}.${revNote} There is no override. Remove the photo or check a better one.`;
    }
    if (stored.label === 'possible_clipping') {
      return `Photo check reports possible clipping: ${stored.reason || 'edge_or_size_gate'}.${revNote} There is no override. Remove the photo or check a better one.`;
    }
    return `Photo check is ${stored.label || 'unknown'}: ${stored.reason || 'needs review'}.${revNote} There is no override. Remove the photo or check a better one.`;
  }
  return `Photo state ${stored.state}: ${stored.reason || 'unavailable'}.${revNote} Approval and export stay refused.`;
}

/** Caption and alt text for selected local pixels, derived from the
 * actual current server verdict plus whether THIS selection is the one
 * the server just checked. Unchecked local pixels are never implied
 * checked: the copy distinguishes a pack with no verdict from one whose
 * current revision already has a detected check, a stale check, or an
 * unconfirmed state. A checked selection is the local generation whose
 * check response already succeeded for the current revision, so its copy
 * never claims the pixels were not sent. Plain product copy, no
 * implementation noise. */
export function selectionPhotoCopy(
  stored: StoredPhoto | null,
  currentRevision: number,
  checkedCurrent = false,
): { caption: string; alt: string } {
  if (checkedCurrent && stored && stored.revision === currentRevision) {
    if (stored.state === 'checked' && stored.label === 'detected') {
      return {
        caption: 'Checked: these current pixels passed the size and edge gates on this revision. They are not approved and not exportable until a fresh human approval passes.',
        alt: 'Selected photo preview (checked on this revision, detected)',
      };
    }
    if (stored.state === 'requested_unchecked') {
      return {
        caption: `Checked: these current pixels were sent to the validation server once, but segmentation did not run (${stored.reason || 'not_run'}). They are not approved and not exportable; approval and export stay refused.`,
        alt: 'Selected photo preview (checked on this revision, segmentation did not run)',
      };
    }
    if (stored.state === 'check_requested') {
      return {
        caption: 'Checking: these current pixels were sent and a check is in flight on this revision. They are not approved and not exportable until it passes.',
        alt: 'Selected photo preview (check in flight for these pixels)',
      };
    }
    if (stored.state === 'unknown' || stored.state === 'checked' || stored.state === 'no_photo') {
      const detail = stored.state === 'checked'
        ? `${stored.label || 'unknown'}: ${stored.reason || 'needs review'}`
        : `${stored.state}: ${stored.reason || 'unavailable'}`;
      return {
        caption: `Checked: these current pixels were checked on this revision and the photo gate did not pass (${detail}). There is no override; they are not approved and not exportable.`,
        alt: 'Selected photo preview (checked on this revision, photo gate did not pass)',
      };
    }
    return {
      caption: `Checked: these current pixels were sent on this revision and the photo state is ${stored.state}: ${stored.reason || 'unavailable'}. They are not approved and not exportable.`,
      alt: 'Selected photo preview (checked on this revision, result unconfirmed)',
    };
  }
  const base = 'These local pixels were not sent, and they are not approved and not exportable until an explicit check passes.';
  if (!stored || stored.state === 'no_photo') {
    return {
      caption: `Unchecked: ${base}`,
      alt: 'Selected photo preview (local only, not yet checked)',
    };
  }
  if (stored.state === 'checked' && stored.label === 'detected' && stored.revision === currentRevision) {
    return {
      caption: `New selection, not yet checked: ${base} The current revision already has a detected check, and fresh human approval is still required before export.`,
      alt: 'Selected photo preview (new local pixels, not yet checked; current revision has a detected check)',
    };
  }
  if (stored.revision !== currentRevision) {
    return {
      caption: `New selection, not yet checked: ${base} The stored summary is from revision ${stored.revision} and is superseded on revision ${currentRevision}.`,
      alt: 'Selected photo preview (new local pixels, not yet checked; stored summary is superseded)',
    };
  }
  if (stored.state === 'check_requested') {
    return {
      caption: `New selection, not yet checked: ${base} A check is already in flight on this revision.`,
      alt: 'Selected photo preview (new local pixels, not yet checked; a check is in flight)',
    };
  }
  return {
    caption: `New selection, not yet checked: ${base} The stored photo state on this revision is ${stored.state}.`,
    alt: 'Selected photo preview (new local pixels, not yet checked)',
  };
}

/** Null when the pack may proceed; otherwise the honest photo reason. */
export function photoBlocksApproval(stored: StoredPhoto | null, currentRevision: number): string | null {
  if (!stored || stored.state === 'no_photo') return null;
  if (stored.state === 'checked' && stored.label === 'detected' && stored.revision === currentRevision) return null;
  if (stored.state === 'requested_unchecked' || stored.state === 'check_requested') {
    return stored.reason || stored.state;
  }
  return `${stored.label || 'unknown'}: ${stored.reason || 'photo check did not pass'}`;
}

export function validateSelection(
  file: { type: string; size: number },
  natural: { width: number; height: number } | null,
): string | null {
  if (file.type !== 'image/png' && file.type !== 'image/jpeg') {
    return 'Only static PNG or JPEG photos are accepted.';
  }
  if (file.size > MAX_PHOTO_BYTES) {
    return 'Photo is larger than 1 MiB of raw bytes.';
  }
  if (natural) {
    if (!Number.isFinite(natural.width) || !Number.isFinite(natural.height) || natural.width <= 0 || natural.height <= 0) {
      return 'Photo could not be validated: the decoded size is invalid, so nothing can be checked.';
    }
    if (natural.width * natural.height > MAX_PHOTO_PIXELS) {
      return 'Photo is larger than 8 megapixels.';
    }
  }
  return null;
}

/** The server frame is EXIF-oriented; the browser decodes oriented too, so an exact match is required before drawing. */
export function cropFitsFrame(naturalW: number, naturalH: number, preview: PhotoPreview): boolean {
  return preview.frame_w === naturalW && preview.frame_h === naturalH;
}

export function cropWithinFrame(preview: PhotoPreview): boolean {
  const crop: CropBox | null = preview.crop;
  if (!crop) return false;
  return (
    crop.x1 >= 0 && crop.y1 >= 0 &&
    crop.x2 >= crop.x1 && crop.y2 >= crop.y1 &&
    crop.x2 < preview.frame_w && crop.y2 < preview.frame_h
  );
}

/** True when a reply must be dropped: it belongs to an older run or an older request. */
export function isStaleReply(sentRun: string, currentRun: string, sentSeq: number, currentSeq: number): boolean {
  return sentRun !== currentRun || sentSeq !== currentSeq;
}

export type ExpectedPhotoAdmission = {
  sentRevision: number;
  expectedRevision: number;
};

/** True when a polled revision is exactly the in-flight check's own paid
 * admission: the server commits N+1 with check_requested before the check
 * HTTP transport finishes. Such a poll must NOT invalidate the pending
 * check. Anything else (text edit, remove, different operation, new run,
 * unmount) still invalidates. Revision alone is never enough: the stored
 * server photo state must be check_requested at exactly the expected
 * revision, so a later text edit that leaves a stale check_requested
 * summary behind still invalidates. No provider IDs, bytes, or digests
 * are consulted here, only the sanitized receipt summary. */
export function isOwnAdmissionPoll(
  expected: ExpectedPhotoAdmission | null,
  currentRevision: number,
  stored: StoredPhoto | null,
): boolean {
  if (!expected) return false;
  if (currentRevision !== expected.expectedRevision) return false;
  if (!stored || stored.state !== 'check_requested') return false;
  return stored.revision === expected.expectedRevision;
}

export function revokePreviewUrl(url: string | null): void {
  if (!url) return;
  URL.revokeObjectURL(url);
}

/** True when an acknowledged mutation receipt may replace the cached one.
 * An already in-flight older GET poll must never overwrite a newer
 * revision that a mutation already acknowledged. Equal revisions are
 * accepted: photo and text mutations always bump the revision, so an
 * equal revision is the same generation, never older. */
export function shouldApplyReceipt(cachedRevision: number | null, nextRevision: number): boolean {
  if (cachedRevision === null) return true;
  return nextRevision >= cachedRevision;
}

function receiptRevision(receipt: unknown): number | null {
  if (!receipt || typeof receipt !== 'object') return null;
  const revision = (receipt as { revision?: unknown }).revision;
  return typeof revision === 'number' ? revision : null;
}

/** Apply an acknowledged mutation receipt without letting a stale in-flight
 * GET poll overwrite it afterwards. Cancels the in-flight receipt poll,
 * then applies only when the acknowledged revision is not older than the
 * cached one. The caller still invalidates the queue separately; receipt
 * polling stays on its regular interval and is never disabled. */
export async function applyAcknowledgedReceipt(
  client: QueryClient,
  runId: string,
  next: components['schemas']['Receipt'],
): Promise<void> {
  await client.cancelQueries({ queryKey: ['run', runId] });
  const cached = client.getQueryData<unknown>(['run', runId]);
  if (cached !== undefined && !shouldApplyReceipt(receiptRevision(cached), receiptRevision(next) ?? 0)) return;
  client.setQueryData(['run', runId], next);
}

export type PhotoPanelProps = {
  runId: string;
  revision: number;
  failed: boolean;
  stored: StoredPhoto | null;
  transport: PhotoTransportNote | null;
  selectionName: string | null;
  selectionMeta: string | null;
  previewUrl: string | null;
  selectionChecked?: boolean;
  cropCanvasRef?: RefObject<HTMLCanvasElement | null>;
  hasPayload: boolean;
  pending: boolean;
  removePending: boolean;
  notice: string | null;
  error: string | null;
  preview: PhotoPreview | null;
  naturalW: number | null;
  naturalH: number | null;
  cropDrawn: boolean;
  cropHint: string | null;
  onFile?: (file: File) => void;
  onCheck?: () => void;
  onRemove?: () => void;
  onClearLocal?: () => void;
  onDownloadCrop?: () => void;
};

export function PhotoCheckPanel(props: PhotoPanelProps) {
  const blockReason = photoBlocksApproval(props.stored, props.revision);
  const attached = !!props.stored && props.stored.state !== 'no_photo';
  const showCropOffer = !!props.preview && props.preview.label === 'detected' && props.preview.crop !== null;
  return (
    <section className="panel" aria-label="Photo check">
      <p className="eyebrow">OPTIONAL PHOTO CHECK</p>
      <h2>Photo visibility check</h2>
      <p className="hint">
        Bound to run {props.runId}, revision {props.revision}. Selecting, previewing, cropping, or removing
        never calls the segmentation provider. Only the explicit Check sends the photo bytes, once, over JSON.
        Text-model usage above covers text models only; actual photo attempts are listed separately below.
      </p>
      {props.failed && <p className="hint">No photo check is offered on failed runs.</p>}
      {!props.failed && (
        <>
          <p role="status">{photoStatusCopy(props.stored, props.revision)}</p>
          {blockReason && <p role="alert">Approval and export are refused: {blockReason}.</p>}
          {!blockReason && attached && (
            <p role="status">Photo gate is satisfied on this revision. Fresh human approval is still required before export.</p>
          )}
          {props.transport && (
            <p className="hint">
              Photo attempts: {props.transport.attempts} attempt(s), {props.transport.uploads} upload(s),{' '}
              {props.transport.segmentations} segmentation(s). Handling: {props.transport.lastHandling}.{' '}
              {props.transport.note}
            </p>
          )}
          <div>
            <label htmlFor={`photo-file-${props.runId}`}>Select photo (PNG or JPEG, max 1 MiB, max 8 megapixels)</label>
            <input
              id={`photo-file-${props.runId}`}
              type="file"
              accept="image/png,image/jpeg"
              disabled={props.pending || props.removePending || props.failed}
              onChange={e => {
                const file = e.target.files?.[0];
                if (file && props.onFile) props.onFile(file);
                e.target.value = '';
              }}
            />
          </div>
          {props.selectionName && (() => {
            const selection = selectionPhotoCopy(props.stored, props.revision, props.selectionChecked === true);
            return (
              <div>
                <p role="status">
                  Selected {props.selectionName}{props.selectionMeta ? ` (${props.selectionMeta})` : ''}. {selection.caption}
                </p>
                {props.previewUrl && (
                  <img className="photo-preview-img" src={props.previewUrl} alt={selection.alt} />
                )}
              </div>
            );
          })()}
          {props.naturalW !== null && props.naturalH !== null && (
            <p className="hint">Loaded image: {props.naturalW} by {props.naturalH} pixels (browser-decoded, EXIF-oriented).</p>
          )}
          <div className="queue-actions">
            <Button onClick={props.onCheck} disabled={props.pending || props.removePending || !props.hasPayload || props.failed}>
              {props.pending ? 'Checking photo...' : 'Check photo'}
            </Button>
            {attached && (
              <Button variant="outline" onClick={props.onRemove} disabled={props.removePending || props.pending}>
                {props.removePending ? 'Removing...' : 'Remove photo'}
              </Button>
            )}
            {props.selectionName && !attached && (
              <Button variant="outline" onClick={props.onClearLocal} disabled={props.pending || props.removePending}>
                Clear selection
              </Button>
            )}
            {props.selectionName && attached && (
              <Button variant="outline" onClick={props.onClearLocal} disabled={props.pending || props.removePending}>
                Clear selection
              </Button>
            )}
          </div>
          {props.pending && <p role="status">Check in flight. Duplicate checks are disabled until it settles.</p>}
          {props.error && <p role="alert">{props.error}</p>}
          {props.notice && <p role="status">{props.notice}</p>}
          {showCropOffer && (
            <div>
              <p role="status">
                Crop suggestion uses only existing pixels. The original file is preserved.
              </p>
              <canvas
                ref={props.cropCanvasRef}
                data-testid="photo-crop-canvas"
                className="photo-crop-canvas"
                style={props.cropDrawn ? undefined : { display: 'none' }}
              />
              {!props.cropDrawn && props.cropHint && <p role="status">{props.cropHint}</p>}
              {!props.cropDrawn && !props.cropHint && <p role="status">Preparing the crop preview. Download unlocks after the preview draws.</p>}
              <div className="queue-actions">
                <Button variant="outline" onClick={props.onDownloadCrop} disabled={!props.cropDrawn}>
                  Download crop
                </Button>
              </div>
            </div>
          )}
        </>
      )}
    </section>
  );
}

type Selection = {
  file: File;
  url: string;
  dataUri: string | null;
  width: number | null;
  height: number | null;
};

export function PhotoCheck({ receipt, onReceipt }: { receipt: Receipt; onReceipt: (next: Receipt) => void }) {
  const runId = receipt.run_id;
  const revision = (receipt as unknown as { revision?: number }).revision ?? 0;
  const failed = receipt.status === 'failed';
  const stored = readStoredPhoto(receipt);
  const transport = readPhotoTransport(receipt);
  const [selection, setSelection] = useState<Selection | null>(null);
  // Local proof that THIS selection generation is the one whose check
  // response already succeeded for the current revision. Ephemeral only:
  // never persisted, never sent, never logged. Set only when the response
  // for the current selection confirms the current photo check; cleared
  // on any new file, external revision, new run, unmount, remove, error,
  // or ambiguous result, so a new file never inherits an older verdict.
  const [checkedProof, setCheckedProof] = useState<{ url: string; revision: number; runId: string } | null>(null);
  const checkedProofRef = useRef<{ url: string; revision: number; runId: string } | null>(null);
  const clearProof = () => {
    checkedProofRef.current = null;
    setCheckedProof(null);
  };
  const [pending, setPending] = useState(false);
  const [removePending, setRemovePending] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<PhotoPreview | null>(null);
  const [cropDrawn, setCropDrawn] = useState(false);
  const [cropHint, setCropHint] = useState<string | null>(null);
  const seq = useRef(0);
  const lastAckedRevision = useRef<number>(revision);
  const trackedRun = useRef<string>(runId);
  // The paid admission the current in-flight check expects: sent N, server
  // commits N+1 with check_requested before the check HTTP finishes. While
  // set, exactly that polled admission is acknowledged without dropping the
  // pending check's local pixels. Cleared when the check settles or when any
  // truly superseding revision, run change, or unmount invalidates it.
  const expectedAdmission = useRef<ExpectedPhotoAdmission | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const selectionRef = useRef<Selection | null>(null);
  selectionRef.current = selection;

  const clearLocalImage = () => {
    const current = selectionRef.current;
    if (current) revokePreviewUrl(current.url);
    selectionRef.current = null;
    setSelection(null);
    setPreview(null);
    setCropDrawn(false);
    setCropHint(null);
    clearProof();
  };

  // Run changes drop every transient pixel and notice. Revision bumps that
  // this component did not acknowledge (text edits, removals elsewhere, or a
  // superseded check) also drop the local bytes so nothing stale can resend.
  // Both branches advance the request generation so deferred FileReader,
  // image, check, remove, and crop callbacks from the older generation are
  // dropped instead of resurrecting old pixels or notices. The one exception
  // is the in-flight check's own paid admission: the Desk polls the receipt
  // every 3 seconds, and the server commits N+1 with check_requested before
  // the check HTTP finishes, so that exact polled admission is acknowledged
  // without clearing the pending check. Its final response then still
  // applies and draws.
  useEffect(() => {
    if (trackedRun.current !== runId) {
      trackedRun.current = runId;
      lastAckedRevision.current = revision;
      expectedAdmission.current = null;
      seq.current += 1;
      clearLocalImage();
      setNotice(null);
      setError(null);
      setPending(false);
      setRemovePending(false);
      return;
    }
    if (revision !== lastAckedRevision.current) {
      if (isOwnAdmissionPoll(expectedAdmission.current, revision, stored)) {
        lastAckedRevision.current = revision;
        return;
      }
      expectedAdmission.current = null;
      lastAckedRevision.current = revision;
      seq.current += 1;
      clearLocalImage();
      setNotice(null);
      setPending(false);
      setRemovePending(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, revision]);

  // Unmount invalidates the request generation so deferred callbacks that
  // resolve after navigation cannot apply an old receipt or notice.
  useEffect(() => {
    return () => {
      seq.current += 1;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Revoke the previous object URL when it is replaced or unmounted.
  useEffect(() => {
    const url = selection?.url ?? null;
    return () => revokePreviewUrl(url);
  }, [selection?.url]);

  const handleFile = (file: File) => {
    if (pending || removePending || failed) return;
    seq.current += 1;
    // A new selection starts a new generation: no earlier admission stays tracked,
    // and no earlier check verdict is inherited by the new file.
    expectedAdmission.current = null;
    clearProof();
    const mySeq = seq.current;
    const myRun = runId;
    setError(null);
    setNotice(null);
    setPreview(null);
    setCropDrawn(false);
    setCropHint(null);
    const early = validateSelection(file, null);
    if (early) {
      // A rejected file must not leave an older valid selection sendable as
      // if it were the new file: drop the stale payload and report the block.
      clearLocalImage();
      setError(early);
      return;
    }
    const previous = selectionRef.current;
    if (previous) revokePreviewUrl(previous.url);
    const url = URL.createObjectURL(file);
    const next: Selection = { file, url, dataUri: null, width: null, height: null };
    selectionRef.current = next;
    setSelection(next);
    const reader = new FileReader();
    reader.onload = () => {
      if (isStaleReply(myRun, trackedRun.current, mySeq, seq.current)) return;
      const text = typeof reader.result === 'string' ? reader.result : null;
      if (!text || !text.startsWith('data:image/')) {
        setError('Could not read that file as a PNG or JPEG image.');
        return;
      }
      const current = selectionRef.current;
      if (current && current.url === url) {
        const updated = { ...current, dataUri: text };
        selectionRef.current = updated;
        setSelection(updated);
      }
    };
    reader.onerror = () => {
      if (isStaleReply(myRun, trackedRun.current, mySeq, seq.current)) return;
      setError('Could not read that file as a PNG or JPEG image.');
    };
    reader.readAsDataURL(file);
    const probe = new Image();
    probe.onload = () => {
      if (isStaleReply(myRun, trackedRun.current, mySeq, seq.current)) return;
      const width = probe.naturalWidth;
      const height = probe.naturalHeight;
      const late = validateSelection(file, { width, height });
      if (late) {
        setError(late);
        const current = selectionRef.current;
        if (current && current.url === url) {
          const updated = { ...current, width, height, dataUri: null };
          selectionRef.current = updated;
          setSelection(updated);
        }
        return;
      }
      const current = selectionRef.current;
      if (current && current.url === url) {
        const updated = { ...current, width, height };
        selectionRef.current = updated;
        setSelection(updated);
      }
    };
    probe.onerror = () => {
      if (isStaleReply(myRun, trackedRun.current, mySeq, seq.current)) return;
      // An unloadable image must not stay sendable on a previously read payload.
      const current = selectionRef.current;
      if (current && current.url === url) {
        const updated = { ...current, width: 0, height: 0, dataUri: null };
        selectionRef.current = updated;
        setSelection(updated);
      }
      setError('Could not load that file as a PNG or JPEG image.');
    };
    probe.src = url;
  };

  const handleCheck = async () => {
    const current = selectionRef.current;
    // Only the current fully validated selection may be sent: payload bytes
    // plus decoded dims that pass the bounds. Anything else stays local.
    if (pending || removePending || failed || !current?.dataUri) return;
    if (
      current.width === null || current.height === null ||
      validateSelection(current.file, { width: current.width, height: current.height }) !== null
    ) {
      setError('Select a valid photo before checking: the current selection failed validation.');
      return;
    }
    seq.current += 1;
    const mySeq = seq.current;
    const myRun = runId;
    const sentRevision = revision;
    // The server commits sentRevision + 1 with check_requested before this
    // HTTP finishes; the 3-second receipt poll will observe that admission
    // while this check is still in flight. Track it so the poll is
    // recognized as our own operation instead of an external revision.
    expectedAdmission.current = { sentRevision, expectedRevision: sentRevision + 1 };
    setPending(true);
    setError(null);
    setNotice(null);
    try {
      const result = await api.POST('/api/runs/{run_id}/photo-check', {
        params: { path: { run_id: myRun } },
        body: { image_data_uri: current.dataUri, expected_revision: sentRevision },
      });
      if (isStaleReply(myRun, trackedRun.current, mySeq, seq.current)) return;
      if (!result.response.ok || result.data === undefined) {
        expectedAdmission.current = null;
        if (result.response.status === 409) {
          clearLocalImage();
          lastAckedRevision.current = revision;
          setError('The draft changed before the check landed (409). Reselect the photo against the latest revision.');
        } else {
          const detail = (result.error as unknown as { detail?: unknown })?.detail;
          const text = typeof detail === 'string' ? detail : `Request failed (${result.response.status}).`;
          clearLocalImage();
          setError(text);
        }
        return;
      }
      const body = result.data;
      expectedAdmission.current = null;
      const ackedRevision = body.receipt.revision ?? sentRevision + 1;
      lastAckedRevision.current = ackedRevision;
      // The response confirms THIS current selection: record the local
      // generation it checked. A newer file would have bumped the
      // generation above and returned early as stale, so only the
      // selection that was actually sent is ever marked checked.
      if (selectionRef.current?.url === current.url) {
        const proof = { url: current.url, revision: ackedRevision, runId: myRun };
        checkedProofRef.current = proof;
        setCheckedProof(proof);
      }
      setPreview(body.preview ?? null);
      setCropDrawn(false);
      setCropHint(null);
      const check = body.check;
      if (check.method === 'not_run') {
        setNotice('SAM not configured, photo unchecked. The pack stays unapproved and unexported; approval and export are refused (422) with the photo reason.');
      } else if (check.label === 'detected') {
        setNotice('Photo check detected one in-frame candidate. Fresh human approval is still required before export.');
      } else {
        setNotice(`Photo check returned ${check.label ?? 'unknown'}: ${check.reason}. There is no override.`);
      }
      onReceipt(body.receipt as Receipt);
    } catch {
      if (isStaleReply(myRun, trackedRun.current, mySeq, seq.current)) return;
      expectedAdmission.current = null;
      clearLocalImage();
      // Ambiguous transport failure: never claim nothing was sent and never
      // retry blindly. The receipt decides the next step.
      setError('Photo check result is unconfirmed. Reload the receipt before deciding; nothing was retried.');
    } finally {
      if (!isStaleReply(myRun, trackedRun.current, mySeq, seq.current)) setPending(false);
    }
  };

  const handleRemove = async () => {
    if (removePending || pending || failed) return;
    if (!stored || stored.state === 'no_photo') return;
    seq.current += 1;
    const mySeq = seq.current;
    const myRun = runId;
    const sentRevision = revision;
    // A remove is a different operation: any tracked admission from an
    // earlier check must not survive it.
    expectedAdmission.current = null;
    setRemovePending(true);
    setError(null);
    setNotice(null);
    try {
      const result = await api.DELETE('/api/runs/{run_id}/photo', {
        params: { path: { run_id: myRun } },
        body: { expected_revision: sentRevision },
      });
      if (isStaleReply(myRun, trackedRun.current, mySeq, seq.current)) return;
      if (!result.response.ok || result.data === undefined) {
        if (result.response.status === 409) {
          setError('The draft changed before removal landed (409). Reload and remove against the latest revision.');
        } else {
          const detail = (result.error as unknown as { detail?: unknown })?.detail;
          setError(typeof detail === 'string' ? detail : `Request failed (${result.response.status}).`);
        }
        return;
      }
      const removed = result.data;
      lastAckedRevision.current = removed.revision;
      clearLocalImage();
      // DELETE returns only the new revision, so refetch the receipt and
      // only present the cleared state once the refetch is consistent.
      const reread = await api.GET('/api/runs/{run_id}/receipt', { params: { path: { run_id: myRun } } });
      if (isStaleReply(myRun, trackedRun.current, mySeq, seq.current)) return;
      if (!reread.response.ok || reread.data === undefined) {
        setNotice(`Photo removed on the server at revision ${removed.revision}. Reload to confirm; fresh approval is required before export.`);
        return;
      }
      const fresh = reread.data as Receipt;
      lastAckedRevision.current = (fresh as unknown as { revision?: number }).revision ?? removed.revision;
      setNotice(`Photo removed at revision ${removed.revision}. The pack is back on the text-only path and needs fresh approval before export.`);
      onReceipt(fresh);
    } catch (e) {
      if (isStaleReply(myRun, trackedRun.current, mySeq, seq.current)) return;
      setError(e instanceof Error ? e.message : 'Photo removal failed. Nothing changed.');
    } finally {
      if (!isStaleReply(myRun, trackedRun.current, mySeq, seq.current)) setRemovePending(false);
    }
  };

  const handleClearLocal = () => {
    if (pending || removePending) return;
    const wasSubmitted = !!stored && stored.state !== 'no_photo';
    clearLocalImage();
    // An unsubmitted local selection was never attached, so this message must
    // never read as a server removal. An attached photo stays untouched here.
    setNotice(wasSubmitted ? null : 'Unsubmitted selection cleared locally. Nothing was sent and nothing was removed.');
    if (wasSubmitted) setNotice('Local preview cleared. The attached photo on the server is unchanged; use Remove photo to detach it.');
  };

  const handleDownloadCrop = () => {
    const canvas = canvasRef.current;
    if (!canvas || !cropDrawn) return;
    const mySeq = seq.current;
    const myRun = runId;
    canvas.toBlob(blob => {
      if (isStaleReply(myRun, trackedRun.current, mySeq, seq.current)) return;
      if (!blob) {
        setError('Crop download failed. The suggestion is unchanged.');
        return;
      }
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `${runId}-crop.png`;
      link.click();
      URL.revokeObjectURL(url);
    }, 'image/png');
  };

  // Draw the server crop onto the canvas only from existing pixels, and only
  // when the loaded image matches the approved oriented frame exactly.
  useEffect(() => {
    if (!preview || preview.label !== 'detected' || !preview.crop || !selection) {
      return;
    }
    if (selection.width === null || selection.height === null) return;
    if (!cropFitsFrame(selection.width, selection.height, preview)) {
      setCropDrawn(false);
      setCropHint(
        `Crop unavailable: the loaded image is ${selection.width} by ${selection.height} but the approved oriented frame is ` +
        `${preview.frame_w} by ${preview.frame_h}. No crop was drawn and no pixels were invented.`,
      );
      return;
    }
    if (!cropWithinFrame(preview)) {
      setCropDrawn(false);
      setCropHint('Crop unavailable: the suggested crop leaves the approved frame. No crop was drawn.');
      return;
    }
    const canvas = canvasRef.current;
    if (!canvas) return;
    const crop = preview.crop;
    const width = crop.x2 - crop.x1 + 1;
    const height = crop.y2 - crop.y1 + 1;
    const mySeq = seq.current;
    const myRun = runId;
    const myUrl = selection.url;
    const image = new Image();
    image.onload = () => {
      // A newer selection, check, removal, revision, or unmount invalidates
      // this draw: never resurrect pixels from an older generation.
      if (isStaleReply(myRun, trackedRun.current, mySeq, seq.current)) return;
      if (selectionRef.current?.url !== myUrl) return;
      const target = canvasRef.current;
      if (!target) return;
      if (image.naturalWidth !== selection.width || image.naturalHeight !== selection.height) {
        setCropDrawn(false);
        setCropHint('Crop unavailable: the loaded image no longer matches the approved oriented frame. No crop was drawn.');
        return;
      }
      target.width = width;
      target.height = height;
      const ctx = target.getContext('2d');
      if (!ctx) {
        setCropDrawn(false);
        setCropHint('Crop unavailable: the canvas is not supported here. The original file is unchanged.');
        return;
      }
      ctx.drawImage(image, crop.x1, crop.y1, width, height, 0, 0, width, height);
      setCropDrawn(true);
      setCropHint(null);
    };
    image.onerror = () => {
      if (isStaleReply(myRun, trackedRun.current, mySeq, seq.current)) return;
      if (selectionRef.current?.url !== myUrl) return;
      setCropDrawn(false);
      setCropHint('Crop unavailable: the selected image could not be reloaded. The original file is unchanged.');
    };
    image.src = myUrl;
  }, [preview, selection]);

  const selectionMeta =
    selection !== null
      ? `${selection.file.type === 'image/jpeg' ? 'JPEG' : 'PNG'}, ${(selection.file.size / 1024).toFixed(1)} KiB`
      : null;

  // The Check control only arms for the current fully validated selection:
  // payload bytes present plus decoded dims that pass the bounds. A pending
  // FileReader without dims, an errored load, or invalid dims stay unarmed.
  const selectionValidated =
    selection !== null &&
    selection.dataUri !== null &&
    selection.width !== null &&
    selection.height !== null &&
    validateSelection(selection.file, { width: selection.width, height: selection.height }) === null;

  // The current selection counts as checked only when the acknowledged
  // proof names exactly this local generation at this revision of this
  // run. A newer file, an external revision, a new run, a removal, or an
  // unmount clears the proof, so file B never inherits file A's verdict.
  const selectionChecked =
    checkedProof !== null &&
    selection !== null &&
    checkedProof.url === selection.url &&
    checkedProof.revision === revision &&
    checkedProof.runId === runId;

  return (
      <PhotoCheckPanel
        runId={runId}
        revision={revision}
        failed={failed}
        stored={stored}
        transport={transport}
        selectionName={selection?.file.name ?? null}
        selectionMeta={selectionMeta}
        previewUrl={selection?.url ?? null}
        selectionChecked={selectionChecked}
        cropCanvasRef={canvasRef}
        hasPayload={selectionValidated}
        pending={pending}
        removePending={removePending}
        notice={notice}
        error={error}
        preview={preview}
        naturalW={selection?.width ?? null}
        naturalH={selection?.height ?? null}
        cropDrawn={cropDrawn}
        cropHint={cropHint}
        onFile={handleFile}
        onCheck={handleCheck}
        onRemove={handleRemove}
        onClearLocal={handleClearLocal}
        onDownloadCrop={handleDownloadCrop}
      />
  );
}
