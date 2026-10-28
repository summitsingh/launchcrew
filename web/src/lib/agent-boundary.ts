// Save/clone boundary for the agent builder.
//
// Clone and dry-run preview read the saved server profile, never the
// in-progress form state. They must not run against unsaved edits or while
// a save is still in flight, or the clone silently copies the old server
// profile while the UI appears updated. Save must not run while a clone is
// in flight either, since the clone renames server identity. Selecting a
// different profile mid-flight would retarget the in-flight mutation, so
// selection waits too.
export interface AgentBuilderState {
  cloneName: string;
  dirty: boolean;
  savePending: boolean;
  clonePending: boolean;
  dryRunPending: boolean;
}

export function canSave(state: Pick<AgentBuilderState, 'savePending' | 'clonePending'>): boolean {
  return !state.savePending && !state.clonePending;
}

export function canPreview(state: Pick<AgentBuilderState, 'dirty' | 'savePending' | 'clonePending' | 'dryRunPending'>): boolean {
  return !state.dirty && !state.savePending && !state.clonePending && !state.dryRunPending;
}

export function canClone(state: Pick<AgentBuilderState, 'cloneName' | 'dirty' | 'savePending' | 'clonePending'>): boolean {
  return state.cloneName !== '' && !state.dirty && !state.savePending && !state.clonePending;
}

export function canSelect(state: Pick<AgentBuilderState, 'savePending' | 'clonePending'>): boolean {
  return !state.savePending && !state.clonePending;
}
