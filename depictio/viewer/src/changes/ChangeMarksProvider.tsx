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
import { isReadOnlyQuery, markDetails, parseReadOnlyQuery } from './describe';
import { newsSplitGroups, type NewsSplit, type NewsView } from './newsSplit';

/** How long a reader stays on the page before it counts as a visit. */
export const VISIT_DELAY_MS = 10_000;

interface Props {
  /** The tab on screen. */
  dashboardId: string | null;
  /** The family's main tab: the key of the stored mark. Unknown until the dashboard loads. */
  familyId: string | undefined;
  /** `?version=` pinned preview: shows nothing, calls nothing. */
  previewVersionId: string | null;
  /** The signed-in user is still being resolved. */
  userLoading: boolean;
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
const NO_DIFF_QUERY: ChangeMarksValue['diffQuery'] = {};
const NO_COMPONENTS: StoredMetadata[] = [];
const NO_FILTERS: InteractiveFilter[] = [];

/** Component types that draw what is new in place when compared. Cards and
 *  tables have nothing to ring: their dot says it. */
const HIGHLIGHTABLE_TYPES = new Set(['figure', 'multiqc', 'advanced_viz']);

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

const ChangeMarksProvider: React.FC<Props> = ({
  dashboardId,
  familyId,
  previewVersionId,
  userLoading,
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
  const [mode, setModeState] = useState<MarkMode>('sticky');
  const [comparing, setComparing] = useState<ReadonlySet<string>>(NO_COMPARING);
  const [seenBusy, setSeenBusy] = useState(false);
  // The component whose Before | Now view is open (a change key), if any.
  const [compareKey, setCompareKey] = useState<string | null>(null);
  const modeRef = useRef(mode);
  modeRef.current = mode;

  // One fetch per open. `changeSet` is kept for the whole session: nothing
  // refetches it, so the marks do not shift under the reader.
  useEffect(() => {
    if (!active || !familyId) return;
    let cancelled = false;
    const local = readOnly ? null : readLocalReader(familyId);
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
      })
      .catch(() => {
        // Decoration: a failed fetch leaves the dashboard as it was.
      });
    return () => {
      cancelled = true;
    };
  }, [active, familyId, readOnly, readOnlyQuery]);

  // After 10 s on the page: one visit. Never in a read-only view.
  const loadedFamily = changeSet?.family_id ?? null;
  useEffect(() => {
    if (!active || readOnly || !familyId || !loadedFamily) return;
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
  }, [active, readOnly, familyId, loadedFamily]);

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

  // How the news shows on the canvas: off, marked in place, or split by run.
  const [view, setViewState] = useState<NewsView>('off');
  const split = useMemo<NewsSplit | null>(
    () =>
      active && changeSet && !changeSet.first_visit
        ? newsSplitGroups(changeSet, {
            fresh: brandHex('--mantine-primary-color-filled', '#228be6'),
            seen: brandHex('--mantine-color-gray-5', '#adb5bd'),
          })
        : null,
    [active, changeSet],
  );
  const setView = useCallback(
    (next: NewsView) => {
      setViewState(next);
      setComparing(next === 'overlay' ? new Set(highlightKeys) : NO_COMPARING);
    },
    [highlightKeys],
  );
  const splitOn = view === 'split' && split !== null;
  // The legend lists every side once, whichever collection it splits.
  const splitLegend = useMemo<GroupRenderDef[] | null>(() => {
    if (!splitOn) return null;
    const byName = new Map<string, GroupRenderDef>();
    for (const g of [...split.groups, ...Object.values(split.samples).flat()]) {
      if (!byName.has(g.name)) byName.set(g.name, g);
    }
    return [...byName.values()];
  }, [splitOn, split]);
  useEffect(() => {
    onSplitChange?.(splitOn ? split : null);
  }, [onSplitChange, splitOn, split]);
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
      splitGroupsByDc: splitOn ? split.samples : NO_SPLIT_BY_DC,
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
    splitOn,
    split,
  ]);

  const details = useMemo(() => markDetails(active ? changeSet : null), [active, changeSet]);

  const sinceValue = useMemo<ChangesSinceValue | null>(() => {
    if (!active || !changeSet || !dashboardId || !familyId) return null;
    return {
      changeSet,
      tabId: dashboardId,
      familyId,
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
