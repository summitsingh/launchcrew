'use client';

import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { CheckCircle2, MinusCircle } from 'lucide-react';
import { DemoButton, demoButtonVariants } from './demo-button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from '@/components/ui/sheet';
import { Skeleton } from '@/components/ui/skeleton';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Textarea } from '@/components/ui/textarea';
import { currentCheckOf, currentDraftOf, describeStageProgress, revisionStatusOf } from '@/components/v2-views';
import { api, unwrap } from '@/lib/api';
import { ClaimStatusBadge, CodeLabel, RunStatusBadge } from './demo-status';

type ReceiptLike = Record<string, unknown>;

function useReceipt(runId: string) {
  return useQuery({
    queryKey: ['demo-receipt', runId],
    queryFn: () => unwrap(api.GET('/api/runs/{run_id}', { params: { path: { run_id: runId } } })),
    refetchInterval: query => {
      const data = query.state.data as unknown as { status?: string } | undefined;
      return data && (data.status === 'completed' || data.status === 'failed') ? false : 2500;
    },
  });
}

function useSteps(runId: string, live: boolean) {
  return useQuery({
    queryKey: ['demo-steps', runId],
    queryFn: () =>
      unwrap(api.GET('/api/runs/{run_id}/steps', { params: { path: { run_id: runId } } })),
    refetchInterval: live ? 2000 : false,
  });
}

type StepRow = { stage: string; state: string; profile?: string; observed_at?: string | null };

function RunStepList({ runId, terminal }: { runId: string; terminal: boolean }) {
  const steps = useSteps(runId, !terminal);
  const list = (steps.data as unknown as { steps?: StepRow[] } | undefined)?.steps ?? [];
  const stages = describeStageProgress(
    list.map(item => ({
      stage: item.stage,
      state: item.state,
      observed_at: item.observed_at,
      profile: item.profile,
    })),
  );
  if (steps.isPending) return <Skeleton className="h-8 w-full" />;
  return (
    <ol className="space-y-1 text-sm" data-testid="demo-step-list">
      {stages.map(stage => (
        <li key={stage.stage} className="flex flex-wrap items-center gap-2">
          {stage.state === 'completed' ? (
            <CheckCircle2 className="size-4 text-green-700 dark:text-green-300" aria-hidden />
          ) : (
            <MinusCircle className="size-4 text-muted-foreground" aria-hidden />
          )}
          <span>{stage.label}</span>
          <span className="text-muted-foreground">
            {stage.state}, {stage.profile && /spark/i.test(stage.profile) ? 'Muse Spark' : 'Deterministic'}
          </span>
        </li>
      ))}
    </ol>
  );
}

type ClaimEntry = {
  claim: string;
  verdict?: string | null;
  reason?: string | null;
  evidence?: string | null;
  source?: string | null;
  blocked?: boolean | null;
  verified?: boolean | null;
};

function blockedClaims(receipt: ReceiptLike): ClaimEntry[] {
  const record = receipt as unknown as {
    checker_v1?: { claim_results?: ClaimEntry[] } | null;
    checker_v2?: { claim_results?: ClaimEntry[] } | null;
    human_check?: { claim_results?: ClaimEntry[] } | null;
  };
  const seen = new Map<string, ClaimEntry>();
  for (const check of [record.checker_v1, record.checker_v2, record.human_check]) {
    for (const entry of check?.claim_results ?? []) {
      if (entry.blocked && !seen.has(entry.claim)) seen.set(entry.claim, entry);
    }
  }
  return [...seen.values()];
}

/** Draft text with verbatim blocked claims struck through. Only exact
 *  case-insensitive matches strike; everything else lists below. */
function StruckDraft({ text, blocked }: { text: string; blocked: ClaimEntry[] }) {
  const spans: { text: string; struck: boolean }[] = [{ text, struck: false }];
  for (const entry of blocked) {
    const needle = entry.claim.trim();
    if (!needle) continue;
    for (let i = 0; i < spans.length; i++) {
      if (spans[i].struck) continue;
      const index = spans[i].text.toLowerCase().indexOf(needle.toLowerCase());
      if (index === -1) continue;
      const before = spans[i].text.slice(0, index);
      const match = spans[i].text.slice(index, index + needle.length);
      const after = spans[i].text.slice(index + needle.length);
      const replacement: typeof spans = [];
      if (before) replacement.push({ text: before, struck: false });
      replacement.push({ text: match, struck: true });
      if (after) replacement.push({ text: after, struck: false });
      spans.splice(i, 1, ...replacement);
      break;
    }
  }
  return (
    <>
      {spans.map((span, index) =>
        span.struck ? <s key={index}>{span.text}</s> : <span key={index}>{span.text}</span>,
      )}
    </>
  );
}

function DraftTab({ runId, receipt }: { runId: string; receipt: ReceiptLike }) {
  const client = useQueryClient();
  const base = currentDraftOf(receipt as never);
  const blocked = blockedClaims(receipt);
  const status = revisionStatusOf(receipt as never);
  const failed = (receipt.status as string) === 'failed';
  const editedAfterApproval = status === 'pending fresh approval';

  const [post, setPost] = useState(base.post);
  const [email, setEmail] = useState(base.email);
  const [confirmOpen, setConfirmOpen] = useState(false);
  useEffect(() => {
    setPost(base.post);
    setEmail(base.email);
  }, [runId, base.revision, base.post, base.email]);
  const dirty = post !== base.post || email !== base.email;

  const revise = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST('/api/runs/{run_id}/revise', {
          params: { path: { run_id: runId } },
          body: { post, email, base_revision: base.revision },
        }),
      ),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ['demo-receipt', runId] });
      client.invalidateQueries({ queryKey: ['demo-queue'] });
    },
  });

  const approve = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST('/api/runs/{run_id}/approve', {
          params: { path: { run_id: runId } },
          body: { expected_revision: base.revision },
        }),
      ),
    onSuccess: () => {
      setConfirmOpen(false);
      client.invalidateQueries({ queryKey: ['demo-receipt', runId] });
      client.invalidateQueries({ queryKey: ['demo-queue'] });
    },
  });

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>Post draft</CardTitle>
          <CardDescription>
            Revision {base.revision} ({base.human ? 'human revision' : 'Maker draft'})
          </CardDescription>
        </CardHeader>
        <CardContent>
          <p className="whitespace-pre-wrap text-sm" data-testid="demo-post-draft">
            <StruckDraft text={base.post || 'No post draft yet.'} blocked={blocked} />
          </p>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Email draft</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="whitespace-pre-wrap text-sm" data-testid="demo-email-draft">
            <StruckDraft text={base.email || 'No email draft yet.'} blocked={blocked} />
          </p>
        </CardContent>
      </Card>
      {blocked.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Blocked sentences</CardTitle>
            <CardDescription>Each failed against the fact shown beside it.</CardDescription>
          </CardHeader>
          <CardContent>
            <ul className="space-y-2 text-sm">
              {blocked.map((entry, index) => (
                <li key={index} className="rounded-md border p-3">
                  <p>
                    <s>{entry.claim}</s>
                  </p>
                  <p className="mt-1 text-muted-foreground">Reason: {entry.reason || 'unsupported'}</p>
                  <p className="text-muted-foreground">
                    Failed against: {entry.evidence || entry.source || 'recorded evidence'}
                  </p>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}
      {editedAfterApproval && (
        <p role="status" className="text-sm text-amber-800 dark:text-amber-200" data-testid="demo-edited-after-approval">
          Edited after approval. Approval cleared. Rechecking.
        </p>
      )}
      {!failed && (
        <Card>
          <CardHeader>
            <CardTitle>Edit drafts</CardTitle>
            <CardDescription>
              Saving runs the deterministic recheck and clears the prior approval.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="space-y-1">
              <Label htmlFor="demo-edit-post">Post text</Label>
              <Textarea
                id="demo-edit-post"
                rows={4}
                value={post}
                onChange={event => setPost(event.target.value)}
                disabled={revise.isPending}
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="demo-edit-email">Email text</Label>
              <Textarea
                id="demo-edit-email"
                rows={4}
                value={email}
                onChange={event => setEmail(event.target.value)}
                disabled={revise.isPending}
              />
            </div>
            <div className="flex flex-wrap gap-2">
              <DemoButton
                variant="outline"
                disabled={revise.isPending || !dirty || !post.trim() || !email.trim()}
                onClick={() => revise.mutate()}
                data-testid="demo-save-revision"
              >
                {revise.isPending ? 'Rechecking…' : 'Save revision'}
              </DemoButton>
              <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
                <DialogTrigger asChild>
                  <DemoButton disabled={dirty} data-testid="demo-approve-open">
                    Approve
                  </DemoButton>
                </DialogTrigger>
                <DialogContent>
                  <DialogHeader>
                    <DialogTitle>Approve this exact text?</DialogTitle>
                    <DialogDescription>
                      Approval binds revision {base.revision}. Nothing publishes without this approval.
                    </DialogDescription>
                  </DialogHeader>
                  <div className="max-h-64 space-y-3 overflow-y-auto text-sm">
                    <div>
                      <p className="font-medium">Post</p>
                      <p className="whitespace-pre-wrap" data-testid="demo-approve-post">
                        {base.post}
                      </p>
                    </div>
                    <div>
                      <p className="font-medium">Email</p>
                      <p className="whitespace-pre-wrap" data-testid="demo-approve-email">
                        {base.email}
                      </p>
                    </div>
                  </div>
                  <DialogFooter>
                    <DemoButton variant="outline" onClick={() => setConfirmOpen(false)}>
                      Cancel
                    </DemoButton>
                    <DemoButton
                      onClick={() => approve.mutate()}
                      disabled={approve.isPending}
                      data-testid="demo-approve-confirm"
                    >
                      {approve.isPending ? 'Approving…' : 'Approve exact text'}
                    </DemoButton>
                  </DialogFooter>
                </DialogContent>
              </Dialog>
            </div>
            {revise.error && (
              <p role="alert" className="text-sm text-red-700 dark:text-red-300">
                {(revise.error as Error).message}
              </p>
            )}
            {approve.error && (
              <p role="alert" className="text-sm text-red-700 dark:text-red-300">
                {(approve.error as Error).message}
              </p>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function ChecksTab({ receipt }: { receipt: ReceiptLike }) {
  const checks = [receipt.checker_v1, receipt.checker_v2, receipt.human_check].filter(
    (check): check is { claim_results?: ClaimEntry[] } => !!check,
  );
  const seen = new Map<string, ClaimEntry>();
  for (const check of checks) {
    for (const entry of check.claim_results ?? []) {
      if (!seen.has(entry.claim)) seen.set(entry.claim, entry);
    }
  }
  const results = [...seen.values()];
  if (results.length === 0) {
    return <p className="text-sm text-muted-foreground">No claim results recorded yet.</p>;
  }
  return (
    <ul className="space-y-2" data-testid="demo-checks-list">
      {results.map((entry, index) => (
        <li key={index} className="flex flex-wrap items-start gap-2 rounded-md border p-3 text-sm">
          <ClaimStatusBadge entry={entry} />
          <div className="min-w-40 flex-1">
            <p>{entry.claim}</p>
            {entry.reason && <p className="text-muted-foreground">Reason: {entry.reason}</p>}
            {(entry.evidence || entry.source) && (
              <p className="text-muted-foreground">
                Evidence: {entry.evidence || entry.source}
              </p>
            )}
          </div>
        </li>
      ))}
    </ul>
  );
}

function humanTime(value: unknown): string {
  if (typeof value !== 'string' || !value) return 'Unknown time';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function ReceiptTab({ receipt }: { receipt: ReceiptLike }) {
  const [digestCopied, setDigestCopied] = useState(false);
  const check = currentCheckOf(receipt as never) as unknown as {
    verified_count?: number | null;
    blocked_count?: number | null;
  } | null;
  const usage = (receipt.model_usage ?? null) as unknown as {
    model_used?: string;
    spark_calls?: number;
    mode?: string;
  } | null;
  const approvals = (Array.isArray(receipt.approvals) ? receipt.approvals : []) as {
    approved_by?: string;
    timestamp?: string;
    revision?: number | null;
  }[];
  const approver = approvals[0];
  const binding = (receipt.approval_binding ?? null) as { digest?: string; version?: string } | null;
  useEffect(() => {
    setDigestCopied(false);
  }, [binding?.digest]);
  const scout = (receipt.scout ?? null) as {
    facts_used?: { claim?: string; source?: string }[];
  } | null;
  const events = (receipt.audit as { event_log?: { action?: string; at?: string }[] } | null)?.event_log ?? [];

  return (
    <div className="space-y-4">
      <Card data-testid="demo-receipt-card">
        <CardHeader>
          <CardTitle>Receipt summary</CardTitle>
          <CardDescription>
            Run {(receipt.run_id as string) ?? ''}, revision{' '}
            {(receipt.revision as number | undefined) ?? 0}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            Status: <RunStatusBadge receipt={receipt as never} />
          </div>
          <p>
            Verdicts: {check?.verified_count ?? 'unknown'} backed by a fact,{' '}
            {check?.blocked_count ?? 'unknown'} blocked
          </p>
          <p>
            Model: {usage?.model_used || 'none'}, {usage?.spark_calls ?? 0} live calls,{' '}
            <CodeLabel code={usage?.mode} />
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <p className="m-0">
              Bound version: {binding?.version || 'unbound'}
              {binding?.digest && (
                <span className="font-mono">, {binding.digest.slice(0, 12)}…</span>
              )}
            </p>
            {binding?.digest && (
              <DemoButton
                variant="outline"
                size="sm"
                onClick={() => {
                  void navigator.clipboard
                    .writeText(binding.digest as string)
                    .then(
                      () => setDigestCopied(true),
                      () => setDigestCopied(false),
                    );
                }}
              >
                {digestCopied ? 'Copied' : 'Copy full digest'}
              </DemoButton>
            )}
          </div>
          <p>
            Approved by: {approver?.approved_by || 'awaiting approval'}
            {approver?.timestamp ? `, ${humanTime(approver.timestamp)}` : ''}
          </p>
          {scout?.facts_used && scout.facts_used.length > 0 && (
            <div>
              <p className="font-medium">Facts with sources</p>
              <ul className="list-disc pl-5 text-muted-foreground">
                {scout.facts_used.map((fact, index) => (
                  <li key={index}>
                    {fact.claim || 'fact'} (source: {fact.source || 'unknown'})
                  </li>
                ))}
              </ul>
            </div>
          )}
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Timeline</CardTitle>
        </CardHeader>
        <CardContent>
          {events.length === 0 ? (
            <p className="text-sm text-muted-foreground">No audit events recorded.</p>
          ) : (
            <ol className="space-y-1 text-sm">
              {events.map((event, index) => (
                <li key={index}>
                  {humanTime(event.at)}, <CodeLabel code={event.action} />
                </li>
              ))}
            </ol>
          )}
        </CardContent>
      </Card>
      <Sheet>
        <SheetTrigger asChild>
          <DemoButton variant="outline" data-testid="demo-raw-json">
            Raw JSON
          </DemoButton>
        </SheetTrigger>
        <SheetContent className="w-full overflow-y-auto sm:max-w-xl">
          <SheetHeader>
            <SheetTitle>Raw receipt JSON</SheetTitle>
          </SheetHeader>
          <pre className="mt-4 overflow-x-auto rounded-md bg-muted p-3 font-mono text-xs">
            {JSON.stringify(receipt, null, 2)}
          </pre>
        </SheetContent>
      </Sheet>
    </div>
  );
}

export function ReviewWorkspace({ runId }: { runId: string }) {
  const receipt = useReceipt(runId);
  if (receipt.isPending) {
    return (
      <div className="space-y-2">
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }
  if (receipt.error || !receipt.data) {
    return (
      <p role="alert" className="text-sm text-red-700 dark:text-red-300">
        Could not load run {runId}
        {receipt.error ? `: ${(receipt.error as Error).message}` : '.'}
      </p>
    );
  }
  const record = receipt.data as unknown as ReceiptLike;
  const terminal =
    (record.status as string) === 'completed' || (record.status as string) === 'failed';

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Review</h1>
        <div className="mt-1 flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
          <RunStatusBadge receipt={record as never} />
          <span className="font-mono">{runId}</span>
        </div>
      </div>
      {!terminal && (
        <Card>
          <CardHeader>
            <CardTitle>Run in progress</CardTitle>
            <CardDescription>Stages appear as the pipeline stores them.</CardDescription>
          </CardHeader>
          <CardContent>
            <RunStepList runId={runId} terminal={false} />
          </CardContent>
        </Card>
      )}
      <Tabs defaultValue="draft" data-testid="demo-review-tabs">
        <TabsList>
          <TabsTrigger value="draft">Draft</TabsTrigger>
          <TabsTrigger value="checks">Checks</TabsTrigger>
          <TabsTrigger value="receipt">Receipt</TabsTrigger>
        </TabsList>
        <TabsContent value="draft" className="pt-4">
          <DraftTab runId={runId} receipt={record} />
        </TabsContent>
        <TabsContent value="checks" className="pt-4">
          <ChecksTab receipt={record} />
        </TabsContent>
        <TabsContent value="receipt" className="pt-4">
          <ReceiptTab receipt={record} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
