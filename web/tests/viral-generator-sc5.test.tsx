import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { CalendarView } from '../src/components/calendar-view';
import {
  ViralGeneratorPanel,
  ViralGenerationCard,
  ViralCreditsBadge,
  describeViralMode,
  generationFrames,
  viralCheckerLine,
  viralCreditWarning,
  type ViralGeneration,
} from '../src/components/viral-generator-panel';

function provider(children: React.ReactNode) {
  return renderToStaticMarkup(<QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>);
}

function generation(partial: Partial<ViralGeneration> = {}): ViralGeneration {
  return {
    id: 'vgen_test', workspace_id: 'demo', output_format: 'carousel', media_mode: 'screenshots',
    asset_ids: [], confirmed_facts: 'Our Trail Wallet costs $49.',
    run_id: 'run_abc', slot_id: null, credits_charged: 1, remaining_credits_after: 9,
    media_provenance: 'owner_upload_only', frames_or_scenes: [], checker_passed: true,
    approval_state: 'pending_approval', run_status: 'completed', checker_decision: 'pass',
    created_at: null, ...partial,
  } as ViralGeneration;
}

describe('viral mode helpers', () => {
  it('labels both owner media modes', () => {
    expect(describeViralMode('screenshots')).toContain('Carousel');
    expect(describeViralMode('screen_recording')).toContain('Short Video');
  });
  it('warns only when credits hit zero', () => {
    expect(viralCreditWarning({ workspace_id: 'demo', remaining_credits: 3, total_used_credits: 0 })).toBeNull();
    expect(viralCreditWarning({ workspace_id: 'demo', remaining_credits: 0, total_used_credits: 10 })).toContain('0 credits remaining');
    expect(viralCreditWarning(undefined)).toBeNull();
  });
  it('reads frames or scenes as records', () => {
    const entry = generation({ frames_or_scenes: [{ text: 'Frame 1', aspect_ratio: '4:5' }] });
    expect(generationFrames(entry)).toHaveLength(1);
    expect(generationFrames(generation({}))).toEqual([]);
    expect(viralCheckerLine(entry)).toBe('Checker: pass');
    expect(viralCheckerLine(generation({ checker_passed: false, checker_decision: 'fail' }))).toBe('Checker: fail');
  });
});

describe('viral generator panel', () => {
  it('renders the panel shell with credits, mode toggle, and generate button', () => {
    const html = provider(<ViralGeneratorPanel />);
    expect(html).toContain('data-testid="viral-generator-panel"');
    expect(html).toContain('data-testid="viral-credits-remaining"');
    expect(html).toContain('data-testid="viral-generate-btn"');
    expect(html).toContain('Generate Pack');
    expect(html).toContain('Owner media only');
    expect(html).toContain('3 to 10 Screenshots to Carousel');
    expect(html).toContain('1 Screen Recording to Short Video');
    expect(html).toContain('Confirmed facts');
  });
  it('shows the visible credit count and the zero balance warning', () => {
    const html = provider(<ViralCreditsBadge credits={{ workspace_id: 'demo', remaining_credits: 7, total_used_credits: 3 }} />);
    expect(html).toContain('Credits remaining: 7');
    const empty = provider(<ViralCreditsBadge credits={{ workspace_id: 'demo', remaining_credits: 0, total_used_credits: 10 }} />);
    expect(empty).toContain('0 credits remaining');
  });
  it('shows frame text, checker status, and the linked approval-bound run', () => {
    const html = provider(<ViralGenerationCard generation={generation({
      frames_or_scenes: [
        { text: 'Frame 1 of 5: Our Trail Wallet costs $49.', aspect_ratio: '4:5' },
        { text: 'Frame 2 of 5: Free shipping in 3 days.', aspect_ratio: '4:5' },
      ],
    })} />);
    expect(html).toContain('Frame 1 of 5');
    expect(html).toContain('Checker: pass');
    expect(html).toContain('run_abc');
    expect(html).toContain('pending_approval');
  });
});

describe('calendar view integration', () => {
  it('embeds the viral generator panel', () => {
    const html = provider(<CalendarView />);
    expect(html).toContain('data-testid="viral-generator-panel"');
  });
});
