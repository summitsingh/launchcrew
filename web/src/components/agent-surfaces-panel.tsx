'use client';
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { api, unwrap } from '@/lib/api';

type WorkspaceKey = {
  id: string;
  label?: string;
  key_prefix?: string;
  scopes?: string[];
  role?: string;
  revoked?: boolean;
  created_at?: string;
  raw_key?: string;
};

const SEAT_ROLES = ['owner', 'editor', 'viewer'] as const;

type McpTool = { name: string; description?: string };

type SkillDoc = {
  name: string;
  version: string;
  content_markdown?: string;
  tools?: string[];
  refusal_rules?: { code: string; reason: string; http_status?: number }[];
};

async function fetchKeys(): Promise<WorkspaceKey[]> {
  return (await unwrap(api.GET('/api/agent-surfaces/keys'))) as WorkspaceKey[];
}

async function fetchTools(): Promise<{ tools: McpTool[] }> {
  return (await unwrap(api.GET('/api/mcp/tools'))) as { tools: McpTool[] };
}

async function fetchSkill(): Promise<SkillDoc> {
  return (await unwrap(api.GET('/api/agent-surfaces/skill'))) as SkillDoc;
}

export function AgentSurfacesPanel() {
  const client = useQueryClient();
  const [label, setLabel] = useState('CLI key');
  const [role, setRole] = useState<string>('owner');
  const [notice, setNotice] = useState('');
  const [rawKey, setRawKey] = useState('');
  const keys = useQuery({ queryKey: ['agent-keys'], queryFn: fetchKeys });
  const tools = useQuery({ queryKey: ['mcp-tools'], queryFn: fetchTools });
  const skill = useQuery({ queryKey: ['agent-skill'], queryFn: fetchSkill });

  const createKey = useMutation({
    mutationFn: () => unwrap(api.POST('/api/agent-surfaces/keys', { body: { label, role } })),
    onSuccess: (data) => {
      const created = data as WorkspaceKey;
      setRawKey(created.raw_key ?? '');
      setNotice('Workspace key created. Copy it now; the raw value shows once.');
      client.invalidateQueries({ queryKey: ['agent-keys'] });
    },
    onError: (error: Error) => setNotice(error.message),
  });

  const revokeKey = useMutation({
    mutationFn: (keyId: string) => unwrap(api.POST('/api/agent-surfaces/keys/{key_id}/revoke', {
      params: { path: { key_id: keyId } },
    })),
    onSuccess: () => {
      setNotice('Workspace key revoked. It now fails closed on every surface.');
      client.invalidateQueries({ queryKey: ['agent-keys'] });
    },
    onError: (error: Error) => setNotice(error.message),
  });

  return <section className="panel" aria-label="Agent surfaces" data-testid="agent-surfaces-panel">
    <h2>Agent surfaces</h2>
    <p className="hint">One backend serves four surfaces over the same workspace state: Web UI, REST API, hosted MCP server, and CLI. Keys are scoped to this workspace.</p>

    <h3>Workspace API keys</h3>
    <div className="queue-actions">
      <label htmlFor="agent-key-label">Key label</label>
      <input id="agent-key-label" value={label} maxLength={120} onChange={e => setLabel(e.target.value)} />
      <label htmlFor="agent-key-role">Seat role</label>
      <select id="agent-key-role" value={role} onChange={e => setRole(e.target.value)}>
        {SEAT_ROLES.map(name => <option key={name} value={name}>{name}{name === 'viewer' ? ' (read-only)' : ''}</option>)}
      </select>
      <Button data-testid="agent-create-key-btn" onClick={() => createKey.mutate()} disabled={createKey.isPending || !label.trim()}>
        {createKey.isPending ? 'Creating...' : 'Create workspace key'}
      </Button>
    </div>
    {notice && <p role="status">{notice}</p>}
    {rawKey && <p role="status">New key (shows once): <code>{rawKey}</code></p>}
    {keys.isPending && <p>Loading keys...</p>}
    {keys.error && <p role="alert">{keys.error.message}</p>}
    <ul data-testid="agent-keys-list" aria-label="Workspace keys">
      {(keys.data ?? []).length === 0 && <li className="hint">No workspace keys yet.</li>}
      {(keys.data ?? []).map(key => <li key={key.id}>
        <span>{key.label || 'Unlabeled'} · <code>{key.key_prefix}</code> · {key.role ?? 'owner'} · {(key.scopes ?? []).join(', ')}</span>
        {' '}<span>{key.revoked ? 'revoked' : 'active'}</span>
        {!key.revoked && <Button variant="outline" onClick={() => revokeKey.mutate(key.id)} disabled={revokeKey.isPending}>Revoke</Button>}
      </li>)}
    </ul>

    <h3>MCP tools and REST API</h3>
    <p className="hint">The hosted MCP server exposes the same six operations as the REST API.</p>
    {tools.isPending && <p>Loading tools...</p>}
    {tools.error && <p role="alert">{tools.error.message}</p>}
    <ul data-testid="agent-mcp-tools-list" aria-label="MCP tools">
      {(tools.data?.tools ?? []).map(tool => <li key={tool.name}>
        <code>{tool.name}</code>{tool.description ? ` ${tool.description}` : ''}
      </li>)}
    </ul>

    <h3>CLI</h3>
    <p className="hint">Export the validated schedule from the Web UI, then apply it unchanged:</p>
    <pre>launchcrew apply schedule-export.json</pre>
    <p className="hint">Validate first with <code>launchcrew validate --slot-id &lt;slot_id&gt;</code>, then check status with <code>launchcrew run-status</code>. Pass <code>--workspace-key</code> or set <code>LAUNCHCREW_WORKSPACE_KEY</code>.</p>

    <h3>Agent skill</h3>
    {skill.isPending && <p>Loading skill...</p>}
    {skill.error && <p role="alert">{skill.error.message}</p>}
    {skill.data && <>
      <p className="hint">{skill.data.name} v{skill.data.version} · Tools: {(skill.data.tools ?? []).join(', ')}</p>
      <pre data-testid="agent-skill-preview">{skill.data.content_markdown ?? ''}</pre>
    </>}
  </section>;
}
