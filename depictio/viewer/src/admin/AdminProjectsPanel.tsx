import React, { useEffect, useMemo, useState } from 'react';
import {
  Accordion,
  Alert,
  Anchor,
  Badge,
  Center,
  Group,
  List,
  Loader,
  Stack,
  Text,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import { FolderKanban, Globe, LayoutDashboard, Lock } from 'lucide-react';

import { listAllProjects, listAllDashboards } from 'depictio-react-core';
import type { AdminProject, AdminDashboard } from 'depictio-react-core';

import { STROKE, useGlassPages } from '../chrome/variants/glass/pages';
import Facts from './Facts';

const AdminProjectsPanel: React.FC = () => {
  const glass = useGlassPages();
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
    <Accordion radius="md" variant="separated" multiple className={glass ? 'ga-rows' : undefined}>
      {sortedProjects.map((project) => {
        const projectId = project.id ?? project._id ?? project.name;
        const ownerEmail = project.permissions?.owners?.[0]?.email ?? 'Unknown';
        const viewerCount = project.permissions?.viewers?.length ?? 0;
        const projectDashboards =
          dashboardsByProject.get(String(projectId)) ?? [];
        const tabCount = projectDashboards.reduce((n, d) => n + 1 + d.children.length, 0);
        const workflowSystem =
          project.workflow_system && project.workflow_system !== 'none'
            ? project.workflow_system
            : null;
        const viewerEntries = project.permissions?.viewers ?? [];
        return (
          <Accordion.Item key={String(projectId)} value={String(projectId)}>
            <Accordion.Control>
              {glass ? (
                <Group gap="sm" wrap="nowrap">
                  <FolderKanban
                    size={17}
                    strokeWidth={STROKE}
                    className="ga-row-icon"
                    style={{ color: 'var(--mantine-color-logoTeal-filled)' }}
                    aria-hidden
                  />
                  <Stack gap={1} style={{ flex: 1, minWidth: 0 }}>
                    <Text fw={550} size="sm" truncate>
                      {project.name}
                    </Text>
                    <Text size="xs" c="dimmed" truncate>
                      {[
                        workflowSystem,
                        projectDashboards.length === 0
                          ? 'No dashboards'
                          : `${projectDashboards.length} ${
                              projectDashboards.length === 1 ? 'dashboard' : 'dashboards'
                            }${tabCount !== projectDashboards.length ? `, ${tabCount} tabs` : ''}`,
                      ]
                        .filter(Boolean)
                        .join(' · ')}
                    </Text>
                  </Stack>
                  <Badge
                    color="gray"
                    size="sm"
                    leftSection={
                      project.is_public ? (
                        <Globe size={12} strokeWidth={STROKE} />
                      ) : (
                        <Lock size={12} strokeWidth={STROKE} />
                      )
                    }
                  >
                    {project.is_public ? 'Public' : 'Private'}
                  </Badge>
                </Group>
              ) : (
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
                    {workflowSystem && (
                      <List.Item>
                        Workflow system: {workflowSystem}
                      </List.Item>
                    )}
                    <List.Item>
                      Dashboards:{' '}
                      {projectDashboards.length === 0
                        ? '0'
                        : `${projectDashboards.length} (${tabCount} tabs)`}
                    </List.Item>
                  </List>
                </Stack>
              )}
            </Accordion.Control>
            <Accordion.Panel>
              <Facts
                items={[
                  { label: 'Project ID', value: String(projectId) },
                  { label: 'Owner', value: ownerEmail },
                  ...(project.description
                    ? [
                        {
                          label: 'Description',
                          top: true,
                          value: (
                            <Text size="sm" style={{ flex: 1 }}>
                              {project.description}
                            </Text>
                          ),
                        },
                      ]
                    : []),
                  {
                    label: 'Viewers',
                    top: true,
                    value:
                      viewerCount === 0 ? (
                        glass ? 'None' : <Text size="sm">None</Text>
                      ) : glass ? (
                        <Stack gap={2}>
                          {viewerEntries.map((v, i) => (
                            <Text key={`${v.email ?? i}`} size="sm">
                              {v.email ?? '*'}
                            </Text>
                          ))}
                        </Stack>
                      ) : (
                        <List size="sm" style={{ flex: 1 }}>
                          {viewerEntries.map((v, i) => (
                            <List.Item key={`${v.email ?? i}`}>{v.email ?? '*'}</List.Item>
                          ))}
                        </List>
                      ),
                  },
                  {
                    label: 'Dashboards',
                    top: true,
                    value:
                      projectDashboards.length === 0 ? (
                        <Text size="sm" c="dimmed">
                          None
                        </Text>
                      ) : glass ? (
                        <Stack gap={4}>
                          {projectDashboards.map((entry) => (
                            <Stack key={entry.main.dashboard_id} gap={2}>
                              <Group gap={6} wrap="nowrap">
                                <LayoutDashboard
                                  size={14}
                                  strokeWidth={STROKE}
                                  style={{ color: 'var(--mantine-color-logoOrange-filled)' }}
                                  aria-hidden
                                />
                                <Anchor
                                  href={`/dashboard/${entry.main.dashboard_id}`}
                                  size="sm"
                                  truncate
                                >
                                  {entry.main.title ??
                                    entry.main.main_tab_name ??
                                    entry.main.dashboard_id}
                                </Anchor>
                              </Group>
                              {entry.children.map((child) => (
                                <Anchor
                                  key={child.dashboard_id}
                                  href={`/dashboard/${child.dashboard_id}`}
                                  size="xs"
                                  c="dimmed"
                                  pl={20}
                                >
                                  {child.title ?? child.dashboard_id}
                                </Anchor>
                              ))}
                            </Stack>
                          ))}
                        </Stack>
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
                      ),
                  },
                ]}
              />
            </Accordion.Panel>
          </Accordion.Item>
        );
      })}
    </Accordion>
  );
};

export default AdminProjectsPanel;
