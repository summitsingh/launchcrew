'use client';
import { useEffect, useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { api, unwrap } from '@/lib/api';
import { PendingReplaceBanner, StructuredProposalFields } from '@/components/import-suggestions-form';
import {
  PENDING_REPLACE_WARNING,
  StructuredReplaceConflict,
  applyStructuredSuggestionToState,
  isStructuredConflictError,
} from '@/lib/import-suggestions';
import {
  DRIVE_AUTHORIZE_URL,
  DRIVE_PICKER_SCRIPT,
  DRIVE_PICKER_PHOTO_MIME_FILTER,
  DRIVE_PHOTO_SUGGESTIONS_URL,
  driveAuthStatusFromSearch,
  driveErrorMessage,
  driveMimeLabel,
  drivePhotoErrorMessage,
  drivePhotoMimeLabel,
  driveStatusMessage,
  isSupportedDriveMime,
  isSupportedDrivePhotoMime,
  toUnconfirmedDrivePhotoClaim,
  validateDriveFileId,
  validateDrivePhotoApproval,
  validateDriveResourceKey,
  type DriveImportOut,
  type DrivePhotoClaim,
  type DrivePhotoProposalOut,
  type DrivePublicConfigOut,
  type DriveStatusOut,
  type DriveSuggestionItem,
} from '@/lib/drive-intake';
import { sourceLabel, type OwnerFactsState } from '@/lib/product-facts';

declare global {
  interface Window {
    gapi?: { load: (api: string, cb: () => void) => void };
    google?: {
      picker?: unknown;
    };
  }
}

type DrivePickerView = {
  setMimeTypes: (mimeTypes: string) => void;
  setSelectFolderEnabled: (enabled: boolean) => void;
};

type DrivePickerBuilt = {
  setVisible: (visible: boolean) => void;
};

type DrivePickerBuilder = {
  setOAuthToken: (token: string) => DrivePickerBuilder;
  setDeveloperKey: (key: string) => DrivePickerBuilder;
  setAppId: (appId: string) => DrivePickerBuilder;
  addView: (view: DrivePickerView) => DrivePickerBuilder;
  setCallback: (callback: (data: unknown) => void) => DrivePickerBuilder;
  build: () => DrivePickerBuilt;
};

type DrivePickerApiShape = {
  PickerBuilder: new () => DrivePickerBuilder;
  DocsView: new (viewId?: string) => DrivePickerView;
  ViewId?: { DOCS?: string };
  Action?: { PICKED?: string; CANCEL?: string };
};

function isDrivePickerApiShape(value: unknown): value is DrivePickerApiShape {
  if (typeof value !== 'object' || value === null) return false;
  const candidate = value as Record<string, unknown>;
  return typeof candidate.PickerBuilder === 'function' && typeof candidate.DocsView === 'function';
}

function loadScript(src: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const existing = document.querySelector(`script[src="${src}"]`);
    if (existing) {
      resolve();
      return;
    }
    const tag = document.createElement('script');
    tag.src = src;
    tag.async = true;
    tag.defer = true;
    tag.onload = () => resolve();
    tag.onerror = () => reject(new Error(`Script failed: ${src}`));
    document.head.appendChild(tag);
  });
}

export function DriveSuggestionsList({
  result,
  edited,
  onEdit,
  onAddOne,
  onAddAll,
}: {
  result: DriveImportOut;
  edited: Record<number, string>;
  onEdit: (index: number, value: string) => void;
  onAddOne: (index: number) => void;
  onAddAll: () => void;
}) {
  if (result.suggestions.length === 0) {
    return <p role="status">No suggestions from the selected Drive file.</p>;
  }
  return (
    <div>
      <p className="hint">
        Drive file selection produced {result.suggestions.length} suggestion{result.suggestions.length === 1 ? '' : 's'}.
        File: {result.file_title} ({driveMimeLabel(result.mime_type)}).
        Status: unconfirmed. Parser: {result.parser_version}.
        {result.truncated ? ' Truncated to the bounded list.' : ''}
        {result.dropped_duplicates > 0 ? ` Dropped duplicates: ${result.dropped_duplicates}.` : ''}
        {result.dropped_overlong > 0 ? ` Dropped overlong: ${result.dropped_overlong}.` : ''}
        {result.dropped_empty > 0 ? ` Skipped empty lines: ${result.dropped_empty}.` : ''}
      </p>
      <ul className="scout-list">
        {result.suggestions.map(item => {
          const current = edited[item.index] ?? item.text;
          return (
            <li key={item.index} className="scout-fact">
              <div className="scout-row">
                <span>Suggestion {item.index + 1}</span>
                <span className="badge pending">Unconfirmed</span>
              </div>
              <label htmlFor={`drive-suggestion-${item.index}`}>Edit suggestion {item.index + 1}</label>
              <input
                id={`drive-suggestion-${item.index}`}
                value={current}
                onChange={e => onEdit(item.index, e.target.value)}
              />
              <p className="hint">
                Source: Drive file ({driveMimeLabel(result.mime_type)}) · Selection: {result.selection_context} · Product fact source: {sourceLabel(item.product_fact_source)} · Status: unconfirmed · Confirmed: no
              </p>
              <div className="queue-actions">
                <Button type="button" variant="outline" onClick={() => onAddOne(item.index)}>
                  Add as allowed claim
                </Button>
              </div>
            </li>
          );
        })}
      </ul>
      {result.suggestions.length > 1 && (
        <div className="queue-actions">
          <Button type="button" variant="outline" onClick={onAddAll}>
            Add all as allowed claims
          </Button>
        </div>
      )}
    </div>
  );
}

export function DriveIntakeForm({
  onApplyState,
  disabled,
}: {
  onApplyState: (updater: (state: OwnerFactsState) => OwnerFactsState) => void;
  disabled?: boolean;
}) {
  const [pickerReady, setPickerReady] = useState(false);
  const [scriptError, setScriptError] = useState('');
  const [pickerToken, setPickerToken] = useState('');
  const [selectionTitle, setSelectionTitle] = useState('');
  const [selectionMime, setSelectionMime] = useState('');
  const [result, setResult] = useState<DriveImportOut | null>(null);
  const [held, setHeld] = useState<DriveImportOut | null>(null);
  const [replaceWarning, setReplaceWarning] = useState('');
  const [localError, setLocalError] = useState('');

  const statusQuery = useQuery({
    queryKey: ['drive-status'],
    queryFn: () => unwrap(api.GET('/api/drive-import/status')),
  });
  const status: DriveStatusOut | undefined = statusQuery.data;
  const available = status?.available === true && status?.configured === true;

  const configQuery = useQuery({
    queryKey: ['drive-config'],
    queryFn: () => unwrap(api.GET('/api/drive-import/config')),
    enabled: available,
    retry: false,
  });
  const config: DrivePublicConfigOut | undefined = configQuery.data;

  useEffect(() => {
    if (!available || !config) return;
    let cancelled = false;
    setScriptError('');
    loadScript(DRIVE_PICKER_SCRIPT)
      .then(() => {
        if (cancelled) return;
        const gapi = window.gapi;
        if (!gapi || typeof gapi.load !== 'function') {
          setScriptError('Drive Picker failed to load. Pasted-text import still works.');
          return;
        }
        gapi.load('picker', () => {
          if (!cancelled) setPickerReady(true);
        });
      })
      .catch(() => {
        if (!cancelled) setScriptError('Drive libraries failed to load. Pasted-text import still works.');
      });
    return () => {
      cancelled = true;
    };
  }, [available, config]);

  const busy = statusQuery.isPending || configQuery.isPending || disabled === true;

  const suggest = useMutation({
    mutationFn: async (input: { file_id: string; resource_key: string | null; drive_token: string; confirm_replace: boolean }) => {
      const { data, error, response } = await api.POST('/api/drive-import/suggestions', {
        body: {
          file_id: input.file_id,
          resource_key: input.resource_key,
          drive_token: input.drive_token,
          active_digest: result?.proposal_digest ?? null,
          confirm_replace: input.confirm_replace,
        },
      });
      if (!response.ok || !data) {
        const conflict = error as unknown;
        if (response.status === 409 && isStructuredConflictError(conflict)) {
          throw new StructuredReplaceConflict(
            conflict.message || PENDING_REPLACE_WARNING,
            conflict.active_digest,
            conflict.proposal_digest,
            conflict.proposal,
          );
        }
        throw new Error(`Request failed (${response.status}). Check the API and try again.`);
      }
      return data;
    },
    onSuccess: data => {
      setResult(data);
      setHeld(null);
      setReplaceWarning('');
      setLocalError('');
      setPickerToken('');
    },
    onError: (error: unknown) => {
      setPickerToken('');
      if (error instanceof StructuredReplaceConflict) {
        setHeld(error.proposal as unknown as DriveImportOut);
        setReplaceWarning(error.message);
        return;
      }
      const message = error instanceof Error ? error.message : '';
      const match = message.match(/\((\d+)\)/);
      const code = match ? Number(match[1]) : 0;
      setLocalError(driveErrorMessage(code));
    },
  });

  const claimToken = useMutation({
    mutationFn: () => unwrap(api.POST('/api/drive-import/picker-token')),
    onSuccess: data => {
      const token = (data as { access_token?: unknown }).access_token;
      if (typeof token !== 'string' || !token) {
        setLocalError(driveErrorMessage(403));
        return;
      }
      setPickerToken(token);
      setLocalError('');
    },
    onError: (error: unknown) => {
      setPickerToken('');
      const message = error instanceof Error ? error.message : '';
      const match = message.match(/\((\d+)\)/);
      const code = match ? Number(match[1]) : 0;
      setLocalError(driveErrorMessage(code));
    },
  });

  useEffect(() => {
    if (typeof window === 'undefined') return;
    if (driveAuthStatusFromSearch(window.location.search) !== 'authorized') return;
    window.history.replaceState(null, '', window.location.pathname);
    claimToken.mutate();
    // Claim once after Drive consent redirect. Token stays in memory only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const applyOne = (proposal: DriveImportOut) => (index: number, value: string) => {
    const item = proposal.field_suggestions.find(s => s.index === index);
    if (!item) return;
    onApplyState(prev => applyStructuredSuggestionToState(prev, item, value));
  };
  const applyAll = (proposal: DriveImportOut) => (selected: { index: number; value: string }[]) => {
    for (const { index, value } of selected) {
      applyOne(proposal)(index, value);
    }
  };

  const launchPickerWithToken = (token: string) => {
    if (!config) {
      setLocalError(driveErrorMessage(503));
      return;
    }
    const rawPicker: unknown = (window.google as { picker?: unknown } | undefined)?.picker;
    if (!isDrivePickerApiShape(rawPicker)) {
      setLocalError('Drive Picker is not ready. Try again after it loads.');
      return;
    }
    const PickerBuilderCtor = rawPicker.PickerBuilder;
    const DocsViewCtor = rawPicker.DocsView;
    const viewIdContainer: unknown = rawPicker.ViewId;
    if (viewIdContainer !== undefined && (typeof viewIdContainer !== 'object' || viewIdContainer === null)) {
      setLocalError('Drive Picker is not ready. Try again after it loads.');
      return;
    }
    const viewIdRaw: unknown = (viewIdContainer as { DOCS?: unknown } | undefined)?.DOCS;
    if (viewIdRaw !== undefined && typeof viewIdRaw !== 'string') {
      setLocalError('Drive Picker is not ready. Try again after it loads.');
      return;
    }
    const docsViewId: string | undefined = typeof viewIdRaw === 'string' ? viewIdRaw : undefined;
    const pickedAction: unknown = rawPicker.Action?.PICKED;
    const cancelAction: unknown = rawPicker.Action?.CANCEL;
    if (
      typeof pickedAction !== 'string' ||
      !pickedAction ||
      typeof cancelAction !== 'string' ||
      !cancelAction
    ) {
      setLocalError('Drive Picker is not ready. Try again after it loads.');
      return;
    }
    try {
      const view = new DocsViewCtor(docsViewId);
      if (typeof view.setMimeTypes !== 'function' || typeof view.setSelectFolderEnabled !== 'function') {
        setLocalError('Drive Picker is not ready. Try again after it loads.');
        return;
      }
      view.setMimeTypes('application/vnd.google-apps.document,text/plain');
      view.setSelectFolderEnabled(false);
      const picker = new PickerBuilderCtor()
        .setOAuthToken(token)
        .setDeveloperKey(config.api_key)
        .setAppId(config.app_id)
        .addView(view)
        .setCallback((data: unknown) => {
          const payload = data as {
            action?: string;
            docs?: { id?: unknown; name?: unknown; mimeType?: unknown; resourceKey?: unknown }[];
          };
          if (payload?.action === cancelAction) {
            return;
          }
          if (payload?.action !== pickedAction || !payload?.docs?.length) {
            setLocalError('No Drive file was selected.');
            return;
          }
          const doc = payload.docs[0];
          const fileId = typeof doc.id === 'string' ? doc.id : '';
          const resourceKey = typeof doc.resourceKey === 'string' ? doc.resourceKey : null;
          const title = typeof doc.name === 'string' ? doc.name : 'Drive file';
          const mime = typeof doc.mimeType === 'string' ? doc.mimeType : '';
          if (validateDriveFileId(fileId).length > 0 || validateDriveResourceKey(resourceKey).length > 0) {
            setLocalError(driveErrorMessage(422));
            return;
          }
          if (!isSupportedDriveMime(mime)) {
            setLocalError(driveErrorMessage(422));
            return;
          }
          setSelectionTitle(title);
          setSelectionMime(mime);
          suggest.mutate({ file_id: fileId, resource_key: resourceKey, drive_token: token, confirm_replace: false });
        })
        .build();
      if (!picker || typeof picker.setVisible !== 'function') {
        setLocalError('Drive Picker is not ready. Try again after it loads.');
        return;
      }
      picker.setVisible(true);
    } catch {
      setLocalError('Drive Picker is not ready. Try again after it loads.');
    }
  };

  const handleChoose = () => {
    setLocalError('');
    if (!config) {
      setLocalError(driveErrorMessage(503));
      return;
    }
    if (!pickerToken) {
      window.location.href = DRIVE_AUTHORIZE_URL;
      return;
    }
    if (!pickerReady) {
      setLocalError('Drive Picker is not ready. Try again after it loads.');
      return;
    }
    launchPickerWithToken(pickerToken);
  };

  useEffect(() => {
    if (!pickerToken || !pickerReady || !config) return;
    launchPickerWithToken(pickerToken);
    // Launch once when a fresh server-issued token and Picker are both ready.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pickerToken, pickerReady, config]);

  const ready = available && !!config && pickerReady && !scriptError && !busy && !claimToken.isPending;

  return (
    <div>
      <h3>Select a Drive file</h3>
      <p className="hint">
        Optional Google Picker intake for one Google Doc or plain text file you select. Sign-in stays Google identity only.
        Drive consent is a separate step that issues a short lived Picker token to this browser session only. Proposals stay
        unconfirmed suggestions with Drive file provenance. Nothing becomes evidence until you edit and
        explicitly confirm each in the fact form. Live Drive proof has not been run.
      </p>
      {statusQuery.isPending && <p role="status">Checking Drive intake status...</p>}
      {statusQuery.isError && (
        <p role="alert">Drive status failed to load. Pasted-text import still works.</p>
      )}
      {status && <p role="status">{driveStatusMessage(status)}</p>}
      {status && !available && (
        <p className="hint">Drive intake is optional and unavailable. Use pasted-text import above.</p>
      )}
      {available && configQuery.isError && (
        <p role="alert">Drive configuration failed to load. Pasted-text import still works.</p>
      )}
      {scriptError && <p role="alert">{scriptError}</p>}
      {localError && <p role="alert">{localError}</p>}
      {selectionTitle && result && (
        <p className="hint">
          Selected: {result.file_title} ({driveMimeLabel(result.mime_type)}). {result.selection_context}.
        </p>
      )}
      {selectionTitle && !result && !suggest.isPending && (
        <p className="hint">
          Selected: {selectionTitle}
          {selectionMime ? ` (${driveMimeLabel(selectionMime)})` : ''}. Reading the selected file.
        </p>
      )}
      <div className="queue-actions">
        <Button type="button" variant="outline" disabled={!available || busy || suggest.isPending || claimToken.isPending} onClick={handleChoose}>
          {suggest.isPending ? 'Reading selected file...' : claimToken.isPending ? 'Connecting Drive...' : pickerToken ? 'Choose Drive file' : 'Connect Drive and choose file'}
        </Button>
      </div>
      {!ready && available && !scriptError && (
        <p className="hint">Loading Drive Picker libraries. Pasted-text import still works.</p>
      )}
      {replaceWarning && held && (
        <div>
          <PendingReplaceBanner
            warning={replaceWarning}
            activeDigest={result?.proposal_digest}
            heldDigest={held.proposal_digest}
            heldLabel="Held"
            onReplace={() => {
              setResult({ ...held, replaced: true });
              setHeld(null);
              setReplaceWarning('');
            }}
            onKeep={() => { setHeld(null); setReplaceWarning(''); }}
          />
          <p className="hint">The held import is shown below for review. Replacement needs no new file read.</p>
        </div>
      )}
      {result && (
        <div>
          <h4>Pending per-field proposal (Drive file)</h4>
          {result.replaced && <p className="hint">Pending proposal was replaced by your confirmed replacement.</p>}
          <StructuredProposalFields
            result={result}
            idPrefix="drive-pending"
            onApplyOne={applyOne(result)}
            onApplyAll={applyAll(result)}
          />
        </div>
      )}
      {held && (
        <div>
          <h4>Held new import (did not replace pending)</h4>
          <StructuredProposalFields
            result={held}
            idPrefix="drive-held"
            onApplyOne={applyOne(held)}
            onApplyAll={applyAll(held)}
          />
        </div>
      )}
      {pickerToken && <p className="hint">Drive session is active for this selection only.</p>}
    </div>
  );
}

export function DrivePhotoProposalView({
  proposal,
  approved,
  onToggleApproval,
  onAdd,
}: {
  proposal: DrivePhotoProposalOut;
  approved: boolean;
  onToggleApproval: (approved: boolean) => void;
  onAdd: (claim: DrivePhotoClaim) => void;
}) {
  const claim = toUnconfirmedDrivePhotoClaim(proposal, approved);
  return (
    <div>
      <p className="hint">
        Drive photo selection produced one unconfirmed proposal. File: {proposal.file_title} (
        {drivePhotoMimeLabel(proposal.mime_type)}). Status: unconfirmed. Parser: {proposal.parser_version}.
      </p>
      <ul className="scout-list">
        <li className="scout-fact">
          <div className="scout-row">
            <span>Selected photo</span>
            <span className="badge pending">Unconfirmed</span>
          </div>
          <p className="hint">
            Source: Drive file ({drivePhotoMimeLabel(proposal.mime_type)}) · Selection: {proposal.selection_context} ·
            Dimensions: {proposal.width} by {proposal.height} · Size: {proposal.byte_size} bytes · Confirmed: no ·
            Photo use needs approval
          </p>
          <label htmlFor="drive-photo-approval">
            <input
              id="drive-photo-approval"
              type="checkbox"
              checked={approved}
              onChange={e => onToggleApproval(e.target.checked)}
            />
            I approve using this selected photo for a later photo check. Original pixels only.
          </label>
          <div className="queue-actions">
            <Button
              type="button"
              variant="outline"
              disabled={!claim}
              onClick={() => {
                if (claim) onAdd(claim);
              }}
            >
              Add photo as unconfirmed claim
            </Button>
          </div>
          {!claim && <p className="hint">Approval is required before the photo can be added. Nothing is confirmed yet.</p>}
        </li>
      </ul>
    </div>
  );
}

export function DrivePhotoIntakeForm({
  onAddPhoto,
  disabled,
}: {
  onAddPhoto: (claim: DrivePhotoClaim) => void;
  disabled?: boolean;
}) {
  const [pickerReady, setPickerReady] = useState(false);
  const [scriptError, setScriptError] = useState('');
  const [pickerToken, setPickerToken] = useState('');
  const [proposal, setProposal] = useState<DrivePhotoProposalOut | null>(null);
  const [approved, setApproved] = useState(false);
  const [localError, setLocalError] = useState('');

  const statusQuery = useQuery({
    queryKey: ['drive-status'],
    queryFn: () => unwrap(api.GET('/api/drive-import/status')),
  });
  const status: DriveStatusOut | undefined = statusQuery.data;
  const available = status?.available === true && status?.configured === true;

  const configQuery = useQuery({
    queryKey: ['drive-config'],
    queryFn: () => unwrap(api.GET('/api/drive-import/config')),
    enabled: available,
    retry: false,
  });
  const config: DrivePublicConfigOut | undefined = configQuery.data;

  useEffect(() => {
    if (!available || !config) return;
    let cancelled = false;
    setScriptError('');
    loadScript(DRIVE_PICKER_SCRIPT)
      .then(() => {
        if (cancelled) return;
        const gapi = window.gapi;
        if (!gapi || typeof gapi.load !== 'function') {
          setScriptError('Drive Picker failed to load. Pasted-text import still works.');
          return;
        }
        gapi.load('picker', () => {
          if (!cancelled) setPickerReady(true);
        });
      })
      .catch(() => {
        if (!cancelled) setScriptError('Drive libraries failed to load. Pasted-text import still works.');
      });
    return () => {
      cancelled = true;
    };
  }, [available, config]);

  const busy = statusQuery.isPending || configQuery.isPending || disabled === true;

  const suggestPhoto = useMutation({
    mutationFn: (input: { file_id: string; resource_key: string | null; drive_token: string }) =>
      unwrap(
        api.POST(DRIVE_PHOTO_SUGGESTIONS_URL as '/api/drive-import/suggestions', {
          body: {
            file_id: input.file_id,
            resource_key: input.resource_key,
            drive_token: input.drive_token,
            confirm_replace: false,
          },
        }),
      ) as unknown as Promise<DrivePhotoProposalOut>,
    onSuccess: data => {
      setProposal(data);
      setApproved(false);
      setLocalError('');
      setPickerToken('');
    },
    onError: (error: unknown) => {
      setPickerToken('');
      const message = error instanceof Error ? error.message : '';
      const match = message.match(/\((\d+)\)/);
      const code = match ? Number(match[1]) : 0;
      setLocalError(drivePhotoErrorMessage(code));
    },
  });

  const claimToken = useMutation({
    mutationFn: () => unwrap(api.POST('/api/drive-import/picker-token')),
    onSuccess: data => {
      const token = (data as { access_token?: unknown }).access_token;
      if (typeof token !== 'string' || !token) {
        setLocalError(drivePhotoErrorMessage(403));
        return;
      }
      setPickerToken(token);
      setLocalError('');
    },
    onError: (error: unknown) => {
      setPickerToken('');
      const message = error instanceof Error ? error.message : '';
      const match = message.match(/\((\d+)\)/);
      const code = match ? Number(match[1]) : 0;
      setLocalError(drivePhotoErrorMessage(code));
    },
  });

  useEffect(() => {
    if (typeof window === 'undefined') return;
    if (driveAuthStatusFromSearch(window.location.search) !== 'authorized') return;
    window.history.replaceState(null, '', window.location.pathname);
    claimToken.mutate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const launchPhotoPickerWithToken = (token: string) => {
    if (!config) {
      setLocalError(drivePhotoErrorMessage(503));
      return;
    }
    const rawPicker: unknown = (window.google as { picker?: unknown } | undefined)?.picker;
    if (!isDrivePickerApiShape(rawPicker)) {
      setLocalError('Drive Picker is not ready. Try again after it loads.');
      return;
    }
    const PickerBuilderCtor = rawPicker.PickerBuilder;
    const DocsViewCtor = rawPicker.DocsView;
    const cancelAction: unknown = rawPicker.Action?.CANCEL;
    const pickedAction: unknown = rawPicker.Action?.PICKED;
    if (typeof pickedAction !== 'string' || !pickedAction || typeof cancelAction !== 'string' || !cancelAction) {
      setLocalError('Drive Picker is not ready. Try again after it loads.');
      return;
    }
    try {
      const view = new DocsViewCtor();
      if (typeof view.setMimeTypes !== 'function' || typeof view.setSelectFolderEnabled !== 'function') {
        setLocalError('Drive Picker is not ready. Try again after it loads.');
        return;
      }
      view.setMimeTypes(DRIVE_PICKER_PHOTO_MIME_FILTER);
      view.setSelectFolderEnabled(false);
      const picker = new PickerBuilderCtor()
        .setOAuthToken(token)
        .setDeveloperKey(config.api_key)
        .setAppId(config.app_id)
        .addView(view)
        .setCallback((data: unknown) => {
          const payload = data as {
            action?: string;
            docs?: { id?: unknown; name?: unknown; mimeType?: unknown; resourceKey?: unknown }[];
          };
          if (payload?.action === cancelAction) return;
          if (payload?.action !== pickedAction || !payload?.docs?.length) {
            setLocalError('No Drive photo was selected.');
            return;
          }
          const doc = payload.docs[0];
          const fileId = typeof doc.id === 'string' ? doc.id : '';
          const resourceKey = typeof doc.resourceKey === 'string' ? doc.resourceKey : null;
          const mime = typeof doc.mimeType === 'string' ? doc.mimeType : '';
          if (validateDriveFileId(fileId).length > 0 || validateDriveResourceKey(resourceKey).length > 0) {
            setLocalError(drivePhotoErrorMessage(422));
            return;
          }
          if (!isSupportedDrivePhotoMime(mime)) {
            setLocalError(drivePhotoErrorMessage(422));
            return;
          }
          suggestPhoto.mutate({ file_id: fileId, resource_key: resourceKey, drive_token: token });
        })
        .build();
      if (!picker || typeof picker.setVisible !== 'function') {
        setLocalError('Drive Picker is not ready. Try again after it loads.');
        return;
      }
      picker.setVisible(true);
    } catch {
      setLocalError('Drive Picker is not ready. Try again after it loads.');
    }
  };

  const handleChoose = () => {
    setLocalError('');
    setProposal(null);
    setApproved(false);
    if (!config) {
      setLocalError(drivePhotoErrorMessage(503));
      return;
    }
    if (!pickerToken) {
      window.location.href = DRIVE_AUTHORIZE_URL;
      return;
    }
    if (!pickerReady) {
      setLocalError('Drive Picker is not ready. Try again after it loads.');
      return;
    }
    launchPhotoPickerWithToken(pickerToken);
  };

  useEffect(() => {
    if (!pickerToken || !pickerReady || !config) return;
    launchPhotoPickerWithToken(pickerToken);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pickerToken, pickerReady, config]);

  const approvalErrors = validateDrivePhotoApproval(approved);

  return (
    <div>
      <h3>Select a Drive photo</h3>
      <p className="hint">
        Optional Google Picker intake for one JPEG or PNG photo you select. Sign-in stays Google identity only. Drive
        consent is a separate step that issues a short lived Picker token to this browser session only. The proposal
        stays unconfirmed with Drive file provenance and needs your explicit approval before any photo check. Original
        pixels only. Live Drive proof has not been run.
      </p>
      {statusQuery.isPending && <p role="status">Checking Drive intake status...</p>}
      {status && <p role="status">{driveStatusMessage(status)}</p>}
      {status && !available && (
        <p className="hint">Drive photo intake is optional and unavailable. Use pasted-text import above.</p>
      )}
      {localError && <p role="alert">{localError}</p>}
      {scriptError && <p role="alert">{scriptError}</p>}
      <div className="queue-actions">
        <Button
          type="button"
          variant="outline"
          disabled={!available || busy || suggestPhoto.isPending || claimToken.isPending}
          onClick={handleChoose}
        >
          {suggestPhoto.isPending
            ? 'Reading selected photo...'
            : claimToken.isPending
              ? 'Connecting Drive...'
              : pickerToken
                ? 'Choose Drive photo'
                : 'Connect Drive and choose photo'}
        </Button>
      </div>
      {proposal && (
        <DrivePhotoProposalView
          proposal={proposal}
          approved={approved}
          onToggleApproval={setApproved}
          onAdd={onAddPhoto}
        />
      )}
      {approvalErrors.length > 0 && !proposal && (
        <p className="hint">Photo use needs your explicit approval before any photo check. Nothing is confirmed yet.</p>
      )}
      {pickerToken && <p className="hint">Drive session is active for this selection only.</p>}
    </div>
  );
}
