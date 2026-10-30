'use client';
import { useEffect, useState, type ReactNode } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { api, unwrap } from '@/lib/api';
import { canApproveDay, canExportDay, memoryEditPayload } from '@/lib/v2';
import { dataModeCopy, dataModeLabel, dataModeNote } from '@/components/model-status';
import { sourceLabel } from '@/lib/product-facts';
import { RunOutcomesSection } from '@/components/run-outcomes';
import type { components } from '@/lib/schema';

type Receipt = components['schemas']['Receipt'];
type ScoutSection = components['schemas']['ScoutSection'];
type ModelUsage = components['schemas']['ModelUsage'];
type ProductFactsSection = components['schemas']['ProductFactsSection'];
type Check = components['schemas']['Check'];
type Diff = components['schemas']['RunDiff'];
type Day = components['schemas']['CampaignDay'];
const wallet = 'Vegan leather wallet, $49, for Austin commuters, launch on Instagram';

/** Shared seed default: normal runs stay clean unless the reviewer opts in. */
export const SEED_CLAIM_DEFAULT = false;
export const SEED_CLAIM_LABEL = 'Include the unsupported claim demo';
export const SEED_CLAIM_HINT = 'Opt-in demo only. Seeds the unsupported claim “best in Texas” so this receipt shows Checker block it and revise it out. Leave unchecked for a normal run.';

/** Readable supported Checker policy labels with exact enforceable IDs. */
export const SUPPORTED_CHECKER_POLICIES = [
  { label: 'Superlatives', veto: 'superlatives', rule: 'Block superlatives', description: 'Block claims containing hype or superlative words from the strict word list.' },
  { label: 'Price claims', veto: 'price_claims', rule: 'Block price claims', description: 'Block claims containing price values such as $49.' },
];

/** Readable policy summary that keeps every exact ID inspectable. */
export function SupportedPoliciesHint({ legacy }: { legacy?: boolean }) {
  return <p className="hint">Supported Checker policies{legacy ? ' (Legacy strictness: strict adds the superlatives policy)' : ''}: {SUPPORTED_CHECKER_POLICIES.map(policy => <span key={policy.veto}>{policy.label} (<code title={policy.veto}>veto_scope {policy.veto}</code>, <code title={policy.rule}>rule {policy.rule}</code>)</span>).reduce<ReactNode[]>((parts, part, i) => (i === 0 ? [part] : [...parts, ' or ', part]), [])}, exact match. Other free-text rules are advisory only. Deterministic claim safety cannot be relaxed. See /api/checker-policies.</p>;
}

type MemoryItem = components['schemas']['MemoryItemOut'];
const memoryKinds = ['brand_fact', 'profile', 'approval_example', 'blocked_rule', 'voice_profile'] as const;

export function MemoryView() {
  const client = useQueryClient();
  const [kind, setKind] = useState<MemoryItem['kind']>('brand_fact');
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('{}');
  const [runId, setRunId] = useState('');
  const [learnKind, setLearnKind] = useState<components['schemas']['LearnMemory']['kind']>('approval_example');
  const [notice, setNotice] = useState('');
  const refresh = () => client.invalidateQueries({ queryKey: ['memory'] });
  const items = useQuery({ queryKey: ['memory'], queryFn: () => unwrap(api.GET('/api/memory')), refetchInterval: 3000 });
  const create = useMutation({
    mutationFn: () => unwrap(api.POST('/api/memory', { body: { kind, ...memoryEditPayload(title, content) } })),
    onSuccess: () => { setTitle(''); setContent('{}'); setNotice('Memory item created.'); refresh(); }
  });
  const learn = useMutation({
    mutationFn: async () => {
      const result = await api.POST('/api/memory/from-run/{run_id}', { params: { path: { run_id: runId.trim() } }, body: { kind: learnKind } });
      if (result.response.status === 409) throw new Error('Request failed (409). This run is not approved. Approve the run before learning from it.');
      return unwrap(Promise.resolve(result));
    },
    onSuccess: () => { setNotice('Memory learned from the selected run.'); refresh(); }
  });
  return <section aria-label="Memory">
    <p className="boundary">No auto-learning, no auto-post, no auto-send, no publishing. Memory changes require your explicit action.</p>
    <p className="hint">Voice profiles hold 3 to 5 synthetic style examples plus banned terms. Samples are style references only and never become confirmed facts. Editing or deleting a selected voice invalidates dependent approvals until a new revision check passes. Samples stay in your actor workspace.</p>
    <div className="two-column equal">
      <section className="panel"><h2>Create memory</h2><form onSubmit={e => { e.preventDefault(); setNotice(''); create.mutate(); }}>
        <label htmlFor="memory-kind">Kind</label><select id="memory-kind" value={kind} onChange={e => setKind(e.target.value as MemoryItem['kind'])}>{memoryKinds.map(value => <option key={value}>{value}</option>)}</select>
        <label htmlFor="memory-title">Title</label><input id="memory-title" required minLength={1} maxLength={200} value={title} onChange={e => setTitle(e.target.value)} />
        <label htmlFor="memory-content">Content JSON object</label><textarea id="memory-content" required rows={5} value={content} onChange={e => setContent(e.target.value)} />
        {kind === 'voice_profile' && <p className="hint">Voice shape: {"{\"examples\": [{\"input\": \"...\", \"output\": \"...\"}], \"banned_terms\": [\"...\"]}"}. Use synthetic samples only, 3 to 5 pairs. Banned terms block drafts and revisions with concrete reasons. Channel helper is tested only, no live channel UI.</p>}
        {create.error && <p role="alert">{create.error.message}</p>}
        <Button type="submit" disabled={create.isPending}>Create memory</Button>
      </form></section>
      <section className="panel"><h2>Learn from run</h2><p>Only approved runs can be learned from.</p><form onSubmit={e => { e.preventDefault(); setNotice(''); learn.mutate(); }}>
        <label htmlFor="memory-run-id">Run id</label><input id="memory-run-id" required value={runId} onChange={e => setRunId(e.target.value)} />
        <label htmlFor="memory-learn-kind">Learned kind</label><select id="memory-learn-kind" value={learnKind} onChange={e => setLearnKind(e.target.value as typeof learnKind)}><option>approval_example</option><option>blocked_rule</option></select>
        {learn.error && <p role="alert">{learn.error.message}</p>}
        <Button type="submit" disabled={learn.isPending || !runId.trim()}>Learn from run</Button>
      </form></section>
    </div>
    {notice && <p role="status">{notice}</p>}
    <div className="section-row"><h2>Memory items</h2><span className="tiny">Refreshes every 3 seconds</span></div>
    {items.isPending && <p>Loading memory...</p>}{items.error && <p role="alert">{items.error.message}</p>}
    {items.data?.length === 0 && <p>No memory items yet.</p>}
    {items.data?.map(item => <MemoryItemCard key={item.id} item={item} />)}
  </section>;
}

export function MemoryItemCard({ item }: { item: MemoryItem }) {
  const client = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(item.title);
  const [content, setContent] = useState(JSON.stringify(item.content, null, 2));
  const refresh = () => client.invalidateQueries({ queryKey: ['memory'] });
  const save = useMutation({
    mutationFn: () => unwrap(api.PUT('/api/memory/{item_id}', { params: { path: { item_id: item.id } }, body: memoryEditPayload(title, content) })),
    onSuccess: () => { setEditing(false); refresh(); }
  });
  const remove = useMutation({
    mutationFn: async () => {
      // DELETE returns 204 with no data, so it cannot use unwrap's data requirement.
      const result = await api.DELETE('/api/memory/{item_id}', { params: { path: { item_id: item.id } } });
      if (!result.response.ok) throw new Error(`Request failed (${result.response.status}). Could not delete memory.`);
    },
    onSuccess: refresh
  });
  const busy = save.isPending || remove.isPending;
  return <article className="panel queue-card" aria-label={`Memory item: ${item.title}`}>
    <h3>{item.title}</h3><p>Kind (read-only): {item.kind}</p><p className="run-id">{item.id}</p>
    {item.source_run_id && <p>Source run: {item.source_run_id}</p>}
    {editing ? <form onSubmit={e => { e.preventDefault(); save.mutate(); }}>
      <label htmlFor={`memory-title-${item.id}`}>Edit title</label><input id={`memory-title-${item.id}`} required minLength={1} maxLength={200} value={title} onChange={e => setTitle(e.target.value)} />
      <label htmlFor={`memory-content-${item.id}`}>Edit content JSON object</label><textarea id={`memory-content-${item.id}`} required rows={5} value={content} onChange={e => setContent(e.target.value)} />
      <div className="queue-actions"><Button type="submit" disabled={busy}>Save memory</Button><Button type="button" variant="outline" disabled={busy} onClick={() => setEditing(false)}>Cancel</Button></div>
    </form> : <><pre>{JSON.stringify(item.content, null, 2)}</pre><Button variant="outline" disabled={busy} onClick={() => { setTitle(item.title); setContent(JSON.stringify(item.content, null, 2)); save.reset(); setEditing(true); }}>Edit memory</Button></>}
    {(save.error || remove.error) && <p role="alert">{save.error?.message || remove.error?.message}</p>}
    <Button variant="outline" disabled={busy} onClick={() => {
      // A native confirmation dialog requires explicit confirmation before deletion.
      if (window.confirm(`Delete memory "${item.title}"?`)) remove.mutate();
    }}>Delete memory</Button>
  </article>;
}

export function DiffResult({ diff }: { diff: Diff }) {
  const voiceA = (diff as unknown as { voice_id_a?: string | null; voice_title_a?: string | null; voice_version_a?: string | null }).voice_id_a;
  const voiceB = (diff as unknown as { voice_id_b?: string | null; voice_title_b?: string | null; voice_version_b?: string | null }).voice_id_b;
  const titleA = (diff as unknown as { voice_title_a?: string | null }).voice_title_a;
  const titleB = (diff as unknown as { voice_title_b?: string | null }).voice_title_b;
  const versionA = (diff as unknown as { voice_version_a?: string | null }).voice_version_a;
  const versionB = (diff as unknown as { voice_version_b?: string | null }).voice_version_b;
  const changed = (diff as unknown as { voice_changed?: boolean }).voice_changed;
  return <div>
    {!diff.same_idea && <p role="status" className="message">These runs have different ideas. The comparison still shows their recorded differences.</p>}
    <section className="panel"><h2>Draft changes</h2><p>Idea from run A: {diff.idea}</p>
      <p>First post changed: {String(diff.draft_v1_post_changed)} · First email changed: {String(diff.draft_v1_email_changed)}</p>
      <p>Final post changed: {String(diff.draft_v2_post_changed)} · Final email changed: {String(diff.draft_v2_email_changed)}</p>
      <div className="two-column equal">{(['a', 'b'] as const).map(side => <article key={side}><h3>Run {side.toUpperCase()}</h3><h4>First post</h4><p className="draft">{diff[`draft_v1_post_${side}`] ?? 'Unavailable'}</p><h4>Final post</h4><p className="draft">{diff[`draft_v2_post_${side}`] ?? 'Unavailable'}</p><h4>Final email</h4><p className="draft">{diff[`draft_v2_email_${side}`] ?? 'Unavailable'}</p></article>)}</div>
    </section>
    <section className="panel"><h2>Checker verdict changes</h2><p>First blocked count: {diff.checker_v1_blocked_count_a ?? 'unavailable'} / {diff.checker_v1_blocked_count_b ?? 'unavailable'}</p><p>Final blocked count: {diff.checker_v2_blocked_count_a ?? 'unavailable'} / {diff.checker_v2_blocked_count_b ?? 'unavailable'}</p>{(['a', 'b'] as const).map(side => <div key={side}><h3>Blocked claims only in {side.toUpperCase()}</h3>{diff[`blocked_claims_only_in_${side}`].map((claim, i) => <p key={i}>{claim.claim}: {claim.reason}</p>)}</div>)}</section>
    <section className="panel"><h2>Checker profile changes</h2><p>Checker profile: {diff.checker_profile_a ?? 'unavailable'} / {diff.checker_profile_b ?? 'unavailable'}</p><p>Changed: {String(diff.checker_profile_changed)}</p><p>Scout: {diff.scout_name_a ?? 'unavailable'} / {diff.scout_name_b ?? 'unavailable'}</p><p>Maker: {diff.maker_name_a ?? 'unavailable'} / {diff.maker_name_b ?? 'unavailable'}</p><p>Checker: {diff.checker_name_a ?? 'unavailable'} / {diff.checker_name_b ?? 'unavailable'}</p><p>Stage bindings changed: {String(diff.stage_bindings_changed)}</p><p>Memory ids only in A: {diff.memory_ids_a.join(', ') || 'None'}</p><p>Memory ids only in B: {diff.memory_ids_b.join(', ') || 'None'}</p></section>
    <section className="panel"><h2>Voice source changes</h2><p>Voice: {titleA || voiceA || 'none'} ({versionA || 'no version'}) / {titleB || voiceB || 'none'} ({versionB || 'no version'})</p><p>Changed: {String(changed ?? (voiceA !== voiceB || versionA !== versionB))}</p><p className="hint">Style references only. Samples never become confirmed facts. Banned terms block with concrete voice reasons.</p></section>
    <section className="panel"><h2>Approval state changes</h2><p>{diff.approval_state_a} / {diff.approval_state_b}</p><p>Changed: {String(diff.approval_state_changed)}</p><p>Status: {diff.status_a} / {diff.status_b}</p></section>
    <section className="panel"><h2>Receipt key diff</h2><p>Only in A: {diff.receipt_keys_only_in_a.join(', ') || 'None'}</p><p>Only in B: {diff.receipt_keys_only_in_b.join(', ') || 'None'}</p></section>
  </div>;
}

/** Voice source/version from receipt.voice_profile. Null when no voice was selected. */
export function VoiceBlock({ receipt }: { receipt: Receipt }) {
  const voice = (receipt as unknown as { voice_profile?: { id?: string | null; title?: string | null; version?: string | null; example_count?: number | null; banned_term_count?: number | null; notice?: string | null } | null }).voice_profile;
  const stale = (receipt as unknown as { voice_stale?: boolean | null }).voice_stale;
  if (!voice || typeof voice !== 'object') return null;
  return <>
    <h3>Voice profile</h3>
    <p className="hint">Source: {voice.title || voice.id || 'voice'} · Version: {voice.version || 'unavailable'} · Examples: {voice.example_count ?? 'unavailable'} · Banned terms: {voice.banned_term_count ?? 'unavailable'}{stale ? ' · Stale: edited or deleted since this receipt, new revision check required' : ''}</p>
    {typeof voice.notice === 'string' && voice.notice && <p className="hint">{voice.notice}</p>}
  </>;
}

/** Product facts from receipt.product_facts with exact provenance. Returns null
 *  on historical or pending receipts that predate the section. */
export function ConfirmedFactsBlock({ receipt }: { receipt: Receipt }) {
  const section = (receipt.product_facts ?? null) as ProductFactsSection | null;
  if (!section || typeof section !== 'object') return null;
  const mode = typeof section.mode === 'string' ? section.mode : 'unknown';
  const templateUsed = section.template_used;
  const templateLabel = typeof section.template_label === 'string' ? section.template_label : '';
  const template = typeof section.template === 'string' ? section.template : '';
  const templateNote = typeof section.template_note === 'string' ? section.template_note : '';
  const fields = Array.isArray(section.fields) ? section.fields : [];
  const confirmedFields = fields.filter(f => f && f.confirmed);
  const confirmedClaims = Array.isArray(section.confirmed_claims) ? section.confirmed_claims : [];
  const suggested = Array.isArray(section.suggested) ? section.suggested : [];
  const founder = section.founder_note ?? null;
  const variant = section.draft_variant ?? null;
  return <>
    <h3>Product facts</h3>
    <p className="hint">Mode: {mode} · Template used: {templateUsed ? 'yes' : 'no'}{templateLabel ? ` · ${templateLabel}` : ''}{template ? ` (${template})` : ''}{templateNote ? ` · ${templateNote}` : ''}</p>
    <h4>Confirmed fields ({confirmedFields.length})</h4>
    {confirmedFields.length === 0 && <p className="hint">No confirmed owner fields on this receipt.</p>}
    <ul className="scout-list">{confirmedFields.map((fact, i) => <li key={i} className="scout-fact"><div className="scout-row"><strong>{fact.label || fact.field || 'Confirmed fact'}: {fact.value || 'empty'}</strong><span className="badge approved">Confirmed</span></div><p className="hint">Source: {fact.source ? sourceLabel(fact.source) : 'unknown'}{fact.claim ? ` · Claim: ${fact.claim}` : ''}</p></li>)}</ul>
    <h4>Confirmed claims ({confirmedClaims.length})</h4>
    {confirmedClaims.length === 0 && <p className="hint">No confirmed claims on this receipt.</p>}
    <ul className="scout-list">{confirmedClaims.map((claim, i) => <li key={i} className="scout-fact"><div className="scout-row"><span>{claim}</span><span className="badge approved">Confirmed</span></div></li>)}</ul>
    <h4>Suggestions, not verified ({suggested.length})</h4>
    {suggested.length === 0 && <p className="hint">No unconfirmed suggestions on this receipt.</p>}
    <ul className="scout-list">{suggested.map((entry, i) => <li key={i} className="scout-fact"><div className="scout-row"><span>{(entry.label || entry.field || 'Suggestion') + ': ' + (entry.value || 'empty')}</span><span className="badge pending">Suggestion</span></div><p className="hint">Source: {entry.source ? sourceLabel(entry.source) : 'unknown'}{entry.reason ? ` · ${entry.reason}` : ' · Suggested but not confirmed by the owner'}</p></li>)}</ul>
    {founder && typeof founder.value === 'string' && founder.value && <>
      <h4>Founder note, separate unverified material</h4>
      <p className="draft">{founder.value}</p>
      <p className="hint">Owner-supplied unverified color, never an authorized factual claim. Source: {founder.source ? sourceLabel(founder.source) : 'unknown'} · Confirmed: {founder.confirmed ? 'yes' : 'no'} · Sentence ok: {founder.sentence_ok ? 'yes' : 'no'} · Authorized as fact: no</p>
    </>}
    {variant && (variant.post || variant.email) && <>
      <h4>Founder draft variant, separate unverified material</h4>
      <p className="hint">{variant.label || 'Owner-supplied founder note variant'} · Authorized: no · Verified: no{variant.note ? ` · ${variant.note}` : ''}</p>
      {variant.post && <><h5>Variant post</h5><p className="draft">{variant.post}</p></>}
      {variant.email && <><h5>Variant email</h5><p className="draft">{variant.email}</p></>}
    </>}
  </>;
}

/** Checker claim results with verdict and quoted evidence. A supported result
 *  records a Checker match only. It never authorizes export. */
export function ClaimResultsBlock({ check, title }: { check: Check | null | undefined; title: string }) {
  if (!check || !Array.isArray(check.claim_results) || check.claim_results.length === 0) return null;
  const results = check.claim_results;
  return <>
    <h4>{title} ({results.length})</h4>
    <p className="hint">Supported: {check.supported_count ?? 'unavailable'} · Unsupported: {check.unsupported_count ?? 'unavailable'} · Conflicts: {check.conflicts_count ?? 'unavailable'}. A supported result does not authorize export. Export still needs human approval.</p>
    <ul className="scout-list">{results.map((entry, i) => {
      const verdict = typeof entry.verdict === 'string' ? entry.verdict : 'unsupported';
      const evidence = typeof entry.evidence === 'string' && entry.evidence ? entry.evidence : null;
      const evidenceClaims = Array.isArray(entry.evidence_claims) ? entry.evidence_claims.filter(c => typeof c === 'string' && c) : [];
      return <li key={i} className="scout-fact"><div className="scout-row"><strong>{entry.claim || 'Unlabeled claim'}</strong><span className={`badge ${entry.verified ? 'approved' : 'pending'}`}>{verdict}</span></div><p className="hint">Reason: {entry.reason || 'none stored'}{entry.source ? ` · Source: ${entry.source}` : ''} · Blocked: {entry.blocked ? 'yes' : 'no'}</p>{evidence && <p className="hint">Evidence: &quot;{evidence}&quot;</p>}{evidenceClaims.length > 0 && <p className="hint">Evidence claims: {evidenceClaims.map(q => `"${q}"`).join(', ')}</p>}</li>;
    })}</ul>
  </>;
}

type SeedMarker = {
  enabled?: unknown;
  claim?: unknown;
  v1_included?: unknown;
  v2_included?: unknown;
  v2_removed?: unknown;
  note?: unknown;
};

/** Approval binding and seed marker exactly as stored. Null when neither is available. */
export function ApprovalBindingBlock({ receipt }: { receipt: Receipt }) {
  const binding = receipt.approval_binding ?? null;
  const seed = (receipt as unknown as { seed_unverified_claim?: unknown }).seed_unverified_claim;
  const hasBinding = !!binding && typeof binding.digest === 'string' && typeof binding.version === 'string';
  const hasSeed = seed !== null && seed !== undefined;
  if (!hasBinding && !hasSeed) return null;
  const marker = (seed ?? {}) as SeedMarker;
  const seedText = typeof seed === 'boolean'
    ? `Seed demo: ${seed ? 'enabled' : 'not enabled'}.`
    : typeof seed === 'object' && seed !== null
      ? `Seed demo: ${marker.enabled ? 'enabled' : 'not enabled'}${typeof marker.claim === 'string' && marker.claim ? ` · claim ${marker.claim}` : ''} · v1 included: ${marker.v1_included ? 'yes' : 'no'} · v2 included: ${marker.v2_included ? 'yes' : 'no'} · v2 removed: ${marker.v2_removed ? 'yes' : 'no'}${typeof marker.note === 'string' && marker.note ? ` · ${marker.note}` : ''}`
      : 'Seed demo: unavailable on this receipt.';
  return <>
    <h4>Approval binding and seed</h4>
    {hasBinding
      ? <p className="hint">Binding version {binding!.version} · digest {binding!.digest}</p>
      : <p className="hint">Approval binding unavailable on this receipt.</p>}
    {hasSeed && <p className="hint">{seedText}</p>}
  </>;
}

export function ScoutFactsSection({ receipt }: { receipt: Receipt }) {
  const scout = (receipt.scout ?? null) as ScoutSection | null;
  const scoutName = receipt.stage_bindings?.scout ?? 'Scout';
  const usage = (receipt.model_usage ?? null) as ModelUsage | null;
  const productMode = (receipt.product_facts as ProductFactsSection | null | undefined)?.mode;
  const isOwner = productMode === 'owner_input';
  if (!scout || !Array.isArray(scout.facts_used)) {
    return <section className="panel" aria-label="Scout facts and sources"><p className="eyebrow">SCOUT FACTS AND RISKS</p><h2>Sourced facts unavailable for this receipt.</h2><p className="hint">Historical or failed runs predate stored Scout facts. No facts are invented here; inspect the complete receipt JSON in the record below.</p><ConfirmedFactsBlock receipt={receipt} /><VoiceBlock receipt={receipt} /><ApprovalBindingBlock receipt={receipt} /></section>;
  }
  const facts = scout.facts_used;
  const risks = Array.isArray(scout.risks) ? scout.risks : [];
  const sourceLabels = Array.isArray(scout.sources) ? scout.sources : [];
  const synthesized = scout.model_mode === 'spark';
  return <section className="panel" aria-label="Scout facts and sources">
    <p className="eyebrow">SCOUT FACTS AND RISKS</p>
    <h2>What Scout sourced{scoutName && scoutName !== 'Scout' ? ` · ${scoutName}` : ''}.</h2>
    {isOwner
      ? <p className="hint">Scout stage{scoutName ? `: ${scoutName}` : ''}. Owner-confirmed facts with provenance from the receipt below. The bundled fictional demo template was not used as facts for this run. No external research was run and no live product verification is claimed. Only confirmed facts reach Maker drafts.</p>
      : <p className="hint">Scout stage{scoutName ? `: ${scoutName}` : ''}. Demo facts only, sourced from the local facts file and demo brand brief below. No external research was run and no live product verification is claimed. Only verified facts reach Maker drafts.</p>}
    <h3>Sourced facts ({facts.length})</h3>
    {facts.length === 0 && <p className="hint">No stored facts on this receipt.</p>}
    <ul className="scout-list">{facts.map((fact, i) => <li key={i} className="scout-fact"><div className="scout-row"><strong>{fact.claim || 'Unlabeled fact'}</strong><span className={`badge ${fact.verified ? 'approved' : 'pending'}`}>{fact.verified ? 'Verified' : 'Unverified'}</span></div><p className="hint">Evidence: {fact.evidence || 'none stored'}{Array.isArray(fact.sources) && fact.sources.length > 0 ? ` · Sources: ${fact.sources.join(', ')}` : ' · No stored source: unverified model hypothesis, not external research.'}</p></li>)}</ul>
    <ConfirmedFactsBlock receipt={receipt} />
    <VoiceBlock receipt={receipt} />
    <ClaimResultsBlock check={receipt.checker_v1} title="First check evidence" />
    <ClaimResultsBlock check={currentCheckOf(receipt)} title="Final check evidence" />
    <ApprovalBindingBlock receipt={receipt} />
    <h3>Risks for review ({risks.length})</h3>
    {isOwner
      ? <p className="hint">Risks are hypotheses for your review, never approved product facts.</p>
      : <p className="hint">Demo risks are hypotheses for your review, never approved product facts.</p>}
    {risks.length === 0 && <p className="hint">No stored risks on this receipt.</p>}
    <ul className="scout-list">{risks.map((risk, i) => <li key={i} className="scout-risk"><div className="scout-row"><span>{risk}</span><span className="tag">{risk.startsWith('Unverified model risk:') ? 'Unverified model hypothesis' : isOwner ? 'Risk, unverified' : 'Demo risk, unverified'}</span></div></li>)}</ul>
    <p className="hint">Model synthesis: {synthesized ? 'spark (optional Scout synthesis received)' : 'none, deterministic fallback'}{scout.model_note ? ` · ${scout.model_note}` : ''}{usage ? ` · Stored usage: ${usage.mode}, ${usage.spark_calls} Spark calls, model ${usage.model_used}. Data: ${dataModeLabel(usage)} (${dataModeCopy(usage)}). ${dataModeNote(usage)}` : ' · Stored model usage unavailable on this receipt. Data: Unknown (unknown). No stored usage on this receipt.'}</p>
    {sourceLabels.length > 0 && <p className="hint">Fact sources on this receipt: {sourceLabels.join(', ')}.</p>}
  </section>;
}

export function ReplayView({ queue }: { queue: Receipt[] }) {
  const [a, setA] = useState('');
  const [b, setB] = useState('');
  const compare = useMutation({ mutationFn: () => unwrap(api.GET('/api/runs/{run_a}/diff/{run_b}', { params: { path: { run_a: a, run_b: b } } })) });
  return <section aria-label="Replay"><section className="panel"><h2>Replay</h2><form onSubmit={e => { e.preventDefault(); compare.mutate(); }}><label htmlFor="replay-a">Run A id</label><input id="replay-a" value={a} onChange={e => setA(e.target.value)} required /><label htmlFor="replay-b">Run B id</label><input id="replay-b" value={b} onChange={e => setB(e.target.value)} required /><Button type="submit" disabled={!a || !b || compare.isPending}>Compare</Button></form><h3>Pick from queue</h3><p className="hint">Queue refreshes every 3 seconds.</p>{queue.map(run => <div key={run.run_id} className="queue-card"><p><RunRef id={run.run_id} /></p><p>{run.idea}</p><div className="queue-actions"><Button variant="outline" onClick={() => setA(run.run_id)}>Use as A</Button><Button variant="outline" onClick={() => setB(run.run_id)}>Use as B</Button></div></div>)}</section>{compare.error && <p role="alert">{compare.error.message}</p>}{compare.data && <DiffResult diff={compare.data} />}{a && <RunOutcomesSection runId={a} label="Run A owner outcomes" />}{b && <RunOutcomesSection runId={b} label="Run B owner outcomes" />}</section>;
}

export function CampaignDayCard({ day, busy, approve, download, markdown, copy }: { day: Day; busy: boolean; approve: () => void; download: () => void; markdown?: () => void; copy?: () => void }) {
  return <article className="panel queue-card"><h3>Day {day.day}: {day.angle}</h3><p>{day.brief}</p><p><RunRef id={day.run_id} /></p><p className="draft">{day.draft_v2_post ?? ''}</p><p>{day.approval_state} · Status: {day.status} · Final blocked count: {day.checker_v2_blocked_count ?? 'unavailable'}</p><div className="queue-actions">{canApproveDay(day) && <Button onClick={approve} disabled={busy}>Approve for export</Button>}{canExportDay(day) && <><Button onClick={download} disabled={busy}>Export pack</Button>{markdown && <Button variant="outline" onClick={markdown} disabled={busy}>Export Markdown</Button>}{copy && <Button variant="outline" onClick={copy} disabled={busy}>Copy pack</Button>}</>}</div></article>;
}

export function CampaignView({ profiles, profilesPending, profilesError }: { profiles: components['schemas']['Profile'][]; profilesPending?: boolean; profilesError?: string }) {
  const client = useQueryClient();
  const [idea, setIdea] = useState(wallet);
  const [agent, setAgent] = useState('Maker');
  const [scout, setScout] = useState('Scout');
  const [checkerAgent, setCheckerAgent] = useState('Checker');
  const [checkerProfile, setCheckerProfile] = useState('standard');
  const [seed, setSeed] = useState(SEED_CLAIM_DEFAULT);
  const [id, setId] = useState('');
  const [notice, setNotice] = useState('');
  const agentsReady = !profilesPending && !profilesError && profiles.length > 0;
  const weeks = useQuery({ queryKey: ['campaigns'], queryFn: () => unwrap(api.GET('/api/campaigns')) });
  const campaign = useQuery({ queryKey: ['campaign', id], queryFn: () => unwrap(api.GET('/api/campaigns/{campaign_id}', { params: { path: { campaign_id: id } } })), enabled: !!id, refetchInterval: 3000 });
  const create = useMutation({ mutationFn: () => unwrap(api.POST('/api/campaigns', { body: { idea, agent_name: agent, scout_name: scout, maker_name: agent, checker_name: checkerAgent, seed_unverified_claim: seed, checker_profile: checkerProfile as 'standard' | 'strict', memory_ids: [] } })), onSuccess: week => { setId(week.id); client.invalidateQueries({ queryKey: ['campaigns'] }); client.invalidateQueries({ queryKey: ['queue'] }); } });
  const approve = useMutation({ mutationFn: (input: { day: number; revision: number }) => unwrap(api.POST('/api/campaigns/{campaign_id}/days/{day}/approve', { params: { path: { campaign_id: id, day: input.day } }, body: { expected_revision: input.revision } })), onSuccess: () => { client.invalidateQueries({ queryKey: ['campaign', id] }); client.invalidateQueries({ queryKey: ['queue'] }); } });
  // Every export path below POSTs the day export first, so the server applies
  // the same approval and revision checks as the JSON download. Markdown and
  // copy only re-present that approved artifact; they add no client authority.
  const dayExport = (input: { day: number; revision: number }) => unwrap(api.POST('/api/campaigns/{campaign_id}/days/{day}/export', { params: { path: { campaign_id: id, day: input.day } }, body: { expected_revision: input.revision } }));
  const download = useMutation({ mutationFn: dayExport, onSuccess: run => {
    downloadTextFile(safeExportFilename(run, new Date(), 'json'), JSON.stringify(run, null, 2), 'application/json'); setNotice(`Export downloaded: ${run.run_id}`);
  } });
  const markdown = useMutation({ mutationFn: dayExport, onSuccess: run => {
    downloadTextFile(safeExportFilename(run, new Date(), 'md'), exportReceiptToMarkdown(run), 'text/markdown'); setNotice(`Markdown export downloaded: ${run.run_id}`);
  } });
  const copy = useMutation({
    mutationFn: dayExport,
    onSuccess: async run => {
      const ok = await copyTextToClipboard(JSON.stringify(run, null, 2));
      setNotice(ok ? `Approved pack copied: ${run.run_id}` : `Copy failed for ${run.run_id}. Download the pack instead.`);
    },
  });
  const error = create.error || campaign.error || weeks.error || approve.error || download.error || markdown.error || copy.error;
  const busyDay = approve.isPending || download.isPending || markdown.isPending || copy.isPending;
  return <section aria-label="Campaign"><section className="panel"><h2>Campaign Week</h2><p>Nothing publishes automatically. Review and approve each day individually.</p><form onSubmit={e => { e.preventDefault(); create.mutate(); }}><label htmlFor="campaign-idea">Idea</label><textarea id="campaign-idea" required maxLength={2000} value={idea} onChange={e => setIdea(e.target.value)} />{profilesPending && <p role="status">Loading agents...</p>}{profilesError && <p role="alert">{profilesError}</p>}<label htmlFor="campaign-scout">Scout agent</label><select id="campaign-scout" value={scout} onChange={e => setScout(e.target.value)} disabled={!agentsReady}>{profiles.map(profile => <option key={profile.name}>{profile.name}</option>)}</select><label htmlFor="campaign-maker">Maker agent</label><select id="campaign-maker" value={agent} onChange={e => setAgent(e.target.value)} disabled={!agentsReady}>{profiles.map(profile => <option key={profile.name}>{profile.name}</option>)}</select><label htmlFor="campaign-checker-agent">Checker agent</label><select id="campaign-checker-agent" value={checkerAgent} onChange={e => setCheckerAgent(e.target.value)} disabled={!agentsReady}>{profiles.map(profile => <option key={profile.name}>{profile.name}</option>)}</select><p className="hint">Each agent runs its own stage. Original names and rules are kept in each day receipt.</p><label htmlFor="campaign-checker">Checker profile</label><select id="campaign-checker" value={checkerProfile} onChange={e => setCheckerProfile(e.target.value)}><option>standard</option><option>strict</option></select><SupportedPoliciesHint /><label className="checkbox"><input type="checkbox" checked={seed} onChange={e => setSeed(e.target.checked)} />{SEED_CLAIM_LABEL}</label><p className="hint">Opt-in demo only. Seeds the unsupported claim “best in Texas” on every day so each receipt shows the block and revision. Leave unchecked for a normal week.</p><Button type="submit" disabled={create.isPending || !agentsReady}>{create.isPending ? 'Creating week...' : 'Create week'}</Button></form><label htmlFor="campaign-select">Open a campaign</label><select id="campaign-select" value={id} onChange={e => setId(e.target.value)}><option value="">Select a week</option>{weeks.data?.map(week => <option key={week.id} value={week.id}>{week.idea} ({week.id})</option>)}</select></section>{error && <p role="alert">{error.message}</p>}{notice && <p role="status">{notice}</p>}{campaign.isFetching && <p>Refreshing week...</p>}{campaign.data && <section><h2>{campaign.data.idea}</h2><p><RunRef id={campaign.data.id} /></p>{campaign.data.days.map(day => <CampaignDayCard key={day.day} day={day} busy={busyDay} approve={() => approve.mutate({ day: day.day, revision: day.revision ?? 0 })} download={() => download.mutate({ day: day.day, revision: day.revision ?? 0 })} markdown={() => markdown.mutate({ day: day.day, revision: day.revision ?? 0 })} copy={() => copy.mutate({ day: day.day, revision: day.revision ?? 0 })} />)}</section>}</section>;
}

export function currentDraftOf(receipt: Receipt) {
  const revision = (receipt as unknown as { revision?: number }).revision ?? 0;
  const human = (receipt as unknown as { human_draft?: { post?: string; email?: string } | null }).human_draft;
  if (revision > 0 && human && typeof human.post === 'string' && typeof human.email === 'string') {
    return { post: human.post, email: human.email, revision, human: true };
  }
  return { post: receipt.maker_draft_v2?.post ?? '', email: receipt.maker_draft_v2?.email ?? '', revision, human: false };
}

export function currentCheckOf(receipt: Receipt) {
  const revision = (receipt as unknown as { revision?: number }).revision ?? 0;
  const human = (receipt as unknown as { human_check?: Receipt['checker_v2'] }).human_check;
  if (revision > 0 && human) return human;
  return receipt.checker_v2;
}

export function revisionStatusOf(receipt: Receipt) {
  const revision = (receipt as unknown as { revision?: number }).revision ?? 0;
  const approved = (receipt as unknown as { approved_revision?: number | null }).approved_revision;
  if (receipt.status === 'failed') return 'failed';
  if (revision > 0 && receipt.approval_state === 'pending_approval') return 'pending fresh approval';
  if (receipt.approval_state === 'approved_for_export' && revision > 0 && approved !== revision) return 'pending fresh approval';
  return receipt.approval_state === 'approved_for_export' ? 'approved' : 'pending approval';
}

/** Compact primary run reference. Full ID stays in the DOM and on hover. */
export function RunRef({ id, className }: { id: string; className?: string }) {
  return <span className={`run-id compact${className ? ` ${className}` : ''}`} title={id}>{id}</span>;
}

const PACK_STARTED_PREFIX = 'Pack started';

/** Replace a stale Pack started notice once the terminal receipt arrives.
 *  Terminal state comes only from receipt status, never from stage counts. */
export function terminalNotice(current: string, runId: string, status: string | undefined): string {
  if (!current.startsWith(PACK_STARTED_PREFIX)) return current;
  if (status === 'completed') return `Pack ready for review: ${runId}.`;
  if (status === 'failed') return `Pack stopped safely: ${runId}. See the failed run record.`;
  return current;
}

type ExportSource = {
  idea?: unknown;
  product_facts?: ProductFactsSection | null;
} & { product_name?: unknown };

function sanitizeSlugCandidate(raw: string): string {
  const withoutContacts = raw
    .replace(/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/g, ' ')
    .replace(/\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b/g, ' ')
    .replace(/\b\d{5,}\b/g, ' ');
  const words = withoutContacts
    .toLowerCase()
    .split(/[^a-z0-9]+/g)
    .map(w => w.trim())
    .filter(Boolean)
    .slice(0, 4)
    .map(w => w.slice(0, 12));
  const slug = words.join('-').replace(/^-+|-+$/g, '').slice(0, 40).replace(/-+$/g, '');
  return slug || 'pack';
}

/** Product slug for exports. Prefers an explicit owner product name when the
 *  receipt carries one, else the first confirmed owner value, else a safe
 *  bounded idea-derived name. Never guesses personal info and never uses raw
 *  freeform text or the run id as the product. */
export function exportProductSlug(receipt: ExportSource): string {
  const explicit = (receipt as { product_name?: unknown }).product_name;
  if (typeof explicit === 'string' && explicit.trim()) return sanitizeSlugCandidate(explicit);
  const section = receipt.product_facts ?? null;
  if (section && section.mode === 'owner_input') {
    const fields = Array.isArray(section.fields) ? section.fields : [];
    const order = ['material', 'contents', 'size', 'price'];
    for (const name of order) {
      const hit = fields.find(f => f && f.field === name && f.confirmed && typeof f.value === 'string' && f.value.trim());
      if (hit) return sanitizeSlugCandidate(hit.value);
    }
    const claims = Array.isArray(section.confirmed_claims) ? section.confirmed_claims : [];
    const first = claims.find(c => typeof c === 'string' && c.trim());
    if (first) return sanitizeSlugCandidate(first);
  }
  if (typeof receipt.idea === 'string' && receipt.idea.trim()) return sanitizeSlugCandidate(receipt.idea);
  return 'pack';
}

/** Safe product and date download name. Only lowercase letters, digits, and dashes. */
export function safeExportFilename(receipt: ExportSource, now: Date, ext: 'json' | 'md'): string {
  const day = Number.isNaN(now.getTime()) ? 'nodate' : now.toISOString().slice(0, 10).replaceAll('-', '');
  return `launchcrew-pack-${day}-${exportProductSlug(receipt)}.${ext}`;
}

export function downloadTextFile(filename: string, text: string, mime: string) {
  const url = URL.createObjectURL(new Blob([text], { type: mime }));
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

export async function copyTextToClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    try {
      const area = document.createElement('textarea');
      area.value = text;
      area.setAttribute('readonly', '');
      area.style.position = 'fixed';
      area.style.opacity = '0';
      document.body.appendChild(area);
      area.select();
      const ok = document.execCommand('copy');
      area.remove();
      return ok;
    } catch {
      return false;
    }
  }
}

/** Markdown rendering of the server-approved export artifact (a Receipt from
 *  the export endpoint). Every line comes from that artifact; nothing is
 *  re-derived from client state and no approval is implied client-side. */
export function exportReceiptToMarkdown(receipt: Receipt): string {
  const exported = (receipt as unknown as { exported_draft?: { post?: unknown; email?: unknown } | null }).exported_draft;
  const exportedRevision = (receipt as unknown as { exported_revision?: number | null }).exported_revision;
  const current = currentDraftOf(receipt);
  const post = typeof exported?.post === 'string' ? exported.post : current.post;
  const email = typeof exported?.email === 'string' ? exported.email : current.email;
  const check = currentCheckOf(receipt);
  const approvals = receipt.approvals.map(entry => `- ${entry.approved_by}${entry.revision != null ? `, revision ${entry.revision}` : ''}, ${entry.timestamp}`);
  const blocked = (check?.blocked_claims ?? []).map(entry => `- ${(entry as { claim?: string }).claim ?? 'unsupported text'}: ${(entry as { reason?: string }).reason ?? 'needs revision'}`);
  const submitted = (receipt.summary as unknown as { submit_attempted?: unknown } | null)?.submit_attempted;
  const lines = [
    '# LaunchCrew launch pack',
    '',
    `- Idea: ${receipt.idea || 'Untitled pack'}`,
    `- Run: ${receipt.run_id}`,
    `- Revision: ${receipt.revision}${exportedRevision != null ? ` (exported revision ${exportedRevision})` : ''}`,
    `- Approval state: ${receipt.approval_state}`,
    ...approvals.map(line => `- Approval: ${line.slice(2)}`),
    '',
    '## Instagram draft',
    '',
    post || 'Unavailable',
    '',
    '## Email draft',
    '',
    email || 'Unavailable',
    '',
    '## Final check',
    '',
    `- Final blocked claims: ${check?.blocked_count ?? 'unavailable'}`,
    ...blocked,
    '',
    '## Submission',
    '',
    submitted === false ? 'Not attempted.' : submitted === true ? 'Attempted.' : 'Unrecorded on this artifact.',
    '',
  ];
  return lines.join('\n');
}

export function FailedRunNotice({ receipt }: { receipt: Receipt }) {
  if (receipt.status !== 'failed') return null;
  const audit = (receipt.audit ?? {}) as { event_log?: unknown[]; stopped_reason?: unknown };
  const log = Array.isArray(audit.event_log) ? audit.event_log : [];
  const stopped = typeof audit.stopped_reason === 'string' ? audit.stopped_reason : 'unavailable';
  const failedAt = log.length > 0 ? (log[log.length - 1] as { step?: string }).step ?? stopped : stopped;
  return <section className="panel" aria-label="Failed run"><p className="eyebrow">RUN STATUS</p><h2>Pipeline stopped safely.</h2><p>This run failed before a complete draft existed, so there is nothing to edit, approve, or export.</p><dl><div><dt>Status</dt><dd>failed</dd></div><div><dt>Failure stage</dt><dd>{String(failedAt)}</dd></div><div><dt>Error type</dt><dd>{(receipt as unknown as { error_type?: string }).error_type ?? 'unavailable'}</dd></div><div><dt>Completed steps</dt><dd>{((receipt as unknown as { completed_steps?: string[] }).completed_steps ?? []).join(', ') || 'none'}</dd></div></dl><p className="hint">No approval or export is offered on failed runs. The stored record is kept as evidence.</p></section>;
}

export function ReceiptTimeline({ receipt }: { receipt: Receipt }) {
  const audit = (receipt.audit ?? {}) as { event_log?: Array<{ step?: string; agent?: string; profile?: string; action?: string; timestamp?: string; revision?: number; exported_by?: string }> };
  const log = Array.isArray(audit.event_log) ? audit.event_log : [];
  const history = ((receipt as unknown as { revision_history?: Array<{ revision?: number; approved_revision?: number | null; superseded_by?: number; outcome?: string; revised_by?: string; revised_at?: string; photo_event?: string; photo_status?: { state?: string; label?: string | null; reason?: string } | null; approvals?: Array<{ approved_by?: string; revision?: number; timestamp?: string }> }> }).revision_history ?? []);
  const exports = ((receipt as unknown as { export_history?: Array<{ revision?: number; exported_by?: string; timestamp?: string }> }).export_history ?? []);
  return <section className="panel" aria-label="Receipt timeline"><p className="eyebrow">TIMELINE</p><h2>Recorded events</h2><p className="hint">Every entry below comes from the stored receipt. No times are invented and no live model activity is claimed.</p><ol>{log.map((entry, i) => <li key={i}><strong>{entry.step ?? 'event'}</strong><span> · {entry.agent ?? 'unknown'}{entry.profile ? ` (${entry.profile})` : ''}</span><br /><small>{entry.action ?? ''}</small><br /><small className="run-id">{entry.timestamp ?? 'timestamp unavailable'}</small></li>)}</ol>{history.length > 0 && <div><h3>Superseded revisions</h3>{history.map((entry, i) => <p key={i} className="hint">Revision {entry.revision ?? '?'} superseded by revision {entry.superseded_by ?? '?'} · revised by {entry.revised_by ?? 'unknown'}{entry.revised_at ? ` · ${entry.revised_at}` : ''}{entry.photo_event ? ` · photo event: ${entry.photo_event}${entry.photo_status?.state ? ` (prior photo: ${entry.photo_status.state}${entry.photo_status.label ? ` ${entry.photo_status.label}` : ''})` : ''}` : ''} · approvals kept as audit: {(entry.approvals ?? []).map(a => `${a.approved_by ?? 'unknown'}${a.revision != null ? ` (rev ${a.revision})` : ''}`).join(', ') || 'none'}</p>)}</div>}{exports.length > 0 && <div><h3>Exports</h3>{exports.map((entry, i) => <p key={i} className="hint">Exported revision {entry.revision ?? '?'} by {entry.exported_by ?? 'unknown'} · {entry.timestamp ?? 'timestamp unavailable'}</p>)}</div>}{receipt.approvals.map((approval, i) => <p key={i} className="hint">Approval {i + 1}: {approval.approved_by}{approval.revision != null ? ` · revision ${approval.revision}` : ''} · {approval.timestamp}</p>)}</section>;
}

export function HumanRevisionEditor({ receipt }: { receipt: Receipt }) {
  const client = useQueryClient();
  const failed = receipt.status === 'failed';
  const base = currentDraftOf(receipt);
  const [post, setPost] = useState(base.post);
  const [email, setEmail] = useState(base.email);
  const [savedAtRevision, setSavedAtRevision] = useState(base.revision);
  useEffect(() => { setPost(base.post); setEmail(base.email); }, [receipt.run_id, base.revision, base.post, base.email]);
  const dirty = post !== base.post || email !== base.email;
  const save = useMutation({
    mutationFn: async () => {
      const result = await api.POST('/api/runs/{run_id}/revise', { params: { path: { run_id: receipt.run_id } }, body: { post, email, base_revision: base.revision } });
      if (!result.response.ok || result.data === undefined) {
        const detail = (result.error as unknown as { detail?: unknown })?.detail;
        const blocked = detail && typeof detail === 'object' && Array.isArray((detail as { blocked_claims?: unknown[] }).blocked_claims)
          ? (detail as { blocked_claims: Array<{ claim?: string; reason?: string }> }).blocked_claims.map(entry => `${entry.claim ?? 'unsupported text'}: ${entry.reason ?? 'needs revision'}`).join('; ')
          : null;
        throw new Error(blocked ? `Unsupported text rejected (${result.response.status}). ${blocked}` : `Request failed (${result.response.status}). Check the API and try again.`);
      }
      return result.data;
    },
    onSuccess: updated => { setSavedAtRevision(updated.revision ?? base.revision + 1); client.invalidateQueries({ queryKey: ['run'] }); client.invalidateQueries({ queryKey: ['queue'] }); },
  });
  const needsRevision = save.error ? String((save.error as Error).message) : '';
  const saved = !dirty && !save.isPending && savedAtRevision === base.revision && base.revision > 0;
  return <section className="panel" aria-label="Edit drafts"><p className="eyebrow">HUMAN REVIEW</p><h2>Edit post and email</h2><p className="hint">Rechecking compares your edited text against the same verified facts, blocked rules, and Checker policies saved on this run. Unsupported text is rejected and not saved. Saved text clears the prior export approval until you approve the latest revision.</p><p className="hint">Current revision: {base.revision}{base.human ? ' (human revision)' : ' (Maker draft)'} · Status: {revisionStatusOf(receipt)}</p><form onSubmit={e => { e.preventDefault(); save.reset(); save.mutate(); }}><label htmlFor={`human-post-${receipt.run_id}`}>Post text</label><textarea id={`human-post-${receipt.run_id}`} rows={4} required maxLength={2000} value={post} onChange={e => { setPost(e.target.value); }} disabled={failed || save.isPending} /><label htmlFor={`human-email-${receipt.run_id}`}>Email text</label><textarea id={`human-email-${receipt.run_id}`} rows={4} required maxLength={2000} value={email} onChange={e => { setEmail(e.target.value); }} disabled={failed || save.isPending} /><div className="queue-actions"><Button type="submit" disabled={failed || save.isPending || !dirty || !post.trim() || !email.trim()}>{save.isPending ? 'Rechecking...' : 'Save human revision'}</Button></div></form>{dirty && <p role="status">Unsaved changes. Save runs the deterministic recheck.</p>}{saved && <p role="status">Saved revision {base.revision}. This pack needs fresh approval before export.</p>}{save.error && <p role="alert">Needs revision: {needsRevision}. The invalid text was not saved.</p>}</section>;
}

export const RUN_STAGE_ORDER = ['accepted', 'deterministic_checks', 'scout', 'maker_draft_v1', 'checker_v1', 'maker_draft_v2', 'checker_v2', 'receipt'];

const RUN_STAGE_LABELS: Record<string, string> = {
  accepted: 'Accepted',
  deterministic_checks: 'Deterministic checks',
  scout: 'Scout facts',
  maker_draft_v1: 'Maker first draft',
  checker_v1: 'Checker first check',
  maker_draft_v2: 'Maker revision',
  checker_v2: 'Checker recheck',
  receipt: 'Final receipt',
};

export type StageProgressState = 'completed' | 'started' | 'pending' | 'failed';

export type StageProgress = {
  stage: string;
  label: string;
  state: StageProgressState;
  observedAt: string | null;
  profile: string;
  evidence: Record<string, unknown>;
};

export type StoredStep = {
  stage: string;
  state: string;
  observed_at?: string | null;
  profile?: string | null;
  evidence?: Record<string, unknown> | null;
};

/** Latest stored state per pipeline stage, in pipeline order. Pure and total: unknown stages are ignored. */
export function describeStageProgress(steps: StoredStep[]): StageProgress[] {
  const latest = new Map<string, StoredStep>();
  for (const row of steps) {
    if (typeof row.stage === 'string' && RUN_STAGE_ORDER.includes(row.stage)) latest.set(row.stage, row);
  }
  return RUN_STAGE_ORDER.map(stage => {
    const row = latest.get(stage);
    const raw = row?.state;
    const state: StageProgressState = raw === 'completed' || raw === 'started' || raw === 'failed' ? raw : 'pending';
    return {
      stage,
      label: RUN_STAGE_LABELS[stage],
      state,
      observedAt: typeof row?.observed_at === 'string' ? row.observed_at : null,
      profile: typeof row?.profile === 'string' ? row.profile : '',
      evidence: row?.evidence && typeof row.evidence === 'object' ? row.evidence : {},
    };
  });
}

function evidenceValue(evidence: Record<string, unknown>, key: string): string | null {
  const value = evidence[key];
  return typeof value === 'number' || typeof value === 'string' ? String(value) : null;
}

/** One honest line drawn only from stored step evidence. Never predicts. */
export function stageEvidenceCopy(stage: string, evidence: Record<string, unknown>): string {
  if (stage === 'accepted') {
    const chars = evidenceValue(evidence, 'idea_chars');
    return chars === null ? 'run accepted' : `run accepted · idea ${chars} chars`;
  }
  if (stage === 'deterministic_checks') {
    const facts = evidenceValue(evidence, 'facts');
    return facts === null ? 'facts file checked' : `${facts} approved facts checked`;
  }
  if (stage === 'scout') {
    const facts = evidenceValue(evidence, 'facts_used');
    const risks = evidenceValue(evidence, 'risks');
    const mode = evidenceValue(evidence, 'model_mode');
    return `${facts ?? '?'} facts sourced · ${risks ?? '?'} risks${mode ? ` · synthesis ${mode}` : ''}`;
  }
  if (stage === 'maker_draft_v1' || stage === 'maker_draft_v2') {
    const claims = evidenceValue(evidence, 'claims');
    return claims === null ? 'draft written' : `${claims} claims drafted`;
  }
  if (stage === 'checker_v1' || stage === 'checker_v2') {
    const blocked = evidenceValue(evidence, 'blocked_count');
    const verified = evidenceValue(evidence, 'verified_count');
    return `blocked ${blocked ?? '?'} · verified ${verified ?? '?'}`;
  }
  if (stage === 'receipt') {
    const blocked = evidenceValue(evidence, 'blocked_count');
    return evidence['stored'] === true
      ? `receipt stored${blocked === null ? '' : ` · final blocked ${blocked}`}`
      : 'receipt prepared';
  }
  return 'recorded';
}

export function RunProgressList({ stages, workerLive, running }: { stages: StageProgress[]; workerLive: boolean; running: boolean }) {
  const unconfirmed = running && !workerLive && stages.some(stage => stage.state === 'completed' || stage.state === 'started');
  return <section className="panel" aria-label="Run progress">
    <p className="eyebrow">LIVE STAGE RECEIPTS</p>
    <h2>{running ? 'Pack in progress.' : 'Pack finished.'}</h2>
    <p className="hint">Each row below was stored when the pipeline actually reached that stage, with the server time. Nothing here is predicted and no per-stage timing is estimated. Approval, editing, photo checks, and export unlock only after the final receipt lands.</p>
    {unconfirmed && <p role="alert">Pipeline worker not observed. Completed rows below are stored evidence, but the result is unconfirmed: nothing restarts automatically. Reload, or create a new pack.</p>}
    <ol>{stages.map(stage => <li key={stage.stage}><strong>{stage.label}</strong><span> · {stage.state === 'completed' ? 'completed' : stage.state === 'started' ? 'in progress' : stage.state === 'failed' ? 'failed' : 'pending'}</span>{stage.profile && <span> · {stage.profile}</span>}<br /><small>{stage.state === 'pending' ? 'not yet reached' : stageEvidenceCopy(stage.stage, stage.evidence)}</small>{stage.observedAt && <><br /><small className="run-id">{stage.observedAt}</small></>}</li>)}</ol>
  </section>;
}

export function RunProgressSection({ runId, receipt }: { runId: string; receipt: Receipt }) {
  const steps = useQuery({
    queryKey: ['run-steps', runId],
    queryFn: () => unwrap(api.GET('/api/runs/{run_id}/steps', { params: { path: { run_id: runId } } })),
    refetchInterval: 2000,
  });
  const running = receipt.status === 'running';
  const stages = describeStageProgress((steps.data?.steps ?? []) as StoredStep[]);
  return <>
    {steps.isPending && <p>Loading stage receipts...</p>}
    {steps.error && <p role="alert">{(steps.error as Error).message}</p>}
    {steps.data && <RunProgressList stages={stages} workerLive={steps.data.worker_live} running={running} />}
  </>;
}
