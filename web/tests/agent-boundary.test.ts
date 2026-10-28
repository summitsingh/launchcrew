import { describe, expect, it } from 'vitest';
import { canClone, canPreview, canSave, canSelect } from '../src/lib/agent-boundary';

// The clone and dry-run preview buttons read the saved server profile, so
// the boundary below must hold or the clone silently copies the old profile
// while the form shows the new text.
describe('agent builder save/clone boundary', () => {
  it('saves only when no save or clone is in flight', () => {
    expect(canSave({ savePending: false, clonePending: false })).toBe(true);
    expect(canSave({ savePending: true, clonePending: false })).toBe(false);
    expect(canSave({ savePending: false, clonePending: true })).toBe(false);
  });

  it('previews the saved profile only when clean and idle', () => {
    const clean = { dirty: false, savePending: false, clonePending: false, dryRunPending: false };
    expect(canPreview(clean)).toBe(true);
    expect(canPreview({ ...clean, dirty: true })).toBe(false);
    expect(canPreview({ ...clean, savePending: true })).toBe(false);
    expect(canPreview({ ...clean, clonePending: true })).toBe(false);
    expect(canPreview({ ...clean, dryRunPending: true })).toBe(false);
  });

  it('clones only a named, clean, idle profile', () => {
    const ready = { cloneName: 'MakerCopy', dirty: false, savePending: false, clonePending: false };
    expect(canClone(ready)).toBe(true);
    expect(canClone({ ...ready, cloneName: '' })).toBe(false);
    expect(canClone({ ...ready, dirty: true })).toBe(false);
    expect(canClone({ ...ready, savePending: true })).toBe(false);
    expect(canClone({ ...ready, clonePending: true })).toBe(false);
  });

  it('selects another profile only when no save or clone is in flight', () => {
    expect(canSelect({ savePending: false, clonePending: false })).toBe(true);
    expect(canSelect({ savePending: true, clonePending: false })).toBe(false);
    expect(canSelect({ savePending: false, clonePending: true })).toBe(false);
  });
});
