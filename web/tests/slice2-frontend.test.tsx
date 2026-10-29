import { describe, it, expect } from 'vitest';
import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { renderToStaticMarkup } from 'react-dom/server';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import {
  CampaignDayCard,
  CampaignView,
  ConfirmedFactsBlock,
  RunRef,
  SEED_CLAIM_DEFAULT,
  SEED_CLAIM_LABEL,
  SupportedPoliciesHint,
  exportReceiptToMarkdown,
  safeExportFilename,
  terminalNotice,
} from '../src/components/v2-views';
import type { components } from '../src/lib/schema';

type Receipt = components['schemas']['Receipt'];
type Day = components['schemas']['CampaignDay'];

const day: Day = { day: 1, run_id: 'run_demo', approval_state: 'pending_approval', status: 'completed', checker_v2_blocked_count: 0, idea: 'Demo wallet', angle: 'Origin story', brief: 'Designed in Texas for Austin commuters', draft_v2_post: 'Vegan leather wallet, designed in Texas.', revision: 0 };
const noop = () => {};

function packReceipt(overrides: Record<string, unknown> = {}): Receipt {
  return {
    run_id: 'run_demo1',
    idea: 'Demo wallet',
    status: 'completed',
    approval_state: 'approved_for_export',
    revision: 1,
    approved_revision: 1,
    approvals: [{ action: 'approve', approved_by: 'demo_placeholder', revision: 1, timestamp: '2026-10-29T00:00:00+00:00' }],
    exported_draft: { post: 'Approved post', email: 'Approved email' },
    exported_revision: 1,
    maker_draft_v2: { post: 'Maker post', email: 'Maker email', claims: [] },
    human_draft: null,
    checker_v2: { blocked_claims: [], blocked_count: 0, revision_instructions: [], verified_count: 3 },
    human_check: null,
    summary: { submit_attempted: false },
    ...overrides,
  } as unknown as Receipt;
}

function frontendSources(): string {
  let combined = '';
  function walk(dir: string) {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const path = join(dir, entry.name);
      if (entry.isDirectory()) { walk(path); continue; }
      if (!/\.(ts|tsx|css)$/.test(path)) continue;
      combined += `\n${readFileSync(path, 'utf8')}`;
    }
  }
  walk('src');
  return combined;
}

describe('slice 2 terminal receipt reconciliation', () => {
  it('replaces a stale Pack started notice only from terminal receipt status', () => {
    const started = 'Pack started. Each stage lands below as the pipeline reaches it; review unlocks with the final receipt.';
    expect(terminalNotice(started, 'run_demo1', 'completed')).toBe('Pack ready for review: run_demo1.');
    expect(terminalNotice(started, 'run_demo1', 'failed')).toBe('Pack stopped safely: run_demo1. See the failed run record.');
    expect(terminalNotice(started, 'run_demo1', 'running')).toBe(started);
    expect(terminalNotice(started, 'run_demo1', undefined)).toBe(started);
    expect(terminalNotice('Approved run_demo1 for export.', 'run_demo1', 'completed')).toBe('Approved run_demo1 for export.');
    expect(terminalNotice('', 'run_demo1', 'completed')).toBe('');
  });

  it('wires the desk notice effect to receipt status, never stage counts', () => {
    const source = readFileSync('src/app/page.tsx', 'utf8');
    expect(source).toContain('terminalNotice(current, active, runStatus)');
    expect(source).toContain('run.data?.status');
  });
});

describe('slice 2 seed intent', () => {
  it('shares one opt-in-off default across brief and campaign', () => {
    expect(SEED_CLAIM_DEFAULT).toBe(false);
    expect(SEED_CLAIM_LABEL).toBe('Include the unsupported claim demo');
    expect(readFileSync('src/app/page.tsx', 'utf8')).toContain('useState(SEED_CLAIM_DEFAULT)');
    expect(readFileSync('src/components/v2-views.tsx', 'utf8')).toContain('useState(SEED_CLAIM_DEFAULT)');
  });

  it('labels the seed as an explicit opt-in with receipt intent', () => {
    const html = renderToStaticMarkup(
      <QueryClientProvider client={new QueryClient()}><CampaignView profiles={[]} /></QueryClientProvider>,
    );
    expect(html).toContain('Include the unsupported claim demo');
    expect(html).toContain('Opt-in demo only');
    expect(html).toContain('Leave unchecked for a normal week');
    const brief = readFileSync('src/app/page.tsx', 'utf8');
    expect(brief).toContain('SEED_CLAIM_HINT');
    expect(readFileSync('src/components/v2-views.tsx', 'utf8')).toContain('Leave unchecked for a normal run');
  });
});

describe('slice 2 review path and advanced navigation', () => {
  it('keeps primary step labels stable and fixes replay and campaign', () => {
    const source = readFileSync('src/app/page.tsx', 'utf8');
    for (const label of ['01 / BRIEF', '02 / CREW', '03 / REVIEW', '04 / APPROVAL', '05 / RECORD', '06 / MEMORY', '07 / REPLAY', '08 / CAMPAIGN']) {
      expect(source).toContain(label);
    }
  });

  it('hides agents, memory, replay and campaign behind an accessible toggle', () => {
    const source = readFileSync('src/app/page.tsx', 'utf8');
    expect(source).toContain('const [advanced, setAdvanced] = useState(false)');
    expect(source).toContain('aria-expanded={advanced}');
    expect(source).toContain('aria-controls="advanced-nav"');
    expect(source).toContain('aria-label="Advanced"');
    expect(source).toContain('Path: facts, draft, check, approve, then copy or export.');
    for (const view of ["item: 'Agents'", "item: 'Memory'", "item: 'Replay'", "item: 'Campaign'"]) {
      expect(source).toContain(view);
    }
  });

  it('names the Maker stage agent consistently', () => {
    const source = readFileSync('src/app/page.tsx', 'utf8') + readFileSync('src/components/v2-views.tsx', 'utf8');
    expect(source).toContain('Maker agent');
    expect(source).not.toContain('Maker profile');
  });
});

describe('slice 2 agent loading states', () => {
  it('shows explicit loading and error states on the campaign form', () => {
    const loading = renderToStaticMarkup(
      <QueryClientProvider client={new QueryClient()}><CampaignView profiles={[]} profilesPending /></QueryClientProvider>,
    );
    expect(loading).toContain('Loading agents...');
    expect(loading).toContain('disabled=""');
    const failed = renderToStaticMarkup(
      <QueryClientProvider client={new QueryClient()}><CampaignView profiles={[]} profilesError="Agents unavailable" /></QueryClientProvider>,
    );
    expect(failed).toContain('Agents unavailable');
    expect(failed).toContain('disabled=""');
  });

  it('disables dependent brief actions until agents load', () => {
    const source = readFileSync('src/app/page.tsx', 'utf8');
    expect(source).toContain('Loading agents...');
    expect(source).toContain('disabled={!agentsReady}');
    expect(source).toContain('disabled={create.isPending || !agentsReady}');
  });
});

describe('slice 2 policy and run reference labels', () => {
  it('renders readable policy labels with exact IDs inspectable', () => {
    const html = renderToStaticMarkup(<SupportedPoliciesHint />);
    for (const text of ['Superlatives', 'Price claims', 'veto_scope superlatives', 'veto_scope price_claims', 'Block superlatives', 'Block price claims', 'exact match', 'advisory only', 'cannot be relaxed', '/api/checker-policies', '<code']) {
      expect(html).toContain(text);
    }
    expect(renderToStaticMarkup(<SupportedPoliciesHint legacy />)).toContain('Legacy strictness');
  });

  it('keeps run references compact while full IDs stay inspectable', () => {
    const html = renderToStaticMarkup(<RunRef id="run_abc123" />);
    expect(html).toContain('run_abc123');
    expect(html).toContain('title="run_abc123"');
    expect(html).toContain('run-id compact');
    expect(readFileSync('src/app/globals.css', 'utf8')).toContain('text-overflow: ellipsis');
  });
});

describe('slice 2 approved-only export and copy', () => {
  it('shares one server export call across JSON, Markdown, and pack copy', () => {
    const desk = readFileSync('src/app/page.tsx', 'utf8');
    expect(desk.match(/mutationFn: runExport/g)?.length).toBe(3);
    const views = readFileSync('src/components/v2-views.tsx', 'utf8');
    expect(views.match(/mutationFn: dayExport/g)?.length).toBe(3);
  });

  it('shows Markdown and copy actions only on approved campaign days', () => {
    const approved = { ...day, approval_state: 'approved_for_export' as const };
    const pendingHtml = renderToStaticMarkup(<CampaignDayCard day={day} busy={false} approve={noop} download={noop} markdown={noop} copy={noop} />);
    expect(pendingHtml).toContain('Approve for export');
    expect(pendingHtml).not.toContain('Export Markdown');
    expect(pendingHtml).not.toContain('Copy pack');
    const approvedHtml = renderToStaticMarkup(<CampaignDayCard day={approved} busy={false} approve={noop} download={noop} markdown={noop} copy={noop} />);
    expect(approvedHtml).toContain('Export pack');
    expect(approvedHtml).toContain('Export Markdown');
    expect(approvedHtml).toContain('Copy pack');
    expect(renderToStaticMarkup(<CampaignDayCard day={approved} busy approve={noop} download={noop} markdown={noop} copy={noop} />)).toContain('disabled=""');
  });

  it('offers draft copy and approved pack actions on the desk', () => {
    const source = readFileSync('src/app/page.tsx', 'utf8');
    for (const label of ['Copy post', 'Copy email', 'Export Markdown', 'Copy pack', 'copyCurrentDraft', 'exportReceiptToMarkdown']) {
      expect(source).toContain(label);
    }
  });

  it('renders Markdown only from the server export artifact', () => {
    const markdown = exportReceiptToMarkdown(packReceipt());
    for (const text of ['# LaunchCrew launch pack', 'Demo wallet', 'run_demo1', 'Approved post', 'Approved email', 'demo_placeholder', 'Final blocked claims: 0', 'Not attempted.']) {
      expect(markdown).toContain(text);
    }
    expect(markdown).not.toContain('Maker post');
    const fallback = exportReceiptToMarkdown(packReceipt({ exported_draft: null, exported_revision: null, summary: {} }));
    expect(fallback).toContain('Maker post');
    expect(fallback).toContain('Unrecorded on this artifact.');
    const attempted = exportReceiptToMarkdown(packReceipt({ summary: { submit_attempted: true } }));
    expect(attempted).toContain('Attempted.');
  });

  it('names downloads safely for product and date', () => {
    expect(safeExportFilename('run_ABC_123', new Date('2026-10-29T12:00:00Z'), 'json')).toBe('launchcrew-pack-20261029-run-abc-123.json');
    expect(safeExportFilename('run_ABC_123', new Date('2026-10-29T12:00:00Z'), 'md')).toBe('launchcrew-pack-20261029-run-abc-123.md');
    expect(safeExportFilename('', new Date('2026-10-29T12:00:00Z'), 'json')).toBe('launchcrew-pack-20261029-run-unknown.json');
    expect(safeExportFilename('run_demo1', new Date('invalid'), 'json')).toBe('launchcrew-pack-nodate-run-demo1.json');
    expect(safeExportFilename('run_demo1', new Date('2026-10-29T12:00:00Z'), 'json')).toMatch(/^[a-z0-9.-]+\.[a-z]+$/);
  });
});

describe('slice 2 confirmed facts integration point', () => {
  it('stays empty on demo-only receipts and renders provided facts', () => {
    expect(renderToStaticMarkup(<ConfirmedFactsBlock receipt={{} as unknown as Receipt} />)).toBe('');
    const html = renderToStaticMarkup(
      <ConfirmedFactsBlock receipt={{ confirmed_facts: [{ claim: 'Vegan leather wallet', evidence: 'owner brief' }] } as unknown as Receipt} />,
    );
    expect(html).toContain('Owner-confirmed facts (1)');
    expect(html).toContain('Vegan leather wallet');
    expect(html).toContain('owner brief');
    expect(html).toContain('Confirmed');
  });
});

describe('slice 2 headers, assets, and metadata', () => {
  it('sets only frame protection and referrer policy at the Next layer', () => {
    const config = readFileSync('next.config.ts', 'utf8');
    expect(config).toContain('X-Frame-Options');
    expect(config).toContain('DENY');
    expect(config).toContain('Referrer-Policy');
    expect(config).toContain('strict-origin-when-cross-origin');
    expect(config).toContain('public, max-age=0, must-revalidate');
    expect(config).not.toContain('Strict-Transport-Security');
    expect(config).not.toContain('s-maxage');
  });

  it('ships robots, sitemap, and favicon with truthful content', () => {
    expect(readFileSync('public/robots.txt', 'utf8')).toContain('Allow: /');
    expect(readFileSync('public/robots.txt', 'utf8')).toContain('Sitemap:');
    expect(readFileSync('public/sitemap.xml', 'utf8')).toContain('<loc>https://launchcrew.summitsingh.com/</loc>');
    expect(readFileSync('public/favicon.svg', 'utf8')).toContain('<svg');
  });

  it('describes the demo honestly in document metadata', () => {
    const layout = readFileSync('src/app/layout.tsx', 'utf8');
    for (const text of ['openGraph', 'twitter', '/favicon.svg', 'Demo facts only']) expect(layout).toContain(text);
  });

  it('links the public repo without a demo video or banned claims', () => {
    const source = readFileSync('src/app/page.tsx', 'utf8');
    expect(source).toContain('https://github.com/summitsingh/launchcrew');
    expect(source).toContain('Public GitHub repo');
    const owned = frontendSources() + readFileSync('next.config.ts', 'utf8');
    for (const banned of ['Company OS', '—', 'META_API_KEY', 'youtube', 'vimeo', 'demo-video', 'demo_video']) {
      expect(owned).not.toContain(banned);
    }
  });
});
