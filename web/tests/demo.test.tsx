import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import DemoPage from '../src/app/demo/page';

describe('public fictional demo view', () => {
  it('labels everything fictional and stays read-only', () => {
    const html = renderToStaticMarkup(<DemoPage />);
    expect(html).toContain('FICTIONAL DEMO');
    expect(html).toContain('invented for demonstration');
    expect(html).toContain('nothing here is a real business');
    expect(html).toContain('nothing on this page can publish anything');
    expect(html).not.toContain('<form');
    expect(html).not.toContain('type="password"');
  });

  it('shows the bundled fictional facts and the four steps', () => {
    const html = renderToStaticMarkup(<DemoPage />);
    expect(html).toContain('Vegan leather wallet');
    expect(html).toContain('$49');
    expect(html).toContain('Austin commuters');
    expect(html).toContain('Designed in Texas');
    for (const step of ['Scout', 'Maker', 'Checker']) {
      expect(html).toContain(step);
    }
    expect(html).toContain('Nothing publishes without your approval');
    expect(html).toContain('href="/privacy"');
    expect(html).toContain('href="/terms"');
    expect(html).toContain('href="/plans"');
  });
});
