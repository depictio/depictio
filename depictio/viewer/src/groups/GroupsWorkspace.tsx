import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Alert,
  Badge,
  Box,
  Button,
  Center,
  Grid,
  Group,
  Loader,
  Paper,
  Select,
  Stack,
  Text,
  TextInput,
  useComputedColorScheme,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { Icon } from '@iconify/react';
import { Crown, Plus, Search, ShieldCheck, UsersRound } from 'lucide-react';
import { AgGridReact } from 'ag-grid-react';
import 'ag-grid-community/styles/ag-grid.css';
import 'ag-grid-community/styles/ag-theme-alpine.css';
import type { ColDef, GridApi, ICellRendererParams, RowClassParams } from 'ag-grid-community';

import {
  deleteGroup as apiDeleteGroup,
  fetchGroup,
  listGroups,
  listMyGroups,
} from 'depictio-react-core';
import type { GroupDetail, GroupSummary, MyGroup } from 'depictio-react-core';

import { STROKE, useGlassPages } from '../chrome/variants/glass/pages';
import '../chrome/variants/glass/pages/groups.css';
import CreateGroupModal from './CreateGroupModal';
import DeleteGroupModal from './DeleteGroupModal';
import GroupDetailPanel, { GroupDetailPlaceholder } from './GroupDetailPanel';

/** Seeded groups the permission system bootstraps around — the backend
 *  refuses to delete them (400), so hide the button entirely. */
const PROTECTED_GROUP_NAMES = new Set(['admin', 'users']);

/** Both panes track the viewport so the list scrolls instead of the page. */
const PANE_HEIGHT = 'calc(100vh - 260px)';
const PANE_MIN_HEIGHT = 420;
const ROW_HEIGHT = 36;

export type GroupsScope =
  /** Sysadmin surface (admin page): every group, plus create/delete/P.I. */
  | 'admin'
  /** Personal surface (/groups): only the caller's groups, managed where
   *  they are a group admin, read-only elsewhere. */
  | 'mine';

interface GroupsWorkspaceProps {
  scope: GroupsScope;
}

/** One row of the master list. `is_group_admin`/`is_pi` are only populated
 *  on the 'mine' scope — the admin surface manages every group regardless. */
interface GroupRow extends GroupSummary {
  is_group_admin: boolean;
  is_pi: boolean;
}

function toRows(scope: GroupsScope, list: GroupSummary[] | MyGroup[]): GroupRow[] {
  return (list as MyGroup[]).map((g) => ({
    ...g,
    is_group_admin: scope === 'admin' ? true : Boolean(g.is_group_admin),
    is_pi: Boolean(g.is_pi),
  }));
}

/** Deep-link support: /groups?group=<id> opens straight on that group (the
 *  profile page's group badges link this way). */
function readGroupIdFromQuery(): string | null {
  try {
    return new URLSearchParams(window.location.search).get('group');
  } catch {
    return null;
  }
}

const GroupsWorkspace: React.FC<GroupsWorkspaceProps> = ({ scope }) => {
  // Paper (Glass) look: the page language comes from pages.css / groups.css;
  // here only what Mantine props and the cell renderers decide.
  const glass = useGlassPages();
  const paneStyle = glass ? undefined : { height: PANE_HEIGHT, minHeight: PANE_MIN_HEIGHT };
  const colorScheme = useComputedColorScheme('light', { getInitialValueInEffect: true });
  const isDark = colorScheme === 'dark';

  const [rows, setRows] = useState<GroupRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  const [selectedId, setSelectedId] = useState<string | null>(readGroupIdFromQuery);
  const [detail, setDetail] = useState<GroupDetail | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const [search, setSearch] = useState('');
  const [ssoFilter, setSsoFilter] = useState<'all' | 'manual' | 'sso'>('all');
  const [createOpened, setCreateOpened] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<GroupRow | null>(null);

  // Selecting the first group on the very first load only — later refreshes
  // must not yank the selection away from whatever the user is editing.
  const autoSelected = useRef(false);

  // AG Grid evaluates a row's class when the row is drawn, not when the
  // callback changes: redraw so the selection wash follows the selected group.
  const gridApi = useRef<GridApi<GroupRow> | null>(null);
  useEffect(() => {
    gridApi.current?.redrawRows();
  }, [selectedId, glass]);

  const refreshList = useCallback(() => setRefreshKey((k) => k + 1), []);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    const request = scope === 'admin' ? listGroups() : listMyGroups();
    request
      .then((list) => {
        if (cancelled) return;
        setRows(toRows(scope, list));
      })
      .catch((err: Error) => {
        if (cancelled) return;
        setError(err.message || 'Failed to load groups');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [scope, refreshKey]);

  // Guards against an in-flight detail request landing after the user moved
  // on to another group — only the newest request may write state.
  const pendingDetailId = useRef<string | null>(null);

  const loadDetail = useCallback((groupId: string) => {
    pendingDetailId.current = groupId;
    setDetailLoading(true);
    setDetailError(null);
    fetchGroup(groupId)
      .then((d) => {
        if (pendingDetailId.current !== groupId) return;
        setDetail(d);
      })
      .catch((err: Error) => {
        if (pendingDetailId.current !== groupId) return;
        setDetailError(err.message || 'Failed to load group details');
      })
      .finally(() => {
        if (pendingDetailId.current === groupId) setDetailLoading(false);
      });
  }, []);

  // Keep the detail pane in sync with the selection, and drop a selection
  // whose group disappeared (deleted elsewhere, or not in the caller's list).
  useEffect(() => {
    if (loading) return;
    if (!autoSelected.current) {
      autoSelected.current = true;
      if (!selectedId && rows.length > 0) {
        setSelectedId(rows[0].id);
        return;
      }
    }
    if (selectedId && !rows.some((r) => r.id === selectedId)) {
      setSelectedId(null);
      setDetail(null);
    }
  }, [loading, rows, selectedId]);

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      setDetailError(null);
      return;
    }
    setDetail(null);
    loadDetail(selectedId);
  }, [selectedId, loadDetail]);

  /** Post-mutation: re-fetch the open group and re-list so member counts,
   *  names and role badges in the master list stay accurate. */
  const handleChanged = useCallback(() => {
    if (selectedId) loadDetail(selectedId);
    refreshList();
  }, [selectedId, loadDetail, refreshList]);

  const handleDelete = useCallback(
    async (groupId: string) => {
      await apiDeleteGroup(groupId);
      notifications.show({
        color: 'teal',
        title: 'Group deleted',
        message: 'Group removed and permission references cleaned up.',
        autoClose: 2500,
      });
      setDeleteTarget(null);
      setSelectedId(null);
      setDetail(null);
      refreshList();
    },
    [refreshList],
  );

  const hasSsoGroups = useMemo(() => rows.some((r) => r.sso_managed), [rows]);

  const visibleRows = useMemo(() => {
    if (ssoFilter === 'all') return rows;
    return rows.filter((r) => (ssoFilter === 'sso' ? r.sso_managed : !r.sso_managed));
  }, [rows, ssoFilter]);

  const selectedRow = useMemo(
    () => rows.find((r) => r.id === selectedId) ?? null,
    [rows, selectedId],
  );

  const colDefs = useMemo<ColDef<GroupRow>[]>(
    () => [
      { field: 'id', hide: true },
      // Not displayed, but kept in the model so the quick filter matches on
      // description text as well as the name.
      { field: 'description', hide: true },
      {
        field: 'name',
        headerName: 'Group',
        flex: 2,
        minWidth: 150,
        sort: 'asc',
        cellRenderer: (params: ICellRendererParams<GroupRow>) =>
          glass ? (
            <div className="gg-name">
              <UsersRound size={16} strokeWidth={STROKE} className="gg-name-icon" aria-hidden />
              <span className="gg-name-text">{params.value as string}</span>
              {params.data?.is_pi && (
                <Crown size={14} strokeWidth={STROKE} className="gg-name-mark" aria-label="P.I." />
              )}
              {!params.data?.is_pi && params.data?.is_group_admin && scope === 'mine' && (
                <ShieldCheck
                  size={14}
                  strokeWidth={STROKE}
                  className="gg-name-mark"
                  aria-label="Group admin"
                />
              )}
              {params.data?.sso_managed && (
                <Badge color="grape" size="xs" className="gp-tag-plain">
                  SSO
                </Badge>
              )}
            </div>
          ) : (
            <Group gap={6} h="100%" wrap="nowrap">
              <Icon
                icon="mdi:account-multiple-outline"
                width={16}
                color="var(--mantine-color-gray-6)"
              />
              <Text size="sm" truncate style={{ minWidth: 0 }}>
                {params.value as string}
              </Text>
              {params.data?.is_pi && (
                <Icon icon="mdi:crown-outline" width={14} color="var(--mantine-color-yellow-6)" />
              )}
              {!params.data?.is_pi && params.data?.is_group_admin && scope === 'mine' && (
                <Icon
                  icon="mdi:shield-account-outline"
                  width={14}
                  color="var(--mantine-color-blue-6)"
                />
              )}
              {params.data?.sso_managed && (
                <Badge color="grape" variant="light" size="xs" radius="sm">
                  SSO
                </Badge>
              )}
            </Group>
          ),
      },
      {
        field: 'member_count',
        headerName: 'Members',
        width: glass ? 84 : 110,
        cellStyle: { textAlign: 'right' },
      },
    ],
    [scope, glass],
  );

  // Classic paints the selection with a Mantine tint; Paper with its accent
  // wash (groups.css), through a class so the theme tokens stay in the CSS.
  const getRowStyle = useCallback(
    (params: RowClassParams<GroupRow>) =>
      !glass && params.data?.id === selectedId
        ? { backgroundColor: 'var(--mantine-color-blue-light)' }
        : undefined,
    [selectedId, glass],
  );
  const getRowClass = useCallback(
    (params: RowClassParams<GroupRow>) =>
      glass && params.data?.id === selectedId ? 'gg-row-selected' : undefined,
    [selectedId, glass],
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
        <Group justify="space-between" wrap="nowrap">
          <Text size="sm">{error}</Text>
          <Button size="xs" variant="light" onClick={refreshList}>
            Retry
          </Button>
        </Group>
      </Alert>
    );
  }

  const canManageSelected = scope === 'admin' || Boolean(selectedRow?.is_group_admin);
  const canDeleteSelected =
    scope === 'admin' &&
    Boolean(selectedRow) &&
    !PROTECTED_GROUP_NAMES.has((selectedRow?.name ?? '').toLowerCase());

  return (
    <>
      <Grid gutter="md" align="stretch" className={glass ? 'gg-workspace' : undefined}>
        <Grid.Col span={{ base: 12, md: 5, lg: 4 }}>
          <Paper
            withBorder
            radius="md"
            p="sm"
            className={glass ? 'gg-pane' : undefined}
            style={paneStyle}
          >
            <Stack gap="xs" h="100%">
              <Group gap="xs" wrap="nowrap">
                <TextInput
                  flex={1}
                  size={glass ? 'sm' : 'xs'}
                  placeholder="Search groups…"
                  value={search}
                  onChange={(e) => setSearch(e.currentTarget.value)}
                  leftSection={
                    glass ? (
                      <Search size={15} strokeWidth={STROKE} aria-hidden />
                    ) : (
                      <Icon icon="mdi:magnify" width={14} />
                    )
                  }
                  data-testid="groups-search"
                />
                {hasSsoGroups && (
                  <Select
                    w={glass ? 118 : 108}
                    size={glass ? 'sm' : 'xs'}
                    aria-label="Group source"
                    allowDeselect={false}
                    checkIconPosition="right"
                    comboboxProps={{ withinPortal: true }}
                    value={ssoFilter}
                    onChange={(v) => setSsoFilter((v as 'all' | 'manual' | 'sso') ?? 'all')}
                    data={[
                      { label: 'All', value: 'all' },
                      { label: 'Manual', value: 'manual' },
                      { label: 'SSO', value: 'sso' },
                    ]}
                    data-testid="groups-source-filter"
                  />
                )}
                {scope === 'admin' && (
                  <Button
                    size={glass ? 'sm' : 'xs'}
                    color={glass ? undefined : 'teal'}
                    leftSection={
                      glass ? (
                        <Plus size={15} strokeWidth={STROKE} aria-hidden />
                      ) : (
                        <Icon icon="mdi:account-multiple-plus-outline" width={14} />
                      )
                    }
                    onClick={() => setCreateOpened(true)}
                    data-testid="admin-create-group-btn"
                  >
                    Create
                  </Button>
                )}
              </Group>

              <Box
                className={isDark ? 'ag-theme-alpine-dark' : 'ag-theme-alpine'}
                style={{ flex: 1, minHeight: 0, width: '100%' }}
                data-testid="groups-list-grid"
              >
                <AgGridReact<GroupRow>
                  rowData={visibleRows}
                  columnDefs={colDefs}
                  getRowId={(params) => params.data.id}
                  headerHeight={36}
                  rowHeight={ROW_HEIGHT}
                  suppressCellFocus
                  quickFilterText={search}
                  rowSelection="single"
                  getRowStyle={getRowStyle}
                  getRowClass={getRowClass}
                  onGridReady={(e) => {
                    gridApi.current = e.api;
                  }}
                  onRowClicked={(e) => e.data && setSelectedId(e.data.id)}
                  overlayNoRowsTemplate={
                    '<span style="color:var(--mantine-color-dimmed);font-size:12px">No groups match.</span>'
                  }
                />
              </Box>

              <Text size="xs" c="dimmed" ta="right">
                {visibleRows.length} group{visibleRows.length === 1 ? '' : 's'}
                {visibleRows.length !== rows.length ? ` of ${rows.length}` : ''}
              </Text>
            </Stack>
          </Paper>
        </Grid.Col>

        <Grid.Col span={{ base: 12, md: 7, lg: 8 }}>
          {!selectedId ? (
            <GroupDetailPlaceholder
              message={
                rows.length === 0
                  ? scope === 'admin'
                    ? 'No groups yet — create one to start sharing projects.'
                    : 'You are not a member of any group yet.'
                  : 'Select a group to manage its members.'
              }
            />
          ) : detailError ? (
            <Paper withBorder radius="md" p="md">
              <Alert color="red" variant="light" icon={<Icon icon="mdi:alert-circle" />}>
                {detailError}
              </Alert>
            </Paper>
          ) : !detail || detail.id !== selectedId ? (
            <Paper
              withBorder
              radius="md"
              p="md"
              className={glass ? 'gg-pane' : undefined}
              style={paneStyle}
            >
              <Center h="100%">
                <Loader size="sm" />
              </Center>
            </Paper>
          ) : (
            <Paper
              withBorder
              radius="md"
              p="md"
              className={glass ? 'gg-pane' : undefined}
              style={{ ...paneStyle, overflowY: 'auto' }}
              data-testid="group-detail-pane"
            >
              <Box style={{ opacity: detailLoading ? 0.6 : 1 }}>
                <GroupDetailPanel
                  group={detail}
                  canManage={canManageSelected}
                  canEditPI={scope === 'admin'}
                  onChanged={handleChanged}
                  onDelete={
                    canDeleteSelected && selectedRow
                      ? () => setDeleteTarget(selectedRow)
                      : undefined
                  }
                />
              </Box>
            </Paper>
          )}
        </Grid.Col>
      </Grid>

      {scope === 'admin' && (
        <>
          <CreateGroupModal
            opened={createOpened}
            onClose={() => setCreateOpened(false)}
            onCreated={(created) => {
              setCreateOpened(false);
              // Insert optimistically: the selection effect drops any id the
              // master list doesn't hold, and the re-list is still in flight.
              setRows((prev) => [
                ...prev,
                {
                  id: created.id,
                  name: created.name,
                  description: created.description ?? null,
                  member_count: created.members.length,
                  sso_managed: created.sso_managed,
                  is_group_admin: true,
                  is_pi: false,
                },
              ]);
              setSelectedId(created.id);
              refreshList();
            }}
          />
          <DeleteGroupModal
            opened={Boolean(deleteTarget)}
            group={deleteTarget}
            onClose={() => setDeleteTarget(null)}
            onConfirm={handleDelete}
          />
        </>
      )}
    </>
  );
};

export default GroupsWorkspace;
