'use client';
import { useEffect, useRef, useState, type RefObject } from 'react';
import { Button } from '@/components/ui/button';
import { api } from '@/lib/api';
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
  if (typeof raw !== 'object') return null;
  const status = raw as Record<string, unknown>;
  const state = typeof status.state === 'string' ? status.state : 'no_photo';
  return {
    state,
    label: typeof status.label === 'string' ? status.label : null,
    reason: typeof status.reason === 'string' ? status.reason : '',
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
  if (stored.state === 'checked') {
    if (stored.label === 'detected') {
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
  if (natural && natural.width * natural.height > MAX_PHOTO_PIXELS) {
    return 'Photo is larger than 8 megapixels.';
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

export function revokePreviewUrl(url: string | null): void {
  if (!url) return;
  URL.revokeObjectURL(url);
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
              disabled={props.pending || props.failed}
              onChange={e => {
                const file = e.target.files?.[0];
                if (file && props.onFile) props.onFile(file);
                e.target.value = '';
              }}
            />
          </div>
          {props.selectionName && (
            <div>
              <p role="status">
                Selected {props.selectionName}{props.selectionMeta ? ` (${props.selectionMeta})` : ''}. Unchecked:
                not approved and not exportable until an explicit check passes.
              </p>
              {props.previewUrl && (
                <img src={props.previewUrl} alt="Selected photo preview (local only, not yet checked)" />
              )}
            </div>
          )}
          {props.naturalW !== null && props.naturalH !== null && (
            <p className="hint">Loaded image: {props.naturalW} by {props.naturalH} pixels (browser-decoded, EXIF-oriented).</p>
          )}
          <div className="queue-actions">
            <Button onClick={props.onCheck} disabled={props.pending || !props.hasPayload || props.failed}>
              {props.pending ? 'Checking photo...' : 'Check photo'}
            </Button>
            {attached && (
              <Button variant="outline" onClick={props.onRemove} disabled={props.removePending || props.pending}>
                {props.removePending ? 'Removing...' : 'Remove photo'}
              </Button>
            )}
            {props.selectionName && !attached && (
              <Button variant="outline" onClick={props.onClearLocal} disabled={props.pending}>
                Clear selection
              </Button>
            )}
            {props.selectionName && attached && (
              <Button variant="outline" onClick={props.onClearLocal} disabled={props.pending}>
                Clear selection
              </Button>
            )}
          </div>
          {props.pending && <p role="status">Check in flight. Duplicate checks are disabled until it settles.</p>}
          {props.error && <p role="alert">{props.error}</p>}
          {props.notice && <p role="status">{props.notice}</p>}
          {showCropOffer && props.cropDrawn && (
            <div>
              <p role="status">
                Crop suggestion subsets existing pixels only (server pad and clamp). The original file is preserved.
              </p>
              <canvas ref={props.cropCanvasRef} data-testid="photo-crop-canvas" />
              <div className="queue-actions">
                <Button variant="outline" onClick={props.onDownloadCrop}>
                  Download crop
                </Button>
              </div>
            </div>
          )}
          {showCropOffer && !props.cropDrawn && props.cropHint && <p role="status">{props.cropHint}</p>}
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
  };

  // Run changes drop every transient pixel and notice. Revision bumps that
  // this component did not acknowledge (text edits, removals elsewhere, or a
  // superseded check) also drop the local bytes so nothing stale can resend.
  useEffect(() => {
    if (trackedRun.current !== runId) {
      trackedRun.current = runId;
      lastAckedRevision.current = revision;
      clearLocalImage();
      setNotice(null);
      setError(null);
      setPending(false);
      setRemovePending(false);
      return;
    }
    if (revision !== lastAckedRevision.current) {
      lastAckedRevision.current = revision;
      clearLocalImage();
      setNotice(null);
      setPending(false);
      setRemovePending(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, revision]);

  // Revoke the previous object URL when it is replaced or unmounted.
  useEffect(() => {
    const url = selection?.url ?? null;
    return () => revokePreviewUrl(url);
  }, [selection?.url]);

  const handleFile = (file: File) => {
    if (pending || failed) return;
    seq.current += 1;
    const mySeq = seq.current;
    const myRun = runId;
    setError(null);
    setNotice(null);
    setPreview(null);
    setCropDrawn(false);
    setCropHint(null);
    const early = validateSelection(file, null);
    if (early) {
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
      setError('Could not load that file as a PNG or JPEG image.');
    };
    probe.src = url;
  };

  const handleCheck = async () => {
    const current = selectionRef.current;
    if (pending || failed || !current?.dataUri) return;
    seq.current += 1;
    const mySeq = seq.current;
    const myRun = runId;
    const sentRevision = revision;
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
      lastAckedRevision.current = body.receipt.revision ?? sentRevision + 1;
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
    } catch (e) {
      if (isStaleReply(myRun, trackedRun.current, mySeq, seq.current)) return;
      clearLocalImage();
      setError(e instanceof Error ? e.message : 'Photo check failed before reaching the server. Nothing was sent.');
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
    if (pending) return;
    const wasSubmitted = !!stored && stored.state !== 'no_photo';
    clearLocalImage();
    setNotice(wasSubmitted ? null : 'Unsubmitted selection cleared locally. Nothing was sent.');
    if (wasSubmitted) setNotice('Local preview cleared. The attached photo on the server is unchanged; use Remove photo to detach it.');
  };

  const handleDownloadCrop = () => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    canvas.toBlob(blob => {
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
    const image = new Image();
    image.onload = () => {
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
      setCropDrawn(false);
      setCropHint('Crop unavailable: the selected image could not be reloaded. The original file is unchanged.');
    };
    image.src = selection.url;
  }, [preview, selection]);

  const selectionMeta =
    selection !== null
      ? `${selection.file.type === 'image/jpeg' ? 'JPEG' : 'PNG'}, ${(selection.file.size / 1024).toFixed(1)} KiB`
      : null;

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
        cropCanvasRef={canvasRef}
        hasPayload={!!selection?.dataUri}
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
