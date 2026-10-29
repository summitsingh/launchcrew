#!/usr/bin/env node
// LaunchCrew demo recording harness, source only.
// Records the real LaunchCrew UI with existing Playwright Chromium, then cuts
// honest evidence holds with ONE edit decision list and muxes offline macOS
// say narration plus captions with ffmpeg.
// Default is dry run. No recording without explicit --record.
// No route interception, no mocks, no fabricated responses, no fake LLM
// activity, no direct SQL seed, no API created state presented as UI.
// All runs, memories, campaigns, approvals, and exports are created through
// natural UI actions. Responses may be observed to collect run IDs, never
// replaced. Read only GET readbacks validate receipts and memory. Failures
// exit nonzero with the failing step, no placeholder pass.
// Private outputs only under .local/demo (gitignored). No IDs, evidence,
// recordings, or manifests are written to committed paths. No credentials are
// accepted, read, logged, or interpolated. Subprocesses use argv, never shell
// strings. This script never clicks Check photo and never makes paid calls.
// Keyless is proven before any mutation and rechecked through capture.
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
// slot_seconds sums to 170 with SAM and without Spark. ONE edit decision list
// derives video cuts, audio placement, captions, and manifest from these slots.
const SEGMENTS = [
  {
    id: 's1-brief', title: 'Wallet brief', slot: '0:00-0:12', slot_seconds: 12,
    say: 'LaunchCrew turns one demo idea into a pack you approve before export. Fictional wallet brief: forty nine dollars, Austin commuters, Instagram. Keyless deterministic flow.',
    caption: 'Fictional wallet brief. Keyless deterministic flow.',
  },
  {
    id: 's2-guard', title: 'Custom PriceGuard checker', slot: '0:12-0:32', slot_seconds: 20,
    say: 'This is a custom checker named PriceGuard. Its veto scope is price claims, exact match, a supported policy. Its rule is Block price claims. Free text rules outside the supported list stay advisory only and are never enforced.',
    caption: 'PriceGuard: supported price_claims policy. Other text stays advisory.',
  },
  {
    id: 's3-scout', title: 'Scout facts and sources', slot: '0:32-0:58', slot_seconds: 26,
    say: 'Scout sourced five demo facts with sources, plus three demo risks. These come from the local demo facts file and the demo brand brief. No external research ran, and no live product check is claimed.',
    caption: '5 demo facts, 3 demo risks. Demo sources. No external research.',
  },
  {
    id: 's4-seed', title: 'Seeded block and revision', slot: '0:58-1:22', slot_seconds: 24,
    say: 'With the seeded demo box checked, the unsupported claim best in Texas is blocked with a reason, then left out of the revised draft. PriceGuard also removes the forty nine dollar claim under its price policy. The final check shows zero blocked.',
    caption: 'Seeded demo: unsupported claim blocked and revised out.',
  },
  {
    id: 's5-replay', title: 'Replay', slot: '1:22-1:40', slot_seconds: 18,
    say: 'Replay compares two actual runs from this session by their stored run IDs. Same brief, different checker binding. The verdict difference comes from the recorded receipts, not from editing.',
    caption: 'Replay of two actual run IDs from this session.',
  },
  {
    id: 's6-memory', title: 'Memory edit', slot: '1:40-1:55', slot_seconds: 15,
    say: 'This is a prepared comparison from two actual runs made through the UI. After editing the memory rule, the next run blocks a different real claim. Nothing here is typed as a fake result.',
    caption: 'Prepared comparison. Two actual UI runs, before and after edit.',
  },
  {
    id: 's7-campaign', title: 'Campaign week', slot: '1:55-2:08', slot_seconds: 13,
    say: 'Campaign week holds seven distinct day packs. Each day stays pending until you approve it on its own. No batch approval, no auto publish.',
    caption: 'Seven distinct days. Each approved on its own.',
  },
  {
    id: 's8-sam', title: 'Separate photo result', slot: '2:08-2:25', slot_seconds: 17,
    say: 'This is the stored result from a separate authorized private jacket photo test. The photo is withheld. This wallet demo has not had a SAM photo check. Checked alone never means segmented.',
    caption: 'Separate private jacket test. Photo withheld. Wallet not SAM checked.',
  },
  {
    id: 's9-approve', title: 'Human approve and export', slot: '2:25-2:43', slot_seconds: 18,
    say: 'Nothing exports without your tap. Approval and export are recorded with the demo actor and time, and the receipt timeline keeps the history. Submission shows not attempted.',
    caption: 'Human approve, export download, stored timeline. Not attempted.',
  },
  {
    id: 's10-close', title: 'Close', slot: '2:43-2:50', slot_seconds: 7,
    say: 'LaunchCrew: one idea, three agents, one pack you approve. Demo only. Repo and site address on screen.',
    caption: 'Demo only. Closing card with repo and site address.',
  },
];
const SPARK_SLOT_SECONDS = 8;
const PUBLIC_REPO = 'https://github.com/summitsingh/launchcrew';

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
    '  HTTPS base URL, GET /api/health is status ok with auth disabled_demo,',
    '  GET /api/auth/status is enabled false, GET /api/model-capabilities shows',
    '  no configured text models, GET / 200, narration ids present, tools present.',
    '  Each new run and campaign receipt must show zero model calls with',
    '  deterministic fallback usage, else refuse. Keyless is rechecked.',
    '  Each say clip must fit its EDL slot, else shorten say plus doc.',
    '  Out dir must be under <repo>/.local to keep IDs and video private.',
    '  SAM card only from a validated sanitized proof file. No photo bytes,',
    '  digests, provider IDs, geometry, filenames, or crop data are accepted.',
    '  This script never clicks Check photo and never makes paid calls.',
    '',
    'Edit: ONE decision list cuts evidence holds to slots 12,20,26,24,18,15,',
    '  13,17,18,7 plus optional 8s Spark. Total at most 180. Setup and run',
    '  waits between holds are trimmed and logged, never sped up or faked.',
    '',
    'Outputs (all private, gitignored):',
    '  <out>/demo-ui.mp4, <out>/trimmed-ui.mp4, <out>/narration/*.m4a,',
    '  <out>/launchcrew-demo.mp4, <out>/launchcrew-demo.srt,',
    '  <out>/shot-manifest.json, <out>/edl.json, <out>/clips/*',
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

function parseJsonBody(res, label) {
  try {
    return JSON.parse(res.bodyText);
  } catch {
    fail(`${label} did not return valid JSON (status ${res.status}). Refusing.`);
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
  info(`checking ${clean} health plus keyless boundary...`);
  // Actual schemas from source: health has status/auth/approval_by, auth
  // status has enabled/user/live_verified, capabilities has spark and wonder
  // configured flags plus variants. Backend runs with model_enabled True but
  // calls models only when a server key exists, so no configured models plus
  // deterministic receipts proves the wallet flow never paid and stayed keyless.
  const health = await fetchStatus(`${clean}/api/health`);
  if (health.status !== 200) fail(`GET /api/health returned ${health.status}, expected 200`);
  const healthJson = parseJsonBody(health, 'GET /api/health');
  if (healthJson.status !== 'ok' || healthJson.auth !== 'disabled_demo' || healthJson.approval_by !== 'demo_placeholder') {
    fail(`keyless boundary refused: /api/health is status=${String(healthJson.status)} auth=${String(healthJson.auth)} approval_by=${String(healthJson.approval_by)}, expected ok/disabled_demo/demo_placeholder.`);
  }
  const auth = await fetchStatus(`${clean}/api/auth/status`);
  if (auth.status !== 200) fail(`GET /api/auth/status returned ${auth.status}, expected 200`);
  const authJson = parseJsonBody(auth, 'GET /api/auth/status');
  if (authJson.enabled !== false || authJson.live_verified !== false || authJson.user !== '') {
    fail(`keyless boundary refused: /api/auth/status is enabled=${String(authJson.enabled)} user=${String(authJson.user)} live_verified=${String(authJson.live_verified)}, expected false/empty/false.`);
  }
  const caps = await fetchStatus(`${clean}/api/model-capabilities`);
  if (caps.status !== 200) fail(`GET /api/model-capabilities returned ${caps.status}, expected 200`);
  const capsJson = parseJsonBody(caps, 'GET /api/model-capabilities');
  if (capsJson.spark_configured !== false || capsJson.wonder_configured !== false || capsJson.sam_configured !== false) {
    fail('keyless boundary refused: model capabilities show a configured model. Omit paid claims and recheck a keyless base URL.');
  }
  if (capsJson.spark_variant !== 'not_configured' || capsJson.wonder_variant !== 'not_configured') {
    fail(`keyless boundary refused: model variants are ${String(capsJson.spark_variant)}/${String(capsJson.wonder_variant)}, expected not_configured.`);
  }
  const home = await fetchStatus(`${clean}/`);
  if (home.status !== 200) fail(`GET / returned ${home.status}, expected 200`);
  info('health gate PASS (https, disabled_demo auth, no configured models, home 200)');
  return clean;
}

async function recheckKeyless(clean, label) {
  // Recheck the same boundary through capture. Any drift refuses.
  const health = await fetchStatus(`${clean}/api/health`);
  const auth = await fetchStatus(`${clean}/api/auth/status`);
  const caps = await fetchStatus(`${clean}/api/model-capabilities`);
  if (health.status !== 200 || auth.status !== 200 || caps.status !== 200) {
    fail(`keyless recheck failed at ${label}: a gate endpoint is not 200. Refusing to continue.`);
  }
  const h = parseJsonBody(health, 'recheck health');
  const a = parseJsonBody(auth, 'recheck auth');
  const c = parseJsonBody(caps, 'recheck capabilities');
  if (h.auth !== 'disabled_demo' || a.enabled !== false || c.spark_configured !== false || c.wonder_configured !== false) {
    fail(`keyless recheck failed at ${label}: boundary drifted. Refusing to continue.`);
  }
  info(`keyless recheck OK at ${label}`);
}

async function fetchReceipt(clean, runId, label) {
  const res = await fetchStatus(`${clean}/api/runs/${encodeURIComponent(runId)}/receipt`);
  if (res.status !== 200) fail(`readback failed at ${label}: GET receipt for ${runId.slice(0, 12)} returned ${res.status}. Refusing to label without a receipt.`);
  return parseJsonBody(res, `receipt ${label}`);
}

function assertKeylessReceipt(receipt, label) {
  // Zero actual model calls with deterministic usage. Any spark use refuses.
  const usage = receipt.model_usage || receipt.modelUsage || null;
  if (!usage) fail(`keyless receipt check failed at ${label}: no stored model_usage. Refusing.`);
  const calls = usage.spark_calls ?? usage.sparkCalls ?? null;
  const wonderAttempts = usage.wonder_attempts ?? usage.wonderAttempts ?? null;
  if (calls !== 0) fail(`keyless receipt check failed at ${label}: spark_calls is ${String(calls)}, expected 0. Refusing.`);
  if (wonderAttempts !== 0) fail(`keyless receipt check failed at ${label}: wonder attempts is ${String(wonderAttempts)}, expected 0. Refusing.`);
  if (usage.mode !== 'deterministic_fallback' || usage.spark_mode !== 'deterministic_fallback') {
    fail(`keyless receipt check failed at ${label}: mode is ${String(usage.mode)}/${String(usage.spark_mode)}, expected deterministic_fallback. Refusing.`);
  }
  if (usage.model_used !== 'none' || usage.wonder_used !== false) {
    fail(`keyless receipt check failed at ${label}: model_used=${String(usage.model_used)} wonder_used=${String(usage.wonder_used)}. Refusing.`);
  }
  if (usage.tokens_known !== false) fail(`keyless receipt check failed at ${label}: tokens_known is not false. Refusing.`);
  const scoutMode = receipt.scout ? receipt.scout.model_mode : null;
  if (scoutMode !== null && scoutMode !== 'deterministic_fallback') {
    fail(`keyless receipt check failed at ${label}: scout model_mode is ${String(scoutMode)}. Refusing.`);
  }
  info(`keyless receipt OK at ${label} (${String(receipt.run_id || '').slice(0, 12)})`);
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
    try {
      const toggle = page.getByRole('button', { name: 'Advanced', exact: true });
      if ((await toggle.getAttribute('aria-expanded')) === 'false') await toggle.click({ timeout: 15000 });
      info('selector OK: Advanced toggle expands agent builder');
    } catch {
      fail('dry run selector missing: Advanced toggle. Recording would refuse here.');
    }
    const selectors = [
      ['Launch brief nav', 'button:has-text("Launch brief")'],
      ['Agent builder nav', 'button:has-text("Agent builder")'],
      ['Brief textarea', 'label:has-text("Product, audience, and launch channel")'],
      ['Scout agent select', '#run-scout'],
      ['Maker agent select', '#run-agent'],
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
  const includeSamDry = Boolean(opts.samProof);
  const activeDry = includeSamDry ? SEGMENTS : SEGMENTS.filter((s) => s.id !== 's8-sam');
  const sparkExtra = opts.sparkRunId ? SPARK_SLOT_SECONDS : 0;
  const totalDry = activeDry.reduce((sum, s) => sum + s.slot_seconds, 0) + sparkExtra;
  console.log('');
  console.log('Dry run PASS. To record after live proof, root runs the same command with --record.');
  console.log('Planned EDL slots: ' + activeDry.map((s) => `${s.slot} ${s.title} (${s.slot_seconds}s)`).join(' | ') + (opts.sparkRunId ? ` | spark-proof Stored Spark receipt (${SPARK_SLOT_SECONDS}s)` : ''));
  console.log(`EDL total ${totalDry}s, target ${TARGET_SECONDS}s, hard limit ${HARD_LIMIT_SECONDS}s. Nothing was created.`);
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
  // Root alone correlates the private proof before supplying this JSON.
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
<h1>Stored jacket photo result (sanitized summary)</h1>
<p>Separate private jacket photo test. The photo is withheld. Stored in a separate private host DB, not the public AWS DB.</p>
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

function writeClosingCard(path, baseUrl) {
  // Closing card carries repo plus site addresses on screen. Playwright video
  // captures the viewport only, not the browser address bar, so this card is
  // the honest on screen source. No verified claim is printed here; the
  // manifest records the HTTPS health gate that root verifies at runtime.
  const html = `<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>LaunchCrew demo close</title>
<style>body{font-family:system-ui,sans-serif;background:#0b0e14;color:#e8ecf1;margin:0;padding:40px}
.card{max-width:900px;margin:0 auto;background:#141a24;border-radius:16px;padding:32px}
.badge{display:inline-block;background:#8ab4ff;color:#0b1a33;padding:4px 12px;border-radius:999px;font-weight:700}
dl{display:grid;grid-template-columns:220px 1fr;gap:8px 16px;margin-top:16px}
dt{color:#9aa4b2}dd{margin:0;word-break:break-all}
.note{margin-top:16px;color:#9aa4b2}</style></head><body>
<div class="card"><span class="badge">CLOSING CARD</span>
<h1>LaunchCrew demo close</h1>
<p>Demo only. No upload, publication, or submission is claimed.</p>
<dl>
<dt>Public repo</dt><dd>${escapeHtml(PUBLIC_REPO)}</dd>
<dt>Site address</dt><dd>${escapeHtml(baseUrl)}</dd>
</dl>
<p class="note">Addresses shown on screen in the viewport. Recorded base URL only, no localhost shown as public.</p>
</div></body></html>
`;
  writeFileSync(path, html);
}

function assertMemoryPair(beforeReceipt, afterReceipt, memId) {
  // Exact blocked claims, final draft differences, no supersede. Fail honestly.
  const beforeBlocked = Array.isArray(beforeReceipt.blocked_claims) ? beforeReceipt.blocked_claims : [];
  const afterBlocked = Array.isArray(afterReceipt.blocked_claims) ? afterReceipt.blocked_claims : [];
  if (!beforeBlocked.includes('$49')) fail(`memory check failed: before receipt blocked_claims is [${beforeBlocked.join(', ')}], expected to include $49. Refusing labels.`);
  if (beforeBlocked.includes('Designed in Texas')) fail('memory check failed: before receipt unexpectedly blocks Designed in Texas. Refusing labels.');
  if (!afterBlocked.includes('Designed in Texas')) fail(`memory check failed: after receipt blocked_claims is [${afterBlocked.join(', ')}], expected to include Designed in Texas. Refusing labels.`);
  if (afterBlocked.includes('$49')) fail('memory check failed: after receipt still blocks $49 after the edit. Refusing labels.');
  const beforeV1 = (beforeReceipt.checker_v1 && beforeReceipt.checker_v1.blocked_claims) || [];
  const afterV1 = (afterReceipt.checker_v1 && afterReceipt.checker_v1.blocked_claims) || [];
  const beforeClaims = beforeV1.map((e) => e.claim);
  const afterClaims = afterV1.map((e) => e.claim);
  if (!beforeClaims.includes('$49')) fail(`memory check failed: before checker_v1 blocked [${beforeClaims.join(', ')}], expected $49. Refusing labels.`);
  if (!afterClaims.includes('Designed in Texas')) fail(`memory check failed: after checker_v1 blocked [${afterClaims.join(', ')}], expected Designed in Texas. Refusing labels.`);
  const beforePost = (beforeReceipt.maker_draft_v2 && beforeReceipt.maker_draft_v2.post) || '';
  const afterPost = (afterReceipt.maker_draft_v2 && afterReceipt.maker_draft_v2.post) || '';
  if (beforePost.includes('$49')) fail('memory check failed: before final draft still contains $49. Revision did not apply. Refusing labels.');
  if (afterPost.includes('Designed in Texas')) fail('memory check failed: after final draft still contains Designed in Texas. Revision did not apply. Refusing labels.');
  if (beforePost === afterPost) fail('memory check failed: final drafts are identical, expected a revision difference. Refusing labels.');
  for (const [label, receipt] of [['before', beforeReceipt], ['after', afterReceipt]]) {
    if ((receipt.revision || 0) !== 0) fail(`memory check failed: ${label} receipt revision is ${String(receipt.revision)}, expected 0 with no supersede. Refusing labels.`);
    if (Array.isArray(receipt.revision_history) && receipt.revision_history.length !== 0) fail(`memory check failed: ${label} receipt has superseded revisions. Refusing labels.`);
    if (receipt.approved_revision !== null && receipt.approved_revision !== undefined) fail(`memory check failed: ${label} receipt has an approved revision. Refusing labels.`);
    const used = Array.isArray(receipt.memory_used) ? receipt.memory_used.map((e) => e.id) : [];
    if (!used.includes(memId)) fail(`memory check failed: ${label} receipt memory_used does not list ${memId.slice(0, 12)}. Refusing labels.`);
  }
  info('memory receipt pair OK (exact blocks, draft difference, no supersede)');
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

  // Phase 1: narration clips first. Each clip must fit its EDL slot, else
  // shorten the SEGMENTS say string plus docs/demo-narration.md together.
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
      if (seconds > seg.slot_seconds) {
        fail(`narration clip ${seg.id} is ${seconds.toFixed(1)}s, over its ${seg.slot_seconds}s EDL slot. Shorten the SEGMENTS say string and docs/demo-narration.md together, then re-run.`);
      }
      clipPlan.push({ ...seg, m4a, seconds });
      info(`${seg.id}: ${seconds.toFixed(1)}s fits ${seg.slot_seconds}s slot`);
    }
    const slotTotal = activeSegments.reduce((sum, s) => sum + s.slot_seconds, 0) + (opts.sparkRunId ? SPARK_SLOT_SECONDS : 0);
    info(`EDL slot total ${slotTotal}s (target ${TARGET_SECONDS}s, hard limit ${HARD_LIMIT_SECONDS}s)`);
    if (slotTotal > HARD_LIMIT_SECONDS) fail(`EDL slot total ${slotTotal}s exceeds the ${HARD_LIMIT_SECONDS}s hard limit. Refusing.`);
  } else {
    for (const seg of activeSegments) clipPlan.push({ ...seg, m4a: '', seconds: 0 });
    warn('audio disabled: video cuts still follow EDL slots, no narration placed');
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
  const takeElapsed = () => (Date.now() - takeStart) / 1000;
  // EDL captures actual source in/out per evidence hold. Video cuts, audio
  // placement, captions, and manifest all derive from this ONE list. Holds
  // between source_in and source_out are the only kept footage, in real
  // order. Setup, navigation, and run waits outside holds are trimmed and
  // logged, never sped up and never faked.
  const edl = [];
  const slotSecondsFor = (id) => {
    if (id === 'spark-proof') return SPARK_SLOT_SECONDS;
    const seg = SEGMENTS.find((s) => s.id === id);
    if (!seg) fail(`unknown EDL id ${id}`);
    return seg.slot_seconds;
  };
  const beginHold = (id) => takeElapsed();
  const endHold = async (page, id, sourceIn, note) => {
    // Fixed slots include actual action elapsed time. SourceIn is placed
    // before the narrated central actions, shows keep evidence after, and
    // this wait covers only the remaining slot duration. If actions plus
    // readable evidence already exceed the slot, fail honestly so the EDL
    // cut never silently drops actual proof. Rebalance within the hard
    // limit is a source change, not a silent trim.
    const slot = slotSecondsFor(id);
    const elapsedAtEntry = takeElapsed() - sourceIn;
    if (elapsedAtEntry > slot + 1.0) {
      fail(`EDL hold ${id} actions already took ${elapsedAtEntry.toFixed(1)}s, over its ${slot}s slot. Essential actions plus readable evidence do not fit. Rebalance slots within ${HARD_LIMIT_SECONDS}s total or trim setup inside the hold. Refusing to cut actual proof.`);
    }
    while (takeElapsed() - sourceIn < slot) {
      await page.waitForTimeout(500);
    }
    const sourceOut = takeElapsed();
    if (sourceOut - sourceIn > slot + 2.0) {
      fail(`EDL hold ${id} kept ${(sourceOut - sourceIn).toFixed(1)}s, over its ${slot}s slot. Refusing to cut actual proof or pad fake video.`);
    }
    edl.push({ id, slot_seconds: slot, source_in: sourceIn, source_out: sourceOut, note });
    manifest.segments.push({ id, source_in_seconds: sourceIn, source_out_seconds: sourceOut, slot_seconds: slot, note });
    info(`hold ${id}: kept ${slot}s from take ${sourceIn.toFixed(1)}s to ${(sourceIn + slot).toFixed(1)}s (${note})`);
  };

  try {
    const context = await browser.newContext({
      viewport: VIEWPORT,
      recordVideo: { dir: clipsDir, size: { width: VIEWPORT.width, height: VIEWPORT.height } },
      acceptDownloads: true,
      ignoreHTTPSErrors: false,
    });
    const page = await context.newPage();

    const mustClick = async (role, name, exact = true) => {
      try {
        await page.getByRole(role, { name, exact }).click({ timeout: 20000 });
      } catch {
        fail(`selector failed: role=${role} name="${name}". UI changed or app is down. Refusing to fake this step.`);
      }
    };
    const showAdvanced = async () => {
      try {
        const toggle = page.getByRole('button', { name: 'Advanced', exact: true });
        if ((await toggle.getAttribute('aria-expanded')) === 'false') await toggle.click({ timeout: 20000 });
      } catch {
        fail('Advanced toggle missing or unreadable. UI changed or app is down. Refusing to fake this step.');
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
    const showInViewport = async (locator, label) => {
      // DOM presence is not proof. Scroll into the viewport and assert the
      // box is actually readable inside 1600x900.
      try {
        await locator.first().scrollIntoViewIfNeeded({ timeout: 20000 });
      } catch {
        fail(`evidence not scrollable into view: ${label}. Refusing to claim it.`);
      }
      await page.waitForTimeout(600);
      const box = await locator.first().boundingBox().catch(() => null);
      if (!box) fail(`evidence has no bounding box in viewport: ${label}. Refusing to claim it.`);
      if (box.y < 0 || box.x < 0 || box.y + box.height > VIEWPORT.height + 4 || box.x + box.width > VIEWPORT.width + 4) {
        fail(`evidence is outside the viewport: ${label} at y=${Math.round(box.y)}. Scroll proof failed.`);
      }
      if (box.height < 12 || box.width < 40) fail(`evidence box is too small to read: ${label}. Refusing.`);
    };

    await page.goto(clean, { waitUntil: 'domcontentloaded', timeout: 30000 });

    // S1: wallet brief visible with approved demo facts. Hold starts on the
    // asserted evidence, so setup navigation before the hold is trimmed.
    await mustClick('button', 'Launch brief', false);
    await mustFill('Product, audience, and launch channel', WALLET_BRIEF);
    await showInViewport(page.getByLabel('Product, audience, and launch channel'), 'wallet brief textarea');
    await page.screenshot({ path: join(shotsDir, 's1-brief.png') });
    {
      const sourceIn = beginHold('s1-brief');
      await showInViewport(page.getByLabel('Product, audience, and launch channel'), 's1 wallet brief');
      await endHold(page, 's1-brief', sourceIn, 'wallet brief filled, demo facts aside');
    }

    // S2: create Scout and PriceGuard through the Agent builder UI.
    // Scout is prerequisite setup and stays trimmed. PriceGuard creation
    // plus dry-run preview are the narrated central actions, so the kept
    // hold starts before PriceGuard creation and keeps evidence after.
    async function createAgent(fields) {
      await showAdvanced();
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
    {
      const sourceIn = beginHold('s2-guard');
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
      await showInViewport(page.getByText('Enforced policies: price_claims'), 's2 enforced policies');
      await endHold(page, 's2-guard', sourceIn, `PriceGuard ${checkerName} created plus enforced price_claims`);
    }

    // Natural runs through the Launch brief UI. Observe responses, never replace them.
    // After each run, read back the stored receipt and prove zero model calls.
    async function runViaUi({ checker, seed, memoryIds = '' }, label) {
      await mustClick('button', 'Launch brief', false);
      await mustSelect('Scout agent', scoutName);
      await mustSelect('Maker agent', 'Maker');
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
        // Completed review renders both headings. Disambiguate the union
        // so strict mode never matches 2, while still requiring real
        // completion. Missing UI still times out and fails below.
        await page.getByRole('heading', { name: 'Unsupported claims stopped.', exact: true }).or(
          page.getByRole('heading', { name: 'Ready for your review.', exact: true }),
        ).first().waitFor({ timeout: 90000 });
      } catch {
        fail(`run ${uiId.slice(0, 12)} never reached review. Refusing to fake completion.`);
      }
      const receipt = await fetchReceipt(clean, uiId, label || 'run');
      assertKeylessReceipt(receipt, label || 'run');
      await recheckKeyless(clean, label || 'run');
      return uiId;
    }

    // S3: default checker, clean (seed off). Scout facts plus risks on screen.
    // The Create draft tap plus actual run progress are the central
    // behavior, so the kept hold starts before the run and keeps the
    // facts evidence after. Fast stages are captured honestly with no
    // fake pause; an already finished run shows its stored completed
    // review and stored timestamps without invented waiting.
    let runDefault = '';
    {
      const sourceIn = beginHold('s3-scout');
      runDefault = await runViaUi({ checker: 'Checker', seed: false }, 's3 default run');
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
      await showInViewport(page.locator('section[aria-label="Scout facts and sources"]'), 's3 scout section');
      await showInViewport(page.locator('section[aria-label="Scout facts and sources"] .scout-fact').first(), 's3 first fact');
      await showInViewport(page.getByText('No external research was run'), 's3 honesty copy');
      await endHold(page, 's3-scout', sourceIn, `default run ${runDefault.slice(0, 12)} created plus 5 facts 3 risks`);
    }

    // PriceGuard clean run shows the genuine price veto without any seed.
    // Trimmed setup for the replay baseline. S4 keeps the seeded run.
    const runGuarded = await runViaUi({ checker: checkerName, seed: false }, 's4 guarded run');
    manifest.runs.runGuarded = runGuarded;
    await page.screenshot({ path: join(shotsDir, 's4a-guarded.png') });

    // S4: seeded run with PriceGuard shows both the seed block and the price veto.
    // The seed checkbox plus Create draft plus actual progress are central,
    // so the kept hold starts before the seeded run and keeps the block
    // plus the revised final draft and the zero-block final check after.
    // Fast stages are captured honestly with no fake pause; an already
    // finished run shows its stored completed review without invented waiting.
    let runSeeded = '';
    {
      const sourceIn = beginHold('s4-seed');
      runSeeded = await runViaUi({ checker: checkerName, seed: true }, 's4 seeded run');
      manifest.runs.runSeeded = runSeeded;
      try {
        await page.getByText('best in Texas', { exact: true }).first().waitFor({ timeout: 20000 });
        await page.getByText('Current Instagram draft').first().waitFor({ timeout: 20000 });
        await page.getByText('Final blocked count: 0').first().waitFor({ timeout: 20000 });
      } catch {
        fail('seeded block, revised draft, or zero-block final check never appeared. Refusing to fake the revision.');
      }
      await page.screenshot({ path: join(shotsDir, 's4-seed.png') });
      await showInViewport(page.getByText('best in Texas', { exact: true }).first(), 's4 seeded block');
      await showInViewport(page.getByText('Current Instagram draft').first(), 's4 revised draft');
      await showInViewport(page.getByText('Final blocked count: 0').first(), 's4 zero-block final check');
      await endHold(page, 's4-seed', sourceIn, `seeded run ${runSeeded.slice(0, 12)} created plus block plus revised plus zero`);
    }

    // S5: Replay the two actual run IDs.
    await showAdvanced();
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
    {
      const sourceIn = beginHold('s5-replay');
      await showInViewport(page.getByText('Stage bindings changed: true'), 's5 binding difference');
      await endHold(page, 's5-replay', sourceIn, 'replay compared two actual run IDs');
    }

    // S6: Memory rule before and after, two actual UI runs, labelled comparison.
    // Labels derive from stored receipts only after exact checks pass.
    await showAdvanced();
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
    const memBefore = await runViaUi({ checker: 'Checker', seed: false, memoryIds: memId }, 's6 before run');
    manifest.runs.memBefore = memBefore;
    await page.screenshot({ path: join(shotsDir, 's6-before.png') });
    await showAdvanced();
    await mustClick('button', 'Memory', false);
    await memCard.getByRole('button', { name: 'Edit memory', exact: true }).click({ timeout: 20000 });
    await mustFill('Edit content JSON object', '{"blocked_claims": [{"claim": "Designed in Texas", "reason": "Edited rule"}]}');
    await mustClick('button', 'Save memory', true);
    // Wait the true UI save close plus persisted content, then read back.
    try {
      await memCard.getByRole('button', { name: 'Edit memory', exact: true }).waitFor({ timeout: 20000 });
      await memCard.locator('pre', { hasText: 'Designed in Texas' }).waitFor({ timeout: 20000 });
    } catch {
      fail('memory edit was not confirmed in the UI with updated content. Refusing to run after.');
    }
    {
      const memRes = await fetchStatus(`${clean}/api/memory/${encodeURIComponent(memId)}`);
      if (memRes.status !== 200) fail(`memory readback failed for ${memId.slice(0, 12)}. Refusing labels.`);
      const memJson = parseJsonBody(memRes, 'memory readback');
      const blockedList = memJson.content && memJson.content.blocked_claims;
      const hasTexas = Array.isArray(blockedList) && blockedList.some((e) => e && e.claim === 'Designed in Texas');
      if (memJson.kind !== 'blocked_rule' || !hasTexas) fail('memory readback does not show the edited Designed in Texas rule. Refusing labels.');
      info('memory edit persisted and read back OK');
    }
    const memAfter = await runViaUi({ checker: 'Checker', seed: false, memoryIds: memId }, 's6 after run');
    manifest.runs.memAfter = memAfter;
    await page.screenshot({ path: join(shotsDir, 's6-after.png') });
    {
      const beforeReceipt = await fetchReceipt(clean, memBefore, 's6 before');
      const afterReceipt = await fetchReceipt(clean, memAfter, 's6 after');
      assertKeylessReceipt(beforeReceipt, 's6 before');
      assertKeylessReceipt(afterReceipt, 's6 after');
      assertMemoryPair(beforeReceipt, afterReceipt, memId);
      const beforeLabelClaim = String((beforeReceipt.checker_v1.blocked_claims[0] || {}).claim || '$49');
      const afterLabelClaim = String((afterReceipt.checker_v1.blocked_claims.find((e) => e.claim === 'Designed in Texas') || {}).claim || 'Designed in Texas');
      writeComparisonCard(
        join(shotsDir, 's6-comparison.html'),
        'Memory edit changes the next run',
        's6-before.png', 's6-after.png',
        `run ${memBefore.slice(0, 12)} blocked ${beforeLabelClaim}`,
        `run ${memAfter.slice(0, 12)} blocked ${afterLabelClaim}`,
        'Prepared comparison. Both screenshots are actual UI captures from this session. Labels derive from stored receipts.',
      );
    }
    await page.goto('file://' + join(shotsDir, 's6-comparison.html'), { waitUntil: 'domcontentloaded' });
    try {
      await page.getByText('PREPARED COMPARISON').waitFor({ timeout: 10000 });
    } catch {
      fail('comparison card failed to render.');
    }
    {
      const sourceIn = beginHold('s6-memory');
      await showInViewport(page.getByText('PREPARED COMPARISON'), 's6 comparison badge');
      await endHold(page, 's6-memory', sourceIn, 'memory before and after comparison card');
    }
    await page.goto(clean, { waitUntil: 'domcontentloaded' });

    // S7: Campaign week, seven distinct days. DOM count alone is not proof,
    // so each day card is scrolled into the viewport and asserted readable
    // inside the actual shot hold. Approvals stay per day and independent.
    await showAdvanced();
    await mustClick('button', 'Campaign', false);
    await mustSelect('Maker agent', 'Maker');
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
    const weekId = (await page.locator('section .run-id').first().innerText()).trim();
    manifest.runs.campaignId = weekId;
    {
      const campRes = await fetchStatus(`${clean}/api/campaigns/${encodeURIComponent(weekId)}`);
      if (campRes.status !== 200) fail(`campaign readback failed for ${weekId.slice(0, 12)}. Refusing seven claim.`);
      const campJson = parseJsonBody(campRes, 'campaign readback');
      if (!Array.isArray(campJson.days) || campJson.days.length !== 7) fail('campaign readback does not show seven stored days. Refusing seven claim.');
      for (const day of campJson.days) {
        const dayReceipt = await fetchReceipt(clean, day.run_id, `s7 day ${day.day}`);
        assertKeylessReceipt(dayReceipt, `s7 day ${day.day}`);
        if (dayReceipt.campaign_day !== day.day) fail(`campaign day ${day.day} receipt mismatch. Refusing.`);
      }
      await recheckKeyless(clean, 's7 campaign');
      info('campaign seven receipts all keyless deterministic');
    }
    await page.screenshot({ path: join(shotsDir, 's7-campaign.png') });
    {
      const sourceIn = beginHold('s7-campaign');
      for (let day = 1; day <= 7; day += 1) {
        const card = page.locator('article', { has: page.locator(`h3:text("Day ${day}:")`) });
        await showInViewport(card.locator('h3'), `s7 day ${day} heading`);
        await showInViewport(card, `s7 day ${day} card`);
      }
      await showInViewport(page.getByRole('heading', { name: 'Day 7: Launch offer' }), 's7 final day evidence');
      await endHold(page, 's7-campaign', sourceIn, 'seven distinct campaign days scrolled readable');
    }

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
      {
        const sourceIn = beginHold('s8-sam');
        await showInViewport(page.getByText('SEPARATE PRIVATE TEST'), 's8 sam badge');
        await endHold(page, 's8-sam', sourceIn, `separate private result, method ${samProof.method}`);
      }
      await page.goto(clean, { waitUntil: 'domcontentloaded' });
    } else {
      manifest.segments.push({ id: 's8-sam', skipped: true, note: 'skipped honestly, no sanitized proof supplied' });
      info('s8-sam skipped honestly, no EDL entry');
    }

    // Optional stored Spark proof with its own explicit 8s EDL slot, silent.
    // Read back only, shown apart. Never claims the new wallet used models.
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
      {
        const sourceIn = beginHold('spark-proof');
        await showInViewport(page.getByRole('heading', { name: 'Receipt', exact: true }), 'spark receipt heading');
        await endHold(page, 'spark-proof', sourceIn, 'stored Spark receipt shown separately from keyless flow');
      }
      await page.goto(clean, { waitUntil: 'domcontentloaded' });
    }

    // S9: human approve plus export download on the seeded run, then receipt timeline.
    // Queue navigation plus the pending check stay trimmed setup. The kept
    // hold starts before the actual Approve tap and keeps the Export
    // download, receipt navigation, and readable timeline after.
    await page.getByRole('navigation', { name: 'Workspace' }).getByRole('button', { name: 'Approval queue' }).click({ timeout: 20000 });
    const card = page.locator(`[data-run-id="${runSeeded}"]`);
    try {
      await card.getByText('Pending approval', { exact: true }).waitFor({ timeout: 30000 });
    } catch {
      fail('seeded run is not pending approval. Refusing to fake the approval tap.');
    }
    {
      const sourceIn = beginHold('s9-approve');
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
      {
        const approvedReceipt = await fetchReceipt(clean, runSeeded, 's9 approved');
        assertKeylessReceipt(approvedReceipt, 's9 approved');
        await recheckKeyless(clean, 's9 approved');
      }
      await page.screenshot({ path: join(shotsDir, 's9-receipt.png') });
      await showInViewport(page.getByText('Not attempted', { exact: true }), 's9 not attempted');
      await showInViewport(page.getByRole('heading', { name: 'Recorded events' }), 's9 timeline');
      await endHold(page, 's9-approve', sourceIn, 'actual approve tap plus export plus timeline, not attempted');
    }

    // S10: closing card with repo plus site addresses on screen in viewport.
    {
      const closePath = join(shotsDir, 's10-close.html');
      writeClosingCard(closePath, clean);
      await page.goto('file://' + closePath, { waitUntil: 'domcontentloaded' });
      try {
        await page.getByText('CLOSING CARD').waitFor({ timeout: 10000 });
        await page.getByText(PUBLIC_REPO, { exact: false }).waitFor({ timeout: 10000 });
      } catch {
        fail('closing card failed to render repo address.');
      }
      await page.screenshot({ path: join(shotsDir, 's10-close.png') });
      const sourceIn = beginHold('s10-close');
      await showInViewport(page.getByText('CLOSING CARD'), 's10 closing badge');
      await showInViewport(page.getByText(PUBLIC_REPO, { exact: false }), 's10 repo address');
      await endHold(page, 's10-close', sourceIn, `closing card on ${clean}`);
    }

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

  // Phase 3: ONE EDL drives video cuts, audio placement, captions, manifest.
  const uiMp4 = join(outDir, 'demo-ui.mp4');
  if (!existsSync(uiMp4)) fail('UI video missing after recording. Refusing to fake output.');
  if (edl.length === 0) fail('no EDL entries were captured. Refusing to fake output.');
  let slotCursor = 0;
  for (const entry of edl) {
    const kept = entry.source_out - entry.source_in;
    if (kept + 0.5 < entry.slot_seconds) {
      fail(`EDL hold ${entry.id} kept only ${kept.toFixed(1)}s, expected ${entry.slot_seconds}s. Evidence too short, refusing to pad video.`);
    }
    if (kept > entry.slot_seconds + 2.0) {
      fail(`EDL hold ${entry.id} kept ${kept.toFixed(1)}s, over its ${entry.slot_seconds}s slot. Actions plus evidence do not fit, refusing to cut actual proof.`);
    }
    entry.slot_start = slotCursor;
    entry.slot_end = slotCursor + entry.slot_seconds;
    slotCursor = entry.slot_end;
  }
  const slotTotal = slotCursor;
  if (slotTotal > HARD_LIMIT_SECONDS) fail(`EDL total ${slotTotal}s exceeds the ${HARD_LIMIT_SECONDS}s hard limit. Refusing.`);
  const trimmedSpans = [];
  let prevOut = 0;
  for (const entry of edl) {
    if (entry.source_in > prevOut + 0.1) trimmedSpans.push({ from_take: prevOut, to_take: entry.source_in, reason: 'setup, navigation, or run wait trimmed' });
    prevOut = entry.source_in + entry.slot_seconds;
  }
  manifest.edl = edl;
  manifest.trimmed_spans = trimmedSpans;
  manifest.slot_total_seconds = slotTotal;
  writeFileSync(join(outDir, 'edl.json'), JSON.stringify({ base_url: clean, slot_total_seconds: slotTotal, entries: edl, trimmed_spans: trimmedSpans }, null, 2));
  info(`EDL total ${slotTotal}s from ${edl.length} evidence holds in real order. Trimmed ${trimmedSpans.length} setup and wait spans.`);

  const finalMp4 = join(outDir, 'launchcrew-demo.mp4');
  const srtPath = join(outDir, 'launchcrew-demo.srt');
  const trimmedMp4 = join(outDir, 'trimmed-ui.mp4');

  // Video: cut exactly slot_seconds from each source_in, concat in EDL order.
  // No speedup, no freeze frames, no reordered evidence.
  {
    const cutList = [];
    for (let i = 0; i < edl.length; i += 1) {
      const entry = edl[i];
      const cutPath = join(clipsDir, `edl_${String(i).padStart(2, '0')}_${entry.id}.mp4`);
      const cut = await runTool(ffmpeg, ['-y', '-ss', String(entry.source_in), '-i', uiMp4, '-t', String(entry.slot_seconds), '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-an', cutPath], 'ffmpeg edl cut');
      if (!cut.ok) fail(`ffmpeg EDL cut failed for ${entry.id}: ${cut.stderr.slice(0, 500)}`);
      cutList.push(`file '${cutPath.replace(/'/g, "'\\''")}'`);
    }
    const videoListPath = join(clipsDir, 'edl-video.txt');
    writeFileSync(videoListPath, cutList.join('\n') + '\n');
    const joinVideo = await runTool(ffmpeg, ['-y', '-f', 'concat', '-safe', '0', '-i', videoListPath, '-c:v', 'libx264', '-pix_fmt', 'yuv420p', trimmedMp4], 'ffmpeg edl join');
    if (!joinVideo.ok) fail(`ffmpeg EDL join failed: ${joinVideo.stderr.slice(0, 500)}`);
    manifest.trimmed_video = 'trimmed-ui.mp4';
  }

  // Captions from EDL slot times, contiguous, no invented gaps.
  {
    const srtBlocks = [];
    for (let i = 0; i < edl.length; i += 1) {
      const entry = edl[i];
      const seg = SEGMENTS.find((s) => s.id === entry.id);
      const title = seg ? seg.title : 'Stored Spark receipt';
      const caption = seg ? seg.caption : 'Separate stored Spark receipt. Keyless wallet stays apart.';
      const slotLabel = seg ? seg.slot : 'spark';
      srtBlocks.push(`${i + 1}\n${formatSrtTime(entry.slot_start)} --> ${formatSrtTime(entry.slot_end)}\n[${slotLabel} ${title}] ${caption}\n`);
    }
    writeFileSync(srtPath, srtBlocks.join('\n'));
  }

  if (opts.audio) {
    // Audio: pad each say clip with silence to its slot, silent slot for
    // Spark, then concat in EDL order so audio aligns to video cuts.
    const paddedList = [];
    for (const entry of edl) {
      if (entry.id === 'spark-proof') {
        const silencePath = join(narrationDir, 'spark-proof-silence.m4a');
        const silence = await runTool(ffmpeg, ['-y', '-f', 'lavfi', '-i', 'anullsrc=r=44100:cl=stereo', '-t', String(entry.slot_seconds), '-c:a', 'aac', '-b:a', '128k', silencePath], 'ffmpeg silence');
        if (!silence.ok) fail(`ffmpeg silence failed: ${silence.stderr.slice(0, 500)}`);
        paddedList.push(`file '${silencePath.replace(/'/g, "'\\''")}'`);
        entry.audio_seconds = 0;
      } else {
        const clip = clipPlan.find((c) => c.id === entry.id);
        if (!clip || !clip.m4a) fail(`missing narration clip for EDL entry ${entry.id}. Refusing.`);
        const paddedPath = join(narrationDir, `${entry.id}.padded.m4a`);
        const pad = await runTool(ffmpeg, ['-y', '-i', clip.m4a, '-af', `apad,atrim=0:${entry.slot_seconds}`, '-c:a', 'aac', '-b:a', '128k', paddedPath], 'ffmpeg pad');
        if (!pad.ok) fail(`ffmpeg audio pad failed for ${entry.id}: ${pad.stderr.slice(0, 500)}`);
        paddedList.push(`file '${paddedPath.replace(/'/g, "'\\''")}'`);
        entry.audio_seconds = clip.seconds;
      }
    }
    const audioListPath = join(narrationDir, 'edl-concat.txt');
    writeFileSync(audioListPath, paddedList.join('\n') + '\n');
    const narrationTrack = join(narrationDir, 'narration.m4a');
    const concat = await runTool(ffmpeg, ['-y', '-f', 'concat', '-safe', '0', '-i', audioListPath, '-c', 'copy', narrationTrack], 'ffmpeg concat');
    if (!concat.ok) fail(`ffmpeg narration concat failed: ${concat.stderr.slice(0, 500)}`);
    const mux = await runTool(ffmpeg, ['-y', '-i', trimmedMp4, '-i', narrationTrack, '-c:v', 'copy', '-c:a', 'aac', '-map', '0:v:0', '-map', '1:a:0', '-movflags', '+faststart', finalMp4], 'ffmpeg mux');
    if (!mux.ok) fail(`ffmpeg mux failed: ${mux.stderr.slice(0, 500)}`);
  } else {
    copyFileSync(trimmedMp4, finalMp4);
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
    info(`ffprobe: ${duration.toFixed(1)}s, ${streams.width}x${streams.height}, audio ${streams.hasAudio ? 'yes' : 'no'} (EDL ${slotTotal}s)`);
    if (streams.width !== VIEWPORT.width || streams.height !== VIEWPORT.height) {
      fail(`dimensions are ${streams.width}x${streams.height}, expected ${VIEWPORT.width}x${VIEWPORT.height}. Refusing to pass.`);
    }
    if (opts.audio && !streams.hasAudio) fail('final video has no audio track. Refusing to pass.');
    if (duration > HARD_LIMIT_SECONDS) {
      fail(`final video is ${duration.toFixed(1)}s, over the ${HARD_LIMIT_SECONDS}s hard limit. No fake pass.`);
    }
    if (Math.abs(duration - slotTotal) > 3) {
      fail(`final video is ${duration.toFixed(1)}s but EDL total is ${slotTotal}s. Audio, video, and captions diverged. Refusing to pass.`);
    }
    if (duration > TARGET_SECONDS + 10 && slotTotal <= TARGET_SECONDS + 10) {
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
