'use client';
import { Card } from '@/components/ui/card';
import { Badge as WorkspaceBadge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { NativeSelect } from '@/components/ui/native-select';

import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { api, unwrap } from '@/lib/api';
import type { components } from '@/lib/schema';

export type MediaAsset = components['schemas']['MediaAssetOut'];
export type SlotMediaAttachment = components['schemas']['SlotMediaAttachmentOut'];

type DerivativeRecord = Record<string, string | number | boolean | Record<string, number> | null | undefined>;

export const MEDIA_ASPECTS = ['4:5', '1:1', '9:16', '16:9'] as const;
export const MEDIA_CHANNELS = ['x', 'linkedin', 'instagram', 'facebook', 'tiktok', 'threads', 'pinterest', 'shopify', 'email'] as const;

/** Derivative record for one channel, or null when it keeps the original. */
export function derivativeForChannel(
  attachment: Pick<SlotMediaAttachment, 'channels' | 'channel_derivatives' | 'use_original_without_derivative'>,
  channel: string,
): DerivativeRecord | null {
  if (attachment.use_original_without_derivative) return null;
  const mapping = (attachment.channel_derivatives ?? {}) as Record<string, DerivativeRecord>;
  const record = mapping[channel];
  return record && typeof record === 'object' ? record : null;
}

/** Plain Checker warning for a slot media validation result. */
export function mediaWarning(validation: { passed?: boolean; reasons?: string[] } | undefined | null): string | null {
  const reasons = validation?.reasons ?? [];
  if (validation?.passed !== false || reasons.length === 0) return null;
  return reasons[0];
}

export function MediaDerivativeList({ asset }: { asset: MediaAsset }) {
  const derivatives = (asset.derivatives ?? {}) as Record<string, DerivativeRecord>;
  const keys = Object.keys(derivatives);
  if (keys.length === 0) return <p className="hint">No derivatives yet.</p>;
  return <ul aria-label="Channel-ready derivatives">
    {keys.map(key => {
      const record = derivatives[key] ?? {};
      const aspect = String(record.aspect_ratio ?? key);
      const width = String(record.width ?? '');
      const height = String(record.height ?? '');
      return <li key={key} {...(key === '4:5' ? { 'data-testid': 'media-derivative-4x5' } : {})}>
        {key === '4:5' ? <strong>4:5 feed crop</strong> : <span>{key} crop</span>}
        {' '}<span className="hint">{aspect} · {width}x{height}</span>
      </li>;
    })}
  </ul>;
}

export function MediaAssetCard({ asset }: { asset: MediaAsset }) {
  const facts = (asset.format_facts ?? {}) as Record<string, string | number | boolean | null | undefined>;
  return <Card appearance="workspace" asChild ><article className="panel queue-card" data-asset-id={asset.id}>
    <p><strong>{asset.filename}</strong> <WorkspaceBadge appearance="workspace" asChild ><span className="badge">{asset.media_type}</span></WorkspaceBadge></p>
    <p className="hint">
      {String(asset.width)}x{String(asset.height)} · aspect {asset.aspect_ratio}
      {asset.duration_seconds != null ? ` · ${String(asset.duration_seconds)}s` : ''}
    </p>
    <p className="hint">Original digest preserved: {(asset.sha256_digest ?? '').slice(0, 12)}...</p>
    <p className="hint">Facts: {String(facts.width ?? asset.width)}x{String(facts.height ?? asset.height)} · {String(facts.aspect_ratio ?? asset.aspect_ratio)}</p>
    <MediaDerivativeList asset={asset} />
  </article></Card>;
}

export function readFileAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ''));
    reader.onerror = () => reject(new Error('Could not read the selected file.'));
    reader.readAsDataURL(file);
  });
}

export function MediaUploadForm() {
  const client = useQueryClient();
  const [filename, setFilename] = useState('');
  const [width, setWidth] = useState('1080');
  const [height, setHeight] = useState('1350');
  const [fileDataUrl, setFileDataUrl] = useState('');
  const [fileMime, setFileMime] = useState('');
  const [notice, setNotice] = useState('');
  const pickFile = async (file: File | undefined) => {
    setNotice('');
    if (!file) {
      setFileDataUrl('');
      setFileMime('');
      return;
    }
    try {
      setFileDataUrl(await readFileAsDataUrl(file));
    } catch (error) {
      setFileDataUrl('');
      setFileMime('');
      setNotice(error instanceof Error ? error.message : 'Could not read the selected file.');
      return;
    }
    setFileMime(file.type || '');
    if (!filename.trim()) setFilename(file.name);
  };
  const upload = useMutation({
    mutationFn: () => {
      const dataB64 = fileDataUrl.includes(',') ? fileDataUrl.split(',')[1] : '';
      return unwrap(api.POST('/api/media/assets', {
        body: {
          filename: filename.trim(), width: Number(width), height: Number(height),
          ...(fileMime ? { mime_type: fileMime } : {}),
          ...(dataB64 ? { data_b64: dataB64 } : {}),
        },
      }));
    },
    onSuccess: asset => {
      setNotice(`Uploaded ${asset.id} with ${Object.keys(asset.derivatives ?? {}).length} derivatives.`);
      setFilename('');
      setFileDataUrl('');
      setFileMime('');
      client.invalidateQueries({ queryKey: ['media-assets'] });
    },
    onError: (error: Error) => setNotice(error.message),
  });
  return <form className="queue-card" aria-label="Upload media asset" onSubmit={e => { e.preventDefault(); upload.mutate(); }}>
    <h3>Upload once</h3>
    <p className="hint">One upload is reused across channels; crops are stored alongside the original. Choose a real file to preserve its bytes; dimensions are read from the file.</p>
    <p>
      <label htmlFor="media-file">File</label>
      <Input appearance="workspace" id="media-file" type="file" accept="image/*,video/*" data-testid="media-file-input"
        onChange={e => void pickFile(e.target.files?.[0])} />
    </p>
    <p>
      <label htmlFor="media-filename">Filename</label>
      <Input appearance="workspace" id="media-filename" value={filename} onChange={e => setFilename(e.target.value)} placeholder="hero-4x5.png" />
    </p>
    <p>
      <label htmlFor="media-width">Width</label>
      <Input appearance="workspace" id="media-width" type="number" value={width} onChange={e => setWidth(e.target.value)} />
    </p>
    <p>
      <label htmlFor="media-height">Height</label>
      <Input appearance="workspace" id="media-height" type="number" value={height} onChange={e => setHeight(e.target.value)} />
    </p>
    <div className="queue-actions">
      <Button type="submit" data-testid="media-upload-btn" disabled={upload.isPending || !filename.trim()}>
        {upload.isPending ? 'Uploading...' : 'Upload media asset'}
      </Button>
    </div>
    {notice && <p role="status">{notice}</p>}
  </form>;
}

export function SlotMediaAttachForm({ slotId, assets }: { slotId: string; assets: MediaAsset[] }) {
  const client = useQueryClient();
  const [assetId, setAssetId] = useState(assets[0]?.id ?? '');
  const [channels, setChannels] = useState<string[]>(['instagram', 'x']);
  const [useOriginal, setUseOriginal] = useState(false);
  const [notice, setNotice] = useState('');
  const current = assetId || assets[0]?.id || '';
  const attach = useMutation({
    mutationFn: () => unwrap(api.POST('/api/calendar/slots/{slot_id}/media', {
      params: { path: { slot_id: slotId } },
      body: { asset_id: current, channels, use_original_without_derivative: useOriginal },
    })),
    onSuccess: result => {
      const validation = (result.format_validation ?? {}) as { passed?: boolean; reasons?: string[] };
      setNotice(validation.passed === false
        ? `Checker blocked: ${(validation.reasons ?? []).join('; ')}`
        : `Attached; every channel received its derivative.`);
      client.invalidateQueries({ queryKey: ['slot-media', slotId] });
      client.invalidateQueries({ queryKey: ['slot-gate', slotId] });
    },
    onError: (error: Error) => setNotice(error.message),
  });
  const toggle = (channel: string) => setChannels(prev =>
    prev.includes(channel) ? prev.filter(entry => entry !== channel) : [...prev, channel]);
  return <form className="queue-card" aria-label="Attach slot media" onSubmit={e => { e.preventDefault(); attach.mutate(); }}>
    <h3>Attach to slot and channels</h3>
    <p>
      <label htmlFor={`slot-media-asset-${slotId}`}>Asset</label>
      <NativeSelect appearance="workspace" id={`slot-media-asset-${slotId}`} value={current} onChange={e => setAssetId(e.target.value)}>
        {assets.map(asset => <option key={asset.id} value={asset.id}>{asset.filename} ({asset.aspect_ratio})</option>)}
      </NativeSelect>
    </p>
    <fieldset>
      <legend>Channels</legend>
      {MEDIA_CHANNELS.map(channel => <p key={channel}>
        <label>
          <Input appearance="workspace" type="checkbox" checked={channels.includes(channel)} onChange={() => toggle(channel)} />
          {channel}
        </label>
      </p>)}
    </fieldset>
    <p>
      <label>
        <Input appearance="workspace" type="checkbox" checked={useOriginal} onChange={e => setUseOriginal(e.target.checked)} />
        Attach the wrong-aspect original without a derivative
      </label>
    </p>
    <div className="queue-actions">
      <Button type="submit" disabled={attach.isPending || !current || channels.length === 0}>
        {attach.isPending ? 'Attaching...' : 'Attach media'}
      </Button>
    </div>
    {notice && <p role="status">{notice}</p>}
  </form>;
}

export function SlotMediaSection({ slotId, assets }: { slotId: string; assets: MediaAsset[] }) {
  const media = useQuery({
    queryKey: ['slot-media', slotId],
    queryFn: () => unwrap(api.GET('/api/calendar/slots/{slot_id}/media', { params: { path: { slot_id: slotId } } })),
  });
  const attached = ((media.data as { attached?: SlotMediaAttachment[] } | undefined)?.attached ?? []);
  const validation = (media.data as { format_validation?: { passed?: boolean; reasons?: string[] } | undefined })?.format_validation;
  const warning = mediaWarning(validation);
  return <div className="queue-card" data-slot-media={slotId}>
    <h3>Slot media</h3>
    {media.isPending && <p className="hint">Loading slot media...</p>}
    {media.error && <p role="alert">{media.error.message}</p>}
    {attached.map(entry => <div key={entry.id} data-testid="slot-media-attachment" data-attachment-id={entry.id}>
      <p><strong>{entry.asset_id}</strong> <span className="hint">{(entry.channels ?? []).join(', ')}</span></p>
      <ul aria-label="Per-channel derivatives">
        {(entry.channels ?? []).map(channel => {
          const record = derivativeForChannel(entry, channel);
          return <li key={channel}>
            {channel}: {record ? `${String(record.aspect_ratio)} derivative (${String(record.width)}x${String(record.height)})` : 'original, no derivative'}
          </li>;
        })}
      </ul>
      {warning == null && (entry.format_validation?.passed !== false) && <p className="hint">Checker media check passed.</p>}
    </div>)}
    {warning && <p role="alert" data-testid="slot-media-warning">{warning}</p>}
    <SlotMediaAttachForm slotId={slotId} assets={assets} />
  </div>;
}

export function MediaLibraryPanel() {
  const assets = useQuery({ queryKey: ['media-assets'], queryFn: () => unwrap(api.GET('/api/media/assets')) });
  const list = ((assets.data ?? []) as MediaAsset[]);
  return <Card appearance="workspace" asChild ><section className="panel" data-testid="media-library-panel" aria-label="Media library">
    <h2>Media library</h2>
    <p className="hint">Upload once, reuse across channels. Derivatives sit alongside the original; the original is never overwritten.</p>
    <MediaUploadForm />
    {assets.isPending && <p>Loading media assets...</p>}
    {assets.error && <p role="alert">{assets.error.message}</p>}
    {list.map(asset => <MediaAssetCard key={asset.id} asset={asset} />)}
    {list.length === 0 && !assets.isPending && <p className="hint">No media assets yet. Upload the first one above.</p>}
  </section></Card>;
}
