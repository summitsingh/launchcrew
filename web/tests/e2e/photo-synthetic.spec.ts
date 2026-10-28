import { test, expect, type Page } from '@playwright/test';
import { readFileSync, writeFileSync } from 'node:fs';
import { deflateSync } from 'node:zlib';

// SYNTHETIC UI PROOF ONLY. Every photo-check response in this file is a
// page.route mock fulfilled from a synthetic detected payload: no SAM key, no
// provider HTTP, no live segmentation, no personal photos. This file never
// claims live SAM behavior. The real keyless API flow lives in
// human-review.spec.ts and stays route-interception free.

// Hand-authored synthetic static PNG bytes, same helper shape as the real
// keyless flow. Never a personal photo.
function crc32Bytes(value: Buffer): number {
  let table = (crc32Bytes as unknown as { table?: number[] }).table;
  if (!table) {
    table = [];
    for (let n = 0; n < 256; n += 1) {
      let c = n;
      for (let k = 0; k < 8; k += 1) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
      table[n] = c >>> 0;
    }
    (crc32Bytes as unknown as { table: number[] }).table = table;
  }
  let crc = 0xffffffff;
  for (const byte of value) crc = table[(crc ^ byte) & 0xff] ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
}

function pngChunk(kind: string, payload: Buffer): Buffer {
  const length = Buffer.alloc(4);
  length.writeUInt32BE(payload.length);
  const type = Buffer.from(kind, 'ascii');
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32Bytes(Buffer.concat([type, payload])));
  return Buffer.concat([length, type, payload, crc]);
}

function syntheticPng(width: number, height: number): Buffer {
  const header = Buffer.alloc(13);
  header.writeUInt32BE(width, 0);
  header.writeUInt32BE(height, 4);
  header[8] = 8;
  header[9] = 2;
  const row = Buffer.concat([Buffer.from([0]), Buffer.alloc(width * 3, 140)]);
  const rows = Buffer.concat(Array.from({ length: height }, () => row));
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    pngChunk('IHDR', header),
    pngChunk('IDAT', deflateSync(rows)),
    pngChunk('IEND', Buffer.alloc(0)),
  ]);
}
// Synthetic detected payload shaped like the real PhotoCheckResponse. The
// receipt is the test's own real receipt with a mocked detected photo_status;
// the preview/frame/crop are synthetic and match the selected fixture bytes.
function syntheticDetected(baseReceipt: Record<string, unknown>, sentRevision: number) {
  const nextRevision = sentRevision + 1;
  return {
    check: {
      method: 'sam-3.1',
      label: 'detected',
      reason: 'synthetic UI proof only, never live SAM',
      policy_version: 'photo-geometry/v1',
      revision: nextRevision,
      photo_state: 'checked',
    },
    receipt: {
      ...baseReceipt,
      revision: nextRevision,
      photo_status: {
        state: 'checked',
        label: 'detected',
        reason: 'synthetic UI proof only, never live SAM',
        policy_version: 'photo-geometry/v1',
        revision: nextRevision,
        actor: 'synthetic-proof',
        checked_at: '2026-01-01T00:00:00Z',
      },
    },
    preview: {
      frame_w: 1600,
      frame_h: 1067,
      crop: { x1: 100, y1: 100, x2: 899, y2: 599 },
      label: 'detected',
    },
  };
}

async function createCleanRun(page: Page) {
  await page.goto('/');
  await page.getByLabel('Maker profile', { exact: true }).selectOption('Maker');
  await page.getByLabel('Include the unsupported claim demo').uncheck();
  await page.getByRole('button', { name: 'Create draft', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Ready for your review.' })).toBeVisible();
  const runId = await page.locator('.section-row .run-id').innerText();
  expect(runId.startsWith('run_')).toBe(true);
  return runId;
}

test('synthetic UI proof (mocked photo-check, never live SAM): detected check draws the crop canvas and unlocks download', async ({
  page,
  request,
}) => {
  test.setTimeout(180_000);
  await page.setViewportSize({ width: 375, height: 1000 });
  const runId = await createCleanRun(page);

  // Actual decoded 1600 by 1067 synthetic bytes: the mocked frame matches, so
  // the draw path runs against real decoded pixels, never fake pixels.
  const fixture = `/tmp/launchcrew-synthetic-proof-${Date.now()}.png`;
  writeFileSync(fixture, syntheticPng(1600, 1067));
  await page.getByLabel(/Select photo \(PNG or JPEG/).setInputFiles(fixture);
  const checkButton = page.getByRole('button', { name: 'Check photo', exact: true });
  await expect(checkButton).toBeEnabled();

  const baseReceipt = (await (await request.get(`/api/runs/${runId}/receipt`)).json()) as Record<string, unknown>;
  await page.route('**/api/runs/*/photo-check', async route => {
    const body = route.request().postDataJSON() as { expected_revision: number };
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(syntheticDetected(baseReceipt, body.expected_revision)),
    });
  });
  await checkButton.click();

  // The canvas mounts with the offer and becomes visible only after the real
  // draw completes: on unfixed code it never mounts and this times out.
  const canvas = page.getByTestId('photo-crop-canvas');
  await expect(canvas).toBeVisible();
  const dims = await canvas.evaluate(el => ({ w: (el as HTMLCanvasElement).width, h: (el as HTMLCanvasElement).height }));
  // Crop buffer keeps the exact synthetic server crop: 899-100+1 by 599-100+1.
  expect(dims).toEqual({ w: 800, h: 500 });
  // CSS display resize only: the drawn buffer stays 800 by 500 while the
  // displayed box fits the 375px viewport with no page overflow.
  expect(await canvas.evaluate(el => el.getBoundingClientRect().width)).toBeLessThanOrEqual(375);
  await expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);

  // Download unlocks only after the draw: the button is disabled until then.
  const downloadButton = page.getByRole('button', { name: 'Download crop', exact: true });
  await expect(downloadButton).toBeEnabled();
  const downloadEvent = page.waitForEvent('download');
  await downloadButton.click();
  const download = await downloadEvent;
  const target = `/tmp/launchcrew-synthetic-crop-${Date.now()}.png`;
  await download.saveAs(target);
  expect(readFileSync(target).length).toBeGreaterThan(0);
  await page.screenshot({ path: '../.local/synthetic-canvas-375-proof.png' });
});

test('synthetic UI proof (mocked photo-check, never live SAM): deferred response after a revision change applies nothing stale', async ({
  page,
  request,
}) => {
  test.setTimeout(180_000);
  await page.setViewportSize({ width: 375, height: 1000 });
  const runId = await createCleanRun(page);

  const fixture = `/tmp/launchcrew-synthetic-stale-${Date.now()}.png`;
  writeFileSync(fixture, syntheticPng(1600, 1067));
  await page.getByLabel(/Select photo \(PNG or JPEG/).setInputFiles(fixture);
  const checkButton = page.getByRole('button', { name: 'Check photo', exact: true });
  await expect(checkButton).toBeEnabled();

  const baseReceipt = (await (await request.get(`/api/runs/${runId}/receipt`)).json()) as Record<string, unknown>;
  let release!: () => void;
  const gate = new Promise<void>(resolve => {
    release = resolve;
  });
  await page.route('**/api/runs/*/photo-check', async route => {
    const body = route.request().postDataJSON() as { expected_revision: number };
    await gate;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(syntheticDetected(baseReceipt, body.expected_revision)),
    });
  });
  await checkButton.click();
  await expect(page.getByText('Check in flight. Duplicate checks are disabled until it settles.')).toBeVisible();

  // External revision change while the check is deferred: a real human
  // revision save bumps the run to revision 1 and must invalidate the old
  // request generation.
  const validPost = 'Vegan leather wallet. Designed in Texas.';
  const validEmail = 'For Austin commuters. $49.';
  await page.getByLabel('Post text').fill(validPost);
  await page.getByLabel('Email text').fill(validEmail);
  await page.getByRole('button', { name: 'Save human revision', exact: true }).click();
  await expect(page.getByText(/Saved revision 1\. This pack needs fresh approval before export\./)).toBeVisible();

  const responsePromise = page.waitForResponse('**/api/runs/*/photo-check');
  release();
  await responsePromise;
  await page.waitForTimeout(500);

  // The stale generation must apply nothing: no detected notice, no canvas,
  // and the server receipt still shows the text-only revision 1 path.
  await expect(page.getByText('Photo check detected one in-frame candidate')).toHaveCount(0);
  await expect(page.getByTestId('photo-crop-canvas')).toHaveCount(0);
  const reread = (await (await request.get(`/api/runs/${runId}/receipt`)).json()) as {
    revision: number;
    photo_status: { state: string } | null;
  };
  expect(reread.revision).toBe(1);
  // A legacy text-only receipt carries an absent photo status, which the UI
  // honestly reads as no_photo; accept that without fabricating a server photo.
  expect(reread.photo_status?.state ?? 'no_photo').toBe('no_photo');
});

test('synthetic UI proof (mocked photo-check, never live SAM): deferred response after unmount applies nothing stale', async ({
  page,
  request,
}) => {
  test.setTimeout(180_000);
  await page.setViewportSize({ width: 375, height: 1000 });
  const runId = await createCleanRun(page);

  const fixture = `/tmp/launchcrew-synthetic-unmount-${Date.now()}.png`;
  writeFileSync(fixture, syntheticPng(1600, 1067));
  await page.getByLabel(/Select photo \(PNG or JPEG/).setInputFiles(fixture);
  const checkButton = page.getByRole('button', { name: 'Check photo', exact: true });
  await expect(checkButton).toBeEnabled();

  const baseReceipt = (await (await request.get(`/api/runs/${runId}/receipt`)).json()) as Record<string, unknown>;
  let release!: () => void;
  const gate = new Promise<void>(resolve => {
    release = resolve;
  });
  await page.route('**/api/runs/*/photo-check', async route => {
    const body = route.request().postDataJSON() as { expected_revision: number };
    await gate;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(syntheticDetected(baseReceipt, body.expected_revision)),
    });
  });
  await checkButton.click();
  await expect(page.getByText('Check in flight. Duplicate checks are disabled until it settles.')).toBeVisible();

  // Navigate away while the check is deferred: unmount must invalidate the
  // old request generation so the late reply cannot apply an old receipt.
  await page.getByRole('navigation', { name: 'Workspace' }).getByRole('button', { name: 'Approval queue' }).click();
  await expect(page.getByRole('heading', { name: /Review queue/ })).toBeVisible();
  const responsePromise = page.waitForResponse('**/api/runs/*/photo-check');
  release();
  await responsePromise;
  await page.waitForTimeout(500);

  // Return to the run: no resurrected detected copy and no canvas, while the
  // server receipt is untouched on the text-only path.
  await page.locator(`[data-run-id="${runId}"]`).getByRole('button', { name: 'Review draft', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Ready for your review.' })).toBeVisible();
  await expect(page.getByText('Photo check passed on this revision')).toHaveCount(0);
  await expect(page.getByText('Photo check detected one in-frame candidate')).toHaveCount(0);
  await expect(page.getByTestId('photo-crop-canvas')).toHaveCount(0);
  const reread = (await (await request.get(`/api/runs/${runId}/receipt`)).json()) as {
    photo_status: { state: string } | null;
  };
  // A legacy text-only receipt carries an absent photo status, which the UI
  // honestly reads as no_photo; accept that without fabricating a server photo.
  expect(reread.photo_status?.state ?? 'no_photo').toBe('no_photo');
});

// SYNTHETIC UI TRANSPORT ONLY, never live SAM. The GET receipt override below
// simulates the paid admission the real server commits (revision N+1 with
// check_requested) while the photo-check POST is still deferred. Direct
// page.request calls in this file bypass page.route and still hit the real
// server, so simulated state is asserted through the UI only.
function simulatedAdmission(baseReceipt: Record<string, unknown>) {
  const sentRevision = (baseReceipt.revision as number) ?? 0;
  const admittedRevision = sentRevision + 1;
  return {
    ...baseReceipt,
    revision: admittedRevision,
    photo_status: {
      state: 'check_requested',
      label: null,
      reason: 'check_requested: segmentation in flight (synthetic UI transport only, never live SAM)',
      policy_version: 'photo-geometry/v1',
      revision: admittedRevision,
      actor: 'synthetic-proof',
      checked_at: '',
    },
  };
}

test('synthetic UI proof (mocked photo-check, never live SAM): own admission observed mid-flight still applies and draws', async ({
  page,
  request,
}) => {
  test.setTimeout(180_000);
  await page.setViewportSize({ width: 375, height: 1000 });
  const runId = await createCleanRun(page);

  const fixture = `/tmp/launchcrew-synthetic-admit-${Date.now()}.png`;
  writeFileSync(fixture, syntheticPng(1600, 1067));
  await page.getByLabel(/Select photo \(PNG or JPEG/).setInputFiles(fixture);
  const checkButton = page.getByRole('button', { name: 'Check photo', exact: true });
  await expect(checkButton).toBeEnabled();

  const baseReceipt = (await (await request.get(`/api/runs/${runId}/receipt`)).json()) as Record<string, unknown>;
  const admittedReceipt = simulatedAdmission(baseReceipt);
  let receiptPhase: 'pre' | 'admitted' = 'pre';
  await page.route('**/api/runs/*/receipt', async route => {
    if (receiptPhase === 'pre') {
      await route.continue();
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(admittedReceipt),
    });
  });
  let release!: () => void;
  const gate = new Promise<void>(resolve => {
    release = resolve;
  });
  await page.route('**/api/runs/*/photo-check', async route => {
    const body = route.request().postDataJSON() as { expected_revision: number };
    await gate;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(syntheticDetected(baseReceipt, body.expected_revision)),
    });
  });
  await checkButton.click();
  // From here the simulated UI transport reports the paid admission N+1 with
  // check_requested while the check POST stays deferred, mirroring the real
  // server commit that lands before a slow transport finishes.
  receiptPhase = 'admitted';

  // The UI must observe its own admission without invalidating the pending
  // check: the admitted summary renders at the admitted revision.
  await expect(page.getByText('Photo check in flight')).toBeVisible({ timeout: 15000 });
  await expect(page.getByText('Stored at revision 1.')).toBeVisible({ timeout: 15000 });

  const responsePromise = page.waitForResponse('**/api/runs/*/photo-check');
  release();
  await responsePromise;

  // The valid final detected response applies and draws with original pixels.
  const canvas = page.getByTestId('photo-crop-canvas');
  await expect(canvas).toBeVisible({ timeout: 15000 });
  const dims = await canvas.evaluate(el => ({ w: (el as HTMLCanvasElement).width, h: (el as HTMLCanvasElement).height }));
  expect(dims).toEqual({ w: 800, h: 500 });
  expect(await canvas.evaluate(el => el.getBoundingClientRect().width)).toBeLessThanOrEqual(375);
  await expect(page.getByText('Photo check detected one in-frame candidate')).toBeVisible();
  const downloadButton = page.getByRole('button', { name: 'Download crop', exact: true });
  await expect(downloadButton).toBeEnabled();
  const downloadEvent = page.waitForEvent('download');
  await downloadButton.click();
  const download = await downloadEvent;
  const target = `/tmp/launchcrew-synthetic-admit-crop-${Date.now()}.png`;
  await download.saveAs(target);
  expect(readFileSync(target).length).toBeGreaterThan(0);
});

test('synthetic UI proof (mocked photo-check, never live SAM): superseding N+2 after own admission drops the stale result', async ({
  page,
  request,
}) => {
  test.setTimeout(180_000);
  await page.setViewportSize({ width: 375, height: 1000 });
  const runId = await createCleanRun(page);

  const fixture = `/tmp/launchcrew-synthetic-supersede-${Date.now()}.png`;
  writeFileSync(fixture, syntheticPng(1600, 1067));
  await page.getByLabel(/Select photo \(PNG or JPEG/).setInputFiles(fixture);
  const checkButton = page.getByRole('button', { name: 'Check photo', exact: true });
  await expect(checkButton).toBeEnabled();

  const baseReceipt = (await (await request.get(`/api/runs/${runId}/receipt`)).json()) as Record<string, unknown>;
  const admittedReceipt = simulatedAdmission(baseReceipt);
  // A later text edit bumps the pack to N+2 while the photo summary stays at
  // the admission revision, exactly as the real server leaves it. This is a
  // proper separate synthetic state, never a live edit.
  const supersededReceipt = { ...admittedReceipt, revision: 2 };
  let receiptPhase: 'pre' | 'admitted' | 'superseded' = 'pre';
  await page.route('**/api/runs/*/receipt', async route => {
    if (receiptPhase === 'pre') {
      await route.continue();
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(receiptPhase === 'admitted' ? admittedReceipt : supersededReceipt),
    });
  });
  let release!: () => void;
  const gate = new Promise<void>(resolve => {
    release = resolve;
  });
  await page.route('**/api/runs/*/photo-check', async route => {
    const body = route.request().postDataJSON() as { expected_revision: number };
    await gate;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(syntheticDetected(baseReceipt, body.expected_revision)),
    });
  });
  await checkButton.click();
  receiptPhase = 'admitted';
  await expect(page.getByText('Stored at revision 1.')).toBeVisible({ timeout: 15000 });

  // The pack moves to N+2 after the admission was observed: the UI must treat
  // this as truly superseding, invalidate the pending check, and never
  // restore the old admission or image once the stale reply lands.
  receiptPhase = 'superseded';
  await expect(page.getByText(`Bound to run ${runId}, revision 2`)).toBeVisible({ timeout: 15000 });
  await expect(page.getByText('superseded')).toBeVisible({ timeout: 15000 });

  const responsePromise = page.waitForResponse('**/api/runs/*/photo-check');
  release();
  await responsePromise;
  await page.waitForTimeout(500);

  await expect(page.getByText('Photo check detected one in-frame candidate')).toHaveCount(0);
  await expect(page.getByTestId('photo-crop-canvas')).toHaveCount(0);
  // The UI stays on the superseding revision: no old receipt is restored.
  await expect(page.getByText(`Bound to run ${runId}, revision 2`)).toBeVisible();
});

test('synthetic UI proof (mocked photo-check, never live SAM): checked selection reads checked, a new file stays unchecked with the old crop gone', async ({
  page,
  request,
}) => {
  test.setTimeout(180_000);
  await page.setViewportSize({ width: 375, height: 1000 });
  const runId = await createCleanRun(page);

  // File A starts unchecked with an honest local-only caption.
  const fixtureA = `/tmp/launchcrew-synthetic-checked-a-${Date.now()}.png`;
  writeFileSync(fixtureA, syntheticPng(1600, 1067));
  await page.getByLabel(/Select photo \(PNG or JPEG/).setInputFiles(fixtureA);
  await expect(page.getByText(/Unchecked:/)).toBeVisible();
  await expect(page.getByAltText('Selected photo preview (local only, not yet checked)')).toBeVisible();

  // The mocked detected response applies to file A only: no live SAM.
  const baseReceipt = (await (await request.get(`/api/runs/${runId}/receipt`)).json()) as Record<string, unknown>;
  let checkCalls = 0;
  await page.route('**/api/runs/*/photo-check', async route => {
    checkCalls += 1;
    const body = route.request().postDataJSON() as { expected_revision: number };
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(syntheticDetected(baseReceipt, body.expected_revision)),
    });
  });
  await page.getByRole('button', { name: 'Check photo', exact: true }).click();

  // The checked selection draws the real crop and reads checked for the
  // current pixels with fresh approval still required: never not-sent.
  const canvas = page.getByTestId('photo-crop-canvas');
  await expect(canvas).toBeVisible();
  await expect(page.getByText('Checked: these current pixels passed the size and edge gates on this revision.')).toBeVisible();
  await expect(page.getByAltText('Selected photo preview (checked on this revision, detected)')).toBeVisible();
  await expect(page.getByText('These local pixels were not sent')).toHaveCount(0);
  expect(checkCalls).toBe(1);

  // Selecting a different file B is a new generation: it stays unchecked
  // with no inherited verdict, the old crop is gone, and nothing is sent
  // automatically.
  const fixtureB = `/tmp/launchcrew-synthetic-checked-b-${Date.now()}.png`;
  writeFileSync(fixtureB, syntheticPng(800, 600));
  await page.getByLabel(/Select photo \(PNG or JPEG/).setInputFiles(fixtureB);
  await expect(page.getByText(/New selection, not yet checked:/)).toBeVisible();
  await expect(
    page.getByAltText('Selected photo preview (new local pixels, not yet checked; current revision has a detected check)'),
  ).toBeVisible();
  await expect(page.getByTestId('photo-crop-canvas')).toHaveCount(0);
  await expect(page.getByText('Checked: these current pixels passed')).toHaveCount(0);
  await page.waitForTimeout(1500);
  expect(checkCalls).toBe(1);
  // The mock never reached the real server, so the stored server receipt
  // is untouched on the text-only path: no phantom server check exists.
  const reread = (await (await request.get(`/api/runs/${runId}/receipt`)).json()) as {
    revision: number;
    photo_status: { state: string } | null;
  };
  expect(reread.revision).toBe(0);
  expect(reread.photo_status?.state ?? 'no_photo').toBe('no_photo');
});
