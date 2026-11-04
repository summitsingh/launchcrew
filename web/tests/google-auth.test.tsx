import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';

describe('public workspace', () => {
  const source = readFileSync('src/app/page.tsx', 'utf8');
  it('uses health to open the workspace without probing disabled auth routes', () => {
    expect(source).toContain("api.GET('/api/health')");
    expect(source).toContain("auth.data?.auth !== 'disabled_demo'");
    expect(source).toContain('enabled: authed');
    expect(source).not.toContain('/api/auth/');
  });
  it('has no sign-in controls or auth chip', () => {
    for (const text of ['auth-signin', 'auth-signed-in', 'sign-out', 'Signed in as', 'Auth enabled', 'demo-front-door']) {
      expect(source).not.toContain(text);
    }
    expect(source).toContain('Shared demo workspace: runs and memory are visible to all demo visitors.');
  });
});
