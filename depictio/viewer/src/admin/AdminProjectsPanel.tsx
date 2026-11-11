import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
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
import { notifications } from '@mantine/notifications';
import { Icon } from '@iconify/react';
import { FolderKanban, Globe, LayoutDashboard, Lock } from 'lucide-react';

import {
  deleteProject as apiDeleteProject,
  listAllProjects,
  listAllDashboards,
  updateProject as apiUpdateProject,
} from 'depictio-react-core';
import type {
  AdminProject,
  AdminDashboard,
  EditProjectInput,
  ProjectListEntry,
} from 'depictio-react-core';

import { STROKE, useGlassPages } from '../chrome/variants/glass/pages';
import { formatDateTime, parseServerTimestamp } from '../lib/datetime';
import AdminTable, { type AdminTableColumn } from './AdminTable';
import Facts from './Facts';
import ProjectActionsMenu from '../projects/ProjectActionsMenu';
import EditProjectModal from '../projects/EditProjectModal';
import DeleteProjectModal from '../projects/DeleteProjectModal';

type ProjectColumnKey =
  | 'name'
  | 'owner'
  | 'visibility'
  | 'workflow'
  | 'dashboards'
  | 'created'
  | 'updated'
  | 'id'
  | 'description';

interface ProjectRow {
  project: AdminProject;
  projectId: string;
  ownerEmail: string;
  viewerEntries: { email?: string }[];
  projectDashboards: { main: AdminDashboard; children: AdminDashboard[] }[];
  tabCount: number;
  workflowSystem: string | null;
}

/** Sort key of a server timestamp: epoch ms, or null when absent. */
function dateSort(raw: unknown): number | null {
  const d = parseServerTimestamp(raw);
  return d ? d.getTime() : null;
}

/** The list-page entry the actions menu and modals read, built from an admin row. */
function toProjectEntry(p: AdminProject): ProjectListEntry {
  return {
    _id: p._id,
    id: p.id,
    name: p.name,
    is_public: p.is_public,
    permissions: p.permissions,
    registration_time: p.registration_time,
    last_modified: p.last_modified,
    data_management_platform_project_url: p.data_management_platform_project_url,
    published_lock: p.published_lock,
  };
}

const NoValue: React.FC = () => (
  <Text span size="sm" c="dimmed">
    —
  </Text>
);

const AdminProjectsPanel: React.FC = () => {
  const glass = useGlassPages();
  const [projects, setProjects] = useState<AdminProject[]>([]);
  const [dashboards, setDashboards] = useState<AdminDashboard[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [editTarget, setEditTarget] = useState<ProjectListEntry | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<ProjectListEntry | null>(null);

  // Reloads keep the table on screen (no spinner) so search and open rows survive.
  const refresh = useCallback(() => setRefreshKey((k) => k + 1), []);

  useEffect(() => {
    let cancelled = false;
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
  }, [refreshKey]);

  // Same calls and notifications as the Projects page. An admin may edit and
  // delete any project (backend: admin bypass in /projects/update and /delete).
  const handleEdit = useCallback(
    async (projectId: string, input: EditProjectInput) => {
      await apiUpdateProject(projectId, input);
      notifications.show({
        color: 'teal',
        title: 'Project updated',
        message: 'Changes saved.',
        autoClose: 2000,
      });
      setEditTarget(null);
      refresh();
    },
    [refresh],
  );

  const handleDelete = useCallback(
    async (projectId: string) => {
      await apiDeleteProject(projectId);
      notifications.show({
        color: 'teal',
        title: 'Project deleted',
        message: 'Project and all linked dashboards removed.',
        autoClose: 2500,
      });
      setDeleteTarget(null);
      refresh();
    },
    [refresh],
  );

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

  const rows = useMemo<ProjectRow[]>(
    () =>
      projects.map((project) => {
        const projectId = String(project.id ?? project._id ?? project.name);
        const entries = dashboardsByProject.get(projectId) ?? [];
        const workflowSystem =
          project.workflow_system && project.workflow_system !== 'none'
            ? project.workflow_system
            : null;
        return {
          project,
          projectId,
          ownerEmail: project.permissions?.owners?.[0]?.email ?? 'Unknown',
          viewerEntries: project.permissions?.viewers ?? [],
          projectDashboards: entries,
          tabCount: entries.reduce((n, d) => n + 1 + d.children.length, 0),
          workflowSystem,
        };
      }),
    [projects, dashboardsByProject],
  );

  const columns = useMemo<AdminTableColumn<ProjectRow, ProjectColumnKey>[]>(
    () => [
      {
        key: 'name',
        label: 'Name',
        alwaysVisible: true,
        sortValue: (r) => r.project.name?.toLowerCase() ?? null,
        render: (r) =>
          glass ? (
            <Group gap="sm" wrap="nowrap">
              <FolderKanban
                size={17}
                strokeWidth={STROKE}
                className="ga-row-icon"
                style={{ color: 'var(--mantine-color-logoTeal-filled)' }}
                aria-hidden
              />
              <Anchor
                href={`/projects/${r.projectId}`}
                fw={550}
                size="sm"
                truncate
                c="inherit"
                underline="hover"
              >
                {r.project.name}
              </Anchor>
            </Group>
          ) : (
            <Anchor
              href={`/projects/${r.projectId}`}
              fw={500}
              size="sm"
              truncate
              c="inherit"
              underline="hover"
            >
              {r.project.name}
            </Anchor>
          ),
      },
      {
        key: 'owner',
        label: 'Owner',
        sortValue: (r) => r.ownerEmail.toLowerCase(),
        render: (r) => <Text size="sm">{r.ownerEmail}</Text>,
      },
      {
        key: 'visibility',
        label: 'Visibility',
        sortValue: (r) => (r.project.is_public ? 'Public' : 'Private'),
        render: (r) =>
          glass ? (
            <Badge
              color="gray"
              size="sm"
              leftSection={
                r.project.is_public ? (
                  <Globe size={12} strokeWidth={STROKE} />
                ) : (
                  <Lock size={12} strokeWidth={STROKE} />
                )
              }
            >
              {r.project.is_public ? 'Public' : 'Private'}
            </Badge>
          ) : (
            <Badge
              color={r.project.is_public ? 'blue' : 'gray'}
              variant="light"
              size="md"
              radius="sm"
            >
              {r.project.is_public ? 'Public' : 'Private'}
            </Badge>
          ),
      },
      {
        key: 'workflow',
        label: 'Workflow',
        description: 'Workflow system',
        sortValue: (r) => r.workflowSystem,
        render: (r) => <Text size="sm">{r.workflowSystem ?? <NoValue />}</Text>,
      },
      {
        key: 'dashboards',
        label: 'Dashboards',
        sortValue: (r) => r.projectDashboards.length,
        render: (r) => (
          <Text size="sm" style={{ fontVariantNumeric: 'tabular-nums' }}>
            {r.projectDashboards.length === 0
              ? '0'
              : r.tabCount !== r.projectDashboards.length
                ? `${r.projectDashboards.length} (${r.tabCount} tabs)`
                : String(r.projectDashboards.length)}
          </Text>
        ),
      },
      {
        key: 'created',
        label: 'Created',
        defaultVisible: false,
        sortValue: (r) => dateSort(r.project.registration_time),
        render: (r) => <Text size="sm">{formatDateTime(r.project.registration_time)}</Text>,
      },
      {
        key: 'updated',
        label: 'Updated',
        description: 'Last modified',
        sortValue: (r) => dateSort(r.project.last_modified),
        render: (r) => <Text size="sm">{formatDateTime(r.project.last_modified)}</Text>,
      },
      {
        key: 'id',
        label: 'ID',
        description: 'Project ID',
        defaultVisible: false,
        sortValue: (r) => r.projectId,
        render: (r) => (
          <Text size="xs" ff="monospace">
            {r.projectId}
          </Text>
        ),
      },
      {
        key: 'description',
        label: 'Description',
        defaultVisible: false,
        sortValue: (r) => r.project.description?.toLowerCase() ?? null,
        render: (r) => (
          <Text size="sm" lineClamp={2}>
            {r.project.description || <NoValue />}
          </Text>
        ),
      },
    ],
    [glass],
  );

  const searchText = useCallback(
    (r: ProjectRow) =>
      [
        r.project.name,
        r.ownerEmail,
        r.projectId,
        r.project.description ?? '',
        r.workflowSystem ?? '',
        r.project.is_public ? 'public' : 'private',
        ...r.projectDashboards.map((d) => d.main.title ?? ''),
      ].join(' '),
    [],
  );

  const renderDetail = (row: ProjectRow) => {
    const { project, projectId, ownerEmail, viewerEntries, projectDashboards } = row;
    const viewerCount = viewerEntries.length;
    return (
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
    );
  };

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

  if (rows.length === 0) {
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
    <>
    <AdminTable
      rows={rows}
      rowKey={(r) => r.projectId}
      columns={columns}
      storageKey="depictio.admin.projects.columns.v1"
      defaultSort={{ key: 'name' }}
      searchText={searchText}
      searchPlaceholder="Search projects..."
      renderDetail={renderDetail}
      rowActions={(r) => (
        <ProjectActionsMenu
          project={toProjectEntry(r.project)}
          canMutate
          onEdit={setEditTarget}
          onDelete={setDeleteTarget}
        />
      )}
    />
    <EditProjectModal
      opened={Boolean(editTarget)}
      project={editTarget}
      onClose={() => setEditTarget(null)}
      onSubmit={handleEdit}
    />
    <DeleteProjectModal
      opened={Boolean(deleteTarget)}
      project={deleteTarget}
      onClose={() => setDeleteTarget(null)}
      onConfirm={handleDelete}
    />
    </>
  );
};

export default AdminProjectsPanel;
