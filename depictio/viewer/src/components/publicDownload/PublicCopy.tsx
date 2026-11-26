import React, { useEffect, useState } from 'react';
import { Text } from '@mantine/core';
import { getPublicBundleStatus, type PublicBundleStatus } from 'depictio-react-core';

/**
 * The visitors' ready copies of a public dashboard (#1480): the files the
 * project's owner lets anyone download, already built at the dashboard's
 * default view. The export modals open on them (`ReadyCopy.tsx`), and "My
 * view" builds the reader's own.
 */

/** The copies on offer, asked once per dashboard; null when there are none
 *  (either switch off, a private project, the offer off, nothing built yet)
 *  or when `dashboardId` is null (the reader builds exports themselves). */
export function usePublicCopy(dashboardId: string | null): PublicBundleStatus | null {
  return usePublicCopyState(dashboardId).copy;
}

/** The copies on offer and whether the server has answered yet: a modal that
 *  opens on the ready copy waits for the answer before it reads anything else
 *  (a visitor's preview counts against their address). */
export function usePublicCopyState(dashboardId: string | null): {
  copy: PublicBundleStatus | null;
  loaded: boolean;
} {
  const [state, setState] = useState<{ copy: PublicBundleStatus | null; loaded: boolean }>({
    copy: null,
    loaded: false,
  });
  useEffect(() => {
    if (!dashboardId) {
      setState({ copy: null, loaded: true });
      return;
    }
    setState({ copy: null, loaded: false });
    let alive = true;
    void getPublicBundleStatus(dashboardId).then((s) => {
      if (alive) setState({ copy: s?.available ? s : null, loaded: true });
    });
    return () => {
      alive = false;
    };
  }, [dashboardId]);
  return state;
}

/** One dimmed line under a card's buttons. */
export const ExportNote: React.FC<{ children: React.ReactNode; testId?: string }> = ({
  children,
  testId,
}) => (
  <Text size="xs" c="dimmed" lh={1.35} data-testid={testId}>
    {children}
  </Text>
);
