'use client';
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { api, unwrap } from '@/lib/api';
import type { components } from '@/lib/schema';

export type ViralCredits = components['schemas']['ViralCreditsOut'];
export type ViralGeneration = components['schemas']['ViralGenerationOut'];
export type ViralMediaMode = 'screenshots' | 'screen_recording';

type MediaAsset = components['schemas']['MediaAssetOut'];

export const VIRAL_MODES: ViralMediaMode[] = ['screenshots', 'screen_recording'];

/** Human label for one viral media mode and its pack output. */
export function describeViralMode(mode: string): string {
  if (mode === 'screen_recording') return '1 Screen Recording to Short Video';
  return '3 to 10 Screenshots to Carousel';
}

/** Warning text when the visible credit count is exhausted, else null. */
export function viralCreditWarning(credits: ViralCredits | undefined | null): string | null {
  const remaining = credits?.remaining_credits;
  if (typeof remaining !== 'number') return null;
  if (remaining <= 0) return '0 credits remaining. Generation is refused before any provider call.';
  return null;
}

/** Frames or scenes of one generation as plain records, else empty. */
export function generationFrames(generation: ViralGeneration): Record<string, unknown>[] {
  const frames = (generation as { frames_or_scenes?: unknown }).frames_or_scenes;
  if (!Array.isArray(frames)) return [];
  return frames.filter((entry): entry is Record<string, unknown> =>
    !!entry && typeof entry === 'object');
}

/** Checker line for one generation: pass or fail with the reason shape. */
export function viralCheckerLine(generation: ViralGeneration): string {
  if (generation.checker_passed) return 'Checker: pass';
  return `Checker: ${generation.checker_decision || 'fail'}`;
}

function inlineShots(text: string): { filename: string; source: string }[] {
  return text.split('\n').map(line => line.trim()).filter(Boolean)
    .map(filename => ({ filename, source: 'owner_upload' }));
}

export function ViralCreditsBadge({ credits }: { credits: ViralCredits | undefined }) {
  const remaining = credits?.remaining_credits;
  const warning = viralCreditWarning(credits);
  return <p className="hint" data-testid="viral-credits-remaining">
    Credits remaining: {typeof remaining === 'number' ? remaining : '...'}
    {warning ? ` (${warning})` : ''}
  </p>;
}

export function ViralGenerationCard({ generation }: { generation: ViralGeneration }) {
  const frames = generationFrames(generation);
  return <article className="panel queue-card" data-generation-id={generation.id}>
    <p><strong>{generation.output_format}</strong> <span className="badge">{generation.media_mode}</span></p>
    <p className="hint">{viralCheckerLine(generation)} · Approval: {generation.approval_state || 'awaiting_human_approval'}</p>
    {generation.run_id && <p className="hint">Linked approval-bound run: {generation.run_id}</p>}
    <p className="hint">Provenance: {generation.media_provenance} · Credits after: {generation.remaining_credits_after}</p>
    <ul aria-label="Generated frames or scenes">
      {frames.map((frame, index) => <li key={index}>
        {String(frame.text ?? frame.shot_text ?? frame.hook ?? `Part ${index + 1}`)}{' '}
        <span className="hint">({String(frame.aspect_ratio ?? '')})</span>
      </li>)}
    </ul>
  </article>;
}

export function ViralGeneratorPanel() {
  const client = useQueryClient();
  const [mode, setMode] = useState<ViralMediaMode>('screenshots');
  const [selectedAssets, setSelectedAssets] = useState<string[]>([]);
  const [inlineShotsText, setInlineShotsText] = useState('');
  const [recordingName, setRecordingName] = useState('');
  const [facts, setFacts] = useState('');
  const [balance, setBalance] = useState('10');
  const [notice, setNotice] = useState('');
  const creditsQuery = useQuery({ queryKey: ['viral-credits'], queryFn: () => unwrap(api.GET('/api/viral-generator/credits')) });
  const assetsQuery = useQuery({ queryKey: ['media-assets'], queryFn: () => unwrap(api.GET('/api/media/assets')) });
  const generationsQuery = useQuery({ queryKey: ['viral-generations'], queryFn: () => unwrap(api.GET('/api/viral-generator/generations')) });
  const credits = (creditsQuery.data ?? undefined) as ViralCredits | undefined;
  const assets = ((assetsQuery.data ?? []) as MediaAsset[]);
  const generations = ((generationsQuery.data ?? []) as ViralGeneration[]);
  const refresh = () => {
    client.invalidateQueries({ queryKey: ['viral-credits'] });
    client.invalidateQueries({ queryKey: ['viral-generations'] });
  };
  const setCredits = useMutation({
    mutationFn: () => unwrap(api.POST('/api/viral-generator/credits', { body: { remaining_credits: Number(balance) } })),
    onSuccess: () => { setNotice('Credit balance updated.'); refresh(); },
    onError: (error: Error) => setNotice(error.message),
  });
  const generate = useMutation({
    mutationFn: () => {
      const shots = inlineShotsText ? inlineShots(inlineShotsText) : [];
      const confirmed_facts = facts.trim();
      if (mode === 'screen_recording') {
        const pickedVideo = assets.find(asset => asset.media_type === 'video' && selectedAssets.includes(asset.id));
        if (pickedVideo) {
          return unwrap(api.POST('/api/viral-generator/generate', {
            body: { media_mode: mode, asset_ids: [pickedVideo.id], confirmed_facts },
          }));
        }
        return unwrap(api.POST('/api/viral-generator/generate', {
          body: {
            media_mode: mode,
            screen_recording: recordingName.trim()
              ? { filename: recordingName.trim(), source: 'owner_upload' }
              : null,
            confirmed_facts,
          },
        }));
      }
      return unwrap(api.POST('/api/viral-generator/generate', {
        body: { media_mode: mode, asset_ids: selectedAssets, screenshots: shots, confirmed_facts },
      }));
    },
    onSuccess: () => { setNotice('Pack generated and checked.'); setFacts(''); refresh(); },
    onError: (error: Error) => setNotice(error.message),
  });
  const toggleAsset = (id: string) => setSelectedAssets(prev =>
    prev.includes(id) ? prev.filter(entry => entry !== id) : [...prev, id]);
  const exhausted = notice.includes('viral_credits_exhausted') || viralCreditWarning(credits) !== null;
  return <section className="panel" data-testid="viral-generator-panel" aria-label="Viral format generator">
    <h2>Viral format generator</h2>
    <p className="hint">Owner media only. Every asset comes from the owner upload, never a creator clip library.</p>
    <ViralCreditsBadge credits={credits} />
    {creditsQuery.error && <p role="alert">{creditsQuery.error.message}</p>}
    <div className="queue-actions" role="group" aria-label="Viral media mode">
      <Button variant={mode === 'screenshots' ? undefined : 'outline'} onClick={() => setMode('screenshots')} aria-pressed={mode === 'screenshots'}>
        3 to 10 Screenshots to Carousel
      </Button>
      <Button variant={mode === 'screen_recording' ? undefined : 'outline'} onClick={() => setMode('screen_recording')} aria-pressed={mode === 'screen_recording'}>
        1 Screen Recording to Short Video
      </Button>
    </div>
    <div className="queue-card">
      <h3>Owner media</h3>
      <p className="hint">Owner media only. Pick uploaded workspace assets or name inline owner files below.</p>
      {assetsQuery.isPending && <p className="hint">Loading owner assets...</p>}
      {assets.map(asset => <p key={asset.id}>
        <label>
          <input type="checkbox" checked={selectedAssets.includes(asset.id)} onChange={() => toggleAsset(asset.id)} />
          {asset.filename} ({asset.media_type}, {asset.aspect_ratio})
        </label>
      </p>)}
      {mode === 'screenshots' && <p>
        <label htmlFor="viral-inline-shots">Inline owner screenshots (one filename per line, 3 to 10 total with selected assets)</label>
        <textarea id="viral-inline-shots" value={inlineShotsText} onChange={e => setInlineShotsText(e.target.value)} placeholder={'owner-shot-1.png'} />
      </p>}
      {mode === 'screen_recording' && <p>
        <label htmlFor="viral-recording-name">Inline owner screen recording filename (or pick one uploaded video above)</label>
        <input id="viral-recording-name" value={recordingName} onChange={e => setRecordingName(e.target.value)} placeholder="owner-recording.mp4" />
      </p>}
    </div>
    <p>
      <label htmlFor="viral-confirmed-facts">Confirmed facts</label>
      <textarea id="viral-confirmed-facts" value={facts} onChange={e => setFacts(e.target.value)} placeholder="Price, material, and shipping facts the pack must stay grounded in." />
    </p>
    <div className="queue-actions">
      <Button data-testid="viral-generate-btn" onClick={() => generate.mutate()} disabled={generate.isPending}>
        {generate.isPending ? 'Generating...' : 'Generate Pack'}
      </Button>
    </div>
    <div className="queue-card">
      <h3>Credit balance</h3>
      <p>
        <label htmlFor="viral-credits-set">Set credits</label>
        <input id="viral-credits-set" type="number" min={0} value={balance} onChange={e => setBalance(e.target.value)} />
      </p>
      <div className="queue-actions">
        <Button variant="outline" onClick={() => setCredits.mutate()} disabled={setCredits.isPending}>
          {setCredits.isPending ? 'Saving...' : 'Save balance'}
        </Button>
      </div>
    </div>
    {exhausted && viralCreditWarning(credits) && <p role="alert" data-testid="viral-credits-exhausted">{viralCreditWarning(credits)}</p>}
    {notice && <p role="status">{notice}</p>}
    {generationsQuery.isPending && <p>Loading generations...</p>}
    {generationsQuery.error && <p role="alert">{generationsQuery.error.message}</p>}
    {generations.map(generation => <ViralGenerationCard key={generation.id} generation={generation} />)}
    {generations.length === 0 && !generationsQuery.isPending && <p className="hint">No viral packs yet. Generate the first one above.</p>}
  </section>;
}
