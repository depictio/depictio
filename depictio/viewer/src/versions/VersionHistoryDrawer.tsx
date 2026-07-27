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
import VersionCompatibilityPanel from './VersionCompatibilityPanel';
import VersionTimelineItem from './VersionTimelineItem';
import { useVersionHistory } from './useVersionHistory';

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
  | null;

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

  const run = useCallback(
    async (work: () => Promise<string>) => {
      setBusy(true);
      try {
        const message = await work();
        await reload();
        onRestored?.();
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

  const handlePreview = useCallback((version: DashboardVersionSummary) => {
    // The viewer honours ?version=; opening a new tab leaves the editor's
    // unsaved state untouched.
    window.open(
      `/dashboard/${version.family_id}?version=${version.version_id}`,
      '_blank',
      'noopener',
    );
  }, []);

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
    void run(async () => {
      const created = await createDashboardVersion(dashboardId, null);
      return `Saved version v${created.seq}.`;
    });
  }, [dashboardId, run]);

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
      <Stack gap="lg">
        {groups.map((group) => (
          <Box key={group.label}>
            <Divider
              labelPosition="left"
              mb="xs"
              label={
                <Text size="xs" c="dimmed" fw={600}>
                  {group.label}
                </Text>
              }
            />
            <Timeline active={-1} bulletSize={20} lineWidth={2}>
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
      >
        <Stack gap="md">
          {canEdit && (
            <Button
              variant="light"
              size="xs"
              leftSection={<Icon icon="mdi:content-save-plus" width={14} />}
              onClick={handleSnapshot}
              loading={busy}
              data-testid="version-snapshot"
            >
              Save a version now
            </Button>
          )}
          <ScrollArea.Autosize mah="calc(100vh - 220px)" type="hover">
            {body}
          </ScrollArea.Autosize>
        </Stack>
      </Drawer>

      {/* Naming a version — used for both pin and rename. */}
      <Modal
        opened={pending?.type === 'pin' || pending?.type === 'rename'}
        onClose={closeModal}
        title={pending?.type === 'pin' ? 'Pin this version' : 'Rename version'}
        centered
      >
        <Stack gap="md">
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
              onClick={() => {
                if (!pending) return;
                const version = pending.version;
                const label = labelDraft.trim() || null;
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
              {pending?.type === 'pin' ? 'Pin' : 'Rename'}
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
            <strong>{pending ? versionTitle(pending.version) : ''}</strong>.
          </Text>
          <VersionCompatibilityPanel versionId={pending?.version.version_id ?? null} />
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
                if (!pending) return;
                const version = pending.version;
                void run(async () => {
                  const result = await restoreDashboardVersion(version.version_id);
                  const bits = [`Restored ${versionTitle(version)}`];
                  if (result.tabs_created) bits.push(`${result.tabs_created} tab(s) recreated`);
                  if (result.tabs_deleted) bits.push(`${result.tabs_deleted} tab(s) removed`);
                  return `${bits.join(' · ')}.`;
                });
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
            <strong>{pending ? versionTitle(pending.version) : ''}</strong> will be removed
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
                if (!pending) return;
                const version = pending.version;
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
