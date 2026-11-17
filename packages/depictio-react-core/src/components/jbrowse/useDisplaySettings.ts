import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { comparer, reaction, when } from 'mobx';
import { isAlive } from '@jbrowse/mobx-state-tree';

import {
  DISPLAY_SETTINGS,
  applyAll,
  applyOne,
  displayKeys,
  displaysOf,
  entryFor,
  groupsFor,
  groupTrackNames,
  openDisplayTypes,
  resolveAll,
  resolveValue,
  restoreBaseline,
  sanitizeValue,
  type Baselines,
  type DisplayGroup,
  type DisplaySettingEntry,
  type DisplaySettingKey,
  type DisplaySettingValue,
  type JBrowseDisplaySettings,
} from './displaySettings';

export interface DisplaySettingsApi {
  /** The groups with something to show: the view's, plus one per open display kind. */
  groups: DisplayGroup[];
  /** Types of the open displays (the alignments wrapper and its panels included). */
  openDisplayTypes: string[];
  /** Names of the open tracks a group acts on, read when asked. */
  tracksIn: (group: DisplayGroup) => string[];
  /** What the control shows: this tile's choice, else the YAML, else JBrowse's own. */
  value: (key: DisplaySettingKey) => DisplaySettingValue | undefined;
  /** Remember a choice for this tile and apply it to the open displays now. */
  set: (key: DisplaySettingKey, value: DisplaySettingValue) => void;
  /** Forget this tile's choices and go back to the YAML (or JBrowse's) values. */
  reset: () => void;
  /** True when this tile holds a choice of its own. */
  modified: boolean;
}

export const displayStorageKey = (index: string, key: string): string =>
  `depictio.jbrowse.${index}.display.${key}`;

/** A stored value the control could have produced; a number may sit outside its
 *  bounds (it is mid-typing) and is clamped when applied. */
function storable(entry: DisplaySettingEntry, value: unknown): DisplaySettingValue | undefined {
  if (entry.control === 'number') {
    return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
  }
  const clean = sanitizeValue(entry, value);
  return clean === '' ? undefined : clean;
}

function readLocal(index: string): JBrowseDisplaySettings {
  const out: Record<string, DisplaySettingValue> = {};
  for (const entry of DISPLAY_SETTINGS) {
    try {
      const raw = window.localStorage.getItem(displayStorageKey(index, entry.key));
      if (raw == null) continue;
      const value = storable(entry, JSON.parse(raw));
      if (value !== undefined) out[entry.key] = value;
    } catch {
      // Blocked storage or a value that is not JSON: no local choice.
    }
  }
  return out as JBrowseDisplaySettings;
}

function writeLocal(index: string, key: string, value: DisplaySettingValue | undefined): void {
  try {
    const storageKey = displayStorageKey(index, key);
    if (value === undefined) window.localStorage.removeItem(storageKey);
    else window.localStorage.setItem(storageKey, JSON.stringify(value));
  } catch {
    // Private mode / blocked storage: the choice just won't persist.
  }
}

/** ``isAlive`` throws on anything that is not a state-tree node. */
const alive = (node: unknown): boolean => {
  try {
    return !!node && isAlive(node as Parameters<typeof isAlive>[0]);
  } catch {
    return false;
  }
};

const sameList = (a: string[], b: string[]) => a.length === b.length && a.every((v, i) => v === b[i]);

/**
 * The display settings of one browser tile.
 *
 * Each setting resolves as this tile's stored choice, then the component's
 * `display:` YAML, then JBrowse's own default. The view settings are always
 * written, to the built-in default when nothing says otherwise: the
 * LinearGenomeView model seeds them from `lgv-*` localStorage keys that every
 * tile's changes overwrite, so a new view would otherwise inherit its sibling's.
 * Settings on displays go through a reaction on the open displays, so a track
 * opened later (or a lower panel swapped in) gets them too, while one the reader
 * already tuned in JBrowse's own menu is left alone.
 */
export function useDisplaySettings(
  view: unknown,
  yamlDisplay: JBrowseDisplaySettings | null | undefined,
  index: string,
): DisplaySettingsApi {
  const [version, setVersion] = useState(0);
  const [openTypes, setOpenTypes] = useState<string[]>([]);
  const baselines = useRef<Baselines>(new WeakMap());
  const yamlRef = useRef(yamlDisplay);
  yamlRef.current = yamlDisplay;
  const yamlSig = JSON.stringify(yamlDisplay ?? null);

  const resolved = useCallback(() => resolveAll(readLocal(index), yamlRef.current), [index]);

  useEffect(() => {
    if (!view || !alive(view)) {
      setOpenTypes((prev) => (prev.length ? [] : prev));
      return undefined;
    }
    baselines.current = new WeakMap();
    let seen = new Set<string>();
    let dispose: (() => void) | undefined;
    // Not before the view has measured itself: a setting applied earlier wakes
    // JBrowse reactions that read `width` and throw ("check model.initialized").
    const ready = when(
      () => !alive(view) || (view as { initialized?: boolean }).initialized !== false,
      () => {
        if (!alive(view)) return;
        applyAll(view, resolved(), { baselines: baselines.current });
        seen = new Set(displayKeys(view));
        setOpenTypes(openDisplayTypes(view));
        dispose = watch();
      },
    );
    const watch = () => reaction(
      () => (alive(view) ? displayKeys(view) : []),
      (keys) => {
        if (!alive(view)) return;
        const fresh = new Set(keys.filter((k) => !seen.has(k)));
        seen = new Set(keys);
        if (fresh.size) applyAll(view, resolved(), { baselines: baselines.current, only: fresh });
        const types = openDisplayTypes(view);
        setOpenTypes((prev) => (sameList(prev, types) ? prev : types));
      },
      { equals: comparer.shallow },
    );
    return () => {
      ready();
      dispose?.();
    };
  }, [view, resolved, yamlSig]);

  const set = useCallback(
    (key: DisplaySettingKey, value: DisplaySettingValue) => {
      const entry = entryFor(key);
      if (!entry) return;
      writeLocal(index, key, storable(entry, value));
      if (view && alive(view)) {
        const all = resolved();
        if (all[key] !== undefined) applyOne(view, key, all, { baselines: baselines.current });
        else restoreBaseline(view, entry, baselines.current, all);
      }
      setVersion((v) => v + 1);
    },
    [view, index, resolved],
  );

  const reset = useCallback(() => {
    for (const entry of DISPLAY_SETTINGS) writeLocal(index, entry.key, undefined);
    if (view && alive(view)) {
      const all = resolved();
      applyAll(view, all, { baselines: baselines.current });
      for (const entry of DISPLAY_SETTINGS) {
        if (all[entry.key] === undefined) restoreBaseline(view, entry, baselines.current, all);
      }
    }
    setVersion((v) => v + 1);
  }, [view, index, resolved]);

  return useMemo<DisplaySettingsApi>(() => {
    const local = readLocal(index);
    const value = (key: DisplaySettingKey): DisplaySettingValue | undefined => {
      const entry = entryFor(key);
      if (!entry) return undefined;
      const chosen = resolveValue(key, local, yamlRef.current) ?? entry.builtin;
      if (chosen !== undefined) return chosen;
      // Nothing says: show what the first matching display is doing.
      if (!view || !alive(view)) return undefined;
      try {
        const node = displaysOf(view, entry)[0];
        return node ? entry.read(node) : undefined;
      } catch {
        return undefined;
      }
    };
    return {
      groups: groupsFor(openTypes),
      openDisplayTypes: openTypes,
      tracksIn: (group) => (view && alive(view) ? groupTrackNames(view, group) : []),
      value,
      set,
      reset,
      modified: Object.keys(local).length > 0,
    };
    // `version` re-reads the stored choices after a set or a reset.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view, index, openTypes, set, reset, version, yamlSig]);
}
