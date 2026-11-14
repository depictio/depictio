/**
 * "Changed since your last visit" for the viewer (#1397): fetches the change
 * set once per open, holds it for the session, and hands it to the pill, the
 * panel and the marks on the canvas.
 *
 * It is always mounted, so the tree under it never remounts when the server
 * answers the feature flag; everything inside is gated on `active`. Off, in a
 * pinned `?version=` preview, or before the dashboard and the user are known,
 * it requests nothing and provides the empty marks.
 *
 * Who holds the mark:
 *  - a signed-in reader: the server (`server_held`), nothing is stored here;
 *  - an anonymous or temporary reader: this browser (`changesStore`). The
 *    server returns `current_baseline`; the stored baseline and dismissals go
 *    back in the request body.
 * The server decides, through `server_held`, not this component.
 *
 * Never mounted by the editor, and a read-only view (`?since=`/`?before_run=`)
 * never records a visit or a "seen".
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { notifications } from '@mantine/notifications';

import {
  ChangeMarksProviderBase,
  changeKey,
  fetchDashboardChanges,
  markDashboardSeen,
  mergeLocalDismissed,
  readLocalMode,
  readLocalReader,
  recordDashboardVisit,
  saveChangesPrefs,
  writeLocalBaseline,
  writeLocalMode,
} from 'depictio-react-core';
import type {
  ChangeMarksValue,
  ChangeReason,
  DashboardChangeSet,
  GroupRenderDef,
  InteractiveFilter,
  MarkMode,
  StoredMetadata,
} from 'depictio-react-core';

import { useChangesSinceEnabled } from '../hooks/useChangesSinceEnabled';
import CompareModal from './CompareModal';
import { ChangesSinceContext, type ChangesSinceValue } from './ChangesSinceContext';
import { dropCachedChangeSet, readCachedChangeSet, writeCachedChangeSet } from './changeSetCache';
import { useRunUnscopedDcs } from './runColumns';
import { isReadOnlyQuery, markDetails, parseReadOnlyQuery } from './describe';
import {
  focusedRuns,
  newSideOnly,
  newsSplitGroups,
  overlaySides,
  readSharedFocus,
  readSharedView,
  writeSharedFocus,
  writeSharedView,
  type NewsSplit,
  type NewsView,
} from './newsSplit';

/** How long a reader stays on the page before it counts as a visit. */
export const VISIT_DELAY_MS = 10_000;

interface Props {
  /** The tab on screen. */
  dashboardId: string | null;
  /** The family's main tab: the key of the stored mark. Unknown until the dashboard loads. */
  familyId: string | undefined;
  /** The dashboard's project, for links to its collections. */
  projectId?: string | null;
  /** `?version=` pinned preview: shows nothing, calls nothing. */
  previewVersionId: string | null;
  /** The signed-in user is still being resolved. */
  userLoading: boolean;
  /** Who reads, for the per-reader cache of the change set; null when anonymous. */
  readerId?: string | null;
  /** The reader may open the editor's History. */
  canEdit: boolean;
  /** The components of the tab (and what it shows from others): the side-by-side view draws one of them. */
  components?: StoredMetadata[];
  /** The filters the dashboard is drawn with, for the side-by-side panes. */
  filters?: InteractiveFilter[];
  /** The "Split" view: the virtual New / Seen before groups the dashboard
   *  draws its figures and cards with, or null to draw them as usual. */
  onSplitChange?: (split: NewsSplit | null) => void;
  children: React.ReactNode;
}

/** A colour of the dashboard's brand, as a hex the group payload accepts. */
function brandHex(variable: string, fallback: string): string {
  try {
    const el = document.querySelector('.depictio-dashboard-brand') ?? document.documentElement;
    const v = getComputedStyle(el).getPropertyValue(variable).trim();
    return /^#[0-9a-f]{6}$/i.test(v) ? v : fallback;
  } catch {
    return fallback;
  }
}

const EMPTY_MARKED: Record<string, ChangeReason[]> = {};
const NO_COMPARING: ReadonlySet<string> = new Set<string>();
const NO_SPLIT_BY_DC: Record<string, GroupRenderDef[]> = {};
const NO_DCS: ReadonlySet<string> = new Set<string>();
const NO_DIFF_QUERY: ChangeMarksValue['diffQuery'] = {};
const NO_COMPONENTS: StoredMetadata[] = [];
const NO_FILTERS: InteractiveFilter[] = [];

/** Component types that draw what is new in place when compared. Cards and
 *  tables have nothing to ring: their dot says it. */
const HIGHLIGHTABLE_TYPES = new Set(['figure', 'multiqc', 'advanced_viz']);
/** Drawn by run in the Overlay when their collection gained one, not ringed. */
const RUN_COLOURED_TYPES = new Set(['figure', 'advanced_viz']);
/** Advanced viz kinds with no marks to colour by run: they keep their ring. */
const KINDS_WITHOUT_RUN_MARKS = new Set(['record_card']);

/** The set after "Mark as seen": a previous visit exists, nothing differs. */
function clearedSet(cs: DashboardChangeSet): DashboardChangeSet {
  return {
    ...cs,
    approximate: false,
    data: [],
    failed_ingestions: [],
    dashboard: [],
    comments: [],
    changed_components: {},
  };
}

const NO_RUNS_BY_DC: Record<string, string[]> = {};

/** The runs each collection gained since the mark, for the tables' Overlay. */
function overlayRuns(cs: DashboardChangeSet): Record<string, string[]> {
  const out: Record<string, string[]> = {};
  for (const d of cs.data) {
    if (d.kind === 'refreshed' && d.new_run_tags.length > 0) out[d.dc_id] = d.new_run_tags;
  }
  return out;
}

const ChangeMarksProvider: React.FC<Props> = ({
  dashboardId,
  familyId,
  projectId,
  previewVersionId,
  userLoading,
  readerId,
  canEdit,
  components = NO_COMPONENTS,
  filters = NO_FILTERS,
  onSplitChange,
  children,
}) => {
  const flagOn = useChangesSinceEnabled();
  const readOnlyQuery = useMemo(() => parseReadOnlyQuery(window.location.search), []);
  const readOnly = isReadOnlyQuery(readOnlyQuery);
  const active = flagOn && !previewVersionId && Boolean(dashboardId) && Boolean(familyId) && !userLoading;

  const [changeSet, setChangeSet] = useState<DashboardChangeSet | null>(null);
  // The family whose set came from the server on this page, not the cache.
  const [fetchedFamily, setFetchedFamily] = useState<string | null>(null);
  const [mode, setModeState] = useState<MarkMode>('sticky');
  const [comparing, setComparing] = useState<ReadonlySet<string>>(NO_COMPARING);
  const [seenBusy, setSeenBusy] = useState(false);
  // The component whose Before | Now view is open (a change key), if any.
  const [compareKey, setCompareKey] = useState<string | null>(null);
  const modeRef = useRef(mode);
  modeRef.current = mode;
  const reader = readerId || 'anonymous';
  // The set painted from the cache: written back, it would renew its own age.
  const paintedFromCache = useRef<DashboardChangeSet | null>(null);

  // One fetch per open. `changeSet` is kept for the whole session: nothing
  // refetches it, so the marks do not shift under the reader. The previous
  // tab's read paints first (each tab is a page load) and the fetch replaces it.
  useEffect(() => {
    if (!active || !familyId) return;
    let cancelled = false;
    const local = readOnly ? null : readLocalReader(familyId);
    if (!readOnly) {
      const cached = readCachedChangeSet(reader, familyId);
      if (cached) {
        setModeState(cached.server_held ? cached.mark_mode : (readLocalMode() ?? cached.mark_mode));
        paintedFromCache.current = cached;
        setChangeSet(cached);
      }
    }
    fetchDashboardChanges(
      familyId,
      readOnly
        ? { since: readOnlyQuery.since, beforeRun: readOnlyQuery.beforeRun }
        : { baseline: local?.baseline ?? null, dismissed: local?.dismissed ?? null },
    )
      .then((cs) => {
        if (cancelled) return;
        if (!cs.server_held) {
          // A first visit: remember where this reader stands, now, so a visit
          // they leave before the debounce still has a baseline next time.
          if (!readOnly && !local?.baseline && cs.current_baseline) {
            writeLocalBaseline(familyId, cs.current_baseline);
          }
          setModeState(readLocalMode() ?? cs.mark_mode);
        } else {
          setModeState(cs.mark_mode);
        }
        setChangeSet(cs);
        setFetchedFamily(cs.family_id);
      })
      .catch(() => {
        // Decoration: a failed fetch leaves the dashboard as it was, minus a
        // cached set the server no longer vouches for.
        if (cancelled || readOnly) return;
        dropCachedChangeSet(reader, familyId);
        if (paintedFromCache.current) setChangeSet(null);
      });
    return () => {
      cancelled = true;
    };
  }, [active, familyId, readOnly, readOnlyQuery, reader]);

  // Every state of the set (fetched, dismissed, marked seen) is what the next
  // tab paints first; the cached paint itself is not, or it never ages out.
  useEffect(() => {
    if (!active || readOnly || !familyId || !changeSet) return;
    if (changeSet === paintedFromCache.current) return;
    writeCachedChangeSet(reader, familyId, changeSet);
  }, [active, readOnly, familyId, changeSet, reader]);

  // After 10 s on the page: one visit. Never in a read-only view, and never
  // on a cached set: its baseline may predate the last tab's visit.
  useEffect(() => {
    if (!active || readOnly || !familyId || !fetchedFamily) return;
    const held = changeSet?.server_held ?? false;
    const baseline = changeSet?.current_baseline;
    const timer = window.setTimeout(() => {
      recordDashboardVisit(familyId).catch(() => {});
      // Anonymous readers keep their own mark: in "previous visit" mode it
      // moves to where this visit opened.
      if (!held && modeRef.current === 'previous_visit' && baseline) {
        writeLocalBaseline(familyId, baseline);
      }
    }, VISIT_DELAY_MS);
    return () => window.clearTimeout(timer);
    // changeSet is read for two values fixed at load; the timer must not restart on dismissals.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, readOnly, familyId, fetchedFamily]);

  const fail = useCallback((message: string, err: unknown) => {
    notifications.show({
      color: 'red',
      title: 'Changes since your last visit',
      message: err instanceof Error ? err.message : message,
    });
  }, []);

  const markAllSeen = useCallback(async () => {
    if (!familyId || readOnly || !changeSet) return;
    setSeenBusy(true);
    try {
      const res = await markDashboardSeen(familyId);
      if (!changeSet.server_held && res.baseline) writeLocalBaseline(familyId, res.baseline);
      setChangeSet((prev) => (prev ? clearedSet(prev) : prev));
      setComparing(NO_COMPARING);
      setViewState('off');
      setFocusRunState(null);
      writeSharedView(familyId, 'off');
      writeSharedFocus(familyId, null);
    } catch (err) {
      fail('Could not mark the changes as seen.', err);
    } finally {
      setSeenBusy(false);
    }
  }, [familyId, readOnly, changeSet, fail]);

  const dismiss = useCallback(
    (key: string) => {
      if (!familyId || readOnly || !changeSet) return;
      const held = changeSet.server_held;
      markDashboardSeen(familyId, [key])
        .then((res) => {
          if (!held && res.dismissed) mergeLocalDismissed(familyId, res.dismissed);
          setChangeSet((prev) => {
            if (!prev || !(key in prev.changed_components)) return prev;
            const { [key]: _gone, ...rest } = prev.changed_components;
            return { ...prev, changed_components: rest };
          });
          setComparing((prev) => {
            if (!prev.has(key)) return prev;
            const next = new Set(prev);
            next.delete(key);
            return next;
          });
        })
        .catch((err) => fail('Could not mark the component as seen.', err));
    },
    [familyId, readOnly, changeSet, fail],
  );

  const toggleCompare = useCallback((key: string) => {
    setComparing((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);

  // The changed figures of this tab: what "Overlay" turns on.
  const highlightKeys = useMemo(() => {
    if (!dashboardId || !changeSet) return [] as string[];
    const marked = changeSet.changed_components;
    return components
      .filter((m) => HIGHLIGHTABLE_TYPES.has(String(m.component_type)))
      .map((m) => changeKey(dashboardId, String(m.index)))
      .filter((key) => key in marked);
  }, [dashboardId, changeSet, components]);
  // Of those, the ones Overlay still rings: a figure or an advanced viz on a
  // collection that gained a run is coloured by run instead (or badged when
  // its marks cannot be), which says more than rings on a box or a curve ever
  // did. Rings there would circle every point of a recomputed ordination.
  const ringKeys = useMemo(() => {
    if (!dashboardId || !changeSet) return [] as string[];
    const byRun = overlayRuns(changeSet);
    const coloured = new Set(
      components
        .filter(
          (m) =>
            RUN_COLOURED_TYPES.has(String(m.component_type)) &&
            !KINDS_WITHOUT_RUN_MARKS.has(String(m.viz_kind)) &&
            m.dc_id &&
            String(m.dc_id) in byRun,
        )
        .map((m) => changeKey(dashboardId, String(m.index))),
    );
    return highlightKeys.filter((key) => !coloured.has(key));
  }, [dashboardId, changeSet, components, highlightKeys]);

  // How the news shows on the canvas: off, marked in place, or split by run.
  const [view, setViewState] = useState<NewsView>('off');
  // One new run followed instead of all of them (null: every new run).
  const [focusRun, setFocusRunState] = useState<string | null>(null);
  const newRuns = useMemo(
    () =>
      [
        ...new Set(
          (changeSet?.data ?? []).flatMap((d) => (d.kind === 'refreshed' ? d.new_run_tags : [])),
        ),
      ].sort(),
    [changeSet],
  );
  const focus = focusRun && newRuns.includes(focusRun) ? focusRun : null;
  const split = useMemo<NewsSplit | null>(
    () =>
      active && changeSet && !changeSet.first_visit
        ? newsSplitGroups(
            changeSet,
            {
              // "New" is blue on every page, like the tile's updated dot and
              // the run rows, whatever the page's primary colour.
              fresh: brandHex('--mantine-color-blue-6', '#228be6'),
              seen: brandHex('--mantine-color-gray-5', '#adb5bd'),
            },
            focus,
          )
        : null,
    [active, changeSet, focus],
  );
  const setFocusRun = useCallback(
    (run: string | null) => {
      setFocusRunState(run);
      if (familyId && !readOnly) writeSharedFocus(familyId, run);
    },
    [familyId, readOnly],
  );
  const setView = useCallback(
    (next: NewsView) => {
      setViewState(next);
      setComparing(next === 'overlay' ? new Set(ringKeys) : NO_COMPARING);
      if (familyId && !readOnly) writeSharedView(familyId, next);
    },
    [ringKeys, familyId, readOnly],
  );
  // "This run on the dashboard": that run alone, or back to every new run when
  // it was already the one shown.
  const showRun = useCallback(
    (run: string) => {
      if (focus === run && view !== 'off') {
        setFocusRun(null);
        return;
      }
      setFocusRun(run);
      if (view === 'off') setView(split ? 'new' : 'overlay');
    },
    [focus, view, split, setFocusRun, setView],
  );
  // The view chosen on another tab of the family follows the reader here,
  // once this tab's news and components are known.
  const restoredFor = useRef<string | null>(null);
  useEffect(() => {
    if (!active || readOnly || !familyId || !changeSet || changeSet.first_visit) return;
    if (restoredFor.current === familyId || components.length === 0) return;
    // A cached set restores at once, and the fetched one again: a run that
    // arrived since the cache was written is a valid focus only in the latter.
    if (fetchedFamily === familyId) restoredFor.current = familyId;
    const sharedFocus = readSharedFocus(familyId);
    if (sharedFocus && newRuns.includes(sharedFocus)) setFocusRunState(sharedFocus);
    const shared = readSharedView(familyId);
    if (!shared || shared === 'off') return;
    const needsSplit = shared === 'split' || shared === 'new';
    if (needsSplit && !split) return;
    if (shared === 'overlay' && highlightKeys.length === 0 && !split) return;
    setViewState(shared);
    setComparing(shared === 'overlay' ? new Set(ringKeys) : NO_COMPARING);
  }, [
    active,
    readOnly,
    familyId,
    fetchedFamily,
    changeSet,
    components.length,
    split,
    highlightKeys.length,
    ringKeys,
    newRuns,
  ]);
  const splitOn = view !== 'off' && split !== null && (view !== 'overlay' || split.groups.length > 0);
  // What the canvas applies: side by side, in one panel, or the new side alone.
  const applied = useMemo<NewsSplit | null>(() => {
    if (!splitOn || !split) return null;
    if (view === 'new') return newSideOnly(split);
    if (view === 'overlay') return overlaySides(split);
    return { ...split, mode: 'split' };
  }, [splitOn, split, view]);
  // The legend lists every side once, whichever collection it splits.
  const splitLegend = useMemo<GroupRenderDef[] | null>(() => {
    if (!splitOn) return null;
    const byName = new Map<string, GroupRenderDef>();
    if (!applied) return null;
    for (const g of [...applied.groups, ...Object.values(applied.samples).flat()]) {
      if (!byName.has(g.name)) byName.set(g.name, g);
    }
    return [...byName.values()];
  }, [splitOn, applied]);
  useEffect(() => {
    onSplitChange?.(applied);
  }, [onSplitChange, applied]);
  const runUnscopedDcs = useRunUnscopedDcs(components, Boolean(applied && applied.groups.length > 0));
  // Gone (marked seen, flag off): the canvas goes back to normal.
  useEffect(() => () => onSplitChange?.(null), [onSplitChange]);

  const openCompare = useCallback((key: string) => setCompareKey(key), []);
  const closeCompare = useCallback(() => setCompareKey(null), []);

  const setMode = useCallback(
    (next: MarkMode) => {
      setModeState(next);
      if (changeSet?.server_held) {
        saveChangesPrefs(next).catch((err) => fail('Could not save the preference.', err));
      } else {
        writeLocalMode(next);
      }
    },
    [changeSet?.server_held, fail],
  );

  const marksValue = useMemo<ChangeMarksValue>(() => {
    if (!active || !changeSet || changeSet.first_visit) {
      return {
        marked: EMPTY_MARKED,
        tabId: dashboardId,
        comparing,
        toggleCompare,
        openCompare,
        dismiss,
        diffQuery: NO_DIFF_QUERY,
        baselineVersionId: null,
        readOnly,
        splitGroupsByDc: NO_SPLIT_BY_DC,
        tabOverlay: false,
        newRunsByDc: NO_RUNS_BY_DC,
        runUnscopedDcs: NO_DCS,
      };
    }
    let diffQuery: ChangeMarksValue['diffQuery'] = NO_DIFF_QUERY;
    if (readOnly) diffQuery = { since: readOnlyQuery.since, beforeRun: readOnlyQuery.beforeRun };
    else if (!changeSet.server_held && familyId) diffQuery = { baseline: readLocalReader(familyId).baseline };
    return {
      marked: changeSet.changed_components,
      tabId: dashboardId,
      comparing,
      toggleCompare,
      openCompare,
      dismiss,
      diffQuery,
      baselineVersionId: changeSet.baseline_version_id,
      readOnly,
      splitGroupsByDc: applied ? applied.samples : NO_SPLIT_BY_DC,
      tabOverlay: view === 'overlay',
      newRunsByDc: view === 'overlay' ? focusedRuns(overlayRuns(changeSet), focus) : NO_RUNS_BY_DC,
      runUnscopedDcs,
    };
  }, [
    active,
    changeSet,
    dashboardId,
    familyId,
    comparing,
    toggleCompare,
    openCompare,
    dismiss,
    readOnly,
    readOnlyQuery,
    applied,
    view,
    focus,
    runUnscopedDcs,
  ]);

  const details = useMemo(() => markDetails(active ? changeSet : null), [active, changeSet]);

  const sinceValue = useMemo<ChangesSinceValue | null>(() => {
    if (!active || !changeSet || !dashboardId || !familyId) return null;
    return {
      changeSet,
      tabId: dashboardId,
      familyId,
      projectId: projectId ?? null,
      canEdit,
      readOnly,
      readOnlyQuery,
      mode,
      setMode,
      markAllSeen,
      seenBusy,
      highlightable: highlightKeys.length,
      view,
      setView,
      splitAvailable: split !== null,
      splitGroups: splitLegend,
      newRuns,
      focusRun: focus,
      setFocusRun,
      showRun,
    };
  }, [
    active,
    changeSet,
    dashboardId,
    familyId,
    canEdit,
    readOnly,
    readOnlyQuery,
    mode,
    setMode,
    markAllSeen,
    seenBusy,
    highlightKeys.length,
    view,
    setView,
    split,
    splitLegend,
    projectId,
    newRuns,
    focus,
    setFocusRun,
    showRun,
  ]);

  // The component behind the open key. Opening needs marks to be live, so the
  // modal is mounted only then and never in a pinned preview or the editor.
  const compareMetadata = useMemo(
    () =>
      compareKey && dashboardId
        ? components.find((m) => changeKey(dashboardId, String(m.index)) === compareKey) ?? null
        : null,
    [compareKey, dashboardId, components],
  );

  return (
    <ChangeMarksProviderBase value={marksValue} details={details}>
      <ChangesSinceContext.Provider value={sinceValue}>
        {children}
        {active && compareMetadata && (
          <CompareModal
            opened
            onClose={closeCompare}
            metadata={compareMetadata}
            dashboardId={dashboardId}
            filters={filters}
            baselineVersionId={changeSet?.baseline_version_id ?? null}
            canEdit={canEdit}
          />
        )}
      </ChangesSinceContext.Provider>
    </ChangeMarksProviderBase>
  );
};

export default ChangeMarksProvider;
