'use client';

import Link from 'next/link';
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { DemoButton, demoButtonVariants } from './demo-button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { Skeleton } from '@/components/ui/skeleton';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { api, unwrap } from '@/lib/api';
import { CLASSIC_PATH } from '@/lib/demo-flag';

type Connection = {
  platform?: string | null;
  account_handle?: string | null;
  account_name?: string | null;
  status?: string | null;
  token_present?: boolean;
  has_token?: boolean;
  token_security?: string | null;
  connect_url?: string | null;
};

function connectionLabel(connection: Connection): string {
  return (
    connection.account_handle || connection.account_name || connection.platform || 'connection'
  );
}

function isConnected(connection: Connection): boolean {
  return !!(connection.token_present || connection.has_token);
}

function ConnectionsSection() {
  const client = useQueryClient();
  const [connectInfo, setConnectInfo] = useState('');
  const connections = useQuery({
    queryKey: ['demo-connections'],
    queryFn: () => unwrap(api.GET('/api/social/connections')),
  });
  const connect = useMutation({
    mutationFn: (platform: string) =>
      unwrap(
        api.POST('/api/social/connections/{platform}/connect', {
          params: { path: { platform } },
          body: { account_type: 'brand' },
        }),
      ),
    onSuccess: data => {
      const record = data as unknown as { authorize_url?: string; platform?: string };
      setConnectInfo(
        record.authorize_url
          ? `Opened for ${record.platform}.`
          : `Connect started for ${record.platform ?? 'platform'}.`,
      );
      if (record.authorize_url) window.open(record.authorize_url, '_blank', 'noopener');
      client.invalidateQueries({ queryKey: ['demo-connections'] });
    },
    onError: (error: Error) => setConnectInfo(error.message),
  });
  const disconnect = useMutation({
    mutationFn: (platform: string) =>
      unwrap(
        api.POST('/api/social/connections/{platform}/disconnect', {
          params: { path: { platform } },
        }),
      ),
    onSuccess: () => client.invalidateQueries({ queryKey: ['demo-connections'] }),
    onError: (error: Error) => setConnectInfo(error.message),
  });

  const list = ((connections.data ?? []) as Connection[]) ?? [];
  const connected = list.filter(isConnected);
  const unconnected = list.filter(item => !isConnected(item));

  return (
    <Card>
      <CardHeader>
        <CardTitle>Connections</CardTitle>
        <CardDescription>Connected platforms first. Only brand accounts connect.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {connections.isPending && <Skeleton className="h-8 w-full" />}
        {connections.error && (
          <p role="alert" className="text-sm text-red-700 dark:text-red-300">
            {(connections.error as Error).message}
          </p>
        )}
        {connected.length === 0 && !connections.isPending && (
          <p className="text-sm text-muted-foreground">No platforms connected.</p>
        )}
        <ul className="space-y-2">
          {connected.map(item => (
            <li
              key={item.platform ?? connectionLabel(item)}
              className="flex flex-wrap items-center gap-2 rounded-md border p-3 text-sm"
              data-testid={`demo-connection-${item.platform}`}
            >
              <span className="font-medium">{item.platform}</span>
              <span className="text-muted-foreground">{connectionLabel(item)}</span>
              <span className="text-muted-foreground">
                Token: {item.token_security || (item.token_present || item.has_token ? 'present' : 'missing')}
              </span>
              <DemoButton
                variant="outline"
                size="sm"
                className="ml-auto"
                disabled={disconnect.isPending}
                onClick={() => item.platform && disconnect.mutate(item.platform)}
              >
                Disconnect
              </DemoButton>
            </li>
          ))}
        </ul>
        {unconnected.length > 0 && (
          <Collapsible>
            <CollapsibleTrigger asChild>
              <DemoButton variant="ghost" data-testid="demo-unconnected-toggle">
                Not connected ({unconnected.length})
              </DemoButton>
            </CollapsibleTrigger>
            <CollapsibleContent>
              <ul className="space-y-2 pt-2">
                {unconnected.map(item => (
                  <li
                    key={item.platform ?? connectionLabel(item)}
                    className="flex flex-wrap items-center gap-2 rounded-md border p-3 text-sm"
                  >
                    <span className="font-medium">{item.platform}</span>
                    <span className="text-muted-foreground">Not connected</span>
                    <DemoButton
                      variant="outline"
                      size="sm"
                      className="ml-auto"
                      disabled={connect.isPending}
                      onClick={() => item.platform && connect.mutate(item.platform)}
                    >
                      Connect
                    </DemoButton>
                  </li>
                ))}
              </ul>
            </CollapsibleContent>
          </Collapsible>
        )}
        {connectInfo && (
          <p role="status" className="text-sm text-muted-foreground">
            {connectInfo}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function AgentsSection() {
  const agents = useQuery({
    queryKey: ['demo-agents'],
    queryFn: () => unwrap(api.GET('/api/agents')),
  });
  const list = (Array.isArray(agents.data) ? agents.data : []) as { name?: string; role?: string }[];
  return (
    <Card>
      <CardHeader>
        <CardTitle>Agents</CardTitle>
        <CardDescription>Scout, Maker, and Checker profiles available to launches.</CardDescription>
      </CardHeader>
      <CardContent>
        {agents.isPending && <Skeleton className="h-8 w-full" />}
        <ul className="space-y-1 text-sm">
          {list.map(agent => (
            <li key={agent.name}>
              {agent.name}
              {agent.role ? <span className="text-muted-foreground">, {agent.role}</span> : null}
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

function FormatsSection() {
  const formats = useQuery({
    queryKey: ['demo-formats'],
    queryFn: () => unwrap(api.GET('/api/formats')),
  });
  const capabilities = useQuery({
    queryKey: ['demo-capabilities'],
    queryFn: () => unwrap(api.GET('/api/channel-capabilities')),
  });
  const formatList = (Array.isArray(formats.data) ? formats.data : []) as {
    title?: string;
    name?: string;
    format_kind?: string;
  }[];
  const capabilityList = (Array.isArray(capabilities.data) ? capabilities.data : []) as {
    channel?: string;
    caption_limit?: number;
  }[];
  return (
    <Card>
      <CardHeader>
        <CardTitle>Format rules and channel limits</CardTitle>
        <CardDescription>Checker enforces these on every draft.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <div>
          <p className="font-medium">Formats</p>
          {formats.isPending ? (
            <Skeleton className="h-6 w-full" />
          ) : (
            <ul className="list-disc pl-5 text-muted-foreground">
              {formatList.map(item => (
                <li key={item.format_kind ?? item.name ?? item.title}>
                  {item.title ?? item.name ?? item.format_kind}
                </li>
              ))}
            </ul>
          )}
        </div>
        <div>
          <p className="font-medium">Channel limits</p>
          {capabilities.isPending ? (
            <Skeleton className="h-6 w-full" />
          ) : (
            <ul className="list-disc pl-5 text-muted-foreground">
              {capabilityList.map(item => (
                <li key={item.channel}>
                  {item.channel}
                  {typeof item.caption_limit === 'number' ? `, caption limit ${item.caption_limit}` : ''}
                </li>
              ))}
            </ul>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

type BrandKit = {
  version?: string;
  digest?: string;
  brand_colors?: string[];
  fonts?: string[];
  logo_reference?: string | null;
  banned_rules?: string[];
};

function BrandKitSection() {
  const queue = useQuery({
    queryKey: ['demo-queue'],
    queryFn: () => unwrap(api.GET('/api/queue')),
  });
  const runs = ((queue.data ?? []) as { approval_state?: string; brand_kit?: BrandKit | null }[]) ?? [];
  const kit = runs.find(run => run.approval_state === 'approved_for_export')?.brand_kit ?? null;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Brand kit</CardTitle>
        <CardDescription>From the latest approved launch. Read only.</CardDescription>
      </CardHeader>
      <CardContent className="text-sm">
        {queue.isPending && <Skeleton className="h-8 w-full" />}
        {!queue.isPending && !kit && (
          <p className="text-muted-foreground">No brand kit yet. Approve a launch first.</p>
        )}
        {kit && (
          <ul className="space-y-1">
            <li>Version: {kit.version || 'unversioned'}</li>
            {kit.digest && (
              <li>
                Digest: <span className="font-mono">{kit.digest.slice(0, 12)}…</span>
              </li>
            )}
            {(kit.brand_colors ?? []).length > 0 && <li>Colors: {kit.brand_colors?.join(', ')}</li>}
            {(kit.fonts ?? []).length > 0 && <li>Fonts: {kit.fonts?.join(', ')}</li>}
            {kit.logo_reference && <li>Logo: {kit.logo_reference}</li>}
            {(kit.banned_rules ?? []).length > 0 && <li>Banned: {kit.banned_rules?.join('; ')}</li>}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

const ADVANCED_LINKS = [
  { label: 'API reference', href: '/api/docs', available: true },
  { label: 'Privacy policy', href: '/privacy', available: true },
  { label: 'Terms of service', href: '/terms', available: true },
  { label: 'Demo facts', href: '/demo', available: true },
  { label: 'Drive import', href: '', available: false, reason: 'Available in the classic workspace' },
  { label: 'Photo checks', href: '', available: false, reason: 'Available in the classic workspace' },
  { label: 'Analytics pulls', href: '', available: false, reason: 'Available in the classic workspace' },
];

function AdvancedSection() {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Advanced</CardTitle>
        <CardDescription>Everything else, plus the classic workspace.</CardDescription>
      </CardHeader>
      <CardContent>
        <ul className="space-y-2 text-sm">
          {ADVANCED_LINKS.map(item => (
            <li key={item.label}>
              {item.available ? (
                <Link href={item.href} className="underline-offset-4 hover:underline">
                  {item.label}
                </Link>
              ) : (
                <Tooltip>
                  <TooltipTrigger disabled>
                    <span className="inline-flex h-8 items-center px-3 text-xs opacity-50">
                      {item.label}
                    </span>
                  </TooltipTrigger>
                  <TooltipContent>{item.reason}</TooltipContent>
                </Tooltip>
              )}
            </li>
          ))}
          <li>
            <Link href={CLASSIC_PATH} className="font-medium underline-offset-4 hover:underline">
              Classic workspace
            </Link>
          </li>
        </ul>
      </CardContent>
    </Card>
  );
}

export function SettingsWorkspace() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Settings</h1>
        <p className="mt-1 text-sm text-muted-foreground">Brand, connections, agents, and formats.</p>
      </div>
      <BrandKitSection />
      <ConnectionsSection />
      <AgentsSection />
      <FormatsSection />
      <AdvancedSection />
    </div>
  );
}
