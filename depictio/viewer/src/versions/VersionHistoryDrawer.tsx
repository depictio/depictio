/**
 * Right-side drawer listing a dashboard's version history.
 *
 * Modelled on `chrome/SettingsDrawer`. Two deliberate behaviours:
 *
 * Selecting a version is **pure** — nothing is written until the user picks an
 * explicit action, and the two irreversible ones confirm first.
 *
 * Preview opens the **viewer** in a new tab rather than loading a snapshot
 * into the editor. A past version sitting in editor state is one stray drag
 * away from being autosaved over the present.
 */

import React, { useCallback, useMemo, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Divider,
  Drawer,
  Group,
  Loader,
  Modal,
  Paper,
  ScrollArea,
  Stack,
  Text,
  TextInput,
  Timeline,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { Icon } from '@iconify/react';
import {
  createDashboardVersion,
  deleteDashboardVersion,
  pinDashboardVersion,
  renameDashboardVersion,
  restoreDashboardVersion,
  unpinDashboardVersion,
  type DashboardVersionSummary,
} from 'depictio-react-core';

import { groupByDay, versionTitle } from './format';
import VersionTimelineItem from './VersionTimelineItem';
import { useVersionHistory } from './useVersionHistory';
import './versions.css';

interface VersionHistoryDrawerProps {
  opened: boolean;
  onClose: () => void;
  dashboardId: string | null;
  /** Editor-level rights: pin, rename, restore, snapshot. */
  canEdit?: boolean;
  /** Owner-level rights: delete. Erasing history is the one action a restore
   *  cannot undo, so it is gated harder than the rest. */
  canDelete?: boolean;
  /** Called after a restore lands so the host can refetch the dashboard. */
  onRestored?: () => void;
}

type PendingAction =
  | { type: 'rename'; version: DashboardVersionSummary }
  | { type: 'pin'; version: DashboardVersionSummary }
  | { type: 'restore'; version: DashboardVersionSummary }
  | { type: 'delete'; version: DashboardVersionSummary }
  | { type: 'snapshot' }
  | null;

/** The version a pending action targets, or null for the snapshot action —
 *  which names the *current* state and so has no version to point at. Keeps
 *  the union's narrowing in one place instead of at each of its six readers. */
function pendingVersion(pending: PendingAction): DashboardVersionSummary | null {
  return pending && pending.type !== 'snapshot' ? pending.version : null;
}

/** Display name of the version a confirm modal is about. Empty while the modal
 *  is closing, when `pending` has already been cleared but the fade is running. */
function pendingTitle(pending: PendingAction): string {
  const version = pendingVersion(pending);
  return version ? versionTitle(version) : '';
}

const VersionHistoryDrawer: React.FC<VersionHistoryDrawerProps> = ({
  opened,
  onClose,
  dashboardId,
  canEdit = false,
  canDelete = false,
  onRestored,
}) => {
  const { versions, currentVersionId, total, loading, error, reload } = useVersionHistory(
    dashboardId,
    opened,
  );

  const [pending, setPending] = useState<PendingAction>(null);
  const [labelDraft, setLabelDraft] = useState('');
  const [busy, setBusy] = useState(false);

  const groups = useMemo(() => groupByDay(versions), [versions]);

  const closeModal = useCallback(() => {
    setPending(null);
    setLabelDraft('');
  }, []);

  /**
   * Run a mutating action, then refresh the timeline.
   *
   * `reloadsDashboard` is opt-in rather than the default: pin, rename and
   * delete change only the ledger, and refetching the dashboard for those
   * would discard the editor's unsaved in-memory state for no reason. Only a
   * restore actually changes what the dashboard *is*.
   */
  const run = useCallback(
    async (work: () => Promise<string>, opts: { reloadsDashboard?: boolean } = {}) => {
      setBusy(true);
      try {
        const message = await work();
        await reload();
        if (opts.reloadsDashboard) onRestored?.();
        notifications.show({ color: 'teal', title: 'Version history', message });
        closeModal();
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
    [reload, onRestored, closeModal],
  );

  const handlePreview = useCallback(
    (version: DashboardVersionSummary) => {
      // Preview the tab the user is *on*, not the family's main tab. A version
      // covers the whole family, so `family_id` is always the main tab's id —
      // opening that would silently move a user previewing "Tab 3" onto a
      // different tab and show them content they did not ask about.
      const target = dashboardId || version.family_id;
      // The viewer renders `?version=` read-only, behind an unmissable banner.
      // A new tab, so the editor's unsaved state is left untouched.
      window.open(`/dashboard/${target}?version=${version.version_id}`, '_blank', 'noopener');
    },
    [dashboardId],
  );

  const handleTogglePin = useCallback(
    (version: DashboardVersionSummary) => {
      if (version.pinned) {
        void run(async () => {
          await unpinDashboardVersion(version.version_id);
          return `Unpinned ${versionTitle(version)}.`;
        });
        return;
      }
      setLabelDraft(version.label ?? '');
      setPending({ type: 'pin', version });
    },
    [run],
  );

  const handleSnapshot = useCallback(() => {
    if (!dashboardId) return;
    setLabelDraft('');
    setPending({ type: 'snapshot' });
  }, [dashboardId]);

  const body = (() => {
    if (loading && versions.length === 0) {
      return (
        <Group justify="center" py="xl">
          <Loader size="sm" />
        </Group>
      );
    }
    if (error) {
      return (
        <Alert color="red" variant="light" icon={<Icon icon="mdi:alert-circle" width={16} />}>
          {error}
        </Alert>
      );
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
        {groups.map((group) => (
          <Box key={group.label}>
            <Divider
              labelPosition="left"
              mb={6}
              label={
                <Text size="xs" c="dimmed" fw={600}>
                  {group.label}
                </Text>
              }
            />
            {/* Density overrides live in versions.css — the rule being beaten
                is a `:not(:first-of-type)` selector, which Mantine's inline
                `styles` prop cannot express. */}
            <Timeline
              active={-1}
              bulletSize={16}
              lineWidth={2}
              className="depictio-version-timeline"
            >
              {group.versions.map((version) => (
                <VersionTimelineItem
                  key={version.version_id}
                  version={version}
                  isCurrent={version.version_id === currentVersionId}
                  canEdit={canEdit}
                  canDelete={canDelete}
                  busy={busy}
                  onPreview={handlePreview}
                  onTogglePin={handleTogglePin}
                  onRename={(v) => {
                    setLabelDraft(v.label ?? '');
                    setPending({ type: 'rename', version: v });
                  }}
                  onRestore={(v) => setPending({ type: 'restore', version: v })}
                  onDelete={(v) => setPending({ type: 'delete', version: v })}
                />
              ))}
            </Timeline>
          </Box>
        ))}
      </Stack>
    );
  })();

  return (
    <>
      <Drawer
        opened={opened}
        onClose={onClose}
        position="right"
        size="md"
        title={
          <Group gap={8}>
            <Icon icon="mdi:history" width={18} />
            <Text fw={600}>Version history</Text>
            {total > 0 && (
              <Text size="xs" c="dimmed">
                {total} version{total === 1 ? '' : 's'}
              </Text>
            )}
          </Group>
        }
        data-testid="version-drawer"
        // Fill the drawer's height so the list runs to the bottom edge.
        //
        // Mantine's drawer body is a plain block sized to its content, so the
        // timeline had no height to fill; the previous `mah: calc(100vh -
        // 260px)` was a guess at the chrome above it and always stopped short.
        // A flex column delegates that measurement to the browser instead.
        // `minHeight: 0` is what lets the inner ScrollArea shrink rather than
        // grow past the viewport — the usual reason a nested scroller quietly
        // refuses to scroll.
        styles={{
          content: { display: 'flex', flexDirection: 'column' },
          body: { flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' },
        }}
      >
        <Stack gap="md" style={{ flex: 1, minHeight: 0 }}>
          {canEdit && (
            <Paper withBorder radius="md" p="sm" bg="var(--mantine-color-body)">
              <Group justify="space-between" wrap="nowrap" gap="sm" align="center">
                <Stack gap={2} style={{ minWidth: 0 }}>
                  <Text size="sm" fw={600}>
                    Bookmark this state
                  </Text>
                  <Text size="xs" c="dimmed">
                    Saving already records a version. Give the current one a name
                    so it stays findable and is never cleaned up.
                  </Text>
                </Stack>
                <Button
                  variant="light"
                  size="xs"
                  leftSection={<Icon icon="mdi:bookmark-plus-outline" width={14} />}
                  onClick={handleSnapshot}
                  disabled={busy}
                  data-testid="version-snapshot"
                  style={{ flexShrink: 0 }}
                >
                  Name it
                </Button>
              </Group>
            </Paper>
          )}
          {/* Plain ScrollArea, not `.Autosize`: Autosize wraps its child in an
              `overflow: auto` box that grows to fit content, which is the
              opposite of filling a fixed pane and would leave the drawer's own
              scrollbar competing with this one. */}
          <ScrollArea
            style={{ flex: 1, minHeight: 0 }}
            type="hover"
            // Reserve the gutter rather than overlaying it. Mantine's default
            // floating scrollbar sits on top of the content, which lands
            // exactly on each row's action menu and makes it unclickable at
            // the moment the user is scrolling to reach it.
            offsetScrollbars
            scrollbarSize={8}
          >
            {body}
          </ScrollArea>
        </Stack>
      </Drawer>

      {/* Naming a version — shared by snapshot, pin and rename, because all
          three ask the same question and differ only in what they do with the
          answer. */}
      <Modal
        opened={
          pending?.type === 'pin' ||
          pending?.type === 'rename' ||
          pending?.type === 'snapshot'
        }
        onClose={closeModal}
        title={
          pending?.type === 'snapshot'
            ? 'Name the current state'
            : pending?.type === 'pin'
              ? 'Pin this version'
              : 'Rename version'
        }
        centered
      >
        <Stack gap="md">
          {pending?.type === 'snapshot' && (
            <Text size="sm" c="dimmed">
              A named version is kept indefinitely and never folds into a later
              autosave, so it stays exactly as it is now.
            </Text>
          )}
          {pending?.type === 'pin' && (
            <Text size="sm" c="dimmed">
              Pinned versions are never removed by retention, and later autosaves
              cannot fold into them.
            </Text>
          )}
          <TextInput
            label="Name"
            placeholder="e.g. Before the Q3 re-run"
            value={labelDraft}
            onChange={(event) => setLabelDraft(event.currentTarget.value)}
            data-autofocus
            maxLength={200}
          />
          <Group justify="flex-end">
            <Button variant="default" size="xs" onClick={closeModal} disabled={busy}>
              Cancel
            </Button>
            <Button
              size="xs"
              loading={busy}
              disabled={pending?.type === 'snapshot' && !labelDraft.trim()}
              onClick={() => {
                if (!pending) return;
                const label = labelDraft.trim() || null;

                if (pending.type === 'snapshot') {
                  if (!dashboardId || !label) return;
                  void run(async () => {
                    const created = await createDashboardVersion(dashboardId, label);
                    return `Saved “${label}” as v${created.seq}.`;
                  });
                  return;
                }

                const version = pendingVersion(pending);
                if (!version) return;
                if (pending.type === 'pin') {
                  void run(async () => {
                    await pinDashboardVersion(version.version_id, label);
                    return `Pinned ${label ?? `v${version.seq}`}.`;
                  });
                } else {
                  void run(async () => {
                    await renameDashboardVersion(version.version_id, label);
                    return 'Version renamed.';
                  });
                }
              }}
            >
              {pending?.type === 'snapshot'
                ? 'Save'
                : pending?.type === 'pin'
                  ? 'Pin'
                  : 'Rename'}
            </Button>
          </Group>
        </Stack>
      </Modal>

      <Modal
        opened={pending?.type === 'restore'}
        onClose={closeModal}
        title="Restore this version?"
        centered
      >
        <Stack gap="md">
          <Text size="sm">
            This replaces the dashboard's current content with{' '}
            <strong>{pendingTitle(pending)}</strong>.
          </Text>
          <Alert color="blue" variant="light" icon={<Icon icon="mdi:information" width={16} />}>
            The current state is saved as a version first, so you can undo this.
            Access permissions are never changed by a restore.
          </Alert>
          <Group justify="flex-end">
            <Button variant="default" size="xs" onClick={closeModal} disabled={busy}>
              Cancel
            </Button>
            <Button
              size="xs"
              color="yellow"
              loading={busy}
              data-testid="version-restore-confirm"
              onClick={() => {
                const version = pendingVersion(pending);
                if (!version) return;
                void run(async () => {
                  const result = await restoreDashboardVersion(version.version_id);
                  const bits = [`Restored ${versionTitle(version)}`];
                  if (result.tabs_created) bits.push(`${result.tabs_created} tab(s) recreated`);
                  if (result.tabs_deleted) bits.push(`${result.tabs_deleted} tab(s) removed`);
                  return `${bits.join(' · ')}.`;
                }, { reloadsDashboard: true });
              }}
            >
              Restore
            </Button>
          </Group>
        </Stack>
      </Modal>

      <Modal
        opened={pending?.type === 'delete'}
        onClose={closeModal}
        title="Delete this version?"
        centered
      >
        <Stack gap="md">
          <Text size="sm">
            <strong>{pendingTitle(pending)}</strong> will be removed
            permanently.
          </Text>
          <Alert color="red" variant="light" icon={<Icon icon="mdi:alert" width={16} />}>
            Unlike a restore, this cannot be undone.
          </Alert>
          <Group justify="flex-end">
            <Button variant="default" size="xs" onClick={closeModal} disabled={busy}>
              Cancel
            </Button>
            <Button
              size="xs"
              color="red"
              loading={busy}
              data-testid="version-delete-confirm"
              onClick={() => {
                const version = pendingVersion(pending);
                if (!version) return;
                void run(async () => {
                  await deleteDashboardVersion(version.version_id, version.pinned);
                  return `Deleted ${versionTitle(version)}.`;
                });
              }}
            >
              Delete
            </Button>
          </Group>
        </Stack>
      </Modal>
    </>
  );
};

export default VersionHistoryDrawer;
