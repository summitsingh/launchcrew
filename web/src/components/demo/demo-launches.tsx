'use client';

import Link from 'next/link';
import { useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Plus } from 'lucide-react';
import { DemoButton, demoButtonVariants } from './demo-button';
import { cn } from '@/lib/utils';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { api, unwrap } from '@/lib/api';
import { CLASSIC_PATH } from '@/lib/demo-flag';
import { SUMMIT_LEATHER_FACTS } from '@/lib/summit-leather-facts';
import { RunStatusBadge } from './demo-status';

const ARCHIVE_KEY = 'demo-archived-runs';

function readArchived(): string[] {
  try {
    const raw = localStorage.getItem(ARCHIVE_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed.filter(item => typeof item === 'string') : [];
  } catch {
    return [];
  }
}

type QueueReceipt = {
  run_id: string;
  idea?: string | null;
  approval_state?: string | null;
  status?: string | null;
};

type CalendarSlot = {
  id: string;
  run_id?: string | null;
  slot_date?: string | null;
};

function nextScheduledByRun(slots: CalendarSlot[]): Map<string, string> {
  const next = new Map<string, string>();
  for (const slot of slots) {
    if (!slot.run_id || !slot.slot_date) continue;
    const current = next.get(slot.run_id);
    if (!current || slot.slot_date < current) next.set(slot.run_id, slot.slot_date);
  }
  return next;
}

function ExampleReceiptCard() {
  return (
    <Card data-testid="demo-example-receipt">
      <CardHeader>
        <CardTitle>Example receipt</CardTitle>
        <CardDescription>
          Sample layout with Summit Leather Co. facts. Open a real launch below for live data.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-2 text-sm">
        <div className="flex flex-wrap items-center gap-2">
          Status: <RunStatusBadge receipt={{ approval_state: 'approved_for_export' }} />
        </div>
        <p>Model: Muse Spark, 3 live calls</p>
        <p>Claims backed by a fact: {SUMMIT_LEATHER_FACTS.length}</p>
        <ul className="list-disc pl-5 text-muted-foreground">
          {SUMMIT_LEATHER_FACTS.slice(0, 3).map(fact => (
            <li key={fact.claim}>
              {fact.claim} (source: {fact.source})
            </li>
          ))}
        </ul>
        <p className="text-muted-foreground">Approved by the owner</p>
      </CardContent>
    </Card>
  );
}

function LaunchesTable() {
  const [showArchived, setShowArchived] = useState(false);
  const [archived, setArchived] = useState<string[]>([]);
  useEffect(() => {
    setArchived(readArchived());
  }, []);
  const toggleArchive = (runId: string) => {
    setArchived(prev => {
      const next = prev.includes(runId) ? prev.filter(id => id !== runId) : [...prev, runId];
      try {
        localStorage.setItem(ARCHIVE_KEY, JSON.stringify(next));
      } catch {
        /* storage unavailable; keep in-memory state only */
      }
      return next;
    });
  };

  const queue = useQuery({
    queryKey: ['demo-queue'],
    queryFn: () => unwrap(api.GET('/api/queue')),
  });
  const slots = useQuery({
    queryKey: ['demo-slots-range'],
    queryFn: () =>
      unwrap(
        api.GET('/api/calendar/slots', {
          params: { query: { start_date: '2026-01-01', end_date: '2027-12-31' } },
        }),
      ),
  });

  const runs = useMemo(
    () => ((queue.data ?? []) as QueueReceipt[]).filter(run => showArchived || !archived.includes(run.run_id)),
    [queue, archived, showArchived],
  );
  const archivedCount = useMemo(
    () => ((queue.data ?? []) as QueueReceipt[]).filter(run => archived.includes(run.run_id)).length,
    [queue, archived],
  );
  const nextByRun = useMemo(
    () => nextScheduledByRun(((slots.data ?? []) as CalendarSlot[]) ?? []),
    [slots],
  );

  if (queue.isPending) {
    return (
      <div className="space-y-2" data-testid="demo-launches-loading">
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-10 w-full" />
      </div>
    );
  }
  if (queue.error) {
    return (
      <p role="alert" className="text-sm text-red-700 dark:text-red-300">
        Could not load launches: {(queue.error as Error).message}
      </p>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-sm text-muted-foreground" data-testid="demo-launch-count">
          {runs.length} {runs.length === 1 ? 'launch' : 'launches'}
          {archivedCount > 0 && !showArchived ? ` (${archivedCount} archived)` : ''}
        </p>
        {archivedCount > 0 && (
          <DemoButton variant="outline" size="sm" onClick={() => setShowArchived(value => !value)}>
            {showArchived ? 'Hide archived' : `Show archived (${archivedCount})`}
          </DemoButton>
        )}
        <Link href="/meta-ai-hackathon-demo/launch" className={cn(demoButtonVariants(), 'ml-auto')}>
          <Plus className="size-4" aria-hidden /> New launch
        </Link>
      </div>
      {runs.length === 0 ? (
        <Card>
          <CardContent className="py-8 text-center text-sm text-muted-foreground">
            No launches yet. Start with New launch.
          </CardContent>
        </Card>
      ) : (
        <div className="overflow-x-auto">
        <Table data-testid="demo-launches-table">
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Next scheduled</TableHead>
              <TableHead>
                <span className="sr-only">Actions</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {runs.map(run => (
              <TableRow key={run.run_id} data-testid={`demo-launch-${run.run_id}`}>
                <TableCell className="max-w-xs truncate font-medium">
                  <Link
                    href={`/meta-ai-hackathon-demo/review/${run.run_id}`}
                    className="underline-offset-4 hover:underline"
                  >
                    {run.idea || run.run_id}
                  </Link>
                </TableCell>
                <TableCell>
                  <RunStatusBadge receipt={run} />
                </TableCell>
                <TableCell>{nextByRun.get(run.run_id) ?? 'Unscheduled'}</TableCell>
                <TableCell className="text-right">
                  <div className="flex justify-end gap-2">
                    <Link
                      href={`/meta-ai-hackathon-demo/review/${run.run_id}`}
                      className={demoButtonVariants({ variant: 'outline', size: 'sm' })}
                    >
                      Open review
                    </Link>
                    <DemoButton
                      variant="ghost"
                      size="sm"
                      onClick={() => toggleArchive(run.run_id)}
                      aria-label={archived.includes(run.run_id) ? 'Unarchive launch' : 'Archive launch'}
                    >
                      {archived.includes(run.run_id) ? 'Unarchive' : 'Archive'}
                    </DemoButton>
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        </div>
      )}
    </div>
  );
}

export function LaunchesHome() {
  const auth = useQuery({
    queryKey: ['demo-auth-status'],
    queryFn: () => unwrap(api.GET('/api/auth/status')),
    staleTime: 30000,
  });
  const data = (auth.data ?? {}) as { enabled?: boolean; user?: string | null };
  const resolved = auth.isSuccess || auth.isError;
  const signedOut = resolved && !data.user;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Launches</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Every launch, its status, and its next scheduled post.
        </p>
      </div>
      {signedOut && (
        <Card data-testid="demo-signed-out">
          <CardHeader>
            <CardTitle>Try the demo, no sign-in needed</CardTitle>
            <CardDescription>
              LaunchCrew drafts launch content, checks every claim against facts you confirm, and
              only publishes what you approve. Nothing posts on its own.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-wrap gap-2">
            <Link href="/meta-ai-hackathon-demo/launch" className={demoButtonVariants()}>
              Start a launch
            </Link>
            {data.enabled && (
              <Link href={CLASSIC_PATH} className={demoButtonVariants({ variant: 'outline' })}>
                Owner sign-in
              </Link>
            )}
          </CardContent>
        </Card>
      )}
      <LaunchesTable />
      {signedOut && <ExampleReceiptCard />}
    </div>
  );
}
