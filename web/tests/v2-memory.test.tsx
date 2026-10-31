import { describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryDeleteDialog, MemoryView, executeMemoryDelete, memoryDeletedNotice } from '../src/components/v2-views';
import { memoryEditPayload } from '../src/lib/v2';
import { unwrap } from '../src/lib/api';
import type { components } from '../src/lib/schema';

describe('Memory review controls', () => {
  it('allows object content and sends only editable fields', () => {
    const payload = memoryEditPayload('Wallet facts', '{"price":49,"details":{"approved":true}}');
    expect(payload).toEqual({ title: 'Wallet facts', content: { price: 49, details: { approved: true } } });
    expect(payload).not.toHaveProperty('kind');
    expect(memoryEditPayload('x'.repeat(200), '{}').title).toHaveLength(200);
  });

  it('blocks invalid titles, invalid JSON, and JSON values that are not objects', () => {
    for (const title of ['', 'x'.repeat(201)]) {
      expect(() => memoryEditPayload(title, '{}')).toThrow('Title must be between 1 and 200 characters.');
    }
    expect(() => memoryEditPayload('Facts', '{broken')).toThrow('Content must be valid JSON.');
    for (const content of ['null', '[]', '"text"', '42', 'true']) {
      expect(() => memoryEditPayload('Facts', content)).toThrow('Content must be a JSON object.');
    }
  });

  it('accepts a 201 create response through unwrap', async () => {
    const data = { id: 'memory_demo' };
    await expect(unwrap(Promise.resolve({ data, response: new Response(JSON.stringify(data), { status: 201 }) }))).resolves.toEqual(data);
  });

  it('deletes through the memory endpoint and reports failures', async () => {
    const okClient = { DELETE: vi.fn().mockResolvedValue({ response: { ok: true, status: 204 } }) };
    await expect(executeMemoryDelete(okClient, 'memory_demo')).resolves.toBeUndefined();
    expect(okClient.DELETE).toHaveBeenCalledWith('/api/memory/{item_id}', { params: { path: { item_id: 'memory_demo' } } });
    const badClient = { DELETE: vi.fn().mockResolvedValue({ response: { ok: false, status: 404 } }) };
    await expect(executeMemoryDelete(badClient, 'memory_missing')).rejects.toThrow('Request failed (404). Could not delete memory.');
  });

  it('names the deleted item in the success notice', () => {
    expect(memoryDeletedNotice('Wallet facts')).toBe('Memory item "Wallet facts" deleted.');
  });

  it('asks for confirmation in a dialogue before deletion runs', () => {
    const dialog = renderToStaticMarkup(
      <MemoryDeleteDialog itemTitle="Wallet facts" itemKind="brand_fact" pending={false} error={null} onConfirm={() => {}} onCancel={() => {}} />,
    );
    expect(dialog).toContain('role="dialog"');
    expect(dialog).toContain('aria-modal="true"');
    expect(dialog).toContain('Wallet facts');
    expect(dialog).toContain('Confirm delete');
    expect(dialog).toContain('Cancel');
    expect(dialog).not.toContain('role="alert"');
  });

  it('shows pending, error, and voice states inside the dialogue', () => {
    const pending = renderToStaticMarkup(
      <MemoryDeleteDialog itemTitle="Wallet facts" itemKind="brand_fact" pending={true} error={null} onConfirm={() => {}} onCancel={() => {}} />,
    );
    expect(pending).toContain('Deleting...');
    const failed = renderToStaticMarkup(
      <MemoryDeleteDialog itemTitle="Wallet facts" itemKind="brand_fact" pending={false} error="Request failed (404). Could not delete memory." onConfirm={() => {}} onCancel={() => {}} />,
    );
    expect(failed).toContain('role="alert"');
    expect(failed).toContain('Request failed (404). Could not delete memory.');
    const voice = renderToStaticMarkup(
      <MemoryDeleteDialog itemTitle="Synthetic voice" itemKind="voice_profile" pending={false} error={null} onConfirm={() => {}} onCancel={() => {}} />,
    );
    expect(voice).toContain('marks dependent approvals stale');
    const plain = renderToStaticMarkup(
      <MemoryDeleteDialog itemTitle="Wallet facts" itemKind="brand_fact" pending={false} error={null} onConfirm={() => {}} onCancel={() => {}} />,
    );
    expect(plain).not.toContain('marks dependent approvals stale');
  });

  it('renders the forms and cached items without contacting a backend', () => {
    const client = new QueryClient();
    const item: components['schemas']['MemoryItemOut'] = {
      id: 'memory_demo', kind: 'brand_fact', title: 'Wallet facts', content: { price: 49 },
      source_run_id: 'run_demo', created_at: '2026-10-27T00:00:00Z', updated_at: '2026-10-27T00:00:00Z'
    };
    client.setQueryData(['memory'], [item]);
    const html = renderToStaticMarkup(<QueryClientProvider client={client}><MemoryView /></QueryClientProvider>);
    for (const label of ['Create memory', 'Content JSON object', 'Learn from run', 'Run id', 'Refreshes every 3 seconds', 'Wallet facts', 'Kind (read-only): brand_fact', 'Edit memory', 'Delete memory', 'No auto-learning, no auto-post, no auto-send, no publishing.']) {
      expect(html).toContain(label);
    }
    const learnedSelect = html.match(/<select id="memory-learn-kind"[^>]*>(.*?)<\/select>/)?.[1];
    expect(learnedSelect).toContain('approval_example');
    expect(learnedSelect).toContain('blocked_rule');
    expect(learnedSelect).not.toContain('brand_fact');
    expect(learnedSelect).not.toContain('profile');
  });
});
