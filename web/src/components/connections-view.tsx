'use client';
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { api, unwrap } from '@/lib/api';

export interface SocialPlatform {
  platform: string;
  priority: boolean;
  tier: string;
  enabled: boolean;
  status: string;
  oauth_configured: boolean;
  limitation: string | null;
  flag_name: string | null;
  client_env: string | null;
}

export interface SocialConnection {
  id: string;
  workspace_id: string;
  platform: string;
  account_handle: string | null;
  account_name: string | null;
  external_account_id: string | null;
  account_type: string;
  status: string;
  token_present: boolean;
  has_token: boolean;
  token_security: string;
  scopes: string[];
  scopes_plain: string[];
  capabilities: Record<string, unknown>;
  capabilities_source: string;
  connected_at: string | null;
  disconnected_at: string | null;
}

export const PRIORITY_TIER = 'priority';
export const FLAGGED_TIER = 'flag_gated';

function capabilitySummary(capabilities: Record<string, unknown>): string {
  if (!capabilities || typeof capabilities !== 'object') return 'No live capabilities yet.';
  const parts: string[] = [];
  const formats = capabilities['allowed_formats'];
  if (Array.isArray(formats) && formats.length > 0) parts.push(`Formats: ${formats.join(', ')}`);
  const limit = capabilities['caption_limit'];
  if (typeof limit === 'number') parts.push(`Caption limit: ${limit}`);
  const media = capabilities['allowed_media_types'];
  if (Array.isArray(media) && media.length > 0) parts.push(`Media: ${media.join(', ')}`);
  const ratios = capabilities['aspect_ratios'];
  if (Array.isArray(ratios) && ratios.length > 0) parts.push(`Ratios: ${ratios.join(', ')}`);
  const video = capabilities['video_supported'];
  if (typeof video === 'boolean') parts.push(video ? 'Video supported' : 'Images only');
  const source = capabilities['source'];
  if (typeof source === 'string' && source) parts.push(`Source: ${source}`);
  return parts.length > 0 ? parts.join(' · ') : 'Live capabilities recorded.';
}

export function BrandAccountConnectionsPanel({
  platforms,
  connections,
  onConnect,
  onDisconnect,
  pending,
}: {
  platforms: SocialPlatform[];
  connections: SocialConnection[];
  onConnect: (platform: string) => void;
  onDisconnect: (platform: string) => void;
  pending?: string | null;
}) {
  const byPlatform = new Map(connections.map(item => [item.platform, item]));
  const priorityPlatforms = platforms.filter(item => item.tier === PRIORITY_TIER || item.priority);
  const flaggedPlatforms = platforms.filter(item => !(item.tier === PRIORITY_TIER || item.priority));
  return (
    <section className="panel" aria-label="Brand account connections" data-testid="brand-account-connections">
      <p className="eyebrow">BRAND CONNECTIONS</p>
      <h2>Brand account connections</h2>
      <p className="hint">
        Only brand accounts are connected by explicit owner action. Personal accounts are never connected.
      </p>
      <h3>Priority platforms</h3>
      {priorityPlatforms.length === 0 && <p className="hint">No priority platforms listed.</p>}
      <ul className="scout-list">
        {priorityPlatforms.map(item => {
          const connection = byPlatform.get(item.platform);
          const connected = !!connection && connection.status === 'connected';
          return (
            <li key={item.platform} className="scout-fact" data-testid={`connection-${item.platform}`}>
              <div className="scout-row">
                <span>{item.platform}</span>
                {connected ? (
                  <span className="badge approved">connected</span>
                ) : connection ? (
                  <span className="badge pending">{connection.status}</span>
                ) : (
                  <span className="badge pending">not connected</span>
                )}
              </div>
              {item.limitation && <p className="hint">{item.limitation}</p>}
              {connected && connection ? (
                <>
                  <p className="hint" data-testid={`handle-${item.platform}`}>
                    Handle: {connection.account_handle || connection.account_name || 'brand account'}
                  </p>
                  <p className="hint">Scopes: {(connection.scopes_plain || []).join(' · ') || 'none'}</p>
                  <p className="hint" data-testid={`capabilities-${item.platform}`}>
                    {capabilitySummary(connection.capabilities)}
                  </p>
                  <p className="hint" data-testid={`token-security-${item.platform}`}>
                    Token: {connection.token_security || 'encrypted_at_rest'}
                  </p>
                  <div className="queue-actions">
                    <Button
                      type="button"
                      variant="outline"
                      data-testid={`disconnect-${item.platform}`}
                      disabled={pending === item.platform}
                      onClick={() => onDisconnect(item.platform)}
                    >
                      {pending === item.platform ? 'Disconnecting...' : 'One-tap disconnect'}
                    </Button>
                  </div>
                </>
              ) : (
                <div className="queue-actions">
                  <Button
                    type="button"
                    variant="outline"
                    data-testid={`connect-${item.platform}`}
                    disabled={pending === item.platform}
                    onClick={() => onConnect(item.platform)}
                  >
                    {pending === item.platform ? 'Connecting...' : 'Connect brand account'}
                  </Button>
                </div>
              )}
            </li>
          );
        })}
      </ul>
      <h3>Capability-flag platforms</h3>
      <p className="hint">Behind capability flags pending platform review.</p>
      <ul className="scout-list">
        {flaggedPlatforms.map(item => {
          const connection = byPlatform.get(item.platform);
          const connected = !!connection && connection.status === 'connected';
          return (
            <li key={item.platform} className="scout-fact" data-testid={`connection-${item.platform}`}>
              <div className="scout-row">
                <span>{item.platform}</span>
                <span className="badge pending">behind capability flag</span>
              </div>
              <p className="hint" data-testid={`flag-${item.platform}`}>
                {item.flag_name || 'capability flag'} pending platform review
                {item.limitation ? ` · ${item.limitation}` : ''}
              </p>
              {connected && connection ? (
                <>
                  <p className="hint">Handle: {connection.account_handle || connection.account_name || 'brand account'}</p>
                  <p className="hint">Scopes: {(connection.scopes_plain || []).join(' · ') || 'none'}</p>
                  <div className="queue-actions">
                    <Button
                      type="button"
                      variant="outline"
                      data-testid={`disconnect-${item.platform}`}
                      disabled={pending === item.platform}
                      onClick={() => onDisconnect(item.platform)}
                    >
                      {pending === item.platform ? 'Disconnecting...' : 'One-tap disconnect'}
                    </Button>
                  </div>
                </>
              ) : (
                <div className="queue-actions">
                  <Button
                    type="button"
                    variant="outline"
                    data-testid={`connect-${item.platform}`}
                    disabled={pending === item.platform || !item.enabled}
                    title={!item.enabled ? `Requires ${item.flag_name}` : undefined}
                    onClick={() => onConnect(item.platform)}
                  >
                    Connect brand account
                  </Button>
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

export function ConnectionsView() {
  const client = useQueryClient();
  const [active, setActive] = useState<string | null>(null);
  const [message, setMessage] = useState('');
  const platforms = useQuery({
    queryKey: ['social-platforms'],
    queryFn: () => unwrap(api.GET('/api/social/platforms')),
  });
  const connections = useQuery({
    queryKey: ['social-connections'],
    queryFn: () => unwrap(api.GET('/api/social/connections')),
  });
  const refresh = () => {
    client.invalidateQueries({ queryKey: ['social-platforms'] });
    client.invalidateQueries({ queryKey: ['social-connections'] });
    client.invalidateQueries({ queryKey: ['channel-capabilities'] });
  };
  const connect = useMutation({
    mutationFn: async (platform: string) => {
      await unwrap(
        api.POST('/api/social/connections/{platform}/connect', {
          params: { path: { platform } },
          body: { account_type: 'brand' },
        }),
      );
      return unwrap(
        api.POST('/api/social/connections/{platform}/callback', {
          params: { path: { platform } },
          body: {
            code: `test-code-${platform}`,
            handle: `@brand-${platform}`,
            account_name: `Brand ${platform}`,
            account_type: 'brand',
            scopes: ['brand_profile', 'brand_capabilities_read'],
          },
        }),
      );
    },
    onMutate: (platform: string) => {
      setActive(platform);
      setMessage('');
    },
    onSuccess: (_data, platform: string) => {
      setMessage(`Connected brand account for ${platform}.`);
      setActive(null);
      refresh();
    },
    onError: (error: Error) => {
      setMessage(error.message);
      setActive(null);
    },
  });
  const disconnect = useMutation({
    mutationFn: (platform: string) =>
      unwrap(
        api.POST('/api/social/connections/{platform}/disconnect', {
          params: { path: { platform } },
        }),
      ),
    onMutate: (platform: string) => {
      setActive(platform);
      setMessage('');
    },
    onSuccess: (_data, platform: string) => {
      setMessage(`Disconnected ${platform}; token deleted, receipts preserved.`);
      setActive(null);
      refresh();
    },
    onError: (error: Error) => {
      setMessage(error.message);
      setActive(null);
    },
  });
  return (
    <div>
      {message && (
        <p role="status" className="message">
          {message}
        </p>
      )}
      {(platforms.isPending || connections.isPending) && <p>Loading brand connections...</p>}
      {(platforms.error || connections.error) && (
        <p role="alert" className="message error">
          {(platforms.error as Error | undefined)?.message || (connections.error as Error | undefined)?.message}
        </p>
      )}
      {platforms.data && connections.data && (
        <BrandAccountConnectionsPanel
          platforms={platforms.data as unknown as SocialPlatform[]}
          connections={connections.data as unknown as SocialConnection[]}
          onConnect={platform => connect.mutate(platform)}
          onDisconnect={platform => disconnect.mutate(platform)}
          pending={active}
        />
      )}
    </div>
  );
}
