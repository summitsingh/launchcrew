'use client';
import { useEffect, useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { api, unwrap } from '@/lib/api';
import {
  DRIVE_GIS_SCRIPT,
  DRIVE_PICKER_SCRIPT,
  DRIVE_SCOPE,
  driveErrorMessage,
  driveMimeLabel,
  driveStatusMessage,
  isSupportedDriveMime,
  toOwnerFactFromDriveSuggestion,
  toOwnerFactsFromDriveSuggestions,
  validateDriveFileId,
  validateDriveResourceKey,
  type DriveImportOut,
  type DrivePublicConfigOut,
  type DriveStatusOut,
  type DriveSuggestionItem,
} from '@/lib/drive-intake';
import { sourceLabel, type OwnerFactState } from '@/lib/product-facts';

declare global {
  interface Window {
    gapi?: { load: (api: string, cb: () => void) => void };
    google?: {
      accounts?: { oauth2?: { initTokenClient: (cfg: unknown) => { requestAccessToken: (opts?: unknown) => void } } };
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
  onAdd,
  disabled,
}: {
  onAdd: (facts: OwnerFactState[]) => void;
  disabled?: boolean;
}) {
  const [gisReady, setGisReady] = useState(false);
  const [pickerReady, setPickerReady] = useState(false);
  const [scriptError, setScriptError] = useState('');
  const [driveToken, setDriveToken] = useState('');
  const [selectionTitle, setSelectionTitle] = useState('');
  const [selectionMime, setSelectionMime] = useState('');
  const [result, setResult] = useState<DriveImportOut | null>(null);
  const [edited, setEdited] = useState<Record<number, string>>({});
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
    loadScript(DRIVE_GIS_SCRIPT)
      .then(() => {
        if (!cancelled) setGisReady(true);
        return loadScript(DRIVE_PICKER_SCRIPT);
      })
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
  const ready = available && !!config && gisReady && pickerReady && !scriptError && !busy;

  const suggest = useMutation({
    mutationFn: (input: { file_id: string; resource_key: string | null; drive_token: string }) =>
      unwrap(
        api.POST('/api/drive-import/suggestions', {
          body: {
            file_id: input.file_id,
            resource_key: input.resource_key,
            drive_token: input.drive_token,
          },
        }),
      ),
    onSuccess: data => {
      setResult(data);
      setEdited({});
      setLocalError('');
      setDriveToken('');
    },
    onError: (error: unknown) => {
      setDriveToken('');
      const message = error instanceof Error ? error.message : '';
      const match = message.match(/\((\d+)\)/);
      const code = match ? Number(match[1]) : 0;
      setLocalError(driveErrorMessage(code));
    },
  });

  const handleEdit = (index: number, value: string) => {
    setEdited(prev => ({ ...prev, [index]: value }));
  };
  const handleAddOne = (index: number) => {
    if (!result) return;
    const item = result.suggestions.find(s => s.index === index) as DriveSuggestionItem | undefined;
    if (!item) return;
    onAdd([toOwnerFactFromDriveSuggestion(item, edited[index] ?? item.text)]);
  };
  const handleAddAll = () => {
    if (!result) return;
    onAdd(toOwnerFactsFromDriveSuggestions(result.suggestions, edited));
  };

  const launchPicker = () => {
    setLocalError('');
    setResult(null);
    if (!config) {
      setLocalError(driveErrorMessage(503));
      return;
    }
    const oauth2 = window.google?.accounts?.oauth2;
    if (!oauth2 || typeof oauth2.initTokenClient !== 'function') {
      setLocalError('Drive sign-in library is not ready. Try again after it loads.');
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
    const tokenClient = oauth2.initTokenClient({
      client_id: config.client_id,
      scope: DRIVE_SCOPE,
      callback: (tokenResponse: unknown) => {
        const token = (tokenResponse as { access_token?: unknown })?.access_token;
        if (typeof token !== 'string' || !token) {
          setLocalError(driveErrorMessage(403));
          return;
        }
        setDriveToken(token);
        try {
          const view = new DocsViewCtor(docsViewId);
          if (typeof view.setMimeTypes !== 'function' || typeof view.setSelectFolderEnabled !== 'function') {
            setDriveToken('');
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
                setDriveToken('');
                return;
              }
              if (payload?.action !== pickedAction || !payload?.docs?.length) {
                setDriveToken('');
                setLocalError('No Drive file was selected.');
                return;
              }
              const doc = payload.docs[0];
              const fileId = typeof doc.id === 'string' ? doc.id : '';
              const resourceKey = typeof doc.resourceKey === 'string' ? doc.resourceKey : null;
              const title = typeof doc.name === 'string' ? doc.name : 'Drive file';
              const mime = typeof doc.mimeType === 'string' ? doc.mimeType : '';
              if (validateDriveFileId(fileId).length > 0 || validateDriveResourceKey(resourceKey).length > 0) {
                setDriveToken('');
                setLocalError(driveErrorMessage(422));
                return;
              }
              if (!isSupportedDriveMime(mime)) {
                setDriveToken('');
                setLocalError(driveErrorMessage(422));
                return;
              }
              setSelectionTitle(title);
              setSelectionMime(mime);
              suggest.mutate({ file_id: fileId, resource_key: resourceKey, drive_token: token });
            })
            .build();
          if (!picker || typeof picker.setVisible !== 'function') {
            setDriveToken('');
            setLocalError('Drive Picker is not ready. Try again after it loads.');
            return;
          }
          picker.setVisible(true);
        } catch {
          setDriveToken('');
          setLocalError('Drive Picker is not ready. Try again after it loads.');
        }
      },
    });
    tokenClient.requestAccessToken({ prompt: '' });
  };

  return (
    <div>
      <h3>Select a Drive file</h3>
      <p className="hint">
        Optional Google Picker intake for one Google Doc or plain text file you select. Proposals stay
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
        <Button type="button" variant="outline" disabled={!ready || suggest.isPending} onClick={launchPicker}>
          {suggest.isPending ? 'Reading selected file...' : 'Choose Drive file'}
        </Button>
      </div>
      {!ready && available && !scriptError && (
        <p className="hint">Loading Drive Picker libraries. Pasted-text import still works.</p>
      )}
      {result && (
        <DriveSuggestionsList
          result={result}
          edited={edited}
          onEdit={handleEdit}
          onAddOne={handleAddOne}
          onAddAll={handleAddAll}
        />
      )}
      {driveToken && <p className="hint">Drive session is active for this selection only.</p>}
    </div>
  );
}
