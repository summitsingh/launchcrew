import type { components } from './schema';
import { PRODUCT_FACT_SOURCES, type OwnerFactState, type ProductFactSource } from './product-facts';

export type DriveStatusOut = components['schemas']['DriveStatusOut'];
export type DrivePublicConfigOut = components['schemas']['DrivePublicConfigOut'];
export type DriveImportIn = components['schemas']['DriveImportIn'];
export type DriveImportOut = components['schemas']['DriveImportOut'];
export type DriveSuggestionItem = components['schemas']['DriveSuggestionItem'];

export const DRIVE_SCOPE = 'https://www.googleapis.com/auth/drive.file';
export const DRIVE_DOC_MIME = 'application/vnd.google-apps.document';
export const DRIVE_TEXT_MIME = 'text/plain';
export const DRIVE_SUPPORTED_MIME_TYPES: readonly string[] = [DRIVE_DOC_MIME, DRIVE_TEXT_MIME] as const;
export const DRIVE_MAX_BYTES = 200000;
export const DRIVE_MAX_REQUESTS = 3;
export const DRIVE_GIS_SCRIPT = 'https://accounts.google.com/gsi/client';
export const DRIVE_PICKER_SCRIPT = 'https://apis.google.com/js/api.js';

export const DRIVE_SOURCE_LABEL = 'Drive file';
export const DRIVE_SELECTION_CONTEXT = 'Drive file selection';

const FILE_ID_PATTERN = /^[A-Za-z0-9_-]{1,256}$/;

export function driveMimeLabel(mime: string): string {
  if (mime === DRIVE_DOC_MIME) return 'Google Doc';
  if (mime === DRIVE_TEXT_MIME) return 'Plain text';
  return mime;
}

export function isSupportedDriveMime(mime: string): boolean {
  return mime === DRIVE_DOC_MIME || mime === DRIVE_TEXT_MIME;
}

export function validateDriveFileId(fileId: string): string[] {
  if (!FILE_ID_PATTERN.test(fileId)) return ['Drive selection is invalid. Pick the file again with Picker.'];
  if (fileId.includes('://') || fileId.includes('/') || fileId.includes('?') || fileId.includes('#')) {
    return ['Drive selection is invalid. Pick the file again with Picker.'];
  }
  return [];
}

export function validateDriveResourceKey(resourceKey: string | null | undefined): string[] {
  if (resourceKey === null || resourceKey === undefined || resourceKey === '') return [];
  if (!FILE_ID_PATTERN.test(resourceKey)) return ['Drive selection is invalid. Pick the file again with Picker.'];
  return [];
}

function coerceDriveSource(value: unknown): ProductFactSource {
  if (value === 'drive_file' && (PRODUCT_FACT_SOURCES as readonly string[]).includes('drive_file')) {
    return 'drive_file' as ProductFactSource;
  }
  return 'drive_file' as ProductFactSource;
}

/** Convert one Drive suggestion to an unconfirmed owner fact.
 * Always returns confirmed false with drive_file provenance. Edited text
 * wins over parsed text. Never truncates silently.
 */
export function toOwnerFactFromDriveSuggestion(
  suggestion: Pick<DriveSuggestionItem, 'text' | 'product_fact_source'>,
  editedText?: string,
): OwnerFactState {
  const raw = typeof editedText === 'string' ? editedText : suggestion.text;
  return {
    value: raw,
    confirmed: false,
    source: coerceDriveSource(suggestion.product_fact_source),
  };
}

export function toOwnerFactsFromDriveSuggestions(
  suggestions: Pick<DriveSuggestionItem, 'text' | 'product_fact_source' | 'index'>[],
  edited: Record<number, string> = {},
): OwnerFactState[] {
  return suggestions.map(item =>
    toOwnerFactFromDriveSuggestion(item, edited[item.index]),
  );
}

export function driveStatusMessage(status: DriveStatusOut | null | undefined): string {
  if (!status) return 'Drive intake status is loading.';
  if (status.available && status.configured) return 'Drive intake is available for a file you select.';
  if (status.reason === 'drive_not_configured') {
    return 'Drive intake is not configured. Pasted-text import still works.';
  }
  if (status.reason === 'auth_required') {
    return 'Drive intake requires Google sign-in. Pasted-text import still works.';
  }
  return 'Drive intake is unavailable. Pasted-text import still works.';
}

export function driveErrorMessage(statusCode: number): string {
  if (statusCode === 401) return 'Sign in is required for Drive intake.';
  if (statusCode === 403) return 'Drive consent is missing or the file was not selected. Reconnect with Picker and pick the file again.';
  if (statusCode === 413) return 'The selected Drive file is too large for the bounded demo import.';
  if (statusCode === 422) return 'The selected Drive file type is not supported. Use a Google Doc or a plain text file.';
  if (statusCode === 503) return 'Drive intake is not configured. Pasted-text import still works.';
  return 'Drive intake failed. Pasted-text import still works.';
}
