/**
 * The two ways to look at a project's dashboards around an ingestion:
 *
 *  - "Open dashboards as before <run>": each dashboard as it last was before
 *    the ingestion started (`?version=`), read from its version history.
 *  - "Compare": the read-only view of what that ingestion changed
 *    (`?before_run=`).
 *
 * A project with several dashboards gets a menu naming them; with one, a
 * plain link. Nothing is requested until the control is on screen (the run
 * row was opened, or the timeline listed).
 */
import React, { useEffect, useState } from 'react';
import { Button, Loader, Menu, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';
import { fetchDashboardVersions } from 'depictio-react-core';
import type { DashboardVersionSummary } from 'depictio-react-core';

import { compareHref, findVersionBeforeRun, versionHref } from './projectChanges';
import { useProjectDashboards, type ProjectDashboardRef } from './useProjectDashboards';

const NO_DASHBOARD = 'This project has no dashboard yet.';

/** A disabled control with the reason on hover: a disabled button takes no
 *  pointer events, so the tooltip sits on a wrapper. */
const Off: React.FC<{ tip: string; children: React.ReactNode }> = ({ tip, children }) => (
  <Tooltip label={tip} withArrow>
    <span style={{ display: 'inline-flex' }}>{children}</span>
  </Tooltip>
);

type ActionProps = {
  size?: 'xs' | 'compact-xs' | 'compact-sm';
  testId: string;
};

/** "Compare": what the ingestion changed, in the dashboard viewer. */
export const CompareMenu: React.FC<
  ActionProps & { projectId: string; ingestionRunId: string | null | undefined }
> = ({ projectId, ingestionRunId, size = 'compact-xs', testId }) => {
  const dashboards = useProjectDashboards(projectId);
  const left = <Icon icon="mdi:compare-horizontal" width={14} />;

  if (!ingestionRunId) {
    return (
      <Off tip="No ingestion is recorded for this run, so there is nothing to compare.">
        <Button size={size} variant="default" leftSection={left} disabled data-testid={testId}>
          Compare
        </Button>
      </Off>
    );
  }
  if (dashboards === null) {
    return (
      <Button size={size} variant="default" leftSection={<Loader size={12} />} disabled data-testid={testId}>
        Compare
      </Button>
    );
  }
  if (dashboards.length === 0) {
    return (
      <Off tip={NO_DASHBOARD}>
        <Button size={size} variant="default" leftSection={left} disabled data-testid={testId}>
          Compare
        </Button>
      </Off>
    );
  }
  if (dashboards.length === 1) {
    return (
      <Tooltip label={`What this ingestion changed in ${dashboards[0].title}`} withArrow>
        <Button
          component="a"
          href={compareHref(dashboards[0].familyId, ingestionRunId)}
          size={size}
          variant="default"
          leftSection={left}
          data-testid={testId}
        >
          Compare
        </Button>
      </Tooltip>
    );
  }
  return (
    <Menu position="bottom-start" withinPortal shadow="md">
      <Menu.Target>
        <Button
          size={size}
          variant="default"
          leftSection={left}
          rightSection={<Icon icon="mdi:chevron-down" width={14} />}
          data-testid={testId}
        >
          Compare
        </Button>
      </Menu.Target>
      <Menu.Dropdown>
        <Menu.Label>What this ingestion changed in</Menu.Label>
        {dashboards.map((d) => (
          <Menu.Item
            key={d.familyId}
            component="a"
            href={compareHref(d.familyId, ingestionRunId)}
            data-testid={`${testId}-item`}
          >
            {d.title}
          </Menu.Item>
        ))}
      </Menu.Dropdown>
    </Menu>
  );
};

type Resolved = Record<string, DashboardVersionSummary | null>;

/** For each dashboard, the version that was current before `startedAt`. */
function useVersionsBefore(
  dashboards: ProjectDashboardRef[] | null,
  startedAt: string | null | undefined,
): Resolved | null {
  const [resolved, setResolved] = useState<Resolved | null>(null);
  useEffect(() => {
    setResolved(null);
    if (!dashboards) return;
    let live = true;
    Promise.all(
      dashboards.map(async (d) => {
        try {
          const hit = await findVersionBeforeRun(async (beforeSeq) => {
            const page = await fetchDashboardVersions(d.familyId, { limit: 100, beforeSeq });
            return { versions: page.versions, total: page.total };
          }, startedAt);
          return [d.familyId, hit] as const;
        } catch {
          return [d.familyId, null] as const;
        }
      }),
    ).then((pairs) => {
      if (live) setResolved(Object.fromEntries(pairs));
    });
    return () => {
      live = false;
    };
  }, [dashboards, startedAt]);
  return resolved;
}

/** "Open dashboards as before <run>". */
export const BeforeRunMenu: React.FC<
  ActionProps & { projectId: string; runTag: string; startedAt: string | null | undefined }
> = ({ projectId, runTag, startedAt, size = 'compact-xs', testId }) => {
  const dashboards = useProjectDashboards(projectId);
  const resolved = useVersionsBefore(dashboards, startedAt);
  const label = `Open dashboards as before ${runTag}`;
  const left = <Icon icon="mdi:history" width={14} />;
  const none = 'No version of this dashboard predates this run.';

  if (!startedAt) {
    return (
      <Off tip="No ingestion is recorded for this run, so its start time is unknown.">
        <Button size={size} variant="default" leftSection={left} disabled data-testid={testId}>
          {label}
        </Button>
      </Off>
    );
  }
  if (dashboards === null || resolved === null) {
    return (
      <Button size={size} variant="default" leftSection={<Loader size={12} />} disabled data-testid={testId}>
        {label}
      </Button>
    );
  }
  if (dashboards.length === 0) {
    return (
      <Off tip={NO_DASHBOARD}>
        <Button size={size} variant="default" leftSection={left} disabled data-testid={testId}>
          {label}
        </Button>
      </Off>
    );
  }
  if (dashboards.length === 1) {
    const only = dashboards[0];
    const version = resolved[only.familyId];
    if (!version) {
      return (
        <Off tip={none}>
          <Button size={size} variant="default" leftSection={left} disabled data-testid={testId}>
            {label}
          </Button>
        </Off>
      );
    }
    return (
      <Button
        component="a"
        href={versionHref(only.familyId, version.version_id)}
        size={size}
        variant="default"
        leftSection={left}
        data-testid={testId}
      >
        {label}
      </Button>
    );
  }
  return (
    <Menu position="bottom-start" withinPortal shadow="md">
      <Menu.Target>
        <Button
          size={size}
          variant="default"
          leftSection={left}
          rightSection={<Icon icon="mdi:chevron-down" width={14} />}
          data-testid={testId}
        >
          {label}
        </Button>
      </Menu.Target>
      <Menu.Dropdown>
        <Menu.Label>As it was before this run</Menu.Label>
        {dashboards.map((d) => {
          const version = resolved[d.familyId];
          if (!version) {
            return (
              <Tooltip key={d.familyId} label={none} withArrow position="right">
                <div>
                  <Menu.Item disabled data-testid={`${testId}-item`}>
                    {d.title}
                  </Menu.Item>
                </div>
              </Tooltip>
            );
          }
          return (
            <Menu.Item
              key={d.familyId}
              component="a"
              href={versionHref(d.familyId, version.version_id)}
              data-testid={`${testId}-item`}
            >
              {d.title}
            </Menu.Item>
          );
        })}
      </Menu.Dropdown>
    </Menu>
  );
};
