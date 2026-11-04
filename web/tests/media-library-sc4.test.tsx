import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { CalendarView } from '../src/components/calendar-view';
import {
  MediaAssetCard,
  MediaDerivativeList,
  MediaLibraryPanel,
  MediaUploadForm,
  SlotMediaSection,
  derivativeForChannel,
  mediaWarning,
  type MediaAsset,
  type SlotMediaAttachment,
} from '../src/components/media-library';

function provider(children: React.ReactNode) {
  return renderToStaticMarkup(<QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>);
}

function asset(partial: Partial<MediaAsset> & { id: string }): MediaAsset {
  return {
    filename: 'hero.png', media_type: 'image', mime_type: 'image/png',
    width: 1080, height: 1350, aspect_ratio: '4:5', duration_seconds: null,
    sha256_digest: 'abc123originaldigest', derivatives: {}, format_facts: {}, created_at: null,
    ...partial,
  };
}

const derivatives = {
  '4:5': { derivative_key: '4:5', aspect_ratio: '4:5', width: 1080, height: 1350, derived_from_id: 'media_1', original_preserved: true, sha256_digest: 'feeddigest' },
  '1:1': { derivative_key: '1:1', aspect_ratio: '1:1', width: 1080, height: 1080, derived_from_id: 'media_1', original_preserved: true, sha256_digest: 'squareddigest' },
  '9:16': { derivative_key: '9:16', aspect_ratio: '9:16', width: 608, height: 1080, derived_from_id: 'media_1', original_preserved: true, sha256_digest: 'reeldigest' },
  '16:9': { derivative_key: '16:9', aspect_ratio: '16:9', width: 1080, height: 608, derived_from_id: 'media_1', original_preserved: true, sha256_digest: 'widedigest' },
};

function attachment(partial: Partial<SlotMediaAttachment> & { id?: string }): SlotMediaAttachment {
  return {
    id: 'matt_1', slot_id: 'slot_1', asset_id: 'media_1', channels: ['instagram', 'x'],
    channel_derivatives: { instagram: derivatives['4:5'], x: derivatives['16:9'] },
    use_original_without_derivative: false,
    format_validation: { passed: true, reasons: [], checked_aspect_ratio: '4:5', required_aspect_ratio: '4:5' },
    asset: {},
    ...partial,
  };
}

describe('channel derivative helpers', () => {
  it('binds each channel to its matching derivative', () => {
    const entry = attachment({});
    expect(derivativeForChannel(entry, 'instagram')?.aspect_ratio).toBe('4:5');
    expect(derivativeForChannel(entry, 'x')?.aspect_ratio).toBe('16:9');
    expect(derivativeForChannel(entry, 'tiktok')).toBeNull();
  });
  it('keeps the original when attached without a derivative', () => {
    const entry = attachment({ use_original_without_derivative: true, channel_derivatives: {} });
    expect(derivativeForChannel(entry, 'instagram')).toBeNull();
  });
  it('surfaces the first Checker wrong-aspect reason', () => {
    expect(mediaWarning({ passed: true, reasons: [] })).toBeNull();
    expect(mediaWarning({ passed: false, reasons: [] })).toBeNull();
    expect(mediaWarning({
      passed: false,
      reasons: ['Feed slot media aspect ratio 16:9 does not match required 4:5 aspect ratio'],
    })).toContain('16:9');
  });
});

describe('media library panel', () => {
  it('renders the upload button and asset format facts', () => {
    const html = provider(<MediaLibraryPanel />);
    expect(html).toContain('data-testid="media-library-panel"');
    expect(html).toContain('data-testid="media-upload-btn"');
    expect(html).toContain('Upload media asset');
    expect(html).toContain('Upload once');
  });
  it('offers a real file input so uploads preserve bytes', () => {
    const html = provider(<MediaUploadForm />);
    expect(html).toContain('data-testid="media-file-input"');
    expect(html).toContain('type="file"');
    expect(html).toContain('image/*');
    expect(html).toContain('preserve its bytes');
  });
  it('shows recorded dimensions, aspect, and the preserved original digest', () => {
    const html = provider(<MediaAssetCard asset={asset({ id: 'media_1', derivatives })} />);
    expect(html).toContain('hero.png');
    expect(html).toContain('1080');
    expect(html).toContain('4:5');
    expect(html).toContain('Original digest preserved');
  });
  it('highlights the 4:5 feed crop derivative', () => {
    const html = provider(<MediaDerivativeList asset={asset({ id: 'media_1', derivatives })} />);
    expect(html).toContain('data-testid="media-derivative-4x5"');
    expect(html).toContain('4:5 feed crop');
    expect(html).toContain('9:16');
  });
});

describe('slot media attach and warning', () => {
  it('names each channel derivative and the Checker wrong-aspect warning', () => {
    const warning = 'Feed slot media aspect ratio 16:9 does not match required 4:5 aspect ratio';
    const wrong = attachment({
      use_original_without_derivative: true,
      channel_derivatives: {},
      format_validation: { passed: false, reasons: [warning], checked_aspect_ratio: '16:9', required_aspect_ratio: '4:5' },
    });
    const record = derivativeForChannel(wrong, 'instagram');
    expect(record).toBeNull();
    expect(mediaWarning(wrong.format_validation)).toBe(warning);
  });
  it('renders the slot media section shell', () => {
    const html = provider(<SlotMediaSection slotId="slot_1" assets={[asset({ id: 'media_1' })]} />);
    expect(html).toContain('Slot media');
    expect(html).toContain('Attach media');
  });
});

describe('calendar view integration', () => {
  it('embeds the media library panel', () => {
    const html = provider(<CalendarView />);
    expect(html).toContain('data-testid="media-library-panel"');
  });
});
