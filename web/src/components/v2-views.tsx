'use client';
import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { api, unwrap } from '@/lib/api';
import { canApproveDay, canExportDay, memoryEditPayload } from '@/lib/v2';
import { dataModeCopy, dataModeLabel, dataModeNote } from '@/components/model-status';
import type { components } from '@/lib/schema';

type Receipt = components['schemas']['Receipt'];
type ScoutSection = components['schemas']['ScoutSection'];
type ModelUsage = components['schemas']['ModelUsage'];
type Diff = components['schemas']['RunDiff'];
type Day = components['schemas']['CampaignDay'];
const wallet = 'Vegan leather wallet, $49, for Austin commuters, launch on Instagram';

type MemoryItem = components['schemas']['MemoryItemOut'];
const memoryKinds = ['brand_fact', 'profile', 'approval_example', 'blocked_rule'] as const;

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
    <div className="two-column equal">
      <section className="panel"><h2>Create memory</h2><form onSubmit={e => { e.preventDefault(); setNotice(''); create.mutate(); }}>
        <label htmlFor="memory-kind">Kind</label><select id="memory-kind" value={kind} onChange={e => setKind(e.target.value as MemoryItem['kind'])}>{memoryKinds.map(value => <option key={value}>{value}</option>)}</select>
        <label htmlFor="memory-title">Title</label><input id="memory-title" required minLength={1} maxLength={200} value={title} onChange={e => setTitle(e.target.value)} />
        <label htmlFor="memory-content">Content JSON object</label><textarea id="memory-content" required rows={5} value={content} onChange={e => setContent(e.target.value)} />
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
  return <div>
    {!diff.same_idea && <p role="status" className="message">These runs have different ideas. The comparison still shows their recorded differences.</p>}
    <section className="panel"><h2>Draft changes</h2><p>Idea from run A: {diff.idea}</p>
      <p>First post changed: {String(diff.draft_v1_post_changed)} · First email changed: {String(diff.draft_v1_email_changed)}</p>
      <p>Final post changed: {String(diff.draft_v2_post_changed)} · Final email changed: {String(diff.draft_v2_email_changed)}</p>
      <div className="two-column equal">{(['a', 'b'] as const).map(side => <article key={side}><h3>Run {side.toUpperCase()}</h3><h4>First post</h4><p className="draft">{diff[`draft_v1_post_${side}`] ?? 'Unavailable'}</p><h4>Final post</h4><p className="draft">{diff[`draft_v2_post_${side}`] ?? 'Unavailable'}</p><h4>Final email</h4><p className="draft">{diff[`draft_v2_email_${side}`] ?? 'Unavailable'}</p></article>)}</div>
    </section>
    <section className="panel"><h2>Checker verdict changes</h2><p>First blocked count: {diff.checker_v1_blocked_count_a ?? 'unavailable'} / {diff.checker_v1_blocked_count_b ?? 'unavailable'}</p><p>Final blocked count: {diff.checker_v2_blocked_count_a ?? 'unavailable'} / {diff.checker_v2_blocked_count_b ?? 'unavailable'}</p>{(['a', 'b'] as const).map(side => <div key={side}><h3>Blocked claims only in {side.toUpperCase()}</h3>{diff[`blocked_claims_only_in_${side}`].map((claim, i) => <p key={i}>{claim.claim}: {claim.reason}</p>)}</div>)}</section>
    <section className="panel"><h2>Checker profile changes</h2><p>Checker profile: {diff.checker_profile_a ?? 'unavailable'} / {diff.checker_profile_b ?? 'unavailable'}</p><p>Changed: {String(diff.checker_profile_changed)}</p><p>Scout: {diff.scout_name_a ?? 'unavailable'} / {diff.scout_name_b ?? 'unavailable'}</p><p>Maker: {diff.maker_name_a ?? 'unavailable'} / {diff.maker_name_b ?? 'unavailable'}</p><p>Checker: {diff.checker_name_a ?? 'unavailable'} / {diff.checker_name_b ?? 'unavailable'}</p><p>Stage bindings changed: {String(diff.stage_bindings_changed)}</p><p>Memory ids only in A: {diff.memory_ids_a.join(', ') || 'None'}</p><p>Memory ids only in B: {diff.memory_ids_b.join(', ') || 'None'}</p></section>
    <section className="panel"><h2>Approval state changes</h2><p>{diff.approval_state_a} / {diff.approval_state_b}</p><p>Changed: {String(diff.approval_state_changed)}</p><p>Status: {diff.status_a} / {diff.status_b}</p></section>
    <section className="panel"><h2>Receipt key diff</h2><p>Only in A: {diff.receipt_keys_only_in_a.join(', ') || 'None'}</p><p>Only in B: {diff.receipt_keys_only_in_b.join(', ') || 'None'}</p></section>
  </div>;
}

export function ScoutFactsSection({ receipt }: { receipt: Receipt }) {
  const scout = (receipt.scout ?? null) as ScoutSection | null;
  const scoutName = receipt.stage_bindings?.scout ?? 'Scout';
  const usage = (receipt.model_usage ?? null) as ModelUsage | null;
  if (!scout || !Array.isArray(scout.facts_used)) {
    return <section className="panel" aria-label="Scout facts and sources"><p className="eyebrow">SCOUT FACTS AND RISKS</p><h2>Sourced facts unavailable for this receipt.</h2><p className="hint">Historical or failed runs predate stored Scout facts. No facts are invented here; inspect the complete receipt JSON in the record below.</p></section>;
  }
  const facts = scout.facts_used;
  const risks = Array.isArray(scout.risks) ? scout.risks : [];
  const sourceLabels = Array.isArray(scout.sources) ? scout.sources : [];
  const synthesized = scout.model_mode === 'spark';
  return <section className="panel" aria-label="Scout facts and sources">
    <p className="eyebrow">SCOUT FACTS AND RISKS</p>
    <h2>What Scout sourced{scoutName && scoutName !== 'Scout' ? ` · ${scoutName}` : ''}.</h2>
    <p className="hint">Scout stage{scoutName ? `: ${scoutName}` : ''}. Demo facts only, sourced from the local facts file and demo brand brief below. No external research was run and no live product verification is claimed. Only verified facts reach Maker drafts.</p>
    <h3>Sourced facts ({facts.length})</h3>
    {facts.length === 0 && <p className="hint">No stored facts on this receipt.</p>}
    <ul className="scout-list">{facts.map((fact, i) => <li key={i} className="scout-fact"><div className="scout-row"><strong>{fact.claim || 'Unlabeled fact'}</strong><span className={`badge ${fact.verified ? 'approved' : 'pending'}`}>{fact.verified ? 'Verified' : 'Unverified'}</span></div><p className="hint">Evidence: {fact.evidence || 'none stored'}{Array.isArray(fact.sources) && fact.sources.length > 0 ? ` · Sources: ${fact.sources.join(', ')}` : ' · No stored source: unverified model hypothesis, not external research.'}</p></li>)}</ul>
    <h3>Risks for review ({risks.length})</h3>
    <p className="hint">Demo risks are hypotheses for your review, never approved product facts.</p>
    {risks.length === 0 && <p className="hint">No stored risks on this receipt.</p>}
    <ul className="scout-list">{risks.map((risk, i) => <li key={i} className="scout-risk"><div className="scout-row"><span>{risk}</span><span className="tag">{risk.startsWith('Unverified model risk:') ? 'Unverified model hypothesis' : 'Demo risk, unverified'}</span></div></li>)}</ul>
    <p className="hint">Model synthesis: {synthesized ? 'spark (optional Scout synthesis received)' : 'none, deterministic fallback'}{scout.model_note ? ` · ${scout.model_note}` : ''}{usage ? ` · Stored usage: ${usage.mode}, ${usage.spark_calls} Spark calls, model ${usage.model_used}. Data: ${dataModeLabel(usage)} (${dataModeCopy(usage)}). ${dataModeNote(usage)}` : ' · Stored model usage unavailable on this receipt. Data: Unknown (unknown). No stored usage on this receipt.'}</p>
    {sourceLabels.length > 0 && <p className="hint">Fact sources on this receipt: {sourceLabels.join(', ')}.</p>}
  </section>;
}

export function ReplayView({ queue }: { queue: Receipt[] }) {
  const [a, setA] = useState('');
  const [b, setB] = useState('');
  const compare = useMutation({ mutationFn: () => unwrap(api.GET('/api/runs/{run_a}/diff/{run_b}', { params: { path: { run_a: a, run_b: b } } })) });
  return <section aria-label="Replay"><section className="panel"><h2>Replay</h2><form onSubmit={e => { e.preventDefault(); compare.mutate(); }}><label htmlFor="replay-a">Run A id</label><input id="replay-a" value={a} onChange={e => setA(e.target.value)} required /><label htmlFor="replay-b">Run B id</label><input id="replay-b" value={b} onChange={e => setB(e.target.value)} required /><Button type="submit" disabled={!a || !b || compare.isPending}>Compare</Button></form><h3>Pick from queue</h3><p className="hint">Queue refreshes every 3 seconds.</p>{queue.map(run => <div key={run.run_id} className="queue-card"><p className="run-id">{run.run_id}</p><p>{run.idea}</p><div className="queue-actions"><Button variant="outline" onClick={() => setA(run.run_id)}>Use as A</Button><Button variant="outline" onClick={() => setB(run.run_id)}>Use as B</Button></div></div>)}</section>{compare.error && <p role="alert">{compare.error.message}</p>}{compare.data && <DiffResult diff={compare.data} />}</section>;
}

export function CampaignDayCard({ day, busy, approve, download }: { day: Day; busy: boolean; approve: () => void; download: () => void }) {
  return <article className="panel queue-card"><h3>Day {day.day}: {day.angle}</h3><p>{day.brief}</p><p className="run-id">{day.run_id}</p><p className="draft">{day.draft_v2_post ?? ''}</p><p>{day.approval_state} · Status: {day.status} · Final blocked count: {day.checker_v2_blocked_count ?? 'unavailable'}</p><div className="queue-actions">{canApproveDay(day) && <Button onClick={approve} disabled={busy}>Approve for export</Button>}{canExportDay(day) && <Button onClick={download} disabled={busy}>Export pack</Button>}</div></article>;
}

export function CampaignView({ profiles }: { profiles: components['schemas']['Profile'][] }) {
  const client = useQueryClient();
  const [idea, setIdea] = useState(wallet);
  const [agent, setAgent] = useState('Maker');
  const [scout, setScout] = useState('Scout');
  const [checkerAgent, setCheckerAgent] = useState('Checker');
  const [checkerProfile, setCheckerProfile] = useState('standard');
  const [seed, setSeed] = useState(false);
  const [id, setId] = useState('');
  const [notice, setNotice] = useState('');
  const weeks = useQuery({ queryKey: ['campaigns'], queryFn: () => unwrap(api.GET('/api/campaigns')) });
  const campaign = useQuery({ queryKey: ['campaign', id], queryFn: () => unwrap(api.GET('/api/campaigns/{campaign_id}', { params: { path: { campaign_id: id } } })), enabled: !!id, refetchInterval: 3000 });
  const create = useMutation({ mutationFn: () => unwrap(api.POST('/api/campaigns', { body: { idea, agent_name: agent, scout_name: scout, maker_name: agent, checker_name: checkerAgent, seed_unverified_claim: seed, checker_profile: checkerProfile as 'standard' | 'strict', memory_ids: [] } })), onSuccess: week => { setId(week.id); client.invalidateQueries({ queryKey: ['campaigns'] }); client.invalidateQueries({ queryKey: ['queue'] }); } });
  const approve = useMutation({ mutationFn: (input: { day: number; revision: number }) => unwrap(api.POST('/api/campaigns/{campaign_id}/days/{day}/approve', { params: { path: { campaign_id: id, day: input.day } }, body: { expected_revision: input.revision } })), onSuccess: () => { client.invalidateQueries({ queryKey: ['campaign', id] }); client.invalidateQueries({ queryKey: ['queue'] }); } });
  const download = useMutation({ mutationFn: (input: { day: number; revision: number }) => unwrap(api.POST('/api/campaigns/{campaign_id}/days/{day}/export', { params: { path: { campaign_id: id, day: input.day } }, body: { expected_revision: input.revision } })), onSuccess: run => {
    const url = URL.createObjectURL(new Blob([JSON.stringify(run, null, 2)], { type: 'application/json' }));
    const link = document.createElement('a'); link.href = url; link.download = `${run.run_id}.json`; link.click(); URL.revokeObjectURL(url); setNotice(`Export downloaded: ${run.run_id}`);
  } });
  const error = create.error || campaign.error || weeks.error || approve.error || download.error;
  return <section aria-label="Campaign"><section className="panel"><h2>Campaign Week</h2><p>Nothing publishes automatically. Review and approve each day individually.</p><form onSubmit={e => { e.preventDefault(); create.mutate(); }}><label htmlFor="campaign-idea">Idea</label><textarea id="campaign-idea" required maxLength={2000} value={idea} onChange={e => setIdea(e.target.value)} /><label htmlFor="campaign-scout">Scout agent</label><select id="campaign-scout" value={scout} onChange={e => setScout(e.target.value)}>{profiles.map(profile => <option key={profile.name}>{profile.name}</option>)}</select><label htmlFor="campaign-maker">Maker profile</label><select id="campaign-maker" value={agent} onChange={e => setAgent(e.target.value)}>{profiles.map(profile => <option key={profile.name}>{profile.name}</option>)}</select><label htmlFor="campaign-checker-agent">Checker agent</label><select id="campaign-checker-agent" value={checkerAgent} onChange={e => setCheckerAgent(e.target.value)}>{profiles.map(profile => <option key={profile.name}>{profile.name}</option>)}</select><p className="hint">Each agent runs its own stage. Original names and rules are kept in each day receipt.</p><label htmlFor="campaign-checker">Checker profile</label><select id="campaign-checker" value={checkerProfile} onChange={e => setCheckerProfile(e.target.value)}><option>standard</option><option>strict</option></select><p className="hint">Supported Checker policies: veto_scope superlatives or price_claims; decision_rules Block superlatives or Block price claims (exact match). Other rules are advisory only.</p><label className="checkbox"><input type="checkbox" checked={seed} onChange={e => setSeed(e.target.checked)} />Include unsupported claim demo</label><Button type="submit" disabled={create.isPending || !profiles.length}>{create.isPending ? 'Creating week...' : 'Create week'}</Button></form><label htmlFor="campaign-select">Open a campaign</label><select id="campaign-select" value={id} onChange={e => setId(e.target.value)}><option value="">Select a week</option>{weeks.data?.map(week => <option key={week.id} value={week.id}>{week.idea} ({week.id})</option>)}</select></section>{error && <p role="alert">{error.message}</p>}{notice && <p role="status">{notice}</p>}{campaign.isFetching && <p>Refreshing week...</p>}{campaign.data && <section><h2>{campaign.data.idea}</h2><p className="run-id">{campaign.data.id}</p>{campaign.data.days.map(day => <CampaignDayCard key={day.day} day={day} busy={approve.isPending || download.isPending} approve={() => approve.mutate({ day: day.day, revision: day.revision ?? 0 })} download={() => download.mutate({ day: day.day, revision: day.revision ?? 0 })} />)}</section>}</section>;
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
