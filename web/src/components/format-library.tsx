'use client';
import { Card } from '@/components/ui/card';
import { Badge as WorkspaceBadge } from '@/components/ui/badge';
import { NativeSelect } from '@/components/ui/native-select';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';

import { useState } from 'react';
import { Button } from '@/components/ui/button';

export type FormatKind = 'feed_carousel' | 'reel_script' | 'story_sequence' | 'single_image';

export interface FormatSpecInput {
  format_kind: FormatKind | '';
  frame_count: string;
  aspect_ratio: string;
  hook_text: string;
  shots: string;
  frame_ideas: string;
  target_surface: string;
}

export const EMPTY_FORMAT_SPEC: FormatSpecInput = {
  format_kind: '',
  frame_count: '',
  aspect_ratio: '',
  hook_text: '',
  shots: '',
  frame_ideas: '',
  target_surface: '',
};

/** Split a comma or newline separated input into trimmed non-empty items. */
export function splitListInput(value: string): string[] {
  return value
    .split(/[\n,]+/)
    .map(part => part.trim())
    .filter(part => part.length > 0);
}

/** Build an API format_spec object from picker state. Null when no format chosen. */
export function buildFormatSpecPayload(input: FormatSpecInput): Record<string, unknown> | null {
  if (!input.format_kind) return null;
  const payload: Record<string, unknown> = { format_kind: input.format_kind };
  if (input.format_kind === 'feed_carousel') {
    const count = parseInt(input.frame_count, 10);
    if (Number.isFinite(count)) payload.frame_count = count;
    if (input.aspect_ratio.trim()) payload.aspect_ratio = input.aspect_ratio.trim();
  }
  if (input.format_kind === 'reel_script') {
    if (input.hook_text.trim()) payload.hook_text = input.hook_text.trim();
    const shots = splitListInput(input.shots);
    if (shots.length > 0) payload.shots = shots;
  }
  if (input.format_kind === 'story_sequence') {
    const ideas = splitListInput(input.frame_ideas);
    if (ideas.length > 0) payload.frame_ideas = ideas;
  }
  if (input.format_kind === 'single_image') {
    if (input.target_surface.trim()) payload.target_surface = input.target_surface.trim();
  }
  return payload;
}

/** Merge brand kit fields into a voice profile content JSON string. Throws on invalid JSON. */
export function mergeBrandKitIntoContent(
  contentJson: string,
  kit: { brand_colors: string; fonts: string; logo_reference: string; banned_rules: string },
): string {
  let parsed: Record<string, unknown>;
  try {
    parsed = JSON.parse(contentJson || '{}');
  } catch {
    throw new Error('Content is not valid JSON.');
  }
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
    throw new Error('Content must be a JSON object.');
  }
  const next: Record<string, unknown> = { ...parsed };
  const colors = splitListInput(kit.brand_colors);
  const fonts = splitListInput(kit.fonts);
  const rules = splitListInput(kit.banned_rules);
  if (colors.length > 0) next.brand_colors = colors;
  if (fonts.length > 0) next.fonts = fonts;
  if (kit.logo_reference.trim()) next.logo_reference = kit.logo_reference.trim();
  if (rules.length > 0) next.banned_rules = rules;
  return JSON.stringify(next, null, 2);
}

export interface FormatDefinition {
  format: string;
  label: string;
  rule: string;
}

export interface ChannelCapability {
  channel: string;
  allowed_formats: string[];
  caption_limit: number;
  media_constraints: { aspect_ratios: string[]; min_frames: number; max_frames: number };
}

/** Format library rules plus the per-channel capabilities table. Pure display, no posting. */
export function FormatLibraryPanel({
  formats,
  capabilities,
}: {
  formats: FormatDefinition[];
  capabilities: ChannelCapability[];
}) {
  return (
    <Card appearance="workspace" asChild ><section className="panel" aria-label="Format library and channel capabilities">
      <p className="eyebrow">FORMAT LIBRARY</p>
      <h2>Formats and channel capabilities</h2>
      <p className="hint">
        Checker enforces these format rules. A failed format check blocks approval with a plain reason naming the rule.
      </p>
      <h3>Format rules</h3>
      {formats.length === 0 && <p className="hint">No formats listed.</p>}
      <ul className="scout-list">
        {formats.map(item => (
          <li key={item.format} className="scout-fact">
            <div className="scout-row">
              <span>{item.label}</span>
              <WorkspaceBadge appearance="workspace" asChild ><span className="badge pending">{item.format}</span></WorkspaceBadge>
            </div>
            <p className="hint">{item.rule}</p>
          </li>
        ))}
      </ul>
      <h3>Per-channel capabilities</h3>
      {capabilities.length === 0 && <p className="hint">No channel capabilities listed.</p>}
      <ul className="scout-list">
        {capabilities.map(row => (
          <li key={row.channel} className="scout-fact">
            <div className="scout-row">
              <span>{row.channel}</span>
              <WorkspaceBadge appearance="workspace" asChild ><span className="badge pending">limit {row.caption_limit}</span></WorkspaceBadge>
            </div>
            <p className="hint">
              Formats: {row.allowed_formats.join(', ') || 'none'} · Caption limit: {row.caption_limit} · Ratios:{' '}
              {(row.media_constraints.aspect_ratios || []).join(', ') || 'none'} · Frames:{' '}
              {row.media_constraints.min_frames} to {row.media_constraints.max_frames}
            </p>
          </li>
        ))}
      </ul>
    </section></Card>
  );
}

/** Picker for the S2 format spec sent with run creation. Display only until submitted. */
export function FormatSpecPicker({
  value,
  onChange,
}: {
  value: FormatSpecInput;
  onChange: (next: FormatSpecInput) => void;
}) {
  const set = (patch: Partial<FormatSpecInput>) => onChange({ ...value, ...patch });
  return (
    <fieldset>
      <legend>Format (optional)</legend>
      <p className="hint">
        Pick a format to enforce its Checker rule on this run. A failed format check blocks approval with a plain reason.
      </p>
      <label htmlFor="format-kind">Format</label>
      <NativeSelect appearance="workspace" id="format-kind" value={value.format_kind} onChange={e => set({ format_kind: e.target.value as FormatKind | '' })}>
        <option value="">No format check</option>
        <option value="feed_carousel">Feed carousel (5 to 10 frames at 4:5)</option>
        <option value="reel_script">Reel script (hook under 140 characters, 1 or more shots)</option>
        <option value="story_sequence">Story sequence (3 to 6 frames, one idea per frame)</option>
        <option value="single_image">Single image (stories and ads drafts, never feed posts)</option>
      </NativeSelect>
      {value.format_kind === 'feed_carousel' && (
        <>
          <label htmlFor="format-frames">Frame count</label>
          <Input appearance="workspace" id="format-frames" inputMode="numeric" value={value.frame_count} onChange={e => set({ frame_count: e.target.value })} />
          <label htmlFor="format-aspect">Aspect ratio</label>
          <Input appearance="workspace" id="format-aspect" value={value.aspect_ratio} onChange={e => set({ aspect_ratio: e.target.value })} placeholder="4:5" />
        </>
      )}
      {value.format_kind === 'reel_script' && (
        <>
          <label htmlFor="format-hook">Reel hook (under 140 characters)</label>
          <Textarea appearance="workspace" id="format-hook" rows={2} value={value.hook_text} onChange={e => set({ hook_text: e.target.value })} />
          <label htmlFor="format-shots">Shots (one per line)</label>
          <Textarea appearance="workspace" id="format-shots" rows={3} value={value.shots} onChange={e => set({ shots: e.target.value })} />
        </>
      )}
      {value.format_kind === 'story_sequence' && (
        <>
          <label htmlFor="format-ideas">Frame ideas (one per line, 3 to 6)</label>
          <Textarea appearance="workspace" id="format-ideas" rows={4} value={value.frame_ideas} onChange={e => set({ frame_ideas: e.target.value })} />
        </>
      )}
      {value.format_kind === 'single_image' && (
        <>
          <label htmlFor="format-surface">Target surface</label>
          <NativeSelect appearance="workspace" id="format-surface" value={value.target_surface} onChange={e => set({ target_surface: e.target.value })}>
            <option value="">Choose a surface</option>
            <option value="stories">Stories</option>
            <option value="ads">Ads drafts</option>
            <option value="feed">Feed posts (blocked)</option>
          </NativeSelect>
        </>
      )}
    </fieldset>
  );
}

/** Brand kit inputs merged into the voice profile content JSON. */
export function BrandKitForm({
  content,
  onContent,
  notify,
}: {
  content: string;
  onContent: (next: string) => void;
  notify: (text: string) => void;
}) {
  const [colors, setColors] = useState('');
  const [fonts, setFonts] = useState('');
  const [logo, setLogo] = useState('');
  const [rules, setRules] = useState('');
  return (
    <div>
      <p className="hint">
        Brand kit (optional): brand colors (hex or named, comma separated), fonts (comma separated), logo reference
        (asset reference string), and banned rules (comma separated). Saved with the voice profile; the receipt records
        the computed kit version and digest, so any change alters the version.
      </p>
      <label htmlFor="brand-colors">Brand colors</label>
      <Input appearance="workspace" id="brand-colors" value={colors} onChange={e => setColors(e.target.value)} placeholder="#ff0000, ink" />
      <label htmlFor="brand-fonts">Fonts</label>
      <Input appearance="workspace" id="brand-fonts" value={fonts} onChange={e => setFonts(e.target.value)} placeholder="Inter, Grotesk" />
      <label htmlFor="brand-logo">Logo reference</label>
      <Input appearance="workspace" id="brand-logo" value={logo} onChange={e => setLogo(e.target.value)} placeholder="assets/logo.png" />
      <label htmlFor="brand-rules">Banned rules</label>
      <Input appearance="workspace" id="brand-rules" value={rules} onChange={e => setRules(e.target.value)} placeholder="hype, superlative" />
      <div className="queue-actions">
        <Button
          type="button"
          variant="outline"
          onClick={() => {
            try {
              onContent(mergeBrandKitIntoContent(content, { brand_colors: colors, fonts, logo_reference: logo, banned_rules: rules }));
              notify('Brand kit merged into the voice profile content.');
            } catch (error) {
              notify(error instanceof Error ? error.message : 'Brand kit merge failed.');
            }
          }}
        >
          Add brand kit to JSON
        </Button>
      </div>
    </div>
  );
}

/** Brand kit version recorded on a run receipt, if any. */
export function BrandKitPanel({
  brandKit,
}: {
  brandKit: {
    version?: string | null;
    digest?: string | null;
    brand_colors?: string[] | null;
    fonts?: string[] | null;
    logo_reference?: string | null;
    banned_rules?: string[] | null;
  } | null;
}) {
  if (!brandKit || typeof brandKit !== 'object') return null;
  return (
    <div>
      <h3>Brand kit</h3>
      <p className="hint" data-testid="receipt-brand-kit">
        Version: {brandKit.version || 'unavailable'} · Digest: {(brandKit.digest || '').slice(0, 16) || 'unavailable'}
        {' · '}Colors: {(brandKit.brand_colors || []).join(', ') || 'none'}
        {' · '}Fonts: {(brandKit.fonts || []).join(', ') || 'none'}
        {' · '}Logo: {brandKit.logo_reference || 'none'}
        {' · '}Banned rules: {(brandKit.banned_rules || []).join(', ') || 'none'}
      </p>
    </div>
  );
}

/** Format check recorded on a run receipt, if any. */
export function FormatCheckPanel({
  formatCheck,
}: {
  formatCheck: { passed?: boolean | null; format?: string | null; reasons?: string[] | null } | null;
}) {
  if (!formatCheck || typeof formatCheck !== 'object') return null;
  const reasons = Array.isArray(formatCheck.reasons) ? formatCheck.reasons.filter(r => typeof r === 'string' && r) : [];
  return (
    <div>
      <h3>Format check</h3>
      <p className="hint" data-testid="receipt-format-check">
        Format: {formatCheck.format || 'none'} · {formatCheck.passed ? 'Passed' : 'Blocked approval'}
        {reasons.length > 0 && ` · ${reasons.join(' ')}`}
      </p>
    </div>
  );
}
