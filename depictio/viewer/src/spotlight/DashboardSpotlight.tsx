import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useHotkeys } from '@mantine/hooks';
import { notifications } from '@mantine/notifications';
import type { DashboardData, DashboardSummary, SpotlightHit } from 'depictio-react-core';

import { dashboardHref } from '../dashboards/lib/dashboardLinks';
import { prefersReducedMotion } from '../guide/showMe';
import SpotlightPalette from './SpotlightPalette';
import { focusComponent, hrefWithComponent, takeComponentParam } from './focus';
import { useSpotlightTabs } from './useSpotlightTabs';

/**
 * Search across every tab of a dashboard, the way Spotlight searches a Mac:
 * Cmd+K (Ctrl+K off Apple keyboards) or the header's magnifier opens a field,
 * and picking a result takes the reader to the component — on its tab,
 * scrolled into view, ringed for a moment.
 *
 * Mounted once by the viewer and once by the editor, which hand it the family,
 * the tab being read and two hooks into their own state. Owns the shortcut,
 * the palette, the fetch of the other tabs and the landing.
 *
 * Landing on another tab's component goes through the app's own tab
 * navigation: tabs are separate documents (the sidebar's pills are plain
 * links), so the palette loads the tab's address as a pill would, with the
 * component in `?component=`, and the tab, once its dashboard is in, finds the
 * component and rings it. A component of the tab being read is landed on in
 * place, and so is one another tab shows here too — a section it pins to every
 * tab, say — rather than reloading for something already on screen.
 */
export interface DashboardSpotlightProps {
  opened: boolean;
  onOpen: () => void;
  onClose: () => void;
  /** The family, in sidebar order. */
  tabs: DashboardSummary[];
  currentId: string | null;
  /** The tab being read, as the page holds it. */
  dashboard: DashboardData | null;
  /** Which app's addresses the results link to. */
  mode: 'view' | 'edit';
  /** The page's dashboard is in: a component named in the address can be
   *  looked for. */
  ready: boolean;
  /**
   * Before landing on something of this page (`index` null for the tab
   * itself): uncover the canvas — close the Guide — and open the drawer a
   * filter lives in on a phone.
   */
  onBeforeFocus?: (index: string | null) => void;
  /** Before leaving for another tab: the editor saves what is pending.
   *  Resolving to `false` stays on this tab. */
  onBeforeLeave?: () => Promise<boolean | void> | boolean | void;
}

/** How long a tab freshly loaded from a result looks for its component: the
 *  dashboard still has to arrive, and its figures to lay out. */
const LANDING_TIMEOUT_MS = 15000;
/** How long to look for another tab's component on this page before going
 *  to its tab: long enough for a folded section to open and mount. */
const HERE_TIMEOUT_MS = 500;

function notifyNotShown(): void {
  notifications.show({
    color: 'gray',
    title: 'That component is not on screen',
    message: 'It may be hidden at this screen size, or inside a panel that is closed.',
    autoClose: 4000,
  });
}

const DashboardSpotlight: React.FC<DashboardSpotlightProps> = ({
  opened,
  onOpen,
  onClose,
  tabs,
  currentId,
  dashboard,
  mode,
  ready,
  onBeforeFocus,
  onBeforeLeave,
}) => {
  // `mod` is Cmd on Apple keyboards and Ctrl elsewhere. Mantine skips the
  // shortcut while focus is in an input, a textarea, a select or editable
  // text, which covers the code editor too (Monaco types into a textarea); the
  // palette's own field closes on it instead.
  useHotkeys([['mod+K', () => (opened ? onClose() : onOpen())]]);

  // Counted rather than flagged so each opening retries a tab that failed.
  const [opens, setOpens] = useState(0);
  useEffect(() => {
    if (opened) setOpens((n) => n + 1);
  }, [opened]);
  const { tabs: searchable, pending, failed } = useSpotlightTabs({
    tabs,
    currentId,
    current: dashboard,
    opens,
  });

  const hrefFor = useCallback(
    (hit: SpotlightHit) => {
      const tabHref = dashboardHref(hit.entry.tabId, mode);
      return hit.entry.index ? hrefWithComponent(tabHref, hit.entry.index) : tabHref;
    },
    [mode],
  );

  const onPick = useCallback(
    async (hit: SpotlightHit) => {
      onClose();
      const { entry } = hit;
      const here = entry.tabId === currentId;
      const leave = async (href: string) => {
        if ((await onBeforeLeave?.()) === false) return;
        window.location.assign(href);
      };
      if (entry.kind === 'tab') {
        if (!here) {
          await leave(dashboardHref(entry.tabId, mode));
          return;
        }
        // The tab being read: back to its top.
        onBeforeFocus?.(null);
        document.querySelector('[data-testid="dashboard-content"]')?.scrollTo({
          top: 0,
          behavior: prefersReducedMotion() ? 'auto' : 'smooth',
        });
        return;
      }
      const index = entry.index!;
      onBeforeFocus?.(index);
      if (here) {
        if (!(await focusComponent(index))) notifyNotShown();
        return;
      }
      if (await focusComponent(index, { timeoutMs: HERE_TIMEOUT_MS })) return;
      await leave(hrefWithComponent(dashboardHref(entry.tabId, mode), index));
    },
    [onClose, currentId, mode, onBeforeFocus, onBeforeLeave],
  );

  // Arriving from a result on another tab: land on the component it named,
  // once the dashboard is in.
  const landedRef = useRef(false);
  useEffect(() => {
    if (!ready || landedRef.current) return;
    landedRef.current = true;
    const index = takeComponentParam();
    if (!index) return;
    onBeforeFocus?.(index);
    void focusComponent(index, { timeoutMs: LANDING_TIMEOUT_MS }).then((found) => {
      if (!found) notifyNotShown();
    });
  }, [ready, onBeforeFocus]);

  return (
    <SpotlightPalette
      opened={opened}
      onClose={onClose}
      tabs={searchable}
      summaries={tabs}
      currentId={currentId}
      pending={pending}
      failed={failed}
      hrefFor={hrefFor}
      onPick={onPick}
    />
  );
};

export default DashboardSpotlight;
