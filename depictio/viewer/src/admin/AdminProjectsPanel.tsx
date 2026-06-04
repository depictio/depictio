import React, { useEffect, useMemo, useState } from 'react';
import {
  Accordion,
  Alert,
  Anchor,
  Center,
  Group,
  List,
  Loader,
  Stack,
  Text,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import { listAllProjects, listAllDashboards } from 'depictio-react-core';
import type { AdminProject, AdminDashboard } from 'depictio-react-core';

const AdminProjectsPanel: React.FC = () => {
  const [projects, setProjects] = useState<AdminProject[]>([]);
  const [dashboards, setDashboards] = useState<AdminDashboard[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    Promise.all([listAllProjects(), listAllDashboards(true)])
      .then(([projectList, dashboardList]) => {
        if (cancelled) return;
        setProjects(projectList);
        setDashboards(dashboardList);
      })
      .catch((err: Error) => {
        if (cancelled) return;
        setError(err.message || 'Failed to load projects');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Group dashboards by project_id so each project row can list its
  // dashboards inline. Main tabs are surfaced as top-level entries; child
  // tabs are nested under their parent main tab so the structure mirrors
  // what the user sees in the viewer sidebar.
  const dashboardsByProject = useMemo(() => {
    const grouped = new Map<
      string,
      { main: AdminDashboard; children: AdminDashboard[] }[]
    >();
    const byParent = new Map<string, AdminDashboard[]>();
    for (const d of dashboards) {
      if (d.is_main_tab === false && d.parent_dashboard_id) {
        const bucket = byParent.get(d.parent_dashboard_id) ?? [];
        bucket.push(d);
        byParent.set(d.parent_dashboard_id, bucket);
      }
    }
    for (const d of dashboards) {
      if (d.is_main_tab === false) continue;
      const pid = d.project_id ?? '';
      const entry = {
        main: d,
        children: (byParent.get(d.dashboard_id) ?? []).slice().sort((a, b) =>
          (a.title ?? '').localeCompare(b.title ?? ''),
        ),
      };
      const bucket = grouped.get(pid) ?? [];
      bucket.push(entry);
      grouped.set(pid, bucket);
    }
    for (const bucket of grouped.values()) {
      bucket.sort((a, b) => (a.main.title ?? '').localeCompare(b.main.title ?? ''));
    }
    return grouped;
  }, [dashboards]);

  const sortedProjects = useMemo(
    () =>
      [...projects].sort((a, b) => {
        const ax = (a.name ?? '').toLowerCase();
        const bx = (b.name ?? '').toLowerCase();
        return ax.localeCompare(bx);
      }),
    [projects],
  );

  if (loading) {
    return (
      <Center mih={200}>
        <Loader />
      </Center>
    );
  }

  if (error) {
    return (
      <Alert color="red" variant="light" icon={<Icon icon="mdi:alert-circle" />}>
        {error}
      </Alert>
    );
  }

  if (sortedProjects.length === 0) {
    return (
      <Center mih={200}>
        <Stack align="center" gap="xs">
          <Icon
            icon="material-symbols:folder-off-outline"
            width={48}
            color="var(--mantine-color-dimmed)"
          />
          <Text c="dimmed">No projects available.</Text>
        </Stack>
      </Center>
    );
  }

  return (
    <Accordion radius="md" variant="separated" multiple>
      {sortedProjects.map((project) => {
        const projectId = project.id ?? project._id ?? project.name;
        const ownerEmail = project.permissions?.owners?.[0]?.email ?? 'Unknown';
        const viewerCount = project.permissions?.viewers?.length ?? 0;
        const projectDashboards =
          dashboardsByProject.get(String(projectId)) ?? [];
        return (
          <Accordion.Item key={String(projectId)} value={String(projectId)}>
            <Accordion.Control>
              <Stack gap={4} style={{ width: '100%' }}>
                <Text fw={500} size="lg" truncate>
                  {project.name}
                </Text>
                <List
                  size="sm"
                  spacing={2}
                  c="dimmed"
                  listStyleType="disc"
                  withPadding
                >
                  <List.Item>
                    Visibility: {project.is_public ? 'Public' : 'Private'}
                  </List.Item>
                  {project.workflow_system && project.workflow_system !== 'none' && (
                    <List.Item>
                      Workflow system: {project.workflow_system}
                    </List.Item>
                  )}
                  <List.Item>
                    Dashboards:{' '}
                    {projectDashboards.length === 0
                      ? '0'
                      : `${projectDashboards.length} (` +
                        projectDashboards
                          .reduce(
                            (n, d) => n + 1 + d.children.length,
                            0,
                          )
                          .toString() +
                        ' tabs)'}
                  </List.Item>
                </List>
              </Stack>
            </Accordion.Control>
            <Accordion.Panel>
              <Stack gap="xs">
                <Group gap="xs">
                  <Text fw="bold" size="sm">
                    Project ID:
                  </Text>
                  <Text size="sm">{String(projectId)}</Text>
                </Group>
                <Group gap="xs">
                  <Text fw="bold" size="sm">
                    Owner:
                  </Text>
                  <Text size="sm">{ownerEmail}</Text>
                </Group>
                {project.description && (
                  <Group gap="xs" align="flex-start">
                    <Text fw="bold" size="sm">
                      Description:
                    </Text>
                    <Text size="sm" style={{ flex: 1 }}>
                      {project.description}
                    </Text>
                  </Group>
                )}
                <Group gap="xs" align="flex-start">
                  <Text fw="bold" size="sm">
                    Viewers:
                  </Text>
                  {viewerCount === 0 ? (
                    <Text size="sm">None</Text>
                  ) : (
                    <List size="sm" style={{ flex: 1 }}>
                      {(project.permissions?.viewers ?? []).map((v, i) => (
                        <List.Item key={`${v.email ?? i}`}>{v.email ?? '*'}</List.Item>
                      ))}
                    </List>
                  )}
                </Group>
                <Group gap="xs" align="flex-start">
                  <Text fw="bold" size="sm">
                    Dashboards:
                  </Text>
                  {projectDashboards.length === 0 ? (
                    <Text size="sm" c="dimmed">
                      None
                    </Text>
                  ) : (
                    <List size="sm" style={{ flex: 1 }}>
                      {projectDashboards.map((entry) => (
                        <List.Item key={entry.main.dashboard_id}>
                          <Anchor
                            href={`/dashboard/${entry.main.dashboard_id}`}
                            size="sm"
                          >
                            {entry.main.title ??
                              entry.main.main_tab_name ??
                              entry.main.dashboard_id}
                          </Anchor>
                          {entry.children.length > 0 && (
                            <List size="xs" withPadding mt={4}>
                              {entry.children.map((child) => (
                                <List.Item key={child.dashboard_id}>
                                  <Anchor
                                    href={`/dashboard/${child.dashboard_id}`}
                                    size="xs"
                                    c="dimmed"
                                  >
                                    {child.title ?? child.dashboard_id}
                                  </Anchor>
                                </List.Item>
                              ))}
                            </List>
                          )}
                        </List.Item>
                      ))}
                    </List>
                  )}
                </Group>
              </Stack>
            </Accordion.Panel>
          </Accordion.Item>
        );
      })}
    </Accordion>
  );
};

export default AdminProjectsPanel;
