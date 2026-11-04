import React, { useEffect, useMemo, useState } from 'react';
import { Anchor, Group, Stack, Text } from '@mantine/core';
import { ArrowUpRight, LayoutDashboard, Layers } from 'lucide-react';
import { listDashboards } from 'depictio-react-core';
import type { DashboardListEntry } from 'depictio-react-core';

import { STROKE, useGlassPages } from '../../chrome/variants/glass/pages';
import { ProjectPart } from './ProjectPart';

interface DashboardRow {
  id: string;
  title: string;
  subtitle?: string;
  tabs: number;
  lastSaved?: string;
}

/** The project's dashboards (main tabs, with their tab count), each a link
 *  to the viewer, as the page's collapsible Dashboards part. */
export const ProjectDashboardsPanel: React.FC<{ projectId: string }> = ({ projectId }) => {
  const glass = useGlassPages();
  const [all, setAll] = useState<DashboardListEntry[] | null>(null);

  useEffect(() => {
    let live = true;
    listDashboards(true)
      .then((d) => {
        if (live) setAll(d);
      })
      .catch(() => {
        if (live) setAll([]);
      });
    return () => {
      live = false;
    };
  }, [projectId]);

  const rows = useMemo<DashboardRow[]>(() => {
    const mine = (all ?? []).filter((d) => String(d.project_id ?? '') === projectId);
    const childCount = new Map<string, number>();
    mine.forEach((d) => {
      if (d.parent_dashboard_id) {
        const p = String(d.parent_dashboard_id);
        childCount.set(p, (childCount.get(p) ?? 0) + 1);
      }
    });
    return mine
      .filter((d) => !d.parent_dashboard_id)
      .map((d) => ({
        id: d.dashboard_id,
        title: d.title || 'Untitled dashboard',
        subtitle: d.subtitle || undefined,
        tabs: 1 + (childCount.get(d.dashboard_id) ?? 0),
        lastSaved: typeof d.last_saved_ts === 'string' ? d.last_saved_ts.slice(0, 16) : undefined,
      }))
      .sort((a, b) => a.title.localeCompare(b.title));
  }, [all, projectId]);

  // Nothing until the list arrives, so the page does not flash "none".
  if (all === null) return null;

  const summary = `${rows.length} dashboard${rows.length === 1 ? '' : 's'}`;
  const empty = (
    <Text size="sm" c="dimmed" data-testid="project-dashboards-empty">
      No dashboard is built on this project yet.
    </Text>
  );

  return (
    <ProjectPart id="dashboards" icon={LayoutDashboard} title="Dashboards" summary={summary}>
      <div data-testid="project-dashboards">
        {!rows.length ? (
          empty
        ) : glass ? (
          <div className="pd-wf-grid">
            {rows.map((r) => (
              <a
                key={r.id}
                className="pd-wf-card pd-dash-card"
                href={`/dashboard/${r.id}`}
                data-testid="project-dashboard-link"
              >
                <span className="pd-wf-chip">
                  <LayoutDashboard size={20} strokeWidth={STROKE} aria-hidden />
                </span>
                <span className="pd-wf-body">
                  <span className="pd-wf-name">{r.title}</span>
                  {r.subtitle && <span className="pd-wf-meta">{r.subtitle}</span>}
                  <span className="pd-wf-meta">
                    <Layers size={13} strokeWidth={STROKE} aria-hidden />
                    {r.tabs} tab{r.tabs === 1 ? '' : 's'}
                    {r.lastSaved ? ` · saved ${r.lastSaved.replace('T', ' ')}` : ''}
                  </span>
                </span>
                <span className="pd-dash-open" aria-hidden>
                  <ArrowUpRight size={16} strokeWidth={STROKE} />
                </span>
              </a>
            ))}
          </div>
        ) : (
          <Stack gap="xs">
            {rows.map((r) => (
              <Group key={r.id} gap="xs" wrap="nowrap">
                <Anchor href={`/dashboard/${r.id}`} fw={600} data-testid="project-dashboard-link">
                  {r.title}
                </Anchor>
                <Text size="sm" c="dimmed" truncate>
                  {r.tabs} tab{r.tabs === 1 ? '' : 's'}
                  {r.subtitle ? ` · ${r.subtitle}` : ''}
                </Text>
              </Group>
            ))}
          </Stack>
        )}
      </div>
    </ProjectPart>
  );
};
