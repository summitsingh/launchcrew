import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import {
  EMPTY_TREND_FORMAT,
  TREND_SOURCE_PRESETS,
  TrendFormatPicker,
  TrendGuidancePanel,
  buildTrendFormatPayload,
  trendSourceMissing,
} from '../src/components/trend-picker';

describe('trend format picker inputs', () => {
  it('renders the description and source inputs with the required test ids', () => {
    const html = renderToStaticMarkup(
      <TrendFormatPicker value={EMPTY_TREND_FORMAT} onChange={() => undefined} />,
    );
    expect(html).toContain("data-testid=\"trend-format-label-input\"");
    expect(html).toContain("data-testid=\"trend-format-source-input\"");
    expect(html).toContain('Trend Format Description');
    expect(html).toContain('Required Source Label');
  });

  it('offers the source label preset pills and the guidance-only note', () => {
    const html = renderToStaticMarkup(
      <TrendFormatPicker value={EMPTY_TREND_FORMAT} onChange={() => undefined} />,
    );
    for (const preset of TREND_SOURCE_PRESETS) {
      expect(html).toContain(preset);
    }
    expect(html).toContain('Maker angle guidance only, never a fact source');
  });

  it('warns when a description has no source label', () => {
    const clean = renderToStaticMarkup(
      <TrendFormatPicker value={EMPTY_TREND_FORMAT} onChange={() => undefined} />,
    );
    expect(clean).not.toContain('role="alert"');
    const missing = renderToStaticMarkup(
      <TrendFormatPicker value={{ label: 'POV unboxing', source: '' }} onChange={() => undefined} />,
    );
    expect(missing).toContain('role="alert"');
  });
});

describe('trend payload helpers', () => {
  it('builds no payload when no trend is entered', () => {
    expect(buildTrendFormatPayload(EMPTY_TREND_FORMAT)).toBeNull();
    expect(buildTrendFormatPayload({ label: '   ', source: '   ' })).toBeNull();
  });

  it('builds the label and source payload when a trend is entered', () => {
    expect(
      buildTrendFormatPayload({ label: 'POV unboxing', source: 'TikTok inspiration page' }),
    ).toEqual({ trend_label: 'POV unboxing', trend_source: 'TikTok inspiration page' });
  });

  it('flags a label without its required source label', () => {
    expect(trendSourceMissing(EMPTY_TREND_FORMAT)).toBe(false);
    expect(trendSourceMissing({ label: 'POV unboxing', source: '' })).toBe(true);
    expect(trendSourceMissing({ label: '', source: 'Seasonal format' })).toBe(false);
    expect(trendSourceMissing({ label: 'POV unboxing', source: 'Seasonal format' })).toBe(false);
  });
});

describe('receipt trend guidance display', () => {
  it('renders the recorded guidance and source label on the receipt', () => {
    const html = renderToStaticMarkup(
      <TrendGuidancePanel
        trend={{
          label: 'POV unboxing transition',
          source_label: 'TikTok inspiration page',
          sanitized_guidance: 'POV unboxing transition',
          screened_out_claims: [],
          role: 'maker_angle_guidance_only',
          guidance_only: true,
          fact_source: false,
        }}
      />,
    );
    expect(html).toContain("data-testid=\"receipt-trend-guidance\"");
    expect(html).toContain('POV unboxing transition');
    expect(html).toContain('TikTok inspiration page');
    expect(html).toContain('Maker angle guidance only, never a fact source');
  });

  it('renders nothing when no trend was attached', () => {
    expect(renderToStaticMarkup(<TrendGuidancePanel trend={null} />)).toBe('');
    expect(renderToStaticMarkup(<TrendGuidancePanel trend={{ label: '' }} />)).toBe('');
  });
});
