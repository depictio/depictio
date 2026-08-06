import { useEffect, useMemo, useState } from 'react';

import { fetchSpecs, fetchUniqueValues, type StoredMetadata } from '../api';
import { stableColorMap } from '../colors';
import type { ColorByState } from '../selectionGroups';

/**
 * Categorical-column discovery for the dashboard-global "Color by" control.
 *
 * Columns come from the precomputed per-DC specs (no Delta scan): a column is
 * offered when its type is categorical and its cardinality is small enough to
 * color by. The list is the union across every data-bearing DC on the
 * dashboard; the server applies the override per component only when that
 * component's frame actually carries the column.
 */

const CATEGORICAL_TYPES = new Set(['object', 'string', 'category', 'bool', 'utf8']);

/** Cardinality ceiling: beyond this a discrete legend is unreadable and the
 *  palette wraps anyway. Keeps id-like columns out of the select. */
const MAX_COLOR_BY_CARDINALITY = 50;

export interface ColorByColumn {
  name: string;
  /** Every DC on the dashboard that carries the column. */
  dcIds: string[];
}

interface SpecsEntry {
  name?: string;
  type?: string;
  specs?: { nunique?: number };
}

// Specs never change within a session (they're ingest-time aggregates), so a
// module-level cache keeps one request per DC across rerenders and both roots.
const specsCache = new Map<string, Promise<SpecsEntry[]>>();

function fetchSpecsCached(dcId: string): Promise<SpecsEntry[]> {
  let pending = specsCache.get(dcId);
  if (!pending) {
    pending = fetchSpecs(dcId)
      .then((specs) => (Array.isArray(specs) ? (specs as SpecsEntry[]) : []))
      .catch(() => {
        specsCache.delete(dcId);
        return [] as SpecsEntry[];
      });
    specsCache.set(dcId, pending);
  }
  return pending;
}

const DATA_COMPONENT_TYPES = new Set(['figure', 'table', 'multiqc', 'map', 'image', 'card']);

/** Distinct data-bearing dc_ids on the dashboard (same walk as the
 *  available-values provider). */
function collectDcIds(metadataList: StoredMetadata[] | undefined): string[] {
  const seen = new Set<string>();
  for (const m of metadataList ?? []) {
    if (m.dc_id && DATA_COMPONENT_TYPES.has(m.component_type ?? '')) seen.add(m.dc_id);
  }
  return Array.from(seen);
}

export function useCategoricalColumns(
  metadataList: StoredMetadata[] | undefined,
): ColorByColumn[] {
  const dcIds = useMemo(() => collectDcIds(metadataList), [metadataList]);
  const dcKey = dcIds.join('|');
  const [columns, setColumns] = useState<ColorByColumn[]>([]);

  useEffect(() => {
    let cancelled = false;
    if (dcIds.length === 0) {
      setColumns([]);
      return;
    }
    Promise.all(dcIds.map((dcId) => fetchSpecsCached(dcId).then((s) => [dcId, s] as const))).then(
      (perDc) => {
        if (cancelled) return;
        const byName = new Map<string, ColorByColumn>();
        for (const [dcId, entries] of perDc) {
          for (const e of entries) {
            if (!e?.name || !e.type) continue;
            const type = e.type.toLowerCase();
            if (!CATEGORICAL_TYPES.has(type)) continue;
            // Specs only record nunique for object-like types (see
            // agg_functions card_methods) — bool/category never carry it, but
            // they are categorical by construction, so a missing count is
            // acceptable for them rather than a silent exclusion.
            const nunique = e.specs?.nunique;
            if (typeof nunique === 'number') {
              if (nunique < 1 || nunique > MAX_COLOR_BY_CARDINALITY) continue;
            } else if (type !== 'bool' && type !== 'category') {
              continue;
            }
            const existing = byName.get(e.name);
            if (existing) existing.dcIds.push(dcId);
            else byName.set(e.name, { name: e.name, dcIds: [dcId] });
          }
        }
        setColumns(Array.from(byName.values()).sort((a, b) => a.name.localeCompare(b.name)));
      },
    );
    return () => {
      cancelled = true;
    };
    // dcKey is the stable identity of dcIds.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dcKey]);

  return columns;
}

export interface ColorByColumnRender {
  columnName: string;
  colorMap?: Record<string, string>;
}

/**
 * Resolve the active column-mode "Color by" into a render payload: the stable
 * color map is built from the column's *unfiltered* universe so category
 * colors don't shift as filters narrow the data.
 */
export function useColorByColumnRender(
  colorBy: ColorByState,
  columns: ColorByColumn[],
): ColorByColumnRender | undefined {
  const columnName = colorBy.kind === 'column' ? colorBy.columnName : null;
  const dcId = useMemo(() => {
    if (!columnName) return null;
    return columns.find((c) => c.name === columnName)?.dcIds[0] ?? null;
  }, [columnName, columns]);

  const [render, setRender] = useState<ColorByColumnRender | undefined>(undefined);

  useEffect(() => {
    let cancelled = false;
    if (!columnName) {
      setRender(undefined);
      return;
    }
    // Column selected but universe still unknown: color without a map rather
    // than blocking the recolor on the values request.
    setRender({ columnName });
    if (!dcId) return;
    fetchUniqueValues(dcId, columnName)
      .then((values) => {
        if (cancelled || values.length === 0) return;
        const stable = stableColorMap(values);
        setRender({
          columnName,
          colorMap: Object.fromEntries(stable.universe.map((v) => [v, stable.get(v)])),
        });
      })
      .catch(() => {
        // Keep the mapless render; server-side px defaults still apply.
      });
    return () => {
      cancelled = true;
    };
  }, [columnName, dcId]);

  return render;
}
