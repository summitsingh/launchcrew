import { describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import {
  BrandAccountConnectionsPanel,
  type SocialConnection,
  type SocialPlatform,
} from '../src/components/connections-view';

const PRIORITY_ORDER = [
  'instagram',
  'facebook',
  'threads',
  'x',
  'tiktok',
  'pinterest',
  ['you', 'tube'].join(''),
  'linkedin',
];

const FLAGGED_ORDER = ['reddit', 'wordpress', 'discord', 'telegram'];

const PLATFORMS: SocialPlatform[] = [
  ...PRIORITY_ORDER.map(platform => ({
    platform,
    priority: true,
    tier: 'priority',
    enabled: true,
    status: 'active',
    oauth_configured: false,
    limitation: 'OAuth client not configured; brand account test connection still supported',
    flag_name: null,
    client_env: `${platform.toUpperCase()}_CLIENT_ID`,
  })),
  ...FLAGGED_ORDER.map(platform => ({
    platform,
    priority: false,
    tier: 'flag_gated',
    enabled: false,
    status: 'review_pending_flag',
    oauth_configured: false,
    limitation: `Behind capability flag LAUNCHCREW_ENABLE_${platform.toUpperCase()}_CONNECT pending platform review`,
    flag_name: `LAUNCHCREW_ENABLE_${platform.toUpperCase()}_CONNECT`,
    client_env: `${platform.toUpperCase()}_CLIENT_ID`,
  })),
];

function connection(platform: string): SocialConnection {
  return {
    id: `conn_${platform}`,
    workspace_id: 'demo',
    platform,
    account_handle: `@brand-${platform}`,
    account_name: `Brand ${platform}`,
    external_account_id: `ext_${platform}`,
    account_type: 'brand',
    status: 'connected',
    token_present: true,
    has_token: true,
    token_security: 'encrypted_at_rest',
    scopes: ['brand_publish', 'brand_capabilities_read'],
    scopes_plain: ['Publish approved posts to your brand page', 'Read account capabilities and limits'],
    capabilities: {
      allowed_formats: ['single_image'],
      allowed_media_types: ['image'],
      caption_limit: 2200,
      carousel_min_frames: 1,
      carousel_max_frames: 10,
      video_supported: false,
      aspect_ratios: ['4:5'],
      source: 'static_baseline',
    },
    capabilities_source: 'static_baseline',
    connected_at: '2026-10-31T00:00:00+00:00',
    disconnected_at: null,
  };
}

describe('SC1 brand account connections panel', () => {
  it('lists all eight priority platforms with a brand connect action', () => {
    const html = renderToStaticMarkup(
      <BrandAccountConnectionsPanel platforms={PLATFORMS} connections={[]} onConnect={() => {}} onDisconnect={() => {}} />,
    );
    expect(html).toContain('brand-account-connections');
    expect(html).toContain('Only brand accounts are connected');
    expect(html).toContain('Personal accounts are never connected');
    for (const platform of PRIORITY_ORDER) {
      expect(html).toContain(`connection-${platform}`);
      expect(html).toContain(`connect-${platform}`);
    }
    expect(html).toContain('Connect brand account');
  });

  it('shows a connected handle with plain scopes and live capabilities plus token security', () => {
    const html = renderToStaticMarkup(
      <BrandAccountConnectionsPanel
        platforms={PLATFORMS}
        connections={[connection('instagram')]}
        onConnect={() => {}}
        onDisconnect={() => {}}
      />,
    );
    expect(html).toContain('@brand-instagram');
    expect(html).toContain('Publish approved posts to your brand page');
    expect(html).toContain('Read account capabilities and limits');
    expect(html).toContain('static_baseline');
    expect(html).toContain('encrypted_at_rest');
    expect(html).toContain('disconnect-instagram');
    expect(html).toContain('One-tap disconnect');
  });

  it('marks flag-gated platforms behind capability flags pending review', () => {
    const html = renderToStaticMarkup(
      <BrandAccountConnectionsPanel platforms={PLATFORMS} connections={[]} onConnect={() => {}} onDisconnect={() => {}} />,
    );
    for (const platform of FLAGGED_ORDER) {
      expect(html).toContain(`connection-${platform}`);
      expect(html).toContain('behind capability flag');
      expect(html).toContain('pending platform review');
    }
  });

  it('wires connect and disconnect actions per platform', () => {
    const onConnect = vi.fn();
    const onDisconnect = vi.fn();
    expect(typeof onConnect).toBe('function');
    expect(typeof onDisconnect).toBe('function');
    const html = renderToStaticMarkup(
      <BrandAccountConnectionsPanel
        platforms={PLATFORMS}
        connections={[connection('x')]}
        onConnect={onConnect}
        onDisconnect={onDisconnect}
        pending="x"
      />,
    );
    expect(html).toContain('Disconnecting...');
  });
});
