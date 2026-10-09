/**
 * The settings' History section: a dashboard family's version timeline.
 *
 * Reads the editor's one `useVersionHistory` instance rather than fetching its
 * own, so the list here, the tile menu's History entry and the per-component
 * history modal can never disagree about which versions exist.
 *
 * Two deliberate behaviours, carried over from the drawer this replaces:
 *
 * Selecting a version is **pure**: nothing is written until an explicit
 * action, and the two irreversible ones (restore, delete) confirm first.
 *
 * Preview opens the **viewer** in a new tab rather than loading a snapshot
 * into the editor. A past version sitting in editor state is one stray drag
 * away from being autosaved over the present.
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Alert,
  Button,
  Group,
  Loader,
  Modal,
  Paper,
  Stack,
  Text,
  TextInput,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { Icon } from '@iconify/react';
import {
  createDashboardVersion,
  deleteDashboardVersion,
  fetchDashboardVersion,
  pinDashboardVersion,
  renameDashboardVersion,
  restoreDashboardVersion,
  unpinDashboardVersion,
  useBrandScopeAttributes,
  Z_LAYERS,
  type DashboardVersionSummary,
  type RestoreVersionResult,
} from 'depictio-react-core';

import { groupByDay, versionTitle } from './format';
import VersionCompatibilityPanel from './VersionCompatibilityPanel';
import VersionTimelineItem from './VersionTimelineItem';
import type { VersionHistory } from './useVersionHistory';

interface VersionHistoryPanelProps {
  /** The tab being edited. Preview opens this tab, not the family's main one. */
  dashboardId: string | null;
  /** The editor's shared timeline state. */
  history: VersionHistory;
  /** Owner-level rights: delete. Everything else here is open to anyone who
   *  can edit the dashboard, as on the server. */
  canDelete: boolean;
  /** Stored version whose data the editor is drawing from, if any. */
  dataVersionId?: string | null;
  /** A restore landed. The host refetches the dashboard (a restore can add or
   *  remove whole tabs) and reloads `history`, which then shows the new
   *  `restore` row. Called after a restore only: every other action here
   *  reloads the list itself. */
  onRestored: (outcome: RestoreOutcome) => void;
}

/** What the host needs to follow a restore. */
export interface RestoreOutcome {
  result: RestoreVersionResult;
  /** The family's main tab: where to go when the tab being edited is gone. */
  familyId: string;
  /** The version has no copy of the tab being edited, so the restore removed
   *  it. Known before the restore, from the version's own tab list. */
  removesCurrentTab: boolean;
}

/**
 * Does restoring this version delete the tab being edited?
 *
 * A restore deletes every child tab the version does not hold, and never the
 * main tab. Read from the version's detail when the restore dialog opens, so
 * the dialog can warn before, and the host can leave the tab after, rather
 * than learn it from a 404.
 */
function useRemovesTab(
  versionId: string | null,
  familyId: string | null,
  dashboardId: string | null,
): boolean {
  const [removes, setRemoves] = useState(false);
  useEffect(() => {
    setRemoves(false);
    if (!versionId || !dashboardId || !familyId || dashboardId === familyId) return;
    let cancelled = false;
    fetchDashboardVersion(versionId)
      .then((detail) => {
        if (cancelled) return;
        const held = (detail.tabs || []).some((tab) => String(tab.dashboard_id) === dashboardId);
        setRemoves(!held);
      })
      .catch(() => {
        // Unknown: no warning. The host still leaves the tab on a 404.
      });
    return () => {
      cancelled = true;
    };
  }, [versionId, familyId, dashboardId]);
  return removes;
}

type PendingAction =
  | { type: 'bookmark'; version: DashboardVersionSummary }
  | { type: 'snapshot' }
  | { type: 'restore'; version: DashboardVersionSummary }
  | { type: 'delete'; version: DashboardVersionSummary }
  | null;

/**
 * A dialog over the settings modal: one layer above it, and put back inside
 * the dashboard's brand scope by hand, since it is portaled to <body> outside
 * the `BrandScope` wrapper (see `useBrandScopeAttributes`).
 */
const NestedDialog: React.FC<{
  opened: boolean;
  onClose: () => void;
  title: React.ReactNode;
  testId: string;
  children: React.ReactNode;
}> = ({ opened, onClose, title, testId, children }) => {
  const brandScope = useBrandScopeAttributes();
  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={title}
      centered
      zIndex={Z_LAYERS.nestedOverlay}
      className={brandScope?.className}
      data-mantine-color-scheme={brandScope?.['data-mantine-color-scheme']}
      data-testid={testId}
    >
      {children}
    </Modal>
  );
};

const VersionHistoryPanel: React.FC<VersionHistoryPanelProps> = ({
  dashboardId,
  history,
  canDelete,
  dataVersionId = null,
  onRestored,
}) => {
  const {
    versions,
    currentVersionId,
    total,
    hasMore,
    loading,
    loadingOlder,
    error,
    olderError,
    reload,
    loadOlder,
  } = history;

  const [pending, setPending] = useState<PendingAction>(null);
  const [labelDraft, setLabelDraft] = useState('');
  const [busy, setBusy] = useState(false);

  // What the open (or closing) dialog is about. `pending` clears the moment a
  // dialog is dismissed, but its fade-out still shows the body: reading the
  // last action keeps the title and the compatibility report from blanking
  // out mid-transition.
  const lastPending = useRef<PendingAction>(null);
  if (pending) lastPending.current = pending;
  const shown = pending ?? lastPending.current;
  const shownVersion = shown && shown.type !== 'snapshot' ? shown.version : null;
  const shownTitle = shownVersion ? versionTitle(shownVersion) : '';

  const groups = useMemo(() => groupByDay(versions), [versions]);

  const restoring = pending?.type === 'restore' ? pending.version : null;
  const removesCurrentTab = useRemovesTab(
    restoring?.version_id ?? null,
    restoring?.family_id ?? null,
    dashboardId,
  );

  const closeDialog = useCallback(() => setPending(null), []);

  /**
   * Run a write, then bring the list up to date (`after`, a reload by default).
   *
   * A restore passes its own `after`, handing over to `onRestored`: it is the
   * one action that changes what the dashboard *is*, so the host refetches
   * the dashboard as well, and reloads the shared list along with it. Every
   * other action (bookmark, rename, delete, snapshot) only reloads the list.
   */
  const run = useCallback(
    async (work: () => Promise<string>, after?: () => void) => {
      setBusy(true);
      try {
        const message = await work();
        if (after) after();
        else await reload();
        notifications.show({ color: 'teal', title: 'Version history', message });
        closeDialog();
      } catch (err) {
        notifications.show({
          color: 'red',
          title: 'Version history',
          message: err instanceof Error ? err.message : 'Action failed',
        });
      } finally {
        setBusy(false);
      }
    },
    [reload, closeDialog],
  );

  const handlePreview = useCallback(
    (version: DashboardVersionSummary) => {
      // The tab the user is *on*, not the family's main tab: a version covers
      // the whole family, so `family_id` is always the main tab's id, and
      // opening that would move someone previewing "Tab 3" onto another tab.
      const target = dashboardId || version.family_id;
      // A new tab, so the editor's unsaved state is left untouched. The viewer
      // renders `?version=` read-only, behind a banner it cannot dismiss.
      window.open(`/dashboard/${target}?version=${version.version_id}`, '_blank', 'noopener');
    },
    [dashboardId],
  );

  const openBookmark = useCallback((version: DashboardVersionSummary) => {
    setLabelDraft(version.label ?? '');
    setPending({ type: 'bookmark', version });
  }, []);

  const openSnapshot = useCallback(() => {
    setLabelDraft('');
    setPending({ type: 'snapshot' });
  }, []);

  const submitLabel = () => {
    if (!pending || busy) return;
    const label = labelDraft.trim() || null;

    if (pending.type === 'snapshot') {
      if (!dashboardId || !label) return;
      void run(async () => {
        // Naming the current state writes an explicit version (or names the
        // newest one, when nothing changed since), and bookmarking it is what
        // keeps it past the retention window, like any other bookmark.
        const created = await createDashboardVersion(dashboardId, label);
        await pinDashboardVersion(created.version_id, label);
        return `Bookmarked “${label}” as v${created.seq}.`;
      });
      return;
    }
    if (pending.type !== 'bookmark') return;

    const { version } = pending;
    if (version.pinned) {
      void run(async () => {
        if (label !== (version.label ?? null)) {
          await renameDashboardVersion(version.version_id, label);
        }
        return 'Bookmark updated.';
      });
      return;
    }
    void run(async () => {
      // A pin with no label keeps the one the version had, so clearing the
      // name is a rename of its own.
      await pinDashboardVersion(version.version_id, label);
      if (label === null && version.label) {
        await renameDashboardVersion(version.version_id, null);
      }
      return `Bookmarked ${label ?? `v${version.seq}`}.`;
    });
  };

  const removeBookmark = () => {
    if (pending?.type !== 'bookmark') return;
    const { version } = pending;
    void run(async () => {
      await unpinDashboardVersion(version.version_id);
      return `Removed the bookmark on ${versionTitle(version)}.`;
    });
  };

  const confirmRestore = () => {
    if (pending?.type !== 'restore') return;
    const { version } = pending;
    let outcome: RestoreOutcome | null = null;
    void run(
      async () => {
        const result = await restoreDashboardVersion(version.version_id);
        outcome = { result, familyId: version.family_id, removesCurrentTab };
        const bits = [`Restored ${versionTitle(version)}`];
        if (result.tabs_created) bits.push(`${result.tabs_created} tab(s) recreated`);
        if (result.tabs_deleted) bits.push(`${result.tabs_deleted} tab(s) removed`);
        return `${bits.join(' · ')}.`;
      },
      () => {
        if (outcome) onRestored(outcome);
      },
    );
  };

  const confirmDelete = () => {
    if (pending?.type !== 'delete') return;
    const { version } = pending;
    void run(async () => {
      // A bookmarked version needs `force`: the server will not let a pin be
      // overridden by accident, and this dialog is the deliberate step.
      await deleteDashboardVersion(version.version_id, version.pinned);
      return `Deleted ${versionTitle(version)}.`;
    });
  };

  const errorAlert = (title: string) => (
    <Alert
      color="red"
      variant="light"
      icon={<Icon icon="mdi:alert-circle" width={16} />}
      title={title}
    >
      <Stack gap="xs" align="flex-start">
        <Text size="sm">{error}</Text>
        <Button
          variant="default"
          size="xs"
          leftSection={<Icon icon="mdi:refresh" width={14} />}
          onClick={() => void reload()}
          data-testid="version-history-retry"
        >
          Retry
        </Button>
      </Stack>
    </Alert>
  );

  const list = (() => {
    if (loading && versions.length === 0) {
      return (
        <Group justify="center" py="xl">
          <Loader size="sm" aria-label="Loading version history" />
        </Group>
      );
    }
    if (error && versions.length === 0) {
      return errorAlert('Could not load the version history');
    }
    if (versions.length === 0) {
      return (
        <Alert color="gray" variant="light" icon={<Icon icon="mdi:history" width={16} />}>
          No versions yet. One is recorded the next time this dashboard is saved.
        </Alert>
      );
    }

    return (
      <Stack gap="md">
        {/* The list on screen is still the last good one; say it may be
            behind rather than replace it with an error. */}
        {error && errorAlert('This list may be out of date')}
        {groups.map((group, index) => (
          <Stack key={`${group.label}-${index}`} gap={4}>
            <Text size="xs" c="dimmed" fw={600}>
              {group.label}
            </Text>
            {/* One line per version, ruled apart rather than boxed: the rule
                lives in the row, since a list may only hold list items. */}
            <Stack gap={0} role="list" aria-label={`Versions saved ${group.label}`}>
              {group.versions.map((version, row) => (
                <VersionTimelineItem
                  key={version.version_id}
                  version={version}
                  isCurrent={version.version_id === currentVersionId}
                  dataActive={version.version_id === dataVersionId}
                  withDivider={row > 0}
                  canDelete={canDelete}
                  busy={busy}
                  onPreview={handlePreview}
                  onBookmark={openBookmark}
                  onRestore={(v) => setPending({ type: 'restore', version: v })}
                  onDelete={(v) => setPending({ type: 'delete', version: v })}
                />
              ))}
            </Stack>
          </Stack>
        ))}
        {hasMore && (
          <Stack gap={4} align="center">
            <Button
              variant="default"
              size="xs"
              onClick={() => void loadOlder()}
              loading={loadingOlder}
              leftSection={<Icon icon="mdi:chevron-down" width={14} />}
              data-testid="version-load-older"
            >
              {olderError ? 'Retry loading older versions' : 'Load older versions'}
            </Button>
            <Text size="xs" c="dimmed">
              Showing {versions.length} of {total}
            </Text>
            {olderError && (
              <Text size="xs" c="red" role="alert">
                {olderError}
              </Text>
            )}
          </Stack>
        )}
      </Stack>
    );
  })();

  const bookmarking = shown?.type === 'bookmark' ? shown.version : null;
  let bookmarkDialogTitle = `Bookmark ${shownTitle}`;
  if (shown?.type === 'snapshot') bookmarkDialogTitle = 'Bookmark the current state';
  else if (bookmarking?.pinned) bookmarkDialogTitle = `Edit the bookmark on ${shownTitle}`;

  return (
    <>
      <Stack gap="md" data-testid="version-history-panel">
        <Paper withBorder radius="md" p="sm">
          <Group justify="space-between" wrap="wrap" gap="sm">
            <Stack gap={2} style={{ minWidth: 0, flex: '1 1 240px' }}>
              <Text size="sm" fw={600}>
                Bookmark the current state
              </Text>
              <Text size="xs" c="dimmed">
                Every save already records a version. A bookmark gives this one a name and
                keeps it for good.
              </Text>
            </Stack>
            <Button
              variant="light"
              size="xs"
              leftSection={<Icon icon="mdi:bookmark-plus-outline" width={14} />}
              onClick={openSnapshot}
              disabled={busy || !dashboardId}
              data-testid="version-snapshot"
            >
              Bookmark
            </Button>
          </Group>
        </Paper>

        {total > 0 && (
          <Text size="xs" c="dimmed">
            {total} version{total === 1 ? '' : 's'}, newest first. Restoring one saves the
            current state first, so a restore can itself be undone.
          </Text>
        )}

        {list}
      </Stack>

      {/* Naming: a bookmark on a row, or the current state. Both ask the same
          question and differ only in what they do with the answer. */}
      <NestedDialog
        opened={pending?.type === 'bookmark' || pending?.type === 'snapshot'}
        onClose={closeDialog}
        title={bookmarkDialogTitle}
        testId="version-bookmark-dialog"
      >
        <Stack gap="md">
          <Text size="sm" c="dimmed">
            A bookmarked version is kept for good, never folds into a later autosave, and is
            easy to find again by its name.
          </Text>
          <TextInput
            label="Name"
            description={shown?.type === 'snapshot' ? undefined : 'Optional'}
            placeholder="e.g. Before the Q3 re-run"
            value={labelDraft}
            onChange={(event) => setLabelDraft(event.currentTarget.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') submitLabel();
            }}
            data-autofocus
            maxLength={200}
            data-testid="version-bookmark-label"
          />
          <Group justify="space-between" gap="xs">
            {bookmarking?.pinned ? (
              <Button
                variant="subtle"
                color="red"
                size="xs"
                onClick={removeBookmark}
                disabled={busy}
                data-testid="version-bookmark-remove"
              >
                Remove bookmark
              </Button>
            ) : (
              <span />
            )}
            <Group gap="xs">
              <Button variant="default" size="xs" onClick={closeDialog} disabled={busy}>
                Cancel
              </Button>
              <Button
                size="xs"
                loading={busy}
                disabled={shown?.type === 'snapshot' && !labelDraft.trim()}
                onClick={submitLabel}
                data-testid="version-bookmark-confirm"
              >
                {bookmarking?.pinned ? 'Save' : 'Bookmark'}
              </Button>
            </Group>
          </Group>
        </Stack>
      </NestedDialog>

      <NestedDialog
        opened={pending?.type === 'restore'}
        onClose={closeDialog}
        title="Restore this version?"
        testId="version-restore-dialog"
      >
        <Stack gap="md">
          <Text size="sm">
            This replaces the dashboard&apos;s current content with <strong>{shownTitle}</strong>.
          </Text>
          <VersionCompatibilityPanel
            versionId={shown?.type === 'restore' ? shown.version.version_id : null}
          />
          {removesCurrentTab && (
            <Alert
              color="orange"
              variant="light"
              icon={<Icon icon="mdi:tab-remove" width={16} />}
              data-testid="version-restore-removes-tab"
            >
              This tab did not exist in {shownTitle}, so restoring it removes this tab. The
              editor then opens the dashboard&apos;s main tab.
            </Alert>
          )}
          <Alert color="blue" variant="light" icon={<Icon icon="mdi:information" width={16} />}>
            The current state is saved as a version first, so you can undo this. Access
            permissions are never changed by a restore.
          </Alert>
          <Group justify="flex-end" gap="xs">
            <Button variant="default" size="xs" onClick={closeDialog} disabled={busy}>
              Cancel
            </Button>
            <Button
              size="xs"
              loading={busy}
              onClick={confirmRestore}
              data-testid="version-restore-confirm"
            >
              Restore
            </Button>
          </Group>
        </Stack>
      </NestedDialog>

      <NestedDialog
        opened={pending?.type === 'delete'}
        onClose={closeDialog}
        title="Delete this version?"
        testId="version-delete-dialog"
      >
        <Stack gap="md">
          <Text size="sm">
            <strong>{shownTitle}</strong> will be removed permanently
            {shownVersion?.pinned ? ', bookmark and all' : ''}.
          </Text>
          <Alert color="red" variant="light" icon={<Icon icon="mdi:alert" width={16} />}>
            Unlike a restore, this cannot be undone.
          </Alert>
          <Group justify="flex-end" gap="xs">
            <Button variant="default" size="xs" onClick={closeDialog} disabled={busy}>
              Cancel
            </Button>
            <Button
              size="xs"
              color="red"
              loading={busy}
              onClick={confirmDelete}
              data-testid="version-delete-confirm"
            >
              Delete
            </Button>
          </Group>
        </Stack>
      </NestedDialog>
    </>
  );
};

export default VersionHistoryPanel;
