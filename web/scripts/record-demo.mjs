#!/usr/bin/env node
// LaunchCrew demo recording harness, source only.
// Records the real LaunchCrew UI with existing Playwright Chromium, then
// muxes offline macOS say narration and captions with ffmpeg.
// Default is dry run. No recording without explicit --record.
// No route interception, no mocks, no fabricated responses, no fake LLM
// activity, no direct SQL seed, no API created state presented as UI.
// All runs, memories, campaigns, approvals, and exports are created through
// natural UI actions. Responses may be observed to collect run IDs, never
// replaced. Failures exit nonzero with the failing selector, no placeholder pass.
// Private outputs only under .local/demo (gitignored). No IDs, evidence,
// recordings, or manifests are written to committed paths. No credentials are
// accepted, read, logged, or interpolated. Subprocesses use argv, never shell
// strings. This script never clicks Check photo and never makes paid calls.
// Root runs this after terminal checks plus live proof. Source checks UNRUN here.

import { createRequire } from 'node:module';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import {
  accessSync, constants, existsSync, mkdirSync, readFileSync, writeFileSync,
  copyFileSync, statSync,
} from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const execFileAsync = promisify(execFile);
const require = createRequire(import.meta.url);

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url));
const WEB_DIR = resolve(SCRIPT_DIR, '..');
const REPO_ROOT = resolve(WEB_DIR, '..');
const DEFAULT_BASE_URL = 'https://launchcrew.summitsingh.com';
const DEFAULT_OUT_DIR = join(REPO_ROOT, '.local', 'demo');
const DEFAULT_NARRATION_MD = join(REPO_ROOT, 'docs', 'demo-narration.md');
const DEFAULT_FFMPEG = '/opt/homebrew/bin/ffmpeg';
const DEFAULT_FFPROBE = '/opt/homebrew/bin/ffprobe';
const DEFAULT_SAY = '/usr/bin/say';
const VIEWPORT = { width: 1600, height: 900 };
const WALLET_BRIEF = 'Vegan leather wallet, $49, for Austin commuters, launch on Instagram';
const TARGET_SECONDS = 170;
const HARD_LIMIT_SECONDS = 180;

// Narration segments. Keep in sync with docs/demo-narration.md.
// Each id must appear in that file. Say text is plain, no hype, no em dash.
const SEGMENTS = [
  {
    id: 's1-brief', title: 'Wallet brief', slot: '0:00-0:12',
    say: 'LaunchCrew turns one demo idea into a launch pack you approve before export. This is a fictional wallet brief: forty nine dollars, Austin commuters, Instagram. The flow you will see is keyless and deterministic.',
    caption: 'Fictional wallet brief. Keyless deterministic flow.',
  },
  {
    id: 's2-guard', title: 'Custom PriceGuard checker', slot: '0:12-0:32',
    say: 'This is a custom checker named PriceGuard. Its veto scope is price claims, exact match, a supported policy. Its rule is Block price claims. Free text rules outside the supported list stay advisory only and are never enforced.',
    caption: 'PriceGuard: supported price_claims policy. Other text stays advisory.',
  },
  {
    id: 's3-scout', title: 'Scout facts and sources', slot: '0:32-0:58',
    say: 'Scout sourced five demo facts with sources, plus three demo risks. These come from the local demo facts file and the demo brand brief. No external research ran, and no live product check is claimed.',
    caption: '5 demo facts, 3 demo risks. Demo sources. No external research.',
  },
  {
    id: 's4-seed', title: 'Seeded block and revision', slot: '0:58-1:22',
    say: 'With the seeded demo box checked, the unsupported claim best in Texas is blocked with a reason, then left out of the revised draft. PriceGuard also removes the forty nine dollar claim under its price policy. The final check shows zero blocked.',
    caption: 'Seeded demo: unsupported claim blocked and revised out.',
  },
  {
    id: 's5-replay', title: 'Replay', slot: '1:22-1:40',
    say: 'Replay compares two actual runs from this session by their stored run IDs. Same brief, different checker binding. The verdict difference comes from the recorded receipts, not from editing.',
    caption: 'Replay of two actual run IDs from this session.',
  },
  {
    id: 's6-memory', title: 'Memory edit', slot: '1:40-1:55',
    say: 'This is a prepared comparison from two actual runs made through the UI. After editing the memory rule, the next run blocks a different real claim. Nothing here is typed as a fake result.',
    caption: 'Prepared comparison. Two actual UI runs, before and after edit.',
  },
  {
    id: 's7-campaign', title: 'Campaign week', slot: '1:55-2:08',
    say: 'Campaign week holds seven distinct day packs. Each day stays pending until you approve it on its own. No batch approval, no auto publish.',
    caption: 'Seven distinct days. Each approved on its own.',
  },
  {
    id: 's8-sam', title: 'Separate photo result', slot: '2:08-2:25',
    say: 'This is the stored result from a separate authorized private jacket photo test. The photo is withheld. This wallet demo has not had a SAM photo check. Checked alone never means segmented.',
    caption: 'Separate private jacket test. Photo withheld. Wallet not SAM checked.',
  },
  {
    id: 's9-approve', title: 'Human approve and export', slot: '2:25-2:43',
    say: 'Nothing exports without your tap. Approval and export are recorded with the demo actor and time, and the receipt timeline keeps the history. Submission shows not attempted.',
    caption: 'Human approve, export download, stored timeline. Not attempted.',
  },
  {
    id: 's10-close', title: 'Close', slot: '2:43-2:50',
    say: 'LaunchCrew: one idea, three agents, one pack you approve, then export. Demo only. See the public repo and the verified site address shown here.',
    caption: 'Demo only. Public repo and verified site address on screen.',
  },
];

function printHelp() {
  const lines = [
    'record-demo.mjs: truthful LaunchCrew UI demo recorder.',
    '',
    'Default with no flags is a readonly dry run. Nothing is created.',
    'Actual recording requires explicit --record plus passing gates.',
    '',
    'Usage:',
    '  node web/scripts/record-demo.mjs [options]',
    '',
    'Options:',
    '  --help                  Show this help and exit.',
    '  --dry-run               Readonly checks only (default). No runs created.',
    '  --record                Record the real UI, mux narration, verify output.',
    '  --base-url URL          Public base URL. Default ' + DEFAULT_BASE_URL,
    '  --out-dir DIR           Private output dir. Default <repo>/.local/demo',
    '  --narration-md PATH     Narration doc to cross check. Default docs/demo-narration.md',
    '  --voice NAME            macOS say voice. Default system voice (no download).',
    '  --headed                Show Chromium. Default headless (safer, no desktop).',
    '  --spark-run-id ID       Optional stored run on same base URL showing Spark usage.',
    '                            Read back only. Keyless wallet stays separate.',
    '  --sam-proof PATH        Optional private sanitized SAM proof JSON for the',
    '                            pixel free evidence card. Absent means the SAM shot',
    '                            is skipped and reported pending honestly.',
    '  --ffmpeg PATH           Default ' + DEFAULT_FFMPEG,
    '  --ffprobe PATH          Default ' + DEFAULT_FFPROBE,
    '  --say PATH              Default ' + DEFAULT_SAY,
    '  --no-audio              Skip say narration (video plus captions only).',
    '  --no-verify             Skip ffprobe verification (not recommended).',
    '',
    'Gates for --record:',
    '  HTTPS base URL, GET /api/health 200, GET /api/auth/status 200,',
    '  GET / 200, narration doc contains every segment id, tools present.',
    '  Out dir must be under <repo>/.local to keep IDs and video private.',
    '  SAM card only from a validated sanitized proof file. No photo bytes,',
    '  digests, provider IDs, geometry, filenames, or crop data are accepted.',
    '  This script never clicks Check photo and never makes paid calls.',
    '',
    'Outputs (all private, gitignored):',
    '  <out>/demo-ui.mp4, <out>/narration/*.m4a, <out>/launchcrew-demo.mp4,',
    '  <out>/launchcrew-demo.srt, <out>/shot-manifest.json, <out>/clips/*',
    '',
    'No video is claimed until root runs this and verifies duration, sound,',
    'frame privacy, and receipt claims, then opens the private video for review.',
  ];
  console.log(lines.join('\n'));
}

function parseArgs(argv) {
  const opts = {
    help: false, dryRun: true, record: false, baseUrl: DEFAULT_BASE_URL,
    outDir: DEFAULT_OUT_DIR, narrationMd: DEFAULT_NARRATION_MD, voice: '',
    headed: false, sparkRunId: '', samProof: '', ffmpeg: DEFAULT_FFMPEG,
    ffprobe: DEFAULT_FFPROBE, say: DEFAULT_SAY, audio: true, verify: true,
  };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    const next = () => {
      const value = argv[i + 1];
      if (value === undefined || value.startsWith('--')) throw new Error(`Missing value for ${arg}`);
      i += 1;
      return value;
    };
    if (arg === '--help') opts.help = true;
    else if (arg === '--dry-run') { opts.dryRun = true; opts.record = false; }
    else if (arg === '--record') { opts.record = true; opts.dryRun = false; }
    else if (arg === '--base-url') opts.baseUrl = next();
    else if (arg === '--out-dir') opts.outDir = next();
    else if (arg === '--narration-md') opts.narrationMd = next();
    else if (arg === '--voice') opts.voice = next();
    else if (arg === '--headed') opts.headed = true;
    else if (arg === '--spark-run-id') opts.sparkRunId = next();
    else if (arg === '--sam-proof') opts.samProof = next();
    else if (arg === '--ffmpeg') opts.ffmpeg = next();
    else if (arg === '--ffprobe') opts.ffprobe = next();
    else if (arg === '--say') opts.say = next();
    else if (arg === '--no-audio') opts.audio = false;
    else if (arg === '--no-verify') opts.verify = false;
    else throw new Error(`Unknown option: ${arg}. Use --help.`);
  }
  return opts;
}

function fail(message) {
  console.error(`record-demo: FAIL: ${message}`);
  process.exit(1);
}

function warn(message) {
  console.error(`record-demo: WARN: ${message}`);
}

function info(message) {
  console.log(`record-demo: ${message}`);
}

function resolveTool(preferred, fallbackName) {
  // Prefer the explicit path, else fall back to PATH lookup by name.
  // execFile resolves bare names via PATH without a shell.
  try {
    accessSync(preferred, constants.X_OK);
    return preferred;
  } catch {
    return fallbackName;
  }
}

async function runTool(exe, args, label) {
  // argv only, no shell interpolation of user input.
  try {
    const result = await execFileAsync(exe, args, { timeout: 60000, maxBuffer: 4 * 1024 * 1024 });
    return { ok: true, stdout: String(result.stdout || ''), stderr: String(result.stderr || '') };
  } catch (error) {
    const err = error;
    return { ok: false, stdout: String(err.stdout || ''), stderr: String(err.stderr || err.message || '') };
  }
}

function mustBeUnderLocal(outDir) {
  const resolved = resolve(outDir);
  const localRoot = resolve(REPO_ROOT, '.local') + '/';
  if (!resolved.startsWith(localRoot)) {
    fail(`out dir must be under ${localRoot} to keep IDs and video private. Got: ${resolved}`);
  }
  return resolved;
}

function checkNarrationDoc(path) {
  if (!existsSync(path)) fail(`narration doc missing: ${path}`);
  const text = readFileSync(path, 'utf8');
  const missing = SEGMENTS.filter((seg) => !text.includes(seg.id));
  if (missing.length > 0) {
    fail(`narration doc is missing segment ids: ${missing.map((s) => s.id).join(', ')}`);
  }
  if (text.includes('\u2014')) fail('narration doc must not contain em dash');
  info(`narration doc OK (${SEGMENTS.length} segment ids present)`);
}

async function fetchStatus(url, timeoutMs = 15000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, { signal: controller.signal, redirect: 'follow' });
    const bodyText = await response.text().catch(() => '');
    return { status: response.status, ok: response.ok, bodyText };
  } finally {
    clearTimeout(timer);
  }
}

async function healthGate(baseUrl, forRecord) {
  let parsed;
  try {
    parsed = new URL(baseUrl);
  } catch {
    fail(`base URL is not a valid URL: ${baseUrl}`);
  }
  if (forRecord && parsed.protocol !== 'https:') {
    fail(`recording requires an https base URL. Got: ${baseUrl}`);
  }
  if (parsed.protocol !== 'https:' && parsed.protocol !== 'http:') {
    fail(`base URL must be http or https. Got: ${baseUrl}`);
  }
  const clean = baseUrl.replace(/\/$/, '');
  info(`checking ${clean} health...`);
  const health = await fetchStatus(`${clean}/api/health`);
  if (health.status !== 200) fail(`GET /api/health returned ${health.status}, expected 200`);
  const auth = await fetchStatus(`${clean}/api/auth/status`);
  if (auth.status !== 200) fail(`GET /api/auth/status returned ${auth.status}, expected 200`);
  const home = await fetchStatus(`${clean}/`);
  if (home.status !== 200) fail(`GET / returned ${home.status}, expected 200`);
  info('health gate PASS (api health, auth status, home all 200)');
  return clean;
}

function loadChromium() {
  // Resolve the existing web Playwright install. No new deps.
  try {
    const mod = require('@playwright/test');
    if (mod && mod.chromium) return mod.chromium;
  } catch { /* fall through */ }
  try {
    const mod = require('playwright');
    if (mod && mod.chromium) return mod.chromium;
  } catch { /* fall through */ }
  fail('Playwright Chromium not found. Run from the repo with web/node_modules present (pnpm install already done by root). No install is attempted here.');
}

async function dryRun(opts, ffmpeg, ffprobe, sayExe) {
  info('DRY RUN (readonly). No runs, memories, campaigns, approvals, or exports will be created.');
  mustBeUnderLocal(opts.outDir);
  checkNarrationDoc(opts.narrationMd);
  const clean = await healthGate(opts.baseUrl, false);

  const ffmpegCheck = await runTool(ffmpeg, ['-version'], 'ffmpeg');
  info(`ffmpeg ${ffmpegCheck.ok ? 'OK' : 'MISSING'} (${ffmpeg})`);
  const ffprobeCheck = await runTool(ffprobe, ['-version'], 'ffprobe');
  info(`ffprobe ${ffprobeCheck.ok ? 'OK' : 'MISSING'} (${ffprobe})`);
  const sayCheck = await runTool(sayExe, ['-v'], 'say voices');
  info(`say ${sayCheck.ok ? 'OK' : 'MISSING'} (${sayExe})`);
  if (opts.voice) {
    if (!sayCheck.ok || !sayCheck.stdout.includes(opts.voice)) {
      fail(`requested voice "${opts.voice}" is not installed. Pick a voice from "say -v" output. No voice download is attempted.`);
    }
    info(`voice OK (${opts.voice})`);
  } else {
    info('voice: system default (no download)');
  }

  // Readonly UI presence checks in a fresh headless context. No clicks that write.
  const chromium = loadChromium();
  const browser = await chromium.launch({ headless: !opts.headed });
  try {
    const context = await browser.newContext({ viewport: VIEWPORT });
    const page = await context.newPage();
    await page.goto(clean, { waitUntil: 'domcontentloaded', timeout: 30000 });
    const selectors = [
      ['Launch brief nav', 'button:has-text("Launch brief")'],
      ['Agent builder nav', 'button:has-text("Agent builder")'],
      ['Brief textarea', 'label:has-text("Product, audience, and launch channel")'],
      ['Scout agent select', '#run-scout'],
      ['Maker profile select', '#run-agent'],
      ['Checker agent select', '#run-checker-agent'],
      ['Seed checkbox', 'text=Include the unsupported claim demo'],
      ['Create draft button', 'button:has-text("Create draft")'],
    ];
    for (const [label, selector] of selectors) {
      try {
        await page.waitForSelector(selector, { timeout: 15000 });
        info(`selector OK: ${label}`);
      } catch {
        fail(`dry run selector missing: ${label} (${selector}). Recording would refuse here.`);
      }
    }
    // Readonly API readback shape (no writes).
    const queue = await fetchStatus(`${clean}/api/queue`);
    if (queue.status !== 200) fail(`GET /api/queue returned ${queue.status}, expected 200`);
    info('GET /api/queue 200 (readonly readback OK)');
    await page.close();
    await context.close();
  } finally {
    await browser.close();
  }

  if (opts.sparkRunId) {
    const receipt = await fetchStatus(`${clean}/api/runs/${encodeURIComponent(opts.sparkRunId)}/receipt`);
    if (receipt.status !== 200) {
      fail(`spark run readback failed: GET receipt returned ${receipt.status}. Supply an actual stored run ID on this base URL, or omit --spark-run-id.`);
    }
    info('spark run ID readback reachable (full usage check runs at record time)');
  }
  if (opts.samProof) {
    validateSamProof(opts.samProof, true);
  } else {
    info('no --sam-proof supplied: SAM shot will be skipped and reported pending honestly');
  }

  mkdirSync(resolve(opts.outDir), { recursive: true });
  info(`out dir ready (private): ${resolve(opts.outDir)}`);
  console.log('');
  console.log('Dry run PASS. To record after live proof, root runs the same command with --record.');
  console.log('Planned slots: ' + SEGMENTS.map((s) => `${s.slot} ${s.title}`).join(' | '));
  console.log(`Target ${TARGET_SECONDS}s, hard limit ${HARD_LIMIT_SECONDS}s. Nothing was created.`);
}

function readJsonFile(path, label) {
  if (!existsSync(path)) fail(`${label} file missing: ${path}`);
  try {
    return JSON.parse(readFileSync(path, 'utf8'));
  } catch (error) {
    fail(`${label} file is not valid JSON: ${path}: ${error.message}`);
  }
}

function validateSamProof(path, dryOnly) {
  // Pixel free evidence card input. Sanitized summary only. Reject anything
  // that could identify bytes, providers, files, geometry, or crops.
  const data = readJsonFile(path, 'sam proof');
  const forbiddenKeys = [
    'bytes', 'digest', 'sha256', 'file_id', 'provider', 'provider_id', 'upload_id',
    'filename', 'file_name', 'path', 'geometry', 'box', 'boxes', 'mask', 'masks',
    'crop', 'crop_box', 'x1', 'y1', 'x2', 'y2', 'image', 'photo_bytes', 'data_uri',
  ];
  const text = JSON.stringify(data).toLowerCase();
  for (const key of forbiddenKeys) {
    if (text.includes(`"${key}"`)) fail(`sam proof contains forbidden key "${key}". Supply a sanitized summary only.`);
  }
  const required = ['method', 'scope', 'photo_state', 'segmentations', 'checked_at', 'revision'];
  for (const key of required) {
    if (data[key] === undefined || data[key] === null || data[key] === '') {
      fail(`sam proof is missing required field "${key}". Refusing SAM shot.`);
    }
  }
  if (typeof data.segmentations !== 'number' || !(data.segmentations > 0)) {
    fail('sam proof must show nonzero actual segmentations. Checked alone is not success. Refusing SAM shot.');
  }
  if (data.photo_state !== 'checked') {
    fail(`sam proof photo_state must be "checked" with a detected label. Got: ${String(data.photo_state)}. Refusing SAM shot.`);
  }
  if (data.label !== undefined && data.label !== 'detected') {
    fail(`sam proof label must be "detected" when present. Got: ${String(data.label)}. Refusing SAM shot.`);
  }
  if (typeof data.method !== 'string' || typeof data.scope !== 'string') {
    fail('sam proof method and scope must be strings.');
  }
  info(`sam proof OK (method "${data.method}", scope "${data.scope}", segmentations ${data.segmentations})${dryOnly ? ' [dry run]' : ''}`);
  return data;
}

function validateSparkReceipt(receipt) {
  const usage = receipt.model_usage || receipt.modelUsage || null;
  if (!usage) fail('spark run receipt has no stored model usage. Supply an actual stored Spark run, or omit --spark-run-id.');
  const mode = usage.mode || '';
  const calls = usage.spark_calls ?? usage.sparkCalls ?? null;
  if (mode !== 'spark' && mode !== 'spark_strict_json' && !String(mode).includes('spark')) {
    fail(`spark run receipt mode is "${mode}", not spark. Refusing Spark shot.`);
  }
  if (typeof calls !== 'number' || !(calls > 0)) {
    fail('spark run receipt must show nonzero stored Spark calls. Refusing Spark shot.');
  }
  return { mode, calls };
}

function escapeHtml(value) {
  return String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function writeComparisonCard(path, title, beforePng, afterPng, beforeLabel, afterLabel, note) {
  // Clearly labelled prepared comparison from two actual screenshots.
  // No invented content: both images are actual captures from this session.
  const html = `<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>${escapeHtml(title)}</title>
<style>body{font-family:system-ui,sans-serif;background:#0b0e14;color:#e8ecf1;margin:0;padding:32px}
.badge{display:inline-block;background:#f5c518;color:#111;padding:4px 12px;border-radius:999px;font-weight:700}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:24px;margin-top:16px}
figure{margin:0;background:#141a24;border-radius:12px;padding:12px}
img{width:100%;border-radius:8px;border:1px solid #2a3342}
figcaption{margin-top:8px;font-size:14px;color:#c6cfdb}
.note{margin-top:16px;color:#9aa4b2}</style></head><body>
<span class="badge">PREPARED COMPARISON</span>
<h1>${escapeHtml(title)}</h1>
<p>Two actual runs made through the UI in this session, shown side by side.</p>
<div class="grid">
<figure><img src="${escapeHtml(beforePng)}" alt="before screenshot"><figcaption>Before: ${escapeHtml(beforeLabel)}</figcaption></figure>
<figure><img src="${escapeHtml(afterPng)}" alt="after screenshot"><figcaption>After: ${escapeHtml(afterLabel)}</figcaption></figure>
</div><p class="note">${escapeHtml(note)}</p></body></html>
`;
  writeFileSync(path, html);
}

function writeSamCard(path, proof) {
  // Pixel free evidence card. No photo, picker, canvas, image, or geometry.
  const html = `<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Separate private photo result</title>
<style>body{font-family:system-ui,sans-serif;background:#0b0e14;color:#e8ecf1;margin:0;padding:40px}
.card{max-width:900px;margin:0 auto;background:#141a24;border-radius:16px;padding:32px}
.badge{display:inline-block;background:#7ee2a8;color:#0b2e1a;padding:4px 12px;border-radius:999px;font-weight:700}
dl{display:grid;grid-template-columns:220px 1fr;gap:8px 16px;margin-top:16px}
dt{color:#9aa4b2}dd{margin:0}
.warn{margin-top:16px;padding:12px;border-radius:8px;background:#2a2113;color:#f5c518}</style></head><body>
<div class="card"><span class="badge">SEPARATE PRIVATE TEST</span>
<h1>Stored photo result (sanitized summary)</h1>
<p>This card shows a stored summary only. No photo pixels are shown here and none were placed beside this card.</p>
<dl>
<dt>Method</dt><dd>${escapeHtml(proof.method)}</dd>
<dt>Scope</dt><dd>${escapeHtml(proof.scope)}</dd>
<dt>Photo state</dt><dd>${escapeHtml(proof.photo_state)}${proof.label ? ' / ' + escapeHtml(proof.label) : ''}</dd>
<dt>Segmentations</dt><dd>${escapeHtml(proof.segmentations)}</dd>
<dt>Checked at</dt><dd>${escapeHtml(proof.checked_at)}</dd>
<dt>Revision</dt><dd>${escapeHtml(proof.revision)}</dd>
</dl>
<div class="warn">The photo is withheld. This wallet demo has not had a SAM photo check. Checked alone never means segmented.</div>
</div></body></html>
`;
  writeFileSync(path, html);
  const check = readFileSync(path, 'utf8').toLowerCase();
  for (const token of ['<img', '<canvas', '<input type="file"', 'picker', 'data:image']) {
    if (check.includes(token)) fail(`sam card must not contain "${token}". Refusing SAM shot.`);
  }
}

async function sayClip(sayExe, voice, text, outAiff) {
  const args = voice ? ['-v', voice, '-o', outAiff, text] : ['-o', outAiff, text];
  const result = await runTool(sayExe, args, 'say');
  if (!result.ok) fail(`say failed for clip ${outAiff}: ${result.stderr.slice(0, 500)}`);
  if (!existsSync(outAiff) || statSync(outAiff).size === 0) fail(`say produced no audio: ${outAiff}`);
}

async function ffprobeDuration(ffprobe, file) {
  const result = await runTool(ffprobe, ['-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', file], 'ffprobe duration');
  if (!result.ok) fail(`ffprobe failed on ${file}: ${result.stderr.slice(0, 500)}`);
  const seconds = Number.parseFloat(result.stdout.trim());
  if (!Number.isFinite(seconds) || seconds <= 0) fail(`ffprobe returned no duration for ${file}`);
  return seconds;
}

async function ffprobeStreams(ffprobe, file) {
  const result = await runTool(ffprobe, ['-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height,codec_name', '-of', 'default=noprint_wrappers=1', file], 'ffprobe video');
  if (!result.ok) fail(`ffprobe failed on ${file}: ${result.stderr.slice(0, 500)}`);
  const width = Number.parseInt(/width=(\d+)/.exec(result.stdout)?.[1] || '', 10);
  const height = Number.parseInt(/height=(\d+)/.exec(result.stdout)?.[1] || '', 10);
  const audio = await runTool(ffprobe, ['-v', 'error', '-select_streams', 'a:0', '-show_entries', 'stream=codec_name', '-of', 'default=noprint_wrappers=1:nokey=1', file], 'ffprobe audio');
  return { width, height, hasAudio: audio.ok && audio.stdout.trim().length > 0 };
}

function formatSrtTime(totalSeconds) {
  const ms = Math.max(0, Math.round(totalSeconds * 1000));
  const hours = Math.floor(ms / 3600000);
  const minutes = Math.floor((ms % 3600000) / 60000);
  const seconds = Math.floor((ms % 60000) / 1000);
  const millis = ms % 1000;
  const pad = (value, width) => String(value).padStart(width, '0');
  return `${pad(hours, 2)}:${pad(minutes, 2)}:${pad(seconds, 2)},${pad(millis, 3)}`;
}

async function recordFlow(opts, ffmpeg, ffprobe, sayExe) {
  const outDir = mustBeUnderLocal(opts.outDir);
  checkNarrationDoc(opts.narrationMd);
  const clean = await healthGate(opts.baseUrl, true);
  mkdirSync(outDir, { recursive: true });
  const clipsDir = join(outDir, 'clips');
  const narrationDir = join(outDir, 'narration');
  const shotsDir = join(outDir, 'shots');
  mkdirSync(clipsDir, { recursive: true });
  mkdirSync(narrationDir, { recursive: true });
  mkdirSync(shotsDir, { recursive: true });

  // Validate optional proofs before touching the UI.
  let samProof = null;
  const includeSam = Boolean(opts.samProof);
  if (opts.samProof) samProof = validateSamProof(opts.samProof, false);
  else info('no --sam-proof: SAM segment will be skipped and reported pending honestly');

  let sparkReceipt = null;
  if (opts.sparkRunId) {
    const receiptRes = await fetchStatus(`${clean}/api/runs/${encodeURIComponent(opts.sparkRunId)}/receipt`);
    if (receiptRes.status !== 200) fail(`spark run readback failed (${receiptRes.status}). Supply an actual stored run ID, or omit --spark-run-id.`);
    try {
      sparkReceipt = JSON.parse(receiptRes.bodyText);
    } catch {
      fail('spark run receipt is not valid JSON.');
    }
    const usage = validateSparkReceipt(sparkReceipt);
    info(`spark proof readback OK (mode ${usage.mode}, ${usage.calls} stored calls). Shown separately from the keyless wallet.`);
  } else {
    info('no --spark-run-id: narration stays keyless only, no model claim is made');
  }

  // Phase 1: narration clips first, so UI holds can match real audio timing.
  const activeSegments = includeSam ? SEGMENTS : SEGMENTS.filter((s) => s.id !== 's8-sam');
  const clipPlan = [];
  if (opts.audio) {
    info('generating offline narration clips...');
    for (const seg of activeSegments) {
      const aiff = join(narrationDir, `${seg.id}.aiff`);
      const m4a = join(narrationDir, `${seg.id}.m4a`);
      await sayClip(sayExe, opts.voice, seg.say, aiff);
      const convert = await runTool(ffmpeg, ['-y', '-i', aiff, '-c:a', 'aac', '-b:a', '128k', m4a], 'ffmpeg convert');
      if (!convert.ok) fail(`ffmpeg narration convert failed for ${seg.id}: ${convert.stderr.slice(0, 500)}`);
      const seconds = await ffprobeDuration(ffprobe, m4a);
      clipPlan.push({ ...seg, m4a, seconds });
      info(`${seg.id}: ${seconds.toFixed(1)}s`);
    }
    const total = clipPlan.reduce((sum, clip) => sum + clip.seconds, 0);
    info(`narration total ${total.toFixed(1)}s (target under ${TARGET_SECONDS}s)`);
    if (total > HARD_LIMIT_SECONDS) {
      fail(`narration alone is ${total.toFixed(1)}s, over the ${HARD_LIMIT_SECONDS}s hard limit. Shorten docs/demo-narration.md before recording.`);
    }
  } else {
    for (const seg of activeSegments) clipPlan.push({ ...seg, m4a: '', seconds: 8 });
    warn('audio disabled: using 8s placeholder holds per segment');
  }

  // Phase 2: record the real UI in one continuous take.
  const chromium = loadChromium();
  const browser = await chromium.launch({ headless: !opts.headed });
  const manifest = {
    tool: 'web/scripts/record-demo.mjs', base_url: clean, started_at: new Date().toISOString(),
    viewport: VIEWPORT, segments: [], runs: {}, proof: {
      spark_run_requested: Boolean(opts.sparkRunId), sam_proof_requested: includeSam,
      sam_included: includeSam, audio: opts.audio,
    },
  };
  const suffix = String(Date.now());
  const scoutName = `EagleScout${suffix}`;
  const checkerName = `PriceGuard${suffix}`;
  let uiVideoSource = '';
  const takeStart = Date.now();

  const holdFor = async (page, clipId, extraMs = 1200) => {
    const clip = clipPlan.find((c) => c.id === clipId);
    const holdMs = clip ? Math.max(2000, Math.round(clip.seconds * 1000)) + extraMs : 3000;
    await page.waitForTimeout(holdMs);
  };

  try {
    const context = await browser.newContext({
      viewport: VIEWPORT,
      recordVideo: { dir: clipsDir, size: { width: VIEWPORT.width, height: VIEWPORT.height } },
      acceptDownloads: true,
      ignoreHTTPSErrors: false,
    });
    const page = await context.newPage();
    const stepTime = (id, note) => {
      manifest.segments.push({ id, at_seconds: (Date.now() - takeStart) / 1000, note });
    };

    const mustClick = async (role, name, exact = true) => {
      try {
        await page.getByRole(role, { name, exact }).click({ timeout: 20000 });
      } catch {
        fail(`selector failed: role=${role} name="${name}". UI changed or app is down. Refusing to fake this step.`);
      }
    };
    const mustFill = async (label, value, exact = true) => {
      try {
        await page.getByLabel(label, { exact }).fill(value, { timeout: 20000 });
      } catch {
        fail(`label failed: "${label}". UI changed or app is down. Refusing to fake this step.`);
      }
    };
    const mustSelect = async (label, value) => {
      try {
        await page.getByLabel(label, { exact: true }).selectOption(value, { timeout: 20000 });
      } catch {
        fail(`select failed: "${label}" option "${value}". Refusing to fake this step.`);
      }
    };

    await page.goto(clean, { waitUntil: 'domcontentloaded', timeout: 30000 });
    stepTime('open', 'home opened');

    // S1: wallet brief visible with approved demo facts.
    await mustClick('button', 'Launch brief', false);
    await mustFill('Product, audience, and launch channel', WALLET_BRIEF);
    await page.screenshot({ path: join(shotsDir, 's1-brief.png') });
    stepTime('s1-brief', 'wallet brief filled, demo facts aside');
    await holdFor(page, 's1-brief', 800);

    // S2: create Scout and PriceGuard through the Agent builder UI.
    async function createAgent(fields) {
      await mustClick('button', 'Agent builder', false);
      await mustClick('button', 'New agent', true);
      await mustFill('Name', fields.name, true);
      await mustFill('Role', fields.role, true);
      await mustFill('Personality', fields.personality, true);
      await mustFill('Expertise', fields.expertise, true);
      await mustFill('decision rules (one per line)', fields.rules);
      await mustFill('veto scope (one per line)', fields.veto);
      await mustClick('button', 'Save agent', true);
      try {
        await page.getByRole('status').filter({ hasText: `Saved agent ${fields.name}` }).waitFor({ timeout: 20000 });
      } catch {
        fail(`agent save confirmation missing for ${fields.name}. Refusing to continue with an unconfirmed agent.`);
      }
    }
    await createAgent({
      name: scoutName, role: 'Skeptical Analyst',
      personality: `Cautious source-first analyst ${suffix}`,
      expertise: `Demo market notes ${suffix}`,
      rules: 'Use facts file first\nCite a source for every fact', veto: '',
    });
    await createAgent({
      name: checkerName, role: 'Strict Auditor',
      personality: `Blocks price claims ${suffix}`,
      expertise: `Demo approval rules ${suffix}`,
      rules: 'Block price claims', veto: 'price_claims',
    });
    await page.getByRole('button', { name: `${checkerName} Strict Auditor`, exact: false }).first().click({ timeout: 20000 });
    await mustClick('button', 'Dry-run preview', true);
    try {
      await page.getByText('Enforced policies: price_claims').waitFor({ timeout: 20000 });
    } catch {
      fail('PriceGuard dry-run preview did not show enforced price_claims. Refusing to claim the policy.');
    }
    await page.screenshot({ path: join(shotsDir, 's2-guard.png') });
    stepTime('s2-guard', `PriceGuard ${checkerName} enforced price_claims`);
    await holdFor(page, 's2-guard', 800);

    // Natural runs through the Launch brief UI. Observe responses, never replace them.
    async function runViaUi({ checker, seed, memoryIds = '' }) {
      await mustClick('button', 'Launch brief', false);
      await mustSelect('Scout agent', scoutName);
      await mustSelect('Maker profile', 'Maker');
      await mustSelect('Checker agent', checker);
      await mustSelect('Checker profile', 'standard');
      await mustFill('Memory ids, comma separated, optional', memoryIds);
      const seedBox = page.getByLabel('Include the unsupported claim demo');
      if (seed) await seedBox.check({ timeout: 20000 });
      else await seedBox.uncheck({ timeout: 20000 });
      await mustFill('Product, audience, and launch channel', WALLET_BRIEF);
      const responseWait = page.waitForResponse(
        (response) => response.url().includes('/api/runs/async') && response.request().method() === 'POST',
        { timeout: 30000 },
      ).catch(() => null);
      await mustClick('button', 'Create draft', true);
      const observed = await responseWait;
      let observedId = '';
      if (observed && observed.ok()) {
        try {
          observedId = String((await observed.json()).run_id || '');
        } catch { observedId = ''; }
      }
      try {
        await page.locator('.section-row .run-id').first().waitFor({ timeout: 60000 });
      } catch {
        fail('run ID never appeared in the UI after Create draft. Refusing to invent a run ID.');
      }
      const uiId = (await page.locator('.section-row .run-id').first().innerText()).trim();
      if (!uiId.startsWith('run_')) fail(`UI run ID looks wrong: "${uiId}". Refusing to continue.`);
      if (observedId && observedId !== uiId) {
        warn(`observed response run ${observedId.slice(0, 12)} differs from UI run ${uiId.slice(0, 12)}; using the UI value`);
      }
      try {
        await page.getByRole('heading', { name: 'Unsupported claims stopped.' }).or(
          page.getByRole('heading', { name: 'Ready for your review.' }),
        ).waitFor({ timeout: 90000 });
      } catch {
        fail(`run ${uiId.slice(0, 12)} never reached review. Refusing to fake completion.`);
      }
      return uiId;
    }

    // S3: default checker, clean (seed off). Scout facts plus risks on screen.
    const runDefault = await runViaUi({ checker: 'Checker', seed: false });
    manifest.runs.runDefault = runDefault;
    try {
      await page.locator('section[aria-label="Scout facts and sources"] .scout-fact').first().waitFor({ timeout: 20000 });
      await page.getByText('No external research was run').waitFor({ timeout: 20000 });
    } catch {
      fail('Scout facts section did not render with demo source honesty copy. Refusing to narrate Scout.');
    }
    const factCount = await page.locator('section[aria-label="Scout facts and sources"] .scout-fact').count();
    const riskCount = await page.locator('section[aria-label="Scout facts and sources"] .scout-risk').count();
    if (factCount !== 5 || riskCount !== 3) {
      fail(`Scout counts are ${factCount} facts and ${riskCount} risks, expected 5 and 3. Refusing to misstate counts.`);
    }
    await page.screenshot({ path: join(shotsDir, 's3-scout.png') });
    stepTime('s3-scout', `default run ${runDefault.slice(0, 12)}, 5 facts 3 risks`);
    await holdFor(page, 's3-scout', 800);

    // PriceGuard clean run shows the genuine price veto without any seed.
    const runGuarded = await runViaUi({ checker: checkerName, seed: false });
    manifest.runs.runGuarded = runGuarded;
    await page.screenshot({ path: join(shotsDir, 's4a-guarded.png') });

    // S4: seeded run with PriceGuard shows both the seed block and the price veto.
    const runSeeded = await runViaUi({ checker: checkerName, seed: true });
    manifest.runs.runSeeded = runSeeded;
    try {
      await page.getByText('best in Texas', { exact: true }).first().waitFor({ timeout: 20000 });
    } catch {
      fail('seeded claim text never appeared. The seed checkbox may not have applied. Refusing to fake the block.');
    }
    await page.screenshot({ path: join(shotsDir, 's4-seed.png') });
    stepTime('s4-seed', `seeded run ${runSeeded.slice(0, 12)}, best-in-Texas plus price veto`);
    await holdFor(page, 's4-seed', 800);

    // S5: Replay the two actual run IDs.
    await mustClick('button', 'Replay', false);
    await mustFill('Run A id', runDefault);
    await mustFill('Run B id', runGuarded);
    await mustClick('button', 'Compare', true);
    try {
      await page.getByText('Stage bindings changed: true').waitFor({ timeout: 20000 });
    } catch {
      fail('Replay did not show the expected binding difference for the two actual runs.');
    }
    await page.screenshot({ path: join(shotsDir, 's5-replay.png') });
    stepTime('s5-replay', 'replay compared two actual run IDs');
    await holdFor(page, 's5-replay', 800);

    // S6: Memory rule before and after, two actual UI runs, labelled comparison.
    await mustClick('button', 'Memory', false);
    const memTitle = `DemoRule${suffix}`;
    await mustFill('Title', memTitle, true);
    await mustFill('Content JSON object', '{"claim": "$49"}', true);
    await page.getByLabel('Kind', { exact: true }).selectOption('blocked_rule', { timeout: 20000 });
    await mustClick('button', 'Create memory', true);
    try {
      await page.getByText('Memory item created.').waitFor({ timeout: 20000 });
    } catch {
      fail('memory creation was not confirmed in the UI.');
    }
    const memCard = page.locator(`article[aria-label="Memory item: ${memTitle}"]`);
    const memId = (await memCard.locator('.run-id').innerText()).trim();
    manifest.runs.memoryId = memId;
    const memBefore = await runViaUi({ checker: 'Checker', seed: false, memoryIds: memId });
    manifest.runs.memBefore = memBefore;
    await page.screenshot({ path: join(shotsDir, 's6-before.png') });
    await mustClick('button', 'Memory', false);
    await memCard.getByRole('button', { name: 'Edit memory', exact: true }).click({ timeout: 20000 });
    await mustFill('Edit content JSON object', '{"blocked_claims": [{"claim": "Designed in Texas", "reason": "Edited rule"}]}');
    await mustClick('button', 'Save memory', true);
    const memAfter = await runViaUi({ checker: 'Checker', seed: false, memoryIds: memId });
    manifest.runs.memAfter = memAfter;
    await page.screenshot({ path: join(shotsDir, 's6-after.png') });
    writeComparisonCard(
      join(shotsDir, 's6-comparison.html'),
      'Memory edit changes the next run',
      's6-before.png', 's6-after.png',
      `run ${memBefore.slice(0, 12)} blocked $49`,
      `run ${memAfter.slice(0, 12)} blocked Designed in Texas`,
      'Prepared comparison. Both screenshots are actual UI captures from this session.',
    );
    await page.goto('file://' + join(shotsDir, 's6-comparison.html'), { waitUntil: 'domcontentloaded' });
    try {
      await page.getByText('PREPARED COMPARISON').waitFor({ timeout: 10000 });
    } catch {
      fail('comparison card failed to render.');
    }
    stepTime('s6-memory', 'memory before and after comparison card');
    await holdFor(page, 's6-memory', 800);
    await page.goto(clean, { waitUntil: 'domcontentloaded' });

    // S7: Campaign week, seven distinct days.
    await mustClick('button', 'Campaign', false);
    await mustSelect('Maker profile', 'Maker');
    await mustClick('button', 'Create week', true);
    try {
      await page.getByRole('heading', { name: 'Day 1: Origin story' }).waitFor({ timeout: 90000 });
      await page.getByRole('heading', { name: 'Day 7: Launch offer' }).waitFor({ timeout: 30000 });
    } catch {
      fail('campaign week did not render all seven days. Refusing to claim seven.');
    }
    const headings = await page.locator('article h3').allInnerTexts();
    const days = headings.filter((h) => h.startsWith('Day '));
    if (days.length !== 7 || new Set(days).size !== 7) {
      fail(`campaign days are not seven distinct cards (got ${days.length}). Refusing to misstate.`);
    }
    const weekId = (await page.locator('section p.run-id').first().innerText()).trim();
    manifest.runs.campaignId = weekId;
    await page.screenshot({ path: join(shotsDir, 's7-campaign.png') });
    stepTime('s7-campaign', 'seven distinct campaign days');
    await holdFor(page, 's7-campaign', 800);

    // S8: optional pixel free SAM card only from validated proof. No photo UI.
    if (includeSam && samProof) {
      const cardPath = join(shotsDir, 's8-sam.html');
      writeSamCard(cardPath, samProof);
      await page.goto('file://' + cardPath, { waitUntil: 'domcontentloaded' });
      try {
        await page.getByText('SEPARATE PRIVATE TEST').waitFor({ timeout: 10000 });
      } catch {
        fail('SAM evidence card failed to render.');
      }
      // Guard: no photo UI may mount on this card.
      const forbiddenOnCard = ['Select photo', 'Check photo', 'photo-crop-canvas'];
      for (const token of forbiddenOnCard) {
        if ((await page.getByText(token, { exact: false }).count()) > 0 || (await page.locator(`[data-testid="${token}"]`).count()) > 0) {
          fail(`SAM card must not contain photo UI ("${token}"). Refusing SAM shot.`);
        }
      }
      await page.screenshot({ path: join(shotsDir, 's8-sam.png') });
      stepTime('s8-sam', `separate private result, method ${samProof.method}`);
      await holdFor(page, 's8-sam', 800);
      await page.goto(clean, { waitUntil: 'domcontentloaded' });
    } else {
      stepTime('s8-sam', 'skipped honestly, no sanitized proof supplied');
    }

    // Optional stored Spark proof, read back separately from the keyless wallet.
    if (sparkReceipt && opts.sparkRunId) {
      await page.getByRole('navigation', { name: 'Workspace' }).getByRole('button', { name: 'Approval queue' }).click({ timeout: 20000 });
      const sparkCard = page.locator(`[data-run-id="${opts.sparkRunId}"]`);
      try {
        await sparkCard.waitFor({ timeout: 20000 });
      } catch {
        fail('stored Spark run is not visible in the queue on this base URL. Supply an ID from the same database, or omit --spark-run-id.');
      }
      await sparkCard.getByRole('button', { name: 'View receipt', exact: true }).click({ timeout: 20000 });
      try {
        await page.getByRole('heading', { name: 'Receipt', exact: true }).waitFor({ timeout: 20000 });
      } catch {
        fail('Spark receipt view did not open.');
      }
      await page.screenshot({ path: join(shotsDir, 'spark-receipt.png') });
      stepTime('spark-proof', 'stored Spark receipt shown separately from keyless flow');
      await page.waitForTimeout(4000);
      await page.goto(clean, { waitUntil: 'domcontentloaded' });
    }

    // S9: human approve plus export download on the seeded run, then receipt timeline.
    await page.getByRole('navigation', { name: 'Workspace' }).getByRole('button', { name: 'Approval queue' }).click({ timeout: 20000 });
    const card = page.locator(`[data-run-id="${runSeeded}"]`);
    try {
      await card.getByText('Pending approval', { exact: true }).waitFor({ timeout: 30000 });
    } catch {
      fail('seeded run is not pending approval. Refusing to fake the approval tap.');
    }
    await card.getByRole('button', { name: 'Approve for export', exact: true }).click({ timeout: 20000 });
    try {
      await card.getByText('Approved for export', { exact: true }).waitFor({ timeout: 20000 });
    } catch {
      fail('approval was not confirmed in the UI.');
    }
    const downloadWait = page.waitForEvent('download', { timeout: 30000 });
    await card.getByRole('button', { name: 'Export pack', exact: true }).click({ timeout: 20000 });
    const download = await downloadWait;
    const exportPath = join(outDir, `export-${suffix}.json`);
    await download.saveAs(exportPath);
    const exported = JSON.parse(readFileSync(exportPath, 'utf8'));
    if (exported.run_id !== runSeeded) fail('exported pack run ID does not match the approved run.');
    if (exported.summary && exported.summary.submit_attempted !== false) {
      fail('exported pack shows submit attempted. Refusing to claim no submission.');
    }
    await card.getByRole('button', { name: 'View receipt', exact: true }).click({ timeout: 20000 });
    try {
      await page.getByRole('heading', { name: 'Receipt', exact: true }).waitFor({ timeout: 20000 });
      await page.getByText('Not attempted', { exact: true }).waitFor({ timeout: 20000 });
      await page.getByRole('heading', { name: 'Recorded events' }).waitFor({ timeout: 20000 });
    } catch {
      fail('receipt timeline did not show stored events with no submission. Refusing to fake the record.');
    }
    await page.screenshot({ path: join(shotsDir, 's9-receipt.png') });
    stepTime('s9-approve', 'approved, exported, timeline kept, not attempted');
    await holdFor(page, 's9-approve', 800);

    // S10: close on the verified base URL. No localhost shown as public.
    await page.goto(clean, { waitUntil: 'domcontentloaded' });
    await page.screenshot({ path: join(shotsDir, 's10-close.png') });
    stepTime('s10-close', `close on ${clean}`);
    await holdFor(page, 's10-close', 800);

    // Close context BEFORE video saveAs. Required for a finalizable file.
    const video = page.video();
    if (!video) fail('page has no recorded video. Refusing to fake output.');
    await page.close();
    await context.close();
    const savedWebm = join(clipsDir, 'take.webm');
    await video.saveAs(savedWebm);
    if (!existsSync(savedWebm)) fail('no recorded video clip was produced. Refusing to fake output.');
    uiVideoSource = savedWebm;
    const uiTarget = join(outDir, 'demo-ui.mp4');
    const remux = await runTool(ffmpeg, ['-y', '-i', uiVideoSource, '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', uiTarget], 'ffmpeg remux');
    if (!remux.ok) fail(`ffmpeg remux failed: ${remux.stderr.slice(0, 500)}`);
    manifest.ui_video = 'demo-ui.mp4';
  } finally {
    await browser.close().catch(() => {});
  }

  // Phase 3: mux narration plus captions, then verify with ffprobe.
  const uiMp4 = join(outDir, 'demo-ui.mp4');
  if (!existsSync(uiMp4)) fail('UI video missing after recording. Refusing to fake output.');
  const finalMp4 = join(outDir, 'launchcrew-demo.mp4');
  const srtPath = join(outDir, 'launchcrew-demo.srt');

  // Build captions from actual narration clip durations in take order.
  let cursor = 0;
  const srtBlocks = [];
  let index = 1;
  for (const clip of clipPlan) {
    const start = cursor;
    const end = cursor + clip.seconds;
    srtBlocks.push(`${index}\n${formatSrtTime(start)} --> ${formatSrtTime(end)}\n[${clip.slot} ${clip.title}] ${clip.caption}\n`);
    cursor = end + 0.4;
    index += 1;
  }
  writeFileSync(srtPath, srtBlocks.join('\n'));

  if (opts.audio) {
    const listPath = join(narrationDir, 'concat.txt');
    const lines = clipPlan.map((clip) => `file '${clip.m4a.replace(/'/g, "'\\''")}'`);
    writeFileSync(listPath, lines.join('\n') + '\n');
    const narrationTrack = join(narrationDir, 'narration.m4a');
    const concat = await runTool(ffmpeg, ['-y', '-f', 'concat', '-safe', '0', '-i', listPath, '-c', 'copy', narrationTrack], 'ffmpeg concat');
    if (!concat.ok) fail(`ffmpeg narration concat failed: ${concat.stderr.slice(0, 500)}`);
    const mux = await runTool(ffmpeg, ['-y', '-i', uiMp4, '-i', narrationTrack, '-c:v', 'copy', '-c:a', 'aac', '-map', '0:v:0', '-map', '1:a:0', '-movflags', '+faststart', finalMp4], 'ffmpeg mux');
    if (!mux.ok) fail(`ffmpeg mux failed: ${mux.stderr.slice(0, 500)}`);
  } else {
    copyFileSync(uiMp4, finalMp4);
  }

  // Burn captions is optional; keep the srt alongside for review.
  manifest.finished_at = new Date().toISOString();
  manifest.final_video = 'launchcrew-demo.mp4';
  manifest.captions = 'launchcrew-demo.srt';
  manifest.shots_dir = 'shots';
  manifest.target_seconds = TARGET_SECONDS;
  manifest.hard_limit_seconds = HARD_LIMIT_SECONDS;
  // Truncate IDs in the terminal summary, keep full values only in this private manifest.
  writeFileSync(join(outDir, 'shot-manifest.json'), JSON.stringify(manifest, null, 2));

  if (opts.verify) {
    const duration = await ffprobeDuration(ffprobe, finalMp4);
    const streams = await ffprobeStreams(ffprobe, finalMp4);
    manifest.ffprobe = { duration_seconds: duration, width: streams.width, height: streams.height, has_audio: streams.hasAudio };
    writeFileSync(join(outDir, 'shot-manifest.json'), JSON.stringify(manifest, null, 2));
    info(`ffprobe: ${duration.toFixed(1)}s, ${streams.width}x${streams.height}, audio ${streams.hasAudio ? 'yes' : 'no'}`);
    if (streams.width !== VIEWPORT.width || streams.height !== VIEWPORT.height) {
      fail(`dimensions are ${streams.width}x${streams.height}, expected ${VIEWPORT.width}x${VIEWPORT.height}. Refusing to pass.`);
    }
    if (opts.audio && !streams.hasAudio) fail('final video has no audio track. Refusing to pass.');
    if (duration > HARD_LIMIT_SECONDS) {
      fail(`final video is ${duration.toFixed(1)}s, over the ${HARD_LIMIT_SECONDS}s hard limit. Trim dead time honestly and re-run. No fake pass.`);
    }
    if (duration > TARGET_SECONDS + 10) {
      warn(`final video is ${duration.toFixed(1)}s, over the ${TARGET_SECONDS}s target but within the hard limit`);
    }
    // Readability: file must be nontrivial and dimensions exact (above).
    if (statSync(finalMp4).size < 100000) fail('final video file is suspiciously small. Refusing to pass.');
    info('ffprobe verification PASS');
  } else {
    warn('verification skipped (--no-verify). Root must still verify before review.');
  }

  console.log('');
  console.log('Recording complete (private outputs only). No upload, no submission, no publication was made.');
  console.log(`Video: ${finalMp4}`);
  console.log(`Captions: ${srtPath}`);
  console.log(`Manifest: ${join(outDir, 'shot-manifest.json')}`);
  console.log('Next gates stay separate: root checks duration, sound, frame privacy, and receipt');
  console.log('claims, opens the private video for user review, then user approves video, upload,');
  console.log('publication, and any Cerebral submission in separate taps.');
}

async function main() {
  const opts = parseArgs(process.argv.slice(2));
  if (opts.help) {
    printHelp();
    return;
  }
  const ffmpeg = resolveTool(opts.ffmpeg, 'ffmpeg');
  const ffprobe = resolveTool(opts.ffprobe, 'ffprobe');
  const sayExe = resolveTool(opts.say, 'say');
  if (opts.record) await recordFlow(opts, ffmpeg, ffprobe, sayExe);
  else await dryRun(opts, ffmpeg, ffprobe, sayExe);
}

main().catch((error) => fail(error.message || String(error)));
