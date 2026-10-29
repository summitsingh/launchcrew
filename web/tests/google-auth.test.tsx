import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';

function desk(): string {
  return readFileSync('src/app/page.tsx', 'utf8');
}

describe('google-only auth UI', () => {
  it('renders only the configured Google provider with no Facebook link', () => {
    const source = desk();
    expect(source).toContain("authProviders.includes('google')");
    expect(source).toContain('/api/auth/google/login');
    expect(source).toContain('data-testid="auth-signin"');
    expect(source).toContain('Google provider setup is required');
    expect(source.toLowerCase()).not.toContain('facebook');
    expect(source).not.toContain('/api/auth/facebook/login');
  });

  it('keeps status unverified and exposes providers from auth status', () => {
    const source = desk();
    expect(source).toContain('Auth enabled, unverified');
    expect(source).not.toContain('Auth enabled, verified');
    expect(source).toContain("auth.data?.providers");
    expect(source).toContain('authProviders');
    expect(source).toContain('authEnabled');
    expect(source).toContain('authUser');
    const schema = readFileSync('src/lib/schema.d.ts', 'utf8');
    expect(schema).toContain('[key: string]: string | boolean | string[];');
  });

  it('adds explicit sign-out with cache and view clearing', () => {
    const source = desk();
    expect(source).toContain("api.POST('/api/auth/logout')");
    expect(source).toContain('data-testid="sign-out"');
    expect(source).toContain('Sign out');
    expect(source).toContain('Signed out.');
    expect(source).toContain('clearActorCache');
    expect(source).toContain('resetActorView');
    expect(source).toContain("client.invalidateQueries({ queryKey: ['auth'] })");
  });

  it('scopes product queries per actor and clears on user switch', () => {
    const source = desk();
    expect(source).toContain("queryKey: ['agents', authUser]");
    expect(source).toContain("queryKey: ['queue', authUser]");
    expect(source).toContain("queryKey: ['run', active, authUser]");
    expect(source).toContain('enabled: authed');
    expect(source).toContain('authUserRef');
    expect(source).toContain("client.removeQueries({ queryKey: ['agents'] })");
    expect(source).toContain("client.removeQueries({ queryKey: ['queue'] })");
    expect(source).toContain("client.removeQueries({ queryKey: ['run'] })");
    expect(source).toContain("setActive('')");
    expect(source).toContain("setExported('')");
  });

  it('carries no Meta credential or secret in frontend source', () => {
    const source = desk();
    expect(source).not.toContain('META_API_KEY');
    expect(source).not.toContain('GOOGLE_CLIENT_SECRET');
    expect(source).not.toContain('apps.googleusercontent.com');
  });
});
