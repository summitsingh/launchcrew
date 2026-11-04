'use client';
import { Textarea } from '@/components/ui/textarea';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';


export interface TrendFormatInput {
  label: string;
  source: string;
}

export const EMPTY_TREND_FORMAT: TrendFormatInput = {
  label: '',
  source: '',
};

export const TREND_SOURCE_PRESETS = [
  'TikTok inspiration page',
  'Named creator format',
  'Seasonal format',
];

/** Build the API trend payload from picker state. Null when no trend entered. */
export function buildTrendFormatPayload(input: TrendFormatInput): { trend_label: string; trend_source: string } | null {
  const label = input.label.trim();
  const source = input.source.trim();
  if (!label && !source) return null;
  if (!label) return null;
  return { trend_label: label, trend_source: source };
}

/** True when the picker holds a label without a source label (blocked submit). */
export function trendSourceMissing(input: TrendFormatInput): boolean {
  return input.label.trim().length > 0 && input.source.trim().length === 0;
}

/** Optional trend picker for run creation and campaign day configuration. */
export function TrendFormatPicker({
  value,
  onChange,
}: {
  value: TrendFormatInput;
  onChange: (next: TrendFormatInput) => void;
}) {
  const set = (patch: Partial<TrendFormatInput>) => onChange({ ...value, ...patch });
  const missing = trendSourceMissing(value);
  return (
    <fieldset>
      <legend>Trend format (optional)</legend>
      <p className="hint">
        Trends are Maker angle guidance only, never a fact source. Superlatives and banned claims are screened out
        before the Maker sees them.
      </p>
      <label htmlFor="trend-format-label">Trend Format Description</label>
      <Textarea appearance="workspace"
        id="trend-format-label"
        data-testid="trend-format-label-input"
        rows={2}
        value={value.label}
        onChange={e => set({ label: e.target.value })}
        placeholder="Short description of a format or angle seen trending"
        maxLength={280}
      />
      <label htmlFor="trend-format-source">Required Source Label</label>
      <Input appearance="workspace"
        id="trend-format-source"
        data-testid="trend-format-source-input"
        value={value.source}
        onChange={e => set({ source: e.target.value })}
        placeholder="Where the trend was seen"
        maxLength={200}
      />
      <div className="queue-actions" aria-label="Trend source presets">
        {TREND_SOURCE_PRESETS.map(preset => (
          <Button appearance="workspace" key={preset} type="button" className="chip" onClick={() => set({ source: preset })}>
            {preset}
          </Button>
        ))}
      </div>
      {missing && (
        <p role="alert" className="hint">
          A trend description needs its source label before this pack can start.
        </p>
      )}
    </fieldset>
  );
}

export interface TrendGuidance {
  label?: string | null;
  source_label?: string | null;
  sanitized_guidance?: string | null;
  screened_out_claims?: string[] | null;
  role?: string | null;
  guidance_only?: boolean | null;
  fact_source?: boolean | null;
}

/** Recorded trend guidance on a run receipt. Renders nothing when no trend attached. */
export function TrendGuidancePanel({ trend }: { trend: TrendGuidance | null | undefined }) {
  if (!trend || typeof trend !== 'object') return null;
  const label = typeof trend.label === 'string' ? trend.label.trim() : '';
  if (!label) return null;
  const source = typeof trend.source_label === 'string' ? trend.source_label : '';
  const guidance = typeof trend.sanitized_guidance === 'string' && trend.sanitized_guidance ? trend.sanitized_guidance : label;
  const screened = Array.isArray(trend.screened_out_claims)
    ? trend.screened_out_claims.filter(item => typeof item === 'string' && item)
    : [];
  return (
    <div>
      <h3>Trend guidance</h3>
      <p className="hint" data-testid="receipt-trend-guidance">
        {guidance} · Source: {source || 'unavailable'} · Maker angle guidance only, never a fact source
        {screened.length > 0 && ` · Screened out: ${screened.join(', ')}`}
      </p>
    </div>
  );
}
