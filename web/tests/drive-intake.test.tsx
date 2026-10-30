import { describe, it, expect } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { DriveIntakeForm, DrivePhotoIntakeForm, DrivePhotoProposalView, DriveSuggestionsList } from '../src/components/drive-intake-form';
import {
  DRIVE_AUTHORIZE_URL,
  DRIVE_MAX_BYTES,
  DRIVE_MAX_PHOTO_BYTES,
  DRIVE_MAX_PHOTO_PIXELS,
  DRIVE_MAX_REQUESTS,
  DRIVE_PHOTO_PARSER_VERSION,
  DRIVE_PHOTO_SUGGESTIONS_URL,
  DRIVE_PICKER_PHOTO_MIME_FILTER,
  DRIVE_PICKER_TOKEN_URL,
  DRIVE_SCOPE,
  DRIVE_SUPPORTED_MIME_TYPES,
  DRIVE_SUPPORTED_PHOTO_MIME_TYPES,
  driveAuthStatusFromSearch,
  driveErrorMessage,
  driveMimeLabel,
  drivePhotoErrorMessage,
  drivePhotoMimeLabel,
  driveStatusMessage,
  isSupportedDriveMime,
  isSupportedDrivePhotoMime,
  toOwnerFactFromDriveSuggestion,
  toOwnerFactsFromDriveSuggestions,
  toUnconfirmedDrivePhotoClaim,
  validateDriveFileId,
  validateDrivePhotoApproval,
  validateDriveResourceKey,
  type DriveImportOut,
  type DrivePhotoProposalOut,
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

  it('uses server auth-code endpoints without browser token client', () => {
    expect(DRIVE_AUTHORIZE_URL).toBe('/api/drive-import/authorize');
    expect(DRIVE_PICKER_TOKEN_URL).toBe('/api/drive-import/picker-token');
    expect(driveAuthStatusFromSearch('?drive=authorized')).toBe('authorized');
    expect(driveAuthStatusFromSearch('?drive=denied')).toBe(null);
    expect(driveAuthStatusFromSearch('')).toBe(null);
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
  it('renders server-consent Picker intake without verified claims or live proof', () => {
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
      'Connect Drive and choose file',
      'separate step',
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

describe('drive photo intake foundation', () => {
  function photoProposal(): DrivePhotoProposalOut {
    return {
      status: 'unconfirmed',
      source: 'drive_file',
      product_fact_source: 'drive_file',
      file_title: 'Campsite photo',
      mime_type: 'image/png',
      selection_context: 'Drive file selection',
      width: 24,
      height: 12,
      byte_size: 1234,
      sha256: 'a'.repeat(64),
      confirmed: false,
      requires_approval: true,
      parser_version: DRIVE_PHOTO_PARSER_VERSION,
    };
  }

  it('advertises photo bounds with original-pixels-only policy', () => {
    expect([...DRIVE_SUPPORTED_PHOTO_MIME_TYPES]).toEqual(['image/jpeg', 'image/png']);
    expect(DRIVE_MAX_PHOTO_BYTES).toBe(1048576);
    expect(DRIVE_MAX_PHOTO_PIXELS).toBe(8000000);
    expect(DRIVE_PICKER_PHOTO_MIME_FILTER).toBe('image/jpeg,image/png');
    expect(DRIVE_PHOTO_SUGGESTIONS_URL).toBe('/api/drive-import/photo-suggestions');
    expect(isSupportedDrivePhotoMime('image/jpeg')).toBe(true);
    expect(isSupportedDrivePhotoMime('image/png')).toBe(true);
    expect(isSupportedDrivePhotoMime('image/gif')).toBe(false);
    expect(isSupportedDrivePhotoMime('video/mp4')).toBe(false);
    expect(isSupportedDrivePhotoMime('application/pdf')).toBe(false);
    expect(isSupportedDriveMime('image/png')).toBe(false);
    expect(drivePhotoMimeLabel('image/jpeg')).toBe('JPEG photo');
    expect(drivePhotoMimeLabel('image/png')).toBe('PNG photo');
    expect(drivePhotoErrorMessage(413)).toContain('1 MiB');
    expect(drivePhotoErrorMessage(422)).toContain('JPEG or PNG');
  });

  it('requires explicit approval and never confirms a photo claim', () => {
    const proposal = photoProposal();
    expect(validateDrivePhotoApproval(false)).not.toEqual([]);
    expect(validateDrivePhotoApproval(true)).toEqual([]);
    expect(toUnconfirmedDrivePhotoClaim(proposal, false)).toBe(null);
    const claim = toUnconfirmedDrivePhotoClaim(proposal, true);
    expect(claim).toEqual({
      fileTitle: 'Campsite photo',
      mimeType: 'image/png',
      width: 24,
      height: 12,
      sha256: 'a'.repeat(64),
      approved: true,
      confirmed: false,
      source: 'drive_file',
    });
    expect(toUnconfirmedDrivePhotoClaim({ ...proposal, sha256: 'short' }, true)).toBe(null);
    expect(toUnconfirmedDrivePhotoClaim({ ...proposal, mime_type: 'image/gif' }, true)).toBe(null);
  });

  it('renders the photo form with approval gate and no pixel bytes', () => {
    const html = renderToStaticMarkup(
      <QueryClientProvider client={new QueryClient()}>
        <DrivePhotoIntakeForm onAddPhoto={() => {}} />
      </QueryClientProvider>,
    );
    for (const text of [
      'Select a Drive photo',
      'JPEG or PNG photo you select',
      'stay unconfirmed',
      'explicit approval before any photo check',
      'Original pixels only',
      'Live Drive proof has not been run',
      'Connect Drive and choose photo',
    ]) {
      expect(html).toContain(text);
    }
    expect(html).not.toContain('data:image');
    expect(html).not.toContain('drive_token');
    expect(html).not.toContain('file_id');
  });

  it('renders a photo proposal with title, dimensions, and approval checkbox', () => {
    const html = renderToStaticMarkup(
      <DrivePhotoProposalView proposal={photoProposal()} approved={false} onToggleApproval={() => {}} onAdd={() => {}} />,
    );
    for (const text of [
      'Drive photo selection produced one unconfirmed proposal',
      'File: Campsite photo (PNG photo)',
      'Status: unconfirmed',
      'Parser: drive-photo/v1',
      'Dimensions: 24 by 12',
      'Confirmed: no',
      'Photo use needs approval',
      'Add photo as unconfirmed claim',
    ]) {
      expect(html).toContain(text);
    }
    expect(html).toContain('Unconfirmed');
    expect(html).not.toContain('Verified');
    expect(html).not.toContain('data:image');
    expect(html).not.toContain('demo-photo');
  });
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
