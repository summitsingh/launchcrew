import { describe, it, expect } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { DriveIntakeForm, DriveSuggestionsList } from '../src/components/drive-intake-form';
import {
  DRIVE_MAX_BYTES,
  DRIVE_MAX_REQUESTS,
  DRIVE_SCOPE,
  DRIVE_SUPPORTED_MIME_TYPES,
  driveErrorMessage,
  driveMimeLabel,
  driveStatusMessage,
  isSupportedDriveMime,
  toOwnerFactFromDriveSuggestion,
  toOwnerFactsFromDriveSuggestions,
  validateDriveFileId,
  validateDriveResourceKey,
  type DriveImportOut,
  type DriveStatusOut,
} from '../src/lib/drive-intake';
import {
  buildProductFactsInput,
  emptyOwnerFacts,
  validateOwnerFacts,
} from '../src/lib/product-facts';

function driveResult(): DriveImportOut {
  return {
    status: 'unconfirmed',
    source: 'drive_file',
    product_fact_source: 'drive_file',
    file_title: 'Demo tote notes',
    mime_type: 'text/plain',
    selection_context: 'Drive file selection',
    suggestions: [
      { text: 'Canvas tote', source: 'drive_file', product_fact_source: 'drive_file', status: 'unconfirmed', confirmed: false, index: 0 },
      { text: 'Large', source: 'drive_file', product_fact_source: 'drive_file', status: 'unconfirmed', confirmed: false, index: 1 },
    ],
    truncated: false,
    dropped_duplicates: 0,
    dropped_overlong: 0,
    dropped_empty: 0,
    parser_version: 'drive-import/v1',
  } as DriveImportOut;
}

function driveStatus(overrides: Partial<DriveStatusOut> = {}): DriveStatusOut {
  return {
    available: true,
    configured: true,
    live_verified: false,
    max_bytes: DRIVE_MAX_BYTES,
    max_requests: DRIVE_MAX_REQUESTS,
    reason: 'ok',
    scope: DRIVE_SCOPE,
    supported_mime_types: [...DRIVE_SUPPORTED_MIME_TYPES],
    ...overrides,
  } as DriveStatusOut;
}

describe('drive intake bounds and scope', () => {
  it('uses drive.file scope with Docs and plain text only, no photos', () => {
    expect(DRIVE_SCOPE).toBe('https://www.googleapis.com/auth/drive.file');
    expect([...DRIVE_SUPPORTED_MIME_TYPES]).toEqual([
      'application/vnd.google-apps.document',
      'text/plain',
    ]);
    expect(DRIVE_MAX_BYTES).toBe(200000);
    expect(DRIVE_MAX_REQUESTS).toBe(3);
    expect(isSupportedDriveMime('application/vnd.google-apps.document')).toBe(true);
    expect(isSupportedDriveMime('text/plain')).toBe(true);
    expect(isSupportedDriveMime('image/jpeg')).toBe(false);
    expect(isSupportedDriveMime('application/pdf')).toBe(false);
    expect(isSupportedDriveMime('video/mp4')).toBe(false);
    expect(driveMimeLabel('application/vnd.google-apps.document')).toBe('Google Doc');
    expect(driveMimeLabel('text/plain')).toBe('Plain text');
  });

  it('validates selected IDs and rejects URLs without provider calls', () => {
    expect(validateDriveFileId('demo-file-01')).toEqual([]);
    expect(validateDriveFileId('ABC_abc-123')).toEqual([]);
    for (const bad of [
      'https://www.googleapis.com/drive/v3/files/demo-file-01',
      'https://evil.invalid/file',
      'demo-file-01?alt=media',
      'demo/file/01',
      'demo-file-01#frag',
      '',
      'x'.repeat(257),
      'bad id!',
    ]) {
      expect(validateDriveFileId(bad).length).toBeGreaterThan(0);
    }
    expect(validateDriveResourceKey(null)).toEqual([]);
    expect(validateDriveResourceKey(undefined)).toEqual([]);
    expect(validateDriveResourceKey('')).toEqual([]);
    expect(validateDriveResourceKey('key-01')).toEqual([]);
    expect(validateDriveResourceKey('https://evil.invalid/key').length).toBeGreaterThan(0);
  });

  it('reports unavailable and error states without secrets', () => {
    expect(driveStatusMessage(driveStatus())).toContain('available for a file you select');
    expect(driveStatusMessage(driveStatus({ available: false, configured: false, reason: 'drive_not_configured' }))).toContain(
      'not configured',
    );
    expect(driveStatusMessage(driveStatus({ available: false, configured: true, reason: 'auth_required' }))).toContain(
      'Google sign-in',
    );
    expect(driveStatusMessage(null)).toContain('loading');
    expect(driveErrorMessage(401)).toContain('Sign in');
    expect(driveErrorMessage(403)).toContain('consent');
    expect(driveErrorMessage(413)).toContain('too large');
    expect(driveErrorMessage(422)).toContain('not supported');
    expect(driveErrorMessage(503)).toContain('not configured');
    expect(driveErrorMessage(502)).toContain('failed');
  });
});

describe('drive suggestion conversion', () => {
  it('always starts unconfirmed with drive_file provenance and never truncates', () => {
    const single = toOwnerFactFromDriveSuggestion({
      text: 'Canvas tote',
      product_fact_source: 'drive_file',
    });
    expect(single).toEqual({ value: 'Canvas tote', confirmed: false, source: 'drive_file' });
    const edited = toOwnerFactFromDriveSuggestion(
      { text: 'Large', product_fact_source: 'drive_file' },
      '  Extra large tote  ',
    );
    expect(edited).toEqual({ value: '  Extra large tote  ', confirmed: false, source: 'drive_file' });
    const long = 'y'.repeat(250);
    const kept = toOwnerFactFromDriveSuggestion({ text: long, product_fact_source: 'drive_file' });
    expect(kept.value).toBe(long);
    expect(kept.confirmed).toBe(false);
  });

  it('converts a result list with per-item edits intact', () => {
    const result = driveResult();
    const facts = toOwnerFactsFromDriveSuggestions(result.suggestions, { 1: 'Extra large' });
    expect(facts).toEqual([
      { value: 'Canvas tote', confirmed: false, source: 'drive_file' },
      { value: 'Extra large', confirmed: false, source: 'drive_file' },
    ]);
  });
});

describe('drive intake UI flow', () => {
  it('renders optional Picker intake without verified claims or live proof', () => {
    const html = renderToStaticMarkup(
      <QueryClientProvider client={new QueryClient()}>
        <DriveIntakeForm onAdd={() => {}} />
      </QueryClientProvider>,
    );
    for (const text of [
      'Select a Drive file',
      'Optional Google Picker intake',
      'Google Doc or plain text file',
      'stay unconfirmed suggestions',
      'Drive file provenance',
      'explicitly confirm each',
      'Live Drive proof has not been run',
      'Choose Drive file',
    ]) {
      expect(html).toContain(text);
    }
    expect(html).not.toContain('Verified');
    expect(html).not.toContain('Approved for export');
    expect(html).not.toContain('live_verified');
    expect(html).not.toContain('drive_token');
    expect(html).not.toContain('file_id');
  });

  it('shows editable Drive suggestions with title and selection context, no provider IDs', () => {
    const html = renderToStaticMarkup(
      <DriveSuggestionsList
        result={driveResult()}
        edited={{ 1: 'Extra large' }}
        onEdit={() => {}}
        onAddOne={() => {}}
        onAddAll={() => {}}
      />,
    );
    for (const text of [
      'Drive file selection produced 2 suggestions',
      'File: Demo tote notes (Plain text)',
      'Status: unconfirmed',
      'Parser: drive-import/v1',
      'Suggestion 1',
      'Suggestion 2',
      'Edit suggestion 1',
      'Edit suggestion 2',
      'Canvas tote',
      'Extra large',
      'Source: Drive file (Plain text)',
      'Selection: Drive file selection',
      'Product fact source: Drive file',
      'Confirmed: no',
      'Add as allowed claim',
      'Add all as allowed claims',
    ]) {
      expect(html).toContain(text);
    }
    expect(html).not.toContain('Verified');
    expect(html).toContain('Unconfirmed');
    expect(html).not.toContain('demo-file-01');
    expect(html).not.toContain('synthetic-drive-token');
    expect(html).not.toContain('resourceKey');
  });

  it('escapes Drive markup as plain text', () => {
    const hostile = driveResult();
    hostile.suggestions = [
      { text: '<script>alert(1)</script>', source: 'drive_file', product_fact_source: 'drive_file', status: 'unconfirmed', confirmed: false, index: 0 },
    ];
    hostile.file_title = '<img src=x onerror=alert(1)>';
    const html = renderToStaticMarkup(
      <DriveSuggestionsList result={hostile} edited={{}} onEdit={() => {}} onAddOne={() => {}} onAddAll={() => {}} />,
    );
    expect(html).toContain('&lt;script&gt;alert(1)&lt;/script&gt;');
    expect(html).not.toContain('<script>alert(1)</script>');
    expect(html).toContain('&lt;img');
    expect(html).not.toContain('<img src=x');
  });

  it('flows from Drive result through fact form to unconfirmed product facts', () => {
    const result = driveResult();
    const facts = toOwnerFactsFromDriveSuggestions(result.suggestions, { 1: 'Extra large' });
    const state = emptyOwnerFacts();
    state.material = { value: 'Canvas', confirmed: true, source: 'owner' };
    state.allowed_claims = facts;
    expect(validateOwnerFacts(state)).toEqual([]);
    const out = buildProductFactsInput(state);
    expect(out.material).toEqual({ value: 'Canvas', confirmed: true, source: 'owner' });
    expect(out.allowed_claims).toEqual([
      { value: 'Canvas tote', confirmed: false, source: 'drive_file' },
      { value: 'Extra large', confirmed: false, source: 'drive_file' },
    ]);
    const confirmedState = {
      ...state,
      allowed_claims: state.allowed_claims.map(fact => ({ ...fact, confirmed: true })),
    };
    const confirmedOut = buildProductFactsInput(confirmedState);
    expect(confirmedOut.allowed_claims?.every(fact => fact.confirmed)).toBe(true);
  });
});
