import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import {
  BrandKitPanel,
  FormatCheckPanel,
  FormatLibraryPanel,
  buildFormatSpecPayload,
  mergeBrandKitIntoContent,
  splitListInput,
} from '../src/components/format-library';

const FORMATS = [
  { format: 'feed_carousel', label: 'Feed carousel', rule: 'Feed carousel needs 5 to 10 frames at 4:5 aspect ratio.' },
  { format: 'reel_script', label: 'Reel script', rule: 'Reel script needs a hook under 140 characters and a shot list with at least 1 shot.' },
  { format: 'story_sequence', label: 'Story sequence', rule: 'Story sequence needs 3 to 6 frames with one idea per frame.' },
  { format: 'single_image', label: 'Single image', rule: 'Single image is allowed for stories and ads drafts, never for feed posts.' },
];

const CAPABILITIES = [
  { channel: 'instagram', allowed_formats: ['feed_carousel', 'reel_script', 'story_sequence', 'single_image'], caption_limit: 2200, media_constraints: { aspect_ratios: ['4:5', '1:1', '9:16'], min_frames: 1, max_frames: 10 } },
  { channel: 'facebook', allowed_formats: ['feed_carousel', 'reel_script', 'story_sequence', 'single_image'], caption_limit: 2000, media_constraints: { aspect_ratios: ['4:5', '1:1', '16:9'], min_frames: 1, max_frames: 10 } },
  { channel: 'threads', allowed_formats: ['single_image', 'story_sequence', 'feed_carousel'], caption_limit: 500, media_constraints: { aspect_ratios: ['4:5', '1:1'], min_frames: 1, max_frames: 10 } },
  { channel: 'x', allowed_formats: ['single_image'], caption_limit: 280, media_constraints: { aspect_ratios: ['16:9', '1:1', '4:5'], min_frames: 1, max_frames: 4 } },
  { channel: 'linkedin', allowed_formats: ['single_image', 'feed_carousel'], caption_limit: 3000, media_constraints: { aspect_ratios: ['4:5', '1:1', '16:9'], min_frames: 1, max_frames: 10 } },
  { channel: 'tiktok', allowed_formats: ['reel_script', 'single_image'], caption_limit: 2200, media_constraints: { aspect_ratios: ['9:16'], min_frames: 1, max_frames: 10 } },
  { channel: 'pinterest', allowed_formats: ['single_image', 'feed_carousel'], caption_limit: 500, media_constraints: { aspect_ratios: ['4:5', '1:1'], min_frames: 1, max_frames: 10 } },
  { channel: 'email', allowed_formats: ['single_image'], caption_limit: 10000, media_constraints: { aspect_ratios: [], min_frames: 0, max_frames: 0 } },
  { channel: 'shopify', allowed_formats: ['single_image'], caption_limit: 2000, media_constraints: { aspect_ratios: ['4:5', '1:1'], min_frames: 0, max_frames: 0 } },
];

describe('S2 format library panel', () => {
  it('names the carousel rule: 5 to 10 frames at 4:5', () => {
    const html = renderToStaticMarkup(<FormatLibraryPanel formats={FORMATS} capabilities={CAPABILITIES} />);
    expect(html).toContain('5 to 10 frames at 4:5');
    expect(html).toContain('feed_carousel');
  });

  it('names the reel hook limit and the story frame rule', () => {
    const html = renderToStaticMarkup(<FormatLibraryPanel formats={FORMATS} capabilities={CAPABILITIES} />);
    expect(html).toContain('under 140 characters');
    expect(html).toContain('3 to 6 frames');
    expect(html).toContain('one idea per frame');
  });

  it('names the single-image surface rule: never for feed posts', () => {
    const html = renderToStaticMarkup(<FormatLibraryPanel formats={FORMATS} capabilities={CAPABILITIES} />);
    expect(html).toContain('never for feed posts');
  });

  it('lists all nine channel capabilities with the X limit', () => {
    const html = renderToStaticMarkup(<FormatLibraryPanel formats={FORMATS} capabilities={CAPABILITIES} />);
    for (const channel of ['instagram', 'facebook', 'threads', 'x', 'linkedin', 'tiktok', 'pinterest', 'email', 'shopify']) {
      expect(html).toContain(channel);
    }
    expect(html).toContain('limit 280');
    expect(html).toContain('Per-channel capabilities');
  });
});

describe('S2 format spec payload', () => {
  it('builds a 6-frame 4:5 feed carousel spec', () => {
    expect(
      buildFormatSpecPayload({ format_kind: 'feed_carousel', frame_count: '6', aspect_ratio: '4:5', hook_text: '', shots: '', frame_ideas: '', target_surface: '' }),
    ).toEqual({ format_kind: 'feed_carousel', frame_count: 6, aspect_ratio: '4:5' });
  });

  it('builds a 1-frame feed spec so the Checker can block it', () => {
    expect(
      buildFormatSpecPayload({ format_kind: 'feed_carousel', frame_count: '1', aspect_ratio: '4:5', hook_text: '', shots: '', frame_ideas: '', target_surface: '' }),
    ).toEqual({ format_kind: 'feed_carousel', frame_count: 1, aspect_ratio: '4:5' });
  });

  it('returns null when no format is chosen', () => {
    expect(
      buildFormatSpecPayload({ format_kind: '', frame_count: '', aspect_ratio: '', hook_text: '', shots: '', frame_ideas: '', target_surface: '' }),
    ).toBeNull();
  });

  it('splits list inputs on commas and newlines', () => {
    expect(splitListInput('navy, copper\nink')).toEqual(['navy', 'copper', 'ink']);
  });
});

describe('S2 brand kit panels', () => {
  it('merges brand kit fields into voice profile JSON', () => {
    const next = mergeBrandKitIntoContent(
      JSON.stringify({ examples: [], banned_terms: [] }),
      { brand_colors: '#ff0000, ink', fonts: 'Inter', logo_reference: 'assets/logo.png', banned_rules: 'hype' },
    );
    const parsed = JSON.parse(next) as Record<string, unknown>;
    expect(parsed.brand_colors).toEqual(['#ff0000', 'ink']);
    expect(parsed.fonts).toEqual(['Inter']);
    expect(parsed.logo_reference).toBe('assets/logo.png');
    expect(parsed.banned_rules).toEqual(['hype']);
  });

  it('rejects invalid JSON content with a plain error', () => {
    expect(() =>
      mergeBrandKitIntoContent('not json', { brand_colors: '', fonts: '', logo_reference: '', banned_rules: '' }),
    ).toThrow('not valid JSON');
  });

  it('shows the computed kit version and digest from the receipt', () => {
    const html = renderToStaticMarkup(
      <BrandKitPanel
        brandKit={{ version: 'brand-kit/v1:abc123', digest: 'abc123def456', brand_colors: ['#ff0000'], fonts: ['Inter'], logo_reference: 'assets/logo.png', banned_rules: ['hype'] }}
      />,
    );
    expect(html).toContain('brand-kit/v1:abc123');
    expect(html).toContain('#ff0000');
    expect(html).toContain('Inter');
  });

  it('renders nothing without a brand kit', () => {
    expect(renderToStaticMarkup(<BrandKitPanel brandKit={null} />)).toBe('');
  });
});

describe('S2 format check panel', () => {
  it('names the blocking rule on a failed check', () => {
    const html = renderToStaticMarkup(
      <FormatCheckPanel formatCheck={{ passed: false, format: 'feed_carousel', reasons: ['Blocked: a 1-frame feed post is not a carousel; the carousel rule needs 5 to 10 frames at 4:5.'] }} />,
    );
    expect(html).toContain('Blocked approval');
    expect(html).toContain('5 to 10 frames at 4:5');
  });

  it('passes a 6-frame carousel check', () => {
    const html = renderToStaticMarkup(
      <FormatCheckPanel formatCheck={{ passed: true, format: 'feed_carousel', reasons: [] }} />,
    );
    expect(html).toContain('Passed');
  });
});
