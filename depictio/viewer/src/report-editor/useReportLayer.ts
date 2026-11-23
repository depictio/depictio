import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ReportLayerConflict,
  fetchReportLayer,
  fetchReportOutline,
  saveReportLayer,
} from 'depictio-react-core';
import type { ReportLayer, ReportLayerConflictDetail, ReportOutline } from 'depictio-react-core';

export type ReportSaveStatus = 'idle' | 'saving' | 'saved' | 'error' | 'conflict';

const AUTOSAVE_DEBOUNCE_MS = 800;

export interface ReportLayerApi {
  layer: ReportLayer | null;
  outline: ReportOutline | null;
  loading: boolean;
  /** Why the page could not load, or null. */
  loadError: string | null;
  saveStatus: ReportSaveStatus;
  saveError: string | null;
  conflict: ReportLayerConflictDetail | null;
  /** Bumped by every reload: editors keyed on it remount with the new content. */
  epoch: number;
  /** Apply an edit. Every edit handler goes through here; it is the only way the
   *  layer is changed and the only thing that arms the autosave. */
  edit: (change: (layer: ReportLayer) => ReportLayer) => void;
  /** Write any pending edit now. Resolves once nothing is pending. */
  flush: () => Promise<void>;
  /** Drop local state and read the layer and the outline again. */
  reload: () => void;
}

/**
 * The report layer of one dashboard: loaded with its outline, edited locally,
 * saved 800 ms after the last edit.
 *
 * Nothing is written before the user acts. The layer only changes through
 * `edit`, which sets `userActedRef`; loading, a reload and the editors'
 * own normalisation on mount never reach it, so opening a report cannot bump
 * its revision. A 409 stops the autosave until the page is reloaded.
 */
export function useReportLayer(dashboardId: string): ReportLayerApi {
  const [layer, setLayer] = useState<ReportLayer | null>(null);
  const [outline, setOutline] = useState<ReportOutline | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saveStatus, setSaveStatus] = useState<ReportSaveStatus>('idle');
  const [saveError, setSaveError] = useState<string | null>(null);
  const [conflict, setConflict] = useState<ReportLayerConflictDetail | null>(null);
  const [epoch, setEpoch] = useState(0);

  const layerRef = useRef<ReportLayer | null>(null);
  const revisionRef = useRef(0);
  const userActedRef = useRef(false);
  const dirtyRef = useRef(false);
  const conflictRef = useRef(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const inflightRef = useRef<Promise<void> | null>(null);

  const clearTimer = () => {
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = null;
  };

  const refreshOutline = useCallback(async () => {
    try {
      setOutline(await fetchReportOutline(dashboardId));
    } catch {
      // The outline on screen stays; the next save tries again.
    }
  }, [dashboardId]);

  const save = useCallback(async (): Promise<void> => {
    if (inflightRef.current) {
      await inflightRef.current;
    }
    const current = layerRef.current;
    if (!current || !dirtyRef.current || !userActedRef.current || conflictRef.current) return;
    dirtyRef.current = false;
    setSaveStatus('saving');
    setSaveError(null);
    const run = (async () => {
      try {
        const stored = await saveReportLayer(dashboardId, revisionRef.current, current);
        revisionRef.current = stored.revision;
        // Keep what is on screen (the user may have typed since): only the
        // server's bookkeeping comes back.
        const latest = layerRef.current ?? current;
        const merged: ReportLayer = {
          ...latest,
          revision: stored.revision,
          updated_by: stored.updated_by,
          updated_at: stored.updated_at,
        };
        layerRef.current = merged;
        setLayer(merged);
        if (!dirtyRef.current) setSaveStatus('saved');
        void refreshOutline();
      } catch (err) {
        if (err instanceof ReportLayerConflict) {
          conflictRef.current = true;
          clearTimer();
          setConflict(err.detail);
          setSaveStatus('conflict');
        } else {
          dirtyRef.current = true;
          setSaveStatus('error');
          setSaveError(err instanceof Error ? err.message : String(err));
        }
      }
    })();
    inflightRef.current = run;
    try {
      await run;
    } finally {
      if (inflightRef.current === run) inflightRef.current = null;
    }
  }, [dashboardId, refreshOutline]);

  const schedule = useCallback(() => {
    clearTimer();
    timerRef.current = setTimeout(() => {
      timerRef.current = null;
      void save();
    }, AUTOSAVE_DEBOUNCE_MS);
  }, [save]);

  const edit = useCallback(
    (change: (layer: ReportLayer) => ReportLayer) => {
      const current = layerRef.current;
      if (!current || conflictRef.current) return;
      userActedRef.current = true;
      dirtyRef.current = true;
      const next = change(current);
      if (next === current) {
        dirtyRef.current = false;
        return;
      }
      layerRef.current = next;
      setLayer(next);
      setSaveStatus('saving');
      schedule();
    },
    [schedule],
  );

  const flush = useCallback(async () => {
    clearTimer();
    await save();
    if (inflightRef.current) await inflightRef.current;
  }, [save]);

  const load = useCallback(
    (signal: AbortSignal) => {
      setLoading(true);
      setLoadError(null);
      Promise.all([
        fetchReportLayer(dashboardId, signal),
        fetchReportOutline(dashboardId, signal),
      ])
        .then(([nextLayer, nextOutline]) => {
          if (signal.aborted) return;
          clearTimer();
          userActedRef.current = false;
          dirtyRef.current = false;
          conflictRef.current = false;
          revisionRef.current = nextLayer.revision;
          layerRef.current = nextLayer;
          setLayer(nextLayer);
          setOutline(nextOutline);
          setConflict(null);
          setSaveStatus('idle');
          setSaveError(null);
          setEpoch((e) => e + 1);
          setLoading(false);
        })
        .catch((err) => {
          if (signal.aborted) return;
          setLoadError(err instanceof Error ? err.message : String(err));
          setLoading(false);
        });
    },
    [dashboardId],
  );

  const controllerRef = useRef<AbortController | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    controllerRef.current = controller;
    load(controller.signal);
    return () => {
      controller.abort();
      clearTimer();
    };
  }, [load]);

  const reload = useCallback(() => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    load(controller.signal);
  }, [load]);

  return {
    layer,
    outline,
    loading,
    loadError,
    saveStatus,
    saveError,
    conflict,
    epoch,
    edit,
    flush,
    reload,
  };
}
