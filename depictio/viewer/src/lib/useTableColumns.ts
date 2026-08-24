import { useCallback, useEffect, useMemo, useState } from 'react';

/** Definition of one selectable table column. */
export interface ColumnDef<K extends string> {
  key: K;
  /** Header text. */
  label: string;
  /** Longer name used in the column picker when `label` is an abbreviation. */
  description?: string;
  /** Columns the user cannot hide (e.g. the entity's name). */
  alwaysVisible?: boolean;
  /** Shown by default on a fresh browser. Ignored when `alwaysVisible`. */
  defaultVisible?: boolean;
}

export interface UseTableColumnsResult<K extends string> {
  /** Columns to render, in definition order, honoring the user's selection. */
  visibleColumns: ColumnDef<K>[];
  /** Membership test for the render path. */
  isVisible: (key: K) => boolean;
  /** All columns, for the picker UI. */
  allColumns: ColumnDef<K>[];
  toggle: (key: K) => void;
  reset: () => void;
  /** True when the current selection differs from the defaults. */
  isCustomized: boolean;
}

function defaultKeys<K extends string>(columns: ColumnDef<K>[]): K[] {
  return columns.filter((c) => c.alwaysVisible || c.defaultVisible !== false).map((c) => c.key);
}

/**
 * Persisted per-table column visibility.
 *
 * Selections live in `localStorage` under `storageKey` so a user's choice of
 * columns survives reloads. Unknown keys from an older build are dropped on
 * load, and `alwaysVisible` columns can never be turned off.
 */
export function useTableColumns<K extends string>(
  storageKey: string,
  columns: ColumnDef<K>[],
): UseTableColumnsResult<K> {
  const defaults = useMemo(() => defaultKeys(columns), [columns]);

  const [selected, setSelected] = useState<K[]>(() => {
    try {
      const raw = localStorage.getItem(storageKey);
      if (!raw) return defaults;
      const parsed = JSON.parse(raw);
      if (!Array.isArray(parsed)) return defaults;
      const known = new Set(columns.map((c) => c.key));
      const kept = parsed.filter((k): k is K => typeof k === 'string' && known.has(k as K));
      // An empty/garbage selection would render a table with no columns —
      // fall back to defaults rather than showing an unusable grid.
      return kept.length > 0 ? kept : defaults;
    } catch {
      return defaults;
    }
  });

  useEffect(() => {
    try {
      localStorage.setItem(storageKey, JSON.stringify(selected));
    } catch {
      /* quota or private mode — selection stays in-memory only */
    }
  }, [storageKey, selected]);

  const selectedSet = useMemo(() => new Set<K>(selected), [selected]);

  const isVisible = useCallback(
    (key: K) => {
      const def = columns.find((c) => c.key === key);
      return Boolean(def?.alwaysVisible) || selectedSet.has(key);
    },
    [columns, selectedSet],
  );

  const visibleColumns = useMemo(
    () => columns.filter((c) => c.alwaysVisible || selectedSet.has(c.key)),
    [columns, selectedSet],
  );

  const toggle = useCallback(
    (key: K) => {
      const def = columns.find((c) => c.key === key);
      if (def?.alwaysVisible) return;
      setSelected((prev) =>
        prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key],
      );
    },
    [columns],
  );

  const reset = useCallback(() => setSelected(defaults), [defaults]);

  const isCustomized = useMemo(() => {
    if (selected.length !== defaults.length) return true;
    const d = new Set(defaults);
    return selected.some((k) => !d.has(k));
  }, [selected, defaults]);

  return { visibleColumns, isVisible, allColumns: columns, toggle, reset, isCustomized };
}
