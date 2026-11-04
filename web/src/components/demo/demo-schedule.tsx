'use client';

import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { CheckCircle2, MinusCircle } from 'lucide-react';
import { DemoButton, demoButtonVariants } from './demo-button';
import { Calendar } from '@/components/ui/calendar';
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
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { api, unwrap } from '@/lib/api';
import { CodeLabel, DeliveryStatusBadge } from './demo-status';

type Slot = {
  id: string;
  slot_date?: string | null;
  slot_type?: string | null;
  run_id?: string | null;
  selected_channels?: string[] | null;
  schedule_state?: string | null;
  status?: string | null;
};

type ReadyCheck = {
  ready_eligible?: boolean;
  failing_conditions?: string[] | null;
  checks?: Record<string, boolean> | null;
  format_reason?: string | null;
};

function monthRange(date: Date): { start: string; end: string } {
  const start = new Date(date.getFullYear(), date.getMonth(), 1);
  const end = new Date(date.getFullYear(), date.getMonth() + 1, 0);
  const iso = (value: Date) => value.toISOString().slice(0, 10);
  return { start: iso(start), end: iso(end) };
}

function ReadyChecklist({ slotId }: { slotId: string }) {
  const check = useQuery({
    queryKey: ['demo-validate-ready', slotId],
    queryFn: () =>
      unwrap(api.GET('/api/calendar/slots/{slot_id}/validate-ready', { params: { path: { slot_id: slotId } } })),
  });
  const data = (check.data ?? {}) as ReadyCheck;
  if (check.isPending) return <Skeleton className="h-6 w-full" />;
  if (check.error) {
    return (
      <p className="text-sm text-muted-foreground">
        Ready check unavailable: {(check.error as Error).message}
      </p>
    );
  }
  const entries = Object.entries(data.checks ?? {});
  return (
    <ul className="space-y-1 text-sm" data-testid={`demo-ready-${slotId}`}>
      {entries.length === 0 && <li className="text-muted-foreground">No checks reported.</li>}
      {entries.map(([key, ok]) => (
        <li key={key} className="flex items-center gap-2">
          {ok ? (
            <CheckCircle2 className="size-4 text-green-700 dark:text-green-300" aria-hidden />
          ) : (
            <MinusCircle className="size-4 text-red-700 dark:text-red-300" aria-hidden />
          )}
          <span>
            <CodeLabel code={key} />: {ok ? 'met' : 'not met'}
          </span>
        </li>
      ))}
      {(data.failing_conditions ?? []).length > 0 && (
        <li className="text-red-700 dark:text-red-300">
          Failing:{' '}
          {(data.failing_conditions ?? []).map(code => (
            <span key={code}>
              <CodeLabel code={code} />;{' '}
            </span>
          ))}
        </li>
      )}
      {data.format_reason && <li className="text-muted-foreground">{data.format_reason}</li>}
    </ul>
  );
}

type Delivery = {
  id: string;
  channel?: string | null;
  delivery_state?: string | null;
  live_url?: string | null;
  match_kind?: string | null;
};

function SlotDeliveries({ slotId }: { slotId: string }) {
  const client = useQueryClient();
  const [postUrl, setPostUrl] = useState('');
  const [dialogChannel, setDialogChannel] = useState('');
  const deliveries = useQuery({
    queryKey: ['demo-deliveries', slotId],
    queryFn: () =>
      unwrap(api.GET('/api/calendar/slots/{slot_id}/deliveries', { params: { path: { slot_id: slotId } } })),
  });
  const markPosted = useMutation({
    mutationFn: (input: { channel: string; liveUrl: string }) =>
      unwrap(
        api.POST('/api/calendar/slots/{slot_id}/deliveries/{channel}/mark-posted', {
          params: { path: { slot_id: slotId, channel: input.channel } },
          body: { live_url: input.liveUrl, verify_now: false },
        }),
      ),
    onSuccess: () => {
      setDialogChannel('');
      setPostUrl('');
      client.invalidateQueries({ queryKey: ['demo-deliveries', slotId] });
    },
  });
  const verify = useMutation({
    mutationFn: (channel: string) =>
      unwrap(
        api.POST('/api/calendar/slots/{slot_id}/deliveries/{channel}/verify', {
          params: { path: { slot_id: slotId, channel } },
          body: {},
        }),
      ),
    onSuccess: () => client.invalidateQueries({ queryKey: ['demo-deliveries', slotId] }),
  });

  const rows = ((deliveries.data ?? []) as Delivery[]) ?? [];
  if (deliveries.isPending) return <Skeleton className="h-6 w-full" />;
  if (rows.length === 0) return <p className="text-sm text-muted-foreground">No deliveries yet.</p>;
  return (
    <ul className="space-y-2 text-sm">
      {rows.map(row => (
        <li key={row.id} className="flex flex-wrap items-center gap-2 rounded-md border p-2">
          <span className="font-medium">{row.channel}</span>
          <DeliveryStatusBadge state={row.delivery_state} />
          {row.live_url ? (
            <a
              href={row.live_url}
              target="_blank"
              rel="noreferrer"
              className="max-w-56 truncate text-sky-700 underline-offset-4 hover:underline dark:text-sky-300"
            >
              Permalink
            </a>
          ) : (
            <span className="text-muted-foreground">No permalink</span>
          )}
          <span className="text-muted-foreground">
            {row.delivery_state === 'verified'
              ? `Verified${row.match_kind ? ` (${row.match_kind})` : ''}`
              : 'Not verified yet'}
          </span>
          <span className="ml-auto flex gap-2">
            <Dialog
              open={dialogChannel === row.channel}
              onOpenChange={open => {
                setDialogChannel(open ? (row.channel ?? '') : '');
                setPostUrl('');
              }}
            >
              <DialogTrigger asChild>
                <DemoButton variant="outline" size="sm">
                  Mark posted
                </DemoButton>
              </DialogTrigger>
              <DialogContent>
                <DialogHeader>
                  <DialogTitle>Mark {row.channel} posted</DialogTitle>
                  <DialogDescription>Paste the live post URL.</DialogDescription>
                </DialogHeader>
                <Input
                  value={postUrl}
                  onChange={event => setPostUrl(event.target.value)}
                  placeholder="https://…"
                  aria-label="Live post URL"
                />
                <DialogFooter>
                  <DemoButton
                    disabled={!postUrl.trim() || markPosted.isPending}
                    onClick={() =>
                      row.channel &&
                      markPosted.mutate({ channel: row.channel, liveUrl: postUrl.trim() })
                    }
                  >
                    {markPosted.isPending ? 'Saving…' : 'Save'}
                  </DemoButton>
                </DialogFooter>
              </DialogContent>
            </Dialog>
            {row.live_url && (
              <DemoButton variant="outline" size="sm" disabled={verify.isPending} onClick={() => row.channel && verify.mutate(row.channel)}>
                {verify.isPending ? 'Verifying…' : 'Verify'}
              </DemoButton>
            )}
          </span>
        </li>
      ))}
      {(markPosted.error || verify.error) && (
        <li role="alert" className="text-sm text-red-700 dark:text-red-300">
          {((markPosted.error ?? verify.error) as Error).message}
        </li>
      )}
    </ul>
  );
}

function SlotCard({ slot }: { slot: Slot }) {
  const client = useQueryClient();
  const markReady = useMutation({
    mutationFn: () =>
      unwrap(api.POST('/api/calendar/slots/{slot_id}/mark-ready', { params: { path: { slot_id: slot.id } } })),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ['demo-slots'] });
      client.invalidateQueries({ queryKey: ['demo-validate-ready', slot.id] });
    },
  });
  return (
    <Card data-testid={`demo-slot-${slot.id}`}>
      <CardHeader>
        <CardTitle className="text-base">
          {slot.slot_date}, {slot.slot_type}
        </CardTitle>
        <CardDescription>
          Channels: {(slot.selected_channels ?? []).join(', ') || 'none selected'}
          {slot.run_id ? `, run ${slot.run_id.slice(0, 12)}…` : ', no linked run'}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <ReadyChecklist slotId={slot.id} />
        <SlotDeliveries slotId={slot.id} />
        <div className="flex flex-wrap items-center gap-2">
          <DemoButton size="sm" disabled={markReady.isPending} onClick={() => markReady.mutate()}>
            {markReady.isPending ? 'Marking…' : 'Mark ready'}
          </DemoButton>
          {markReady.error && (
            <span role="alert" className="text-sm text-red-700 dark:text-red-300">
              {(markReady.error as Error).message}
            </span>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

const CHANNEL_CHOICES = ['instagram', 'x', 'linkedin', 'facebook', 'email'];

function CreateSlotForm({ runs }: { runs: { run_id: string; idea?: string | null }[] }) {
  const client = useQueryClient();
  const [date, setDate] = useState('');
  const [runId, setRunId] = useState('');
  const [slotType, setSlotType] = useState<'feed_post' | 'story' | 'reel'>('feed_post');
  const [channels, setChannels] = useState<string[]>(['instagram']);
  const create = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST('/api/calendar/slots', {
          body: {
            slot_date: date,
            slot_type: slotType,
            pillar: 'product',
            format: slotType,
            ...(runId ? { run_id: runId } : {}),
          },
        }),
      ),
    onSuccess: () => {
      setDate('');
      client.invalidateQueries({ queryKey: ['demo-slots'] });
    },
  });
  const toggleChannel = (channel: string) =>
    setChannels(prev => (prev.includes(channel) ? prev.filter(item => item !== channel) : [...prev, channel]));
  return (
    <Card>
      <CardHeader>
        <CardTitle>New slot</CardTitle>
        <CardDescription>Ready slots publish automatically at their time.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid gap-3 sm:grid-cols-3">
          <div className="space-y-1">
            <Label htmlFor="demo-slot-date">Date</Label>
            <Input id="demo-slot-date" type="date" value={date} onChange={event => setDate(event.target.value)} />
          </div>
          <div className="space-y-1">
            <Label htmlFor="demo-slot-run">Launch</Label>
            <Select value={runId} onValueChange={setRunId}>
              <SelectTrigger id="demo-slot-run">
                <SelectValue placeholder="No linked launch" />
              </SelectTrigger>
              <SelectContent>
                {runs.map(run => (
                  <SelectItem key={run.run_id} value={run.run_id}>
                    {(run.idea || run.run_id).slice(0, 40)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1">
            <Label htmlFor="demo-slot-type">Type</Label>
            <Select value={slotType} onValueChange={value => setSlotType(value as 'feed_post' | 'story' | 'reel')}>
              <SelectTrigger id="demo-slot-type">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="feed_post">Feed post</SelectItem>
                <SelectItem value="story">Story</SelectItem>
                <SelectItem value="reel">Reel</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>
        <fieldset className="space-y-1">
          <legend className="text-sm font-medium">Channels</legend>
          <div className="flex flex-wrap gap-3">
            {CHANNEL_CHOICES.map(channel => (
              <label key={channel} className="flex items-center gap-1 text-sm">
                <input
                  type="checkbox"
                  checked={channels.includes(channel)}
                  onChange={() => toggleChannel(channel)}
                />
                {channel}
              </label>
            ))}
          </div>
        </fieldset>
        <DemoButton disabled={!date || create.isPending} onClick={() => create.mutate()} data-testid="demo-create-slot">
          {create.isPending ? 'Creating…' : 'Create slot'}
        </DemoButton>
        {create.error && (
          <p role="alert" className="text-sm text-red-700 dark:text-red-300">
            {(create.error as Error).message}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

export function ScheduleWorkspace() {
  const [month, setMonth] = useState<Date>(new Date());
  const range = monthRange(month);
  const queue = useQuery({
    queryKey: ['demo-queue'],
    queryFn: () => unwrap(api.GET('/api/queue')),
  });
  const slots = useQuery({
    queryKey: ['demo-slots', range.start, range.end],
    queryFn: () =>
      unwrap(
        api.GET('/api/calendar/slots', {
          params: { query: { start_date: range.start, end_date: range.end } },
        }),
      ),
  });
  const list = ((slots.data ?? []) as Slot[]) ?? [];
  const runs = ((queue.data ?? []) as { run_id: string; idea?: string | null }[]) ?? [];
  const marked = new Set(list.filter(slot => slot.slot_date).map(slot => slot.slot_date as string));

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Schedule</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Ready slots publish automatically at their time.
        </p>
      </div>
      <div className="grid gap-6 md:grid-cols-[auto_1fr]">
        <Calendar
          mode="single"
          month={month}
          onMonthChange={setMonth}
          modifiers={{ hasSlot: day => marked.has(day.toISOString().slice(0, 10)) }}
          modifiersClassNames={{ hasSlot: 'font-bold underline' }}
          aria-label="Schedule month"
        />
        <div className="space-y-4">
          {slots.isPending && <Skeleton className="h-32 w-full" />}
          {slots.error && (
            <p role="alert" className="text-sm text-red-700 dark:text-red-300">
              {(slots.error as Error).message}
            </p>
          )}
          {list.length === 0 && !slots.isPending && (
            <p className="text-sm text-muted-foreground">No slots this month.</p>
          )}
          {list.map(slot => (
            <SlotCard key={slot.id} slot={slot} />
          ))}
        </div>
      </div>
      <CreateSlotForm runs={runs} />
    </div>
  );
}
