import { describe, expect, it } from 'vitest';
import { buildConnectCallbackBody } from '../src/components/connections-view';

describe('connect callback body carries owner-supplied credentials', () => {
  it('passes the pasted token and handle through verbatim', () => {
    const body = buildConnectCallbackBody('instagram', 'EAALiveOwnerToken123', '@summitleather.co');
    expect(body.token).toBe('EAALiveOwnerToken123');
    expect(body.handle).toBe('@summitleather.co');
    expect(body.account_type).toBe('brand');
  });

  it('refuses a missing token instead of fabricating one', () => {
    expect(() => buildConnectCallbackBody('instagram', '   ', '@summitleather.co')).toThrow(
      /token/i,
    );
  });

  it('refuses a missing handle instead of fabricating one', () => {
    expect(() => buildConnectCallbackBody('instagram', 'EAALiveOwnerToken123', '')).toThrow(
      /handle/i,
    );
  });

  it('never fabricates test credentials', () => {
    const body = buildConnectCallbackBody('instagram', 'EAALiveOwnerToken123', '@summitleather.co');
    const serialized = JSON.stringify(body);
    expect(serialized).not.toContain('test-code-');
    expect(serialized).not.toContain('@brand-');
  });
});
