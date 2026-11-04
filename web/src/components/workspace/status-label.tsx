import { Ban, CalendarClock, Check, CircleAlert, CircleCheck, CircleHelp, FileText, LoaderCircle, Send, ShieldCheck, XCircle } from 'lucide-react';
import type { StatusDefinition } from '@/lib/ui-status';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';

const icons = { draft: FileText, checking: LoaderCircle, review: CircleAlert, approved: Check, scheduled: CalendarClock, published: Send, verified: ShieldCheck, failed: XCircle, blocked: Ban, info: CircleHelp };

export function StatusLabel({ status, code }: { status: StatusDefinition; code?: string }) {
  const Icon = icons[status.icon] ?? CircleCheck;
  return <Tooltip><TooltipTrigger asChild><span tabIndex={0} className="workspace-status" data-tone={status.tone}><Icon aria-hidden="true" size={14} /><span>{status.label}</span></span></TooltipTrigger><TooltipContent><p>{status.description}</p>{code && <p>Recorded code: <code>{code}</code></p>}</TooltipContent></Tooltip>;
}
