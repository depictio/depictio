import { useEffect, useState } from 'react';
import { listDashboards } from 'depictio-react-core';

export interface ProjectDashboardRef {
  /** The main tab's id: the id of the dashboard's version family. */
  familyId: string;
  title: string;
}

const cache = new Map<string, { at: number; promise: Promise<ProjectDashboardRef[]> }>();
const TTL_MS = 30_000;

/** The project's dashboards (main tabs), read once per half minute however
 *  many rows ask. */
export function loadProjectDashboards(projectId: string): Promise<ProjectDashboardRef[]> {
  const hit = cache.get(projectId);
  if (hit && Date.now() - hit.at < TTL_MS) return hit.promise;
  const promise = listDashboards(true)
    .then((all) =>
      all
        .filter((d) => String(d.project_id ?? '') === projectId && !d.parent_dashboard_id)
        .map((d) => ({ familyId: d.dashboard_id, title: d.title || 'Untitled dashboard' }))
        .sort((a, b) => a.title.localeCompare(b.title)),
    )
    .catch(() => {
      cache.delete(projectId);
      return [] as ProjectDashboardRef[];
    });
  cache.set(projectId, { at: Date.now(), promise });
  return promise;
}

/** The project's dashboards once `enabled`; `null` while loading. */
export function useProjectDashboards(projectId: string, enabled = true): ProjectDashboardRef[] | null {
  const [dashboards, setDashboards] = useState<ProjectDashboardRef[] | null>(null);
  useEffect(() => {
    if (!enabled) return;
    let live = true;
    loadProjectDashboards(projectId).then((d) => {
      if (live) setDashboards(d);
    });
    return () => {
      live = false;
    };
  }, [projectId, enabled]);
  return dashboards;
}
