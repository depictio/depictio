/**
 * Data hooks of the molecule_3d tile: is 3Dmol available here, which
 * structure objects does the indexed_file DC hold, what does the resolver
 * answer, and the structure text itself (cached per object).
 */

import { useCallback, useEffect, useRef, useState, type RefCallback } from 'react';

import { authFetch, fetchAdvancedVizData, type InteractiveFilter } from '../../../api';
import { parseChainLayout } from '../protein/alignment';
import type { ChainSegment, MsaRow } from '../protein/types';
import type { IndexedFileEntry } from '../genomespy/fileSpec';
import { ResolveError, resolveStructure, type ResolvedStructure } from './resolve';
import {
  loadStructureTextRenewing,
  structureCacheKey,
  type LoadedStructure,
} from './structureText';

/** Message of the catalog preview's 3dmol stub; shown as the empty state. */
export const PREVIEW_UNAVAILABLE = '3D preview unavailable in the catalog';

export type ThreeDmolStatus = 'loading' | 'ready' | 'unavailable';

/**
 * Whether the real 3Dmol.js is behind `import('3dmol')`.
 *
 * The catalog preview aliases the module to a stub (it flags itself with
 * `CATALOG_PREVIEW_STUB`); probing it first means the tile says so at once
 * instead of fetching a structure it can never draw.
 */
export function useThreeDmolStatus(): ThreeDmolStatus {
  const [status, setStatus] = useState<ThreeDmolStatus>('loading');
  useEffect(() => {
    let cancelled = false;
    import('3dmol')
      .then((mod) => {
        if (cancelled) return;
        const stub = (mod as unknown as { CATALOG_PREVIEW_STUB?: boolean }).CATALOG_PREVIEW_STUB;
        setStatus(stub ? 'unavailable' : 'ready');
      })
      .catch(() => {
        if (!cancelled) setStatus('unavailable');
      });
    return () => {
      cancelled = true;
    };
  }, []);
  return status;
}

interface Async<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
}

export function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/** First structure object per sample of an indexed_file DC. */
async function readManifest(dcId: string): Promise<Map<string, IndexedFileEntry>> {
  const res = await authFetch(`/depictio/api/v1/files/indexed/${dcId}`);
  if (!res.ok) throw new Error(`Structure files unavailable (${res.status})`);
  const body = (await res.json()) as { files?: IndexedFileEntry[] };
  const bySample = new Map<string, IndexedFileEntry>();
  for (const f of body.files ?? []) {
    if (f.sample && !bySample.has(f.sample)) bySample.set(f.sample, f);
  }
  return bySample;
}

export type StructureManifest = Async<Map<string, IndexedFileEntry>> & {
  /** Re-read the manifest (new presigned URLs); resolves to the new map, or
   *  null when it failed or the tile moved to another collection meanwhile. */
  reload: () => Promise<Map<string, IndexedFileEntry> | null>;
};

/**
 * One structure object per entity, from `GET /files/indexed/{dc_id}`.
 *
 * The URLs are presigned and expire (15 minutes), so the manifest is re-read
 * on the refresh tick and on demand (`reload`, when a download is refused);
 * the structure text itself is cached by object path and is not downloaded
 * again.
 */
export function useStructureManifest(
  dcId: string | null | undefined,
  enabled: boolean,
  refreshTick?: number,
): StructureManifest {
  const [state, setState] = useState<Async<Map<string, IndexedFileEntry>>>({
    data: null,
    loading: enabled && Boolean(dcId),
    error: null,
  });
  const current = useRef({ dcId, enabled });
  current.current = { dcId, enabled };
  useEffect(() => {
    if (!enabled) return undefined;
    if (!dcId) {
      setState({ data: null, loading: false, error: 'No structure collection is bound to this tile' });
      return undefined;
    }
    let cancelled = false;
    setState((s) => ({ ...s, loading: true, error: null }));
    readManifest(dcId)
      .then((bySample) => {
        if (!cancelled) setState({ data: bySample, loading: false, error: null });
      })
      .catch((err: unknown) => {
        if (!cancelled) setState({ data: null, loading: false, error: errorMessage(err) });
      });
    return () => {
      cancelled = true;
    };
  }, [dcId, enabled, refreshTick]);
  // The URLs in hand stay up while the manifest is re-read: no loading state.
  const reload = useCallback(async () => {
    const { dcId: id, enabled: on } = current.current;
    if (!id || !on) return null;
    try {
      const bySample = await readManifest(id);
      if (current.current.dcId !== id) return null;
      setState({ data: bySample, loading: false, error: null });
      return bySample;
    } catch {
      return null;
    }
  }, []);
  return { ...state, reload };
}

export interface ResolverAsk {
  uniprot: string | null;
  gene: string | null;
  sequence: string | null;
  taxon: number;
}

type Resolved = Async<ResolvedStructure> & { refusal: ResolveError['kind'] | null };

/** The resolver's answer for one entity, with its refusals as messages. */
export function useResolvedStructure(ask: ResolverAsk | null, enabled: boolean): Resolved {
  const [state, setState] = useState<Resolved>({
    data: null,
    loading: false,
    error: null,
    refusal: null,
  });
  const key = ask ? JSON.stringify(ask) : '';
  useEffect(() => {
    if (!enabled || !ask) {
      setState({ data: null, loading: false, error: null, refusal: null });
      return undefined;
    }
    let cancelled = false;
    // The previous model stays up while the next one resolves, so the viewer
    // is reused rather than torn down and rebuilt.
    setState((s) => ({ ...s, loading: true, error: null, refusal: null }));
    resolveStructure(ask)
      .then((data) => {
        if (!cancelled) setState({ data, loading: false, error: null, refusal: null });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setState({
          data: null,
          loading: false,
          error: errorMessage(err),
          refusal: err instanceof ResolveError ? err.kind : null,
        });
      });
    return () => {
      cancelled = true;
    };
    // `key` carries `ask`'s content.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, enabled]);
  return state;
}

/**
 * The structure text behind a URL, from the per-object cache.
 *
 * `renew` gives a fresh URL for the same object (a manifest re-read): a
 * download refused with 403, the mark of an expired presigned URL, is retried
 * once through it. Once per object until it loads, so an object the store
 * really refuses ends in an error, not in a loop of re-reads.
 */
export function useStructureText(
  url: string | null,
  nameHint: string | null,
  renew?: () => Promise<string | null>,
): Async<LoadedStructure> {
  const [state, setState] = useState<Async<LoadedStructure>>({
    data: null,
    loading: Boolean(url),
    error: null,
  });
  // A new presigned URL for the same object must not blank the tile: the
  // cache answers at once, and the previous text stays up meanwhile.
  const last = useRef<LoadedStructure | null>(null);
  const renewRef = useRef(renew);
  renewRef.current = renew;
  const renewedFor = useRef<string | null>(null);
  useEffect(() => {
    if (!url) {
      last.current = null;
      setState({ data: null, loading: false, error: null });
      return undefined;
    }
    let cancelled = false;
    setState({ data: last.current, loading: true, error: null });
    const key = structureCacheKey(url);
    const canRenew = Boolean(renewRef.current) && renewedFor.current !== key;
    loadStructureTextRenewing(url, {
      nameHint,
      renew: canRenew
        ? () => {
            renewedFor.current = key;
            return renewRef.current?.() ?? Promise.resolve(null);
          }
        : null,
    })
      .then((data) => {
        if (renewedFor.current === key) renewedFor.current = null;
        if (cancelled) return;
        last.current = data;
        setState({ data, loading: false, error: null });
      })
      .catch((err: unknown) => {
        if (!cancelled) setState({ data: null, loading: false, error: errorMessage(err) });
      });
    return () => {
      cancelled = true;
    };
  }, [url, nameHint]);
  return state;
}

/** Content-box size of an element, tracked with a ResizeObserver. */
export function useElementSize<T extends HTMLElement>(): [
  RefCallback<T>,
  { width: number; height: number },
] {
  const [size, setSize] = useState({ width: 0, height: 0 });
  const observer = useRef<ResizeObserver | null>(null);
  const ref = useCallback((node: T | null) => {
    observer.current?.disconnect();
    observer.current = null;
    if (!node || typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver((entries) => {
      const r = entries[0]?.contentRect;
      if (r) {
        setSize((prev) =>
          Math.round(prev.width) === Math.round(r.width) &&
          Math.round(prev.height) === Math.round(r.height)
            ? prev
            : { width: r.width, height: r.height },
        );
      }
    });
    ro.observe(node);
    observer.current = ro;
  }, []);
  return [ref, size];
}

/** Canonical MSA table columns (contract: `MsaConfig` defaults). The
 *  molecule_3d config names the MSA collection only, not its columns. */
const MSA_COLUMNS = {
  msaId: 'msa_id',
  seqId: 'seq_id',
  sequence: 'aligned_sequence',
  rank: 'rank',
  identity: 'identity',
  coverage: 'coverage',
  /** Chain layout of a complex's reference row (`MsaConfig.chains_col` default). */
  chains: 'chains',
} as const;

/** Rows read from an MSA table the tile cannot scope to one alignment (no
 *  entity on screen): enough for the panel, never the whole table. */
const MSA_UNSCOPED_ROW_CAP = 500;

/** One alignment and, for a complex, the chain layout of its reference row. */
export interface MsaRows {
  rows: MsaRow[];
  chains: ChainSegment[] | null;
}

/** Rows of the alignment of one entity, for the `structure_msa` layout. The
 *  `msa_id` filter is applied server-side, so only that alignment travels.
 *  With no entity to scope to, the first rows are read (capped) and the first
 *  alignment among them is drawn. */
export function useMsaRows(args: {
  wfId: string | null | undefined;
  dcId: string | null | undefined;
  msaId: string | null;
  enabled: boolean;
  refreshTick?: number;
}): Async<MsaRows> {
  const { wfId, dcId, msaId, enabled, refreshTick } = args;
  const [state, setState] = useState<Async<MsaRows>>({ data: null, loading: false, error: null });
  useEffect(() => {
    if (!enabled || !wfId || !dcId) {
      setState({ data: null, loading: false, error: null });
      return undefined;
    }
    let cancelled = false;
    setState((s) => ({ ...s, loading: true, error: null }));
    const filters: InteractiveFilter[] = msaId
      ? [
          {
            index: `molecule_3d_msa_${dcId}`,
            value: [msaId],
            column_name: MSA_COLUMNS.msaId,
            interactive_component_type: 'MultiSelect',
            metadata: {
              dc_id: dcId,
              column_name: MSA_COLUMNS.msaId,
              interactive_component_type: 'MultiSelect',
            },
          },
        ]
      : [];
    fetchAdvancedVizData({
      wfId,
      dcId,
      columns: Object.values(MSA_COLUMNS),
      filters,
      limitRows: msaId ? undefined : MSA_UNSCOPED_ROW_CAP,
      vizKind: 'msa',
      roles: { msa_id: MSA_COLUMNS.msaId, seq_id: MSA_COLUMNS.seqId, sequence: MSA_COLUMNS.sequence },
    })
      .then((res) => {
        if (cancelled) return;
        const cols = res.rows ?? {};
        const ids = (cols[MSA_COLUMNS.seqId] ?? []) as unknown[];
        const seqs = (cols[MSA_COLUMNS.sequence] ?? []) as unknown[];
        const ranks = (cols[MSA_COLUMNS.rank] ?? []) as unknown[];
        const idents = (cols[MSA_COLUMNS.identity] ?? []) as unknown[];
        const covs = (cols[MSA_COLUMNS.coverage] ?? []) as unknown[];
        const layouts = (cols[MSA_COLUMNS.chains] ?? []) as unknown[];
        const msaIds = (cols[MSA_COLUMNS.msaId] ?? []) as unknown[];
        // Unscoped, the rows may span alignments: draw the first one only.
        const firstMsa = msaId ? null : (msaIds.find((v) => v != null) ?? null);
        let chains: ChainSegment[] | null = null;
        const num = (v: unknown) => (v === null || v === undefined || v === '' ? null : Number(v));
        const rows: MsaRow[] = [];
        for (let i = 0; i < ids.length; i += 1) {
          if (ids[i] == null || seqs[i] == null) continue;
          if (firstMsa != null && String(msaIds[i]) !== String(firstMsa)) continue;
          if (!chains && layouts[i] != null) chains = parseChainLayout(String(layouts[i]));
          rows.push({
            seqId: String(ids[i]),
            sequence: String(seqs[i]),
            rank: num(ranks[i]),
            identity: num(idents[i]),
            coverage: num(covs[i]),
          });
        }
        // One chain is the single-chain case: nothing to translate.
        setState({
          data: { rows, chains: chains && chains.length > 1 ? chains : null },
          loading: false,
          error: null,
        });
      })
      .catch((err: unknown) => {
        if (!cancelled) setState({ data: null, loading: false, error: errorMessage(err) });
      });
    return () => {
      cancelled = true;
    };
  }, [wfId, dcId, msaId, enabled, refreshTick]);
  return state;
}
