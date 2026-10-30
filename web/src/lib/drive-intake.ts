import type { components } from './schema';
import { PRODUCT_FACT_SOURCES, type OwnerFactState, type ProductFactSource } from './product-facts';

export type DriveStatusOut = components['schemas']['DriveStatusOut'];
export type DrivePublicConfigOut = components['schemas']['DrivePublicConfigOut'];
export type DriveImportIn = components['schemas']['DriveImportIn'];
export type DriveImportOut = components['schemas']['DriveImportOut'];
export type DriveSuggestionItem = components['schemas']['DriveSuggestionItem'];
export type DrivePickerTokenOut = components['schemas']['DrivePickerTokenOut'];

export const DRIVE_SCOPE = 'https://www.googleapis.com/auth/drive.file';
export const DRIVE_DOC_MIME = 'application/vnd.google-apps.document';
export const DRIVE_TEXT_MIME = 'text/plain';
export const DRIVE_SUPPORTED_MIME_TYPES: readonly string[] = [DRIVE_DOC_MIME, DRIVE_TEXT_MIME] as const;
export const DRIVE_MAX_BYTES = 200000;
export const DRIVE_MAX_REQUESTS = 3;
export const DRIVE_PICKER_SCRIPT = 'https://apis.google.com/js/api.js';
export const DRIVE_AUTHORIZE_URL = '/api/drive-import/authorize';
export const DRIVE_PICKER_TOKEN_URL = '/api/drive-import/picker-token';
export const DRIVE_PHOTO_SUGGESTIONS_URL = '/api/drive-import/photo-suggestions';

export const DRIVE_JPEG_MIME = 'image/jpeg';
export const DRIVE_PNG_MIME = 'image/png';
export const DRIVE_SUPPORTED_PHOTO_MIME_TYPES: readonly string[] = [DRIVE_JPEG_MIME, DRIVE_PNG_MIME] as const;
export const DRIVE_PICKER_PHOTO_MIME_FILTER = 'image/jpeg,image/png';
export const DRIVE_MAX_PHOTO_BYTES = 1048576;
export const DRIVE_MAX_PHOTO_PIXELS = 8000000;
export const DRIVE_PHOTO_PARSER_VERSION = 'drive-photo/v1';

export type DrivePhotoProposalOut = {
  status: 'unconfirmed';
  source: 'drive_file';
  product_fact_source: 'drive_file';
  file_title: string;
  mime_type: string;
  selection_context: string;
  width: number;
  height: number;
  byte_size: number;
  sha256: string;
  confirmed: false;
  requires_approval: true;
  parser_version: string;
};

export type DrivePhotoClaim = {
  fileTitle: string;
  mimeType: string;
  width: number;
  height: number;
  sha256: string;
  approved: boolean;
  confirmed: false;
  source: 'drive_file';
};

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

export function isSupportedDrivePhotoMime(mime: string): boolean {
  return mime === DRIVE_JPEG_MIME || mime === DRIVE_PNG_MIME;
}

export function drivePhotoMimeLabel(mime: string): string {
  if (mime === DRIVE_JPEG_MIME) return 'JPEG photo';
  if (mime === DRIVE_PNG_MIME) return 'PNG photo';
  return mime;
}

export function validateDrivePhotoApproval(approved: boolean): string[] {
  if (approved !== true) return ['Photo use needs your explicit approval before any photo check.'];
  return [];
}

export function toUnconfirmedDrivePhotoClaim(
  proposal: Pick<DrivePhotoProposalOut, 'file_title' | 'mime_type' | 'width' | 'height' | 'sha256'>,
  approved: boolean,
): DrivePhotoClaim | null {
  if (approved !== true) return null;
  if (typeof proposal.sha256 !== 'string' || !/^[0-9a-f]{64}$/.test(proposal.sha256)) return null;
  if (!Number.isInteger(proposal.width) || proposal.width <= 0) return null;
  if (!Number.isInteger(proposal.height) || proposal.height <= 0) return null;
  if (proposal.width * proposal.height > DRIVE_MAX_PHOTO_PIXELS) return null;
  if (!isSupportedDrivePhotoMime(proposal.mime_type)) return null;
  return {
    fileTitle: proposal.file_title,
    mimeType: proposal.mime_type,
    width: proposal.width,
    height: proposal.height,
    sha256: proposal.sha256,
    approved: true,
    confirmed: false,
    source: 'drive_file',
  };
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

export function driveAuthStatusFromSearch(search: string): 'authorized' | null {
  if (!search) return null;
  const params = new URLSearchParams(search.startsWith('?') ? search.slice(1) : search);
  if (params.get('drive') === 'authorized') return 'authorized';
  return null;
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
  if (statusCode === 403) return 'Drive consent is missing or expired. Reconnect and pick the file again.';
  if (statusCode === 413) return 'The selected Drive file is too large for the bounded demo import.';
  if (statusCode === 422) return 'The selected Drive file type is not supported. Use a Google Doc or a plain text file.';
  if (statusCode === 503) return 'Drive intake is not configured. Pasted-text import still works.';
  return 'Drive intake failed. Pasted-text import still works.';
}

export function drivePhotoErrorMessage(statusCode: number): string {
  if (statusCode === 413) return 'The selected Drive photo is too large. Photos stay within 1 MiB and 8 million pixels.';
  if (statusCode === 422) return 'The selected Drive photo is not supported. Use a JPEG or PNG photo you select.';
  return driveErrorMessage(statusCode);
}
