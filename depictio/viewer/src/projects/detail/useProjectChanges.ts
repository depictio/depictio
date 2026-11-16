import { useCallback, useEffect, useState } from 'react';
import {
  fetchProjectChanges,
  markProjectSeen,
  recordProjectVisit,
} from 'depictio-react-core';
import type { ProjectChangeSet } from 'depictio-react-core';

import { useChangesSinceEnabled } from '../../hooks/useChangesSinceEnabled';
import { changeCount, readStoredBaseline, writeStoredBaseline } from './projectChanges';

/** A visit counts once the reader has stayed this long. */
export const VISIT_AFTER_MS = 10_000;

export interface ProjectChanges {
  /** The server offers "changed since" (nothing below renders or loads otherwise). */
  enabled: boolean;
  changeSet: ProjectChangeSet | null;
  /** What the pill counts. */
  count: number;
  /** The reader's mark moves to now. */
  markSeen: () => Promise<void>;
}

/**
 * What changed in a project since the reader last looked.
 *
 * A signed-in reader's mark lives on the server and a visit is recorded after
 * {@link VISIT_AFTER_MS} on the page. An anonymous or temporary reader's lives
 * in the browser: the server hands back `current_baseline`, kept in
 * localStorage on the first visit and on "Mark as seen", and sent back as
 * `baseline` on the next load. Every storage call is guarded.
 */
export function useProjectChanges(projectId: string | null): ProjectChanges {
  const enabled = useChangesSinceEnabled();
  const [changeSet, setChangeSet] = useState<ProjectChangeSet | null>(null);

  useEffect(() => {
    setChangeSet(null);
    if (!enabled || !projectId) return;
    let cancelled = false;
    let timer: number | undefined;
    const stored = readStoredBaseline(projectId);
    fetchProjectChanges(projectId, { baseline: stored })
      .then((cs) => {
        if (cancelled) return;
        setChangeSet(cs);
        if (cs.server_held) {
          timer = window.setTimeout(() => {
            recordProjectVisit(projectId).catch(() => undefined);
          }, VISIT_AFTER_MS);
        } else if (cs.current_baseline && (cs.first_visit || !stored)) {
          // First visit: the mark is stored at once, so closing the tab early
          // still leaves a baseline to compare against next time.
          writeStoredBaseline(projectId, cs.current_baseline);
        }
      })
      .catch(() => {
        // The pill is an extra; a failed request leaves the page as it was.
      });
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [enabled, projectId]);

  const markSeen = useCallback(async () => {
    if (!projectId) return;
    const result = await markProjectSeen(projectId);
    if (!result.persisted && result.baseline) writeStoredBaseline(projectId, result.baseline);
    const seenAt = result.baseline?.seen_at ?? new Date().toISOString();
    setChangeSet((prev) =>
      prev
        ? {
            ...prev,
            first_visit: false,
            since: seenAt,
            data: [],
            new_runs: [],
            failed_ingestions: [],
            dashboards: [],
          }
        : prev,
    );
  }, [projectId]);

  return { enabled, changeSet, count: changeCount(changeSet), markSeen };
}
