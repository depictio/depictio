import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Alert, Badge, Center, Group, List, Loader, Stack, Text } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { Icon } from '@iconify/react';
import { Globe, LayoutDashboard, Lock } from 'lucide-react';

import {
  deleteDashboard as apiDeleteDashboard,
  duplicateDashboard as apiDuplicateDashboard,
  editDashboard as apiEditDashboard,
  exportDashboardJson,
  listAllDashboards,
  listAllProjects,
} from 'depictio-react-core';
import type {
  AdminDashboard,
  AdminProject,
  DashboardListEntry,
  EditDashboardInput,
} from 'depictio-react-core';

import { STROKE, useGlassPages } from '../chrome/variants/glass/pages';
import { formatDateTime, parseServerTimestamp } from '../lib/datetime';
import AdminTable, { type AdminTableColumn } from './AdminTable';
import Facts from './Facts';
import DashboardActionsMenu from '../dashboards/DashboardActionsMenu';
import EditDashboardModal from '../dashboards/EditDashboardModal';
import DeleteDashboardModal from '../dashboards/DeleteDashboardModal';
import { recordOpen as recordDashboardOpen } from '../dashboards/lib/dashboardRecents';

type DashboardColumnKey =
  | 'title'
  | 'project'
  | 'owner'
  | 'visibility'
  | 'components'
  | 'saved'
  | 'created'
  | 'version'
  | 'id';

interface DashboardRow {
  dashboard: AdminDashboard;
  dashboardId: string;
  title: string;
  projectName: string | null;
  ownerEmail: string;
  viewers: { email?: string }[];
  isPublic: boolean;
  componentCount: number;
}

function formatLastSaved(raw: unknown): string {
  if (!raw || typeof raw !== 'string') return 'Never';
  return formatDateTime(raw, raw);
}

/** Sort key of a server timestamp: epoch ms, or null when absent. */
function dateSort(raw: unknown): number | null {
  const d = parseServerTimestamp(raw);
  return d ? d.getTime() : null;
}

/** The list-page entry the actions menu and modals read, built from an admin row. */
function toDashboardEntry(d: AdminDashboard): DashboardListEntry {
  return {
    dashboard_id: d.dashboard_id,
    title: d.title,
    subtitle: d.subtitle,
    icon: d.icon,
    icon_color: d.icon_color,
    is_public: d.is_public,
    is_main_tab: d.is_main_tab,
    parent_dashboard_id: d.parent_dashboard_id,
    main_tab_name: d.main_tab_name,
    project_id: d.project_id,
    last_saved_ts: d.last_saved_ts,
    workflow_system: d.workflow_system,
    permissions: d.permissions,
  };
}

const NoValue: React.FC = () => (
  <Text span size="sm" c="dimmed">
    —
  </Text>
);

const AdminDashboardsPanel: React.FC = () => {
  const glass = useGlassPages();
  const [dashboards, setDashboards] = useState<AdminDashboard[]>([]);
  const [projects, setProjects] = useState<AdminProject[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [editTarget, setEditTarget] = useState<DashboardListEntry | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<DashboardListEntry | null>(null);

  // Reloads keep the table on screen (no spinner) so search and open rows survive.
  const refresh = useCallback(() => setRefreshKey((k) => k + 1), []);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    // The project list only feeds the "Project" column: if it fails the table
    // still renders, with the column empty.
    Promise.all([listAllDashboards(), listAllProjects().catch(() => [] as AdminProject[])])
      .then(([dashboardList, projectList]) => {
        if (cancelled) return;
        setDashboards(dashboardList);
        setProjects(projectList);
      })
      .catch((err: Error) => {
        if (cancelled) return;
        setError(err.message || 'Failed to load dashboards');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [refreshKey]);

  // Same calls and notifications as the Dashboards page. An admin passes the
  // backend's mutation check on any dashboard (admin bypass in
  // check_project_permission), so the menu is always enabled here.
  const handleEdit = useCallback(
    async (dashboardId: string, input: EditDashboardInput) => {
      await apiEditDashboard(dashboardId, input);
      notifications.show({
        color: 'teal',
        title: 'Dashboard updated',
        message: 'Changes saved.',
        autoClose: 2000,
      });
      setEditTarget(null);
      refresh();
    },
    [refresh],
  );

  const handleDelete = useCallback(
    async (dashboardId: string) => {
      await apiDeleteDashboard(dashboardId);
      notifications.show({
        color: 'teal',
        title: 'Dashboard deleted',
        message: 'Dashboard removed.',
        autoClose: 2000,
      });
      setDeleteTarget(null);
      refresh();
    },
    [refresh],
  );

  const handleDuplicate = useCallback(
    async (dashboard: DashboardListEntry) => {
      try {
        await apiDuplicateDashboard(dashboard.dashboard_id);
        notifications.show({
          color: 'teal',
          title: 'Dashboard duplicated',
          message: `"${dashboard.title} (copy)" is ready.`,
          autoClose: 2500,
        });
        refresh();
      } catch (err) {
        notifications.show({
          color: 'red',
          title: 'Duplicate failed',
          message: (err as Error).message,
        });
      }
    },
    [refresh],
  );

  const handleView = useCallback((dashboard: DashboardListEntry) => {
    recordDashboardOpen(String(dashboard.dashboard_id));
    window.location.assign(`/dashboard/${dashboard.dashboard_id}`);
  }, []);

  const handleExport = useCallback(async (dashboard: DashboardListEntry) => {
    try {
      const payload = await exportDashboardJson(dashboard.dashboard_id);
      const blob = new Blob([JSON.stringify(payload, null, 2)], {
        type: 'application/json',
      });
      const url = URL.createObjectURL(blob);
      const safeTitle = (dashboard.title || dashboard.dashboard_id).replace(
        /[^a-zA-Z0-9._-]+/g,
        '_',
      );
      const a = document.createElement('a');
      a.href = url;
      a.download = `${safeTitle}.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (err) {
      notifications.show({
        color: 'red',
        title: 'Export failed',
        message: (err as Error).message,
      });
    }
  }, []);

  const rows = useMemo<DashboardRow[]>(() => {
    const projectNames = new Map<string, string>();
    for (const p of projects) {
      const id = p.id ?? p._id;
      if (id) projectNames.set(String(id), p.name);
    }
    return dashboards.map((dashboard) => {
      const viewers = dashboard.permissions?.viewers ?? [];
      return {
        dashboard,
        dashboardId: dashboard.dashboard_id,
        title: dashboard.title || dashboard.dashboard_id,
        projectName: dashboard.project_id
          ? (projectNames.get(String(dashboard.project_id)) ?? null)
          : null,
        ownerEmail: dashboard.permissions?.owners?.[0]?.email ?? 'Unknown',
        viewers,
        isPublic: Boolean(dashboard.is_public) || viewers.some((v) => v?.email === '*'),
        componentCount: Array.isArray(dashboard.stored_metadata)
          ? dashboard.stored_metadata.length
          : 0,
      };
    });
  }, [dashboards, projects]);

  const columns = useMemo<AdminTableColumn<DashboardRow, DashboardColumnKey>[]>(
    () => [
      {
        key: 'title',
        label: 'Title',
        alwaysVisible: true,
        sortValue: (r) => r.title.toLowerCase(),
        render: (r) =>
          glass ? (
            <Group gap="sm" wrap="nowrap">
              <LayoutDashboard
                size={17}
                strokeWidth={STROKE}
                className="ga-row-icon"
                style={{ color: 'var(--mantine-color-logoOrange-filled)' }}
                aria-hidden
              />
              <Text fw={550} size="sm" truncate>
                {r.title}
              </Text>
            </Group>
          ) : (
            <Text fw={500} size="sm" truncate>
              {r.title}
            </Text>
          ),
      },
      {
        key: 'project',
        label: 'Project',
        sortValue: (r) => r.projectName?.toLowerCase() ?? null,
        render: (r) => <Text size="sm">{r.projectName ?? <NoValue />}</Text>,
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
        sortValue: (r) => (r.isPublic ? 'Public' : 'Private'),
        render: (r) =>
          glass ? (
            <Badge
              color="gray"
              size="sm"
              leftSection={
                r.isPublic ? (
                  <Globe size={12} strokeWidth={STROKE} />
                ) : (
                  <Lock size={12} strokeWidth={STROKE} />
                )
              }
            >
              {r.isPublic ? 'Public' : 'Private'}
            </Badge>
          ) : (
            <Badge color={r.isPublic ? 'blue' : 'gray'} variant="light" size="md" radius="sm">
              {r.isPublic ? 'Public' : 'Private'}
            </Badge>
          ),
      },
      {
        key: 'components',
        label: 'Components',
        sortValue: (r) => r.componentCount,
        render: (r) => (
          <Text size="sm" style={{ fontVariantNumeric: 'tabular-nums' }}>
            {r.componentCount}
          </Text>
        ),
      },
      {
        key: 'saved',
        label: 'Last saved',
        sortValue: (r) => dateSort(r.dashboard.last_saved_ts),
        render: (r) => <Text size="sm">{formatLastSaved(r.dashboard.last_saved_ts)}</Text>,
      },
      {
        key: 'created',
        label: 'Created',
        defaultVisible: false,
        sortValue: (r) => dateSort(r.dashboard.creation_time),
        render: (r) => <Text size="sm">{formatDateTime(r.dashboard.creation_time)}</Text>,
      },
      {
        key: 'version',
        label: 'Version',
        defaultVisible: false,
        sortValue: (r) =>
          typeof r.dashboard.version === 'number' ? r.dashboard.version : null,
        render: (r) => (
          <Text size="sm" style={{ fontVariantNumeric: 'tabular-nums' }}>
            {r.dashboard.version ?? <NoValue />}
          </Text>
        ),
      },
      {
        key: 'id',
        label: 'ID',
        description: 'Dashboard ID',
        defaultVisible: false,
        sortValue: (r) => r.dashboardId,
        render: (r) => (
          <Text size="xs" ff="monospace">
            {r.dashboardId}
          </Text>
        ),
      },
    ],
    [glass],
  );

  const searchText = useCallback(
    (r: DashboardRow) =>
      [
        r.title,
        r.projectName ?? '',
        r.ownerEmail,
        r.dashboardId,
        r.isPublic ? 'public' : 'private',
      ].join(' '),
    [],
  );

  const renderDetail = (row: DashboardRow) => {
    const { dashboard, dashboardId, ownerEmail, viewers, componentCount } = row;
    return (
      <Facts
        items={[
          { label: 'Dashboard ID', value: dashboardId },
          ...(row.projectName ? [{ label: 'Project', value: row.projectName }] : []),
          { label: 'Owner', value: ownerEmail },
          {
            label: 'Viewers',
            top: true,
            value:
              viewers.length === 0 ? (
                glass ? (
                  'None'
                ) : (
                  <Text size="sm">None</Text>
                )
              ) : glass ? (
                <Stack gap={2}>
                  {viewers.map((v, i) => (
                    <Text key={`${v?.email ?? i}`} size="sm">
                      {v?.email ?? '*'}
                    </Text>
                  ))}
                </Stack>
              ) : (
                <List size="sm" style={{ flex: 1 }}>
                  {viewers.map((v, i) => (
                    <List.Item key={`${v?.email ?? i}`}>{v?.email ?? '*'}</List.Item>
                  ))}
                </List>
              ),
          },
          { label: 'Components', value: String(componentCount) },
          { label: 'Last saved', value: formatLastSaved(dashboard.last_saved_ts) },
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
          <Icon icon="ph:empty-bold" width={48} color="var(--mantine-color-dimmed)" />
          <Text c="dimmed">No dashboards available.</Text>
        </Stack>
      </Center>
    );
  }

  return (
    <>
    <AdminTable
      rows={rows}
      rowKey={(r) => r.dashboardId}
      columns={columns}
      storageKey="depictio.admin.dashboards.columns.v1"
      defaultSort={{ key: 'title' }}
      searchText={searchText}
      searchPlaceholder="Search dashboards..."
      renderDetail={renderDetail}
      rowActions={(r) => (
        <DashboardActionsMenu
          dashboard={toDashboardEntry(r.dashboard)}
          isOwner
          onView={handleView}
          onEdit={setEditTarget}
          onDelete={setDeleteTarget}
          onDuplicate={handleDuplicate}
          onExport={handleExport}
          triggerSize="sm"
        />
      )}
    />
    <EditDashboardModal
      opened={Boolean(editTarget)}
      dashboard={editTarget}
      onClose={() => setEditTarget(null)}
      onSubmit={handleEdit}
    />
    <DeleteDashboardModal
      opened={Boolean(deleteTarget)}
      dashboard={deleteTarget}
      onClose={() => setDeleteTarget(null)}
      onConfirm={handleDelete}
    />
    </>
  );
};

export default AdminDashboardsPanel;
