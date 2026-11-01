import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { renderToStaticMarkup } from 'react-dom/server';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AgentSurfacesPanel } from '../src/components/agent-surfaces-panel';

const TOOL_NAMES = [
  'launchcrew_accounts',
  'launchcrew_capabilities',
  'launchcrew_upload',
  'launchcrew_validate',
  'launchcrew_apply',
  'launchcrew_run_status',
];

function seededClient() {
  const client = new QueryClient();
  client.setQueryData(['agent-keys'], [
    { id: 'wkey_1', label: 'CLI key', key_prefix: 'lc_wk_abc123', scopes: ['accounts', 'validate', 'apply'], revoked: false },
  ]);
  client.setQueryData(['mcp-tools'], {
    tools: TOOL_NAMES.map(name => ({ name, description: `${name} description` })),
  });
  client.setQueryData(['agent-skill'], {
    name: 'launchcrew-socialclaw',
    version: '1.0.0',
    content_markdown: '# LaunchCrew SocialClaw\nValidate then apply. Refusals: pack_not_approved, format_check_failed, unapproved_channel_variants.',
    tools: TOOL_NAMES,
    refusal_rules: [{ code: 'pack_not_approved', reason: 'Pack is not approved.', http_status: 409 }],
  });
  return client;
}

function renderPanel() {
  return renderToStaticMarkup(
    <QueryClientProvider client={seededClient()}><AgentSurfacesPanel /></QueryClientProvider>,
  );
}

describe('agent surfaces panel', () => {
  it('renders the panel with key generator, key list, and MCP tool list', () => {
    const html = renderPanel();
    expect(html).toContain('data-testid="agent-surfaces-panel"');
    expect(html).toContain('data-testid="agent-create-key-btn"');
    expect(html).toContain('Create workspace key');
    expect(html).toContain('data-testid="agent-keys-list"');
    expect(html).toContain('CLI key');
    expect(html).toContain('lc_wk_abc123');
    expect(html).toContain('Revoke');
    expect(html).toContain('data-testid="agent-mcp-tools-list"');
    for (const name of TOOL_NAMES) {
      expect(html).toContain(name);
    }
  });

  it('shows the CLI apply snippet and the installable skill preview', () => {
    const html = renderPanel();
    expect(html).toContain('launchcrew apply schedule-export.json');
    expect(html).toContain('LAUNCHCREW_WORKSPACE_KEY');
    expect(html).toContain('data-testid="agent-skill-preview"');
    expect(html).toContain('launchcrew-socialclaw');
    expect(html).toContain('pack_not_approved');
  });

  it('is wired into the Calendar view', () => {
    const source = readFileSync('src/app/page.tsx', 'utf8');
    expect(source).toContain('AgentSurfacesPanel');
    expect(source).toContain('<CalendarView /><AgentSurfacesPanel />');
  });
});
