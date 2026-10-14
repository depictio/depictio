/**
 * The structure behind a ramachandran tile, found the way molecule_3d finds
 * its own: the bound residue table gives the entities and the colouring rows,
 * an indexed_file collection (`file`) or the structure resolver (`resolve`)
 * gives the model, and the text of the model comes through the same per-object
 * cache, so a molecule_3d tile and this one on the same protein share one
 * download.
 *
 * The entity shown is chosen exactly as molecule_3d chooses it (a dashboard
 * filter, the reader's pick, the dashboard's agreed opening entity, the entity
 * with the most rows that has a structure), so the two tiles open on the same
 * protein. Composed here rather than copied out of `Molecule3DRenderer`; a
 * candidate to promote into `molecule/hooks.ts` for both renderers to share.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';

import { fetchAdvancedVizData, type InteractiveFilter } from '../../../api';
import { useSharedOpeningEntity } from '../../../highlight/openingEntity';
import { residueEntityFromFilters } from '../../../selection';
import {
  errorMessage,
  useIndexedManifest,
  useResolvedStructure,
  useStructureText,
  type IndexedManifest,
} from '../molecule/hooks';
import {
  chooseEntity,
  columnsToFetch,
  distinctEntities,
  filtersForMoleculeFetch,
  parseResidueRows,
  resolverQuery,
  rowsForEntity,
  type ResidueColumns,
  type ResidueRow,
} from '../molecule/residueData';
import type { ResolveOrigin } from '../molecule/resolve';
import type { LoadedStructure } from '../molecule/structureText';
import { withoutOwnChainPick } from '../protein/rendererData';

export interface StructureSourceArgs {
  /** The bound residue table. */
  wfId: string | undefined;
  dcId: string | undefined;
  /** The tile's index: its own residue and chain picks never narrow its fetch. */
  index: string;
  filters: InteractiveFilter[];
  refreshTick?: number;
  fileMode: boolean;
  /** The indexed_file collection of structure files (`file` mode). */
  structureDcId: string | null | undefined;
  cols: ResidueColumns;
  taxon: number;
  /** The entity the reader picked in the tile. */
  pickedEntity: string | null;
}

export interface StructureSource {
  /** The bound table's rows, column-oriented, for the data popover. */
  frame: Record<string, unknown[]> | null;
  fetchCols: string[];
  /** The entity on screen, null until the table and the file list are in. */
  entity: string | null;
  /** The one entity the dashboard filters name, whether or not it has a structure. */
  fromFilters: string | null;
  /** Entities the tile can show (files in `file` mode, table entities in `resolve`). */
  available: string[];
  /** The rows of the entity on screen. */
  entityRows: ResidueRow[];
  /** Every parsed row, for colours that must not change with the entity. */
  rows: ResidueRow[];
  structure: { data: LoadedStructure | null; loading: boolean; error: string | null };
  /** Where a resolved model came from. */
  origin: ResolveOrigin | null;
  /** The accession a resolved model was found under. */
  accession: string | null;
  loading: boolean;
  /** An explained state rather than a failure: nothing to draw, and why. */
  emptyMessage: string | undefined;
  /** A failure to report. */
  error: string | null;
}

/** The molecule_3d tile's messages, so the two read alike. */
export const NO_STRUCTURE_BOUND = 'No structure collection is bound to this tile';

export function useStructureSource(args: StructureSourceArgs): StructureSource {
  const { wfId, dcId, index, filters, refreshTick, fileMode, structureDcId, cols, taxon } = args;
  const entityCol = cols.entity ?? null;
  const positionCol = cols.position || 'position';
  const hasTable = Boolean(wfId && dcId);

  // ---- The bound table ------------------------------------------------------------
  const fetchCols = useMemo(() => columnsToFetch(cols), [cols]);
  const emphasisCols = useMemo(() => [positionCol], [positionCol]);
  const filtersForFetch = useMemo(
    () => filtersForMoleculeFetch(withoutOwnChainPick(filters, index), index, emphasisCols),
    [filters, index, emphasisCols],
  );

  const [frame, setFrame] = useState<Record<string, unknown[]> | null>(null);
  const [rowsLoading, setRowsLoading] = useState(hasTable);
  const [rowsError, setRowsError] = useState<string | null>(null);
  useEffect(() => {
    if (!wfId || !dcId) {
      setFrame(null);
      setRowsLoading(false);
      return undefined;
    }
    let cancelled = false;
    setRowsLoading(true);
    setRowsError(null);
    fetchAdvancedVizData({
      wfId,
      dcId,
      columns: fetchCols,
      filters: filtersForFetch,
      vizKind: 'ramachandran',
      roles: { position: positionCol },
    })
      .then((res) => {
        if (!cancelled) setFrame(res.rows);
      })
      .catch((err: unknown) => {
        if (!cancelled) setRowsError(errorMessage(err));
      })
      .finally(() => {
        if (!cancelled) setRowsLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // The JSON keys stand for the arrays' content.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wfId, dcId, JSON.stringify(fetchCols), JSON.stringify(filtersForFetch), positionCol, refreshTick]);

  const rows = useMemo(() => parseResidueRows(frame, cols), [frame, cols]);
  const hasEntityColumn = useMemo(() => rows.some((r) => r.entity !== null), [rows]);
  const rowEntities = useMemo(() => distinctEntities(rows), [rows]);

  // ---- The entity -----------------------------------------------------------------
  const manifest: IndexedManifest = useIndexedManifest(structureDcId, fileMode, refreshTick);
  const available = useMemo(
    () => (fileMode ? Array.from(manifest.data?.keys() ?? []) : rowEntities),
    [fileMode, manifest.data, rowEntities],
  );
  const fromFilters = useMemo(
    () => residueEntityFromFilters(filters, entityCol),
    [filters, entityCol],
  );
  // What this tile would open on by itself once its rows and its file list are
  // in, agreed with the dashboard's other protein tiles under the entity column
  // name. A filter or the reader's pick still wins.
  const openingReady = !rowsLoading && (!fileMode || !manifest.loading);
  const ownOpening = useMemo(
    () =>
      openingReady
        ? chooseEntity({ fromFilters: null, picked: null, rowEntities, available })
        : null,
    [openingReady, rowEntities, available],
  );
  const opening = useSharedOpeningEntity(
    entityCol,
    index,
    ownOpening,
    openingReady ? available : null,
  );
  const entity = chooseEntity({
    fromFilters,
    picked: args.pickedEntity,
    rowEntities,
    available,
    opening,
  });
  // A dashboard filter naming an entity with no structure must not silently
  // show another protein instead.
  const missingEntity =
    fromFilters !== null && available.length > 0 && !available.includes(fromFilters)
      ? fromFilters
      : null;
  const entityRows = useMemo(
    () => rowsForEntity(rows, entity, hasEntityColumn),
    [rows, entity, hasEntityColumn],
  );

  // ---- The model ------------------------------------------------------------------
  const ask = useMemo(() => {
    if (fileMode) return null;
    const q = resolverQuery(entityRows);
    return q ? { ...q, taxon } : null;
  }, [fileMode, entityRows, taxon]);
  const resolved = useResolvedStructure(ask, !fileMode);

  const fileEntry = fileMode && entity ? (manifest.data?.get(entity) ?? null) : null;
  const structureUrl = (fileMode ? fileEntry?.url : resolved.data?.url) ?? null;
  // A file's presigned URL expires: a refused download re-reads the manifest.
  const { reload: reloadManifest } = manifest;
  const renewFileUrl = useCallback(
    async () => (entity ? ((await reloadManifest())?.get(entity)?.url ?? null) : null),
    [reloadManifest, entity],
  );
  const structure = useStructureText(
    structureUrl,
    fileMode ? (fileEntry?.name ?? null) : 'model.pdb',
    fileMode ? renewFileUrl : undefined,
  );

  // ---- What to say ----------------------------------------------------------------
  const loading =
    !structure.data &&
    (rowsLoading ||
      (fileMode && manifest.loading) ||
      (!fileMode && resolved.loading) ||
      structure.loading);

  let emptyMessage: string | undefined;
  let error: string | null = null;
  if (fileMode && !structureDcId) {
    emptyMessage = NO_STRUCTURE_BOUND;
  } else if (rowsError) {
    error = rowsError;
  } else if (fileMode && manifest.error) {
    error = manifest.error;
  } else if (missingEntity) {
    emptyMessage = `No structure file for ${missingEntity}`;
  } else if (fileMode && manifest.data && available.length === 0) {
    emptyMessage = 'No structure files in the bound collection';
  } else if (!fileMode && !rowsLoading && ask === null) {
    emptyMessage = 'No UniProt accession, gene or sequence to look a structure up with';
  } else if (!fileMode && resolved.error) {
    // Disabled resolver, sign-in needed, nothing found, unreadable id: a state
    // to explain, not a failure to report.
    if (resolved.refusal && resolved.refusal !== 'upstream') emptyMessage = resolved.error;
    else error = resolved.error;
  } else if (structure.error) {
    error = structure.error;
  }

  return {
    frame,
    fetchCols,
    entity,
    fromFilters,
    available,
    entityRows,
    rows,
    structure,
    origin: fileMode ? null : (resolved.data?.origin ?? null),
    accession: fileMode ? null : (resolved.data?.accession ?? null),
    loading,
    emptyMessage,
    error,
  };
}
