'use client';

import { AlertTriangle, CheckCircle2, Clock, MinusCircle, OctagonX } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import {
  claimStatusLabel,
  codeLabel,
  deliveryStatusLabel,
  runStatusLabel,
  type ClaimStatusLabel,
  type RunStatusLabel,
} from '@/lib/status-labels';
import { cn } from '@/lib/utils';

const STATUS_ICON: Record<RunStatusLabel, typeof Clock> = {
  Draft: Clock,
  Checking: Clock,
  'Needs review': AlertTriangle,
  Approved: CheckCircle2,
  Scheduled: Clock,
  Published: CheckCircle2,
  Verified: CheckCircle2,
};

const STATUS_CLASS: Record<RunStatusLabel, string> = {
  Draft: 'bg-muted text-muted-foreground',
  Checking: 'bg-muted text-muted-foreground',
  'Needs review': 'bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200',
  Approved: 'bg-green-100 text-green-900 dark:bg-green-950 dark:text-green-200',
  Scheduled: 'bg-sky-100 text-sky-900 dark:bg-sky-950 dark:text-sky-200',
  Published: 'bg-green-100 text-green-900 dark:bg-green-950 dark:text-green-200',
  Verified: 'bg-green-100 text-green-900 dark:bg-green-950 dark:text-green-200',
};

/** Single-vocabulary status badge with icon and label. */
export function DemoStatusBadge({ status }: { status: RunStatusLabel }) {
  const Icon = STATUS_ICON[status] ?? MinusCircle;
  return (
    <Badge className={cn('gap-1 font-medium', STATUS_CLASS[status] ?? '')} data-testid="demo-status">
      <Icon className="size-3.5" aria-hidden />
      {status}
    </Badge>
  );
}

/** Badge for a run receipt. */
export function RunStatusBadge({ receipt }: { receipt: Parameters<typeof runStatusLabel>[0] }) {
  return <DemoStatusBadge status={runStatusLabel(receipt)} />;
}

/** Badge for a delivery or execution state. */
export function DeliveryStatusBadge({ state }: { state: string | null | undefined }) {
  return <DemoStatusBadge status={deliveryStatusLabel(state)} />;
}

const CLAIM_ICON: Record<ClaimStatusLabel, typeof CheckCircle2> = {
  'Backed by a fact': CheckCircle2,
  'Needs a fix': AlertTriangle,
  Blocked: OctagonX,
};

const CLAIM_CLASS: Record<ClaimStatusLabel, string> = {
  'Backed by a fact': 'bg-green-100 text-green-900 dark:bg-green-950 dark:text-green-200',
  'Needs a fix': 'bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200',
  Blocked: 'bg-red-100 text-red-900 dark:bg-red-950 dark:text-red-200',
};

/** Badge for one claim check result, always icon plus label. */
export function ClaimStatusBadge({ entry }: { entry: Parameters<typeof claimStatusLabel>[0] }) {
  const status = claimStatusLabel(entry);
  const Icon = CLAIM_ICON[status];
  return (
    <Badge className={cn('gap-1 font-medium', CLAIM_CLASS[status])}>
      <Icon className="size-3.5" aria-hidden />
      {status}
    </Badge>
  );
}

/** Plain label for a raw backend code. */
export function CodeLabel({ code }: { code: string | null | undefined }) {
  return <>{codeLabel(code)}</>;
}
