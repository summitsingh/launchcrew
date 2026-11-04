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

export interface ConnectCredentials {
  token: string;
  handle: string;
}

/** Build the connect-callback body from owner-supplied credentials only.
 * Refuses blank input; never fabricates a token or handle. */
export function buildConnectCallbackBody(
  _platform: string,
  token: string,
  handle: string,
): ConnectCredentials & { account_type: string; scopes: string[] } {
  const cleanToken = (token || '').trim();
  if (!cleanToken) throw new Error('A provider token is required to complete the brand connection');
  const cleanHandle = (handle || '').trim();
  if (!cleanHandle) throw new Error('A brand account handle is required to complete the brand connection');
  return {
    token: cleanToken,
    handle: cleanHandle,
    account_type: 'brand',
    scopes: ['brand_profile', 'brand_capabilities_read'],
  };
}

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
  confirming,
}: {
  platforms: SocialPlatform[];
  connections: SocialConnection[];
  onConnect: (platform: string) => void;
  onDisconnect: (platform: string) => void;
  pending?: string | null;
  confirming?: string | null;
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
              {!connected && item.limitation && <p className="hint">{item.limitation}</p>}
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
                      {pending === item.platform ? 'Disconnecting...' : confirming === item.platform ? 'Confirm disconnect' : 'One-tap disconnect'}
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
                {!connected && item.limitation ? ` · ${item.limitation}` : ''}
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
                      {pending === item.platform ? 'Disconnecting...' : confirming === item.platform ? 'Confirm disconnect' : 'One-tap disconnect'}
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
  const [formFor, setFormFor] = useState<string | null>(null);
  const [tokenInput, setTokenInput] = useState('');
  const [handleInput, setHandleInput] = useState('');
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
  const openConnectForm = (platform: string) => {
    setFormFor(platform);
    setTokenInput('');
    setHandleInput('');
    setMessage('');
  };
  const connect = useMutation({
    mutationFn: async ({ platform, token, handle }: ConnectCredentials & { platform: string }) => {
      await unwrap(
        api.POST('/api/social/connections/{platform}/connect', {
          params: { path: { platform } },
          body: { account_type: 'brand' },
        }),
      );
      return unwrap(
        api.POST('/api/social/connections/{platform}/callback', {
          params: { path: { platform } },
          body: buildConnectCallbackBody(platform, token, handle),
        }),
      );
    },
    onMutate: ({ platform }) => {
      setActive(platform);
      setMessage('');
    },
    onSuccess: (_data, { platform }) => {
      setMessage(`Connected brand account for ${platform}.`);
      setActive(null);
      setFormFor(null);
      setTokenInput('');
      setHandleInput('');
      refresh();
    },
    onError: (error: Error) => {
      setMessage(error.message);
      setActive(null);
    },
  });
  const [confirming, setConfirming] = useState<string | null>(null);
  const disconnect = useMutation({
    mutationFn: (input: { platform: string; confirm: boolean }) =>
      unwrap(
        api.POST('/api/social/connections/{platform}/disconnect', {
          params: { path: { platform: input.platform } },
          body: { confirm: input.confirm },
        }),
      ),
    onMutate: (input: { platform: string; confirm: boolean }) => {
      setActive(input.platform);
      setMessage('');
    },
    onSuccess: (_data, input: { platform: string; confirm: boolean }) => {
      setMessage(`Disconnected ${input.platform}; token deleted, receipts preserved.`);
      setActive(null);
      setConfirming(null);
      refresh();
    },
    onError: (error: Error, input: { platform: string; confirm: boolean }) => {
      // The server refuses with 409 when the account has posted content.
      // Arm the button instead of failing: the next tap confirms.
      if (!input.confirm && /confirm/i.test(error.message)) {
        setConfirming(input.platform);
        setMessage(
          `This brand account has posted content. Tap disconnect on ${input.platform} again to confirm; past posts and receipts stay.`,
        );
      } else {
        setMessage(error.message);
      }
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
          onConnect={openConnectForm}
          onDisconnect={platform => disconnect.mutate({ platform, confirm: confirming === platform })}
          pending={active}
          confirming={confirming}
        />
      )}
      {formFor && (
        <form
          aria-label={`Connect ${formFor} brand account`}
          data-testid="connect-credentials-form"
          onSubmit={event => {
            event.preventDefault();
            connect.mutate({ platform: formFor, token: tokenInput, handle: handleInput });
          }}
        >
          <h3>Connect {formFor} brand account</h3>
          <p className="hint">
            Paste the provider token for the brand account and confirm its handle. Only brand
            accounts are connected by explicit owner action.
          </p>
          <label className="hint" htmlFor="connect-token-input">
            Provider token
            <input
              id="connect-token-input"
              data-testid="connect-token-input"
              type="password"
              autoComplete="off"
              value={tokenInput}
              onChange={event => setTokenInput(event.target.value)}
            />
          </label>
          <label className="hint" htmlFor="connect-handle-input">
            Brand account handle
            <input
              id="connect-handle-input"
              data-testid="connect-handle-input"
              type="text"
              autoComplete="off"
              placeholder="@brand-handle"
              value={handleInput}
              onChange={event => setHandleInput(event.target.value)}
            />
          </label>
          <div className="queue-actions">
            <Button
              type="submit"
              variant="default"
              data-testid="connect-submit"
              disabled={connect.isPending || !tokenInput.trim() || !handleInput.trim()}
            >
              {connect.isPending ? 'Connecting...' : 'Complete brand connection'}
            </Button>
            <Button type="button" variant="outline" onClick={() => setFormFor(null)}>
              Cancel
            </Button>
          </div>
        </form>
      )}
    </div>
  );
}
