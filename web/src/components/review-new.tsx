'use client';
import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog';
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from '@/components/ui/sheet';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { api, unwrap } from '@/lib/api';
import { sanitizeReceiptForPresentation } from '@/lib/approver-presentation';
import {
  ChannelVariantsSection,
  HumanRevisionEditor,
  ReceiptTimeline,
  ConfirmedFactsBlock,
  currentCheckOf,
  currentDraftOf,
  displayRunStatus,
  downloadTextFile,
  humanStatusLabel,
  isLiveRun,
  revisionStatusOf,
  safeExportFilename,
} from '@/components/v2-views';
import { PhotoCheck, readStoredPhoto, readPhotoTransport } from '@/components/photo-check';
import type { components } from '@/lib/schema';

type Receipt = components['schemas']['Receipt'];
type StepRow = { seq: number; stage: string; state: string; observed_at: string | null; profile: string; evidence: Record<string, unknown> };

function modelActuallyUsed(receipt: Receipt): string {
  const current = currentDraftOf(receipt);
  if (current.human) return 'Human edited draft';
  if (draftOriginInfo(receipt).fallback) return 'Rules-based fallback';
  const usage = (receipt as unknown as { model_usage?: { model_used?: unknown } | null }).model_usage;
  if (usage && typeof usage.model_used === 'string' && usage.model_used.trim() && usage.model_used !== 'none') return usage.model_used;
  const draft = (receipt as unknown as { maker_draft_v2?: { model_used?: unknown } | null }).maker_draft_v2;
  if (draft && typeof draft.model_used === 'string' && draft.model_used.trim() && draft.model_used !== 'none') return draft.model_used;
  return 'Not recorded';
}

function sparkCallCount(receipt: Receipt): string {
  const usage = (receipt as unknown as { model_usage?: { spark_calls?: unknown } | null }).model_usage;
  if (usage && typeof usage.spark_calls === 'number') return String(usage.spark_calls);
  return 'unavailable';
}

function draftOriginInfo(receipt: Receipt): { fallback: boolean; origin: string; modelWritten: boolean | null } {
  const draft = (receipt as unknown as { maker_draft_v2?: { draft_origin?: unknown; model_written?: unknown } | null }).maker_draft_v2;
  const origin = draft && typeof draft.draft_origin === 'string' ? draft.draft_origin : 'unavailable';
  const modelWritten = draft && typeof draft.model_written === 'boolean' ? draft.model_written : null;
  if (modelWritten === true) return { fallback: false, origin, modelWritten };
  const fallback = modelWritten === false || origin.toLowerCase().includes('fallback');
  return { fallback, origin, modelWritten };
}

function canApproveRun(receipt: Receipt): { ok: boolean; reason: string } {
  if (receipt.status === 'failed') return { ok: false, reason: 'Failed runs cannot be approved.' };
  if (receipt.status === 'running' || isLiveRun(receipt)) return { ok: false, reason: 'The run is still in flight. Approval unlocks when the final receipt lands.' };
  const check = currentCheckOf(receipt);
  if (!check) return { ok: false, reason: 'Final check is unavailable, so approval stays disabled.' };
  if (typeof check.blocked_count === 'number' && check.blocked_count !== 0) return { ok: false, reason: `Final check still blocks ${check.blocked_count} claim(s). Resolve them with a human revision first.` };
  const stale = revisionStatusOf(receipt) === 'pending fresh approval' && receipt.approval_state === 'approved_for_export';
  if (stale) return { ok: false, reason: 'The pack changed since approval. Save a fresh human revision and approve the latest revision.' };
  if (receipt.approval_state === 'approved_for_export') return { ok: false, reason: 'This revision is already approved for export.' };
  const voiceStale = (receipt as unknown as { voice_stale?: unknown }).voice_stale === true;
  if (voiceStale) return { ok: false, reason: 'Voice profile changed since this receipt. A new human revision check is required.' };
  return { ok: true, reason: '' };
}

function snippetAround(text: string, needle: string, radius = 48): string | null {
  if (!text || !needle) return null;
  const idx = text.toLowerCase().indexOf(needle.toLowerCase());
  if (idx < 0) return null;
  const start = Math.max(0, idx - radius);
  const end = Math.min(text.length, idx + needle.length + radius);
  return (start > 0 ? '...' : '') + text.slice(start, end) + (end < text.length ? '...' : '');
}

function BlockedPhrases({ receipt }: { receipt: Receipt }) {
  const check = currentCheckOf(receipt);
  const v1 = (receipt.checker_v1 ?? null) as { blocked_claims?: Array<{ claim?: string; reason?: string }>; claim_results?: Array<{ claim?: string; reason?: string; evidence?: string | null; evidence_claims?: string[] }> } | null;
  const v1Blocked = (v1?.blocked_claims ?? []) as Array<{ claim?: string; reason?: string }>;
  const v1Results = (v1?.claim_results ?? []) as Array<{ claim?: string; reason?: string; evidence?: string | null; evidence_claims?: string[] }>;
  const originalDraft = receipt.maker_draft_v1 as { post?: string; email?: string } | null | undefined;
  const original = `${originalDraft?.post ?? ''}\n${originalDraft?.email ?? ''}`;
  const current = currentDraftOf(receipt);
  const revised = `${current.post}\n${current.email}`;
  const currentBlocked = (check?.blocked_claims ?? []) as Array<{ claim?: string; reason?: string }>;
  const currentResults = (check?.claim_results ?? []) as Array<{ claim?: string; reason?: string; evidence?: string | null; evidence_claims?: string[] }>;
  const combined = new Map<string, { claim: string; inV1: boolean; inCurrent: boolean }>();
  for (const entry of [...v1Blocked, ...currentBlocked]) {
    const claim = typeof entry.claim === 'string' && entry.claim ? entry.claim : 'Unlabeled claim';
    const hit = combined.get(claim) ?? { claim, inV1: false, inCurrent: false };
    if (v1Blocked.some(b => b.claim === entry.claim)) hit.inV1 = true;
    if (currentBlocked.some(b => b.claim === entry.claim)) hit.inCurrent = true;
    combined.set(claim, hit);
  }
  const reasonFor = (claim: string) => currentResults.find(r => r.claim === claim)?.reason || v1Results.find(r => r.claim === claim)?.reason || currentBlocked.find(b => b.claim === claim)?.reason || v1Blocked.find(b => b.claim === claim)?.reason || 'Blocked by the deterministic Checker';
  const evidenceFor = (claim: string) => {
    const hit = v1Results.find(r => r.claim === claim) ?? currentResults.find(r => r.claim === claim);
    if (!hit) return null;
    if (typeof hit.evidence === 'string' && hit.evidence) return hit.evidence;
    if (Array.isArray(hit.evidence_claims) && hit.evidence_claims.length > 0) return hit.evidence_claims.join('; ');
    return null;
  };
  const rows = [...combined.values()];
  if (rows.length === 0) return <p className="hint">No blocked phrases. The final check is clean.</p>;
  return (
    <ul className="scout-list">
      {rows.map((entry, i) => {
        const reason = reasonFor(entry.claim);
        const evidence = evidenceFor(entry.claim);
        const context = snippetAround(original, entry.claim) || snippetAround(revised, entry.claim);
        return (
          <li key={i} className="scout-fact">
            <p><strong className="line-through text-red-700" style={{ textDecoration: 'line-through' }}>{entry.claim}</strong>{' '}{entry.inCurrent ? <Badge variant="destructive">blocked</Badge> : <Badge variant="outline">Resolved in current revision</Badge>}</p>
            <p className="hint">Reason: {reason}</p>
            {evidence ? <p className="hint">Original evidence: &quot;{evidence}&quot;</p> : <p className="hint">Not in your confirmed facts.</p>}
            {context ? <p className="hint">Original around blocked text: {context}</p> : <p className="hint">Blocked text does not appear verbatim in the kept drafts.</p>}
          </li>
        );
      })}
    </ul>
  );
}

function stageLabel(stage: string): string {
  if (!stage) return 'Unknown stage';
  return stage.split('_').map(part => (part ? part[0].toUpperCase() + part.slice(1) : part)).join(' ');
}

function localStepTime(value: string | null): { text: string; raw: string } {
  if (!value) return { text: 'time not recorded', raw: '' };
  try {
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return { text: 'time not recorded', raw: value };
    return { text: parsed.toLocaleString(), raw: value };
  } catch {
    return { text: 'time not recorded', raw: value };
  }
}

function ModelActivity({ runId, receipt, live }: { runId: string; receipt: Receipt; live: boolean }) {
  const steps = useQuery({
    queryKey: ['run-steps', runId],
    queryFn: () => unwrap(api.GET('/api/runs/{run_id}/steps', { params: { path: { run_id: runId } } })),
    refetchInterval: live ? 1500 : false,
    retry: false,
  });
  const rows = useMemo(() => {
    const all = (((steps.data as { steps?: StepRow[] } | undefined)?.steps ?? []) as StepRow[]);
    const latest = new Map<string, StepRow>();
    for (const row of all) {
      const prev = latest.get(row.stage);
      if (!prev || row.seq >= prev.seq) latest.set(row.stage, row);
    }
    return [...latest.values()].sort((a, b) => a.seq - b.seq);
  }, [steps.data]);
  const transport = readPhotoTransport(receipt);
  return (
    <section aria-label="Model activity">
      <h3>Model activity</h3>
      <p className="hint">Stored stage receipts only. Polls every 1 to 2 seconds while the run is in flight, then stops.</p>
      {steps.isPending && <p role="status">Loading stage receipts...</p>}
      {steps.error && <p role="alert">Stage receipts are unavailable right now. The draft and checks above are still the record.</p>}
      {steps.data && rows.length === 0 && <p className="hint">Fixed rules. No stored stage telemetry on this receipt. Not recorded, never invented.</p>}
      {rows.length > 0 && (
        <ol>
          {rows.map(row => {
            const ev = (row.evidence ?? {}) as Record<string, unknown>;
            const rawModel = typeof ev.model_id === 'string' && ev.model_id.trim() ? ev.model_id : typeof ev.model_used === 'string' && ev.model_used.trim() && ev.model_used !== 'none' ? ev.model_used : null;
            const modelId = rawModel ?? 'Not recorded';
            const calls = typeof ev.spark_calls === 'number' ? String(ev.spark_calls) : typeof ev.actual_calls === 'number' ? String(ev.actual_calls) : typeof ev.calls === 'number' ? String(ev.calls) : 'Not recorded';
            const latency = typeof ev.latency_ms === 'number' ? `${ev.latency_ms} ms` : typeof ev.duration_ms === 'number' ? `${ev.duration_ms} ms` : 'Not recorded';
            const when = localStepTime(row.observed_at);
            return (
              <li key={`${row.seq}-${row.stage}`}>
                <strong>{stageLabel(row.stage)}</strong> · model {modelId} · calls {calls} · latency {latency} · {row.state || 'unknown'}
                <span className="hint" title={when.raw}> · {when.text}</span>
              </li>
            );
          })}
        </ol>
      )}
      {transport && (
        <p className="hint">Photo calls from stored photo evidence: {transport.attempts} attempt(s), {transport.uploads} upload(s), {transport.segmentations} segmentation(s). Handling: {transport.lastHandling}.</p>
      )}
    </section>
  );
}

function ApproveDialog({ receipt, disabledReason }: { receipt: Receipt; disabledReason: string }) {
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const [snapshot, setSnapshot] = useState<{ revision: number; post: string; email: string } | null>(null);
  const current = currentDraftOf(receipt);
  const changedWhileOpen = snapshot !== null && (snapshot.revision !== current.revision || snapshot.post !== current.post || snapshot.email !== current.email);
  const approve = useMutation({
    mutationFn: (revision: number) => unwrap(api.POST('/api/runs/{run_id}/approve', { params: { path: { run_id: receipt.run_id } }, body: { expected_revision: revision } })),
    onSuccess: () => { setOpen(false); setSnapshot(null); client.invalidateQueries({ queryKey: ['run'] }); client.invalidateQueries({ queryKey: ['queue'] }); },
  });
  return (
    <>
      <Button
        disabled={!!disabledReason || approve.isPending}
        title={disabledReason || undefined}
        onClick={() => { setSnapshot({ revision: current.revision, post: current.post, email: current.email }); setOpen(true); approve.reset(); }}
      >
        Approve latest revision
      </Button>
      {disabledReason ? <p className="hint">{disabledReason}</p> : null}
      <Dialog open={open} onOpenChange={value => { if (!approve.isPending) { setOpen(value); if (!value) setSnapshot(null); } }}>
        <DialogContent aria-label="Approve exact text" className="panel queue-card">
          <DialogTitle asChild><h3>Approve exact text</h3></DialogTitle>
          <p className="hint">Snapshot revision {snapshot?.revision ?? current.revision}. Approval binds the exact full post and email below at that revision. Channel variant approvals stay separate and are still required per channel.</p>
          {snapshot && (
            <div><h4>Exact post (revision {snapshot.revision})</h4><p className="draft" style={{ whiteSpace: 'pre-wrap' }}>{snapshot.post || 'unavailable'}</p></div>
          )}
          {snapshot && (
            <div><h4>Exact email (revision {snapshot.revision})</h4><p className="draft" style={{ whiteSpace: 'pre-wrap' }}>{snapshot.email || 'unavailable'}</p></div>
          )}
          {changedWhileOpen && <p role="alert">The pack changed while this dialog was open. Approval is refused until you review the latest revision.</p>}
          {approve.error && <p role="alert">{(approve.error as Error).message}</p>}
          <div className="queue-actions">
            <Button variant="outline" disabled={approve.isPending} onClick={() => { setOpen(false); setSnapshot(null); }}>Cancel</Button>
            <Button disabled={approve.isPending || changedWhileOpen || snapshot === null} onClick={() => { if (snapshot) approve.mutate(snapshot.revision); }}>
              {approve.isPending ? 'Approving...' : `Approve revision ${snapshot?.revision ?? current.revision}`}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}

function ReceiptTab({ receipt }: { receipt: Receipt }) {
  const [jsonOpen, setJsonOpen] = useState(false);
  const client = useQueryClient();
  const safe = useMemo(() => sanitizeReceiptForPresentation(receipt) as Receipt, [receipt]);
  const text = useMemo(() => JSON.stringify(safe, null, 2), [safe]);
  const approved = receipt.approval_state === 'approved_for_export';
  const revision = currentDraftOf(receipt).revision;
  const [exportNote, setExportNote] = useState('');
  const approvedExport = useMutation({
    mutationFn: (expectedRevision: number) => unwrap(api.POST('/api/runs/{run_id}/export', { params: { path: { run_id: receipt.run_id } }, body: { expected_revision: expectedRevision } })),
    onSuccess: artifact => {
      const clean = sanitizeReceiptForPresentation(artifact) as Receipt;
      downloadTextFile(safeExportFilename(clean, new Date(), 'json'), JSON.stringify(clean, null, 2), 'application/json');
      setExportNote(`Approved pack exported: revision ${revision}.`);
      client.invalidateQueries({ queryKey: ['run'] });
      client.invalidateQueries({ queryKey: ['queue'] });
    },
    onError: (error: Error) => setExportNote(error.message),
  });
  const generatedAt = typeof receipt.generated_at === 'string' ? receipt.generated_at : 'timestamp unavailable';
  let local = 'local time unavailable';
  try {
    const parsed = new Date(generatedAt);
    if (!Number.isNaN(parsed.getTime())) local = parsed.toLocaleString();
  } catch { local = 'local time unavailable'; }
  return (
    <div>
      <Card appearance="workspace" asChild><section className="panel" aria-label="Receipt summary">
        <p className="eyebrow">RECEIPT</p>
        <h3>Decision summary</h3>
        <dl>
          <div><dt>Approval state</dt><dd>{humanStatusLabel(receipt.approval_state)}</dd></div>
          <div><dt>Status</dt><dd>{humanStatusLabel(displayRunStatus(receipt))}</dd></div>
          <div><dt>Revision</dt><dd>{currentDraftOf(receipt).revision}</dd></div>
          <div><dt>Recorded at</dt><dd>{local}</dd></div>
        </dl>
      </section></Card>
      <ConfirmedFactsBlock receipt={receipt} />
      <ReceiptTimeline receipt={receipt} />
      <div className="queue-actions">
        <Button
          disabled={!approved || approvedExport.isPending}
          title={approved ? undefined : 'Export needs a current approval for export'}
          onClick={() => { setExportNote(''); approvedExport.mutate(revision); }}
        >
          {approvedExport.isPending ? 'Exporting...' : `Export approved pack (revision ${revision})`}
        </Button>
      </div>
      {!approved && <p className="hint">Export unlocks after the latest revision is approved for export.</p>}
      {exportNote && <p role="status">{exportNote}</p>}
      <Sheet open={jsonOpen} onOpenChange={setJsonOpen}>
        <SheetTrigger asChild><Button variant="outline">Inspect sanitized receipt JSON</Button></SheetTrigger>
        <SheetContent aria-label="Sanitized receipt JSON">
          <SheetHeader><SheetTitle>Sanitized receipt JSON</SheetTitle></SheetHeader>
          <pre style={{ whiteSpace: 'pre-wrap' }}>{text}</pre>
          {false && (
          <div className="queue-actions">
            <Button variant="outline" onClick={() => { void navigator.clipboard.writeText(text); }}>Copy sanitized JSON</Button>
          </div>
          )}
        </SheetContent>
      </Sheet>
    </div>
  );
}

export function ReviewNew({ receipt, runId, onReceipt }: { receipt: Receipt; runId: string; onReceipt: (next: Receipt) => void }) {
  const live = isLiveRun(receipt);
  const current = currentDraftOf(receipt);
  const check = currentCheckOf(receipt);
  const usage = (receipt as unknown as { model_usage?: { model_used?: unknown; spark_calls?: unknown; mode?: unknown } | null }).model_usage;
  const modelUsed = modelActuallyUsed(receipt);
  const eligibility = canApproveRun(receipt);
  const origin = draftOriginInfo(receipt);
  const channel = (receipt as unknown as { channel?: unknown }).channel;
  const channelLabel = typeof channel === 'string' && channel ? channel : 'instagram and email pack';
  const stored = readStoredPhoto(receipt);
  const [kind, setKind] = useState<'post' | 'email'>('post');
  const draftText = kind === 'post' ? current.post : current.email;
  const originalDraft = receipt.maker_draft_v1 as { post?: string; email?: string } | null | undefined;
  const originalCombined = `${originalDraft?.post ?? ''}\n${originalDraft?.email ?? ''}`;
  const revisedCombined = `${current.post}\n${current.email}`;
  const revisedDiffers = originalCombined !== revisedCombined;
  return (
    <section aria-label="Review">
      <dl>
        <div><dt>Status</dt><dd>{humanStatusLabel(displayRunStatus(receipt))}</dd></div>
        <div><dt>Channel</dt><dd>{channelLabel}</dd></div>
        <div><dt>Model actually used</dt><dd>{modelUsed}</dd></div>
        <div><dt>Deterministic Checker result</dt><dd>{check ? `${check.verified_count ?? 'unavailable'} verified, ${check.blocked_count ?? 'unavailable'} blocked` : 'unavailable'}</dd></div>
        <div><dt>Model calls recorded</dt><dd>{sparkCallCount(receipt)}{usage && typeof usage.mode === 'string' ? ` · ${usage.mode}` : ''}</dd></div>
      </dl>
      <Tabs defaultValue="draft">
        <TabsList aria-label="Review tabs">
          <TabsTrigger value="draft">Draft</TabsTrigger>
          <TabsTrigger value="checks">Checks</TabsTrigger>
          <TabsTrigger value="receipt">Receipt</TabsTrigger>
        </TabsList>
        <TabsContent value="draft">
          {origin.fallback && (
            <Alert><AlertTitle>Muse Spark unavailable, deterministic fallback used</AlertTitle><AlertDescription>This draft uses the deterministic fallback. Review the text below and save a human revision before approval.</AlertDescription></Alert>
          )}
          <div className="queue-actions" role="group" aria-label="Draft selector">
            <Button variant={kind === 'post' ? undefined : 'outline'} onClick={() => setKind('post')}>Post</Button>
            <Button variant={kind === 'email' ? undefined : 'outline'} onClick={() => setKind('email')}>Email</Button>
          </div>
          <h3>Current {kind} draft, revision {current.revision}</h3>
          <p className="draft" style={revisedDiffers ? { whiteSpace: 'pre-wrap', borderLeft: '4px solid #b45309', paddingLeft: '8px' } : { whiteSpace: 'pre-wrap' }}>{draftText || 'unavailable'}</p>
          {revisedDiffers
            ? <p className="hint">Revised text differs from the original Maker draft; the wording above is the current record.</p>
            : <p className="hint">Current text matches the original Maker draft.</p>}
          <p className="hint">Showing revision {current.revision}{current.human ? ' (saved human revision)' : ' (Maker draft)'} · {revisionStatusOf(receipt)}.</p>
          <h3>Blocked phrases with reason and evidence</h3>
          <BlockedPhrases receipt={receipt} />
          <ApproveDialog receipt={receipt} disabledReason={eligibility.ok ? '' : eligibility.reason} />
          <p className="hint">Channel variant approvals stay separate. Approving this pack does not approve any channel variant text.</p>
          <ModelActivity runId={runId} receipt={receipt} live={live} />
          <details>
            <summary>Editing and channel tools</summary>
            <HumanRevisionEditor receipt={receipt} />
            <ChannelVariantsSection runId={runId} revision={current.revision} />
          </details>
          <PhotoCheck receipt={receipt} onReceipt={onReceipt} />
          {!stored || stored.state === 'no_photo' ? <p className="hint">No photo attached. Text-only approval and export rules apply.</p> : null}
        </TabsContent>
        <TabsContent value="checks">
          <h3>Checks, one list</h3>
          <BlockedPhrases receipt={receipt} />
          <p className="hint">Final blocked: {check?.blocked_count ?? 'unavailable'} · verified: {check?.verified_count ?? 'unavailable'}.</p>
        </TabsContent>
        <TabsContent value="receipt">
          <ReceiptTab receipt={receipt} />
        </TabsContent>
      </Tabs>
    </section>
  );
}

export { canApproveRun as canApproveReviewRun };
